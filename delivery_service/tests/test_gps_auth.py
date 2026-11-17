"""Подтверждение трекера при приёме точки и разбор удостоверений в строке.

TOTP убран 17.11.2026: трекер шлёт «<номер> <широта> <долгота> <спутники>».
Остался только необязательный статический токен. Прошивка с кодом TOTP после
номера могла остаться на машинах — её точки должны приниматься, код
отбрасывается.

Запуск из папки delivery_service:  pytest tests/test_gps_auth.py
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("JWT_SECRET_KEY", "x" * 48)
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.services import gps_service  # noqa: E402
from app.services.gps_protocol import (  # noqa: E402
    ERR_AUTH,
    ProtocolError,
    parse_line,
)

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
TOKEN = "0123456789abcdef0123456789abcdef"


# ── Разбор строки ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "SZTK-01 59.938732 30.312345 9",
    "SZTK-01,59.938732,30.312345,9",
    "SZTK-01;59.938732;30.312345;9",
])
def test_plain_message_parses(raw):
    p = parse_line(raw, now=NOW)
    assert (p.device, str(p.lat), str(p.lon), p.sats, p.token) == (
        "SZTK-01", "59.938732", "30.312345", 9, None)


@pytest.mark.parametrize("raw", [
    "SZTK-01 48291376 59.938732 30.312345 9",
    "SZTK-01,48291376,59.938732,30.312345,9",
    "SZTK-01;07081804;59.938732;30.312345;9",
])
def test_legacy_totp_code_is_skipped_not_rejected(raw):
    # Прошивка Платона с TOTP: код после номера молча отбрасывается.
    p = parse_line(raw, now=NOW)
    assert (p.device, str(p.lat), str(p.lon), p.sats, p.token) == (
        "SZTK-01", "59.938732", "30.312345", 9, None)


def test_parsed_point_has_no_code_field():
    assert not hasattr(parse_line("SZTK-01 59.9 30.3 9", now=NOW), "code")


def test_hex_token_is_still_parsed():
    p = parse_line(f"SZTK-01 {TOKEN} 59.9 30.3 9", now=NOW)
    assert p.token == TOKEN and str(p.lat) == "59.900000"


# ── Проверка при приёме (_authenticate) ───────────────────────────────────────

def _device(token_hash: str | None = None):
    return SimpleNamespace(id=uuid.uuid4(), device_number="SZTK-TEST", token_hash=token_hash)


def _point(prefix: str = ""):
    return parse_line(f"SZTK-TEST {prefix}59.938732 30.312345 9", now=NOW)


def test_device_without_token_accepts_plain_points():
    gps_service._authenticate(_device(), _point())


def test_device_without_token_accepts_legacy_code_points():
    gps_service._authenticate(_device(), _point("48291376 "))


def test_static_token_is_checked_when_issued():
    device = _device(token_hash=gps_service.hash_token(TOKEN))
    gps_service._authenticate(device, _point(f"{TOKEN} "))
    with pytest.raises(ProtocolError) as e:
        gps_service._authenticate(device, _point())
    assert e.value.code == ERR_AUTH
