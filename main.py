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

# ===== РАСШИРЕННЫЙ СПИСОК ЛОКАЦИЙ (25) =====
LOCATIONS = [
    {
        "name": "Русские ворота",
        "description": "Остатки турецкой крепости. Отправьте геопозицию, когда окажетесь рядом.",
        "lat": 44.8955, "lon": 37.3198,
        "photo": "1.jpg",
        "info": (
            "🏛 <b>Русские ворота</b> — памятник архитектуры XVIII века.\n"
            "Построены в 1783 году как часть турецкой крепости Анапа.\n"
            "Названы в честь 25-летия освобождения города от турок в 1828 году.\n"
            "Автор проекта неизвестен, реставрация проводилась в 1950-х годах."
        )
    },
    {
        "name": "Храм Святого Онуфрия Великого",
        "description": "Старейший православный храм Анапы. Подойдите поближе.",
        "lat": 44.8977, "lon": 37.3174,
        "photo": "2.jpg",
        "info": (
            "⛪ <b>Храм Святого Онуфрия</b> построен в 1830 году.\n"
            "Освящён в честь небесного покровителя города — святого Онуфрия.\n"
            "Архитектор: предположительно И. К. Мальберг.\n"
            "Храм пережил Крымскую войну и советские гонения, возвращён верующим в 1990-х."
        )
    },
    {
        "name": "Сквер имени Гудовича",
        "description": "Уютный сквер с фонтаном в центре города. Отметьтесь здесь.",
        "lat": 44.8959, "lon": 37.3148,
        "photo": "3.jpg",
        "info": (
            "🌳 <b>Сквер Гудовича</b> назван в честь генерала Ивана Гудовича,\n"
            "командовавшего русскими войсками при взятии Анапы в 1791 году.\n"
            "Благоустроен в 1960-х, фонтан установлен в 1985 году."
        )
    },
    {
        "name": "Анапский краеведческий музей",
        "description": "Богатая коллекция артефактов от античности до наших дней. Вход рядом.",
        "lat": 44.8961, "lon": 37.3167,
        "photo": "4.jpg",
        "info": (
            "🏺 <b>Краеведческий музей</b> основан в 1913 году.\n"
            "Содержит более 30 000 экспонатов: античные амфоры, турецкое оружие,\n"
            "предметы быта казаков. Здание построено в стиле модерн в 1909 году."
        )
    },
    {
        "name": "Цветомузыкальный фонтан на набережной",
        "description": "Светомузыкальное шоу на центральной набережной. Найдите фонтаны.",
        "lat": 44.8936, "lon": 37.3170,
        "photo": "5.jpg",
        "info": (
            "💦 <b>Цветомузыкальный фонтан</b> открыт в 2014 году.\n"
            "Вечерние представления под музыку собирают сотни зрителей.\n"
            "Фонтан состоит из 120 струй, подсвечиваемых RGB-светильниками."
        )
    },
    {
        "name": "Памятник «Отдыхающий»",
        "description": "Забавная скульптура отдыхающего в гамаке на набережной.",
        "lat": 44.8933, "lon": 37.3162,
        "photo": "6.jpg",
        "info": (
            "😂 <b>Памятник отдыхающему</b> установлен в 2004 году.\n"
            "Скульптор: Александр Аполлонов.\n"
            "Стал одним из символов курортной Анапы, популярен для фото."
        )
    },
    {
        "name": "Памятник «Белая шляпа»",
        "description": "Огромная белая шляпа – дань курортной моде. Сделайте фото.",
        "lat": 44.8921, "lon": 37.3150,
        "photo": "7.jpg",
        "info": (
            "👒 <b>Белая шляпа</b> — арт-объект, установленный в 2010 году.\n"
            "Диаметр шляпы около 3 метров, весит более тонны.\n"
            "Символизирует защиту от солнца и лёгкость отпуска."
        )
    },
    {
        "name": "Парк 30-летия Победы",
        "description": "Главный городской парк с аттракционами и аллеями.",
        "lat": 44.8941, "lon": 37.3135,
        "photo": "8.jpg",
        "info": (
            "🌲 <b>Парк 30-летия Победы</b> разбит в 1975 году.\n"
            "Занимает площадь около 20 гектаров.\n"
            "Здесь установлен Вечный огонь и памятник воинам-освободителям."
        )
    },
    {
        "name": "Арка Центрального пляжа",
        "description": "Знаменитая арка, ведущая к главному песчаному пляжу.",
        "lat": 44.8905, "lon": 37.3127,
        "photo": "9.jpg",
        "info": (
            "🏖 <b>Арка Центрального пляжа</b> построена в 1956 году по проекту\n"
            "архитектора В. П. Соколова. Мозаичное панно на арке изображает\n"
            "морские мотивы и является визитной карточкой курорта."
        )
    },
    {
        "name": "Лермонтовская беседка",
        "description": "Место, где любил бывать Михаил Лермонтов. Панорамный вид на море.",
        "lat": 44.8917, "lon": 37.3082,
        "photo": "10.jpg",
        "info": (
            "📜 <b>Лермонтовская беседка</b> сооружена в 1900-х годах на месте,\n"
            "где по преданию поэт любовался морем во время ссылки на Кавказ.\n"
            "Отсюда открывается вид на Анапскую бухту и мыс Утриш."
        )
    },
    {
        "name": "Анапский маяк",
        "description": "Действующий маяк на высоком обрывистом берегу.",
        "lat": 44.8869, "lon": 37.2990,
        "photo": "11.jpg",
        "info": (
            "🔦 <b>Анапский маяк</b> построен в 1898 году.\n"
            "Высота башни 21 м, свет виден на 18 миль.\n"
            "Конструкция: французская оптика Френеля, капитальный ремонт в 2003 г."
        )
    },
    {
        "name": "Смотровая площадка «Ласточкино гнездо»",
        "description": "Потрясающий обзор побережья со скалы.",
        "lat": 44.8878, "lon": 37.3005,
        "photo": "12.jpg",
        "info": (
            "🌅 <b>Смотровая площадка</b> обустроена в 1970-х годах.\n"
            "Название получила из-за сходства с крымским Ласточкиным гнездом.\n"
            "В ясную погоду видно от мыса Утриш до косы Чушка."
        )
    },
    {
        "name": "Дельфинарий на Пионерском проспекте",
        "description": "Яркие представления с дельфинами и морскими котиками.",
        "lat": 44.8790, "lon": 37.2935,
        "photo": "13.jpg",
        "info": (
            "🐬 <b>Анапский дельфинарий</b> открыт в 1992 году.\n"
            "Вмещает до 500 зрителей, представления идут с мая по сентябрь.\n"
            "Помимо дельфинов, выступают белухи и морские львы."
        )
    },
    {
        "name": "Аквапарк «Золотой пляж»",
        "description": "Один из крупнейших аквапарков России с десятками горок.",
        "lat": 44.8840, "lon": 37.2975,
        "photo": "14.jpg",
        "info": (
            "🌊 <b>Аквапарк «Золотой пляж»</b> работает с 2006 года.\n"
            "Более 25 горок, бассейн с искусственной волной, детский городок.\n"
            "Расположен прямо у берега Чёрного моря."
        )
    },
    {
        "name": "Кипарисовое озеро",
        "description": "Живописное озеро среди кипарисов – рай для фотографов.",
        "lat": 44.910, "lon": 37.350,
        "photo": "15.jpg",
        "info": (
            "🌲 <b>Кипарисовое озеро</b> — искусственный водоём, созданный в 1980-х.\n"
            "Окружён болотными кипарисами, занесёнными в Красную книгу.\n"
            "Популярно для снимков на фоне отражения деревьев в воде."
        )
    },
    {
        "name": "Долина Сукко",
        "description": "Можжевеловые леса и целебный воздух в долине реки Сукко.",
        "lat": 44.790, "lon": 37.370,
        "photo": "16.jpg",
        "info": (
            "🌿 <b>Долина Сукко</b> известна реликтовыми можжевельниками возрастом до 600 лет.\n"
            "Здесь снимались фильмы «Кавказская пленница» и «Формула любви».\n"
            "Находится на территории заказника «Большой Утриш»."
        )
    },
    {
        "name": "Заповедник «Большой Утриш»",
        "description": "Дикие пляжи, скалы и уникальная природа заповедника.",
        "lat": 44.750, "lon": 37.380,
        "photo": "17.jpg",
        "info": (
            "🏞 <b>Большой Утриш</b> — государственный природный заповедник с 2010 года.\n"
            "Включает реликтовые фисташково-можжевеловые леса и морские гроты.\n"
            "Обитают черепахи Никольского и средиземноморские сколопендры."
        )
    },
    {
        "name": "Станица Варваровка",
        "description": "Тихая станица, окружённая виноградниками и холмами.",
        "lat": 44.840, "lon": 37.370,
        "photo": "18.jpg",
        "info": (
            "🍇 <b>Варваровка</b> основана в 1862 году как казачья станица.\n"
            "Местные винодельни производят сорта «Саперави» и «Рислинг».\n"
            "В окрестностях находится древнее городище Горгиппия (III в. до н.э.)."
        )
    },
    {
        "name": "Благовещенская коса",
        "description": "Узкая песчаная коса между Чёрным морем и лиманами.",
        "lat": 44.960, "lon": 37.280,
        "photo": "19.jpg",
        "info": (
            "🏄 <b>Благовещенская</b> — посёлок на косе длиной 12 км.\n"
            "Идеальное место для кайтинга, виндсёрфинга и пляжного отдыха.\n"
            "Лиманы Кизилташский и Витязевский богаты лечебными грязями."
        )
    },
    {
        "name": "Винодельня «Шато Тамань»",
        "description": "Современное винодельческое хозяйство с дегустационным залом.",
        "lat": 45.150, "lon": 36.710,
        "photo": "20.jpg",
        "info": (
            "🍷 <b>Шато Тамань</b> открыто в 2006 году на Таманском полуострове.\n"
            "Производит премиальные вина из местного винограда.\n"
            "Архитектура здания напоминает французские замки."
        )
    },
    {
        "name": "Крепость Фанагория",
        "description": "Руины античного города и крепости, археологический памятник.",
        "lat": 45.270, "lon": 36.960,
        "photo": "21.jpg",
        "info": (
            "🏛 <b>Фанагория</b> — крупнейшая древнегреческая колония на территории России,\n"
            "основанная в 543 году до н.э. Раскопки ведутся с 1936 года.\n"
            "Обнаружены остатки храмов, виноделен и жилых кварталов."
        )
    },
    {
        "name": "Грязевой вулкан Карабетова гора",
        "description": "Действующий грязевой вулкан с лечебной глиной.",
        "lat": 45.200, "lon": 37.000,
        "photo": "22.jpg",
        "info": (
            "🌋 <b>Карабетова гора</b> — один из крупнейших грязевых вулканов Тамани.\n"
            "Высота около 150 м, извержения происходят каждые 10-15 лет.\n"
            "Грязь используется в бальнеологических целях."
        )
    },
    {
        "name": "Памятник «Казакам-переселенцам»",
        "description": "Монумент в честь основания казачьих станиц на Кубани.",
        "lat": 44.920, "lon": 37.300,
        "photo": "23.jpg",
        "info": (
            "🗿 <b>Памятник казакам</b> установлен в 2011 году.\n"
            "Скульптор А. Скнарин изобразил казака с конём, олицетворяющего\n"
            "переселение Черноморского казачьего войска в 1792 году."
        )
    },
    {
        "name": "Анапский археологический музей под открытым небом",
        "description": "Остатки античного города Горгиппия на месте раскопок.",
        "lat": 44.8960, "lon": 37.3150,
        "photo": "24.jpg",
        "info": (
            "🏺 <b>Горгиппия</b> — античный город Боспорского царства (IV в. до н.э. – III в. н.э.).\n"
            "Раскопки ведутся с 1940-х, открыты улицы, дома, винодельни и некрополь.\n"
            "В 1977 году на этом месте создан музей-заповедник под открытым небом."
        )
    },
    {
        "name": "Скала «Парус»",
        "description": "Одинокая скала в море, напоминающая парусник.",
        "lat": 44.438, "lon": 38.230,
        "photo": "25.jpg",
        "info": (
            "⛵ <b>Скала Парус</b> находится в районе посёлка Джанхот (близ Анапы).\n"
            "Представляет собой вертикально стоящий пласт песчаника высотой 25 м.\n"
            "По легенде, это окаменевший парусник греческих мореплавателей."
        )
    }
]

# ===== СОСТОЯНИЯ =====
class QuestState(StatesGroup):
    current_idx = State()

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
    """Собирает статистику и сбрасывает прогресс при полном завершении."""
    progress = get_user_progress(user_id)
    visited_count = sum(1 for v in progress.values() if v['visited'])
    skipped_count = sum(1 for v in progress.values() if v['skipped'])
    completed = visited_count == len(LOCATIONS)
    if completed:
        # Сброс прогресса для возможности нового старта
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
    """Возвращает индексы локаций, которые ещё не отмечены."""
    progress = get_user_progress(user_id)
    all_indices = set(range(len(LOCATIONS)))
    marked = set(progress.keys())
    return sorted(list(all_indices - marked))

def get_skipped_locations(user_id):
    """Возвращает индексы локаций, отмеченных как пропущенные."""
    progress = get_user_progress(user_id)
    return [idx for idx, v in progress.items() if v['skipped']]

# ===== КЛАВИАТУРЫ =====
def get_main_menu_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    stats = get_user_stats(user_id)
    # Определяем состояние пользователя
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
    builder.adjust(2, 2, 1)  # в 2 столбца
    return builder.as_markup()

def get_quest_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data="skip_location")
    builder.button(text="📊 Статистика", callback_data="my_stats")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 1)
    return builder.as_markup()

def get_retry_skipped_keyboard(user_id):
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

async def send_location_with_photo(chat_id, index, prefix=""):
    loc = LOCATIONS[index]
    photo_path = get_photo_path(loc)
    stats = get_user_stats(chat_id)
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
        await bot.send_message(chat_id, loc["info"], parse_mode="HTML")

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====
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
    text = ("ℹ️ <b>Гид-бот по Анапе</b>\n\n"
            "Посещайте интересные места, узнавайте их историю.\n"
            "Маршрут включает 25 локаций по Анапе и окрестностям.\n"
            "Пропущенные локации можно перепройти.")
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

# ===== АДМИН-ПАНЕЛЬ =====
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
        ORDER BY cnt DESC LIMIT 10
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
