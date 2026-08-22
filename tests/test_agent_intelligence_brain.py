"""Tests for the Agent Intelligence brain packet.

The brain is the compact, durable state packet a future agent (or operator)
reads first: ledger truth, label quality, hypothesis state, lifecycle tail,
a maturity radar for when new evidence arrives, and machine-readable
attention flags + recommended actions. It must degrade cleanly — missing or
malformed sources become explicit statuses, never exceptions — and it must
never carry execution authority.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.agent_intelligence_brain import (
    FLAG_ALL_RESOLVED_SUSPECT,
    FLAG_DUE_FORECASTS,
    FLAG_FEED_LAG,
    FLAG_NO_TRUSTED_LABELS,
    FLAG_PRIORS_ACTIVE,
    FLAG_SOURCES_DEGRADED,
    build_agent_intelligence_brain,
    render_agent_intelligence_brain,
    write_agent_intelligence_brain,
)
from tradingagents.evals.agent_intelligence_ledger import AgentForecast, write_ledger
from tradingagents.evals.hypothesis_factory import (
    ResearchHypothesis,
    research_priors,
    summarize_hypotheses,
    write_hypotheses,
)
from tradingagents.evals.hypothesis_lifecycle import (
    EVENT_HYPOTHESIS_REGISTERED,
    append_lifecycle_events,
    hypothesis_lifecycle_events,
)

runner = CliRunner()

NOW = "2026-06-11T12:00:00+00:00"


def _forecast(
    forecast_id: str,
    *,
    resolve_after: str,
    resolved: bool = False,
    outcome: bool | None = None,
    label_quality: str | None = None,
) -> AgentForecast:
    return AgentForecast(
        forecast_id=forecast_id,
        agent="market_analyst",
        ticker="XOM",
        claim="test claim",
        forecast_type="test_direction",
        horizon="5 trading days",
        probability="0.60",
        expected_outcome="XOM outperforms SPY by >1.5%",
        direction="bullish",
        created_at="2026-06-01T00:00:00+00:00",
        resolve_after=resolve_after,
        resolved=resolved,
        outcome=outcome,
        brier_score="0.36" if resolved else None,
        label_quality=label_quality,
    )


def _hypothesis(status: str = "preregistered") -> ResearchHypothesis:
    return ResearchHypothesis(
        hypothesis_id="hyp-cccccccccccccccc",
        claim="bearish forecasts outperform the resolved baseline",
        context={"direction": "bearish"},
        comparison="outperforms_baseline",
        source="mined_from_resolution",
        preregistered_at="2026-06-10T00:14:48+00:00",
        in_sample_count=9,
        in_sample_accuracy="0.3333",
        in_sample_baseline_accuracy="0.0833",
        in_sample_average_brier="0.2383",
        min_out_of_sample=8,
        edge_threshold="0.15",
        status=status,
        out_of_sample_count=8 if status == "supported" else 0,
        out_of_sample_delta="0.2500" if status == "supported" else None,
    )


def _brain_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "ledger_path": tmp_path / "ledger.jsonl",
        "agent_summary_path": tmp_path / "summary.json",
        "resolution_quality_path": tmp_path / "resolution_quality.json",
        "hypothesis_store_path": tmp_path / "hypotheses.jsonl",
        "hypothesis_summary_path": tmp_path / "hypothesis_summary.json",
        "research_priors_path": tmp_path / "priors.json",
        "lifecycle_path": tmp_path / "lifecycle.jsonl",
    }


def _write_full_state(tmp_path: Path, *, hypothesis_status: str = "preregistered") -> dict[str, Path]:
    paths = _brain_paths(tmp_path)
    write_ledger(
        [
            _forecast(
                "af-resolved-1",
                resolve_after="2026-06-08T00:00:00+00:00",
                resolved=True,
                outcome=False,
                label_quality="suspect",
            ),
            _forecast(
                "af-resolved-2",
                resolve_after="2026-06-08T00:00:00+00:00",
                resolved=True,
                outcome=False,
                label_quality="suspect",
            ),
            _forecast("af-due-1", resolve_after="2026-06-10T20:00:00+00:00"),
            _forecast("af-soon-1", resolve_after="2026-06-13T20:00:00+00:00"),
            _forecast("af-soon-2", resolve_after="2026-06-13T20:00:00+00:00"),
            _forecast("af-far-1", resolve_after="2026-07-11T20:00:00+00:00"),
        ],
        path=paths["ledger_path"],
    )
    paths["agent_summary_path"].write_text(
        json.dumps(
            {
                "influence_weights": {
                    "agents": {
                        "market_analyst": {"weight": "0.62", "state": "earned_weight"},
                        "trader": {"weight": "1.00", "state": "insufficient_history"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    paths["resolution_quality_path"].write_text(
        json.dumps(
            {
                "kind": "resolution_quality_summary",
                "report_count": 4,
                "trusted_label_count": 0,
                "deferred_count": 1,
                "not_mature_count": 3,
                "resolvable_count": 0,
                "defer_reason_counts": {"final_bar_missing": 1},
                "label_quality_counts": {},
            }
        ),
        encoding="utf-8",
    )
    hypothesis = _hypothesis(hypothesis_status)
    write_hypotheses([hypothesis], path=paths["hypothesis_store_path"])
    paths["hypothesis_summary_path"].write_text(
        json.dumps(summarize_hypotheses([hypothesis])), encoding="utf-8"
    )
    paths["research_priors_path"].write_text(
        json.dumps(research_priors([hypothesis])), encoding="utf-8"
    )
    append_lifecycle_events(
        hypothesis_lifecycle_events([hypothesis], [hypothesis], evaluated_at=NOW),
        path=paths["lifecycle_path"],
    )
    return paths


def test_brain_fuses_full_state_with_radar_flags_and_actions(tmp_path):
    paths = _write_full_state(tmp_path)
    brain = build_agent_intelligence_brain(**paths, now=NOW)

    assert brain["kind"] == "agent_intelligence_brain"
    assert brain["schema"] == "agent_intelligence_brain_v1"
    assert brain["analysis_only"] is True
    assert brain["can_submit_orders"] is False
    assert brain["execution_authority"] == "none"
    assert brain["source_statuses"] == {
        "ledger": "ok",
        "agent_summary": "ok",
        "resolution_quality": "ok",
        "hypothesis_store": "ok",
        "hypothesis_summary": "ok",
        "research_priors": "ok",
        "lifecycle": "ok",
    }
    assert brain["ledger"]["forecast_count"] == 6
    assert brain["ledger"]["resolved_forecast_count"] == 2
    assert brain["ledger"]["pending_forecast_count"] == 4
    assert brain["ledger"]["label_quality_counts"] == {"suspect": 2}
    assert brain["influence"]["weights"]["market_analyst"] == "0.62"
    assert brain["influence"]["states"]["trader"] == "insufficient_history"
    assert brain["resolution_quality"]["trusted_label_count"] == 0
    assert brain["resolution_quality"]["defer_reason_counts"] == {"final_bar_missing": 1}

    radar = brain["maturity_radar"]
    assert radar["as_of"] == "2026-06-11"
    assert radar["horizon_days"] == 7
    assert radar["due_unresolved_count"] == 1
    assert radar["due_dates"] == {"2026-06-13": 2}
    assert radar["beyond_horizon_pending_count"] == 1
    assert radar["next_maturity_date"] == "2026-06-13"

    hypotheses = brain["hypotheses"]
    assert hypotheses["hypothesis_count"] == 1
    assert hypotheses["status_counts"] == {"preregistered": 1}
    assert hypotheses["supported_count"] == 0
    assert hypotheses["prior_count"] == 0
    assert len(hypotheses["active"]) == 1
    assert hypotheses["active"][0]["hypothesis_id"] == "hyp-cccccccccccccccc"
    assert hypotheses["active"][0]["min_out_of_sample"] == 8

    lifecycle = brain["lifecycle"]
    assert lifecycle["event_count"] == 1
    assert lifecycle["event_type_counts"] == {EVENT_HYPOTHESIS_REGISTERED: 1}
    assert lifecycle["last_events"][0]["event_type"] == EVENT_HYPOTHESIS_REGISTERED

    flags = brain["attention_flags"]
    assert FLAG_ALL_RESOLVED_SUSPECT in flags
    assert FLAG_NO_TRUSTED_LABELS in flags
    assert FLAG_FEED_LAG in flags
    assert FLAG_DUE_FORECASTS in flags
    assert FLAG_PRIORS_ACTIVE not in flags
    assert FLAG_SOURCES_DEGRADED not in flags

    actions = brain["recommended_actions"]
    assert actions
    assert any("ledger-quality-audit" in action for action in actions)
    assert any("agent-ledger-resolve" in action for action in actions)


def test_brain_degrades_cleanly_when_sources_missing(tmp_path):
    brain = build_agent_intelligence_brain(**_brain_paths(tmp_path), now=NOW)
    assert brain["source_statuses"]["ledger"] == "missing"
    assert brain["source_statuses"]["agent_summary"] == "missing"
    assert brain["source_statuses"]["research_priors"] == "missing"
    assert brain["ledger"]["forecast_count"] == 0
    assert brain["maturity_radar"]["due_unresolved_count"] == 0
    assert brain["maturity_radar"]["next_maturity_date"] is None
    assert FLAG_SOURCES_DEGRADED in brain["attention_flags"]
    assert brain["recommended_actions"]
    assert brain["execution_authority"] == "none"


def test_brain_marks_malformed_sources_without_raising(tmp_path):
    paths = _write_full_state(tmp_path)
    paths["agent_summary_path"].write_text("{not json", encoding="utf-8")
    paths["research_priors_path"].write_text("[]", encoding="utf-8")
    brain = build_agent_intelligence_brain(**paths, now=NOW)
    assert brain["source_statuses"]["agent_summary"] == "malformed"
    assert brain["source_statuses"]["research_priors"] == "malformed"
    assert FLAG_SOURCES_DEGRADED in brain["attention_flags"]
    assert brain["influence"]["weights"] == {}


def test_brain_radar_fails_closed_on_extreme_maturity_overflow(tmp_path):
    paths = _brain_paths(tmp_path)
    write_ledger(
        [
            _forecast("af-due-ok", resolve_after="2026-06-10T20:00:00+00:00"),
            _forecast(
                "af-extreme-maturity-overflow",
                resolve_after="9999-12-31T23:59:59-14:00",
            ),
        ],
        path=paths["ledger_path"],
    )

    brain = build_agent_intelligence_brain(**paths, now=NOW)

    radar = brain["maturity_radar"]
    assert radar["unparseable_maturity_count"] == 1
    assert radar["due_unresolved_count"] == 1
    assert radar["due_dates"] == {}
    assert radar["beyond_horizon_pending_count"] == 0
    assert radar["next_maturity_date"] is None
    assert brain["ledger"]["forecast_count"] == 2
    assert brain["ledger"]["pending_forecast_count"] == 2


def test_brain_surfaces_supported_priors(tmp_path):
    paths = _write_full_state(tmp_path, hypothesis_status="supported")
    brain = build_agent_intelligence_brain(**paths, now=NOW)
    assert brain["hypotheses"]["supported_count"] == 1
    assert brain["hypotheses"]["prior_count"] == 1
    assert brain["research_priors"][0]["hypothesis_id"] == "hyp-cccccccccccccccc"
    assert FLAG_PRIORS_ACTIVE in brain["attention_flags"]
    # A supported hypothesis is no longer waiting on out-of-sample evidence.
    assert brain["hypotheses"]["active"] == []


def test_render_and_write_brain(tmp_path):
    paths = _write_full_state(tmp_path)
    brain = build_agent_intelligence_brain(**paths, now=NOW)
    text = render_agent_intelligence_brain(brain)
    assert "advisory" in text.lower()
    assert "trusted labels: 0" in text.lower()
    brain_path = tmp_path / "out" / "brain.json"
    written = write_agent_intelligence_brain(brain, path=brain_path)
    assert written == brain_path
    assert json.loads(brain_path.read_text(encoding="utf-8")) == brain


def test_cli_agent_intelligence_brief_writes_brain(tmp_path):
    paths = _write_full_state(tmp_path)
    brain_path = tmp_path / "brain.json"
    args = [
        "research",
        "agent-intelligence-brief",
        "--ledger-path",
        str(paths["ledger_path"]),
        "--summary-path",
        str(paths["agent_summary_path"]),
        "--quality-path",
        str(paths["resolution_quality_path"]),
        "--hypothesis-store-path",
        str(paths["hypothesis_store_path"]),
        "--hypothesis-summary-path",
        str(paths["hypothesis_summary_path"]),
        "--priors-path",
        str(paths["research_priors_path"]),
        "--lifecycle-path",
        str(paths["lifecycle_path"]),
        "--brain-path",
        str(brain_path),
    ]
    result = runner.invoke(app, [*args, "--json-output"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "agent_intelligence_brain"
    assert payload["brain_path"] == str(brain_path)
    assert brain_path.exists()

    plain = runner.invoke(app, args)
    assert plain.exit_code == 0, plain.output
    assert "Agent Intelligence" in plain.output
