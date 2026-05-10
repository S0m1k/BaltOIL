import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, case, func as sa_func

from app.models.fuel_transaction import FuelTransaction, TransactionType, FUEL_TYPE_LABELS, FUEL_TYPES
from app.models.fuel_stock import FuelStock
from app.models.trip import Trip
from app.core.dependencies import TokenUser, ROLE_ADMIN, ROLE_MANAGER
from app.core.exceptions import ForbiddenError, ValidationError
from app.schemas.inventory import (
    ArrivalRequest, TransactionResponse,
    FuelStockResponse, FuelSummary, InventoryReport,
)


# ── Вспомогательные функции ──────────────────────────────────────────────────

def _require_manager(actor: TokenUser) -> None:
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Требуется роль менеджера или администратора")


def _tx_to_response(tx: FuelTransaction) -> TransactionResponse:
    return TransactionResponse(
        id=tx.id,
        type=tx.type.value,
        fuel_type=tx.fuel_type,
        fuel_label=FUEL_TYPE_LABELS.get(tx.fuel_type, tx.fuel_type),
        volume=float(tx.volume),
        transaction_date=tx.transaction_date,
        trip_id=tx.trip_id,
        order_id=tx.order_id,
        order_number=tx.order_number,
        client_id=tx.client_id,
        client_name=tx.client_name,
        driver_id=tx.driver_id,
        driver_name=tx.driver_name,
        supplier_name=tx.supplier_name,
        invoice_number=tx.invoice_number,
        notes=tx.notes,
        created_by_id=tx.created_by_id,
        created_at=tx.created_at,
    )


async def _upsert_stock(db: AsyncSession, fuel_type: str, delta: float) -> None:
    """Обновить текущий остаток (+delta для прихода, -delta для расхода).

    Использует SELECT FOR UPDATE для защиты от race condition
    при параллельных запросах.
    При расходе (delta < 0) проверяет, что остаток не уйдёт в минус.
    """
    result = await db.execute(
        select(FuelStock)
        .where(FuelStock.fuel_type == fuel_type)
        .with_for_update()
    )
    stock = result.scalar_one_or_none()
    current = float(stock.current_volume) if stock else 0.0

    if delta < 0:
        # Расход — проверяем достаточность остатка
        if current + delta < -0.001:   # допуск на флоат-погрешность
            fuel_label = FUEL_TYPE_LABELS.get(fuel_type, fuel_type)
            raise ValidationError(
                f"Недостаточно топлива «{fuel_label}» на складе. "
                f"Доступно: {current:.1f} л, требуется: {abs(delta):.1f} л. "
                f"Сначала оприходуйте топливо через вкладку Склад → Приход."
            )

    if stock is None:
        stock = FuelStock(fuel_type=fuel_type, current_volume=0.0)
        db.add(stock)
        await db.flush()  # INSERT, чтобы следующий FOR UPDATE мог его поймать

    stock.current_volume = current + delta
    stock.last_updated = datetime.now(timezone.utc)


# ── Публичные функции ────────────────────────────────────────────────────────

async def get_stock(db: AsyncSession, actor: TokenUser) -> list[FuelStockResponse]:
    """Текущие остатки по всем видам топлива."""
    _require_manager(actor)
    result = await db.execute(select(FuelStock))
    stocks: dict[str, FuelStock] = {s.fuel_type: s for s in result.scalars().all()}

    rows = []
    for ft in FUEL_TYPES:
        s = stocks.get(ft)
        rows.append(FuelStockResponse(
            fuel_type=ft,
            fuel_label=FUEL_TYPE_LABELS[ft],
            current_volume=float(s.current_volume) if s else 0.0,
            last_updated=s.last_updated if s else datetime.now(timezone.utc),
        ))
    return rows


async def record_arrival(
    db: AsyncSession,
    data: ArrivalRequest,
    actor: TokenUser,
) -> TransactionResponse:
    """Записать приход топлива (ввод оператора)."""
    _require_manager(actor)
    if data.fuel_type not in FUEL_TYPE_LABELS:
        raise ValidationError(f"Неизвестный вид топлива: {data.fuel_type!r}")

    # Дата не должна быть в далёком будущем (макс. +1 день от сейчас)
    if data.transaction_date:
        from datetime import timedelta
        max_date = datetime.now(timezone.utc) + timedelta(days=1)
        if data.transaction_date.replace(tzinfo=timezone.utc) > max_date:
            raise ValidationError("Дата операции не может быть в будущем")

    tx = FuelTransaction(
        type=TransactionType.ARRIVAL,
        fuel_type=data.fuel_type,
        volume=data.volume,
        transaction_date=data.transaction_date or datetime.now(timezone.utc),
        supplier_name=data.supplier_name,
        invoice_number=data.invoice_number,
        notes=data.notes,
        created_by_id=actor.id,
    )
    db.add(tx)
    await _upsert_stock(db, data.fuel_type, data.volume)
    return _tx_to_response(tx)


async def record_departure_on_start(
    db: AsyncSession,
    trip: Trip,
    actor: TokenUser,
) -> None:
    """Списать плановый объём при переходе рейса в статус IN_TRANSIT (отправка).

    Вызывается из trip_service.start_trip().
    Если inv_fuel_type не задан — пропускаем.
    Идемпотентно: проверяем, нет ли уже записи с notes='trip_planned'.
    """
    if not trip.inv_fuel_type:
        return

    existing = await db.execute(
        select(FuelTransaction.id).where(
            FuelTransaction.trip_id == trip.id,
            FuelTransaction.type == TransactionType.DEPARTURE,
            FuelTransaction.notes == "trip_planned",
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    tx = FuelTransaction(
        type=TransactionType.DEPARTURE,
        fuel_type=trip.inv_fuel_type,
        volume=float(trip.volume_planned),
        transaction_date=trip.departed_at or datetime.now(timezone.utc),
        trip_id=trip.id,
        order_id=trip.order_id,
        order_number=trip.inv_order_number,
        client_id=trip.inv_client_id,
        client_name=trip.inv_client_name,
        driver_id=trip.driver_id,
        driver_name=trip.inv_driver_name,
        notes="trip_planned",
        created_by_id=actor.id,
    )
    db.add(tx)
    await _upsert_stock(db, trip.inv_fuel_type, -float(trip.volume_planned))


async def record_departure_adjustment(
    db: AsyncSession,
    trip: Trip,
    actor: TokenUser,
) -> None:
    """Скорректировать остаток при завершении рейса (факт vs план).

    Вызывается из trip_service.complete_trip().
    Если объём факт == план — коррекция не нужна.
    Если факт < план — возвращаем разницу (приход).
    Если факт > план — списываем разницу (расход).
    """
    if not trip.inv_fuel_type or not trip.volume_actual:
        return

    planned = float(trip.volume_planned)
    actual  = float(trip.volume_actual)
    diff    = actual - planned

    if abs(diff) < 0.001:
        return  # расхождение несущественно

    # Идемпотентность
    existing = await db.execute(
        select(FuelTransaction.id).where(
            FuelTransaction.trip_id == trip.id,
            FuelTransaction.notes == "trip_adjustment",
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    if diff > 0:
        # Факт > план: списываем дополнительно
        tx = FuelTransaction(
            type=TransactionType.DEPARTURE,
            fuel_type=trip.inv_fuel_type,
            volume=diff,
            transaction_date=trip.arrived_at or datetime.now(timezone.utc),
            trip_id=trip.id,
            order_id=trip.order_id,
            order_number=trip.inv_order_number,
            client_id=trip.inv_client_id,
            client_name=trip.inv_client_name,
            driver_id=trip.driver_id,
            driver_name=trip.inv_driver_name,
            notes="trip_adjustment",
            created_by_id=actor.id,
        )
        db.add(tx)
        await _upsert_stock(db, trip.inv_fuel_type, -diff)
    else:
        # Факт < план: возвращаем разницу
        tx = FuelTransaction(
            type=TransactionType.ARRIVAL,
            fuel_type=trip.inv_fuel_type,
            volume=-diff,           # -diff > 0
            transaction_date=trip.arrived_at or datetime.now(timezone.utc),
            trip_id=trip.id,
            order_id=trip.order_id,
            order_number=trip.inv_order_number,
            client_id=trip.inv_client_id,
            client_name=trip.inv_client_name,
            driver_id=trip.driver_id,
            driver_name=trip.inv_driver_name,
            notes="trip_adjustment",
            created_by_id=actor.id,
        )
        db.add(tx)
        await _upsert_stock(db, trip.inv_fuel_type, -diff)   # -diff > 0 → прибавит


async def record_reversal_for_cancelled_trip(
    db: AsyncSession,
    trip: Trip,
    actor: TokenUser,
) -> None:
    """Вернуть списанный объём если рейс отменён из статуса IN_TRANSIT.

    Вызывается из trip_service.cancel_trip() когда prev_status == IN_TRANSIT.
    """
    if not trip.inv_fuel_type:
        return

    # Идемпотентность
    existing = await db.execute(
        select(FuelTransaction.id).where(
            FuelTransaction.trip_id == trip.id,
            FuelTransaction.notes == "trip_cancelled",
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    tx = FuelTransaction(
        type=TransactionType.ARRIVAL,
        fuel_type=trip.inv_fuel_type,
        volume=float(trip.volume_planned),
        transaction_date=datetime.now(timezone.utc),
        trip_id=trip.id,
        order_id=trip.order_id,
        order_number=trip.inv_order_number,
        client_id=trip.inv_client_id,
        client_name=trip.inv_client_name,
        driver_id=trip.driver_id,
        driver_name=trip.inv_driver_name,
        notes="trip_cancelled",
        created_by_id=actor.id,
    )
    db.add(tx)
    await _upsert_stock(db, trip.inv_fuel_type, float(trip.volume_planned))


async def list_transactions(
    db: AsyncSession,
    actor: TokenUser,
    *,
    fuel_type: str | None = None,
    tx_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[TransactionResponse]:
    """Список операций с фильтрами."""
    _require_manager(actor)

    conditions = []
    if fuel_type:
        conditions.append(FuelTransaction.fuel_type == fuel_type)
    if tx_type:
        conditions.append(FuelTransaction.type == tx_type)
    if date_from:
        conditions.append(FuelTransaction.transaction_date >= date_from)
    if date_to:
        conditions.append(FuelTransaction.transaction_date <= date_to)

    q = (
        select(FuelTransaction)
        .order_by(FuelTransaction.transaction_date.desc())
        .offset(offset)
        .limit(limit)
    )
    if conditions:
        q = q.where(and_(*conditions))

    result = await db.execute(q)
    return [_tx_to_response(tx) for tx in result.scalars().all()]


async def generate_report(
    db: AsyncSession,
    actor: TokenUser,
    *,
    date_from: datetime,
    date_to: datetime,
    fuel_type: str | None = None,
) -> InventoryReport:
    """Сводный отчёт за период: остатки + список операций."""
    _require_manager(actor)

    fuel_types_scope = [fuel_type] if fuel_type else FUEL_TYPES

    # Операции за период (для строк отчёта)
    period_txs = await list_transactions(
        db, actor,
        fuel_type=fuel_type,
        date_from=date_from,
        date_to=date_to,
        limit=10_000,
    )

    # Входящий остаток — агрегация на стороне БД (вместо загрузки всех записей в память)
    opening_q = (
        select(
            FuelTransaction.fuel_type,
            sa_func.coalesce(
                sa_func.sum(
                    case(
                        (FuelTransaction.type == TransactionType.ARRIVAL, FuelTransaction.volume),
                        else_=-FuelTransaction.volume,
                    )
                ),
                0.0,
            ).label("balance"),
        )
        .where(
            and_(
                FuelTransaction.transaction_date < date_from,
                FuelTransaction.fuel_type.in_(fuel_types_scope),
            )
        )
        .group_by(FuelTransaction.fuel_type)
    )
    opening_result = await db.execute(opening_q)
    opening_by_ft: dict[str, float] = {
        row.fuel_type: float(row.balance) for row in opening_result.all()
    }

    summaries: list[FuelSummary] = []
    for ft in fuel_types_scope:
        opening = opening_by_ft.get(ft, 0.0)

        # Обороты за период
        period_ft = [tx for tx in period_txs if tx.fuel_type == ft]
        arrivals   = sum(tx.volume for tx in period_ft if tx.type == "arrival")
        departures = sum(tx.volume for tx in period_ft if tx.type == "departure")
        closing    = opening + arrivals - departures

        summaries.append(FuelSummary(
            fuel_type=ft,
            fuel_label=FUEL_TYPE_LABELS[ft],
            opening_balance=round(opening, 2),
            total_arrivals=round(arrivals, 2),
            total_departures=round(departures, 2),
            closing_balance=round(closing, 2),
        ))

    return InventoryReport(
        period_from=date_from,
        period_to=date_to,
        fuel_type_filter=fuel_type,
        summary=summaries,
        transactions=period_txs,
    )


async def reconcile_stock(
    db: AsyncSession,
    actor: TokenUser,
) -> list[FuelStockResponse]:
    """Пересчитать текущие остатки из суммы транзакций (исправление рассинхрона).

    Выполняет один агрегирующий запрос к fuel_transactions и
    перезаписывает fuel_stock. Идемпотентно.
    """
    if actor.role != ROLE_ADMIN:
        raise ForbiddenError("Пересчёт остатков доступен только администратору")

    # Агрегат по всем операциям
    reconcile_q = (
        select(
            FuelTransaction.fuel_type,
            sa_func.coalesce(
                sa_func.sum(
                    case(
                        (FuelTransaction.type == TransactionType.ARRIVAL, FuelTransaction.volume),
                        else_=-FuelTransaction.volume,
                    )
                ),
                0.0,
            ).label("balance"),
        )
        .group_by(FuelTransaction.fuel_type)
    )
    rows = (await db.execute(reconcile_q)).all()
    actual: dict[str, float] = {r.fuel_type: float(r.balance) for r in rows}

    # Ensure all known fuel types are represented
    for ft in FUEL_TYPES:
        actual.setdefault(ft, 0.0)

    now = datetime.now(timezone.utc)
    for ft, balance in actual.items():
        result = await db.execute(
            select(FuelStock).where(FuelStock.fuel_type == ft).with_for_update()
        )
        stock = result.scalar_one_or_none()
        if stock is None:
            stock = FuelStock(fuel_type=ft, current_volume=balance)
            db.add(stock)
        else:
            stock.current_volume = balance
        stock.last_updated = now

    # Flush so the subsequent get_stock reads fresh data in the same transaction
    await db.flush()
    return await get_stock(db, actor)
