"""Tests for the agent-intelligence motor bridge into overnight research context.

Earned influence weights (Agent Intelligence Ledger) and supported hypothesis
priors (Hypothesis Factory) must reach future research runs as an advisory,
analysis-only context packet — and must degrade cleanly when the source files
are missing or malformed.
"""

from __future__ import annotations

import json

from tradingagents.research.overnight_context import (
    build_agent_intelligence_packet,
    build_overnight_prior_feed,
    build_overnight_research_context_packets,
    summarize_overnight_research_context,
)


def _summary_payload() -> dict:
    return {
        "forecast_count": 4784,
        "resolved_forecast_count": 132,
        "outcome_counts": {"harmful": 121, "useful": 11, "pending": 4652},
        "label_quality_counts": {"high": 100, "degraded": 20, "suspect": 12},
        "influence_weights": {
            "kind": "agent_influence_weights",
            "agents": {
                "market_analyst": {
                    "weight": "0.62",
                    "state": "earned_weight",
                    "resolved_count": 51,
                },
                "bull_researcher": {
                    "weight": "1.00",
                    "state": "insufficient_history",
                    "resolved_count": 0,
                },
            },
            "execution_authority": "none",
            "forbidden_effects": ["submit_order"],
        },
    }


def _priors_payload() -> dict:
    return {
        "kind": "research_priors",
        "prior_count": 1,
        "priors": [
            {
                "hypothesis_id": "hyp-434cc01a6433d705",
                "context": {"agent": "portfolio_manager", "direction": "bearish"},
                "comparison": "outperforms_baseline",
                "multiplier": "1.25",
                "out_of_sample_count": 9,
                "out_of_sample_delta": "0.25",
                "guidance": "portfolio_manager bearish calls outperform the baseline",
            }
        ],
        "multiplier_floor": "0.70",
        "multiplier_ceiling": "1.30",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
    }


def _write_sources(tmp_path, *, summary=True, priors=True):
    summary_path = tmp_path / "summary.json"
    priors_path = tmp_path / "priors.json"
    if summary:
        summary_path.write_text(json.dumps(_summary_payload()), encoding="utf-8")
    if priors:
        priors_path.write_text(json.dumps(_priors_payload()), encoding="utf-8")
    return summary_path, priors_path


def test_packet_carries_counts_weights_priors_and_advisory_language(tmp_path):
    summary_path, priors_path = _write_sources(tmp_path)
    packet = build_agent_intelligence_packet(
        agent_summary_path=summary_path,
        research_priors_path=priors_path,
    )
    assert packet.source_name == "agent_intelligence_ledger"
    assert packet.analysis_only is True
    assert packet.quality == "medium"
    payload = packet.payload
    assert payload["status"] == "ok"
    assert payload["summary_status"] == "ok"
    assert payload["priors_status"] == "ok"
    assert payload["forecast_count"] == 4784
    assert payload["resolved_forecast_count"] == 132
    assert payload["pending_forecast_count"] == 4652
    assert payload["label_quality_counts"]["suspect"] == 12
    assert payload["influence_weights"]["market_analyst"] == "0.62"
    assert payload["influence_states"]["bull_researcher"] == "insufficient_history"
    assert payload["prior_count"] == 1
    assert payload["research_priors"][0]["multiplier"] == "1.25"
    assert "advisory only" in payload["influence_context"]
    assert "cannot bypass live gates" in payload["influence_context"]
    assert "market_analyst: weight 0.62" in payload["influence_context"]
    assert "advisory only" in payload["priors_context"]
    assert "agent=portfolio_manager" in payload["priors_context"]
    assert "[1.25]" in payload["priors_context"]
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert "submit_order" in payload["forbidden_effects"]
    assert str(summary_path) == payload["source_paths"]["agent_summary"]


def test_missing_priors_degrade_to_neutral_weighting(tmp_path):
    summary_path, priors_path = _write_sources(tmp_path, priors=False)
    packet = build_agent_intelligence_packet(
        agent_summary_path=summary_path,
        research_priors_path=priors_path,
    )
    payload = packet.payload
    assert payload["status"] == "ok"
    assert payload["priors_status"] == "missing"
    assert payload["prior_count"] == 0
    assert payload["research_priors"] == []
    assert "no out-of-sample supported research priors" in payload["priors_context"]


def test_missing_and_malformed_sources_degrade_cleanly(tmp_path):
    missing = build_agent_intelligence_packet(
        agent_summary_path=tmp_path / "absent-summary.json",
        research_priors_path=tmp_path / "absent-priors.json",
    )
    assert missing.payload["status"] == "agent_intelligence_unavailable"
    assert missing.payload["summary_status"] == "missing"
    assert missing.payload["priors_status"] == "missing"
    assert missing.quality == "low"
    summary_path = tmp_path / "summary.json"
    priors_path = tmp_path / "priors.json"
    summary_path.write_text("{not valid json", encoding="utf-8")
    priors_path.write_text("[]", encoding="utf-8")
    malformed = build_agent_intelligence_packet(
        agent_summary_path=summary_path,
        research_priors_path=priors_path,
    )
    assert malformed.payload["summary_status"] == "malformed"
    assert malformed.payload["priors_status"] == "malformed"
    assert malformed.payload["prior_count"] == 0
    assert malformed.payload["can_submit_orders"] is False


def _bridge_only_packets(tmp_path, **overrides):
    summary_path, priors_path = _write_sources(tmp_path)
    options = {
        "evidence_needs": (),
        "include_source_quality": False,
        "include_reddit": False,
        "include_release_calendar": False,
        "include_social_watchlists": False,
        "include_methodology": False,
        "include_market_structure": False,
        "include_mirofish_handoff": False,
        "agent_intelligence_summary_path": summary_path,
        "research_priors_path": priors_path,
    }
    options.update(overrides)
    return build_overnight_research_context_packets(**options)


def test_overnight_context_includes_agent_intelligence_packet_with_flag(tmp_path):
    packets = _bridge_only_packets(tmp_path)
    assert [packet.source_name for packet in packets] == ["agent_intelligence_ledger"]
    disabled = _bridge_only_packets(tmp_path, include_agent_intelligence=False)
    assert disabled == []


def test_summary_and_prior_feed_surface_earned_intelligence(tmp_path):
    packets = _bridge_only_packets(tmp_path)
    summary = summarize_overnight_research_context(packets)
    block = summary["agent_intelligence"]
    assert block["resolved_forecast_count"] == 132
    assert block["influence_weights"]["market_analyst"] == "0.62"
    assert block["prior_count"] == 1
    assert block["blocked"] is False
    feed = build_overnight_prior_feed(summary)
    assert "agent_intelligence" in feed["carry_forward_scope"]
    feed_block = feed["agent_intelligence"]
    assert feed_block["influence_weights"]["market_analyst"] == "0.62"
    assert feed_block["research_priors"][0]["hypothesis_id"] == "hyp-434cc01a6433d705"
    assert feed_block["label_quality_counts"]["high"] == 100
    assert feed["analysis_only"] is True
    assert feed["execution_authority"] == "none"
