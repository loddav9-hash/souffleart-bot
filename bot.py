import sys, io, os, asyncio, logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = 1979681125

from database import init_db, save_user, get_user, save_booking
from locales import LOCALES, LANGUAGE_NAMES

logging.basicConfig(level=logging.INFO)

# Фейковый HTTP-сервер для Render (чтобы не ругался на отсутствие порта)
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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

def get_text(lang: str, key: str, **kwargs) -> str:
    try:
        text = LOCALES[lang][key]
    except KeyError:
        text = LOCALES["ru"][key]
    return text.format(**kwargs) if kwargs else text

# --- FSM для анкеты и записи ---
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
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_payment = State()

# --- Главное меню ---
def get_main_menu_keyboard(lang: str = "ru"):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_text(lang, "course_btn"), callback_data="courses"))
    builder.row(InlineKeyboardButton(text=get_text(lang, "enroll_btn"), callback_data="enroll"))
    builder.row(InlineKeyboardButton(text=get_text(lang, "portfolio_btn"), callback_data="portfolio"))
    builder.row(InlineKeyboardButton(text=get_text(lang, "about_btn"), callback_data="about"))
    builder.row(InlineKeyboardButton(text=get_text(lang, "prices_btn"), callback_data="prices"))
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await get_user(user_id)
    if not user_data:
        # Запускаем анкету
        await message.answer("🎨 Привет! Давай познакомимся. Как тебя зовут?")
        await state.set_state(EnrollState.waiting_for_name)
    else:
        await message.answer(
            get_text("ru", "start", name=user_data["name"]),
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
    builder.row(
        InlineKeyboardButton(text="Новичок", callback_data="skill_beginner"),
        InlineKeyboardButton(text="Небольшой опыт", callback_data="skill_intermediate"),
        InlineKeyboardButton(text="Рисую уверенно", callback_data="skill_advanced")
    )
    await message.answer("Какой у тебя уровень рисования?", reply_markup=builder.as_markup())
    await state.set_state(EnrollState.waiting_for_skill)

@dp.callback_query(lambda c: c.data == "enroll")
async def start_enroll(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Сначала пройдите анкету! (нажмите /start)")
        return
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Академический рисунок", callback_data="enroll_course_academic"))
    builder.row(InlineKeyboardButton(text="Скетчинг", callback_data="enroll_course_sketching"))
    builder.row(InlineKeyboardButton(text="Свободная тема", callback_data="enroll_course_free"))
    builder.row(InlineKeyboardButton(text=get_text("ru", "back_btn"), callback_data="back_to_main"))
    await state.set_state(BookingState.waiting_for_course)
    await callback.message.edit_text("Выберите курс:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("enroll_course_"))
async def enroll_course_chosen(callback: types.CallbackQuery, state: FSMContext):
    course = callback.data.split("_")[2]
    await state.update_data(course=course)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Пробное занятие", callback_data="lesson_trial"))
    builder.row(InlineKeyboardButton(text="Разовое занятие", callback_data="lesson_single"))
    builder.row(InlineKeyboardButton(text="Абонемент на 4 занятия", callback_data="lesson_4"))
    builder.row(InlineKeyboardButton(text="Абонемент на 8 занятий", callback_data="lesson_8"))
    builder.row(InlineKeyboardButton(text="Абонемент на 12 занятий", callback_data="lesson_12"))
    builder.row(InlineKeyboardButton(text=get_text("ru", "back_btn"), callback_data="back_to_main"))
    await state.set_state(BookingState.waiting_for_lesson_type)
    await callback.message.edit_text("Выберите тип занятия:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("lesson_"))
async def lesson_type_chosen(callback: types.CallbackQuery, state: FSMContext):
    lesson_type = callback.data.split("_")[1]
    await state.update_data(lesson_type=lesson_type)
    # Список доступных дат (пока заглушка)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Понедельник 15:00", callback_data="date_monday_15"))
    builder.row(InlineKeyboardButton(text="Понедельник 17:00", callback_data="date_monday_17"))
    builder.row(InlineKeyboardButton(text="Среда 15:00", callback_data="date_wednesday_15"))
    builder.row(InlineKeyboardButton(text="Среда 17:00", callback_data="date_wednesday_17"))
    builder.row(InlineKeyboardButton(text=get_text("ru", "back_btn"), callback_data="back_to_main"))
    await state.set_state(BookingState.waiting_for_date)
    await callback.message.edit_text("Выберите дату и время:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("date_"))
async def date_chosen(callback: types.CallbackQuery, state: FSMContext):
    date_info = callback.data.split("_")[1] + " " + callback.data.split("_")[2]
    await state.update_data(date=date_info)
    data = await state.get_data()
    text = f"Подтвердите запись:\nКурс: {data['course']}\nТип: {data['lesson_type']}\nДата: {date_info}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Оплатить", callback_data="confirm_pay"))
    builder.row(InlineKeyboardButton(text=get_text("ru", "back_btn"), callback_data="back_to_main"))
    await state.set_state(BookingState.waiting_for_payment)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "confirm_pay", BookingState.waiting_for_payment)
async def confirm_payment(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    await save_booking(user_id, data['course'], data['lesson_type'], data['date'], "time_placeholder")
    await state.clear()
    await callback.message.edit_text("✅ Запись подтверждена! (Оплата получена условно)")
    # Отправка админу
    admin_text = f"Новая запись!\nУченик: {user_id}\nКурс: {data['course']}\nТип: {data['lesson_type']}\nДата: {data['date']}"
    await bot.send_message(ADMIN_ID, admin_text)
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

# --- Заглушки для кнопок меню ---
@dp.callback_query(lambda c: c.data == "courses")
async def show_courses(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_text("ru", "academic_drawing"), callback_data="course_academic"))
    builder.row(InlineKeyboardButton(text=get_text("ru", "sketching"), callback_data="course_sketching"))
    builder.row(InlineKeyboardButton(text=get_text("ru", "free_theme"), callback_data="course_free"))
    builder.row(InlineKeyboardButton(text=get_text("ru", "back_btn"), callback_data="back_to_main"))
    await callback.message.edit_text("📚 Наши курсы:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("course_"))
async def course_info(callback: types.CallbackQuery):
    # Заглушка, потом добавим описание
    course = callback.data.split("_")[1]
    await callback.answer(f"Информация о курсе {course} появится позже.")
    await callback.message.edit_text(f"Вы выбрали курс: {course}. Запись на него пока в разработке.",
                                     reply_markup=get_main_menu_keyboard())

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["portfolio", "about", "prices"])
async def info_pages(callback: types.CallbackQuery):
    texts = {
        "portfolio": "🖼 Здесь будут наши работы.",
        "about": "👩‍🎨 О студии SouffleArt...",
        "prices": "💰 Прайс-лист появится скоро."
    }
    await callback.message.edit_text(texts[callback.data], reply_markup=get_main_menu_keyboard())
    await callback.answer()

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())