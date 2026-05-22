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
        start_date TIMESTAMP,
        last_activity TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS location_progress (
        user_id INTEGER,
        location_index INTEGER,
        location_name TEXT,
        visited INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        timestamp TIMESTAMP,
        PRIMARY KEY (user_id, location_index)
    )''')
    conn.commit()
    conn.close()

init_db()

# ===== ОБЩИЙ МАРШРУТ (19 локаций) =====
LOCATIONS = [
    {"name": "Русские ворота", "description": "Остатки турецкой крепости.", "lat": 44.8955, "lon": 37.3198, "photo": "1.jpg", "info": "Памятник XVIII века."},
    {"name": "Храм Святого Онуфрия", "description": "Старейший храм города.", "lat": 44.8977, "lon": 37.3174, "photo": "2.jpg", "info": "Построен в 1830 году."},
    {"name": "Сквер Гудовича", "description": "Фонтан и тенистые аллеи.", "lat": 44.8959, "lon": 37.3148, "photo": "3.jpg", "info": "Приятный отдых."},
    {"name": "Краеведческий музей", "description": "Богатая коллекция артефактов.", "lat": 44.8961, "lon": 37.3167, "photo": "4.jpg", "info": "От античности до СССР."},
    {"name": "Набережная (фонтан)", "description": "Светомузыкальный фонтан.", "lat": 44.8936, "lon": 37.3170, "photo": "5.jpg", "info": "Вечернее шоу."},
    {"name": "Памятник отдыхающему", "description": "Забавная скульптура.", "lat": 44.8933, "lon": 37.3162, "photo": "6.jpg", "info": "Фото на удачу."},
    {"name": "Памятник «Белая шляпа»", "description": "Символ курортной моды.", "lat": 44.8921, "lon": 37.3150, "photo": "7.jpg", "info": "Популярное место."},
    {"name": "Парк 30-летия Победы", "description": "Аттракционы, кафе.", "lat": 44.8941, "lon": 37.3135, "photo": "8.jpg", "info": "Тенистые аллеи."},
    {"name": "Арка Центрального пляжа", "description": "Вход на главный пляж.", "lat": 44.8905, "lon": 37.3127, "photo": "9.jpg", "info": "Морские ворота."},
    {"name": "Лермонтовская беседка", "description": "Панорамный вид на море.", "lat": 44.8917, "lon": 37.3082, "photo": "10.jpg", "info": "Любимое место поэта."},
    {"name": "Маяк Анапский", "description": "Старинный маяк.", "lat": 44.8869, "lon": 37.2990, "photo": "11.jpg", "info": "Построен в 1898 году."},
    {"name": "Смотровая площадка", "description": "Вид на побережье.", "lat": 44.8878, "lon": 37.3005, "photo": "12.jpg", "info": "Обзор на десятки км."},
    {"name": "Дельфинарий", "description": "Представления с дельфинами.", "lat": 44.8790, "lon": 37.2935, "photo": "13.jpg", "info": "Работает с 1992 года."},
    {"name": "Аквапарк «Золотой пляж»", "description": "Горки и бассейны.", "lat": 44.8840, "lon": 37.2975, "photo": "14.jpg", "info": "Более 20 горок."},
    {"name": "Кипарисовое озеро", "description": "Зеркальная гладь среди кипарисов.", "lat": 44.910, "lon": 37.350, "photo": "15.jpg", "info": "Популярное фото."},
    {"name": "Сукко", "description": "Долина Сукко.", "lat": 44.790, "lon": 37.370, "photo": "16.jpg", "info": "Целебный воздух."},
    {"name": "Большой Утриш", "description": "Заповедник.", "lat": 44.750, "lon": 37.380, "photo": "17.jpg", "info": "Дикие пляжи."},
    {"name": "Варваровка", "description": "Станица с виноградниками.", "lat": 44.840, "lon": 37.370, "photo": "18.jpg", "info": "Местное виноделие."},
    {"name": "Благовещенская", "description": "Коса, лиманы.", "lat": 44.960, "lon": 37.280, "photo": "19.jpg", "info": "Кайтинг."},
]

# ===== СОСТОЯНИЯ =====
class QuestState(StatesGroup):
    current_idx = State()  # индекс активной локации (может быть None)

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

def get_user_progress(user_id):
    """Возвращает словарь: {location_index: {'visited': bool, 'skipped': bool}}"""
    rows = db_execute(
        "SELECT location_index, visited, skipped FROM location_progress WHERE user_id = ?",
        (user_id,), fetch=True
    )
    progress = {}
    for idx, visited, skipped in rows:
        progress[idx] = {'visited': bool(visited), 'skipped': bool(skipped)}
    return progress

def get_user_stats(user_id):
    """Собирает статистику и автоматически сбрасывает прогресс при полном завершении."""
    progress = get_user_progress(user_id)
    visited_count = sum(1 for v in progress.values() if v['visited'])
    skipped_count = sum(1 for v in progress.values() if v['skipped'])
    completed = visited_count == len(LOCATIONS)
    if completed:
        # Сброс прогресса, чтобы можно было начать заново
        db_execute("DELETE FROM location_progress WHERE user_id = ?", (user_id,))
        progress = {}
        visited_count = 0
        skipped_count = 0
        completed = False
    return {
        "visited": visited_count,
        "skipped": skipped_count,
        "total": len(LOCATIONS),
        "completed": completed,
        "progress_percent": round(visited_count / len(LOCATIONS) * 100, 1) if visited_count else 0,
        "progress": progress
    }

def mark_location(user_id, index, action='visited'):
    """Отмечает локацию как посещённую или пропущенную."""
    existing = db_execute(
        "SELECT visited, skipped FROM location_progress WHERE user_id = ? AND location_index = ?",
        (user_id, index), fetch=True
    )
    if existing:
        if action == 'visited':
            db_execute(
                "UPDATE location_progress SET visited = 1, skipped = 0, timestamp = ? WHERE user_id = ? AND location_index = ?",
                (datetime.now(), user_id, index)
            )
        else:
            db_execute(
                "UPDATE location_progress SET skipped = 1, visited = 0, timestamp = ? WHERE user_id = ? AND location_index = ?",
                (datetime.now(), user_id, index)
            )
    else:
        db_execute(
            "INSERT INTO location_progress (user_id, location_index, location_name, visited, skipped, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, index, LOCATIONS[index]["name"],
             1 if action == 'visited' else 0,
             1 if action == 'skipped' else 0,
             datetime.now())
        )

def get_unvisited_locations(user_id):
    """Возвращает индексы локаций, которые ещё не отмечены (ни visited, ни skipped)."""
    progress = get_user_progress(user_id)
    all_indices = set(range(len(LOCATIONS)))
    marked = set(progress.keys())
    return sorted(list(all_indices - marked))

def get_skipped_locations(user_id):
    """Возвращает индексы локаций, отмеченных как пропущенные (можно перепройти)."""
    progress = get_user_progress(user_id)
    return [idx for idx, v in progress.items() if v['skipped']]

# ===== КЛАВИАТУРЫ =====
def get_main_menu_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    stats = get_user_stats(user_id)
    if stats['visited'] == 0 and stats['skipped'] == 0:
        builder.button(text="🚀 Начать маршрут", callback_data="start_quest")
    else:
        unvisited = get_unvisited_locations(user_id)
        if unvisited:
            builder.button(text="📍 Продолжить маршрут", callback_data="continue_quest")
        skipped = get_skipped_locations(user_id)
        if skipped:
            builder.button(text="🔄 Перепройти пропущенные", callback_data="retry_skipped")
        builder.button(text="📊 Моя статистика", callback_data="my_stats")
    builder.button(text="ℹ️ О гиде", callback_data="about_quest")
    builder.button(text="🆘 Помощь", callback_data="help_info")
    builder.adjust(1, 2, 1)
    return builder.as_markup()

def get_quest_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data="skip_location")
    builder.button(text="📊 Статистика", callback_data="my_stats")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 1)
    return builder.as_markup()

def get_retry_skipped_keyboard(user_id):
    """Клавиатура со списком пропущенных локаций."""
    skipped = get_skipped_locations(user_id)
    builder = InlineKeyboardBuilder()
    for idx in skipped:
        loc = LOCATIONS[idx]
        builder.button(text=loc["name"], callback_data=f"retry_{idx}")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_photo_path(location):
    if "photo" in location:
        path = os.path.join(IMAGES_FOLDER, location["photo"])
        if os.path.isfile(path):
            return path
    return None

def is_nearby(user_lat, user_lon, target_lat, target_lon):
    return geodesic((user_lat, user_lon), (target_lat, target_lon)).meters <= RADIUS_METERS

async def send_location_with_photo(chat_id, index, state=None, prefix=""):
    """Отправляет фото и описание локации по индексу."""
    loc = LOCATIONS[index]
    photo_path = get_photo_path(loc)
    stats = get_user_stats(chat_id)  # используем chat_id как user_id
    progress_bar = "▓" * stats['visited'] + "░" * (len(LOCATIONS) - stats['visited'])
    caption = (f"{prefix}📍 <b>{loc['name']}</b> ({index+1}/{len(LOCATIONS)})\n"
               f"{loc['description']}\n\n"
               f"Прогресс: {progress_bar} ({stats['visited']}/{len(LOCATIONS)})\n"
               f"Отправьте геопозицию или используйте кнопки.")
    if photo_path:
        await bot.send_photo(chat_id, FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=get_quest_keyboard())
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=get_quest_keyboard())

async def send_location_info(chat_id, index):
    loc = LOCATIONS[index]
    if "info" in loc:
        await bot.send_message(chat_id, f"📚 <b>Это интересно:</b>\n{loc['info']}", parse_mode="HTML")

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
    await callback.message.edit_text(
        "🏙 <b>Главное меню</b>",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data == "start_quest")
async def start_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    # Сброс прогресса
    db_execute("DELETE FROM location_progress WHERE user_id = ?", (user_id,))
    await state.clear()
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        first_idx = unvisited[0]
        await state.update_data(current_idx=first_idx)
        await send_location_with_photo(callback.message.chat.id, first_idx, prefix="🚀 Поехали!\n")
        await callback.message.edit_text("Начинаем маршрут!")
    else:
        await callback.message.edit_text("Все локации уже посещены, но вы можете перепройти пропущенные.")
    await callback.answer()

@dp.callback_query(F.data == "continue_quest")
async def continue_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        next_idx = unvisited[0]
        await state.update_data(current_idx=next_idx)
        await send_location_with_photo(callback.message.chat.id, next_idx)
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
    skipped = get_skipped_locations(user_id)
    if not skipped:
        await callback.answer("Нет пропущенных локаций.", show_alert=True)
        return
    await callback.message.edit_text(
        "🔄 Выберите локацию для повторного прохождения:",
        reply_markup=get_retry_skipped_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("retry_"))
async def retry_location(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    idx = int(callback.data.split("_")[1])
    progress = get_user_progress(user_id)
    if idx not in progress or not progress[idx]['skipped']:
        await callback.answer("Эту локацию нельзя перепройти.", show_alert=True)
        return
    # Удаляем запись, чтобы локация снова стала доступной
    db_execute("DELETE FROM location_progress WHERE user_id = ? AND location_index = ?", (user_id, idx))
    await state.update_data(current_idx=idx)
    await callback.message.edit_text(f"Можете снова посетить «{LOCATIONS[idx]['name']}».\nОтправьте геопозицию, когда будете на месте.")
    await send_location_with_photo(callback.message.chat.id, idx)
    await callback.answer()

@dp.callback_query(F.data == "skip_location")
async def skip_location(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    current_idx = data.get("current_idx")
    if current_idx is None:
        await callback.answer("Нечего пропускать.", show_alert=True)
        return
    progress = get_user_progress(user_id)
    if current_idx in progress:
        await callback.answer("Эта локация уже отмечена.", show_alert=True)
        return
    mark_location(user_id, current_idx, 'skipped')
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"⏭ «{LOCATIONS[current_idx]['name']}» пропущена.")
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        next_idx = unvisited[0]
        await state.update_data(current_idx=next_idx)
        await send_location_with_photo(callback.message.chat.id, next_idx)
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
                "🎉 Вы посетили все локации! Маршрут завершён.\n/start для нового захода.",
                reply_markup=get_main_menu_keyboard(user_id)
            )
    await callback.answer()

@dp.message(F.location)
async def handle_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)

    data = await state.get_data()
    current_idx = data.get("current_idx")
    if current_idx is None:
        # Если нет активной, ищем первую непосещённую
        unvisited = get_unvisited_locations(user_id)
        if not unvisited:
            await message.answer("Все локации отмечены.")
            return
        current_idx = unvisited[0]
        await state.update_data(current_idx=current_idx)

    loc = LOCATIONS[current_idx]
    progress = get_user_progress(user_id)
    if current_idx in progress:
        await message.answer("Эта локация уже отмечена. Ищем следующую...")
        unvisited = get_unvisited_locations(user_id)
        if unvisited:
            current_idx = unvisited[0]
            await state.update_data(current_idx=current_idx)
            loc = LOCATIONS[current_idx]
        else:
            await message.answer("Все локации отмечены.")
            return

    if is_nearby(message.location.latitude, message.location.longitude, loc["lat"], loc["lon"]):
        await message.answer(f"✅ «{loc['name']}» пройдена!")
        mark_location(user_id, current_idx, 'visited')
        await send_location_info(message.chat.id, current_idx)
        unvisited = get_unvisited_locations(user_id)
        if unvisited:
            next_idx = unvisited[0]
            await state.update_data(current_idx=next_idx)
            await send_location_with_photo(message.chat.id, next_idx)
        else:
            await state.update_data(current_idx=None)
            skipped = get_skipped_locations(user_id)
            if skipped:
                await message.answer(
                    "Все локации отмечены. Можете перепройти пропущенные.",
                    reply_markup=get_retry_skipped_keyboard(user_id)
                )
            else:
                await message.answer(
                    "🏆 Вы посетили все локации! Маршрут завершён.\n/start для нового захода.",
                    reply_markup=get_main_menu_keyboard(user_id)
                )
    else:
        dist = geodesic((message.location.latitude, message.location.longitude), (loc["lat"], loc["lon"])).meters
        await message.answer(f"❌ До «{loc['name']}» ещё {dist:.0f} м.", reply_markup=get_quest_keyboard())

@dp.callback_query(F.data == "my_stats")
async def my_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)
    text = (f"📊 <b>Ваша статистика</b>\n\n"
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
    text = ("ℹ️ <b>Гид-бот по Анапе</b>\n\n"
            "Посещайте локации, отмечайте их геопозицией.\n"
            "Пропущенные можно перепройти.\n"
            "После завершения маршрута можно начать заново.")
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "help_info")
async def help_info(callback: types.CallbackQuery):
    text = ("🆘 <b>Помощь</b>\n\n"
            "/start – главное меню\n"
            "/skip – пропустить текущую локацию\n\n"
            "Для отметки локации отправьте геопозицию (📎 > Геопозиция).")
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.message(Command("skip"))
async def skip_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    current_idx = data.get("current_idx")
    if current_idx is None:
        await message.answer("Нечего пропускать.")
        return
    progress = get_user_progress(user_id)
    if current_idx in progress:
        await message.answer("Эта локация уже отмечена.")
        return
    mark_location(user_id, current_idx, 'skipped')
    await message.answer(f"⏭ «{LOCATIONS[current_idx]['name']}» пропущена.")
    unvisited = get_unvisited_locations(user_id)
    if unvisited:
        next_idx = unvisited[0]
        await state.update_data(current_idx=next_idx)
        await send_location_with_photo(message.chat.id, next_idx)
    else:
        await state.update_data(current_idx=None)
        await message.answer("Все локации отмечены.")

# ===== АДМИН-ПАНЕЛЬ (упрощённая) =====
async def show_admin_panel(target):
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="📍 Локации", callback_data="admin_locations")
    builder.button(text="🔔 Напомнить", callback_data="admin_remind_stuck")
    if CHART_AVAILABLE:
        builder.button(text="📈 График", callback_data="admin_chart")
    builder.adjust(2, 2, 1)
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

# Заглушки для админ-кнопок
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    total_users = db_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    active = db_execute("SELECT COUNT(DISTINCT user_id) FROM location_progress", fetch=True)[0][0]
    text = f"👥 Всего пользователей: {total_users}\n🎮 Активных: {active}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    top = db_execute("""
        SELECT u.username, u.first_name, COUNT(lp.location_index) as cnt
        FROM users u
        LEFT JOIN location_progress lp ON u.user_id = lp.user_id AND lp.visited = 1
        GROUP BY u.user_id
        ORDER BY cnt DESC
        LIMIT 10
    """, fetch=True)
    text = "👥 Топ-10 игроков:\n\n"
    for username, first_name, cnt in top:
        name = username or first_name or "Игрок"
        text += f"{name} – {cnt} локаций\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_locations")
async def admin_locations(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    text = "📍 Статистика по локациям (заглушка)"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_remind_stuck")
async def remind_stuck(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    threshold = datetime.now() - timedelta(hours=24)
    stuck = db_execute(
        "SELECT user_id FROM users WHERE last_activity < ? AND user_id IN (SELECT user_id FROM location_progress)",
        (threshold,), fetch=True
    )
    count = 0
    for (user_id,) in stuck:
        try:
            await bot.send_message(user_id, "⏰ Давно вас не было! Продолжите исследование.")
            count += 1
        except:
            pass
    await callback.answer(f"Отправлено {count} напоминаний.", show_alert=True)

async def main():
    print("Бот гида запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
