"""Pre-registered mechanical exit policy for losing positions.

The loss-review evidence contract (``brokers/supervisor/loss_review.py``)
was designed for narrative exits: thesis broken, company news, earnings
break. In practice nothing supplied that narrative, so losing positions
(NFLX, TSM) sat in HOLD/loss-review indefinitely while drawdowns grew.

This module adds the missing deterministic lane, based on standard
swing-trading risk discipline:

- **Hard stop floor** (default −8%): the classic max-loss rule (O'Neil's
  7–8% discipline). Cutting at −8% means a losing trade needs only a
  +8.7% recovery elsewhere; waiting to −25% needs +33%.
- **Catastrophic floor** (default −12%): unconditional exit; no position
  in a caps-first tiny-live book earns a deeper drawdown.
- **Time stop** (default 15 trading days at worse than −5%): positions
  that stay underwater for weeks have negative expectancy vs redeploying;
  requires holding-period evidence to fire.
- **Realistic fills**: sell limits are priced slightly *below* the last
  price (default 0.3%) so the limit-only order actually executes instead
  of sitting unfilled above the bid.

The policy is *pre-registered*: the rules and thresholds live here (and
may be overridden in ``config/risk_envelope.yaml``), so a triggered exit
is its own documented justification — no per-position narrative needed.
This module only annotates positions; order submission still passes the
hourly guardrails and the unified go-live guard.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

UTC = datetime.timezone.utc

#: Reason codes contributed by this policy (accepted by loss_review).
POLICY_STOP_FLOOR = "policy_stop_floor"
POLICY_TIME_STOP = "policy_time_stop"
POLICY_REASON_CODES = frozenset({POLICY_STOP_FLOOR, POLICY_TIME_STOP})
POLICY_REASON_RULE_IDS: dict[str, frozenset[str]] = {
    POLICY_STOP_FLOOR: frozenset({"hard_stop", "catastrophic_stop"}),
    POLICY_TIME_STOP: frozenset({"time_stop"}),
}


@dataclass(frozen=True)
class ExitPolicy:
    hard_stop_loss_pct: Decimal = Decimal("8")
    catastrophic_stop_loss_pct: Decimal = Decimal("12")
    time_stop_trading_days: int = 15
    time_stop_min_loss_pct: Decimal = Decimal("5")
    sell_limit_discount_pct: Decimal = Decimal("0.3")

    def as_dict(self) -> dict[str, str | int]:
        return {
            "hard_stop_loss_pct": str(self.hard_stop_loss_pct),
            "catastrophic_stop_loss_pct": str(self.catastrophic_stop_loss_pct),
            "time_stop_trading_days": self.time_stop_trading_days,
            "time_stop_min_loss_pct": str(self.time_stop_min_loss_pct),
            "sell_limit_discount_pct": str(self.sell_limit_discount_pct),
        }


@dataclass(frozen=True)
class ExitPolicyDecision:
    triggered: bool
    reason_code: str | None = None
    rule_id: str | None = None
    rationale: str = ""
    proposed_limit_price: Decimal | None = None
    loss_pct: Decimal | None = None


DEFAULT_EXIT_POLICY = ExitPolicy()

_ENVELOPE_KEYS = {
    "hard_stop_loss_pct": "hard_stop_loss_pct",
    "catastrophic_stop_loss_pct": "catastrophic_stop_loss_pct",
    "time_stop_trading_days": "time_stop_trading_days",
    "time_stop_min_loss_pct": "time_stop_min_loss_pct",
    "sell_limit_discount_pct": "sell_limit_discount_pct",
}


def _as_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def load_exit_policy(envelope_path: str | Path = "config/risk_envelope.yaml") -> ExitPolicy:
    """Read optional exit-policy overrides from the risk envelope file.

    Missing file or keys fall back to the pre-registered defaults; the
    policy must never fail open (an unreadable file means defaults, and
    defaults are the conservative documented rules).
    """
    path = Path(envelope_path)
    if not path.exists():
        return DEFAULT_EXIT_POLICY
    values: dict[str, Any] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key, _, raw = stripped.partition(":")
            key = key.strip()
            if key in _ENVELOPE_KEYS:
                values[key] = raw.split("#", 1)[0].strip()
    except OSError:
        return DEFAULT_EXIT_POLICY
    if not values:
        return DEFAULT_EXIT_POLICY
    return ExitPolicy(
        hard_stop_loss_pct=_as_decimal(
            values.get("hard_stop_loss_pct"), str(DEFAULT_EXIT_POLICY.hard_stop_loss_pct)
        ),
        catastrophic_stop_loss_pct=_as_decimal(
            values.get("catastrophic_stop_loss_pct"),
            str(DEFAULT_EXIT_POLICY.catastrophic_stop_loss_pct),
        ),
        time_stop_trading_days=int(
            _as_decimal(
                values.get("time_stop_trading_days"),
                str(DEFAULT_EXIT_POLICY.time_stop_trading_days),
            )
        ),
        time_stop_min_loss_pct=_as_decimal(
            values.get("time_stop_min_loss_pct"),
            str(DEFAULT_EXIT_POLICY.time_stop_min_loss_pct),
        ),
        sell_limit_discount_pct=_as_decimal(
            values.get("sell_limit_discount_pct"),
            str(DEFAULT_EXIT_POLICY.sell_limit_discount_pct),
        ),
    )


def _holding_trading_days(position: Mapping, *, generated_at: datetime.datetime) -> int | None:
    explicit = position.get("holding_period_trading_days")
    if explicit not in (None, ""):
        try:
            return max(0, int(Decimal(str(explicit))))
        except (InvalidOperation, TypeError, ValueError):
            return None
    opened_raw = None
    for key in ("opened_at", "entry_at", "buy_filled_at", "filled_at"):
        if position.get(key):
            opened_raw = position.get(key)
            break
    if opened_raw is None:
        return None
    try:
        opened = datetime.datetime.fromisoformat(str(opened_raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)
    current = opened.astimezone(UTC).date()
    end_date = generated_at.astimezone(UTC).date()
    days = 0
    while current < end_date:
        current += datetime.timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def evaluate_exit_policy(
    position: Mapping,
    *,
    generated_at: datetime.datetime,
    policy: ExitPolicy | None = None,
) -> ExitPolicyDecision:
    policy = policy or DEFAULT_EXIT_POLICY
    plpc = _as_decimal(position.get("unrealized_plpc"))
    if plpc >= 0:
        return ExitPolicyDecision(triggered=False)
    loss_pct = -plpc * Decimal("100")
    current_price = _as_decimal(position.get("current_price"))
    # Round the sell limit DOWN: the fill-friendly direction for a limit sell.
    limit_price = (
        (current_price * (Decimal("1") - policy.sell_limit_discount_pct / Decimal("100")))
        .quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if current_price > 0
        else None
    )

    if loss_pct >= policy.catastrophic_stop_loss_pct:
        return ExitPolicyDecision(
            triggered=True,
            reason_code=POLICY_STOP_FLOOR,
            rule_id="catastrophic_stop",
            rationale=(
                f"Position is down {loss_pct:.2f}%, beyond the "
                f"{policy.catastrophic_stop_loss_pct}% catastrophic floor. The "
                "pre-registered policy exits unconditionally: recovering a "
                "deeper drawdown requires outsized gains elsewhere."
            ),
            proposed_limit_price=limit_price,
            loss_pct=loss_pct,
        )
    if loss_pct >= policy.hard_stop_loss_pct:
        return ExitPolicyDecision(
            triggered=True,
            reason_code=POLICY_STOP_FLOOR,
            rule_id="hard_stop",
            rationale=(
                f"Position is down {loss_pct:.2f}%, beyond the "
                f"{policy.hard_stop_loss_pct}% max-loss stop. Cutting here keeps "
                "single-trade damage recoverable (the 7-8% max-loss discipline)."
            ),
            proposed_limit_price=limit_price,
            loss_pct=loss_pct,
        )
    holding_days = _holding_trading_days(position, generated_at=generated_at)
    if (
        holding_days is not None
        and holding_days >= policy.time_stop_trading_days
        and loss_pct >= policy.time_stop_min_loss_pct
    ):
        return ExitPolicyDecision(
            triggered=True,
            reason_code=POLICY_TIME_STOP,
            rule_id="time_stop",
            rationale=(
                f"Position has been underwater {loss_pct:.2f}% for "
                f"{holding_days} trading day(s) (limit "
                f"{policy.time_stop_trading_days}). Dead money is redeployed "
                "instead of waiting on a thesis that has not paid."
            ),
            proposed_limit_price=limit_price,
            loss_pct=loss_pct,
        )
    return ExitPolicyDecision(triggered=False, loss_pct=loss_pct)


def verify_pre_registered_exit_policy(
    position: Mapping,
    *,
    generated_at: datetime.datetime,
    proposed_limit_price: Decimal | int | float | str | None,
    policy: ExitPolicy | None = None,
) -> ExitPolicyDecision | None:
    """Return a fresh matching policy decision, never caller-supplied authority.

    A mechanical exit may carry a deterministic source string instead of a
    discretionary evidence-packet descriptor.  That exception is valid only
    when every policy claim and the proposed sell limit agree with a fresh
    evaluation of the current position.
    """
    policy = policy or DEFAULT_EXIT_POLICY
    decision = evaluate_exit_policy(position, generated_at=generated_at, policy=policy)
    if not decision.triggered or decision.proposed_limit_price is None:
        return None
    if position.get("allowed_exit_reason") != decision.reason_code:
        return None
    if position.get("allowed_exit_reason_source") != _policy_reason_source(decision, policy):
        return None
    if position.get("exit_policy_rule") != decision.rule_id:
        return None
    if position.get("exit_policy_rationale") != decision.rationale:
        return None
    if not _matches_policy_limit(
        position.get("exit_policy_limit_price"), decision.proposed_limit_price
    ):
        return None
    if not _matches_policy_limit(proposed_limit_price, decision.proposed_limit_price):
        return None
    return decision


def verify_pre_registered_exit_policy_review(
    review: Mapping,
    *,
    policy: ExitPolicy | None = None,
    current_position: Mapping | None = None,
    now: datetime.datetime | None = None,
) -> ExitPolicyDecision | None:
    """Verify a persisted mechanical review against current broker facts.

    This is an authority-bearing verifier.  A detached persisted review is
    deliberately not a valid input: callers must independently capture both
    the current position and a timezone-aware authority clock.  Producer-side
    inspection belongs to :func:`verify_pre_registered_exit_policy`, which
    only evaluates the position supplied to that producer and cannot grant
    final submit authority.
    """
    policy = policy or DEFAULT_EXIT_POLICY
    if (
        not isinstance(current_position, Mapping)
        or not isinstance(now, datetime.datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        return None
    generated_at = _review_generated_at(review.get("evidence_generated_at"))
    evaluation_at = now.astimezone(UTC)
    current_price = _finite_decimal(review.get("current_price"))
    average_entry_price = _finite_decimal(review.get("average_entry_price"))
    unrealized_pct = _finite_decimal(review.get("unrealized_plpc"))
    policy_loss_pct = _finite_decimal(review.get("exit_policy_loss_pct"))
    holding_days = _review_holding_days(review.get("holding_period_trading_days"))
    if (
        generated_at is None
        or evaluation_at is None
        or current_price is None
        or current_price <= 0
        or average_entry_price is None
        or current_price >= average_entry_price
        or unrealized_pct is None
    ):
        return None
    live_symbol = str(current_position.get("symbol") or "").upper()
    review_symbol = str(review.get("symbol") or "").upper()
    live_current_price = _finite_decimal(current_position.get("current_price"))
    live_average_entry = _finite_decimal(
        current_position.get("avg_entry_price")
        if current_position.get("avg_entry_price") not in (None, "")
        else current_position.get("average_entry_price")
    )
    live_quantity = _finite_decimal(
        current_position.get("qty")
        if current_position.get("qty") not in (None, "")
        else current_position.get("quantity")
    )
    review_quantity = _finite_decimal(review.get("quantity"))
    review_opened_at = _review_opened_at(review.get("opened_at"))
    live_opened_at = _position_opened_at(current_position)
    if (
        not live_symbol
        or live_symbol != review_symbol
        or live_current_price is None
        or live_average_entry is None
        or live_quantity is None
        or live_current_price <= 0
        or live_average_entry <= 0
        or live_quantity <= 0
        or review_quantity is None
        or review_quantity <= 0
        or current_price != live_current_price
        or average_entry_price != live_average_entry
        or review_quantity != live_quantity
        or holding_days is None
        or review_opened_at is None
        or review_opened_at != live_opened_at
    ):
        return None
    recomputed_holding_days = _holding_trading_days(
        {"opened_at": live_opened_at}, generated_at=evaluation_at
    )
    if recomputed_holding_days is None or holding_days != recomputed_holding_days:
        return None
    supplied_holding_days = current_position.get("holding_period_trading_days")
    if supplied_holding_days not in (None, "") and _review_holding_days(
        supplied_holding_days
    ) != recomputed_holding_days:
        return None

    # Recompute the loss from broker price/entry rather than accepting a
    # persisted percentage.  The two-decimal percent is the receipt format;
    # any broker scalar is checked against a bounded canonical fraction to
    # tolerate harmless vendor precision differences without accepting a
    # different return.
    recomputed_unrealized_plpc = (
        live_current_price - live_average_entry
    ) / live_average_entry
    supplied_unrealized_plpc = current_position.get("unrealized_plpc")
    if supplied_unrealized_plpc not in (None, ""):
        broker_unrealized_plpc = _finite_decimal(supplied_unrealized_plpc)
        if (
            broker_unrealized_plpc is None
            or _canonical_unrealized_plpc(broker_unrealized_plpc)
            != _canonical_unrealized_plpc(recomputed_unrealized_plpc)
        ):
            return None
    recomputed_unrealized_pct = (recomputed_unrealized_plpc * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    if unrealized_pct != recomputed_unrealized_pct:
        return None
    if (
        policy_loss_pct is None
        or policy_loss_pct <= 0
        or _canonical_unrealized_plpc(-policy_loss_pct / Decimal("100"))
        != _canonical_unrealized_plpc(recomputed_unrealized_plpc)
    ):
        return None
    position = {
        "unrealized_plpc": str(recomputed_unrealized_plpc),
        "current_price": str(live_current_price),
        "opened_at": live_opened_at,
        "allowed_exit_reason": review.get("allowed_exit_reason"),
        "allowed_exit_reason_source": review.get("allowed_exit_reason_source"),
        "exit_policy_rule": review.get("exit_policy_rule"),
        "exit_policy_rationale": review.get("exit_policy_rationale"),
        "exit_policy_limit_price": review.get("proposed_limit_price"),
    }
    return verify_pre_registered_exit_policy(
        position,
        generated_at=evaluation_at,
        proposed_limit_price=review.get("proposed_limit_price"),
        policy=policy,
    )


def _policy_reason_source(decision: ExitPolicyDecision, policy: ExitPolicy) -> str:
    return (
        f"pre-registered exit policy rule '{decision.rule_id}' "
        f"(tradingagents/policy/exit_policy.py; thresholds {policy.as_dict()})"
    )


def _matches_policy_limit(value: object, expected: Decimal) -> bool:
    if value in (None, ""):
        return False
    try:
        return Decimal(str(value)) == expected
    except (InvalidOperation, TypeError, ValueError):
        return False


def _finite_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _canonical_unrealized_plpc(value: Decimal) -> Decimal:
    """Return the fixed broker-return precision used for live binding."""
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def _review_generated_at(value: object) -> datetime.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _review_holding_days(value: object) -> int | None:
    parsed = _finite_decimal(value)
    if parsed is None or parsed < 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _review_opened_at(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    parsed = _review_generated_at(value)
    return parsed.isoformat(timespec="seconds") if parsed is not None else None


def _position_opened_at(position: Mapping) -> str | None:
    for key in ("opened_at", "entry_at", "buy_filled_at", "filled_at"):
        normalized = _review_opened_at(position.get(key))
        if normalized is not None:
            return normalized
    return None


def apply_exit_policy_to_position(
    position: Mapping,
    *,
    generated_at: datetime.datetime,
    policy: ExitPolicy | None = None,
) -> dict:
    """Return the position enriched with policy-exit evidence when triggered.

    Never overwrites narrative evidence already present on the position;
    the mechanical lane only fills the gap that caused HOLD deadlocks.
    """
    policy = policy or DEFAULT_EXIT_POLICY
    enriched = dict(position)
    if enriched.get("allowed_exit_reason"):
        return enriched
    decision = evaluate_exit_policy(position, generated_at=generated_at, policy=policy)
    if not decision.triggered:
        return enriched
    enriched["allowed_exit_reason"] = decision.reason_code
    enriched["allowed_exit_reason_source"] = _policy_reason_source(decision, policy)
    enriched["exit_policy_rule"] = decision.rule_id
    enriched["exit_policy_rationale"] = decision.rationale
    if decision.proposed_limit_price is not None:
        enriched["exit_policy_limit_price"] = str(decision.proposed_limit_price)
    return enriched
