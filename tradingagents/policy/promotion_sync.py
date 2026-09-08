"""Production bridge from paper-tournament evidence to live promotion state.

Historically ``results/policy/promotion_state.json`` was hand-authored and the
paper tournament's winner was written only as an advisory
``live-strategy-selection.json`` that nothing consumed. This module closes
that gap deterministically:

- the tournament's ``live_strategy_candidate`` can earn a real promotion
  record (``evaluate_sleeve_promotion`` gates plus drawdown/win-rate quality
  gates), and
- any live-enabled sleeve whose own tournament evidence has turned negative
  over a full evaluation window is demoted to ``paper_only``.

The output schema stays compatible with ``tradingagents.policy.live_gate``:
per-sleeve records keep ``stage``, ``live_enabled``, the named gate booleans,
``validation_report_ref``, and ``risk_envelope_ref``.

This module never submits orders. ``arm_live`` only marks a sleeve
live-enabled inside the promotion file; every live order still has to pass
the unified go-live guard (risk envelope, dead-man control, buying power,
limit-only checks) at submit time.
"""

from __future__ import annotations

import base64
import datetime
import fcntl
import hashlib
import json
import os
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.promotion import (
    SleevePromotionDecision,
    SleevePromotionEvidence,
    _write_promotion_state_unlocked,
    build_promotion_state,
    evaluate_sleeve_promotion,
)
from tradingagents.policy.strategy_promotion import INTERNAL_EVIDENCE_MAX_AGE_SECONDS

UTC = datetime.timezone.utc


def _owner_approval_authority_utc_now() -> datetime.datetime:
    """Return the policy-owned clock for owner-approval authority.

    Tournament ``generated_at`` / ``now`` values are reproducibility evidence,
    not authority.  Keep this private zero-argument seam so isolated tests can
    choose a deterministic policy clock without exposing a caller-controlled
    runtime or CLI override.
    """

    return datetime.datetime.now(tz=UTC)

#: Sleeves that are preregistered by construction: they exist as named,
#: deterministic strategies in the paper tournament code and methodology docs.
PREREGISTERED_TOURNAMENT_SLEEVES = (
    "current-aggressive",
    "pullback-support",
    "catalyst-relative-strength",
)

#: Evidence-quality gates applied on top of the base promotion gates.
MIN_TRACKED_DAYS = 5
MAX_DRAWDOWN_FLOOR_PCT = Decimal("-10")
MIN_WIN_RATE_PCT = Decimal("50")

DEFAULT_VALIDATION_REPORT_REF = "results/paper_strategy_tournament/latest.json"
DEFAULT_RISK_ENVELOPE_REF = "config/risk_envelope.yaml"

_PROMOTION_STATE_V1_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "generated_at", "sleeves"}
)
_PROMOTION_STATE_V1_LEGACY_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "sleeves"}
)
_PROMOTION_STATE_V1_1_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "generated_at", "source", "sleeves"}
)
_PROMOTION_SYNC_SOURCE_KEYS = frozenset(
    {
        "kind",
        "tournament_id",
        "report_generated_at",
        "arm_live",
        "ci_green",
    }
)
_PROMOTION_RECORD_REQUIRED_KEYS = frozenset(
    {
        "stage",
        "live_enabled",
        "ci_green",
        "shadow_confirmed",
        "preregistered",
        "benchmark_gate_passed",
        "cost_gate_passed",
        "recent_alpha_gate_passed",
        "capacity_gate_passed",
        "validation_report_ref",
        "risk_envelope_ref",
    }
)
_PROMOTION_RECORD_OPTIONAL_KEYS = frozenset(
    {
        "promoted_at",
        "demoted_at",
        "demotion_reason",
        "metrics",
        "issues",
        "source",
        "evidence_metrics",
    }
)
_PROMOTION_METRIC_KEYS = frozenset(
    {
        "benchmark_excess_return",
        "cost_adjusted_alpha",
        "recent_alpha",
        "capacity_usd",
        "requested_tiny_live_tranche_usd",
    }
)
_PROMOTION_RECORD_SOURCE_KEYS = frozenset(
    {
        "kind",
        "tournament_id",
        "report_generated_at",
        "candidate_reason",
    }
)

#: Public mirror of the authoritative persisted paper_tournament provenance
#: schema for consumers (policy.live_gate) that must fail closed on any
#: deviation from the writer-side source requirements.
PAPER_TOURNAMENT_RECORD_SOURCE_KEYS = _PROMOTION_RECORD_SOURCE_KEYS
_PROMOTION_EVIDENCE_METRIC_KEYS = frozenset(
    {
        "total_return",
        "total_return_pct",
        "max_drawdown_pct",
        "win_rate_pct",
        "tracked_days",
    }
)


@dataclass(frozen=True)
class PromotionSyncResult:
    state: dict
    promoted: list[str]
    demoted: list[str]
    unchanged: list[str]
    issues_by_sleeve: dict[str, list[str]] = field(default_factory=dict)
    summary: str = ""


@dataclass(frozen=True)
class LegacyReadinessSupersessionResult:
    state: dict
    prepared_receipt_path: Path
    completed_receipt_path: Path
    resumed: bool


def build_current_readiness_packet(
    *,
    supersession_receipt_path: str | Path,
    promotion_state_path: str | Path,
    live_control_path: str | Path,
    schedule_contract_path: str | Path,
    automation_root: str | Path,
    role_contract_path: str | Path,
    now: datetime.datetime,
) -> dict[str, object]:
    """Build an authority-free readiness packet from current verified files."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    generated_at = now.astimezone(UTC).isoformat(timespec="seconds")
    receipt_path = Path(supersession_receipt_path).resolve()
    state_path = Path(promotion_state_path).resolve()
    control_path = Path(live_control_path).resolve()
    completed_bytes = receipt_path.read_bytes()
    completed = _read_json_object(
        completed_bytes, field="completed supersession receipt"
    )
    if (
        completed.get("schema_version") != "1.0.0"
        or completed.get("status") != "completed"
        or completed.get("analysis_only") is not True
        or completed.get("execution_authority") != "none"
        or completed.get("can_promote") is not False
        or completed.get("can_submit_orders") is not False
        or completed.get("reason") != "economic qualification pending"
    ):
        raise ValueError("completed supersession receipt is not authority-free")
    artifacts = completed.get("artifacts")
    prepared_ref = completed.get("prepared_receipt")
    if not isinstance(artifacts, Mapping) or not isinstance(prepared_ref, Mapping):
        raise ValueError("completed supersession receipt bindings are invalid")
    state_before = artifacts.get("promotion_state_before")
    if (
        not isinstance(state_before, Mapping)
        or state_before.get("path") != str(state_path)
    ):
        raise ValueError("supersession receipt names a different promotion state")
    prepared_path = Path(str(prepared_ref.get("path", ""))).resolve()
    prepared_bytes = prepared_path.read_bytes()
    if prepared_ref.get("sha256") != _sha256(prepared_bytes):
        raise ValueError("prepared supersession receipt digest mismatch")
    prepared = _read_json_object(prepared_bytes, field="prepared supersession receipt")
    if (
        prepared.get("schema_version") != "1.0.0"
        or prepared.get("status") != "prepared"
        or prepared.get("artifacts") != artifacts
        or prepared.get("analysis_only") is not True
        or prepared.get("execution_authority") != "none"
        or prepared.get("can_promote") is not False
        or prepared.get("can_submit_orders") is not False
        or prepared.get("reason") != "economic qualification pending"
    ):
        raise ValueError("prepared supersession receipt is invalid")

    try:
        before_bytes = base64.b64decode(
            str(prepared.get("promotion_state_before_base64", "")), validate=True
        )
    except ValueError as exc:
        raise ValueError("prepared supersession before-image is invalid") from exc
    before_binding = artifacts.get("promotion_state_before")
    if (
        not isinstance(before_binding, Mapping)
        or before_binding.get("sha256") != _sha256(before_bytes)
    ):
        raise ValueError("prepared supersession before-image digest mismatch")
    operation_iso = prepared.get("prepared_at")
    if type(operation_iso) is not str:
        raise ValueError("prepared supersession timestamp is invalid")
    try:
        operation_now = datetime.datetime.fromisoformat(operation_iso)
    except ValueError as exc:
        raise ValueError("prepared supersession timestamp is invalid") from exc
    if operation_now.tzinfo is None or operation_now.utcoffset() is None:
        raise ValueError("prepared supersession timestamp is invalid")
    before_state = _validate_existing_promotion_state(
        _read_json_object(before_bytes, field="prepared promotion before-image")
    )
    expected_decisions = _paper_only_decisions(
        before_state,
        now_iso=operation_iso,
        reason="economic qualification pending",
    )
    expected_state = build_promotion_state(
        expected_decisions, generated_at=operation_iso
    )
    expected_state_bytes = json.dumps(expected_state, indent=2).encode("utf-8")
    if (
        prepared.get("promotion_state_after") != expected_state
        or prepared.get("promotion_state_after_sha256")
        != _sha256(expected_state_bytes)
    ):
        raise ValueError("prepared supersession state is not derived from before-image")

    state_bytes = state_path.read_bytes()
    state_sha256 = _sha256(state_bytes)
    if (
        completed.get("promotion_state_after_sha256") != state_sha256
        or prepared.get("promotion_state_after_sha256") != state_sha256
    ):
        raise ValueError("current promotion state does not match supersession")
    state = _validate_existing_promotion_state(
        _read_json_object(state_bytes, field="current promotion state")
    )
    if state_bytes != expected_state_bytes or expected_state != state:
        raise ValueError("prepared supersession state does not match current state")
    sleeves = state["sleeves"]
    if not sleeves or any(
        record.get("stage") != "paper_only"
        or record.get("live_enabled") is not False
        or record.get("demotion_reason") != "economic qualification pending"
        for record in sleeves.values()
    ):
        raise ValueError("every current sleeve must remain paper-only and live-disabled")

    control_bytes = control_path.read_bytes()
    control = _read_json_object(control_bytes, field="live control")
    if control.get("frozen") is not True:
        raise ValueError("live control is not frozen")

    from tradingagents.evals.automation_health_audit import (
        PREDEPLOYMENT_PAUSED_PHASE,
        capture_schedule_contract_snapshot,
        evaluate_schedule_contract,
        schedule_contract_snapshot_manifest,
    )

    snapshot = capture_schedule_contract_snapshot(
        contract_path=schedule_contract_path,
        automation_root=automation_root,
        role_contract_path=role_contract_path,
        captured_at=now,
    )
    manifest = schedule_contract_snapshot_manifest(snapshot)
    schedule = evaluate_schedule_contract(
        deployment_phase=PREDEPLOYMENT_PAUSED_PHASE,
        captured_snapshot=snapshot,
    )
    rows = schedule.get("automations")
    automation_sources = manifest.get("automation_tomls")
    if (
        manifest.get("capture_issues")
        or schedule.get("contract_status") != "pass"
        or schedule.get("safe_predeployment") is not True
        or schedule.get("paused_count") != 10
        or schedule.get("configured_count") != 10
        or not isinstance(rows, list)
        or len(rows) != 10
        or any(
            not isinstance(row, Mapping)
            or row.get("status") != "match"
            or row.get("config_status") != "PAUSED"
            for row in rows
        )
        or not isinstance(automation_sources, list)
        or len(automation_sources) != 10
    ):
        raise ValueError("ten paused automations were not verified")
    paused = [
        {"automation_id": source["automation_id"], "sha256": source["sha256"]}
        for source in sorted(
            automation_sources, key=lambda item: str(item.get("automation_id"))
        )
    ]
    return {
        "schema_version": "trading_readiness_packet/v1",
        "generated_at": generated_at,
        "readiness_status": "NOT_ESTABLISHED",
        "profitability": "NOT_ESTABLISHED",
        "economic_qualification": "pending",
        "shadow_phase": "qualification_pending",
        "historical_go_status": "superseded_historical",
        "all_sleeves_paper_only": True,
        "all_sleeves_live_disabled": True,
        "sleeve_ids": sorted(sleeves),
        "promotion_state": {"path": str(state_path), "sha256": state_sha256},
        "supersession_receipt": {
            "path": str(receipt_path),
            "sha256": _sha256(completed_bytes),
        },
        "live_control": {
            "path": str(control_path),
            "sha256": _sha256(control_bytes),
            "frozen": True,
        },
        "paused_automations": paused,
        "paused_automation_count": 10,
        "runtime_transition_executed": False,
        "compact_context_refreshed": False,
        "tsm_board_review_executed": False,
        "analysis_only": True,
        "execution_authority": "none",
        "can_promote": False,
        "can_submit_orders": False,
    }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: str, *, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _write_immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    """Create a durable receipt without ever replacing an existing receipt."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _read_json_object(payload: bytes, *, field: str) -> dict:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must be valid UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ValueError(f"{field} must be a JSON object")
    return value


def _paper_only_decisions(
    state: Mapping[str, object], *, now_iso: str, reason: str
) -> list[SleevePromotionDecision]:
    decisions: list[SleevePromotionDecision] = []
    sleeves = state["sleeves"]
    assert isinstance(sleeves, dict)  # established by the strict validator
    for sleeve_id, before_record in sleeves.items():
        record = dict(before_record)
        issues = list(record.get("issues") or [])
        if reason not in issues:
            issues.append(reason)
        record.update(
            {
                "stage": "paper_only",
                "live_enabled": False,
                "demoted_at": now_iso,
                "demotion_reason": reason,
                "issues": issues,
            }
        )
        decisions.append(
            SleevePromotionDecision(
                sleeve=sleeve_id,
                stage="paper_only",
                live_enabled=False,
                passed=False,
                gates={},
                issues=issues,
                state=record,
            )
        )
    return decisions


def supersede_legacy_readiness(
    *,
    go_packet_path: str | Path,
    promotion_state_path: str | Path,
    expired_tournament_ledger_path: str | Path,
    receipt_path: str | Path,
    expected_go_packet_sha256: str,
    expected_promotion_state_sha256: str,
    expected_expired_tournament_sha256: str,
    now: datetime.datetime,
    reason: str = "economic qualification pending",
) -> LegacyReadinessSupersessionResult:
    """Retire legacy readiness evidence without turning it into authority.

    A prepared receipt makes an interrupted state replacement recoverable.  A
    completed receipt is created only after the trusted promotion writer's
    exact output is visible.  Historical inputs are read and reverified, never
    rewritten or deleted.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if reason != "economic qualification pending":
        raise ValueError("unverified economic verdicts cannot supersede readiness")
    expected_go_packet_sha256 = _require_sha256(
        expected_go_packet_sha256, field="expected_go_packet_sha256"
    )
    expected_promotion_state_sha256 = _require_sha256(
        expected_promotion_state_sha256, field="expected_promotion_state_sha256"
    )
    expected_expired_tournament_sha256 = _require_sha256(
        expected_expired_tournament_sha256,
        field="expected_expired_tournament_sha256",
    )
    go_path = Path(go_packet_path).resolve()
    state_path = Path(promotion_state_path).resolve()
    tournament_path = Path(expired_tournament_ledger_path).resolve()
    completed_path = Path(receipt_path).resolve()
    prepared_path = completed_path.with_name(completed_path.name + ".prepared")
    all_paths = {go_path, state_path, tournament_path, completed_path, prepared_path}
    if len(all_paths) != 5:
        raise ValueError("supersession inputs and receipts must use distinct paths")

    now_iso = now.isoformat(timespec="seconds")
    expected_artifacts = {
        "historical_go_packet": {
            "path": str(go_path),
            "sha256": expected_go_packet_sha256,
        },
        "promotion_state_before": {
            "path": str(state_path),
            "sha256": expected_promotion_state_sha256,
        },
        "expired_tournament_ledger": {
            "path": str(tournament_path),
            "sha256": expected_expired_tournament_sha256,
        },
    }

    with promotion_state_lock(state_path):
        go_bytes = go_path.read_bytes()
        tournament_bytes = tournament_path.read_bytes()
        if _sha256(go_bytes) != expected_go_packet_sha256:
            raise ValueError("historical GO packet digest mismatch")
        if _sha256(tournament_bytes) != expected_expired_tournament_sha256:
            raise ValueError("expired tournament ledger digest mismatch")
        go_packet = _read_json_object(go_bytes, field="historical GO packet")
        if go_packet.get("decision") != "GO":
            raise ValueError("historical GO packet decision must be 'GO'")
        from tradingagents.brokers.paper_tournament import (
            fingerprint_expired_tournament_ledger,
        )

        tournament_identity = fingerprint_expired_tournament_ledger(
            tournament_bytes, now=now
        )
        current_bytes = state_path.read_bytes()

        prepared: dict | None = None
        if prepared_path.exists():
            prepared = _read_json_object(
                prepared_path.read_bytes(), field="prepared supersession receipt"
            )
            if (
                prepared.get("schema_version") != "1.0.0"
                or prepared.get("status") != "prepared"
                or prepared.get("artifacts") != expected_artifacts
                or prepared.get("reason") != reason
                or prepared.get("analysis_only") is not True
                or prepared.get("execution_authority") != "none"
                or prepared.get("can_promote") is not False
                or prepared.get("can_submit_orders") is not False
                or prepared.get("expired_tournament_identity")
                != tournament_identity
            ):
                raise ValueError("prepared supersession receipt is foreign or stale")
            operation_iso = prepared.get("prepared_at")
            if type(operation_iso) is not str:
                raise ValueError("prepared supersession receipt timestamp is invalid")
            operation_now = datetime.datetime.fromisoformat(operation_iso)
            if operation_now.tzinfo is None or operation_now.utcoffset() is None:
                raise ValueError("prepared supersession receipt timestamp is invalid")
            after_state = prepared.get("promotion_state_after")
            if type(after_state) is not dict:
                raise ValueError("prepared supersession receipt has no exact after-state")
            try:
                after_bytes = base64.b64decode(
                    str(prepared.get("promotion_state_after_base64", "")),
                    validate=True,
                )
            except ValueError as exc:
                raise ValueError(
                    "prepared supersession after-state bytes are invalid"
                ) from exc
            if _read_json_object(after_bytes, field="promotion state after-image") != after_state:
                raise ValueError("prepared supersession after-state bytes mismatch")
            if prepared.get("promotion_state_after_sha256") != _sha256(after_bytes):
                raise ValueError("prepared supersession after-state digest mismatch")
            before_bytes = base64.b64decode(
                str(prepared.get("promotion_state_before_base64", "")),
                validate=True,
            )
            if _sha256(before_bytes) != expected_promotion_state_sha256:
                raise ValueError("prepared supersession before-image mismatch")
            decisions = _paper_only_decisions(
                _validate_existing_promotion_state(
                    _read_json_object(before_bytes, field="promotion state before-image")
                ),
                now_iso=operation_iso,
                reason=reason,
            )
            expected_after_state = build_promotion_state(
                decisions, generated_at=operation_iso
            )
            expected_after_bytes = json.dumps(expected_after_state, indent=2).encode(
                "utf-8"
            )
            if (
                after_state != expected_after_state
                or after_bytes != expected_after_bytes
                or prepared.get("promotion_state_after_sha256")
                != _sha256(expected_after_bytes)
            ):
                raise ValueError(
                    "prepared supersession after-state was not derived from its before-image"
                )
            after_state = expected_after_state
            after_bytes = expected_after_bytes
            if current_bytes not in {before_bytes, expected_after_bytes}:
                raise ValueError("promotion state changed outside prepared supersession")
        else:
            operation_iso = now_iso
            operation_now = now
            if _sha256(current_bytes) != expected_promotion_state_sha256:
                raise ValueError("promotion state before-image digest mismatch")
            before_bytes = current_bytes
            before_state = _validate_existing_promotion_state(
                _read_json_object(before_bytes, field="promotion state")
            )
            decisions = _paper_only_decisions(
                before_state, now_iso=operation_iso, reason=reason
            )
            after_state = build_promotion_state(decisions, generated_at=operation_iso)
            after_bytes = json.dumps(after_state, indent=2).encode("utf-8")
            prepared = {
                "schema_version": "1.0.0",
                "status": "prepared",
                "prepared_at": operation_iso,
                "reason": reason,
                "analysis_only": True,
                "execution_authority": "none",
                "can_promote": False,
                "can_submit_orders": False,
                "artifacts": expected_artifacts,
                "expired_tournament_identity": tournament_identity,
                "promotion_state_before_base64": base64.b64encode(before_bytes).decode(
                    "ascii"
                ),
                "promotion_state_after": after_state,
                "promotion_state_after_base64": base64.b64encode(after_bytes).decode(
                    "ascii"
                ),
                "promotion_state_after_sha256": _sha256(after_bytes),
            }
            _write_immutable_json(prepared_path, prepared)

        if current_bytes == before_bytes:
            # The lock is already held, so use the trusted writer's explicitly
            # unlocked seam rather than creating an independent state writer.
            _write_promotion_state_unlocked(state_path, decisions, now=operation_now)
        written_bytes = state_path.read_bytes()
        if written_bytes != after_bytes:
            raise ValueError("trusted promotion replacement did not match prepared state")
        if _sha256(go_path.read_bytes()) != expected_go_packet_sha256:
            raise ValueError("historical GO packet changed during supersession")
        if _sha256(tournament_path.read_bytes()) != expected_expired_tournament_sha256:
            raise ValueError("expired tournament ledger changed during supersession")

        prepared_sha256 = _sha256(prepared_path.read_bytes())
        completed = {
            "schema_version": "1.0.0",
            "status": "completed",
            "completed_at": operation_iso,
            "reason": reason,
            "analysis_only": True,
            "execution_authority": "none",
            "can_promote": False,
            "can_submit_orders": False,
            "artifacts": expected_artifacts,
            "prepared_receipt": {
                "path": str(prepared_path),
                "sha256": prepared_sha256,
            },
            "promotion_state_after_sha256": _sha256(after_bytes),
        }
        if completed_path.exists():
            if _read_json_object(
                completed_path.read_bytes(), field="completed supersession receipt"
            ) != completed:
                raise ValueError("completed supersession receipt is foreign or stale")
        else:
            _write_immutable_json(completed_path, completed)
        return LegacyReadinessSupersessionResult(
            state=after_state,
            prepared_receipt_path=prepared_path,
            completed_receipt_path=completed_path,
            resumed=current_bytes == after_bytes,
        )


def promotion_state_lock_path(state_path: str | Path) -> Path:
    state_file = Path(state_path).resolve()
    return state_file.with_name(f".{state_file.name}.recovery.lock")


@contextmanager
def promotion_state_lock(state_path: str | Path):
    """Serialize every canonical promotion-state read/replace."""

    lock_path = promotion_state_lock_path(state_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield lock_path
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _now_iso(now: datetime.datetime | None = None) -> str:
    moment = now or datetime.datetime.now(tz=UTC)
    return moment.isoformat(timespec="seconds")


def _as_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _ranking_for(report: Mapping, sleeve_id: str) -> Mapping | None:
    for ranking in report.get("rankings") or []:
        if ranking.get("strategy_id") == sleeve_id:
            return ranking
    return None


def _quality_gate_issues(ranking: Mapping) -> list[str]:
    issues: list[str] = []
    tracked_days = int(ranking.get("tracked_days") or 0)
    if tracked_days < MIN_TRACKED_DAYS:
        issues.append(
            f"tracked_days {tracked_days} is below the {MIN_TRACKED_DAYS}-day floor"
        )
    drawdown = _as_decimal(ranking.get("max_drawdown_pct"))
    if drawdown < MAX_DRAWDOWN_FLOOR_PCT:
        issues.append(
            f"max_drawdown_pct {drawdown} breaches the {MAX_DRAWDOWN_FLOOR_PCT}% floor"
        )
    win_rate = _as_decimal(ranking.get("win_rate_pct"))
    if win_rate < MIN_WIN_RATE_PCT:
        issues.append(
            f"win_rate_pct {win_rate} is below the {MIN_WIN_RATE_PCT}% floor"
        )
    return issues


def build_tournament_promotion_evidence(
    report: Mapping,
    sleeve_id: str,
    *,
    incumbent_sleeve_id: str | None,
    tiny_live_tranche_usd: Decimal,
    ci_green: bool,
    validation_report_ref: str = DEFAULT_VALIDATION_REPORT_REF,
    risk_envelope_ref: str = DEFAULT_RISK_ENVELOPE_REF,
) -> SleevePromotionEvidence | None:
    ranking = _ranking_for(report, sleeve_id)
    if ranking is None:
        return None
    return_pct = _as_decimal(ranking.get("total_return_pct"))
    incumbent_return_pct = Decimal("0")
    if incumbent_sleeve_id and incumbent_sleeve_id != sleeve_id:
        incumbent = _ranking_for(report, incumbent_sleeve_id)
        if incumbent is not None:
            incumbent_return_pct = _as_decimal(incumbent.get("total_return_pct"))
    tracked_days = int(ranking.get("tracked_days") or 0)
    return SleevePromotionEvidence(
        sleeve=sleeve_id,
        preregistered=sleeve_id in PREREGISTERED_TOURNAMENT_SLEEVES,
        ci_green=ci_green,
        # Paper tournament runs are the shadow lane for these sleeves: the
        # sleeve traded the full evaluation window without live authority.
        shadow_confirmed=tracked_days >= MIN_TRACKED_DAYS,
        # Benchmark baseline is flat cash (0%): the sleeve must have made
        # money at all before live consideration.
        benchmark_excess_return=return_pct,
        # Orders are limit-only equities with zero commission; no separate
        # cost model exists yet, so cost-adjusted alpha equals raw return.
        cost_adjusted_alpha=return_pct,
        # Recent alpha is measured against the incumbent live sleeve over the
        # same tournament window.
        recent_alpha=return_pct - incumbent_return_pct,
        capacity_usd=_as_decimal(ranking.get("equity")),
        requested_tiny_live_tranche_usd=tiny_live_tranche_usd,
        validation_report_ref=validation_report_ref,
        risk_envelope_ref=risk_envelope_ref,
    )


def _report_evidence_age_issue(
    report: Mapping, *, now: datetime.datetime
) -> str | None:
    """Return a demotion-grade freshness complaint about the report, if any.

    The tournament ``generated_at`` stamp must already be strict canonical
    UTC evidence: missing, malformed, timezone-naive, non-UTC-offset,
    Z-suffixed, sub-second, future-dated, or reports at or beyond the
    internal-evidence age ceiling are all rejected outright.
    """

    raw = report.get("generated_at")
    if type(raw) is not str or not raw:
        return "tournament report generated_at is missing"
    try:
        moment = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return f"tournament report generated_at is invalid: {raw!r}"
    if moment.tzinfo is None or moment.utcoffset() is None:
        return (
            f"tournament report generated_at {raw} is timezone-naive and is "
            "not canonical UTC evidence"
        )
    if (
        moment.utcoffset() != datetime.timedelta(0)
        or moment.microsecond
        or moment.isoformat(timespec="seconds") != raw
    ):
        return (
            f"tournament report generated_at {raw} is not canonical UTC: it "
            "must already be tz-aware UTC at second precision with an exact "
            "+00:00 isoformat round trip"
        )
    if moment > now:
        return f"tournament report generated_at {raw} is in the future"
    if now - moment >= datetime.timedelta(seconds=INTERNAL_EVIDENCE_MAX_AGE_SECONDS):
        return (
            f"tournament report generated_at {raw} is stale: older than the "
            f"{INTERNAL_EVIDENCE_MAX_AGE_SECONDS}-second internal-evidence ceiling"
        )
    return None


def _demoted_record(
    existing: Mapping,
    ranking: Mapping,
    *,
    now_iso: str,
    validation_report_ref: str,
    demotion_reason: str | None = None,
) -> dict:
    record = dict(existing)
    record["stage"] = "paper_only"
    record["live_enabled"] = False
    record["benchmark_gate_passed"] = False
    record["recent_alpha_gate_passed"] = False
    record["demoted_at"] = now_iso
    if demotion_reason is None:
        record["demotion_reason"] = (
            "tournament evidence turned negative: total_return "
            f"{ranking.get('total_return')} ({ranking.get('total_return_pct')}%) "
            f"over {ranking.get('tracked_days')} tracked day(s) with win rate "
            f"{ranking.get('win_rate_pct')}%"
        )
    else:
        record["demotion_reason"] = demotion_reason
    record["validation_report_ref"] = validation_report_ref
    return record


def _require_exact_keys(value: dict, expected: frozenset[str], *, field: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"existing promotion state {field} has invalid fields "
            f"(missing={missing}, extra={extra})"
        )


def _require_string(value: Any, *, field: str, allow_none: bool = False) -> None:
    if allow_none and value is None:
        return
    if type(value) is not str or not value:
        raise ValueError(
            f"existing promotion state {field} must be a non-empty string"
        )


def _validate_promotion_record(record: Any, *, sleeve_id: str) -> None:
    field = f"sleeves.{sleeve_id}"
    if type(record) is not dict:
        raise ValueError(f"existing promotion state {field} must be a JSON object")

    actual_keys = frozenset(record)
    missing = sorted(_PROMOTION_RECORD_REQUIRED_KEYS - actual_keys)
    extra = sorted(
        actual_keys
        - _PROMOTION_RECORD_REQUIRED_KEYS
        - _PROMOTION_RECORD_OPTIONAL_KEYS
    )
    if missing or extra:
        raise ValueError(
            f"existing promotion state {field} has invalid fields "
            f"(missing={missing}, extra={extra})"
        )

    if record["stage"] not in {"paper_only", "tiny_live_eligible"}:
        raise ValueError(
            f"existing promotion state {field}.stage has an invalid value"
        )
    for name in (
        "live_enabled",
        "ci_green",
        "shadow_confirmed",
        "preregistered",
        "benchmark_gate_passed",
        "cost_gate_passed",
        "recent_alpha_gate_passed",
        "capacity_gate_passed",
    ):
        if type(record[name]) is not bool:
            raise ValueError(
                f"existing promotion state {field}.{name} must be a boolean"
            )
    for name in ("validation_report_ref", "risk_envelope_ref"):
        _require_string(record[name], field=f"{field}.{name}")

    for name in ("promoted_at", "demoted_at", "demotion_reason"):
        if name in record:
            _require_string(record[name], field=f"{field}.{name}")
    if ("demoted_at" in record) != ("demotion_reason" in record):
        raise ValueError(
            f"existing promotion state {field} must bind demoted_at and "
            "demotion_reason together"
        )

    if "metrics" in record:
        metrics = record["metrics"]
        if type(metrics) is not dict:
            raise ValueError(
                f"existing promotion state {field}.metrics must be a JSON object"
            )
        _require_exact_keys(metrics, _PROMOTION_METRIC_KEYS, field=f"{field}.metrics")
        for name, value in metrics.items():
            _require_string(value, field=f"{field}.metrics.{name}")

    if "issues" in record:
        issues = record["issues"]
        if type(issues) is not list or any(type(issue) is not str for issue in issues):
            raise ValueError(
                f"existing promotion state {field}.issues must be a list of strings"
            )

    has_source = "source" in record
    has_evidence_metrics = "evidence_metrics" in record
    if has_source != has_evidence_metrics:
        raise ValueError(
            f"existing promotion state {field} must bind source and "
            "evidence_metrics together"
        )
    if has_source:
        source = record["source"]
        if type(source) is not dict:
            raise ValueError(
                f"existing promotion state {field}.source must be a JSON object"
            )
        _require_exact_keys(
            source,
            _PROMOTION_RECORD_SOURCE_KEYS,
            field=f"{field}.source",
        )
        if source["kind"] != "paper_tournament":
            raise ValueError(
                f"existing promotion state {field}.source.kind has an invalid value"
            )
        for name in ("tournament_id", "report_generated_at", "candidate_reason"):
            _require_string(
                source[name],
                field=f"{field}.source.{name}",
                allow_none=True,
            )

        evidence_metrics = record["evidence_metrics"]
        if type(evidence_metrics) is not dict:
            raise ValueError(
                f"existing promotion state {field}.evidence_metrics must be a "
                "JSON object"
            )
        _require_exact_keys(
            evidence_metrics,
            _PROMOTION_EVIDENCE_METRIC_KEYS,
            field=f"{field}.evidence_metrics",
        )
        for name in _PROMOTION_EVIDENCE_METRIC_KEYS - {"tracked_days"}:
            _require_string(
                evidence_metrics[name],
                field=f"{field}.evidence_metrics.{name}",
            )
        if (
            type(evidence_metrics["tracked_days"]) is not int
            or evidence_metrics["tracked_days"] < 0
        ):
            raise ValueError(
                f"existing promotion state {field}.evidence_metrics.tracked_days "
                "must be a non-negative integer"
            )


def _validate_existing_promotion_state(state: Any) -> dict:
    """Accept only persisted shapes this module can preserve without data loss."""

    if type(state) is not dict:
        raise ValueError("existing promotion state must be a JSON object")
    schema_version = state.get("schema_version")
    if schema_version == "1.0.0":
        if frozenset(state) not in {
            _PROMOTION_STATE_V1_LEGACY_TOP_LEVEL_KEYS,
            _PROMOTION_STATE_V1_TOP_LEVEL_KEYS,
        }:
            expected = (
                _PROMOTION_STATE_V1_TOP_LEVEL_KEYS
                if "generated_at" in state
                else _PROMOTION_STATE_V1_LEGACY_TOP_LEVEL_KEYS
            )
            _require_exact_keys(state, expected, field="top level")
        if "generated_at" in state:
            _require_string(state["generated_at"], field="generated_at")
    elif schema_version == "1.1.0":
        _require_exact_keys(
            state,
            _PROMOTION_STATE_V1_1_TOP_LEVEL_KEYS,
            field="top level",
        )
        _require_string(state["generated_at"], field="generated_at")
        source = state["source"]
        if type(source) is not dict:
            raise ValueError(
                "existing promotion state source must be a JSON object"
            )
        expected_source_keys = _PROMOTION_SYNC_SOURCE_KEYS
        if "canonical_input_sha256" in source:
            expected_source_keys = expected_source_keys | {"canonical_input_sha256"}
        _require_exact_keys(source, expected_source_keys, field="source")
        if source["kind"] != "paper_tournament_sync":
            raise ValueError("existing promotion state source.kind has an invalid value")
        for name in ("tournament_id", "report_generated_at"):
            _require_string(source[name], field=f"source.{name}", allow_none=True)
        for name in ("arm_live", "ci_green"):
            if type(source[name]) is not bool:
                raise ValueError(
                    f"existing promotion state source.{name} must be a boolean"
                )
        if "canonical_input_sha256" in source:
            digest = source["canonical_input_sha256"]
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(
                    "existing promotion state source.canonical_input_sha256 "
                    "must be a lowercase SHA-256 digest"
                )
    else:
        raise ValueError(
            "existing promotion state schema_version must be '1.0.0' or '1.1.0'"
        )

    sleeves = state["sleeves"]
    if type(sleeves) is not dict:
        raise ValueError("existing promotion state sleeves must be a JSON object")
    for sleeve_id, record in sleeves.items():
        _require_string(sleeve_id, field="sleeve id")
        _validate_promotion_record(record, sleeve_id=sleeve_id)
    return state


def sync_promotion_state_from_tournament(
    report: Mapping,
    current_state: Mapping | None,
    *,
    tiny_live_tranche_usd: Decimal,
    arm_live: bool = False,
    ci_green: bool = False,
    validation_report_ref: str = DEFAULT_VALIDATION_REPORT_REF,
    risk_envelope_ref: str = DEFAULT_RISK_ENVELOPE_REF,
    now: datetime.datetime | None = None,
) -> PromotionSyncResult:
    now_moment = now or datetime.datetime.now(tz=UTC)
    now_iso = _now_iso(now_moment)
    existing_sleeves: dict[str, dict] = {}
    if isinstance(current_state, Mapping):
        raw = current_state.get("sleeves")
        if isinstance(raw, Mapping):
            existing_sleeves = {
                str(key): dict(value)
                for key, value in raw.items()
                if isinstance(value, Mapping)
            }

    incumbents = [
        sleeve
        for sleeve, record in existing_sleeves.items()
        if record.get("live_enabled") is True
    ]
    incumbent_sleeve_id = incumbents[0] if incumbents else None

    candidate = report.get("live_strategy_candidate") or {}
    candidate_id = (
        str(candidate.get("strategy_id"))
        if candidate.get("status") == "candidate" and candidate.get("strategy_id")
        else None
    )

    new_sleeves: dict[str, dict] = {}
    promoted: list[str] = []
    demoted: list[str] = []
    unchanged: list[str] = []
    issues_by_sleeve: dict[str, list[str]] = {}

    # 1. Demote live-enabled sleeves whose own evidence is missing, stale,
    #    invalid, quality-floor-breaching, or turned negative.
    evidence_issue = _report_evidence_age_issue(report, now=now_moment)
    for sleeve_id, record in existing_sleeves.items():
        ranking = _ranking_for(report, sleeve_id)
        demote = False
        demotion_reason: str | None = None
        if record.get("live_enabled") is True:
            if ranking is None:
                demote = True
                demotion_reason = (
                    "tournament evidence missing: no ranking for this sleeve "
                    "in the tournament report"
                )
            elif evidence_issue is not None:
                demote = True
                demotion_reason = f"tournament evidence rejected: {evidence_issue}"
            else:
                quality_issues = _quality_gate_issues(ranking)
                if quality_issues:
                    demote = True
                    demotion_reason = (
                        "tournament evidence breached quality floor(s): "
                        + "; ".join(quality_issues)
                    )
                else:
                    demote = _as_decimal(ranking.get("total_return")) < 0
        if demote:
            new_sleeves[sleeve_id] = _demoted_record(
                record,
                ranking or {},
                now_iso=now_iso,
                validation_report_ref=validation_report_ref,
                demotion_reason=demotion_reason,
            )
            demoted.append(sleeve_id)
        else:
            new_sleeves[sleeve_id] = record
            unchanged.append(sleeve_id)

    # 2. Evaluate the tournament candidate for promotion.
    if candidate_id:
        ranking = _ranking_for(report, candidate_id)
        quality_issues = _quality_gate_issues(ranking or {})
        evidence = build_tournament_promotion_evidence(
            report,
            candidate_id,
            incumbent_sleeve_id=incumbent_sleeve_id,
            tiny_live_tranche_usd=tiny_live_tranche_usd,
            ci_green=ci_green,
            validation_report_ref=validation_report_ref,
            risk_envelope_ref=risk_envelope_ref,
        )
        if evidence is not None:
            decision = evaluate_sleeve_promotion(
                evidence, arm_live=arm_live, promoted_at=now_iso
            )
            state = dict(decision.state)
            all_issues = list(decision.issues) + quality_issues
            if evidence_issue is not None:
                all_issues.append(f"tournament evidence rejected: {evidence_issue}")
            # Rejected evidence may persist an explicit paper_only record with
            # its issue, but it can never promote the candidate or grant any
            # live authority.
            if quality_issues or evidence_issue is not None:
                state["stage"] = "paper_only"
                state["live_enabled"] = False
            state["issues"] = all_issues
            state["source"] = {
                "kind": "paper_tournament",
                "tournament_id": report.get("tournament_id"),
                "report_generated_at": report.get("generated_at"),
                "candidate_reason": candidate.get("reason"),
            }
            if ranking is not None:
                state["evidence_metrics"] = {
                    "total_return": str(ranking.get("total_return")),
                    "total_return_pct": str(ranking.get("total_return_pct")),
                    "max_drawdown_pct": str(ranking.get("max_drawdown_pct")),
                    "win_rate_pct": str(ranking.get("win_rate_pct")),
                    "tracked_days": int(ranking.get("tracked_days") or 0),
                }
            new_sleeves[candidate_id] = state
            issues_by_sleeve[candidate_id] = all_issues
            if state["stage"] == "tiny_live_eligible":
                promoted.append(candidate_id)
                if candidate_id in unchanged:
                    unchanged.remove(candidate_id)

    issues_by_sleeve = {
        sleeve_id: list(record["issues"])
        for sleeve_id, record in new_sleeves.items()
        if isinstance(record.get("issues"), list)
    }
    live_enabled_now = [
        sleeve
        for sleeve, record in new_sleeves.items()
        if record.get("live_enabled") is True
    ]
    summary_bits = []
    if promoted:
        summary_bits.append(f"promoted {', '.join(promoted)}")
    if demoted:
        summary_bits.append(f"demoted {', '.join(demoted)}")
    if not summary_bits:
        summary_bits.append("no promotion changes")
    summary_bits.append(
        "live-enabled now: " + (", ".join(live_enabled_now) or "none (fail-closed)")
    )

    state_payload = {
        "schema_version": "1.1.0",
        "generated_at": now_iso,
        "source": {
            "kind": "paper_tournament_sync",
            "tournament_id": report.get("tournament_id"),
            "report_generated_at": report.get("generated_at"),
            "arm_live": bool(arm_live),
            "ci_green": bool(ci_green),
        },
        "sleeves": new_sleeves,
    }
    return PromotionSyncResult(
        state=state_payload,
        promoted=promoted,
        demoted=demoted,
        unchanged=unchanged,
        issues_by_sleeve=issues_by_sleeve,
        summary="; ".join(summary_bits),
    )


def sync_promotion_state_file(
    report_path: str | Path,
    state_path: str | Path,
    *,
    output_state_path: str | Path | None = None,
    tiny_live_tranche_usd: Decimal,
    arm_live: bool = False,
    ci_green: bool = False,
    now: datetime.datetime | None = None,
    owner_approval: Mapping[str, object] | None = None,
    owner_approval_envelope_ref: str | None = None,
    owner_approval_envelope_sha256: str | None = None,
    risk_envelope_ref: str = DEFAULT_RISK_ENVELOPE_REF,
) -> PromotionSyncResult:
    state_file = Path(state_path)
    output_file = (
        Path(output_state_path) if output_state_path is not None else state_file
    )

    def evaluate_and_write() -> PromotionSyncResult:
        current_state: Mapping | None = None
        input_bytes = b""
        if state_file.exists():
            input_bytes = state_file.read_bytes()
            try:
                current_state = json.loads(input_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "existing promotion state must be valid UTF-8 JSON"
                ) from exc
            current_state = _validate_existing_promotion_state(current_state)
        report_bytes = Path(report_path).read_bytes()
        report = json.loads(report_bytes.decode("utf-8"))
        # The tournament dir stores the full report under "latest_report" inside
        # compact packets; accept either a bare report or a wrapper.
        if "rankings" not in report and isinstance(
            report.get("latest_report"), dict
        ):
            report = report["latest_report"]
        result = sync_promotion_state_from_tournament(
            report,
            current_state,
            tiny_live_tranche_usd=tiny_live_tranche_usd,
            arm_live=arm_live,
            ci_green=ci_green,
            validation_report_ref=DEFAULT_VALIDATION_REPORT_REF,
            risk_envelope_ref=risk_envelope_ref,
            now=now,
        )
        result.state["source"]["canonical_input_sha256"] = hashlib.sha256(
            input_bytes
        ).hexdigest()
        serialized = json.dumps(result.state, indent=2)
        output_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        # Final envelope source validation MUST precede approval consumption:
        # a changed/missing envelope leaves no promotion write and no approval
        # consumption.
        prewrite_ok = False
        if result.promoted and owner_approval_envelope_sha256:
            try:
                prewrite_bytes = Path(owner_approval_envelope_ref).read_bytes()
            except OSError as exc:
                raise ValueError(
                    "bound risk envelope is unavailable before promotion write"
                ) from exc
            if (
                hashlib.sha256(prewrite_bytes).hexdigest()
                != owner_approval_envelope_sha256
            ):
                raise ValueError(
                    "bound risk envelope changed after approval validation; "
                    "promotion refused"
                )
            prewrite_ok = True
        if result.promoted:
            from tradingagents.policy.owner_approval import (
                OwnerApprovalError,
                consume_owner_approval,
                finalize_owner_approval_prepare,
                owner_approval_prepare_exists,
                owner_approval_prepare_matches,
                owner_approval_prepare_path,
                owner_prepare_has_exact_consumption,
                prepared_transaction_binding_sha256,
                prepared_transaction_sha256,
                read_owner_approval_prepare,
                transaction_binding_sha256,
                verify_owner_approval_structure,
                write_owner_approval_prepare,
            )

            # ``now`` belongs exclusively to deterministic tournament
            # evaluation/output evidence.  Signature freshness and durable
            # single-use consumption always use the policy-owned UTC clock.
            moment = _owner_approval_authority_utc_now()
            subject, source_binding, purpose = _tournament_promotion_request(
                tournament_id=str(report.get("tournament_id") or ""),
                report_generated_at=str(report.get("generated_at") or ""),
                report_sha256=hashlib.sha256(report_bytes).hexdigest(),
                canonical_input_sha256=hashlib.sha256(input_bytes).hexdigest(),
                promoted=list(result.promoted),
                demoted=list(result.demoted),
                unchanged=list(result.unchanged),
                output_path=output_file.resolve(),
                output_state_sha256=output_digest,
            )
            recovery_identity = {
                "operation": "tournament_promotion_sync",
                "tournament_id": str(report.get("tournament_id") or ""),
                "report_generated_at": str(report.get("generated_at") or ""),
                "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                "promoted": sorted(result.promoted),
                "demoted": sorted(result.demoted),
                "unchanged": sorted(result.unchanged),
                "risk_envelope_ref": owner_approval_envelope_ref,
                "risk_envelope_sha256": owner_approval_envelope_sha256,
                "canonical_before_sha256": hashlib.sha256(input_bytes).hexdigest(),
                "input_state_path": str(state_file.resolve()),
                "output_state_path": str(output_file.resolve()),
                "report_path": str(Path(report_path).resolve()),
            }
            transaction = {
                **recovery_identity,
                "canonical_after_sha256": output_digest,
                "serialized_output": serialized,
                "recovery_identity": recovery_identity,
            }
            prepare_path = owner_approval_prepare_path(output_file)
            prepared = read_owner_approval_prepare(prepare_path)
            matching_prepare = owner_approval_prepare_matches(
                prepare_path, transaction=transaction
            )
            recovered = (
                prepared is not None
                and prepared["transaction"].get("recovery_identity")
                == recovery_identity
                and owner_prepare_has_exact_consumption(prepare_path)
            )
            if prepared is None and owner_approval_prepare_exists(prepare_path):
                # A durable-but-unreadable sidecar is never equivalent to an
                # absent prepare.  Continuing to a fresh verification here
                # could conceal tampering after an interrupted consumption.
                raise OwnerApprovalError("owner approval prepare is malformed")
            if prepared is not None and matching_prepare is None and not recovered:
                raise ValueError(
                    "owner approval prepare does not match this promotion transaction"
                )
            if recovered:
                stored_output = prepared["transaction"].get("serialized_output")
                if type(stored_output) is not str:
                    raise ValueError("prepared promotion transaction output is invalid")
                if output_file.exists():
                    if output_file.read_bytes() != stored_output.encode("utf-8"):
                        raise ValueError(
                            "prepared promotion transaction output does not match"
                        )
                else:
                    atomic_write_text(output_file, stored_output)
                finalize_owner_approval_prepare(prepare_path)
                return result
            else:
                try:
                    if (
                        owner_approval is None
                        or not owner_approval_envelope_ref
                        or not owner_approval_envelope_sha256
                    ):
                        raise OwnerApprovalError("owner approval required")
                    parsed = verify_owner_approval_structure(
                        approval=owner_approval,
                        expected_action="live_promotion",
                        subject=subject,
                        source_binding=source_binding,
                        now=moment,
                        purpose=purpose,
                    )
                    envelope = parsed["risk_envelope_binding"]
                    if (
                        envelope["ref"] != owner_approval_envelope_ref
                        or envelope["sha256"] != owner_approval_envelope_sha256
                    ):
                        raise OwnerApprovalError(
                            "owner approval risk envelope binding does not match this request"
                        )
                    binding = transaction_binding_sha256(
                        approval_id=parsed["approval_id"],
                        action=parsed["action"],
                        purpose=purpose,
                        subject=subject,
                        risk_envelope_ref=owner_approval_envelope_ref,
                        risk_envelope_sha256=owner_approval_envelope_sha256,
                    )
                    prepared_binding = prepared_transaction_binding_sha256(
                        transaction_binding_sha256=binding,
                        transaction_sha256=prepared_transaction_sha256(transaction),
                    )
                    if matching_prepare is not None:
                        if (
                            matching_prepare["approval_id"] != parsed["approval_id"]
                            or matching_prepare["action"] != parsed["action"]
                            or matching_prepare["purpose"] != purpose
                            or matching_prepare["transaction_binding_sha256"] != binding
                            or matching_prepare[
                                "prepared_transaction_binding_sha256"
                            ]
                            != prepared_binding
                        ):
                            raise OwnerApprovalError(
                                "owner approval prepare does not match this exact approval"
                            )
                    else:
                        written_binding = write_owner_approval_prepare(
                            prepare_path,
                            approval_id=parsed["approval_id"],
                            action=parsed["action"],
                            purpose=purpose,
                            transaction_binding_sha256=binding,
                            transaction=transaction,
                            now=moment,
                        )
                        if written_binding != prepared_binding:
                            raise OwnerApprovalError(
                                "owner approval prepare binding does not match this promotion transaction"
                            )
                    consume_owner_approval(
                        approval_id=parsed["approval_id"],
                        action=parsed["action"],
                        purpose=purpose,
                        transaction_binding_sha256=binding,
                        prepared_transaction_binding_sha256=prepared_binding,
                        now=moment,
                    )
                except OwnerApprovalError:
                    raise
            if owner_approval_envelope_sha256 and not prewrite_ok:
                raise ValueError(
                    "bound risk envelope is unavailable before promotion write"
                )
            atomic_write_text(output_file, serialized)
            finalize_owner_approval_prepare(prepare_path)
            return result
        atomic_write_text(output_file, serialized)
        return result

    with promotion_state_lock(state_file):
        if output_file.resolve() == state_file.resolve():
            return evaluate_and_write()
        with promotion_state_lock(output_file):
            return evaluate_and_write()


def _tournament_promotion_request(
    *,
    tournament_id: str,
    report_generated_at: str,
    report_sha256: str,
    canonical_input_sha256: str,
    promoted: list[str],
    demoted: list[str],
    unchanged: list[str],
    output_path: Path,
    output_state_sha256: str,
) -> tuple[dict[str, object], dict[str, object], str]:
    """Return the exact signed request image for a tournament promotion."""
    subject = {
        "kind": "tournament_promotion_sync",
        "tournament_id": tournament_id,
        "report_generated_at": report_generated_at,
        "report_sha256": report_sha256,
        "input_state_sha256": canonical_input_sha256,
        "promoted": sorted(promoted),
        "demoted": sorted(demoted),
        "unchanged": sorted(unchanged),
        "output_path": str(output_path),
        "output_state_sha256": output_state_sha256,
    }
    source_binding = {
        "kind": "paper_tournament_sync",
        "tournament_id": tournament_id,
        "report_sha256": report_sha256,
        "canonical_input_sha256": canonical_input_sha256,
    }
    purpose = (
        f"tournament_promotion:{tournament_id}:"
        f"{canonical_input_sha256}:{output_state_sha256}"
    )
    return subject, source_binding, purpose
