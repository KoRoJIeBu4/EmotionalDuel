import os
import traceback
from aiogram import Router, types, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import UPLOADS_DIR, CLEANUP_UPLOADS_AFTER_EVALUATION, RANDOM_MATCH_TIMEOUT, DATABASE_URL
from game_state import game_manager
from modules.emotion_recognition_pipeline.duel_api import DuelML
from modules.emotion_recognition_pipeline.task_management import TaskManager
from modules.database.database import Database

router = Router()

ml = DuelML()
task_manager = TaskManager()
db = Database(DATABASE_URL)

os.makedirs(UPLOADS_DIR, exist_ok=True)

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

# --- КНОПКИ --- #
@router.callback_query(F.data == "create_room")
async def on_create_room(call: CallbackQuery):
    await call.answer()  # снимаем подсветку

    code = game_manager.create_room(call.from_user.id)
    await call.message.answer(
        f"🏠 Комната создана!\nКод: <code>{code}</code>\n"
        f"Отправь этот код другу, чтобы он подключился.",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "join_room")
async def on_join_room_request(call: CallbackQuery):
    await call.answer()  # снимаем подсветку

    await call.message.answer("🔢 Введи код комнаты (4 цифры).")


@router.callback_query(F.data == "find_random")
async def on_find_random(call: CallbackQuery):
    await call.answer()  # снимаем подсветку

    user_id = call.from_user.id
    opponent = game_manager.find_or_enqueue_for_random(user_id, timeout_seconds=RANDOM_MATCH_TIMEOUT)
    if opponent is None:
        await call.message.answer("🔍 Поиск соперника... ожидай!")
    else:
        room = game_manager.create_room_for_pair(host_id=user_id, guest_id=opponent)
        category, task_text, hint = task_manager.get_random_task()
        room.task_text = task_text
        await call.message.answer(f"🎯 Соперник найден!\nЗадание: <b>{task_text}</b>\nОтправь фото.", parse_mode="HTML")
        await call.bot.send_message(opponent, f"🎯 Соперник найден!\nЗадание: <b>{task_text}</b>\nОтправь фото.", parse_mode="HTML")


# --- Ввод кода --- #
@router.message(F.text.regexp(r"^\d{4}$"))
async def on_code_text(message: Message):
    code = message.text.strip()
    room = game_manager.join_room_by_code(code, message.from_user.id)
    if not room:
        await message.answer("❌ Комната не найдена.")
        return

    category, task_text, hint = task_manager.get_random_task()
    room.task_text = task_text
    await message.answer(f"✅ Подключился к комнате {code}.\nЗадание: <b>{task_text}</b>\nОтправь селфи.", parse_mode="HTML")
    await message.bot.send_message(room.host_id, f"🎮 Игрок подключился!\nЗадание: <b>{task_text}</b>\nОтправь селфи.", parse_mode="HTML")


# --- Фото --- #
@router.message(F.photo)
async def on_photo_received(message: Message):
    user_id = message.from_user.id
    bot = message.bot
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    file_path = os.path.join(UPLOADS_DIR, f"{user_id}.jpg")

    # скачиваем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    await bot.download_file(file.file_path, destination=file_path)
    print(f"[PHOTO] Получено фото от {user_id}, сохранено в {file_path}")

    await message.answer("📷 Фото получено! Ожидаем соперника...")

    room = game_manager.find_room_by_user(user_id)
    if not room:
        await message.answer("ℹ️ Ты не в активной комнате.")
        return

    room.mark_photo(user_id)
    print(f"[ROOM] {user_id} отметил фото. Room state: {room.photo_received}")

    if room.both_photos_received() and not room.evaluation_started:
        room.evaluation_started = True
        print(f"[DUEL] Оба фото получены, запускаем дуэль для комнаты {room.code}")
        await run_duel_and_notify(room, bot)


# --- Запуск дуэли --- #
async def run_duel_and_notify(room, bot):
    host = room.host_id
    guest = room.guest_id
    task_text = room.task_text or "neutral"

    try:
        await notify_users(bot, room, "🔎 Анализ эмоций...")

        scores = ml.score_duel_by_user_ids(
            task_text=task_text,
            user_a_id=host,
            user_b_id=guest,
            uploads_dir=UPLOADS_DIR,
            cleanup_after=CLEANUP_UPLOADS_AFTER_EVALUATION,
        )

        print(f"[ML] Duel result: A={scores.score_a}, B={scores.score_b}, winner={scores.winner}")

        # определяем победителя
        winner_user_id = None
        if scores.winner == "a":
            winner_user_id = host
        elif scores.winner == "b":
            winner_user_id = guest

        # сохраняем в базу
        db.save_duel(
            user_a_id=host,
            user_b_id=guest,
            task_text=task_text,
            score_a=scores.score_a,
            score_b=scores.score_b,
        )
        print(f"[DB] Результат сохранён в БД")

        # уведомляем игроков
        try:
            main_menu = get_main_menu_keyboard()  # если такая функция есть в файле
        except Exception as e:
            traceback.print_exc()
            main_menu = None

        await room_notify_result(bot, room, host, guest, scores.score_a, scores.score_b, winner_user_id, task_text,
                                 main_menu_markup=main_menu)

    except Exception as e:
        traceback.print_exc()
        await notify_users(bot, room, f"❌ Ошибка при анализе: {e}")
    finally:
        game_manager.remove_room(room.code)
        print(f"[ROOM] Удалена комната {room.code}")


# --- Уведомления --- #
async def notify_users(bot, room, text: str):
    for uid in (room.host_id, room.guest_id):
        if not uid:
            continue
        try:
            await bot.send_message(chat_id=uid, text=text)
        except Exception as e:
            print(f"[ERROR] Не удалось отправить уведомление {uid}: {e}")


async def room_notify_result(bot, room, host, guest, score_a, score_b, winner_user_id, task_text, main_menu_markup=None):
    """
    Отправим персонализованные результаты обоим игрокам.
    Если передан main_menu_markup — отправим отдельное сообщение с этим меню.
    """
    def format_text(is_winner, score_self, score_opp):
        if winner_user_id is None:
            return f"⚖️ Ничья!\n\nЭмоция: {task_text}\nТвой результат: {score_self:.3f}\nСоперник: {score_opp:.3f}"
        if is_winner:
            return f"🏆 Ты победил!\n\nЭмоция: {task_text}\nТвой результат: {score_self:.3f}\nСоперник: {score_opp:.3f}"
        else:
            return f"😞 Ты проиграл.\n\nЭмоция: {task_text}\nТвой результат: {score_self:.3f}\nСоперник: {score_opp:.3f}"

    try:
        await bot.send_message(host, format_text(winner_user_id == host, score_a, score_b))
    except Exception as e:
        print(f"[ERROR] Не удалось отправить результат хосту {host}: {e}")

    try:
        await bot.send_message(guest, format_text(winner_user_id == guest, score_b, score_a))
    except Exception as e:
        print(f"[ERROR] Не удалось отправить результат гостю {guest}: {e}")

    # Отправляем главное меню (если передано)
    if main_menu_markup is not None:
        try:
            await bot.send_message(host, "🏁 Игра окончена! Выбирай, что делать дальше:", reply_markup=main_menu_markup)
        except Exception as e:
            print(f"[ERROR] Не удалось отправить клавиатуру хосту: {e}")
        try:
            await bot.send_message(guest, "🏁 Игра окончена! Выбирай, что делать дальше:", reply_markup=main_menu_markup)
        except Exception as e:
            print(f"[ERROR] Не удалось отправить клавиатуру гостю: {e}")