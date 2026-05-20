"""DaData integration for INN/company lookup.

Uses the findById/party endpoint. Returns None on any error so
the caller can fall back to manual entry without crashing.
"""
import logging
import httpx

log = logging.getLogger(__name__)

_DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"


async def lookup_by_inn(inn: str, api_key: str) -> dict | None:
    """Look up company data by INN via DaData.

    Returns {company_name, kpp, ogrn, legal_address} or None on failure/not-found.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                _DADATA_URL,
                json={"query": inn},
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        if resp.status_code != 200:
            log.warning("DaData returned %s for INN %s", resp.status_code, inn)
            return None
        suggestions = resp.json().get("suggestions", [])
        if not suggestions:
            return None
        s = suggestions[0]
        d = s.get("data", {})
        address = d.get("address") or {}
        return {
            "company_name": s.get("value", ""),
            "kpp": d.get("kpp"),
            "ogrn": d.get("ogrn"),
            "legal_address": address.get("value", "") if address else "",
        }
    except Exception as exc:
        log.warning("DaData lookup failed for INN %s: %s", inn, exc)
        return None
