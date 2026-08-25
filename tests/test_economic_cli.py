"""CLI contracts for the analysis-only economic protocol admission boundary."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_market_date_partitions,
    build_market_session_calendar,
)
from tradingagents.evals.economic_evaluation_protocol import (
    EvaluationSearchBudget,
    build_bitemporal_input_manifest,
    build_decision_event,
    build_frozen_evaluation_protocol,
    canonical_universe_id,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy

runner = CliRunner()
NOW = dt.datetime(2026, 1, 9, 21, 30, tzinfo=dt.UTC)


def _protocol():
    primary = tuple(f"T{index:03d}" for index in range(75))
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
        dataset_id="economic-cli-fixture",
        as_of_cutoff="2026-01-09T21:00:00+00:00",
        captured_at="2026-01-09T21:00:00+00:00",
        events=events,
    )
    return build_frozen_evaluation_protocol(
        input_manifest=manifest,
        primary_universe=primary,
        sensitivity_universe_50=primary[:50],
        sensitivity_universe_100=tuple(f"T{index:03d}" for index in range(100)),
        evaluation_policy=StrategyEvaluationPolicy(
            benchmark_symbol="SPY",
            holding_sessions=5,
            commission_bps_per_side="0",
            half_spread_bps_per_side="5",
            slippage_bps_per_side="5",
            round_trip_sides=2,
        ),
        search_budget=EvaluationSearchBudget(5, 3, 25),
        development_event_ids=(events[0].decision_event_id,),
        validation_event_ids=(events[1].decision_event_id,),
        holdout_event_ids=(events[2].decision_event_id,),
    )


def _market_dates() -> tuple[str, ...]:
    day = dt.date(2026, 1, 5)
    dates: list[str] = []
    while len(dates) < 60:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return tuple(dates)


def _partitioned_protocol(tmp_path: Path):
    primary = tuple(f"T{index:03d}" for index in range(75))
    market_dates = _market_dates()
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifact = archive.admit(
        raw_bytes=json.dumps([{"date": value} for value in market_dates]).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-12-31T21:00:00+00:00",
    )
    calendar = build_market_session_calendar(archive=archive, raw_artifact=artifact)
    events = tuple(
        build_decision_event(
            universe_id=canonical_universe_id(primary),
            symbol=primary[index % len(primary)],
            decision_at=f"{market_date}T20:55:00+00:00",
            market_date=market_date,
            horizon_sessions=5,
            horizon="5_sessions",
            benchmark="SPY",
            created_at=f"{market_date}T20:45:00+00:00",
            resolution_window={"start_at": f"{market_date}T20:55:00+00:00"},
            observation_start=f"{market_date}T19:00:00+00:00",
            observation_end=f"{market_date}T20:50:00+00:00",
            available_at=f"{market_date}T20:50:00+00:00",
            recorded_at=f"{market_date}T20:52:00+00:00",
            source_packet_id=f"packet-{market_date}-{index:03d}",
            source_artifact_id=f"artifact-{market_date}-{index:03d}",
            source_artifact_sha256=hashlib.sha256(
                f"{market_date}-{index:03d}".encode()
            ).hexdigest(),
        )
        for index, market_date in enumerate(market_dates)
    )
    partitions = build_market_date_partitions(
        market_calendar=calendar,
        events=events,
    )
    manifest = build_bitemporal_input_manifest(
        dataset_id="economic-cli-partitioned-fixture",
        as_of_cutoff="2026-12-31T21:00:00+00:00",
        captured_at="2026-12-31T21:00:00+00:00",
        events=events,
    )
    protocol = build_frozen_evaluation_protocol(
        input_manifest=manifest,
        primary_universe=primary,
        sensitivity_universe_50=primary[:50],
        sensitivity_universe_100=tuple(f"T{index:03d}" for index in range(100)),
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


def _tournament_input(protocol, partitions) -> dict[str, object]:
    events_by_id = {
        event.decision_event_id: event for event in protocol.input_manifest.events
    }
    event_ids = partitions.validation_eligible_event_ids
    return {
        "candidates_by_event": [
            {
                "decision_event_id": event_id,
                "candidates": [
                    {
                        "symbol": symbol,
                        "available_at": events_by_id[event_id].available_at,
                        "close_t_21": "110" if symbol == "T000" else None,
                        "close_t_252": "100" if symbol == "T000" else None,
                        "trailing_operating_income": "10" if symbol == "T000" else None,
                        "average_total_assets": "100" if symbol == "T000" else None,
                        "pullback_features": None,
                    }
                    for symbol in protocol.primary_universe
                ],
            }
            for event_id in event_ids
        ],
        "outcomes": [
            {
                "decision_event_id": event_id,
                "realized_returns": [
                    {"symbol": symbol, "return": "0.02" if symbol == "SPY" else "0.01"}
                    for symbol in sorted((*protocol.primary_universe, "SPY"))
                ],
            }
            for event_id in event_ids
        ],
    }


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


def _cohort_input() -> dict[str, object]:
    return {
        "market_date": "2026-01-09",
        "as_of_cutoff": "2026-01-09T21:00:00+00:00",
        "candidates": [
            {
                "security": {
                    "schema_version": "security_identity/v1",
                    "security_id": f"security-{index:03d}",
                    "symbol": f"C{index:03d}",
                    "cik": None,
                    "figi": None,
                    "exchange": "NYSE",
                    "security_type": "common_stock",
                    "effective_from": "2020-01-01",
                    "effective_to": None,
                    "status": "active",
                    "successor_security_id": None,
                    "terminal_proceeds_artifact_id": None,
                    "source_hashes": {
                        "security-master": hashlib.sha256(
                            f"security-{index:03d}".encode()
                        ).hexdigest(),
                    },
                    "analysis_only": True,
                    "execution_authority": "none",
                    "can_submit_orders": False,
                },
                "prior_complete_close": "5",
                "session_dollar_volumes": [str(index + 1)] * 60,
                "selection_artifact_id": f"selection-{index:03d}",
                "selection_artifact_sha256": hashlib.sha256(
                    f"selection-{index:03d}".encode()
                ).hexdigest(),
            }
            for index in range(100)
        ],
    }


def test_economic_cohort_build_writes_only_one_canonical_analysis_receipt(tmp_path: Path):
    input_path = tmp_path / "cohort-input.json"
    output_path = tmp_path / "cohort.json"
    input_path.write_text(json.dumps(_cohort_input()), encoding="utf-8")
    args = [
        "research",
        "economic-cohort-build",
        "--candidate-input-path",
        str(input_path),
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
    output_path = tmp_path / "cohort.json"
    input_path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "research",
            "economic-cohort-build",
            "--candidate-input-path",
            str(input_path),
            "--output-path",
            str(output_path),
        ],
    )

    assert result.exit_code == 2
    assert not output_path.exists()


def test_economic_cohort_build_rejects_different_existing_receipt_without_overwrite(
    tmp_path: Path,
):
    input_path = tmp_path / "cohort-input.json"
    output_path = tmp_path / "cohort.json"
    input_path.write_text(json.dumps(_cohort_input()), encoding="utf-8")
    args = [
        "research",
        "economic-cohort-build",
        "--candidate-input-path",
        str(input_path),
        "--output-path",
        str(output_path),
        "--json-output",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    original = output_path.read_bytes()

    changed = _cohort_input()
    candidates = changed["candidates"]
    assert isinstance(candidates, list)
    candidates[0]["prior_complete_close"] = "6"
    input_path.write_text(json.dumps(changed), encoding="utf-8")

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert output_path.read_bytes() == original


def test_economic_tournament_run_binds_only_purged_validation_results(tmp_path: Path):
    protocol, partitions = _partitioned_protocol(tmp_path)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "tournament-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    tournament_path.write_text(
        json.dumps(_tournament_input(protocol, partitions)),
        encoding="utf-8",
    )
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


def test_economic_tournament_run_rejects_malformed_local_input_before_evidence_write(
    tmp_path: Path,
):
    protocol, partitions = _partitioned_protocol(tmp_path)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "invalid-tournament-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    tournament_path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
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


def test_economic_tournament_run_rejects_malformed_candidate_availability_before_write(
    tmp_path: Path,
):
    protocol, partitions = _partitioned_protocol(tmp_path)
    protocol_path = tmp_path / "protocol.json"
    partitions_path = tmp_path / "partitions.json"
    tournament_path = tmp_path / "invalid-availability-tournament-input.json"
    protocol_path.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    partitions_path.write_text(json.dumps(partitions.to_dict()), encoding="utf-8")
    tournament_input = _tournament_input(protocol, partitions)
    candidate_rows = tournament_input["candidates_by_event"]
    assert isinstance(candidate_rows, list)
    candidate_rows[0]["candidates"][0]["available_at"] = "0000+00:00"
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


def test_economic_protocol_admit_is_idempotent_and_analysis_only(tmp_path: Path):
    protocol_path = tmp_path / "protocol.json"
    protocol = _protocol()
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


def test_economic_protocol_admit_rejects_unknown_revision_and_source_byte_drift(tmp_path: Path):
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(_protocol().to_dict()), encoding="utf-8")
    unknown_args = _admit_args(tmp_path, protocol_path)
    unknown_args[unknown_args.index("--source-revision") + 1] = "b" * 40

    unknown = runner.invoke(app, unknown_args)

    assert unknown.exit_code == 2
    assert not (tmp_path / "evidence").exists()

    drift_path = tmp_path / "drift"
    drift_path.mkdir()
    drift_protocol_path = drift_path / "protocol.json"
    drift_protocol_path.write_text(json.dumps(_protocol().to_dict()), encoding="utf-8")
    drift_args = _admit_args(drift_path, drift_protocol_path)
    (drift_path / "repo" / "evaluation.py").write_text(
        "VALUE = 'drifted'\n",
        encoding="utf-8",
    )

    drift = runner.invoke(app, drift_args)

    assert drift.exit_code == 2
    assert not (drift_path / "evidence").exists()
