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
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from tradingagents.policy.integrity import write_state_with_integrity
from tradingagents.policy.promotion import (
    SleevePromotionEvidence,
    evaluate_sleeve_promotion,
)

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


@dataclass(frozen=True)
class PromotionSyncResult:
    state: dict
    promoted: list[str]
    demoted: list[str]
    unchanged: list[str]
    issues_by_sleeve: dict[str, list[str]] = field(default_factory=dict)
    summary: str = ""


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


def _demoted_record(
    existing: Mapping,
    ranking: Mapping,
    *,
    now_iso: str,
    validation_report_ref: str,
) -> dict:
    record = dict(existing)
    record["stage"] = "paper_only"
    record["live_enabled"] = False
    record["benchmark_gate_passed"] = False
    record["recent_alpha_gate_passed"] = False
    record["demoted_at"] = now_iso
    record["demotion_reason"] = (
        "tournament evidence turned negative: total_return "
        f"{ranking.get('total_return')} ({ranking.get('total_return_pct')}%) "
        f"over {ranking.get('tracked_days')} tracked day(s) with win rate "
        f"{ranking.get('win_rate_pct')}%"
    )
    record["validation_report_ref"] = validation_report_ref
    return record


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
    now_iso = _now_iso(now)
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

    # 1. Demote live-enabled sleeves whose own evidence turned negative.
    for sleeve_id, record in existing_sleeves.items():
        ranking = _ranking_for(report, sleeve_id)
        if (
            record.get("live_enabled") is True
            and ranking is not None
            and int(ranking.get("tracked_days") or 0) >= MIN_TRACKED_DAYS
            and _as_decimal(ranking.get("total_return")) < 0
        ):
            new_sleeves[sleeve_id] = _demoted_record(
                record,
                ranking,
                now_iso=now_iso,
                validation_report_ref=validation_report_ref,
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
                    "tracked_days": int(ranking.get("tracked_days") or 0),
                }
            new_sleeves[candidate_id] = state
            issues_by_sleeve[candidate_id] = all_issues
            if state["stage"] == "tiny_live_eligible":
                promoted.append(candidate_id)
                if candidate_id in unchanged:
                    unchanged.remove(candidate_id)

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
    tiny_live_tranche_usd: Decimal,
    arm_live: bool = False,
    ci_green: bool = False,
    now: datetime.datetime | None = None,
) -> PromotionSyncResult:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    # The tournament dir stores the full report under "latest_report" inside
    # compact packets; accept either a bare report or a wrapper.
    if "rankings" not in report and isinstance(report.get("latest_report"), dict):
        report = report["latest_report"]
    current_state: Mapping | None = None
    state_file = Path(state_path)
    if state_file.exists():
        try:
            current_state = json.loads(state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current_state = None
    result = sync_promotion_state_from_tournament(
        report,
        current_state,
        tiny_live_tranche_usd=tiny_live_tranche_usd,
        arm_live=arm_live,
        ci_green=ci_green,
        now=now,
    )
    write_state_with_integrity(
        state_file, json.dumps(result.state, indent=2), actor="promotion_sync"
    )
    return result
