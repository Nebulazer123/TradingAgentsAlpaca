from decimal import Decimal

import pytest

from tradingagents.policy.risk_posture import (
    normalize_risk_posture,
    risk_posture_policy,
    risk_posture_policy_from_config,
)


def test_risk_posture_defaults_are_paper_balanced_and_live_conservative():
    paper = risk_posture_policy(environment="paper")
    live = risk_posture_policy(environment="live")

    assert paper.name == "balanced"
    assert paper.paper_first_threshold == Decimal("0.60")
    assert live.name == "conservative"
    assert live.live_gate_relaxation_allowed is False
    assert live.live_cap_multiplier == Decimal("1")


def test_performance_seeking_widens_research_and_paper_only():
    balanced = risk_posture_policy("balanced", environment="paper")
    performance = risk_posture_policy("performance-seeking", environment="paper")

    assert performance.name == "performance_seeking"
    assert performance.paper_first_threshold < balanced.paper_first_threshold
    assert performance.overnight_candidate_limit > balanced.overnight_candidate_limit
    assert performance.deep_research_top_n > balanced.deep_research_top_n
    assert performance.market_mirror_max_agents > balanced.market_mirror_max_agents
    assert performance.paid_model_route == "cap_required"
    assert performance.live_gate_relaxation_allowed is False
    assert performance.live_cap_multiplier == Decimal("1")


def test_risk_posture_from_config_and_invalid_values():
    policy = risk_posture_policy_from_config(
        {"risk_posture": "conservative"},
        environment="paper",
    )

    assert policy.name == "conservative"
    with pytest.raises(ValueError):
        normalize_risk_posture("YOLO")
