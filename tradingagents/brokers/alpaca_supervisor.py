"""Hourly Alpaca portfolio supervisor guardrails and reporting."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.brokers.alpaca import AlpacaExecutionConfig, OrderIssue
from tradingagents.brokers.supervisor.alert import (
    classify_supervisor_alert,
    render_supervisor_alert_email,
    should_throttle_supervisor_alert,
    supervisor_alert_fingerprint,
    supervisor_issue_category,
)
from tradingagents.brokers.supervisor.candidates import (
    AGGRESSIVE_CANDIDATE_UNIVERSE,
    CROWDED_AI_BETA_SYMBOLS,
    DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS,
    DEEP_RESEARCH_POSITIVE_RELATIVE_SYMBOLS,
    DEFAULT_LIVE_BUY_NOTIONAL,
    LIQUID_SP100_STYLE_UNIVERSE,
    MEGA_CAP_AI_UNIVERSE,
    MIN_LIVE_BUY_NOTIONAL,
    CandidateSignal,
    aggressive_limit_price,
    build_candidate_signals,
    choose_autonomous_live_buy_notional,
    is_buy_entry_candidate,
    is_chase_buy_candidate,
)
from tradingagents.brokers.supervisor.daily_report import render_daily_supervisor_report
from tradingagents.brokers.supervisor.hourly import (
    HourlyDecisionContext,
    build_buy_candidate_decision,
    build_hourly_decision_context,
    build_loss_review_decision,
    build_open_orders_review_decision,
    build_profit_take_decision,
    build_trailing_hold_decision,
    compact_hourly_supervisor_payload,
    find_latest_hourly_packet,
)
from tradingagents.brokers.supervisor.hourly import (
    build_hourly_decision as _build_hourly_decision,
)
from tradingagents.brokers.supervisor.hourly import (
    build_hourly_evidence as _build_hourly_evidence,
)
from tradingagents.brokers.supervisor.hourly import (
    serialize_hourly_decision as _serialize_hourly_decision,
)
from tradingagents.brokers.supervisor.hourly import (
    write_hourly_decision_packet as _write_hourly_decision_packet,
)
from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.brokers.supervisor.orders import (
    build_supervisor_order_payload,
    is_order_action,
    should_notify_supervisor,
)
from tradingagents.brokers.supervisor.overnight import (
    compact_overnight_plan_payload,
    load_latest_overnight_plan,
    render_overnight_plan_markdown,
    validate_overnight_plan_against_candidates,
    write_overnight_plan_packet,
)
from tradingagents.brokers.supervisor.premarket import (
    build_premarket_brief_packet,
    compact_premarket_brief_payload,
    is_expected_hourly_safety_lock,
    load_latest_premarket_brief,
    render_premarket_brief_markdown,
    validate_premarket_brief_against_candidates,
    write_premarket_brief_packet,
)
from tradingagents.brokers.supervisor.session import can_trade_session, market_session_label
from tradingagents.brokers.supervisor.sizing import (
    BASE_LIVE_CAP,
    MAX_DYNAMIC_LIVE_CAP,
    calculate_dynamic_live_cap,
    live_exposure_from_positions,
    total_unrealized_pl,
)
from tradingagents.brokers.supervisor.types import (
    HourlySupervisorAction,
    HourlySupervisorConfig,
    HourlySupervisorDecision,
)
from tradingagents.execution.authorized_normal_trade_intent import (
    AuthorizedNormalTradeIntent,
)
from tradingagents.execution.reconcile import (
    _claim_normal_live_submit_reconciliation,
    _owned_normal_live_broker_read,
    _refresh_normal_live_submit_reconciliation,
    _release_normal_live_submit_reconciliation,
    _revalidate_normal_live_submit_reconciliation,
    reconcile_normal_live_submit,
)
from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.live_control import live_control_lock, load_live_control_state
from tradingagents.policy.live_gate import evaluate_go_live_guard
from tradingagents.policy.order_rate_limit import (
    LiveOrderRateReservation,
    evaluate_order_rate_limit,
    normal_live_order_rate_reservation_lock,
    record_live_order_submission,
    release_live_order_reservation,
    reserve_live_order_submission,
)
from tradingagents.policy.risk_envelope import (
    load_risk_envelope,
    read_risk_envelope_bytes_locked,
    risk_envelope_lock,
)
from tradingagents.policy.strategy_promotion_sync import NormalLiveActivationReceipt

__all__ = [
    "AGGRESSIVE_CANDIDATE_UNIVERSE",
    "BASE_LIVE_CAP",
    "CROWDED_AI_BETA_SYMBOLS",
    "DEEP_RESEARCH_EVENT_SENSITIVE_SYMBOLS",
    "DEEP_RESEARCH_POSITIVE_RELATIVE_SYMBOLS",
    "DEFAULT_LIVE_BUY_NOTIONAL",
    "LIQUID_SP100_STYLE_UNIVERSE",
    "MEGA_CAP_AI_UNIVERSE",
    "MAX_DYNAMIC_LIVE_CAP",
    "MIN_LIVE_BUY_NOTIONAL",
    "CandidateSignal",
    "HourlyDecisionContext",
    "HourlySupervisorAction",
    "HourlySupervisorConfig",
    "HourlySupervisorDecision",
    "aggressive_limit_price",
    "build_candidate_signals",
    "build_buy_candidate_decision",
    "build_hourly_decision_context",
    "build_loss_review_decision",
    "build_open_orders_review_decision",
    "build_premarket_brief_packet",
    "build_profit_take_decision",
    "build_supervisor_order_payload",
    "build_trailing_hold_decision",
    "calculate_dynamic_live_cap",
    "can_trade_session",
    "choose_autonomous_live_buy_notional",
    "compact_hourly_supervisor_payload",
    "compact_overnight_plan_payload",
    "compact_premarket_brief_payload",
    "find_latest_hourly_packet",
    "is_buy_entry_candidate",
    "is_chase_buy_candidate",
    "is_expected_hourly_safety_lock",
    "is_order_action",
    "live_exposure_from_positions",
    "loss_exit_review_packet",
    "load_latest_overnight_plan",
    "load_latest_premarket_brief",
    "market_session_label",
    "render_daily_supervisor_report",
    "resolve_live_sleeve",
    "render_overnight_plan_markdown",
    "render_premarket_brief_markdown",
    "should_notify_supervisor",
    "submit_authorized_normal_live_order",
    "supervisor_issue_category",
    "total_unrealized_pl",
    "validate_overnight_plan_against_candidates",
    "validate_premarket_brief_against_candidates",
    "write_overnight_plan_packet",
    "write_premarket_brief_packet",
]

UTC = datetime.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
LIVE_AGGRESSIVE_SLEEVE = "current-aggressive"
DEFAULT_ALERT_THROTTLE_WINDOW = datetime.timedelta(hours=4)
_NORMAL_LIVE_ADMISSION_MAX_AGE_SECONDS = 60
_NORMAL_LIVE_RISK_METRICS_MAX_AGE_SECONDS = 30


@dataclass(frozen=True, slots=True)
class NormalLiveSubmitAdmission:
    """Opaque, process-local request to run the final normal-live checks."""

    intent_full_sha256: str
    issued_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class NormalLiveRiskMetrics:
    """Opaque, short-lived account-risk evidence for one normal-live order.

    The values are derived only from an owned Alpaca account snapshot and a
    pre-existing durable day baseline.  A lookalike dataclass has no authority:
    the in-process capability registry below retains the real issuance record.
    """

    intent_full_sha256: str
    order_payload_sha256: str
    account_snapshot_sha256: str
    daily_loss_usd: Decimal
    drawdown_pct: Decimal
    issued_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class _NormalLiveAdmissionContext:
    risk_envelope_path: Path
    promotion_state_path: Path
    control_state_path: Path
    order_rate_state_path: Path
    risk_metrics: NormalLiveRiskMetrics
    decision_evidence: dict[str, object]
    # Exact canonical risk-envelope binding captured from disk at successful
    # final-gate admission.  Carried through the durable commitment and the
    # raw-POST capability so the sole transport consumer can refuse unless a
    # fresh reread still hashes identically (TOCTOU defense).
    admitted_risk_envelope_ref: str
    admitted_risk_envelope_sha256: str
    # Owner-approval enforcement at the final gate.  A missing artifact
    # fails closed: the guard refuses any live order without a current,
    # signed account_owner approval bound to this exact order.  Trust anchor,
    # consumption ledger, and policy fingerprint resolve to canonical
    # protected runtime paths inside the loaded checkout.
    owner_approval: Mapping[str, object] | None = None
    # Independently signed risk_envelope_expansion artifact retained from
    # issuance; consumed by the final go-live guard only after every other
    # gate passes.  Structural preflight happened at issuance (consume=False).
    risk_envelope_expansion_approval: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class _NormalLiveAdmissionClaim:
    """Private lease retained only while the policy lock is held."""

    intent_full_sha256: str
    order_payload_sha256: str
    issued_at: str
    expires_at: str
    broker_read_adapter: object


_NORMAL_LIVE_ADMISSION_CAPABILITIES: dict[
    int, tuple[NormalLiveSubmitAdmission, _NormalLiveAdmissionContext]
] = {}
_NORMAL_LIVE_ADMISSION_CLAIMS: dict[
    int,
    tuple[
        _NormalLiveAdmissionClaim,
        _NormalLiveAdmissionContext,
        LiveOrderRateReservation | None,
    ],
] = {}
_NORMAL_LIVE_ADMISSION_RECONCILIATIONS: dict[int, object] = {}
_NORMAL_LIVE_RISK_METRICS_CAPABILITIES: dict[int, NormalLiveRiskMetrics] = {}
_NORMAL_LIVE_SUBMIT_POST_CAPABILITIES: dict[
    int,
    tuple[
        object,
        object,
        str,
        str,
        Path,
        dict[str, object],
        _NormalLiveAdmissionClaim,
        LiveOrderRateReservation,
    ],
] = {}


def _normal_live_admission_utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=UTC).replace(microsecond=0)


def _normal_live_admission_moment() -> datetime.datetime:
    current = _normal_live_admission_utc_now()
    if (
        type(current) is not datetime.datetime
        or current.tzinfo is None
        or current.utcoffset() is None
        or current.microsecond
    ):
        raise ValueError("normal live admission requires an aware whole-second clock")
    return current.astimezone(UTC)


def _normal_live_admission_lease_time(value: str, *, label: str) -> datetime.datetime:
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"normal live admission {label} is invalid") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.microsecond
    ):
        raise ValueError(f"normal live admission {label} is invalid")
    return parsed.astimezone(UTC)


def _require_normal_live_admission_lease_current(
    *, issued_at: str, expires_at: str
) -> None:
    issued = _normal_live_admission_lease_time(issued_at, label="issued_at")
    expires = _normal_live_admission_lease_time(expires_at, label="expires_at")
    if expires - issued != datetime.timedelta(seconds=_NORMAL_LIVE_ADMISSION_MAX_AGE_SECONDS):
        raise ValueError("normal live admission lease is invalid")
    current = _normal_live_admission_moment()
    if current < issued or current >= expires:
        raise ValueError("supervisor admission is stale")


def _normal_live_admission_path(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError(f"normal live admission {label} path must be absolute")
    return path


def _normal_live_admission_mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"normal live admission {label} must be a mapping")
    try:
        frozen = json.loads(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"normal live admission {label} must be JSON-safe") from exc
    if type(frozen) is not dict:
        raise ValueError(f"normal live admission {label} must be an object")
    return frozen


def _normal_live_admission_positions(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("normal live admission positions must be a sequence")
    return tuple(
        _normal_live_admission_mapping(position, label="position")
        for position in value
    )


def _normal_live_risk_metrics_state_path(control_state_path: str | Path) -> Path:
    """Return the deterministic durable day-baseline path for one control file."""

    control_path = _normal_live_admission_path(
        control_state_path, label="live control"
    )
    return control_path.with_name(f".{control_path.name}.normal-live-risk-metrics.json")


def _normal_live_metrics_decimal(value: object, *, label: str) -> Decimal:
    if type(value) not in (str, Decimal):
        raise ValueError(f"normal live risk metrics {label} is invalid")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"normal live risk metrics {label} is invalid") from exc
    if not parsed.is_finite() or parsed <= Decimal("0"):
        raise ValueError(f"normal live risk metrics {label} is invalid")
    return parsed


def _normal_live_metrics_time(value: object, *, label: str) -> datetime.datetime:
    if type(value) is not str:
        raise ValueError(f"normal live risk metrics {label} is invalid")
    return _normal_live_admission_lease_time(value, label=f"risk metrics {label}")


def _normal_live_metrics_payload_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _normal_live_metrics_account_sha256(account: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(account), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _read_normal_live_risk_metrics_baseline_state(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
        state = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("normal live risk metrics baseline is unavailable") from exc
    if type(state) is not dict:
        raise ValueError("normal live risk metrics baseline is invalid")
    return state


def _validate_normal_live_risk_metrics_baseline_state(
    state: Mapping[str, object],
    *,
    trade_date: str,
    observed_at: datetime.datetime,
) -> tuple[Decimal, Decimal]:
    required = {
        "schema_version",
        "trade_date",
        "day_start_equity",
        "high_water_equity",
        "updated_at",
    }
    if set(state) != required or state["schema_version"] != 1:
        raise ValueError("normal live risk metrics baseline is invalid")
    if type(state["trade_date"]) is not str or state["trade_date"] != trade_date:
        raise ValueError("normal live risk metrics baseline is not current")
    day_start = _normal_live_metrics_decimal(
        state["day_start_equity"], label="day_start_equity"
    )
    high_water = _normal_live_metrics_decimal(
        state["high_water_equity"], label="high_water_equity"
    )
    updated_at = _normal_live_metrics_time(state["updated_at"], label="updated_at")
    if updated_at > observed_at or high_water < day_start:
        raise ValueError("normal live risk metrics baseline is invalid")
    return day_start, high_water


def _preflight_normal_live_risk_metrics_baseline(
    path: Path,
    *,
    current: datetime.datetime,
) -> None:
    """Require observer-owned day evidence before any owned broker read.

    This is intentionally read-only.  The submit path must not create or
    repair a day baseline, because that could erase an earlier intraday loss.
    """

    with live_control_lock(path):
        state = _read_normal_live_risk_metrics_baseline_state(path)
        _validate_normal_live_risk_metrics_baseline_state(
            state,
            trade_date=current.astimezone(CENTRAL).date().isoformat(),
            observed_at=current,
        )


def _load_normal_live_risk_metrics_baseline(
    path: Path,
    *,
    trade_date: str,
    observed_at: datetime.datetime,
    equity: Decimal,
) -> tuple[Decimal, Decimal]:
    """Read/update the observer-owned same-day high-water baseline.

    There is no safe first-write default: creating a baseline at submission
    time would conceal all earlier intraday loss.  A dedicated observer must
    establish the day start before this direct live path can ever be admitted.
    """

    with live_control_lock(path):
        state = _read_normal_live_risk_metrics_baseline_state(path)
        day_start, high_water = _validate_normal_live_risk_metrics_baseline_state(
            state, trade_date=trade_date, observed_at=observed_at
        )
        if equity > high_water:
            state["high_water_equity"] = str(equity)
            state["updated_at"] = observed_at.isoformat(timespec="seconds")
            atomic_write_text(path, json.dumps(state, indent=2))
            high_water = equity
        return day_start, high_water


def _preflight_normal_live_submit_local_prerequisites(
    intent: AuthorizedNormalTradeIntent,
    *,
    order_payload: Mapping[str, object],
    risk_envelope_path: str | Path,
    control_state_path: str | Path,
    order_rate_state_path: str | Path,
) -> None:
    """Reject local normal-live failures before the first owned broker GET.

    This preflight deliberately establishes no admission and never receives
    caller-provided account metrics.  It validates the locally durable gates
    and the observer-owned daily baseline first; only a clean result permits
    creation of a fresh owned broker snapshot for risk metrics.
    """

    if type(intent) is not AuthorizedNormalTradeIntent:
        raise ValueError("normal live local preflight requires an exact live intent")
    payload = _normal_live_admission_mapping(order_payload, label="normal live order")
    expected_payload = {
        "symbol": intent.symbol,
        "side": intent.side,
        "type": intent.order_type,
        "time_in_force": intent.tif,
        "notional": intent.notional_usd,
        "limit_price": intent.limit_price,
        "client_order_id": intent.client_order_id,
    }
    if _normal_live_metrics_payload_sha256(payload) != _normal_live_metrics_payload_sha256(
        expected_payload
    ):
        raise ValueError("normal live local preflight does not bind the exact order")
    risk_path = _normal_live_admission_path(risk_envelope_path, label="risk envelope")
    control_path = _normal_live_admission_path(control_state_path, label="live control")
    rate_path = _normal_live_admission_path(order_rate_state_path, label="rate state")
    current = _normal_live_admission_moment()
    _state, control_issues = load_live_control_state(control_path, now=current)
    if control_issues:
        raise ValueError("normal live submit final gates rejected admission")
    envelope, envelope_issues = load_risk_envelope(risk_path)
    if envelope_issues or envelope is None:
        raise ValueError("normal live submit local gate config is unavailable")
    if (
        envelope.max_live_orders_per_window is None
        or envelope.live_order_window_minutes is None
    ):
        raise ValueError("normal live submit local gate config is unavailable")
    try:
        notional = Decimal(payload["notional"])
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise ValueError("normal live submit local gate config is unavailable") from exc
    if notional > envelope.per_name_cap_usd:
        raise ValueError("normal live submit final gates rejected admission")
    if not rate_path.exists():
        raise ValueError("normal live submit rate ledger is unavailable")
    rate_issues = evaluate_order_rate_limit(
        path=rate_path,
        now=current,
        window_minutes=envelope.live_order_window_minutes,
        max_orders=envelope.max_live_orders_per_window,
        new_order_count=1,
        exclude_client_order_id=payload["client_order_id"],
    )
    if rate_issues:
        raise ValueError("normal live submit final gates rejected admission")
    _preflight_normal_live_risk_metrics_baseline(
        _normal_live_risk_metrics_state_path(control_path), current=current
    )


def _issue_normal_live_submit_risk_metrics(
    intent: AuthorizedNormalTradeIntent,
    *,
    order_payload: Mapping[str, object],
    control_state_path: str | Path,
    broker_read_adapter: object,
) -> NormalLiveRiskMetrics:
    """Mint exact risk evidence from an owned Alpaca account snapshot only."""

    if type(intent) is not AuthorizedNormalTradeIntent:
        raise ValueError("normal live risk metrics require an exact live intent")
    payload = _normal_live_admission_mapping(order_payload, label="risk metrics order")
    payload_sha256 = _normal_live_metrics_payload_sha256(payload)
    if payload_sha256 != _normal_live_metrics_payload_sha256(
        {
            "symbol": intent.symbol,
            "side": intent.side,
            "type": intent.order_type,
            "time_in_force": intent.tif,
            "notional": intent.notional_usd,
            "limit_price": intent.limit_price,
            "client_order_id": intent.client_order_id,
        }
    ):
        raise ValueError("normal live risk metrics do not bind the exact order")
    account, _positions, _orders, _existing, observed_at = _owned_normal_live_broker_read(
        broker_read_adapter, client_order_id=intent.client_order_id
    )
    issued_at = _normal_live_admission_moment()
    if (
        observed_at > issued_at
        or issued_at - observed_at
        > datetime.timedelta(seconds=_NORMAL_LIVE_RISK_METRICS_MAX_AGE_SECONDS)
    ):
        raise ValueError("normal live risk metrics owned account snapshot is stale")
    equity = _normal_live_metrics_decimal(account.get("equity"), label="account equity")
    trade_date = observed_at.astimezone(CENTRAL).date().isoformat()
    baseline_path = _normal_live_risk_metrics_state_path(control_state_path)
    day_start, high_water = _load_normal_live_risk_metrics_baseline(
        baseline_path,
        trade_date=trade_date,
        observed_at=observed_at,
        equity=equity,
    )
    metrics = NormalLiveRiskMetrics(
        intent_full_sha256=_normal_live_intent_sha256(intent),
        order_payload_sha256=payload_sha256,
        account_snapshot_sha256=_normal_live_metrics_account_sha256(account),
        daily_loss_usd=max(day_start - equity, Decimal("0")),
        drawdown_pct=max((high_water - equity) / high_water, Decimal("0")),
        issued_at=issued_at.isoformat(timespec="seconds"),
        expires_at=(
            issued_at + datetime.timedelta(seconds=_NORMAL_LIVE_RISK_METRICS_MAX_AGE_SECONDS)
        ).isoformat(timespec="seconds"),
    )
    _NORMAL_LIVE_RISK_METRICS_CAPABILITIES[id(metrics)] = metrics
    return metrics


def _claim_normal_live_submit_risk_metrics(
    risk_metrics: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload: Mapping[str, object],
) -> NormalLiveRiskMetrics:
    """Consume one genuine short-lived owned-metrics capability into admission."""

    if type(risk_metrics) is not NormalLiveRiskMetrics:
        raise ValueError("normal live admission requires exact owned risk metrics")
    entry = _NORMAL_LIVE_RISK_METRICS_CAPABILITIES.pop(id(risk_metrics), None)
    if entry is not risk_metrics:
        raise ValueError("normal live admission requires unconsumed owned risk metrics")
    metrics = entry
    payload_sha256 = _normal_live_metrics_payload_sha256(order_payload)
    if (
        metrics.intent_full_sha256 != _normal_live_intent_sha256(intent)
        or metrics.order_payload_sha256 != payload_sha256
        or not metrics.account_snapshot_sha256
        or type(metrics.daily_loss_usd) is not Decimal
        or type(metrics.drawdown_pct) is not Decimal
        or metrics.daily_loss_usd < Decimal("0")
        or metrics.drawdown_pct < Decimal("0")
    ):
        raise ValueError("normal live admission risk metrics do not bind the exact order")
    issued = _normal_live_admission_lease_time(metrics.issued_at, label="risk metrics issued_at")
    expires = _normal_live_admission_lease_time(metrics.expires_at, label="risk metrics expires_at")
    if expires - issued != datetime.timedelta(seconds=_NORMAL_LIVE_RISK_METRICS_MAX_AGE_SECONDS):
        raise ValueError("normal live admission risk metrics lease is invalid")
    now = _normal_live_admission_moment()
    if now < issued or now >= expires:
        raise ValueError("normal live admission risk metrics are stale")
    return metrics


def _require_normal_live_submit_risk_metrics_current(
    metrics: NormalLiveRiskMetrics,
    *,
    intent_full_sha256: str,
    order_payload_sha256: str,
) -> None:
    if (
        type(metrics) is not NormalLiveRiskMetrics
        or metrics.intent_full_sha256 != intent_full_sha256
        or metrics.order_payload_sha256 != order_payload_sha256
        or not metrics.account_snapshot_sha256
        or type(metrics.daily_loss_usd) is not Decimal
        or type(metrics.drawdown_pct) is not Decimal
        or metrics.daily_loss_usd < Decimal("0")
        or metrics.drawdown_pct < Decimal("0")
    ):
        raise ValueError("normal live admission risk metrics are invalid")
    issued = _normal_live_admission_lease_time(metrics.issued_at, label="risk metrics issued_at")
    expires = _normal_live_admission_lease_time(metrics.expires_at, label="risk metrics expires_at")
    now = _normal_live_admission_moment()
    if (
        expires - issued != datetime.timedelta(seconds=_NORMAL_LIVE_RISK_METRICS_MAX_AGE_SECONDS)
        or now < issued
        or now >= expires
    ):
        raise ValueError("normal live admission risk metrics are stale")


def _normal_live_intent_sha256(intent: AuthorizedNormalTradeIntent) -> str:
    return hashlib.sha256(intent.canonical_json_bytes()).hexdigest()


def _require_risk_envelope_expansion_authorized(
    resolved_envelope_path: Path,
    current_envelope_sha256: str,
    *,
    expansion_approval: Mapping[str, object] | None,
    now: datetime.datetime,
    consume: bool = False,
) -> None:
    """Thin delegate to the policy-layer risk_envelope_expansion gate."""

    from tradingagents.policy.owner_approval import (
        OwnerApprovalError,
        require_risk_envelope_expansion,
    )

    try:
        require_risk_envelope_expansion(
            resolved_envelope_path=resolved_envelope_path,
            current_envelope_sha256=current_envelope_sha256,
            expansion_approval=expansion_approval,
            now=now,
            consume=consume,
        )
    except OwnerApprovalError as exc:
        raise ValueError(f"risk envelope expansion refused: {exc}") from exc


def _issue_normal_live_submit_admission(
    intent: AuthorizedNormalTradeIntent,
    *,
    order_payload: Mapping[str, object],
    risk_envelope_path: str | Path,
    promotion_state_path: str | Path,
    control_state_path: str | Path,
    order_rate_state_path: str | Path,
    risk_metrics: object,
    decision_evidence: Mapping,
    owner_approval: Mapping[str, object] | None = None,
    risk_envelope_expansion_approval: Mapping[str, object] | None = None,
) -> NormalLiveSubmitAdmission:
    """Issue a local capability; gates are re-evaluated under the policy lock."""
    if type(intent) is not AuthorizedNormalTradeIntent:
        raise ValueError("normal live admission requires an exact AuthorizedNormalTradeIntent")
    payload = _normal_live_admission_mapping(order_payload, label="normal live order")
    claimed_risk_metrics = _claim_normal_live_submit_risk_metrics(
        risk_metrics, intent=intent, order_payload=payload
    )
    resolved_envelope_path = _normal_live_admission_path(
        risk_envelope_path, label="risk envelope"
    )
    try:
        admitted_envelope_sha256 = hashlib.sha256(
            resolved_envelope_path.read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise ValueError("risk envelope is unavailable for normal live admission") from exc
    # P1-A: a changed/enlarged envelope becomes usable for normal-live only
    # through an independently signed, single-use risk_envelope_expansion
    # approval consumed at this transition point.
    _require_risk_envelope_expansion_authorized(
        resolved_envelope_path,
        admitted_envelope_sha256,
        expansion_approval=risk_envelope_expansion_approval,
        now=_normal_live_admission_moment(),
    )
    issued_at = _normal_live_admission_moment()
    admission = NormalLiveSubmitAdmission(
        intent_full_sha256=_normal_live_intent_sha256(intent),
        issued_at=issued_at.isoformat(timespec="seconds"),
        expires_at=(
            issued_at
            + datetime.timedelta(seconds=_NORMAL_LIVE_ADMISSION_MAX_AGE_SECONDS)
        ).isoformat(timespec="seconds"),
    )
    _NORMAL_LIVE_ADMISSION_CAPABILITIES[id(admission)] = (
        admission,
        _NormalLiveAdmissionContext(
            risk_envelope_path=resolved_envelope_path,
            promotion_state_path=_normal_live_admission_path(
                promotion_state_path, label="promotion state"
            ),
            control_state_path=_normal_live_admission_path(
                control_state_path, label="live control"
            ),
            order_rate_state_path=_normal_live_admission_path(
                order_rate_state_path, label="rate state"
            ),
            risk_metrics=claimed_risk_metrics,
            decision_evidence=_normal_live_admission_mapping(
                decision_evidence, label="decision evidence"
            ),
            admitted_risk_envelope_ref=str(resolved_envelope_path),
            admitted_risk_envelope_sha256=admitted_envelope_sha256,
            owner_approval=owner_approval,
            risk_envelope_expansion_approval=risk_envelope_expansion_approval,
        ),
    )
    return admission


def _claim_normal_live_submit_admission(
    admission: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload: Mapping[str, str],
    promotion_state_path: Path,
    broker_read_adapter: object,
) -> _NormalLiveAdmissionClaim:
    if type(admission) is not NormalLiveSubmitAdmission:
        raise ValueError("live submit requires an exact supervisor admission artifact")
    entry = _NORMAL_LIVE_ADMISSION_CAPABILITIES.get(id(admission))
    if entry is None or entry[0] is not admission:
        raise ValueError("live submit requires an unconsumed supervisor admission artifact")
    context = entry[1]
    if admission.intent_full_sha256 != _normal_live_intent_sha256(intent):
        raise ValueError("supervisor admission does not bind the exact live intent")
    if context.promotion_state_path != promotion_state_path.resolve():
        raise ValueError("supervisor admission does not bind the active promotion state")
    _require_normal_live_admission_lease_current(
        issued_at=admission.issued_at, expires_at=admission.expires_at
    )
    _require_normal_live_submit_risk_metrics_current(
        context.risk_metrics,
        intent_full_sha256=admission.intent_full_sha256,
        order_payload_sha256=_normal_live_metrics_payload_sha256(order_payload),
    )
    del _NORMAL_LIVE_ADMISSION_CAPABILITIES[id(admission)]
    order_payload_sha256 = hashlib.sha256(
        json.dumps(
            dict(order_payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    claim = _NormalLiveAdmissionClaim(
        intent_full_sha256=admission.intent_full_sha256,
        order_payload_sha256=order_payload_sha256,
        issued_at=admission.issued_at,
        expires_at=admission.expires_at,
        broker_read_adapter=broker_read_adapter,
    )
    _NORMAL_LIVE_ADMISSION_CLAIMS[id(claim)] = (claim, context, None)
    return claim


def _bind_normal_live_submit_claim_reconciliation(
    claim: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload: Mapping[str, str],
) -> tuple[dict[str, object], tuple[dict[str, object], ...], dict[str, object] | None]:
    """Perform the first owned broker read only after a durable control commit."""

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    reconciliation = reconcile_normal_live_submit(
        intent=intent,
        order_payload=order_payload,
        broker_read_adapter=claim.broker_read_adapter,
    )
    reconciliation_claim = _claim_normal_live_submit_reconciliation(
        reconciliation,
        intent=intent,
        order_payload_sha256=claim.order_payload_sha256,
        claimed_at=_normal_live_admission_moment(),
    )
    _NORMAL_LIVE_ADMISSION_RECONCILIATIONS[id(claim)] = reconciliation_claim
    return _refresh_normal_live_submit_reconciliation(
        reconciliation_claim,
        intent=intent,
        order_payload=order_payload,
    )


def _normal_live_submit_claim_reconciliation(claim: _NormalLiveAdmissionClaim) -> object:
    reconciliation = _NORMAL_LIVE_ADMISSION_RECONCILIATIONS.get(id(claim))
    if reconciliation is None:
        raise ValueError("live submit reconciliation is unavailable before owned broker reads")
    return reconciliation


def _normal_live_submit_admission_control_path(admission: object) -> Path:
    """Read the control path from an unconsumed exact admission only."""

    if type(admission) is not NormalLiveSubmitAdmission:
        raise ValueError("live submit requires an exact supervisor admission artifact")
    entry = _NORMAL_LIVE_ADMISSION_CAPABILITIES.get(id(admission))
    if entry is None or entry[0] is not admission:
        raise ValueError("live submit requires an unconsumed supervisor admission artifact")
    return entry[1].control_state_path


def _require_normal_live_submit_admission_available(admission: object) -> None:
    """Reject a missing/generic capability before any other final handoff work."""

    if type(admission) is not NormalLiveSubmitAdmission:
        raise ValueError("live submit requires an exact supervisor admission artifact")
    entry = _NORMAL_LIVE_ADMISSION_CAPABILITIES.get(id(admission))
    if entry is None or entry[0] is not admission:
        raise ValueError("live submit requires an unconsumed supervisor admission artifact")


def _exact_durable_commitment(
    control_state_path: Path,
    *,
    intent_full_sha256: str,
    order_payload_sha256: str,
    client_order_id: str,
    approval_id: str,
    transaction_binding: str,
) -> dict[str, object] | None:
    """Return only a durable record matching every exact owner field.

    Matches pending OR resolved records of the SAME order so an idempotent
    lookup-only recovery can continue; nothing else qualifies.
    """

    from tradingagents.policy.live_control import load_live_control_state

    state, issues = load_live_control_state(control_state_path)
    if issues or not isinstance(state, dict):
        return None
    commitments = state.get("normal_live_submission_commitments") or []
    if not isinstance(commitments, list):
        return None
    matches = [
        item
        for item in commitments
        if isinstance(item, dict)
        and item.get("intent_full_sha256") == intent_full_sha256
        and item.get("order_payload_sha256") == order_payload_sha256
        and item.get("client_order_id") == client_order_id
        and item.get("owner_approval_id") == approval_id
        and item.get("owner_approval_transaction_binding_sha256")
        == transaction_binding
    ]
    return dict(matches[0]) if len(matches) == 1 else None


def _exact_durable_commitment_matches(
    control_state_path: Path,
    *,
    intent_full_sha256: str,
    order_payload_sha256: str,
    client_order_id: str,
    approval_id: str,
    transaction_binding: str,
) -> bool:
    """True only when one durable record matches every exact owner field."""

    return (
        _exact_durable_commitment(
            control_state_path,
            intent_full_sha256=intent_full_sha256,
            order_payload_sha256=order_payload_sha256,
            client_order_id=client_order_id,
            approval_id=approval_id,
            transaction_binding=transaction_binding,
        )
        is not None
    )


def _consume_or_confirm_owner_approval_before_commit(
    supervisor_claim: object,
    *,
    payload: Mapping[str, str],
    sleeve: str,
    intent: AuthorizedNormalTradeIntent,
    rate_reservation_sha256: str,
    commitment_now: datetime.datetime,
) -> dict[str, object]:
    """Burn the bound owner approval exactly once, before the first commit.

    The first submission of a fresh bound order consumes its fully verified
    approval atomically before the durable commitment is created.  A later
    retry that still carries an exact pending commitment is recognized as
    recovery only when the canonical ledger already proves this same
    deterministic approval (id + action + purpose); anything else fails
    closed downstream at the final gate.
    """

    from tradingagents.policy.live_control import (
        prepare_normal_live_submission_candidate_locked,
    )
    from tradingagents.policy.live_gate import _live_order_owner_subject
    from tradingagents.policy.owner_approval import (
        OwnerApprovalError,
        consume_owner_approval,
        owner_approval_has_consumption,
        prepared_transaction_binding_sha256,
        prepared_transaction_sha256,
        transaction_binding_sha256,
        verify_owner_approval_structure,
    )

    if type(supervisor_claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires an exact supervisor admission claim")
    claim_entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(supervisor_claim))
    if claim_entry is None or claim_entry[0] is not supervisor_claim:
        raise ValueError("live submit requires an unconsumed supervisor admission claim")
    context = claim_entry[1]
    artifact = context.owner_approval
    if artifact is None:
        raise ValueError(
            "owner approval required: a fresh normal-live order cannot create "
            "its durable commitment without a current account_owner approval"
        )
    # TOCTOU guard at commit time: the canonical envelope must still hash to
    # the value captured during successful final-gate admission.
    try:
        current_envelope_sha256 = hashlib.sha256(
            Path(context.risk_envelope_path).read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise ValueError("risk envelope is unavailable before commitment") from exc
    if (
        current_envelope_sha256 != context.admitted_risk_envelope_sha256
        or str(context.risk_envelope_path) != context.admitted_risk_envelope_ref
    ):
        raise ValueError(
            "normal live submit final gates rejected admission: risk envelope "
            "changed after admission"
        )
    action = _normal_live_action_from_payload(payload, sleeve=sleeve)
    subject = _live_order_owner_subject(
        action,
        client_order_id=str(payload.get("client_order_id", "")),
        intent_full_sha256=_normal_live_intent_sha256(intent),
        order_payload_sha256=_normal_live_metrics_payload_sha256(payload),
    )
    purpose = f"live_order:{subject['decision_id']}:{subject['client_order_id']}"
    # Crash-safe prepare: durable, non-executable record of the intended
    # consumption BEFORE any ledger write.  An exact prepare + canonical
    # ledger consumption authorizes recovery/finalization even after the
    # original artifact TTL expires.
    from tradingagents.policy.owner_approval import (
        owner_prepare_has_exact_consumption,
        read_owner_approval_prepare,
        write_owner_approval_prepare,
    )

    control_dir = Path(context.control_state_path).parent
    prepare_path = control_dir / (
        f"{payload.get('client_order_id', 'order')}.owner-approval-prepare.json"
    )
    recovery_identity = {
        "operation": "normal_live_broker_submit",
        "subject": dict(subject),
        "source_binding": {"guard": "unified_go_live_guard"},
        "intent_full_sha256": _normal_live_intent_sha256(intent),
        "order_payload_sha256": _normal_live_metrics_payload_sha256(payload),
        "client_order_id": str(payload.get("client_order_id", "")),
        "sleeve": sleeve,
        "control_state_path": str(context.control_state_path),
        "risk_envelope_ref": context.admitted_risk_envelope_ref,
        "risk_envelope_sha256": context.admitted_risk_envelope_sha256,
    }
    prepared = read_owner_approval_prepare(prepare_path)
    exact_recovery_prepare = (
        prepared is not None
        and prepared["transaction"].get("recovery_identity")
        == recovery_identity
    )
    if prepared is not None and not exact_recovery_prepare:
        raise ValueError(
            "owner approval prepare does not match this normal-live transaction"
        )
    exact_recovery = (
        exact_recovery_prepare
        and owner_prepare_has_exact_consumption(prepare_path)
    )
    if not exact_recovery:
        try:
            parsed = verify_owner_approval_structure(
                approval=artifact,
                expected_action="live_promotion",
                subject=subject,
                source_binding={"guard": "unified_go_live_guard"},
                now=_normal_live_admission_moment(),
                purpose=purpose,
            )
            envelope_sha256 = hashlib.sha256(
                Path(context.risk_envelope_path).read_bytes()
            ).hexdigest()
            binding = parsed["risk_envelope_binding"]
            if (
                binding["ref"] != str(context.risk_envelope_path)
                or binding["sha256"] != envelope_sha256
            ):
                raise OwnerApprovalError(
                    "owner approval risk envelope binding does not match this request"
                )
            binding = transaction_binding_sha256(
                approval_id=parsed["approval_id"],
                action=parsed["action"],
                purpose=purpose,
                subject=subject,
                risk_envelope_ref=str(context.risk_envelope_path),
                risk_envelope_sha256=envelope_sha256,
            )
            if prepared is not None:
                prepared_transaction = prepared["transaction"]
                candidate = prepared_transaction.get("commitment_candidate")
                if (
                    prepared["approval_id"] != parsed["approval_id"]
                    or prepared["action"] != parsed["action"]
                    or prepared["purpose"] != purpose
                    or prepared["transaction_binding_sha256"] != binding
                    or not isinstance(candidate, Mapping)
                ):
                    raise OwnerApprovalError(
                        "owner approval prepare does not match this exact normal-live commitment"
                    )
            else:
                candidate = prepare_normal_live_submission_candidate_locked(
                    context.control_state_path,
                    intent_full_sha256=_normal_live_intent_sha256(intent),
                    order_payload_sha256=_normal_live_metrics_payload_sha256(payload),
                    client_order_id=str(payload.get("client_order_id", "")),
                    rate_reservation_sha256=rate_reservation_sha256,
                    owner_approval_id=parsed["approval_id"],
                    owner_approval_transaction_binding_sha256=binding,
                    risk_envelope_ref=str(context.risk_envelope_path),
                    risk_envelope_sha256=envelope_sha256,
                    now=commitment_now,
                )
                prepared_transaction = {
                    **recovery_identity,
                    "recovery_identity": recovery_identity,
                    "approval_artifact": dict(artifact),
                    "commitment_candidate": candidate,
                }
            prepared_binding = prepared_transaction_binding_sha256(
                transaction_binding_sha256=binding,
                transaction_sha256=prepared_transaction_sha256(prepared_transaction),
            )
            consumed = owner_approval_has_consumption(parsed["approval_id"])
            if consumed:
                # Conservative transaction rule (NOT atomic): once this approval
                # is consumed it may only continue an EXACT durable commitment
                # of the same order (pending or already-resolved lookup-only
                # recovery) — OR an exact crash recovery proven by this
                # transaction's durable prepare plus the canonical ledger.
                durable_match = _exact_durable_commitment(
                    context.control_state_path,
                    intent_full_sha256=_normal_live_intent_sha256(intent),
                    order_payload_sha256=_normal_live_metrics_payload_sha256(payload),
                    client_order_id=str(payload.get("client_order_id", "")),
                    approval_id=parsed["approval_id"],
                    transaction_binding=binding,
                )
                existing_match = durable_match is not None or (
                    prepared is not None
                    and exact_recovery_prepare
                    and prepared.get("approval_id") == parsed["approval_id"]
                    and owner_prepare_has_exact_consumption(prepare_path)
                )
                if not existing_match:
                    raise OwnerApprovalError(
                        "consumed owner approval cannot create a new normal-live "
                        "commitment after a failed write; issue a new approval"
                    )
                if (
                    durable_match is not None
                    and durable_match.get("state") == "resolved"
                ):
                    # A terminal exact record is already the complete outcome
                    # of this approval.  Its recovery sidecar was deliberately
                    # retired, so an idempotent retry must reuse the resolved
                    # record rather than create a second pending commitment.
                    return {
                        "owner_approval_id": parsed["approval_id"],
                        "owner_approval_transaction_binding_sha256": binding,
                        "risk_envelope_ref": context.admitted_risk_envelope_ref,
                        "risk_envelope_sha256": context.admitted_risk_envelope_sha256,
                        "resolved_commitment": durable_match,
                    }
            else:
                # Prepare strictly precedes consumption: a crash between the
                # two leaves the approval unconsumed but identifiable.
                if prepared is None:
                    written_binding = write_owner_approval_prepare(
                        prepare_path,
                        approval_id=parsed["approval_id"],
                        action=parsed["action"],
                        purpose=purpose,
                        transaction_binding_sha256=binding,
                        transaction=prepared_transaction,
                        now=commitment_now,
                    )
                    if written_binding != prepared_binding:
                        raise OwnerApprovalError(
                            "owner approval prepare binding does not match this normal-live transaction"
                        )
                consume_owner_approval(
                    approval_id=parsed["approval_id"],
                    action=parsed["action"],
                    purpose=purpose,
                    transaction_binding_sha256=binding,
                    prepared_transaction_binding_sha256=prepared_binding,
                    now=commitment_now,
                )
        except OwnerApprovalError as exc:
            raise ValueError(f"owner approval refused before first commitment: {exc}") from exc
    if exact_recovery:
        candidate = prepared["transaction"].get("commitment_candidate")
        if not isinstance(candidate, Mapping):
            raise ValueError("normal-live recovery candidate is invalid")
        return {
            "owner_approval_id": str(prepared.get("approval_id")),
            "owner_approval_transaction_binding_sha256": str(
                prepared.get("transaction_binding_sha256")
            ),
            "risk_envelope_ref": context.admitted_risk_envelope_ref,
            "risk_envelope_sha256": context.admitted_risk_envelope_sha256,
            "commitment_candidate": candidate,
        }
    return {
        "owner_approval_id": parsed["approval_id"],
        "owner_approval_transaction_binding_sha256": binding,
        "risk_envelope_ref": context.admitted_risk_envelope_ref,
        "risk_envelope_sha256": context.admitted_risk_envelope_sha256,
        "commitment_candidate": candidate,
    }


def _preflight_normal_live_submit_before_broker_reads(
    admission: object,
    *,
    payload: Mapping[str, str],
) -> None:
    """Deny obvious frozen/cap/rate failures before even read-only broker I/O.

    This deliberately never grants authority.  The full gate is re-run later
    against an owned broker snapshot under the short control transaction.
    """

    if type(admission) is not NormalLiveSubmitAdmission:
        raise ValueError("live submit requires an exact supervisor admission artifact")
    entry = _NORMAL_LIVE_ADMISSION_CAPABILITIES.get(id(admission))
    if entry is None or entry[0] is not admission:
        raise ValueError("live submit requires an unconsumed supervisor admission artifact")
    context = entry[1]
    current = _normal_live_admission_moment()
    _require_normal_live_admission_lease_current(
        issued_at=admission.issued_at, expires_at=admission.expires_at
    )
    _require_normal_live_submit_risk_metrics_current(
        context.risk_metrics,
        intent_full_sha256=admission.intent_full_sha256,
        order_payload_sha256=_normal_live_metrics_payload_sha256(payload),
    )
    _state, control_issues = load_live_control_state(
        context.control_state_path, now=current
    )
    if control_issues:
        raise ValueError("normal live submit final gates rejected admission")
    envelope, envelope_issues = load_risk_envelope(context.risk_envelope_path)
    if envelope_issues or envelope is None:
        raise ValueError("normal live submit final gates rejected admission")
    try:
        notional = Decimal(payload["notional"])
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise ValueError("normal live submit final gates rejected admission") from exc
    if notional > envelope.per_name_cap_usd:
        raise ValueError("normal live submit final gates rejected admission")
    if (
        envelope.max_live_orders_per_window is None
        or envelope.live_order_window_minutes is None
        or evaluate_order_rate_limit(
            path=context.order_rate_state_path,
            now=current,
            window_minutes=envelope.live_order_window_minutes,
            max_orders=envelope.max_live_orders_per_window,
            new_order_count=1,
            exclude_client_order_id=payload["client_order_id"],
        )
    ):
        raise ValueError("normal live submit final gates rejected admission")


def _normal_live_action_from_payload(
    payload: Mapping[str, str], *, sleeve: str
) -> HourlySupervisorAction:
    return HourlySupervisorAction(
        action="buy",
        symbol=payload["symbol"],
        notional=Decimal(payload["notional"]),
        limit_price=Decimal(payload["limit_price"]),
        side=payload["side"],
        order_type=payload["type"],
        reason="exact authorized normal-live order",
        account="live",
        execution_mode="tiny_live",
        sleeve=sleeve,
    )


def _normal_live_commitment_recovery_identity(
    claim: _NormalLiveAdmissionClaim,
    *,
    context: _NormalLiveAdmissionContext,
    payload: Mapping[str, str],
    sleeve: str,
) -> dict[str, object]:
    """Return the immutable identity of one normal-live recovery transaction."""

    from tradingagents.policy.live_gate import _live_order_owner_subject

    action = _normal_live_action_from_payload(payload, sleeve=sleeve)
    recovery_subject = _live_order_owner_subject(
        action,
        client_order_id=str(payload.get("client_order_id", "")),
        intent_full_sha256=claim.intent_full_sha256,
        order_payload_sha256=claim.order_payload_sha256,
    )
    return {
        "operation": "normal_live_broker_submit",
        "subject": recovery_subject,
        "source_binding": {"guard": "unified_go_live_guard"},
        "intent_full_sha256": claim.intent_full_sha256,
        "order_payload_sha256": claim.order_payload_sha256,
        "client_order_id": str(payload.get("client_order_id", "")),
        "sleeve": sleeve,
        "control_state_path": str(context.control_state_path),
        "risk_envelope_ref": context.admitted_risk_envelope_ref,
        "risk_envelope_sha256": context.admitted_risk_envelope_sha256,
    }


def _require_pending_normal_live_commitment_owner_prepare(
    claim: object,
    *,
    payload: Mapping[str, str],
    sleeve: str,
    normal_live_commitment: Mapping[str, object],
    require_current_control_after: bool = True,
) -> tuple[dict[str, object], Path, dict[str, object]]:
    """Require the exact retained owner prepare for a pending commitment.

    A pending record is not independently executable.  Its retained generic
    sidecar carries the original signed artifact plus the complete candidate
    control image, so it must be intact before either a final gate or even a
    lookup-only broker read can resume the transaction.  Terminal records do
    not use this helper: their sidecar may already have been safely retired.
    The pre-read caller requires the current control image to equal the
    candidate after-image.  A later final gate may follow a cooperating freeze
    that changes that image; it still verifies the retained candidate itself
    and lets canonical live-control validation report the freeze.
    """

    from tradingagents.policy.owner_approval import (
        owner_prepare_has_exact_consumption,
        read_owner_approval_prepare,
    )

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    if normal_live_commitment.get("state") != "pending":
        raise ValueError("normal-live commitment is not pending")
    context = entry[1]
    prepare_path = Path(context.control_state_path).parent / (
        f"{payload.get('client_order_id', 'order')}.owner-approval-prepare.json"
    )
    prepared = read_owner_approval_prepare(prepare_path)
    transaction = prepared.get("transaction") if prepared is not None else None
    artifact = (
        transaction.get("approval_artifact")
        if isinstance(transaction, Mapping)
        else None
    )
    candidate = (
        transaction.get("commitment_candidate")
        if isinstance(transaction, Mapping)
        else None
    )
    recovery_identity = _normal_live_commitment_recovery_identity(
        claim, context=context, payload=payload, sleeve=sleeve
    )
    subject = recovery_identity["subject"]
    if not isinstance(subject, Mapping):  # defensive: the helper owns this map
        raise ValueError("normal-live recovery identity is invalid")
    purpose = f"live_order:{subject['decision_id']}:{subject['client_order_id']}"
    candidate_fields = {
        "schema_version",
        "control_state_path",
        "control_preimage_sha256",
        "control_after_sha256",
        "control_after_json",
        "commitment",
    }
    try:
        current_control_sha256 = hashlib.sha256(
            Path(context.control_state_path).read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise ValueError(
            "pending normal-live commitment control after-image is unavailable"
        ) from exc
    candidate_after_json = (
        candidate.get("control_after_json") if isinstance(candidate, Mapping) else None
    )
    exact = (
        prepared is not None
        and isinstance(transaction, Mapping)
        and isinstance(artifact, Mapping)
        and isinstance(candidate, Mapping)
        and set(candidate) == candidate_fields
        and candidate.get("schema_version") == 1
        and candidate.get("control_state_path") == str(context.control_state_path)
        and type(candidate.get("control_preimage_sha256")) is str
        and re.fullmatch(r"[0-9a-f]{64}", candidate["control_preimage_sha256"])
        is not None
        and type(candidate.get("control_after_sha256")) is str
        and re.fullmatch(r"[0-9a-f]{64}", candidate["control_after_sha256"])
        is not None
        and type(candidate_after_json) is str
        and hashlib.sha256(candidate_after_json.encode("utf-8")).hexdigest()
        == candidate["control_after_sha256"]
        and (
            not require_current_control_after
            or candidate["control_after_sha256"] == current_control_sha256
        )
        and candidate.get("commitment") == dict(normal_live_commitment)
        and prepared.get("approval_id")
        == normal_live_commitment.get("owner_approval_id")
        and prepared.get("action") == "live_promotion"
        and prepared.get("purpose") == purpose
        and prepared.get("transaction_binding_sha256")
        == normal_live_commitment.get(
            "owner_approval_transaction_binding_sha256"
        )
        and transaction.get("recovery_identity") == recovery_identity
        and transaction.get("intent_full_sha256") == claim.intent_full_sha256
        and transaction.get("order_payload_sha256") == claim.order_payload_sha256
        and transaction.get("client_order_id")
        == str(payload.get("client_order_id", ""))
        and owner_prepare_has_exact_consumption(prepare_path)
    )
    if not exact:
        raise ValueError(
            "pending normal-live commitment requires its exact retained owner prepare"
        )
    return dict(artifact), prepare_path, recovery_identity


def _revalidate_normal_live_submit_claim(
    claim: object,
    *,
    payload: Mapping[str, str],
    sleeve: str,
    live_account: Mapping[str, object],
    live_positions: Sequence[Mapping[str, object]],
    rate_limit_exclude_client_order_id: str | None = None,
    normal_live_commitment: Mapping[str, object] | None = None,
) -> None:
    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    context = entry[1]
    _require_normal_live_submit_claim_leases_current(
        claim, order_payload=payload
    )
    from contextlib import nullcontext

    owner_approval_for_gate = context.owner_approval
    expired_recovery_context = nullcontext()
    if (
        normal_live_commitment is not None
        and normal_live_commitment.get("state") == "pending"
    ):
        from tradingagents.policy.owner_approval import (
            exact_expired_owner_approval_recovery,
        )

        (
            owner_approval_for_gate,
            prepare_path,
            recovery_identity,
        ) = _require_pending_normal_live_commitment_owner_prepare(
            claim,
            payload=payload,
            sleeve=sleeve,
            normal_live_commitment=normal_live_commitment,
            require_current_control_after=False,
        )
        # A restart may carry a newly issued admission envelope, but only this
        # retained, ledger-proven original approval can satisfy the pending
        # commitment's exact recovery binding.  Enter this context even before
        # TTL expiry so gate plumbing can never fall back to a caller artifact.
        expired_recovery_context = exact_expired_owner_approval_recovery(
            prepare_path, recovery_identity=recovery_identity
        )
    current = _normal_live_admission_moment()
    with expired_recovery_context:
        issues = validate_supervisor_live_submit_allowed(
            actions=[_normal_live_action_from_payload(payload, sleeve=sleeve)],
            risk_envelope_path=context.risk_envelope_path,
            promotion_state_path=context.promotion_state_path,
            control_state_path=context.control_state_path,
            order_rate_state_path=context.order_rate_state_path,
            current_live_exposure=live_exposure_from_positions(live_positions),
            current_daily_loss_usd=context.risk_metrics.daily_loss_usd,
            current_drawdown_pct=context.risk_metrics.drawdown_pct,
            live_account=live_account,
            live_positions=live_positions,
            decision_evidence=context.decision_evidence,
            now=current,
            rate_limit_exclude_client_order_id=rate_limit_exclude_client_order_id,
            normal_live_commitment=normal_live_commitment,
            normal_live_intent_full_sha256=claim.intent_full_sha256,
            normal_live_order_payload_sha256=claim.order_payload_sha256,
            normal_live_client_order_id=str(payload.get("client_order_id", "")),
            owner_approval=owner_approval_for_gate,
            risk_envelope_expansion_approval=context.risk_envelope_expansion_approval,
        )
    if issues:
        raise ValueError(
            "normal live submit final gates rejected admission: "
            + "; ".join(issue.reason for issue in issues)
        )


def _refresh_normal_live_submit_claim_broker_state(
    claim: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    payload: Mapping[str, str],
) -> tuple[dict[str, object], tuple[dict[str, object], ...], dict[str, object] | None]:
    """Refresh the trusted complete broker snapshot before the commit point."""

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    return _refresh_normal_live_submit_reconciliation(
        _normal_live_submit_claim_reconciliation(claim),
        intent=intent,
        order_payload=payload,
    )


def _revalidate_normal_live_submit_reconciliation_after_lookup(
    claim: object,
    *,
    intent: AuthorizedNormalTradeIntent,
    order_payload_sha256: str,
) -> None:
    """Bind the policy's final read-only lookup to the issued reconciliation."""

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    _revalidate_normal_live_submit_reconciliation(
        _normal_live_submit_claim_reconciliation(claim),
        intent=intent,
        order_payload_sha256=order_payload_sha256,
    )


def _normal_live_submit_claim_control_path(claim: object) -> Path:
    """Return the lock path bound to one trusted normal-live claim.

    Lock order for the normal-live boundary is always promotion state, then
    live control, then the rate ledger.  Control writers take only their
    control lock, so they cannot deadlock a policy handoff that already owns
    the promotion-state lock.
    """

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    return entry[1].control_state_path


def _normal_live_submit_claim_context(
    claim: object,
) -> _NormalLiveAdmissionContext:
    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    return entry[1]


def _require_normal_live_submit_claim_leases_current(
    claim: object,
    *,
    order_payload: Mapping[str, str],
) -> None:
    """Recheck the typed admission and metrics leases at a broker-I/O edge."""

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    payload = dict(order_payload)
    payload_sha256 = _normal_live_metrics_payload_sha256(payload)
    if payload_sha256 != claim.order_payload_sha256:
        raise ValueError("supervisor admission does not bind the exact live order")
    _require_normal_live_admission_lease_current(
        issued_at=claim.issued_at, expires_at=claim.expires_at
    )
    _require_normal_live_submit_risk_metrics_current(
        entry[1].risk_metrics,
        intent_full_sha256=claim.intent_full_sha256,
        order_payload_sha256=payload_sha256,
    )


def _reserve_normal_live_submit_claim(
    claim: object,
    *,
    client_order_id: str,
) -> LiveOrderRateReservation:
    """Reserve rate capacity under the final control-held broker handoff."""

    context = _normal_live_submit_claim_context(claim)
    envelope, issues = load_risk_envelope(context.risk_envelope_path)
    if (
        issues
        or envelope is None
        or envelope.max_live_orders_per_window is None
        or envelope.live_order_window_minutes is None
    ):
        raise ValueError("normal live submit rate reservation is unavailable")
    reservation = reserve_live_order_submission(
        context.order_rate_state_path,
        client_order_id=client_order_id,
        now=_normal_live_admission_moment(),
        window_minutes=envelope.live_order_window_minutes,
        max_orders=envelope.max_live_orders_per_window,
        require_existing_ledger=True,
    )
    if type(reservation) is not LiveOrderRateReservation:
        raise ValueError("normal live submit rate reservation is unavailable")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    _NORMAL_LIVE_ADMISSION_CLAIMS[id(claim)] = (entry[0], entry[1], reservation)
    return reservation


def _normal_live_submit_claim_reservation(
    claim: object,
) -> LiveOrderRateReservation:
    """Return the one durable rate binding reserved for the exact claim."""

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim or type(entry[2]) is not LiveOrderRateReservation:
        raise ValueError("normal live submit rate reservation is unavailable")
    return entry[2]


def _release_normal_live_submit_claim_reservation(
    claim: object,
    *,
    client_order_id: str,
) -> None:
    """Release only after an exact read-only retry proves the order absent."""

    context = _normal_live_submit_claim_context(claim)
    reservation = _normal_live_submit_claim_reservation(claim)
    release_live_order_reservation(
        context.order_rate_state_path,
        client_order_id=client_order_id,
        reservation=reservation,
    )


def _record_normal_live_submit_claim(
    claim: object,
    *,
    client_order_id: str,
    accepted_at: datetime.datetime,
) -> None:
    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    reservation = _normal_live_submit_claim_reservation(claim)
    record_live_order_submission(
        entry[1].order_rate_state_path,
        client_order_id=client_order_id,
        now=accepted_at,
        reservation=reservation,
    )
    _NORMAL_LIVE_ADMISSION_CLAIMS.pop(id(claim), None)
    reconciliation = _NORMAL_LIVE_ADMISSION_RECONCILIATIONS.pop(id(claim), None)
    if reconciliation is not None:
        _release_normal_live_submit_reconciliation(reconciliation)


def _discard_normal_live_submit_claim(claim: object) -> None:
    """Release a one-use claim after an error before its durable outcome."""

    if type(claim) is not _NormalLiveAdmissionClaim:
        return
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.pop(id(claim), None)
    if entry is not None and entry[0] is claim:
        reconciliation = _NORMAL_LIVE_ADMISSION_RECONCILIATIONS.pop(id(claim), None)
        if reconciliation is not None:
            _release_normal_live_submit_reconciliation(reconciliation)


def _issue_normal_live_submit_post_capability(
    claim: object,
    *,
    order_payload: Mapping[str, str],
    commitment: Mapping[str, object],
) -> object:
    """Mint the sole raw-POST capability from a verified policy admission claim."""

    if type(claim) is not _NormalLiveAdmissionClaim:
        raise ValueError("live submit requires a trusted supervisor admission claim")
    entry = _NORMAL_LIVE_ADMISSION_CLAIMS.get(id(claim))
    if entry is None or entry[0] is not claim:
        raise ValueError("live submit supervisor admission claim is unavailable")
    _require_normal_live_submit_claim_leases_current(
        claim, order_payload=order_payload
    )
    if _normal_live_submit_claim_reconciliation(claim) is None:
        raise ValueError("live submit reconciliation is unavailable before raw post")
    reservation = _normal_live_submit_claim_reservation(claim)
    payload = dict(order_payload)
    client_order_id = payload.get("client_order_id")
    intent_full_sha256 = claim.intent_full_sha256
    payload_sha256 = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    required_commitment = {
        "commitment_id",
        "intent_full_sha256",
        "order_payload_sha256",
        "client_order_id",
        "control_preimage_sha256",
        "rate_reservation_sha256",
        "risk_envelope_ref",
        "risk_envelope_sha256",
    }
    if (
        type(client_order_id) is not str
        or not client_order_id
        or not isinstance(commitment, Mapping)
        or set(commitment) < required_commitment
        or any(type(commitment.get(field)) is not str for field in required_commitment)
        or commitment.get("intent_full_sha256") != intent_full_sha256
        or commitment.get("order_payload_sha256") != payload_sha256
        or commitment.get("client_order_id") != client_order_id
        or commitment.get("rate_reservation_sha256") != reservation.binding_sha256
    ):
        raise ValueError("normal live broker post capability is invalid")
    # Retain the complete canonical record, including its lifecycle state.
    # The sole raw-POST consumer revalidates this exact snapshot against the
    # control ledger and requires it to remain pending.
    bound_commitment = dict(commitment)
    capability = object()
    _NORMAL_LIVE_SUBMIT_POST_CAPABILITIES[id(capability)] = (
        capability,
        claim.broker_read_adapter,
        payload_sha256,
        client_order_id,
        _normal_live_submit_claim_control_path(claim),
        bound_commitment,
        claim,
        reservation,
    )
    return capability


def _after_normal_live_final_envelope_hash_check() -> None:
    """Private deterministic race seam; production intentionally does nothing."""


def _consume_normal_live_submit_post_capability(
    broker_read_adapter: object,
    capability: object,
    *,
    order_payload: Mapping[str, str],
    send,
) -> object:
    """Consume a supervisor-minted token at Alpaca's raw POST primitive."""

    entry = _NORMAL_LIVE_SUBMIT_POST_CAPABILITIES.get(id(capability))
    if entry is None or entry[0] is not capability:
        raise ValueError("live raw post requires a policy post capability")
    (
        _token,
        expected_adapter,
        payload_sha256,
        client_order_id,
        control_state_path,
        commitment,
        claim,
        reservation,
    ) = entry
    payload = dict(order_payload)
    if (
        expected_adapter is not broker_read_adapter
        or payload.get("client_order_id") != client_order_id
        or hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        != payload_sha256
    ):
        raise ValueError("live raw post capability does not bind the exact order")
    # The final post decision is made here, directly beside the sole network
    # primitive.  A resolved, substituted, malformed, or missing commitment
    # cannot be converted into a broker write after the policy's last lookup.
    from tradingagents.policy.live_control import (
        _verify_pending_normal_live_submission_commitment_locked,
    )

    with live_control_lock(control_state_path):
        # A blocked control lock can itself consume the bounded local leases.
        # Recheck the real registry-owned artifacts at the final raw transport
        # point, not through a caller callback or copied values.
        _require_normal_live_submit_claim_leases_current(
            claim, order_payload=payload
        )
        _verify_pending_normal_live_submission_commitment_locked(
            control_state_path,
            commitment=commitment,
            intent_full_sha256=commitment["intent_full_sha256"],
            order_payload_sha256=payload_sha256,
            client_order_id=client_order_id,
            rate_reservation_sha256=reservation.binding_sha256,
        )
        _NORMAL_LIVE_SUBMIT_POST_CAPABILITIES.pop(id(capability), None)
    # TOCTOU defense at the sole raw-POST consumer: the canonical bound
    # envelope is reread and hash-compared under the shared envelope-content
    # lock immediately adjacent to send().  Future production writers must
    # honor the same lock (there are no in-repo content writers today), so no
    # cooperating writer can open a check-to-POST window.  A swapped,
    # modified, missing, or malformed envelope blocks here with zero broker
    # POST.
    bound_envelope_ref = str(commitment.get("risk_envelope_ref") or "")
    bound_envelope_sha256 = str(commitment.get("risk_envelope_sha256") or "")
    if not bound_envelope_ref or len(bound_envelope_sha256) != 64:
        raise ValueError("normal live submit final gates rejected admission")
    # Never hold the control lock around broker I/O: a later safety freeze must
    # record promptly.  The rate lock plus envelope-content lock cover the
    # immediate proof and raw POST; neither is a live-control lock.
    if not callable(send):
        raise ValueError("live raw post requires a classified transport sender")
    with normal_live_order_rate_reservation_lock(reservation), risk_envelope_lock(
        bound_envelope_ref
    ):
        try:
            current_envelope_bytes = read_risk_envelope_bytes_locked(
                bound_envelope_ref
            )
        except (OSError, ValueError) as exc:
            raise ValueError(
                "normal live submit final gates rejected admission: risk "
                "envelope is unavailable"
            ) from exc
        if hashlib.sha256(current_envelope_bytes).hexdigest() != bound_envelope_sha256:
            raise ValueError(
                "normal live submit final gates rejected admission: risk "
                "envelope changed after commitment"
            )
        _after_normal_live_final_envelope_hash_check()
        # The deterministic seam above deliberately models a write that
        # ignored the lock.  Re-prove immediately before the raw transport
        # call so even that hostile race cannot reach ``send``.
        try:
            final_envelope_bytes = read_risk_envelope_bytes_locked(
                bound_envelope_ref
            )
        except (OSError, ValueError) as exc:
            raise ValueError(
                "normal live submit final gates rejected admission: risk "
                "envelope is unavailable"
            ) from exc
        if hashlib.sha256(final_envelope_bytes).hexdigest() != bound_envelope_sha256:
            raise ValueError(
                "normal live submit final gates rejected admission: risk "
                "envelope changed after commitment"
            )
        return send()


def resolve_live_sleeve(
    live_strategy_selection: Mapping | None,
    promotion_state: Mapping | None,
) -> tuple[str, str]:
    """Pick the sleeve identity stamped on live supervisor actions.

    The paper-tournament selection becomes binding only when the selected
    sleeve holds a live-enabled ``tiny_live_eligible`` promotion record.
    Otherwise fall back to any live-enabled sleeve from promotion state, and
    finally to the legacy default — which the unified live gate fails closed
    on when it has no promotion record.
    """
    sleeves: Mapping = {}
    if isinstance(promotion_state, Mapping):
        raw = promotion_state.get("sleeves")
        if isinstance(raw, Mapping):
            sleeves = raw

    def _live_enabled(sleeve_id: str) -> bool:
        record = sleeves.get(sleeve_id)
        return (
            isinstance(record, Mapping)
            and record.get("stage") == "tiny_live_eligible"
            and record.get("live_enabled") is True
        )

    selected = None
    if isinstance(live_strategy_selection, Mapping):
        selected = live_strategy_selection.get("strategy_id")
    if selected and _live_enabled(str(selected)):
        return (
            str(selected),
            "tournament selection with live-enabled promotion record",
        )
    enabled = sorted(sleeve for sleeve in sleeves if _live_enabled(str(sleeve)))
    if enabled:
        return (
            enabled[0],
            "promotion-state live-enabled sleeve; tournament selection is not live-enabled",
        )
    return (
        LIVE_AGGRESSIVE_SLEEVE,
        "fail-closed default; no live-enabled sleeve in promotion state",
    )

_SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9.]{0,5}\b")
_NON_SYMBOL_WORDS = {
    "AI",
    "API",
    "ACTIVE",
    "ALPACA",
    "AND",
    "BUT",
    "CASH",
    "CAP",
    "CEO",
    "CFO",
    "CHECKS",
    "BUY",
    "DAY",
    "DELTA",
    "CME",
    "CLOSED",
    "DMA",
    "ECB",
    "EPS",
    "ETF",
    "EU",
    "EQUITY",
    "FED",
    "FIRST",
    "FALSE",
    "FOMC",
    "FOR",
    "FOUND",
    "FRESH",
    "FROM",
    "GDP",
    "GTC",
    "HOLD",
    "HOURLY",
    "HTTP",
    "IPO",
    "ISSUES",
    "JSON",
    "LIMIT",
    "LIVE",
    "LLM",
    "MACD",
    "MARKET",
    "MCP",
    "NEWS",
    "NONE",
    "NYSE",
    "OCR",
    "OPEN",
    "ORDER",
    "ORDERS",
    "PACKET",
    "PAPER",
    "PCE",
    "PDF",
    "PLAN",
    "PM",
    "PRICE",
    "PROFIT",
    "QQQ",
    "QTY",
    "RATIO",
    "REASON",
    "REVIEW",
    "RAM",
    "RISK",
    "ROI",
    "SCORE",
    "SEC",
    "SELL",
    "SMA",
    "SOURCE",
    "STATUS",
    "SYMBOL",
    "THIS",
    "TICK",
    "TIF",
    "TRUE",
    "URL",
    "USA",
    "USD",
    "UTC",
    "V2",
    "VOLUME",
    "WAS",
}


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _positive_decimal_or_none(value: Decimal | int | float | str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = _as_decimal(value)
    return parsed if parsed > 0 else None


def _money(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _loss_exit_review_packet(
    position: Mapping,
    *,
    generated_at: datetime.datetime,
    decision_id: str | None = None,
    side: str = "sell",
    proposed_order_id: str | None = None,
    proposed_limit_price: Decimal | int | float | str | None = None,
) -> dict:
    return loss_exit_review_packet(
        position,
        generated_at=generated_at,
        decision_id=decision_id,
        side=side,
        proposed_order_id=proposed_order_id,
        proposed_limit_price=proposed_limit_price,
    )


def _display_money(value: Decimal | int | float | str | None) -> str:
    amount = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{amount:,.2f}"


def _price(value: Decimal | int | float | str) -> str:
    return str(_as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN))

def _pct(value: Decimal | int | float | str | None) -> str:
    return str((_as_decimal(value) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _display_pct(value: Decimal | int | float | str | None) -> str:
    pct = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return f"{pct:,.2f}"


def _portfolio_unrealized_plpc(portfolio_section: Mapping) -> str:
    exposure = _as_decimal(portfolio_section.get("exposure"))
    if exposure <= 0:
        return "0.00"
    return _display_pct(_as_decimal(portfolio_section.get("unrealized_pl")) / exposure * Decimal("100"))


def _normalize_symbol(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw or raw in _NON_SYMBOL_WORDS:
        return None
    if not _SYMBOL_RE.fullmatch(raw):
        return None
    return raw


def _add_symbol(source_map: dict[str, set[str]], symbol: object, source: str) -> None:
    normalized = _normalize_symbol(symbol)
    if normalized:
        source_map.setdefault(normalized, set()).add(source)


def _add_position_symbols(
    source_map: dict[str, set[str]],
    positions: Iterable[Mapping],
    source: str,
) -> None:
    for position in positions:
        _add_symbol(source_map, position.get("symbol"), source)


def _add_order_symbols(
    source_map: dict[str, set[str]],
    orders: Iterable[Mapping],
    source: str,
) -> None:
    for order in orders:
        _add_symbol(source_map, order.get("symbol"), source)


def _add_packet_symbols(
    source_map: dict[str, set[str]],
    packet: Mapping,
    source: str,
) -> None:
    for candidate in packet.get("ranked_candidates") or []:
        if isinstance(candidate, Mapping):
            _add_symbol(source_map, candidate.get("symbol"), source)
    for action in packet.get("actions") or []:
        if isinstance(action, Mapping):
            _add_symbol(source_map, action.get("symbol"), source)
    portfolio = packet.get("portfolio") or {}
    if isinstance(portfolio, Mapping):
        for candidate in portfolio.get("ranked_candidates") or []:
            if isinstance(candidate, Mapping):
                _add_symbol(source_map, candidate.get("symbol"), source)
        for section_name in ("live", "paper"):
            section = portfolio.get(section_name) or {}
            if not isinstance(section, Mapping):
                continue
            _add_position_symbols(
                source_map,
                section.get("positions") or [],
                f"{source}:{section_name}_positions",
            )
            _add_order_symbols(
                source_map,
                section.get("open_orders") or [],
                f"{source}:{section_name}_open_orders",
            )


def _extract_symbols_from_text(text: str) -> set[str]:
    symbols = set()
    for match in _SYMBOL_RE.findall(text.upper()):
        normalized = _normalize_symbol(match)
        if normalized:
            symbols.add(normalized)
    return symbols


def build_overnight_candidate_universe(
    *,
    live_positions: Sequence[Mapping],
    paper_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    paper_open_orders: Sequence[Mapping],
    recent_supervisor_packets: Sequence[Mapping] = (),
    market_packet_paths: Sequence[str | Path] = (),
    watchlist_paths: Sequence[str | Path] = (),
    base_universe: Sequence[str] = AGGRESSIVE_CANDIDATE_UNIVERSE,
) -> list[dict]:
    source_map: dict[str, set[str]] = {}
    owned_symbols: set[str] = set()

    _add_position_symbols(source_map, live_positions, "live_positions")
    _add_position_symbols(source_map, paper_positions, "paper_positions")
    _add_order_symbols(source_map, live_open_orders, "live_open_orders")
    _add_order_symbols(source_map, paper_open_orders, "paper_open_orders")
    for position in list(live_positions) + list(paper_positions):
        normalized = _normalize_symbol(position.get("symbol") if isinstance(position, Mapping) else None)
        if normalized:
            owned_symbols.add(normalized)

    for symbol in base_universe:
        _add_symbol(source_map, symbol, "base_universe")

    for packet in recent_supervisor_packets:
        if isinstance(packet, Mapping):
            _add_packet_symbols(source_map, packet, "recent_supervisor_packet")

    for path_like in market_packet_paths:
        path = Path(path_like)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            packet = json.loads(text)
        except json.JSONDecodeError:
            packet = None
        if isinstance(packet, Mapping):
            _add_packet_symbols(source_map, packet, f"market_packet:{path.name}")
            continue
        for symbol in _extract_symbols_from_text(text):
            _add_symbol(source_map, symbol, f"market_packet:{path.name}")

    for path_like in watchlist_paths:
        path = Path(path_like)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for symbol in _extract_symbols_from_text(text):
            _add_symbol(source_map, symbol, f"watchlist:{path.name}")

    return [
        {
            "symbol": symbol,
            "sources": sorted(source_map[symbol]),
            "owned": symbol in owned_symbols,
            "research_weight": "equal",
        }
        for symbol in sorted(source_map)
    ]


def _position_snapshot(position: Mapping) -> dict:
    return {
        "symbol": str(position.get("symbol", "")).upper(),
        "qty": str(position.get("qty", "")),
        "market_value": _money(position.get("market_value", "0")),
        "cost_basis": _money(position.get("cost_basis", "0")),
        "unrealized_pl": _money(position.get("unrealized_pl", "0")),
        "unrealized_plpc": _pct(position.get("unrealized_plpc")),
        "unrealized_intraday_pl": _money(position.get("unrealized_intraday_pl", "0")),
        "unrealized_intraday_plpc": _pct(position.get("unrealized_intraday_plpc")),
        "current_price": _price(position.get("current_price", "0")),
        "avg_entry_price": _price(position.get("avg_entry_price", "0")),
    }


def _order_snapshot(order: Mapping) -> dict:
    return {
        "symbol": str(order.get("symbol", "")).upper(),
        "side": str(order.get("side", "")),
        "type": str(order.get("type", "")),
        "status": str(order.get("status", "")),
        "qty": str(order.get("qty", "")),
        "notional": str(order.get("notional", "")),
        "limit_price": str(order.get("limit_price", "")),
        "client_order_id": str(order.get("client_order_id", "")),
        "id": str(order.get("id", "")),
    }


def _client_order_component(value: object, *, max_length: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (slug[:max_length].rstrip("-") or "x")


def supervisor_live_client_order_id(
    action: HourlySupervisorAction,
    *,
    generated_at: datetime.datetime,
) -> str:
    """Stable tiny-live broker id for retry-safe supervisor submits."""

    local_day = generated_at.astimezone(CENTRAL).strftime("%Y%m%d")
    raw = "|".join(
        [
            local_day,
            action.sleeve,
            action.symbol.upper(),
            action.action.lower(),
            action.normalized_side(),
            _money(action.notional),
            _price(action.limit_price),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    parts = [
        "ta-tiny",
        local_day,
        _client_order_component(action.sleeve, max_length=8),
        _client_order_component(action.symbol, max_length=6),
        _client_order_component(action.normalized_side(), max_length=4),
        digest,
    ]
    return "-".join(parts)[:48]


def build_portfolio_snapshot(
    *,
    live_account: Mapping,
    paper_account: Mapping,
    live_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    paper_positions: Sequence[Mapping] | None = None,
    paper_open_orders: Sequence[Mapping] | None = None,
    dynamic_live_cap: Decimal = BASE_LIVE_CAP,
    market_session: str = "regular",
    candidates: Sequence[CandidateSignal] = (),
) -> dict:
    paper_positions = paper_positions or []
    paper_open_orders = paper_open_orders or []
    live_unrealized = total_unrealized_pl(live_positions)
    paper_unrealized = total_unrealized_pl(paper_positions)
    return {
        "live": {
            "status": live_account.get("status"),
            "buying_power": _money(live_account.get("buying_power", "0")),
            "equity": _money(live_account.get("equity", "0")),
            "portfolio_value": _money(live_account.get("portfolio_value") or live_account.get("equity", "0")),
            "cash": _money(live_account.get("cash", "0")),
            "exposure": _money(live_exposure_from_positions(live_positions)),
            "dynamic_cap": _money(dynamic_live_cap),
            "unused_cap": _money(max(Decimal("0"), dynamic_live_cap - live_exposure_from_positions(live_positions))),
            "unrealized_pl": _money(live_unrealized),
            "positions": [_position_snapshot(position) for position in live_positions],
            "open_orders": [_order_snapshot(order) for order in live_open_orders],
        },
        "paper": {
            "status": paper_account.get("status"),
            "buying_power": _money(paper_account.get("buying_power", "0")),
            "equity": _money(paper_account.get("equity", "0")),
            "portfolio_value": _money(paper_account.get("portfolio_value") or paper_account.get("equity", "0")),
            "cash": _money(paper_account.get("cash", "0")),
            "unrealized_pl": _money(paper_unrealized),
            "positions": [_position_snapshot(position) for position in paper_positions],
            "open_orders": [_order_snapshot(order) for order in paper_open_orders],
        },
        "market_session": market_session,
        "ranked_candidates": [
            {
                "symbol": candidate.symbol,
                "score": str(candidate.score),
                "current_price": _price(candidate.current_price),
                "day_change_pct": _pct(candidate.day_change_pct),
                "volume_ratio": str(candidate.volume_ratio),
                "time_sensitive": candidate.time_sensitive,
                "source": candidate.source,
                "reason": candidate.reason,
            }
            for candidate in candidates
        ],
    }


def validate_hourly_supervisor_actions(
    actions: Sequence[HourlySupervisorAction],
    *,
    current_live_exposure: Decimal,
    config: AlpacaExecutionConfig,
    open_orders: Sequence[Mapping] = (),
) -> list[OrderIssue]:
    issues: list[OrderIssue] = []
    open_keys = {
        (
            str(order.get("symbol", "")).upper(),
            str(order.get("side", "")).lower(),
        )
        for order in open_orders
    }

    for action in actions:
        action_name = action.action.lower()
        order_type = action.order_type.lower()
        account = action.account.lower()
        if action_name == "hold_cash":
            if action.notional < 0:
                issues.append(OrderIssue(action.symbol, "notional cannot be negative"))
            continue
        if account not in {"live", "paper"}:
            issues.append(OrderIssue(action.symbol, "order actions must target live or paper"))
        if action.asset_class.lower() != "stock":
            issues.append(OrderIssue(action.symbol, "only stock orders are allowed"))
        if order_type != "limit":
            issues.append(OrderIssue(action.symbol, "market orders are not allowed"))
        if action.normalized_side() not in {"buy", "sell"}:
            issues.append(OrderIssue(action.symbol, "only buy/sell stock orders are allowed"))
        if action_name not in {"hold", "buy", "reduce", "close", "rotate", "cancel", "hold_cash"}:
            issues.append(OrderIssue(action.symbol, f"unsupported action {action.action}"))
        if action.notional < 0:
            issues.append(OrderIssue(action.symbol, "notional cannot be negative"))
        if action.limit_price <= 0 and action_name != "hold_cash":
            issues.append(OrderIssue(action.symbol, "limit price must be positive"))
        if (action.symbol.upper(), action.normalized_side()) in open_keys:
            issues.append(OrderIssue(action.symbol, "duplicate open order for symbol and side"))

    return issues

def validate_supervisor_live_submit_allowed(
    actions: Sequence[HourlySupervisorAction],
    *,
    risk_envelope_path: str | Path = "config/risk_envelope.yaml",
    promotion_state_path: str | Path = "results/policy/promotion_state.json",
    control_state_path: str | Path = "results/policy/live_control.json",
    order_rate_state_path: str | Path = "results/policy/live_order_rate_state.json",
    current_live_exposure: Decimal = Decimal("0"),
    current_daily_loss_usd: Decimal | None = None,
    current_drawdown_pct: Decimal | None = None,
    live_account: Mapping | None = None,
    live_positions: Sequence[Mapping] = (),
    decision_evidence: Mapping | None = None,
    now: datetime.datetime | None = None,
    rate_limit_exclude_client_order_id: str | None = None,
    normal_live_commitment: Mapping[str, object] | None = None,
    normal_live_intent_full_sha256: str | None = None,
    normal_live_order_payload_sha256: str | None = None,
    normal_live_client_order_id: str | None = None,
    owner_approval: Mapping[str, object] | Sequence[Mapping[str, object]] | None = None,
    risk_envelope_expansion_approval: Mapping[str, object] | None = None,
) -> list[OrderIssue]:
    live_buying_power = None
    if isinstance(live_account, Mapping):
        try:
            live_buying_power = _as_decimal(live_account.get("buying_power"))
        except Exception:
            live_buying_power = None
    result = evaluate_go_live_guard(
        actions=actions,
        risk_envelope_path=risk_envelope_path,
        promotion_state_path=promotion_state_path,
        control_state_path=control_state_path,
        order_rate_state_path=order_rate_state_path,
        current_live_exposure=current_live_exposure,
        current_daily_loss_usd=current_daily_loss_usd,
        current_drawdown_pct=current_drawdown_pct,
        live_buying_power=live_buying_power,
        live_positions=live_positions,
        decision_evidence=decision_evidence,
        now=now,
        rate_limit_exclude_client_order_id=rate_limit_exclude_client_order_id,
        normal_live_commitment=normal_live_commitment,
        normal_live_intent_full_sha256=normal_live_intent_full_sha256,
        normal_live_order_payload_sha256=normal_live_order_payload_sha256,
        normal_live_client_order_id=normal_live_client_order_id,
        owner_approval=owner_approval,
        risk_envelope_expansion_approval=risk_envelope_expansion_approval,
    )
    return result.issues


def submit_authorized_normal_live_order(
    *,
    live_client,
    authorized_normal_trade_intent: AuthorizedNormalTradeIntent,
    activation_receipt: NormalLiveActivationReceipt,
    risk_envelope_path: str | Path,
    promotion_state_path: str | Path,
    control_state_path: str | Path,
    order_rate_state_path: str | Path,
    decision_evidence: Mapping,
    owner_approval: Mapping[str, object] | None = None,
    risk_envelope_expansion_approval: Mapping[str, object] | None = None,
) -> dict:
    """Forward one already-issued intent through the locked final gate.

    The local admission artifact is bound to one exact intent and is consumed
    under the Task 3 promotion-state lock by the Alpaca boundary.  It carries
    explicit final-gate inputs rather than a caller-provided approval boolean.
    """
    # The supervisor must never delegate the final capability to a duck-typed
    # writer.  The owned Alpaca client provides the registered read/post adapter
    # consumed by the policy handoff below.
    from tradingagents.brokers.alpaca import AlpacaRestClient

    if type(live_client) is not AlpacaRestClient:
        raise ValueError("live supervisor submit requires an owned AlpacaRestClient")
    if type(authorized_normal_trade_intent) is not AuthorizedNormalTradeIntent:
        raise ValueError(
            "live supervisor submit requires an exact AuthorizedNormalTradeIntent"
        )
    if type(activation_receipt) is not NormalLiveActivationReceipt:
        raise ValueError(
            "live supervisor submit requires an exact NormalLiveActivationReceipt"
        )
    intent = authorized_normal_trade_intent
    order = {
        "symbol": intent.symbol,
        "side": intent.side,
        "type": intent.order_type,
        "time_in_force": intent.tif,
        "notional": intent.notional_usd,
        "limit_price": intent.limit_price,
        "client_order_id": intent.client_order_id,
    }
    _preflight_normal_live_submit_local_prerequisites(
        intent,
        order_payload=order,
        risk_envelope_path=risk_envelope_path,
        control_state_path=control_state_path,
        order_rate_state_path=order_rate_state_path,
    )
    risk_metrics = _issue_normal_live_submit_risk_metrics(
        intent,
        order_payload=order,
        control_state_path=control_state_path,
        broker_read_adapter=live_client._normal_live_broker_read_adapter,
    )
    admission = _issue_normal_live_submit_admission(
        intent,
        order_payload=order,
        risk_envelope_path=risk_envelope_path,
        promotion_state_path=promotion_state_path,
        control_state_path=control_state_path,
        order_rate_state_path=order_rate_state_path,
        risk_metrics=risk_metrics,
        decision_evidence=decision_evidence,
        owner_approval=owner_approval,
        risk_envelope_expansion_approval=risk_envelope_expansion_approval,
    )
    return live_client.submit_order(
        order,
        authorized_normal_trade_intent=intent,
        activation_receipt=activation_receipt,
        supervisor_admission=admission,
    )


def build_hourly_decision(
    *,
    live_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    config: HourlySupervisorConfig,
    candidate_signals: Sequence[CandidateSignal] = (),
    market_session: str = "regular",
    dynamic_live_cap: Decimal = BASE_LIVE_CAP,
    new_buys_suspended_reason: str | None = None,
    live_sleeve: str | None = None,
) -> HourlySupervisorDecision:
    return _build_hourly_decision(
        live_positions=live_positions,
        live_open_orders=live_open_orders,
        config=config,
        candidate_signals=candidate_signals,
        market_session=market_session,
        dynamic_live_cap=dynamic_live_cap,
        new_buys_suspended_reason=new_buys_suspended_reason,
        can_trade_session=can_trade_session,
        positive_decimal_or_none=_positive_decimal_or_none,
        live_sleeve=live_sleeve or LIVE_AGGRESSIVE_SLEEVE,
    )


def build_hourly_evidence(
    *,
    live_account: Mapping,
    paper_account: Mapping,
    live_positions: Sequence[Mapping],
    live_open_orders: Sequence[Mapping],
    previous_packet: Path | None = None,
    overnight_validation: Mapping | None = None,
    premarket_brief_validation: Mapping | None = None,
) -> dict:
    return _build_hourly_evidence(
        live_account=live_account,
        paper_account=paper_account,
        live_positions=live_positions,
        live_open_orders=live_open_orders,
        previous_packet=previous_packet,
        overnight_validation=overnight_validation,
        premarket_brief_validation=premarket_brief_validation,
    )


def serialize_hourly_decision(
    decision: HourlySupervisorDecision,
    *,
    recent_packets: Sequence[Mapping] = (),
    alert_throttle_window: datetime.timedelta = DEFAULT_ALERT_THROTTLE_WINDOW,
) -> dict:
    return _serialize_hourly_decision(
        decision,
        recent_packets=recent_packets,
        alert_throttle_window=alert_throttle_window,
        classify_alert=classify_supervisor_alert,
        alert_fingerprint=supervisor_alert_fingerprint,
        should_throttle_alert=should_throttle_supervisor_alert,
        render_alert_email=render_supervisor_alert_email,
        client_order_id=supervisor_live_client_order_id,
        is_order_action=is_order_action,
    )


def write_hourly_decision_packet(
    decision: HourlySupervisorDecision,
    *,
    output_dir: str | Path = "results/hourly_supervisor",
    recent_packets: Sequence[Mapping] = (),
    alert_throttle_window: datetime.timedelta = DEFAULT_ALERT_THROTTLE_WINDOW,
    packet_metadata: Mapping[str, Any] | None = None,
) -> Path:
    return _write_hourly_decision_packet(
        decision,
        serialize_decision=serialize_hourly_decision,
        output_dir=output_dir,
        recent_packets=recent_packets,
        alert_throttle_window=alert_throttle_window,
        packet_metadata=packet_metadata,
    )
