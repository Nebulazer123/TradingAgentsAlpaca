"""Massive.com market-data evidence adapters.

Massive is the Polygon replacement path. These adapters are research-only and
write sanitized evidence packets; they do not stream or place orders.
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

BASE_URL = "https://api.massive.com"
ALLOWED_ENDPOINT_PREFIXES = (
    "v3/reference/tickers",
    "v2/aggs/ticker",
    "v2/aggs/grouped/locale/us/market/stocks",
    "v2/snapshot/locale/us/markets/stocks/tickers",
    "v1/open-close",
    "v2/last/trade",
    "v2/last/nbbo",
)


def _api_key(explicit: str | None = None) -> str:
    return (
        env_value("MASSIVE_API_KEY", explicit)
        or env_value("POLYGON_API_KEY", explicit, required=True)
        or ""
    )


def _ticker(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise OfficialDataError("Massive ticker is missing")
    return clean


def fetch_massive_route(
    route: str,
    *,
    params: dict[str, Any] | None = None,
    api_key: str | None = None,
    session: Any | None = None,
    evidence_type: str = "market_data",
    subject: str | None = None,
    symbol: str | None = None,
) -> Any:
    safe_route = validate_official_path(route, allowed_prefixes=ALLOWED_ENDPOINT_PREFIXES)
    url = f"{BASE_URL}/{safe_route}"
    request_params = dict(params or {})
    request_params["apiKey"] = _api_key(api_key)
    payload = get_json(url, params=request_params, session=session)
    as_of = extract_payload_timestamp(
        payload,
        ("updated", "last_updated", "timestamp", "from", "date"),
    )
    return evidence_packet(
        source_name="massive",
        evidence_type=evidence_type,
        subject=subject or safe_route,
        symbol=symbol,
        source_ref=safe_source_ref(url, request_params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", url, request_params, None),
        tool_route="massive_api",
    )


def fetch_massive_ticker_overview(
    ticker: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    symbol = _ticker(ticker)
    return fetch_massive_route(
        f"v3/reference/tickers/{symbol}",
        api_key=api_key,
        session=session,
        evidence_type="ticker_overview",
        subject=symbol,
        symbol=symbol,
    )


def fetch_massive_previous_day_bar(
    ticker: str,
    *,
    adjusted: bool = True,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    symbol = _ticker(ticker)
    return fetch_massive_route(
        f"v2/aggs/ticker/{symbol}/prev",
        params={"adjusted": str(bool(adjusted)).lower()},
        api_key=api_key,
        session=session,
        evidence_type="previous_day_bar",
        subject=symbol,
        symbol=symbol,
    )


def fetch_massive_daily_prices(
    ticker: str,
    *,
    start_date: str,
    end_date: str,
    adjusted: bool = True,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    symbol = _ticker(ticker)
    if not start_date or not end_date:
        raise OfficialDataError("Massive daily prices require start_date and end_date")
    return fetch_massive_route(
        f"v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}",
        params={
            "adjusted": str(bool(adjusted)).lower(),
            "sort": "asc",
            "limit": 5000,
        },
        api_key=api_key,
        session=session,
        evidence_type="daily_prices",
        subject=symbol,
        symbol=symbol,
    )


def fetch_massive_grouped_daily(
    date: str,
    *,
    adjusted: bool = True,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    return fetch_massive_route(
        f"v2/aggs/grouped/locale/us/market/stocks/{date}",
        params={"adjusted": str(bool(adjusted)).lower()},
        api_key=api_key,
        session=session,
        evidence_type="grouped_daily_bars",
        subject=date,
    )
