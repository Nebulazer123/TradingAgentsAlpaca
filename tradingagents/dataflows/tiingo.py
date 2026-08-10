"""Tiingo evidence adapters for optional price/news enrichment.

Tiingo is a supplemental market-data route. Use it for research packets and
cross-checks, not as a live-trading authority.
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

BASE_URL = "https://api.tiingo.com"
ALLOWED_ENDPOINT_PREFIXES = (
    "tiingo/daily",
    "iex",
    "tiingo/news",
)


def _api_token(explicit: str | None = None) -> str:
    return env_value("TIINGO_API_KEY", explicit, required=True) or ""


def _ticker(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise OfficialDataError("Tiingo ticker is missing")
    return clean


def fetch_tiingo_route(
    route: str,
    *,
    params: dict[str, Any] | None = None,
    api_key: str | None = None,
    session: Any | None = None,
    evidence_type: str = "tiingo",
    subject: str | None = None,
    symbol: str | None = None,
):
    safe_route = validate_official_path(route, allowed_prefixes=ALLOWED_ENDPOINT_PREFIXES)
    url = f"{BASE_URL}/{safe_route}"
    request_params = dict(params or {})
    headers = {"Authorization": f"Token {_api_token(api_key)}"}
    payload = get_json(url, params=request_params, headers=headers, session=session)
    as_of = extract_payload_timestamp(payload, ("date", "timestamp", "publishedDate"))
    return evidence_packet(
        source_name="tiingo",
        evidence_type=evidence_type,
        subject=subject or safe_route,
        symbol=symbol,
        source_ref=safe_source_ref(url, request_params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", url, request_params, None),
        tool_route="tiingo_api",
    )


def fetch_tiingo_daily_prices(
    ticker: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    api_key: str | None = None,
    session: Any | None = None,
):
    symbol = _ticker(ticker)
    params: dict[str, Any] = {}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    return fetch_tiingo_route(
        f"tiingo/daily/{symbol}/prices",
        params=params,
        api_key=api_key,
        session=session,
        evidence_type="daily_prices",
        subject=symbol,
        symbol=symbol,
    )


def fetch_tiingo_ticker_metadata(
    ticker: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
):
    symbol = _ticker(ticker)
    return fetch_tiingo_route(
        f"tiingo/daily/{symbol}",
        api_key=api_key,
        session=session,
        evidence_type="ticker_metadata",
        subject=symbol,
        symbol=symbol,
    )


def fetch_tiingo_news(
    *,
    tickers: list[str] | None = None,
    query: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    api_key: str | None = None,
    session: Any | None = None,
):
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 100))}
    clean_tickers = [ticker.strip().upper() for ticker in (tickers or []) if ticker and ticker.strip()]
    if clean_tickers:
        params["tickers"] = ",".join(clean_tickers)
    if query and query.strip():
        params["query"] = query.strip()
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    if "tickers" not in params and "query" not in params:
        raise OfficialDataError("Tiingo news requires tickers or query")
    subject = params.get("tickers") or params.get("query") or "tiingo_news"
    return fetch_tiingo_route(
        "tiingo/news",
        params=params,
        api_key=api_key,
        session=session,
        evidence_type="market_news",
        subject=str(subject),
        symbol=clean_tickers[0] if len(clean_tickers) == 1 else None,
    )
