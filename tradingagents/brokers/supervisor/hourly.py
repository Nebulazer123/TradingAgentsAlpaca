"""Hourly supervisor packet helpers.

This module owns compact hourly packet summaries and pure hourly decision
context helpers. It has no order submission authority.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from tradingagents.brokers.supervisor.alert import (
    human_supervisor_summary,
    supervisor_issue_category_counts,
    supervisor_issue_dict,
)
from tradingagents.brokers.supervisor.candidates import (
    MIN_LIVE_BUY_NOTIONAL,
    CandidateSignal,
    aggressive_limit_price,
    choose_autonomous_live_buy_notional,
    is_buy_entry_candidate,
)
from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.brokers.supervisor.types import (
    HourlySupervisorAction,
    HourlySupervisorConfig,
    HourlySupervisorDecision,
)
from tradingagents.policy.exit_policy import apply_exit_policy_to_position
from tradingagents.policy.io import atomic_write_text, unique_packet_path

DEFAULT_ALERT_THROTTLE_WINDOW = datetime.timedelta(hours=4)


@dataclass(frozen=True)
class HourlyDecisionContext:
    held_symbols: frozenset[str]
    live_unallocated: Decimal
    best_candidate: CandidateSignal | None
    worst_position: Mapping[str, Any] | None
    best_position: Mapping[str, Any] | None


def build_hourly_decision_context(
    *,
    live_positions: Sequence[Mapping[str, Any]],
    candidate_signals: Sequence[CandidateSignal] = (),
    current_live_exposure: Decimal,
    dynamic_live_cap: Decimal,
) -> HourlyDecisionContext:
    held_symbols = frozenset(
        str(position.get("symbol", "")).upper()
        for position in live_positions
        if position.get("symbol")
    )
    live_unallocated = max(Decimal("0"), dynamic_live_cap - current_live_exposure)
    ranked = [
        candidate
        for candidate in candidate_signals
        if candidate.symbol not in held_symbols
    ]

    worst = None
    best = None
    for position in live_positions:
        plpc = _as_decimal(position.get("unrealized_plpc"))
        if worst is None or plpc < _as_decimal(worst.get("unrealized_plpc")):
            worst = position
        if best is None or plpc > _as_decimal(best.get("unrealized_plpc")):
            best = position

    return HourlyDecisionContext(
        held_symbols=held_symbols,
        live_unallocated=live_unallocated,
        best_candidate=ranked[0] if ranked else None,
        worst_position=worst,
        best_position=best,
    )


def build_open_orders_review_decision(
    *,
    live_open_orders: Sequence[Mapping[str, Any]],
    live_exposure: Decimal,
) -> HourlySupervisorDecision | None:
    if not live_open_orders:
        return None
    return HourlySupervisorDecision(
        decision="review-open-orders",
        material=True,
        reason=f"{len(live_open_orders)} open live order(s) need inspection",
        live_exposure=live_exposure,
    )


def build_loss_review_decision(
    *,
    worst_position: Mapping[str, Any] | None,
    loss_review_plpc: Decimal,
    market_session: str,
    live_exposure: Decimal,
    generated_at: datetime.datetime,
    can_trade_session: Callable[[str], bool],
    positive_decimal_or_none: Callable[[Any], Decimal | None],
    live_sleeve: str,
) -> HourlySupervisorDecision | None:
    if (
        not worst_position
        or _as_decimal(worst_position.get("unrealized_plpc")) > loss_review_plpc
    ):
        return None

    # Mechanical stop-floor / time-stop lane: enrich the position with
    # pre-registered exit-policy evidence before the review, so rule-based
    # exits stop deadlocking in HOLD when no narrative evidence exists.
    worst_position = apply_exit_policy_to_position(
        worst_position, generated_at=generated_at
    )
    symbol = str(worst_position.get("symbol", "")).upper()
    loss_decision_id = f"loss-exit-{symbol}-{generated_at:%Y%m%d%H%M%S}"
    loss_exit_review = loss_exit_review_packet(
        worst_position,
        generated_at=generated_at,
        decision_id=loss_decision_id,
        side="sell",
        proposed_limit_price=(
            worst_position.get("exit_policy_limit_price")
            or worst_position.get("current_price")
        ),
    )
    loss_exit_reason = str(loss_exit_review.get("allowed_exit_reason") or "")
    tradeable_session = can_trade_session(market_session)
    if not tradeable_session:
        loss_exit_review = {
            **loss_exit_review,
            "allowed": False,
            "market_session": market_session,
            "blockers": [
                *loss_exit_review.get("blockers", []),
                "market session is not tradeable for a live loss exit",
            ],
        }
    if not loss_exit_review.get("allowed"):
        session_note = (
            ""
            if tradeable_session
            else " The market session is not tradeable for a live loss exit."
        )
        blockers = "; ".join(str(item) for item in loss_exit_review.get("blockers", []))
        return HourlySupervisorDecision(
            decision="loss-review",
            material=True,
            reason=(
                f"{symbol} crossed loss review, but no live sell was submitted "
                "because HOLD/loss-review is active. No loss sell was submitted and "
                "BOARD/manual review is required before a loss exit. "
                "Missing thesis-break/exit evidence keeps HOLD mode active. "
                f"Exact evidence gaps: {blockers or 'none'}. "
                "Paper exploration continues while review is open. "
                "New live buys are paused during this review. "
                f"{session_note} BOARD should review whether holding for recovery "
                "or freeing capital has the better expected value."
            ),
            live_exposure=live_exposure,
            evidence={"loss_exit_review": loss_exit_review},
            generated_at=generated_at,
        )
    current_price = positive_decimal_or_none(worst_position.get("current_price"))
    if current_price is None:
        loss_exit_review = {
            **loss_exit_review,
            "allowed": False,
            "blockers": [
                *loss_exit_review.get("blockers", []),
                "current price evidence is missing for approved loss exit order",
            ],
        }
        blockers = "; ".join(str(item) for item in loss_exit_review.get("blockers", []))
        return HourlySupervisorDecision(
            decision="loss-review",
            material=True,
            reason=(
                f"{symbol} crossed loss review, but no live sell was submitted "
                "because current price evidence is missing. "
                f"Exact evidence gaps: {blockers or 'current price evidence is missing'}. "
                "BOARD/manual review must refresh broker price data before any close order."
            ),
            live_exposure=live_exposure,
            evidence={"loss_exit_review": loss_exit_review},
            generated_at=generated_at,
        )

    notional = _as_decimal(worst_position.get("market_value") or worst_position.get("cost_basis"))
    qty_raw = worst_position.get("qty")
    # Price rule-based exits slightly below market so the limit-only sell
    # realistically fills instead of resting above the bid.
    policy_limit = positive_decimal_or_none(
        worst_position.get("exit_policy_limit_price")
    )
    action = HourlySupervisorAction(
        action="close",
        symbol=symbol,
        side="sell",
        qty=_as_decimal(qty_raw) if qty_raw else None,
        notional=notional,
        limit_price=policy_limit or current_price,
        reason=f"Exit approved loss: {symbol} crossed loss review; {loss_exit_reason}",
        execution_mode="tiny_live",
        sleeve=live_sleeve,
        decision_id=loss_decision_id,
        evidence={"loss_exit_review": loss_exit_review},
    )
    hold_cash = HourlySupervisorAction(
        action="hold_cash",
        symbol="CASH",
        side="hold",
        notional=Decimal("0"),
        limit_price=Decimal("0"),
        order_type="none",
        reason=(
            "Sell decision is independent; keep freed buying power in cash "
            "until a separate dip-buy setup qualifies."
        ),
        account="none",
        execution_mode="hold_cash",
        asset_class="cash",
    )
    return HourlySupervisorDecision(
        decision="close",
        material=True,
        reason=action.reason,
        live_exposure=live_exposure,
        actions=[action, hold_cash],
        evidence={"loss_exit_review": loss_exit_review},
        generated_at=generated_at,
    )


def build_profit_take_decision(
    *,
    best_position: Mapping[str, Any] | None,
    profit_review_plpc: Decimal,
    market_session: str,
    live_exposure: Decimal,
    generated_at: datetime.datetime,
    can_trade_session: Callable[[str], bool],
    positive_decimal_or_none: Callable[[Any], Decimal | None],
    live_sleeve: str,
) -> HourlySupervisorDecision | None:
    if (
        not best_position
        or _as_decimal(best_position.get("unrealized_plpc")) < profit_review_plpc
        or not can_trade_session(market_session)
    ):
        return None
    symbol = str(best_position.get("symbol", "")).upper()
    current_price = positive_decimal_or_none(best_position.get("current_price"))
    if current_price is None:
        return HourlySupervisorDecision(
            decision="profit-review",
            material=True,
            reason=(
                f"{symbol} reached profit review threshold, but no live sell was submitted "
                "because current price evidence is missing. Refresh broker price data before "
                "attempting to sell the spike."
            ),
            live_exposure=live_exposure,
            evidence={
                "profit_exit_review": {
                    "symbol": symbol,
                    "allowed": False,
                    "blockers": ["current price evidence is missing"],
                }
            },
            generated_at=generated_at,
        )
    notional = _as_decimal(best_position.get("market_value") or best_position.get("cost_basis"))
    qty_raw = best_position.get("qty")
    action = HourlySupervisorAction(
        action="close",
        symbol=symbol,
        side="sell",
        qty=_as_decimal(qty_raw) if qty_raw else None,
        notional=notional,
        limit_price=current_price,
        reason=f"Sell the spike: {symbol} reached profit review threshold",
        execution_mode="tiny_live",
        sleeve=live_sleeve,
    )
    return HourlySupervisorDecision(
        decision="profit-take",
        material=True,
        reason=action.reason,
        live_exposure=live_exposure,
        actions=[action],
        generated_at=generated_at,
    )


def build_buy_candidate_decision(
    *,
    best_candidate: CandidateSignal | None,
    new_buys_suspended_reason: str | None,
    live_buy_threshold: Decimal,
    paper_first_threshold: Decimal,
    live_unallocated: Decimal,
    market_session: str,
    live_exposure: Decimal,
    can_trade_session: Callable[[str], bool],
    live_sleeve: str,
) -> HourlySupervisorDecision | None:
    if best_candidate is None or not can_trade_session(market_session):
        return None

    if (
        new_buys_suspended_reason
        and best_candidate.score >= live_buy_threshold
        and best_candidate.time_sensitive
        and is_buy_entry_candidate(best_candidate)
    ):
        return HourlySupervisorDecision(
            decision="hold",
            material=True,
            reason=f"new live buys paused by BOARD review: {new_buys_suspended_reason}",
            live_exposure=live_exposure,
        )

    if best_candidate.score >= paper_first_threshold and not is_buy_entry_candidate(
        best_candidate
    ):
        return HourlySupervisorDecision(
            decision="hold",
            material=False,
            reason=(
                f"top candidate {best_candidate.symbol} already spiked; "
                "do not chase, wait for a controlled pullback"
            ),
            live_exposure=live_exposure,
        )

    extended_hours = market_session in {"pre_open", "after_close"}
    if (
        best_candidate.score >= live_buy_threshold
        and live_unallocated >= MIN_LIVE_BUY_NOTIONAL
        and best_candidate.time_sensitive
        and is_buy_entry_candidate(best_candidate)
    ):
        buy_notional = choose_autonomous_live_buy_notional(
            best_candidate,
            live_unallocated,
        )
        action = HourlySupervisorAction(
            action="buy",
            symbol=best_candidate.symbol,
            side="buy",
            notional=buy_notional,
            limit_price=aggressive_limit_price(
                best_candidate.current_price,
                side="buy",
                extended_hours=extended_hours,
            ),
            reason=f"Time-sensitive high-conviction candidate: {best_candidate.reason}",
            account="live",
            execution_mode="tiny_live",
            sleeve=live_sleeve,
            extended_hours=extended_hours,
        )
        return HourlySupervisorDecision(
            decision="buy",
            material=True,
            reason=action.reason,
            live_exposure=live_exposure,
            actions=[action],
        )

    if best_candidate.score >= paper_first_threshold:
        action = HourlySupervisorAction(
            action="buy",
            symbol=best_candidate.symbol,
            side="buy",
            notional=Decimal("100"),
            limit_price=aggressive_limit_price(best_candidate.current_price, side="buy"),
            reason=f"Paper-first candidate before live rotation: {best_candidate.reason}",
            account="paper",
            execution_mode="paper_first",
        )
        return HourlySupervisorDecision(
            decision="paper-first",
            material=True,
            reason=action.reason,
            live_exposure=live_exposure,
            actions=[action],
        )

    return None


def build_trailing_hold_decision(
    *,
    best_position: Mapping[str, Any] | None,
    profit_review_plpc: Decimal,
    live_exposure: Decimal,
) -> HourlySupervisorDecision:
    if best_position and _as_decimal(best_position.get("unrealized_plpc")) >= profit_review_plpc:
        symbol = str(best_position.get("symbol", "")).upper()
        return HourlySupervisorDecision(
            decision="profit-review",
            material=True,
            reason=f"{symbol} reached profit review threshold",
            live_exposure=live_exposure,
        )

    return HourlySupervisorDecision(
        decision="hold",
        material=False,
        reason="no risk, profit, order, or thesis-change trigger detected",
        live_exposure=live_exposure,
    )


def build_hourly_decision(
    *,
    live_positions: Sequence[Mapping[str, Any]],
    live_open_orders: Sequence[Mapping[str, Any]],
    config: HourlySupervisorConfig,
    candidate_signals: Sequence[CandidateSignal] = (),
    market_session: str = "regular",
    dynamic_live_cap: Decimal,
    new_buys_suspended_reason: str | None = None,
    can_trade_session: Callable[[str], bool],
    positive_decimal_or_none: Callable[[Any], Decimal | None],
    live_sleeve: str,
    generated_at: datetime.datetime | None = None,
) -> HourlySupervisorDecision:
    generated_at = generated_at or datetime.datetime.now(tz=datetime.timezone.utc)
    exposure = _live_exposure_from_positions(live_positions)
    open_order_review = build_open_orders_review_decision(
        live_open_orders=live_open_orders,
        live_exposure=exposure,
    )
    if open_order_review is not None:
        return open_order_review

    context = build_hourly_decision_context(
        live_positions=live_positions,
        candidate_signals=candidate_signals,
        current_live_exposure=exposure,
        dynamic_live_cap=dynamic_live_cap,
    )
    loss_review = build_loss_review_decision(
        worst_position=context.worst_position,
        loss_review_plpc=config.loss_review_plpc,
        market_session=market_session,
        live_exposure=exposure,
        generated_at=generated_at,
        can_trade_session=can_trade_session,
        positive_decimal_or_none=positive_decimal_or_none,
        live_sleeve=live_sleeve,
    )
    if loss_review is not None:
        return loss_review

    profit_take = build_profit_take_decision(
        best_position=context.best_position,
        profit_review_plpc=config.profit_review_plpc,
        market_session=market_session,
        live_exposure=exposure,
        generated_at=generated_at,
        can_trade_session=can_trade_session,
        positive_decimal_or_none=positive_decimal_or_none,
        live_sleeve=live_sleeve,
    )
    if profit_take is not None:
        return profit_take

    buy_candidate = build_buy_candidate_decision(
        best_candidate=context.best_candidate,
        new_buys_suspended_reason=new_buys_suspended_reason,
        live_buy_threshold=config.live_buy_threshold,
        paper_first_threshold=config.paper_first_threshold,
        live_unallocated=context.live_unallocated,
        market_session=market_session,
        live_exposure=exposure,
        can_trade_session=can_trade_session,
        live_sleeve=live_sleeve,
    )
    if buy_candidate is not None:
        return buy_candidate

    return build_trailing_hold_decision(
        best_position=context.best_position,
        profit_review_plpc=config.profit_review_plpc,
        live_exposure=exposure,
    )


def find_latest_hourly_packet(output_dir: str | Path) -> Path | None:
    path = Path(output_dir)
    if not path.exists():
        return None
    packets = [
        packet
        for packet in path.glob("hourly-supervisor-*.json")
        if _is_raw_json_packet_path(packet)
    ]
    return max(packets, key=lambda packet: packet.stat().st_mtime_ns) if packets else None


def _is_raw_json_packet_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    name = path.name.lower()
    return not (name.endswith(".compact.json") or name == "latest-compact.json")


def build_hourly_evidence(
    *,
    live_account: Mapping[str, Any],
    paper_account: Mapping[str, Any],
    live_positions: Sequence[Mapping[str, Any]],
    live_open_orders: Sequence[Mapping[str, Any]],
    previous_packet: Path | None = None,
    overnight_validation: Mapping[str, Any] | None = None,
    premarket_brief_validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_items = []
    if previous_packet:
        previous_summary = _previous_packet_summary(previous_packet)
        baseline_items.append(
            {
                "category": "previous_hourly_packet",
                "summary": previous_summary,
                "source": str(previous_packet),
            }
        )
    else:
        baseline_items.append(
            {
                "category": "initial_hourly_baseline",
                "summary": (
                    "No earlier hourly supervisor packet was found; this run "
                    "starts the local baseline."
                ),
                "source": "results/hourly_supervisor",
            }
        )

    symbols = [
        str(position.get("symbol", "")).upper()
        for position in live_positions
        if position.get("symbol")
    ]
    delta_items = [
        {
            "category": "live_account",
            "summary": (
                f"status={live_account.get('status')}; "
                f"buying_power={live_account.get('buying_power')}; "
                f"equity={live_account.get('equity')}"
            ),
            "source": "alpaca_live:/v2/account",
        },
        {
            "category": "paper_account",
            "summary": (
                f"status={paper_account.get('status')}; "
                f"buying_power={paper_account.get('buying_power')}; "
                f"equity={paper_account.get('equity')}"
            ),
            "source": "alpaca_paper:/v2/account",
        },
        {
            "category": "live_positions",
            "summary": (
                f"{len(live_positions)} live position(s); "
                f"symbols={', '.join(symbols) if symbols else 'none'}"
            ),
            "source": "alpaca_live:/v2/positions",
        },
        {
            "category": "live_open_orders",
            "summary": f"{len(live_open_orders)} open live order(s)",
            "source": "alpaca_live:/v2/orders?status=open",
        },
        {
            "category": "methodology",
            "summary": (
                "Account, position, order, live gate, risk-threshold, and "
                "notification checks completed for this tick."
            ),
            "source": "tradingagents alpaca supervise-hourly",
        },
        {
            "category": "market_structure",
            "summary": (
                "FINRA intraday-margin reform is approved but its effective date or "
                "account-specific broker adoption is not established here. Preserve "
                "current account restrictions until fresh broker evidence proves the "
                "new regime applies; always keep buying-power and margin validation."
            ),
            "source": "SEC 34-105226 / FINRA SR-FINRA-2025-017 / Alpaca transition guide",
        },
    ]
    evidence = {
        "baseline": baseline_items,
        "delta": delta_items,
    }
    if overnight_validation:
        evidence["overnight_plan"] = dict(overnight_validation)
    if premarket_brief_validation:
        evidence["premarket_brief"] = dict(premarket_brief_validation)
    return evidence


def serialize_hourly_decision(
    decision: Any,
    *,
    classify_alert: Callable[[Any], Any],
    alert_fingerprint: Callable[[Any, Any], str],
    should_throttle_alert: Callable[..., bool],
    render_alert_email: Callable[[Any], Mapping[str, Any]],
    client_order_id: Callable[..., str],
    is_order_action: Callable[[Any], bool],
    recent_packets: Sequence[Mapping[str, Any]] = (),
    alert_throttle_window: datetime.timedelta = DEFAULT_ALERT_THROTTLE_WINDOW,
) -> dict[str, Any]:
    alert = classify_alert(decision)
    fingerprint = alert_fingerprint(decision, alert)
    email_suppressed = should_throttle_alert(
        decision,
        recent_packets=recent_packets,
        throttle_window=alert_throttle_window,
    )
    notify = alert.notify and not email_suppressed
    issue_rows = [supervisor_issue_dict(issue) for issue in decision.issues]
    payload = {
        "generated_at": decision.generated_at.isoformat(timespec="seconds"),
        "decision": decision.decision,
        "material": decision.material,
        "reason": decision.reason,
        "human_summary": human_supervisor_summary(decision, issue_rows),
        "live_exposure": _money(decision.live_exposure),
        "actions": [
            {
                "action": action.action,
                "symbol": action.symbol,
                "side": action.normalized_side(),
                "notional": _money(action.notional),
                "limit_price": _price(action.limit_price),
                "reason": action.reason,
                "account": action.account,
                "execution_mode": action.execution_mode,
                "sleeve": action.sleeve,
                "extended_hours": action.extended_hours,
                "decision_id": action.decision_id,
                "evidence": action.evidence,
                "idempotency_key": (
                    client_order_id(action, generated_at=decision.generated_at)
                    if (
                        action.account.lower() == "live"
                        and action.execution_mode.lower() == "tiny_live"
                        and is_order_action(action)
                    )
                    else None
                ),
            }
            for action in decision.actions
        ],
        "issues": issue_rows,
        "issue_category_counts": supervisor_issue_category_counts(issue_rows),
        "submitted": decision.submitted,
        "reconciled_orders": decision.reconciled_orders,
        "alert": alert.as_dict(
            notify=notify,
            base_notify=alert.notify,
            fingerprint=fingerprint,
            email_suppressed=email_suppressed,
            suppression_reason=(
                "same-cause alert already emitted inside throttle window"
                if email_suppressed
                else None
            ),
        ),
        "evidence": decision.evidence,
        "portfolio": decision.portfolio,
    }
    if notify:
        payload["alert_email"] = dict(render_alert_email(decision))
    return payload


def write_hourly_decision_packet(
    decision: Any,
    *,
    serialize_decision: Callable[..., Mapping[str, Any]],
    output_dir: str | Path = "results/hourly_supervisor",
    recent_packets: Sequence[Mapping[str, Any]] = (),
    alert_throttle_window: datetime.timedelta = DEFAULT_ALERT_THROTTLE_WINDOW,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = f"hourly-supervisor-{decision.generated_at:%Y%m%d-%H%M%S-%f}"
    packet_path = unique_packet_path(output_path, stem)
    packet = dict(
        serialize_decision(
            decision,
            recent_packets=recent_packets,
            alert_throttle_window=alert_throttle_window,
        )
    )
    packet_text = json.dumps(packet, indent=2)
    compact = compact_hourly_supervisor_payload(packet, packet_path)
    compact_text = json.dumps(compact, indent=2)
    atomic_write_text(packet_path, packet_text)
    atomic_write_text(packet_path.with_suffix(".compact.json"), compact_text)
    atomic_write_text(output_path / "latest.json", packet_text)
    atomic_write_text(output_path / "latest-compact.json", compact_text)
    return packet_path


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _live_exposure_from_positions(positions: Sequence[Mapping[str, Any]]) -> Decimal:
    return sum((_as_decimal(position.get("market_value")) for position in positions), Decimal("0"))


def _money(value: Decimal | int | float | str) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _price(value: Decimal | int | float | str) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _previous_packet_summary(packet_path: Path) -> str:
    try:
        data = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"Previous packet exists at {packet_path.name}, but it could not be parsed."
    decision = data.get("decision", "unknown")
    generated_at = data.get("generated_at", "unknown time")
    live_exposure = data.get("live_exposure", "unknown")
    return (
        f"Previous hourly supervisor decision={decision}; "
        f"generated_at={generated_at}; live_exposure={live_exposure}."
    )


def compact_hourly_supervisor_payload(
    packet: Mapping[str, Any],
    packet_path: Path | str,
) -> dict[str, Any]:
    portfolio = packet.get("portfolio") or {}
    live = portfolio.get("live") if isinstance(portfolio, dict) else {}
    paper = portfolio.get("paper") if isinstance(portfolio, dict) else {}
    ranked_candidates = portfolio.get("ranked_candidates") if isinstance(portfolio, dict) else []
    evidence = packet.get("evidence") or {}
    live_budget = evidence.get("live_budget") if isinstance(evidence, dict) else {}
    risk_posture = evidence.get("risk_posture") if isinstance(evidence, dict) else {}
    overnight_plan = evidence.get("overnight_plan") if isinstance(evidence, dict) else {}
    premarket_brief = evidence.get("premarket_brief") if isinstance(evidence, dict) else {}
    paper_tournament = evidence.get("paper_tournament") if isinstance(evidence, dict) else {}
    execution_board = evidence.get("execution_board_review") if isinstance(evidence, dict) else {}
    actions = packet.get("actions") or []
    issues = packet.get("issues") or []
    submitted = packet.get("submitted") or []
    alert = packet.get("alert") or {}

    action_counts: dict[str, int] = {}
    account_counts: dict[str, int] = {}
    order_action_count = 0
    top_action: Mapping[str, Any] = {}
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_name = str(action.get("action", "unknown")).lower()
            account = str(action.get("account", "unknown")).lower()
            side = str(action.get("side", "")).lower()
            action_counts[action_name] = action_counts.get(action_name, 0) + 1
            account_counts[account] = account_counts.get(account, 0) + 1
            if side in {"buy", "sell"}:
                order_action_count += 1
            if not top_action:
                top_action = action
    top_candidate = (
        ranked_candidates[0]
        if (
            isinstance(ranked_candidates, list)
            and ranked_candidates
            and isinstance(ranked_candidates[0], dict)
        )
        else {}
    )

    return {
        "schema": "compact_hourly_supervisor_v1",
        "raw_packet_path": str(packet_path),
        "generated_at": packet.get("generated_at"),
        "decision": packet.get("decision"),
        "material": packet.get("material"),
        "reason": packet.get("reason"),
        "market_session": portfolio.get("market_session") if isinstance(portfolio, dict) else None,
        "submitted_count": len(submitted) if isinstance(submitted, list) else 0,
        "issue_count": len(issues) if isinstance(issues, list) else 0,
        "can_submit_orders": False,
        "execution_authority": "none",
        "action_summary": {
            "action_count": len(actions) if isinstance(actions, list) else 0,
            "order_action_count": order_action_count,
            "action_counts": action_counts,
            "account_counts": account_counts,
            "top_action": {
                "action": top_action.get("action"),
                "symbol": top_action.get("symbol"),
                "side": top_action.get("side"),
                "account": top_action.get("account"),
                "execution_mode": top_action.get("execution_mode"),
                "sleeve": top_action.get("sleeve"),
            }
            if top_action
            else {},
        },
        "portfolio_summary": {
            "live": {
                "status": live.get("status") if isinstance(live, dict) else None,
                "equity": live.get("equity") if isinstance(live, dict) else None,
                "buying_power": live.get("buying_power") if isinstance(live, dict) else None,
                "cash": live.get("cash") if isinstance(live, dict) else None,
                "exposure": live.get("exposure") if isinstance(live, dict) else None,
                "dynamic_cap": live.get("dynamic_cap") if isinstance(live, dict) else None,
                "unrealized_pl": live.get("unrealized_pl") if isinstance(live, dict) else None,
                "position_count": len(live.get("positions") or []) if isinstance(live, dict) else 0,
                "open_order_count": len(live.get("open_orders") or []) if isinstance(live, dict) else 0,
            },
            "paper": {
                "status": paper.get("status") if isinstance(paper, dict) else None,
                "equity": paper.get("equity") if isinstance(paper, dict) else None,
                "buying_power": paper.get("buying_power") if isinstance(paper, dict) else None,
                "unrealized_pl": paper.get("unrealized_pl") if isinstance(paper, dict) else None,
                "position_count": len(paper.get("positions") or []) if isinstance(paper, dict) else 0,
                "open_order_count": len(paper.get("open_orders") or []) if isinstance(paper, dict) else 0,
            },
            "ranked_candidate_count": len(ranked_candidates) if isinstance(ranked_candidates, list) else 0,
        },
        "top_candidate": {
            "symbol": top_candidate.get("symbol"),
            "score": top_candidate.get("score"),
            "day_change_pct": top_candidate.get("day_change_pct"),
            "time_sensitive": top_candidate.get("time_sensitive"),
            "source": top_candidate.get("source"),
        }
        if top_candidate
        else {},
        "context_summary": {
            "overnight_plan": {
                "status": overnight_plan.get("status") if isinstance(overnight_plan, dict) else None,
                "top_symbol": (
                    overnight_plan.get("overnight_top_symbol")
                    if isinstance(overnight_plan, dict)
                    else None
                ),
                "packet_path": overnight_plan.get("json_path") if isinstance(overnight_plan, dict) else None,
            },
            "premarket_brief": {
                "status": premarket_brief.get("status") if isinstance(premarket_brief, dict) else None,
                "top_symbol": (
                    premarket_brief.get("premarket_top_symbol")
                    if isinstance(premarket_brief, dict)
                    else None
                ),
                "packet_path": (
                    premarket_brief.get("json_path") if isinstance(premarket_brief, dict) else None
                ),
            },
            "paper_tournament": {
                "status": paper_tournament.get("status") if isinstance(paper_tournament, dict) else None,
                "candidate_strategy": (
                    paper_tournament.get("strategy_id") if isinstance(paper_tournament, dict) else None
                ),
            },
            "execution_board": {
                "recommendation": (
                    execution_board.get("recommendation") if isinstance(execution_board, dict) else None
                ),
                "new_buys_suspended": (
                    execution_board.get("new_buys_suspended")
                    if isinstance(execution_board, dict)
                    else None
                ),
                "packet_path": (
                    execution_board.get("json_path") if isinstance(execution_board, dict) else None
                ),
            },
        },
        "live_budget": {
            "mode": live_budget.get("mode") if isinstance(live_budget, dict) else None,
            "repo_dollar_cap_active": (
                live_budget.get("repo_dollar_cap_active") if isinstance(live_budget, dict) else None
            ),
            "plain_english": live_budget.get("plain_english") if isinstance(live_budget, dict) else None,
        },
        "risk_posture": {
            "name": risk_posture.get("name") if isinstance(risk_posture, dict) else None,
            "paper_first_threshold": (
                risk_posture.get("paper_first_threshold") if isinstance(risk_posture, dict) else None
            ),
            "live_gate_relaxation_allowed": (
                risk_posture.get("live_gate_relaxation_allowed")
                if isinstance(risk_posture, dict)
                else None
            ),
        },
        "alert_summary": {
            "severity": alert.get("severity") if isinstance(alert, dict) else None,
            "notify": alert.get("notify") if isinstance(alert, dict) else None,
            "email_suppressed": alert.get("email_suppressed") if isinstance(alert, dict) else None,
        },
        "raw_field_groups": [
            "actions",
            "issues",
            "submitted",
            "reconciled_orders",
            "alert",
            "alert_email",
            "evidence",
            "portfolio",
            "account",
        ],
    }
