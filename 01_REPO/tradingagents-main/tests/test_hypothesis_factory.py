"""Tests for the Hypothesis Factory kernel.

The factory's core guarantee is epistemic: in-sample mining can propose a
hypothesis, but only forecasts created after preregistration can support or
refute it. These tests prove the no-peeking guarantee, the full
preregister -> evaluate lifecycle, dedupe-on-remine, and the advisory-only
safety envelope of every emitted packet.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from tradingagents.evals.agent_intelligence_ledger import AgentForecast, write_ledger
from tradingagents.evals.hypothesis_factory import (
    STATUS_PREREGISTERED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    ResearchHypothesis,
    evaluate_hypotheses,
    load_hypotheses,
    merge_hypotheses,
    mine_hypotheses,
    render_research_priors_context,
    research_priors,
    run_hypothesis_factory,
    summarize_hypotheses,
)
from tradingagents.evals.hypothesis_lifecycle import (
    EVENT_HYPOTHESIS_REGISTERED,
    EVENT_HYPOTHESIS_SUPPORTED,
    EVENT_PRIOR_EMITTED,
    load_lifecycle_events_with_stats,
)

MINE_AT = "2026-02-01T00:00:00+00:00"
IN_SAMPLE_AT = "2026-01-05T00:00:00+00:00"
OUT_OF_SAMPLE_AT = "2026-03-05T00:00:00+00:00"


def _forecast(
    agent: str,
    outcome: bool,
    *,
    created_at: str = IN_SAMPLE_AT,
    index: int = 0,
    direction: str = "bullish",
    setup: str = "overnight_tradingagents",
    regime: str = "pdt_reform_window",
    sector: str = "energy",
    label_quality: str | None = "high",
) -> AgentForecast:
    return AgentForecast(
        forecast_id=f"af-{agent}-{created_at}-{index}",
        agent=agent,
        ticker="XOM",
        claim=f"{agent} test claim",
        forecast_type="test_direction",
        horizon="5 trading days",
        probability="0.60",
        expected_outcome="XOM outperforms SPY by >1.5%",
        direction=direction,
        setup=setup,
        regime=regime,
        sector=sector,
        created_at=created_at,
        resolve_after=created_at,
        resolved=True,
        outcome=outcome,
        brier_score="0.16" if outcome else "0.36",
        label_quality=label_quality,
    )


def _in_sample_cohort() -> list[AgentForecast]:
    bad = [_forecast("bad_agent", False, index=i) for i in range(12)]
    good = [_forecast("good_agent", True, index=i) for i in range(12)]
    return [*bad, *good]


def _hypothesis_for(hypotheses, agent: str) -> ResearchHypothesis:
    matches = [
        h for h in hypotheses if h.context == {"agent": agent}
    ]
    assert matches, f"expected a hypothesis with context agent={agent}"
    return matches[0]


def test_mining_preregisters_deviating_cells_with_frozen_in_sample_evidence():
    hypotheses = mine_hypotheses(_in_sample_cohort(), now=MINE_AT)
    bad = _hypothesis_for(hypotheses, "bad_agent")
    assert bad.status == STATUS_PREREGISTERED
    assert bad.comparison == "underperforms_baseline"
    assert bad.in_sample_count == 12
    assert Decimal(bad.in_sample_accuracy) == Decimal("0")
    assert Decimal(bad.in_sample_baseline_accuracy) == Decimal("0.5")
    assert bad.preregistered_at == MINE_AT
    assert bad.analysis_only is True
    assert bad.execution_authority == "none"
    good = _hypothesis_for(hypotheses, "good_agent")
    assert good.comparison == "outperforms_baseline"


def test_mining_ignores_cells_below_min_sample_and_threshold():
    cohort = _in_sample_cohort()
    assert mine_hypotheses(cohort, min_sample=13, now=MINE_AT) == []
    assert mine_hypotheses(cohort, edge_threshold="0.95", now=MINE_AT) == []


def test_no_peeking_in_sample_evidence_cannot_support_a_hypothesis():
    cohort = _in_sample_cohort()
    hypotheses = mine_hypotheses(cohort, now=MINE_AT)
    bad = _hypothesis_for(hypotheses, "bad_agent")
    evaluated = evaluate_hypotheses([bad], cohort, now=MINE_AT)
    assert len(evaluated) == 1
    result = evaluated[0]
    # Perfect in-sample signal, zero out-of-sample evidence: stays preregistered.
    assert result.status == STATUS_PREREGISTERED
    assert result.out_of_sample_count == 0
    assert result.out_of_sample_accuracy is None


def test_supported_when_effect_persists_out_of_sample():
    cohort = _in_sample_cohort()
    bad = _hypothesis_for(mine_hypotheses(cohort, now=MINE_AT), "bad_agent")
    out_of_sample = [
        *[
            _forecast("bad_agent", False, created_at=OUT_OF_SAMPLE_AT, index=i)
            for i in range(8)
        ],
        *[
            _forecast("good_agent", True, created_at=OUT_OF_SAMPLE_AT, index=i)
            for i in range(8)
        ],
    ]
    evaluated = evaluate_hypotheses([bad], [*cohort, *out_of_sample], now=OUT_OF_SAMPLE_AT)
    result = evaluated[0]
    assert result.status == STATUS_SUPPORTED
    assert result.out_of_sample_count == 8
    assert Decimal(result.out_of_sample_delta) < 0
    priors = research_priors(evaluated)
    assert priors["prior_count"] == 1
    prior = priors["priors"][0]
    assert prior["context"] == {"agent": "bad_agent"}
    assert Decimal(prior["multiplier"]) < Decimal("1.00")
    assert Decimal(prior["multiplier"]) >= Decimal(priors["multiplier_floor"])
    context_text = render_research_priors_context(priors)
    assert "advisory only" in context_text
    assert "agent=bad_agent" in context_text


def test_refuted_when_effect_vanishes_out_of_sample():
    cohort = _in_sample_cohort()
    bad = _hypothesis_for(mine_hypotheses(cohort, now=MINE_AT), "bad_agent")
    out_of_sample = [
        *[
            _forecast("bad_agent", True, created_at=OUT_OF_SAMPLE_AT, index=i)
            for i in range(8)
        ],
        *[
            _forecast("good_agent", True, created_at=OUT_OF_SAMPLE_AT, index=i)
            for i in range(8)
        ],
    ]
    evaluated = evaluate_hypotheses([bad], [*cohort, *out_of_sample], now=OUT_OF_SAMPLE_AT)
    result = evaluated[0]
    assert result.status == STATUS_REFUTED
    assert research_priors(evaluated)["prior_count"] == 0


def test_mining_excludes_suspect_labels_from_evidence():
    cohort = [
        *[_forecast("bad_agent", False, index=i, label_quality="suspect") for i in range(12)],
        *[_forecast("good_agent", True, index=i) for i in range(12)],
    ]
    hypotheses = mine_hypotheses(cohort, now=MINE_AT)
    assert not [h for h in hypotheses if h.context == {"agent": "bad_agent"}]


def test_require_audited_labels_excludes_unaudited_evidence():
    cohort = [
        *[_forecast("bad_agent", False, index=i, label_quality=None) for i in range(12)],
        *[_forecast("good_agent", True, index=i) for i in range(12)],
    ]
    permissive = mine_hypotheses(cohort, now=MINE_AT)
    assert [h for h in permissive if h.context == {"agent": "bad_agent"}]
    strict = mine_hypotheses(cohort, now=MINE_AT, require_audited_labels=True)
    assert not [h for h in strict if h.context == {"agent": "bad_agent"}]


def test_evaluate_ignores_suspect_out_of_sample_evidence():
    cohort = _in_sample_cohort()
    bad = _hypothesis_for(mine_hypotheses(cohort, now=MINE_AT), "bad_agent")
    suspect_oos = [
        _forecast(
            "bad_agent",
            False,
            created_at=OUT_OF_SAMPLE_AT,
            index=i,
            label_quality="suspect",
        )
        for i in range(8)
    ]
    evaluated = evaluate_hypotheses([bad], [*cohort, *suspect_oos], now=OUT_OF_SAMPLE_AT)
    result = evaluated[0]
    assert result.status == STATUS_PREREGISTERED
    assert result.out_of_sample_count == 0


def test_run_factory_reports_label_quality_gates_and_corrupt_store_lines(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    cohort = [
        *_in_sample_cohort(),
        _forecast("bad_agent", True, index=90, label_quality="suspect"),
        _forecast("bad_agent", True, index=91, label_quality="suspect"),
        _forecast("bad_agent", True, index=92, label_quality=None),
    ]
    write_ledger(cohort, path=ledger_path)
    store_path = tmp_path / "hypotheses.jsonl"
    store_path.write_text("{corrupt line\n", encoding="utf-8")
    priors_path = tmp_path / "priors.json"
    summary_path = tmp_path / "summary.json"

    payload = run_hypothesis_factory(
        ledger_path=ledger_path,
        store_path=store_path,
        priors_path=priors_path,
        summary_path=summary_path,
        now=MINE_AT,
    )

    assert payload["require_audited_labels"] is True
    assert payload["resolved_forecast_count"] == 27
    assert payload["minable_forecast_count"] == 24
    assert payload["excluded_suspect_count"] == 2
    assert payload["excluded_unaudited_count"] == 1
    assert payload["corrupt_store_line_count"] == 1
    assert payload["mined_count"] > 0
    priors = json.loads(priors_path.read_text(encoding="utf-8"))
    assert priors["can_submit_orders"] is False
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["can_submit_orders"] is False


def test_merge_never_re_registers_an_existing_hypothesis():
    cohort = _in_sample_cohort()
    first = mine_hypotheses(cohort, now=MINE_AT)
    re_mined = mine_hypotheses(cohort, now="2026-04-01T00:00:00+00:00")
    merged, appended = merge_hypotheses(first, re_mined)
    assert appended == 0
    assert {h.hypothesis_id for h in merged} == {h.hypothesis_id for h in first}
    # The out-of-sample clock must not reset.
    assert all(h.preregistered_at == MINE_AT for h in merged)


def test_run_hypothesis_factory_end_to_end_is_idempotent(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    write_ledger(_in_sample_cohort(), path=ledger_path)
    store_path = tmp_path / "hypotheses.jsonl"
    priors_path = tmp_path / "priors.json"
    summary_path = tmp_path / "summary.json"
    payload = run_hypothesis_factory(
        ledger_path=ledger_path,
        store_path=store_path,
        priors_path=priors_path,
        summary_path=summary_path,
        now=MINE_AT,
    )
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert "submit_order" in payload["forbidden_effects"]
    assert payload["resolved_forecast_count"] == 24
    assert payload["mined_count"] > 0
    assert payload["appended_count"] == payload["mined_count"]
    assert payload["prior_count"] == 0  # no out-of-sample evidence yet
    assert payload["status_counts"] == {STATUS_PREREGISTERED: payload["hypothesis_count"]}
    assert store_path.exists() and priors_path.exists() and summary_path.exists()
    again = run_hypothesis_factory(
        ledger_path=ledger_path,
        store_path=store_path,
        priors_path=priors_path,
        summary_path=summary_path,
        now=MINE_AT,
    )
    assert again["appended_count"] == 0
    assert again["hypothesis_count"] == payload["hypothesis_count"]
    stored = load_hypotheses(store_path)
    assert len(stored) == payload["hypothesis_count"]
    summary = summarize_hypotheses(stored)
    assert summary["execution_authority"] == "none"
    assert summary["hypothesis_count"] == payload["hypothesis_count"]


def test_run_factory_appends_lifecycle_registrations_idempotently(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    write_ledger(_in_sample_cohort(), path=ledger_path)
    store_path = tmp_path / "hypotheses.jsonl"
    factory_paths = dict(
        ledger_path=ledger_path,
        store_path=store_path,
        priors_path=tmp_path / "priors.json",
        summary_path=tmp_path / "summary.json",
    )

    payload = run_hypothesis_factory(**factory_paths, now=MINE_AT)

    # The lifecycle ledger lives next to the store unless overridden, so
    # tmp-path runs never touch the real results tree.
    lifecycle_path = Path(payload["lifecycle_path"])
    assert lifecycle_path == store_path.with_name("lifecycle.jsonl")
    events, corrupt = load_lifecycle_events_with_stats(lifecycle_path)
    assert corrupt == 0
    assert payload["corrupt_lifecycle_line_count"] == 0
    assert payload["lifecycle_appended_event_count"] == payload["hypothesis_count"]
    assert payload["lifecycle_total_event_count"] == payload["hypothesis_count"]
    assert len(events) == payload["hypothesis_count"]
    assert {event.event_type for event in events} == {EVENT_HYPOTHESIS_REGISTERED}
    assert payload["lifecycle_event_type_counts"] == {
        EVENT_HYPOTHESIS_REGISTERED: payload["hypothesis_count"]
    }
    # Registration events are dated at preregistration time.
    assert {event.occurred_at for event in events} == {MINE_AT}

    again = run_hypothesis_factory(**factory_paths, now=MINE_AT)
    assert again["lifecycle_appended_event_count"] == 0
    assert again["lifecycle_total_event_count"] == payload["hypothesis_count"]


def test_run_factory_records_first_supported_verdict_in_lifecycle(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    write_ledger(_in_sample_cohort(), path=ledger_path)
    store_path = tmp_path / "hypotheses.jsonl"
    factory_paths = dict(
        ledger_path=ledger_path,
        store_path=store_path,
        priors_path=tmp_path / "priors.json",
        summary_path=tmp_path / "summary.json",
    )
    run_hypothesis_factory(**factory_paths, now=MINE_AT)
    bad_id = next(
        h.hypothesis_id
        for h in load_hypotheses(store_path)
        if h.context == {"agent": "bad_agent"}
    )
    out_of_sample = [
        *[
            _forecast("bad_agent", False, created_at=OUT_OF_SAMPLE_AT, index=i)
            for i in range(8)
        ],
        *[
            _forecast("good_agent", True, created_at=OUT_OF_SAMPLE_AT, index=i)
            for i in range(8)
        ],
    ]
    write_ledger([*_in_sample_cohort(), *out_of_sample], path=ledger_path)

    payload = run_hypothesis_factory(**factory_paths, now=OUT_OF_SAMPLE_AT)

    assert payload["prior_count"] >= 1
    events, _ = load_lifecycle_events_with_stats(Path(payload["lifecycle_path"]))
    bad_events = [event for event in events if event.hypothesis_id == bad_id]
    bad_event_types = {event.event_type for event in bad_events}
    assert EVENT_HYPOTHESIS_SUPPORTED in bad_event_types
    assert EVENT_PRIOR_EMITTED in bad_event_types
    supported = next(
        event for event in bad_events if event.event_type == EVENT_HYPOTHESIS_SUPPORTED
    )
    assert supported.from_status == STATUS_PREREGISTERED
    assert supported.to_status == STATUS_SUPPORTED
    assert supported.out_of_sample_count == 8
    emitted = next(
        event for event in bad_events if event.event_type == EVENT_PRIOR_EMITTED
    )
    assert emitted.prior_multiplier is not None
    assert Decimal(emitted.prior_multiplier) < Decimal("1.00")
