"""Unified go-live guard for any supervisor path that can submit live orders."""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from tradingagents.brokers.alpaca import OrderIssue
from tradingagents.policy.integrity import verify_state_integrity
from tradingagents.policy.live_control import load_live_control_state
from tradingagents.policy.order_rate_limit import evaluate_order_rate_limit
from tradingagents.policy.risk_envelope import RiskEnvelope, load_risk_envelope

STRICT_ALLOWED_LOSS_EXIT_REASONS = frozenset(
    {
        "thesis_invalidated",
        "company_specific_negative_news",
        "earnings_or_guidance_break",
        "hard_stop_defined_before_entry",
        "portfolio_exposure_limit",
        "user_manual_override",
    }
)

LOSS_EXIT_REVIEW_REQUIRED_FIELDS = (
    "symbol",
    "side",
    "decision_id",
    "current_price",
    "average_entry_price",
    "estimated_realized_loss",
    "unrealized_pnl_percent",
    "holding_period_trading_days",
    "original_entry_thesis",
    "current_thesis_status",
    "allowed_exit_reason",
    "allowed_exit_reason_source",
    "broad_market_context",
    "relative_performance_vs_SPY",
    "relative_performance_vs_QQQ",
    "company_specific_negative_news_check",
    "earnings_guidance_or_filing_check",
    "why_hold_is_worse_than_sell",
    "why_this_is_not_broad_market_red_day_noise",
    "confidence",
    "evidence_generated_at",
    "source_packet_ids",
    "allowed",
    "blocked_reasons",
)


@dataclass(frozen=True)
class LiveGateResult:
    allowed: bool
    issues: list[OrderIssue] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)


def _action_value(action: Any, name: str, default: Any = None) -> Any:
    if isinstance(action, dict):
        return action.get(name, default)
    return getattr(action, name, default)


def _action_symbol(action: Any) -> str:
    return str(_action_value(action, "symbol", "LIVE_GATE")).upper()


def _is_live_order_action(action: Any) -> bool:
    action_name = str(_action_value(action, "action", "")).lower()
    account = str(_action_value(action, "account", "")).lower()
    order_type = str(_action_value(action, "order_type", "")).lower()
    return (
        account == "live"
        and action_name not in {"hold", "hold_cash", ""}
        and order_type not in {"none", ""}
    )


def _read_promotion_state(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists():
        return {}, [f"promotion state missing at {path}"]
    raw_text = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return {}, [f"promotion state is invalid JSON: {exc}"]
    if not isinstance(parsed, dict):
        return {}, ["promotion state must be a JSON object"]
    integrity_issues = verify_state_integrity(path, raw_text)
    return parsed, integrity_issues


def _promotion_issues(action: Any, promotion_state: dict[str, Any]) -> list[str]:
    sleeve = str(_action_value(action, "sleeve", "")).strip()
    if not sleeve:
        return ["live action has no sleeve identity for promotion gate"]
    sleeves = promotion_state.get("sleeves")
    if not isinstance(sleeves, dict):
        return ["promotion state has no sleeves map"]
    state = sleeves.get(sleeve)
    if not isinstance(state, dict):
        return [f"sleeve {sleeve} has no promotion record"]

    issues: list[str] = []
    if state.get("stage") != "tiny_live_eligible":
        issues.append(f"sleeve {sleeve} is not tiny_live_eligible")
    if state.get("live_enabled") is not True:
        issues.append(f"sleeve {sleeve} live_enabled is not true")
    if state.get("preregistered") is not True:
        issues.append(f"sleeve {sleeve} preregistered is not true")
    if state.get("ci_green") is not True:
        issues.append(f"sleeve {sleeve} ci_green is not true")
    if state.get("shadow_confirmed") is not True:
        issues.append(f"sleeve {sleeve} shadow_confirmed is not true")
    for gate_name in (
        "benchmark_gate_passed",
        "cost_gate_passed",
        "recent_alpha_gate_passed",
        "capacity_gate_passed",
    ):
        if state.get(gate_name) is not True:
            issues.append(f"sleeve {sleeve} {gate_name} is not true")
    if not state.get("validation_report_ref"):
        issues.append(f"sleeve {sleeve} validation_report_ref is missing")
    if not state.get("risk_envelope_ref"):
        issues.append(f"sleeve {sleeve} risk_envelope_ref is missing")
    return issues


def _decimal_action_value(action: Any, name: str) -> Decimal:
    return Decimal(str(_action_value(action, name, "0")))


def _is_buy_action(action: Any) -> bool:
    side = str(_action_value(action, "side", "")).lower()
    action_name = str(_action_value(action, "action", "")).lower()
    return side == "buy" or action_name == "buy"


def _is_sell_action(action: Any) -> bool:
    side = str(_action_value(action, "side", "")).lower()
    action_name = str(_action_value(action, "action", "")).lower()
    return side == "sell" or action_name in {"close", "reduce", "rotate", "sell"}


def _position_by_symbol(positions: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(position.get("symbol", "")).upper(): position
        for position in positions
        if isinstance(position, Mapping) and position.get("symbol")
    }


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        if value is None or value == "":
            return None
        return Decimal(str(value))
    except Exception:
        return None


def _review_from_action_or_decision(
    action: Any,
    decision_evidence: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    action_evidence = _action_value(action, "evidence", None)
    for evidence in (action_evidence, decision_evidence):
        if isinstance(evidence, Mapping):
            review = evidence.get("loss_exit_review")
            if isinstance(review, Mapping):
                return review
    return None


def _missing_review_fields(review: Mapping[str, Any]) -> list[str]:
    missing = []
    for review_field in LOSS_EXIT_REVIEW_REQUIRED_FIELDS:
        value = review.get(review_field)
        if review_field == "blocked_reasons":
            if value is None:
                missing.append(review_field)
            continue
        if value in (None, "", []):
            missing.append(review_field)
    source_packet_ids = review.get("source_packet_ids")
    if (
        (not isinstance(source_packet_ids, list) or not source_packet_ids)
        and "source_packet_ids" not in missing
    ):
        missing.append("source_packet_ids")
    return missing


def _current_action_identity(action: Any) -> tuple[str, str, str]:
    return (
        str(_action_value(action, "decision_id", "") or ""),
        str(
            _action_value(action, "client_order_id", "")
            or _action_value(action, "idempotency_key", "")
            or ""
        ),
        str(_action_value(action, "symbol", "") or "").upper(),
    )


def _loss_exit_review_issues(
    action: Any,
    review: Mapping[str, Any] | None,
    *,
    now: datetime.datetime | None,
) -> list[str]:
    if review is None:
        return ["loss_exit_review is missing"]
    issues = _missing_review_fields(review)
    if review.get("allowed") is not True:
        issues.append("loss_exit_review.allowed is not true")
    reason = str(review.get("allowed_exit_reason") or "")
    if reason not in STRICT_ALLOWED_LOSS_EXIT_REASONS:
        issues.append(
            "allowed_exit_reason must be one of "
            + ", ".join(sorted(STRICT_ALLOWED_LOSS_EXIT_REASONS))
        )

    action_decision_id, action_client_order_id, action_symbol = _current_action_identity(action)
    review_decision_id = str(review.get("decision_id") or "")
    if action_decision_id and review_decision_id != action_decision_id:
        issues.append("decision_id does not match current action")
    if action_symbol and str(review.get("symbol") or "").upper() != action_symbol:
        issues.append("symbol does not match current action")
    action_side = "sell" if _is_sell_action(action) else str(_action_value(action, "side", "")).lower()
    if action_side and str(review.get("side") or "").lower() != action_side:
        issues.append("side does not match current action")
    if action_client_order_id:
        review_order_id = str(review.get("client_order_id") or review.get("proposed_order_id") or "")
        if review_order_id and review_order_id != action_client_order_id:
            issues.append("client_order_id/proposed_order_id does not match current action")

    generated_at = review.get("evidence_generated_at")
    if now is not None and generated_at:
        try:
            parsed = datetime.datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        except ValueError:
            issues.append("evidence_generated_at is not an ISO timestamp")
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            age = now.astimezone(datetime.timezone.utc) - parsed.astimezone(
                datetime.timezone.utc
            )
            if age < datetime.timedelta(0) or age > datetime.timedelta(hours=6):
                issues.append("loss_exit_review is stale for current submit")
    return sorted(set(issues))


def _final_submit_loss_gate_issues(
    live_actions: Sequence[Any],
    *,
    live_positions: Sequence[Mapping[str, Any]],
    decision_evidence: Mapping[str, Any] | None,
    now: datetime.datetime | None,
) -> list[OrderIssue]:
    positions = _position_by_symbol(live_positions)
    issues: list[OrderIssue] = []
    for action in live_actions:
        if not _is_sell_action(action):
            continue
        symbol = _action_symbol(action)
        position = positions.get(symbol)
        if not position:
            issues.append(
                OrderIssue(
                    symbol,
                    (
                        "final_submit_loss_gate_blocked: current live position "
                        "snapshot is missing for sell action"
                    ),
                )
            )
            continue
        proposed_price = _decimal_or_none(
            _action_value(action, "limit_price")
            or _action_value(action, "proposed_limit_price")
            or position.get("current_price")
        )
        avg_entry = _decimal_or_none(
            position.get("avg_entry_price") or position.get("average_entry_price")
        )
        if (
            proposed_price is not None
            and avg_entry is not None
            and avg_entry > Decimal("0")
            and proposed_price >= avg_entry
        ):
            # Confirmed non-loss sell (proposed price at or above entry): the
            # loss-exit review is not required.
            continue
        # Either a confirmed loss, or price/entry-price provenance is incomplete.
        # Fail closed: require a valid loss-exit review instead of skipping the gate.
        review = _review_from_action_or_decision(action, decision_evidence)
        failed = _loss_exit_review_issues(action, review, now=now)
        if failed:
            issues.append(
                OrderIssue(
                    symbol,
                    "final_submit_loss_gate_blocked: " + "; ".join(failed),
                )
            )
    return issues


def _risk_cap_issues(action: Any, envelope: RiskEnvelope) -> list[str]:
    notional = _decimal_action_value(action, "notional")
    issues: list[str] = []
    if envelope.live_budget_mode == "autonomous_uncapped":
        return issues
    if (
        envelope.live_budget_mode != "autonomous_with_caps"
        and notional > envelope.tiny_live_tranche_usd
    ):
        issues.append(
            f"live action notional {notional} exceeds tiny_live_tranche_usd "
            f"{envelope.tiny_live_tranche_usd}"
        )
    if notional > envelope.per_name_cap_usd:
        issues.append(
            f"live action notional {notional} exceeds per_name_cap_usd "
            f"{envelope.per_name_cap_usd}"
        )
    return issues


def _portfolio_circuit_breaker_issues(
    action: Any,
    envelope: RiskEnvelope,
    *,
    current_daily_loss_usd: Decimal | None,
    current_drawdown_pct: Decimal | None,
) -> list[str]:
    if not _is_buy_action(action):
        return []
    issues: list[str] = []
    if (
        current_daily_loss_usd is not None
        and current_daily_loss_usd >= envelope.daily_loss_halt_usd
    ):
        issues.append(
            f"portfolio circuit breaker blocked new live buy: current daily loss "
            f"{current_daily_loss_usd} meets or exceeds daily_loss_halt_usd "
            f"{envelope.daily_loss_halt_usd}"
        )
    if (
        current_drawdown_pct is not None
        and current_drawdown_pct >= envelope.max_drawdown_halt_pct
    ):
        issues.append(
            f"portfolio circuit breaker blocked new live buy: current drawdown "
            f"{current_drawdown_pct} meets or exceeds max_drawdown_halt_pct "
            f"{envelope.max_drawdown_halt_pct}"
        )
    return issues


def _broker_buying_power_issues(
    action: Any,
    *,
    live_buying_power: Decimal | None,
    projected_buy_notional: Decimal,
) -> list[str]:
    if not _is_buy_action(action):
        return []
    symbol = _action_symbol(action)
    if live_buying_power is None:
        return [
            f"broker buying_power is missing for final live buy validation on {symbol}"
        ]
    if projected_buy_notional > live_buying_power:
        return [
            f"projected live buy notional {projected_buy_notional} exceeds broker "
            f"buying_power {live_buying_power}"
        ]
    return []


def evaluate_go_live_guard(
    actions: Sequence[Any],
    *,
    risk_envelope_path: str | Path = "config/risk_envelope.yaml",
    promotion_state_path: str | Path = "results/policy/promotion_state.json",
    control_state_path: str | Path = "results/policy/live_control.json",
    order_rate_state_path: str | Path = "results/policy/live_order_rate_state.json",
    current_live_exposure: Decimal = Decimal("0"),
    current_daily_loss_usd: Decimal | None = None,
    current_drawdown_pct: Decimal | None = None,
    live_buying_power: Decimal | None = None,
    live_positions: Sequence[Mapping[str, Any]] = (),
    decision_evidence: Mapping[str, Any] | None = None,
    now: datetime.datetime | None = None,
) -> LiveGateResult:
    live_actions = [action for action in actions if _is_live_order_action(action)]
    if not live_actions:
        return LiveGateResult(allowed=True, checks={"no_live_actions": True})

    issues: list[OrderIssue] = []
    checks: dict[str, bool] = {
        "risk_envelope_loaded": False,
        "promotion_state_loaded": False,
        "control_state_loaded": False,
        "live_not_frozen": False,
        "dead_man_fresh": False,
        "tiny_live_only": True,
        "risk_caps": True,
        "account_hard_ceiling": True,
        "order_rate_limit": True,
        "portfolio_circuit_breakers": True,
        "autonomous_live_budget": False,
        "autonomous_live_budget_uncapped": False,
        "promotion": True,
        "loss_exit_review": True,
        "broker_buying_power": True,
        "current_live_exposure_considered": current_live_exposure > Decimal("0"),
        "daily_loss_considered": current_daily_loss_usd is not None,
        "drawdown_considered": current_drawdown_pct is not None,
        "broker_buying_power_considered": live_buying_power is not None,
    }

    envelope, envelope_issues = load_risk_envelope(risk_envelope_path)
    if envelope_issues:
        checks["risk_envelope_loaded"] = False
        issues.extend(OrderIssue(_action_symbol(action), issue) for action in live_actions for issue in envelope_issues)
    else:
        checks["risk_envelope_loaded"] = True
        checks["autonomous_live_budget"] = envelope.live_budget_mode in {
            "autonomous_with_caps",
            "autonomous_uncapped",
        }
        checks["autonomous_live_budget_uncapped"] = (
            envelope.live_budget_mode == "autonomous_uncapped"
        )

    promotion_state, state_issues = _read_promotion_state(Path(promotion_state_path))
    if state_issues:
        checks["promotion_state_loaded"] = False
        issues.extend(OrderIssue(_action_symbol(action), issue) for action in live_actions for issue in state_issues)
    else:
        checks["promotion_state_loaded"] = True

    control_state, control_issues = load_live_control_state(control_state_path, now=now)
    if control_issues:
        checks["control_state_loaded"] = control_state is not None
        checks["live_not_frozen"] = not any("frozen" in issue for issue in control_issues)
        checks["dead_man_fresh"] = not any("dead-man" in issue or "dead_man" in issue for issue in control_issues)
        issues.extend(OrderIssue(_action_symbol(action), issue) for action in live_actions for issue in control_issues)
    else:
        checks["control_state_loaded"] = True
        checks["live_not_frozen"] = True
        checks["dead_man_fresh"] = True

    total_buy_notional = Decimal("0")
    for action in live_actions:
        execution_mode = str(_action_value(action, "execution_mode", "")).lower()
        if execution_mode != "tiny_live":
            checks["tiny_live_only"] = False
            issues.append(
                OrderIssue(
                    _action_symbol(action),
                    f"live action must use tiny_live execution_mode; got {execution_mode or 'missing'}",
                )
            )

        asset_class = str(_action_value(action, "asset_class", "")).lower()
        order_type = str(_action_value(action, "order_type", "")).lower()
        if asset_class != "stock":
            issues.append(OrderIssue(_action_symbol(action), "live gate allows stock orders only"))
        if order_type != "limit":
            issues.append(OrderIssue(_action_symbol(action), "live gate allows limit orders only"))

        if envelope is not None and _is_buy_action(action):
            proposed_buy_notional = _decimal_action_value(action, "notional")
            projected_buy_notional = total_buy_notional + proposed_buy_notional
            broker_issues = _broker_buying_power_issues(
                action,
                live_buying_power=live_buying_power,
                projected_buy_notional=projected_buy_notional,
            )
            if broker_issues:
                checks["broker_buying_power"] = False
                issues.extend(
                    OrderIssue(_action_symbol(action), issue)
                    for issue in broker_issues
                )
            cap_issues = _risk_cap_issues(action, envelope)
            if cap_issues:
                checks["risk_caps"] = False
                issues.extend(OrderIssue(_action_symbol(action), issue) for issue in cap_issues)
            breaker_issues = _portfolio_circuit_breaker_issues(
                action,
                envelope,
                current_daily_loss_usd=current_daily_loss_usd,
                current_drawdown_pct=current_drawdown_pct,
            )
            if breaker_issues:
                checks["portfolio_circuit_breakers"] = False
                issues.extend(
                    OrderIssue(_action_symbol(action), issue)
                    for issue in breaker_issues
                )
            total_buy_notional = projected_buy_notional

        if promotion_state:
            action_promotion_issues = _promotion_issues(action, promotion_state)
            if action_promotion_issues:
                checks["promotion"] = False
                issues.extend(OrderIssue(_action_symbol(action), issue) for issue in action_promotion_issues)

    loss_gate_issues = _final_submit_loss_gate_issues(
        live_actions,
        live_positions=live_positions,
        decision_evidence=decision_evidence,
        now=now,
    )
    if loss_gate_issues:
        checks["loss_exit_review"] = False
        issues.extend(loss_gate_issues)

    if (
        envelope is not None
        and envelope.live_budget_mode != "autonomous_uncapped"
        and current_live_exposure + total_buy_notional > envelope.account_max_capital_at_risk_usd
    ):
        checks["risk_caps"] = False
        issues.append(
            OrderIssue(
                "LIVE_GATE",
                f"projected live exposure {current_live_exposure + total_buy_notional} "
                f"(current {current_live_exposure} + new buy {total_buy_notional}) exceeds "
                f"account_max_capital_at_risk_usd {envelope.account_max_capital_at_risk_usd}",
            )
        )

    # Hard account-exposure ceiling applies in EVERY live_budget_mode (including
    # autonomous_uncapped). Inert unless account_hard_ceiling_usd is configured.
    if (
        envelope is not None
        and envelope.account_hard_ceiling_usd is not None
        and current_live_exposure + total_buy_notional > envelope.account_hard_ceiling_usd
    ):
        checks["account_hard_ceiling"] = False
        issues.append(
            OrderIssue(
                "LIVE_GATE",
                f"projected live exposure {current_live_exposure + total_buy_notional} "
                f"(current {current_live_exposure} + new buy {total_buy_notional}) exceeds "
                f"account_hard_ceiling_usd {envelope.account_hard_ceiling_usd}",
            )
        )

    # Rolling-window live-order rate limit. Inert unless BOTH
    # max_live_orders_per_window and live_order_window_minutes are configured.
    if (
        envelope is not None
        and envelope.max_live_orders_per_window is not None
        and envelope.live_order_window_minutes is not None
    ):
        rate_issues = evaluate_order_rate_limit(
            path=order_rate_state_path,
            now=now or datetime.datetime.now(tz=datetime.timezone.utc),
            window_minutes=envelope.live_order_window_minutes,
            max_orders=envelope.max_live_orders_per_window,
            new_order_count=len(live_actions),
        )
        if rate_issues:
            checks["order_rate_limit"] = False
            issues.extend(OrderIssue("LIVE_GATE", issue) for issue in rate_issues)

    return LiveGateResult(
        allowed=not issues,
        issues=issues,
        checks=checks,
    )
