from aiogram.utils.keyboard import InlineKeyboardBuilder

async def main_menu():
    """
    Возвращает клавиатуру главного меню.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Случайный соперник", callback_data="find_random")
    kb.button(text="🏠 Создать комнату", callback_data="create_room")
    kb.button(text="🔢 Подключиться по коду", callback_data="join_room")
    kb.button(text="📊 Моя статистика", callback_data="my_stats")
    kb.button(text="🏆 Лидерборд", callback_data="leaderboard")
    kb.adjust(1)
    return kb.as_markup()

async def exit_queue():
    """
    Возвращает клавиатуру главного меню.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Выйти из очереди", callback_data="exit_queue")
    kb.adjust(1)
    return kb.as_markup()
