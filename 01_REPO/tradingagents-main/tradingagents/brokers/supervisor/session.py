"""Market-session labeling helpers for supervisor automations."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

UTC = datetime.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")


def market_session_label(now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now(tz=UTC)
    local = now.astimezone(CENTRAL)
    if local.weekday() >= 5:
        return "closed"
    minutes = local.hour * 60 + local.minute
    if 8 * 60 <= minutes < 8 * 60 + 30:
        return "pre_open"
    if 8 * 60 + 30 <= minutes < 10 * 60:
        return "open_window"
    if 10 * 60 <= minutes < 14 * 60 + 30:
        return "regular"
    if 14 * 60 + 30 <= minutes < 15 * 60:
        return "pre_close"
    if 15 * 60 <= minutes < 15 * 60 + 30:
        return "after_close"
    return "closed"


def can_trade_session(session: str) -> bool:
    return session in {"pre_open", "open_window", "regular", "pre_close", "after_close"}

