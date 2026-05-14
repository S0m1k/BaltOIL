"""
Статусная машина заявок.

Жизненный цикл:
  NEW → IN_PROGRESS → IN_TRANSIT → DELIVERED      → CLOSED
      ↘ REJECTED              ↘ PARTIALLY_DELIVERED → CLOSED
                                                   ↘ IN_PROGRESS (повторный рейс)

Статус ASSIGNED упразднён: водитель сам берёт заявку через /claim,
затем сразу переводит в in_transit. Менеджер уже не назначает водителей.
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
    OrderStatus.NEW: {
        OrderStatus.IN_PROGRESS: {ROLE_MANAGER, ROLE_ADMIN},
        OrderStatus.REJECTED:    {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.IN_PROGRESS: {
        # Водитель взял заявку и начинает рейс
        OrderStatus.IN_TRANSIT:  {ROLE_DRIVER},
        OrderStatus.REJECTED:    {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.IN_TRANSIT: {
        OrderStatus.DELIVERED:           {ROLE_DRIVER},
        OrderStatus.PARTIALLY_DELIVERED: {ROLE_DRIVER},
    },
    OrderStatus.DELIVERED: {
        OrderStatus.CLOSED: {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.PARTIALLY_DELIVERED: {
        # Закрыть или вернуть в работу для повторного рейса
        OrderStatus.CLOSED:       {ROLE_MANAGER, ROLE_ADMIN},
        OrderStatus.IN_PROGRESS:  {ROLE_MANAGER, ROLE_ADMIN},
    },
    # Терминальные — переходов нет
    OrderStatus.CLOSED:   {},
    OrderStatus.REJECTED: {},
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
