"""Financial Modeling Prep evidence adapters for optional research enrichment."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ._official_common import (
    DataUnavailableError,
    OfficialDataError,
    env_value,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
    validate_official_path,
)

BASE_URL = "https://financialmodelingprep.com/stable"
ALLOWED_ENDPOINT_PREFIXES = (
    "search-symbol",
    "profile",
    "quote",
    "quote-short",
    "news/stock",
    "earning-call-transcript",
    "earning-call-transcript-dates",
    "earning-call-transcript-latest",
    "earnings-transcript-list",
    "income-statement",
    "balance-sheet-statement",
    "cash-flow-statement",
    "key-metrics",
    "ratios",
)


def _api_key(explicit: str | None = None) -> str:
    return env_value("FMP_API_KEY", explicit, required=True) or ""


def _symbol(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise OfficialDataError("FMP symbol is missing")
    return clean


def fetch_fmp_route(
    route: str,
    *,
    params: dict[str, Any] | None = None,
    api_key: str | None = None,
    session: Any | None = None,
    evidence_type: str = "financial_data",
    subject: str | None = None,
    symbol: str | None = None,
) -> Any:
    safe_route = validate_official_path(route, allowed_prefixes=ALLOWED_ENDPOINT_PREFIXES)
    url = f"{BASE_URL}/{safe_route}"
    request_params = dict(params or {})
    request_params["apikey"] = _api_key(api_key)
    payload = get_json(url, params=request_params, session=session)
    as_of = extract_payload_timestamp(payload, ("date", "publishedDate", "timestamp"))
    return evidence_packet(
        source_name="fmp",
        evidence_type=evidence_type,
        subject=subject or safe_route,
        symbol=symbol,
        source_ref=safe_source_ref(url, request_params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", url, request_params, None),
        tool_route="fmp_api",
    )


def fetch_fmp_symbol_search(
    query: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    clean = query.strip()
    if not clean:
        raise OfficialDataError("FMP search query is missing")
    return fetch_fmp_route(
        "search-symbol",
        params={"query": clean},
        api_key=api_key,
        session=session,
        evidence_type="symbol_search",
        subject=clean,
    )


def fetch_fmp_company_profile(
    symbol: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    return fetch_fmp_route(
        "profile",
        params={"symbol": ticker},
        api_key=api_key,
        session=session,
        evidence_type="company_profile",
        subject=ticker,
        symbol=ticker,
    )


def fetch_fmp_quote(
    symbol: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    return fetch_fmp_route(
        "quote-short",
        params={"symbol": ticker},
        api_key=api_key,
        session=session,
        evidence_type="quote",
        subject=ticker,
        symbol=ticker,
    )


def fetch_fmp_stock_news(
    symbols: Iterable[str],
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    tickers = [_symbol(symbol) for symbol in symbols]
    if not tickers:
        raise OfficialDataError("FMP stock news requires at least one symbol")
    params: dict[str, Any] = {
        "symbols": ",".join(tickers),
        "limit": max(1, min(int(limit), 100)),
    }
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return fetch_fmp_route(
        "news/stock",
        params=params,
        api_key=api_key,
        session=session,
        evidence_type="stock_news",
        subject=",".join(tickers),
        symbol=tickers[0] if len(tickers) == 1 else None,
    )


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "transcripts", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _int_value(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _transcript_text(item: dict[str, Any]) -> str:
    for key in ("content", "transcript", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def fetch_fmp_earning_call_transcript(
    symbol: str,
    *,
    year: int,
    quarter: int,
    published_at: str | None = None,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    fiscal_year = int(year)
    fiscal_quarter = int(quarter)
    if fiscal_quarter < 1 or fiscal_quarter > 4:
        raise OfficialDataError("FMP earnings transcript quarter must be 1-4")
    packet = fetch_fmp_route(
        "earning-call-transcript",
        params={"symbol": ticker, "year": fiscal_year, "quarter": fiscal_quarter},
        api_key=api_key,
        session=session,
        evidence_type="earnings_transcripts",
        subject=f"{ticker} Q{fiscal_quarter} {fiscal_year} earnings call transcript",
        symbol=ticker,
    )
    transcript_items = _items(packet.payload)
    if not any(_transcript_text(item) for item in transcript_items):
        raise DataUnavailableError(
            f"FMP returned no transcript text for {ticker} Q{fiscal_quarter} {fiscal_year}"
        )
    packet.freshness["read_only"] = True
    packet.freshness["route"] = "dataflow:fmp"
    provider_published_at = published_at or next(
        (str(item.get("date") or item.get("publishedDate") or "") for item in transcript_items if item.get("date") or item.get("publishedDate")),
        "",
    )
    if not provider_published_at:
        raise DataUnavailableError(
            f"FMP transcript lacks a provider publication timestamp for {ticker} Q{fiscal_quarter} {fiscal_year}"
        )
    packet.payload = {
        "symbol": ticker,
        "year": fiscal_year,
        "quarter": fiscal_quarter,
        "published_at": provider_published_at,
        "transcript_items": transcript_items,
        "transcript_item_count": len(transcript_items),
        "transcript_char_count": sum(len(_transcript_text(item)) for item in transcript_items),
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
    }
    return packet


def fetch_fmp_earning_call_transcript_dates(
    symbol: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    return fetch_fmp_route(
        "earning-call-transcript-dates",
        params={"symbol": ticker},
        api_key=api_key,
        session=session,
        evidence_type="earnings_transcript_dates",
        subject=f"{ticker} earnings transcript dates",
        symbol=ticker,
    )


def fetch_fmp_latest_earning_call_transcript(
    symbol: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
) -> Any:
    ticker = _symbol(symbol)
    dates_packet = fetch_fmp_earning_call_transcript_dates(
        ticker,
        api_key=api_key,
        session=session,
    )
    date_items = _items(dates_packet.payload)
    dated_candidates: list[tuple[str, int, int]] = []
    for item in date_items:
        year = _int_value(item.get("year"))
        quarter = _int_value(item.get("quarter"))
        if year is None or quarter is None:
            continue
        sort_date = str(item.get("date") or item.get("fiscalDateEnding") or "")
        dated_candidates.append((sort_date, year, quarter))
    if not dated_candidates:
        raise DataUnavailableError(
            f"FMP returned no earnings transcript dates for {ticker}"
        )
    latest_date, latest_year, latest_quarter = sorted(dated_candidates, reverse=True)[0]
    return fetch_fmp_earning_call_transcript(
        ticker,
        year=latest_year,
        quarter=latest_quarter,
        published_at=latest_date,
        api_key=api_key,
        session=session,
    )
