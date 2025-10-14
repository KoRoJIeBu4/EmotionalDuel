from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
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
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


logger = logging.getLogger("database")

# ============================
# ORM: база и модель таблицы
# ============================

class Base(DeclarativeBase):
    pass


class DuelResult(Base):
    """
    MVP: одна запись = один раунд/дуэль.
    Позже можно нормализовать (duels/rounds/submissions/scores).
    """
    __tablename__ = "duel_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_a_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_b_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    task_text: Mapped[str] = mapped_column(Text, nullable=False)


    # Проценты совпадения [0..1] для каждого игрока
    score_a: Mapped[float] = mapped_column(Float, nullable=False)
    score_b: Mapped[float] = mapped_column(Float, nullable=False)

    # Победитель: user_id, либо NULL если ничья
    winner_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_duel_results_winner_user_id", "winner_user_id"),
        Index("ix_duel_results_user_a_id", "user_a_id"),
        Index("ix_duel_results_user_b_id", "user_b_id"),
        Index("ix_duel_results_created_at", "created_at"),
    )

# ============================
# DTO для удобной передачи
# ============================

@dataclass(frozen=True)
class SavedDuel:
    id: int
    user_a_id: int
    user_b_id: int
    score_a: float
    score_b: float
    winner_user_id: Optional[int]
    created_at: datetime

@dataclass(frozen=True)
class LeaderboardRow:
    user_id: int
    wins: int
    games: int
    winrate: float

# ============================
# Класс работы с БД
# ============================

class Database:
    """
    Упрощённая обёртка над SQLAlchemy для MVP.

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
        Для MVP: metadata.create_all. Позже замените на Alembic миграции.
        """
        if drop_existing:
            logger.warning("Dropping all tables before migrate()")
            Base.metadata.drop_all(self._engine)
        Base.metadata.create_all(self._engine)
        logger.info("Database schema migrated (tables and indexes are up-to-date)")
    def save_duel(
        self,
        *,
        user_a_id: int,
        user_b_id: int,
        task_text: str,
        score_a: float,
        score_b: float,
        # winner_user_id: Optional[int],
        created_at: Optional[datetime] = None,
    ) -> SavedDuel:
        """
        Сохраняет результат дуэли (один раунд) и возвращает SavedDuel.

        Параметры:
        - user_a_id, user_b_id: telegram user ids участников
        - task_text: текст задания (например, "радость с закрытыми глазами")
        - score_a, score_b: проценты совпадения [0..1] от ML
        - winner_user_id: user_id победителя или None при ничьей
        - created_at: время создания; по умолчанию — сейчас UTC

        Возвращает:
        - SavedDuel с id созданной записи и основными полями
        """
        created = created_at or datetime.now(timezone.utc)

        def _insert(sess: Session) -> SavedDuel:
            winner_user_id = user_a_id
            if score_b > score_a:
                winner_user_id = user_b_id
            elif score_a == score_b:
                winner_user_id = None
            row = DuelResult(
                user_a_id=user_a_id,
                user_b_id=user_b_id,
                task_text=task_text,
                score_a=float(score_a),
                score_b=float(score_b),
                winner_user_id=winner_user_id,
                created_at=created,
            )
            sess.add(row)
            sess.flush()  # получить row.id до commit
            return SavedDuel(
                id=row.id,
                user_a_id=row.user_a_id,
                user_b_id=row.user_b_id,
                score_a=row.score_a,
                score_b=row.score_b,
                winner_user_id=row.winner_user_id,
                created_at=row.created_at,
            )

        with self.session() as s:
            return _insert(s)
        
    
    def get_user_history(
        self,
        user_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SavedDuel]:
        """
        Возвращает последние дуэли пользователя (участник A или B), отсортированные по дате (DESC).
        """
        logger.debug("Fetching user history: user_id=%s, limit=%s, offset=%s", user_id, limit, offset)
        with self.session() as s:
            stmt = (
                select(DuelResult)
                .where(or_(DuelResult.user_a_id == user_id, DuelResult.user_b_id == user_id))
                .order_by(DuelResult.created_at.desc(), DuelResult.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = s.execute(stmt).scalars().all()

            history = [
                SavedDuel(
                    id=r.id,
                    user_a_id=r.user_a_id,
                    user_b_id=r.user_b_id,
                    score_a=r.score_a,
                    score_b=r.score_b,
                    winner_user_id=r.winner_user_id,
                    created_at=r.created_at,
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
        Лидерборд: топ пользователей по числу побед.
        Также считает общее число игр и win_rate = wins/games.

        Аргументы:
        - limit: сколько вернуть (по умолчанию 10)
        - since: если задан, учитываются только дуэли с created_at >= since
        """
        with self.session() as s:
            # Фильтр по дате
            date_filter = []


            # Победы (winner_user_id не NULL)
            wins_stmt = (
                select(
                    DuelResult.winner_user_id.label("user_id"),
                    func.count(DuelResult.id).label("wins"),
                )
                .where(DuelResult.winner_user_id.is_not(None), *date_filter)
                .group_by(DuelResult.winner_user_id)
                .subquery("wins")
            )

            # Игры: считаем появление user_id в A и B (union all), затем группируем
            games_a = select(DuelResult.user_a_id.label("user_id")).where(*date_filter)
            games_b = select(DuelResult.user_b_id.label("user_id")).where(*date_filter)
            games_union = union_all(games_a, games_b).subquery("games_union")

            games_stmt = (
                select(
                    games_union.c.user_id,
                    func.count().label("games"),
                )
                .group_by(games_union.c.user_id)
                .subquery("games")
            )

            # Join games с wins (left join: у пользователя могут быть 0 побед)
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
            leaderboard = [
                LeaderboardRow(
                    user_id=row.user_id,
                    wins=int(row.wins),
                    games=int(row.games),
                    win_rate=float(row.win_rate) if row.win_rate is not None else 0.0,
                )
                for row in res
            ]
            logger.info("Leaderboard fetched: entries=%s", len(leaderboard))
            return leaderboard

