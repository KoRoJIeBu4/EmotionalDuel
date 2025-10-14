from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image

from .clip import initialize_model, EDModel


# Разрешённые расширения файлов с изображениями (в приоритете — первые)
ALLOWED_EXTENSIONS: Sequence[str] = (".jpg", ".jpeg", ".png", ".webp")


@dataclass(frozen=True)
class DuelScores:
    """
    Результат ML-оценки дуэли из двух фото.
    """
    score_a: float
    score_b: float
    winner: Optional[str]  # 'a' | 'b' | None (ничья)


class DuelML:
    """
    Адаптер поверх EDModel:
    - Инициализирует CLIP-модель один раз.
    - Читает фотографии участников из папки по user_id.
    - Вычисляет score для каждой фотографии по текстовому заданию.
    - Возвращает победителя и оценки.
    """

    def __init__(self, model: Optional[EDModel] = None):
        self._model: EDModel = model or initialize_model()

    def score_duel_by_user_ids(
        self,
        *,
        task_text: str,
        user_a_id: int,
        user_b_id: int,
        uploads_dir: str = "data/images",
        cleanup_after: bool = False, # На время дебага false
        eps_draw: float = 1e-3,
    ) -> DuelScores:
        """
        Оценивает две фотографии, сохранённые ботом в uploads_dir, по user_id.

        Параметры:
          - task_text: текст задания
          - user_a_id, user_b_id: Telegram user_id участников
          - uploads_dir: корневая папка, где бот сохраняет фото (по имени файла = {user_id}.*)
          - cleanup_after: если True — после оценки удаляет использованные файлы
          - eps_draw: порог ничьей по разнице score

        Ожидаемый формат файлов:
          uploads_dir/{user_id}.jpg|.jpeg|.png|.webp

        Исключения:
          - FileNotFoundError — если файл пользователя не найден
          - ValueError — если файл найден, но формат не поддерживается/не читается
        """
        a_path = self._resolve_user_image_path(Path(uploads_dir), user_a_id)
        b_path = self._resolve_user_image_path(Path(uploads_dir), user_b_id)

        img_a = self._load_image(a_path)
        img_b = self._load_image(b_path)

        report = self._model.play_duel(task_text, [img_a, img_b])

        score_a = float(report[0][1])
        score_b = float(report[1][1])

        if abs(score_a - score_b) < eps_draw:
            winner = None
        else:
            winner = "a" if score_a > score_b else "b"

        if cleanup_after:
            for p in (a_path, b_path):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

        return DuelScores(score_a=round(score_a, 6), score_b=round(score_b, 6), winner=winner)

    @staticmethod
    def _resolve_user_image_path(root: Path, user_id: int) -> Path:
        """
        Ищет файл изображения по шаблону {user_id}.* в списке ALLOWED_EXTENSIONS.
        Берёт первое совпадение по приоритету расширений.
        """
        for ext in ALLOWED_EXTENSIONS:
            candidate = root / f"{user_id}{ext}"
            if candidate.exists():
                return candidate

        # Если строго по имени не нашли — сделаем fallback: найти любое {user_id}.*
        matches = list(root.glob(f"{user_id}.*"))
        if matches:
            return matches[0]

        raise FileNotFoundError(
            f"Image for user_id={user_id} not found in {root}. "
            f"Expected one of: {[f'{user_id}{ext}' for ext in ALLOWED_EXTENSIONS]}"
        )

    @staticmethod
    def _load_image(path: Path) -> Image.Image:
        try:
            return Image.open(path).convert("RGB")
        except Exception as e:
            raise ValueError(f"Failed to load image at {path}: {e}") from e