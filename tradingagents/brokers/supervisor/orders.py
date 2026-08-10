"""Hourly supervisor order/notification formatting helpers.

These helpers shape already-approved supervisor actions into payloads and
notification decisions. They do not validate live authority or submit orders.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from tradingagents.brokers.supervisor.types import (
    HourlySupervisorAction,
    HourlySupervisorDecision,
)


def should_notify_supervisor(
    decision: HourlySupervisorDecision,
    *,
    notification_policy: str,
) -> bool:
    if notification_policy == "every-check":
        return True
    if notification_policy == "daily-digest":
        return decision.material
    if notification_policy == "urgent-exceptions":
        return (
            bool(decision.submitted)
            or bool(decision.issues)
            or decision.decision
            in {
                "blocked",
                "buy",
                "close",
                "loss-review",
                "paper-first",
                "profit-take",
                "reduce",
                "rotate",
                "review-open-orders",
            }
        )
    return decision.material or bool(decision.issues) or bool(decision.submitted)


def is_order_action(action: HourlySupervisorAction) -> bool:
    return action.action.lower() in {"buy", "reduce", "close", "rotate"}


def build_supervisor_order_payload(
    action: HourlySupervisorAction,
    *,
    client_order_id: str,
) -> dict:
    payload = {
        "symbol": action.symbol.upper(),
        "side": action.normalized_side(),
        "type": "limit",
        "time_in_force": "day",
        "limit_price": _price(action.limit_price),
        "client_order_id": client_order_id,
        "extended_hours": bool(action.extended_hours),
    }
    if action.qty is not None and action.normalized_side() == "sell":
        payload["qty"] = str(action.qty.normalize())
    else:
        payload["notional"] = _money(action.notional)
    return payload


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def _money(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _price(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
