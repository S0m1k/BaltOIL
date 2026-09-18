"""GPS-мониторинг: приём точек от трекеров и данные для карты.

Два разных по природе куска в одном роутере:

* `/gps/ingest` — открытая ручка для трекеров. Без JWT (модем его не осилит),
  отвечает коротким текстом `OK` / `ERR:<код>` и никогда не отдаёт 5xx на
  кривые данные: трекер на ошибку всё равно ничего умного не сделает, а
  бесконечные ретраи сожгут трафик на SIM-карте.
* остальное — админка карты, обычный JWT и роль admin.
"""
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import CurrentUser, require_roles, ROLE_ADMIN
from app.core.exceptions import ValidationError
from app.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.gps import (
    GpsDeviceCreateRequest, GpsDeviceCreated, GpsDeviceResponse,
    GpsDeviceUpdateRequest, GpsRawMessage, GpsTrackResponse,
)
from app.services import gps_protocol as proto
from app.services import gps_service

router = APIRouter(prefix="/gps", tags=["gps"])
settings = get_settings()

# Карту транспорта смотрит администратор — как и договаривались по спринту.
AdminOnly = Annotated[CurrentUser, Depends(require_roles(ROLE_ADMIN))]

# Тело запроса от трекера: больше этого не читаем, чтобы мусорный поток не
# раздувал память.
_MAX_BODY_BYTES = 4096


# ── Приём точек (без авторизации) ────────────────────────────────────────────

@router.api_route("/ingest", methods=["POST", "GET", "PUT"], response_class=PlainTextResponse)
async def ingest(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    """Принимает одну точку: «номер широта долгота спутники».

    Формат намеренно всеядный (текст, JSON, форма, query) — прошивка уже
    залита в устройства, подстраивается сервер, а не трекер.
    """
    source = _client_ip(request)

    # Выключатель приёма проверяем до любых обращений к БД: иначе поток мусора
    # дёргал бы базу даже при выключенном GPS.
    if not settings.gps_enabled:
        return PlainTextResponse(f"ERR:{proto.ERR_INACTIVE}\n", status_code=200)

    raw_body = await _read_capped_body(request)
    if raw_body is None:
        gps_service.log_raw(source, "<тело больше лимита>", proto.ERR_BADFMT, "слишком большое тело")
        return PlainTextResponse(f"ERR:{proto.ERR_BADFMT}\n", status_code=413)

    text = raw_body.decode("utf-8", "replace").strip()
    query = dict(request.query_params)
    payload_for_log = text or (json.dumps(query, ensure_ascii=False) if query else "")

    try:
        point = _parse_request(text, query, request.headers.get("content-type", ""))
    except proto.ProtocolError as e:
        gps_service.log_raw(source, payload_for_log, e.code, e.detail)
        # Трекер жив, но фикса нет — отмечаем контакт, если номер разобрать
        # всё-таки удалось. Через тот же антифлуд: поток «нет фикса» иначе давал
        # бы неограниченный UPDATE в БД в обход всех лимитов.
        if e.code == proto.ERR_NOFIX:
            device_hint = _device_hint(text, query)
            if device_hint and gps_service.allow_contact(device_hint):
                await gps_service.mark_seen(db, device_hint)
        return PlainTextResponse(f"ERR:{e.code}\n", status_code=200)

    try:
        await gps_service.ingest_point(db, point, source=source)
    except proto.ProtocolError as e:
        gps_service.log_raw(source, payload_for_log, e.code, e.detail, point.device)
        return PlainTextResponse(f"ERR:{e.code}\n", status_code=200)

    return PlainTextResponse("OK\n", status_code=200)


async def _read_capped_body(request: Request) -> bytes | None:
    """Читает тело, обрывая чтение на лимите. None — тело слишком большое.

    `request.body()` втянул бы в память всё, что пропустил nginx, а лимит
    применялся бы уже после чтения — на открытом в интернет порту так нельзя.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _client_ip(request: Request) -> str:
    """Реальный адрес отправителя.

    nginx ДОПИСЫВАЕТ адрес клиента в конец X-Forwarded-For, а левую часть
    цепочки полностью контролирует отправитель — берём последний элемент,
    иначе в журнале приёма оказывался бы адрес, который придумал атакующий.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "?"


def _parse_request(text: str, query: dict, content_type: str) -> proto.ParsedPoint:
    """Разбирает точку из тела или из query-параметров.

    Content-Type не смотрим намеренно: модемы ставят его как попало (часто
    text/plain на JSON-теле), а разбор всё равно определяет вид по содержимому.
    """
    if text:
        return proto.parse_line(text)
    if query:
        return proto.parse_mapping(query)
    raise proto.ProtocolError(proto.ERR_BADFMT, "пустой запрос")


def _device_hint(text: str, query: dict) -> str:
    """Номер устройства из сообщения, которое не удалось разобрать целиком."""
    for key in ("device", "device_id", "id", "node", "imei", "dev"):
        if key in query and str(query[key]).strip():
            candidate = str(query[key]).strip()
            return candidate if proto.is_valid_device_number(candidate) else ""
    first = text.replace(",", " ").split()
    if first and proto.is_valid_device_number(first[0]):
        return first[0]
    return ""


# ── Админка: трекеры ─────────────────────────────────────────────────────────

@router.get("/devices", response_model=list[GpsDeviceResponse])
async def list_devices(current_user: AdminOnly, db: Annotated[AsyncSession, Depends(get_db)]):
    return await gps_service.list_devices(db)


@router.post("/devices", response_model=GpsDeviceCreated, status_code=201)
async def create_device(
    data: GpsDeviceCreateRequest,
    current_user: AdminOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    device, issued = await gps_service.create_device(
        db,
        device_number=data.device_number,
        label=data.label,
        vehicle_id=data.vehicle_id,
        sim_phone=data.sim_phone,
        notes=data.notes,
        with_token=data.with_token,
        with_totp=data.with_totp,
    )
    return await _created(db, device, issued)


@router.patch("/devices/{device_id}", response_model=GpsDeviceCreated)
async def update_device(
    device_id: uuid.UUID,
    data: GpsDeviceUpdateRequest,
    current_user: AdminOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    device, issued = await gps_service.update_device(
        db, device_id, data.model_dump(exclude_unset=True)
    )
    return await _created(db, device, issued)


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: uuid.UUID,
    current_user: AdminOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await gps_service.delete_device(db, device_id)


async def _created(db: AsyncSession, device, issued: gps_service.IssuedCredentials) -> dict:
    vehicle = await db.get(Vehicle, device.vehicle_id) if device.vehicle_id else None
    return {
        "device": gps_service._device_dict(device, vehicle, datetime.now(timezone.utc)),
        "token": issued.token,
        "totp": issued.totp,
    }


# ── Админка: карта ───────────────────────────────────────────────────────────

@router.get("/live", response_model=list[GpsDeviceResponse])
async def live(current_user: AdminOnly, db: Annotated[AsyncSession, Depends(get_db)]):
    """Текущие позиции — то, что рисуется на карте в режиме «Сейчас»."""
    return await gps_service.live_positions(db)


@router.get("/track", response_model=GpsTrackResponse)
async def track(
    current_user: AdminOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
    device_id: uuid.UUID | None = Query(default=None),
    vehicle_id: uuid.UUID | None = Query(default=None),
    date: str | None = Query(default=None, description="YYYY-MM-DD, сутки по местному времени"),
    tz_offset_minutes: int = Query(default=180, ge=-840, le=840, description="Смещение часового пояса клиента"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
):
    """Маршрут за сутки (`date`) или за произвольный период (`date_from`/`date_to`)."""
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError("Дата в формате ГГГГ-ММ-ДД")
        # Сутки считаем по времени пользователя: «маршрут за 12 сентября» —
        # это его 00:00–24:00, а не UTC-сутки.
        shift = timedelta(minutes=tz_offset_minutes)
        start = datetime.combine(day, time.min, tzinfo=timezone.utc) - shift
        end = start + timedelta(days=1)
    else:
        if not date_from or not date_to:
            raise ValidationError("Укажите дату или период")
        start = date_from if date_from.tzinfo else date_from.replace(tzinfo=timezone.utc)
        end = date_to if date_to.tzinfo else date_to.replace(tzinfo=timezone.utc)

    return await gps_service.get_track(
        db, device_id=device_id, vehicle_id=vehicle_id, date_from=start, date_to=end
    )


@router.get("/raw", response_model=list[GpsRawMessage])
async def raw_messages(current_user: AdminOnly):
    """Последние сообщения как есть — диагностика приёма без доступа к логам."""
    return gps_service.raw_log()
