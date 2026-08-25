"""Tests for immutable point-in-time learning availability evidence."""

from __future__ import annotations

import datetime as dt
import json
import multiprocessing
from dataclasses import replace
from pathlib import Path

import pytest

from tradingagents.evals.agent_intelligence_ledger import AgentForecast
from tradingagents.evals.hypothesis_lifecycle import HypothesisLifecycleEvent
from tradingagents.evals.learning_availability import (
    LEARNING_AVAILABILITY_SCHEMA_VERSION,
    AvailabilityCorruptionError,
    LearningAvailabilityError,
    LearningAvailabilityLedger,
    LearningObservation,
    ObservationCollisionError,
    observe_forecasts,
    observe_lifecycle_events,
)

UTC = dt.timezone.utc
EFFECTIVE = dt.datetime(2026, 7, 18, 15, 0, tzinfo=UTC)
RECORDED = dt.datetime(2026, 7, 18, 15, 5, tzinfo=UTC)

FORECAST_FIELDS = {
    "forecast_id",
    "agent",
    "ticker",
    "forecast_type",
    "horizon",
    "probability",
    "direction",
    "benchmark",
    "sector",
    "evidence_sources",
    "evidence_refs",
    "setup",
    "regime",
    "created_at",
    "resolve_after",
    "source_packet_id",
    "resolved",
    "outcome",
    "actual_return",
    "benchmark_return",
    "relative_return",
    "brier_score",
    "agent_score_delta",
    "resolved_at",
    "label_quality",
    "quality_flags",
    "resolution_window",
}
SOURCE_BOUND_FORECAST_FIELDS = {"resolution_evidence", *FORECAST_FIELDS}
LIFECYCLE_FIELDS = {
    "event_id",
    "event_type",
    "hypothesis_id",
    "occurred_at",
    "from_status",
    "to_status",
    "out_of_sample_count",
    "out_of_sample_delta",
    "prior_multiplier",
    "context",
    "analysis_only",
    "execution_authority",
}


def _window() -> dict[str, object]:
    return {
        "intended_start": "2026-07-11",
        "intended_end": "2026-07-18",
        "expected_entry_session": "2026-07-13",
        "expected_exit_session": "2026-07-17",
        "expected_session_count": 5,
        "ticker_entry_date": "2026-07-13",
        "ticker_exit_date": "2026-07-17",
        "benchmark_entry_date": "2026-07-13",
        "benchmark_exit_date": "2026-07-17",
        "ticker_session_count": 5,
        "benchmark_session_count": 5,
        "final_bar_available": True,
        "horizon": "5 trading days",
        "horizon_kind": "trading_days_weekend_adjusted",
    }


def _resolution_evidence() -> dict[str, object]:
    def leg(*, marker: str) -> dict[str, str]:
        return {
            "schema_version": "source_bound_price_window_evidence/v1",
            "window_id": f"spw-{marker}",
            "window_sha256": marker * 64,
            "security_id": f"security-{marker}",
            "raw_artifact_id": f"pit-{marker}",
            "raw_artifact_sha256": marker * 64,
            "decision_cutoff": "2026-07-18T15:00:00+00:00",
            "retrieved_at": "2026-07-18T14:00:00+00:00",
            "feed": "iex",
            "adjustment_mode": "all",
            "adjustment_status": "total_return_adjusted",
        }

    return {
        "schema_version": "source_bound_resolution_evidence/v1",
        "ticker": leg(marker="a"),
        "benchmark": leg(marker="b"),
    }


def _forecast(**changes: object) -> AgentForecast:
    values: dict[str, object] = {
        "forecast_id": "af-safe-001",
        "agent": "market_analyst",
        "ticker": "NFLX",
        "claim": "forbidden raw claim",
        "forecast_type": "relative_return",
        "horizon": "5 trading days",
        "probability": "0.64",
        "expected_outcome": "forbidden raw recommendation",
        "direction": "bullish",
        "benchmark": "SPY",
        "sector": "communication_services",
        "evidence_sources": ["market_report"],
        "evidence_refs": ["packet:research:abc"],
        "setup": "overnight_tradingagents",
        "regime": "normal",
        "created_at": "2026-07-11T15:00:00+00:00",
        "resolve_after": "2026-07-18T15:00:00+00:00",
        "source_packet_id": "wp-run-research_evidence",
        "resolved": True,
        "outcome": True,
        "actual_return": "4.00",
        "benchmark_return": "1.00",
        "relative_return": "3.00",
        "brier_score": "0.1296",
        "agent_score_delta": "0.14",
        "resolved_at": EFFECTIVE.isoformat(timespec="seconds"),
        "resolution_note": "forbidden raw note",
        "label_quality": "high",
        "quality_flags": [],
        "resolution_window": _window(),
        "resolution_evidence": _resolution_evidence(),
    }
    values.update(changes)
    return AgentForecast(**values)


def _event(**changes: object) -> HypothesisLifecycleEvent:
    values: dict[str, object] = {
        "event_id": "hle-safe-001",
        "event_type": "hypothesis_supported",
        "hypothesis_id": "hyp-safe-001",
        "occurred_at": EFFECTIVE.isoformat(timespec="seconds"),
        "from_status": "preregistered",
        "to_status": "supported",
        "out_of_sample_count": 8,
        "out_of_sample_delta": "0.25",
        "prior_multiplier": "1.20",
        "context": {"agent": "market_analyst", "direction": "bullish"},
        "claim": "forbidden lifecycle claim",
        "note": "forbidden lifecycle note",
        "analysis_only": True,
        "execution_authority": "none",
    }
    values.update(changes)
    return HypothesisLifecycleEvent(**values)


def _record_forecast(root: str, index: int) -> None:
    forecast = _forecast(forecast_id=f"af-concurrent-{index:03d}")
    LearningAvailabilityLedger(root).record(
        LearningObservation.from_historical_forecast(
            forecast,
            recorded_at=RECORDED,
        )
    )


def test_exact_schema_authority_allowlist_and_forbidden_text_absence():
    observation = LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED)

    assert observation.schema_version == LEARNING_AVAILABILITY_SCHEMA_VERSION == 1
    assert observation.observation_id.startswith("lo-")
    assert len(observation.observation_id) == 67
    assert observation.source_kind == "forecast_resolution_quality"
    assert observation.effective_at == EFFECTIVE.isoformat(timespec="seconds")
    assert observation.recorded_at == RECORDED.isoformat(timespec="seconds")
    assert set(observation.payload) == FORECAST_FIELDS
    assert observation.analysis_only is True
    assert observation.execution_authority == "none"
    assert observation.can_submit_orders is False
    encoded = observation.canonical_json_bytes()
    assert b"forbidden raw claim" not in encoded
    assert b"forbidden raw recommendation" not in encoded
    assert b"forbidden raw note" not in encoded


def test_source_bound_observation_requires_issued_receipt_lookup():
    with pytest.raises(LearningAvailabilityError, match="exact SourceBoundWindowLookup"):
        LearningObservation.from_source_bound_forecast(
            _forecast(),
            recorded_at=RECORDED,
            verifier=None,
        )


def test_legacy_forecast_constructor_rejects_new_admission():
    with pytest.raises(LearningAvailabilityError, match="historical read-only"):
        LearningObservation.from_forecast(_forecast(), recorded_at=RECORDED)


def test_observe_forecasts_rejects_legacy_price_windows(tmp_path: Path):
    admissions = observe_forecasts(
        [_forecast(resolution_evidence=None)],
        availability_root=tmp_path,
        recorded_at=RECORDED,
    )

    assert admissions == ()
    assert not any(tmp_path.iterdir())


def test_lifecycle_payload_is_exact_and_omits_claim_and_note():
    observation = LearningObservation.from_lifecycle_event(_event(), recorded_at=RECORDED)
    assert observation.source_kind == "hypothesis_lifecycle"
    assert set(observation.payload) == LIFECYCLE_FIELDS
    encoded = observation.canonical_json_bytes()
    assert b"forbidden lifecycle claim" not in encoded
    assert b"forbidden lifecycle note" not in encoded


@pytest.mark.parametrize(
    "recorded_at",
    [
        dt.datetime(2026, 7, 18, 15, 5),
        dt.datetime(2026, 7, 18, 10, 5, tzinfo=dt.timezone(dt.timedelta(hours=-5))),
    ],
)
def test_recorded_at_requires_utc_timezone(recorded_at: dt.datetime):
    with pytest.raises(LearningAvailabilityError, match="recorded_at"):
        LearningObservation.from_historical_forecast(_forecast(), recorded_at=recorded_at)


def test_effective_time_cannot_be_future_relative_to_recorded():
    with pytest.raises(LearningAvailabilityError, match="effective_at"):
        LearningObservation.from_historical_forecast(
            _forecast(resolved_at="2026-07-18T15:06:00+00:00"),
            recorded_at=RECORDED,
        )


def test_nonfinite_payload_values_are_rejected():
    with pytest.raises(LearningAvailabilityError, match="finite canonical JSON"):
        LearningObservation.from_historical_forecast(
            _forecast(actual_return=float("nan")),
            recorded_at=RECORDED,
        )


def test_unresolved_or_unaudited_forecasts_are_neutral(tmp_path: Path):
    admissions = observe_forecasts(
        [
            _forecast(forecast_id="af-unresolved", resolved=False),
            _forecast(forecast_id="af-no-outcome", outcome=None),
            _forecast(forecast_id="af-unaudited", label_quality=None),
            _forecast(forecast_id="af-no-window", resolution_window=None),
        ],
        availability_root=tmp_path,
        recorded_at=RECORDED,
    )
    assert admissions == ()
    assert not any(tmp_path.iterdir())


def test_stable_id_excludes_recorded_at_and_later_retry_keeps_first_time(tmp_path: Path):
    first = LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED)
    later = LearningObservation.from_historical_forecast(
        _forecast(),
        recorded_at=RECORDED + dt.timedelta(minutes=10),
    )
    assert first.observation_id == later.observation_id

    ledger = LearningAvailabilityLedger(tmp_path)
    admitted = ledger.record(first)
    retried = ledger.record(later)

    assert admitted.created is True
    assert retried.created is False
    assert retried.path == admitted.path
    assert retried.observation.recorded_at == first.recorded_at
    assert len(ledger.verify()) == 1
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1


def test_earlier_retry_is_rejected_as_backdating(tmp_path: Path):
    ledger = LearningAvailabilityLedger(tmp_path)
    later = LearningObservation.from_historical_forecast(
        _forecast(),
        recorded_at=RECORDED + dt.timedelta(minutes=10),
    )
    ledger.record(later)
    earlier = LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED)
    with pytest.raises(ObservationCollisionError, match="backdat"):
        ledger.record(earlier)


def test_same_id_material_change_is_collision(tmp_path: Path):
    ledger = LearningAvailabilityLedger(tmp_path)
    original = LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED)
    ledger.record(original)
    changed = replace(original, source_id="af-other")
    with pytest.raises(ObservationCollisionError):
        ledger.record(changed)


def test_object_and_journal_are_canonical_and_strictly_verified(tmp_path: Path):
    ledger = LearningAvailabilityLedger(tmp_path)
    observation = LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED)
    admission = ledger.record(observation)
    assert admission.path.read_bytes() == observation.canonical_json_bytes()
    line = (tmp_path / "events.jsonl").read_bytes()
    assert line.endswith(b"\n")
    assert b" " not in line
    assert ledger.verify() == (observation,)

    event = json.loads(line)
    event["sequence"] = 2
    (tmp_path / "events.jsonl").write_text(
        json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AvailabilityCorruptionError, match="sequence"):
        ledger.verify()


def test_digest_tampering_is_detected(tmp_path: Path):
    ledger = LearningAvailabilityLedger(tmp_path)
    admission = ledger.record(
        LearningObservation.from_lifecycle_event(_event(), recorded_at=RECORDED)
    )
    payload = json.loads(admission.path.read_text(encoding="utf-8"))
    payload["payload"]["to_status"] = "refuted"
    admission.path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(AvailabilityCorruptionError, match="digest|canonical|identity"):
        ledger.verify()


def test_root_and_managed_paths_reject_symlinks(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(AvailabilityCorruptionError, match="root.*symlink"):
        LearningAvailabilityLedger(alias)

    ledger = LearningAvailabilityLedger(real)
    observations = real / "observations"
    observations.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(AvailabilityCorruptionError, match="observations"):
        ledger.record(LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED))


def test_crash_after_object_fsync_recovers_orphan_with_original_time(tmp_path: Path):
    class CrashAfterObject(LearningAvailabilityLedger):
        def _after_object_fsync(self, path: Path) -> None:
            raise RuntimeError("crash after object fsync")

    observation = LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED)
    with pytest.raises(RuntimeError, match="object fsync"):
        CrashAfterObject(tmp_path).record(observation)
    assert list((tmp_path / "observations").glob("*.json"))
    assert not (tmp_path / "events.jsonl").exists()

    later = replace(
        observation,
        recorded_at=(RECORDED + dt.timedelta(hours=1)).isoformat(timespec="seconds"),
    )
    admission = LearningAvailabilityLedger(tmp_path).record(later)
    assert admission.created is True
    assert admission.observation.recorded_at == observation.recorded_at
    assert LearningAvailabilityLedger(tmp_path).verify() == (observation,)


def test_crash_after_event_fsync_is_event_silent_on_retry(tmp_path: Path):
    class CrashAfterEvent(LearningAvailabilityLedger):
        def _after_event_fsync(self, event: object) -> None:
            raise RuntimeError("crash after event fsync")

    observation = LearningObservation.from_historical_forecast(_forecast(), recorded_at=RECORDED)
    with pytest.raises(RuntimeError, match="event fsync"):
        CrashAfterEvent(tmp_path).record(observation)
    admission = LearningAvailabilityLedger(tmp_path).record(observation)
    assert admission.created is False
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1


def test_record_many_is_sorted_and_retry_converges(tmp_path: Path):
    first = LearningObservation.from_historical_forecast(
        _forecast(forecast_id="af-z"), recorded_at=RECORDED
    )
    second = LearningObservation.from_lifecycle_event(_event(event_id="hle-a"), recorded_at=RECORDED)
    ledger = LearningAvailabilityLedger(tmp_path)
    admissions = ledger.record_many([first, second])
    assert [item.observation.observation_id for item in admissions] == sorted(
        [first.observation_id, second.observation_id]
    )
    assert [item.created for item in admissions] == [True, True]
    assert [item.created for item in ledger.record_many([second, first])] == [False, False]
    assert ledger.rebuild() == ledger.verify()


def test_concurrent_distinct_writers_keep_contiguous_journal(tmp_path: Path):
    count = 12
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(target=_record_forecast, args=(str(tmp_path), index))
        for index in range(count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    verified = LearningAvailabilityLedger(tmp_path).verify()
    assert len(verified) == count
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["sequence"] for event in events] == list(range(1, count + 1))


def test_concurrent_duplicate_writers_create_one_event(tmp_path: Path):
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(target=_record_forecast, args=(str(tmp_path), 1))
        for _ in range(12)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert len(LearningAvailabilityLedger(tmp_path).verify()) == 1
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1


def test_observe_lifecycle_events_dedupes_and_uses_atomic_created_flags(tmp_path: Path):
    first = observe_lifecycle_events([_event()], availability_root=tmp_path, recorded_at=RECORDED)
    second = observe_lifecycle_events(
        [_event()],
        availability_root=tmp_path,
        recorded_at=RECORDED + dt.timedelta(minutes=1),
    )
    assert len(first) == len(second) == 1
    assert first[0].created is True
    assert second[0].created is False
    assert second[0].observation.recorded_at == first[0].observation.recorded_at
