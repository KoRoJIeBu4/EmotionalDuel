from aiogram import Router, types
from aiogram.filters.command import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """
    Приветствие и главное меню.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Случайный соперник", callback_data="find_random")
    kb.button(text="🏠 Создать комнату", callback_data="create_room")
    kb.button(text="🔢 Подключиться по коду", callback_data="join_room")
    kb.button(text="📊 Моя статистика", callback_data="my_stats")
    kb.button(text="🏆 Лидерборд", callback_data="leaderboard")
    kb.adjust(1)

    await message.answer(
        "👋 Привет! Я бот для дуэлей эмоций.\n\n"
        "Выбери действие:",
        reply_markup=kb.as_markup()
    )