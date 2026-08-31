"""Source-bound input contracts for qualifying TA-Control evaluation."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.economic_tournament import build_tournament_receipt
from tests.test_economic_evaluation_protocol import protocol_source as protocol_source
from tradingagents.evals.economic_evaluation_partition_binding import (
    bind_validation_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import (
    EvaluationSearchBudget,
    build_frozen_evaluation_protocol,
)
from tradingagents.evals.economic_tournament_evidence import (
    EconomicTournamentInputEvidenceError,
    validate_source_bound_tournament_input,
)
from tradingagents.evals.economic_tournament_evidence_admission import (
    EconomicTournamentReceiptArchive,
    verify_source_bound_tournament_input,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy


def _protocol(protocol_source):
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
    return protocol, bind_validation_phase_eligibility(protocol=protocol, partitions=partitions)


def _receipt(tmp_path: Path, protocol_source):
    protocol, eligibility = _protocol(protocol_source)
    receipt, archive = build_tournament_receipt(
        tmp_path / "pit",
        protocol=protocol,
        eligibility=eligibility,
    )
    return protocol, eligibility, receipt, archive


def test_features_freeze_once_per_market_date_and_outcomes_only_reference_them(
    tmp_path: Path, protocol_source
):
    protocol, eligibility, receipt, _archive = _receipt(tmp_path, protocol_source)

    rebuilt = validate_source_bound_tournament_input(
        receipt.to_dict(),
        protocol=protocol,
        eligibility=eligibility,
    )

    assert rebuilt.canonical_json_bytes() == receipt.canonical_json_bytes()
    assert len(rebuilt.features.date_evidence) == len(rebuilt.outcome_receipt.date_evidence)
    assert len(rebuilt.features.date_evidence[0]["candidates"]) == 75
    assert "candidates" not in rebuilt.outcome_receipt.date_evidence[0]
    assert rebuilt.outcome_receipt.feature_id == rebuilt.features.feature_id
    event_ids = tuple(rebuilt.candidates_by_event)
    assert rebuilt.candidates_by_event[event_ids[0]] is rebuilt.candidates_by_event[event_ids[1]]


def test_raw_replay_and_complete_receipt_archive_are_idempotent_and_owner_only(
    tmp_path: Path, protocol_source
):
    protocol, eligibility, receipt, pit_archive = _receipt(tmp_path, protocol_source)
    archive = EconomicTournamentReceiptArchive(tmp_path / "evidence" / "_tournament_receipts")

    archive.admit(receipt, pit_artifact_root=pit_archive.root)
    archive.admit(receipt, pit_artifact_root=pit_archive.root)
    reopened = archive.reopen(
        input_id=receipt.input_id,
        input_sha256=receipt.input_sha256,
        protocol=protocol,
        eligibility=eligibility,
    )

    assert reopened.canonical_json_bytes() == receipt.canonical_json_bytes()
    for directory in (
        archive.root,
        archive.root / "features",
        archive.root / "outcomes",
        archive.root / "custody",
        archive.root / ".staging",
    ):
        assert directory.stat().st_mode & 0o777 == 0o700
    for path in archive.root.rglob("*.json"):
        assert path.stat().st_mode & 0o777 == 0o600


def test_raw_value_tampering_is_nonqualifying(tmp_path: Path, protocol_source):
    protocol, eligibility, receipt, pit_archive = _receipt(tmp_path, protocol_source)
    first = receipt.features.to_dict()["market_dates"][0]["candidates"][0]
    artifact_id = first["candidate_observation"]["raw_artifact_id"]
    raw_path = pit_archive._objects_root / f"{artifact_id}.raw"
    raw_path.write_bytes(b'{"value":{"symbol":"TAMPERED"}}')

    with pytest.raises(EconomicTournamentInputEvidenceError, match="raw artifact"):
        verify_source_bound_tournament_input(
            archive=pit_archive,
            value=receipt.to_dict(),
            protocol=protocol,
            eligibility=eligibility,
        )


def test_pure_receipt_module_has_no_custody_or_execution_imports():
    source_path = Path(__file__).parents[1] / "tradingagents/evals/economic_tournament_evidence.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    prohibited = {
        "tradingagents.dataflows.pit.raw_artifacts",
        "tradingagents.strategy._immutable_evidence_store",
        "tradingagents.brokers",
        "tradingagents.orchestration",
    }
    assert imported.isdisjoint(prohibited)
    completed = subprocess.run(
        [
            "/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python",
            "-I",
            "-c",
            (
                f"import sys; sys.path.insert(0, {str(Path(__file__).parents[1])!r}); "
                "import tradingagents.evals.economic_tournament_evidence as evidence; "
                "assert not hasattr(evidence, 'RawPointInTimeArtifactArchive')"
            ),
        ],
        cwd=Path(__file__).parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
