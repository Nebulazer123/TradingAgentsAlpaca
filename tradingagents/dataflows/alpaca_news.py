"""Alpaca market-data news evidence adapter.

Alpaca is execution/account truth elsewhere in the repo. This adapter is
read-only and writes news evidence packets only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ._official_common import (
    OfficialDataError,
    evidence_packet,
    extract_payload_timestamp,
    get_json,
    request_hash,
    safe_source_ref,
)

ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


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


def fetch_alpaca_news(
    *,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    include_content: bool = False,
    api_key: str | None = None,
    secret_key: str | None = None,
    environ: Mapping[str, str] | None = None,
    session: Any | None = None,
):
    clean_symbols = [symbol.strip().upper() for symbol in (symbols or []) if symbol and symbol.strip()]
    params: dict[str, Any] = {
        "limit": max(1, min(int(limit), 50)),
        "sort": "desc",
        "include_content": str(bool(include_content)).lower(),
    }
    if clean_symbols:
        params["symbols"] = ",".join(clean_symbols)
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    headers = _headers(api_key=api_key, secret_key=secret_key, environ=environ)
    payload = get_json(ALPACA_NEWS_URL, params=params, headers=headers, session=session)
    as_of = extract_payload_timestamp(payload, ("updated_at", "created_at", "published_at"))
    subject = params.get("symbols") or "latest_alpaca_news"
    return evidence_packet(
        source_name="alpaca_news",
        evidence_type="market_news",
        subject=str(subject),
        symbol=clean_symbols[0] if len(clean_symbols) == 1 else None,
        source_ref=safe_source_ref(ALPACA_NEWS_URL, params),
        payload=payload,
        quality="medium",
        as_of=as_of,
        request_fingerprint=request_hash("GET", ALPACA_NEWS_URL, params, None),
        tool_route="alpaca_news_read_only",
        redaction_status="redacted",
        freshness_extra={"read_only": True, "execution_authority": "none"},
    )
