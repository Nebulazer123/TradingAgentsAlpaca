"""Read-only yfinance short-interest context.

This adapter is a supplemental research route for public short-interest fields
that yfinance exposes from Yahoo metadata. It is not exchange-grade data and
never creates trade intents or execution signals.
"""

from __future__ import annotations

from typing import Any

from tradingagents.dataflows._official_common import (
    OfficialDataError,
    evidence_packet,
    now_iso,
    request_hash,
)

SHORT_INTEREST_FIELDS = (
    "sharesShort",
    "sharesShortPriorMonth",
    "sharesShortPreviousMonthDate",
    "dateShortInterest",
    "shortRatio",
    "shortPercentOfFloat",
    "sharesPercentSharesOut",
    "floatShares",
    "sharesOutstanding",
    "heldPercentInstitutions",
    "heldPercentInsiders",
)
REQUIRED_SHORT_INTEREST_FIELDS = (
    "sharesShort",
    "sharesShortPriorMonth",
    "dateShortInterest",
    "shortRatio",
    "shortPercentOfFloat",
    "sharesPercentSharesOut",
)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        if hasattr(value, "item"):
            return _json_safe(value.item())
    except Exception:  # noqa: BLE001 - best-effort normalization for numpy/pandas scalars.
        pass
    return str(value)


def _float_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _epoch_to_iso(value: Any) -> str | None:
    number = _float_value(value)
    if number is None or number <= 0:
        return None
    import datetime as dt

    return dt.datetime.fromtimestamp(number, tz=dt.UTC).date().isoformat()


def fetch_yfinance_short_interest(symbol: str) -> Any:
    """Fetch supplemental public short-interest context from yfinance."""

    import yfinance as yf

    ticker_symbol = symbol.strip().upper()
    if not ticker_symbol:
        raise OfficialDataError("ticker symbol is required")
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.get_info() if hasattr(ticker, "get_info") else getattr(ticker, "info", None)
    if not isinstance(info, dict):
        raise OfficialDataError(f"yfinance returned no metadata for {ticker_symbol}")

    raw_fields = {
        field: _json_safe(info.get(field))
        for field in SHORT_INTEREST_FIELDS
        if info.get(field) is not None
    }
    if not any(info.get(field) is not None for field in REQUIRED_SHORT_INTEREST_FIELDS):
        raise OfficialDataError(f"yfinance returned no short-interest fields for {ticker_symbol}")

    shares_short = _float_value(info.get("sharesShort"))
    shares_short_prior = _float_value(info.get("sharesShortPriorMonth"))
    short_delta = (
        round(shares_short - shares_short_prior, 4)
        if shares_short is not None and shares_short_prior is not None
        else None
    )
    short_delta_pct = (
        round(short_delta / shares_short_prior, 6)
        if short_delta is not None and shares_short_prior and shares_short_prior > 0
        else None
    )
    as_of = now_iso()
    payload = {
        "symbol": ticker_symbol,
        "status": "short_interest_context_available",
        "as_of": as_of,
        "raw_fields": raw_fields,
        "date_short_interest": _epoch_to_iso(info.get("dateShortInterest")),
        "shares_short": shares_short,
        "shares_short_prior_month": shares_short_prior,
        "shares_short_delta": short_delta,
        "shares_short_delta_pct": short_delta_pct,
        "short_ratio_days_to_cover": _float_value(info.get("shortRatio")),
        "short_percent_of_float": _float_value(info.get("shortPercentOfFloat")),
        "shares_percent_shares_out": _float_value(info.get("sharesPercentSharesOut")),
        "float_shares": _float_value(info.get("floatShares")),
        "shares_outstanding": _float_value(info.get("sharesOutstanding")),
        "limitations": [
            "supplemental public yfinance metadata, not exchange-grade short-interest data",
            "short-interest fields may update slowly and can lag official exchange publications",
            "use for advisory confirmation/downrank only, never direct execution",
        ],
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
    }
    source_ref = f"https://finance.yahoo.com/quote/{ticker_symbol}/key-statistics"
    return evidence_packet(
        source_name="yfinance_short_interest",
        evidence_type="short_interest",
        subject=f"yfinance short-interest context for {ticker_symbol}",
        symbol=ticker_symbol,
        source_ref=source_ref,
        payload=payload,
        quality="low",
        as_of=as_of,
        request_fingerprint=request_hash("GET", source_ref, {"symbol": ticker_symbol}, None),
        tool_route="dataflow:yfinance_short_interest",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "route": "dataflow:yfinance_short_interest",
            "downrank_evidence": True,
            "connector_status": "configured_public_supplemental",
        },
    )
