"""Read-only yfinance options/IV context.

This adapter is a supplemental research route for options open interest, volume,
and implied volatility. It never creates trade intents or execution signals.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tradingagents.dataflows._official_common import (
    OfficialDataError,
    evidence_packet,
    now_iso,
    request_hash,
)

OPTION_FIELDS = (
    "contractSymbol",
    "lastTradeDate",
    "strike",
    "lastPrice",
    "bid",
    "ask",
    "change",
    "percentChange",
    "volume",
    "openInterest",
    "impliedVolatility",
    "inTheMoney",
    "contractSize",
    "currency",
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


def _records_from_frame(frame: Any, *, option_type: str, max_contracts: int) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []
    records = [
        {field: _json_safe(row.get(field)) for field in OPTION_FIELDS if field in row}
        for row in frame.to_dict(orient="records")
    ]
    for record in records:
        record["option_type"] = option_type
        bid = _float_value(record.get("bid"))
        ask = _float_value(record.get("ask"))
        if bid is not None and ask is not None and bid >= 0 and ask >= 0:
            record["mid"] = round((bid + ask) / 2, 4)
            if record["mid"] > 0:
                record["spread_pct_mid"] = round((ask - bid) / record["mid"], 4)
    records.sort(
        key=lambda item: (
            _float_value(item.get("volume")) or 0.0,
            _float_value(item.get("openInterest")) or 0.0,
        ),
        reverse=True,
    )
    return records[: max(1, int(max_contracts))]


def _sum_numeric(records: Iterable[dict[str, Any]], key: str) -> float:
    return round(sum(_float_value(record.get(key)) or 0.0 for record in records), 4)


def _weighted_average(records: Iterable[dict[str, Any]], value_key: str, weight_key: str) -> float | None:
    total_weight = 0.0
    weighted_sum = 0.0
    for record in records:
        value = _float_value(record.get(value_key))
        weight = _float_value(record.get(weight_key)) or 0.0
        if value is None or weight <= 0:
            continue
        total_weight += weight
        weighted_sum += value * weight
    if total_weight <= 0:
        return None
    return round(weighted_sum / total_weight, 6)


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def fetch_yfinance_options_iv_flow(
    symbol: str,
    *,
    max_expirations: int = 2,
    max_contracts_per_side: int = 25,
) -> Any:
    """Fetch supplemental options IV/open-interest context from yfinance."""

    import yfinance as yf

    ticker_symbol = symbol.strip().upper()
    if not ticker_symbol:
        raise OfficialDataError("ticker symbol is required")
    ticker = yf.Ticker(ticker_symbol)
    expirations = list(getattr(ticker, "options", None) or [])
    if not expirations:
        raise OfficialDataError(f"yfinance returned no option expirations for {ticker_symbol}")

    expiration_packets: list[dict[str, Any]] = []
    all_calls: list[dict[str, Any]] = []
    all_puts: list[dict[str, Any]] = []
    for expiration in expirations[: max(1, int(max_expirations))]:
        chain = ticker.option_chain(expiration)
        calls = _records_from_frame(
            getattr(chain, "calls", None),
            option_type="call",
            max_contracts=max_contracts_per_side,
        )
        puts = _records_from_frame(
            getattr(chain, "puts", None),
            option_type="put",
            max_contracts=max_contracts_per_side,
        )
        all_calls.extend(calls)
        all_puts.extend(puts)
        call_volume = _sum_numeric(calls, "volume")
        put_volume = _sum_numeric(puts, "volume")
        call_open_interest = _sum_numeric(calls, "openInterest")
        put_open_interest = _sum_numeric(puts, "openInterest")
        expiration_packets.append(
            {
                "expiration": str(expiration),
                "call_contract_count": len(calls),
                "put_contract_count": len(puts),
                "call_volume": call_volume,
                "put_volume": put_volume,
                "put_call_volume_ratio": _ratio(put_volume, call_volume),
                "call_open_interest": call_open_interest,
                "put_open_interest": put_open_interest,
                "put_call_open_interest_ratio": _ratio(put_open_interest, call_open_interest),
                "call_iv_weighted_by_open_interest": _weighted_average(
                    calls,
                    "impliedVolatility",
                    "openInterest",
                ),
                "put_iv_weighted_by_open_interest": _weighted_average(
                    puts,
                    "impliedVolatility",
                    "openInterest",
                ),
                "top_call_contracts_by_volume": calls[:5],
                "top_put_contracts_by_volume": puts[:5],
            }
        )

    total_call_volume = _sum_numeric(all_calls, "volume")
    total_put_volume = _sum_numeric(all_puts, "volume")
    total_call_open_interest = _sum_numeric(all_calls, "openInterest")
    total_put_open_interest = _sum_numeric(all_puts, "openInterest")
    as_of = now_iso()
    payload = {
        "symbol": ticker_symbol,
        "status": "options_iv_flow_available",
        "as_of": as_of,
        "expiration_count_available": len(expirations),
        "expiration_count_sampled": len(expiration_packets),
        "sampled_expirations": [item["expiration"] for item in expiration_packets],
        "total_call_volume_sample": total_call_volume,
        "total_put_volume_sample": total_put_volume,
        "put_call_volume_ratio_sample": _ratio(total_put_volume, total_call_volume),
        "total_call_open_interest_sample": total_call_open_interest,
        "total_put_open_interest_sample": total_put_open_interest,
        "put_call_open_interest_ratio_sample": _ratio(
            total_put_open_interest,
            total_call_open_interest,
        ),
        "call_iv_weighted_by_open_interest_sample": _weighted_average(
            all_calls,
            "impliedVolatility",
            "openInterest",
        ),
        "put_iv_weighted_by_open_interest_sample": _weighted_average(
            all_puts,
            "impliedVolatility",
            "openInterest",
        ),
        "expirations": expiration_packets,
        "limitations": [
            "supplemental public yfinance options data, not an exchange-grade feed",
            "sample is limited to near expirations and top contracts by volume",
            "use for advisory confirmation/downrank only, never direct execution",
        ],
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
    }
    source_ref = f"https://finance.yahoo.com/quote/{ticker_symbol}/options"
    return evidence_packet(
        source_name="yfinance_options",
        evidence_type="options_iv_flow",
        subject=f"yfinance options IV/open-interest context for {ticker_symbol}",
        symbol=ticker_symbol,
        source_ref=source_ref,
        payload=payload,
        quality="low",
        as_of=as_of,
        request_fingerprint=request_hash(
            "GET",
            source_ref,
            {
                "symbol": ticker_symbol,
                "max_expirations": max_expirations,
                "max_contracts_per_side": max_contracts_per_side,
            },
            None,
        ),
        tool_route="dataflow:yfinance_options",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "route": "dataflow:yfinance_options",
            "downrank_evidence": True,
            "connector_status": "configured_public_supplemental",
        },
    )
