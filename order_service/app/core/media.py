"""Безопасное разрешение путей к файлам в MEDIA_ROOT.

Пути к файлам (file_path) приходят из БД и в норме формируются сервисом из
санированных значений. Эта функция — defense-in-depth: даже если в БД попадёт
значение с обходом каталога (../../etc/passwd), отдать файл за пределами
MEDIA_ROOT не получится.
"""
from pathlib import Path
from urllib.parse import quote

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


def _ascii_fallback(filename: str) -> str:
    """Транслит-безопасный ascii-вариант имени: не-ascii → '_', кавычки убраны."""
    cleaned = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in filename)
    cleaned = cleaned.strip() or "document"
    return cleaned


def content_disposition_attachment(filename: str) -> str:
    """Заголовок Content-Disposition с кириллицей по RFC 5987.

    HTTP-заголовки передаются в latin-1, поэтому кириллическое имя файла нельзя
    класть в filename= как есть (UnicodeEncodeError на сервере / мусор в браузере).
    Отдаём ascii-фолбэк в filename= и настоящее имя в filename*=UTF-8''… —
    все актуальные браузеры предпочитают filename*.
    """
    quoted = quote(filename, safe="")
    return f"attachment; filename=\"{_ascii_fallback(filename)}\"; filename*=UTF-8''{quoted}"
