"""StockTwits public symbol-stream fetcher.

StockTwits exposes a per-symbol message stream at
``api.stocktwits.com/api/2/streams/symbol/{ticker}.json`` that requires no
API key, no OAuth, and no registration. Each message includes a
user-labeled sentiment field (``Bullish``/``Bearish``/null), the message
body, timestamp, and posting user.

The function is deliberately self-contained: short timeout, graceful
degradation on any HTTP or parse failure, and a string return type so
the calling agent gets a uniform interface regardless of whether the
network call succeeded.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from tradingagents.dataflows._official_common import (
    OfficialDataError,
    get_text,
    record_connector_health,
)

logger = logging.getLogger(__name__)

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"


def _parse_window_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _created_at_date(value: object) -> datetime.date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _date_window_label(start_date: str | None, end_date: str | None) -> str:
    if start_date and end_date:
        return f"{start_date} to {end_date}"
    if start_date:
        return f"since {start_date}"
    if end_date:
        return f"through {end_date}"
    return "most-recent messages"


def _in_date_window(message: dict, start_date: str | None, end_date: str | None) -> bool:
    created = _created_at_date(message.get("created_at"))
    if created is None:
        return True
    start = _parse_window_date(start_date)
    end = _parse_window_date(end_date)
    if start and created < start:
        return False
    return not (end and created > end)


def fetch_stocktwits_messages(
    ticker: str,
    limit: int = 30,
    timeout: float = 10.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Fetch recent StockTwits messages for ``ticker`` and return them as a
    formatted plaintext block ready for prompt injection.

    Returns a placeholder string when the endpoint is unreachable, the
    symbol has no messages, or the response shape is unexpected — the
    caller never has to special-case None or exceptions.
    """
    url = _API.format(ticker=ticker.upper())
    try:
        text = get_text(
            url,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=timeout,
            connector_name="stocktwits_public",
        )
        data = json.loads(text)
    except OfficialDataError as exc:
        logger.warning("StockTwits fetch failed for %s: %s", ticker, exc)
        return f"<stocktwits unavailable: {type(exc).__name__}>"
    except json.JSONDecodeError as exc:
        record_connector_health(
            "stocktwits_public",
            success=False,
            error="JSONDecodeError: StockTwits endpoint returned invalid JSON",
            write=True,
        )
        logger.warning("StockTwits fetch failed for %s: %s", ticker, exc)
        return f"<stocktwits unavailable: {type(exc).__name__}>"

    messages = data.get("messages", []) if isinstance(data, dict) else []
    messages = [message for message in messages if isinstance(message, dict)]
    messages = [message for message in messages if _in_date_window(message, start_date, end_date)]
    window_label = _date_window_label(start_date, end_date)
    if not messages:
        return f"<no StockTwits messages found for ${ticker.upper()} in {window_label}>"

    lines = []
    bullish = bearish = unlabeled = 0
    for m in messages[:limit]:
        created = m.get("created_at", "")
        user = (m.get("user") or {}).get("username", "?")
        entities = m.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic") if isinstance(sentiment_obj, dict) else None
        body = (m.get("body") or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"

        if sentiment == "Bullish":
            bullish += 1
            tag = "Bullish"
        elif sentiment == "Bearish":
            bearish += 1
            tag = "Bearish"
        else:
            unlabeled += 1
            tag = "no-label"
        lines.append(f"[{created} · @{user} · {tag}] {body}")

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    summary = (
        f"Bullish: {bullish} ({bull_pct}%) · "
        f"Bearish: {bearish} ({bear_pct}%) · "
        f"Unlabeled: {unlabeled} · "
        f"Total: {total} messages in {window_label}"
    )
    return summary + "\n\n" + "\n".join(lines)
