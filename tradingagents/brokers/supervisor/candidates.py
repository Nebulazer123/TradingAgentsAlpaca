"""Candidate ranking and sizing helpers for the Alpaca supervisor."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

MEGA_CAP_AI_UNIVERSE = (
    "GOOGL",
    "MSFT",
    "NVDA",
    "AAPL",
    "AMZN",
    "META",
    "AVGO",
    "TSM",
    "AMD",
    "ORCL",
)
CROWDED_AI_BETA_SYMBOLS = frozenset(
    {
        "AAPL",
        "AMAT",
        "AMD",
        "AMZN",
        "AVGO",
        "GOOGL",
        "INTC",
        "META",
        "MSFT",
        "NVDA",
        "ORCL",
        "QCOM",
        "TSM",
        "TXN",
    }
)
DEEP_RESEARCH_POSITIVE_RELATIVE_SYMBOLS = frozenset(
    {
        "BAC",
        "CAT",
        "COST",
        "CVX",
        "HD",
        "IBM",
        "JNJ",
        "JPM",
        "KO",
        "MA",
        "PEP",
        "PG",
        "UNH",
        "V",
        "WMT",
        "XOM",
    }
)
DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS = (
    "HOOD",
    "BULL",
    "IBKR",
    "SCHW",
)
LIQUID_SP100_STYLE_UNIVERSE = (
    "ADBE",
    "CRM",
    "NFLX",
    "COST",
    "LLY",
    "JPM",
    "V",
    "MA",
    "UNH",
    "HD",
    "PG",
    "XOM",
    "CVX",
    "JNJ",
    "BAC",
    "WMT",
    "KO",
    "PEP",
    "CSCO",
    "QCOM",
    "INTC",
    "IBM",
    "NOW",
    "TXN",
    "AMAT",
    "CAT",
)

AGGRESSIVE_CANDIDATE_UNIVERSE = tuple(
    dict.fromkeys(
        MEGA_CAP_AI_UNIVERSE
        + LIQUID_SP100_STYLE_UNIVERSE
        + DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS
    )
)

MIN_LIVE_BUY_NOTIONAL = Decimal("5")
DEFAULT_LIVE_BUY_NOTIONAL = Decimal("25")


@dataclass(frozen=True)
class CandidateSignal:
    symbol: str
    score: Decimal
    current_price: Decimal
    previous_close: Decimal | None = None
    day_change_pct: Decimal = Decimal("0")
    volume_ratio: Decimal = Decimal("1")
    time_sensitive: bool = False
    source: str = "market_data"
    reason: str = ""


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _truthy_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(value)
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _falsey_flag(value: object) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float, Decimal)):
        return not bool(value)
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"0", "false", "no", "n", "off"}


def _quantized_score(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("0.95"), value)).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )


def is_chase_buy_candidate(candidate: CandidateSignal) -> bool:
    """Return True when a buy would chase a move that already ran."""

    reason = candidate.reason.lower()
    return (
        candidate.day_change_pct >= Decimal("0.020")
        or "green spike" in reason
        or "do not chase" in reason
    )


def is_buy_entry_candidate(candidate: CandidateSignal) -> bool:
    return not is_chase_buy_candidate(candidate)


def choose_autonomous_live_buy_notional(
    candidate: CandidateSignal,
    available_notional: Decimal,
    *,
    floor_notional: Decimal = DEFAULT_LIVE_BUY_NOTIONAL,
) -> Decimal:
    """Let the sleeve size a live buy while staying inside the supplied cap."""

    available = _as_decimal(available_notional)
    if available < MIN_LIVE_BUY_NOTIONAL:
        return Decimal("0")
    if available < floor_notional:
        return available.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    score = _as_decimal(candidate.score)
    if score >= Decimal("0.90"):
        fraction = Decimal("0.50")
    elif score >= Decimal("0.85"):
        fraction = Decimal("0.40")
    elif score >= Decimal("0.80"):
        fraction = Decimal("0.30")
    elif score >= Decimal("0.75"):
        fraction = Decimal("0.25")
    else:
        fraction = Decimal("0.20")
    sized = (available * fraction).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if available >= floor_notional:
        sized = max(floor_notional, sized)
    else:
        sized = max(MIN_LIVE_BUY_NOTIONAL, sized)
    return min(available, sized).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def aggressive_limit_price(
    price: Decimal | int | float | str,
    *,
    side: str,
    extended_hours: bool = False,
) -> Decimal:
    raw = _as_decimal(price, "0")
    buffer = Decimal("1.003") if extended_hours else Decimal("1.002")
    if side.lower() == "sell":
        buffer = Decimal("0.997") if extended_hours else Decimal("0.998")
    return (raw * buffer).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def build_candidate_signals(
    market_data: Mapping[str, Mapping[str, Any]],
    *,
    held_symbols: Iterable[str] = (),
) -> list[CandidateSignal]:
    held = {symbol.upper() for symbol in held_symbols}
    signals: list[CandidateSignal] = []
    for symbol, data in market_data.items():
        upper = symbol.upper()
        if upper not in AGGRESSIVE_CANDIDATE_UNIVERSE:
            continue
        if data.get("tradable") is False:
            continue
        if _truthy_flag(data.get("stale_quote")) or _falsey_flag(data.get("quote_fresh")):
            continue
        current = _as_decimal(data.get("current_price") or data.get("price"))
        if current <= 0:
            continue
        previous = _as_decimal(data.get("previous_close") or current)
        day_change = Decimal("0")
        if previous > 0:
            day_change = (current - previous) / previous
        volume_ratio = _as_decimal(data.get("volume_ratio"), "1")
        controlled_dip = Decimal("-0.030") <= day_change <= Decimal("-0.003")
        falling_knife = day_change < Decimal("-0.040")
        green_spike = day_change >= Decimal("0.020")
        if controlled_dip:
            score = Decimal("0.72") + (abs(day_change) * Decimal("3"))
            reason = (
                f"controlled dip {day_change:.2%}; buy-the-dip candidate if support/volume checks stay clean, "
                f"volume ratio {volume_ratio}"
            )
            time_sensitive = True
        elif green_spike:
            score = Decimal("0.43") - (min(day_change, Decimal("0.08")) * Decimal("1.5"))
            reason = (
                f"green spike {day_change:.2%}; do not chase after the move, "
                f"volume ratio {volume_ratio}"
            )
            time_sensitive = False
        elif falling_knife:
            score = Decimal("0.30")
            reason = (
                f"sharp drop {day_change:.2%}; falling-knife watch only until support reclaims, "
                f"volume ratio {volume_ratio}"
            )
            time_sensitive = False
        else:
            score = Decimal("0.50") + (day_change * Decimal("2"))
            reason = (
                f"neutral drift {day_change:.2%}, "
                f"volume ratio {volume_ratio}, paper-first eligible"
            )
            time_sensitive = False
        if upper in MEGA_CAP_AI_UNIVERSE:
            score += Decimal("0.05")
        if controlled_dip and volume_ratio >= Decimal("1.0"):
            score += Decimal("0.04")
        elif not green_spike and volume_ratio >= Decimal("1.5"):
            score += Decimal("0.08")
        if _truthy_flag(data.get("deep_research_positive_relative_bias")) and not green_spike and not falling_knife:
            score += Decimal("0.06") if controlled_dip else Decimal("0.04")
            reason = (
                f"{reason}; report-33 macro window favors quality/energy/defensive "
                "relative-strength setups over crowded growth when price action is not a chase"
            )
        has_flow_confirmation = any(
            _truthy_flag(data.get(key))
            for key in (
                "institutional_confirmation",
                "independent_flow_confirmation",
                "broker_flow_confirmation",
            )
        )
        if _truthy_flag(data.get("bot_copycat_attention")) and not has_flow_confirmation:
            score -= Decimal("0.12")
            reason = (
                f"{reason}; MiroFish bot-copycat attention is unconfirmed by institutional/flow "
                "evidence, so treat social momentum as false-signal risk"
            )
        if (
            _truthy_flag(data.get("macro_event_risk"))
            and (_truthy_flag(data.get("ai_beta_crowding_risk")) or upper in CROWDED_AI_BETA_SYMBOLS)
        ):
            score -= Decimal("0.07")
            reason = (
                f"{reason}; crowded AI beta during macro event risk gets downranked until "
                "post-data confirmation appears"
            )
        if _truthy_flag(data.get("deep_research_event_sensitive_watch")) and not _truthy_flag(
            data.get("broker_flow_confirmation")
        ):
            score -= Decimal("0.05")
            reason = (
                f"{reason}; broker/fintech rule-change watch names require real broker/flow "
                "confirmation before they can outrank cleaner setups"
            )
        if _truthy_flag(data.get("mirofish_false_signal_suppression")) and not has_flow_confirmation:
            score -= Decimal("0.08")
            gates = data.get("mirofish_triggered_advisory_gates") or []
            gate_text = ", ".join(str(gate) for gate in gates[:4]) if isinstance(gates, Sequence) else ""
            reason = (
                f"{reason}; MiroFish advisory gates"
                f"{f' ({gate_text})' if gate_text else ''} suppress unconfirmed crowded/social "
                "or broker-friction signals until independent confirmation appears"
            )
        if upper in held:
            score -= Decimal("0.05")
        signals.append(
            CandidateSignal(
                symbol=upper,
                score=_quantized_score(score),
                current_price=current,
                previous_close=previous,
                day_change_pct=day_change,
                volume_ratio=volume_ratio,
                time_sensitive=time_sensitive,
                source=str(data.get("source", "market_data")),
                reason=reason,
            )
        )
    return sorted(signals, key=lambda signal: signal.score, reverse=True)

