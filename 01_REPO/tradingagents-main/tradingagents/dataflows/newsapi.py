"""NewsAPI evidence adapter for optional broad news discovery.

NewsAPI is supplemental context only. It helps the overnight planner see broad
market/news coverage, but it cannot create a trade intent or bypass gates.
"""

from __future__ import annotations

from typing import Any

from ._official_common import (
    OfficialDataError,
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
    validate_official_path,
)

BASE_URL = "https://newsapi.org/v2"
ALLOWED_ENDPOINT_PREFIXES = (
    "everything",
    "top-headlines",
    "top-headlines/sources",
)


def _api_key(explicit: str | None = None) -> str:
    return env_value("NEWSAPI_API_KEY", explicit, required=True) or ""


def fetch_newsapi_route(
    route: str,
    *,
    params: dict[str, Any] | None = None,
    api_key: str | None = None,
    session: Any | None = None,
    evidence_type: str = "newsapi",
    subject: str | None = None,
    symbol: str | None = None,
):
    safe_route = validate_official_path(route, allowed_prefixes=ALLOWED_ENDPOINT_PREFIXES)
    url = f"{BASE_URL}/{safe_route}"
    request_params = dict(params or {})
    request_params["apiKey"] = _api_key(api_key)
    payload = get_json(url, params=request_params, session=session)
    as_of = extract_payload_timestamp(payload, ("publishedAt", "published_at", "date"))
    return evidence_packet(
        source_name="newsapi",
        evidence_type=evidence_type,
        subject=subject or safe_route,
        symbol=symbol.strip().upper() if symbol else None,
        source_ref=safe_source_ref(url, request_params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", url, request_params, None),
        tool_route="newsapi_api",
    )


def fetch_newsapi_everything(
    query: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    language: str = "en",
    sort_by: str = "publishedAt",
    page_size: int = 50,
    api_key: str | None = None,
    session: Any | None = None,
    symbol: str | None = None,
):
    clean_query = query.strip()
    if not clean_query:
        raise OfficialDataError("NewsAPI query is missing")
    params: dict[str, Any] = {
        "q": clean_query[:500],
        "language": language,
        "sortBy": sort_by,
        "pageSize": max(1, min(int(page_size), 100)),
    }
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return fetch_newsapi_route(
        "everything",
        params=params,
        api_key=api_key,
        session=session,
        evidence_type="market_news",
        subject=clean_query,
        symbol=symbol,
    )
