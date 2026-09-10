"""Разовая заявка от юрлица считается по тарифам юрлица (баг 2026-09-10).

Заказчица: «при разовой заявке от юр лица считается по тарифам физика».
Причина была в preview_price: у разового клиента client_id ещё нет (он
создаётся при сабмите), и ветка «менеджер без клиента» подставляла
client_type="individual", ИГНОРИРУЯ выбранную организацию. Превью в форме
показывало цену физлица, хотя заказчик — юрлицо.

Тесты держат карту выбора тарифа: организация в запросе → тариф юрлица,
без организации → профиль клиента (разовый = физлицо).

БД и auth_service не нужны: подменяем get_client_context (границу с auth) и
compute_price_breakdown (границу с тарифами), проверяя, ЧТО именно уехало
в расчёт.

Запуск из папки order_service:  pytest tests/test_oneoff_company_pricing.py
"""
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.dependencies import TokenUser  # noqa: E402
from app.schemas.order import PricePreviewRequest  # noqa: E402
from app.services import order_service  # noqa: E402
from app.services.client_context import ClientContext  # noqa: E402

pytestmark = pytest.mark.asyncio

# Тарифы: у юрлица литр дороже — по цене в ответе видно, чей тариф применён.
ORG_TARIFF_ID = uuid.uuid4()
COMPANY_PROFILE_TARIFF_ID = uuid.uuid4()
PRICE_BY_TARIFF = {
    ORG_TARIFF_ID: Decimal("60.00"),
    COMPANY_PROFILE_TARIFF_ID: Decimal("58.00"),
}
# Тариф не задан → default-тариф своего client_type (см. get_default_tariff)
DEFAULT_PRICE = {"individual": Decimal("50.00"), "company": Decimal("55.00")}

ORG_ID = uuid.uuid4()
ONE_OFF_CLIENT_ID = uuid.uuid4()
COMPANY_CLIENT_ID = uuid.uuid4()
INDIVIDUAL_CLIENT_ID = uuid.uuid4()

# Профили клиентов в auth_service. Разовый клиент — всегда физлицо.
_PROFILES = {
    ONE_OFF_CLIENT_ID: ("individual", None),
    INDIVIDUAL_CLIENT_ID: ("individual", None),
    COMPANY_CLIENT_ID: ("company", COMPANY_PROFILE_TARIFF_ID),
}


@pytest.fixture
def spy(monkeypatch):
    """Подменяет границы preview_price и записывает аргументы вызовов."""
    calls = {"context": [], "breakdown": []}

    async def fake_get_client_context(client_id, organization_id=None):
        calls["context"].append((client_id, organization_id))
        if organization_id is not None:
            # Заявка от имени организации: коммерческие условия — организации.
            # Членство разового клиента auth не требует (см. _load_member_org).
            return ClientContext(
                user_id=client_id, client_type="company", credit_allowed=True,
                tariff_id=ORG_TARIFF_ID, credit_limit=None,
            )
        client_type, tariff_id = _PROFILES[client_id]
        return ClientContext(
            user_id=client_id, client_type=client_type, credit_allowed=False,
            tariff_id=tariff_id, credit_limit=None,
        )

    async def fake_compute_price_breakdown(
        db, fuel_type, volume, tariff_id, client_type=None, fuel_coefficient=1.0
    ):
        calls["breakdown"].append(
            {"tariff_id": tariff_id, "client_type": client_type, "volume": volume}
        )
        price = (
            PRICE_BY_TARIFF[tariff_id] if tariff_id is not None
            else DEFAULT_PRICE[client_type or "individual"]
        )
        return {
            "tariff_found": True,
            "price_per_liter": price,
            "discount_pct": Decimal("0"),
            "effective_price_per_liter": price,
            "fuel_subtotal": (price * Decimal(str(volume))),
            "base_delivery_cost": None,
        }

    async def fake_vat_rate(db):
        return 20

    monkeypatch.setattr(order_service, "get_client_context", fake_get_client_context)
    monkeypatch.setattr(order_service, "compute_price_breakdown", fake_compute_price_breakdown)
    monkeypatch.setattr(order_service, "get_seller_vat_rate", fake_vat_rate)
    return calls


def _manager() -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role="manager", token="t")


def _client(user_id: uuid.UUID) -> TokenUser:
    return TokenUser(id=user_id, role="client", token="t")


def _request(**kw) -> PricePreviewRequest:
    return PricePreviewRequest(fuel_type="DT", volume=1000, **kw)


async def test_oneoff_with_organization_uses_company_tariff(spy):
    """Разовый клиент + организация → тариф юрлица (баг заказчицы)."""
    actor = _manager()
    # Разовый клиент создаётся только при сабмите — client_id в превью нет
    result = await order_service.preview_price(
        None, _request(organization_id=ORG_ID), actor
    )

    assert spy["breakdown"][0]["client_type"] == "company"
    assert spy["breakdown"][0]["tariff_id"] == ORG_TARIFF_ID
    assert result["price_per_liter"] == Decimal("60.00")
    # Членство проверяется по самому сотруднику — разовый клиент ни в одной
    # организации не состоит.
    assert spy["context"] == [(actor.id, ORG_ID)]


async def test_oneoff_without_organization_uses_individual_tariff(spy):
    """Разовый клиент без организации → тариф физлица, auth не спрашиваем."""
    result = await order_service.preview_price(None, _request(), _manager())

    assert spy["breakdown"][0]["client_type"] == "individual"
    assert spy["breakdown"][0]["tariff_id"] is None
    assert result["price_per_liter"] == DEFAULT_PRICE["individual"]
    assert spy["context"] == []


async def test_regular_company_client_uses_company_tariff(spy):
    """Обычный клиент-юрлицо (тариф в профиле) → тариф юрлица."""
    result = await order_service.preview_price(
        None, _request(client_id=COMPANY_CLIENT_ID), _manager()
    )

    assert spy["breakdown"][0]["client_type"] == "company"
    assert result["price_per_liter"] == PRICE_BY_TARIFF[COMPANY_PROFILE_TARIFF_ID]
    assert spy["context"] == [(COMPANY_CLIENT_ID, None)]


async def test_regular_individual_client_uses_individual_tariff(spy):
    """Обычный клиент-физлицо остаётся на тарифе физлица."""
    result = await order_service.preview_price(
        None, _request(client_id=INDIVIDUAL_CLIENT_ID), _manager()
    )

    assert spy["breakdown"][0]["client_type"] == "individual"
    assert result["price_per_liter"] == DEFAULT_PRICE["individual"]


async def test_selected_client_wins_over_actor_when_organization_given(spy):
    """Клиент выбран И организация выбрана → тариф организации."""
    result = await order_service.preview_price(
        None, _request(client_id=ONE_OFF_CLIENT_ID, organization_id=ORG_ID), _manager()
    )

    assert spy["breakdown"][0]["client_type"] == "company"
    assert result["price_per_liter"] == Decimal("60.00")
    assert spy["context"] == [(ONE_OFF_CLIENT_ID, ORG_ID)]


async def test_client_actor_organization_context_asked_for_himself(spy):
    """Клиент сам себе заявку от организации: контекст — по нему (членство!)."""
    result = await order_service.preview_price(
        None, _request(organization_id=ORG_ID), _client(INDIVIDUAL_CLIENT_ID)
    )

    assert spy["context"] == [(INDIVIDUAL_CLIENT_ID, ORG_ID)]
    assert result["price_per_liter"] == Decimal("60.00")


async def test_client_actor_without_organization_uses_own_profile(spy):
    """Клиент без организации — по своему профилю (физлицо)."""
    result = await order_service.preview_price(
        None, _request(), _client(INDIVIDUAL_CLIENT_ID)
    )

    assert spy["context"] == [(INDIVIDUAL_CLIENT_ID, None)]
    assert result["price_per_liter"] == DEFAULT_PRICE["individual"]
