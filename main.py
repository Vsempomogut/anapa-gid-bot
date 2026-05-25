import asyncio
import sqlite3
import io
import os
import threading
from datetime import datetime, timedelta
import logging
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile, Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from geopy.distance import geodesic
from flask import Flask

# ===== НАСТРОЙКИ =====
TOKEN = "8675178726:AAHnnPNuVVfI23wwWfEVEK_c0kZUhzALVhY"
RADIUS_METERS = 50
ADMIN_IDS = [5196749531]            # замените на свои Telegram ID
IMAGES_FOLDER = "images"

YOOKASSA_SHOP_ID = "1363267"
YOOKASSA_SECRET_KEY = "live_XjLtEtimRDR0qeJRjN3wh0YnfzHXJf18sQ30-XBfTuk"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===== Flask (для Render) =====
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_flask, daemon=True).start()

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect('quest.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        start_date TIMESTAMP,
        last_activity TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount REAL,
        status TEXT,
        created_at TIMESTAMP,
        completed_at TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('payment_enabled', '0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '100')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('location_price', '500')")

    c.execute('''CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        info TEXT,
        lat REAL,
        lon REAL,
        photo TEXT,
        type TEXT DEFAULT 'attraction'
    )''')

    try:
        c.execute("ALTER TABLE locations ADD COLUMN type TEXT DEFAULT 'attraction'")
    except:
        pass

    c.execute("SELECT COUNT(*) FROM locations")
    if c.fetchone()[0] == 0:
        default_locations = [
            ("Русские ворота", "Остатки турецкой крепости.",
             "🏛 <b>Русские ворота</b> — памятник архитектуры XVIII века.\nПостроены в 1783 году как часть турецкой крепости Анапа.\nНазваны в честь 25-летия освобождения города от турок в 1828 году.\nАвтор проекта неизвестен, реставрация проводилась в 1950-х годах.\n📍 Координаты: 44.8955, 37.3198",
             44.8955, 37.3115, "1.jpg", "attraction"),
            # ... (остальные 24 локации + кафе, как в предыдущем ответе)
        ]
        c.executemany(
            "INSERT INTO locations (name, description, info, lat, lon, photo, type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            default_locations
        )

    c.execute('''CREATE TABLE IF NOT EXISTS location_progress (
        user_id INTEGER,
        location_id INTEGER,
        location_name TEXT,
        visited INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        timestamp TIMESTAMP,
        PRIMARY KEY (user_id, location_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message_text TEXT,
        timestamp TIMESTAMP,
        replied INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS location_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        photo TEXT,
        tags TEXT,
        city TEXT,
        address TEXT,
        description TEXT,
        status TEXT DEFAULT 'pending',
        payment_id TEXT,
        timestamp TIMESTAMP
    )''')

    conn.commit()
    conn.close()

init_db()

# ===== FSM =====
class QuestState(StatesGroup):
    current_idx = State()

class AdminAddLocation(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_info = State()
    waiting_for_lat = State()
    waiting_for_lon = State()
    waiting_for_photo = State()
    waiting_for_type = State()

class AdminEditLocation(StatesGroup):
    waiting_for_new_value = State()

class AdminChangePrice(StatesGroup):
    waiting_for_price = State()

class AdminChangeLocationPrice(StatesGroup):
    waiting_for_price = State()

class UserSupportMessage(StatesGroup):
    waiting_for_message = State()

class AdminReplyMessage(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_reply_text = State()

class UserAddLocation(StatesGroup):
    waiting_for_name = State()
    waiting_for_photo = State()
    waiting_for_tags = State()
    waiting_for_city = State()
    waiting_for_address = State()
    waiting_for_description = State()

class NearbySearchType(StatesGroup):
    waiting_for_location = State()

class AdminGrantAccess(StatesGroup):
    waiting_for_user_id = State()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def db_execute(query, params=(), fetch=False):
    conn = sqlite3.connect('quest.db')
    c = conn.cursor()
    c.execute(query, params)
    result = c.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return result

def register_user(user_id, username, first_name):
    existing = db_execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if not existing:
        db_execute(
            "INSERT INTO users (user_id, username, first_name, start_date, last_activity) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, datetime.now(), datetime.now())
        )
    else:
        db_execute("UPDATE users SET last_activity = ? WHERE user_id = ?", (datetime.now(), user_id))

def is_payment_enabled():
    row = db_execute("SELECT value FROM settings WHERE key='payment_enabled'", fetch=True)
    return row[0][0] == '1' if row else False

def set_payment_enabled(enabled: bool):
    db_execute("UPDATE settings SET value=? WHERE key='payment_enabled'", ('1' if enabled else '0',))

def get_price():
    row = db_execute("SELECT value FROM settings WHERE key='price'", fetch=True)
    return float(row[0][0]) if row else 100.0

def set_price(price: float):
    db_execute("UPDATE settings SET value=? WHERE key='price'", (str(price),))

def get_location_price():
    row = db_execute("SELECT value FROM settings WHERE key='location_price'", fetch=True)
    return float(row[0][0]) if row else 500.0

def set_location_price(price: float):
    db_execute("UPDATE settings SET value=? WHERE key='location_price'", (str(price),))

def is_user_paid(user_id):
    if not is_payment_enabled():
        return True
    row = db_execute(
        "SELECT payment_id FROM payments WHERE user_id = ? AND status = 'succeeded' LIMIT 1",
        (user_id,), fetch=True
    )
    return bool(row)

def grant_access_to_user(user_id):
    if is_user_paid(user_id):
        return False
    db_execute(
        "INSERT INTO payments (payment_id, user_id, amount, status, created_at, completed_at) VALUES (?, ?, 0, 'succeeded', ?, ?)",
        (f"manual_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}", user_id, datetime.now(), datetime.now())
    )
    return True

def get_location(loc_id):
    row = db_execute("SELECT id, name, description, info, lat, lon, photo, type FROM locations WHERE id=?", (loc_id,), fetch=True)
    if row:
        return {
            "id": row[0][0], "name": row[0][1], "description": row[0][2],
            "info": row[0][3], "lat": row[0][4], "lon": row[0][5], "photo": row[0][6], "type": row[0][7]
        }
    return None

def get_all_location_ids():
    rows = db_execute("SELECT id FROM locations ORDER BY id", fetch=True)
    return [r[0] for r in rows]

def get_locations_count():
    row = db_execute("SELECT COUNT(*) FROM locations", fetch=True)
    return row[0][0]

def add_location(name, description, info, lat, lon, photo_filename, loc_type="attraction"):
    db_execute(
        "INSERT INTO locations (name, description, info, lat, lon, photo, type) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, description, info, lat, lon, photo_filename, loc_type)
    )
    return db_execute("SELECT last_insert_rowid()", fetch=True)[0][0]

def update_location_field(loc_id, field, value):
    allowed_fields = ["name", "description", "info", "lat", "lon", "photo", "type"]
    if field not in allowed_fields:
        return False
    db_execute(f"UPDATE locations SET {field}=? WHERE id=?", (value, loc_id))
    return True

def delete_location(loc_id):
    db_execute("DELETE FROM location_progress WHERE location_id=?", (loc_id,))
    loc = get_location(loc_id)
    if loc and loc['photo']:
        photo_path = os.path.join(IMAGES_FOLDER, loc['photo'])
        if os.path.isfile(photo_path):
            os.remove(photo_path)
    db_execute("DELETE FROM locations WHERE id=?", (loc_id,))

def get_user_progress(user_id):
    rows = db_execute(
        "SELECT location_id, visited, skipped FROM location_progress WHERE user_id = ?",
        (user_id,), fetch=True
    )
    progress = {}
    for loc_id, visited, skipped in rows:
        progress[loc_id] = {'visited': bool(visited), 'skipped': bool(skipped)}
    return progress

def get_user_stats(user_id):
    progress = get_user_progress(user_id)
    total = get_locations_count()
    visited_count = sum(1 for v in progress.values() if v['visited'])
    skipped_count = sum(1 for v in progress.values() if v['skipped'])
    completed = visited_count == total
    if completed:
        db_execute("DELETE FROM location_progress WHERE user_id = ?", (user_id,))
        progress = {}
        visited_count = 0
        skipped_count = 0
        completed = False
    return {
        "visited": visited_count,
        "skipped": skipped_count,
        "total": total,
        "completed": completed,
        "progress_percent": round(visited_count / total * 100, 1) if visited_count else 0,
        "progress": progress
    }

def mark_location(user_id, loc_id, action='visited'):
    existing = db_execute(
        "SELECT visited, skipped FROM location_progress WHERE user_id = ? AND location_id = ?",
        (user_id, loc_id), fetch=True
    )
    name = get_location(loc_id)["name"]
    if existing:
        if action == 'visited':
            db_execute(
                "UPDATE location_progress SET visited = 1, skipped = 0, timestamp = ? WHERE user_id = ? AND location_id = ?",
                (datetime.now(), user_id, loc_id)
            )
        else:
            db_execute(
                "UPDATE location_progress SET skipped = 1, visited = 0, timestamp = ? WHERE user_id = ? AND location_id = ?",
                (datetime.now(), user_id, loc_id)
            )
    else:
        db_execute(
            "INSERT INTO location_progress (user_id, location_id, location_name, visited, skipped, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, loc_id, name, 1 if action == 'visited' else 0, 1 if action == 'skipped' else 0, datetime.now())
        )

def get_unvisited_locations(user_id):
    progress = get_user_progress(user_id)
    all_ids = set(get_all_location_ids())
    marked = set(progress.keys())
    return sorted(list(all_ids - marked))

def get_skipped_locations(user_id):
    progress = get_user_progress(user_id)
    return [loc_id for loc_id, v in progress.items() if v['skipped']]

def is_nearby(user_lat, user_lon, target_lat, target_lon):
    return geodesic((user_lat, user_lon), (target_lat, target_lon)).meters <= RADIUS_METERS

def get_photo_path(loc):
    if loc and loc.get("photo"):
        path = os.path.join(IMAGES_FOLDER, loc["photo"])
        if os.path.isfile(path):
            return path
    return None

def find_nearest_locations(lat, lon, limit=3, filter_type=None):
    locs = []
    for loc_id in get_all_location_ids():
        loc = get_location(loc_id)
        if not loc:
            continue
        if filter_type and loc.get('type') != filter_type:
            continue
        dist = geodesic((lat, lon), (loc['lat'], loc['lon'])).meters
        locs.append((dist, loc))
    locs.sort(key=lambda x: x[0])
    result = []
    for dist, loc in locs[:limit]:
        loc_copy = loc.copy()
        loc_copy['distance'] = dist
        result.append(loc_copy)
    return result

def get_map_buttons(loc, user_lat=None, user_lon=None):
    builder = InlineKeyboardBuilder()
    if user_lat and user_lon:
        google_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lon}&destination={loc['lat']},{loc['lon']}&travelmode=walking"
        yandex_url = f"https://yandex.ru/maps/?rtext={user_lat},{user_lon}~{loc['lat']},{loc['lon']}&rtt=pd"
    else:
        google_url = f"https://www.google.com/maps/place/@{loc['lat']},{loc['lon']},17z"
        yandex_url = f"https://yandex.ru/maps/?pt={loc['lon']},{loc['lat']}&z=17"
    builder.button(text="🗺 Google", url=google_url)
    builder.button(text="📍 Яндекс", url=yandex_url)
    return builder

def get_full_location_keyboard(loc, user_lat=None, user_lon=None):
    """Клавиатура с картами И кнопками управления квестом."""
    builder = get_map_buttons(loc, user_lat, user_lon)
    builder.button(text="📍 Я на месте (гео)", callback_data="confirm_location")
    builder.button(text="✅ Подтвердить посещение", callback_data="confirm_visit")
    builder.button(text="⏭ Пропустить", callback_data="skip_location")
    builder.button(text="📊 Статистика", callback_data="my_stats")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

async def send_location_with_photo(chat_id, loc_id, prefix="", user_lat=None, user_lon=None):
    loc = get_location(loc_id)
    if not loc:
        await bot.send_message(chat_id, "Локация не найдена.")
        return
    photo_path = get_photo_path(loc)
    total = get_locations_count()
    stats = get_user_stats(chat_id)
    progress_bar = "▓" * stats['visited'] + "░" * (total - stats['visited'])
    full_info = loc['info'] if loc['info'] else loc['description']
    caption = (f"{prefix}📍 <b>{loc['name']}</b>\n\n"
               f"{full_info}\n\n"
               f"Прогресс: {progress_bar} ({stats['visited']}/{total})")
    keyboard = get_full_location_keyboard(loc, user_lat, user_lon)
    if photo_path:
        await bot.send_photo(chat_id, FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=keyboard)

async def send_location_info(chat_id, loc_id):
    pass

# ===== КЛАВИАТУРЫ =====
def get_main_menu_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    if not is_user_paid(user_id):
        price = get_price()
        builder.button(text=f"💳 Оплатить доступ ({price:.0f}₽)", callback_data="pay_access")
    else:
        stats = get_user_stats(user_id)
        if stats['visited'] == 0 and stats['skipped'] == 0:
            builder.button(text="🚀 Начать маршрут", callback_data="start_quest")
        else:
            unvisited = get_unvisited_locations(user_id)
            if unvisited:
                builder.button(text="📍 Продолжить маршрут", callback_data="continue_quest")
            else:
                builder.button(text="🔄 Начать заново", callback_data="start_quest")
        skipped = get_skipped_locations(user_id)
        if skipped:
            builder.button(text="🔄 Перепройти пропущенные", callback_data="retry_skipped")
    builder.button(text="🔍 Локации рядом", callback_data="nearby_all")
    builder.button(text="🍽 Где поесть", callback_data="nearby_food")
    builder.button(text="➕ Добавить локацию", callback_data="add_location_info")
    builder.button(text="📊 Моя статистика", callback_data="my_stats")
    builder.button(text="ℹ️ О гиде", callback_data="about_quest")
    builder.button(text="🆘 Помощь", callback_data="help_info")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

def get_quest_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Я на месте (гео)", callback_data="confirm_location")
    builder.button(text="✅ Подтвердить посещение", callback_data="confirm_visit")
    builder.button(text="⏭ Пропустить", callback_data="skip_location")
    builder.button(text="📊 Статистика", callback_data="my_stats")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def get_retry_skipped_keyboard(user_id):
    skipped = get_skipped_locations(user_id)
    builder = InlineKeyboardBuilder()
    for loc_id in skipped:
        loc = get_location(loc_id)
        builder.button(text=loc["name"], callback_data=f"retry_{loc_id}")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_share_location_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📍 Отправить геопозицию", request_location=True))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

# ===== АСИНХРОННЫЕ ОБЁРТКИ ДЛЯ YOOKASSA =====
async def create_payment_async(amount, description, metadata):
    import uuid
    from yookassa import Configuration, Payment
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    idempotence_key = str(uuid.uuid4())
    payment = await asyncio.to_thread(
        Payment.create,
        {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/anapa_gid_bot"
            },
            "capture": True,
            "description": description,
            "metadata": metadata
        },
        idempotence_key
    )
    return payment

async def check_payment_async(payment_id):
    from yookassa import Configuration, Payment
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    payment = await asyncio.to_thread(Payment.find_one, payment_id)
    return payment

# ===== ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    await message.answer(
        "🏙 <b>Гид-бот по Анапе</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(user_id)
    )

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.edit_text("🏙 <b>Главное меню</b>", parse_mode="HTML", reply_markup=get_main_menu_keyboard(user_id))
    await callback.answer()

@dp.callback_query(F.data == "nearby_all")
async def nearby_all(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_paid(callback.from_user.id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    await state.set_state(NearbySearchType.waiting_for_location)
    await state.update_data(search_filter=None)
    await callback.message.answer(
        "📍 Пожалуйста, поделитесь вашим местоположением, чтобы я показал ближайшие интересные места.",
        reply_markup=get_share_location_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "nearby_food")
async def nearby_food(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_paid(callback.from_user.id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    await state.set_state(NearbySearchType.waiting_for_location)
    await state.update_data(search_filter="food")
    await callback.message.answer(
        "🍽 Пожалуйста, поделитесь вашим местоположением, чтобы я показал ближайшие заведения.",
        reply_markup=get_share_location_keyboard()
    )
    await callback.answer()

@dp.message(F.location, StateFilter(NearbySearchType.waiting_for_location))
async def handle_nearby_search(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_lat = message.location.latitude
    user_lon = message.location.longitude
    data = await state.get_data()
    filter_type = data.get('search_filter')
    nearest = find_nearest_locations(user_lat, user_lon, limit=3, filter_type=filter_type)
    if nearest:
        title = "🍽 <b>Ближайшие заведения:</b>\n\n" if filter_type == "food" else "📍 <b>Ближайшие места:</b>\n\n"
        first = True
        for loc in nearest:
            d = loc['distance']
            dist_str = f"{d/1000:.1f} км" if d >= 1000 else f"{int(d)} м"
            map_buttons = get_map_buttons(loc, user_lat, user_lon)
            full_info = loc['info'] if loc['info'] else loc['description']
            loc_text = f"{title if first else ''}<b>{loc['name']}</b> – {dist_str}\n{full_info}"
            first = False
            photo_path = get_photo_path(loc)
            if photo_path:
                await message.answer_photo(FSInputFile(photo_path), caption=loc_text, parse_mode="HTML", reply_markup=map_buttons.as_markup())
            else:
                await message.answer(loc_text, parse_mode="HTML", reply_markup=map_buttons.as_markup())
    else:
        await message.answer("Рядом ничего не найдено.", reply_markup=ReplyKeyboardRemove())
    await bot.send_message(chat_id=message.chat.id, text="🏙 <b>Главное меню</b>", parse_mode="HTML", reply_markup=get_main_menu_keyboard(user_id))
    await state.clear()

@dp.callback_query(F.data == "add_location_info")
async def add_location_info(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserAddLocation.waiting_for_name)
    await callback.message.edit_text(
        "📝 <b>Добавление заведения</b>\n\n"
        "Пожалуйста, введите <b>название</b> заведения:",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(StateFilter(UserAddLocation.waiting_for_name))
async def process_new_location_name(message: Message, state: FSMContext):
    await state.update_data(loc_name=message.text)
    await state.set_state(UserAddLocation.waiting_for_photo)
    await message.answer("📷 Загрузите <b>одно фото</b> заведения (или отправьте '-', если нет).", parse_mode="HTML")

@dp.message(StateFilter(UserAddLocation.waiting_for_photo))
async def process_new_location_photo(message: Message, state: FSMContext):
    if message.photo:
        file_id = message.photo[-1].file_id
        file = await bot.get_file(file_id)
        filename = f"user_loc_{message.from_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
        dest_path = os.path.join(IMAGES_FOLDER, filename)
        await bot.download(file, destination=dest_path)
        await state.update_data(loc_photo=filename)
    else:
        await state.update_data(loc_photo=None)
    await state.set_state(UserAddLocation.waiting_for_tags)
    await message.answer("🏷 Введите <b>теги</b> (например: ресторан, кафе, шашлычная).", parse_mode="HTML")

@dp.message(StateFilter(UserAddLocation.waiting_for_tags))
async def process_new_location_tags(message: Message, state: FSMContext):
    await state.update_data(loc_tags=message.text)
    await state.set_state(UserAddLocation.waiting_for_city)
    await message.answer("🏙 Введите <b>город</b> (например: Анапа).", parse_mode="HTML")

@dp.message(StateFilter(UserAddLocation.waiting_for_city))
async def process_new_location_city(message: Message, state: FSMContext):
    await state.update_data(loc_city=message.text)
    await state.set_state(UserAddLocation.waiting_for_address)
    await message.answer("📍 Введите <b>адрес</b> заведения.", parse_mode="HTML")

@dp.message(StateFilter(UserAddLocation.waiting_for_address))
async def process_new_location_address(message: Message, state: FSMContext):
    await state.update_data(loc_address=message.text)
    await state.set_state(UserAddLocation.waiting_for_description)
    await message.answer("📝 Введите <b>описание</b> заведения (кухня, особенности, часы работы).", parse_mode="HTML")

@dp.message(StateFilter(UserAddLocation.waiting_for_description))
async def process_new_location_description(message: Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user
    db_execute(
        "INSERT INTO location_requests (user_id, name, photo, tags, city, address, description, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user.id, data['loc_name'], data.get('loc_photo'), data['loc_tags'], data['loc_city'], data['loc_address'], message.text, datetime.now())
    )
    request_id = db_execute("SELECT last_insert_rowid()", fetch=True)[0][0]
    admin_text = (
        f"📩 <b>Новая заявка на добавление заведения (#{request_id})</b>\n\n"
        f"👤 Пользователь: {user.first_name} (@{user.username or 'нет'}) ID: {user.id}\n"
        f"📛 Название: {data['loc_name']}\n"
        f"🏙 Город: {data['loc_city']}\n"
        f"📍 Адрес: {data['loc_address']}\n"
        f"🏷 Теги: {data['loc_tags']}\n"
        f"📝 Описание: {message.text}\n"
        f"📎 Фото: {'есть' if data.get('loc_photo') else 'нет'}\n\n"
        f"Используйте /admin для управления заявками."
    )
    photo = data.get('loc_photo')
    if photo:
        photo_path = os.path.join(IMAGES_FOLDER, photo)
        if os.path.isfile(photo_path):
            with open(photo_path, 'rb') as f:
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_photo(admin_id, f, caption=admin_text, parse_mode="HTML")
                    except:
                        pass
    else:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_text, parse_mode="HTML")
            except:
                pass
    db_execute(
        "INSERT INTO support_messages (user_id, message_text, timestamp) VALUES (?, ?, ?)",
        (user.id, admin_text, datetime.now())
    )
    await state.clear()
    await message.answer("✅ Спасибо! Ваша заявка отправлена администраторам. После одобрения вам придёт ссылка на оплату.")
    await start_cmd(message, state)

# ===== ОБРАБОТЧИКИ КВЕСТА =====
@dp.callback_query(F.data == "start_quest")
async def start_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    db_execute("DELETE FROM location_progress WHERE user_id = ?", (user_id,))
    await state.clear()
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        first_id = unvisited[0]
        await state.update_data(current_idx=first_id)
        await send_location_with_photo(callback.message.chat.id, first_id, prefix="🚀 Поехали!\n")
        await callback.message.edit_text("Маршрут начат!")
    else:
        await callback.message.edit_text("Все локации уже посещены, но вы можете перепройти пропущенные.")
    await callback.answer()

@dp.callback_query(F.data == "continue_quest")
async def continue_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        next_id = unvisited[0]
        await state.update_data(current_idx=next_id)
        await send_location_with_photo(callback.message.chat.id, next_id)
        await callback.message.edit_text("📍 Продолжаем!")
    else:
        skipped = get_skipped_locations(user_id)
        if skipped:
            await callback.message.edit_text(
                "Все локации отмечены, но вы можете перепройти пропущенные.",
                reply_markup=get_retry_skipped_keyboard(user_id)
            )
        else:
            await callback.message.edit_text(
                "🎉 Поздравляем! Все локации посещены!\nИспользуйте /start для нового захода.",
                reply_markup=get_main_menu_keyboard(user_id)
            )
    await callback.answer()

@dp.callback_query(F.data == "retry_skipped")
async def retry_skipped_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    skipped = get_skipped_locations(user_id)
    if not skipped:
        await callback.answer("Нет пропущенных локаций.", show_alert=True)
        return
    await callback.message.edit_text("🔄 Выберите локацию:", reply_markup=get_retry_skipped_keyboard(user_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("retry_"))
async def retry_location(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    loc_id = int(callback.data.split("_")[1])
    progress = get_user_progress(user_id)
    if loc_id not in progress or not progress[loc_id]['skipped']:
        await callback.answer("Эту локацию нельзя перепройти.", show_alert=True)
        return
    db_execute("DELETE FROM location_progress WHERE user_id = ? AND location_id = ?", (user_id, loc_id))
    await state.update_data(current_idx=loc_id)
    await callback.message.edit_text(f"Можете снова посетить «{get_location(loc_id)['name']}».")
    await send_location_with_photo(callback.message.chat.id, loc_id)
    await callback.answer()

@dp.callback_query(F.data == "confirm_location")
async def confirm_location_button(callback: types.CallbackQuery):
    await callback.message.answer(
        "📍 Пожалуйста, отправьте вашу геопозицию, нажав кнопку ниже.",
        reply_markup=get_share_location_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "confirm_visit")
async def confirm_visit_button(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    data = await state.get_data()
    current_id = data.get("current_idx")
    if current_id is None:
        await callback.answer("Нет активной локации.", show_alert=True)
        return
    progress = get_user_progress(user_id)
    if current_id in progress:
        await callback.answer("Эта локация уже отмечена.", show_alert=True)
        return
    mark_location(user_id, current_id, 'visited')
    loc_name = get_location(current_id)["name"]
    await callback.message.answer(f"✅ Локация «{loc_name}» засчитана как пройденная!")
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        next_id = unvisited[0]
        await state.update_data(current_idx=next_id)
        await send_location_with_photo(callback.message.chat.id, next_id)
    else:
        await state.update_data(current_idx=None)
        skipped = get_skipped_locations(user_id)
        if skipped:
            await callback.message.answer(
                "Все локации отмечены. Можете перепройти пропущенные.",
                reply_markup=get_retry_skipped_keyboard(user_id)
            )
        else:
            await callback.message.answer(
                "🏆 Вы посетили все локации! Маршрут завершён.\n/start для нового захода.",
                reply_markup=get_main_menu_keyboard(user_id)
            )
    await callback.answer()

@dp.callback_query(F.data == "skip_location")
async def skip_location(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    data = await state.get_data()
    current_id = data.get("current_idx")
    if current_id is None:
        await callback.answer("Нечего пропускать.", show_alert=True)
        return
    progress = get_user_progress(user_id)
    if current_id in progress:
        await callback.answer("Эта локация уже отмечена.", show_alert=True)
        return
    mark_location(user_id, current_id, 'skipped')
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"⏭ «{get_location(current_id)['name']}» пропущена.")
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        next_id = unvisited[0]
        await state.update_data(current_idx=next_id)
        await send_location_with_photo(callback.message.chat.id, next_id)
    else:
        await state.update_data(current_idx=None)
        skipped = get_skipped_locations(user_id)
        if skipped:
            await callback.message.answer("Все локации отмечены. Можете перепройти пропущенные.", reply_markup=get_retry_skipped_keyboard(user_id))
        else:
            await callback.message.answer("🎉 Все локации посещены! Маршрут завершён.", reply_markup=get_main_menu_keyboard(user_id))
    await callback.answer()

@dp.message(F.location)
async def handle_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    if not is_user_paid(user_id):
        await message.answer("❌ Доступ платный. Нажмите /start и оплатите.")
        return
    current_state = await state.get_state()
    if current_state is None:
        return
    if current_state == NearbySearchType.waiting_for_location.state:
        await handle_nearby_search(message, state)
        return
    data = await state.get_data()
    current_id = data.get("current_idx")
    if current_id is None:
        unvisited = get_unvisited_locations(user_id)
        if not unvisited:
            await message.answer("Все локации отмечены.")
            return
        current_id = unvisited[0]
        await state.update_data(current_idx=current_id)
    loc = get_location(current_id)
    if not loc:
        await message.answer("Локация не найдена.")
        return
    progress = get_user_progress(user_id)
    if current_id in progress:
        await message.answer("Эта локация уже отмечена. Ищем следующую...")
        unvisited = get_unvisited_locations(user_id)
        if unvisited:
            current_id = unvisited[0]
            await state.update_data(current_idx=current_id)
            loc = get_location(current_id)
        else:
            await message.answer("Все локации отмечены.")
            return
    if is_nearby(message.location.latitude, message.location.longitude, loc["lat"], loc["lon"]):
        await message.answer(f"✅ «{loc['name']}» пройдена!")
        mark_location(user_id, current_id, 'visited')
        unvisited = get_unvisited_locations(user_id)
        if unvisited:
            next_id = unvisited[0]
            await state.update_data(current_idx=next_id)
            await send_location_with_photo(message.chat.id, next_id)
        else:
            await state.update_data(current_idx=None)
            skipped = get_skipped_locations(user_id)
            if skipped:
                await message.answer("Все локации отмечены. Можете перепройти пропущенные.", reply_markup=get_retry_skipped_keyboard(user_id))
            else:
                await message.answer("🏆 Вы посетили все локации! Маршрут завершён.\n/start для нового захода.", reply_markup=get_main_menu_keyboard(user_id))
    else:
        dist = geodesic((message.location.latitude, message.location.longitude), (loc["lat"], loc["lon"])).meters
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 Главное меню", callback_data="main_menu")
        unvisited = get_unvisited_locations(user_id)
        if current_id in unvisited:
            unvisited.remove(current_id)
        if unvisited:
            next_id = unvisited[0]
            builder.button(text="📍 Следующая локация", callback_data=f"goto_location_{next_id}")
        builder.adjust(1)
        await message.answer(
            f"❌ Вы не на месте! До «{loc['name']}» ещё {dist:.0f} м.\n\nВыберите действие:",
            reply_markup=builder.as_markup()
        )

@dp.callback_query(F.data.startswith("goto_location_"))
async def goto_location(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    loc_id = int(callback.data.split("_")[2])
    progress = get_user_progress(user_id)
    if loc_id in progress:
        await callback.answer("Эта локация уже отмечена.", show_alert=True)
        return
    await state.update_data(current_idx=loc_id)
    await send_location_with_photo(callback.message.chat.id, loc_id)
    await callback.message.edit_text("📍 Перешли к следующей локации.")
    await callback.answer()

# Статистика и информация
@dp.callback_query(F.data == "my_stats")
async def my_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_user_paid(user_id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
    stats = get_user_stats(user_id)
    text = (f"📊 <b>Моя статистика</b>\n\n"
            f"📍 Всего локаций: {stats['total']}\n"
            f"✅ Посещено: {stats['visited']}\n"
            f"⏭ Пропущено: {stats['skipped']}\n"
            f"Прогресс: {stats['progress_percent']}%")
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "about_quest")
async def about_quest(callback: types.CallbackQuery):
    price = get_price()
    loc_price = get_location_price()
    payment_status = "включён" if is_payment_enabled() else "отключён"
    text = (f"ℹ️ <b>Гид-бот по Анапе</b>\n\n"
            f"{get_locations_count()} локаций с историческими справками.\n"
            f"Режим оплаты: {payment_status}.\n"
            f"Стоимость доступа: {price:.0f}₽.\n"
            f"Стоимость добавления локации: {loc_price:.0f}₽.\n"
            "Пропущенные можно перепройти.")
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "help_info")
async def help_info(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 <b>Обратная связь</b>\n\n"
        "Опишите ваш вопрос или предложение, и администраторы получат ваше сообщение.\n"
        "Для отмены нажмите /start.\n\n"
        "📍 <b>Поиск мест рядом:</b> используйте кнопки «Локации рядом» или «Где поесть» в главном меню.",
        parse_mode="HTML"
    )
    await state.set_state(UserSupportMessage.waiting_for_message)
    await callback.answer()

@dp.message(StateFilter(UserSupportMessage.waiting_for_message))
async def process_support_message(message: Message, state: FSMContext):
    user = message.from_user
    text = message.text
    db_execute(
        "INSERT INTO support_messages (user_id, message_text, timestamp) VALUES (?, ?, ?)",
        (user.id, text, datetime.now())
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Новое сообщение</b>\n"
                f"От: {user.first_name} (@{user.username or 'нет'})\n"
                f"ID: {user.id}\n\n"
                f"{text}",
                parse_mode="HTML"
            )
        except:
            pass
    await message.answer("✅ Ваше сообщение отправлено администраторам. Спасибо!")
    await state.clear()
    await start_cmd(message, state)

# ===== АДМИН-ПАНЕЛЬ =====
async def show_admin_panel(target):
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats_menu")
    builder.button(text="👥 Пользователи", callback_data="admin_users_info")
    builder.button(text="📍 Управление локациями", callback_data="admin_locations_menu")
    builder.button(text="💰 Управление оплатой", callback_data="admin_payment_settings")
    builder.button(text="💳 Платежи", callback_data="admin_payments_list")
    builder.button(text="➕ Доступ по ID", callback_data="admin_grant_access")
    builder.button(text="📩 Сообщения", callback_data="admin_messages")
    builder.button(text="📋 Заявки на добавление", callback_data="admin_location_requests")
    builder.button(text="🔔 Напомнить", callback_data="admin_remind_stuck")
    builder.adjust(2, 2, 2, 2, 1)
    if isinstance(target, types.Message):
        await target.answer("🔐 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await target.message.edit_text("🔐 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён!")
        return
    await show_admin_panel(message)

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await show_admin_panel(callback)
    await callback.answer()

# --- Статистика ---
@dp.callback_query(F.data == "admin_stats_menu")
async def admin_stats_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 За день", callback_data="admin_stats_day")
    builder.button(text="📅 За неделю", callback_data="admin_stats_week")
    builder.button(text="📅 За месяц", callback_data="admin_stats_month")
    builder.button(text="📅 Всё время", callback_data="admin_stats_all")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(2, 2, 1)
    await callback.message.edit_text("📊 <b>Статистика</b> – выберите период:", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

async def show_period_stats(callback, period):
    now = datetime.now()
    if period == "day":
        since = now - timedelta(days=1)
    elif period == "week":
        since = now - timedelta(weeks=1)
    elif period == "month":
        since = now - timedelta(days=30)
    else:
        since = datetime(2000, 1, 1)
    total_users = db_execute("SELECT COUNT(*) FROM users WHERE start_date >= ?", (since,), fetch=True)[0][0]
    active_users = db_execute("SELECT COUNT(DISTINCT user_id) FROM location_progress WHERE timestamp >= ?", (since,), fetch=True)[0][0]
    completed_users = db_execute("SELECT COUNT(DISTINCT user_id) FROM location_progress WHERE visited = 1 AND timestamp >= ?", (since,), fetch=True)[0][0]
    text = (f"📊 <b>Статистика за {period}</b>\n\n"
            f"👥 Новых пользователей: {total_users}\n"
            f"🎮 Активных (отмечались): {active_users}\n"
            f"🏆 Посетили локации: {completed_users}")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="admin_stats_menu").as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_stats_day")
async def admin_stats_day(callback: types.CallbackQuery):
    await show_period_stats(callback, "day")

@dp.callback_query(F.data == "admin_stats_week")
async def admin_stats_week(callback: types.CallbackQuery):
    await show_period_stats(callback, "week")

@dp.callback_query(F.data == "admin_stats_month")
async def admin_stats_month(callback: types.CallbackQuery):
    await show_period_stats(callback, "month")

@dp.callback_query(F.data == "admin_stats_all")
async def admin_stats_all(callback: types.CallbackQuery):
    await show_period_stats(callback, "all")

# --- Пользователи ---
@dp.callback_query(F.data == "admin_users_info")
async def admin_users_info(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    now = datetime.now()
    total_users = db_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    active_now = db_execute("SELECT COUNT(DISTINCT user_id) FROM location_progress WHERE timestamp >= ?", (now - timedelta(hours=1),), fetch=True)[0][0]
    completed = db_execute("SELECT COUNT(DISTINCT user_id) FROM location_progress WHERE visited = 1", fetch=True)[0][0]
    on_route = db_execute("SELECT COUNT(DISTINCT user_id) FROM location_progress WHERE visited = 0 AND skipped = 0", fetch=True)[0][0]
    text = (f"👥 <b>Пользователи</b>\n\n"
            f"Всего в боте: {total_users}\n"
            f"На маршруте: {on_route}\n"
            f"Завершили: {completed}\n"
            f"Активны сейчас (последний час): {active_now}")
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

# --- Управление локациями ---
@dp.callback_query(F.data == "admin_locations_menu")
async def admin_locations_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить", callback_data="admin_add_location")
    builder.button(text="📋 Список", callback_data="admin_list_locations")
    builder.button(text="✏️ Редактировать", callback_data="admin_edit_location_select")
    builder.button(text="❌ Удалить", callback_data="admin_delete_location")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    await callback.message.edit_text("📍 <b>Управление локациями</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

# Добавление (пошаговый ввод)
@dp.callback_query(F.data == "admin_add_location")
async def admin_add_location_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminAddLocation.waiting_for_name)
    await callback.message.edit_text("Введите <b>название</b> локации:", parse_mode="HTML")
    await callback.answer()

@dp.message(StateFilter(AdminAddLocation.waiting_for_name))
async def process_name(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.update_data(name=message.text)
    await state.set_state(AdminAddLocation.waiting_for_description)
    await message.answer("Введите <b>краткое описание</b> (для карточки):", parse_mode="HTML")

@dp.message(StateFilter(AdminAddLocation.waiting_for_description))
async def process_description(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.update_data(description=message.text)
    await state.set_state(AdminAddLocation.waiting_for_info)
    await message.answer("Введите <b>подробную историческую справку</b> (info):", parse_mode="HTML")

@dp.message(StateFilter(AdminAddLocation.waiting_for_info))
async def process_info(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.update_data(info=message.text)
    await state.set_state(AdminAddLocation.waiting_for_lat)
    await message.answer("Введите <b>широту</b> (lat), например 44.8955:", parse_mode="HTML")

@dp.message(StateFilter(AdminAddLocation.waiting_for_lat))
async def process_lat(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        lat = float(message.text.replace(',', '.'))
        await state.update_data(lat=lat)
        await state.set_state(AdminAddLocation.waiting_for_lon)
        await message.answer("Введите <b>долготу</b> (lon), например 37.3198:", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Введите число. Пример: 44.8955")

@dp.message(StateFilter(AdminAddLocation.waiting_for_lon))
async def process_lon(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        lon = float(message.text.replace(',', '.'))
        await state.update_data(lon=lon)
        await state.set_state(AdminAddLocation.waiting_for_photo)
        await message.answer("📷 Отправьте <b>фотографию</b> локации (сжатое изображение).", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Введите число. Пример: 37.3198")

@dp.message(StateFilter(AdminAddLocation.waiting_for_photo), F.photo)
async def process_photo(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    data = await state.get_data()
    loc_id = add_location(data['name'], data['description'], data['info'], data['lat'], data['lon'], "")
    new_filename = f"loc_{loc_id}.jpg"
    dest_path = os.path.join(IMAGES_FOLDER, new_filename)
    await bot.download(message.photo[-1], destination=dest_path)
    db_execute("UPDATE locations SET photo=? WHERE id=?", (new_filename, loc_id))
    await state.clear()
    await message.answer(f"✅ Локация «{data['name']}» добавлена с ID {loc_id}.")
    await show_admin_panel(message)

@dp.message(StateFilter(AdminAddLocation.waiting_for_photo))
async def process_photo_invalid(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("Пожалуйста, отправьте именно фотографию (не документ).")

# Редактирование локации
@dp.callback_query(F.data == "admin_edit_location_select")
async def admin_edit_location_select(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    all_ids = get_all_location_ids()
    if not all_ids:
        await callback.answer("Нет локаций.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for loc_id in all_ids:
        loc = get_location(loc_id)
        builder.button(text=loc["name"], callback_data=f"edit_loc_{loc_id}")
    builder.button(text="🔙 Назад", callback_data="admin_locations_menu")
    builder.adjust(1)
    await callback.message.edit_text("Выберите локацию для редактирования:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_loc_"))
async def edit_location_choose_field(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    loc_id = int(callback.data.split("_")[2])
    await state.update_data(editing_loc_id=loc_id)
    builder = InlineKeyboardBuilder()
    fields = [
        ("Название", "edit_field_name"),
        ("Описание", "edit_field_description"),
        ("Историческая справка", "edit_field_info"),
        ("Широта", "edit_field_lat"),
        ("Долгота", "edit_field_lon"),
        ("Фото", "edit_field_photo")
    ]
    for label, callback_data in fields:
        builder.button(text=label, callback_data=callback_data)
    builder.button(text="🔙 Назад", callback_data="admin_edit_location_select")
    builder.adjust(2)
    await callback.message.edit_text("Что будем редактировать?", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_field_"))
async def edit_field_ask_value(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    field = callback.data.split("_")[2]
    await state.update_data(editing_field=field)
    await state.set_state(AdminEditLocation.waiting_for_new_value)
    prompts = {
        "name": "Введите новое название:",
        "description": "Введите новое описание:",
        "info": "Введите новую историческую справку:",
        "lat": "Введите новую широту:",
        "lon": "Введите новую долготу:",
        "photo": "Отправьте новое фото (или текстовое имя файла)."
    }
    await callback.message.edit_text(prompts.get(field, "Введите значение:"))
    await callback.answer()

@dp.message(StateFilter(AdminEditLocation.waiting_for_new_value))
async def process_edit_value(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    data = await state.get_data()
    loc_id = data["editing_loc_id"]
    field = data["editing_field"]
    value = message.text
    if field in ("lat", "lon"):
        try:
            value = float(value.replace(',', '.'))
        except ValueError:
            await message.answer("❌ Введите число.")
            return
    if field == "photo":
        if message.photo:
            file_id = message.photo[-1].file_id
            file = await bot.get_file(file_id)
            new_filename = f"loc_{loc_id}.jpg"
            dest_path = os.path.join(IMAGES_FOLDER, new_filename)
            await bot.download(file, destination=dest_path)
            value = new_filename
    update_location_field(loc_id, field, value)
    await state.clear()
    await message.answer("✅ Локация обновлена.")
    await show_admin_panel(message)

# Список и удаление
@dp.callback_query(F.data == "admin_list_locations")
async def admin_list_locations(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    all_ids = get_all_location_ids()
    if not all_ids:
        await callback.message.edit_text("Нет ни одной локации.", reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="admin_locations_menu").as_markup())
        await callback.answer()
        return
    text = "📍 <b>Список локаций:</b>\n\n"
    for loc_id in all_ids:
        loc = get_location(loc_id)
        text += f"ID {loc_id}: {loc['name']}\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_locations_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_delete_location")
async def admin_delete_location_start(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    all_ids = get_all_location_ids()
    builder = InlineKeyboardBuilder()
    for loc_id in all_ids:
        loc = get_location(loc_id)
        builder.button(text=f"❌ {loc['name']}", callback_data=f"confirm_delete_{loc_id}")
    builder.button(text="🔙 Назад", callback_data="admin_locations_menu")
    builder.adjust(1)
    await callback.message.edit_text("Выберите локацию для удаления:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete_location(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    loc_id = int(callback.data.split("_")[2])
    loc = get_location(loc_id)
    if not loc:
        await callback.answer("Локация не найдена.", show_alert=True)
        return
    delete_location(loc_id)
    await callback.answer(f"Локация «{loc['name']}» удалена.", show_alert=True)
    await admin_locations_menu(callback)

# --- Управление оплатой ---
@dp.callback_query(F.data == "admin_payment_settings")
async def admin_payment_settings(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    enabled = is_payment_enabled()
    price = get_price()
    loc_price = get_location_price()
    status_text = "✅ Включена" if enabled else "❌ Отключена"
    text = (f"💰 <b>Настройки оплаты</b>\n\n"
            f"Статус: {status_text}\n"
            f"Цена доступа: {price:.0f}₽\n"
            f"Цена добавления локации: {loc_price:.0f}₽")
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Переключить (вкл/выкл)", callback_data="admin_toggle_payment")
    builder.button(text="💵 Изменить цену доступа", callback_data="admin_change_price")
    builder.button(text="💵 Изменить цену локации", callback_data="admin_change_location_price")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_toggle_payment")
async def admin_toggle_payment(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    set_payment_enabled(not is_payment_enabled())
    await admin_payment_settings(callback)

@dp.callback_query(F.data == "admin_change_price")
async def admin_change_price(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminChangePrice.waiting_for_price)
    await callback.message.edit_text("Введите новую цену доступа (целое число):")
    await callback.answer()

@dp.callback_query(F.data == "admin_change_location_price")
async def admin_change_location_price(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminChangeLocationPrice.waiting_for_price)
    await callback.message.edit_text("Введите новую цену добавления локации (целое число):")
    await callback.answer()

@dp.message(StateFilter(AdminChangePrice.waiting_for_price))
async def process_new_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    try:
        new_price = float(message.text)
        if new_price <= 0:
            raise ValueError
        set_price(new_price)
        await message.answer(f"✅ Цена доступа изменена на {new_price:.0f}₽")
    except ValueError:
        await message.answer("❌ Введите положительное число.")
    finally:
        await state.clear()
    await show_admin_panel(message)

@dp.message(StateFilter(AdminChangeLocationPrice.waiting_for_price))
async def process_new_location_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    try:
        new_price = float(message.text)
        if new_price <= 0:
            raise ValueError
        set_location_price(new_price)
        await message.answer(f"✅ Цена добавления локации изменена на {new_price:.0f}₽")
    except ValueError:
        await message.answer("❌ Введите положительное число.")
    finally:
        await state.clear()
    await show_admin_panel(message)

# --- Платежи (список оплаченных пользователей) ---
@dp.callback_query(F.data == "admin_payments_list")
async def admin_payments_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    payments = db_execute("""
        SELECT p.user_id, u.username, u.first_name, p.amount, p.completed_at
        FROM payments p
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE p.status = 'succeeded'
        ORDER BY p.completed_at DESC
        LIMIT 20
    """, fetch=True)
    if not payments:
        await callback.message.edit_text("Нет успешных платежей.", reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="admin_back").as_markup())
        await callback.answer()
        return
    text = "💳 <b>Оплатившие пользователи:</b>\n\n"
    for user_id, username, first_name, amount, completed_at in payments:
        name = username or first_name or f"ID:{user_id}"
        text += f"• {name} (ID {user_id}) — {amount:.0f}₽, {completed_at[:16]}\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

# --- Доступ по ID ---
@dp.callback_query(F.data == "admin_grant_access")
async def admin_grant_access_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminGrantAccess.waiting_for_user_id)
    await callback.message.edit_text("Введите Telegram ID пользователя, которому нужно выдать доступ:")
    await callback.answer()

@dp.message(StateFilter(AdminGrantAccess.waiting_for_user_id))
async def admin_grant_access_process(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    try:
        user_id = int(message.text)
        if grant_access_to_user(user_id):
            await message.answer(f"✅ Доступ выдан пользователю {user_id}.")
            try:
                await bot.send_message(user_id, "🎉 Администратор выдал вам доступ к гиду по Анапе! Используйте /start для начала.")
            except:
                pass
            admin_name = message.from_user.first_name
            now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"🔑 <b>Ручная выдача доступа</b>\n"
                        f"👤 ID пользователя: <code>{user_id}</code>\n"
                        f"👨‍💼 Выдал: {admin_name}\n"
                        f"🕒 Время: {now_str}",
                        parse_mode="HTML"
                    )
                except:
                    pass
        else:
            await message.answer(f"⚠️ У пользователя {user_id} уже есть доступ.")
    except ValueError:
        await message.answer("❌ Введите корректный числовой ID.")
    finally:
        await state.clear()
    await show_admin_panel(message)

# --- Сообщения (30 дней) ---
@dp.callback_query(F.data == "admin_messages")
async def admin_messages_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    since = datetime.now() - timedelta(days=30)
    messages = db_execute(
        "SELECT id, user_id, message_text, timestamp, replied FROM support_messages WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT 15",
        (since,), fetch=True
    )
    if not messages:
        await callback.message.edit_text("Нет сообщений за последние 30 дней.", reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="admin_back").as_markup())
        await callback.answer()
        return
    text = "📩 <b>Последние сообщения (30 дн.):</b>\n\n"
    for msg_id, user_id, msg_text, ts, replied in messages:
        status = "✅" if replied else "🆕"
        text += f"{status} {ts[:16]} | ID {user_id}: {msg_text[:50]}...\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="Ответить на сообщение", callback_data="admin_reply_start")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_reply_start")
async def admin_reply_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminReplyMessage.waiting_for_user_id)
    await callback.message.edit_text("Введите ID пользователя, которому хотите ответить:")
    await callback.answer()

@dp.message(StateFilter(AdminReplyMessage.waiting_for_user_id))
async def admin_reply_get_user_id(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    try:
        user_id = int(message.text)
        await state.update_data(reply_user_id=user_id)
        await state.set_state(AdminReplyMessage.waiting_for_reply_text)
        await message.answer("Введите текст ответа:")
    except ValueError:
        await message.answer("❌ Введите числовой ID.")
        await state.clear()

@dp.message(StateFilter(AdminReplyMessage.waiting_for_reply_text))
async def admin_reply_send(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    data = await state.get_data()
    user_id = data["reply_user_id"]
    reply_text = message.text
    try:
        await bot.send_message(user_id, f"📩 <b>Ответ от администратора:</b>\n\n{reply_text}", parse_mode="HTML")
        db_execute("UPDATE support_messages SET replied=1 WHERE user_id=?", (user_id,))
        await message.answer("✅ Ответ отправлен.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить: {e}")
    finally:
        await state.clear()
    await show_admin_panel(message)

# --- Заявки на добавление локаций (с оплатой) ---
@dp.callback_query(F.data == "admin_location_requests")
async def admin_location_requests(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    requests = db_execute(
        "SELECT id, user_id, name, city, address, status FROM location_requests WHERE status='pending' ORDER BY timestamp DESC",
        fetch=True
    )
    if not requests:
        await callback.message.edit_text("Нет новых заявок.", reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="admin_back").as_markup())
        await callback.answer()
        return
    text = "📋 <b>Заявки на добавление:</b>\n\n"
    builder = InlineKeyboardBuilder()
    for req_id, user_id, name, city, address, status in requests:
        text += f"#{req_id} {name} ({city}, {address}) от {user_id}\n"
        builder.button(text=f"Одобрить #{req_id}", callback_data=f"approve_req_{req_id}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("approve_req_"))
async def approve_location_request(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    req_id = int(callback.data.split("_")[2])
    req = db_execute("SELECT user_id, name, photo, tags, city, address, description FROM location_requests WHERE id=?", (req_id,), fetch=True)
    if not req:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    user_id, name, photo, tags, city, address, description = req[0]
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        await callback.answer("ЮKassa не настроена.", show_alert=True)
        return
    try:
        payment = await create_payment_async(
            amount=get_location_price(),
            description=f"Добавление локации '{name}'",
            metadata={"request_id": req_id}
        )
        db_execute("UPDATE location_requests SET status='awaiting_payment', payment_id=? WHERE id=?", (payment.id, req_id))
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Оплатить добавление", url=payment.confirmation.confirmation_url)
        builder.button(text="🔄 Проверить оплату", callback_data=f"check_loc_payment_{req_id}")
        try:
            await bot.send_message(
                user_id,
                f"📢 Ваша заявка на добавление «{name}» одобрена!\n"
                f"Для публикации оплатите {get_location_price():.0f}₽.",
                reply_markup=builder.as_markup()
            )
            await callback.answer("Пользователю отправлена ссылка на оплату.", show_alert=True)
        except Exception as e:
            await callback.answer(f"Не удалось отправить сообщение пользователю: {e}", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка при создании платежа: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("check_loc_payment_"))
async def check_location_payment(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    req_id = int(callback.data.split("_")[3])
    req = db_execute("SELECT payment_id, user_id, name FROM location_requests WHERE id=?", (req_id,), fetch=True)
    if not req:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    payment_id, user_id, name = req[0]
    try:
        payment = await check_payment_async(payment_id)
        if payment.status == "succeeded":
            db_execute("UPDATE location_requests SET status='paid' WHERE id=?", (req_id,))
            await bot.send_message(user_id, "✅ Оплата получена! Администратор скоро добавит вашу локацию на карту.")
            await callback.answer("Оплата подтверждена.", show_alert=True)
            loc_price = get_location_price()
            now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"🏗 <b>Оплата за добавление локации!</b>\n"
                        f"📍 Локация: {name}\n"
                        f"👤 ID пользователя: <code>{user_id}</code>\n"
                        f"💳 Сумма: {loc_price:.0f}₽\n"
                        f"🕒 Время: {now_str}",
                        parse_mode="HTML"
                    )
                except:
                    pass
        elif payment.status == "pending":
            await callback.answer("Платёж ещё не завершён.", show_alert=True)
        else:
            await callback.answer(f"Статус платежа: {payment.status}", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка при проверке платежа: {e}", show_alert=True)
    await admin_location_requests(callback)

# --- Напоминания ---
@dp.callback_query(F.data == "admin_remind_stuck")
async def remind_stuck(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    threshold = datetime.now() - timedelta(hours=24)
    stuck = db_execute(
        "SELECT user_id FROM users WHERE last_activity < ? AND user_id IN (SELECT user_id FROM location_progress)",
        (threshold,), fetch=True
    )
    count = 0
    for (uid,) in stuck:
        try:
            await bot.send_message(uid, "⏰ Вы давно не заходили в гид! Продолжите исследование.")
            count += 1
        except:
            pass
    await callback.answer(f"Отправлено {count} напоминаний.", show_alert=True)

# ===== ОПЛАТА ДОСТУПА (асинхронная) =====
@dp.callback_query(F.data == "pay_access")
async def pay_access(callback: types.CallbackQuery):
    if not is_payment_enabled():
        await callback.answer("Оплата отключена.", show_alert=True)
        return
    user_id = callback.from_user.id
    if is_user_paid(user_id):
        await callback.answer("Вы уже оплатили доступ!", show_alert=True)
        return
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        await callback.answer("Платёжная система не настроена.", show_alert=True)
        return
    await callback.answer("Создаю платёж...")
    try:
        payment = await create_payment_async(
            amount=get_price(),
            description=f"Доступ к гиду по Анапе (пользователь {user_id})",
            metadata={"user_id": user_id}
        )
        db_execute("INSERT INTO payments (payment_id, user_id, amount, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                   (payment.id, user_id, get_price(), datetime.now()))
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Перейти к оплате", url=payment.confirmation.confirmation_url)
        builder.button(text="🔄 Проверить оплату", callback_data=f"check_payment_{payment.id}")
        builder.button(text="🏠 Главное меню", callback_data="main_menu")
        await callback.message.edit_text(
            f"💳 <b>Оплата доступа</b>\n\nСтоимость: {get_price():.0f}₽\n\n"
            "После оплаты нажмите «Проверить оплату».",
            parse_mode="HTML", reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        await callback.message.edit_text("❌ Не удалось создать платёж. Попробуйте позже.")
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def process_payment_check(callback: types.CallbackQuery, state: FSMContext):
    payment_id = callback.data.replace("check_payment_", "")
    try:
        payment = await check_payment_async(payment_id)
        if payment.status == "succeeded":
            db_execute("UPDATE payments SET status='succeeded', completed_at=? WHERE payment_id=?",
                       (datetime.now(), payment_id))
            await callback.message.edit_text("✅ Оплата прошла успешно!")
            await main_menu(callback, state)
            user = callback.from_user
            amount = get_price()
            now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"💰 <b>Новая оплата доступа!</b>\n"
                        f"👤 Имя: {user.first_name}\n"
                        f"🆔 ID: <code>{user.id}</code>\n"
                        f"💳 Сумма: {amount:.0f}₽\n"
                        f"🕒 Время: {now_str}",
                        parse_mode="HTML"
                    )
                except:
                    pass
        elif payment.status == "pending":
            await callback.answer("⏳ Платёж ещё не завершён. Попробуйте позже.", show_alert=True)
        else:
            await callback.answer(f"❌ Статус: {payment.status}. Попробуйте снова или обратитесь в поддержку.", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
        await callback.answer("⚠️ Не удалось проверить платёж.", show_alert=True)
    await callback.answer()

# ===== ЗАПУСК =====
async def main():
    try:
        print("Бот гида запущен")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
