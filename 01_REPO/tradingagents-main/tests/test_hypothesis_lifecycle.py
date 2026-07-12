"""Tests for the Hypothesis Lifecycle Ledger.

The hypothesis store (`hypotheses.jsonl`) is current-state-only: every factory
run rewrites it, so status transitions would otherwise vanish. The lifecycle
ledger is the append-only event history underneath it — registration,
supported/refuted/insufficient transitions, and prior emission/retraction are
recorded once, deterministically, and never rewritten.
"""

from __future__ import annotations

from tradingagents.evals.hypothesis_factory import (
    STATUS_INSUFFICIENT,
    STATUS_PREREGISTERED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    ResearchHypothesis,
)
from tradingagents.evals.hypothesis_lifecycle import (
    EVENT_HYPOTHESIS_EVIDENCE_INSUFFICIENT,
    EVENT_HYPOTHESIS_REFUTED,
    EVENT_HYPOTHESIS_REGISTERED,
    EVENT_HYPOTHESIS_SUPPORTED,
    EVENT_PRIOR_EMITTED,
    EVENT_PRIOR_RETRACTED,
    STATUS_EVENT_TYPES,
    HypothesisLifecycleEvent,
    append_lifecycle_events,
    hypothesis_lifecycle_events,
    load_lifecycle_events_with_stats,
    summarize_lifecycle,
)

REGISTERED_AT = "2026-06-10T00:14:48+00:00"
EVALUATED_AT = "2026-06-12T05:00:00+00:00"


def _hypothesis(
    hypothesis_id: str = "hyp-aaaaaaaaaaaaaaaa",
    *,
    status: str = STATUS_PREREGISTERED,
    context: dict[str, str] | None = None,
    out_of_sample_count: int = 0,
    out_of_sample_delta: str | None = None,
    evaluated_at: str | None = None,
) -> ResearchHypothesis:
    return ResearchHypothesis(
        hypothesis_id=hypothesis_id,
        claim="bearish forecasts outperform the resolved baseline",
        context=context or {"direction": "bearish"},
        comparison="outperforms_baseline",
        source="mined_from_resolution",
        preregistered_at=REGISTERED_AT,
        in_sample_count=9,
        in_sample_accuracy="0.3333",
        in_sample_baseline_accuracy="0.0833",
        in_sample_average_brier="0.2383",
        min_out_of_sample=8,
        edge_threshold="0.15",
        status=status,
        out_of_sample_count=out_of_sample_count,
        out_of_sample_delta=out_of_sample_delta,
        evaluated_at=evaluated_at,
    )


def _registered_event(hypothesis: ResearchHypothesis) -> HypothesisLifecycleEvent:
    events = hypothesis_lifecycle_events([hypothesis], [hypothesis], evaluated_at=EVALUATED_AT)
    assert len(events) == 1
    return events[0]


def test_status_vocabulary_matches_hypothesis_factory():
    assert set(STATUS_EVENT_TYPES) == {STATUS_SUPPORTED, STATUS_REFUTED, STATUS_INSUFFICIENT}
    assert STATUS_EVENT_TYPES[STATUS_SUPPORTED] == EVENT_HYPOTHESIS_SUPPORTED
    assert STATUS_EVENT_TYPES[STATUS_REFUTED] == EVENT_HYPOTHESIS_REFUTED
    assert STATUS_EVENT_TYPES[STATUS_INSUFFICIENT] == EVENT_HYPOTHESIS_EVIDENCE_INSUFFICIENT


def test_registration_is_backfilled_for_unrecorded_hypothesis():
    hypothesis = _hypothesis()
    events = hypothesis_lifecycle_events([hypothesis], [hypothesis], evaluated_at=EVALUATED_AT)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EVENT_HYPOTHESIS_REGISTERED
    assert event.hypothesis_id == hypothesis.hypothesis_id
    # Registration is dated at preregistration time, not at evaluation time.
    assert event.occurred_at == REGISTERED_AT
    assert event.from_status is None
    assert event.to_status == STATUS_PREREGISTERED
    assert event.context == {"direction": "bearish"}
    assert event.event_id.startswith("hle-")
    assert event.analysis_only is True
    assert event.execution_authority == "none"


def test_no_events_when_already_registered_and_status_unchanged():
    hypothesis = _hypothesis()
    registered = _registered_event(hypothesis)
    events = hypothesis_lifecycle_events(
        [hypothesis],
        [hypothesis],
        evaluated_at=EVALUATED_AT,
        known_events=[registered],
    )
    assert events == []


def test_newly_mined_hypothesis_gets_registration_event():
    hypothesis = _hypothesis("hyp-bbbbbbbbbbbbbbbb")
    events = hypothesis_lifecycle_events([], [hypothesis], evaluated_at=EVALUATED_AT)
    assert [event.event_type for event in events] == [EVENT_HYPOTHESIS_REGISTERED]


def test_supported_transition_emits_supported_and_prior_emitted():
    before = _hypothesis()
    after = _hypothesis(
        status=STATUS_SUPPORTED,
        out_of_sample_count=8,
        out_of_sample_delta="0.2500",
        evaluated_at=EVALUATED_AT,
    )
    events = hypothesis_lifecycle_events(
        [before],
        [after],
        evaluated_at=EVALUATED_AT,
        known_events=[_registered_event(before)],
        prior_multipliers={before.hypothesis_id: "1.25"},
    )
    assert [event.event_type for event in events] == [
        EVENT_HYPOTHESIS_SUPPORTED,
        EVENT_PRIOR_EMITTED,
    ]
    supported, emitted = events
    assert supported.from_status == STATUS_PREREGISTERED
    assert supported.to_status == STATUS_SUPPORTED
    assert supported.occurred_at == EVALUATED_AT
    assert supported.out_of_sample_count == 8
    assert supported.out_of_sample_delta == "0.2500"
    assert supported.claim == before.claim
    assert emitted.hypothesis_id == before.hypothesis_id
    assert emitted.prior_multiplier == "1.25"
    assert emitted.to_status == STATUS_SUPPORTED


def test_refuted_after_supported_emits_refuted_and_prior_retracted():
    before = _hypothesis(status=STATUS_SUPPORTED, out_of_sample_count=8)
    after = _hypothesis(
        status=STATUS_REFUTED,
        out_of_sample_count=16,
        out_of_sample_delta="0.0100",
        evaluated_at=EVALUATED_AT,
    )
    events = hypothesis_lifecycle_events(
        [before],
        [after],
        evaluated_at=EVALUATED_AT,
        known_events=[_registered_event(before)],
    )
    assert [event.event_type for event in events] == [
        EVENT_HYPOTHESIS_REFUTED,
        EVENT_PRIOR_RETRACTED,
    ]
    refuted, retracted = events
    assert refuted.from_status == STATUS_SUPPORTED
    assert refuted.to_status == STATUS_REFUTED
    assert retracted.from_status == STATUS_SUPPORTED
    assert retracted.prior_multiplier is None


def test_insufficient_transition_emits_evidence_insufficient_event():
    before = _hypothesis()
    after = _hypothesis(
        status=STATUS_INSUFFICIENT,
        out_of_sample_count=3,
        evaluated_at=EVALUATED_AT,
    )
    events = hypothesis_lifecycle_events(
        [before],
        [after],
        evaluated_at=EVALUATED_AT,
        known_events=[_registered_event(before)],
    )
    assert [event.event_type for event in events] == [EVENT_HYPOTHESIS_EVIDENCE_INSUFFICIENT]
    assert events[0].out_of_sample_count == 3


def test_event_ids_are_deterministic_and_append_dedupes(tmp_path):
    hypothesis = _hypothesis()
    path = tmp_path / "lifecycle" / "lifecycle.jsonl"
    first = hypothesis_lifecycle_events([hypothesis], [hypothesis], evaluated_at=EVALUATED_AT)
    second = hypothesis_lifecycle_events([hypothesis], [hypothesis], evaluated_at=EVALUATED_AT)
    assert [event.event_id for event in first] == [event.event_id for event in second]
    assert append_lifecycle_events(first, path=path) == 1
    assert append_lifecycle_events(second, path=path) == 0
    loaded, corrupt = load_lifecycle_events_with_stats(path)
    assert corrupt == 0
    assert [event.event_id for event in loaded] == [event.event_id for event in first]


def test_append_is_append_only_and_load_counts_corrupt_lines(tmp_path):
    path = tmp_path / "lifecycle.jsonl"
    hypothesis = _hypothesis()
    registered = _registered_event(hypothesis)
    append_lifecycle_events([registered], path=path)
    original_line = path.read_text(encoding="utf-8").splitlines()[0]
    insufficient = hypothesis_lifecycle_events(
        [hypothesis],
        [_hypothesis(status=STATUS_INSUFFICIENT, out_of_sample_count=3)],
        evaluated_at=EVALUATED_AT,
        known_events=[registered],
    )
    appended = append_lifecycle_events(insufficient, path=path)
    assert appended == len(insufficient) == 1
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == original_line  # history is never rewritten
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    loaded, corrupt = load_lifecycle_events_with_stats(path)
    assert corrupt == 1
    assert len(loaded) == 2


def test_load_missing_file_returns_empty():
    loaded, corrupt = load_lifecycle_events_with_stats("results/does-not-exist/lifecycle.jsonl")
    assert loaded == []
    assert corrupt == 0


def test_summarize_lifecycle_counts_events_and_keeps_safety_envelope():
    hypothesis = _hypothesis()
    registered = _registered_event(hypothesis)
    transitions = hypothesis_lifecycle_events(
        [hypothesis],
        [
            _hypothesis(
                status=STATUS_SUPPORTED,
                out_of_sample_count=8,
                out_of_sample_delta="0.25",
                evaluated_at=EVALUATED_AT,
            )
        ],
        evaluated_at=EVALUATED_AT,
        known_events=[registered],
        prior_multipliers={hypothesis.hypothesis_id: "1.25"},
    )
    summary = summarize_lifecycle([registered, *transitions])
    assert summary["kind"] == "hypothesis_lifecycle_summary"
    assert summary["event_count"] == 3
    assert summary["event_type_counts"] == {
        EVENT_HYPOTHESIS_REGISTERED: 1,
        EVENT_HYPOTHESIS_SUPPORTED: 1,
        EVENT_PRIOR_EMITTED: 1,
    }
    assert summary["hypothesis_count"] == 1
    assert summary["first_event_at"] == REGISTERED_AT
    assert summary["last_event_at"] == EVALUATED_AT
    latest = summary["latest_event_by_hypothesis"][hypothesis.hypothesis_id]
    assert latest["event_type"] == EVENT_PRIOR_EMITTED
    assert summary["analysis_only"] is True
    assert summary["can_submit_orders"] is False
    assert summary["execution_authority"] == "none"
