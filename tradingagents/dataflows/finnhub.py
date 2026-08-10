"""Finnhub evidence adapters for optional research enrichment."""

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

BASE_URL = "https://finnhub.io/api/v1"
ALLOWED_ENDPOINT_PREFIXES = (
    "quote",
    "company-news",
    "stock/profile2",
    "stock/metric",
    "news-sentiment",
)


def _api_key(explicit: str | None = None) -> str:
    return env_value("FINNHUB_API_KEY", explicit, required=True) or ""


def _symbol(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise OfficialDataError("Finnhub symbol is missing")
    return clean


def _fetch(
    path: str,
    *,
    params: dict[str, Any],
    api_key: str | None,
    session: Any | None,
    evidence_type: str,
    subject: str,
    symbol: str | None = None,
) -> Any:
    safe_path = validate_official_path(path, allowed_prefixes=ALLOWED_ENDPOINT_PREFIXES)
    url = f"{BASE_URL}/{safe_path}"
    headers = {"X-Finnhub-Token": _api_key(api_key)}
    payload = get_json(url, params=params, headers=headers, session=session)
    as_of = extract_payload_timestamp(payload, ("t", "datetime", "date", "atDate"))
    return evidence_packet(
        source_name="finnhub",
        evidence_type=evidence_type,
        subject=subject,
        symbol=symbol,
        source_ref=safe_source_ref(url, params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", url, params, None),
        tool_route="finnhub_api",
    )


def fetch_finnhub_quote(
    symbol: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    return _fetch(
        "quote",
        params={"symbol": ticker},
        api_key=api_key,
        session=session,
        evidence_type="quote",
        subject=ticker,
        symbol=ticker,
    )


def fetch_finnhub_company_news(
    symbol: str,
    *,
    from_date: str,
    to_date: str,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    return _fetch(
        "company-news",
        params={"symbol": ticker, "from": from_date, "to": to_date},
        api_key=api_key,
        session=session,
        evidence_type="company_news",
        subject=ticker,
        symbol=ticker,
    )


def fetch_finnhub_profile2(
    symbol: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    return _fetch(
        "stock/profile2",
        params={"symbol": ticker},
        api_key=api_key,
        session=session,
        evidence_type="company_profile",
        subject=ticker,
        symbol=ticker,
    )


def fetch_finnhub_basic_financials(
    symbol: str,
    *,
    metric: str = "all",
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    return _fetch(
        "stock/metric",
        params={"symbol": ticker, "metric": metric},
        api_key=api_key,
        session=session,
        evidence_type="basic_financials",
        subject=ticker,
        symbol=ticker,
    )
