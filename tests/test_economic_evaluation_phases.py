"""Three-phase economic lifecycle contracts."""

from __future__ import annotations

import pytest

from tests.test_economic_evaluation_admission import _protocol_from_receipts
from tests.test_economic_evaluation_protocol import protocol_source as protocol_source
from tradingagents.evals.economic_evaluation_partition_binding import (
    EconomicPartitionBindingError,
    bind_phase_eligibility,
    bind_validation_phase_eligibility,
    validate_phase_eligibility,
)


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
