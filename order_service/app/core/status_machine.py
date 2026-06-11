"""
Статусная машина заявок.

Жизненный цикл (Д1 + согласование крупных заявок, правки 2026-06-11):
  AWAITING_MANAGER → NEW (менеджер/админ «согласовать», объём >= 3000 л)
                   → CANCELLED (менеджер/админ)
  NEW → ACCEPTED (водитель /claim или берёт назначенную)
      → CANCELLED (менеджер/админ)
  ACCEPTED → DELIVERED (водитель, требуется ttn_number)
           → CANCELLED (менеджер/админ)
  DELIVERED и CANCELLED — терминальные.
"""
from app.models.order import OrderStatus
from app.core.exceptions import StatusTransitionError, ForbiddenError

# Роли
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_DRIVER = "driver"
ROLE_CLIENT = "client"

# allowed_transitions[from_status] = {to_status: {roles_that_can_do_it}}
ALLOWED_TRANSITIONS: dict[OrderStatus, dict[OrderStatus, set[str]]] = {
    OrderStatus.AWAITING_MANAGER: {
        OrderStatus.NEW:       {ROLE_MANAGER, ROLE_ADMIN},
        OrderStatus.CANCELLED: {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.NEW: {
        OrderStatus.ACCEPTED:  {ROLE_DRIVER},
        OrderStatus.CANCELLED: {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.ACCEPTED: {
        OrderStatus.DELIVERED: {ROLE_DRIVER},
        OrderStatus.CANCELLED: {ROLE_MANAGER, ROLE_ADMIN},
    },
    # Терминальные — переходов нет
    OrderStatus.DELIVERED: {},
    OrderStatus.CANCELLED: {},
}


def validate_transition(
    current_status: OrderStatus,
    to_status: OrderStatus,
    role: str,
) -> None:
    """
    Проверяет, допустим ли переход и есть ли у роли право его делать.
    Бросает StatusTransitionError или ForbiddenError.
    """
    allowed = ALLOWED_TRANSITIONS.get(current_status, {})

    if to_status not in allowed:
        raise StatusTransitionError(
            f"Переход из «{current_status.value}» в «{to_status.value}» недопустим"
        )

    roles_allowed = allowed[to_status]
    if role not in roles_allowed:
        raise ForbiddenError(
            f"Переход в «{to_status.value}» доступен только: "
            f"{', '.join(roles_allowed)}"
        )
