"""Pure, analysis-only bounded strategy mutation primitives."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)
from pathlib import Path

from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
)
from tradingagents.strategy.genome import (
    CatalystRelativeStrengthParameters,
    CurrentAggressiveParameters,
    PullbackSupportParameters,
    StrategyEvolutionPolicy,
    StrategyFamily,
    StrategyGenome,
)
from tradingagents.strategy.promotion_evidence import (
    StrategyEvaluationRegistration,
    StrategyPromotionEvidence,
)

BASELINE_GENOME_REGISTRATION_SCHEMA_VERSION = 1
STRATEGY_MUTATION_RECORD_SCHEMA_VERSION = 1
MUTATION_CYCLE_MATERIAL_SCHEMA_VERSION = 1
MUTATION_DECIMAL_CONTEXT_PRECISION = 50
MUTATION_DECIMAL_MAX_FRACTIONAL_DIGITS = 32

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FIXED = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,32})?$")
_PATHS = frozenset(
    {
        "current-aggressive.min_score",
        "pullback-support.min_daily_change_fraction",
        "pullback-support.max_daily_change_fraction",
        "pullback-support.max_volume_ratio",
        "catalyst-relative-strength.min_score",
    }
)


class StrategyMutationRegistryError(ValueError):
    """A bounded mutation invariant was not satisfied."""


def _fixed(value: object, *, label: str, nonzero: bool = False) -> str:
    if type(value) is not str or _FIXED.fullmatch(value) is None:
        raise StrategyMutationRegistryError(f"{label} must be a canonical fixed-point decimal")
    decimal_value = Decimal(value)
    if decimal_value == 0 and value.startswith("-"):
        raise StrategyMutationRegistryError(f"{label} cannot be negative zero")
    canonical = format(decimal_value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if value != canonical:
        raise StrategyMutationRegistryError(f"{label} must not have redundant trailing zeroes")
    if nonzero and decimal_value == 0:
        raise StrategyMutationRegistryError(f"{label} must be nonzero")
    return value


def _fixed_result(value: Decimal, *, label: str, nonzero: bool = False) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return _fixed(text, label=label, nonzero=nonzero)


def _context() -> Context:
    context = Context(
        prec=MUTATION_DECIMAL_CONTEXT_PRECISION,
        rounding=ROUND_HALF_EVEN,
        Emin=-999,
        Emax=999,
    )
    for signal in (InvalidOperation, DivisionByZero, Overflow, Inexact, Rounded):
        context.traps[signal] = True
    return context


def _datetime_text(value: dt.datetime) -> str:
    if not isinstance(value, dt.datetime):
        raise TypeError("cycle_effective_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise StrategyMutationRegistryError("cycle_effective_at must be timezone-aware")
    if value.microsecond != 0:
        raise StrategyMutationRegistryError("cycle_effective_at must have zero microseconds")
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _canonical_utc_text(value: object, *, label: str) -> str:
    if type(value) is not str or value.endswith("Z"):
        raise StrategyMutationRegistryError(f"{label} must use +00:00")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise StrategyMutationRegistryError(f"{label} is invalid") from exc
    if (
        parsed.tzinfo is None
        or parsed.microsecond != 0
        or parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
        != value
    ):
        raise StrategyMutationRegistryError(f"{label} is not canonical UTC")
    return value


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _expected_object_id(
    *,
    kind: str,
    effective_at: str,
    payload: Mapping[str, object],
) -> str:
    material = {
        "kind": kind,
        "effective_at": effective_at,
        "payload": payload,
    }
    return f"{kind}-{hashlib.sha256(_canonical_json_bytes(material)).hexdigest()}"


def build_mutation_cycle_id(
    *,
    source_evidence_id: str,
    parent_genome_canonical_sha256: str,
    evolution_policy_sha256: str,
    cycle_effective_at: dt.datetime,
) -> str:
    if type(source_evidence_id) is not str or not re.fullmatch(r"promotion-evidence-[0-9a-f]{64}", source_evidence_id):
        raise StrategyMutationRegistryError("source_evidence_id must be a full digest")
    for value, label in (
        (parent_genome_canonical_sha256, "parent_genome_canonical_sha256"),
        (evolution_policy_sha256, "evolution_policy_sha256"),
    ):
        if type(value) is not str or _DIGEST.fullmatch(value) is None:
            raise StrategyMutationRegistryError(f"{label} must be lowercase SHA-256")
    material = {
        "cycle_effective_at": _datetime_text(cycle_effective_at),
        "evolution_policy_sha256": evolution_policy_sha256,
        "parent_genome_canonical_sha256": parent_genome_canonical_sha256,
        "schema_version": MUTATION_CYCLE_MATERIAL_SCHEMA_VERSION,
        "source_evidence_id": source_evidence_id,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"cycle-{hashlib.sha256(encoded).hexdigest()}"


def _bound(policy: StrategyEvolutionPolicy, path: str) -> str:
    if type(policy) is not StrategyEvolutionPolicy:
        raise TypeError("evolution_policy must be a StrategyEvolutionPolicy")
    family, field_name = path.split(".", 1)
    if family == StrategyFamily.CURRENT_AGGRESSIVE.value:
        value = policy.mutation_bounds.current_aggressive.min_score
    elif family == StrategyFamily.PULLBACK_SUPPORT.value:
        value = getattr(policy.mutation_bounds.pullback_support, field_name)
    else:
        value = policy.mutation_bounds.catalyst_relative_strength.min_score
    return _fixed(value, label="durable mutation bound", nonzero=True)


def build_mutated_genome(
    parent: StrategyGenome,
    parameter_path: str,
    signed_delta: str,
    evolution_policy: StrategyEvolutionPolicy,
) -> StrategyGenome:
    if type(parent) is not StrategyGenome:
        raise TypeError("parent must be a StrategyGenome")
    if type(parameter_path) is not str or parameter_path not in _PATHS:
        raise StrategyMutationRegistryError("parameter_path is not mutable")
    if type(signed_delta) is not str:
        raise TypeError("signed_delta must be a canonical decimal string")
    delta = _fixed(signed_delta, label="signed_delta", nonzero=True)
    family, field_name = parameter_path.split(".", 1)
    if parent.family.value != family:
        raise StrategyMutationRegistryError("parameter_path family does not match")
    before = _fixed(getattr(parent.parameters, field_name), label="before_value")
    with localcontext(_context()):
        if abs(Decimal(delta)) > Decimal(_bound(evolution_policy, parameter_path)):
            raise StrategyMutationRegistryError("signed_delta exceeds durable bound")
        after = _fixed_result(Decimal(before) + Decimal(delta), label="after_value")
        reverse = _fixed_result(Decimal(after) - Decimal(before), label="signed_delta", nonzero=True)
    if reverse != delta:
        raise StrategyMutationRegistryError("mutation arithmetic does not round trip")
    values = parent.parameters.to_dict()
    values[field_name] = after
    if parent.family is StrategyFamily.CURRENT_AGGRESSIVE:
        parameters = CurrentAggressiveParameters(**values)
    elif parent.family is StrategyFamily.PULLBACK_SUPPORT:
        parameters = PullbackSupportParameters(**values)
    elif parent.family is StrategyFamily.CATALYST_RELATIVE_STRENGTH:
        parameters = CatalystRelativeStrengthParameters(**values)
    else:
        raise StrategyMutationRegistryError("hold-cash cannot mutate")
    return StrategyGenome.create(
        family=parent.family,
        parameters=parameters,
        generation=parent.generation + 1,
        parent_id=parent.genome_id,
    )


@dataclass(frozen=True, slots=True)
class BaselineGenomeRegistration:
    baseline_id: str
    genome: StrategyGenome
    genome_canonical_sha256: str
    evolution_policy_sha256: str
    effective_at: str
    recorded_at: str
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"baseline-genome-[0-9a-f]{64}", self.baseline_id):
            raise StrategyMutationRegistryError("baseline_id must be a full digest")
        if type(self.genome) is not StrategyGenome or self.genome.generation != 0:
            raise StrategyMutationRegistryError("baseline genome must be a root")
        if self.genome_canonical_sha256 != hashlib.sha256(self.genome.canonical_json_bytes()).hexdigest():
            raise StrategyMutationRegistryError("baseline genome digest does not match")
        if type(self.evolution_policy_sha256) is not str or _DIGEST.fullmatch(self.evolution_policy_sha256) is None:
            raise StrategyMutationRegistryError("baseline policy digest is invalid")
        for value, label in (
            (self.effective_at, "baseline effective_at"),
            (self.recorded_at, "baseline recorded_at"),
        ):
            if type(value) is not str or value.endswith("Z"):
                raise StrategyMutationRegistryError(f"{label} must use +00:00")
            parsed = dt.datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds") != value:
                raise StrategyMutationRegistryError(f"{label} is not canonical UTC")
        if self.effective_at > self.recorded_at:
            raise StrategyMutationRegistryError("baseline effective_at exceeds recorded_at")
        expected_baseline_id = _expected_object_id(
            kind="baseline-genome",
            effective_at=self.effective_at,
            payload=self._evidence_payload(),
        )
        if self.baseline_id != expected_baseline_id:
            raise StrategyMutationRegistryError(
                "baseline_id does not match evidence identity"
            )

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for field_name in ("baseline_id", "effective_at", "recorded_at"):
            del payload[field_name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": BASELINE_GENOME_REGISTRATION_SCHEMA_VERSION,
            "baseline_id": self.baseline_id,
            "genome": self.genome.to_dict(),
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "evolution_policy_sha256": self.evolution_policy_sha256,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }

    def canonical_json_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_envelope(cls, envelope: EvidenceEnvelope) -> BaselineGenomeRegistration:
        if type(envelope) is not EvidenceEnvelope or envelope.kind != "baseline-genome":
            raise StrategyMutationRegistryError("baseline envelope kind is invalid")
        payload = dict(envelope.payload)
        expected = {
            "schema_version",
            "genome",
            "genome_canonical_sha256",
            "evolution_policy_sha256",
            "analysis_only",
            "execution_authority",
            "can_submit_orders",
        }
        if set(payload) != expected:
            raise StrategyMutationRegistryError("baseline payload schema is invalid")
        if payload["schema_version"] != BASELINE_GENOME_REGISTRATION_SCHEMA_VERSION:
            raise StrategyMutationRegistryError("baseline schema_version is invalid")
        if payload["analysis_only"] is not True or payload["execution_authority"] != "none" or payload["can_submit_orders"] is not False:
            raise StrategyMutationRegistryError("baseline authority is invalid")
        baseline = cls(
            baseline_id=envelope.object_id,
            genome=StrategyGenome.from_dict(payload["genome"]),  # type: ignore[arg-type]
            genome_canonical_sha256=payload["genome_canonical_sha256"],  # type: ignore[arg-type]
            evolution_policy_sha256=payload["evolution_policy_sha256"],  # type: ignore[arg-type]
            effective_at=envelope.effective_at,
            recorded_at=envelope.recorded_at,
        )
        if baseline._evidence_payload() != payload:
            raise StrategyMutationRegistryError(
                "baseline payload round trip is not exact"
            )
        return baseline


@dataclass(frozen=True, slots=True)
class StrategyMutationRecord:
    mutation_id: str
    cycle_id: str
    ordinal: int
    source_evidence_id: str
    parent_genome: StrategyGenome
    parent_genome_canonical_sha256: str
    child_genome: StrategyGenome
    child_genome_canonical_sha256: str
    family: StrategyFamily
    parameter_path: str
    before_value: str
    after_value: str
    signed_delta: str
    evolution_policy_sha256: str
    effective_at: str
    recorded_at: str
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if (
            type(self.mutation_id) is not str
            or re.fullmatch(r"mutation-record-[0-9a-f]{64}", self.mutation_id)
            is None
        ):
            raise StrategyMutationRegistryError(
                "mutation_id must be a full digest"
            )
        if (
            type(self.cycle_id) is not str
            or re.fullmatch(r"cycle-[0-9a-f]{64}", self.cycle_id) is None
        ):
            raise StrategyMutationRegistryError("cycle_id must be a full digest")
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise StrategyMutationRegistryError("ordinal must be positive")
        if (
            type(self.source_evidence_id) is not str
            or re.fullmatch(
                r"promotion-evidence-[0-9a-f]{64}",
                self.source_evidence_id,
            )
            is None
        ):
            raise StrategyMutationRegistryError(
                "source_evidence_id must be a full digest"
            )
        if type(self.parent_genome) is not StrategyGenome:
            raise TypeError("parent_genome must be a StrategyGenome")
        if type(self.child_genome) is not StrategyGenome:
            raise TypeError("child_genome must be a StrategyGenome")
        expected_parent_digest = hashlib.sha256(
            self.parent_genome.canonical_json_bytes()
        ).hexdigest()
        expected_child_digest = hashlib.sha256(
            self.child_genome.canonical_json_bytes()
        ).hexdigest()
        if self.parent_genome_canonical_sha256 != expected_parent_digest:
            raise StrategyMutationRegistryError(
                "parent genome digest does not match"
            )
        if self.child_genome_canonical_sha256 != expected_child_digest:
            raise StrategyMutationRegistryError(
                "child genome digest does not match"
            )
        if type(self.family) is not StrategyFamily:
            raise TypeError("family must be a StrategyFamily")
        if (
            self.parent_genome.family is not self.family
            or self.child_genome.family is not self.family
        ):
            raise StrategyMutationRegistryError("mutation family does not match")
        if self.family is StrategyFamily.HOLD_CASH:
            raise StrategyMutationRegistryError("hold-cash cannot mutate")
        if (
            type(self.parameter_path) is not str
            or self.parameter_path not in _PATHS
            or not self.parameter_path.startswith(f"{self.family.value}.")
        ):
            raise StrategyMutationRegistryError(
                "parameter_path does not match family"
            )
        before = _fixed(self.before_value, label="before_value")
        after = _fixed(self.after_value, label="after_value")
        delta = _fixed(self.signed_delta, label="signed_delta", nonzero=True)
        if (
            self.child_genome.generation
            != self.parent_genome.generation + 1
        ):
            raise StrategyMutationRegistryError(
                "child generation must follow parent"
            )
        if self.child_genome.parent_id != self.parent_genome.genome_id:
            raise StrategyMutationRegistryError(
                "child parent_id does not match parent"
            )
        parent_values = self.parent_genome.parameters.to_dict()
        child_values = self.child_genome.parameters.to_dict()
        changed = tuple(
            name
            for name in parent_values
            if parent_values[name] != child_values[name]
        )
        field_name = self.parameter_path.split(".", 1)[1]
        if changed != (field_name,):
            raise StrategyMutationRegistryError(
                "exactly one numeric parameter must change"
            )
        if parent_values[field_name] != before:
            raise StrategyMutationRegistryError(
                "before_value does not match parent"
            )
        if child_values[field_name] != after:
            raise StrategyMutationRegistryError(
                "after_value does not match child"
            )
        with localcontext(_context()):
            computed_after = _fixed_result(
                Decimal(before) + Decimal(delta),
                label="after_value",
            )
            computed_delta = _fixed_result(
                Decimal(after) - Decimal(before),
                label="signed_delta",
                nonzero=True,
            )
        if computed_after != after or computed_delta != delta:
            raise StrategyMutationRegistryError(
                "mutation arithmetic does not round trip"
            )
        if (
            type(self.evolution_policy_sha256) is not str
            or _DIGEST.fullmatch(self.evolution_policy_sha256) is None
        ):
            raise StrategyMutationRegistryError(
                "evolution policy digest is invalid"
            )
        effective = _canonical_utc_text(
            self.effective_at,
            label="mutation effective_at",
        )
        recorded = _canonical_utc_text(
            self.recorded_at,
            label="mutation recorded_at",
        )
        if effective > recorded:
            raise StrategyMutationRegistryError(
                "mutation effective_at exceeds recorded_at"
            )
        expected_cycle = build_mutation_cycle_id(
            source_evidence_id=self.source_evidence_id,
            parent_genome_canonical_sha256=(
                self.parent_genome_canonical_sha256
            ),
            evolution_policy_sha256=self.evolution_policy_sha256,
            cycle_effective_at=dt.datetime.fromisoformat(self.effective_at),
        )
        if self.cycle_id != expected_cycle:
            raise StrategyMutationRegistryError(
                "cycle_id does not match cycle material"
            )
        expected_mutation_id = _expected_object_id(
            kind="mutation-record",
            effective_at=self.effective_at,
            payload=self._evidence_payload(),
        )
        if self.mutation_id != expected_mutation_id:
            raise StrategyMutationRegistryError(
                "mutation_id does not match evidence identity"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StrategyMutationRecord:
        expected = {
            "schema_version",
            "mutation_id",
            "cycle_id",
            "ordinal",
            "source_evidence_id",
            "parent_genome",
            "parent_genome_canonical_sha256",
            "child_genome",
            "child_genome_canonical_sha256",
            "family",
            "parameter_path",
            "before_value",
            "after_value",
            "signed_delta",
            "evolution_policy_sha256",
            "effective_at",
            "recorded_at",
            "analysis_only",
            "execution_authority",
            "can_submit_orders",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StrategyMutationRegistryError("mutation record schema is invalid")
        if payload["schema_version"] != STRATEGY_MUTATION_RECORD_SCHEMA_VERSION:
            raise StrategyMutationRegistryError("mutation record schema is invalid")
        if (
            payload["analysis_only"] is not True
            or payload["execution_authority"] != "none"
            or payload["can_submit_orders"] is not False
        ):
            raise StrategyMutationRegistryError("mutation record authority is invalid")
        return cls(
            mutation_id=payload["mutation_id"],  # type: ignore[arg-type]
            cycle_id=payload["cycle_id"],  # type: ignore[arg-type]
            ordinal=payload["ordinal"],  # type: ignore[arg-type]
            source_evidence_id=payload["source_evidence_id"],  # type: ignore[arg-type]
            parent_genome=StrategyGenome.from_dict(payload["parent_genome"]),  # type: ignore[arg-type]
            parent_genome_canonical_sha256=payload["parent_genome_canonical_sha256"],  # type: ignore[arg-type]
            child_genome=StrategyGenome.from_dict(payload["child_genome"]),  # type: ignore[arg-type]
            child_genome_canonical_sha256=payload["child_genome_canonical_sha256"],  # type: ignore[arg-type]
            family=StrategyFamily(payload["family"]),  # type: ignore[arg-type]
            parameter_path=payload["parameter_path"],  # type: ignore[arg-type]
            before_value=payload["before_value"],  # type: ignore[arg-type]
            after_value=payload["after_value"],  # type: ignore[arg-type]
            signed_delta=payload["signed_delta"],  # type: ignore[arg-type]
            evolution_policy_sha256=payload["evolution_policy_sha256"],  # type: ignore[arg-type]
            effective_at=payload["effective_at"],  # type: ignore[arg-type]
            recorded_at=payload["recorded_at"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_envelope(
        cls,
        envelope: EvidenceEnvelope,
    ) -> StrategyMutationRecord:
        if type(envelope) is not EvidenceEnvelope:
            raise TypeError("mutation envelope type does not match")
        if envelope.kind != "mutation-record":
            raise StrategyMutationRegistryError(
                "envelope kind is not mutation-record"
            )
        payload = dict(envelope.payload)
        full = {
            **payload,
            "mutation_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
        }
        record = cls.from_dict(full)
        if record._evidence_payload() != payload:
            raise StrategyMutationRegistryError(
                "mutation payload round trip is not exact"
            )
        return record

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for field_name in ("mutation_id", "effective_at", "recorded_at"):
            del payload[field_name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": STRATEGY_MUTATION_RECORD_SCHEMA_VERSION,
            "mutation_id": self.mutation_id,
            "cycle_id": self.cycle_id,
            "ordinal": self.ordinal,
            "source_evidence_id": self.source_evidence_id,
            "parent_genome": self.parent_genome.to_dict(),
            "parent_genome_canonical_sha256": (
                self.parent_genome_canonical_sha256
            ),
            "child_genome": self.child_genome.to_dict(),
            "child_genome_canonical_sha256": (
                self.child_genome_canonical_sha256
            ),
            "family": self.family.value,
            "parameter_path": self.parameter_path,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "signed_delta": self.signed_delta,
            "evolution_policy_sha256": self.evolution_policy_sha256,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _mutation_material(
    parent: StrategyGenome,
    child: StrategyGenome,
) -> tuple[str, str, str, str]:
    if parent.family is StrategyFamily.HOLD_CASH:
        raise StrategyMutationRegistryError("hold-cash cannot mutate")
    if child.family is not parent.family:
        raise StrategyMutationRegistryError(
            "parent and child families do not match"
        )
    if child.generation != parent.generation + 1:
        raise StrategyMutationRegistryError(
            "child generation must follow parent"
        )
    if child.parent_id != parent.genome_id:
        raise StrategyMutationRegistryError(
            "child parent_id does not match parent"
        )
    parent_values = parent.parameters.to_dict()
    child_values = child.parameters.to_dict()
    if set(parent_values) != set(child_values):
        raise StrategyMutationRegistryError(
            "parent and child parameter schemas do not match"
        )
    changed = tuple(
        name
        for name in parent_values
        if parent_values[name] != child_values[name]
    )
    if len(changed) != 1:
        raise StrategyMutationRegistryError(
            "exactly one numeric parameter must change"
        )
    field_name = changed[0]
    parameter_path = f"{parent.family.value}.{field_name}"
    if parameter_path not in _PATHS:
        raise StrategyMutationRegistryError("parameter_path is not mutable")
    before = _fixed(parent_values[field_name], label="before_value")
    after = _fixed(child_values[field_name], label="after_value")
    with localcontext(_context()):
        delta = _fixed_result(
            Decimal(after) - Decimal(before),
            label="signed_delta",
            nonzero=True,
        )
        forward = _fixed_result(
            Decimal(before) + Decimal(delta),
            label="after_value",
        )
        reverse = _fixed_result(
            Decimal(after) - Decimal(before),
            label="signed_delta",
            nonzero=True,
        )
    if forward != after or reverse != delta:
        raise StrategyMutationRegistryError(
            "mutation arithmetic does not round trip"
        )
    return parameter_path, before, after, delta


def _envelope_by_id(
    snapshot: tuple[EvidenceEnvelope, ...],
    object_id: str,
    *,
    label: str,
) -> EvidenceEnvelope:
    matches = tuple(item for item in snapshot if item.object_id == object_id)
    if len(matches) != 1:
        raise StrategyMutationRegistryError(
            f"durable {label} is missing or duplicated"
        )
    return matches[0]


def _durable_parent_envelope(
    snapshot: tuple[EvidenceEnvelope, ...],
    record: StrategyMutationRecord,
) -> EvidenceEnvelope:
    exact: list[EvidenceEnvelope] = []
    partial_match = False
    for envelope in snapshot:
        if envelope.kind == "baseline-genome":
            baseline = BaselineGenomeRegistration.from_envelope(envelope)
            semantic_matches = (
                baseline.genome.genome_id == record.parent_genome.genome_id
            )
            digest_matches = (
                baseline.genome_canonical_sha256
                == record.parent_genome_canonical_sha256
            )
            partial_match = partial_match or semantic_matches or digest_matches
            if semantic_matches and digest_matches:
                if (
                    baseline.genome.canonical_json_bytes()
                    != record.parent_genome.canonical_json_bytes()
                ):
                    raise StrategyMutationRegistryError(
                        "durable parent bytes do not match"
                    )
                exact.append(envelope)
        elif envelope.kind == "mutation-record":
            mutation = StrategyMutationRecord.from_envelope(envelope)
            semantic_matches = (
                mutation.child_genome.genome_id
                == record.parent_genome.genome_id
            )
            digest_matches = (
                mutation.child_genome_canonical_sha256
                == record.parent_genome_canonical_sha256
            )
            partial_match = partial_match or semantic_matches or digest_matches
            if semantic_matches and digest_matches:
                if (
                    mutation.child_genome.canonical_json_bytes()
                    != record.parent_genome.canonical_json_bytes()
                ):
                    raise StrategyMutationRegistryError(
                        "durable parent bytes do not match"
                    )
                exact.append(envelope)
    if len(exact) != 1:
        detail = "lineage does not match" if partial_match else "is missing"
        raise StrategyMutationRegistryError(f"durable parent {detail}")
    return exact[0]


def _validate_mutation_dependencies(
    snapshot: tuple[EvidenceEnvelope, ...],
    record: StrategyMutationRecord,
    *,
    source_evidence: StrategyPromotionEvidence | None = None,
    evolution_policy: StrategyEvolutionPolicy | None = None,
    exclude_object_id: str | None = None,
    replay: bool = False,
) -> None:
    source_envelope = _envelope_by_id(
        snapshot,
        record.source_evidence_id,
        label="source evidence",
    )
    durable_source = StrategyPromotionEvidence.from_envelope(source_envelope)
    if (
        source_evidence is not None
        and durable_source.canonical_json_bytes()
        != source_evidence.canonical_json_bytes()
    ):
        raise StrategyMutationRegistryError(
            "caller source bytes do not match durable source"
        )
    registration_envelope = _envelope_by_id(
        snapshot,
        durable_source.registration_id,
        label="registration",
    )
    try:
        registration = StrategyEvaluationRegistration.from_envelope(
            registration_envelope
        )
    except (TypeError, ValueError) as exc:
        raise StrategyMutationRegistryError(
            f"durable registration is malformed: {exc}"
        ) from exc
    if (
        durable_source.evaluation_code_commit
        != registration.evaluation_code_commit
        or durable_source.evaluation_runtime_sha256
        != registration.evaluation_runtime_sha256
    ):
        raise StrategyMutationRegistryError(
            "durable source provenance does not match registration"
        )
    if (
        durable_source.genome_id != record.parent_genome.genome_id
        or durable_source.genome_canonical_sha256
        != record.parent_genome_canonical_sha256
        or registration.genome.genome_id
        != record.parent_genome.genome_id
        or registration.genome_canonical_sha256
        != record.parent_genome_canonical_sha256
    ):
        raise StrategyMutationRegistryError(
            "source registration does not bind parent lineage"
        )
    embedded_policy_digest = hashlib.sha256(
        registration.evolution_policy.canonical_json_bytes()
    ).hexdigest()
    if (
        registration.evolution_policy_sha256 != embedded_policy_digest
        or record.evolution_policy_sha256 != embedded_policy_digest
    ):
        raise StrategyMutationRegistryError(
            "mutation policy digest does not match durable registration policy"
        )
    if (
        evolution_policy is not None
        and hashlib.sha256(
            evolution_policy.canonical_json_bytes()
        ).hexdigest()
        != embedded_policy_digest
    ):
        raise StrategyMutationRegistryError(
            "caller policy does not match durable registration policy"
        )
    if registration.evolution_policy.enabled is not True:
        raise StrategyMutationRegistryError(
            "durable registration policy is disabled"
        )
    durable_parent = _durable_parent_envelope(snapshot, record)
    if (
        record.effective_at < source_envelope.recorded_at
        or record.effective_at < durable_parent.recorded_at
    ):
        raise StrategyMutationRegistryError(
            "mutation effective_at predates a durable dependency"
        )
    if record.effective_at > record.recorded_at:
        raise StrategyMutationRegistryError(
            "mutation effective_at exceeds first-seen time"
        )
    try:
        expected_child = build_mutated_genome(
            record.parent_genome,
            record.parameter_path,
            record.signed_delta,
            registration.evolution_policy,
        )
    except StrategyMutationRegistryError as exc:
        if "bound" in str(exc):
            raise StrategyMutationRegistryError(
                "mutation exceeds durable policy bound"
            ) from exc
        raise
    if (
        expected_child.canonical_json_bytes()
        != record.child_genome.canonical_json_bytes()
    ):
        raise StrategyMutationRegistryError(
            "child genome does not match deterministic mutation"
        )
    _validate_mutation_indexes(
        snapshot,
        record,
        registration.evolution_policy,
        exclude_object_id=exclude_object_id,
        replay=replay,
    )


def _validate_mutation_indexes(
    snapshot: tuple[EvidenceEnvelope, ...],
    record: StrategyMutationRecord,
    durable_policy: StrategyEvolutionPolicy,
    *,
    exclude_object_id: str | None,
    replay: bool,
) -> None:
    prior_records = tuple(
        StrategyMutationRecord.from_envelope(envelope)
        for envelope in snapshot
        if envelope.kind == "mutation-record"
        and envelope.object_id != exclude_object_id
    )
    same_cycle = tuple(
        item for item in prior_records if item.cycle_id == record.cycle_id
    )
    for prior in same_cycle:
        if (
            prior.source_evidence_id != record.source_evidence_id
            or prior.parent_genome_canonical_sha256
            != record.parent_genome_canonical_sha256
            or prior.evolution_policy_sha256
            != record.evolution_policy_sha256
            or prior.effective_at != record.effective_at
        ):
            raise StrategyMutationRegistryError(
                "same cycle material does not match"
            )
    if record.ordinal > durable_policy.mutations_per_cycle:
        raise StrategyMutationRegistryError(
            "ordinal exceeds durable mutations_per_cycle"
        )
    if any(item.ordinal == record.ordinal for item in same_cycle):
        raise StrategyMutationRegistryError("duplicate cycle slot")
    cycle_ordinals = tuple(
        sorted((record.ordinal, *(item.ordinal for item in same_cycle)))
    )
    if replay and cycle_ordinals != tuple(
        range(1, len(cycle_ordinals) + 1)
    ):
        raise StrategyMutationRegistryError(
            "durable cycle ordinals are not contiguous"
        )
    if not replay and record.ordinal != len(same_cycle) + 1:
        raise StrategyMutationRegistryError(
            "ordinal is not the next contiguous cycle ordinal"
        )
    if any(
        item.child_genome_canonical_sha256
        == record.child_genome_canonical_sha256
        for item in prior_records
    ):
        raise StrategyMutationRegistryError(
            "duplicate child full canonical digest"
        )
    if any(
        item.child_genome.genome_id == record.child_genome.genome_id
        for item in prior_records
    ):
        raise StrategyMutationRegistryError("duplicate semantic child")
    baselines = tuple(
        BaselineGenomeRegistration.from_envelope(envelope)
        for envelope in snapshot
        if envelope.kind == "baseline-genome"
    )
    if any(
        item.genome_canonical_sha256
        == record.child_genome_canonical_sha256
        for item in baselines
    ):
        raise StrategyMutationRegistryError(
            "duplicate child full canonical digest"
        )
    if any(
        item.genome.genome_id == record.child_genome.genome_id
        for item in baselines
    ):
        raise StrategyMutationRegistryError("duplicate semantic child")


def _validate_mutation_snapshot(
    snapshot: tuple[EvidenceEnvelope, ...],
) -> tuple[StrategyMutationRecord, ...]:
    baselines = tuple(
        BaselineGenomeRegistration.from_envelope(envelope)
        for envelope in snapshot
        if envelope.kind == "baseline-genome"
    )
    records = tuple(
        StrategyMutationRecord.from_envelope(envelope)
        for envelope in snapshot
        if envelope.kind == "mutation-record"
    )
    for index, baseline in enumerate(baselines):
        others = baselines[:index] + baselines[index + 1 :]
        if any(
            item.genome.genome_id == baseline.genome.genome_id
            for item in others
        ):
            raise StrategyMutationRegistryError(
                "duplicate baseline semantic genome"
            )
        if any(
            item.genome_canonical_sha256
            == baseline.genome_canonical_sha256
            for item in others
        ):
            raise StrategyMutationRegistryError(
                "duplicate baseline full genome"
            )
        if any(
            item.child_genome.genome_id == baseline.genome.genome_id
            for item in records
        ):
            raise StrategyMutationRegistryError(
                "duplicate semantic genome from mutation child"
            )
        if any(
            item.child_genome_canonical_sha256
            == baseline.genome_canonical_sha256
            for item in records
        ):
            raise StrategyMutationRegistryError(
                "duplicate full genome from mutation child"
            )
    for record in records:
        _validate_mutation_dependencies(
            snapshot,
            record,
            exclude_object_id=record.mutation_id,
            replay=True,
        )
    return records


class StrategyMutationRegistry:
    """Shared-store admission of immutable generation-zero baselines."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        self._store = ImmutableStrategyEvidenceStore(root, clock=clock)

    def register_baseline(
        self,
        genome: StrategyGenome,
        evolution_policy: StrategyEvolutionPolicy,
        *,
        effective_at: dt.datetime,
    ) -> BaselineGenomeRegistration:
        if type(genome) is not StrategyGenome or genome.generation != 0:
            raise StrategyMutationRegistryError("baseline must be generation zero")
        if type(evolution_policy) is not StrategyEvolutionPolicy:
            raise TypeError("evolution_policy must be a StrategyEvolutionPolicy")
        effective = _datetime_text(effective_at)
        digest = hashlib.sha256(evolution_policy.canonical_json_bytes()).hexdigest()
        candidate = EvidenceCandidate(
            kind="baseline-genome",
            effective_at=effective,
            payload={
                "schema_version": BASELINE_GENOME_REGISTRATION_SCHEMA_VERSION,
                "genome": genome.to_dict(),
                "genome_canonical_sha256": hashlib.sha256(genome.canonical_json_bytes()).hexdigest(),
                "evolution_policy_sha256": digest,
                "analysis_only": True,
                "execution_authority": "none",
                "can_submit_orders": False,
            },
        )

        def validate(snapshot: tuple[EvidenceEnvelope, ...], envelope: EvidenceEnvelope) -> None:
            baseline = BaselineGenomeRegistration.from_envelope(envelope)
            existing = tuple(
                item
                for item in snapshot
                if item.object_id == baseline.baseline_id
            )
            if existing:
                if len(existing) != 1:
                    raise StrategyMutationRegistryError(
                        "duplicate baseline object identity"
                    )
                durable = BaselineGenomeRegistration.from_envelope(existing[0])
                if (
                    durable.canonical_json_bytes()
                    != baseline.canonical_json_bytes()
                ):
                    raise StrategyMutationRegistryError(
                        "baseline retry bytes do not match"
                    )
            others = tuple(
                BaselineGenomeRegistration.from_envelope(item)
                for item in snapshot
                if item.kind == "baseline-genome"
                and item.object_id != baseline.baseline_id
            )
            if any(item.genome.genome_id == baseline.genome.genome_id for item in others):
                raise StrategyMutationRegistryError("duplicate baseline semantic genome")
            if any(item.genome_canonical_sha256 == baseline.genome_canonical_sha256 for item in others):
                raise StrategyMutationRegistryError("duplicate baseline full genome")
            mutations = tuple(
                StrategyMutationRecord.from_envelope(item)
                for item in snapshot
                if item.kind == "mutation-record"
            )
            if any(
                item.child_genome.genome_id == baseline.genome.genome_id
                for item in mutations
            ):
                raise StrategyMutationRegistryError(
                    "duplicate semantic genome from mutation child"
                )
            if any(
                item.child_genome_canonical_sha256
                == baseline.genome_canonical_sha256
                for item in mutations
            ):
                raise StrategyMutationRegistryError(
                    "duplicate full genome from mutation child"
                )

        return BaselineGenomeRegistration.from_envelope(self._store.admit_checked(candidate, validate=validate).envelope)

    def register_mutation(
        self,
        *,
        cycle_id: str,
        ordinal: int,
        source_evidence: StrategyPromotionEvidence,
        parent: StrategyGenome,
        child: StrategyGenome,
        evolution_policy: StrategyEvolutionPolicy,
        effective_at: dt.datetime,
    ) -> StrategyMutationRecord:
        if type(source_evidence) is not StrategyPromotionEvidence:
            raise TypeError(
                "source_evidence must be a StrategyPromotionEvidence"
            )
        if type(parent) is not StrategyGenome:
            raise TypeError("parent must be a StrategyGenome")
        if type(child) is not StrategyGenome:
            raise TypeError("child must be a StrategyGenome")
        if type(evolution_policy) is not StrategyEvolutionPolicy:
            raise TypeError(
                "evolution_policy must be a StrategyEvolutionPolicy"
            )
        if type(ordinal) is not int or ordinal < 1:
            raise StrategyMutationRegistryError("ordinal must be positive")
        effective = _datetime_text(effective_at)
        parent_digest = hashlib.sha256(
            parent.canonical_json_bytes()
        ).hexdigest()
        child_digest = hashlib.sha256(
            child.canonical_json_bytes()
        ).hexdigest()
        policy_digest = hashlib.sha256(
            evolution_policy.canonical_json_bytes()
        ).hexdigest()
        if (
            type(cycle_id) is not str
            or cycle_id
            != build_mutation_cycle_id(
                source_evidence_id=source_evidence.evidence_id,
                parent_genome_canonical_sha256=parent_digest,
                evolution_policy_sha256=policy_digest,
                cycle_effective_at=effective_at,
            )
        ):
            raise StrategyMutationRegistryError(
                "cycle_id does not match cycle material"
            )
        parameter_path, before_value, after_value, signed_delta = (
            _mutation_material(parent, child)
        )
        candidate = EvidenceCandidate(
            kind="mutation-record",
            effective_at=effective,
            payload={
                "schema_version": STRATEGY_MUTATION_RECORD_SCHEMA_VERSION,
                "cycle_id": cycle_id,
                "ordinal": ordinal,
                "source_evidence_id": source_evidence.evidence_id,
                "parent_genome": parent.to_dict(),
                "parent_genome_canonical_sha256": parent_digest,
                "child_genome": child.to_dict(),
                "child_genome_canonical_sha256": child_digest,
                "family": parent.family.value,
                "parameter_path": parameter_path,
                "before_value": before_value,
                "after_value": after_value,
                "signed_delta": signed_delta,
                "evolution_policy_sha256": policy_digest,
                "analysis_only": True,
                "execution_authority": "none",
                "can_submit_orders": False,
            },
        )

        def validate(
            snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            record = StrategyMutationRecord.from_envelope(envelope)
            existing = tuple(
                item
                for item in snapshot
                if item.object_id == record.mutation_id
            )
            exact_retry = False
            if existing:
                if len(existing) != 1:
                    raise StrategyMutationRegistryError(
                        "duplicate mutation object identity"
                    )
                durable = StrategyMutationRecord.from_envelope(existing[0])
                if (
                    durable.canonical_json_bytes()
                    != record.canonical_json_bytes()
                ):
                    raise StrategyMutationRegistryError(
                        "mutation retry bytes do not match"
                    )
                exact_retry = True
            _validate_mutation_dependencies(
                snapshot,
                record,
                source_evidence=source_evidence,
                evolution_policy=evolution_policy,
                exclude_object_id=(
                    record.mutation_id if exact_retry else None
                ),
                replay=exact_retry,
            )

        admission = self._store.admit_checked(candidate, validate=validate)
        return StrategyMutationRecord.from_envelope(admission.envelope)

    def verify(self) -> tuple[StrategyMutationRecord, ...]:
        return _validate_mutation_snapshot(self._store.verify())

    def rebuild(self) -> tuple[StrategyMutationRecord, ...]:
        return _validate_mutation_snapshot(self._store.rebuild())
