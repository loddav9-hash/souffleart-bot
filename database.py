import aiosqlite
import logging

DB_PATH = "souffle.db"

async def init_db():
    """Создаёт таблицы, если их нет"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица пользователей (учеников)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                age INTEGER,
                skill TEXT,
                goals TEXT,
                language TEXT DEFAULT 'ru'
            )
        """)
        # Таблица записей на уроки
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                course TEXT,
                lesson_type TEXT,
                date TEXT,
                time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    logging.info("База данных SouffleArt инициализирована")

async def save_user(user_id: int, name: str, age: int, skill: str, goals: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, name, age, skill, goals) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET name=?, age=?, skill=?, goals=?
        """, (user_id, name, age, skill, goals, name, age, skill, goals))
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"user_id": row[0], "name": row[1], "age": row[2], "skill": row[3], "goals": row[4], "language": row[5]}
            return None

async def save_booking(user_id: int, course: str, lesson_type: str, date: str, time: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO bookings (user_id, course, lesson_type, date, time) VALUES (?, ?, ?, ?, ?)",
            (user_id, course, lesson_type, date, time)
        )
        await db.commit()