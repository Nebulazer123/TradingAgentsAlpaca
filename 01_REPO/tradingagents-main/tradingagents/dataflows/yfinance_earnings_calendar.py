"""Read-only yfinance earnings-calendar context.

This adapter is a supplemental public route for company earnings dates and
calendar metadata. It is useful for event-risk awareness, but it is not an
official company filing or exchange-grade calendar feed and never carries
execution authority.
"""

from __future__ import annotations

from typing import Any

from tradingagents.dataflows._official_common import (
    DataUnavailableError,
    OfficialDataError,
    evidence_packet,
    now_iso,
    request_hash,
)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _records_from_frame(frame: Any, *, max_rows: int) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []
    if not hasattr(frame, "to_dict"):
        return []
    records = frame.to_dict(orient="records")
    if not isinstance(records, list):
        return []
    safe_records = []
    for record in records[: max(1, int(max_rows))]:
        if isinstance(record, dict):
            safe_records.append({str(key): _json_safe(value) for key, value in record.items()})
    return safe_records


def _calendar_payload(calendar: Any) -> dict[str, Any]:
    if calendar is None:
        return {}
    if isinstance(calendar, dict):
        return {str(key): _json_safe(value) for key, value in calendar.items()}
    if hasattr(calendar, "to_dict"):
        value = calendar.to_dict()
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
    return {}


def fetch_yfinance_earnings_calendar(
    symbol: str,
    *,
    max_rows: int = 8,
) -> Any:
    """Fetch supplemental earnings-calendar context from yfinance."""

    import yfinance as yf

    ticker_symbol = symbol.strip().upper()
    if not ticker_symbol:
        raise OfficialDataError("ticker symbol is required")
    ticker = yf.Ticker(ticker_symbol)

    calendar = _calendar_payload(getattr(ticker, "calendar", None))
    earnings_dates: list[dict[str, Any]] = []
    if hasattr(ticker, "get_earnings_dates"):
        earnings_dates = _records_from_frame(
            ticker.get_earnings_dates(limit=max(1, int(max_rows))),
            max_rows=max_rows,
        )

    if not calendar and not earnings_dates:
        raise DataUnavailableError(
            f"yfinance returned no earnings calendar data for {ticker_symbol}"
        )

    as_of = now_iso()
    payload = {
        "symbol": ticker_symbol,
        "status": "earnings_calendar_available",
        "as_of": as_of,
        "calendar": calendar,
        "earnings_dates": earnings_dates,
        "earnings_date_count": len(earnings_dates),
        "limitations": [
            "supplemental public yfinance calendar data, not an issuer or exchange-grade calendar",
            "dates can revise; refresh before trading around earnings events",
            "use for advisory event-risk/downrank context only, never direct execution",
        ],
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
    }
    source_ref = f"https://finance.yahoo.com/quote/{ticker_symbol}/analysis"
    return evidence_packet(
        source_name="yfinance_earnings_calendar",
        evidence_type="earnings_calendar",
        subject=f"yfinance earnings-calendar context for {ticker_symbol}",
        symbol=ticker_symbol,
        source_ref=source_ref,
        payload=payload,
        quality="low",
        as_of=as_of,
        request_fingerprint=request_hash(
            "GET",
            source_ref,
            {"symbol": ticker_symbol, "max_rows": max_rows},
            None,
        ),
        tool_route="dataflow:yfinance_earnings_calendar",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "route": "dataflow:yfinance_earnings_calendar",
            "downrank_evidence": True,
            "connector_status": "configured_public_supplemental",
        },
    )
