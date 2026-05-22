# TOKEN = "8966936854:AAEl_6PQgLLvKslZQCMLZciivcFQwDlSjPc" 
# ADMIN_IDS = [5196749531] Telegram ID
import asyncio
import sqlite3
import io
import os
from datetime import datetime, timedelta
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile
from geopy.distance import geodesic

# Попытка импорта matplotlib (необязательно)
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    CHART_AVAILABLE = True
except ImportError:
    CHART_AVAILABLE = False

# ===== НАСТРОЙКИ =====
TOKEN = "8966936854:AAEl_6PQgLLvKslZQCMLZciivcFQwDlSjPc"
RADIUS_METERS = 50
ADMIN_IDS = [5196749531]            # замените на свои Telegram ID
IMAGES_FOLDER = "images"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect('quest.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        current_step INTEGER DEFAULT 0,
        route_id TEXT,
        completed INTEGER DEFAULT 0,
        start_time TIMESTAMP,
        completed_date TIMESTAMP,
        start_date TIMESTAMP,
        last_activity TIMESTAMP
    )''')
    # Добавим недостающие поля, если таблица уже существовала
    try:
        c.execute("ALTER TABLE users ADD COLUMN start_time TIMESTAMP")
    except:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN route_id TEXT")
    except:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_activity TIMESTAMP")
    except:
        pass
    c.execute('''CREATE TABLE IF NOT EXISTS location_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        route_id TEXT,
        location_index INTEGER,
        location_name TEXT,
        visited INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        timestamp TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

# ===== МАРШРУТЫ =====
ROUTES = {
    "kids": {
        "name": "👶 Анапа с детьми",
        "description": "Семейные локации, парки, дельфинарий, аквапарк.",
        "locations": [
            {"name": "Парк 30-летия Победы", "description": "Аттракционы, тенистые аллеи, кафе.", "lat": 44.8941, "lon": 37.3135, "photo": "kids1.jpg", "info": "Отличное место для прогулок с детьми."},
            {"name": "Дельфинарий", "description": "Представления с дельфинами и морскими котиками.", "lat": 44.8790, "lon": 37.2935, "photo": "kids2.jpg", "info": "Дети в восторге!"},
            {"name": "Аквапарк «Золотой пляж»", "description": "Горки и бассейны для всей семьи.", "lat": 44.8840, "lon": 37.2975, "photo": "kids3.jpg", "info": "Более 20 горок."},
            {"name": "Памятник «Белая шляпа»", "description": "Весёлое фото на память.", "lat": 44.8921, "lon": 37.3150, "photo": "kids4.jpg", "info": "Символ курортной моды."},
            {"name": "Центральный пляж", "description": "Песчаный пляж с пологим входом.", "lat": 44.8905, "lon": 37.3127, "photo": "kids5.jpg", "info": "Идеально для купания с малышами."},
        ]
    },
    "adult": {
        "name": "🍷 Анапа взрослая",
        "description": "История, вино, панорамные виды.",
        "locations": [
            {"name": "Русские ворота", "description": "Остатки турецкой крепости.", "lat": 44.8955, "lon": 37.3198, "photo": "adult1.jpg", "info": "Памятник XVIII века."},
            {"name": "Краеведческий музей", "description": "Богатая коллекция артефактов.", "lat": 44.8961, "lon": 37.3167, "photo": "adult2.jpg", "info": "От античности до СССР."},
            {"name": "Лермонтовская беседка", "description": "Панорамный вид на море.", "lat": 44.8917, "lon": 37.3082, "photo": "adult3.jpg", "info": "Любимое место поэта."},
            {"name": "Винодельня «Кубань-Вино»", "description": "Дегустация местных вин.", "lat": 44.870, "lon": 37.350, "photo": "adult4.jpg", "info": "Экскурсии и магазин."},
            {"name": "Маяк Анапский", "description": "Старинный маяк на обрыве.", "lat": 44.8869, "lon": 37.2990, "photo": "adult5.jpg", "info": "Построен в 1898 году."},
        ]
    },
    "car": {
        "name": "🚗 На машине по району",
        "description": "Окрестности Анапы, природные красоты.",
        "locations": [
            {"name": "Кипарисовое озеро", "description": "Зеркальная гладь среди кипарисов.", "lat": 44.910, "lon": 37.350, "photo": "car1.jpg", "info": "Популярное место для фото."},
            {"name": "Сукко", "description": "Долина Сукко, можжевеловые леса.", "lat": 44.790, "lon": 37.370, "photo": "car2.jpg", "info": "Целебный воздух."},
            {"name": "Большой Утриш", "description": "Заповедник, дикие пляжи.", "lat": 44.750, "lon": 37.380, "photo": "car3.jpg", "info": "Место силы."},
            {"name": "Варваровка", "description": "Тихая станица с виноградниками.", "lat": 44.840, "lon": 37.370, "photo": "car4.jpg", "info": "Местное виноделие."},
            {"name": "Благовещенская", "description": "Коса, лиманы, кайтинг.", "lat": 44.960, "lon": 37.280, "photo": "car5.jpg", "info": "Рай для виндсёрферов."},
        ]
    },
    "walk": {
        "name": "🚶 Пешеходная классика",
        "description": "Исторический центр, набережная, парки.",
        "locations": [
            {"name": "Русские ворота", "description": "Старт от крепости.", "lat": 44.8955, "lon": 37.3198, "photo": "walk1.jpg", "info": "Символ Анапы."},
            {"name": "Храм Святого Онуфрия", "description": "Старейший храм города.", "lat": 44.8977, "lon": 37.3174, "photo": "walk2.jpg", "info": "Построен в 1830 году."},
            {"name": "Сквер Гудовича", "description": "Фонтан и тенистые аллеи.", "lat": 44.8959, "lon": 37.3148, "photo": "walk3.jpg", "info": "Приятный отдых."},
            {"name": "Набережная (фонтан)", "description": "Светомузыкальный фонтан.", "lat": 44.8936, "lon": 37.3170, "photo": "walk4.jpg", "info": "Вечернее шоу."},
            {"name": "Памятник отдыхающему", "description": "Забавная скульптура.", "lat": 44.8933, "lon": 37.3162, "photo": "walk5.jpg", "info": "Фото на удачу."},
        ]
    }
}

# ===== СОСТОЯНИЯ =====
class QuestState(StatesGroup):
    route = State()
    step = State()

# ===== РАБОТА С БД =====
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

def start_user_quest(user_id, route_id):
    db_execute(
        "UPDATE users SET current_step=0, route_id=?, completed=0, start_time=?, last_activity=? WHERE user_id=?",
        (route_id, datetime.now(), datetime.now(), user_id)
    )

def update_user_step(user_id, step, route_id):
    completed = 1 if step >= len(ROUTES[route_id]["locations"]) else 0
    db_execute(
        "UPDATE users SET current_step=?, completed=?, completed_date=?, last_activity=? WHERE user_id=?",
        (step, completed, datetime.now() if completed else None, datetime.now(), user_id)
    )

def log_location_action(user_id, route_id, location_index, location_name, action_type):
    db_execute(
        "INSERT INTO location_progress (user_id, route_id, location_index, location_name, visited, skipped, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, route_id, location_index, location_name,
         1 if action_type == 'visited' else 0,
         1 if action_type == 'skipped' else 0,
         datetime.now())
    )

def get_user_stats(user_id):
    row = db_execute("SELECT current_step, completed, route_id FROM users WHERE user_id=?", (user_id,), fetch=True)
    if not row:
        return None
    step, completed, route_id = row[0]
    if route_id not in ROUTES:
        return None
    total = len(ROUTES[route_id]["locations"])
    visited = db_execute("SELECT COUNT(*) FROM location_progress WHERE user_id=? AND visited=1", (user_id,), fetch=True)[0][0]
    skipped = db_execute("SELECT COUNT(*) FROM location_progress WHERE user_id=? AND skipped=1", (user_id,), fetch=True)[0][0]
    return {"step": step, "completed": completed, "route_id": route_id, "total": total,
            "visited": visited, "skipped": skipped,
            "progress_percent": round(step / total * 100, 1) if total else 0}

# ===== КЛАВИАТУРЫ =====
def get_main_menu_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    stats = get_user_stats(user_id)
    if not stats or stats['step'] == 0:
        builder.button(text="🗺 Выбрать маршрут", callback_data="select_route")
    else:
        if stats['completed']:
            builder.button(text="🔄 Пройти другой маршрут", callback_data="select_route")
            builder.button(text="📊 Моя статистика", callback_data="my_stats")
        else:
            builder.button(text="📍 Продолжить", callback_data="continue_quest")
            builder.button(text="📊 Прогресс", callback_data="my_stats")
    builder.button(text="🏆 Рейтинг", callback_data="leaders")
    builder.button(text="ℹ️ О боте", callback_data="about_quest")
    builder.button(text="🆘 Помощь", callback_data="help_info")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def get_route_selection_keyboard():
    builder = InlineKeyboardBuilder()
    for route_id, data in ROUTES.items():
        builder.button(text=data["name"], callback_data=f"start_route_{route_id}")
    builder.button(text="🔙 Главное меню", callback_data="main_menu")
    builder.adjust(2)  # кнопки маршрутов в два столбца
    return builder.as_markup()

def get_quest_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data="skip_location")
    builder.button(text="📊 Прогресс", callback_data="my_stats")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 1)
    return builder.as_markup()

def get_location(route_id, index):
    if route_id in ROUTES and 0 <= index < len(ROUTES[route_id]["locations"]):
        return ROUTES[route_id]["locations"][index]
    return None

def is_nearby(user_lat, user_lon, target_lat, target_lon):
    return geodesic((user_lat, user_lon), (target_lat, target_lon)).meters <= RADIUS_METERS

def get_photo_path(location):
    if "photo" in location:
        path = os.path.join(IMAGES_FOLDER, location["photo"])
        if os.path.isfile(path):
            return path
    return None

async def send_location_with_photo(chat_id, state):
    data = await state.get_data()
    route_id = data.get("route")
    step = data.get("step", 0)
    route = ROUTES.get(route_id)
    if not route or step >= len(route["locations"]):
        await bot.send_message(chat_id, "🎉 Маршрут пройден!")
        return
    loc = route["locations"][step]
    photo_path = get_photo_path(loc)
    total = len(route["locations"])
    progress_bar = "▓" * step + "░" * (total - step)

    # Расстояние до следующей точки
    distance_text = ""
    if step + 1 < total:
        next_loc = route["locations"][step + 1]
        dist_m = geodesic(
            (loc["lat"], loc["lon"]),
            (next_loc["lat"], next_loc["lon"])
        ).meters
        if dist_m >= 1000:
            distance_text = f"\n📏 До следующей точки: {dist_m/1000:.1f} км"
        else:
            steps_count = int(dist_m / 0.75)  # примерный шаг 0.75 м
            distance_text = f"\n📏 До следующей точки: {int(dist_m)} м (примерно {steps_count} шагов)"

    caption = (f"📍 <b>{route['name']}</b> – локация {step+1}/{total}\n"
               f"<b>{loc['name']}</b>\n\n{loc['description']}{distance_text}\n\n"
               f"Прогресс: {progress_bar} ({step}/{total})\n"
               f"Отправьте геопозицию или используйте кнопки.")

    if photo_path:
        await bot.send_photo(chat_id, FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=get_quest_keyboard())
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=get_quest_keyboard())

async def send_location_info(chat_id, route_id, index):
    loc = get_location(route_id, index)
    if loc and "info" in loc:
        await bot.send_message(chat_id, f"📚 <b>Это интересно:</b>\n{loc['info']}", parse_mode="HTML")

# ===== АДМИН-ПАНЕЛЬ (исправленная) =====
async def show_admin_panel(target):
    """Отображает админ-панель в переданном объекте (Message или CallbackQuery)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="📍 Локации", callback_data="admin_locations")
    builder.button(text="🔔 Напомнить застрявшим", callback_data="admin_remind_stuck")
    if CHART_AVAILABLE:
        builder.button(text="📈 График", callback_data="admin_chart")
    builder.adjust(2, 2, 1)

    if isinstance(target, types.Message):
        await target.answer("🔐 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    else:  # CallbackQuery
        await target.message.edit_text("🔐 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён!")
        return
    await show_admin_panel(message)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    total_users = db_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    active = db_execute("SELECT COUNT(*) FROM users WHERE completed=0 AND current_step>0", fetch=True)[0][0]
    completed = db_execute("SELECT COUNT(*) FROM users WHERE completed=1", fetch=True)[0][0]
    text = f"👥 Всего: {total_users}\n🎮 Активных: {active}\n🏆 Завершили: {completed}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    users = db_execute("SELECT username, first_name, route_id, current_step FROM users WHERE completed=0 LIMIT 10", fetch=True)
    text = "👥 Активные игроки:\n\n"
    for u, f, r, s in users:
        name = u or f or "Игрок"
        text += f"{name} – {ROUTES.get(r, {}).get('name', r)} (шаг {s})\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_locations")
async def admin_locations(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    text = "📍 Статистика по локациям будет здесь (можно доработать)"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_remind_stuck")
async def remind_stuck(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    threshold = datetime.now() - timedelta(hours=24)
    stuck = db_execute(
        "SELECT user_id FROM users WHERE completed=0 AND current_step>0 AND last_activity < ?",
        (threshold,), fetch=True
    )
    count = 0
    for (user_id,) in stuck:
        try:
            await bot.send_message(user_id, "⏰ Вы давно не заходили в гид! Продолжите своё приключение 🗺")
            count += 1
        except:
            pass
    await callback.answer(f"Напоминания отправлены {count} пользователям.", show_alert=True)

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    await show_admin_panel(callback)
    await callback.answer()

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    await message.answer(
        "🏙 <b>Гид-бот по Анапе</b>\n\nВыберите действие в меню:",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(user_id)
    )

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "🏙 <b>Главное меню</b>",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data == "select_route")
async def select_route(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🗺 <b>Выберите маршрут:</b>",
        parse_mode="HTML",
        reply_markup=get_route_selection_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("start_route_"))
async def start_route(callback: types.CallbackQuery, state: FSMContext):
    route_id = callback.data.split("_", 2)[2]
    if route_id not in ROUTES:
        await callback.answer("Маршрут не найден", show_alert=True)
        return
    user_id = callback.from_user.id
    start_user_quest(user_id, route_id)
    await state.set_state(QuestState.step)
    await state.update_data(route=route_id, step=0)
    await callback.message.edit_text(f"🚀 Начинаем маршрут «{ROUTES[route_id]['name']}»!")
    await send_location_with_photo(callback.message.chat.id, state)
    await callback.answer()

@dp.callback_query(F.data == "continue_quest")
async def continue_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    row = db_execute("SELECT route_id, current_step FROM users WHERE user_id=?", (user_id,), fetch=True)
    if row:
        route_id, step = row[0]
        if route_id in ROUTES:
            await state.set_state(QuestState.step)
            await state.update_data(route=route_id, step=step)
            await callback.message.edit_text("📍 Продолжаем!")
            await send_location_with_photo(callback.message.chat.id, state)
    await callback.answer()

# ИСПРАВЛЕННАЯ ФУНКЦИЯ ПРОПУСКА
@dp.callback_query(F.data == "skip_location")
async def skip_location(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    route_id = data.get("route")
    step = data.get("step", 0)
    if route_id not in ROUTES:
        await callback.answer("Маршрут не найден", show_alert=True)
        return
    if step >= len(ROUTES[route_id]["locations"]):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        return
    loc = ROUTES[route_id]["locations"][step]
    log_location_action(user_id, route_id, step, loc["name"], 'skipped')
    step += 1
    await state.update_data(step=step)
    update_user_step(user_id, step, route_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    if step < len(ROUTES[route_id]["locations"]):
        await callback.message.answer(f"⏭ «{loc['name']}» пропущена.")
        await send_location_with_photo(callback.message.chat.id, state)
    else:
        await callback.message.answer(
            f"⏭ «{loc['name']}» пропущена.\n🏆 <b>Маршрут завершён!</b>",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard(user_id)
        )
    await callback.answer()

@dp.message(F.location)
async def handle_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    data = await state.get_data()
    route_id = data.get("route")
    step = data.get("step", 0)
    if not route_id or route_id not in ROUTES:
        await message.answer("Сначала выберите маршрут.", reply_markup=get_main_menu_keyboard(user_id))
        return
    if step >= len(ROUTES[route_id]["locations"]):
        await message.answer("Маршрут уже пройден!")
        return
    target = ROUTES[route_id]["locations"][step]
    if is_nearby(message.location.latitude, message.location.longitude, target["lat"], target["lon"]):
        await message.answer(f"✅ «{target['name']}» пройдена!")
        log_location_action(user_id, route_id, step, target["name"], 'visited')
        await send_location_info(message.chat.id, route_id, step)
        step += 1
        await state.update_data(step=step)
        update_user_step(user_id, step, route_id)
        if step < len(ROUTES[route_id]["locations"]):
            await send_location_with_photo(message.chat.id, state)
        else:
            await message.answer("🏆 Поздравляем! Вы прошли весь маршрут!", reply_markup=get_main_menu_keyboard(user_id))
    else:
        dist = geodesic((message.location.latitude, message.location.longitude), (target["lat"], target["lon"])).meters
        await message.answer(f"❌ До цели «{target['name']}» ещё {dist:.0f} м.", reply_markup=get_quest_keyboard())

@dp.callback_query(F.data == "my_stats")
async def my_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)
    if not stats:
        await callback.answer("Сначала начните маршрут!", show_alert=True)
        return
    progress_bar = "▓" * stats['step'] + "░" * (stats['total'] - stats['step'])
    text = (f"📊 <b>Ваша статистика</b>\n\n{progress_bar}\n"
            f"Маршрут: {ROUTES[stats['route_id']]['name']}\n"
            f"Пройдено: {stats['step']}/{stats['total']}\n"
            f"Посещено: {stats['visited']}, пропущено: {stats['skipped']}\n")
    if stats['completed']:
        duration = db_execute("SELECT (julianday(completed_date) - julianday(start_time)) * 86400 FROM users WHERE user_id=?", (user_id,), fetch=True)
        if duration:
            sec = int(duration[0][0])
            mins, sec = divmod(sec, 60)
            text += f"⏱ Время прохождения: {mins} мин {sec} сек\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "leaders")
async def leaders(callback: types.CallbackQuery):
    rows = db_execute("""
        SELECT username, first_name, route_id,
               (julianday(completed_date) - julianday(start_time)) * 86400 AS duration
        FROM users
        WHERE completed = 1 AND start_time IS NOT NULL
        ORDER BY duration ASC LIMIT 10
    """, fetch=True)
    text = "🏆 <b>Рейтинг (быстрейшие прохождения):</b>\n\n"
    if not rows:
        text += "Пока никто не завершил маршрут."
    else:
        for i, (username, first_name, route_id, sec) in enumerate(rows, 1):
            name = username or first_name or "Игрок"
            mins, s = divmod(int(sec), 60)
            route_name = ROUTES.get(route_id, {}).get("name", route_id)
            text += f"{i}. {name} – {mins} мин {s} сек ({route_name})\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.message(Command("leaders"))
async def leaders_cmd(message: types.Message):
    rows = db_execute("""
        SELECT username, first_name, route_id,
               (julianday(completed_date) - julianday(start_time)) * 86400 AS duration
        FROM users
        WHERE completed = 1 AND start_time IS NOT NULL
        ORDER BY duration ASC LIMIT 10
    """, fetch=True)
    text = "🏆 <b>Рейтинг:</b>\n\n"
    if rows:
        for i, (username, first_name, route_id, sec) in enumerate(rows, 1):
            name = username or first_name or "Игрок"
            mins, s = divmod(int(sec), 60)
            route_name = ROUTES.get(route_id, {}).get("name", route_id)
            text += f"{i}. {name} – {mins} мин {s} сек ({route_name})\n"
    else:
        text += "Пока никто не завершил маршрут."
    await message.answer(text, parse_mode="HTML")

@dp.callback_query(F.data == "about_quest")
async def about_quest(callback: types.CallbackQuery):
    text = ("ℹ️ <b>Гид-бот по Анапе</b>\n\n"
            "Выбирайте маршрут, посещайте локации, соревнуйтесь в рейтинге!\n\n"
            "Доступные маршруты:\n" +
            "\n".join([f"• {v['name']} – {v['description']}" for v in ROUTES.values()]))
    builder = InlineKeyboardBuilder()
    builder.button(text="🗺 Выбрать маршрут", callback_data="select_route")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "help_info")
async def help_info(callback: types.CallbackQuery):
    text = ("🆘 <b>Помощь</b>\n\n"
            "/start – главное меню\n"
            "/leaders – рейтинг\n"
            "/skip – пропустить локацию\n\n"
            "Для отметки локации отправьте свою геопозицию (📎 > Геопозиция).")
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.message(Command("skip"))
async def skip_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    route_id = data.get("route")
    step = data.get("step", 0)
    if route_id not in ROUTES or step >= len(ROUTES[route_id]["locations"]):
        await message.answer("Нечего пропускать.")
        return
    loc = ROUTES[route_id]["locations"][step]
    log_location_action(user_id, route_id, step, loc["name"], 'skipped')
    step += 1
    await state.update_data(step=step)
    update_user_step(user_id, step, route_id)
    if step < len(ROUTES[route_id]["locations"]):
        await message.answer(f"⏭ «{loc['name']}» пропущена.")
        await send_location_with_photo(message.chat.id, state)
    else:
        await message.answer("🏆 Маршрут завершён!", reply_markup=get_main_menu_keyboard(user_id))

@dp.message()
async def any_text(message: types.Message):
    await message.answer("Используйте меню или /start")

async def main():
    print("Бот гида запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
