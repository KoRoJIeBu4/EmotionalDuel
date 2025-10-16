import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, DATABASE_URL
import handlers
from modules.database.database import Database

async def main():
    # инициализируем БД
    db = Database(DATABASE_URL)
    db.migrate()  # создаёт таблицы, если их ещё нет
    #db.migrate(drop_existing=True)  # Пересоздаст все таблицы
    db.cleanup_duplicate_queues()
    db.cleanup_duplicate_duels()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # регистрируем роутер
    dp.include_router(handlers.router)

    print("Бот запущен. Ожидание сообщений...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Бот оффнут')