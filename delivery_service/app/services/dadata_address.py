"""Прокси к DaData suggest/address — геокодирование адреса.

Токен хранится на сервере (settings.dadata_api_key), браузер не видит его.
Если токен не задан → возвращаем пустой список (фича отключена тихо).
Сетевые ошибки → лог предупреждения + пустой список (деградация без 500).
"""
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"
_MAX_QUERY_LEN = 200


async def suggest_address(query: str) -> list[dict]:
    """Возвращает список подсказок вида {value, lat, lon}.

    lat/lon — float или None (если DaData не вернула координаты).
    """
    settings = get_settings()
    api_key = settings.dadata_api_key
    if not api_key:
        return []

    query = query[:_MAX_QUERY_LEN].strip()
    if not query:
        return []

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                _DADATA_URL,
                json={"query": query, "count": 10},
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        if resp.status_code != 200:
            log.warning("dadata suggest_address returned %s", resp.status_code)
            return []

        suggestions = resp.json().get("suggestions", [])
        result = []
        for s in suggestions:
            value = s.get("value", "")
            data = s.get("data") or {}
            lat_str = data.get("geo_lat")
            lon_str = data.get("geo_lon")
            lat = float(lat_str) if lat_str else None
            lon = float(lon_str) if lon_str else None
            result.append({"value": value, "lat": lat, "lon": lon})
        return result

    except httpx.HTTPError as exc:
        log.warning("dadata suggest_address HTTPError: %s", exc)
        return []
    except Exception as exc:
        log.warning("dadata suggest_address unexpected error: %s", exc)
        return []
