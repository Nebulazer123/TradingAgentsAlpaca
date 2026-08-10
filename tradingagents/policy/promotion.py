"""Promotion evidence policy for moving a sleeve toward tiny-live eligibility."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc


@dataclass(frozen=True)
class SleevePromotionEvidence:
    sleeve: str
    preregistered: bool
    ci_green: bool
    shadow_confirmed: bool
    benchmark_excess_return: Decimal
    cost_adjusted_alpha: Decimal
    recent_alpha: Decimal
    capacity_usd: Decimal
    requested_tiny_live_tranche_usd: Decimal
    validation_report_ref: str
    risk_envelope_ref: str
    min_benchmark_excess_return: Decimal = Decimal("0")
    min_cost_adjusted_alpha: Decimal = Decimal("0")
    min_recent_alpha: Decimal = Decimal("0")


@dataclass(frozen=True)
class SleevePromotionDecision:
    sleeve: str
    stage: str
    live_enabled: bool
    passed: bool
    gates: dict[str, bool]
    issues: list[str]
    state: dict


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _decimal_str(value: Decimal) -> str:
    return str(value)


def evaluate_sleeve_promotion(
    evidence: SleevePromotionEvidence,
    *,
    arm_live: bool = False,
    promoted_at: str | None = None,
) -> SleevePromotionDecision:
    gates = {
        "preregistered": evidence.preregistered,
        "ci_green": evidence.ci_green,
        "shadow_confirmed": evidence.shadow_confirmed,
        "benchmark_gate_passed": evidence.benchmark_excess_return >= evidence.min_benchmark_excess_return,
        "cost_gate_passed": evidence.cost_adjusted_alpha >= evidence.min_cost_adjusted_alpha,
        "recent_alpha_gate_passed": evidence.recent_alpha >= evidence.min_recent_alpha,
        "capacity_gate_passed": evidence.capacity_usd >= evidence.requested_tiny_live_tranche_usd,
        "validation_report_present": bool(evidence.validation_report_ref),
        "risk_envelope_ref_present": bool(evidence.risk_envelope_ref),
    }
    issues = [name for name, passed in gates.items() if not passed]
    passed = not issues
    stage = "tiny_live_eligible" if passed else "paper_only"
    live_enabled = bool(arm_live and passed)
    state = {
        "stage": stage,
        "live_enabled": live_enabled,
        "ci_green": evidence.ci_green,
        "shadow_confirmed": evidence.shadow_confirmed,
        "preregistered": evidence.preregistered,
        "benchmark_gate_passed": gates["benchmark_gate_passed"],
        "cost_gate_passed": gates["cost_gate_passed"],
        "recent_alpha_gate_passed": gates["recent_alpha_gate_passed"],
        "capacity_gate_passed": gates["capacity_gate_passed"],
        "validation_report_ref": evidence.validation_report_ref,
        "risk_envelope_ref": evidence.risk_envelope_ref,
        "promoted_at": promoted_at or _now_iso(),
        "metrics": {
            "benchmark_excess_return": _decimal_str(evidence.benchmark_excess_return),
            "cost_adjusted_alpha": _decimal_str(evidence.cost_adjusted_alpha),
            "recent_alpha": _decimal_str(evidence.recent_alpha),
            "capacity_usd": _decimal_str(evidence.capacity_usd),
            "requested_tiny_live_tranche_usd": _decimal_str(evidence.requested_tiny_live_tranche_usd),
        },
        "issues": issues,
    }
    return SleevePromotionDecision(
        sleeve=evidence.sleeve,
        stage=stage,
        live_enabled=live_enabled,
        passed=passed,
        gates=gates,
        issues=issues,
        state=state,
    )


def build_promotion_state(
    decisions: list[SleevePromotionDecision],
    *,
    generated_at: str | None = None,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "generated_at": generated_at or _now_iso(),
        "sleeves": {
            decision.sleeve: decision.state
            for decision in decisions
        },
    }


def write_promotion_state(path: str | Path, decisions: list[SleevePromotionDecision]) -> Path:
    state_path = Path(path)
    payload = build_promotion_state(decisions)
    atomic_write_text(state_path, json.dumps(payload, indent=2))
    return state_path
