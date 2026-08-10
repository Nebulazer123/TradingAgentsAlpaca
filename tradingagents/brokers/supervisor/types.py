"""Shared supervisor data contracts.

These dataclasses are pure data. They do not fetch broker state, validate live
authority, or submit orders.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from tradingagents.brokers.alpaca import OrderIssue
from tradingagents.brokers.supervisor.session import UTC


@dataclass(frozen=True)
class HourlySupervisorConfig:
    profit_review_plpc: Decimal = Decimal("0.05")
    loss_review_plpc: Decimal = Decimal("-0.03")
    notification_policy: str = "material-only"
    run_prefix: str = "hourly-supervisor"
    live_buy_threshold: Decimal = Decimal("0.75")
    paper_first_threshold: Decimal = Decimal("0.60")


@dataclass(frozen=True)
class HourlySupervisorAction:
    action: str
    symbol: str
    notional: Decimal
    limit_price: Decimal
    side: str | None = None
    order_type: str = "limit"
    reason: str = ""
    qty: Decimal | None = None
    account: str = "live"
    execution_mode: str = "live_now"
    sleeve: str = "legacy-supervisor"
    extended_hours: bool = False
    asset_class: str = "stock"
    decision_id: str = ""
    evidence: dict = field(default_factory=dict)

    def normalized_side(self) -> str:
        if self.action.lower() in {"hold", "hold_cash"}:
            if self.side:
                return self.side.lower()
            return "none"
        if self.side:
            return self.side.lower()
        return "buy" if self.action == "buy" else "sell"


@dataclass(frozen=True)
class HourlySupervisorDecision:
    decision: str
    material: bool
    reason: str
    live_exposure: Decimal
    actions: list[HourlySupervisorAction] = field(default_factory=list)
    issues: list[OrderIssue] = field(default_factory=list)
    submitted: list[dict] = field(default_factory=list)
    reconciled_orders: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    portfolio: dict = field(default_factory=dict)
    generated_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(tz=UTC)
    )
