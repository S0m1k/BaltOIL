"""
Скрипт ДЕСТРУКТИВНОЙ очистки данных delivery_service перед переходом на новую нумерацию.

НАЗНАЧЕНИЕ
----------
Удаляет рейсы (trips) и departure-транзакции склада, привязанные к тестовым заявкам.
Arrival-транзакции НЕ трогаются — они фиксируют реальный приход топлива на склад.

После этого скрипта запустить сверку склада:
  POST /api/v1/inventory/reconcile
  (доступно менеджеру/администратору)

ПОРЯДОК ДЕЙСТВИЙ (полный цикл)
-------------------------------
1. python order_service/scripts/cleanup_orders_2026_08.py --yes
2. python delivery_service/scripts/cleanup_delivery_2026_08.py --yes  (этот файл)
3. POST /api/v1/inventory/reconcile

ИСПОЛЬЗОВАНИЕ
-------------
Переменная окружения:
  DELIVERY_CLEANUP_CONFIRMED=1 python cleanup_delivery_2026_08.py

или флаг командной строки:
  python cleanup_delivery_2026_08.py --yes

Без явного подтверждения скрипт завершается с ошибкой.
"""
import asyncio
import os
import sys


def _require_confirmation() -> None:
    confirmed_env = os.environ.get("DELIVERY_CLEANUP_CONFIRMED", "").strip() in ("1", "true", "yes")
    confirmed_arg = "--yes" in sys.argv
    if not confirmed_env and not confirmed_arg:
        print(
            "\n[ERROR] Деструктивная операция требует явного подтверждения.\n"
            "  Запустите с флагом --yes:\n"
            "    python cleanup_delivery_2026_08.py --yes\n"
            "  или установите переменную окружения:\n"
            "    DELIVERY_CLEANUP_CONFIRMED=1 python cleanup_delivery_2026_08.py\n"
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
            # Удаляем все рейсы (привязаны к заявкам)
            result = await session.execute(text("DELETE FROM trips RETURNING id"))
            print(f"  Удалено рейсов: {result.rowcount}")

            # Удаляем departure-транзакции (расход по заявкам)
            # Arrival-транзакции (type='arrival') НЕ трогаем
            result2 = await session.execute(text("""
                DELETE FROM fuel_transactions
                WHERE type = 'departure'
                  AND order_id IS NOT NULL
                RETURNING id
            """))
            print(f"  Удалено departure-транзакций: {result2.rowcount}")

            # fuel_stock пересчитается через POST /inventory/reconcile — не трогаем здесь

    await engine.dispose()
    print("  Готово. Запустите POST /api/v1/inventory/reconcile для пересчёта остатков.")


def main() -> None:
    _require_confirmation()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("[ERROR] Переменная окружения DATABASE_URL не задана (delivery_service DB)")
        sys.exit(1)

    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    print("\n[CLEANUP] Удаление рейсов и departure-транзакций delivery_service...")
    asyncio.run(cleanup(db_url))


if __name__ == "__main__":
    main()
