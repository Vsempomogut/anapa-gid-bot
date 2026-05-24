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

YOOKASSA_SHOP_ID = "ВАШ_SHOP_ID"
YOOKASSA_SECRET_KEY = "ВАШ_СЕКРЕТНЫЙ_КЛЮЧ"

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

    # Добавляем поле type, если таблица уже существовала без него
    try:
        c.execute("ALTER TABLE locations ADD COLUMN type TEXT DEFAULT 'attraction'")
    except:
        pass

    c.execute("SELECT COUNT(*) FROM locations")
    if c.fetchone()[0] == 0:
        default_locations = [
            ("Русские ворота", "Остатки турецкой крепости. Отправьте геопозицию, когда окажетесь рядом.",
             "🏛 <b>Русские ворота</b> — памятник архитектуры XVIII века.\nПостроены в 1783 году как часть турецкой крепости Анапа.\nНазваны в честь 25-летия освобождения города от турок в 1828 году.\nАвтор проекта неизвестен, реставрация проводилась в 1950-х годах.",
             44.8955, 37.3198, "1.jpg", "attraction"),
            ("Храм Святого Онуфрия Великого", "Старейший православный храм Анапы. Подойдите поближе.",
             "⛪ <b>Храм Святого Онуфрия</b> построен в 1830 году.\nОсвящён в честь небесного покровителя города — святого Онуфрия.\nАрхитектор: предположительно И. К. Мальберг.\nХрам пережил Крымскую войну и советские гонения, возвращён верующим в 1990-х.",
             44.8977, 37.3174, "2.jpg", "attraction"),
            # ... (остальные 23 локации с type='attraction')
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

def is_user_paid(user_id):
    if not is_payment_enabled():
        return True
    row = db_execute(
        "SELECT payment_id FROM payments WHERE user_id = ? AND status = 'succeeded' LIMIT 1",
        (user_id,), fetch=True
    )
    return bool(row)

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

def find_nearest_locations(lat, lon, limit=5, filter_type=None):
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

async def send_location_with_photo(chat_id, loc_id, prefix=""):
    loc = get_location(loc_id)
    if not loc:
        await bot.send_message(chat_id, "Локация не найдена.")
        return
    photo_path = get_photo_path(loc)
    total = get_locations_count()
    stats = get_user_stats(chat_id)
    progress_bar = "▓" * stats['visited'] + "░" * (total - stats['visited'])
    distance_text = ""
    all_ids = get_all_location_ids()
    if loc_id in all_ids:
        idx = all_ids.index(loc_id)
        if idx + 1 < len(all_ids):
            next_loc = get_location(all_ids[idx + 1])
            if next_loc:
                dist_m = geodesic((loc["lat"], loc["lon"]), (next_loc["lat"], next_loc["lon"])).meters
                if dist_m >= 1000:
                    distance_text = f"\n📏 До следующей: {dist_m/1000:.1f} км"
                else:
                    steps = int(dist_m / 0.75)
                    distance_text = f"\n📏 До следующей: {int(dist_m)} м (~{steps} шагов)"
    caption = (f"{prefix}📍 <b>{loc['name']}</b> ({loc_id}/{total})\n"
               f"{loc['description']}{distance_text}\n\n"
               f"Прогресс: {progress_bar} ({stats['visited']}/{total})\n\n"
               f"Нажмите «📍 Я на месте» или отправьте геопозицию.")
    if photo_path:
        await bot.send_photo(chat_id, FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=get_quest_keyboard())
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=get_quest_keyboard())

async def send_location_info(chat_id, loc_id):
    loc = get_location(loc_id)
    if loc and loc["info"]:
        await bot.send_message(chat_id, loc["info"], parse_mode="HTML")

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
    builder.button(text="📍 Я на месте", callback_data="confirm_location")
    builder.button(text="⏭ Пропустить", callback_data="skip_location")
    builder.button(text="📊 Статистика", callback_data="my_stats")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 2)
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
    data = await state.get_data()
    filter_type = data.get('search_filter')
    nearest = find_nearest_locations(message.location.latitude, message.location.longitude, limit=5, filter_type=filter_type)
    if nearest:
        title = "🍽 <b>Ближайшие заведения:</b>\n\n" if filter_type == "food" else "📍 <b>Ближайшие места:</b>\n\n"
        text = title
        for i, loc in enumerate(nearest, 1):
            d = loc['distance']
            if d >= 1000:
                dist_str = f"{d/1000:.1f} км"
            else:
                dist_str = f"{int(d)} м"
            text += f"{i}. <b>{loc['name']}</b> – {dist_str}\n{loc['description']}\n\n"
        await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("Рядом ничего не найдено.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

@dp.callback_query(F.data == "add_location_info")
async def add_location_info(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_paid(callback.from_user.id):
        await callback.answer("Сначала оплатите доступ!", show_alert=True)
        return
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
    admin_text = (
        f"📩 <b>Новая заявка на добавление заведения</b>\n\n"
        f"👤 Пользователь: {user.first_name} (@{user.username or 'нет'}) ID: {user.id}\n"
        f"📛 Название: {data['loc_name']}\n"
        f"🏙 Город: {data['loc_city']}\n"
        f"📍 Адрес: {data['loc_address']}\n"
        f"🏷 Теги: {data['loc_tags']}\n"
        f"📝 Описание: {message.text}\n"
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
    await message.answer("✅ Спасибо! Ваша заявка отправлена администраторам и будет рассмотрена в ближайшее время.")
    await start_cmd(message, state)

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
    await callback.answer("📍 Отправьте вашу геопозицию для подтверждения.", show_alert=False)
    await callback.message.answer("Пожалуйста, отправьте вашу геопозицию (📎 > Геопозиция).")

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
        data = await state.get_data()
        filter_type = data.get('search_filter')
        nearest = find_nearest_locations(message.location.latitude, message.location.longitude, limit=5, filter_type=filter_type)
        if nearest:
            title = "🍽 <b>Ближайшие заведения:</b>\n\n" if filter_type == "food" else "📍 <b>Ближайшие места:</b>\n\n"
            text = title
            for i, loc in enumerate(nearest, 1):
                d = loc['distance']
                if d >= 1000:
                    dist_str = f"{d/1000:.1f} км"
                else:
                    dist_str = f"{int(d)} м"
                text += f"{i}. <b>{loc['name']}</b> – {dist_str}\n{loc['description']}\n\n"
            await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        else:
            await message.answer("Рядом ничего не найдено.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    # Квест активен
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
        await send_location_info(message.chat.id, current_id)
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
        await message.answer(f"❌ До «{loc['name']}» ещё {dist:.0f} м.", reply_markup=get_quest_keyboard())

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
    payment_status = "включён" if is_payment_enabled() else "отключён"
    text = (f"ℹ️ <b>Гид-бот по Анапе</b>\n\n"
            f"{get_locations_count()} локаций с историческими справками.\n"
            f"Режим оплаты: {payment_status}.\n"
            f"Стоимость: {price:.0f}₽.\n"
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

# ===== АДМИН-ПАНЕЛЬ (без изменений) =====
# ... (вставьте сюда весь код админки, управления локациями, оплаты, сообщений, напоминаний из предыдущего полного ответа)

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
