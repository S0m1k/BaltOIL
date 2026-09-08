"""Резолв id пользователя → ФИО для журнала действий (CRM-44).

Батч-запрос в auth_service (/internal/users/contacts) с маленьким кэшем в
процессе: журнал одной заявки почти всегда упирается в 2-3 человек, и дёргать
auth на каждую строку смысла нет. Недоступность auth не критична — в журнале
вместо имени останется роль («Администратор»).
"""
import logging
import uuid

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_settings = get_settings()
# Кэш живёт до перезапуска процесса: ФИО меняются крайне редко, а журнал
# читается редко и только админом — инвалидация тут не окупается.
_CACHE: dict[str, str] = {}
_CACHE_CAP = 500


async def resolve_names(ids: list[uuid.UUID | None]) -> dict[str, str]:
    """{str(user_id): ФИО} для переданных id. Неизвестные просто отсутствуют."""
    wanted = {str(i) for i in ids if i}
    out = {i: _CACHE[i] for i in wanted if i in _CACHE}
    missing = sorted(wanted - out.keys())
    if not missing:
        return out

    base = _settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": _settings.internal_api_secret}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base}/api/v1/internal/users/contacts",
                params={"ids": ",".join(missing)},
                headers=headers,
            )
            r.raise_for_status()
            for row in r.json():
                name = (row.get("full_name") or "").strip()
                if not name:
                    continue
                if len(_CACHE) < _CACHE_CAP:
                    _CACHE[str(row["id"])] = name
                out[str(row["id"])] = name
    except Exception as exc:
        log.warning("actor_names: резолв ФИО не удался (не критично): %s", exc)
    return out
