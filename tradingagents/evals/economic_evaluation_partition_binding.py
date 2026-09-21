"""Bind a frozen protocol to source-backed, purged economic phase eligibility."""

from __future__ import annotations

from dataclasses import dataclass

from tradingagents.dataflows.pit.partitions import (
    MarketDatePartitions,
    validate_market_date_partitions,
)
from tradingagents.evals.economic_evaluation_protocol import (
    FrozenEvaluationProtocol,
    validate_frozen_evaluation_protocol,
)

__all__ = [
    "EconomicPhaseEligibility",
    "EconomicPartitionBindingError",
    "ValidationPhaseEligibility",
    "bind_phase_eligibility",
    "bind_validation_phase_eligibility",
    "validate_phase_eligibility",
    "validate_validation_phase_eligibility",
]


class EconomicPartitionBindingError(ValueError):
    """Raised when a protocol and PIT partition receipt disagree."""


_PHASE_EVENT_ATTRS = {
    "development": "development_eligible_event_ids",
    "validation": "validation_eligible_event_ids",
    "holdout": "holdout_eligible_event_ids",
}


@dataclass(frozen=True, slots=True, init=False)
class EconomicPhaseEligibility:
    """Canonical evaluable IDs for one frozen economic protocol phase."""

    protocol_id: str
    partition_id: str
    partition_sha256: str
    phase: str
    event_ids: tuple[str, ...]
    partitions: MarketDatePartitions

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("EconomicPhaseEligibility instances must be created by its binder")


@dataclass(frozen=True, slots=True, init=False)
class ValidationPhaseEligibility:
    """Canonical evaluable validation IDs bound to one PIT partition receipt."""

    protocol_id: str
    partition_id: str
    partition_sha256: str
    event_ids: tuple[str, ...]
    partitions: MarketDatePartitions

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("ValidationPhaseEligibility instances must be created by its binder")


def _new_eligibility(**fields: object) -> ValidationPhaseEligibility:
    value = object.__new__(ValidationPhaseEligibility)
    for name, field_value in fields.items():
        object.__setattr__(value, name, field_value)
    return value


def _new_phase_eligibility(**fields: object) -> EconomicPhaseEligibility:
    value = object.__new__(EconomicPhaseEligibility)
    for name, field_value in fields.items():
        object.__setattr__(value, name, field_value)
    return value


def bind_phase_eligibility(
    *,
    protocol: FrozenEvaluationProtocol,
    partitions: MarketDatePartitions,
    phase: str,
) -> EconomicPhaseEligibility:
    """Bind one named lifecycle phase to its exact frozen PIT event IDs."""

    if type(protocol) is not FrozenEvaluationProtocol or type(partitions) is not MarketDatePartitions:
        raise EconomicPartitionBindingError("protocol and partitions must be exact frozen values")
    if phase not in _PHASE_EVENT_ATTRS:
        raise EconomicPartitionBindingError("phase must be development, validation, or holdout")
    frozen = validate_frozen_evaluation_protocol(protocol.to_dict())
    partitioned = validate_market_date_partitions(partitions.to_dict())
    if (
        frozen.development_event_ids != partitioned.development_event_ids
        or frozen.validation_event_ids != partitioned.validation_event_ids
        or frozen.holdout_event_ids != partitioned.holdout_event_ids
    ):
        raise EconomicPartitionBindingError("protocol partitions do not match PIT partition receipt")
    return _new_phase_eligibility(
        protocol_id=frozen.protocol_id,
        partition_id=partitioned.partition_id,
        partition_sha256=partitioned.partition_sha256,
        phase=phase,
        event_ids=getattr(partitioned, _PHASE_EVENT_ATTRS[phase]),
        partitions=partitioned,
    )


def validate_phase_eligibility(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: EconomicPhaseEligibility,
) -> EconomicPhaseEligibility:
    """Rebuild a phase binding from its complete frozen partition receipt."""

    if type(protocol) is not FrozenEvaluationProtocol:
        raise EconomicPartitionBindingError("protocol must be an exact frozen value")
    if type(eligibility) is not EconomicPhaseEligibility:
        raise EconomicPartitionBindingError("eligibility must be an exact phase binding")
    canonical = bind_phase_eligibility(
        protocol=protocol,
        partitions=eligibility.partitions,
        phase=eligibility.phase,
    )
    if eligibility != canonical:
        raise EconomicPartitionBindingError("eligibility bytes do not match canonical rebuild")
    return canonical


def bind_validation_phase_eligibility(
    *,
    protocol: FrozenEvaluationProtocol,
    partitions: MarketDatePartitions,
) -> ValidationPhaseEligibility:
    """Require the protocol's exhaustive partitions before exposing validation IDs."""

    generic = bind_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
        phase="validation",
    )
    return _new_eligibility(
        protocol_id=generic.protocol_id,
        partition_id=generic.partition_id,
        partition_sha256=generic.partition_sha256,
        event_ids=generic.event_ids,
        partitions=generic.partitions,
    )


def validate_validation_phase_eligibility(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
) -> ValidationPhaseEligibility:
    """Rebuild a validation eligibility value from its complete PIT receipt."""

    if type(protocol) is not FrozenEvaluationProtocol:
        raise EconomicPartitionBindingError("protocol must be an exact frozen value")
    if type(eligibility) is not ValidationPhaseEligibility:
        raise EconomicPartitionBindingError("eligibility must be an exact partition binding")
    canonical = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=eligibility.partitions,
    )
    if eligibility != canonical:
        raise EconomicPartitionBindingError("eligibility bytes do not match canonical rebuild")
    return canonical
