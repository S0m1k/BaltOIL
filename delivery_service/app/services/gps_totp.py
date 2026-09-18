"""TOTP для GPS-трекеров (спринт 2026-09-19) и хранение секрета.

Трекер доказывает, что он — это он, кодом TOTP (RFC 6238): HMAC-SHA1 от
секрета устройства и номера 30-секундного шага, 8 цифр. Время трекер берёт
с GPS, так что часы у него точные без отдельной синхронизации. Координаты
не подписываются — решено с разработчиком прошивки: от сканеров и подделки
по номеру устройства хватает кода, а сговор с оператором связи вне модели
угроз.

8 цифр, а не привычные 6: приёмник открыт в интернет, и 6-значный код при
допуске ±1 шаг перебирается примерно за сутки с одного IP.

Всё на стандартной библиотеке: у прод-сервера нет доступа к PyPI, а
`cryptography` в образе delivery_service нет.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct

TOTP_DIGITS = 8
TOTP_PERIOD_SEC = 30
# ±1 шаг: часы трекера (GPS) точные, запас нужен на задержку отправки по 2G
# и на границу шага, а не на дрейф.
TOTP_WINDOW_STEPS = 1
SECRET_BYTES = 20  # 160 бит — рекомендация RFC 4226 для HMAC-SHA1

_CIPHER_VERSION = b"g1"
_NONCE_BYTES = 16
_TAG_BYTES = 16


# ── TOTP ─────────────────────────────────────────────────────────────────────

def hotp(secret: bytes, counter: int, digits: int = TOTP_DIGITS) -> str:
    """HOTP по RFC 4226: HMAC-SHA1 → динамическое усечение → остаток."""
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def totp(secret: bytes, unix_time: int, digits: int = TOTP_DIGITS,
         period: int = TOTP_PERIOD_SEC) -> str:
    return hotp(secret, unix_time // period, digits)


def verify_totp(secret: bytes, code: str, unix_time: int,
                window: int = TOTP_WINDOW_STEPS) -> bool:
    """Код подходит к текущему шагу или к соседним в пределах окна.

    Повторное использование кода внутри шага не запрещаем: трекер может
    слать точки чаще раза в 30 секунд, и все они несут один и тот же код.
    """
    if not code or not code.isdigit() or len(code) != TOTP_DIGITS:
        return False
    step = unix_time // TOTP_PERIOD_SEC
    return any(
        hmac.compare_digest(hotp(secret, step + delta), code)
        for delta in range(-window, window + 1)
    )


def generate_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def secret_formats(secret: bytes) -> dict:
    """Секрет в видах, удобных для прошивки и для проверки на телефоне."""
    return {
        "hex": secret.hex(),
        "base32": base64.b32encode(secret).decode().rstrip("="),
        "arduino": "const uint8_t TOTP_SECRET[20] = {"
                   + ", ".join(f"0x{b:02X}" for b in secret) + "};",
        "digits": TOTP_DIGITS,
        "period": TOTP_PERIOD_SEC,
    }


# ── Хранение секрета ─────────────────────────────────────────────────────────
# В отличие от статического токена, секрет TOTP нужен серверу в исходном
# виде — отпечаток sha256 для проверки не годится. Поэтому в БД он лежит
# зашифрованным: утёкший дамп или бэкап без ключа из .env секретов не отдаёт.
#
# Шифр — HMAC-SHA256 в режиме счётчика (как расширение в HKDF) плюс
# HMAC-тег поверх (encrypt-then-MAC). Для 20-байтного секрета этого
# достаточно; Fernet/AES взяли бы, будь в образе `cryptography`.

class SecretDecryptError(Exception):
    """Секрет не расшифровывается — сменился ключ или запись повреждена."""


def _subkeys(master_key: str) -> tuple[bytes, bytes]:
    base = hashlib.sha256(("baltoil-gps-totp|" + master_key).encode()).digest()
    enc = hmac.new(base, b"enc", hashlib.sha256).digest()
    mac = hmac.new(base, b"mac", hashlib.sha256).digest()
    return enc, mac


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(enc_key, nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def encrypt_secret(secret: bytes, master_key: str) -> str:
    enc_key, mac_key = _subkeys(master_key)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    body = bytes(a ^ b for a, b in zip(secret, _keystream(enc_key, nonce, len(secret))))
    tag = hmac.new(mac_key, _CIPHER_VERSION + nonce + body, hashlib.sha256).digest()[:_TAG_BYTES]
    blob = _CIPHER_VERSION + nonce + body + tag
    return base64.urlsafe_b64encode(blob).decode()


def decrypt_secret(token: str, master_key: str) -> bytes:
    try:
        blob = base64.urlsafe_b64decode(token.encode())
    except (ValueError, TypeError) as e:
        raise SecretDecryptError("битая запись секрета") from e
    head = len(_CIPHER_VERSION)
    if len(blob) <= head + _NONCE_BYTES + _TAG_BYTES or blob[:head] != _CIPHER_VERSION:
        raise SecretDecryptError("неизвестный формат секрета")
    nonce = blob[head:head + _NONCE_BYTES]
    body = blob[head + _NONCE_BYTES:-_TAG_BYTES]
    tag = blob[-_TAG_BYTES:]
    enc_key, mac_key = _subkeys(master_key)
    expected = hmac.new(mac_key, blob[:head] + nonce + body, hashlib.sha256).digest()[:_TAG_BYTES]
    if not hmac.compare_digest(tag, expected):
        raise SecretDecryptError("ключ не подходит к секрету")
    return bytes(a ^ b for a, b in zip(body, _keystream(enc_key, nonce, len(body))))
