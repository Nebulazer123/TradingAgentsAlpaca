"""Loss-exit review packet helpers for the hourly supervisor.

This module only builds evidence packets and blocker lists. It does not size,
approve, submit, or cancel broker orders.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal

from tradingagents.policy.decision_authority import (
    POLICY_EXIT_REASONS,
    resolve_exit_authority,
)
from tradingagents.policy.exit_policy import (
    POLICY_STOP_FLOOR,
    verify_pre_registered_exit_policy,
)

UTC = datetime.timezone.utc

ALLOWED_LOSS_EXIT_REASONS = frozenset(
    {
        "thesis_invalidated",
        "company_specific_negative_news",
        "earnings_or_guidance_break",
        "hard_stop_defined_before_entry",
        "portfolio_exposure_limit",
        "user_manual_override",
    }
) | POLICY_EXIT_REASONS

RECENT_LOSS_EXIT_ALLOWED_REASONS = frozenset(
    {
        "thesis_invalidated",
        "hard_stop_defined_before_entry",
        "user_manual_override",
    }
) | frozenset({POLICY_STOP_FLOOR})

LOSS_EXIT_REASON_ALIASES = {
    "thesis_broken": "thesis_invalidated",
    "thesis broken": "thesis_invalidated",
    "invalidator": "thesis_invalidated",
    "invalidated": "thesis_invalidated",
    "company specific": "company_specific_negative_news",
    "company-specific": "company_specific_negative_news",
    "negative news": "company_specific_negative_news",
    "earnings": "earnings_or_guidance_break",
    "guidance": "earnings_or_guidance_break",
    "hard stop": "hard_stop_defined_before_entry",
    "portfolio exposure": "portfolio_exposure_limit",
    "manual override": "user_manual_override",
    "user override": "user_manual_override",
}


def loss_exit_review_packet(
    position: Mapping,
    *,
    generated_at: datetime.datetime,
    decision_id: str | None = None,
    side: str = "sell",
    proposed_order_id: str | None = None,
    proposed_limit_price: Decimal | int | float | str | None = None,
) -> dict:
    symbol = str(position.get("symbol", "")).upper()
    allowed_reason = _normalize_loss_exit_reason(position)
    current_price = _as_decimal(position.get("current_price"))
    avg_entry_price = _as_decimal(position.get("avg_entry_price"))
    proposed_price = (
        _as_decimal(proposed_limit_price, "0")
        if proposed_limit_price not in (None, "")
        else current_price
    )
    qty = _as_decimal(position.get("qty"), "0")
    stated_unrealized_loss = _as_decimal(position.get("unrealized_pl"), "0")
    realized_loss = (
        stated_unrealized_loss
        if stated_unrealized_loss < 0
        else (
            (proposed_price - avg_entry_price) * qty
            if qty > 0 and proposed_price > 0 and avg_entry_price > 0
            else stated_unrealized_loss
        )
    )
    holding_days = _holding_period_trading_days(position, generated_at=generated_at)
    original_buy_thesis = str(position.get("original_buy_thesis") or position.get("buy_thesis") or "").strip()
    current_thesis_status = str(position.get("current_thesis_status") or position.get("thesis_status") or "").strip()
    mechanical_policy_decision = verify_pre_registered_exit_policy(
        position,
        generated_at=generated_at,
        proposed_limit_price=proposed_limit_price,
    )
    allowed_reason_source = (
        position.get("allowed_exit_reason_source")
        if mechanical_policy_decision is not None
        else _exact_reason_source(position.get("allowed_exit_reason_source"))
    )
    company_news = str(
        position.get("company_specific_news_check")
        or position.get("company_news_check")
        or ""
    ).strip()
    earnings_check = str(position.get("earnings_guidance_or_filing_check") or "").strip()
    why_hold_worse = str(position.get("why_hold_is_worse_than_sell") or "").strip()
    anti_noise = str(position.get("why_this_is_not_broad_market_red_day_noise") or "").strip()
    source_packet_ids = position.get("source_packet_ids")
    if isinstance(source_packet_ids, str):
        source_ids = [item.strip() for item in source_packet_ids.split(",") if item.strip()]
    elif isinstance(source_packet_ids, Sequence) and not isinstance(source_packet_ids, (str, bytes)):
        source_ids = [str(item) for item in source_packet_ids if str(item).strip()]
    else:
        source_ids = []
    recent_fills = position.get("recent_same_symbol_fills")
    if not isinstance(recent_fills, list):
        recent_fills = []
    opened_at = None
    for key in ("opened_at", "entry_at", "buy_filled_at", "filled_at"):
        if position.get(key):
            opened_at = str(position.get(key))
            break
    confidence_raw = position.get("loss_exit_confidence", position.get("confidence"))
    confidence = _as_decimal(confidence_raw) if confidence_raw not in (None, "") else Decimal("0")
    blockers: list[str] = []
    review_decision_id = decision_id or f"loss-exit-{symbol}-{generated_at:%Y%m%d%H%M%S}"

    policy_rule_exit = mechanical_policy_decision is not None
    authority_source_ids = (
        source_ids
        or ([review_decision_id] if policy_rule_exit else [])
    )

    if current_price <= 0:
        blockers.append("current price evidence is missing")
    if avg_entry_price <= 0:
        blockers.append("average entry price evidence is missing")
    if current_price >= avg_entry_price and avg_entry_price > 0:
        blockers.append("position is not proven below average entry price")
    if allowed_reason not in ALLOWED_LOSS_EXIT_REASONS:
        blockers.append("allowed loss-exit reason is missing")
    if allowed_reason in POLICY_EXIT_REASONS and not policy_rule_exit:
        blockers.append("pre-registered policy exit does not match fresh policy evaluation")
    if allowed_reason_source is None:
        blockers.append("allowed loss-exit reason source is missing")
    if holding_days is None and not policy_rule_exit:
        blockers.append("holding period evidence is missing")
    elif (
        holding_days is not None
        and holding_days < 3
        and allowed_reason not in RECENT_LOSS_EXIT_ALLOWED_REASONS
    ):
        blockers.append("recent-position churn guard blocks opposite-side sell")
    if not policy_rule_exit:
        if not original_buy_thesis:
            blockers.append("original buy thesis is missing")
        if not current_thesis_status:
            blockers.append("current thesis status is missing")
        if not _market_context_has_required_benchmarks(position):
            blockers.append("SPY/QQQ/sector context is missing")
        if _market_context_is_broad_weakness(position):
            blockers.append("broad-market weakness is insufficient")
        if not company_news:
            blockers.append("company-specific news check is missing")
        if not earnings_check:
            blockers.append("earnings/guidance/filing check is missing")
        if not why_hold_worse:
            blockers.append("why HOLD is worse than SELL is missing")
        if not anti_noise:
            blockers.append("why this is not broad-market red-day noise is missing")
        if confidence <= 0:
            blockers.append("loss-exit confidence is missing")
        if not source_ids:
            blockers.append("source packet ids are missing")
    market_context = dict(_market_context_mapping(position))

    review = {
        "symbol": symbol,
        "side": side,
        "decision_id": review_decision_id,
        "proposed_order_id": proposed_order_id,
        "current_price": _price(current_price),
        "proposed_limit_price": _price(proposed_price),
        "average_entry_price": _price(avg_entry_price),
        "estimated_realized_loss": _money(realized_loss),
        "unrealized_pl": _money(position.get("unrealized_pl", "0")),
        "unrealized_pnl_percent": _pct(position.get("unrealized_plpc")),
        "unrealized_plpc": _pct(position.get("unrealized_plpc")),
        "holding_period_trading_days": holding_days,
        "opened_at": opened_at,
        "recent_same_symbol_fills": recent_fills,
        "original_entry_thesis": original_buy_thesis or None,
        "original_buy_thesis": original_buy_thesis or None,
        "current_thesis_status": current_thesis_status or None,
        "allowed_exit_reason_source": allowed_reason_source,
        "broad_market_context": market_context,
        "relative_performance_vs_SPY": market_context.get("relative_performance_vs_SPY")
        or market_context.get("spy")
        or position.get("relative_performance_vs_SPY"),
        "relative_performance_vs_QQQ": market_context.get("relative_performance_vs_QQQ")
        or market_context.get("qqq")
        or position.get("relative_performance_vs_QQQ"),
        "sector_or_peer_context": market_context.get("sector")
        or market_context.get("peer")
        or position.get("sector_or_peer_context"),
        "spy_qqq_sector_context": market_context,
        "company_specific_negative_news_check": company_news or None,
        "company_specific_news_check": company_news or None,
        "earnings_guidance_or_filing_check": earnings_check or None,
        "allowed_exit_reason": allowed_reason,
        "why_hold_is_worse_than_sell": why_hold_worse or None,
        "why_this_is_not_broad_market_red_day_noise": anti_noise or None,
        "confidence": str(confidence),
        "evidence_generated_at": generated_at.isoformat(timespec="seconds"),
        "source_packet_ids": authority_source_ids,
        "source_identity": "hourly_supervisor.loss_exit_review",
        "policy_rule_exit": policy_rule_exit,
        "exit_policy_rule": position.get("exit_policy_rule"),
        "exit_policy_rationale": position.get("exit_policy_rationale"),
        "exit_policy_loss_pct": (
            str(mechanical_policy_decision.loss_pct)
            if mechanical_policy_decision is not None
            else None
        ),
        "allowed": not blockers,
        "blocked_reasons": blockers,
        "blockers": blockers,
    }
    authority = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )
    return {
        **review,
        "allowed": authority.allowed,
        "authority_source": authority.authority_source,
        "requires_additional_decision": authority.requires_additional_decision,
        "decision_owner": authority.decision_owner,
    }


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _price(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _pct(value: Decimal | int | float | str | None) -> str:
    return str((_as_decimal(value) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _truthy_position_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "approved"}


def _normalize_loss_exit_reason(position: Mapping) -> str | None:
    for key in (
        "allowed_exit_reason",
        "exit_reason_code",
        "loss_exit_reason_code",
    ):
        value = str(position.get(key) or "").strip().lower()
        if value in ALLOWED_LOSS_EXIT_REASONS:
            return value
    for key, reason in (
        ("company_specific_negative_news", "company_specific_negative_news"),
        ("earnings_or_guidance_break", "earnings_or_guidance_break"),
        ("hard_stop_defined_before_entry", "hard_stop_defined_before_entry"),
        ("portfolio_exposure_limit", "portfolio_exposure_limit"),
        ("user_manual_override", "user_manual_override"),
        ("manual_override", "user_manual_override"),
    ):
        if _truthy_position_flag(position.get(key)):
            return reason
    if _thesis_invalidator_event(position.get("thesis_invalidator_event")):
        return "thesis_invalidated"
    exit_reason = str(position.get("exit_reason") or "").strip().lower()
    for token, reason in LOSS_EXIT_REASON_ALIASES.items():
        if reason == "thesis_invalidated":
            continue
        if token in exit_reason:
            return reason
    return None


def _exact_reason_source(value: object) -> dict[str, str] | None:
    """Reason authority is a bound packet identity, never a human-text label."""
    if not isinstance(value, Mapping) or set(value) != {"packet_id", "path", "sha256"}:
        return None
    packet_id, path, sha256 = (value.get(key) for key in ("packet_id", "path", "sha256"))
    if not all(isinstance(item, str) and item.strip() == item for item in (packet_id, path, sha256)):
        return None
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        return None
    return {"packet_id": packet_id, "path": path, "sha256": sha256}


def _thesis_invalidator_event(value: object) -> bool:
    """Only a dedicated normalized invalidator event can claim thesis failure."""
    if not isinstance(value, Mapping):
        return False
    return (
        set(value) == {"event_category", "source", "reason_source"}
        and value.get("event_category") == "thesis_invalidator"
        and value.get("source") == "normalized_company_news"
        and _exact_reason_source(value.get("reason_source")) is not None
    )


def _parse_position_time(value: object) -> datetime.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, datetime.date):
        parsed = datetime.datetime.combine(value, datetime.time.min)
    else:
        try:
            parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _holding_period_trading_days(
    position: Mapping,
    *,
    generated_at: datetime.datetime,
) -> int | None:
    explicit = position.get("holding_period_trading_days")
    if explicit not in (None, ""):
        try:
            return max(0, int(Decimal(str(explicit))))
        except Exception:
            return None
    opened_at = None
    for key in ("opened_at", "entry_at", "buy_filled_at", "filled_at"):
        opened_at = _parse_position_time(position.get(key))
        if opened_at is not None:
            break
    if opened_at is None:
        return None
    end = generated_at.astimezone(UTC)
    current = opened_at.date()
    end_date = end.date()
    days = 0
    while current < end_date:
        current += datetime.timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def _market_context_mapping(position: Mapping) -> Mapping:
    for key in ("relative_market_context", "market_context", "spy_qqq_sector_context"):
        value = position.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _market_context_has_required_benchmarks(position: Mapping) -> bool:
    context = _market_context_mapping(position)
    text = " ".join(
        str(position.get(key) or "")
        for key in (
            "spy_context",
            "qqq_context",
            "sector_context",
            "peer_context",
        )
    ).lower()
    return (
        all(key in context for key in ("spy", "qqq", "sector"))
        or ("spy" in text and "qqq" in text and "sector" in text)
    )


def _market_context_is_broad_weakness(position: Mapping) -> bool:
    context = _market_context_mapping(position)
    broad = _truthy_position_flag(context.get("broad_market_weakness")) or _truthy_position_flag(
        context.get("mostly_market_wide")
    )
    sector = _truthy_position_flag(context.get("sector_weakness"))
    company_damage = _truthy_position_flag(context.get("company_specific_damage")) or _truthy_position_flag(
        position.get("company_specific_damage")
    )
    return (broad or sector) and not company_damage
