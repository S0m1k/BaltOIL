import uuid
from datetime import datetime
from pydantic import BaseModel


class OrderAuditLogResponse(BaseModel):
    """Запись журнала действий по заявке (CRM-44, только для админа).

    `message` — готовая русская формулировка («Сомов изменил объём 3000 л →
    2800 л»): собирается на сервере, где известны и метки полей, и ФИО, чтобы
    фронт не дублировал словари.
    """
    id: uuid.UUID
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_role: str | None
    actor_name: str | None
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None
    message: str
