"""DaData integration for INN/BIK lookup.

Uses DaData "findById" endpoints to look up legal entities (ЕГРЮЛ/ЕГРИП)
and banks (БИК-справочник ЦБ РФ). All errors return None — the caller
falls back to manual entry, never crashes.
"""
import logging
import re
import httpx

log = logging.getLogger(__name__)

_DADATA_PARTY_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
_DADATA_BANK_URL  = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/bank"
_TIMEOUT_S = 5.0

# DaData в норме не отдаёт HTML, но мы пишем эти поля в БД и потом рендерим
# в инвойсах / письмах / UI. Подстраховка от MITM / подмены: режем теги.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize(value):
    if not isinstance(value, str):
        return value
    return _HTML_TAG_RE.sub("", value).strip() or None


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
            "company_name":  _sanitize(s.get("value")),
            "kpp":           _sanitize(d.get("kpp")),
            "ogrn":          _sanitize(d.get("ogrn")),
            "legal_address": _sanitize(address.get("value") if address else None),
            "okved":         _sanitize(d.get("okved")),
            "okpo":          _sanitize(d.get("okpo")),
            "okato":         _sanitize(d.get("okato")),
            "fns_status":    _sanitize(state.get("status")),
            "director_name": _sanitize(director),
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
            "bank_name":             _sanitize(s.get("value")),
            "correspondent_account": _sanitize(d.get("correspondent_account")),
            "swift":                 _sanitize(d.get("swift")),
            "bank_status":           _sanitize(state.get("status")),
            "bank_address":          _sanitize(address.get("value") if address else None),
        }
    except Exception as exc:
        log.warning("DaData bank lookup failed for BIK %s: %s", bik, exc)
        return None
