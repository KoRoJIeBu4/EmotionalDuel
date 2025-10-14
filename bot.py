import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, DATABASE_URL
from handlers import start, duel, stats
from modules.database.database import Database

async def main():
    # инициализируем БД
    db = Database(DATABASE_URL)
    db.migrate()  # создаёт таблицы, если их ещё нет

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # регистрируем роутеры
    dp.include_router(start.router)
    dp.include_router(duel.router)
    dp.include_router(stats.router)

    print("✅ Бот запущен. Ожидание сообщений...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())