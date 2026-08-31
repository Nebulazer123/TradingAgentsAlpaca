"""Contract tests for immutable admission of a frozen economic protocol."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import lzma
import subprocess

import pytest

from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_market_date_partitions,
    build_market_session_calendar,
)
from tradingagents.evals import economic_evaluation_admission as admission_module
from tradingagents.evals import economic_evaluation_result as result_module
from tradingagents.evals.economic_evaluation_admission import (
    EconomicEvaluationAdmissionAdapter,
    EconomicEvaluationAdmissionError,
)
from tradingagents.evals.economic_evaluation_partition_binding import (
    bind_validation_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import (
    EvaluationSearchBudget,
    build_frozen_evaluation_protocol,
)
from tradingagents.evals.economic_evaluation_result import (
    EconomicEvaluationResultError,
    LegacyEconomicValidationResult,
    build_validation_evaluation_result,
    validate_economic_validation_result,
)
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy
from tests.test_economic_evaluation_protocol import protocol_source as protocol_source
from tests.test_point_in_time_cohort import (
    _build_from_fixture,
    _source_cohort_fixture,
)

NOW = dt.datetime(2026, 1, 9, 21, 30, tzinfo=dt.UTC)
_PROTOCOL_SOURCE = None
_PROTOCOL_CACHE = None


@pytest.fixture(scope="module", autouse=True)
def _bind_protocol_source(protocol_source):
    global _PROTOCOL_CACHE, _PROTOCOL_SOURCE
    _PROTOCOL_SOURCE = protocol_source
    _PROTOCOL_CACHE = None


def _protocol():
    global _PROTOCOL_CACHE
    assert _PROTOCOL_SOURCE is not None
    if _PROTOCOL_CACHE is None:
        cohort, partitions, manifest = _PROTOCOL_SOURCE
        _PROTOCOL_CACHE = _protocol_from_receipts(cohort, partitions, manifest)
    return _PROTOCOL_CACHE


def _protocol_from_receipts(cohort, partitions, manifest):
    policy = StrategyEvaluationPolicy(
        benchmark_symbol="SPY",
        holding_sessions=5,
        commission_bps_per_side="0",
        half_spread_bps_per_side="5",
        slippage_bps_per_side="5",
        round_trip_sides=2,
    )
    return build_frozen_evaluation_protocol(
        cohort=cohort,
        market_date_partitions=partitions,
        input_manifest=manifest,
        primary_universe=cohort.primary_universe_75,
        sensitivity_universe_50=cohort.sensitivity_universe_50,
        sensitivity_universe_100=cohort.sensitivity_universe_100,
        evaluation_policy=policy,
        search_budget=EvaluationSearchBudget(5, 3, 25),
        development_event_ids=partitions.development_event_ids,
        validation_event_ids=partitions.validation_event_ids,
        holdout_event_ids=partitions.holdout_event_ids,
    )


def _partitioned_protocol(tmp_path):
    assert _PROTOCOL_SOURCE is not None
    return _protocol(), _PROTOCOL_SOURCE[1]


def _adapter(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "evaluation.py").write_text("VALUE = 'frozen'\n", encoding="utf-8")
    for command in (
        ("git", "init", "-q", str(repo_root)),
        ("git", "-C", str(repo_root), "config", "user.name", "Economic Test"),
        ("git", "-C", str(repo_root), "config", "user.email", "economic-test@example.invalid"),
        ("git", "-C", str(repo_root), "add", "evaluation.py"),
        ("git", "-C", str(repo_root), "commit", "-qm", "freeze evaluation source"),
    ):
        subprocess.run(command, check=True, capture_output=True)
    return EconomicEvaluationAdmissionAdapter(
        tmp_path / "evidence",
        repo_root=repo_root,
        clock=lambda: NOW,
    )


def _source_revision(tmp_path) -> str:
    result = subprocess.run(
        ("git", "-C", str(tmp_path / "repo"), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _chunks_for_compressed_receipt(compressed: bytes) -> list[str]:
    encoded = base64.b64encode(compressed).decode("ascii")
    return [
        encoded[offset : offset + admission_module._PROTOCOL_RECEIPT_CHUNK_CHARS]
        for offset in range(
            0,
            len(encoded),
            admission_module._PROTOCOL_RECEIPT_CHUNK_CHARS,
        )
    ]


def _receipt_for_raw_bytes(
    raw: bytes,
    *,
    check: int = lzma.CHECK_CRC64,
    filters=None,
) -> list[str]:
    return _chunks_for_compressed_receipt(
        lzma.compress(
            raw,
            format=lzma.FORMAT_XZ,
            check=check,
            filters=(
                admission_module._RECEIPT_LZMA_FILTERS
                if filters is None
                else filters
            ),
        )
    )


def _forged_envelope_payload(envelope, payload):
    forged = object.__new__(type(envelope))
    for field_name in type(envelope).__dataclass_fields__:
        object.__setattr__(forged, field_name, getattr(envelope, field_name))
    object.__setattr__(forged, "payload", payload)
    return forged


def test_receipt_writer_rejects_raw_oversize_before_compression(monkeypatch):
    monkeypatch.setattr(
        admission_module,
        "_canonical_json_bytes",
        lambda _value: b"x" * (admission_module._MAX_PROTOCOL_RECEIPT_BYTES + 1),
    )

    def unexpected_compression(*_args, **_kwargs):
        pytest.fail("oversized raw receipt reached compression")

    monkeypatch.setattr(admission_module.lzma, "compress", unexpected_compression)

    with pytest.raises(EconomicEvaluationAdmissionError, match="too large"):
        admission_module._receipt_chunks({"oversized": True})


def test_receipt_writer_rejects_compressed_output_outside_store_envelope(monkeypatch):
    monkeypatch.setattr(
        admission_module.lzma,
        "compress",
        lambda *_args, **_kwargs: b"x"
        * (admission_module._MAX_RECEIPT_COMPRESSED_BYTES + 1),
    )

    with pytest.raises(EconomicEvaluationAdmissionError, match="too large"):
        admission_module._receipt_chunks({"small": True})


def test_receipt_decoder_rejects_nonlist_count_size_and_rechunking():
    valid = admission_module._receipt_chunks({"canonical": True})
    encoded = "".join(valid)
    invalid_receipts = (
        tuple(valid),
        ["A" * admission_module._PROTOCOL_RECEIPT_CHUNK_CHARS]
        * (admission_module._MAX_RECEIPT_CHUNKS + 1),
        ["A" * admission_module._PROTOCOL_RECEIPT_CHUNK_CHARS]
        * admission_module._MAX_RECEIPT_CHUNKS,
        [encoded[:4], encoded[4:]],
    )

    for receipt in invalid_receipts:
        with pytest.raises(EconomicEvaluationAdmissionError):
            admission_module._receipt_value(receipt, label="test")


def test_receipt_decoder_rejects_noncanonical_base64_and_lzma_profile():
    noncanonical_base64 = "AB=="
    assert base64.b64decode(noncanonical_base64) == base64.b64decode("AA==")

    alternate_lzma = _receipt_for_raw_bytes(
        admission_module._canonical_json_bytes({"canonical": True}),
        check=lzma.CHECK_CRC32,
    )

    for receipt in ([noncanonical_base64], alternate_lzma):
        with pytest.raises(EconomicEvaluationAdmissionError):
            admission_module._receipt_value(receipt, label="test")


def test_receipt_decoder_rejects_high_dictionary_before_output_allocation():
    high_dictionary_filters = (
        {
            "id": lzma.FILTER_LZMA2,
            "dict_size": 64 * 1024 * 1024,
            "lc": 3,
            "lp": 0,
            "pb": 2,
            "mode": lzma.MODE_FAST,
            "nice_len": 32,
            "mf": lzma.MF_HC3,
            "depth": 4,
        },
    )
    receipt = _receipt_for_raw_bytes(b'{"canonical":true}', filters=high_dictionary_filters)

    with pytest.raises(EconomicEvaluationAdmissionError):
        admission_module._receipt_value(receipt, label="test")


def test_receipt_decoder_rejects_constants_and_excessive_json_depth():
    malformed_values = (
        b"NaN",
        b"[" * 1_100 + b"0" + b"]" * 1_100,
    )

    for raw in malformed_values:
        with pytest.raises(EconomicEvaluationAdmissionError):
            admission_module._receipt_value(
                _receipt_for_raw_bytes(raw),
                label="test",
            )


def test_receipt_decoder_rejects_truncation_trailing_concatenation_and_output_limit(
    monkeypatch,
):
    canonical = admission_module._receipt_chunks({"canonical": True})
    compressed = base64.b64decode("".join(canonical), validate=True)
    invalid_streams = (
        compressed[:-1],
        compressed + b"trailing",
        compressed + compressed,
    )
    for stream in invalid_streams:
        with pytest.raises(EconomicEvaluationAdmissionError):
            admission_module._receipt_value(
                _chunks_for_compressed_receipt(stream),
                label="test",
            )

    raw = admission_module._canonical_json_bytes("x" * 100)
    receipt = _receipt_for_raw_bytes(raw)
    monkeypatch.setattr(admission_module, "_MAX_PROTOCOL_RECEIPT_BYTES", len(raw) - 1)
    with pytest.raises(EconomicEvaluationAdmissionError):
        admission_module._receipt_value(receipt, label="test")


def test_persisted_protocol_and_validation_report_reads_reject_alternate_codec(tmp_path):
    adapter = _adapter(tmp_path)
    protocol, _partitions = _partitioned_protocol(tmp_path)
    admitted = adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    forged_protocol_payload = admission_module._thaw_json(admitted.envelope.payload)
    forged_protocol_payload["protocol"] = _receipt_for_raw_bytes(
        protocol.canonical_json_bytes(),
        check=lzma.CHECK_CRC32,
    )
    forged_protocol = _forged_envelope_payload(
        admitted.envelope,
        forged_protocol_payload,
    )
    _snapshot, events = adapter._store.verify_with_events()
    with pytest.raises(EconomicEvaluationAdmissionError):
        admission_module._admitted_protocol_from_envelope(
            forged_protocol,
            events=events,
        )

    forged_run_payload = {
        "schema_version": admission_module.ECONOMIC_EVALUATION_RUN_SCHEMA,
        "protocol_id": protocol.protocol_id,
        "protocol_admission_object_id": admitted.envelope.object_id,
        "phase": "validation",
        "frozen_validation_report": _receipt_for_raw_bytes(
            b'{"malformed":"alternate-codec"}',
            check=lzma.CHECK_CRC32,
        ),
        "validation_report_sha256": "0" * 64,
        "store_predecessor": {
            "sequence": 1,
            "object_id": admitted.envelope.object_id,
            "event_sha256": "0" * 64,
        },
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    forged_run = _forged_envelope_payload(admitted.envelope, forged_run_payload)
    object.__setattr__(
        forged_run,
        "kind",
        admission_module.ECONOMIC_EVALUATION_RUN_KIND,
    )
    with pytest.raises(EconomicEvaluationAdmissionError):
        admission_module._evaluation_run_from_envelope(
            forged_run,
            protocol=protocol,
            protocol_admission_object_id=admitted.envelope.object_id,
            events=events,
        )


def test_current_validation_report_mapping_cannot_bypass_receipt_codec():
    with pytest.raises(EconomicEvaluationAdmissionError):
        admission_module._validation_report_receipt_value(
            {
                "schema_version": admission_module.ECONOMIC_VALIDATION_REPORT_SCHEMA,
            },
            label="test validation report",
        )


def test_admission_binds_complete_protocol_source_bytes_and_store_predecessor(tmp_path):
    protocol = _protocol()
    admission = _adapter(tmp_path).admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    assert admission.created is True
    assert admission.protocol_id == protocol.protocol_id
    assert admission.input_manifest_sha256 == protocol.input_manifest_sha256
    assert admission.predecessor_sequence == 0
    assert admission.predecessor_event_sha256 == "0" * 64
    assert admission.envelope.kind == "economic-evaluation-protocol"
    assert admission.envelope.payload["source_revision"] == _source_revision(tmp_path)
    assert admission.envelope.payload["cohort_id"] == protocol.cohort_id
    assert admission.envelope.payload["cohort_sha256"] == protocol.cohort_sha256
    assert admission.envelope.payload["partition_id"] == protocol.partition_id
    assert admission.envelope.payload["partition_sha256"] == protocol.partition_sha256
    assert lzma.decompress(
        base64.b64decode(
            "".join(admission.envelope.payload["protocol"]), validate=True
        )
    ) == protocol.canonical_json_bytes()
    assert admission.envelope.payload["analysis_only"] is True
    assert admission.envelope.payload["can_submit_orders"] is False


def test_same_admitted_protocol_is_idempotent_but_not_reissued(tmp_path):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    first = adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    second = adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    assert first.created is True
    assert second.created is False
    assert second.envelope.object_id == first.envelope.object_id


def test_admission_rejects_same_manifest_rebound_to_a_different_cohort(tmp_path):
    assert _PROTOCOL_SOURCE is not None
    cohort, partitions, manifest = _PROTOCOL_SOURCE
    adapter = _adapter(tmp_path)
    adapter.admit_protocol(
        _protocol(),
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    symbol_overrides = {
        99 - position: symbol
        for position, symbol in enumerate(cohort.sensitivity_universe_100)
    }
    archive, calendar, payload = _source_cohort_fixture(
        tmp_path / "different-cohort",
        symbol_overrides=symbol_overrides,
        archive_recorded_at=dt.datetime(2026, 3, 31, 20, 32, tzinfo=dt.UTC),
    )
    different_cohort = _build_from_fixture(archive, calendar, payload)
    rebound = _protocol_from_receipts(different_cohort, partitions, manifest)
    assert rebound.protocol_id != _protocol().protocol_id
    assert rebound.primary_universe == _protocol().primary_universe

    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.admit_protocol(
            rebound,
            source_revision=_source_revision(tmp_path),
            effective_at=NOW,
            source_paths=("evaluation.py",),
        )


def test_admission_rejects_same_manifest_rebound_to_a_different_partition(tmp_path):
    assert _PROTOCOL_SOURCE is not None
    cohort, partitions, manifest = _PROTOCOL_SOURCE
    adapter = _adapter(tmp_path)
    adapter.admit_protocol(
        _protocol(),
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    archive = RawPointInTimeArtifactArchive(
        tmp_path / "different-partition-calendar",
        clock=lambda: dt.datetime(2026, 4, 1, 12, 0, tzinfo=dt.UTC),
    )
    artifact = archive.admit(
        raw_bytes=json.dumps(
            [
                {"close": "16:00", "date": day, "open": "09:30"}
                for day in partitions.market_calendar.market_dates
            ],
            indent=1,
        ).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-04-01T12:00:00+00:00",
    )
    different_calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=artifact,
    )
    different_partitions = build_market_date_partitions(
        market_calendar=different_calendar,
        cadence=partitions.cadence,
        registered_at=partitions.registered_at,
        primary_universe=partitions.primary_universe,
        decision_market_dates=partitions.decision_market_dates,
        events=partitions.events,
    )
    rebound = _protocol_from_receipts(cohort, different_partitions, manifest)
    assert rebound.protocol_id != _protocol().protocol_id
    assert rebound.input_manifest_id == _protocol().input_manifest_id

    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.admit_protocol(
            rebound,
            source_revision=_source_revision(tmp_path),
            effective_at=NOW,
            source_paths=("evaluation.py",),
        )


def test_admission_rejects_changed_provenance_for_an_existing_protocol(tmp_path):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
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
            source_revision=_source_revision(tmp_path),
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
            source_revision=_source_revision(tmp_path),
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
            source_revision=_source_revision(tmp_path),
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
            source_revision=_source_revision(tmp_path),
            effective_at=NOW,
            source_paths=("evaluation.py",),
        )


def _validation_report(protocol, partitions):
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    event_count = str(len(eligibility.event_ids))
    result = build_validation_evaluation_result(
        protocol,
        eligibility=eligibility,
        arm_metrics={
            arm_id: {
                "net_return_after_costs": "0",
                "benchmark_excess_after_costs": "0",
                "max_drawdown": "0",
                "turnover": "0",
                "false_positive_rate": "0",
                "decision_event_count": event_count,
                "packet_event_cluster_count": event_count,
                "market_event_cluster_count": event_count,
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
        "schema_version": "economic_validation_report/v2",
        "protocol_id": protocol.protocol_id,
        "market_date_partitions": partitions.to_dict(),
        "validation_event_ids": list(eligibility.event_ids),
        "result": result.to_dict(),
        "result_id": result.result_id,
        "result_sha256": result.result_sha256,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _legacy_validation_report(protocol):
    event_count = str(len(protocol.validation_event_ids))
    arm_metrics = result_module._legacy_canonical_arm_metrics(
        {
            arm_id: {
                "net_return_after_costs": "0",
                "benchmark_excess_after_costs": "0",
                "max_drawdown": "0",
                "turnover": "0.0",
                "false_positive_rate": "0",
                "decision_event_count": event_count,
                "packet_event_cluster_count": event_count,
                "market_event_cluster_count": event_count,
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
        validation_event_count=len(protocol.validation_event_ids),
    )
    result = result_module._build_legacy_result_from_components(
        protocol_id=protocol.protocol_id,
        validation_event_ids=protocol.validation_event_ids,
        arm_metrics=arm_metrics,
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


def _append_legacy_validation_run_and_holdout_release(adapter, protocol, report):
    snapshot, events = adapter._store.verify_with_events()
    protocol_envelope = next(
        item
        for item in snapshot
        if item.kind == "economic-evaluation-protocol"
        and item.payload["protocol_id"] == protocol.protocol_id
    )
    run_payload = {
        "schema_version": "economic_evaluation_run/v1",
        "protocol_id": protocol.protocol_id,
        "protocol_admission_object_id": protocol_envelope.object_id,
        "phase": "validation",
        "frozen_validation_report": report,
        "validation_report_sha256": admission_module._sha256(report),
        "store_predecessor": admission_module._current_predecessor(events),
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    run = adapter._store.admit_checked(
        EvidenceCandidate(
            kind="economic-evaluation-run",
            effective_at=NOW.isoformat(timespec="seconds"),
            payload=run_payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    ).envelope
    _snapshot, events = adapter._store.verify_with_events()
    release_payload = {
        "schema_version": "economic_holdout_release/v1",
        "protocol_id": protocol.protocol_id,
        "protocol_admission_object_id": protocol_envelope.object_id,
        "validation_run_object_id": run.object_id,
        "released_by": "owner-corbin",
        "released_at": NOW.isoformat(timespec="seconds"),
        "frozen_validation_report": report,
        "validation_report_sha256": admission_module._sha256(report),
        "store_predecessor": admission_module._current_predecessor(events),
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    release = adapter._store.admit_checked(
        EvidenceCandidate(
            kind="economic-holdout-release",
            effective_at=NOW.isoformat(timespec="seconds"),
            payload=release_payload,
        ),
        validate=lambda _snapshot, _envelope: None,
    ).envelope
    return protocol_envelope, run, release


def test_validation_result_is_complete_canonical_and_alias_resistant(tmp_path):
    protocol, partitions = _partitioned_protocol(tmp_path)
    result = _validation_report(protocol, partitions)["result"]
    parsed = validate_economic_validation_result(json.loads(json.dumps(result)))

    assert parsed.protocol_id == protocol.protocol_id
    assert parsed.validation_event_ids == partitions.validation_eligible_event_ids
    assert parsed.validation_partition_id == partitions.partition_id
    assert parsed.validation_partition_sha256 == partitions.partition_sha256
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
    tampered["arm_metrics"][0]["metrics"]["decision_event_count"] = "1"
    with pytest.raises(EconomicEvaluationResultError):
        validate_economic_validation_result(tampered)
    tampered = json.loads(parsed.canonical_json_bytes())
    tampered["arm_metrics"][0]["metrics"]["turnover"] = "0.0"
    with pytest.raises(EconomicEvaluationResultError):
        validate_economic_validation_result(tampered)


def test_legacy_result_and_report_remain_readable_but_are_nonqualifying(tmp_path):
    protocol = _protocol()
    report = _legacy_validation_report(protocol)
    parsed = validate_economic_validation_result(report["result"])

    assert type(parsed) is LegacyEconomicValidationResult
    assert parsed.canonical_json_bytes() == json.dumps(
        report["result"],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert admission_module._frozen_validation_report(
        report,
        protocol=protocol,
        allow_legacy=True,
    ) == report

    adapter = _adapter(tmp_path)
    adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.admit_evaluation_run(
            protocol.protocol_id,
            phase="validation",
            effective_at=NOW,
            frozen_validation_report=report,
        )


def test_persisted_legacy_release_remains_readable_but_cannot_unlock_holdout(tmp_path):
    adapter = _adapter(tmp_path)
    protocol = _protocol()
    report = _legacy_validation_report(protocol)
    adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    protocol_envelope, run, _release = _append_legacy_validation_run_and_holdout_release(
        adapter,
        protocol,
        report,
    )
    _snapshot, events = adapter._store.verify_with_events()
    parsed_run = admission_module._evaluation_run_from_envelope(
        run,
        protocol=protocol,
        protocol_admission_object_id=protocol_envelope.object_id,
        events=events,
    )

    assert parsed_run.protocol_id == protocol.protocol_id
    assert adapter.is_holdout_released(protocol.protocol_id) is False


def test_holdout_release_requires_admitted_protocol_and_freezes_validation_report(
    tmp_path,
):
    adapter = _adapter(tmp_path)
    protocol, partitions = _partitioned_protocol(tmp_path)
    admitted = adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    validation_run = adapter.admit_evaluation_run(
        protocol.protocol_id,
        phase="validation",
        effective_at=NOW,
        frozen_validation_report=_validation_report(protocol, partitions),
    )

    release = adapter.release_holdout(
        protocol.protocol_id,
        released_by="owner-corbin",
        released_at=NOW,
        frozen_validation_report=_validation_report(protocol, partitions),
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
    protocol, partitions = _partitioned_protocol(tmp_path)
    adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    report = _validation_report(protocol, partitions)
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
    protocol, partitions = _partitioned_protocol(tmp_path)
    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.release_holdout(
            protocol.protocol_id,
            released_by="owner-corbin",
            released_at=NOW,
            frozen_validation_report=_validation_report(protocol, partitions),
        )

    adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    report = _validation_report(protocol, partitions)
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
    protocol, partitions = _partitioned_protocol(tmp_path)
    adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )

    with pytest.raises(EconomicEvaluationAdmissionError):
        adapter.release_holdout(
            protocol.protocol_id,
            released_by="owner-corbin",
            released_at=NOW,
            frozen_validation_report=_validation_report(protocol, partitions),
        )


def test_readiness_status_and_validation_report_are_read_only_and_protocol_bound(tmp_path):
    adapter = _adapter(tmp_path)
    protocol, partitions = _partitioned_protocol(tmp_path)

    absent = adapter.readiness_status(protocol.protocol_id)
    assert absent.state == "protocol_not_admitted"
    assert absent.protocol_admission_object_id is None
    assert absent.validation_run_object_id is None
    assert absent.holdout_release_object_id is None

    protocol_admission = adapter.admit_protocol(
        protocol,
        source_revision=_source_revision(tmp_path),
        effective_at=NOW,
        source_paths=("evaluation.py",),
    )
    admitted = adapter.readiness_status(protocol.protocol_id)
    assert admitted.state == "validation_not_admitted"
    assert admitted.protocol_admission_object_id == protocol_admission.envelope.object_id

    report = _validation_report(protocol, partitions)
    run = adapter.admit_evaluation_run(
        protocol.protocol_id,
        phase="validation",
        effective_at=NOW,
        frozen_validation_report=report,
    )
    sealed = adapter.readiness_status(protocol.protocol_id)
    assert sealed.state == "holdout_sealed"
    assert sealed.validation_run_object_id == run.envelope.object_id
    assert adapter.frozen_validation_report(protocol.protocol_id) == report

    release = adapter.release_holdout(
        protocol.protocol_id,
        released_by="owner-corbin",
        released_at=NOW,
        frozen_validation_report=adapter.frozen_validation_report(protocol.protocol_id),
    )
    released = adapter.readiness_status(protocol.protocol_id)
    assert released.state == "holdout_released_analysis_only"
    assert released.holdout_release_object_id == release.envelope.object_id


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
