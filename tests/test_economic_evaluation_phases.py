"""Three-phase economic lifecycle contracts."""

from __future__ import annotations

import pytest

import tradingagents.evals.economic_evaluation_admission as admission_module
from tests.fixtures.economic_tournament import build_tournament_receipt
from tests.test_economic_evaluation_admission import _protocol_from_receipts
from tests.test_economic_evaluation_protocol import protocol_source as protocol_source
from tradingagents.evals.economic_evaluation_partition_binding import (
    EconomicPartitionBindingError,
    bind_phase_eligibility,
    bind_validation_phase_eligibility,
    validate_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import CONTROL_ARM_IDS
from tradingagents.evals.economic_evaluation_result import (
    build_phase_evaluation_result,
    validate_economic_phase_result,
)
from tradingagents.evals.economic_tournament import evaluate_phase_ta_control


def test_phase_eligibility_binds_each_frozen_partition_and_keeps_validation_compatibility(
    protocol_source,
):
    cohort, partitions, manifest = protocol_source
    protocol = _protocol_from_receipts(cohort, partitions, manifest)

    development = bind_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
        phase="development",
    )
    validation = bind_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
        phase="validation",
    )
    holdout = bind_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
        phase="holdout",
    )

    assert development.event_ids == partitions.development_eligible_event_ids
    assert validation.event_ids == partitions.validation_eligible_event_ids
    assert holdout.event_ids == partitions.holdout_eligible_event_ids
    assert validate_phase_eligibility(protocol=protocol, eligibility=holdout) == holdout
    assert bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    ).event_ids == validation.event_ids

    with pytest.raises(EconomicPartitionBindingError, match="phase"):
        bind_phase_eligibility(protocol=protocol, partitions=partitions, phase="paper")


def test_phase_result_uses_a_new_phase_bound_schema(protocol_source):
    cohort, partitions, manifest = protocol_source
    protocol = _protocol_from_receipts(cohort, partitions, manifest)
    eligibility = bind_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
        phase="development",
    )
    event_count = str(len(eligibility.event_ids))
    metrics = {
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
        for arm_id in CONTROL_ARM_IDS
    }
    result = build_phase_evaluation_result(
        protocol,
        eligibility=eligibility,
        arm_metrics=metrics,
    )
    assert result.to_dict()["schema_version"] == "economic_evaluation_result/v4"
    assert result.to_dict()["phase"] == "development"
    assert result.validation_event_ids == eligibility.event_ids
    assert validate_economic_phase_result(result.to_dict()).canonical_json_bytes() == result.canonical_json_bytes()


def test_development_evaluator_uses_the_bound_development_events(tmp_path, protocol_source):
    cohort, partitions, manifest = protocol_source
    protocol = _protocol_from_receipts(cohort, partitions, manifest)
    eligibility = bind_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
        phase="development",
    )
    receipt, _archive = build_tournament_receipt(
        tmp_path / "development-pit",
        protocol=protocol,
        eligibility=eligibility,
    )

    result = evaluate_phase_ta_control(
        protocol=protocol,
        eligibility=eligibility,
        candidates_by_event=dict(receipt.candidates_by_event),
        execution_outcomes=receipt.outcomes,
        tournament_input_id=receipt.input_id,
        tournament_input_sha256=receipt.input_sha256,
    )

    assert result.to_dict()["schema_version"] == "economic_evaluation_result/v4"
    assert result.to_dict()["phase"] == "development"
    assert result.validation_event_ids == eligibility.event_ids
    assert validate_economic_phase_result(result.to_dict()).canonical_json_bytes() == result.canonical_json_bytes()


def test_phase_report_rejects_cross_phase_result_substitution(protocol_source):
    cohort, partitions, manifest = protocol_source
    protocol = _protocol_from_receipts(cohort, partitions, manifest)
    eligibility = bind_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
        phase="development",
    )
    event_count = str(len(eligibility.event_ids))
    result = build_phase_evaluation_result(
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
            for arm_id in CONTROL_ARM_IDS
        },
    )
    report = {
        "schema_version": admission_module.ECONOMIC_PHASE_REPORT_SCHEMA,
        "protocol_id": protocol.protocol_id,
        "phase": "development",
        "market_date_partitions": partitions.to_dict(),
        "event_ids": list(eligibility.event_ids),
        "result": result.to_dict(),
        "result_id": result.result_id,
        "result_sha256": result.result_sha256,
        "tournament_input": {
            "input_id": "economic-tournament-input-" + "0" * 64,
            "input_sha256": "0" * 64,
        },
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }

    assert admission_module._frozen_phase_report(report, protocol=protocol) == report
    report["phase"] = "holdout"
    with pytest.raises(admission_module.EconomicEvaluationAdmissionError, match="event IDs"):
        admission_module._frozen_phase_report(report, protocol=protocol)
