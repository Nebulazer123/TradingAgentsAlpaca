"""Shared supervisor formatting helpers."""

from __future__ import annotations

import re
from decimal import Decimal

#: Owner-facing names for internal strategy ids. Bodies of emails must never
#: show raw strategy ids.
STRATEGY_DISPLAY_NAMES = {
    "current-aggressive": "the aggressive strategy",
    "pullback-support": "the buy-the-dip strategy",
    "catalyst-relative-strength": "the momentum strategy",
}


def strategy_display_name(strategy_id: object) -> str:
    key = str(strategy_id or "").strip()
    return STRATEGY_DISPLAY_NAMES.get(key, "an experimental strategy")


#: Ordered (pattern, plain sentence) rules that turn machine reasons into
#: sentences a non-technical owner can act on. First match wins.
_PLAIN_REASON_RULES: tuple[tuple[str, str], ...] = (
    (
        "exit approved loss",
        "A losing stock hit its pre-set safety stop, so it was sold to cap "
        "the damage. The freed cash stays in cash until a clean setup appears.",
    ),
    (
        "loss review",
        "One stock is down enough that the rules require a review before "
        "selling at a loss. It is being held while the facts are gathered.",
    ),
    (
        "crossed loss review",
        "One stock is down enough that the rules require a review before "
        "selling at a loss. The system is holding it while it collects the "
        "facts that decision needs.",
    ),
    (
        "dead-man",
        "The safety timer that allows real-money orders has expired, so no "
        "real-money trades can happen until it is renewed.",
    ),
    (
        "promotion",
        "The strategy asking to trade real money has not earned that "
        "permission yet, so the order was stopped.",
    ),
    (
        "buying power",
        "The account does not have enough available cash for that order, so "
        "nothing was bought.",
    ),
    (
        "exposure limit",
        "The order would have put more money at risk than the safety limit "
        "allows, so it was stopped.",
    ),
    (
        "graph run",
        "The overnight research assistant hit a technical fault, so last "
        "night's stock research used the simpler backup ranking instead.",
    ),
    (
        "stale",
        "Some of the market information was too old to trust, so the system "
        "played it safe and skipped acting on it.",
    ),
    (
        "guardrail validation",
        "A safety check stopped the planned orders before any money moved.",
    ),
    (
        "market session is not tradeable",
        "The market is closed right now, so no orders can happen until it "
        "reopens.",
    ),
)


def plain_language_reason(reason: object, *, default: str | None = None) -> str:
    """Translate a machine reason string into one plain-language sentence."""
    text = str(reason or "").strip()
    lowered = text.lower()
    for needle, sentence in _PLAIN_REASON_RULES:
        if needle in lowered:
            return sentence
    if default is not None:
        return default
    return email_reason_text(text) if text else "Nothing unusual happened."


def email_reason_text(reason: object, *, max_length: int = 190) -> str:
    text = str(reason or "no supervisor packets found").strip()

    def _round_long_decimal(match: re.Match[str]) -> str:
        try:
            return f"{Decimal(match.group(0)):.2f}"
        except Exception:
            return match.group(0)

    text = re.sub(r"\b\d+\.\d{5,}\b", _round_long_decimal, text)
    if len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text
