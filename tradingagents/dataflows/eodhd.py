"""EODHD evidence adapters for optional research enrichment."""

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

BASE_URL = "https://eodhd.com/api"


def _api_token(explicit: str | None = None) -> str:
    return (
        env_value("EODHD_API_TOKEN", explicit)
        or env_value("EODHD_API_KEY", explicit, required=True)
        or ""
    )


def _symbol(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise OfficialDataError("EODHD symbol is missing")
    return clean


def _packet(
    *,
    evidence_type: str,
    subject: str,
    url: str,
    params: dict[str, Any],
    payload: dict[str, Any],
    symbol: str | None = None,
) -> Any:
    as_of = extract_payload_timestamp(
        payload,
        ("date", "datetime", "publishedDate", "published_at", "timestamp"),
    )
    return evidence_packet(
        source_name="eodhd",
        evidence_type=evidence_type,
        subject=subject,
        symbol=symbol,
        source_ref=safe_source_ref(url, params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", url, params, None),
        tool_route="eodhd_api",
    )


def fetch_eodhd_fundamentals(
    symbol: str,
    *,
    api_token: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    url = f"{BASE_URL}/fundamentals/{ticker}"
    params = {"api_token": _api_token(api_token), "fmt": "json"}
    payload = get_json(url, params=params, session=session)
    return _packet(
        evidence_type="fundamentals",
        subject=ticker,
        symbol=ticker.split(".")[0],
        url=url,
        params=params,
        payload=payload,
    )


def fetch_eodhd_news(
    *,
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
    api_token: str | None = None,
    session: Any | None = None,
) -> Any:
    url = f"{BASE_URL}/news"
    params: dict[str, Any] = {
        "api_token": _api_token(api_token),
        "fmt": "json",
        "limit": max(1, min(int(limit), 100)),
    }
    if symbol:
        params["s"] = _symbol(symbol)
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    payload = get_json(url, params=params, session=session)
    subject = _symbol(symbol) if symbol else "global"
    return _packet(
        evidence_type="news",
        subject=subject,
        symbol=subject.split(".")[0] if symbol else None,
        url=url,
        params=params,
        payload=payload,
    )


def fetch_eodhd_sentiments(
    symbols: Iterable[str],
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    api_token: str | None = None,
    session: Any | None = None,
) -> Any:
    tickers = [_symbol(symbol) for symbol in symbols]
    if not tickers:
        raise OfficialDataError("EODHD sentiments require at least one symbol")
    url = f"{BASE_URL}/sentiments"
    params: dict[str, Any] = {
        "s": ",".join(tickers),
        "api_token": _api_token(api_token),
        "fmt": "json",
    }
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    payload = get_json(url, params=params, session=session)
    return _packet(
        evidence_type="sentiments",
        subject=",".join(tickers),
        symbol=tickers[0].split(".")[0] if len(tickers) == 1 else None,
        url=url,
        params=params,
        payload=payload,
    )
