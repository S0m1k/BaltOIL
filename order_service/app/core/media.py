"""Безопасное разрешение путей к файлам в MEDIA_ROOT.

Пути к файлам (file_path) приходят из БД и в норме формируются сервисом из
санированных значений. Эта функция — defense-in-depth: даже если в БД попадёт
значение с обходом каталога (../../etc/passwd), отдать файл за пределами
MEDIA_ROOT не получится.
"""
from pathlib import Path

from app.core.exceptions import NotFoundError


def resolve_media_path(media_root: Path, file_path: str) -> Path:
    """Вернуть абсолютный путь внутри media_root или поднять NotFoundError.

    Защищает от path traversal: результат гарантированно лежит внутри media_root.
    """
    base = media_root.resolve()
    candidate = (base / file_path).resolve()
    if base != candidate and base not in candidate.parents:
        raise NotFoundError("Файл не найден на сервере")
    return candidate
