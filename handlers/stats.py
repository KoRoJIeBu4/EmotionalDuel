from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from modules.database.database import Database, LeaderboardRow
from config import DATABASE_URL

router = Router()
db = Database(DATABASE_URL)


def get_main_menu_keyboard():
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


@router.callback_query(F.data == "leaderboard")
async def show_leaderboard(call: types.CallbackQuery):
    """
    Показать топ-10 игроков.
    """
    await call.answer()  # снимаем подсветку кнопки

    top: list[LeaderboardRow] = db.get_leaderboard_top(limit=10)
    if not top:
        await call.message.answer("🏆 Лидерборд пуст — ещё не было игр.")
    else:
        lines = ["🏆 Лидерборд (топ 10):", ""]
        for i, row in enumerate(top, start=1):
            win_rate_pct = f"{row.winrate*100:.0f}%"
            lines.append(
                f"{i}. 👤 {row.user_id} — Побед: {row.wins}, Игр: {row.games}, WinRate: {win_rate_pct}"
            )
        await call.message.answer("\n".join(lines))

    # выводим главное меню снова
    kb = get_main_menu_keyboard()
    await call.message.answer("Выбирай действие:", reply_markup=kb)


@router.callback_query(F.data == "my_stats")
async def my_stats(call: types.CallbackQuery):
    """
    Показать базовую статистику пользователя (последние игры).
    """
    await call.answer()  # снимаем подсветку кнопки

    user_id = call.from_user.id
    history = db.get_user_history(user_id=user_id, limit=10)
    if not history:
        await call.message.answer("📊 У тебя ещё нет сыгранных дуэлей.")
    else:
        lines = ["📊 Твои последние игры:"]
        for d in history:
            if d.winner_user_id is None:
                result = "Ничья 🤝"
            elif d.winner_user_id == user_id:
                result = "Победа 🏆"
            else:
                result = "Поражение 🤦"
            lines.append(f"{d.created_at.date()} — {result} — {d.score_a:.3f}/{d.score_b:.3f}")
        await call.message.answer("\n".join(lines))

    # выводим главное меню снова
    kb = get_main_menu_keyboard()
    await call.message.answer("Выбирай действие:", reply_markup=kb)
