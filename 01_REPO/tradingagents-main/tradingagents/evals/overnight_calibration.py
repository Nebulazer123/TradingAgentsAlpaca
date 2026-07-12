"""Calibration guard for mature overnight walk-forward cohorts."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

FORBIDDEN_EFFECTS = [
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
]

MAX_FALSE_POSITIVE_RATE = Decimal("0.2500")
MIN_DIRECTIONAL_ACCURACY = Decimal("0.5000")
MIN_ACTION_RELATIVE_RETURN = Decimal("0.0000")


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds")


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _metric_by_arm(cohort_summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    metrics = cohort_summary.get("walk_forward_metrics") or []
    if not isinstance(metrics, list):
        return {}
    by_arm: dict[str, dict[str, Any]] = {}
    for row in metrics:
        if not isinstance(row, Mapping):
            continue
        arm_id = str(row.get("arm_id") or "").strip()
        if arm_id:
            by_arm[arm_id] = dict(row)
    return by_arm


def _metric_summary(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {
            "available": False,
            "scored_count": 0,
            "sample_floor_met": False,
            "directional_accuracy": None,
            "false_positive_rate": None,
            "average_brier": None,
            "average_action_relative_return": None,
            "average_gross_action_relative_return": None,
            "average_transaction_cost": None,
            "average_latency_seconds": None,
            "baseline_arm_id": None,
            "net_edge_vs_baseline": None,
            "beats_baseline_after_costs": None,
        }
    return {
        "available": True,
        "scored_count": int(row.get("scored_count") or 0),
        "sample_floor_met": bool(row.get("sample_floor_met")),
        "directional_accuracy": row.get("directional_accuracy"),
        "false_positive_rate": row.get("false_positive_rate"),
        "average_brier": row.get("average_brier"),
        "average_action_relative_return": row.get("average_action_relative_return"),
        "average_gross_action_relative_return": row.get("average_gross_action_relative_return"),
        "average_transaction_cost": row.get("average_transaction_cost"),
        "average_latency_seconds": row.get("average_latency_seconds"),
        "baseline_arm_id": row.get("baseline_arm_id"),
        "net_edge_vs_baseline": row.get("net_edge_vs_baseline"),
        "beats_baseline_after_costs": row.get("beats_baseline_after_costs"),
    }


def _append_metric_flags(
    red_flags: list[str],
    *,
    arm_name: str,
    metric: Mapping[str, Any],
    require_sample: bool,
) -> None:
    if not metric.get("available"):
        red_flags.append(f"{arm_name}_unavailable")
        return
    if require_sample and not metric.get("sample_floor_met"):
        red_flags.append(f"{arm_name}_sample_floor_not_met")
    action_return = _as_decimal(metric.get("average_action_relative_return"))
    if action_return is not None and action_return < MIN_ACTION_RELATIVE_RETURN:
        red_flags.append(f"{arm_name}_negative_action_return")
    false_positive_rate = _as_decimal(metric.get("false_positive_rate"))
    if false_positive_rate is not None and false_positive_rate > MAX_FALSE_POSITIVE_RATE:
        red_flags.append(f"{arm_name}_false_positive_risk")
    accuracy = _as_decimal(metric.get("directional_accuracy"))
    if accuracy is not None and accuracy < MIN_DIRECTIONAL_ACCURACY:
        red_flags.append(f"{arm_name}_weak_directional_accuracy")


def _guard_decision(sample_floor_met: bool, red_flags: list[str]) -> str:
    if not sample_floor_met:
        return "collect_more"
    if red_flags:
        return "tighten"
    return "monitor"


def _recommended_guardrails(decision: str) -> list[str]:
    base = [
        "Keep overnight research analysis-only; do not promote live influence from a weak cohort.",
        "Require controlled dip, support, or reclaim evidence before any buy-side escalation.",
        "Reject green-spike chase setups unless a later controlled pullback creates a new entry.",
        "Downrank bot-copycat, crowded AI beta, and unconfirmed broker/fintech watch names until independent flow or institutional confirmation appears.",
        "Keep paper-first exploration active while collecting more mature overnight outcome samples.",
    ]
    if decision == "monitor":
        return [
            "Maintain current guardrails and keep monitoring mature cohort metrics before increasing influence.",
            *base[1:],
        ]
    if decision == "collect_more":
        return [
            "Do not change live influence until the cohort meets the minimum sample floor.",
            *base[1:],
        ]
    return base


def _live_influence_policy(decision: str) -> dict[str, Any]:
    """Machine-readable overnight influence policy for morning automations."""
    if decision == "monitor":
        return {
            "mode": "monitor",
            "can_increase_live_influence": True,
            "live_influence_action": "hold_current_weight_until_next_cohort",
            "new_buy_permission": "controlled_dip_only",
            "replacement_buy_permission": "independent_controlled_setup_only",
            "sell_permission": "independent_profit_or_board_approved_exit_only",
        }
    if decision == "collect_more":
        return {
            "mode": "collect_more",
            "can_increase_live_influence": False,
            "live_influence_action": "do_not_increase_until_sample_floor_met",
            "new_buy_permission": "paper_or_dry_run_preferred",
            "replacement_buy_permission": "disabled_without_independent_setup",
            "sell_permission": "independent_profit_or_board_approved_exit_only",
        }
    return {
        "mode": "tighten",
        "can_increase_live_influence": False,
        "live_influence_action": "tighten_or_hold_reduced_weight",
        "new_buy_permission": "controlled_dip_support_reclaim_only",
        "replacement_buy_permission": "disabled_unless_fresh_independent_setup",
        "sell_permission": "independent_profit_or_board_approved_exit_only",
    }


def _entry_validation_requirements(decision: str) -> list[dict[str, Any]]:
    """Return explicit gates that convert the prose guardrails into checks."""
    base = [
        {
            "id": "controlled_dip_or_support_reclaim",
            "required": True,
            "description": "Entry needs a pullback, support hold, reclaim, or other non-chase setup.",
        },
        {
            "id": "no_green_spike_chase",
            "required": True,
            "description": "Reject entries whose primary evidence is an already-extended green spike.",
        },
        {
            "id": "buy_sell_independence",
            "required": True,
            "description": "A sell never forces a same-run replacement buy; buys need their own setup.",
        },
        {
            "id": "source_freshness_and_quality",
            "required": True,
            "description": "Use fresh/downrank-aware source packets; stale or blocked evidence cannot promote a trade.",
        },
    ]
    anti_crowding = {
        "id": "anti_crowding_confirmation",
        "required": decision in {"tighten", "collect_more"},
        "description": "Bot-copycat, crowded AI beta, broker-friction, and social-flow names need independent price/volume, broker/flow, options, or institutional confirmation.",
        "confirmation_sources": [
            "fresh_price_volume",
            "broker_or_order_flow",
            "options_iv_or_open_interest",
            "institutional_or_filing_context",
        ],
    }
    return [*base, anti_crowding]


def _promotion_blockers(decision: str, red_flags: list[str]) -> list[str]:
    blockers: list[str] = []
    if decision == "collect_more":
        blockers.append("sample_floor_not_met")
    if decision == "tighten":
        blockers.append("weak_or_negative_walk_forward_cohort")
    if any("false_positive" in flag for flag in red_flags):
        blockers.append("false_positive_rate_too_high")
    if any("negative_action_return" in flag for flag in red_flags):
        blockers.append("action_relative_return_negative")
    if any("weak_directional_accuracy" in flag for flag in red_flags):
        blockers.append("directional_accuracy_below_floor")
    if any("not_beating_baseline_after_costs" in flag for flag in red_flags):
        blockers.append("overlay_not_beating_baseline_after_costs")
    return sorted(dict.fromkeys(blockers))


def build_overnight_calibration_guard(
    cohort_summary: Mapping[str, Any] | None,
    *,
    cohort_summary_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a compact guard from mature overnight walk-forward metrics."""

    generated_at = _now_iso()
    if not isinstance(cohort_summary, Mapping):
        return {
            "kind": "overnight_calibration_guard",
            "schema_version": "1.0.0",
            "generated_at": generated_at,
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "forbidden_effects": FORBIDDEN_EFFECTS,
            "status": "blocked_missing_cohort",
            "guard_decision": "collect_more",
            "can_increase_live_influence": False,
            "red_flags": ["cohort_summary_missing"],
            "live_influence_policy": _live_influence_policy("collect_more"),
            "entry_validation_requirements": _entry_validation_requirements("collect_more"),
            "promotion_blockers": ["cohort_summary_missing", "sample_floor_not_met"],
            "paper_exploration_policy": {
                "status": "continue",
                "reason": "paper sleeves should keep collecting samples while live influence is frozen",
            },
            "recommended_guardrails": _recommended_guardrails("collect_more"),
            "cohort_summary_path": str(cohort_summary_path) if cohort_summary_path else None,
            "metric_summary": {},
            "next_action": "Run research walk-forward-refresh-overnight-cohort before changing overnight influence.",
        }

    by_arm = _metric_by_arm(cohort_summary)
    baseline = _metric_summary(by_arm.get("deterministic_sleeve_only"))
    tradingagents = _metric_summary(by_arm.get("tradingagents_advisory_overlay"))
    sample_floor_met = bool(cohort_summary.get("sample_floor_met"))
    red_flags: list[str] = []
    if not sample_floor_met:
        red_flags.append("cohort_sample_floor_not_met")
    _append_metric_flags(
        red_flags,
        arm_name="deterministic_sleeve",
        metric=baseline,
        require_sample=True,
    )
    _append_metric_flags(
        red_flags,
        arm_name="tradingagents_overlay",
        metric=tradingagents,
        require_sample=False,
    )
    if tradingagents.get("beats_baseline_after_costs") is False:
        red_flags.append("tradingagents_overlay_not_beating_baseline_after_costs")
    overlay_edge = _as_decimal(tradingagents.get("net_edge_vs_baseline"))
    if overlay_edge is not None and overlay_edge < Decimal("0"):
        red_flags.append("tradingagents_overlay_not_beating_baseline_after_costs")
    red_flags = sorted(dict.fromkeys(red_flags))
    decision = _guard_decision(sample_floor_met, red_flags)
    can_increase_live_influence = decision == "monitor"
    packet = {
        "kind": "overnight_calibration_guard",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "status": "ok",
        "guard_decision": decision,
        "can_increase_live_influence": can_increase_live_influence,
        "red_flags": red_flags,
        "live_influence_policy": _live_influence_policy(decision),
        "entry_validation_requirements": _entry_validation_requirements(decision),
        "promotion_blockers": _promotion_blockers(decision, red_flags),
        "paper_exploration_policy": {
            "status": "continue",
            "reason": "paper sleeves collect strategy evidence and do not bypass live gates",
        },
        "recommended_guardrails": _recommended_guardrails(decision),
        "cohort_summary_path": str(cohort_summary_path) if cohort_summary_path else None,
        "cohort_generated_at": cohort_summary.get("generated_at"),
        "selected_packet_count": cohort_summary.get("selected_packet_count"),
        "returns_row_count": cohort_summary.get("returns_row_count"),
        "fixture_row_count": cohort_summary.get("fixture_row_count"),
        "replay_packet_path": cohort_summary.get("replay_packet_path"),
        "sample_floor_met": sample_floor_met,
        "metric_summary": {
            "deterministic_sleeve_only": baseline,
            "tradingagents_advisory_overlay": tradingagents,
        },
        "next_action": (
            "Keep overnight influence tight and require anti-crowding confirmation."
            if decision == "tighten"
            else "Keep monitoring mature overnight cohorts before changing influence."
        ),
    }
    return packet


def render_overnight_calibration_guard_markdown(packet: Mapping[str, Any]) -> str:
    """Render a short human-readable guard packet."""

    lines = [
        "# Overnight Calibration Guard",
        "",
        f"- Status: `{packet.get('status')}`",
        f"- Decision: `{packet.get('guard_decision')}`",
        f"- Can increase live influence: `{packet.get('can_increase_live_influence')}`",
        f"- Cohort: `{packet.get('cohort_summary_path')}`",
        f"- Red flags: {', '.join(packet.get('red_flags') or []) or 'none'}",
        "",
        "## Guardrails",
    ]
    for item in packet.get("recommended_guardrails") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def compact_overnight_calibration_guard(
    packet: Mapping[str, Any],
    *,
    packet_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the token-budgeted guard view used by hooks, n8n, and context."""

    metric_summary = (
        packet.get("metric_summary")
        if isinstance(packet.get("metric_summary"), Mapping)
        else {}
    )
    baseline = (
        metric_summary.get("deterministic_sleeve_only")
        if isinstance(metric_summary.get("deterministic_sleeve_only"), Mapping)
        else {}
    )
    advisory = (
        metric_summary.get("tradingagents_advisory_overlay")
        if isinstance(metric_summary.get("tradingagents_advisory_overlay"), Mapping)
        else {}
    )
    live_influence_policy = (
        packet.get("live_influence_policy")
        if isinstance(packet.get("live_influence_policy"), Mapping)
        else {}
    )
    entry_requirements = [
        item
        for item in packet.get("entry_validation_requirements") or []
        if isinstance(item, Mapping)
    ]
    return {
        "schema": "compact_overnight_calibration_guard_v1",
        "kind": packet.get("kind", "overnight_calibration_guard"),
        "raw_packet_path": str(packet_path) if packet_path else None,
        "generated_at": packet.get("generated_at"),
        "status": packet.get("status"),
        "analysis_only": packet.get("analysis_only"),
        "can_submit_orders": packet.get("can_submit_orders"),
        "execution_authority": packet.get("execution_authority"),
        "guard_decision": packet.get("guard_decision"),
        "can_increase_live_influence": packet.get("can_increase_live_influence"),
        "red_flags": [str(item) for item in packet.get("red_flags") or []][:12],
        "promotion_blockers": [
            str(item) for item in packet.get("promotion_blockers") or []
        ][:8],
        "live_influence_policy": {
            key: live_influence_policy.get(key)
            for key in (
                "mode",
                "live_influence_action",
                "new_buy_permission",
                "replacement_buy_permission",
                "sell_permission",
            )
            if live_influence_policy.get(key) is not None
        },
        "entry_validation_requirement_ids": [
            str(item.get("id")) for item in entry_requirements[:8] if item.get("id")
        ],
        "required_entry_validation_ids": [
            str(item.get("id"))
            for item in entry_requirements
            if item.get("id") and item.get("required") is True
        ][:8],
        "paper_exploration_policy": packet.get("paper_exploration_policy"),
        "sample_floor_met": packet.get("sample_floor_met"),
        "selected_packet_count": packet.get("selected_packet_count"),
        "returns_row_count": packet.get("returns_row_count"),
        "fixture_row_count": packet.get("fixture_row_count"),
        "cohort_summary_path": packet.get("cohort_summary_path"),
        "replay_packet_path": packet.get("replay_packet_path"),
        "baseline_action_relative_return": baseline.get(
            "average_action_relative_return"
        ),
        "baseline_false_positive_rate": baseline.get("false_positive_rate"),
        "tradingagents_action_relative_return": advisory.get(
            "average_action_relative_return"
        ),
        "tradingagents_false_positive_rate": advisory.get("false_positive_rate"),
        "recommended_guardrails": list(packet.get("recommended_guardrails") or [])[:6],
        "next_action": packet.get("next_action"),
    }


def write_overnight_calibration_guard(
    packet: Mapping[str, Any],
    output_dir: str | Path = "results/overnight_calibration",
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    packet_path = output_path / f"overnight-calibration-guard-{stamp}.json"
    text = json.dumps(dict(packet), indent=2)
    packet_path.write_text(text, encoding="utf-8")
    (output_path / "latest.json").write_text(text, encoding="utf-8")
    compact = compact_overnight_calibration_guard(packet, packet_path=packet_path)
    compact_text = json.dumps(compact, indent=2)
    compact_path = output_path / f"overnight-calibration-guard-{stamp}.compact.json"
    compact_path.write_text(compact_text, encoding="utf-8")
    (output_path / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    (output_path / "latest.md").write_text(
        render_overnight_calibration_guard_markdown(packet),
        encoding="utf-8",
    )
    return packet_path


def latest_walk_forward_cohort_path(input_dir: str | Path) -> Path | None:
    paths = sorted(Path(input_dir).glob("walk_forward_cohort_refresh_*_h*.json"))
    return paths[-1] if paths else None
