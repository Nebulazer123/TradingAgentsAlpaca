"""C3: owner panic-flatten kill switch.

A doomsday "stand down" that does everything it can do *safely*:
  1. Cancel open live orders (best-effort — stops resting buys/sells).
  2. Sell every live position it can push through the FULL unified go-live guard
     (winners and flats need no loss review; losers must still carry a valid
     loss-exit review — the guard's anti-panic-sale protection is NOT bypassed).
  3. Freeze live trading *after* the sells (freeze blocks sells too).
  4. Queue a plain-language owner email.

Dry-run is the default. A real submit requires ``confirm == "FLATTEN"`` AND
``TA_LIVE_SUBMIT=1``. This module reuses the exact guard, payload and lock code the
hourly supervisor uses, so a real submission travels the same, tested path. It never
weakens a gate: positions the guard blocks are reported, not force-sold.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from tradingagents.brokers.alpaca_supervisor import supervisor_live_client_order_id
from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.brokers.supervisor.orders import build_supervisor_order_payload
from tradingagents.brokers.supervisor.types import HourlySupervisorAction
from tradingagents.execution.lock import release_execution_lock
from tradingagents.execution.tiny_live import acquire_tiny_live_operational_guard
from tradingagents.notifications.outbox import write_outbox_message
from tradingagents.policy.exit_policy import load_exit_policy
from tradingagents.policy.live_control import write_live_control_state
from tradingagents.policy.live_gate import _read_promotion_state, evaluate_go_live_guard

UTC = datetime.timezone.utc


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        if value in (None, ""):
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@dataclass(frozen=True)
class FlattenLine:
    symbol: str
    qty: str
    limit_price: str
    at_loss: bool
    submittable: bool
    block_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PanicFlattenPlan:
    generated_at: datetime.datetime
    live_sleeve: str | None
    lines: list[FlattenLine]
    submittable_actions: list[HourlySupervisorAction]
    open_orders_to_cancel: list[str]

    @property
    def submittable_symbols(self) -> list[str]:
        return [line.symbol for line in self.lines if line.submittable]

    @property
    def blocked_symbols(self) -> list[str]:
        return [line.symbol for line in self.lines if not line.submittable]


@dataclass(frozen=True)
class PanicFlattenResult:
    plan: PanicFlattenPlan
    dry_run: bool
    submitted: list[dict] = field(default_factory=list)
    canceled: list[str] = field(default_factory=list)
    froze_live: bool = False
    operational_guard_ok: bool | None = None
    operational_guard_issues: list[str] = field(default_factory=list)
    email_queued: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "live_sleeve": self.plan.live_sleeve,
            "would_submit" if self.dry_run else "submitted": [
                {"symbol": ln.symbol, "qty": ln.qty, "limit_price": ln.limit_price}
                for ln in self.plan.lines
                if ln.submittable
            ],
            "blocked_by_guard": [
                {"symbol": ln.symbol, "reasons": ln.block_reasons}
                for ln in self.plan.lines
                if not ln.submittable
            ],
            "open_orders_to_cancel" if self.dry_run else "canceled":
                self.plan.open_orders_to_cancel if self.dry_run else self.canceled,
            "froze_live": self.froze_live,
            "operational_guard_ok": self.operational_guard_ok,
            "operational_guard_issues": self.operational_guard_issues,
            "email_queued": self.email_queued,
        }

    def render_plain(self) -> str:
        if self.dry_run:
            head = "PANIC-FLATTEN PREVIEW (nothing was submitted or changed)."
        else:
            head = "PANIC-FLATTEN EXECUTED — the system is standing down."
        lines = [head, ""]
        sellable = [ln for ln in self.plan.lines if ln.submittable]
        blocked = [ln for ln in self.plan.lines if not ln.submittable]
        verb = "Would sell" if self.dry_run else "Sold"
        if sellable:
            lines.append(f"{verb} (passes every safety check):")
            for ln in sellable:
                lines.append(f"  - {ln.symbol}: {ln.qty} share(s), limit {ln.limit_price}")
        else:
            lines.append(f"No positions {'would be' if self.dry_run else 'were'} sold automatically.")
        if blocked:
            lines.append("")
            lines.append("The safety gate is holding these back (it needs proper loss evidence "
                         "before selling at a loss — this is protecting you, not a bug):")
            for ln in blocked:
                lines.append(f"  - {ln.symbol}: {'; '.join(ln.block_reasons) or 'blocked by go-live guard'}")
            lines.append("  To exit these, provide a loss-exit review through the normal flow, "
                         "or sell them yourself at the broker.")
        cancel_list = self.plan.open_orders_to_cancel if self.dry_run else self.canceled
        if cancel_list:
            lines.append("")
            lines.append(("Would cancel" if self.dry_run else "Canceled")
                         + f" {len(cancel_list)} open live order(s).")
        lines.append("")
        lines.append(("Live trading would be frozen after selling." if self.dry_run
                      else "Live trading is now frozen (no new orders until you refresh it)."))
        return "\n".join(lines)


def _resolve_live_sleeve(promotion_state: dict[str, Any] | None) -> str | None:
    sleeves = promotion_state.get("sleeves") if isinstance(promotion_state, dict) else None
    if not isinstance(sleeves, dict):
        return None
    for name, record in sleeves.items():
        if isinstance(record, dict) and record.get("live_enabled") is True:
            return name
    return None


def _review_position_dict(position: dict[str, Any], *, limit_price: Decimal) -> dict[str, Any]:
    """Honest manual-override review inputs. Narrative fields attest the override;
    no market/thesis data is fabricated, so a losing position still fails the loss
    gate unless real evidence exists — by design."""

    enriched = dict(position)
    enriched.setdefault("allowed_exit_reason", "user_manual_override")
    enriched.setdefault("allowed_exit_reason_source", "owner_panic_flatten_kill_switch")
    enriched.setdefault("current_thesis_status", "owner_manual_override_stand_down")
    enriched.setdefault(
        "why_hold_is_worse_than_sell",
        "Owner invoked the panic-flatten kill switch to stand down all live positions.",
    )
    enriched.setdefault("confidence", "1.0")
    return enriched


def build_flatten_actions(
    live_positions: list[dict[str, Any]],
    *,
    live_sleeve: str | None,
    discount_pct: Decimal,
    now: datetime.datetime,
    decision_prefix: str = "panic-flatten",
) -> list[HourlySupervisorAction]:
    actions: list[HourlySupervisorAction] = []
    for position in live_positions:
        symbol = str(position.get("symbol", "")).upper()
        qty = _dec(position.get("qty"))
        current_price = _dec(position.get("current_price"))
        if not symbol or qty <= 0 or current_price <= 0:
            continue
        limit_price = (current_price * (Decimal("1") - discount_pct / Decimal("100"))).quantize(Decimal("0.01"))
        decision_id = f"{decision_prefix}-{symbol}-{now:%Y%m%d%H%M%S}"
        review = loss_exit_review_packet(
            _review_position_dict(position, limit_price=limit_price),
            generated_at=now,
            decision_id=decision_id,
            side="sell",
            proposed_limit_price=limit_price,
        )
        actions.append(
            HourlySupervisorAction(
                action="sell",
                symbol=symbol,
                notional=(qty * limit_price).quantize(Decimal("0.01")),
                limit_price=limit_price,
                side="sell",
                order_type="limit",
                reason="owner panic-flatten kill switch",
                qty=qty,
                account="live",
                execution_mode="tiny_live",
                sleeve=live_sleeve or "",
                asset_class="stock",
                decision_id=decision_id,
                evidence={"loss_exit_review": review},
            )
        )
    return actions


def plan_panic_flatten(
    *,
    live_positions: list[dict[str, Any]],
    live_open_orders: list[dict[str, Any]],
    live_account: dict[str, Any] | None,
    live_sleeve: str | None,
    now: datetime.datetime,
    discount_pct: Decimal,
    risk_envelope_path: str | Path = "config/risk_envelope.yaml",
    promotion_state_path: str | Path = "results/policy/promotion_state.json",
    control_state_path: str | Path = "results/policy/live_control.json",
) -> PanicFlattenPlan:
    """Build the flatten plan and classify each position via the FULL go-live guard."""

    actions = build_flatten_actions(
        live_positions, live_sleeve=live_sleeve, discount_pct=discount_pct, now=now
    )
    live_buying_power = _dec(live_account.get("buying_power")) if isinstance(live_account, dict) else None

    lines: list[FlattenLine] = []
    submittable_actions: list[HourlySupervisorAction] = []
    positions_by_symbol = {str(p.get("symbol", "")).upper(): p for p in live_positions}
    for action in actions:
        position = positions_by_symbol.get(action.symbol, {})
        avg_entry = _dec(position.get("avg_entry_price"))
        at_loss = avg_entry > 0 and action.limit_price < avg_entry
        # Each action must independently pass the full unified guard.
        result = evaluate_go_live_guard(
            [action],
            risk_envelope_path=risk_envelope_path,
            promotion_state_path=promotion_state_path,
            control_state_path=control_state_path,
            live_buying_power=live_buying_power,
            live_positions=live_positions,
            now=now,
        )
        submittable = result.allowed
        block_reasons = [str(issue) for issue in result.issues]
        lines.append(FlattenLine(
            symbol=action.symbol,
            qty=str(action.qty.normalize()) if action.qty is not None else "0",
            limit_price=str(action.limit_price),
            at_loss=at_loss,
            submittable=submittable,
            block_reasons=block_reasons,
        ))
        if submittable:
            submittable_actions.append(action)

    open_ids = [
        str(order.get("client_order_id") or order.get("id") or "")
        for order in live_open_orders
        if order.get("client_order_id") or order.get("id")
    ]
    return PanicFlattenPlan(
        generated_at=now,
        live_sleeve=live_sleeve,
        lines=lines,
        submittable_actions=submittable_actions,
        open_orders_to_cancel=open_ids,
    )


def _cancel_open_orders(live_client: Any, open_orders: list[dict[str, Any]]) -> list[str]:
    cancel = getattr(live_client, "cancel_order", None)
    if not callable(cancel):
        return []
    canceled: list[str] = []
    for order in open_orders:
        order_id = order.get("id") or order.get("client_order_id")
        if not order_id:
            continue
        try:
            cancel(order_id)
            canceled.append(str(order_id))
        except Exception:  # noqa: BLE001 - best effort; report what succeeded.
            continue
    return canceled


def run_panic_flatten(
    *,
    live_client: Any,
    confirm: str = "",
    submit_enabled: bool = False,
    risk_envelope_path: str | Path = "config/risk_envelope.yaml",
    promotion_state_path: str | Path = "results/policy/promotion_state.json",
    control_state_path: str | Path = "results/policy/live_control.json",
    lock_path: str | Path = "results/policy/tiny_live_submit.lock",
    now: datetime.datetime | None = None,
    discount_pct: Decimal | None = None,
    email: bool = True,
    email_to: str = "",
    outbox_dir: str | Path = "results/outbox",
) -> PanicFlattenResult:
    now = now or datetime.datetime.now(tz=UTC)
    if discount_pct is None:
        discount_pct = load_exit_policy(risk_envelope_path).sell_limit_discount_pct

    positions = list(live_client.list_positions())
    open_orders = list(live_client.list_orders(status="open"))
    account = live_client.get_account() if hasattr(live_client, "get_account") else None
    promotion_state, _ = _read_promotion_state(Path(promotion_state_path))
    live_sleeve = _resolve_live_sleeve(promotion_state)

    plan = plan_panic_flatten(
        live_positions=positions,
        live_open_orders=open_orders,
        live_account=account,
        live_sleeve=live_sleeve,
        now=now,
        discount_pct=discount_pct,
        risk_envelope_path=risk_envelope_path,
        promotion_state_path=promotion_state_path,
        control_state_path=control_state_path,
    )

    armed = confirm == "FLATTEN" and bool(submit_enabled)
    if not armed:
        return PanicFlattenResult(plan=plan, dry_run=True)

    # --- ARMED: cancel opens, submit guard-passing sells, freeze, email. ---
    canceled = _cancel_open_orders(live_client, open_orders)

    submitted: list[dict] = []
    op_ok: bool | None = None
    op_issues: list[str] = []
    if plan.submittable_actions:
        guard = acquire_tiny_live_operational_guard(
            live_actions=plan.submittable_actions,
            live_client=live_client,
            expected_live_positions=positions,
            expected_live_open_orders=open_orders,
            owner=f"panic-flatten-{now:%Y%m%d-%H%M%S}",
            lock_path=lock_path,
            control_state_path=control_state_path,
            now=now,
        )
        op_ok = guard.allowed
        op_issues = [str(issue) for issue in guard.issues]
        try:
            if guard.allowed:
                for action in plan.submittable_actions:
                    client_order_id = supervisor_live_client_order_id(action, generated_at=now)
                    payload = build_supervisor_order_payload(action, client_order_id=client_order_id)
                    submitted.append(live_client.submit_order(payload))
        finally:
            if guard.lock and guard.lock.acquired:
                release_execution_lock(guard.lock.path)

    # Freeze AFTER selling (freeze blocks sells too).
    write_live_control_state(
        control_state_path,
        frozen=True,
        reason="panic-flatten kill switch invoked by owner",
        dead_man_expires_at=now + datetime.timedelta(days=3650),
    )

    result = PanicFlattenResult(
        plan=plan,
        dry_run=False,
        submitted=submitted,
        canceled=canceled,
        froze_live=True,
        operational_guard_ok=op_ok,
        operational_guard_issues=op_issues,
        email_queued=False,
    )
    if email:
        write_outbox_message(
            {
                "email_to": email_to,
                "subject": "Trading system: PANIC-FLATTEN executed",
                "body": result.render_plain(),
            },
            outbox_dir=outbox_dir,
            report_type="panic_flatten",
            severity="CRITICAL",
        )
        result = PanicFlattenResult(
            plan=plan, dry_run=False, submitted=submitted, canceled=canceled,
            froze_live=True, operational_guard_ok=op_ok,
            operational_guard_issues=op_issues, email_queued=True,
        )
    return result
