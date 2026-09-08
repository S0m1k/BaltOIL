"""Нумерация ТТН по типу контрагента (CRM-42).

БД не поднимаем: сессия подменяется заглушкой, которая воспроизводит поведение
`INSERT ... ON CONFLICT DO UPDATE ... RETURNING` — счётчик по ключу.

Запуск из папки order_service:  pytest tests/test_ttn_number.py
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.order import OrderKind  # noqa: E402
from app.services import ttn_number  # noqa: E402
from app.services.ttn_number import (  # noqa: E402
    ISSUABLE_TTN_KINDS,
    TTN_PREFIX,
    TtnKind,
    TtnKindNotIssuable,
    counter_key,
    format_ttn_number,
    generate_ttn_number,
    resolve_ttn_kind,
)


class FakeResult:
    def __init__(self, value: int):
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeCounterSession:
    """Эмулирует атомарный upsert-счётчик order_kind_counters."""

    def __init__(self, seed: dict[str, int] | None = None):
        self.counters: dict[str, int] = dict(seed or {})

    async def execute(self, stmt):
        params = stmt.compile(dialect=postgresql.dialect()).params
        key = params["kind"]
        # Точка переключения контекста ровно между чтением и записью: если бы
        # выдача не была атомарной, параллельные корутины получили бы один seq.
        await asyncio.sleep(0)
        self.counters[key] = self.counters.get(key, 0) + 1
        return FakeResult(self.counters[key])


def _at(year: int) -> datetime:
    return datetime(year, 6, 1, tzinfo=timezone.utc)


# ── Реестр префиксов ──────────────────────────────────────────────────────────

def test_every_kind_has_prefix():
    assert set(TTN_PREFIX) == set(TtnKind)
    assert TTN_PREFIX[TtnKind.COMPANY] == "Ю"
    assert TTN_PREFIX[TtnKind.INDIVIDUAL] == "Ф"
    assert TTN_PREFIX[TtnKind.SPECIAL] == "Л"


def test_all_registered_kinds_are_issuable():
    # Л введён в оборот (CRM-42.1): внутренние заявки нумеруются своим рядом.
    assert set(ISSUABLE_TTN_KINDS) == set(TtnKind)


def test_kind_outside_registry_is_refused_by_the_guard(monkeypatch):
    # Страховка остаётся: новый префикс не выдаётся, пока его не включили
    # в ISSUABLE_TTN_KINDS и не описали правило в resolve_ttn_kind.
    monkeypatch.setattr(
        ttn_number, "ISSUABLE_TTN_KINDS", frozenset({TtnKind.COMPANY})
    )
    db = FakeCounterSession()
    with pytest.raises(TtnKindNotIssuable):
        asyncio.run(generate_ttn_number(db, TtnKind.SPECIAL, now=_at(2026)))
    assert db.counters == {}


def test_format_matches_customer_examples():
    assert format_ttn_number(TtnKind.COMPANY, 2026, 2) == "ТТН-2026-Ю000002"
    assert format_ttn_number(TtnKind.INDIVIDUAL, 2026, 5) == "ТТН-2026-Ф000005"
    assert format_ttn_number(TtnKind.SPECIAL, 2026, 3) == "ТТН-2026-Л000003"


def test_company_reuses_legacy_counter_key():
    # Ключ без суффикса — тот же, которым нумеровались ТТН до CRM-42,
    # поэтому Ю продолжает исторический ряд, а не начинает с 1.
    assert counter_key(TtnKind.COMPANY, 2026) == "ttn-2026"
    assert counter_key(TtnKind.INDIVIDUAL, 2026) == "ttn-2026-individual"
    assert counter_key(TtnKind.SPECIAL, 2026) == "ttn-2026-special"


def test_counter_keys_fit_column_width():
    for kind in TtnKind:
        assert len(counter_key(kind, 2026)) <= 40


# ── Вид заявки → тип ТТН ──────────────────────────────────────────────────────

def test_resolve_kind_from_order_kind():
    assert resolve_ttn_kind(OrderKind.COMPANY) is TtnKind.COMPANY
    assert resolve_ttn_kind(OrderKind.INDIVIDUAL) is TtnKind.INDIVIDUAL
    # Внутренняя заявка (чекбокс «ТТН-Л») — свой префикс Л.
    assert resolve_ttn_kind(OrderKind.TTN_L) is TtnKind.SPECIAL
    assert resolve_ttn_kind("ttn_l") is TtnKind.SPECIAL


def test_resolve_kind_accepts_raw_values_and_falls_back():
    assert resolve_ttn_kind("individual") is TtnKind.INDIVIDUAL
    assert resolve_ttn_kind(None) is TtnKind.COMPANY
    assert resolve_ttn_kind("who_knows") is TtnKind.COMPANY


# ── Выдача номеров ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_company_continues_existing_sequence():
    db = FakeCounterSession({"ttn-2026": 41})
    assert await generate_ttn_number(db, TtnKind.COMPANY, now=_at(2026)) == "ТТН-2026-Ю000042"


@pytest.mark.asyncio
async def test_individual_starts_from_one():
    db = FakeCounterSession({"ttn-2026": 41})
    assert await generate_ttn_number(db, TtnKind.INDIVIDUAL, now=_at(2026)) == "ТТН-2026-Ф000001"


@pytest.mark.asyncio
async def test_special_starts_from_one_regardless_of_legacy_sequence():
    # Внутренние заявки раньше нумеровались общим Ю-рядом; ряд Л начинается с 1.
    db = FakeCounterSession({"ttn-2026": 41})
    assert await generate_ttn_number(db, TtnKind.SPECIAL, now=_at(2026)) == "ТТН-2026-Л000001"
    assert db.counters["ttn-2026"] == 41


@pytest.mark.asyncio
async def test_special_matches_customer_example():
    db = FakeCounterSession({"ttn-2026-special": 2})
    assert await generate_ttn_number(db, TtnKind.SPECIAL, now=_at(2026)) == "ТТН-2026-Л000003"


@pytest.mark.asyncio
async def test_counters_are_independent():
    db = FakeCounterSession()
    numbers = [
        await generate_ttn_number(db, TtnKind.COMPANY, now=_at(2026)),
        await generate_ttn_number(db, TtnKind.INDIVIDUAL, now=_at(2026)),
        await generate_ttn_number(db, TtnKind.SPECIAL, now=_at(2026)),
        await generate_ttn_number(db, TtnKind.COMPANY, now=_at(2026)),
        await generate_ttn_number(db, TtnKind.SPECIAL, now=_at(2026)),
    ]
    assert numbers == [
        "ТТН-2026-Ю000001",
        "ТТН-2026-Ф000001",
        "ТТН-2026-Л000001",
        "ТТН-2026-Ю000002",
        "ТТН-2026-Л000002",
    ]


@pytest.mark.asyncio
async def test_year_rollover_resets_each_counter():
    db = FakeCounterSession()
    for _ in range(3):
        await generate_ttn_number(db, TtnKind.COMPANY, now=_at(2026))
    await generate_ttn_number(db, TtnKind.INDIVIDUAL, now=_at(2026))
    await generate_ttn_number(db, TtnKind.SPECIAL, now=_at(2026))

    assert await generate_ttn_number(db, TtnKind.COMPANY, now=_at(2027)) == "ТТН-2027-Ю000001"
    assert await generate_ttn_number(db, TtnKind.INDIVIDUAL, now=_at(2027)) == "ТТН-2027-Ф000001"
    assert await generate_ttn_number(db, TtnKind.SPECIAL, now=_at(2027)) == "ТТН-2027-Л000001"
    # Прошлый год продолжается со своего места (номер задним числом).
    assert await generate_ttn_number(db, TtnKind.COMPANY, now=_at(2026)) == "ТТН-2026-Ю000004"


@pytest.mark.asyncio
async def test_parallel_issue_has_no_duplicates():
    db = FakeCounterSession()
    kinds = [TtnKind.COMPANY, TtnKind.INDIVIDUAL, TtnKind.SPECIAL] * 25
    numbers = await asyncio.gather(
        *(generate_ttn_number(db, k, now=_at(2026)) for k in kinds)
    )

    assert len(set(numbers)) == len(numbers) == 75
    for kind in TtnKind:
        prefix = TTN_PREFIX[kind]
        issued = sorted(n for n in numbers if prefix in n)
        assert issued == [f"ТТН-2026-{prefix}{i:06d}" for i in range(1, 26)]
