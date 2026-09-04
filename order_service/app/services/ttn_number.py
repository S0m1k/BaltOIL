"""Нумерация ТТН с раздельными счётчиками по типу контрагента (CRM-42).

Формат номера::

    ТТН-{год}-{префикс}{NNNNNN}

    ТТН-2026-Ю000002   юрлицо
    ТТН-2026-Ф000005   физлицо
    ТТН-2026-Л000003   внутренняя заявка (ТТН-Л)

Правила:

* каждый префикс — свой счётчик, сбрасывается с началом календарного года
  (ключ счётчика содержит год, поэтому в январе последовательность
  начинается с 1 автоматически, без крона и ручных операций);
* **Ю продолжает историческую сквозную нумерацию**: до CRM-42 номера
  выдавались одним общим счётчиком с ключом ``ttn-{год}`` и без префикса
  (``ТТН-2026-000042``). Этот ключ закреплён за Ю (``_LEGACY_KEY_KIND``),
  поэтому уже выданные номера не переписываются, а следующий юрлицовый
  номер продолжает ряд — просто с префиксом Ю;
* Ф и Л начинают с 1 (у каждого собственный ключ, которого в БД ещё нет);
* Л (CRM-42.1) выдаётся **внутренним заявкам** — вид заявки ``ttn_l``,
  чекбокс «ТТН-Л (внутренняя заявка)» в форме. Уже выданные внутренним
  заявкам номера остаются на Ю-ряду вместе со своей классификацией
  ``ttn_kind='company'`` — номера не переписываются, чтобы префикс в номере
  всегда соответствовал ``ttn_kind``; ряд Л начинается с ТТН-{год}-Л000001.

Реестр ``ISSUABLE_TTN_KINDS`` оставлен как точка расширения: новый префикс
заводится в ``TtnKind``/``TTN_PREFIX`` и включается в оборот отдельно, когда
для него определено правило в ``resolve_ttn_kind``.

Атомарность: номер выдаётся тем же upsert-ом
(``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``), что и номера заявок —
один round-trip, без окна гонки между читателями счётчика.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import OrderKind
from app.models.order_counter import OrderKindCounter


class TtnKind(str, enum.Enum):
    """Тип ТТН = тип контрагента. Значение хранится в orders.ttn_kind."""

    COMPANY = "company"        # Ю — юрлица
    INDIVIDUAL = "individual"  # Ф — физлица
    SPECIAL = "special"        # Л — внутренние заявки (order_kind=ttn_l)


#: Реестр префиксов. Добавление нового вида ТТН = запись здесь + значение enum.
TTN_PREFIX: dict[TtnKind, str] = {
    TtnKind.COMPANY: "Ю",
    TtnKind.INDIVIDUAL: "Ф",
    TtnKind.SPECIAL: "Л",
}

#: Виды, которым разрешено выдавать номера прямо сейчас.
ISSUABLE_TTN_KINDS: frozenset[TtnKind] = frozenset(
    {TtnKind.COMPANY, TtnKind.INDIVIDUAL, TtnKind.SPECIAL}
)

#: Ширина порядкового номера — как в исторических номерах (ТТН-2026-000042).
TTN_SEQ_WIDTH = 6

#: Вид, за которым закреплён исторический ключ счётчика без суффикса.
_LEGACY_KEY_KIND = TtnKind.COMPANY

#: Вид заявки → вид ТТН. Внутренняя заявка (ttn_l) = Л со своим счётчиком.
_ORDER_KIND_TO_TTN_KIND: dict[str, TtnKind] = {
    OrderKind.COMPANY.value: TtnKind.COMPANY,
    OrderKind.INDIVIDUAL.value: TtnKind.INDIVIDUAL,
    OrderKind.TTN_L.value: TtnKind.SPECIAL,
}


class TtnKindNotIssuable(ValueError):
    """Попытка выдать номер для префикса, который ещё не введён в оборот."""


def resolve_ttn_kind(order_kind: OrderKind | str | None) -> TtnKind:
    """Определить тип ТТН по виду заявки. Неизвестный вид → Ю (исторический ряд)."""
    value = getattr(order_kind, "value", order_kind)
    return _ORDER_KIND_TO_TTN_KIND.get(str(value or ""), TtnKind.COMPANY)


def counter_key(kind: TtnKind, year: int) -> str:
    """Ключ строки счётчика в order_kind_counters."""
    if kind is _LEGACY_KEY_KIND:
        return f"ttn-{year}"
    return f"ttn-{year}-{kind.value}"


def format_ttn_number(kind: TtnKind, year: int, seq: int) -> str:
    """Собрать номер ТТН из типа, года и порядкового номера."""
    return f"ТТН-{year}-{TTN_PREFIX[kind]}{seq:0{TTN_SEQ_WIDTH}d}"


async def generate_ttn_number(
    db: AsyncSession,
    kind: TtnKind,
    *,
    now: datetime | None = None,
) -> str:
    """Атомарно выдать следующий номер ТТН для указанного типа контрагента."""
    if kind not in ISSUABLE_TTN_KINDS:
        raise TtnKindNotIssuable(
            f"Выдача ТТН с префиксом {TTN_PREFIX[kind]} пока не включена"
        )

    year = (now or datetime.now(timezone.utc)).year
    stmt = (
        pg_insert(OrderKindCounter)
        .values(kind=counter_key(kind, year), last_seq=1)
        .on_conflict_do_update(
            index_elements=["kind"],
            set_={"last_seq": OrderKindCounter.last_seq + 1},
        )
        .returning(OrderKindCounter.last_seq)
    )
    result = await db.execute(stmt)
    seq: int = result.scalar_one()
    return format_ttn_number(kind, year, seq)
