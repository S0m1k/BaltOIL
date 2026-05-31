"""
Статусная машина заявок.

Жизненный цикл:
  NEW → ACCEPTED (водитель /claim) → IN_TRANSIT (начал рейс) → DELIVERED → CLOSED
      ↘ REJECTED                                            ↘ PARTIALLY_DELIVERED → CLOSED
                                                                                  ↘ ACCEPTED (повторный рейс)

IN_PROGRESS и ASSIGNED удалены: водитель сам берёт заявку из NEW и сам начинает рейс.
Менеджер водителей не назначает и в работу не переводит — только отклоняет/закрывает.
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
        OrderStatus.ACCEPTED: {ROLE_DRIVER},
        OrderStatus.REJECTED: {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.ACCEPTED: {
        OrderStatus.IN_TRANSIT: {ROLE_DRIVER},
        OrderStatus.REJECTED:   {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.IN_TRANSIT: {
        OrderStatus.DELIVERED:           {ROLE_DRIVER},
        OrderStatus.PARTIALLY_DELIVERED: {ROLE_DRIVER},
        # Компенсация при отмене рейса в пути: заявка возвращается в ACCEPTED,
        # её можно переназначить. Иначе заказ навсегда застревал в IN_TRANSIT.
        OrderStatus.ACCEPTED:            {ROLE_DRIVER, ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.DELIVERED: {
        OrderStatus.CLOSED: {ROLE_MANAGER, ROLE_ADMIN},
    },
    OrderStatus.PARTIALLY_DELIVERED: {
        OrderStatus.CLOSED:   {ROLE_MANAGER, ROLE_ADMIN},
        # Повторный рейс — возвращаем в ACCEPTED, водитель снова едет
        OrderStatus.ACCEPTED: {ROLE_MANAGER, ROLE_ADMIN},
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
