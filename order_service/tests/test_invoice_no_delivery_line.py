"""Д3: доставка в счёте НЕ выводится отдельной строкой — и при ручной цене тоже.

Жалоба заказчицы 19.11.2026 («в счетах опять вылезает доставка», счёт 0249 по
ю257): отдельную строку доставки вводили 24.08 (откат 85e3863) и 06.11 (f7bfc9d,
для ручной цены за литр). Этот тест падает, если строка появится снова.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

import pytest  # noqa: E402

from app.services import document_service as ds  # noqa: E402
from app.services.money import order_total  # noqa: E402


def _order(**kw):
    base = dict(
        order_number="ю257", fuel_type="diesel_summer", delivery_cost=Decimal("4880"),
        manual_price_per_liter=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("manual_price", [None, Decimal("85")])
def test_invoice_has_single_fuel_line_with_delivery_inside(manual_price):
    total = float(order_total(Decimal("255000"), Decimal("4880"), 3000, 22))
    order = _order(manual_price_per_liter=manual_price)

    items, subtotal, vat, grand = ds._build_line_items(order, 3000.0, total, 22)

    assert len(items) == 1
    assert all("оставк" not in it["name"] for it in items)
    assert items[0]["qty"] == 3000.0
    # «Всего к оплате» = сумма заявки, «Итого» + НДС = «Всего»
    assert grand == total == 259890.0
    assert round(subtotal + vat, 2) == grand


def test_document_service_has_no_delivery_line_helper():
    src = Path(ds.__file__).read_text(encoding="utf-8")
    assert "Доставка топлива" not in src
    assert "manual_price_lines" not in src
