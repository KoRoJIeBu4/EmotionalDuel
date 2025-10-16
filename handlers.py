import os
from aiogram import Router, types, F
from aiogram.filters.command import Command
from aiogram.types import CallbackQuery, Message, InputFile, InputMediaPhoto
from modules.database.database import Database, LeaderboardRow
from config import UPLOADS_DIR, CLEANUP_UPLOADS_AFTER_EVALUATION, RANDOM_MATCH_TIMEOUT, DATABASE_URL
from modules.emotion_recognition_pipeline.duel_api import DuelML
from modules.emotion_recognition_pipeline.task_management import TaskManager
import keyboards as kb

router = Router()

ml = DuelML()
task_manager = TaskManager()
db = Database(DATABASE_URL)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """
    Приветствие и главное меню.
    """

    user = message.from_user
    # Сохраняем информацию о пользователе
    db.save_user(
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
    )

    # Проверяем и отменяем активную дуэль
    was_cancelled, cancelled_duel = db.cancel_duel_on_start(user.id)

    if was_cancelled and cancelled_duel:
        # Определяем ID оппонента
        opponent_id = cancelled_duel.user_a_id if cancelled_duel.user_a_id != user.id else cancelled_duel.user_b_id

        try:
            # Отправляем уведомление оппоненту
            opponent_name = db.get_user_name(opponent_id)
            await message.bot.send_message(
                opponent_id,
                f"⚠️ Дуэль была отменена вашим оппонентом {user.first_name}.",
                reply_markup=await kb.main_menu()
            )

            # Сообщение текущему пользователю
            await message.answer(
                f"🔴 Ваша предыдущая дуэль с {opponent_name} была отменена.\n\n"
                "👋 Привет! Я бот для дуэлей эмоций.\n\n"
                "Выбери действие:",
                reply_markup=await kb.main_menu()
            )

        except Exception as e:
            # Если не удалось отправить сообщение оппоненту (например, он заблокировал бота)
            print(f"[WARN] Не удалось уведомить оппонента {opponent_id}: {e}")
            await message.answer(
                f"🔴 Ваша предыдущая дуэль была отменена.\n\n"
                "👋 Привет! Я бот для дуэлей эмоций.\n\n"
                "Выбери действие:",
                reply_markup=await kb.main_menu()
            )
    else:
        # Если активной дуэли не было
        await message.answer(
            "👋 Привет! Я бот для дуэлей эмоций.\n\n"
            "Выбери действие:",
            reply_markup=await kb.main_menu()
        )


@router.callback_query(F.data == "exit_queue")
async def on_exit_queue(call: CallbackQuery):
    await call.answer()  # снимаем подсветку

    user_id = call.from_user.id

    # Сначала проверяем и отменяем активную дуэль (аналогично start)
    was_cancelled, cancelled_duel = db.cancel_duel_on_start(user_id)

    # Затем выходим из очереди
    db.leave_queue(user_id)

    if was_cancelled and cancelled_duel:
        # Определяем ID оппонента
        opponent_id = cancelled_duel.user_a_id if cancelled_duel.user_a_id != user_id else cancelled_duel.user_b_id

        try:
            # Отправляем уведомление оппоненту
            opponent_name = db.get_user_name(opponent_id)
            await call.bot.send_message(
                opponent_id,
                f"⚠️ Ваш оппонент {call.from_user.first_name} вышел из дуэли.\n\n"
                "Выбирай действие:",
                reply_markup=await kb.main_menu()
            )

            # Сообщение текущему пользователю
            await call.message.answer(
                f"🔴 Вы вышли из дуэли с {opponent_name}.\n\n"
                "Выбирай действие:",
                reply_markup=await kb.main_menu()
            )

        except Exception as e:
            # Если не удалось отправить сообщение оппоненту
            print(f"[WARN] Не удалось уведомить оппонента {opponent_id}: {e}")
            await call.message.answer(
                "🔴 Вы вышли из дуэли (не удалось уведомить оппонента).\n\n"
                "Выбирай действие:",
                reply_markup=await kb.main_menu()
            )
    else:
        # Если активной дуэли не было, просто выходим из очереди
        await call.message.answer(
            "Выбирай действие:",
            reply_markup=await kb.main_menu()
        )

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
                f"{i}. 👤 {row.user_name} — Побед: {row.wins}, Игр: {row.games}, Винрейт: {win_rate_pct}"
            )
        await call.message.answer("\n".join(lines))

    # выводим главное меню снова
    await call.message.answer("Выбирай действие:", reply_markup=await kb.main_menu())


@router.callback_query(F.data == "my_stats")
async def my_stats(call: types.CallbackQuery):
    """
    Показать последние игры пользователя.
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
            lines.append(f"{d.created_at.date()} — {result} — {(d.score_a + 1) * 50:.3f}% / {(d.score_b + 1) * 50:.3f}%")
        await call.message.answer("\n".join(lines))

    # выводим главное меню снова
    await call.message.answer("Выбирай действие:", reply_markup=await kb.main_menu())

# --- КНОПКИ --- #
@router.callback_query(F.data == "create_room")
async def on_create_room(call: CallbackQuery):
    await call.answer()  # снимаем подсветку

    # Проверяем текущее состояние
    state = db.is_user_in_queue(call.from_user.id)
    if state:
        await call.message.answer(
            "⚠️ Вы уже в очереди на игру. Можете выйти нажав кнопку ниже", reply_markup=await kb.exit_queue())
        return

    code = db.create_room(call.from_user.id)

    await call.message.answer(
        f"🏠 Комната создана!\nКод: <code>{code}</code>\n"
        f"Отправь этот код другу, чтобы он подключился.",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "join_room")
async def on_join_room_request(call: CallbackQuery):
    await call.answer()  # снимаем подсветку

    # Проверяем текущее состояние
    state = db.is_user_in_queue(call.from_user.id)
    if state:
        await call.message.answer(
            "⚠️ Вы уже в очереди на игру. Можете выйти нажав кнопку ниже", reply_markup=await kb.exit_queue())
        return

    await call.message.answer("🔢 Введи код комнаты (4 цифры)")


@router.callback_query(F.data == "find_random")
async def on_find_random(call: CallbackQuery):
    await call.answer()  # снимаем подсветку

    user_id = call.from_user.id

    # Проверяем текущее состояние
    state = db.is_user_in_queue(call.from_user.id)
    if state:
        await call.message.answer(
            "⚠️ Вы уже в очереди на игру. Можете выйти нажав кнопку ниже", reply_markup=await kb.exit_queue())
        return

    db.join_queue(call.from_user.id)

    opponent = db.find_opponent(user_id=user_id)
    if opponent is None:
        # пользователь поставлен в очередь — ждём
        await call.message.answer("🔍 Поиск соперника... ожидай!", reply_markup=await kb.exit_queue())
    else:
        # найден оппонент — создаём комнату для пары
        duel = db.create_duel_from_queue(user_id=user_id, opponent_user_id=opponent.user_id)
        print(f"случайный бой {call.from_user.id} c {opponent.user_id}")

        await call.message.answer(f"🎯 Соперник найден!\nЗадание: <b>{duel.task_text}</b>\nОтправь фото.", parse_mode="HTML")
        # отправляем собщение сопернику (его чат_id == opponent.user_id)
        await call.bot.send_message(opponent.user_id, f"🎯 Соперник найден!\nЗадание: <b>{duel.task_text}</b>\nОтправь фото.", parse_mode="HTML")


@router.message(F.text.regexp(r"^\d{4}$"))
async def on_code_text(message: Message):
    # Проверяем текущее состояние
    state = db.is_user_in_queue(message.from_user.id)
    if state:
        await message.answer(
            "⚠️ Вы уже в очереди на игру. Можете выйти нажав кнопку ниже", reply_markup=await kb.exit_queue())
        return
    else:
        db.join_queue(user_id=message.from_user.id, room_code=int(message.text))
        opponent = db.find_opponent(user_id=message.from_user.id)
        if opponent is None:
            await message.answer("❌ Комната не найдена.")
            db.leave_queue(message.from_user.id)
        else:
            # найден оппонент — создаём комнату для пары
            duel = db.create_duel_from_queue(user_id=message.from_user.id, opponent_user_id=opponent.user_id)

            await message.answer(f"✅ Подключился к комнате {int(message.text)}.\nЗадание: <b>{duel.task_text}</b>\nОтправь селфи.", parse_mode="HTML")
            await message.bot.send_message(opponent.user_id, f"🎮 Игрок подключился!\nЗадание: <b>{duel.task_text}</b>\nОтправь селфи.", parse_mode="HTML")

# --- Фото --- #
@router.message(F.photo)
async def on_photo_received(message: Message):
    """
    Обработка полученного фото
    """
    duel = db.get_active_duel_for_user(message.from_user.id)
    if duel is None:
        await message.answer(f"❌ Вы не в дуэли, не отправляйте фотографии просто так")
        return

    user_id = message.from_user.id
    bot = message.bot
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    file_path = os.path.join(UPLOADS_DIR, f"{user_id}.jpg")

    # скачиваем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    await bot.download_file(file.file_path, destination=file_path)
    print(f"[PHOTO] Получено фото от {user_id}, сохранено в {file_path}")

    if db.mark_duel_photo_received(duel.id, user_id):
        print(f"[DUEL] Оба фото получены, запускаем дуэль для игроков {duel.user_a_id} и {duel.user_b_id}")
        # Отправим медиагруппу с 2-мя фото каждому
        await send_duel_photos(duel, bot)

        # запускаем анализ и уведомления
        await run_duel(duel, bot)
    else:
        await message.answer("📷 Фото получено! Ожидаем соперника.")
        return

async def send_duel_photos(duel, bot):
    """
    Отправляет обоим игрокам сообщение (медиагруппу) с двумя фото:
    - для каждого пользователя: сначала его фото, затем фото соперника
    """

    # пути к файлам по user_id
    a_path = os.path.join(UPLOADS_DIR, f"{duel.user_a_id}.jpg")
    b_path = os.path.join(UPLOADS_DIR, f"{duel.user_b_id}.jpg")

    # Проверяем наличие файлов
    if not (os.path.exists(a_path) and os.path.exists(b_path)):
        # Если каких-то файлов нет, логируем и просто возращаем
        print(f"[WARN] Отсутствуют файлы для медиагруппы: {a_path} / {b_path}")
        return

    for user_id, self_path, opp_path in (
        (duel.user_a_id, a_path, b_path),
        (duel.user_b_id, b_path, a_path),
    ):
        try:
            media = [
                InputMediaPhoto(
                    media=types.BufferedInputFile.from_file(self_path),
                    caption="📸 Это ваше селфи"
                ),
                InputMediaPhoto(
                    media=types.BufferedInputFile.from_file(opp_path),
                    caption="🧑‍🤝‍🧑 Это селфи соперника"
                ),
            ]
            # send_media_group отправляет несколько фото в одном сообщении (альбом)
            await bot.send_media_group(chat_id=user_id, media=media)
        except Exception as e:
            print(f"[ERROR] Не удалось отправить медиагруппу пользователю {user_id}: {e}")

# --- Запуск дуэли --- #
async def run_duel(duel, bot):
    """
    Запускает ML-анализ и уведомляет игроков.
    """
    user_a = duel.user_a_id
    user_b = duel.user_b_id
    task_text = duel.task_text

    try:
        for user_id in (user_a, user_b):
            if not user_id:
                continue
            try:
                await bot.send_message(chat_id=user_id, text="🔎 Анализ эмоций...")
            except Exception as e:
                print(f"[ERROR] Не удалось отправить уведомление {user_id}: {e}")

        scores = ml.score_duel_by_user_ids(
            task_text=task_text,
            user_a_id=user_a,
            user_b_id=user_b,
            uploads_dir=UPLOADS_DIR,
            cleanup_after=CLEANUP_UPLOADS_AFTER_EVALUATION,
        )

        print(f"[ML] Duel result: A={scores.score_a}, B={scores.score_b}, winner={scores.winner}")

        # определяем победителя
        winner_user_id = None
        if scores.winner == "a":
            winner_user_id = user_a
        elif scores.winner == "b":
            winner_user_id = user_b

        # сохраняем в базу
        updated = db.update_duel_result(
            duel_id=duel.id,
            task_text=task_text,
            score_a=scores.score_a,
            score_b=scores.score_b,
        )
        print(f"[DB] Результат сохранён в БД: id={updated.id}")

        # Уведомляем пользователей о результате
        def format_text(is_winner, score_self, score_opp):
            if winner_user_id is None:
                return f"⚖️ Ничья!\n\nЭмоция: {task_text}\nТвой результат: {(score_self + 1) * 50:.3f}%\nСоперник: {(score_opp + 1) * 50:.3f}%"
            if is_winner:
                return f"🏆 Ты победил!\n\nЭмоция: {task_text}\nТвой результат: {(score_self + 1) * 50:.3f}%\nСоперник: {(score_opp + 1) * 50:.3f}%"
            else:
                return f"😞 Ты проиграл.\n\nЭмоция: {task_text}\nТвой результат: {(score_self + 1) * 50:.3f}%\nСоперник: {(score_opp + 1) * 50:.3f}%"

        try:
            await bot.send_message(user_a, format_text(winner_user_id == user_a, updated.score_a, updated.score_b))
            await bot.send_message(user_a, "🏁 Игра окончена! Выбирай, что делать дальше:", reply_markup=await kb.main_menu())
        except Exception as e:
            print(f"[ERROR] Не удалось отправить результат {user_a}: {e}")

        try:
            await bot.send_message(user_b, format_text(winner_user_id == user_b, updated.score_b, updated.score_a))
            await bot.send_message(user_b, "🏁 Игра окончена! Выбирай, что делать дальше:", reply_markup=await kb.main_menu())
        except Exception as e:
            print(f"[ERROR] Не удалось отправить результат {user_b}: {e}")

    except Exception as e:
        print(f"[ERROR] ошибка анализа: {e}")
        for user_id in (user_a, user_b):
            if not user_id:
                continue
            try:
                await bot.send_message(chat_id=user_id, text="❌ Ошибка при анализе")
            except Exception as e:
                print(f"[ERROR] Не удалось отправить уведомление {user_id}: {e}")
