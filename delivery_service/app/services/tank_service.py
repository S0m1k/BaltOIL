"""Ёмкости хранения топлива со счётчиками колонок (правки 2026-07-14).

Права:
- смотреть ёмкости и журнал — водитель/менеджер/админ;
- создавать/переименовывать/корректировать — только админ;
- приход в ёмкость, выдача по заявке, переливы — водитель/менеджер/админ.

Счётчик — шестизначный (0..999999), при выдаче водитель вводит НОВОЕ
показание; списанные литры = разница показаний (с переполнением через
999999 → 0). Остаток ёмкости может уходить в минус: продажа разрешена
даже при пустом складе.

Журнал tank_transactions — append-only: править записи нельзя никому,
ошибки исправляются корректировкой админа (kind=adjust).
"""
import logging
import uuid
from datetime import datetime

import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import TokenUser, ROLE_ADMIN, ROLE_MANAGER, ROLE_DRIVER
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.fuel_tank import FuelTank, TankTransaction, TankTxKind, TANK_COUNTER_MODULUS
from app.schemas.tank import (
    TankCreate, TankUpdate, TankAdjust, TankArrival, TankIssue, TankTransfer,
    TankResponse, TankTxResponse,
)
from app.services import fuel_catalog

log = logging.getLogger(__name__)


def _require_view(actor: TokenUser) -> None:
    if actor.role not in (ROLE_DRIVER, ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Требуется роль водителя, менеджера или администратора")


def _require_admin(actor: TokenUser) -> None:
    if actor.role != ROLE_ADMIN:
        raise ForbiddenError("Доступно только администратору")


async def _resolve_actor_name(actor_id: uuid.UUID) -> str | None:
    """ФИО актора из auth_service — fail-open: без имени операция не блокируется."""
    _settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{_settings.auth_service_url}/api/v1/internal/users/{actor_id}/profile",
                headers={"X-Internal-Secret": _settings.internal_api_secret},
            )
        if r.status_code == 200:
            return r.json().get("full_name")
    except Exception as exc:
        log.warning("tank: actor name lookup failed (non-fatal): %s", exc)
    return None


async def _get_tank_locked(db: AsyncSession, tank_id: uuid.UUID) -> FuelTank:
    """Ёмкость под FOR UPDATE — защита от параллельных списаний."""
    result = await db.execute(
        select(FuelTank).where(FuelTank.id == tank_id).with_for_update()
    )
    tank = result.scalar_one_or_none()
    if tank is None:
        raise NotFoundError("Ёмкость не найдена")
    return tank


async def _tank_response(tank: FuelTank, labels: dict[str, str] | None = None) -> TankResponse:
    if labels is None:
        labels = await fuel_catalog.get_fuel_labels()
    return TankResponse(
        id=tank.id,
        name=tank.name,
        fuel_type=tank.fuel_type,
        fuel_label=labels.get(tank.fuel_type, tank.fuel_type),
        current_volume=float(tank.current_volume),
        counter=int(tank.counter),
        is_active=tank.is_active,
        updated_at=tank.updated_at,
    )


# ── Просмотр ─────────────────────────────────────────────────────────────────

async def list_tanks(
    db: AsyncSession, actor: TokenUser, *, include_inactive: bool = False
) -> list[TankResponse]:
    _require_view(actor)
    conditions = []
    if not include_inactive:
        conditions.append(FuelTank.is_active == True)  # noqa: E712
    stmt = select(FuelTank).order_by(FuelTank.fuel_type, FuelTank.name)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    tanks = list((await db.execute(stmt)).scalars().all())
    labels = await fuel_catalog.get_fuel_labels()
    return [await _tank_response(t, labels) for t in tanks]


async def list_transactions(
    db: AsyncSession,
    actor: TokenUser,
    *,
    tank_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 200,
) -> list[TankTxResponse]:
    """Журнал операций: ёмкость, объём, было → стало, кто (для отчёта)."""
    _require_view(actor)
    conditions = []
    if tank_id:
        conditions.append(TankTransaction.tank_id == tank_id)
    if date_from:
        conditions.append(TankTransaction.created_at >= date_from)
    if date_to:
        conditions.append(TankTransaction.created_at <= date_to)
    stmt = select(TankTransaction).order_by(TankTransaction.created_at.desc()).limit(limit)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    txs = list((await db.execute(stmt)).scalars().all())

    # Имена ёмкостей для журнала (включая скрытые и второй конец перелива)
    tank_names: dict[uuid.UUID, str] = {
        t.id: t.name
        for t in (await db.execute(select(FuelTank))).scalars().all()
    }
    return [
        TankTxResponse(
            id=tx.id,
            tank_id=tx.tank_id,
            tank_name=tank_names.get(tx.tank_id),
            kind=tx.kind.value,
            volume=float(tx.volume),
            counter_before=int(tx.counter_before) if tx.counter_before is not None else None,
            counter_after=int(tx.counter_after) if tx.counter_after is not None else None,
            order_id=tx.order_id,
            order_number=tx.order_number,
            peer_tank_id=tx.peer_tank_id,
            peer_tank_name=tank_names.get(tx.peer_tank_id) if tx.peer_tank_id else None,
            actor_id=tx.actor_id,
            actor_name=tx.actor_name,
            notes=tx.notes,
            created_at=tx.created_at,
        )
        for tx in txs
    ]


# ── Управление (admin) ───────────────────────────────────────────────────────

async def create_tank(db: AsyncSession, data: TankCreate, actor: TokenUser) -> TankResponse:
    _require_admin(actor)
    labels = await fuel_catalog.get_fuel_labels()
    if data.fuel_type not in labels:
        raise ValidationError(f"Неизвестный вид топлива: {data.fuel_type!r}")
    tank = FuelTank(
        name=data.name.strip(),
        fuel_type=data.fuel_type,
        current_volume=data.initial_volume,
        counter=data.counter,
        is_active=True,
    )
    db.add(tank)
    await db.flush()
    if data.initial_volume > 0:
        db.add(TankTransaction(
            tank_id=tank.id,
            kind=TankTxKind.ADJUST,
            volume=data.initial_volume,
            counter_before=data.counter,
            counter_after=data.counter,
            actor_id=actor.id,
            actor_name=await _resolve_actor_name(actor.id),
            notes="Начальный остаток при создании ёмкости",
        ))
        await db.flush()
    return await _tank_response(tank, labels)


async def update_tank(
    db: AsyncSession, tank_id: uuid.UUID, data: TankUpdate, actor: TokenUser
) -> TankResponse:
    _require_admin(actor)
    tank = await _get_tank_locked(db, tank_id)
    if data.name is not None:
        tank.name = data.name.strip()
    if data.fuel_type is not None:
        labels = await fuel_catalog.get_fuel_labels()
        if data.fuel_type not in labels:
            raise ValidationError(f"Неизвестный вид топлива: {data.fuel_type!r}")
        tank.fuel_type = data.fuel_type
    if data.is_active is not None:
        tank.is_active = data.is_active
    await db.flush()
    return await _tank_response(tank)


async def adjust_tank(
    db: AsyncSession, tank_id: uuid.UUID, data: TankAdjust, actor: TokenUser
) -> TankResponse:
    """Корректировка админа: точный остаток и/или показание счётчика."""
    _require_admin(actor)
    if data.volume is None and data.counter is None:
        raise ValidationError("Укажите новый остаток и/или показание счётчика")
    tank = await _get_tank_locked(db, tank_id)

    counter_before = int(tank.counter)
    volume_delta = 0.0
    if data.volume is not None:
        volume_delta = float(data.volume) - float(tank.current_volume)
        tank.current_volume = data.volume
    if data.counter is not None:
        tank.counter = data.counter

    db.add(TankTransaction(
        tank_id=tank.id,
        kind=TankTxKind.ADJUST,
        volume=abs(volume_delta),
        counter_before=counter_before,
        counter_after=int(tank.counter),
        actor_id=actor.id,
        actor_name=await _resolve_actor_name(actor.id),
        notes=data.notes or (
            f"Корректировка: объём {'+' if volume_delta >= 0 else ''}{volume_delta:.2f} л"
        ),
    ))
    await db.flush()
    return await _tank_response(tank)


# ── Операции (водитель/менеджер/админ) ───────────────────────────────────────

async def record_arrival(
    db: AsyncSession, tank_id: uuid.UUID, data: TankArrival, actor: TokenUser
) -> TankResponse:
    """Приход топлива в ёмкость. Счётчик не меняется (он считает выдачу)."""
    _require_view(actor)
    tank = await _get_tank_locked(db, tank_id)
    tank.current_volume = float(tank.current_volume) + float(data.volume)
    db.add(TankTransaction(
        tank_id=tank.id,
        kind=TankTxKind.ARRIVAL,
        volume=data.volume,
        counter_before=int(tank.counter),
        counter_after=int(tank.counter),
        actor_id=actor.id,
        actor_name=await _resolve_actor_name(actor.id),
        notes=data.notes,
    ))
    await db.flush()
    return await _tank_response(tank)


def _counter_delta(before: int, after: int) -> int:
    """Литры по счётчику с учётом переполнения шестизначного счётчика."""
    if after >= before:
        return after - before
    return TANK_COUNTER_MODULUS - before + after


async def record_issue(
    db: AsyncSession, tank_id: uuid.UUID, data: TankIssue, actor: TokenUser
) -> TankTxResponse:
    """Выдача по заявке: водитель вводит новое показание счётчика.

    Списанные литры = разница показаний. Остаток может уйти в минус.
    """
    _require_view(actor)
    tank = await _get_tank_locked(db, tank_id)

    counter_before = int(tank.counter)
    volume = _counter_delta(counter_before, data.counter_after)
    if volume <= 0:
        raise ValidationError(
            "Показание счётчика не изменилось — литры по счётчику равны нулю"
        )

    tank.counter = data.counter_after
    tank.current_volume = float(tank.current_volume) - volume

    notes = data.notes
    # Сверка с фактическим объёмом доставки — фиксируем расхождение в журнале
    if data.volume_hint is not None and abs(volume - float(data.volume_hint)) > 0.5:
        mismatch = (
            f"Расхождение: по счётчику {volume} л, в доставке {float(data.volume_hint):.2f} л"
        )
        notes = f"{notes} · {mismatch}" if notes else mismatch

    tx = TankTransaction(
        tank_id=tank.id,
        kind=TankTxKind.ISSUE,
        volume=volume,
        counter_before=counter_before,
        counter_after=data.counter_after,
        order_id=data.order_id,
        order_number=data.order_number,
        actor_id=actor.id,
        actor_name=await _resolve_actor_name(actor.id),
        notes=notes,
    )
    db.add(tx)
    await db.flush()
    tank_name = tank.name
    return TankTxResponse(
        id=tx.id,
        tank_id=tx.tank_id,
        tank_name=tank_name,
        kind=tx.kind.value,
        volume=float(tx.volume),
        counter_before=counter_before,
        counter_after=data.counter_after,
        order_id=tx.order_id,
        order_number=tx.order_number,
        peer_tank_id=None,
        peer_tank_name=None,
        actor_id=tx.actor_id,
        actor_name=tx.actor_name,
        notes=tx.notes,
        created_at=tx.created_at or datetime.now(),
    )


async def record_expense_from_tank(
    db: AsyncSession,
    tank_id: uuid.UUID,
    *,
    volume: float,
    counter_after: int | None,
    actor: TokenUser,
    actor_name: str | None,
    notes: str | None,
) -> None:
    """Списание из ёмкости при ручном расходе «в бак / иное» (правки 2026-07-14).

    Если counter_after задан (лили через колонку) — двигаем счётчик и сверяем
    литры по нему; расхождение фиксируем в примечании. Иначе счётчик не трогаем.
    Вызывается из inventory_service.record_expense в одной транзакции БД.
    """
    tank = await _get_tank_locked(db, tank_id)
    counter_before = int(tank.counter)

    final_notes = notes
    if counter_after is not None:
        by_counter = _counter_delta(counter_before, counter_after)
        if by_counter <= 0:
            raise ValidationError("Показание счётчика не изменилось")
        if abs(by_counter - volume) > 0.5:
            mismatch = f"Расхождение: по счётчику {by_counter} л, введено {volume:.2f} л"
            final_notes = f"{final_notes} · {mismatch}" if final_notes else mismatch
        tank.counter = counter_after

    tank.current_volume = float(tank.current_volume) - volume
    db.add(TankTransaction(
        tank_id=tank.id,
        kind=TankTxKind.EXPENSE,
        volume=volume,
        counter_before=counter_before,
        counter_after=int(tank.counter),
        actor_id=actor.id,
        actor_name=actor_name,
        notes=final_notes,
    ))
    await db.flush()


async def transfer(
    db: AsyncSession, data: TankTransfer, actor: TokenUser
) -> list[TankResponse]:
    """Перелив между ёмкостями — доступен всем ролям склада, любые виды топлива."""
    _require_view(actor)
    if data.from_tank_id == data.to_tank_id:
        raise ValidationError("Выберите две разные ёмкости")

    # Блокируем в детерминированном порядке — иначе два встречных перелива
    # могут схватить блокировки крест-накрест (deadlock).
    first_id, second_id = sorted([data.from_tank_id, data.to_tank_id], key=str)
    first = await _get_tank_locked(db, first_id)
    second = await _get_tank_locked(db, second_id)
    src = first if first.id == data.from_tank_id else second
    dst = second if second.id == data.to_tank_id else first

    src.current_volume = float(src.current_volume) - float(data.volume)
    dst.current_volume = float(dst.current_volume) + float(data.volume)

    actor_name = await _resolve_actor_name(actor.id)
    db.add(TankTransaction(
        tank_id=src.id, kind=TankTxKind.TRANSFER_OUT, volume=data.volume,
        counter_before=int(src.counter), counter_after=int(src.counter),
        peer_tank_id=dst.id, actor_id=actor.id, actor_name=actor_name, notes=data.notes,
    ))
    db.add(TankTransaction(
        tank_id=dst.id, kind=TankTxKind.TRANSFER_IN, volume=data.volume,
        counter_before=int(dst.counter), counter_after=int(dst.counter),
        peer_tank_id=src.id, actor_id=actor.id, actor_name=actor_name, notes=data.notes,
    ))
    await db.flush()
    labels = await fuel_catalog.get_fuel_labels()
    return [await _tank_response(src, labels), await _tank_response(dst, labels)]
