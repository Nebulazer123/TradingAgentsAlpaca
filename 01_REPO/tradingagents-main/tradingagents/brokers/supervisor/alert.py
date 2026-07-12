"""Hourly supervisor alert classification and email rendering.

This module is reporting-only. It does not fetch broker state, validate orders,
or submit anything; callers pass in the already-built supervisor decision.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from tradingagents.brokers.supervisor.formatting import email_reason_text
from tradingagents.brokers.supervisor.session import UTC

DEFAULT_ALERT_THROTTLE_WINDOW = datetime.timedelta(hours=4)


@dataclass(frozen=True)
class SupervisorAlert:
    severity: str
    notify: bool
    reason: str
    problem: str = "none"
    approval_prompt: str = (
        "No approval needed. The bot will continue inside the configured envelope."
    )

    def as_dict(
        self,
        *,
        notify: bool | None = None,
        base_notify: bool | None = None,
        fingerprint: str | None = None,
        email_suppressed: bool = False,
        suppression_reason: str | None = None,
    ) -> dict[str, Any]:
        effective_notify = self.notify if notify is None else notify
        original_notify = self.notify if base_notify is None else base_notify
        payload: dict[str, Any] = {
            "severity": self.severity,
            "notify": effective_notify,
            "base_notify": original_notify,
            "reason": self.reason,
            "problem": self.problem,
            "approval_prompt": self.approval_prompt,
            "email_suppressed": email_suppressed,
        }
        if fingerprint:
            payload["fingerprint"] = fingerprint
        if suppression_reason:
            payload["suppression_reason"] = suppression_reason
        return payload


def supervisor_alert_fingerprint(
    decision: Any,
    alert: SupervisorAlert | None = None,
) -> str:
    alert = alert or classify_supervisor_alert(decision)
    parts = [
        alert.severity,
        decision.decision,
        alert.problem,
        decision.reason,
    ]
    for issue in sorted(
        decision.issues,
        key=lambda issue: (
            getattr(issue, "ticket_id", ""),
            getattr(issue, "reason", ""),
        ),
    ):
        parts.append(getattr(issue, "ticket_id", "issue"))
        parts.append(getattr(issue, "reason", ""))
    for action in sorted(
        decision.actions,
        key=lambda action: (
            action.account,
            action.symbol,
            action.action,
            action.execution_mode,
        ),
    ):
        parts.extend(
            [
                action.account,
                action.symbol,
                action.action,
                action.execution_mode,
                action.sleeve,
            ]
        )
    normalized = [_alert_fingerprint_part(part) for part in parts]
    return "|".join(part for part in normalized if part)


def should_throttle_supervisor_alert(
    decision: Any,
    *,
    recent_packets: Sequence[Mapping[str, Any]] = (),
    throttle_window: datetime.timedelta = DEFAULT_ALERT_THROTTLE_WINDOW,
) -> bool:
    alert = classify_supervisor_alert(decision)
    if not alert.notify:
        return False
    fingerprint = supervisor_alert_fingerprint(decision, alert)
    generated_at = decision.generated_at.astimezone(UTC)
    for packet in reversed(list(recent_packets)):
        if not isinstance(packet, Mapping):
            continue
        packet_alert = packet.get("alert")
        if not isinstance(packet_alert, Mapping):
            continue
        previous_notify = bool(
            packet_alert.get("base_notify", packet_alert.get("notify"))
        )
        if not previous_notify:
            continue
        previous_generated_at = _parse_packet_generated_at(packet.get("generated_at"))
        if previous_generated_at is None:
            continue
        age = generated_at - previous_generated_at
        if age < datetime.timedelta(0) or age > throttle_window:
            continue
        if _packet_alert_fingerprint(packet) == fingerprint:
            return True
    return False


def classify_supervisor_alert(decision: Any) -> SupervisorAlert:
    issue_text = " ".join(
        f"{getattr(issue, 'ticket_id', '')} {getattr(issue, 'reason', '')}"
        for issue in decision.issues
    ).lower()
    if (
        decision.decision == "blocked"
        or "live-submit-guard" in issue_text
        or "risk envelope" in issue_text
        or "broker rejected" in issue_text
        or "submit failed" in issue_text
        or "reconciliation" in issue_text
        or "dead-man" in issue_text
        or "drawdown" in issue_text
    ):
        return SupervisorAlert(
            severity="CRITICAL",
            notify=True,
            reason=decision.reason,
            problem="A guardrail, broker, or live-submit control blocked the run.",
            approval_prompt=(
                "Question: approve Codex to repair or refresh the missing ops setup if it can be done safely? "
                "Until then, the bot stays blocked and will not spend live money."
            ),
        )
    if decision.decision == "loss-review":
        context = _loss_review_alert_context(decision.evidence)
        symbol = context["symbol"]
        missing_clause = context["missing_clause"]
        return SupervisorAlert(
            severity="NOTABLE",
            notify=True,
            reason=decision.reason,
            problem=(
                f"{symbol} hit loss review. No live loss sell was submitted. "
                f"{missing_clause}. BOARD/Codex must review the packet before any loss exit."
            ),
            approval_prompt=context["approval_prompt"],
        )
    if decision.submitted or decision.decision in {
        "buy",
        "close",
        "paper-first",
        "profit-take",
        "reduce",
        "rotate",
        "review-open-orders",
    }:
        return SupervisorAlert(
            severity="NOTABLE",
            notify=True,
            reason=decision.reason,
            problem="The supervisor found material activity worth recording.",
        )
    return SupervisorAlert(
        severity="ROUTINE",
        notify=False,
        reason=decision.reason,
    )


def supervisor_issue_category(ticket_id: str = "", reason: str = "") -> str:
    text = f"{ticket_id} {reason}".lower()
    if any(token in text for token in ("stale", "freshness", "outdated", "old source")):
        return "stale"
    if any(
        token in text
        for token in (
            "risk envelope",
            "live-submit",
            "live gate",
            "promotion",
            "dead-man",
            "pdt",
            "cap",
            "exposure limit",
            "drawdown",
            "halt",
            "freeze",
        )
    ):
        return "policy"
    if any(token in text for token in ("cash", "buying power", "insufficient funds")):
        return "cash"
    if any(
        token in text
        for token in ("broker", "alpaca", "rejected", "submit failed", "reconciliation")
    ):
        return "broker"
    if any(
        token in text
        for token in (
            "missing",
            "unavailable",
            "parse",
            "malformed",
            "no data",
            "provider",
            "source",
        )
    ):
        return "data"
    if any(
        token in text
        for token in ("setup", "thesis", "strategy", "green-spike", "falling knife")
    ):
        return "strategy"
    if any(token in text for token in ("unsupported", "duplicate", "not actionable", "no actionable")):
        return "actionability"
    return "ops"


def supervisor_issue_dict(issue: Any) -> dict[str, str]:
    ticket_id = str(getattr(issue, "ticket_id", "issue"))
    reason = str(getattr(issue, "reason", ""))
    return {
        "ticket_id": ticket_id,
        "reason": reason,
        "category": supervisor_issue_category(ticket_id, reason),
    }


def supervisor_issue_category_counts(issues: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        category = str(issue.get("category") or "ops")
        counts[category] = counts.get(category, 0) + 1
    return counts


def human_supervisor_summary(
    decision: Any,
    issue_rows: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    rows = list(issue_rows) if issue_rows is not None else [supervisor_issue_dict(issue) for issue in decision.issues]
    if rows:
        primary = rows[0]
        category = str(primary.get("category") or "ops")
        reason = str(primary.get("reason") or "needs review")
        return f"Stopped before trading because a {category} blocker needs review: {reason}."
    if decision.submitted:
        return f"Submitted {len(decision.submitted)} order(s) after checks: {decision.reason}."
    if decision.actions:
        return f"Prepared {len(decision.actions)} action(s) but did not submit them: {decision.reason}."
    return f"No order action needed: {decision.reason}."


def render_supervisor_alert_email(decision: Any) -> dict[str, str]:
    alert = classify_supervisor_alert(decision)
    issue_rows = [supervisor_issue_dict(issue) for issue in decision.issues]
    issue_reason = "none"
    if issue_rows:
        primary_issue = issue_rows[0]
        issue_reason = (
            f"{primary_issue['reason']} "
            f"({primary_issue['category']} | {primary_issue['ticket_id']})"
        )
    elif (
        alert.problem
        and alert.problem != "The supervisor found material activity worth recording."
    ):
        issue_reason = alert.problem
    live = decision.portfolio.get("live", {}) if isinstance(decision.portfolio, Mapping) else {}
    paper = decision.portfolio.get("paper", {}) if isinstance(decision.portfolio, Mapping) else {}

    submitted_live = Decimal("0")
    submitted_paper = Decimal("0")
    for submitted in decision.submitted:
        if not isinstance(submitted, Mapping):
            continue
        notional = _as_decimal(submitted.get("notional"))
        if _submitted_account(decision, submitted) == "paper":
            submitted_paper += notional
        else:
            submitted_live += notional

    action_lines: list[str] = []
    for action in decision.actions:
        if action.action.lower() == "hold_cash":
            action_lines.append("- Plan: keep the money in cash.")
            continue
        side = action.normalized_side()
        verb = "Buy" if side == "buy" else "Sell"
        action_lines.append(
            f"- Plan: {verb} {action.symbol} in {action.account} for about ${_display_money(action.notional)}."
        )
    if not action_lines:
        action_lines.append("- Plan: no order was planned.")
    if len(action_lines) > 3:
        action_lines = [
            *action_lines[:3],
            f"- {len(action_lines) - 3} more action(s) in the packet.",
        ]
    if alert.severity == "CRITICAL":
        plain = (
            "The bot stopped before live money moved. Trading stays blocked until "
            "the safety issue is cleared."
        )
    elif decision.submitted:
        plain = "The bot submitted an order and saved a proof record."
    else:
        plain = "The bot found something important and saved a proof record."
    need = alert.approval_prompt or "No action needed from you."
    safety_reason = email_reason_text(decision.reason)
    if decision.decision == "loss-review":
        symbol = "a live position"
        market_session = None
        if isinstance(decision.evidence, Mapping):
            review = decision.evidence.get("loss_exit_review")
            if isinstance(review, Mapping):
                raw_symbol = str(review.get("symbol") or "").strip().upper()
                if raw_symbol:
                    symbol = raw_symbol
                market_session = review.get("market_session")
        safety_reason = f"{symbol} hit loss review. The bot held and did not sell at a loss."
        if market_session and str(market_session).lower() != "regular":
            safety_reason += f" Market was {str(market_session).lower()}."
    submitted_count = len(decision.submitted)
    submitted_line = (
        f"- Submitted orders: {submitted_count}."
        if submitted_count
        else "- Submitted orders: none."
    )
    if alert.severity == "CRITICAL" or decision.issues:
        next_step = (
            "Codex next step: self-heal safe setup problems, then rerun checks. "
            "If it cannot do that safely, trading stays blocked."
        )
    elif decision.submitted:
        next_step = (
            "Next step: reconcile the submitted order, then re-check positions "
            "before any new action."
        )
    elif decision.decision == "loss-review":
        next_step = (
            "Next step: HOLD/loss-review is default. New live buys are paused while paper "
            "exploration continues. BOARD/manual review is required before any loss exit can be "
            "submitted."
        )
    else:
        next_step = (
            "Next step: No repair needed. The next supervisor run will re-check "
            "prices, positions, and guardrails before doing anything else."
        )
    body_lines = [
        "Plain English",
        f"- {plain}",
        "",
        "What happened",
        f"- Last decision: {decision.decision}.",
        f"- Safety check said: {safety_reason}",
        *action_lines,
        submitted_line,
        "",
        f"Problem: {issue_reason}",
        "",
        "Money today",
        (
            f"- This alert submitted live ${_display_money(submitted_live)} "
            f"and paper ${_display_money(submitted_paper)}."
        ),
        "",
        "Live account",
        _account_snapshot("Live", live),
        "",
        "Paper account",
        _account_snapshot("Paper", paper),
        "",
        "Need from you",
        f"- {need}",
        "",
        next_step,
    ]
    return {
        "subject": f"TradingAgents {alert.severity}: {decision.decision}",
        "body": "\n".join(body_lines),
    }


def _loss_review_alert_context(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    symbol = "A live position"
    missing_count = 0
    refreshed_missing_count: int | None = None
    refreshed_resolved_count: int | None = None
    refreshed_review_allowed: Any = None
    if isinstance(evidence, Mapping):
        review = evidence.get("loss_exit_review")
        if isinstance(review, Mapping):
            raw_symbol = str(review.get("symbol") or "").strip().upper()
            if raw_symbol:
                symbol = raw_symbol
            missing_count = len(
                [item for item in review.get("blockers", []) if str(item).strip()]
            )
        board = evidence.get("execution_board_review")
        if isinstance(board, Mapping):
            loss_evidence = board.get("loss_review_evidence")
            if isinstance(loss_evidence, Mapping):
                raw_symbol = str(loss_evidence.get("symbol") or "").strip().upper()
                if raw_symbol:
                    symbol = raw_symbol
                try:
                    refreshed_missing_count = int(
                        loss_evidence.get("remaining_blocker_count")
                    )
                except (TypeError, ValueError):
                    refreshed_missing_count = None
                try:
                    refreshed_resolved_count = int(
                        loss_evidence.get("resolved_blocker_count")
                    )
                except (TypeError, ValueError):
                    refreshed_resolved_count = None
                refreshed_review_allowed = loss_evidence.get("review_allowed")
    if refreshed_missing_count is not None:
        missing_clause = (
            f"{refreshed_missing_count} evidence item(s) still open after refresh"
        )
        if refreshed_resolved_count:
            missing_clause += f"; {refreshed_resolved_count} resolved"
        approval_prompt = (
            "No action needed right now. HOLD remains default until BOARD/Codex can prove "
            "the thesis is broken and selling is better than holding."
        )
        if refreshed_review_allowed is True:
            approval_prompt = (
                "No action needed right now. BOARD/Codex has refreshed evidence; live loss "
                "exit still requires the normal market/session and submit gates."
            )
    else:
        missing_clause = (
            f"{missing_count} evidence item(s) still missing"
            if missing_count
            else "loss-exit evidence still needs review"
        )
        approval_prompt = (
            "No action needed right now. BOARD/Codex should refresh thesis, market, "
            "news, and earnings evidence before any live loss exit."
        )
    return {
        "symbol": symbol,
        "missing_clause": missing_clause,
        "approval_prompt": approval_prompt,
    }


def _alert_fingerprint_part(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"ta-[a-z0-9-]+", "ta-order", text)
    text = re.sub(r"\d{8}-\d{6}(?:-\d+)?", "<timestamp>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _packet_alert_fingerprint(packet: Mapping[str, Any]) -> str:
    alert = packet.get("alert") if isinstance(packet.get("alert"), Mapping) else {}
    existing = alert.get("fingerprint") if isinstance(alert, Mapping) else None
    if existing:
        return str(existing)
    parts = [
        alert.get("severity", "") if isinstance(alert, Mapping) else "",
        packet.get("decision", ""),
        alert.get("problem", "") if isinstance(alert, Mapping) else "",
        packet.get("reason", ""),
    ]
    for issue in packet.get("issues") or []:
        if not isinstance(issue, Mapping):
            continue
        parts.append(issue.get("ticket_id", "issue"))
        parts.append(issue.get("reason", ""))
    for action in packet.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        parts.extend(
            [
                action.get("account", ""),
                action.get("symbol", ""),
                action.get("action", ""),
                action.get("execution_mode", ""),
                action.get("sleeve", ""),
            ]
        )
    normalized = [_alert_fingerprint_part(part) for part in parts]
    return "|".join(part for part in normalized if part)


def _parse_packet_generated_at(value: object) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _account_snapshot(label: str, account: Mapping[str, Any]) -> str:
    positions = account.get("positions") if isinstance(account, Mapping) else []
    open_orders = account.get("open_orders") if isinstance(account, Mapping) else []
    symbols = [
        str(position.get("symbol", "")).upper()
        for position in positions or []
        if isinstance(position, Mapping) and position.get("symbol")
    ]
    holding_text = ", ".join(symbols[:4]) if symbols else "none"
    if len(symbols) > 4:
        holding_text += f", +{len(symbols) - 4} more"
    exposure = account.get("exposure") if label == "Live" else account.get("equity")
    exposure_label = "exposure" if label == "Live" else "equity"
    return (
        f"- {label}: holdings {holding_text}; open orders {len(open_orders or [])}; "
        f"{exposure_label} ${_display_money(exposure)}."
    )


def _submitted_account(decision: Any, submitted: Mapping[str, Any]) -> str:
    explicit_account = submitted.get("account") or submitted.get("execution_account")
    if explicit_account:
        return str(explicit_account).lower()
    client_order_id = str(submitted.get("client_order_id", "")).lower()
    if "paper" in client_order_id:
        return "paper"
    symbol = str(submitted.get("symbol", "")).upper()
    side = str(submitted.get("side", "")).lower()
    for action in decision.actions:
        if action.symbol.upper() == symbol and action.normalized_side() == side:
            return action.account.lower()
    return "live"


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _display_money(value: Decimal | int | float | str | None) -> str:
    amount = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{amount:,.2f}"
