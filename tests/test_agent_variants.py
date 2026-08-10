"""Tests for the agent variant registration convention and scoreboard.

The ledger keys everything by the ``agent`` string, so a prompt/model/toolset
variant is just a new agent name that earns influence through the same
audited pipeline as the base roles. These tests lock the naming convention
(parse/build roundtrip, malformed names degrade to plain agents) and the
scoreboard that lets variants compete per role on resolved evidence.
"""

from __future__ import annotations

import pytest

from tradingagents.evals.agent_intelligence_ledger import AgentForecast
from tradingagents.evals.agent_variants import (
    AgentVariantSpec,
    base_role,
    parse_variant_agent_name,
    variant_agent_name,
    variant_scoreboard,
)


def _resolved_forecast(agent: str, *, outcome: bool, index: int) -> AgentForecast:
    return AgentForecast(
        forecast_id=f"af-{agent}-{index}",
        agent=agent,
        ticker="XOM",
        claim=f"{agent} test claim",
        forecast_type="test_direction",
        horizon="5 trading days",
        probability="0.60",
        expected_outcome="XOM outperforms SPY by >1.5%",
        direction="bullish",
        created_at="2026-06-01T00:00:00+00:00",
        resolve_after="2026-06-08T00:00:00+00:00",
        resolved=True,
        outcome=outcome,
        brier_score="0.16" if outcome else "0.36",
        agent_score_delta="0.10" if outcome else "-0.10",
        label_quality="high",
    )


def test_variant_name_roundtrip_and_normalization():
    name = variant_agent_name(
        role="Market Analyst",
        prompt_version="PV-2",
        model_route="sonnet45",
        toolset="Default",
        context_policy="lean ctx",
    )
    assert name == "market_analyst::pv_2+sonnet45+default+lean_ctx"
    spec = parse_variant_agent_name(name)
    assert spec == AgentVariantSpec(
        role="market_analyst",
        prompt_version="pv_2",
        model_route="sonnet45",
        toolset="default",
        context_policy="lean_ctx",
    )
    assert spec.agent_name == name
    assert base_role(name) == "market_analyst"


def test_plain_role_is_not_a_variant():
    assert parse_variant_agent_name("market_analyst") is None
    assert base_role("market_analyst") == "market_analyst"


def test_malformed_variant_names_degrade_to_plain_agents():
    assert parse_variant_agent_name("x::a+b") is None
    assert parse_variant_agent_name("::a+b+c+d") is None
    assert parse_variant_agent_name("x::a+b+c+") is None
    assert base_role("x::a+b") == "x::a+b"


def test_variant_agent_name_requires_a_role():
    with pytest.raises(ValueError):
        variant_agent_name(role="   ", prompt_version="pv1", model_route="sonnet45")


def test_scoreboard_ranks_variants_within_their_role():
    variant_name = variant_agent_name(
        role="market_analyst", prompt_version="pv2", model_route="sonnet45"
    )
    rookie_name = variant_agent_name(
        role="market_analyst", prompt_version="pv3", model_route="haiku45"
    )
    forecasts = [
        # Baseline role: 4 resolved at 50% accuracy.
        *[_resolved_forecast("market_analyst", outcome=(i % 2 == 0), index=i) for i in range(4)],
        # Challenger variant: 4 resolved, all useful.
        *[_resolved_forecast(variant_name, outcome=True, index=i) for i in range(4)],
        # Rookie variant: one resolved forecast, not enough history.
        _resolved_forecast(rookie_name, outcome=True, index=0),
        # A second role to prove grouping.
        _resolved_forecast("trader", outcome=False, index=0),
    ]

    board = variant_scoreboard(forecasts, min_resolved=3)

    assert board["kind"] == "agent_variant_scoreboard"
    assert board["analysis_only"] is True
    assert board["can_submit_orders"] is False
    assert board["execution_authority"] == "none"
    assert "submit_order" in board["forbidden_effects"]
    assert board["role_count"] == 2

    role = board["roles"]["market_analyst"]
    assert role["variant_count"] == 3
    # Earned entries rank ahead of unproven ones; the challenger leads.
    assert [entry["agent"] for entry in role["variants"]] == [
        variant_name,
        "market_analyst",
        rookie_name,
    ]
    assert role["leader"] == variant_name
    challenger = role["variants"][0]
    assert challenger["is_baseline"] is False
    assert challenger["variant"]["prompt_version"] == "pv2"
    baseline = role["variants"][1]
    assert baseline["is_baseline"] is True
    rookie = role["variants"][2]
    assert rookie["state"] == "insufficient_history"
    assert rookie["weight"] == "1.00"

    trader_role = board["roles"]["trader"]
    assert trader_role["variant_count"] == 1
    # One resolved forecast is below min_resolved: no leader is crowned.
    assert trader_role["leader"] is None
