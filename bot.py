import sys, io, os, asyncio, logging, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
import openai

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8759642687:AAEz_aaDnrPBVfZ_z4a6Fljzo78jOiG9N0A")
ADMIN_ID = 1979681125

from database import init_db, save_user, get_user, save_booking
from locales import LOCALES, LANGUAGE_NAMES

logging.basicConfig(level=logging.INFO)

# Фейковый HTTP-сервер для Render
class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")
    def log_message(self, format, *args):
        pass

def run_fake_server():
    try:
        port = int(os.environ.get('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), FakeHandler)
        logging.info(f"Фейковый сервер запущен на порту {port}")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Ошибка фейкового сервера: {e}")

threading.Thread(target=run_fake_server, daemon=True).start()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- AI Модуль ---
if "GROQ_API_KEY" not in os.environ:
    logging.error("GROQ_API_KEY не найден в переменных окружения!")
    sys.exit(1)

client = openai.OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"]
)

async def get_ai_response(user_message: str, user_data: dict, history: list) -> str:
    user_info = f"Имя ученика: {user_data.get('name', 'неизвестно')}, Возраст: {user_data.get('age', 'неизвестно')}, Уровень: {user_data.get('skill', 'неизвестно')}, Цели: {user_data.get('goals', 'неизвестно')}."

    system_prompt = (
        "Ты — интеллектуальный ассистент Софии, основательницы студии рисования SouffleArt. "
        "Твоя задача — приветствовать, рассказывать о курсах, помогать с записью на пробный урок.\n\n"
        "Правила общения:\n"
        "1. Если тебя настоятельно не просят представиться ещё раз, делай это ТОЛЬКО в первом ответе пользователю. В последующих диалогах сразу переходи к делу.\n"
        "2. Отвечай приветливо, кратко (2-3 предложения).\n"
        "3. Если клиент хочет записаться, предложи пробный урок (он бесплатный, 20-30 мин). Спроси удобный день.\n"
        "4. Если клиент спрашивает о направлениях, расскажи о трёх: Академический рисунок, Скетчинг, Свободная тема.\n"
        "8. Отвечай на том же языке, на котором к тебе обращаются (русский, сербский, английский). "
        "Если видишь, что клиент использует несколько языков, выбери тот, который преобладает.\n\n"
        "5. Учитывай возраст: детям до 14 лет вежливо откажи (только индивидуальный мастер-класс по договорённости).\n"
        "6. Не давай медицинских советов.\n"
        "7. Оплата: только карты или перевод. Наличных нет.\n\n"
        "База знаний:\n"
        "- Направления:\n"
        "  • Академический рисунок: композиция, перспектива, светотень, конструктивное построение.\n"
        "  • Скетчинг: быстрые зарисовки, развитие креативности, подходит для любого уровня.\n"
        "  • Свободная тема: рисуете что хотите, я помогаю.\n"
        "- Цены:\n"
        "  • Пробный урок: бесплатно, 20-30 мин.\n"
        "  • Разовое занятие: 10€, 50 мин.\n"
        "  • Абонемент на 4 занятия: 36€ (9€/урок).\n"
        "  • Абонемент на 8 занятий: 64€ (8€/урок).\n"
        "  • Абонемент на 12 занятий: 90€ (7.5€/урок).\n"
        "- Расписание: Пн, Ср, Пт, Сб с 17:00 до 21:00 (по часам).\n"
        "- Формат: онлайн через Zoom/Skype/Telegram. Материалы для скетчинга/свободной темы — бумага и карандаш, для академического — дополнительные, объясню на пробном.\n"
        "- Контакты: Instagram https://www.instagram.com/sofia_lodygina , Telegram канал https://t.me/Souffle_LSD .\n"
        "- Правила: за день напоминание, после урока — отзыв.\n\n"
        "Примеры:\n"
        "Клиент: «Я новичок, что посоветуете?»\n"
        "Ты: «Рекомендую Скетчинг. Пробный урок бесплатный, хотели бы попробовать в среду в 17:00?»\n"
        "Клиент: «Сколько стоит?»\n"
        "Ты: «Пробный — бесплатно. Разовое занятие — 10€, абонементы выгоднее. Рассказать подробнее?»"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-4:]:
        messages.append(msg)
    messages.append({"role": "user", "content": f"{user_info}\n\nСообщение от ученика: {user_message}"})

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Ошибка Groq API: {e}")
        return None

user_dialogs = {}
welcomed_users = set()  # пользователи, которых уже поприветствовали

# --- FSM ---
class EnrollState(StatesGroup):
    waiting_for_name = State()
    waiting_for_age = State()
    waiting_for_skill = State()
    waiting_for_goals = State()
    waiting_for_course = State()
    waiting_for_lesson_type = State()
    waiting_for_date = State()
    waiting_for_time = State()

class BookingState(StatesGroup):
    waiting_for_course = State()
    waiting_for_lesson_type = State()
    waiting_for_subscription_qty = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_payment = State()

# --- Клавиатуры и функции ---
def get_text(lang: str, key: str, **kwargs) -> str:
    try:
        text = LOCALES[lang][key]
    except KeyError:
        text = LOCALES["ru"][key]
    return text.format(**kwargs) if kwargs else text

def get_main_menu_keyboard(lang: str = "ru"):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📚 Курсы", callback_data="courses"))
    builder.row(InlineKeyboardButton(text="📝 Записаться", callback_data="enroll"))
    builder.row(InlineKeyboardButton(text="🖼 Портфолио", callback_data="portfolio"))
    builder.row(InlineKeyboardButton(text="👩‍🎨 О студии", callback_data="about"))
    builder.row(InlineKeyboardButton(text="💰 Прайс-лист", callback_data="prices"))
    return builder.as_markup()

# --- Обработчики ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await get_user(user_id)
    if not user_data:
        await message.answer("🎨 Привет! Давай познакомимся. Как тебя зовут?")
        await state.set_state(EnrollState.waiting_for_name)
    else:
        await message.answer(
            f"Добрый день. Я — интеллектуальный ассистент Софии, художницы и основательницы студии SouffleArt.\nОна учит рисовать без страха и скуки, а я здесь, чтобы ответить на ваши вопросы, рассказать о курсах и помочь с записью на пробное занятие.\nЧем я могу быть вам полезен?",
            reply_markup=get_main_menu_keyboard()
        )

@dp.message(EnrollState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Сколько тебе лет?")
    await state.set_state(EnrollState.waiting_for_age)

@dp.message(EnrollState.waiting_for_age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введи возраст цифрами.")
        return
    await state.update_data(age=int(message.text))
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Новичок", callback_data="skill_beginner"))
    builder.row(InlineKeyboardButton(text="Небольшой опыт", callback_data="skill_intermediate"))
    builder.row(InlineKeyboardButton(text="Рисую уверенно", callback_data="skill_advanced"))

    await message.answer("Какой у тебя уровень рисования?", reply_markup=builder.as_markup())
    await state.set_state(EnrollState.waiting_for_skill)

@dp.callback_query(lambda c: c.data.startswith("skill_"))
async def process_skill(callback: types.CallbackQuery, state: FSMContext):
    skill_map = {"skill_beginner": "Новичок", "skill_intermediate": "Небольшой опыт", "skill_advanced": "Рисую уверенно"}
    skill = skill_map[callback.data]
    await state.update_data(skill=skill)
    await callback.message.answer("Какие у тебя цели и пожелания? Напиши своими словами.")
    await state.set_state(EnrollState.waiting_for_goals)
    await callback.answer()

@dp.message(EnrollState.waiting_for_goals)
async def process_goals(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    await save_user(user_id, data["name"], data["age"], data["skill"], message.text)
    await state.clear()
    await message.answer(
        f"Отлично, {data['name']}! Твои данные сохранены.",
        reply_markup=get_main_menu_keyboard()
    )

@dp.callback_query(lambda c: c.data == "courses")
async def show_courses(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔹 Академический рисунок", callback_data="course_academic"))
    builder.row(InlineKeyboardButton(text="🔹 Скетчинг", callback_data="course_sketching"))
    builder.row(InlineKeyboardButton(text="🔹 Свободная тема", callback_data="course_free"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(
        "Я предлагаю три основных направления. Выберите то, что вам ближе:\n\n"
        "🔹 Академический рисунок\nДля тех, кто хочет получить серьёзную базу. Изучим композицию, перспективу, светотень и конструктивное построение.\n\n"
        "🔹 Скетчинг\nДля лёгкости и смелости. Быстрые, живые зарисовки. Научимся не бояться ошибок и находить свой стиль.\n\n"
        "🔹 Свободная тема\nРисуем то, что интересно именно Вам. Я буду вашим наставником и помогу прийти к результату.",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("course_"))
async def course_info(callback: types.CallbackQuery):
    course = callback.data.split("_")[1]
    info = {
        "academic": "📐 Академический рисунок — база для серьёзного роста. Композиция, перспектива, светотень.",
        "sketching": "✏️ Скетчинг — лёгкость и смелость. Быстрые наброски, развитие стиля.",
        "free": "🎨 Свободная тема — рисуйте что хотите, я помогу."
    }
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📝 Записаться", callback_data="enroll"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(info.get(course, "Описание скоро появится."), reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["portfolio", "about", "prices"])
async def info_pages(callback: types.CallbackQuery):
    texts = {
        "portfolio": (
    "🖼 Мои работы можно посмотреть здесь:\n\n"
    "📸 Instagram: https://www.instagram.com/sofia_lodygina\n"
    "✏️ Telegram-канал: https://t.me/Souffle_LSD\n"
    "📂 Портфолио по направлениям в одном файле (скоро здесь)."
        ),
        "about": (
            "👩‍🎨 Меня зовут София. Souffle — мой творческий псевдоним.\n\n"
            "Я художница и преподаватель. Училась в художественной школе, участвовала в выставках и конкурсах. "
            "Вела мастер-классы для детей, сейчас работаю над анимационным проектом.\n\n"
            "Мой стиль: смешанная техника, контраст жёсткой линии и мягкой тени. "
            "Люблю скетчи, учу лёгкости и смелости.\n\n"
            "Верю, что рисовать может каждый. И я здесь, чтобы помочь вам сделать первый шаг."
        ),
        "prices": (
            "💰 Прайс-лист:\n\n"
            "🎁 Пробный урок — бесплатно (20-30 мин).\n"
            "⚡ Разовое занятие — 10€ (50 мин).\n"
            "📦 Абонемент на 4 занятия — 36€ (9€/урок).\n"
            "📦 Абонемент на 8 занятий — 64€ (8€/урок).\n"
            "📦 Абонемент на 12 занятий — 90€ (7.5€/урок).\n\n"
            "Материалы включены в стоимость."
        )
    }
    await callback.message.edit_text(texts[callback.data], reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "enroll")
async def start_enroll(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Сначала пройдите анкету! (нажмите /start)")
        return
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎁 Пробный урок (бесплатно)", callback_data="enroll_course_trial"))
    builder.row(InlineKeyboardButton(text="⚡ Разовое занятие", callback_data="enroll_course_single"))
    builder.row(InlineKeyboardButton(text="📦 Абонемент на курс", callback_data="enroll_course_subscription"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await state.set_state(BookingState.waiting_for_lesson_type)
    await callback.message.edit_text(
        "Выберите удобный формат:\nЯ помогу подобрать подходящий вариант, и мы обо всём договоримся.",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("enroll_course_"))
async def enroll_format_chosen(callback: types.CallbackQuery, state: FSMContext):
    format_type = callback.data.split("_")[2]  # trial, single, subscription
    await state.update_data(format_type=format_type)
    if format_type == "subscription":
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="4 занятия (36€)", callback_data="sub_qty_4"))
        builder.row(InlineKeyboardButton(text="8 занятий (64€)", callback_data="sub_qty_8"))
        builder.row(InlineKeyboardButton(text="12 занятий (90€)", callback_data="sub_qty_12"))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
        await state.set_state(BookingState.waiting_for_subscription_qty)
        await callback.message.edit_text("Выберите количество занятий:", reply_markup=builder.as_markup())
    else:
        # Для пробного или разового — сразу к выбору даты
        await state.update_data(course="Скетчинг")  # Можно позже дать выбор курса, пока упростим
        await show_date_selection(callback, state)
    await callback.answer()

async def show_date_selection(callback, state):
    builder = InlineKeyboardBuilder()
    days = ["Понедельник", "Среда", "Пятница", "Суббота"]
    times = ["17:00", "18:00", "19:00", "20:00", "21:00"]
    for day in days:
        for t in times:
            builder.row(InlineKeyboardButton(text=f"{day} {t}", callback_data=f"date_{day}_{t}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await state.set_state(BookingState.waiting_for_date)
    await callback.message.edit_text("Выберите удобные день и время:", reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data.startswith("sub_qty_"))
async def subscription_qty_chosen(callback: types.CallbackQuery, state: FSMContext):
    qty = int(callback.data.split("_")[2])
    prices = {4: 36, 8: 64, 12: 90}
    total = prices.get(qty, 0)
    await state.update_data(subscription_qty=qty, total_price=total, course="Абонемент")
    await show_date_selection(callback, state)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("date_"))
async def date_chosen(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    day = parts[1]
    time = parts[2] if len(parts) > 2 else ""
    date_info = f"{day} {time}"
    await state.update_data(date=date_info)
    data = await state.get_data()
    format_type = data.get("format_type", "trial")
    if format_type == "trial":
        price_text = "бесплатно"
        total = 0
    elif format_type == "single":
        price_text = "10€"
        total = 10
    else:
        qty = data.get("subscription_qty", 4)
        prices = {4: 36, 8: 64, 12: 90}
        total = prices.get(qty, 0)
        price_text = f"{total}€"
    await state.update_data(total_price=total)
    text = f"Подтвердите запись:\nФормат: {format_type}\nДата: {date_info}\nСтоимость: {price_text}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_pay"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await state.set_state(BookingState.waiting_for_payment)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "confirm_pay", BookingState.waiting_for_payment)
async def confirm_payment(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    await save_booking(user_id, data.get("course", "Скетчинг"), data.get("format_type", "trial"), data["date"], "confirmed")
    await state.clear()
    await callback.message.edit_text("✅ Запись подтверждена! Ждите напоминания за день до занятия.")
    admin_text = (
        f"📝 Новая запись!\n"
        f"Ученик: {user_id}\n"
        f"Формат: {data.get('format_type', 'trial')}\n"
        f"Курс: {data.get('course', 'не указан')}\n"
        f"Дата: {data['date']}\n"
        f"Стоимость: {data.get('total_price', 0)}€"
    )
    await bot.send_message(ADMIN_ID, admin_text)
    await callback.answer()

# --- AI-Обработчик ---
@dp.message()
async def ai_chat_handler(message: types.Message, state: FSMContext = None):
    user_id = message.from_user.id
    user_data = await get_user(user_id)
    if message.text and message.text.startswith('/'):
        return
    if not user_data:
        await message.answer("Чтобы я мог вам помочь, сначала расскажите о себе. Нажмите /start")
        return

    await bot.send_chat_action(user_id, action="typing")
# Временно сбрасываем историю, чтобы язык мог переключиться (для теста)
# user_dialogs.pop(user_id, None)
    if user_id not in user_dialogs:
        user_dialogs[user_id] = []
    user_dialogs[user_id].append({"role": "user", "content": message.text})

    ai_response = await get_ai_response(message.text, user_data, user_dialogs[user_id])

    if ai_response:
        # Если пользователь ещё не поприветствован — добавляем приглашение к диалогу
        if user_id not in welcomed_users:
            ai_response += "\n\n💬 Вы можете задать мне любой вопрос или просто описать, что вам интересно — я слушаю."
            welcomed_users.add(user_id)

        user_dialogs[user_id].append({"role": "assistant", "content": ai_response})
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main"))
        await message.answer(ai_response, reply_markup=builder.as_markup())
    else:
        await message.answer("Извините, у меня небольшие технические трудности. Попробуйте позже.")
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())