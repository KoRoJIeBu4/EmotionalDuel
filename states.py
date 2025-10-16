from aiogram.fsm.state import StatesGroup, State

class UserStates(StatesGroup):
    """
    Состояния пользователя в боте:
    - Idle: обычное состояние, главное меню
    - SearchingRandom: пользователь ждет соперника в режиме "рандом"
    - CreatingRoom: пользователь нажал "создать комнату" (в момент создания кода)
    - JoiningRoom: пользователь ввел режим "ввод кода" — ждём 4 цифры
    - InRoom: пользователь находится в комнате и должен прислать фото
    - InDuel: запущена оценка/дуэль (чтобы не принимать лишние команды / фото)
    """
    Idle = State()
    SearchingRandom = State()
    CreatingRoom = State()
    JoiningRoom = State()
    InRoom = State()
    InDuel = State()
