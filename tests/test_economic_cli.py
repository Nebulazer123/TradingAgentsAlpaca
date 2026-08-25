"""CLI contracts for the analysis-only economic protocol admission boundary."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
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
