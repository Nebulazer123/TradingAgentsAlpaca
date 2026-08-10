"""Operational guard for the tiny-live submit path."""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from tradingagents.brokers.alpaca import OrderIssue
from tradingagents.execution.clock import evaluate_clock_guard
from tradingagents.execution.lock import ExecutionLockResult, acquire_execution_lock
from tradingagents.execution.reconcile import reconcile_live_state
from tradingagents.policy.live_control import load_live_control_state

UTC = datetime.timezone.utc


@dataclass(frozen=True)
class TinyLiveOperationalGuardResult:
    allowed: bool
    issues: list[OrderIssue] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    lock: ExecutionLockResult | None = None


def _action_symbol(action) -> str:
    if isinstance(action, dict):
        return str(action.get("symbol", "TINY_LIVE")).upper()
    return str(getattr(action, "symbol", "TINY_LIVE")).upper()


def _expected_positions(positions: Sequence[Mapping]) -> dict[str, Decimal]:
    expected: dict[str, Decimal] = {}
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        if not symbol:
            continue
        expected[symbol] = Decimal(str(position.get("qty") or "0"))
    return expected


def _expected_open_ids(open_orders: Sequence[Mapping]) -> set[str]:
    return {
        str(order.get("client_order_id"))
        for order in open_orders
        if order.get("client_order_id")
    }


def _broker_clock_snapshot(live_client) -> Mapping | None:
    if not hasattr(live_client, "get_clock"):
        return None
    clock = live_client.get_clock()
    return clock if isinstance(clock, Mapping) else None


def _broker_clock_time(clock: Mapping | None) -> datetime.datetime | None:
    if not isinstance(clock, Mapping):
        return None
    raw = str(clock.get("timestamp") or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _broker_clock_is_open(clock: Mapping | None) -> bool | None:
    if not isinstance(clock, Mapping) or "is_open" not in clock:
        return None
    raw = clock.get("is_open")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _action_extended_hours(action) -> bool:
    if isinstance(action, Mapping):
        return bool(action.get("extended_hours"))
    return bool(getattr(action, "extended_hours", False))


def _broker_has_trading_day(live_client, reference_time: datetime.datetime) -> bool:
    if not hasattr(live_client, "list_calendar"):
        return False
    day = reference_time.astimezone(UTC).date().isoformat()
    try:
        calendar = live_client.list_calendar(start=day, end=day)
    except Exception:
        return False
    return bool(calendar)


def acquire_tiny_live_operational_guard(
    *,
    live_actions: Sequence,
    live_client,
    expected_live_positions: Sequence[Mapping],
    expected_live_open_orders: Sequence[Mapping],
    owner: str,
    lock_path: str | Path = "results/policy/tiny_live_submit.lock",
    control_state_path: str | Path | None = None,
    now: datetime.datetime | None = None,
    max_clock_skew_seconds: int = 120,
    stale_lock_after_seconds: int = 900,
) -> TinyLiveOperationalGuardResult:
    if not live_actions:
        return TinyLiveOperationalGuardResult(
            allowed=True,
            checks={"no_live_actions": True},
        )

    checks = {
        "single_writer_lock": False,
        "broker_clock": False,
        "broker_session": False,
        "reconciliation": False,
    }
    issues: list[OrderIssue] = []
    symbol = _action_symbol(live_actions[0])

    lock = acquire_execution_lock(
        lock_path,
        owner=owner,
        stale_after_seconds=stale_lock_after_seconds,
    )
    if not lock.acquired:
        issues.append(OrderIssue(symbol, f"tiny-live single-writer lock blocked submit: {lock.reason}"))
        return TinyLiveOperationalGuardResult(
            allowed=False,
            issues=issues,
            checks=checks,
            lock=lock,
        )
    checks["single_writer_lock"] = True

    # Re-validate live control (freeze + dead-man) at the actual submit moment.
    # The unified gate already checked this at decision time; this catches a
    # freeze or dead-man expiry that happened between gate evaluation and submit.
    if control_state_path is not None:
        _control_state, control_issues = load_live_control_state(
            control_state_path, now=now
        )
        checks["live_control_recheck"] = not control_issues
        issues.extend(
            OrderIssue(
                symbol,
                f"tiny-live live-control re-check blocked submit: {issue}",
            )
            for issue in control_issues
        )

    clock_snapshot = _broker_clock_snapshot(live_client)
    reference_time = _broker_clock_time(clock_snapshot)
    if reference_time is None:
        issues.append(OrderIssue(symbol, "tiny-live broker clock is unavailable"))
    else:
        clock = evaluate_clock_guard(
            local_time=now or datetime.datetime.now(tz=UTC),
            reference_time=reference_time,
            max_skew_seconds=max_clock_skew_seconds,
        )
        checks["broker_clock"] = clock.allowed
        if not clock.allowed:
            issues.append(OrderIssue(symbol, f"tiny-live clock guard blocked submit: {clock.reason}"))
        broker_is_open = _broker_clock_is_open(clock_snapshot)
        if broker_is_open is True:
            checks["broker_session"] = True
        elif broker_is_open is False:
            if all(_action_extended_hours(action) for action in live_actions):
                if _broker_has_trading_day(live_client, reference_time):
                    checks["broker_session"] = True
                else:
                    issues.append(
                        OrderIssue(
                            symbol,
                            (
                                "tiny-live broker calendar blocked extended-hours submit: "
                                "today is not confirmed as a trading day"
                            ),
                        )
                    )
            else:
                issues.append(
                    OrderIssue(
                        symbol,
                        "tiny-live broker clock reports market is closed for a regular-hours order",
                    )
                )
        else:
            issues.append(OrderIssue(symbol, "tiny-live broker clock is_open is unavailable"))

    reconciliation = reconcile_live_state(
        expected_positions=_expected_positions(expected_live_positions),
        broker_positions=live_client.list_positions(),
        expected_open_client_order_ids=_expected_open_ids(expected_live_open_orders),
        broker_open_orders=live_client.list_orders(status="open"),
    )
    checks["reconciliation"] = reconciliation.matched
    issues.extend(
        OrderIssue(symbol, f"tiny-live reconciliation blocked submit: {issue}")
        for issue in reconciliation.issues
    )

    return TinyLiveOperationalGuardResult(
        allowed=not issues,
        issues=issues,
        checks=checks,
        lock=lock,
    )
