"""CLI contracts for the analysis-only economic protocol admission boundary."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

import cli.main as main
from cli.main import app
from tests.fixtures.economic_tournament import build_tournament_receipt
from tests.test_economic_evaluation_protocol import protocol_source as protocol_source
from tests.test_point_in_time_cohort import _source_cohort_fixture
from tradingagents.evals.economic_evaluation_partition_binding import (
    bind_validation_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import (
    EvaluationSearchBudget,
    build_frozen_evaluation_protocol,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy

runner = CliRunner()
NOW = dt.datetime(2026, 1, 9, 21, 30, tzinfo=dt.UTC)


def _partitioned_protocol(protocol_source):
    cohort, partitions, manifest = protocol_source
    protocol = build_frozen_evaluation_protocol(
        cohort=cohort,
        market_date_partitions=partitions,
        input_manifest=manifest,
        primary_universe=cohort.primary_universe_75,
        sensitivity_universe_50=cohort.sensitivity_universe_50,
        sensitivity_universe_100=cohort.sensitivity_universe_100,
        evaluation_policy=StrategyEvaluationPolicy(
            benchmark_symbol="SPY",
            holding_sessions=5,
            commission_bps_per_side="0",
            half_spread_bps_per_side="5",
            slippage_bps_per_side="5",
            round_trip_sides=2,
        ),
        search_budget=EvaluationSearchBudget(5, 3, 25),
        development_event_ids=partitions.development_event_ids,
        validation_event_ids=partitions.validation_event_ids,
        holdout_event_ids=partitions.holdout_event_ids,
    )
    return protocol, partitions


def _admit_args(tmp_path: Path, protocol_path: Path):
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
    revision = subprocess.run(
        ("git", "-C", str(repo_root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return [
        "research",
        "economic-protocol-admit",
        "--protocol-path",
        str(protocol_path),
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--repo-root",
        str(repo_root),
        "--source-revision",
        revision,
        "--source-path",
        "evaluation.py",
        "--effective-at",
        NOW.isoformat(timespec="seconds"),
        "--json-output",
    ]


def _cohort_input(tmp_path: Path):
    return _source_cohort_fixture(tmp_path / "cohort-pit")


def test_economic_cohort_build_writes_only_one_canonical_analysis_receipt(tmp_path: Path):
    archive, calendar, cohort_input = _cohort_input(tmp_path)
    input_path = tmp_path / "cohort-input.json"
    calendar_path = tmp_path / "market-calendar.json"
    output_path = tmp_path / "cohort.json"
    input_path.write_text(json.dumps(cohort_input), encoding="utf-8")
    calendar_path.write_bytes(calendar.canonical_json_bytes())
    args = [
        "research",
        "economic-cohort-build",
        "--candidate-input-path",
        str(input_path),
        "--pit-artifact-root",
        str(archive.root),
        "--market-calendar-path",
        str(calendar_path),
        "--output-path",
        str(output_path),
        "--json-output",
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    payload = json.loads(first.output)
    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["can_submit_orders"] is False
    assert receipt["cohort_id"] == payload["cohort_id"]
    assert receipt["analysis_only"] is True


def test_economic_cohort_build_rejects_invalid_input_without_writing_receipt(tmp_path: Path):
    input_path = tmp_path / "invalid-cohort-input.json"
    calendar_path = tmp_path / "market-calendar.json"
    artifact_root = tmp_path / "cohort-pit"
    output_path = tmp_path / "cohort.json"
    input_path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
    calendar_path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
    artifact_root.mkdir()

    result = runner.invoke(
        app,
        [
            "research",
            "economic-cohort-build",
            "--candidate-input-path",
            str(input_path),
            "--pit-artifact-root",
            str(artifact_root),
            "--market-calendar-path",
            str(calendar_path),
            "--output-path",
            str(output_path),
        ],
    )

    assert result.exit_code == 2
    assert not output_path.exists()


def test_economic_cohort_build_rejects_different_existing_receipt_without_overwrite(
    tmp_path: Path,
):
    archive, calendar, cohort_input = _cohort_input(tmp_path)
    input_path = tmp_path / "cohort-input.json"
    calendar_path = tmp_path / "market-calendar.json"
    output_path = tmp_path / "cohort.json"
    input_path.write_text(json.dumps(cohort_input), encoding="utf-8")
    calendar_path.write_bytes(calendar.canonical_json_bytes())
    args = [
        "research",
        "economic-cohort-build",
        "--candidate-input-path",
        str(input_path),
        "--pit-artifact-root",
        str(archive.root),
        "--market-calendar-path",
        str(calendar_path),
        "--output-path",
        str(output_path),
        "--json-output",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    original = output_path.read_bytes()

    changed = dict(cohort_input)
    changed["selection_time"] = "2026-04-01T11:56:00+00:00"
    input_path.write_text(json.dumps(changed), encoding="utf-8")

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert output_path.read_bytes() == original


def test_economic_cohort_build_rejects_ambiguous_nonfinite_and_oversized_input(
    tmp_path: Path,
):
    archive, calendar, _cohort_input_payload = _cohort_input(tmp_path)
    input_path = tmp_path / "cohort-input.json"
    calendar_path = tmp_path / "market-calendar.json"
    output_path = tmp_path / "cohort.json"
    calendar_path.write_bytes(calendar.canonical_json_bytes())
    args = [
        "research",
        "economic-cohort-build",
        "--candidate-input-path",
        str(input_path),
        "--pit-artifact-root",
        str(archive.root),
        "--market-calendar-path",
        str(calendar_path),
        "--output-path",
        str(output_path),
    ]

    for raw_bytes in (
        b'{"market_date":"2026-04-01","market_date":"2026-04-02"}',
        b'{"unexpected":NaN}',
        b'{"unexpected":' + (b"9" * 129) + b'}',
        b'{"padding":"' + (b"x" * 4_000_001) + b'"}',
    ):
        input_path.write_bytes(raw_bytes)
        result = runner.invoke(app, args)
        assert result.exit_code == 2
        assert not output_path.exists()


def test_economic_tournament_run_binds_only_purged_validation_results(
    tmp_path: Path, protocol_source
):
    protocol, partitions = _partitioned_protocol(protocol_source)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "tournament-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    source_input, archive = build_tournament_receipt(
        tmp_path / "tournament-pit",
        protocol=protocol,
        eligibility=eligibility,
    )
    tournament_path.write_bytes(source_input.canonical_json_bytes())
    admission_args = _admit_args(tmp_path, protocol_path)
    admitted = runner.invoke(app, admission_args)
    assert admitted.exit_code == 0, admitted.output
    args = [
        "research",
        "economic-tournament-run",
        "--protocol-path",
        str(protocol_path),
        "--partitions-path",
        str(partitions_path),
        "--tournament-input-path",
        str(tournament_path),
        "--pit-artifact-root",
        str(archive.root),
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--repo-root",
        str(tmp_path / "repo"),
        "--effective-at",
        NOW.isoformat(timespec="seconds"),
        "--json-output",
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_payload = json.loads(first.output)
    second_payload = json.loads(second.output)
    assert first_payload["analysis_only"] is True
    assert first_payload["execution_authority"] == "none"
    assert first_payload["can_submit_orders"] is False
    assert first_payload["protocol_id"] == protocol.protocol_id
    assert first_payload["created"] is True
    assert second_payload["created"] is False
    assert second_payload["evaluation_run_object_id"] == first_payload["evaluation_run_object_id"]

    status_args = [
        "research",
        "economic-readiness-status",
        "--protocol-id",
        protocol.protocol_id,
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--repo-root",
        str(tmp_path / "repo"),
        "--json-output",
    ]
    sealed = runner.invoke(app, status_args)
    assert sealed.exit_code == 0, sealed.output
    assert json.loads(sealed.output)["state"] == "holdout_sealed"

    release_args = [
        "research",
        "economic-holdout-release",
        "--protocol-id",
        protocol.protocol_id,
        "--released-by",
        "owner-corbin",
        "--released-at",
        NOW.isoformat(timespec="seconds"),
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--repo-root",
        str(tmp_path / "repo"),
        "--json-output",
    ]
    released = runner.invoke(app, release_args)
    repeated = runner.invoke(app, release_args)
    assert released.exit_code == 0, released.output
    assert repeated.exit_code == 0, repeated.output
    release_payload = json.loads(released.output)
    repeated_payload = json.loads(repeated.output)
    assert release_payload["analysis_only"] is True
    assert release_payload["execution_authority"] == "none"
    assert release_payload["can_submit_orders"] is False
    assert release_payload["created"] is True
    assert repeated_payload["created"] is False
    assert (
        repeated_payload["holdout_release_object_id"]
        == release_payload["holdout_release_object_id"]
    )

    final_status = runner.invoke(app, status_args)
    assert final_status.exit_code == 0, final_status.output
    final_payload = json.loads(final_status.output)
    assert final_payload["state"] == "holdout_released_analysis_only"
    assert final_payload["holdout_release_object_id"] == release_payload["holdout_release_object_id"]


def test_economic_tournament_run_admits_unavailable_as_completed_nonqualifying(
    tmp_path: Path, protocol_source
):
    protocol, partitions = _partitioned_protocol(protocol_source)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "unavailable-tournament-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    market_date = next(
        event.market_date
        for event in protocol.input_manifest.events
        if event.decision_event_id in set(eligibility.event_ids)
    )
    source_input, archive = build_tournament_receipt(
        tmp_path / "unavailable-tournament-pit",
        protocol=protocol,
        eligibility=eligibility,
        unavailable_next_open=frozenset({(market_date, "T001")}),
    )
    tournament_path.write_bytes(source_input.canonical_json_bytes())
    admitted = runner.invoke(app, _admit_args(tmp_path, protocol_path))
    assert admitted.exit_code == 0, admitted.output
    args = [
        "research",
        "economic-tournament-run",
        "--protocol-path",
        str(protocol_path),
        "--partitions-path",
        str(partitions_path),
        "--tournament-input-path",
        str(tournament_path),
        "--pit-artifact-root",
        str(archive.root),
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--repo-root",
        str(tmp_path / "repo"),
        "--effective-at",
        NOW.isoformat(timespec="seconds"),
        "--json-output",
    ]

    completed = runner.invoke(app, args)

    assert completed.exit_code == 0, completed.output
    payload = json.loads(completed.output)
    assert payload["availability_status"] == "unavailable"
    assert payload["qualification_status"] == (
        "nonqualifying_unavailable_execution_evidence"
    )
    assert payload["evaluation_run_object_id"]
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["can_submit_orders"] is False
    status = runner.invoke(
        app,
        [
            "research",
            "economic-readiness-status",
            "--protocol-id",
            protocol.protocol_id,
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--repo-root",
            str(tmp_path / "repo"),
            "--json-output",
        ],
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["state"] == "validation_not_admitted"
    release = runner.invoke(
        app,
        [
            "research",
            "economic-holdout-release",
            "--protocol-id",
            protocol.protocol_id,
            "--released-by",
            "owner-corbin",
            "--released-at",
            NOW.isoformat(timespec="seconds"),
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--repo-root",
            str(tmp_path / "repo"),
            "--json-output",
        ],
    )
    assert release.exit_code == 2


def test_economic_tournament_run_rejects_malformed_local_input_before_evidence_write(
    tmp_path: Path, protocol_source
):
    protocol, partitions = _partitioned_protocol(protocol_source)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "invalid-tournament-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    tournament_path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
    pit_root = tmp_path / "tournament-pit"
    pit_root.mkdir()
    evidence_root = tmp_path / "evidence"

    result = runner.invoke(
        app,
        [
            "research",
            "economic-tournament-run",
            "--protocol-path",
            str(protocol_path),
            "--partitions-path",
            str(partitions_path),
            "--tournament-input-path",
            str(tournament_path),
            "--pit-artifact-root",
            str(pit_root),
            "--evidence-root",
            str(evidence_root),
            "--repo-root",
            str(tmp_path),
            "--effective-at",
            NOW.isoformat(timespec="seconds"),
        ],
    )

    assert result.exit_code == 2
    assert not evidence_root.exists()


def test_holdout_tournament_is_denied_before_its_input_is_read(
    tmp_path: Path, protocol_source, monkeypatch
):
    protocol, partitions = _partitioned_protocol(protocol_source)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "sealed-holdout-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    tournament_path.write_text('{"must_not_be_read":true}', encoding="utf-8")
    original_reader = main._economic_json_object
    reads: list[Path] = []

    def spy_reader(path: Path, **kwargs):
        if path == tournament_path:
            reads.append(path)
            raise AssertionError("sealed holdout input was read")
        return original_reader(path, **kwargs)

    monkeypatch.setattr(main, "_economic_json_object", spy_reader)
    result = runner.invoke(
        app,
        [
            "research",
            "economic-tournament-run",
            "--protocol-path",
            str(protocol_path),
            "--partitions-path",
            str(partitions_path),
            "--tournament-input-path",
            str(tournament_path),
            "--pit-artifact-root",
            str(tmp_path),
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--repo-root",
            str(tmp_path),
            "--effective-at",
            NOW.isoformat(timespec="seconds"),
            "--phase",
            "holdout",
        ],
    )

    assert result.exit_code == 2
    assert reads == []


def test_economic_tournament_run_rejects_malformed_candidate_availability_before_write(
    tmp_path: Path, protocol_source
):
    protocol, partitions = _partitioned_protocol(protocol_source)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "invalid-availability-tournament-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    receipt, archive = build_tournament_receipt(
        tmp_path / "tournament-pit",
        protocol=protocol,
        eligibility=eligibility,
    )
    tournament_input = receipt.to_dict()
    tournament_input["features"]["market_dates"][0]["candidates"][0]["candidate"][
        "available_at"
    ] = "0000+00:00"
    tournament_path.write_text(json.dumps(tournament_input), encoding="utf-8")
    evidence_root = tmp_path / "evidence"

    result = runner.invoke(
        app,
        [
            "research",
            "economic-tournament-run",
            "--protocol-path",
            str(protocol_path),
            "--partitions-path",
            str(partitions_path),
            "--tournament-input-path",
            str(tournament_path),
            "--pit-artifact-root",
            str(archive.root),
            "--evidence-root",
            str(evidence_root),
            "--repo-root",
            str(tmp_path),
            "--effective-at",
            NOW.isoformat(timespec="seconds"),
        ],
    )

    assert result.exit_code == 2
    assert not evidence_root.exists()


def test_economic_protocol_admit_is_idempotent_and_analysis_only(
    tmp_path: Path, protocol_source
):
    protocol_path = tmp_path / "protocol.json"
    protocol, _partitions = _partitioned_protocol(protocol_source)
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    args = _admit_args(tmp_path, protocol_path)

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_payload = json.loads(first.output)
    second_payload = json.loads(second.output)
    assert first_payload["analysis_only"] is True
    assert first_payload["execution_authority"] == "none"
    assert first_payload["can_submit_orders"] is False
    assert first_payload["protocol_id"] == protocol.protocol_id
    assert first_payload["created"] is True
    assert second_payload["created"] is False
    assert second_payload["admission_object_id"] == first_payload["admission_object_id"]


def test_economic_protocol_admit_rejects_invalid_input_before_creating_evidence(tmp_path: Path):
    protocol_path = tmp_path / "invalid.json"
    protocol_path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
    args = _admit_args(tmp_path, protocol_path)

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "economic protocol admission rejected" in result.output
    assert not (tmp_path / "evidence").exists()


def test_economic_protocol_admit_rejects_unknown_revision_and_source_byte_drift(
    tmp_path: Path, protocol_source
):
    protocol, _partitions = _partitioned_protocol(protocol_source)
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    unknown_args = _admit_args(tmp_path, protocol_path)
    unknown_args[unknown_args.index("--source-revision") + 1] = "b" * 40

    unknown = runner.invoke(app, unknown_args)

    assert unknown.exit_code == 2
    assert not (tmp_path / "evidence").exists()

    drift_path = tmp_path / "drift"
    drift_path.mkdir()
    drift_protocol_path = drift_path / "protocol.json"
    drift_protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    drift_args = _admit_args(drift_path, drift_protocol_path)
    (drift_path / "repo" / "evaluation.py").write_text(
        "VALUE = 'drifted'\n",
        encoding="utf-8",
    )

    drift = runner.invoke(app, drift_args)

    assert drift.exit_code == 2
    assert not (drift_path / "evidence").exists()
