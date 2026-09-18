"""TOTP для GPS-трекеров: совместимость с RFC 6238, хранение секрета,
разбор кода в строке трекера, защита от перебора (без БД и сети).

Запуск из папки delivery_service:  pytest tests/test_gps_totp.py
"""
import base64
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("JWT_SECRET_KEY", "x" * 48)
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.services import gps_service, gps_totp  # noqa: E402
from app.services.gps_protocol import (  # noqa: E402
    ERR_AUTH,
    FailureThrottle,
    ProtocolError,
    parse_line,
    parse_mapping,
)

# Ключ из приложения A RFC 6238 для SHA1.
RFC_SECRET = b"12345678901234567890"
NOW = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)


# ── Совместимость с RFC 6238 ──────────────────────────────────────────────────
# Если эти значения совпадают, код на Arduino, написанный по стандарту,
# гарантированно считает то же, что и сервер.

@pytest.mark.parametrize("unix_time,expected", [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
])
def test_rfc6238_sha1_vectors(unix_time, expected):
    assert gps_totp.totp(RFC_SECRET, unix_time) == expected


def test_code_is_accepted_one_step_around_and_rejected_further():
    t = 1_726_740_000
    code = gps_totp.totp(RFC_SECRET, t)
    assert gps_totp.verify_totp(RFC_SECRET, code, t)
    assert gps_totp.verify_totp(RFC_SECRET, code, t + 30)   # задержка отправки по 2G
    assert gps_totp.verify_totp(RFC_SECRET, code, t - 30)   # часы сервера отстали
    assert not gps_totp.verify_totp(RFC_SECRET, code, t + 90)
    assert not gps_totp.verify_totp(RFC_SECRET, code, t - 90)


@pytest.mark.parametrize("bad", ["", "1234567", "123456789", "12a45678", None])
def test_malformed_codes_are_rejected(bad):
    # 6-значный код от «стандартной» библиотеки тоже не проходит: только 8 цифр.
    assert not gps_totp.verify_totp(RFC_SECRET, bad, 59)


def test_secret_formats_are_consistent():
    secret = gps_totp.generate_secret()
    f = gps_totp.secret_formats(secret)
    assert len(secret) == 20
    assert bytes.fromhex(f["hex"]) == secret
    padded = f["base32"] + "=" * (-len(f["base32"]) % 8)
    assert base64.b32decode(padded) == secret
    assert f["arduino"].count("0x") == 20
    assert (f["digits"], f["period"]) == (8, 30)


# ── Хранение секрета ──────────────────────────────────────────────────────────

def test_secret_roundtrip_through_encryption():
    secret = gps_totp.generate_secret()
    stored = gps_totp.encrypt_secret(secret, "master-key")
    assert secret.hex() not in stored
    assert gps_totp.decrypt_secret(stored, "master-key") == secret


def test_same_secret_encrypts_differently_each_time():
    secret = gps_totp.generate_secret()
    assert gps_totp.encrypt_secret(secret, "k") != gps_totp.encrypt_secret(secret, "k")


def test_wrong_key_does_not_decrypt():
    stored = gps_totp.encrypt_secret(gps_totp.generate_secret(), "right")
    with pytest.raises(gps_totp.SecretDecryptError):
        gps_totp.decrypt_secret(stored, "wrong")


def test_tampered_record_does_not_decrypt():
    stored = gps_totp.encrypt_secret(gps_totp.generate_secret(), "k")
    blob = bytearray(base64.urlsafe_b64decode(stored))
    blob[20] ^= 0x01
    with pytest.raises(gps_totp.SecretDecryptError):
        gps_totp.decrypt_secret(base64.urlsafe_b64encode(bytes(blob)).decode(), "k")


@pytest.mark.parametrize("garbage", ["", "не base64", base64.urlsafe_b64encode(b"x1short").decode()])
def test_garbage_record_does_not_decrypt(garbage):
    with pytest.raises(gps_totp.SecretDecryptError):
        gps_totp.decrypt_secret(garbage, "k")


# ── Разбор кода в строке трекера ──────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "SZTK-01 48291376 59.938732 30.312345 9",
    "SZTK-01,48291376,59.938732,30.312345,9",
    "SZTK-01;48291376;59.938732;30.312345;9",
])
def test_code_after_device_number_is_parsed(raw):
    p = parse_line(raw, now=NOW)
    assert (p.device, p.code, str(p.lat), p.sats) == ("SZTK-01", "48291376", "59.938732", 9)


def test_code_with_leading_zeros_is_kept_as_text():
    # «07081804» из RFC: ведущий ноль обязан дожить до сравнения.
    assert parse_line("SZTK-01 07081804 59.9 30.3 9", now=NOW).code == "07081804"


def test_code_in_key_value_and_json_forms():
    assert parse_line("id=SZTK-01&code=48291376&lat=59.9&lon=30.3&sats=9", now=NOW).code == "48291376"
    assert parse_mapping({"id": "SZTK-01", "otp": "48291376", "lat": 59.9, "lon": 30.3}, now=NOW).code == "48291376"


def test_message_without_code_still_parses():
    p = parse_line("SZTK-01 59.938732 30.312345 9", now=NOW)
    assert p.code is None and p.lat is not None


def test_hex_token_is_not_mistaken_for_code():
    token = "0123456789abcdef0123456789abcdef"
    p = parse_line(f"SZTK-01 {token} 59.9 30.3 9", now=NOW)
    assert p.token == token and p.code is None


# ── Защита от перебора ────────────────────────────────────────────────────────

def test_throttle_blocks_after_limit_and_releases_after_window():
    th = FailureThrottle(max_failures=3, window_sec=600)
    for t in (0, 1, 2):
        assert not th.is_blocked("dev", t)
        th.record_failure("dev", t)
    assert th.is_blocked("dev", 3)
    assert not th.is_blocked("other", 3)       # соседний трекер не страдает
    assert not th.is_blocked("dev", 700)       # окно прошло


def test_throttle_does_not_grow_forever():
    th = FailureThrottle(max_failures=3, window_sec=600, max_entries=10)
    for i in range(100):
        th.record_failure(f"dev{i}", float(i))
    assert len(th._fails) <= 10


# ── Проверка при приёме (_authenticate) ───────────────────────────────────────

def _device(secret: bytes | None = None, token_hash: str | None = None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        device_number="SZTK-TEST",
        token_hash=token_hash,
        totp_secret_enc=(
            gps_totp.encrypt_secret(secret, gps_service.settings.gps_secret_master_key)
            if secret else None
        ),
    )


def _point(code=None, token=None):
    return parse_line(
        "SZTK-TEST " + (f"{code} " if code else "") + (f"{token} " if token else "")
        + "59.938732 30.312345 9"
    )


def test_valid_code_passes():
    secret = gps_totp.generate_secret()
    gps_service._authenticate(_device(secret), _point(code=gps_totp.totp(secret, int(time.time()))))


def test_wrong_code_is_rejected():
    secret = gps_totp.generate_secret()
    with pytest.raises(ProtocolError) as e:
        gps_service._authenticate(_device(secret), _point(code="00000000"))
    assert e.value.code == ERR_AUTH


def test_missing_code_is_rejected_but_not_counted_as_guess():
    secret = gps_totp.generate_secret()
    device = _device(secret)
    for _ in range(gps_service.settings.gps_totp_max_failures + 5):
        with pytest.raises(ProtocolError):
            gps_service._authenticate(device, _point())
    # Старая прошивка без кода не должна заблокировать трекер для новой.
    gps_service._authenticate(device, _point(code=gps_totp.totp(secret, int(time.time()))))


def test_brute_force_locks_device_even_for_the_right_code():
    secret = gps_totp.generate_secret()
    device = _device(secret)
    for _ in range(gps_service.settings.gps_totp_max_failures):
        with pytest.raises(ProtocolError):
            gps_service._authenticate(device, _point(code="00000000"))
    with pytest.raises(ProtocolError) as e:
        gps_service._authenticate(device, _point(code=gps_totp.totp(secret, int(time.time()))))
    assert "приостановлена" in e.value.detail


def test_secret_encrypted_with_other_key_is_reported_not_crashed():
    device = _device()
    device.totp_secret_enc = gps_totp.encrypt_secret(gps_totp.generate_secret(), "другой ключ")
    with pytest.raises(ProtocolError) as e:
        gps_service._authenticate(device, _point(code="12345678"))
    assert e.value.code == ERR_AUTH


def test_static_token_still_works_for_devices_without_totp():
    token = "0123456789abcdef0123456789abcdef"
    device = _device(token_hash=gps_service.hash_token(token))
    gps_service._authenticate(device, _point(token=token))
    with pytest.raises(ProtocolError):
        gps_service._authenticate(device, _point())


def test_device_without_credentials_accepts_plain_points():
    # Уже прошитые трекеры без кода продолжают работать, пока секрет не выдан.
    gps_service._authenticate(_device(), _point())
