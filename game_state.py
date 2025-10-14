from dataclasses import dataclass, field
from typing import Dict, Optional
import random
import time

@dataclass
class GameRoom:
    code: str
    host_id: int
    guest_id: Optional[int] = None
    task_text: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    # кто прислал фото: mapping user_id -> True/False
    photo_received: Dict[int, bool] = field(default_factory=dict)
    # можно хранить дополнительные поля при необходимости (например, hint image id)
    # отметка о том, что уже запущена оценка
    evaluation_started: bool = False

    def mark_photo(self, user_id: int):
        self.photo_received[user_id] = True

    def both_photos_received(self) -> bool:
        if self.host_id is None or self.guest_id is None:
            return False
        return bool(self.photo_received.get(self.host_id)) and bool(self.photo_received.get(self.guest_id))


class GameManager:
    def __init__(self):
        # код -> GameRoom
        self.rooms: Dict[str, GameRoom] = {}
        # Очередь ожидающих (режим "рандом"). Элементы: (user_id, timestamp)
        self.waiting_players: Dict[int, float] = {}

    def create_room(self, host_id: int) -> str:
        # создаём уникальный 4-значный код
        for _ in range(10):
            code = f"{random.randint(1000, 9999)}"
            if code not in self.rooms:
                room = GameRoom(code=code, host_id=host_id)
                self.rooms[code] = room
                return code
        # в редком случае — генерация через host_id
        code = f"{host_id % 10000:04d}"
        self.rooms[code] = GameRoom(code=code, host_id=host_id)
        return code

    def join_room_by_code(self, code: str, user_id: int) -> Optional[GameRoom]:
        room = self.rooms.get(code)
        if not room:
            return None
        if room.guest_id is not None:
            return None
        room.guest_id = user_id
        # инициализируем состояния фото
        room.photo_received = {room.host_id: False, room.guest_id: False}
        return room

    def find_or_enqueue_for_random(self, user_id: int, timeout_seconds: int):
        """
        Если есть ожидающий игрок — возвращает его user_id и удаляет из очереди.
        Иначе — добавляет текущего игрока в очередь и возвращает None.
        """
        # очищаем просроченные
        now = time.time()
        expired = [uid for uid, ts in self.waiting_players.items() if now - ts > timeout_seconds]
        for uid in expired:
            del self.waiting_players[uid]

        # ищем любого ожидающего, кроме самого юзера
        for uid in list(self.waiting_players.keys()):
            if uid != user_id:
                # удаляем найденного из очереди и возвращаем его
                del self.waiting_players[uid]
                return uid

        # не найден — ставим в очередь
        self.waiting_players[user_id] = now
        return None

    def create_room_for_pair(self, host_id: int, guest_id: int) -> GameRoom:
        # создаём "временную" комнату с кодом r{min}{max}
        code = f"r{min(host_id, guest_id)}_{max(host_id, guest_id)}"
        room = GameRoom(code=code, host_id=host_id, guest_id=guest_id)
        room.photo_received = {host_id: False, guest_id: False}
        self.rooms[code] = room
        return room

    def find_room_by_user(self, user_id: int) -> Optional[GameRoom]:
        # найти комнату, где user участвует и оценка ещё не началась
        for room in self.rooms.values():
            if (room.host_id == user_id or room.guest_id == user_id) and not room.evaluation_started:
                return room
        return None

    def remove_room(self, code: str):
        self.rooms.pop(code, None)


# один глобальный менеджер
game_manager = GameManager()
