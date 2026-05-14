"""Validation matrix: which payment_type is allowed for a given actor + client context.

Rules (agreed 2026-05-14, revised):
┌──────────────┬────────────┬─────────┬──────────────────────┬───────────────────────┐
│ payment_type │ INDIVIDUAL │ COMPANY │ requires credit_allowed │ who can select      │
├──────────────┼────────────┼─────────┼──────────────────────┼───────────────────────┤
│ prepaid      │     ✓      │    ✓    │          —           │ client, manager, admin│
│ on_delivery  │     ✓      │    ✓    │          —           │ client, manager, admin│
│ postpaid     │     ✗      │    ✓    │          —           │ manager, admin        │
│ trade_credit │     ✗      │    ✓    │          —           │ client (company), mgr │
│ debt         │     ✓      │    ✓    │         yes          │ client (if allowed)   │
└──────────────┴────────────┴─────────┴──────────────────────┴───────────────────────┘
"""
from app.models.order import PaymentType
from app.core.exceptions import ValidationError

_CLIENT_ROLE = "client"
_STAFF_ROLES = {"manager", "admin"}

# payment_type → (allowed_client_types, staff_only, requires_credit_allowed)
_RULES: dict[PaymentType, tuple[set[str], bool, bool]] = {
    PaymentType.PREPAID:       ({"individual", "company"}, False, False),
    PaymentType.ON_DELIVERY:   ({"individual", "company"}, False, False),
    PaymentType.POSTPAID:      ({"company"},               True,  False),
    PaymentType.TRADE_CREDIT:  ({"company"},               False, False),  # company clients pick it themselves
    PaymentType.DEBT:          ({"individual", "company"}, False, True),   # any client, only if admin enabled
}


def validate_payment_type(
    payment_type: PaymentType,
    actor_role: str,
    client_type: str,        # "individual" | "company"
    credit_allowed: bool,
) -> None:
    """Raise ValidationError if the combination is forbidden.

    Called on order create AND on manager update of payment_type.
    """
    allowed_types, staff_only, requires_credit = _RULES.get(
        payment_type, (set(), True, False)
    )

    if staff_only and actor_role == _CLIENT_ROLE:
        raise ValidationError(
            f"Тип оплаты «{payment_type.value}» назначается менеджером или администратором"
        )

    if client_type not in allowed_types:
        type_label = "физическому лицу" if client_type == "individual" else "юридическому лицу"
        raise ValidationError(
            f"Тип оплаты «{payment_type.value}» недоступен {type_label}"
        )

    if requires_credit and not credit_allowed:
        raise ValidationError(
            "Тип оплаты «в долг» доступен только клиентам с разрешённым кредитом. "
            "Обратитесь к администратору."
        )
