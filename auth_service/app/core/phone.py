"""Нормализация телефонных номеров.

Телефон хранится в свободном формате (+7 999…, 8 (999)…, с пробелами/скобками),
поэтому сравнение/поиск ведём по последним 10 значащим цифрам.
"""
import re

from sqlalchemy import func


def normalize_phone(raw: str | None) -> str:
    """Свести телефон к 10 значащим цифрам (рус. формат), отбросив +7/8 и разделители."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = digits[1:]
    return digits[-10:]


def normalized_phone_column(col):
    """SQL-выражение: последние 10 цифр телефона из колонки (для поиска по номеру)."""
    return func.right(func.regexp_replace(col, r"\D", "", "g"), 10)
