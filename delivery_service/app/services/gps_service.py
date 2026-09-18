"""Приём точек GPS и выборки для карты.

Приём принципиально отличается от остального API: запрос приходит не от
человека с JWT, а от трекера в поле — без авторизации, без TLS, с возможным
мусором в теле. Поэтому здесь всё построено на «не потерять данные, но и не
дать себя завалить»: строгая валидация формата, антифлуд по устройству,
автозаведение неизвестного номера с потолком и кольцевой журнал сырых
сообщений для диагностики.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.gps import GpsDevice, GpsPosition
from app.models.vehicle import Vehicle
from app.services import gps_protocol as proto
from app.services import gps_totp
from app.services.gps_protocol import ParsedPoint, ProtocolError

logger = logging.getLogger(__name__)
settings = get_settings()

_rate_limiter = proto.RateLimiter(settings.gps_min_interval_sec)
# Отдельный лимитер на «контакт без точки» (нет фикса): эта ветка не доходит до
# сохранения, а базу дёргает — без своего лимита её можно было бы долбить.
_contact_limiter = proto.RateLimiter(settings.gps_min_interval_sec)
# Новые устройства заводятся редко и вручную. Чаще раза в минуту с одного
# адреса — это не сборка трекеров, а перебор номеров, чтобы выжечь потолок
# автозаведения и заблокировать регистрацию настоящих машин.
_register_limiter = proto.RateLimiter(60.0)
# Перебор кода TOTP: после N неверных кодов за окно трекер не проверяется.
_totp_throttle = proto.FailureThrottle(
    settings.gps_totp_max_failures, settings.gps_totp_failure_window_sec
)

# Значения токенов не должны оседать в журнале сырых сообщений.
_TOKENISH_KEY = re.compile(r"(?i)\b(token|key|secret|auth)\s*[=:]\s*[^&;,\s\"']+")
_TOKENISH_HEX = re.compile(r"\b[0-9a-fA-F]{16,64}\b")

# Кольцевой журнал последних сообщений — и принятых, и отвергнутых. Нужен, пока
# точный формат трекера не зафиксирован: админ открывает вкладку «Трекеры» и
# видит сырьё ровно так, как его прислало устройство.
RAW_LOG_SIZE = 200
_raw_log: deque[dict] = deque(maxlen=RAW_LOG_SIZE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mask_secrets(payload: str) -> str:
    """Прячет токены в сыром сообщении перед записью в журнал."""
    masked = _TOKENISH_KEY.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=***", payload or "")
    return _TOKENISH_HEX.sub("***", masked)


def allow_contact(device_number: str) -> bool:
    """Антифлуд для отметки «трекер жив» (точка не сохраняется)."""
    return _contact_limiter.allow(device_number, time.monotonic())


def log_raw(source: str, payload: str, result: str, detail: str = "", device: str = "") -> None:
    _raw_log.appendleft({
        "at": _now(),
        "source": source[:45],
        "payload": mask_secrets(payload or "")[:400],
        "result": result,
        "detail": detail[:200],
        "device": device[:32],
    })


def raw_log() -> list[dict]:
    return list(_raw_log)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_hex(16)


# ── Приём точки ──────────────────────────────────────────────────────────────

async def ingest_point(db: AsyncSession, point: ParsedPoint, *, source: str) -> GpsPosition:
    """Сохраняет разобранную точку. Бросает ProtocolError с кодом для трекера."""
    if not settings.gps_enabled:
        raise ProtocolError(proto.ERR_INACTIVE, "приём точек выключен")

    device = await _resolve_device(db, point, source)

    _authenticate(device, point)
    if not device.is_active:
        raise ProtocolError(proto.ERR_INACTIVE, "трекер отключён в админке")

    # Отметку «на связи» ставим до антифлуда: даже слишком частые пакеты
    # доказывают, что устройство живо.
    device.last_seen_at = _now()

    if not _rate_limiter.allow(str(device.id), time.monotonic()):
        await db.commit()
        raise ProtocolError(proto.ERR_RATE, "слишком часто")

    recorded_at = point.recorded_at or _now()
    accuracy = proto.accuracy_for_sats(point.sats)

    position = GpsPosition(
        device_id=device.id,
        vehicle_id=device.vehicle_id,
        recorded_at=recorded_at,
        lat=point.lat,
        lon=point.lon,
        sats=point.sats,
        accuracy_m=accuracy,
        speed_kmh=point.speed_kmh,
    )
    db.add(position)

    device.last_fix_at = recorded_at
    device.last_lat = point.lat
    device.last_lon = point.lon
    device.last_sats = point.sats
    device.last_speed_kmh = point.speed_kmh

    await db.commit()
    await db.refresh(position)
    log_raw(source, f"{point.device} {point.lat} {point.lon} {point.sats}",
            "ok", "", point.device)
    return position


def _authenticate(device: GpsDevice, point: ParsedPoint) -> None:
    """Подтверждение, что точку прислал именно этот трекер.

    Порядок: TOTP → статический токен → ничего (старые прошивки, риск принят).
    У трекера с секретом TOTP точки без верного кода не принимаются вовсе.
    """
    if device.totp_secret_enc:
        key = str(device.id)
        now_mono = time.monotonic()
        if _totp_throttle.is_blocked(key, now_mono):
            raise ProtocolError(proto.ERR_AUTH, "много неверных кодов — проверка приостановлена")
        try:
            secret = gps_totp.decrypt_secret(device.totp_secret_enc, settings.gps_secret_master_key)
        except gps_totp.SecretDecryptError:
            logger.error("GPS: секрет TOTP трекера %s не расшифровывается — ключ в .env "
                         "сменился? Перевыдайте секрет в админке", device.device_number)
            raise ProtocolError(proto.ERR_AUTH, "секрет трекера не расшифровывается")
        if not point.code:
            # Без кода — прошивка старая. В счётчик перебора не идёт: подобрать
            # так ничего нельзя, а блокировать трекер из-за этого незачем.
            raise ProtocolError(proto.ERR_AUTH, "нет кода TOTP")
        if not gps_totp.verify_totp(secret, point.code, int(time.time())):
            _totp_throttle.record_failure(key, now_mono)
            raise ProtocolError(proto.ERR_AUTH, "неверный или просроченный код TOTP")
        return

    if device.token_hash and hash_token(point.token or "") != device.token_hash:
        raise ProtocolError(proto.ERR_AUTH, "неверный токен устройства")


async def mark_seen(db: AsyncSession, device_number: str) -> None:
    """Трекер вышел на связь, но точка непригодна (нет фикса).

    Отмечаем контакт: на карте это «трекер живой, спутников не видит» —
    иначе такая машина выглядит как потерянная.
    """
    result = await db.execute(select(GpsDevice).where(GpsDevice.device_number == device_number))
    device = result.scalar_one_or_none()
    if device:
        device.last_seen_at = _now()
        await db.commit()


async def _resolve_device(db: AsyncSession, point: ParsedPoint, source: str) -> GpsDevice:
    result = await db.execute(
        select(GpsDevice).where(GpsDevice.device_number == point.device)
    )
    device = result.scalar_one_or_none()
    if device:
        return device

    if not settings.gps_auto_register:
        raise ProtocolError(proto.ERR_AUTH, "трекер не зарегистрирован")

    # Перебор новых номеров с одного адреса режем до обращения к БД: иначе
    # потолок автозаведения выжигается за секунды, и настоящий новый трекер
    # получает отказ. Настоящая сборка трекеров так быстро не происходит.
    if not _register_limiter.allow("reg:" + source, time.monotonic()):
        raise ProtocolError(proto.ERR_AUTH, "слишком много новых устройств с одного адреса")

    # Потолок на самозаведение: без него любой сканер интернета, случайно
    # попавший в формат, наплодит устройств.
    auto_count = await db.scalar(
        select(func.count()).select_from(GpsDevice).where(GpsDevice.auto_registered.is_(True))
    )
    # Проверка и вставка не атомарны: при одновременных запросах с разных
    # адресов потолок можно немного перескочить. Живём с этим — лимитер выше
    # уже режет перебор, а точное значение потолка здесь не принципиально.
    if (auto_count or 0) >= settings.gps_max_auto_devices:
        raise ProtocolError(proto.ERR_AUTH, "лимит автозаведения исчерпан")

    device = GpsDevice(
        device_number=point.device,
        auto_registered=True,
        is_active=True,
        label=None,
    )
    db.add(device)
    try:
        await db.commit()
    except IntegrityError:
        # Гонка двух точек одного нового трекера — второй просто перечитывает.
        await db.rollback()
        result = await db.execute(
            select(GpsDevice).where(GpsDevice.device_number == point.device)
        )
        device = result.scalar_one_or_none()
        if device is None:
            raise ProtocolError(proto.ERR_AUTH, "трекер не зарегистрирован")
        return device
    await db.refresh(device)
    logger.info("GPS: автозаведён трекер %s", point.device)
    return device


# ── Чтение для карты ─────────────────────────────────────────────────────────

def device_status(last_seen_at: datetime | None, now: datetime | None = None) -> str:
    now = now or _now()
    if last_seen_at is None:
        return "never"
    minutes = (now - last_seen_at).total_seconds() / 60
    if minutes <= settings.gps_online_minutes:
        return "online"
    if minutes <= settings.gps_stale_minutes:
        return "stale"
    return "offline"


async def list_devices(db: AsyncSession) -> list[dict]:
    """Трекеры + привязанная машина + последняя точка, для списка и карты."""
    result = await db.execute(
        select(GpsDevice, Vehicle)
        .outerjoin(Vehicle, Vehicle.id == GpsDevice.vehicle_id)
        .order_by(GpsDevice.auto_registered.desc(), GpsDevice.device_number)
    )
    now = _now()
    out: list[dict] = []
    for device, vehicle in result.all():
        out.append(_device_dict(device, vehicle, now))
    return out


def _device_dict(device: GpsDevice, vehicle: Vehicle | None, now: datetime) -> dict:
    return {
        "id": device.id,
        "device_number": device.device_number,
        "label": device.label,
        "sim_phone": device.sim_phone,
        "notes": device.notes,
        "is_active": device.is_active,
        "auto_registered": device.auto_registered,
        "has_token": device.token_hash is not None,
        "has_totp": device.totp_secret_enc is not None,
        "vehicle_id": device.vehicle_id,
        "vehicle_plate": vehicle.plate_number if vehicle else None,
        "vehicle_model": vehicle.model if vehicle else None,
        "status": device_status(device.last_seen_at, now),
        "last_seen_at": device.last_seen_at,
        "last_fix_at": device.last_fix_at,
        "last_lat": device.last_lat,
        "last_lon": device.last_lon,
        "last_sats": device.last_sats,
        "last_speed_kmh": device.last_speed_kmh,
        "accuracy_m": proto.accuracy_for_sats(device.last_sats) if device.last_sats is not None else None,
        "quality": proto.quality_for_sats(device.last_sats) if device.last_sats is not None else "no_fix",
        "created_at": device.created_at,
    }


async def live_positions(db: AsyncSession) -> list[dict]:
    """Только те трекеры, у которых есть координаты, — для карты «Сейчас»."""
    devices = await list_devices(db)
    return [d for d in devices if d["last_lat"] is not None and d["last_lon"] is not None]


async def get_device(db: AsyncSession, device_id: uuid.UUID) -> GpsDevice:
    result = await db.execute(select(GpsDevice).where(GpsDevice.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise NotFoundError("Трекер не найден")
    return device


@dataclass(frozen=True)
class IssuedCredentials:
    """Секреты, которые показываются админу один раз — в БД их не прочитать."""

    token: str | None = None
    totp: dict | None = None  # gps_totp.secret_formats(...)


def _issue_totp(device: GpsDevice) -> dict:
    secret = gps_totp.generate_secret()
    device.totp_secret_enc = gps_totp.encrypt_secret(secret, settings.gps_secret_master_key)
    return gps_totp.secret_formats(secret)


async def create_device(
    db: AsyncSession, *, device_number: str, label: str | None,
    vehicle_id: uuid.UUID | None, sim_phone: str | None, notes: str | None,
    with_token: bool, with_totp: bool = False,
) -> tuple[GpsDevice, IssuedCredentials]:
    """Заводит трекер вручную. Токен и секрет TOTP возвращаются один раз."""
    number = (device_number or "").strip()
    if not number:
        raise ValidationError("Укажите номер устройства")
    if not proto.is_valid_device_number(number):
        raise ValidationError("Номер устройства: латиница, цифры, «-», «_», «.», «:» до 32 символов")

    exists = await db.execute(select(GpsDevice).where(GpsDevice.device_number == number))
    if exists.scalar_one_or_none():
        raise ConflictError(f"Трекер с номером {number} уже заведён")

    if vehicle_id is not None:
        await _assert_vehicle_free(db, vehicle_id, exclude_device_id=None)

    token = new_token() if with_token else None
    device = GpsDevice(
        device_number=number,
        label=(label or None),
        vehicle_id=vehicle_id,
        sim_phone=(sim_phone or None),
        notes=(notes or None),
        token_hash=hash_token(token) if token else None,
        auto_registered=False,
    )
    totp = _issue_totp(device) if with_totp else None
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device, IssuedCredentials(token=token, totp=totp)


async def update_device(
    db: AsyncSession, device_id: uuid.UUID, data: dict
) -> tuple[GpsDevice, IssuedCredentials]:
    """Правка трекера. Возвращает новые токен/секрет, если их перевыдали."""
    device = await get_device(db, device_id)

    if "vehicle_id" in data:
        vehicle_id = data["vehicle_id"]
        if vehicle_id is not None:
            await _assert_vehicle_free(db, vehicle_id, exclude_device_id=device.id)
        device.vehicle_id = vehicle_id

    for field in ("label", "sim_phone", "notes"):
        if field in data:
            value = data[field]
            setattr(device, field, (value or None))
    if "is_active" in data and data["is_active"] is not None:
        device.is_active = bool(data["is_active"])

    # Подтверждение: админ увидел новый трекер и признал его своим.
    if data.get("confirm"):
        device.auto_registered = False

    token: str | None = None
    if data.get("rotate_token"):
        token = new_token()
        device.token_hash = hash_token(token)
    elif data.get("drop_token"):
        device.token_hash = None

    # Перевыдача секрета сразу отключает старый: трекер со старой прошивкой
    # получает ERR:AUTH, пока в него не зальют новый массив.
    totp: dict | None = None
    if data.get("enable_totp"):
        totp = _issue_totp(device)
    elif data.get("disable_totp"):
        device.totp_secret_enc = None

    await db.commit()
    await db.refresh(device)
    return device, IssuedCredentials(token=token, totp=totp)


async def delete_device(db: AsyncSession, device_id: uuid.UUID) -> None:
    device = await get_device(db, device_id)
    await db.delete(device)  # позиции уходят каскадом
    await db.commit()


async def _assert_vehicle_free(
    db: AsyncSession, vehicle_id: uuid.UUID, *, exclude_device_id: uuid.UUID | None
) -> None:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.is_archived:
        raise NotFoundError("Транспортное средство не найдено")
    query = select(GpsDevice).where(GpsDevice.vehicle_id == vehicle_id)
    if exclude_device_id is not None:
        query = query.where(GpsDevice.id != exclude_device_id)
    other = (await db.execute(query)).scalar_one_or_none()
    if other is not None:
        raise ConflictError(
            f"К этой машине уже привязан трекер {other.device_number} — сначала отвяжите его"
        )


# ── Трек за период ───────────────────────────────────────────────────────────

MAX_RANGE_DAYS = 31


async def get_track(
    db: AsyncSession,
    *,
    device_id: uuid.UUID | None,
    vehicle_id: uuid.UUID | None,
    date_from: datetime,
    date_to: datetime,
) -> dict:
    if device_id is None and vehicle_id is None:
        raise ValidationError("Укажите трекер или машину")
    if date_to <= date_from:
        raise ValidationError("Конец периода должен быть позже начала")
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise ValidationError(f"Период не больше {MAX_RANGE_DAYS} дней")
    # Сутки +1: самая ранняя доступная дата начинается за 31 день до «сейчас»
    # минус часовой пояс, и без запаса она бы упиралась в эту же границу.
    if date_from < _now() - timedelta(days=settings.gps_retention_days + 1):
        raise ValidationError(
            f"История хранится {settings.gps_retention_days} дней — более ранние точки удалены"
        )

    query = select(GpsPosition).where(
        GpsPosition.recorded_at >= date_from,
        GpsPosition.recorded_at < date_to,
    ).order_by(GpsPosition.recorded_at)
    if device_id is not None:
        query = query.where(GpsPosition.device_id == device_id)
    else:
        query = query.where(GpsPosition.vehicle_id == vehicle_id)

    rows = list((await db.execute(query)).scalars().all())
    points = [
        {
            "recorded_at": p.recorded_at,
            "lat": float(p.lat),
            "lon": float(p.lon),
            "sats": p.sats,
            "accuracy_m": p.accuracy_m,
            "speed_kmh": float(p.speed_kmh) if p.speed_kmh is not None else None,
        }
        for p in rows
    ]

    # Сводку считаем по всем точкам, а отдаём прореженные: иначе пробег
    # зависел бы от того, сколько точек влезло в ответ.
    summary = proto.track_summary(points)
    shown = proto.downsample(points, settings.gps_max_track_points)
    summary["shown_points"] = len(shown)
    return {"points": shown, "summary": summary}


# ── Чистка истории ───────────────────────────────────────────────────────────

async def purge_old_positions(db: AsyncSession) -> int:
    cutoff = _now() - timedelta(days=settings.gps_retention_days)
    result = await db.execute(delete(GpsPosition).where(GpsPosition.recorded_at < cutoff))
    await db.commit()
    return result.rowcount or 0


async def purge_loop() -> None:
    """Раз в сутки чистит историю глубже срока хранения.

    Первый прогон — через минуту после старта, чтобы рестарт сервиса не
    упирался в тяжёлый DELETE на старте.
    """
    from app.database import AsyncSessionLocal

    await asyncio.sleep(60)
    while True:
        try:
            async with AsyncSessionLocal() as session:
                removed = await purge_old_positions(session)
            if removed:
                logger.info("GPS: удалено %s устаревших точек", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Чистка — фоновая гигиена: падать из-за неё сервису незачем.
            logger.exception("GPS: чистка истории не удалась")
        await asyncio.sleep(24 * 3600)
