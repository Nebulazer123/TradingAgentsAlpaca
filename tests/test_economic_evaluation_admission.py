"""Contract tests for immutable admission of a frozen economic protocol."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

from tradingagents.evals import economic_evaluation_admission as admission_module
from tradingagents.evals.economic_evaluation_admission import (
    EconomicEvaluationAdmissionAdapter,
    EconomicEvaluationAdmissionError,
)
from tradingagents.evals.economic_evaluation_protocol import (
    EvaluationSearchBudget,
    build_bitemporal_input_manifest,
    build_decision_event,
    build_frozen_evaluation_protocol,
    canonical_universe_id,
)
from tradingagents.evals.economic_evaluation_result import (
    EconomicEvaluationResultError,
    build_validation_evaluation_result,
    validate_economic_validation_result,
)
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy

NOW = dt.datetime(2026, 1, 9, 21, 30, tzinfo=dt.UTC)


def _protocol():
    primary = tuple(f"T{i:03d}" for i in range(75))
    events = tuple(
        build_decision_event(
            universe_id=canonical_universe_id(primary),
            symbol=symbol,
            decision_at="2026-01-09T20:55:00+00:00",
            market_date="2026-01-09",
            horizon_sessions=5,
            horizon="5_sessions",
            benchmark="SPY",
            created_at="2026-01-09T20:45:00+00:00",
            resolution_window={"start_at": "2026-01-09T20:55:00+00:00"},
            observation_start="2026-01-09T19:00:00+00:00",
            observation_end="2026-01-09T20:50:00+00:00",
            available_at="2026-01-09T20:50:00+00:00",
            recorded_at="2026-01-09T20:52:00+00:00",
            source_packet_id=f"packet-{symbol.lower()}",
            source_artifact_id=f"artifact-{symbol.lower()}",
            source_artifact_sha256=hashlib.sha256(symbol.encode()).hexdigest(),
        )
        for symbol in ("T000", "T001", "T002")
    )
    manifest = build_bitemporal_input_manifest(
        dataset_id="pit-admission-fixture",
        as_of_cutoff="2026-01-09T21:00:00+00:00",
        captured_at="2026-01-09T21:00:00+00:00",
        events=events,
    )
    policy = StrategyEvaluationPolicy(
        benchmark_symbol="SPY",
        holding_sessions=5,
        commission_bps_per_side="0",
        half_spread_bps_per_side="5",
        slippage_bps_per_side="5",
        round_trip_sides=2,
    )
    return build_frozen_evaluation_protocol(
        input_manifest=manifest,
        primary_universe=primary,
        sensitivity_universe_50=primary[:50],
        sensitivity_universe_100=tuple(f"T{i:03d}" for i in range(100)),
        evaluation_policy=policy,
        search_budget=EvaluationSearchBudget(5, 3, 25),
        development_event_ids=(manifest.events[0].decision_event_id,),
        validation_event_ids=(manifest.events[1].decision_event_id,),
        holdout_event_ids=(manifest.events[2].decision_event_id,),
    )


def _adapter(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "evaluation.py").write_text("VALUE = 'frozen'\n", encoding="utf-8")
    return EconomicEvaluationAdmissionAdapter(
        tmp_path / "evidence",
        repo_root=repo_root,
        clock=lambda: NOW,
    )


def test_admission_binds_complete_protocol_source_bytes_and_store_predecessor(tmp_path):
    protocol = _protocol()
    admission = _adapter(tmp_path).admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    assert admission.created is True
    assert admission.protocol_id == protocol.protocol_id
    assert admission.input_manifest_sha256 == protocol.input_manifest_sha256
    assert admission.predecessor_sequence == 0
    assert admission.predecessor_event_sha256 == "0" * 64
    assert admission.envelope.kind == "economic-evaluation-protocol"
    assert admission.envelope.payload["source_revision"] == "a" * 40
    assert admission.envelope.payload["analysis_only"] is True
    assert admission.envelope.payload["can_submit_orders"] is False


def test_same_admitted_protocol_is_idempotent_but_not_reissued(tmp_path):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    first = adapter.admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    second = adapter.admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    assert first.created is True
    assert second.created is False
    assert second.envelope.object_id == first.envelope.object_id


def test_admission_rejects_changed_provenance_for_an_existing_protocol(tmp_path):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    adapter.admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    (tmp_path / "repo" / "evaluation.py").write_text(
        "VALUE = 'changed'\n",
        encoding="utf-8",
    )

    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.admit_protocol(
            protocol,
            source_revision="a" * 40,
            effective_at=NOW,
            source_paths=("evaluation.py",),
        )


def test_admission_rejects_source_bytes_changed_during_preflight(
    tmp_path,
    monkeypatch,
):
    adapter = _adapter(tmp_path)
    original_manifest = admission_module._source_manifest
    calls = 0

    def mutate_after_first_preflight(root, paths):
        nonlocal calls
        rows, digest = original_manifest(root, paths)
        calls += 1
        if calls == 1:
            (root / "evaluation.py").write_text(
                "VALUE = 'changed during preflight'\n",
                encoding="utf-8",
            )
        return rows, digest

    monkeypatch.setattr(
        admission_module,
        "_source_manifest",
        mutate_after_first_preflight,
    )

    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.admit_protocol(
            _protocol(),
            source_revision="a" * 40,
            effective_at=NOW,
            source_paths=("evaluation.py",),
        )


def test_admission_rejects_changed_evidence_store_head_after_preflight(
    tmp_path,
    monkeypatch,
):
    adapter = _adapter(tmp_path)
    original_verify = adapter._store.verify_with_events

    def change_head_after_preflight():
        snapshot, events = original_verify()
        concurrent_store = ImmutableStrategyEvidenceStore(
            adapter._store.root,
            clock=lambda: NOW,
        )
        concurrent_store.admit_checked(
            EvidenceCandidate(
                kind="evaluation-registration",
                effective_at="2026-01-09T21:30:00+00:00",
                payload={"fixture": "concurrent-head-change"},
            ),
            validate=lambda _snapshot, _envelope: None,
        )
        return snapshot, events

    monkeypatch.setattr(adapter._store, "verify_with_events", change_head_after_preflight)

    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.admit_protocol(
            _protocol(),
            source_revision="a" * 40,
            effective_at=NOW,
            source_paths=("evaluation.py",),
        )


def test_admission_rejects_an_orphaned_economic_protocol_object(tmp_path):
    class CrashAfterObject(ImmutableStrategyEvidenceStore):
        def _after_object_fsync(self, _object_path):
            raise RuntimeError("simulated crash after durable object")

    root = tmp_path / "evidence"
    crashing_store = CrashAfterObject(root, clock=lambda: NOW)
    with pytest.raises(RuntimeError):
        crashing_store.admit_checked(
            EvidenceCandidate(
                kind="economic-evaluation-protocol",
                effective_at="2026-01-09T21:30:00+00:00",
                payload={"forged": "orphan"},
            ),
            validate=lambda _snapshot, _envelope: None,
        )

    with pytest.raises(EconomicEvaluationAdmissionError):
        _adapter(tmp_path).admit_protocol(
            _protocol(),
            source_revision="a" * 40,
            effective_at=NOW,
            source_paths=("evaluation.py",),
        )


def _validation_report(protocol):
    result = build_validation_evaluation_result(
        protocol,
        arm_metrics={
            arm_id: {
                "net_return_after_costs": "0",
                "benchmark_excess_after_costs": "0",
                "max_drawdown": "0",
                "turnover": "0",
                "false_positive_rate": "0",
                "decision_event_count": "1",
                "packet_event_cluster_count": "1",
                "market_event_cluster_count": "1",
                "cost_per_useful_decision": "0",
            }
            for arm_id in (
                "cash",
                "spy",
                "equal_weight",
                "momentum_quality",
                "pullback_support",
            )
        },
    )
    return {
        "schema_version": "economic_validation_report/v1",
        "protocol_id": protocol.protocol_id,
        "validation_event_ids": list(protocol.validation_event_ids),
        "result": result.to_dict(),
        "result_id": result.result_id,
        "result_sha256": result.result_sha256,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def test_validation_result_is_complete_canonical_and_alias_resistant():
    protocol = _protocol()
    result = _validation_report(protocol)["result"]
    parsed = validate_economic_validation_result(json.loads(json.dumps(result)))

    assert parsed.protocol_id == protocol.protocol_id
    assert parsed.validation_event_ids == protocol.validation_event_ids
    assert [row["arm_id"] for row in parsed.arm_metrics] == [
        "cash",
        "spy",
        "equal_weight",
        "momentum_quality",
        "pullback_support",
    ]
    with pytest.raises(TypeError):
        parsed.arm_metrics[0]["metrics"]["turnover"] = "1"
    with pytest.raises(TypeError):
        parsed.arm_metrics[0]["arm_id"] = "forged-arm"

    tampered = json.loads(parsed.canonical_json_bytes())
    tampered["arm_metrics"][0]["metrics"]["decision_event_count"] = "2"
    with pytest.raises(EconomicEvaluationResultError):
        validate_economic_validation_result(tampered)


def test_holdout_release_requires_admitted_protocol_and_freezes_validation_report(
    tmp_path,
):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    admitted = adapter.admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    validation_run = adapter.admit_evaluation_run(
        protocol.protocol_id,
        phase="validation",
        effective_at=NOW,
        frozen_validation_report=_validation_report(protocol),
    )

    release = adapter.release_holdout(
        protocol.protocol_id,
        released_by="owner-corbin",
        released_at=NOW,
        frozen_validation_report=_validation_report(protocol),
    )

    assert release.created is True
    assert release.protocol_id == protocol.protocol_id
    assert release.protocol_admission_object_id == admitted.envelope.object_id
    assert release.validation_run_object_id == validation_run.envelope.object_id
    assert release.predecessor_sequence == 2
    assert release.envelope.kind == "economic-holdout-release"
    assert release.envelope.payload["analysis_only"] is True
    assert release.envelope.payload["can_submit_orders"] is False
    assert adapter.is_holdout_released(protocol.protocol_id) is True


def test_holdout_release_is_idempotent_only_for_the_same_frozen_report(tmp_path):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    adapter.admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    report = _validation_report(protocol)
    adapter.admit_evaluation_run(
        protocol.protocol_id,
        phase="validation",
        effective_at=NOW,
        frozen_validation_report=report,
    )
    first = adapter.release_holdout(
        protocol.protocol_id,
        released_by="owner-corbin",
        released_at=NOW,
        frozen_validation_report=report,
    )
    second = adapter.release_holdout(
        protocol.protocol_id,
        released_by="owner-corbin",
        released_at=NOW,
        frozen_validation_report=report,
    )

    assert first.created is True
    assert second.created is False
    assert second.envelope.object_id == first.envelope.object_id
    report["result_sha256"] = hashlib.sha256(b"different-results").hexdigest()
    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.release_holdout(
            protocol.protocol_id,
            released_by="owner-corbin",
            released_at=NOW,
            frozen_validation_report=report,
        )


def test_holdout_release_rejects_missing_protocol_and_report_not_bound_to_validation(
    tmp_path,
):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.release_holdout(
            protocol.protocol_id,
            released_by="owner-corbin",
            released_at=NOW,
            frozen_validation_report=_validation_report(protocol),
        )

    adapter.admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    report = _validation_report(protocol)
    report["validation_event_ids"] = []
    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.release_holdout(
            protocol.protocol_id,
            released_by="owner-corbin",
            released_at=NOW,
            frozen_validation_report=report,
        )


def test_holdout_release_rejects_a_report_without_an_immutable_validation_run(
    tmp_path,
):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    adapter.admit_protocol(
        protocol,
        source_revision="a" * 40,
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.release_holdout(
            protocol.protocol_id,
            released_by="owner-corbin",
            released_at=NOW,
            frozen_validation_report=_validation_report(protocol),
        )


@pytest.mark.parametrize(
    "source_revision,source_paths",
    [
        ("not-a-commit", ("evaluation.py",)),
        ("A" * 40, ("evaluation.py",)),
        ("a" * 40, ("../outside.py",)),
        ("a" * 40, ("missing.py",)),
        ("a" * 40, ()),
    ],
)
def test_admission_rejects_unpinned_or_uncontained_source_provenance(
    tmp_path, source_revision, source_paths
):
    with pytest.raises(EconomicEvaluationAdmissionError):
        _adapter(tmp_path).admit_protocol(
            _protocol(),
            source_revision=source_revision,
            effective_at=NOW,
            source_paths=source_paths,
        )
