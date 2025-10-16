import os
import traceback
from aiogram import Router, types, F
from aiogram.types import CallbackQuery, Message, InputFile, InputMediaPhoto
from aiogram.fsm.context import FSMContext
import keyboards as kb
from config import UPLOADS_DIR, CLEANUP_UPLOADS_AFTER_EVALUATION, RANDOM_MATCH_TIMEOUT, DATABASE_URL
from game_state import game_manager
from modules.emotion_recognition_pipeline.duel_api import DuelML
from modules.emotion_recognition_pipeline.task_management import TaskManager
from modules.database.database import Database

from states import UserStates  # наши состояния

router = Router()

ml = DuelML()
task_manager = TaskManager()
db = Database(DATABASE_URL)

os.makedirs(UPLOADS_DIR, exist_ok=True)

async def set_user_state(state_storage, user_id: int, new_state):
    """
    Устанавливает состояние для пользователя
    """
    try:
        await state_storage.set_state(key=user_id, state=new_state)
    except Exception as e:
        print(f"[WARN] Не удалось выставить состояние для пользователя {user_id}: {e}")

async def get_user_state(state_storage, user_id: int):
    """
    Получает состояние пользователя
    """
    try:
        return await state_storage.get_state(key=user_id)
    except Exception as e:
        print(f"[WARN] Не удалось получить состояние пользователя {user_id}: {e}")

# ---------------------------
# ХЕЛПЕР: отправка 2-х фото
# ---------------------------
async def send_duel_photos(bot, room):
    """
    Отправляет обоим игрокам сообщение (медиагруппу) с двумя фото:
    - для каждого пользователя: сначала его фото, затем фото соперника
    """
    host = room.host_id
    guest = room.guest_id
    if not host or not guest:
        return

    # пути к файлам по user_id
    host_path = os.path.join(UPLOADS_DIR, f"{host}.jpg")
    guest_path = os.path.join(UPLOADS_DIR, f"{guest}.jpg")

    # Проверяем наличие файлов
    if not (os.path.exists(host_path) and os.path.exists(guest_path)):
        # Если каких-то файлов нет, логируем и просто возращаем
        print(f"[WARN] Отсутствуют файлы для медиагруппы: {host_path} / {guest_path}")
        return

    for user_self, user_opp, self_path, opp_path in (
        (host, guest, host_path, guest_path),
        (guest, host, guest_path, host_path),
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
            await bot.send_media_group(chat_id=user_self, media=media)
        except Exception as e:
            print(f"[ERROR] Не удалось отправить медиагруппу пользователю {user_self}: {e}")


# --- КНОПКИ --- #
@router.callback_query(F.data == "create_room")
async def on_create_room(call: CallbackQuery, state: FSMContext):
    await call.answer()  # снимаем подсветку

    # Проверяем текущее состояние — не разрешаем создавать комнату если пользователь в другом режиме
    cur = await state.get_state()
    if cur not in (None, UserStates.Idle.state):
        await call.message.answer("⚠️ Нельзя создать комнату в текущем режиме. Завершите предыдущую операцию или нажмите /start.")
        return

    # пометить, что пользователь создаёт комнату (кратковременное состояние)
    await state.set_state(UserStates.CreatingRoom)

    code = game_manager.create_room(call.from_user.id)

    # После создания — переводим в состояние InRoom (ожидание соперника и фото)
    await state.set_state(UserStates.InRoom)

    await call.message.answer(
        f"🏠 Комната создана!\nКод: <code>{code}</code>\n"
        f"Отправь этот код другу, чтобы он подключился.",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "join_room")
async def on_join_room_request(call: CallbackQuery, state: FSMContext):
    await call.answer()  # снимаем подсветку

    # Проверяем текущее состояние
    cur = await state.get_state()
    if cur not in (None, UserStates.Idle.state):
        await call.message.answer("⚠️ Нельзя подключаться по коду, пока вы в другом режиме. Завершите операцию или нажмите /start.")
        return

    # переводим пользователя в режим ввода кода
    await state.set_state(UserStates.JoiningRoom)
    await call.message.answer("🔢 Введи код комнаты (4 цифры).")


@router.callback_query(F.data == "find_random")
async def on_find_random(call: CallbackQuery, state: FSMContext):
    await call.answer()  # снимаем подсветку

    user_id = call.from_user.id

    # Проверяем текущее состояние
    cur = await state.get_state()
    if cur not in (None, UserStates.Idle.state):
        await call.message.answer("⚠️ Нельзя начать поиск соперника в текущем режиме. Сначала завершите текущее действие или нажмите /start.")
        return

    # ставим состояние поиска (чтобы другие команды не мешали)
    await state.set_state(UserStates.SearchingRandom)

    opponent = game_manager.find_or_enqueue_for_random(user_id, timeout_seconds=RANDOM_MATCH_TIMEOUT)
    if opponent is None:
        # пользователь поставлен в очередь — ждём
        await call.message.answer("🔍 Поиск соперника... ожидай!")
    else:
        # найден оппонент — создаём комнату для пары
        room = game_manager.create_room_for_pair(host_id=user_id, guest_id=opponent)

        # ставим состояниe InRoom для обоих участников:
        try:
            await set_user_state(state.storage, opponent, UserStates.InRoom)
            await set_user_state(state.storage, user_id, UserStates.InRoom)
        except Exception as e:
            # возможны варианты хранения, но это не критично — мы уже уведомили пользователя ниже
            print(f"[WARN] Не удалось выставить состояние для соперника {opponent}: {e}")

        # даём задание
        category, task_text, hint = task_manager.get_random_task()
        room.task_text = task_text

        await call.message.answer(f"🎯 Соперник найден!\nЗадание: <b>{task_text}</b>\nОтправь фото.", parse_mode="HTML")
        # отправляем собщение сопернику (его чат_id == opponent)
        await call.bot.send_message(opponent, f"🎯 Соперник найден!\nЗадание: <b>{task_text}</b>\nОтправь фото.", parse_mode="HTML")


# --- Ввод кода (только когда пользователь в состоянии JoiningRoom) --- #
@router.message(F.text.regexp(r"^\d{4}$"))
async def on_code_text(message: Message, state: FSMContext):
    # проверяем состояние — код принимаем только в состоянии JoiningRoom
    cur = await state.get_state()
    if cur != UserStates.JoiningRoom.state:
        # если пользователь просто ввёл 4 цифры вне режима — игнорируем/сообщаем
        await message.answer("ℹ️ Чтобы подключиться по коду, сначала выберите кнопку '🔢 Подключиться по коду'.")
        return

    code = message.text.strip()
    room = game_manager.join_room_by_code(code, message.from_user.id)
    if not room:
        await message.answer("❌ Комната не найдена.")
        await state.set_state(UserStates.Idle)
        return

    try:
        await set_user_state(state.storage, room.host_id, UserStates.InRoom)
    except Exception as e:
        print(f"[WARN] Не удалось выставить состояние для хоста {room.host_id}: {e}")

    category, task_text, hint = task_manager.get_random_task()
    room.task_text = task_text
    await message.answer(f"✅ Подключился к комнате {code}.\nЗадание: <b>{task_text}</b>\nОтправь селфи.", parse_mode="HTML")
    await message.bot.send_message(room.host_id, f"🎮 Игрок подключился!\nЗадание: <b>{task_text}</b>\nОтправь селфи.", parse_mode="HTML")


# --- Фото --- #
@router.message(F.photo)
async def on_photo_received(message: Message, state: FSMContext):
    """
    Обработка полученного фото
    """
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

    # Найдём комнату пользователя
    room = game_manager.find_room_by_user(user_id)
    if not room:
        await message.answer("ℹ️ Ты не в активной комнате.")
        await state.set_state(UserStates.Idle)
        return

    # Более гибкая проверка состояния
    current_state = await state.get_state()
    allowed_states = [UserStates.InRoom.state, UserStates.InDuel.state, UserStates.SearchingRandom.state]

    if current_state not in allowed_states:
        print(f"[WARN] Пользователь {user_id} отправил фото в неожиданном состоянии: {current_state}")

    room.mark_photo(user_id)
    print(f"[ROOM] {user_id} отметил фото. Room state: {room.photo_received}")

    # Если оба фото получены и оценка ещё не начата
    if room.both_photos_received() and not room.evaluation_started:
        room.evaluation_started = True
        print(f"[DUEL] Оба фото получены, запускаем дуэль для комнаты {room.code}")

        # перед запуском анализа: переводим обоих в состояние InDuel
        await state.set_state(UserStates.InDuel)
        await set_user_state(state.storage, room.host_id, UserStates.InDuel)
        await set_user_state(state.storage, room.guest_id, UserStates.InDuel)

        # Отправим медиагруппу с 2-мя фото каждому
        await send_duel_photos(bot, room)

        # запускаем анализ и уведомления
        await run_duel_and_notify(room, bot, state)


# --- Запуск дуэли --- #
async def run_duel_and_notify(room, bot, caller_state: FSMContext):
    """
    Запускает ML-анализ и уведомляет игроков.
    caller_state — FSMContext вызвавшего (нужен для доступа к storage & сброса состояний).
    """
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
        saved = db.save_duel(
            user_a_id=host,
            user_b_id=guest,
            task_text=task_text,
            score_a=scores.score_a,
            score_b=scores.score_b,
        )
        print(f"[DB] Результат сохранён в БД: id={saved.id}")

        await room_notify_result(bot, room, host, guest, scores.score_a, scores.score_b, winner_user_id, task_text,
                                 main_menu_markup=kb.main_menu)

    except Exception as e:
        traceback.print_exc()
        await notify_users(bot, room, f"❌ Ошибка при анализе: {e}")
    finally:
        # после окончания дуэли — сбрасываем состояния обоих игроков в Idle (None)
        try:
            await set_user_state(caller_state.storage, host, UserStates.Idle)
            await set_user_state(caller_state.storage, guest, UserStates.Idle)
        except Exception as e:
            print(f"[WARN] Не удалось сбросить состояния игроков после дуэли: {e}")

        # удаляем комнату
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
            return f"⚖️ Ничья!\n\nЭмоция: {task_text}\nТвой результат: {(score_self + 1) * 50:.3f}%\nСоперник: {(score_opp + 1) * 50:.3f}%"
        if is_winner:
            return f"🏆 Ты победил!\n\nЭмоция: {task_text}\nТвой результат: {(score_self + 1) * 50:.3f}%\nСоперник: {(score_opp + 1) * 50:.3f}%"
        else:
            return f"😞 Ты проиграл.\n\nЭмоция: {task_text}\nТвой результат: {(score_self + 1) * 50:.3f}%\nСоперник: {(score_opp + 1) * 50:.3f}%"

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
