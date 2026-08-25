"""Tests for the agent variant registration convention and scoreboard.

The ledger keys everything by the ``agent`` string, so a prompt/model/toolset
variant is just a new agent name that earns influence through the same
audited pipeline as the base roles. These tests lock the naming convention
(parse/build roundtrip, malformed names degrade to plain agents) and the
scoreboard that lets variants compete per role on resolved evidence.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_source_bound_adjusted_price_window,
)
from tradingagents.evals.agent_intelligence_ledger import AgentForecast
from tradingagents.evals.agent_variants import (
    AgentVariantSpec,
    base_role,
    parse_variant_agent_name,
    variant_agent_name,
    variant_scoreboard,
)
from tradingagents.evals.source_bound_resolution import build_source_bound_window_lookup


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


def _source_bound_verifier_for(tmp_path):
    """Build retained, local receipt evidence for the shared forecast window."""

    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifacts = {}
    receipts = []
    for symbol, first_close, last_close in (
        ("XOM", "100", "110"),
        ("SPY", "100", "102"),
    ):
        artifact = archive.admit(
            raw_bytes=json.dumps(
                {
                    "bars": {
                        symbol: [
                            {"t": "2026-06-01T05:00:00Z", "c": first_close},
                            {"t": "2026-06-02T05:00:00Z", "c": "101"},
                            {"t": "2026-06-03T05:00:00Z", "c": "102"},
                            {"t": "2026-06-04T05:00:00Z", "c": "103"},
                            {"t": "2026-06-05T05:00:00Z", "c": "104"},
                            {"t": "2026-06-08T05:00:00Z", "c": last_close},
                        ]
                    }
                }
            ).encode("utf-8"),
            source_uri=(
                f"https://data.alpaca.markets/v2/stocks/{symbol}/bars?"
                "timeframe=1Day&feed=iex&adjustment=all"
                "&start=2026-06-01T00:00:00Z&end=2026-06-09T00:00:00Z"
            ),
            content_type="application/json",
            retrieved_at="2026-06-11T00:00:00+00:00",
        )
        artifacts[artifact.raw_artifact_id] = artifact
        receipts.append(
            build_source_bound_adjusted_price_window(
                archive=archive,
                raw_artifact=artifact,
                security_id=f"security-{symbol.lower()}",
                symbol=symbol,
                requested_start="2026-06-01",
                requested_end="2026-06-08",
                decision_cutoff="2026-06-12T00:00:00+00:00",
            )
        )
    return build_source_bound_window_lookup(
        archive=archive,
        raw_artifacts=artifacts,
        receipts=receipts,
    )


def _with_source_bound_evidence(
    forecasts: list[AgentForecast],
    *,
    source_bound_verifier,
) -> list[AgentForecast]:
    ticker = source_bound_verifier("XOM", "2026-06-01", "2026-06-08")
    benchmark = source_bound_verifier("SPY", "2026-06-01", "2026-06-08")
    assert ticker is not None and benchmark is not None
    return [
        replace(
            forecast,
            resolution_window={
                "intended_start": "2026-06-01",
                "intended_end": "2026-06-08",
            },
            resolution_evidence={
                "schema_version": "source_bound_resolution_evidence/v2",
                "ticker": ticker.source_evidence,
                "benchmark": benchmark.source_evidence,
                "alpha_threshold_pct": "1.5",
            },
        )
        for forecast in forecasts
    ]


def _with_verified_source_bound_result(
    forecast: AgentForecast,
    *,
    probability: str,
) -> AgentForecast:
    probability_value = Decimal(probability)
    return replace(
        forecast,
        probability=probability,
        resolved=True,
        outcome=True,
        actual_return="10.00",
        benchmark_return="2.00",
        relative_return="8.00",
        brier_score=str(((Decimal("1") - probability_value) ** 2).quantize(Decimal("0.0001"))),
        agent_score_delta=str((probability_value - Decimal("0.50")).quantize(Decimal("0.01"))),
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


def test_scoreboard_ranks_variants_within_their_role(tmp_path):
    variant_name = variant_agent_name(
        role="market_analyst", prompt_version="pv2", model_route="sonnet45"
    )
    rookie_name = variant_agent_name(
        role="market_analyst", prompt_version="pv3", model_route="haiku45"
    )
    forecasts = [
        # Baseline role: 4 source-verified resolutions with modest confidence.
        *[
            _with_verified_source_bound_result(
                _resolved_forecast("market_analyst", outcome=True, index=i),
                probability="0.51",
            )
            for i in range(4)
        ],
        # Challenger variant: 4 source-verified resolutions with stronger calibration.
        *[
            _with_verified_source_bound_result(
                _resolved_forecast(variant_name, outcome=True, index=i),
                probability="0.99",
            )
            for i in range(4)
        ],
        # Rookie variant: one resolved forecast, not enough history.
        _with_verified_source_bound_result(
            _resolved_forecast(rookie_name, outcome=True, index=0),
            probability="0.60",
        ),
        # A second role to prove grouping.
        _with_verified_source_bound_result(
            _resolved_forecast("trader", outcome=True, index=0),
            probability="0.60",
        ),
    ]

    verifier = _source_bound_verifier_for(tmp_path)
    board = variant_scoreboard(
        _with_source_bound_evidence(forecasts, source_bound_verifier=verifier),
        source_bound_verifier=verifier,
        min_resolved=3,
    )

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


def test_scoreboard_requires_source_bound_verifier_for_an_earned_leader():
    board = variant_scoreboard(
        [
            _resolved_forecast("market_analyst", outcome=True, index=index)
            for index in range(3)
        ],
        min_resolved=3,
    )

    role = board["roles"]["market_analyst"]
    assert role["leader"] is None
    assert role["variants"][0]["state"] not in {"earned_weight", "contextual_earned_weight"}
