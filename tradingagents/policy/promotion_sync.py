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
    SleevePromotionEvidence,
    evaluate_sleeve_promotion,
)
from tradingagents.policy.strategy_promotion import INTERNAL_EVIDENCE_MAX_AGE_SECONDS

UTC = datetime.timezone.utc

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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _quality_decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _ranking_for(report: Mapping, sleeve_id: str) -> Mapping | None:
    for ranking in report.get("rankings") or []:
        if ranking.get("strategy_id") == sleeve_id:
            return ranking
    return None


def _quality_gate_issues(ranking: Mapping) -> list[str]:
    issues: list[str] = []

    raw_tracked_days = ranking.get("tracked_days")
    try:
        tracked_days = int(raw_tracked_days or 0)
    except (TypeError, ValueError, OverflowError):
        tracked_days = 0
        issues.append(f"tracked_days {raw_tracked_days!r} is invalid")
    if tracked_days < MIN_TRACKED_DAYS:
        issues.append(
            f"tracked_days {tracked_days} is below the {MIN_TRACKED_DAYS}-day floor"
        )

    raw_drawdown = ranking.get("max_drawdown_pct")
    drawdown = _quality_decimal(raw_drawdown)
    if drawdown is None:
        issues.append(f"max_drawdown_pct {raw_drawdown!r} is invalid")
    elif drawdown < MAX_DRAWDOWN_FLOOR_PCT:
        issues.append(
            f"max_drawdown_pct {drawdown} breaches the {MAX_DRAWDOWN_FLOOR_PCT}% floor"
        )

    raw_win_rate = ranking.get("win_rate_pct")
    win_rate = _quality_decimal(raw_win_rate)
    if win_rate is None:
        issues.append(f"win_rate_pct {raw_win_rate!r} is invalid")
    elif win_rate < MIN_WIN_RATE_PCT:
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
    tracked_days = _as_int(ranking.get("tracked_days") or 0)
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
    """Return a demotion-grade freshness complaint about the report, if any."""

    raw = report.get("generated_at")
    if type(raw) is not str or not raw:
        return "tournament report generated_at is missing"
    try:
        moment = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return f"tournament report generated_at is invalid: {raw!r}"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
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

    # 2. Evaluate the tournament candidate for promotion only when the report
    #    itself is fresh and this sync did not just demote that same sleeve.
    if candidate_id and evidence_issue is None and candidate_id not in demoted:
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
            if quality_issues:
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
                    "tracked_days": _as_int(ranking.get("tracked_days") or 0),
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
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
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
            now=now,
        )
        result.state["source"]["canonical_input_sha256"] = hashlib.sha256(
            input_bytes
        ).hexdigest()
        atomic_write_text(output_file, json.dumps(result.state, indent=2))
        return result

    with promotion_state_lock(state_file):
        return evaluate_and_write()
