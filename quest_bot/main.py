# TOKEN = "8966936854:AAEl_6PQgLLvKslZQCMLZciivcFQwDlSjPc" 
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

# Попытка импорта matplotlib для графиков (опционально)
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    CHART_AVAILABLE = True
except ImportError:
    CHART_AVAILABLE = False
    print("⚠️ Matplotlib не установлен. Графики в админке будут недоступны.")
    print("   Установите командой: pip install matplotlib")

# ===== НАСТРОЙКИ =====
TOKEN = "8966936854:AAEl_6PQgLLvKslZQCMLZciivcFQwDlSjPc"          # 🔹 замените на токен от @BotFather
RADIUS_METERS = 50                 # радиус подтверждения локации
ADMIN_IDS = [5196749531]            # 🔹 замените на ваши Telegram ID
IMAGES_FOLDER = "images"           # папка с фотографиями

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
        completed INTEGER DEFAULT 0,
        completed_date TIMESTAMP,
        start_date TIMESTAMP,
        last_activity TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS location_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        location_index INTEGER,
        location_name TEXT,
        visited INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        timestamp TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

# ===== СПИСОК ЛОКАЦИЙ =====
LOCATIONS = [
    {
        "name": "Русские ворота",
        "description": "Начни квест с остатков турецкой крепости — Русские ворота.",
        "lat": 44.8955, "lon": 37.3198,
        "photo": "1.jpg",
        "info": "Русские ворота — единственная сохранившаяся часть турецкой крепости Анапа, построенной в 1783 году. Названы в честь 25-летия освобождения Анапы от турок в 1828 году."
    },
    {
        "name": "Храм Святого Онуфрия",
        "description": "Поднимись к храму Святого Онуфрия Великого, он совсем рядом.",
        "lat": 44.8977, "lon": 37.3174,
        "photo": "2.jpg",
        "info": "Храм Святого Онуфрия Великого — один из старейших храмов Анапы, построенный в 1830 году. Освящён в честь небесного покровителя города."
    },
    {
        "name": "Памятник «Мать и дитя»",
        "description": "Скульптура «Мать и дитя» в районе санатория «Надежда».",
        "lat": 44.8973, "lon": 37.3115,
        "photo": "3.jpg",
        "info": "Памятник символизирует материнство и семейные ценности. Установлен в 1960-х годах, стал одной из визитных карточек курорта."
    },
    {
        "name": "Сквер имени Гудовича",
        "description": "Зайди в сквер имени Гудовича и отметься у фонтана.",
        "lat": 44.8959, "lon": 37.3148,
        "photo": "4.jpg",
        "info": "Сквер назван в честь генерала Ивана Гудовича, командовавшего русскими войсками при взятии Анапы в 1791 году."
    },
    {
        "name": "Краеведческий музей",
        "description": "Посети Анапский краеведческий музей.",
        "lat": 44.8961, "lon": 37.3167,
        "photo": "5.jpg",
        "info": "Музей основан в 1913 году. Хранит богатую коллекцию артефактов от античности до советского периода."
    },
    {
        "name": "Набережная (Цветомузыкальный фонтан)",
        "description": "Найди светомузыкальный фонтан на центральной набережной.",
        "lat": 44.8936, "lon": 37.3170,
        "photo": "6.jpg",
        "info": "Цветомузыкальный фонтан — центр притяжения вечерней Анапы. Шоу огней и воды проводится ежедневно в летний сезон."
    },
    {
        "name": "Памятник отдыхающему",
        "description": "Скульптура «Отдыхающий» на набережной.",
        "lat": 44.8933, "lon": 37.3162,
        "photo": "7.jpg",
        "info": "Шутливая скульптура изображает курортника в гамаке. Появилась в 2000-х и быстро стала любимой у туристов."
    },
    {
        "name": "Памятник «Белая шляпа»",
        "description": "Продолжай по набережной до памятника «Белая шляпа».",
        "lat": 44.8921, "lon": 37.3150,
        "photo": "8.jpg",
        "info": "Символ курортной моды и защиты от солнца. Огромная белая шляпа — популярное место для фото."
    },
    {
        "name": "Парк 30-летия Победы",
        "description": "Поднимись к главному входу в парк 30-летия Победы.",
        "lat": 44.8941, "lon": 37.3135,
        "photo": "9.jpg",
        "info": "Парк разбит в 1975 году в честь юбилея Победы. Сегодня здесь аттракционы, кафе и тенистые аллеи."
    },
    {
        "name": "Арка Центрального пляжа",
        "description": "Спустись к морю через арку Центрального пляжа.",
        "lat": 44.8905, "lon": 37.3127,
        "photo": "10.jpg",
        "info": "Главный вход на центральный пляж Анапы. Арка украшена мозаикой и считается морскими воротами города."
    },
    {
        "name": "Лермонтовская беседка",
        "description": "Пройди на запад до Лермонтовской беседки.",
        "lat": 44.8917, "lon": 37.3082,
        "photo": "11.jpg",
        "info": "Беседка названа в честь Михаила Лермонтова, который бывал в Анапе. Отсюда открывается панорамный вид на море."
    },
    {
        "name": "Анапский маяк",
        "description": "Дойди до старинного Анапского маяка.",
        "lat": 44.8869, "lon": 37.2990,
        "photo": "12.jpg",
        "info": "Маяк построен в 1898 году. Высота башни 21 метр, свет виден на 18 миль. До сих пор действует."
    },
    {
        "name": "Смотровая площадка «Ласточкино гнездо»",
        "description": "Поднимись на смотровую площадку.",
        "lat": 44.8878, "lon": 37.3005,
        "photo": "13.jpg",
        "info": "Смотровая площадка на скале над морем. В хорошую погоду видно побережье на десятки километров."
    },
    {
        "name": "Дельфинарий",
        "description": "Переместись к дельфинарию на Пионерском проспекте.",
        "lat": 44.8790, "lon": 37.2935,
        "photo": "14.jpg",
        "info": "Анапский дельфинарий работает с 1992 года. Здесь проходят представления с дельфинами, морскими котиками и белухами."
    },
    {
        "name": "Аквапарк «Золотой пляж»",
        "description": "Финиш! Найди вход в аквапарк и заверши квест!",
        "lat": 44.8840, "lon": 37.2975,
        "photo": "15.jpg",
        "info": "Аквапарк «Золотой пляж» — один из крупнейших в России. Более 20 горок, бассейны и зоны отдыха."
    }
]

# ===== СОСТОЯНИЯ =====
class QuestState(StatesGroup):
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

def update_user_step(user_id, step):
    completed = 1 if step >= len(LOCATIONS) else 0
    db_execute(
        "UPDATE users SET current_step = ?, completed = ?, completed_date = ?, last_activity = ? WHERE user_id = ?",
        (step, completed, datetime.now() if completed else None, datetime.now(), user_id)
    )

def log_location_action(user_id, location_index, location_name, action_type):
    db_execute(
        "INSERT INTO location_progress (user_id, location_index, location_name, visited, skipped, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, location_index, location_name,
         1 if action_type == 'visited' else 0,
         1 if action_type == 'skipped' else 0,
         datetime.now())
    )

def get_user_stats(user_id):
    stats = db_execute("""
        SELECT current_step, completed,
               (SELECT COUNT(*) FROM location_progress WHERE user_id = ? AND visited = 1),
               (SELECT COUNT(*) FROM location_progress WHERE user_id = ? AND skipped = 1)
        FROM users WHERE user_id = ?
    """, (user_id, user_id, user_id), fetch=True)
    if stats:
        step, completed, visited, skipped = stats[0]
        return {
            "step": step,
            "completed": completed,
            "visited": visited,
            "skipped": skipped,
            "total_locations": len(LOCATIONS),
            "progress_percent": round(step / len(LOCATIONS) * 100, 1) if step > 0 else 0
        }
    return None

# ===== КЛАВИАТУРЫ =====
def get_main_menu_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    user_data = db_execute("SELECT completed, current_step FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if not user_data:
        builder.button(text="🚀 Начать квест", callback_data="start_quest")
        builder.button(text="ℹ️ О квесте", callback_data="about_quest")
    else:
        completed, step = user_data[0]
        if completed:
            builder.button(text="🔄 Пройти заново", callback_data="restart_quest")
            builder.button(text="📊 Моя статистика", callback_data="my_stats")
            builder.button(text="ℹ️ О квесте", callback_data="about_quest")
        elif step > 0:
            builder.button(text="📍 Продолжить квест", callback_data="continue_quest")
            builder.button(text="📊 Мой прогресс", callback_data="my_stats")
            builder.button(text="ℹ️ О квесте", callback_data="about_quest")
        else:
            builder.button(text="🚀 Начать квест", callback_data="start_quest")
            builder.button(text="ℹ️ О квесте", callback_data="about_quest")
    builder.button(text="🆘 Помощь", callback_data="help_info")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def get_quest_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data="skip_location")
    builder.button(text="📊 Прогресс", callback_data="my_stats")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 1)
    return builder.as_markup()

def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Общая статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="📍 Локации", callback_data="admin_locations")
    if CHART_AVAILABLE:
        builder.button(text="📈 График", callback_data="admin_chart")
    builder.button(text="📋 Детально за день", callback_data="admin_detail_today")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def get_location(index):
    return LOCATIONS[index] if 0 <= index < len(LOCATIONS) else None

def is_nearby(user_lat, user_lon, target_lat, target_lon):
    return geodesic((user_lat, user_lon), (target_lat, target_lon)).meters <= RADIUS_METERS

def get_photo_path(location_index: int) -> str | None:
    loc = get_location(location_index)
    if not loc or "photo" not in loc:
        return None
    path = os.path.join(IMAGES_FOLDER, loc["photo"])
    if os.path.isfile(path):
        return path
    return None

async def send_location_with_photo(chat_id, state, prefix=""):
    """Отправляет фото (если есть) и описание текущей локации"""
    data = await state.get_data()
    step = data.get("step", 0)
    if step >= len(LOCATIONS):
        await bot.send_message(chat_id, "🎉 Квест пройден! /start для меню.")
        return

    loc = get_location(step)
    photo_path = get_photo_path(step)

    progress_bar = "▓" * step + "░" * (len(LOCATIONS) - step)
    caption = (
        f"{prefix}"
        f"📍 <b>Локация {step+1}/{len(LOCATIONS)}</b>\n"
        f"<b>{loc['name']}</b>\n\n"
        f"{loc['description']}\n\n"
        f"Прогресс: {progress_bar} ({step}/{len(LOCATIONS)})\n\n"
        f"Отправь свою геопозицию или используй кнопки:"
    )

    if photo_path:
        await bot.send_photo(
            chat_id,
            FSInputFile(photo_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_quest_keyboard()
        )
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=get_quest_keyboard())

async def send_location_info(chat_id, location_index):
    """Отправляет дополнительную информацию о локации после её прохождения"""
    loc = get_location(location_index)
    if loc and "info" in loc:
        await bot.send_message(chat_id, f"📚 <b>Это интересно:</b>\n{loc['info']}", parse_mode="HTML")

# ===== ОБРАБОТЧИКИ КОМАНД =====
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    user_data = db_execute("SELECT completed, current_step FROM users WHERE user_id = ?", (user_id,), fetch=True)

    if user_data:
        completed, step = user_data[0]
        if completed:
            text = (f"🏙 <b>Добро пожаловать в квест по Анапе!</b>\n\n"
                    f"🎉 Вы уже прошли квест!\n📍 Пройдено: <b>{len(LOCATIONS)}</b> локаций\n\n"
                    f"Хотите пройти заново или посмотреть статистику?")
        elif step > 0:
            text = (f"🏙 <b>Квест по Анапе</b>\n\n"
                    f"👋 С возвращением!\n📍 Пройдено: <b>{step}/{len(LOCATIONS)}</b>\n\nВыберите действие:")
        else:
            text = (f"🏙 <b>Квест по Анапе — {len(LOCATIONS)} локаций</b>\n\n"
                    f"🗺 Исследуйте город, посещайте знаковые места\n"
                    f"📍 Подтверждайте геопозицией\n⏭ Можно пропускать локации\n\n"
                    f"Готовы начать приключение?")
    else:
        text = (f"🏙 <b>Квест по Анапе — {len(LOCATIONS)} локаций</b>\n\n"
                f"🗺 Исследуйте город, посещайте знаковые места\n"
                f"📍 Подтверждайте геопозицией\n⏭ Можно пропускать локации\n\n"
                f"Готовы начать приключение?")

    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard(user_id))

# ===== ОБРАБОТЧИКИ КНОПОК МЕНЮ =====
@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)

    if stats and stats['completed']:
        text = (f"🏙 <b>Главное меню</b>\n\n"
                f"🎉 Квест пройден!\n📍 Локаций: <b>{len(LOCATIONS)}</b>\n"
                f"✅ Посещено: <b>{stats['visited']}</b> | ⏭ Пропущено: <b>{stats['skipped']}</b>\n\n"
                f"Выберите действие:")
    elif stats:
        text = (f"🏙 <b>Главное меню</b>\n\n"
                f"📊 Прогресс: <b>{stats['progress_percent']}%</b>\n"
                f"📍 Локация: <b>{stats['step']}/{len(LOCATIONS)}</b>\n"
                f"✅ Пройдено: <b>{stats['visited']}</b> | ⏭ Пропущено: <b>{stats['skipped']}</b>\n\n"
                f"Выберите действие:")
    else:
        text = (f"🏙 <b>Главное меню</b>\n\n"
                f"🗺 Локаций: <b>{len(LOCATIONS)}</b>\n\nВыберите действие:")

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard(user_id))
    await callback.answer()

@dp.callback_query(F.data == "start_quest")
async def start_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    register_user(user_id, callback.from_user.username, callback.from_user.first_name)

    await state.set_state(QuestState.step)
    await state.update_data(step=0)
    update_user_step(user_id, 0)

    await callback.message.edit_text("🚀 Начинаем квест!")
    await send_location_with_photo(callback.message.chat.id, state, prefix="🎉 Первое задание!\n\n")
    await callback.answer("Квест начался! 🚀")

@dp.callback_query(F.data == "continue_quest")
async def continue_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db_execute("SELECT current_step FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if user_data:
        step = user_data[0][0]
        await state.set_state(QuestState.step)
        await state.update_data(step=step)
        await callback.message.edit_text("📍 Продолжаем квест!")
        await send_location_with_photo(callback.message.chat.id, state)
    await callback.answer()

@dp.callback_query(F.data == "restart_quest")
async def restart_quest(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    update_user_step(user_id, 0)

    await state.set_state(QuestState.step)
    await state.update_data(step=0)

    await callback.message.edit_text("🔄 Квест начат заново!")
    await send_location_with_photo(callback.message.chat.id, state, prefix="🎉 Первое задание!\n\n")
    await callback.answer("Поехали заново! 🔄")

@dp.callback_query(F.data == "my_stats")
async def my_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)

    if not stats:
        await callback.answer("Начните квест сначала!", show_alert=True)
        return

    progress_bar = "▓" * stats['step'] + "░" * (stats['total_locations'] - stats['step'])

    text = (f"📊 <b>Моя статистика</b>\n\n"
            f"Прогресс: {progress_bar}\n"
            f"📍 Пройдено локаций: <b>{stats['step']}/{stats['total_locations']}</b> ({stats['progress_percent']}%)\n\n"
            f"✅ Посещено: <b>{stats['visited']}</b>\n"
            f"⏭ Пропущено: <b>{stats['skipped']}</b>\n\n")

    if stats['completed']:
        text += "🏆 <b>Квест полностью пройден!</b>\n"
    else:
        next_loc = get_location(stats['step'])
        text += f"📍 Следующая: <b>{next_loc['name']}</b>\n"

    builder = InlineKeyboardBuilder()
    if not stats['completed']:
        builder.button(text="📍 Продолжить", callback_data="continue_quest")
    else:
        builder.button(text="🔄 Пройти заново", callback_data="restart_quest")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "about_quest")
async def about_quest(callback: types.CallbackQuery):
    text = (f"ℹ️ <b>О квесте</b>\n\n"
            f"🏙 <b>Квест по Анапе</b>\n"
            f"📍 <b>{len(LOCATIONS)}</b> знаковых мест города\n"
            f"🗺 Маршрут выстроен для удобной прогулки\n\n"
            f"<b>Как играть:</b>\n"
            f"1️⃣ Получаете задание с локацией\n"
            f"2️⃣ Идёте к ней и отправляете геопозицию\n"
            f"3️⃣ Бот проверяет расстояние (50м)\n"
            f"4️⃣ Получаете следующую локацию\n\n"
            f"⏭ Можно пропускать локации\n\n"
            f"Готовы исследовать Анапу? 🚀")

    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Начать квест", callback_data="start_quest")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "help_info")
async def help_info(callback: types.CallbackQuery):
    text = ("🆘 <b>Помощь</b>\n\n"
            "<b>Доступные команды:</b>\n"
            "/start — главное меню\n"
            "/progress — прогресс\n"
            "/skip — пропустить локацию\n"
            "/help — помощь\n\n"
            "<b>Как отправить геопозицию?</b>\n"
            "Нажмите на скрепку 📎 в поле ввода → Геопозиция → Отправить свою геопозицию\n\n"
            "<b>Не засчитывает локацию?</b>\n"
            "Нужно быть в радиусе 50м от точки. Подойдите ближе.\n\n"
            "По вопросам: @admin")

    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="main_menu")

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

# ===== ОБРАБОТЧИКИ КВЕСТА =====
@dp.callback_query(F.data == "skip_location")
async def skip_location(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    step = data.get("step", 0)

    if step >= len(LOCATIONS):
        await callback.answer("Квест завершён!")
        return

    name = get_location(step)["name"]
    log_location_action(user_id, step, name, 'skipped')
    step += 1
    await state.update_data(step=step)
    update_user_step(user_id, step)

    # Убираем кнопки у предыдущего сообщения с локацией
    await callback.message.edit_reply_markup(reply_markup=None)

    if step < len(LOCATIONS):
        await callback.message.answer(f"⏭ Локация «{name}» пропущена.")
        await send_location_with_photo(callback.message.chat.id, state)
    else:
        await callback.message.answer(
            f"⏭ Локация «{name}» пропущена.\n\n"
            f"🏆 <b>Поздравляю! Вы прошли весь квест по Анапе!</b>\n\n"
            f"Спасибо за участие!\n\nХотите пройти заново?",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard(user_id)
        )
    await callback.answer()

@dp.message(Command("skip"))
async def skip_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    step = data.get("step", 0)

    if step >= len(LOCATIONS):
        await message.answer("Квест пройден!")
        return

    name = get_location(step)["name"]
    log_location_action(user_id, step, name, 'skipped')
    step += 1
    await state.update_data(step=step)
    update_user_step(user_id, step)

    if step < len(LOCATIONS):
        await message.answer(f"⏭ «{name}» пропущена.")
        await send_location_with_photo(message.chat.id, state)
    else:
        await message.answer(
            f"⏭ «{name}» пропущена.\n🏆 Квест завершён!",
            reply_markup=get_main_menu_keyboard(user_id)
        )

@dp.message(F.location)
async def handle_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)

    current_state = await state.get_state()
    if current_state is None:
        await message.answer(
            "🎯 Сначала начните квест!\nИспользуйте /start для открытия меню.",
            reply_markup=get_main_menu_keyboard(user_id)
        )
        return

    data = await state.get_data()
    step = data.get("step", 0)

    if step >= len(LOCATIONS):
        await message.answer("Квест пройден! /start")
        return

    target = get_location(step)

    if is_nearby(message.location.latitude, message.location.longitude, target["lat"], target["lon"]):
        # Подтверждение локации
        await message.answer(f"✅ Локация «{target['name']}» пройдена!")
        log_location_action(user_id, step, target['name'], 'visited')
        
        # Отправляем историческую справку о пройденной локации
        await send_location_info(message.chat.id, step)

        # Переходим к следующей
        step += 1
        await state.update_data(step=step)
        update_user_step(user_id, step)

        if step < len(LOCATIONS):
            await send_location_with_photo(message.chat.id, state)
        else:
            await message.answer(
                f"🏆 <b>Поздравляю! Вы прошли весь квест по Анапе!</b>\n\n"
                f"🎉 Вы посетили все {len(LOCATIONS)} локаций!\nСпасибо за участие!\n\nХотите пройти заново?",
                parse_mode="HTML",
                reply_markup=get_main_menu_keyboard(user_id)
            )
    else:
        dist = geodesic(
            (message.location.latitude, message.location.longitude),
            (target["lat"], target["lon"])
        ).meters
        await message.answer(
            f"❌ До цели «{target['name']}» ещё примерно <b>{dist:.0f} м</b>.\n"
            f"Подойдите ближе и отправьте геопозицию снова.",
            parse_mode="HTML",
            reply_markup=get_quest_keyboard()
        )

@dp.message(Command("progress"))
async def progress(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = db_execute("SELECT current_step FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if not user_data:
        await message.answer("Начните квест: /start")
        return

    step = user_data[0][0]
    progress_bar = "▓" * step + "░" * (len(LOCATIONS) - step)
    await message.answer(
        f"📊 <b>Прогресс квеста</b>\n\n{progress_bar}\n📍 <b>{step}/{len(LOCATIONS)}</b> локаций\n\nИспользуйте кнопки для управления:",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(user_id)
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        "🆘 <b>Помощь по боту</b>\n\n/start — главное меню\n/progress — прогресс\n/skip — пропустить локацию\n/help — помощь\n\nПо вопросам: @admin",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(user_id)
    )

# ===== АДМИН-ПАНЕЛЬ =====
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён!")
        return

    await message.answer("🔐 <b>Админ-панель</b>\n\nВыберите раздел:", parse_mode="HTML", reply_markup=get_admin_keyboard())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!")
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="📅 За день", callback_data="admin_period_day")
    builder.button(text="📅 За неделю", callback_data="admin_period_week")
    builder.button(text="📅 За месяц", callback_data="admin_period_month")
    builder.button(text="📅 Всё время", callback_data="admin_period_all")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(2, 2, 1)

    await callback.message.edit_text("📊 <b>Выберите период:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_period_"))
async def admin_period(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!")
        return

    period = callback.data.replace("admin_period_", "")
    now = datetime.now()
    periods = {"day": timedelta(days=1), "week": timedelta(days=7), "month": timedelta(days=30), "all": timedelta(days=365*10)}
    start_date = now - periods.get(period, timedelta(days=365*10))

    total_users = db_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    completed_users = db_execute("SELECT COUNT(*) FROM users WHERE completed = 1", fetch=True)[0][0]
    active_users = db_execute("SELECT COUNT(*) FROM users WHERE current_step > 0 AND completed = 0", fetch=True)[0][0]

    new_period = db_execute("SELECT COUNT(*) FROM users WHERE start_date >= ?", (start_date,), fetch=True)[0][0]
    completed_period = db_execute("SELECT COUNT(*) FROM users WHERE completed = 1 AND completed_date >= ?", (start_date,), fetch=True)[0][0]

    period_names = {"day": "за сутки", "week": "за неделю", "month": "за месяц", "all": "за всё время"}
    text = (f"📊 <b>Статистика {period_names[period]}</b>\n\n"
            f"👥 <b>Пользователи:</b>\n"
            f"• Всего: <b>{total_users}</b>\n"
            f"• Новых: <b>{new_period}</b>\n"
            f"• Активных: <b>{active_users}</b>\n"
            f"• Завершили: <b>{completed_period}</b>\n\n")
    if new_period > 0:
        text += f"📈 <b>Конверсия в завершение:</b> <b>{completed_period/new_period*100:.1f}%</b>\n\n"
    text += f"🏆 <b>Всего завершили:</b> <b>{completed_users}</b>"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 К периодам", callback_data="admin_stats")
    builder.button(text="🏠 В меню", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_detail_today")
async def admin_detail_today(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!")
        return

    today = datetime.now().replace(hour=0, minute=0, second=0)
    new_today = db_execute("SELECT COUNT(*) FROM users WHERE start_date >= ?", (today,), fetch=True)[0][0]
    active_today = db_execute("SELECT COUNT(*) FROM users WHERE last_activity >= ?", (today,), fetch=True)[0][0]
    completed_today = db_execute("SELECT COUNT(*) FROM users WHERE completed = 1 AND completed_date >= ?", (today,), fetch=True)[0][0]

    location_activity = db_execute("""
        SELECT location_name, COUNT(*) as cnt
        FROM location_progress
        WHERE timestamp >= ?
        GROUP BY location_name
        ORDER BY cnt DESC
        LIMIT 5
    """, (today,), fetch=True)

    text = (f"📋 <b>Детальная статистика за сегодня</b>\n\n"
            f"👥 Новых пользователей: <b>{new_today}</b>\n"
            f"🎮 Активных сегодня: <b>{active_today}</b>\n"
            f"🏆 Завершили сегодня: <b>{completed_today}</b>\n\n")
    if location_activity:
        text += "📍 <b>Топ-5 локаций сегодня:</b>\n"
        for i, (name, count) in enumerate(location_activity, 1):
            text += f"{i}. {name}: <b>{count}</b> посещений\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!")
        return

    users = db_execute("""
        SELECT user_id, username, first_name, current_step, completed, start_date
        FROM users ORDER BY current_step DESC LIMIT 10
    """, fetch=True)

    text = "👥 <b>Топ-10 активных пользователей:</b>\n\n"
    for i, user in enumerate(users, 1):
        user_id, username, first_name, step, completed, start_date = user
        status = "✅ Завершил" if completed else f"📍 Локация {step+1}/{len(LOCATIONS)}"
        name = username or first_name or f"ID:{user_id}"
        text += f"{i}. {name}\n   {status}\n   🗓 {start_date[:10] if start_date else 'N/A'}\n\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_locations")
async def admin_locations(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!")
        return

    stats = []
    for i, loc in enumerate(LOCATIONS):
        visited = db_execute("SELECT COUNT(*) FROM location_progress WHERE location_index = ? AND visited = 1", (i,), fetch=True)[0][0]
        skipped = db_execute("SELECT COUNT(*) FROM location_progress WHERE location_index = ? AND skipped = 1", (i,), fetch=True)[0][0]
        stuck = db_execute("SELECT COUNT(*) FROM users WHERE current_step = ? AND completed = 0", (i,), fetch=True)[0][0]
        stats.append({"name": loc["name"], "index": i, "visited": visited, "skipped": skipped, "stuck": stuck})

    text = "📍 <b>Статистика по локациям:</b>\n\n"
    for loc in stats:
        text += (f"<b>{loc['index']+1}. {loc['name']}</b>\n"
                 f"   ✅ Посетили: {loc['visited']} | ⏭ Пропустили: {loc['skipped']} | Всего: {loc['visited']+loc['skipped']}\n"
                 f"   👤 Застряли: {loc['stuck']}\n\n")

    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await callback.message.answer(part, parse_mode="HTML")
    else:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="admin_back")
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_chart")
async def admin_chart(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!")
        return
    if not CHART_AVAILABLE:
        await callback.answer("📈 Графики недоступны. Установите matplotlib.", show_alert=True)
        return

    await callback.answer("📈 Создаю график...")
    dates, new_users, active, completed = [], [], [], []
    for i in range(6, -1, -1):
        date = datetime.now() - timedelta(days=i)
        dates.append(date.strftime("%d.%m"))
        day_start = date.replace(hour=0, minute=0, second=0)
        day_end = date.replace(hour=23, minute=59, second=59)
        new_users.append(db_execute("SELECT COUNT(*) FROM users WHERE start_date BETWEEN ? AND ?", (day_start, day_end), fetch=True)[0][0])
        active.append(db_execute("SELECT COUNT(*) FROM users WHERE last_activity BETWEEN ? AND ?", (day_start, day_end), fetch=True)[0][0])
        completed.append(db_execute("SELECT COUNT(*) FROM users WHERE completed = 1 AND completed_date BETWEEN ? AND ?", (day_start, day_end), fetch=True)[0][0])

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(dates, new_users, 'b-o', label='Новые', linewidth=2, markersize=8)
    ax.plot(dates, active, 'g-s', label='Активные', linewidth=2, markersize=8)
    ax.plot(dates, completed, 'r-^', label='Завершили', linewidth=2, markersize=8)
    ax.set_xlabel('Дата', fontsize=12)
    ax.set_ylabel('Количество', fontsize=12)
    ax.set_title('Статистика за неделю', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    for i, (n, a, c) in enumerate(zip(new_users, active, completed)):
        if n > 0: ax.annotate(str(n), (dates[i], n), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9, color='blue')
        if a > 0: ax.annotate(str(a), (dates[i], a), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9, color='green')
        if c > 0: ax.annotate(str(c), (dates[i], c), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9, color='red')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close()

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_back")
    await callback.message.answer_photo(
        types.BufferedInputFile(buf.getvalue(), filename="stats.png"),
        caption="📈 Статистика за последние 7 дней",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён!")
        return
    await callback.message.edit_text("🔐 <b>Админ-панель</b>\n\nВыберите раздел:", parse_mode="HTML", reply_markup=get_admin_keyboard())
    await callback.answer()

@dp.message()
async def any_text(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        "Используйте кнопки меню или команды:\n/start - главное меню\n/progress - прогресс\n/help - помощь",
        reply_markup=get_main_menu_keyboard(user_id)
    )

async def main():
    print("=" * 50)
    print("✅ Бот запущен и работает!")
    print(f"👑 Администраторы: {ADMIN_IDS}")
    print(f"📍 Локаций: {len(LOCATIONS)}")
    print(f"🎯 Радиус проверки: {RADIUS_METERS}м")
    if CHART_AVAILABLE:
        print("📈 Графики: доступны")
    else:
        print("⚠️ Графики: недоступны (установите matplotlib)")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())