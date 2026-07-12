import json
from decimal import Decimal

from tradingagents.policy.promotion import (
    SleevePromotionEvidence,
    build_promotion_state,
    evaluate_sleeve_promotion,
    write_promotion_state,
)


def _evidence(**overrides):
    values = {
        "sleeve": "pullback-support",
        "preregistered": True,
        "ci_green": True,
        "shadow_confirmed": True,
        "benchmark_excess_return": Decimal("0.03"),
        "cost_adjusted_alpha": Decimal("0.02"),
        "recent_alpha": Decimal("0.01"),
        "capacity_usd": Decimal("500"),
        "requested_tiny_live_tranche_usd": Decimal("25"),
        "validation_report_ref": "results/validation/pullback-support.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
    }
    values.update(overrides)
    return SleevePromotionEvidence(**values)


def test_promotion_policy_builds_tiny_live_eligible_state_when_all_gates_pass():
    decision = evaluate_sleeve_promotion(
        _evidence(),
        arm_live=True,
        promoted_at="2026-06-01T15:00:00+00:00",
    )

    assert decision.passed is True
    assert decision.stage == "tiny_live_eligible"
    assert decision.live_enabled is True
    assert decision.state["benchmark_gate_passed"] is True
    assert decision.state["recent_alpha_gate_passed"] is True
    assert decision.state["risk_envelope_ref"] == "config/risk_envelope.yaml"


def test_promotion_policy_keeps_live_disabled_until_armed():
    decision = evaluate_sleeve_promotion(_evidence(), arm_live=False)

    assert decision.passed is True
    assert decision.stage == "tiny_live_eligible"
    assert decision.live_enabled is False
    assert decision.state["live_enabled"] is False


def test_promotion_policy_blocks_weak_or_low_capacity_sleeve():
    decision = evaluate_sleeve_promotion(
        _evidence(
            recent_alpha=Decimal("-0.01"),
            capacity_usd=Decimal("10"),
            requested_tiny_live_tranche_usd=Decimal("25"),
        ),
        arm_live=True,
    )

    assert decision.passed is False
    assert decision.stage == "paper_only"
    assert decision.live_enabled is False
    assert "recent_alpha_gate_passed" in decision.issues
    assert "capacity_gate_passed" in decision.issues


def test_promotion_state_writer_uses_live_gate_shape(tmp_path):
    decision = evaluate_sleeve_promotion(
        _evidence(),
        arm_live=True,
        promoted_at="2026-06-01T15:00:00+00:00",
    )
    state = build_promotion_state([decision], generated_at="2026-06-01T15:00:00+00:00")
    path = write_promotion_state(tmp_path / "promotion.json", [decision])

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "1.0.0"
    assert state["schema_version"] == "1.0.0"
    assert state["sleeves"]["pullback-support"]["stage"] == "tiny_live_eligible"
    assert saved["sleeves"]["pullback-support"]["live_enabled"] is True
    assert saved["sleeves"]["pullback-support"]["validation_report_ref"]
    assert list(tmp_path.glob(".promotion.json.*.tmp")) == []
