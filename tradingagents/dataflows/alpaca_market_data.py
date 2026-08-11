"""Alpaca read-only market-data evidence adapters."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from ._official_common import (
    OfficialDataError,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
)

ALPACA_LATEST_TRADES_URL = "https://data.alpaca.markets/v2/stocks/trades/latest"
ALPACA_STOCK_FEEDS = {"sip", "iex", "delayed_sip", "boats", "overnight", "otc"}


def _read_windows_user_env(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value) if value is not None else None
    except OSError:
        return None


def _env(name: str, explicit: str | None = None, environ: Mapping[str, str] | None = None) -> str:
    if explicit is not None and explicit.strip():
        return explicit.strip()
    env = os.environ if environ is None else environ
    value = (env.get(name) or _read_windows_user_env(name) or "").strip()
    if not value:
        raise OfficialDataError(f"{name} is missing")
    return value


def _headers(
    *,
    api_key: str | None = None,
    secret_key: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": _env("ALPACA_PAPER_API_KEY", api_key, environ),
        "APCA-API-SECRET-KEY": _env("ALPACA_PAPER_SECRET_KEY", secret_key, environ),
    }


def _symbols(symbols: Sequence[str]) -> list[str]:
    clean = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    if not clean:
        raise OfficialDataError("Alpaca latest trades require at least one symbol")
    return sorted(set(clean))


def fetch_alpaca_latest_trades(
    symbols: Sequence[str],
    *,
    api_key: str | None = None,
    secret_key: str | None = None,
    environ: Mapping[str, str] | None = None,
    session: Any | None = None,
    feed: str = "iex",
):
    """Fetch latest stock trades from Alpaca market data without broker authority."""

    tickers = _symbols(symbols)
    selected_feed = feed.strip().lower()
    if selected_feed not in ALPACA_STOCK_FEEDS:
        raise OfficialDataError(
            f"Unsupported Alpaca stock feed {feed!r}; expected one of {sorted(ALPACA_STOCK_FEEDS)}"
        )
    params = {"symbols": ",".join(tickers), "feed": selected_feed}
    headers = _headers(api_key=api_key, secret_key=secret_key, environ=environ)
    payload = get_json(ALPACA_LATEST_TRADES_URL, params=params, headers=headers, session=session)
    as_of = extract_payload_timestamp(payload, ("t", "timestamp"))
    return evidence_packet(
        source_name="alpaca_market_data",
        evidence_type="quote_price_context",
        subject=params["symbols"],
        symbol=tickers[0] if len(tickers) == 1 else None,
        source_ref=safe_source_ref(ALPACA_LATEST_TRADES_URL, params),
        payload={
            "request_context": {"feed": selected_feed, "symbols": tickers},
            "semantic_caveat": (
                "Latest-trade results exclude trade conditions that do not update bar price "
                "and are not a complete tape."
            ),
            "data": payload,
        },
        quality="high",
        as_of=as_of,
        request_fingerprint=request_hash("GET", ALPACA_LATEST_TRADES_URL, params, None),
        tool_route="alpaca_market_data_read_only",
        redaction_status="redacted",
        freshness_extra={
            "read_only": True,
            "feed": selected_feed,
            "execution_authority": "none",
            "forbidden_effects": [
                "create_trade_intent",
                "size_position",
                "submit_order",
                "promote_sleeve",
                "waive_live_gate",
            ],
        },
    )
