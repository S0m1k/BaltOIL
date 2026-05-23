"""DaData integration for INN/BIK lookup.

Uses DaData "findById" endpoints to look up legal entities (ЕГРЮЛ/ЕГРИП)
and banks (БИК-справочник ЦБ РФ). All errors return None — the caller
falls back to manual entry, never crashes.
"""
import logging
import httpx

log = logging.getLogger(__name__)

_DADATA_PARTY_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
_DADATA_BANK_URL  = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/bank"
_TIMEOUT_S = 5.0


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def lookup_by_inn(inn: str, api_key: str) -> dict | None:
    """Look up legal entity by INN via DaData /findById/party.

    Returns dict with company / FNS extra fields, or None on failure/not-found.
    Keys always present (may be None): company_name, kpp, ogrn, legal_address,
        okved, okpo, okato, fns_status, director_name.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(
                _DADATA_PARTY_URL,
                json={"query": inn},
                headers=_headers(api_key),
            )
        if resp.status_code != 200:
            log.warning("DaData party returned %s for INN %s", resp.status_code, inn)
            return None
        suggestions = resp.json().get("suggestions") or []
        if not suggestions:
            return None
        s = suggestions[0]
        d = s.get("data") or {}
        address = d.get("address") or {}
        state   = d.get("state")   or {}
        mgmt    = d.get("management") or {}
        fio     = d.get("fio") or {}  # для ИП

        director = mgmt.get("name") or fio.get("full") or None

        return {
            "company_name":  s.get("value") or None,
            "kpp":           d.get("kpp") or None,
            "ogrn":          d.get("ogrn") or None,
            "legal_address": (address.get("value") if address else None) or None,
            "okved":         d.get("okved") or None,
            "okpo":          d.get("okpo") or None,
            "okato":         d.get("okato") or None,
            "fns_status":    state.get("status") or None,
            "director_name": director,
        }
    except Exception as exc:
        log.warning("DaData party lookup failed for INN %s: %s", inn, exc)
        return None


async def lookup_by_bik(bik: str, api_key: str) -> dict | None:
    """Look up bank by БИК via DaData /findById/bank.

    Returns dict or None on failure/not-found. Keys: bank_name,
    correspondent_account, swift, bank_status, bank_address.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(
                _DADATA_BANK_URL,
                json={"query": bik},
                headers=_headers(api_key),
            )
        if resp.status_code != 200:
            log.warning("DaData bank returned %s for BIK %s", resp.status_code, bik)
            return None
        suggestions = resp.json().get("suggestions") or []
        if not suggestions:
            return None
        s = suggestions[0]
        d = s.get("data") or {}
        address = d.get("address") or {}
        state   = d.get("state")   or {}
        return {
            "bank_name":             s.get("value") or None,
            "correspondent_account": d.get("correspondent_account") or None,
            "swift":                 d.get("swift") or None,
            "bank_status":           state.get("status") or None,
            "bank_address":          (address.get("value") if address else None) or None,
        }
    except Exception as exc:
        log.warning("DaData bank lookup failed for BIK %s: %s", bik, exc)
        return None
