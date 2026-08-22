"""Paper-account strategy tournament accounting and selection.

Alpaca paper accounts aggregate positions by symbol, so this module keeps a
local virtual ledger that attributes orders and performance to each strategy.
"""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingagents.brokers.alpaca import PAPER_BASE_URL
from tradingagents.brokers.alpaca_supervisor import CandidateSignal

UTC = datetime.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
MAX_BROKER_CLOCK_SKEW_SECONDS = 15 * 60
LEDGER_FILE = "paper-tournament-ledger.json"
COMPACT_LEDGER_FILE = "paper-tournament-ledger.compact.json"
LIVE_SELECTION_FILE = "live-strategy-selection.json"
LIVE_SELECTION_SCHEMA_VERSION = 1
STRATEGY_CURRENT_AGGRESSIVE = "current-aggressive"
STRATEGY_PULLBACK_SUPPORT = "pullback-support"
STRATEGY_CATALYST_ROTATION = "catalyst-relative-strength"
ALPHAINSIDER_PAPER_WATCH_ID = "alphainsider-popular-paper"
QUALIFICATION_TRIAL_LEDGER_TYPE = "qualification_paper_trial"
SUBMISSION_WINDOW_OPEN = "open"
SUBMISSION_WINDOW_FINALIZED = "finalized"
SUBMISSION_WINDOW_RECOVERY_REQUIRED = "recovery_required"
DEFAULT_TOURNAMENT_RESERVED_BUDGET = Decimal("30000")
STRATEGY_IDS = (
    STRATEGY_CURRENT_AGGRESSIVE,
    STRATEGY_PULLBACK_SUPPORT,
    STRATEGY_CATALYST_ROTATION,
)

_LEASE_THREAD_LOCKS: dict[str, threading.RLock] = {}
_LEASE_THREAD_LOCKS_GUARD = threading.Lock()

STRATEGY_DEFINITIONS = {
    STRATEGY_CURRENT_AGGRESSIVE: {
        "name": "Current Aggressive TradingAgents",
        "description": "Existing aggressive supervisor style: broad ranking, time-sensitive momentum, and rotations.",
    },
    STRATEGY_PULLBACK_SUPPORT: {
        "name": "Pullback Support Buyer",
        "description": "Buys strong liquid stocks on disciplined, non-thesis-breaking pullbacks.",
    },
    STRATEGY_CATALYST_ROTATION: {
        "name": "Catalyst / Relative Strength Rotation",
        "description": "Prioritizes fresh strength, volume, and catalyst-style momentum.",
    },
}

ALPHAINSIDER_PAPER_WATCH_DEFINITION = {
    "strategy_id": ALPHAINSIDER_PAPER_WATCH_ID,
    "name": "AlphaInsider Popular Strategies Paper Watch",
    "description": (
        "Tracks popular AlphaInsider stock strategies with leftover paper buying power. "
        "This is advisory/paper-only and cannot submit live orders."
    ),
}

POPULAR_STRATEGY_SCORECARD_DEFINITIONS = {
    STRATEGY_PULLBACK_SUPPORT: {
        "name": "Pullback Support",
        "setup_type": "buy_the_dip_support",
        "status_when_missing": "planned_paper_sleeve",
        "thesis": "Buy strong, liquid names on controlled dips that do not break the thesis.",
        "pass_criteria": [
            "positive paper total return",
            "controlled drawdown versus other sleeves",
            "evidence of rebound after entry",
        ],
        "fail_criteria": [
            "dip keeps falling through support",
            "drawdown dominates return",
            "entries cluster in stale or low-liquidity names",
        ],
    },
    "earnings-drift-estimate-revision": {
        "name": "Earnings Drift / Estimate Revision",
        "setup_type": "post_earnings_underreaction",
        "status_when_missing": "planned_paper_sleeve",
        "thesis": "Test whether positive estimate/guidance revisions keep drifting after the first reaction.",
        "pass_criteria": [
            "outperforms benchmark over stated horizon",
            "revision evidence remains fresh",
            "does not buy after an exhausted spike",
        ],
        "fail_criteria": [
            "guidance was already priced in",
            "revision reverses",
            "price loses relative strength before entry",
        ],
    },
    "event-underreaction": {
        "name": "Event Underreaction",
        "setup_type": "event_underreaction",
        "status_when_missing": "planned_paper_sleeve",
        "thesis": "Paper-test whether markets underreact to concrete catalysts with follow-through evidence.",
        "pass_criteria": [
            "event thesis resolves within the horizon",
            "relative return beats sector or broad benchmark",
            "source quality stays primary or corroborated",
        ],
        "fail_criteria": [
            "event impact was already priced",
            "follow-through volume fades",
            "source quality is weak or stale",
        ],
    },
    "pairs-comovement-residuals": {
        "name": "Pairs / Co-Movement Residuals",
        "setup_type": "pairs_residual_mean_reversion",
        "status_when_missing": "planned_paper_sleeve",
        "thesis": "Paper-test liquid relative-value spreads when one name diverges from a close peer basket.",
        "pass_criteria": [
            "spread closes without thesis break",
            "both legs remain liquid and borrow-neutral",
            "residual signal is not explained by new fundamentals",
        ],
        "fail_criteria": [
            "divergence has a real fundamental cause",
            "spread widens beyond invalidator",
            "leg liquidity or correlation deteriorates",
        ],
    },
    "news-sentiment-swing": {
        "name": "News / Sentiment Swing",
        "setup_type": "sentiment_overreaction_swing",
        "status_when_missing": "planned_paper_sleeve",
        "thesis": "Paper-test whether broad news/social sentiment overreacts before price mean-reverts.",
        "pass_criteria": [
            "sentiment shock fades",
            "price stabilizes near support",
            "source overlap confirms the story is not fake or stale",
        ],
        "fail_criteria": [
            "negative news is fundamental",
            "sentiment remains one-sided",
            "price breaks support with abnormal volume",
        ],
    },
    "macro-regime-overlay": {
        "name": "Macro Regime Overlay",
        "setup_type": "macro_regime_filter",
        "status_when_missing": "planned_paper_sleeve",
        "thesis": "Paper-test whether regime filters improve sleeve timing, cash thresholds, and sector selection.",
        "pass_criteria": [
            "reduces drawdown during risk-off tape",
            "improves cash deployment timing",
            "keeps sector exposure aligned with macro evidence",
        ],
        "fail_criteria": [
            "filter overreacts to noisy macro releases",
            "misses strong idiosyncratic setups",
            "adds turnover without better return",
        ],
    },
    ALPHAINSIDER_PAPER_WATCH_ID: {
        "name": ALPHAINSIDER_PAPER_WATCH_DEFINITION["name"],
        "setup_type": "popular_strategy_allocation_shadow",
        "status_when_missing": "planned_paper_shadow",
        "thesis": "Shadow popular third-party strategy allocations in paper only and compare outcomes.",
        "pass_criteria": [
            "shadow basket outperforms tournament reserve baseline",
            "strategy metadata contains concrete tickers",
            "weekly rotation improves paper evidence quality",
        ],
        "fail_criteria": [
            "popular basket underperforms or churns",
            "strategy metadata lacks actionable tickers",
            "shadow allocation conflicts with live safety gates",
        ],
        "rotation_schedule": "RRULE:FREQ=WEEKLY;BYHOUR=2;BYMINUTE=30;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    },
}

_STRATEGY_CLIENT_PREFIX = {
    STRATEGY_CURRENT_AGGRESSIVE: "current-aggressive",
    STRATEGY_PULLBACK_SUPPORT: "pullback-support",
    STRATEGY_CATALYST_ROTATION: "catalyst",
}


@dataclass(frozen=True)
class TournamentAction:
    strategy_id: str
    action: str
    symbol: str
    side: str
    notional: Decimal
    limit_price: Decimal
    reason: str
    extended_hours: bool = False


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value: Decimal | int | float | str | None) -> str:
    amount = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if amount == 0:
        amount = abs(amount)
    return str(amount)


def _price(value: Decimal | int | float | str | None) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _iso(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _parse_timestamp(value: object) -> datetime.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (OverflowError, TypeError, ValueError):
        return None


def _normalize_timestamp(value: datetime.datetime) -> datetime.datetime | None:
    try:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError):
        return None


def _tournament_expired(ends_at: object, *, now: datetime.datetime) -> bool:
    ends_at_timestamp = _parse_timestamp(ends_at)
    if ends_at_timestamp is None:
        return False
    now_timestamp = _normalize_timestamp(now)
    return now_timestamp is None or now_timestamp >= ends_at_timestamp


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=UTC)


@contextmanager
def tournament_submission_lock(output_dir: str | Path):
    """Serialize every paper-submit/finalize lease transaction for one ledger."""

    lock_path = Path(output_dir) / ".paper-tournament-submission.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_key = str(lock_path.resolve())
    with _LEASE_THREAD_LOCKS_GUARD:
        thread_lock = _LEASE_THREAD_LOCKS.setdefault(lock_key, threading.RLock())
    with thread_lock, lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _submission_lease_evidence(ledger: Mapping) -> str:
    """Hash the immutable part of the bounded paper-submission lease."""

    evidence = {
        "ledger_type": ledger.get("ledger_type"),
        "tournament_id": ledger.get("tournament_id"),
        "started_at": ledger.get("started_at"),
        "ends_at": ledger.get("ends_at"),
        "authorized_market_day_limit": ledger.get("authorized_market_day_limit"),
    }
    canonical = json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _central_market_date(now: datetime.datetime) -> str | None:
    normalized = _normalize_timestamp(now)
    if normalized is None:
        return None
    return normalized.astimezone(CENTRAL).date().isoformat()


def _parse_broker_clock_timestamp(value: object) -> datetime.datetime | None:
    """Accept only a timezone-aware timestamp from the broker clock response."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(UTC)
    except (OverflowError, TypeError, ValueError):
        return None


def _normalize_aware_policy_timestamp(value: object) -> datetime.datetime | None:
    """Reject a policy clock unless it is an aware datetime value."""

    if not isinstance(value, datetime.datetime) or value.tzinfo is None:
        return None
    try:
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError):
        return None


def _validate_regular_paper_broker_clock(
    paper_client: object,
    *,
    now: datetime.datetime,
    market_date: str,
) -> None:
    """Require a fresh, open, same-day regular-session paper broker clock."""

    get_clock = getattr(paper_client, "get_clock", None)
    if not callable(get_clock):
        raise ValueError("paper submission lease cannot verify the broker clock")
    try:
        clock = get_clock()
    except Exception as exc:
        raise ValueError("paper submission lease broker clock check failed") from exc
    if not isinstance(clock, Mapping) or clock.get("is_open") is not True:
        raise ValueError("paper submission lease requires an open broker clock")
    clock_timestamp = _parse_broker_clock_timestamp(clock.get("timestamp"))
    now_timestamp = _normalize_aware_policy_timestamp(now)
    if clock_timestamp is None or now_timestamp is None:
        raise ValueError("paper submission lease broker clock is malformed")
    if clock_timestamp > now_timestamp:
        raise ValueError("paper submission lease broker clock is future")
    if (now_timestamp - clock_timestamp).total_seconds() > MAX_BROKER_CLOCK_SKEW_SECONDS:
        raise ValueError("paper submission lease broker clock is stale")
    clock_central = clock_timestamp.astimezone(CENTRAL)
    policy_central = now_timestamp.astimezone(CENTRAL)
    if (
        policy_central.date().isoformat() != market_date
        or clock_central.date().isoformat() != market_date
    ):
        raise ValueError("paper submission lease broker clock has the wrong Central market date")
    regular_open = datetime.time(hour=8, minute=30)
    regular_close = datetime.time(hour=15)
    if not (
        regular_open <= policy_central.timetz().replace(tzinfo=None) < regular_close
        and regular_open <= clock_central.timetz().replace(tzinfo=None) < regular_close
    ):
        raise ValueError("paper submission lease broker clock is outside the regular session")


def _validate_exact_paper_client(paper_client: object) -> None:
    """Prove that the only possible submission transport is Alpaca paper."""

    assert_expected_mode = getattr(paper_client, "assert_expected_mode", None)
    if not callable(assert_expected_mode):
        raise ValueError("paper client does not provide exact mode enforcement")
    try:
        assert_expected_mode(paper=True)
    except Exception as exc:
        raise ValueError("paper client is not configured for exact paper mode") from exc
    settings = getattr(paper_client, "settings", None)
    if (
        settings is None
        or getattr(settings, "paper", None) is not True
        or getattr(settings, "base_url", None) != PAPER_BASE_URL
    ):
        raise ValueError("paper client endpoint is not the exact Alpaca paper endpoint")


def validate_submission_transaction_state(ledger: Mapping) -> None:
    """Reject every durable submission reservation that is not proven complete."""

    if "submission_transaction" not in ledger:
        return
    transaction = ledger["submission_transaction"]
    if not isinstance(transaction, Mapping) or transaction.get("status") != "completed":
        raise ValueError("paper submission lease recovery is required for an incomplete transaction")
    market_date = transaction.get("market_date")
    pending = transaction.get("pending_client_order_ids")
    successful = transaction.get("successful_submissions")
    if (
        type(market_date) is not str
        or _submitted_market_date_is_malformed(market_date)
        or not isinstance(pending, list)
        or pending
        or not isinstance(successful, list)
        or not successful
        or _parse_timestamp(transaction.get("started_at")) is None
        or _parse_timestamp(transaction.get("completed_at")) is None
        or not isinstance(ledger.get("submitted_market_dates"), list)
        or market_date not in ledger["submitted_market_dates"]
    ):
        raise ValueError("paper submission lease recovery is required for an incomplete transaction")
    for submission in successful:
        if (
            not isinstance(submission, Mapping)
            or type(submission.get("client_order_id")) is not str
            or not submission.get("client_order_id")
            or submission.get("market_date") != market_date
            or _parse_timestamp(submission.get("recorded_at")) is None
            or not isinstance(submission.get("response"), Mapping)
        ):
            raise ValueError("paper submission lease recovery is required for an incomplete transaction")


def _validate_submission_lease(
    ledger: Mapping,
    *,
    paper_client: object,
    now: datetime.datetime,
    allow_submitting_transaction: bool,
) -> str:
    """Validate every condition required before a paper order can be posted."""

    _validate_exact_paper_client(paper_client)
    now_timestamp = _normalize_aware_policy_timestamp(now)
    if now_timestamp is None or not isinstance(ledger, Mapping):
        raise ValueError("paper submission lease is malformed")
    if ledger.get("ledger_type") != QUALIFICATION_TRIAL_LEDGER_TYPE:
        raise ValueError("paper submission lease has an unsupported ledger type")
    if (
        not isinstance(ledger.get("tournament_id"), str)
        or not ledger.get("tournament_id")
        or not isinstance(ledger.get("started_at"), str)
        or not isinstance(ledger.get("ends_at"), str)
    ):
        raise ValueError("paper submission lease is malformed")
    if ledger.get("submission_window_status") != SUBMISSION_WINDOW_OPEN:
        raise ValueError("paper submission lease is closed or finalized")
    if not isinstance(ledger.get("submission_lease_evidence"), str) or (
        ledger.get("submission_lease_evidence") != _submission_lease_evidence(ledger)
    ):
        raise ValueError("paper submission lease evidence does not match ledger")
    started_at = _parse_timestamp(ledger.get("started_at"))
    ends_at = _parse_timestamp(ledger.get("ends_at"))
    if started_at is None or ends_at is None or started_at >= ends_at:
        raise ValueError("paper submission lease timestamps are malformed")
    if now_timestamp < started_at:
        raise ValueError("paper submission lease has not started")
    if now_timestamp >= ends_at:
        raise ValueError("paper submission lease has expired")
    limit = ledger.get("authorized_market_day_limit")
    submitted_dates = ledger.get("submitted_market_dates")
    if (
        type(limit) is not int
        or not 1 <= limit <= 31
        or not isinstance(submitted_dates, list)
        or any(type(value) is not str for value in submitted_dates)
        or any(_submitted_market_date_is_malformed(value) for value in submitted_dates)
        or len(set(submitted_dates)) != len(submitted_dates)
        or len(submitted_dates) > limit
    ):
        raise ValueError("paper submission lease market-date ledger is malformed")
    active_submission_market_date = None
    if allow_submitting_transaction:
        transaction = ledger.get("submission_transaction")
        if isinstance(transaction, Mapping) and transaction.get("status") == "submitting":
            transaction_market_date = transaction.get("market_date")
            if type(transaction_market_date) is str and not _submitted_market_date_is_malformed(
                transaction_market_date
            ):
                active_submission_market_date = transaction_market_date
            else:
                raise ValueError("paper submission lease recovery is required for an incomplete transaction")
        elif transaction is not None:
            validate_submission_transaction_state(ledger)
    else:
        validate_submission_transaction_state(ledger)
    market_date = _central_market_date(now_timestamp)
    if market_date is None:
        raise ValueError("paper submission lease has no Central market date")
    if now_timestamp.astimezone(CENTRAL).weekday() >= 5:
        raise ValueError("paper submission lease requires a regular Central market date")
    list_calendar = getattr(paper_client, "list_calendar", None)
    if not callable(list_calendar):
        raise ValueError("paper submission lease cannot verify the broker market calendar")
    try:
        calendar = list_calendar(start=market_date, end=market_date)
    except Exception as exc:
        raise ValueError("paper submission lease broker calendar check failed") from exc
    if not isinstance(calendar, Sequence) or not any(
        isinstance(item, Mapping) and str(item.get("date", "")) == market_date
        for item in calendar
    ):
        raise ValueError("paper submission lease requires a regular Central market date")
    consuming_active_submission_date = active_submission_market_date == market_date
    if market_date in submitted_dates and not consuming_active_submission_date:
        raise ValueError("paper submission lease already used this Central market date")
    if len(submitted_dates) >= limit and not consuming_active_submission_date:
        raise ValueError("paper submission lease market-day capacity is exhausted")
    _validate_regular_paper_broker_clock(
        paper_client,
        now=now_timestamp,
        market_date=market_date,
    )
    return market_date


def validate_submission_lease(
    ledger: Mapping,
    *,
    paper_client: object,
    now: datetime.datetime,
) -> str:
    """Validate every condition required before a paper submission starts."""

    return _validate_submission_lease(
        ledger,
        paper_client=paper_client,
        now=now,
        allow_submitting_transaction=False,
    )


def validate_submission_runtime_boundary(
    ledger: Mapping,
    *,
    paper_client: object,
    now: datetime.datetime,
    expected_market_date: str,
) -> None:
    """Revalidate the exact paper submission boundary immediately before a POST."""

    market_date = _validate_submission_lease(
        ledger,
        paper_client=paper_client,
        now=now,
        allow_submitting_transaction=True,
    )
    if market_date != expected_market_date:
        raise ValueError("paper submission lease Central market date changed")


def _submitted_market_date_is_malformed(value: str) -> bool:
    try:
        return datetime.date.fromisoformat(value).isoformat() != value
    except ValueError:
        return True


def record_submitted_market_date(ledger: dict, market_date: str) -> None:
    """Consume one lease day only after at least one paper order was posted."""

    submitted_dates = ledger.get("submitted_market_dates")
    if not isinstance(submitted_dates, list) or market_date in submitted_dates:
        raise ValueError("paper submission lease market-date recording failed")
    submitted_dates.append(market_date)


def begin_submission_transaction(
    ledger: dict,
    *,
    market_date: str,
    payloads: Sequence[Mapping],
    now: datetime.datetime,
) -> None:
    """Persist the exact intended paper order identities before the first POST."""

    validate_submission_transaction_state(ledger)
    client_order_ids: list[str] = []
    for payload in payloads:
        strategy_id = payload.get("strategy_id")
        client_order_id = payload.get("client_order_id")
        if (
            strategy_id not in STRATEGY_IDS
            or type(client_order_id) is not str
            or _strategy_from_client_order_id(client_order_id) != strategy_id
            or client_order_id in client_order_ids
        ):
            raise ValueError("paper submission payload identities are malformed")
        client_order_ids.append(client_order_id)
    ledger["submission_transaction"] = {
        "status": "submitting",
        "market_date": market_date,
        "started_at": _iso(now),
        "pending_client_order_ids": client_order_ids,
        "successful_submissions": [],
    }


def _validate_paper_submission_response(payload: Mapping, response: object) -> dict:
    if not isinstance(response, Mapping):
        raise ValueError("paper submission response is not a mapping")
    normalized = dict(response)
    try:
        json.dumps(normalized, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("paper submission response is not durable JSON evidence") from exc
    client_order_id = payload.get("client_order_id")
    if normalized.get("client_order_id") != client_order_id:
        raise ValueError("paper submission response client order identity does not match request")
    if "strategy_id" in normalized and normalized["strategy_id"] != payload.get("strategy_id"):
        raise ValueError("paper submission response strategy identity does not match request")
    for field in (
        "symbol",
        "side",
        "type",
        "time_in_force",
        "limit_price",
        "notional",
        "extended_hours",
    ):
        if field in normalized and normalized[field] != payload.get(field):
            raise ValueError(f"paper submission response {field} does not match request")
    if type(normalized.get("id")) is not str or not normalized["id"]:
        raise ValueError("paper submission response has no broker order identity")
    if type(normalized.get("status")) is not str or not normalized["status"]:
        raise ValueError("paper submission response has no broker order status")
    return normalized


def record_submission_response(
    ledger: dict,
    *,
    payload: Mapping,
    response: object,
    market_date: str,
    now: datetime.datetime,
) -> dict:
    """Record one verified paper POST before the next POST may be attempted."""

    transaction = ledger.get("submission_transaction")
    if not isinstance(transaction, dict) or transaction.get("status") != "submitting":
        raise ValueError("paper submission transaction is not active")
    normalized = _validate_paper_submission_response(payload, response)
    client_order_id = str(payload["client_order_id"])
    pending = transaction.get("pending_client_order_ids")
    if not isinstance(pending, list) or client_order_id not in pending:
        raise ValueError("paper submission response has no pending request evidence")
    submitted = {
        "strategy_id": payload["strategy_id"],
        "reason": payload["reason"],
        **{
            key: value
            for key, value in payload.items()
            if key not in {"strategy_id", "reason"}
        },
        **normalized,
    }
    record_submitted_orders(ledger, [submitted], now=now)
    if market_date not in ledger.get("submitted_market_dates", []):
        record_submitted_market_date(ledger, market_date)
    successful = transaction.get("successful_submissions")
    if not isinstance(successful, list):
        raise ValueError("paper submission transaction evidence is malformed")
    successful.append(
        {
            "client_order_id": client_order_id,
            "market_date": market_date,
            "recorded_at": _iso(now),
            "response": normalized,
        }
    )
    pending.remove(client_order_id)
    return submitted


def complete_submission_transaction(ledger: dict, *, now: datetime.datetime) -> None:
    transaction = ledger.get("submission_transaction")
    if not isinstance(transaction, dict) or transaction.get("status") != "submitting":
        raise ValueError("paper submission transaction is not active")
    if transaction.get("pending_client_order_ids"):
        raise ValueError("paper submission transaction has unresolved requests")
    transaction["status"] = "completed"
    transaction["completed_at"] = _iso(now)


def mark_submission_recovery_required(ledger: dict, *, reason: str, now: datetime.datetime) -> None:
    """Seal an uncertain broker side effect so no same-ledger retry can duplicate it."""

    transaction = ledger.get("submission_transaction")
    if not isinstance(transaction, dict):
        transaction = {}
        ledger["submission_transaction"] = transaction
    transaction["status"] = SUBMISSION_WINDOW_RECOVERY_REQUIRED
    transaction["failed_at"] = _iso(now)
    transaction["failure_reason"] = reason[:500]
    ledger["submission_window_status"] = SUBMISSION_WINDOW_RECOVERY_REQUIRED


def finalize_submission_lease(
    ledger: dict,
    *,
    paper_client: object,
    paper_orders: Iterable[Mapping],
    now: datetime.datetime,
) -> dict:
    """Close a bounded lease after fully reconciling only tournament paper orders."""

    _validate_exact_paper_client(paper_client)
    if ledger.get("ledger_type") != QUALIFICATION_TRIAL_LEDGER_TYPE:
        raise ValueError("paper finalization has an unsupported ledger type")
    if ledger.get("submission_window_status") != SUBMISSION_WINDOW_OPEN:
        raise ValueError("paper submission lease is already closed or finalized")
    if ledger.get("submission_lease_evidence") != _submission_lease_evidence(ledger):
        raise ValueError("paper submission lease evidence does not match ledger")
    validate_submission_transaction_state(ledger)
    strategies = ledger.get("strategies")
    if not isinstance(strategies, Mapping) or not isinstance(paper_orders, list):
        raise ValueError("paper finalization has malformed order evidence")
    local_order_items: list[tuple[str, Mapping]] = []
    for strategy_id, strategy in strategies.items():
        if not isinstance(strategy, Mapping) or not isinstance(strategy.get("orders", []), list):
            raise ValueError("paper finalization has malformed local order evidence")
        for order in strategy.get("orders", []):
            if not isinstance(order, Mapping):
                continue
            client_order_id = order.get("client_order_id")
            if type(client_order_id) is not str or not client_order_id.startswith("ta-paperbot-"):
                continue
            if (
                _strategy_from_client_order_id(client_order_id) != strategy_id
                or any(
                    key not in order
                    for key in (
                        "id",
                        "status",
                        "symbol",
                        "side",
                        "type",
                        "notional",
                        "limit_price",
                        "submitted_at",
                        "reason",
                    )
                )
            ):
                raise ValueError("paper finalization has malformed local order evidence")
            local_order_items.append((client_order_id, order))
    local_orders = {client_order_id: order for client_order_id, order in local_order_items}
    if len(local_orders) != len(local_order_items):
        raise ValueError("paper finalization is incomplete because local order identities are duplicated")
    if any(not isinstance(order, Mapping) for order in paper_orders):
        raise ValueError("paper finalization has malformed broker order evidence")
    remote_orders = []
    for order in paper_orders:
        client_order_id = order.get("client_order_id")
        if type(client_order_id) is not str or not client_order_id.startswith("ta-paperbot-"):
            continue
        if (
            type(order.get("id")) is not str
            or not order.get("id")
            or type(order.get("status")) is not str
            or not order.get("status")
        ):
            raise ValueError("paper finalization has malformed broker order evidence")
        remote_orders.append(order)
    remote_by_client_id = {str(order["client_order_id"]): order for order in remote_orders}
    if len(remote_by_client_id) != len(remote_orders) or set(local_orders) != set(remote_by_client_id):
        raise ValueError("paper finalization is incomplete because tournament orders are ambiguous")
    for client_order_id, local_order in local_orders.items():
        remote_order = remote_by_client_id[client_order_id]
        if local_order.get("id") != remote_order.get("id"):
            raise ValueError("paper finalization is incomplete because order evidence does not match")
        for field in ("symbol", "side", "type"):
            if field in remote_order and local_order.get(field) != remote_order.get(field):
                raise ValueError("paper finalization is incomplete because order evidence does not match")
    terminal_statuses = {"filled", "canceled", "expired", "rejected"}
    unresolved = [
        client_order_id
        for client_order_id, order in remote_by_client_id.items()
        if str(order.get("status", "")).lower() not in terminal_statuses
    ]
    if unresolved:
        raise ValueError("paper finalization is incomplete because tournament orders remain open")
    reconcile_tournament_orders(ledger, remote_orders, now=now)
    finalized_at = _iso(now)
    ledger["submission_window_status"] = SUBMISSION_WINDOW_FINALIZED
    ledger["submission_finalization"] = {
        "finalized_at": finalized_at,
        "reconciled_order_count": len(remote_orders),
        "status": SUBMISSION_WINDOW_FINALIZED,
    }
    return dict(ledger["submission_finalization"])


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _unique_packet_path(output_path: Path, stem: str, suffix: str = ".json") -> Path:
    candidate = output_path / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = output_path / f"{stem}-{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique paper tournament packet path for {stem}{suffix}")


def _position_market_value(position: Mapping) -> Decimal:
    market_value = _as_decimal(position.get("market_value"))
    if market_value > 0:
        return market_value
    qty = _as_decimal(position.get("qty"))
    current_price = _as_decimal(position.get("current_price") or position.get("avg_entry_price"))
    return qty * current_price


def _position_current_price(position: Mapping) -> Decimal:
    current_price = _as_decimal(position.get("current_price"))
    if current_price > 0:
        return current_price
    qty = _as_decimal(position.get("qty"))
    market_value = _position_market_value(position)
    if qty > 0 and market_value > 0:
        return market_value / qty
    return _as_decimal(position.get("avg_entry_price"), "0")


def initialize_tournament(
    *,
    paper_account: Mapping,
    paper_positions: Sequence[Mapping],
    capital_per_strategy: Decimal,
    now: datetime.datetime | None = None,
    duration_days: int = 31,
    max_submission_market_days: int = 31,
) -> dict:
    if type(duration_days) is not int or not 1 <= duration_days <= 31:
        raise ValueError("duration_days must be an integer from 1 through 31")
    if type(max_submission_market_days) is not int or not 1 <= max_submission_market_days <= 31:
        raise ValueError("max_submission_market_days must be an integer from 1 through 31")
    now = now or _now()
    started_at = _iso(now)
    ends_at = _iso(now + datetime.timedelta(days=duration_days))
    capital = _as_decimal(capital_per_strategy)
    strategies = {}
    for strategy_id in STRATEGY_IDS:
        strategies[strategy_id] = {
            "strategy_id": strategy_id,
            "name": STRATEGY_DEFINITIONS[strategy_id]["name"],
            "description": STRATEGY_DEFINITIONS[strategy_id]["description"],
            "starting_capital": _money(capital),
            "cash": _money(capital),
            "baseline_imported_value": "0.00",
            "positions": {},
            "orders": [],
            "realized_pl": "0.00",
            "equity_history": [{"generated_at": started_at, "equity": _money(capital)}],
        }

    imported_value = Decimal("0")
    current_strategy = strategies[STRATEGY_CURRENT_AGGRESSIVE]
    for position in paper_positions:
        symbol = str(position.get("symbol", "")).upper()
        if not symbol:
            continue
        qty = _as_decimal(position.get("qty"))
        market_value = _position_market_value(position)
        current_price = _position_current_price(position)
        if qty <= 0 or market_value <= 0 or current_price <= 0:
            continue
        imported_value += market_value
        current_strategy["positions"][symbol] = {
            "symbol": symbol,
            "qty": str(qty.normalize()),
            "avg_entry_price": _price(current_price),
            "cost_basis": _money(market_value),
            "baseline_value": _money(market_value),
            "baseline_unrealized_pl": "0.00",
            "current_price": _price(current_price),
            "source": "imported_current_paper_position",
        }
    imported_value = sum(
        _as_decimal(position.get("cost_basis"))
        for position in current_strategy["positions"].values()
    )
    current_strategy["baseline_imported_value"] = _money(imported_value)
    current_strategy["cash"] = _money(max(Decimal("0"), capital - imported_value))

    ledger = {
        "version": 1,
        "ledger_type": QUALIFICATION_TRIAL_LEDGER_TYPE,
        "tournament_id": f"paper-tournament-{now.strftime('%Y%m%d-%H%M%S')}",
        "started_at": started_at,
        "ends_at": ends_at,
        "authorized_market_day_limit": max_submission_market_days,
        "submitted_market_dates": [],
        "submission_window_status": SUBMISSION_WINDOW_OPEN,
        "capital_per_strategy": _money(capital),
        "paper_account_baseline": {
            "status": paper_account.get("status"),
            "equity": str(paper_account.get("equity", "")),
            "buying_power": str(paper_account.get("buying_power", "")),
            "portfolio_value": str(paper_account.get("portfolio_value", "")),
        },
        "strategies": strategies,
        "live_strategy_selection": {
            "status": "pending",
            "strategy_id": None,
            "reason": "not enough tournament evidence yet",
        },
    }
    ledger["submission_lease_evidence"] = _submission_lease_evidence(ledger)
    return ledger


def compact_tournament_ledger_payload(
    ledger: Mapping,
    *,
    raw_packet_path: str | Path | None = None,
) -> dict:
    """Return the small scoreboard morning/n8n contexts need from the ledger."""

    latest_report = ledger.get("latest_report") if isinstance(ledger.get("latest_report"), Mapping) else {}
    rankings = latest_report.get("rankings") if isinstance(latest_report, Mapping) else []
    if not isinstance(rankings, list):
        rankings = []
    candidate = latest_report.get("live_strategy_candidate") if isinstance(latest_report, Mapping) else {}
    if not isinstance(candidate, Mapping):
        candidate = ledger.get("live_strategy_selection") if isinstance(ledger.get("live_strategy_selection"), Mapping) else {}
    selection = ledger.get("live_strategy_selection") if isinstance(ledger.get("live_strategy_selection"), Mapping) else {}
    strategies = ledger.get("strategies") if isinstance(ledger.get("strategies"), Mapping) else {}
    baseline = ledger.get("paper_account_baseline") if isinstance(ledger.get("paper_account_baseline"), Mapping) else {}
    alphainsider = (
        ledger.get("alphainsider_paper_watch_plan")
        if isinstance(ledger.get("alphainsider_paper_watch_plan"), Mapping)
        else {}
    )

    compact_rankings = []
    for item in rankings[:5]:
        if not isinstance(item, Mapping):
            continue
        compact_rankings.append(
            {
                "strategy_id": item.get("strategy_id"),
                "name": item.get("name"),
                "equity": item.get("equity"),
                "total_return": item.get("total_return"),
                "total_return_pct": item.get("total_return_pct"),
                "max_drawdown_pct": item.get("max_drawdown_pct"),
                "win_rate_pct": item.get("win_rate_pct"),
                "tracked_days": item.get("tracked_days"),
            }
        )

    compact: dict[str, object] = {
        "schema": "compact_paper_tournament_ledger_v1",
        "analysis_only": True,
        "paper_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "raw_packet_path": str(raw_packet_path) if raw_packet_path is not None else None,
        "generated_at": latest_report.get("generated_at") if isinstance(latest_report, Mapping) else None,
        "tournament_id": ledger.get("tournament_id"),
        "started_at": ledger.get("started_at"),
        "ends_at": ledger.get("ends_at"),
        "capital_per_strategy": ledger.get("capital_per_strategy"),
        "strategy_count": len(strategies),
        "paper_account_baseline": {
            "status": baseline.get("status"),
            "equity": baseline.get("equity"),
            "buying_power": baseline.get("buying_power"),
            "portfolio_value": baseline.get("portfolio_value"),
        },
        "latest_report": {
            "generated_at": latest_report.get("generated_at") if isinstance(latest_report, Mapping) else None,
            "rankings": compact_rankings,
            "ranking_count": len(rankings),
            "live_strategy_candidate": {
                "status": candidate.get("status") if isinstance(candidate, Mapping) else None,
                "strategy_id": candidate.get("strategy_id") if isinstance(candidate, Mapping) else None,
                "reason": candidate.get("reason") if isinstance(candidate, Mapping) else None,
            },
        },
        "live_strategy_selection": {
            "status": selection.get("status"),
            "strategy_id": selection.get("strategy_id"),
            "reason": selection.get("reason"),
        },
        "alphainsider_paper_watch": {
            "mode": alphainsider.get("paper_shadow_mode"),
            "watch_item_count": len(alphainsider.get("watch_items") or [])
            if isinstance(alphainsider.get("watch_items"), list)
            else 0,
            "shadow_order_count": alphainsider.get("shadow_order_count"),
            "paper_shadow_spend_usd": alphainsider.get("paper_shadow_spend_usd"),
            "execution_authority": alphainsider.get("execution_authority"),
        },
        "next_open": (
            "Open the raw paper tournament ledger only when the candidate changes, "
            "paper orders submit, a strategy leader changes, or AlphaInsider watch status changes."
        ),
    }
    return compact


def write_tournament_ledger(ledger: Mapping, output_dir: str | Path) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    ledger_path = path / LEDGER_FILE
    ledger_text = json.dumps(ledger, indent=2)
    _atomic_write_text(ledger_path, ledger_text)
    _atomic_write_text(path / "latest.json", ledger_text)
    compact = compact_tournament_ledger_payload(ledger, raw_packet_path=ledger_path)
    compact_text = json.dumps(compact, indent=2)
    _atomic_write_text(path / COMPACT_LEDGER_FILE, compact_text)
    _atomic_write_text(path / "latest-compact.json", compact_text)
    return ledger_path


def load_tournament_ledger(log_dir: str | Path) -> dict:
    ledger_path = Path(log_dir) / LEDGER_FILE
    if not ledger_path.exists():
        raise FileNotFoundError(f"paper tournament ledger not found: {ledger_path}")
    return json.loads(ledger_path.read_text(encoding="utf-8"))


def _current_price(symbol: str, position: Mapping, market_data: Mapping[str, Mapping]) -> Decimal:
    data = market_data.get(symbol.upper()) or {}
    price = _as_decimal(data.get("current_price") or data.get("price"))
    if price > 0:
        return price
    return _as_decimal(position.get("current_price") or position.get("avg_entry_price"), "0")


def strategy_position_value(strategy: Mapping, market_data: Mapping[str, Mapping]) -> Decimal:
    value = Decimal("0")
    for symbol, position in (strategy.get("positions") or {}).items():
        if not market_data and position.get("source") == "imported_current_paper_position":
            value += _as_decimal(position.get("cost_basis"))
            continue
        qty = _as_decimal(position.get("qty"))
        price = _current_price(symbol, position, market_data)
        value += qty * price
    return value


def strategy_open_order_reserve(strategy: Mapping) -> Decimal:
    reserve = Decimal("0")
    for order in strategy.get("orders") or []:
        status = str(order.get("status", "")).lower()
        side = str(order.get("side", "")).lower()
        if side == "buy" and status not in {"filled", "canceled", "expired", "rejected"}:
            reserve += _as_decimal(order.get("notional"))
    return reserve


def strategy_available_cash(strategy: Mapping) -> Decimal:
    return max(Decimal("0"), _as_decimal(strategy.get("cash")) - strategy_open_order_reserve(strategy))


def tournament_reserved_budget(
    ledger: Mapping | None = None,
    *,
    fallback_reserved_budget: Decimal = DEFAULT_TOURNAMENT_RESERVED_BUDGET,
) -> Decimal:
    if not ledger:
        return fallback_reserved_budget
    total = Decimal("0")
    strategies = ledger.get("strategies") or {}
    for strategy_id in STRATEGY_IDS:
        strategy = strategies.get(strategy_id) or {}
        total += _as_decimal(strategy.get("starting_capital"))
    return total if total > 0 else fallback_reserved_budget


def remaining_paper_budget_after_tournament(
    paper_account: Mapping,
    *,
    ledger: Mapping | None = None,
    reserved_budget: Decimal | None = None,
) -> Decimal:
    reserve = _as_decimal(reserved_budget) if reserved_budget is not None else tournament_reserved_budget(ledger)
    buying_power = _as_decimal(paper_account.get("buying_power") or paper_account.get("equity"))
    return max(Decimal("0"), buying_power - reserve).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _normalize_shadow_symbol(value: object) -> str | None:
    raw = str(value or "").strip().upper().lstrip("$")
    if not raw:
        return None
    symbol = "".join(ch for ch in raw if ch.isalnum() or ch in {".", "-"})
    if not symbol or len(symbol) > 12:
        return None
    return symbol


def _alphainsider_strategy_symbols(strategy: Mapping) -> list[str]:
    symbols: list[str] = []

    def add_symbol(value: object) -> None:
        symbol = _normalize_shadow_symbol(value)
        if symbol and symbol not in symbols:
            symbols.append(symbol)

    for key in (
        "symbols",
        "tickers",
        "ticker_mentions",
        "recommended_symbols",
        "holdings",
        "positions",
        "allocations",
    ):
        value = strategy.get(key)
        if isinstance(value, str):
            for item in value.replace(";", ",").split(","):
                add_symbol(item)
        elif isinstance(value, Mapping):
            add_symbol(value.get("symbol") or value.get("ticker"))
            for item in value.values():
                if isinstance(item, Mapping):
                    add_symbol(item.get("symbol") or item.get("ticker"))
        elif isinstance(value, Sequence):
            for item in value:
                if isinstance(item, Mapping):
                    add_symbol(item.get("symbol") or item.get("ticker"))
                else:
                    add_symbol(item)
    return symbols


def build_alphainsider_paper_watch_plan(
    *,
    paper_account: Mapping,
    recommended_strategies: Sequence[Mapping] | None = None,
    ledger: Mapping | None = None,
    reserved_budget: Decimal | None = None,
    max_strategies: int = 5,
    max_allocation_per_strategy: Decimal = Decimal("2000"),
    fetch_status: str = "not_requested",
    fetch_reason: str = "",
    env_status: Mapping | None = None,
    now: datetime.datetime | None = None,
) -> dict:
    now = now or _now()
    reserve = _as_decimal(reserved_budget) if reserved_budget is not None else tournament_reserved_budget(ledger)
    available = remaining_paper_budget_after_tournament(
        paper_account,
        ledger=ledger,
        reserved_budget=reserve,
    )
    selected = list(recommended_strategies or [])[: max(0, int(max_strategies))]
    allocation = Decimal("0")
    if selected and available > 0:
        allocation = min(
            _as_decimal(max_allocation_per_strategy),
            (available / Decimal(len(selected))).quantize(Decimal("0.01"), rounding=ROUND_DOWN),
        )
    watch_items = []
    paper_shadow_orders = []
    paper_shadow_spend = Decimal("0")
    for index, strategy in enumerate(selected, start=1):
        strategy_id = str(
            strategy.get("strategy_id")
            or strategy.get("id")
            or strategy.get("_id")
            or strategy.get("uuid")
            or ""
        )
        symbols = _alphainsider_strategy_symbols(strategy)
        if not strategy_id:
            shadow_status = "missing_strategy_id"
        elif allocation <= 0:
            shadow_status = "no_shadow_budget"
        elif not symbols:
            shadow_status = "needs_strategy_tickers"
        else:
            shadow_status = "shadow_orders_ready"
            per_symbol = (allocation / Decimal(len(symbols))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if per_symbol > 0:
                for symbol in symbols:
                    paper_shadow_spend += per_symbol
                    paper_shadow_orders.append(
                        {
                            "paper_watch_strategy_id": ALPHAINSIDER_PAPER_WATCH_ID,
                            "alphainsider_strategy_id": strategy_id,
                            "source_strategy_rank": index,
                            "source_strategy_name": str(
                                strategy.get("name") or strategy.get("title") or "unnamed strategy"
                            )[:160],
                            "symbol": symbol,
                            "side": "buy",
                            "type": "paper_shadow_allocation",
                            "notional": _money(per_symbol),
                            "status": "shadow_only",
                            "execution_authority": "none",
                            "broker_submission_ready": False,
                            "reason": (
                                "AlphaInsider popular-strategy paper emulation; "
                                "comparison signal only, not trade truth."
                            ),
                        }
                    )
        watch_items.append(
            {
                "rank": index,
                "strategy_id": strategy_id,
                "name": str(strategy.get("name") or strategy.get("title") or "unnamed strategy")[:160],
                "type": str(strategy.get("type") or strategy.get("strategy_type") or "unknown"),
                "proposed_paper_allocation_usd": _money(allocation),
                "action": "watch_only",
                "status": "missing_strategy_id" if not strategy_id else "ready_for_paper_shadow",
                "shadow_status": shadow_status,
                "shadow_symbols": symbols,
            }
        )
    return {
        "kind": "alphainsider_paper_watch_plan",
        "generated_at": _iso(now),
        "strategy_id": ALPHAINSIDER_PAPER_WATCH_ID,
        "name": ALPHAINSIDER_PAPER_WATCH_DEFINITION["name"],
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "forbidden_effects": [
            "submit_live_order",
            "submit_alphainsider_order",
            "submit_paper_order",
            "start_bot",
            "guess_strategy_id",
            "guess_bot_id",
            "waive_live_gate",
        ],
        "paper_account": {
            "status": paper_account.get("status"),
            "buying_power": str(paper_account.get("buying_power", "")),
            "equity": str(paper_account.get("equity", "")),
            "portfolio_value": str(paper_account.get("portfolio_value", "")),
        },
        "reserved_tournament_budget_usd": _money(reserve),
        "available_shadow_budget_usd": _money(available),
        "max_allocation_per_strategy_usd": _money(max_allocation_per_strategy),
        "strategy_count": len(selected),
        "watch_items": watch_items,
        "paper_shadow_mode": "paper_strategy_emulation",
        "paper_shadow_spend_usd": _money(paper_shadow_spend),
        "shadow_order_count": len(paper_shadow_orders),
        "paper_shadow_orders": paper_shadow_orders,
        "fetch_status": fetch_status,
        "fetch_reason": fetch_reason,
        "alphainsider_env_status": dict(env_status or {}),
        "notes": [
            "Uses only paper buying power left after the existing tournament reserve.",
            "AlphaInsider data is a comparison source, not trade truth.",
            "Paper-shadow orders are fake emulation records until a separate paper-submit gate is built.",
            "No AlphaInsider, Alpaca paper, or Alpaca live order is submitted by this plan.",
        ],
    }


def strategy_equity(strategy: Mapping, market_data: Mapping[str, Mapping]) -> Decimal:
    return _as_decimal(strategy.get("cash")) + strategy_position_value(strategy, market_data)


def _max_drawdown(equity_history: Sequence[Mapping]) -> Decimal:
    peak = Decimal("0")
    worst = Decimal("0")
    for item in equity_history:
        equity = _as_decimal(item.get("equity"))
        if equity > peak:
            peak = equity
        if peak > 0:
            drawdown = (equity - peak) / peak
            if drawdown < worst:
                worst = drawdown
    return worst


def _position_win_rate_pct(strategy: Mapping, market_data: Mapping[str, Mapping]) -> str:
    if _tracked_days(strategy) <= 1:
        return "0.00"
    positions = [
        (symbol, position)
        for symbol, position in (strategy.get("positions") or {}).items()
        if _as_decimal(position.get("qty")) > 0
    ]
    if not positions:
        return "0.00"
    wins = 0
    for symbol, position in positions:
        current_value = (
            _as_decimal(position.get("cost_basis"))
            if not market_data and position.get("source") == "imported_current_paper_position"
            else _as_decimal(position.get("qty")) * _current_price(symbol, position, market_data)
        )
        if current_value > _as_decimal(position.get("cost_basis")):
            wins += 1
    return str((Decimal(wins) / Decimal(len(positions)) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _strategy_turnover(strategy: Mapping) -> Decimal:
    return sum(_as_decimal(order.get("notional")) for order in strategy.get("orders") or [])


def _tracked_days(strategy: Mapping) -> int:
    days = set()
    for item in strategy.get("equity_history") or []:
        try:
            days.add(datetime.datetime.fromisoformat(str(item.get("generated_at"))).date())
        except ValueError:
            continue
    return len(days)


def record_equity_snapshot(
    ledger: dict,
    *,
    market_data: Mapping[str, Mapping],
    now: datetime.datetime | None = None,
) -> None:
    now = now or _now()
    generated_at = _iso(now)
    for strategy in ledger.get("strategies", {}).values():
        equity = strategy_equity(strategy, market_data)
        history = strategy.setdefault("equity_history", [])
        if history and str(history[-1].get("generated_at")) == generated_at:
            history[-1]["equity"] = _money(equity)
        else:
            history.append({"generated_at": generated_at, "equity": _money(equity)})


def _scorecard_metrics_from_ranking(ranking: Mapping[str, object] | None) -> dict[str, object]:
    if not ranking:
        return {}
    keys = (
        "equity",
        "total_return",
        "total_return_pct",
        "max_drawdown_pct",
        "win_rate_pct",
        "turnover",
        "cash_usage_pct",
        "tracked_days",
    )
    return {key: ranking.get(key) for key in keys if key in ranking}


def build_popular_strategy_scorecards(ledger: Mapping, *, report: Mapping | None = None) -> list[dict]:
    """Return paper-only scorecards for popular strategy families.

    These scorecards make the experiments auditable. They do not submit orders or
    grant live authority; live mirroring still depends on the deterministic
    tournament promotion and Alpaca gates.
    """
    rankings = {
        str(item.get("strategy_id")): item
        for item in (report or {}).get("rankings", [])
        if isinstance(item, Mapping)
    }
    strategies = ledger.get("strategies") or {}
    live_candidate = (report or {}).get("live_strategy_candidate") or {}
    alpha_plan = ledger.get("alphainsider_paper_watch_plan") or {}
    scorecards: list[dict] = []
    for strategy_id, definition in POPULAR_STRATEGY_SCORECARD_DEFINITIONS.items():
        active_paper = strategy_id in strategies
        is_alpha = strategy_id == ALPHAINSIDER_PAPER_WATCH_ID
        if active_paper:
            status = "active_paper_sleeve"
            paper_metrics = _scorecard_metrics_from_ranking(rankings.get(strategy_id))
        elif is_alpha and alpha_plan:
            status = "paper_shadow_watch"
            paper_metrics = {
                "strategy_count": alpha_plan.get("strategy_count", 0),
                "available_shadow_budget_usd": alpha_plan.get("available_shadow_budget_usd", "0.00"),
                "paper_shadow_spend_usd": alpha_plan.get("paper_shadow_spend_usd", "0.00"),
                "shadow_order_count": alpha_plan.get("shadow_order_count", 0),
            }
        else:
            status = str(definition.get("status_when_missing", "planned_paper_sleeve"))
            paper_metrics = {}

        promoted_by_tournament = (
            active_paper
            and live_candidate.get("status") == "candidate"
            and live_candidate.get("strategy_id") == strategy_id
        )
        scorecards.append(
            {
                "strategy_id": strategy_id,
                "name": definition["name"],
                "status": status,
                "setup_type": definition["setup_type"],
                "thesis": definition["thesis"],
                "paper_only": True,
                "analysis_only": True,
                "execution_authority": "none",
                "forbidden_effects": [
                    "submit_live_order",
                    "submit_paper_order_without_tournament_gate",
                    "promote_live_strategy_without_report_candidate",
                    "waive_live_gate",
                ],
                "paper_metrics": paper_metrics,
                "pass_criteria": list(definition["pass_criteria"]),
                "fail_criteria": list(definition["fail_criteria"]),
                "rotation_schedule": definition.get("rotation_schedule"),
                "live_mirror_allowed": bool(promoted_by_tournament),
                "live_mirror_policy": (
                    "Only after this scorecard is the live_strategy_candidate and the deterministic Alpaca live gate passes."
                ),
            }
        )
    return scorecards


def build_tournament_report(
    ledger: Mapping,
    *,
    market_data: Mapping[str, Mapping],
    now: datetime.datetime | None = None,
    min_promotion_days: int = 5,
) -> dict:
    now = now or _now()
    rankings = []
    for strategy_id, strategy in ledger.get("strategies", {}).items():
        equity = strategy_equity(strategy, market_data)
        if not market_data and strategy.get("equity_history"):
            equity = _as_decimal(strategy["equity_history"][-1].get("equity"))
        start = _as_decimal(strategy.get("starting_capital"))
        total_return = equity - start
        total_return_pct = Decimal("0") if start <= 0 else total_return / start
        rankings.append(
            {
                "strategy_id": strategy_id,
                "name": strategy.get("name"),
                "equity": _money(equity),
                "cash": _money(strategy.get("cash")),
                "position_value": _money(strategy_position_value(strategy, market_data)),
                "open_order_reserve": _money(strategy_open_order_reserve(strategy)),
                "realized_pl": _money(strategy.get("realized_pl")),
                "total_return": _money(total_return),
                "total_return_pct": str((total_return_pct * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                "max_drawdown_pct": str((_max_drawdown(strategy.get("equity_history") or []) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                "win_rate_pct": _position_win_rate_pct(strategy, market_data),
                "turnover": _money(_strategy_turnover(strategy)),
                "cash_usage_pct": str(((Decimal("1") - (_as_decimal(strategy.get("cash")) / start)) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if start > 0 else Decimal("0.00")),
                "tracked_days": _tracked_days(strategy),
                "open_orders": [
                    order for order in strategy.get("orders", [])
                    if str(order.get("status", "")).lower() not in {"filled", "canceled", "expired", "rejected"}
                ],
            }
        )
    rankings.sort(
        key=lambda item: (
            _as_decimal(item["total_return"]),
            _as_decimal(item["max_drawdown_pct"]),
        ),
        reverse=True,
    )
    top = rankings[0] if rankings else None
    tournament_expired = _tournament_expired(ledger.get("ends_at"), now=now)
    if tournament_expired:
        live_candidate = {
            "status": "expired",
            "strategy_id": top["strategy_id"] if top else None,
            "reason": "tournament ended before this report; strategy is not eligible for selection",
        }
    elif top and top["tracked_days"] >= min_promotion_days and _as_decimal(top["total_return"]) > 0:
        live_candidate = {
            "status": "candidate",
            "strategy_id": top["strategy_id"],
            "reason": f"best positive paper strategy after {top['tracked_days']} tracked day(s)",
        }
    else:
        live_candidate = {
            "status": "pending",
            "strategy_id": top["strategy_id"] if top else None,
            "reason": f"need at least {min_promotion_days} tracked days and a positive winner",
        }
    report = {
        "generated_at": _iso(now),
        "ledger_type": ledger.get("ledger_type"),
        "tournament_id": ledger.get("tournament_id"),
        "started_at": ledger.get("started_at"),
        "ends_at": ledger.get("ends_at"),
        "capital_per_strategy": ledger.get("capital_per_strategy"),
        "rankings": rankings,
        "live_strategy_candidate": live_candidate,
    }
    report["popular_strategy_scorecards"] = build_popular_strategy_scorecards(ledger, report=report)
    return report


def _symbols_held(strategy: Mapping) -> set[str]:
    return {
        symbol.upper()
        for symbol, position in (strategy.get("positions") or {}).items()
        if _as_decimal(position.get("qty")) > 0
    }


def _buy_limit(price: Decimal, *, extended_hours: bool) -> Decimal:
    buffer = Decimal("1.003") if extended_hours else Decimal("1.002")
    return (price * buffer).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _action_notional(strategy: Mapping, preferred: Decimal) -> Decimal:
    available = strategy_available_cash(strategy)
    if available < Decimal("100"):
        return Decimal("0")
    return min(preferred, available).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def build_tournament_actions(
    ledger: Mapping,
    *,
    candidate_signals: Sequence[CandidateSignal],
    market_session: str,
    strategy_ids: Sequence[str] | None = None,
) -> list[TournamentAction]:
    if market_session not in {"pre_open", "open_window", "regular", "pre_close"}:
        return []
    selected = list(strategy_ids or STRATEGY_IDS)
    strategies = ledger.get("strategies", {})
    actions: list[TournamentAction] = []
    extended_hours = market_session == "pre_open"

    if STRATEGY_CURRENT_AGGRESSIVE in selected:
        strategy = strategies[STRATEGY_CURRENT_AGGRESSIVE]
        held = _symbols_held(strategy)
        best = next(
            (
                signal for signal in candidate_signals
                if signal.symbol not in held and signal.score >= Decimal("0.70")
            ),
            None,
        )
        notional = _action_notional(strategy, Decimal("2000"))
        if best and notional > 0:
            actions.append(
                TournamentAction(
                    strategy_id=STRATEGY_CURRENT_AGGRESSIVE,
                    action="buy",
                    symbol=best.symbol,
                    side="buy",
                    notional=notional,
                    limit_price=_buy_limit(best.current_price, extended_hours=extended_hours),
                    reason=f"aggressive top ranked candidate: {best.reason}",
                    extended_hours=extended_hours,
                )
            )

    if STRATEGY_PULLBACK_SUPPORT in selected:
        strategy = strategies[STRATEGY_PULLBACK_SUPPORT]
        held = _symbols_held(strategy)
        pullbacks = [
            signal for signal in candidate_signals
            if signal.symbol not in held
            and Decimal("-0.025") <= signal.day_change_pct <= Decimal("-0.003")
            and signal.volume_ratio <= Decimal("2.5")
        ]
        pullbacks.sort(key=lambda signal: (signal.volume_ratio, -abs(signal.day_change_pct)), reverse=True)
        notional = _action_notional(strategy, Decimal("1500"))
        if pullbacks and notional > 0:
            best = pullbacks[0]
            actions.append(
                TournamentAction(
                    strategy_id=STRATEGY_PULLBACK_SUPPORT,
                    action="buy",
                    symbol=best.symbol,
                    side="buy",
                    notional=notional,
                    limit_price=_buy_limit(best.current_price, extended_hours=extended_hours),
                    reason=f"disciplined pullback setup: {best.reason}",
                    extended_hours=extended_hours,
                )
            )

    if STRATEGY_CATALYST_ROTATION in selected:
        strategy = strategies[STRATEGY_CATALYST_ROTATION]
        held = _symbols_held(strategy)
        catalysts = [
            signal for signal in candidate_signals
            if signal.symbol not in held and signal.time_sensitive and signal.score >= Decimal("0.65")
        ]
        notional = _action_notional(strategy, Decimal("2000"))
        if catalysts and notional > 0:
            best = catalysts[0]
            actions.append(
                TournamentAction(
                    strategy_id=STRATEGY_CATALYST_ROTATION,
                    action="buy",
                    symbol=best.symbol,
                    side="buy",
                    notional=notional,
                    limit_price=_buy_limit(best.current_price, extended_hours=extended_hours),
                    reason=f"time-sensitive catalyst/relative-strength setup: {best.reason}",
                    extended_hours=extended_hours,
                )
            )

    return actions


def _client_order_id(action: TournamentAction, *, now: datetime.datetime, index: int) -> str:
    prefix = _STRATEGY_CLIENT_PREFIX[action.strategy_id]
    raw = f"ta-paperbot-{prefix}-{now.strftime('%y%m%d%H%M')}-{index}-{action.symbol.lower()}"
    return raw[:48]


def build_tournament_order_payloads(
    actions: Sequence[TournamentAction],
    *,
    now: datetime.datetime | None = None,
) -> list[dict]:
    now = now or _now()
    payloads = []
    for index, action in enumerate(actions, start=1):
        payloads.append(
            {
                "strategy_id": action.strategy_id,
                "symbol": action.symbol.upper(),
                "side": action.side.lower(),
                "type": "limit",
                "time_in_force": "day",
                "limit_price": _price(action.limit_price),
                "notional": _money(action.notional),
                "extended_hours": bool(action.extended_hours),
                "client_order_id": _client_order_id(action, now=now, index=index),
                "reason": action.reason,
            }
        )
    return payloads


def record_submitted_orders(ledger: dict, submitted_orders: Sequence[Mapping], *, now: datetime.datetime | None = None) -> None:
    now = now or _now()
    recorded_at = _iso(now)
    strategies = ledger.get("strategies", {})
    for order in submitted_orders:
        strategy_id = str(order.get("strategy_id") or _strategy_from_client_order_id(order.get("client_order_id")))
        if strategy_id not in strategies:
            continue
        strategies[strategy_id].setdefault("orders", []).append(
            {
                "client_order_id": str(order.get("client_order_id", "")),
                "id": str(order.get("id", "")),
                "symbol": str(order.get("symbol", "")).upper(),
                "side": str(order.get("side", "")),
                "type": str(order.get("type", "")),
                "status": str(order.get("status", "submitted")),
                "notional": _money(order.get("notional")),
                "limit_price": _price(order.get("limit_price")),
                "filled_qty": str(order.get("filled_qty", "0") or "0"),
                "filled_avg_price": str(order.get("filled_avg_price", "") or ""),
                "applied_filled_qty": "0",
                "submitted_at": recorded_at,
                "reason": str(order.get("reason", "")),
            }
        )


def _strategy_from_client_order_id(client_order_id: object) -> str | None:
    raw = str(client_order_id or "")
    if raw.startswith("ta-paperbot-current-aggressive"):
        return STRATEGY_CURRENT_AGGRESSIVE
    if raw.startswith("ta-paperbot-pullback-support"):
        return STRATEGY_PULLBACK_SUPPORT
    if raw.startswith("ta-paperbot-catalyst"):
        return STRATEGY_CATALYST_ROTATION
    return None


def reconcile_tournament_orders(
    ledger: dict,
    alpaca_orders: Iterable[Mapping],
    *,
    now: datetime.datetime | None = None,
) -> None:
    now = now or _now()
    order_by_client_id = {
        str(order.get("client_order_id", "")): order
        for order in alpaca_orders
        if str(order.get("client_order_id", "")).startswith("ta-paperbot-")
    }
    for strategy in ledger.get("strategies", {}).values():
        for local_order in strategy.get("orders") or []:
            client_order_id = local_order.get("client_order_id")
            if client_order_id not in order_by_client_id:
                continue
            remote = order_by_client_id[client_order_id]
            local_order["status"] = str(remote.get("status", local_order.get("status", "")))
            local_order["id"] = str(remote.get("id", local_order.get("id", "")))
            local_order["filled_qty"] = str(remote.get("filled_qty", local_order.get("filled_qty", "0")) or "0")
            local_order["filled_avg_price"] = str(remote.get("filled_avg_price", local_order.get("filled_avg_price", "")) or "")
            _apply_new_fill(strategy, local_order, now=now)


def _apply_new_fill(strategy: dict, order: dict, *, now: datetime.datetime) -> None:
    filled_qty = _as_decimal(order.get("filled_qty"))
    applied_qty = _as_decimal(order.get("applied_filled_qty"))
    delta_qty = filled_qty - applied_qty
    if delta_qty <= 0:
        return
    price = _as_decimal(order.get("filled_avg_price") or order.get("limit_price"))
    if price <= 0:
        return
    symbol = str(order.get("symbol", "")).upper()
    side = str(order.get("side", "")).lower()
    value = delta_qty * price
    positions = strategy.setdefault("positions", {})
    if side == "buy":
        existing = positions.get(symbol, {})
        existing_qty = _as_decimal(existing.get("qty"))
        existing_cost = _as_decimal(existing.get("cost_basis"))
        new_qty = existing_qty + delta_qty
        new_cost = existing_cost + value
        positions[symbol] = {
            "symbol": symbol,
            "qty": str(new_qty.normalize()),
            "avg_entry_price": _price(new_cost / new_qty if new_qty > 0 else price),
            "cost_basis": _money(new_cost),
            "baseline_value": existing.get("baseline_value", "0.00"),
            "baseline_unrealized_pl": existing.get("baseline_unrealized_pl", "0.00"),
            "current_price": _price(price),
            "source": existing.get("source", "tournament_order"),
        }
        strategy["cash"] = _money(_as_decimal(strategy.get("cash")) - value)
    order["applied_filled_qty"] = str(filled_qty.normalize())
    order["last_reconciled_at"] = _iso(now)


def write_tournament_packet(packet: Mapping, output_dir: str | Path, *, prefix: str) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S-%f")
    packet_path = _unique_packet_path(path, f"{prefix}-{timestamp}")
    _atomic_write_text(packet_path, json.dumps(packet, indent=2))
    return packet_path


def _report_sha256(report: Mapping) -> str | None:
    try:
        canonical = json.dumps(
            report,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (OverflowError, TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _selection_source_for_report(report: Mapping) -> dict | None:
    candidate = report.get("live_strategy_candidate")
    tournament_id = report.get("tournament_id")
    started_at = _parse_timestamp(report.get("started_at"))
    generated_at = _parse_timestamp(report.get("generated_at"))
    ends_at = _parse_timestamp(report.get("ends_at"))
    if (
        not isinstance(candidate, Mapping)
        or candidate.get("status") != "candidate"
        or candidate.get("strategy_id") not in STRATEGY_IDS
        or not isinstance(tournament_id, str)
        or not tournament_id
        or started_at is None
        or generated_at is None
        or ends_at is None
        or started_at > generated_at
        or generated_at >= ends_at
    ):
        return None
    report_sha256 = _report_sha256(report)
    if report_sha256 is None:
        return None
    return {
        "tournament_id": tournament_id,
        "report_generated_at": _iso(generated_at),
        "ends_at": _iso(ends_at),
        "candidate_status": "candidate",
        "candidate_strategy_id": candidate["strategy_id"],
        "report_sha256": report_sha256,
        "ledger_identity": {
            "tournament_id": tournament_id,
            "started_at": _iso(started_at),
            "ends_at": _iso(ends_at),
        },
    }


def maybe_write_live_strategy_selection(
    report: Mapping,
    output_dir: str | Path,
    *,
    now: datetime.datetime | None = None,
) -> Path | None:
    if remove_trial_live_strategy_selection(report, output_dir):
        return None
    path = Path(output_dir)
    selection_path = path / LIVE_SELECTION_FILE
    candidate = report.get("live_strategy_candidate") or {}
    if candidate.get("status") != "candidate" or not candidate.get("strategy_id"):
        return None
    now = now or _now()
    now_timestamp = _normalize_timestamp(now)
    source_report = _selection_source_for_report(report)
    if (
        now_timestamp is None
        or source_report is None
        or _tournament_expired(report.get("ends_at"), now=now)
    ):
        return None
    report_generated_at = _parse_timestamp(source_report["report_generated_at"])
    ends_at = _parse_timestamp(source_report["ends_at"])
    if (
        report_generated_at is None
        or ends_at is None
        or now_timestamp < report_generated_at
        or now_timestamp >= ends_at
    ):
        return None
    selection = {
        "schema_version": LIVE_SELECTION_SCHEMA_VERSION,
        "status": "active",
        "strategy_id": candidate["strategy_id"],
        "selected_at": _iso(now_timestamp),
        "reason": candidate.get("reason", ""),
        "source_report": source_report,
    }
    path.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    return selection_path


def remove_trial_live_strategy_selection(ledger_or_report: Mapping, output_dir: str | Path) -> bool:
    """Remove the selection target whenever a qualification trial owns this path."""

    if ledger_or_report.get("ledger_type") != QUALIFICATION_TRIAL_LEDGER_TYPE:
        return False
    (Path(output_dir) / LIVE_SELECTION_FILE).unlink(missing_ok=True)
    return True


def load_live_strategy_selection(
    log_dir: str | Path,
    *,
    now: datetime.datetime | None = None,
) -> dict | None:
    selection_path = Path(log_dir) / LIVE_SELECTION_FILE
    ledger_path = Path(log_dir) / LEDGER_FILE
    now_timestamp = _normalize_timestamp(now or _now())
    if now_timestamp is None:
        return None
    if not selection_path.exists():
        return None
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(selection, Mapping) or not isinstance(ledger, Mapping):
        return None
    if set(selection) != {
        "schema_version",
        "status",
        "strategy_id",
        "selected_at",
        "reason",
        "source_report",
    }:
        return None
    if (
        selection.get("schema_version") != LIVE_SELECTION_SCHEMA_VERSION
        or selection.get("status") != "active"
        or selection.get("strategy_id") not in STRATEGY_IDS
        or not isinstance(selection.get("reason"), str)
        or not isinstance(selection.get("source_report"), Mapping)
    ):
        return None
    source_report = selection["source_report"]
    authoritative_report = ledger.get("latest_report")
    if not isinstance(authoritative_report, Mapping):
        return None
    for field in ("tournament_id", "started_at", "ends_at"):
        ledger_value = ledger.get(field)
        report_value = authoritative_report.get(field)
        if not isinstance(ledger_value, str) or ledger_value != report_value:
            return None
    strategies = ledger.get("strategies")
    if not isinstance(strategies, Mapping):
        return None
    expected_source = _selection_source_for_report(authoritative_report)
    if expected_source is None or dict(source_report) != expected_source:
        return None
    if selection["strategy_id"] != source_report.get("candidate_strategy_id"):
        return None
    if source_report["candidate_strategy_id"] not in strategies:
        return None
    selected_at = _parse_timestamp(selection.get("selected_at"))
    report_generated_at = _parse_timestamp(source_report.get("report_generated_at"))
    ends_at = _parse_timestamp(source_report.get("ends_at"))
    if (
        selected_at is None
        or report_generated_at is None
        or ends_at is None
        or report_generated_at > selected_at
        or selected_at >= ends_at
        or selected_at > now_timestamp
        or now_timestamp >= ends_at
    ):
        return None
    return selection


def adapt_candidate_signals_for_live_strategy(
    strategy_id: str | None,
    candidate_signals: Sequence[CandidateSignal],
) -> list[CandidateSignal]:
    if strategy_id == STRATEGY_PULLBACK_SUPPORT:
        adjusted = []
        for signal in candidate_signals:
            if Decimal("-0.025") <= signal.day_change_pct <= Decimal("-0.003"):
                adjusted.append(
                    replace(
                        signal,
                        score=max(signal.score, Decimal("0.76")),
                        time_sensitive=True,
                        reason=f"live pullback winner profile: {signal.reason}",
                    )
                )
        return sorted(adjusted, key=lambda signal: signal.score, reverse=True)
    if strategy_id == STRATEGY_CATALYST_ROTATION:
        adjusted = []
        for signal in candidate_signals:
            if signal.time_sensitive or signal.volume_ratio >= Decimal("1.5"):
                adjusted.append(
                    replace(
                        signal,
                        score=max(signal.score, Decimal("0.76")),
                        time_sensitive=True,
                        reason=f"live catalyst winner profile: {signal.reason}",
                    )
                )
        return sorted(adjusted, key=lambda signal: signal.score, reverse=True)
    return list(candidate_signals)
