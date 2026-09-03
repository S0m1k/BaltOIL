"""Подписка delivery_service на канал events:orders.

Пока обрабатывается единственное событие — `order_deleted` (полное удаление
заявки админом, order_service.hard_delete_order): нужно убрать рейсы и складские
проводки заявки так, чтобы остаток топлива вернулся к значению «как будто заявки
не было».

Остаток хранится в полях `fuel_stock.current_volume` и `fuel_tanks.current_volume`
(не агрегат по транзакциям), поэтому одного удаления проводок мало — каждую
проводку компенсируем обратной дельтой в той же транзакции БД. Счётчик колонки
(`fuel_tanks.counter`) НЕ откатываем: это показание физического прибора, оно не
зависит от того, существует заявка в системе или нет.
"""
import asyncio
import json
import logging
import uuid

import redis.asyncio as aioredis
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.fuel_tank import FuelTank, TankTransaction, TankTxKind
from app.models.fuel_transaction import FuelTransaction, TransactionType
from app.models.trip import Trip
from app.services.inventory_service import _upsert_stock

log = logging.getLogger(__name__)

CHANNELS = ["events:orders"]

# Пополняют ёмкость → при удалении вычитаем; остальные виды списывают → прибавляем.
_TANK_INCOMING_KINDS = (TankTxKind.ARRIVAL, TankTxKind.TRANSFER_IN)


async def handle_order_deleted(db, order_id: uuid.UUID) -> float:
    """Удалить рейсы и проводки заявки, вернув остаток. Возвращает литры на складе."""
    restored = 0.0

    txs = (
        await db.execute(
            select(FuelTransaction).where(FuelTransaction.order_id == order_id)
        )
    ).scalars().all()
    for tx in txs:
        # Обратная дельта: приход по заявке вычитаем, расход возвращаем.
        delta = -float(tx.volume) if tx.type == TransactionType.ARRIVAL else float(tx.volume)
        await _upsert_stock(db, tx.fuel_type, delta)
        restored += delta
    if txs:
        await db.execute(
            delete(FuelTransaction).where(FuelTransaction.order_id == order_id)
        )

    tank_txs = (
        await db.execute(
            select(TankTransaction).where(TankTransaction.order_id == order_id)
        )
    ).scalars().all()
    for ttx in tank_txs:
        if ttx.kind == TankTxKind.ADJUST:
            # У корректировки не сохранён знак дельты — вернуть литры нельзя.
            log.warning(
                "tank_transaction %s (adjust) заявки %s удалена без возврата литров",
                ttx.id, order_id,
            )
            continue
        delta = -float(ttx.volume) if ttx.kind in _TANK_INCOMING_KINDS else float(ttx.volume)
        tank = (
            await db.execute(
                select(FuelTank).where(FuelTank.id == ttx.tank_id).with_for_update()
            )
        ).scalar_one_or_none()
        if tank is not None:
            tank.current_volume = float(tank.current_volume) + delta
    if tank_txs:
        await db.execute(
            delete(TankTransaction).where(TankTransaction.order_id == order_id)
        )

    await db.execute(delete(Trip).where(Trip.order_id == order_id))
    await db.commit()

    log.warning(
        "action=order.hard_deleted.delivery_cleanup order_id=%s trips=deleted "
        "fuel_tx=%s tank_tx=%s stock_restored_l=%.2f",
        order_id, len(txs), len(tank_txs), restored,
    )
    return restored


async def _handle(payload: dict) -> None:
    if payload.get("event") != "order_deleted":
        return
    raw_id = payload.get("order_id")
    if not raw_id:
        return
    try:
        order_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError, TypeError):
        log.warning("order_deleted с некорректным order_id: %r", raw_id)
        return

    async with AsyncSessionLocal() as db:
        try:
            await handle_order_deleted(db, order_id)
        except Exception:
            log.exception("Не удалось очистить данные удалённой заявки %s", order_id)
            await db.rollback()


async def order_events_subscriber_task() -> None:
    """Фоновая задача: слушает events:orders, переподключаясь при сбоях."""
    settings = get_settings()
    # warning, а не info: в delivery_service нет basicConfig(level=INFO), и строка
    # старта подписчика — та самая, по которой DEPLOY_NOTES велят проверять деплой.
    log.warning("Delivery Redis subscriber starting…")
    while True:
        try:
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(*CHANNELS)
            log.warning("Subscribed to %s", CHANNELS)
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    payload = json.loads(msg["data"])
                except json.JSONDecodeError:
                    continue
                asyncio.create_task(_handle(payload))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Redis subscriber crashed, reconnecting in 5 s…")
            await asyncio.sleep(5)
