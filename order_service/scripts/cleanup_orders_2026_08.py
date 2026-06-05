"""
Скрипт ДЕСТРУКТИВНОЙ очистки заявок перед переходом на новую нумерацию.

НАЗНАЧЕНИЕ
----------
Удаляет все тестовые заявки и связанные данные из БД до запуска в production.
Счётчики нумерации сбрасываются — новые заявки пойдут с ф1/ю1/л1.

ВАЖНО: запускать вручную оператором ПОСЛЕ деплоя миграции 0012
       и ДО появления реальных клиентов.

ПОРЯДОК ДЕЙСТВИЙ
----------------
1. Запустить этот скрипт с флагом --yes (или ORDER_CLEANUP_CONFIRMED=1):
   python order_service/scripts/cleanup_orders_2026_08.py --yes

2. Запустить скрипт на стороне delivery_service:
   python delivery_service/scripts/cleanup_delivery_2026_08.py --yes

3. После обоих скриптов — вызвать сверку склада:
   POST /api/v1/inventory/reconcile
   (доступно менеджеру/администратору через фронт или curl с токеном)

   Это пересчитает fuel_stock из оставшихся arrival-транзакций.

DELIVERY_SERVICE — ЧТО УДАЛЯЕТСЯ
---------------------------------
- trips: все строки
- fuel_transactions WHERE type = 'departure' (order_id IS NOT NULL)
  Приходы (type='arrival') НЕ трогаются — они не привязаны к заявкам.

После удаления departure-транзакций текущие остатки (fuel_stock) станут
больше реальных (так как «расход» убран). Сверка (reconcile) исправит это,
пересчитав stock = sum(arrivals) - sum(departures) по каждому виду топлива.

ИСПОЛЬЗОВАНИЕ
-------------
Переменная окружения:
  ORDER_CLEANUP_CONFIRMED=1 python cleanup_orders_2026_08.py

или флаг командной строки:
  python cleanup_orders_2026_08.py --yes

Без явного подтверждения скрипт завершается с ошибкой.
"""
import asyncio
import os
import sys


def _require_confirmation() -> None:
    confirmed_env = os.environ.get("ORDER_CLEANUP_CONFIRMED", "").strip() in ("1", "true", "yes")
    confirmed_arg = "--yes" in sys.argv
    if not confirmed_env and not confirmed_arg:
        print(
            "\n[ERROR] Деструктивная операция требует явного подтверждения.\n"
            "  Запустите с флагом --yes:\n"
            "    python cleanup_orders_2026_08.py --yes\n"
            "  или установите переменную окружения:\n"
            "    ORDER_CLEANUP_CONFIRMED=1 python cleanup_orders_2026_08.py\n"
        )
        sys.exit(1)


async def cleanup(db_url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            # Документы удаляются каскадно через FK (orders.id → documents.order_id)
            # Статус-логи удаляются каскадно аналогично
            # Платежи — каскадно
            result = await session.execute(text("DELETE FROM orders RETURNING id"))
            deleted_orders = result.rowcount
            print(f"  Удалено заявок: {deleted_orders}")

            # Сбросить счётчики нумерации
            result2 = await session.execute(text("UPDATE order_kind_counters SET last_seq = 0"))
            print(f"  Счётчики сброшены: {result2.rowcount} строк")

    await engine.dispose()
    print("  Готово. Не забудьте запустить delivery cleanup + POST /inventory/reconcile")


def main() -> None:
    _require_confirmation()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("[ERROR] Переменная окружения DATABASE_URL не задана")
        sys.exit(1)

    # asyncpg требует postgresql+asyncpg://
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    print("\n[CLEANUP] Удаление всех заявок и сброс счётчиков нумерации...")
    asyncio.run(cleanup(db_url))


if __name__ == "__main__":
    main()
