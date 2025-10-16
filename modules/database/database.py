from __future__ import annotations

import hashlib
from config import RANDOM_MATCH_TIMEOUT
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import secrets
from typing import Generator, Optional
import logging
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Integer,
    Text,
    Index,
    create_engine,
    func,
    select,
    union_all,
    or_,
    String,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger("database")

from modules.emotion_recognition_pipeline.task_management import TaskManager

task_manager = TaskManager()


# ============================
# ORM: база и модель таблицы
# ============================

class Base(DeclarativeBase):
    pass


class User(Base):
    """
    Таблица для хранения информации о пользователях
    """
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now(),
                                                 onupdate=func.now())


class Duel(Base):
    """
    Таблица дуэлей
    """
    __tablename__ = "duels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_a_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_b_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    room_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # NULL для случайных дуэлей
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    score_a: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_b: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    winner_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # NULL - ничья
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default='waiting_photos')  # waiting_photos, scoring, completed, cancelled
    photo_a_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    photo_b_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_duels_user_a_id", "user_a_id"),
        Index("ix_duels_user_b_id", "user_b_id"),
        Index("ix_duels_winner_user_id", "winner_user_id"),
        Index("ix_duels_status", "status"),
        Index("ix_duels_created_at", "created_at"),
        Index("ix_duels_room_code", "room_code"),
    )


class DuelQueue(Base):
    """
    Очередь пользователей, ожидающих дуэль
    """
    __tablename__ = "duel_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    room_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # NULL для случайных дуэлей
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default='waiting')  # waiting, matched, cancelled, expired

    __table_args__ = (
        Index("ix_duel_queue_status", "status"),
        Index("ix_duel_queue_expires_at", "expires_at"),
        Index("ix_duel_queue_user_id", "user_id"),
        Index("ix_duel_queue_room_code", "room_code"),
        Index("ix_duel_queue_status_room", "status", "room_code"),
    )


# ============================
# DTO для удобной передачи
# ============================

@dataclass(frozen=True)
class SavedDuel:
    id: int
    user_a_id: int
    user_b_id: int
    room_code: Optional[int]
    task_text: str
    score_a: Optional[float]
    score_b: Optional[float]
    winner_user_id: Optional[int]
    created_at: datetime
    status: str
    photo_a_received: bool
    photo_b_received: bool


@dataclass(frozen=True)
class LeaderboardRow:
    user_id: int
    user_name: str
    wins: int
    games: int
    winrate: float


@dataclass(frozen=True)
class QueueEntry:
    id: int
    user_id: int
    room_code: Optional[int]
    created_at: datetime
    expires_at: datetime
    status: str


@dataclass(frozen=True)
class RoomInfo:
    room_code: str
    creator_user_id: int
    creator_name: str
    created_at: datetime
    waiting_since: timedelta


# ============================
# Класс работы с БД
# ============================

class Database:
    """
    Обёртка над SQLAlchemy.

    - migrate(): создаёт таблицы (idempotent).
    - save_duel(): сохраняет одну дуэль (результат сравнения двух фото).
    """

    def __init__(self, database_url: str):
        """
        database_url пример:
        postgresql+psycopg2://postgres:123@localhost:5432/duels
        """
        self._engine = create_engine(database_url, pool_pre_ping=True, future=True)
        self._SessionLocal = sessionmaker(bind=self._engine, autoflush=False, autocommit=False, future=True)
        logger.info("Database initialized")

    @property
    def engine(self):
        return self._engine

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Контекстный менеджер для сессий.
        """
        session: Session = self._SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.exception("DB transaction rolled back due to error: %s", e)
            raise
        finally:
            session.close()

    def migrate(self, drop_existing: bool = False) -> None:
        """
        Создаёт (и опционально пересоздаёт) таблицы ORM.
        """
        if drop_existing:
            logger.warning("Dropping all tables before migrate()")
            Base.metadata.drop_all(self._engine)
        Base.metadata.create_all(self._engine)
        logger.info("Database schema migrated (tables and indexes are up-to-date)")

    def save_user(
            self,
            user_id: int,
            first_name: str,
            last_name: Optional[str] = None,
            username: Optional[str] = None,
    ) -> None:
        """
        Сохраняет или обновляет информацию о пользователе
        """
        with self.session() as s:
            existing_user = s.get(User, user_id)
            if existing_user:
                # Обновляем существующего пользователя
                existing_user.first_name = first_name
                existing_user.last_name = last_name
                existing_user.username = username
                existing_user.updated_at = datetime.now(timezone.utc)
            else:
                # Создаем нового пользователя
                user = User(
                    user_id=user_id,
                    first_name=first_name,
                    last_name=last_name,
                    username=username,
                )
                s.add(user)

    def get_user_name(self, user_id: int) -> str:
        """
        Получает имя пользователя по его ID
        """
        with self.session() as s:
            user = s.get(User, user_id)
            if user:
                name_parts = [user.first_name]
                if user.last_name:
                    name_parts.append(user.last_name)
                return " ".join(name_parts)
            return f"User {user_id}"

    def get_active_duel_for_user(self, user_id: int) -> Optional[SavedDuel]:
        """
        Возвращает активную дуэль пользователя в состоянии waiting_photos,
        или None если пользователь не участвует в активной дуэли
        """
        with self.session() as s:
            active_duel = s.execute(
                select(Duel).where(
                    or_(Duel.user_a_id == user_id, Duel.user_b_id == user_id),
                    Duel.status == 'waiting_photos'
                ).order_by(Duel.created_at.desc())
            ).scalars().first()

            if active_duel:
                return SavedDuel(
                    id=active_duel.id,
                    user_a_id=active_duel.user_a_id,
                    user_b_id=active_duel.user_b_id,
                    room_code=active_duel.room_code,
                    task_text=active_duel.task_text,
                    score_a=active_duel.score_a,
                    score_b=active_duel.score_b,
                    winner_user_id=active_duel.winner_user_id,
                    created_at=active_duel.created_at,
                    status=active_duel.status,
                    photo_a_received=active_duel.photo_a_received,
                    photo_b_received=active_duel.photo_b_received
                )
            return None

    def mark_duel_photo_received(self, duel_id: int, user_id: int) -> bool:
        """
        Отмечает получение фото в дуэли и возвращает True, если оба фото получены
        """
        with self.session() as s:
            duel = s.get(Duel, duel_id)
            if not duel:
                return False

            if user_id == duel.user_a_id:
                duel.photo_a_received = True
            elif user_id == duel.user_b_id:
                duel.photo_b_received = True
            else:
                return False

            # Проверяем, получены ли оба фото
            both_received = duel.photo_a_received and duel.photo_b_received

            if both_received and duel.status == 'waiting_photos':
                duel.status = 'scoring'

            return both_received

    def are_both_photos_received(self, duel_id: int) -> bool:
        """
        Проверяет, получены ли фото от обоих участников дуэли
        """
        with self.session() as s:
            duel = s.get(Duel, duel_id)
            if not duel:
                return False
            return duel.photo_a_received and duel.photo_b_received

    def has_user_sent_photo(self, duel_id: int, user_id: int) -> bool:
        """
        Проверяет, отправил ли пользователь фото в дуэли
        """
        with self.session() as s:
            duel = s.get(Duel, duel_id)
            if not duel:
                return False

            if user_id == duel.user_a_id:
                return duel.photo_a_received
            elif user_id == duel.user_b_id:
                return duel.photo_b_received
            return False

    def generate_room_code(self) -> int:
        """
        Генерирует случайный уникальный четырёхзначный код комнаты
        """
        max_attempts = 50  # Максимальное количество попыток генерации

        with self.session() as s:
            for attempt in range(max_attempts):
                code = secrets.randbelow(9000) + 1000  # 1000-9999

                # Проверяем, есть ли активная комната с таким кодом
                existing_room = s.execute(
                    select(DuelQueue).where(
                        DuelQueue.room_code == code,
                        DuelQueue.status == 'waiting'
                    )
                ).scalar_one_or_none()

                if not existing_room:
                    return code

            # Если не удалось сгенерировать уникальный код за max_attempts попыток
            raise RuntimeError(f"Не удалось сгенерировать уникальный код комнаты после {max_attempts} попыток")

    def join_queue(
            self,
            user_id: int,
            room_code: Optional[int] = None,
            wait_minutes: int = RANDOM_MATCH_TIMEOUT
    ) -> QueueEntry:
        """
        Добавляет пользователя в очередь ожидания дуэли
        """
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=wait_minutes)

        with self.session() as s:
            # Проверяем, не находится ли пользователь уже в очереди
            existing_entry = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == user_id,
                    DuelQueue.status == 'waiting'
                )
            ).scalar_one_or_none()

            if existing_entry:
                raise ValueError("Пользователь уже находится в очереди")

            # Если комната указана, проверяем её существование
            if room_code:
                room_entries = s.execute(
                    select(DuelQueue).where(
                        DuelQueue.room_code == room_code,
                        DuelQueue.status == 'waiting'
                    )
                ).scalars().all()

                if not room_entries:
                    return None

                if len(room_entries) >= 2:
                    return None

            # Создаем запись в очереди
            entry = DuelQueue(
                user_id=user_id,
                room_code=room_code,
                expires_at=expires_at,
                status='waiting'
            )
            s.add(entry)
            s.flush()

            return QueueEntry(
                id=entry.id,
                user_id=entry.user_id,
                room_code=entry.room_code,
                created_at=entry.created_at,
                expires_at=entry.expires_at,
                status=entry.status
            )

    def create_room(self, user_id: int, wait_minutes: int = 5) -> int:
        """
        Создает новую комнату и добавляет создателя в очередь
        """
        room_code = self.generate_room_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=wait_minutes)

        with self.session() as s:
            # Создаем запись в очереди с комнатой
            entry = DuelQueue(
                user_id=user_id,
                room_code=room_code,
                expires_at=expires_at,
                status='waiting'
            )
            s.add(entry)

            return room_code

    def is_user_in_queue(self, user_id: int) -> bool:
        """
        Проверяет, ожидает ли пользователь матча в очереди
        """
        with self.session() as s:
            existing_entry = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == user_id,
                    DuelQueue.status == 'waiting'
                )
            ).scalar_one_or_none()

            return existing_entry is not None

    def find_opponent(self, user_id: int) -> Optional[QueueEntry]:
        """
        Ищет соперника для пользователя в очереди
        """
        with self.session() as s:
            # Находим запись пользователя
            user_entry = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == user_id,
                    DuelQueue.status == 'waiting',
                    DuelQueue.expires_at > datetime.now(timezone.utc)
                )
            ).scalar_one_or_none()

            if not user_entry:
                return None

            # Ищем соперника
            if user_entry.room_code:
                # Для комнат ищем второго участника с тем же room_code
                opponent_entry = s.execute(
                    select(DuelQueue).where(
                        DuelQueue.room_code == user_entry.room_code,
                        DuelQueue.user_id != user_id,
                        DuelQueue.status == 'waiting',
                        DuelQueue.expires_at > datetime.now(timezone.utc)
                    )
                ).scalar_one_or_none()
            else:
                # Для случайных дуэлей ищем любого waiting с room_code=NULL
                opponent_entry = s.execute(
                    select(DuelQueue).where(
                        DuelQueue.room_code.is_(None),
                        DuelQueue.user_id != user_id,
                        DuelQueue.status == 'waiting',
                        DuelQueue.expires_at > datetime.now(timezone.utc)
                    ).order_by(DuelQueue.created_at.asc())
                ).scalar_one_or_none()

            if opponent_entry:
                return QueueEntry(
                    id=opponent_entry.id,
                    user_id=opponent_entry.user_id,
                    room_code=opponent_entry.room_code,
                    created_at=opponent_entry.created_at,
                    expires_at=opponent_entry.expires_at,
                    status=opponent_entry.status
                )

            return None

    def create_duel_from_queue(self, user_id: int, opponent_user_id: int) -> SavedDuel:
        """
        Создает дуэль из двух пользователей в очереди и удаляет их из очереди
        """
        with self.session() as s:

            # Получаем записи из очереди
            user_entry = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == user_id,
                    DuelQueue.status == 'waiting'
                )
            ).scalar_one_or_none()

            opponent_entry = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == opponent_user_id,
                    DuelQueue.status == 'waiting'
                )
            ).scalar_one_or_none()

            if not user_entry or not opponent_entry:
                raise ValueError("Один из пользователей не найден в очереди")

            # Создаем дуэль
            category, task_text, hint = task_manager.get_random_task()

            duel = Duel(
                user_a_id=user_id,
                user_b_id=opponent_user_id,
                room_code=user_entry.room_code,
                task_text=task_text,
                status='waiting_photos',
                photo_a_received=False,
                photo_b_received=False
            )
            s.add(duel)
            s.flush()

            # Помечаем записи в очереди как matched
            user_entry.status = 'matched'
            opponent_entry.status = 'matched'

            return SavedDuel(
                id=duel.id,
                user_a_id=duel.user_a_id,
                user_b_id=duel.user_b_id,
                room_code=duel.room_code,
                task_text=duel.task_text,
                score_a=duel.score_a,
                score_b=duel.score_b,
                winner_user_id=duel.winner_user_id,
                created_at=duel.created_at,
                status=duel.status,
                photo_a_received=duel.photo_a_received,
                photo_b_received=duel.photo_b_received
            )

    def leave_queue(self, user_id: int) -> bool:
        """
        Удаляет пользователя из очереди
        """
        with self.session() as s:
            result = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == user_id,
                    DuelQueue.status == 'waiting'
                )
            ).scalar_one_or_none()

            if result:
                result.status = 'cancelled'
                return True
            return False

    def cleanup_expired_queues(self) -> int:
        """
        Очищает просроченные записи в очереди
        """
        with self.session() as s:
            result = s.execute(
                select(DuelQueue).where(
                    DuelQueue.expires_at < datetime.now(timezone.utc),
                    DuelQueue.status == 'waiting'
                )
            ).scalars().all()

            for entry in result:
                entry.status = 'expired'

            cleaned_count = len(result)
            logger.info("Cleaned up %s expired queue entries", cleaned_count)
            return cleaned_count

    def save_duel(
            self,
            *,
            user_a_id: int,
            user_b_id: int,
            task_text: str,
            score_a: float,
            score_b: float,
            room_code: Optional[int] = None,
            created_at: Optional[datetime] = None,
    ) -> SavedDuel:
        """
        Сохраняет результат дуэли (устаревший вариант)
        """
        created = created_at or datetime.now(timezone.utc)

        with self.session() as s:
            winner_user_id = user_a_id
            if score_b > score_a:
                winner_user_id = user_b_id
            elif score_a == score_b:
                winner_user_id = None

            duel = Duel(
                user_a_id=user_a_id,
                user_b_id=user_b_id,
                room_code=room_code,
                task_text=task_text,
                score_a=float(score_a),
                score_b=float(score_b),
                winner_user_id=winner_user_id,
                created_at=created,
                status='completed',
                photo_a_received=True,
                photo_b_received=True
            )
            s.add(duel)
            s.flush()

            return SavedDuel(
                id=duel.id,
                user_a_id=duel.user_a_id,
                user_b_id=duel.user_b_id,
                room_code=duel.room_code,
                task_text=duel.task_text,
                score_a=duel.score_a,
                score_b=duel.score_b,
                winner_user_id=duel.winner_user_id,
                created_at=duel.created_at,
                status=duel.status,
                photo_a_received=duel.photo_a_received,
                photo_b_received=duel.photo_b_received
            )

    def update_duel_result(
            self,
            duel_id: int,
            score_a: float,
            score_b: float,
            task_text: str
    ) -> SavedDuel:
        """
        Обновляет результат дуэли (после анализа моделькой)
        """
        with self.session() as s:
            duel = s.get(Duel, duel_id)
            if not duel:
                raise ValueError(f"Дуэль {duel_id} не найдена")

            # Получаем записи из очереди
            user_a_entry = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == duel.user_a_id,
                    DuelQueue.status == 'matched'
                )
            ).scalar_one_or_none()

            user_b_entry = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id == duel.user_b_id,
                    DuelQueue.status == 'matched'
                )
            ).scalar_one_or_none()

            if not user_a_entry or not user_b_entry:
                raise ValueError("Один из пользователей не найден в очереди")

            # Помечаем записи в очереди как expired
            user_a_entry.status = 'expired'
            user_b_entry.status = 'expired'

            duel.task_text = task_text
            duel.score_a = score_a
            duel.score_b = score_b
            duel.status = 'completed'

            # Определяем победителя
            if score_a > score_b:
                duel.winner_user_id = duel.user_a_id
            elif score_b > score_a:
                duel.winner_user_id = duel.user_b_id
            else:
                duel.winner_user_id = None



            return SavedDuel(
                id=duel.id,
                user_a_id=duel.user_a_id,
                user_b_id=duel.user_b_id,
                room_code=duel.room_code,
                task_text=duel.task_text,
                score_a=duel.score_a,
                score_b=duel.score_b,
                winner_user_id=duel.winner_user_id,
                created_at=duel.created_at,
                status=duel.status,
                photo_a_received=duel.photo_a_received,
                photo_b_received=duel.photo_b_received
            )

    def get_user_history(
            self,
            user_id: int,
            *,
            limit: int = 10,
            offset: int = 0,
    ) -> list[SavedDuel]:
        """
        Возвращает последние дуэли пользователя
        """
        logger.debug("Fetching user history: user_id=%s, limit=%s, offset=%s", user_id, limit, offset)
        with self.session() as s:
            stmt = (
                select(Duel)
                .where(or_(Duel.user_a_id == user_id, Duel.user_b_id == user_id),
                       Duel.status == 'completed',
                       Duel.score_a.is_not(None),
                       Duel.score_b.is_not(None)
                       )
                .order_by(Duel.created_at.desc(), Duel.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = s.execute(stmt).scalars().all()

            history = [
                SavedDuel(
                    id=r.id,
                    user_a_id=r.user_a_id,
                    user_b_id=r.user_b_id,
                    room_code=r.room_code,
                    task_text=r.task_text,
                    score_a=r.score_a,
                    score_b=r.score_b,
                    winner_user_id=r.winner_user_id,
                    created_at=r.created_at,
                    status=r.status,
                    photo_a_received=r.photo_a_received,
                    photo_b_received=r.photo_b_received
                )
                for r in rows
            ]
            logger.info("User history fetched: user_id=%s, count=%s", user_id, len(history))
            return history

    def get_leaderboard_top(
            self,
            *,
            limit: int = 10,
    ) -> list[LeaderboardRow]:
        """
        Лидерборд: топ пользователей по числу побед
        """
        with self.session() as s:
            # Победы (winner_user_id не NULL)
            wins_stmt = (
                select(
                    Duel.winner_user_id.label("user_id"),
                    func.count(Duel.id).label("wins"),
                )
                .where(
                    Duel.winner_user_id.is_not(None),
                    Duel.status == 'completed'
                )
                .group_by(Duel.winner_user_id)
                .subquery("wins")
            )

            # Игры: считаем появление user_id в A и B (union all)
            games_a = select(Duel.user_a_id.label("user_id")).where(Duel.status == 'completed')
            games_b = select(Duel.user_b_id.label("user_id")).where(Duel.status == 'completed')
            games_union = union_all(games_a, games_b).subquery("games_union")

            games_stmt = (
                select(
                    games_union.c.user_id,
                    func.count().label("games"),
                )
                .group_by(games_union.c.user_id)
                .subquery("games")
            )

            # Join games с wins
            lb_stmt = (
                select(
                    games_stmt.c.user_id,
                    games_stmt.c.games,
                    func.coalesce(wins_stmt.c.wins, 0).label("wins"),
                    (func.coalesce(wins_stmt.c.wins, 0) / games_stmt.c.games).label("win_rate"),
                )
                .select_from(games_stmt)
                .join(wins_stmt, wins_stmt.c.user_id == games_stmt.c.user_id, isouter=True)
                .order_by(
                    func.coalesce(wins_stmt.c.wins, 0).desc(),
                    games_stmt.c.games.desc(),
                    games_stmt.c.user_id.asc(),
                )
                .limit(limit)
            )

            res = s.execute(lb_stmt).all()
            leaderboard = []
            for row in res:
                user_name = self.get_user_name(row.user_id)
                leaderboard.append(
                    LeaderboardRow(
                        user_id=row.user_id,
                        user_name=user_name,
                        wins=int(row.wins),
                        games=int(row.games),
                        winrate=float(row.win_rate) if row.win_rate is not None else 0.0,
                    )
                )
            logger.info("Leaderboard fetched: entries=%s", len(leaderboard))
            return leaderboard


    def cleanup_duplicate_queues(self) -> int:
        """
        Удаляет дублирующиеся записи в очереди для одного пользователя
        Оставляет только самую свежую запись
        """
        with self.session() as s:
            # Находим пользователей с несколькими активными записями
            subquery = (
                select(DuelQueue.user_id)
                .where(DuelQueue.status == 'waiting')
                .group_by(DuelQueue.user_id)
                .having(func.count() > 1)
            ).subquery()

            # Для каждого пользователя оставляем только самую свежую запись
            duplicates = s.execute(
                select(DuelQueue).where(
                    DuelQueue.user_id.in_(select(subquery.c.user_id)),
                    DuelQueue.status == 'waiting'
                ).order_by(DuelQueue.user_id, DuelQueue.created_at.desc())
            ).scalars().all()

            # Собираем ID записей, которые нужно удалить (все кроме самых свежих)
            users_processed = set()
            records_to_update = []

            for record in duplicates:
                if record.user_id not in users_processed:
                    # Первая запись для пользователя (самая свежая) - оставляем
                    users_processed.add(record.user_id)
                else:
                    # Последующие записи - помечаем как отмененные
                    record.status = 'cancelled'
                    records_to_update.append(record)

            cleaned_count = len(records_to_update)
            if cleaned_count > 0:
                logger.info("Cleaned up %s duplicate queue entries", cleaned_count)

            return cleaned_count

    def cleanup_duplicate_duels(self) -> int:
        """
        Очищает дублирующие активные дуэли для пользователей
        Оставляет только самую свежую дуэль для каждого пользователя
        """
        with self.session() as s:
            # Находим пользователей с несколькими активными дуэлями
            subquery = (
                select(Duel.user_a_id.label("user_id"))
                .where(Duel.status == 'waiting_photos')
                .union_all(
                    select(Duel.user_b_id.label("user_id"))
                    .where(Duel.status == 'waiting_photos')
                )
            ).alias("all_users")

            duplicate_users = s.execute(
                select(subquery.c.user_id)
                .group_by(subquery.c.user_id)
                .having(func.count() > 1)
            ).scalars().all()

            # Для каждого пользователя оставляем только самую свежую дуэль
            duels_to_cancel = []

            for user_id in duplicate_users:
                # Находим все активные дуэли пользователя
                user_duels = s.execute(
                    select(Duel).where(
                        or_(Duel.user_a_id == user_id, Duel.user_b_id == user_id),
                        Duel.status == 'waiting_photos'
                    ).order_by(Duel.created_at.desc())
                ).scalars().all()

                # Оставляем первую (самую свежую), остальные отменяем
                for i, duel in enumerate(user_duels):
                    if i > 0:  # Все кроме первой
                        duel.status = 'cancelled'
                        duels_to_cancel.append(duel)

            cleaned_count = len(duels_to_cancel)
            if cleaned_count > 0:
                logger.info("Cleaned up %s duplicate active duels", cleaned_count)

            return cleaned_count

    def cancel_duel_on_start(self, user_id: int) -> tuple[bool, Optional[SavedDuel]]:
        """
        Проверяет есть ли у пользователя начатая дуэль и отменяет её.
        Возвращает кортеж (была_ли_дуэль, объект_дуэли)
        """
        with self.session() as s:
            # Ищем активную дуэль пользователя
            active_duel = s.execute(
                select(Duel).where(
                    or_(Duel.user_a_id == user_id, Duel.user_b_id == user_id),
                    Duel.status.in_(['waiting_photos', 'scoring'])
                )
            ).scalars().first()

            if active_duel:
                # Сохраняем информацию о дуэли перед отменой
                saved_duel = SavedDuel(
                    id=active_duel.id,
                    user_a_id=active_duel.user_a_id,
                    user_b_id=active_duel.user_b_id,
                    room_code=active_duel.room_code,
                    task_text=active_duel.task_text,
                    score_a=active_duel.score_a,
                    score_b=active_duel.score_b,
                    winner_user_id=active_duel.winner_user_id,
                    created_at=active_duel.created_at,
                    status=active_duel.status,
                    photo_a_received=active_duel.photo_a_received,
                    photo_b_received=active_duel.photo_b_received
                )

                # ОТМЕНЯЕМ ДУЭЛЬ И ВСЕ СВЯЗАННЫЕ ЗАПИСИ
                active_duel.status = 'cancelled'

                # ВАЖНО: также отменяем дуэль у оппонента и все связанные записи в очереди
                opponent_id = active_duel.user_a_id if active_duel.user_a_id != user_id else active_duel.user_b_id

                # Отменяем ВСЕ записи в очереди для обоих пользователей
                user_queue_entries = s.execute(
                    select(DuelQueue).where(
                        DuelQueue.user_id == user_id,
                        DuelQueue.status.in_(['waiting', 'matched'])
                    )
                ).scalars().all()

                opponent_queue_entries = s.execute(
                    select(DuelQueue).where(
                        DuelQueue.user_id == opponent_id,
                        DuelQueue.status.in_(['waiting', 'matched'])
                    )
                ).scalars().all()

                # Отменяем все найденные записи
                for entry in user_queue_entries + opponent_queue_entries:
                    entry.status = 'cancelled'

                logger.info(f"Дуэль {active_duel.id} отменена для пользователя {user_id}, оппонент {opponent_id}")
                return True, saved_duel

            return False, None
