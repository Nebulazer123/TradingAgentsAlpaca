"""Marketaux financial-news evidence adapter.

Marketaux is supplemental news/sentiment context. It can help explain what is
being talked about, but it cannot create trade intents or approve execution.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ._official_common import (
    OfficialDataError,
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
)

BASE_URL = "https://api.marketaux.com/v1/news/all"


def _api_token(explicit: str | None = None) -> str:
    return (
        env_value("MARKETAUX_API_TOKEN", explicit)
        or env_value("MARKETAUX_API_KEY", explicit, required=True)
        or ""
    )


def _symbol(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise OfficialDataError("Marketaux symbol is missing")
    return clean


def _bool_param(value: bool) -> str:
    return str(bool(value)).lower()


def fetch_marketaux_news(
    *,
    symbols: Iterable[str] | None = None,
    search: str | None = None,
    countries: Iterable[str] = ("us",),
    language: str = "en",
    limit: int = 50,
    published_after: str | None = None,
    published_before: str | None = None,
    filter_entities: bool = True,
    must_have_entities: bool = False,
    group_similar: bool = True,
    api_token: str | None = None,
    session: Any | None = None,
) -> Any:
    tickers = [_symbol(symbol) for symbol in symbols or ()]
    clean_search = search.strip() if search else ""
    if not tickers and not clean_search:
        raise OfficialDataError("Marketaux news requires symbols or a search query")

    params: dict[str, Any] = {
        "api_token": _api_token(api_token),
        "limit": max(1, min(int(limit), 100)),
        "language": language.strip() or "en",
        "filter_entities": _bool_param(filter_entities),
        "must_have_entities": _bool_param(must_have_entities),
        "group_similar": _bool_param(group_similar),
    }
    country_values = [country.strip().lower() for country in countries if country and country.strip()]
    if country_values:
        params["countries"] = ",".join(country_values)
    if tickers:
        params["symbols"] = ",".join(tickers)
    if clean_search:
        params["search"] = clean_search
    if published_after:
        params["published_after"] = published_after
    if published_before:
        params["published_before"] = published_before

    payload = get_json(BASE_URL, params=params, session=session)
    as_of = extract_payload_timestamp(payload, ("published_at", "published_on", "date"))
    subject = ",".join(tickers) if tickers else clean_search
    return evidence_packet(
        source_name="marketaux",
        evidence_type="market_news",
        subject=subject,
        symbol=tickers[0] if len(tickers) == 1 else None,
        source_ref=safe_source_ref(BASE_URL, params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", BASE_URL, params, None),
        tool_route="marketaux_api",
    )
