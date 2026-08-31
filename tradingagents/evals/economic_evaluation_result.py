"""Pure canonical result material for one completed economic validation phase.

This module has no store, broker, runtime, filesystem, scheduler, or network
dependency.  It makes the complete validation result that an admission adapter
may later preserve and bind to a sealed holdout release explicit and auditable.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from tradingagents.evals.economic_evaluation_partition_binding import (
    ValidationPhaseEligibility,
    validate_validation_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import (
    CONTROL_ARM_IDS,
    REQUIRED_METRICS,
    FrozenEvaluationProtocol,
    validate_frozen_evaluation_protocol,
)
from tradingagents.evals.economic_tournament_statistics import (
    EconomicTournamentStatistics,
    validate_economic_tournament_statistics,
)

__all__ = [
    "EconomicEvaluationResultError",
    "EconomicValidationResult",
    "ECONOMIC_TOURNAMENT_RESULT_SCHEMA",
    "LegacyEconomicValidationResult",
    "build_validation_evaluation_result",
    "validate_economic_validation_result",
]


ECONOMIC_VALIDATION_RESULT_SCHEMA = "economic_validation_result/v2"
ECONOMIC_TOURNAMENT_RESULT_SCHEMA = "economic_validation_result/v3"
_LEGACY_ECONOMIC_VALIDATION_RESULT_SCHEMA = "economic_validation_result/v1"
_RESULT_STATUS = "completed"
_AUTHORITY_FIELDS: dict[str, object] = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_NONNEGATIVE_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COUNT_METRICS = frozenset(
    {
        "decision_event_count",
        "packet_event_cluster_count",
        "market_event_cluster_count",
    }
)
_COST_VARIANT_BPS = ("5", "10", "25", "50")


class EconomicEvaluationResultError(ValueError):
    """A completed validation result is not a canonical protocol output."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _exact_fields(
    value: object,
    expected: frozenset[str],
    *,
    label: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise EconomicEvaluationResultError(f"{label} must be a JSON object")
    keys = set(value)
    if keys != expected:
        raise EconomicEvaluationResultError(
            f"{label} fields mismatch: missing={sorted(expected - keys)} "
            f"extra={sorted(keys - expected)}"
        )
    return {key: value[key] for key in expected}


def _require_authority(value: Mapping[str, object], *, label: str) -> None:
    if value["analysis_only"] is not True:
        raise EconomicEvaluationResultError(f"{label}.analysis_only must be true")
    if type(value["execution_authority"]) is not str or value[
        "execution_authority"
    ] != "none":
        raise EconomicEvaluationResultError(
            f"{label}.execution_authority must be none"
        )
    if value["can_submit_orders"] is not False:
        raise EconomicEvaluationResultError(
            f"{label}.can_submit_orders must be false"
        )


def _metric_value(value: object, *, metric: str) -> str:
    if type(value) is not str:
        raise EconomicEvaluationResultError(f"{metric} must be a canonical string")
    if metric in _COUNT_METRICS:
        if _NONNEGATIVE_INTEGER.fullmatch(value) is None:
            raise EconomicEvaluationResultError(f"{metric} must be a nonnegative integer")
    elif _DECIMAL.fullmatch(value) is None:
        raise EconomicEvaluationResultError(f"{metric} must be a canonical decimal")
    else:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise EconomicEvaluationResultError(
                f"{metric} must be a canonical decimal"
            ) from exc
        canonical = "0" if parsed.is_zero() else format(parsed.normalize(), "f")
        if value != canonical:
            raise EconomicEvaluationResultError(f"{metric} must be a canonical decimal")
    return value


def _canonical_arm_metrics(
    value: object,
    *,
    validation_event_count: int,
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, Mapping) or set(value) != set(CONTROL_ARM_IDS):
        raise EconomicEvaluationResultError(
            "arm_metrics must contain the exact frozen control arms"
        )
    arms: list[Mapping[str, object]] = []
    expected_metrics = frozenset(REQUIRED_METRICS)
    for arm_id in CONTROL_ARM_IDS:
        metrics = _exact_fields(value[arm_id], expected_metrics, label=f"{arm_id} metrics")
        canonical = {
            metric: _metric_value(metrics[metric], metric=metric)
            for metric in REQUIRED_METRICS
        }
        if canonical["decision_event_count"] != str(validation_event_count):
            raise EconomicEvaluationResultError(
                "each arm must report the complete validation decision count"
            )
        if int(canonical["packet_event_cluster_count"]) > validation_event_count:
            raise EconomicEvaluationResultError(
                "packet cluster count cannot exceed validation decisions"
            )
        if int(canonical["market_event_cluster_count"]) > validation_event_count:
            raise EconomicEvaluationResultError(
                "market cluster count cannot exceed validation decisions"
            )
        arms.append(
            MappingProxyType(
                {
                    "arm_id": arm_id,
                    "metrics": MappingProxyType(canonical),
                }
            )
        )
    return tuple(arms)


def _canonical_cost_variants(
    value: object,
    *,
    validation_event_count: int,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Mapping) or set(value) != set(_COST_VARIANT_BPS):
        raise EconomicEvaluationResultError(
            "cost variants must contain the exact 5/10/25/50 bps cases"
        )
    variants: list[Mapping[str, object]] = []
    for cost in _COST_VARIANT_BPS:
        arms = _canonical_arm_metrics(
            value[cost],
            validation_event_count=validation_event_count,
        )
        half = _metric_value(
            _canonical_decimal_half(cost),
            metric="half_spread_bps_per_side",
        )
        variants.append(
            MappingProxyType(
                {
                    "cost_bps_per_side": cost,
                    "half_spread_bps_per_side": half,
                    "slippage_bps_per_side": half,
                    "arm_metrics": arms,
                }
            )
        )
    return tuple(variants)


def _canonical_decimal_half(value: str) -> str:
    parsed = Decimal(value) / Decimal("2")
    return "0" if parsed.is_zero() else format(parsed.normalize(), "f")


def _legacy_metric_value(value: object, *, metric: str) -> str:
    """Apply the historical v1 decimal rules without rewriting stored bytes."""

    if type(value) is not str:
        raise EconomicEvaluationResultError(f"{metric} must be a canonical string")
    if metric in _COUNT_METRICS:
        if _NONNEGATIVE_INTEGER.fullmatch(value) is None:
            raise EconomicEvaluationResultError(f"{metric} must be a nonnegative integer")
    elif _DECIMAL.fullmatch(value) is None:
        raise EconomicEvaluationResultError(f"{metric} must be a canonical decimal")
    return value


def _legacy_canonical_arm_metrics(
    value: object,
    *,
    validation_event_count: int,
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, Mapping) or set(value) != set(CONTROL_ARM_IDS):
        raise EconomicEvaluationResultError(
            "arm_metrics must contain the exact frozen control arms"
        )
    arms: list[Mapping[str, object]] = []
    expected_metrics = frozenset(REQUIRED_METRICS)
    for arm_id in CONTROL_ARM_IDS:
        metrics = _exact_fields(value[arm_id], expected_metrics, label=f"{arm_id} metrics")
        canonical = {
            metric: _legacy_metric_value(metrics[metric], metric=metric)
            for metric in REQUIRED_METRICS
        }
        if canonical["decision_event_count"] != str(validation_event_count):
            raise EconomicEvaluationResultError(
                "each arm must report the complete validation decision count"
            )
        if int(canonical["packet_event_cluster_count"]) > validation_event_count:
            raise EconomicEvaluationResultError(
                "packet cluster count cannot exceed validation decisions"
            )
        if int(canonical["market_event_cluster_count"]) > validation_event_count:
            raise EconomicEvaluationResultError(
                "market cluster count cannot exceed validation decisions"
            )
        arms.append(
            MappingProxyType(
                {
                    "arm_id": arm_id,
                    "metrics": MappingProxyType(canonical),
                }
            )
        )
    return tuple(arms)


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class EconomicValidationResult:
    """Canonical completed result for the protocol's validation partition."""

    result_id: str
    result_sha256: str
    protocol_id: str
    validation_partition_id: str
    validation_partition_sha256: str
    validation_event_ids: tuple[str, ...]
    arm_metrics: tuple[Mapping[str, object], ...]
    cost_variants: tuple[Mapping[str, object], ...] | None
    registered_statistics: Mapping[str, object] | None

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError(
            "EconomicValidationResult instances must be created by "
            "build_validation_evaluation_result"
        )

    def to_dict(self) -> dict[str, object]:
        extended = self.cost_variants is not None
        payload: dict[str, object] = {
            "schema_version": (
                ECONOMIC_TOURNAMENT_RESULT_SCHEMA
                if extended
                else ECONOMIC_VALIDATION_RESULT_SCHEMA
            ),
            "result_id": self.result_id,
            "result_sha256": self.result_sha256,
            "protocol_id": self.protocol_id,
            "validation_partition_id": self.validation_partition_id,
            "validation_partition_sha256": self.validation_partition_sha256,
            "phase": "validation",
            "status": _RESULT_STATUS,
            "validation_event_ids": list(self.validation_event_ids),
            "arm_metrics": [
                {"arm_id": arm["arm_id"], "metrics": dict(arm["metrics"])}
                for arm in self.arm_metrics
            ],
            **_AUTHORITY_FIELDS,
        }
        if extended:
            assert self.registered_statistics is not None
            payload["cost_variants"] = [
                {
                    "cost_bps_per_side": row["cost_bps_per_side"],
                    "commission_bps_per_side": "0",
                    "half_spread_bps_per_side": row[
                        "half_spread_bps_per_side"
                    ],
                    "slippage_bps_per_side": row[
                        "slippage_bps_per_side"
                    ],
                    "arm_metrics": [
                        {
                            "arm_id": arm["arm_id"],
                            "metrics": dict(arm["metrics"]),
                        }
                        for arm in row["arm_metrics"]
                    ],
                }
                for row in self.cost_variants
            ]
            payload["registered_statistics"] = dict(self.registered_statistics)
        return payload

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class LegacyEconomicValidationResult:
    """Read-only v1 result retained for historical inspection, never admission."""

    result_id: str
    result_sha256: str
    protocol_id: str
    validation_event_ids: tuple[str, ...]
    arm_metrics: tuple[Mapping[str, object], ...]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("LegacyEconomicValidationResult instances are read from v1 bytes")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _LEGACY_ECONOMIC_VALIDATION_RESULT_SCHEMA,
            "result_id": self.result_id,
            "result_sha256": self.result_sha256,
            "protocol_id": self.protocol_id,
            "phase": "validation",
            "status": _RESULT_STATUS,
            "validation_event_ids": list(self.validation_event_ids),
            "arm_metrics": [
                {"arm_id": arm["arm_id"], "metrics": dict(arm["metrics"])}
                for arm in self.arm_metrics
            ],
            **_AUTHORITY_FIELDS,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_RESULT_FIELD_NAMES = tuple(
    field.name for field in dataclasses.fields(EconomicValidationResult)
)
_RESULT_SERIALIZED_FIELDS = frozenset(
    tuple(
        name
        for name in _RESULT_FIELD_NAMES
        if name not in {"cost_variants", "registered_statistics"}
    )
    + (
        "schema_version",
        "phase",
        "status",
    )
    + tuple(_AUTHORITY_FIELDS)
)
_TOURNAMENT_RESULT_SERIALIZED_FIELDS = frozenset(
    _RESULT_SERIALIZED_FIELDS | {"cost_variants", "registered_statistics"}
)
_LEGACY_RESULT_SERIALIZED_FIELDS = frozenset(
    {
        "schema_version",
        "result_id",
        "result_sha256",
        "protocol_id",
        "phase",
        "status",
        "validation_event_ids",
        "arm_metrics",
        *_AUTHORITY_FIELDS,
    }
)


def _new_result(**fields: object) -> EconomicValidationResult:
    result = object.__new__(EconomicValidationResult)
    for field_name in _RESULT_FIELD_NAMES:
        object.__setattr__(result, field_name, fields[field_name])
    return result


def _new_legacy_result(**fields: object) -> LegacyEconomicValidationResult:
    result = object.__new__(LegacyEconomicValidationResult)
    for field_name in dataclasses.fields(LegacyEconomicValidationResult):
        object.__setattr__(result, field_name.name, fields[field_name.name])
    return result


def _result_material(
    *,
    protocol_id: str,
    validation_partition_id: str,
    validation_partition_sha256: str,
    validation_event_ids: tuple[str, ...],
    arm_metrics: tuple[Mapping[str, object], ...],
    cost_variants: tuple[Mapping[str, object], ...] | None = None,
    registered_statistics: Mapping[str, object] | None = None,
    result_id: str | None = None,
    result_sha256: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": (
            ECONOMIC_TOURNAMENT_RESULT_SCHEMA
            if cost_variants is not None
            else ECONOMIC_VALIDATION_RESULT_SCHEMA
        ),
        "protocol_id": protocol_id,
        "validation_partition_id": validation_partition_id,
        "validation_partition_sha256": validation_partition_sha256,
        "phase": "validation",
        "status": _RESULT_STATUS,
        "validation_event_ids": list(validation_event_ids),
        "arm_metrics": [
            {
                "arm_id": arm["arm_id"],
                "metrics": dict(arm["metrics"]),
            }
            for arm in arm_metrics
        ],
        **_AUTHORITY_FIELDS,
    }
    if cost_variants is not None:
        if registered_statistics is None:
            raise EconomicEvaluationResultError(
                "cost variants require registered statistics"
            )
        payload["cost_variants"] = [
            {
                "cost_bps_per_side": row["cost_bps_per_side"],
                "commission_bps_per_side": "0",
                "half_spread_bps_per_side": row["half_spread_bps_per_side"],
                "slippage_bps_per_side": row["slippage_bps_per_side"],
                "arm_metrics": [
                    {"arm_id": arm["arm_id"], "metrics": dict(arm["metrics"])}
                    for arm in row["arm_metrics"]
                ],
            }
            for row in cost_variants
        ]
        payload["registered_statistics"] = dict(registered_statistics)
    if result_id is not None:
        payload["result_id"] = result_id
    if result_sha256 is not None:
        payload["result_sha256"] = result_sha256
    return payload


def _legacy_result_material(
    *,
    protocol_id: str,
    validation_event_ids: tuple[str, ...],
    arm_metrics: tuple[Mapping[str, object], ...],
    result_id: str | None = None,
    result_sha256: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": _LEGACY_ECONOMIC_VALIDATION_RESULT_SCHEMA,
        "protocol_id": protocol_id,
        "phase": "validation",
        "status": _RESULT_STATUS,
        "validation_event_ids": list(validation_event_ids),
        "arm_metrics": [
            {"arm_id": arm["arm_id"], "metrics": dict(arm["metrics"])}
            for arm in arm_metrics
        ],
        **_AUTHORITY_FIELDS,
    }
    if result_id is not None:
        payload["result_id"] = result_id
    if result_sha256 is not None:
        payload["result_sha256"] = result_sha256
    return payload


def build_validation_evaluation_result(
    protocol: FrozenEvaluationProtocol,
    *,
    arm_metrics: Mapping[str, Mapping[str, str]],
    eligibility: ValidationPhaseEligibility,
    cost_variant_metrics: Mapping[str, Mapping[str, Mapping[str, str]]] | None = None,
    registered_statistics: EconomicTournamentStatistics | None = None,
) -> EconomicValidationResult:
    """Build a complete result for the canonical, purged validation phase."""

    if type(protocol) is not FrozenEvaluationProtocol:
        raise EconomicEvaluationResultError(
            "protocol must be an exact FrozenEvaluationProtocol"
        )
    try:
        validated = validate_frozen_evaluation_protocol(protocol.to_dict())
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationResultError("protocol canonical validation failed") from exc
    if validated.canonical_json_bytes() != protocol.canonical_json_bytes():
        raise EconomicEvaluationResultError("protocol bytes do not round trip exactly")
    try:
        bound = validate_validation_phase_eligibility(
            protocol=validated,
            eligibility=eligibility,
        )
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationResultError(
            "validation eligibility canonical validation failed"
        ) from exc
    metrics = _canonical_arm_metrics(
        arm_metrics,
        validation_event_count=len(bound.event_ids),
    )
    variants = None
    statistics = None
    if cost_variant_metrics is not None or registered_statistics is not None:
        if cost_variant_metrics is None or type(registered_statistics) is not EconomicTournamentStatistics:
            raise EconomicEvaluationResultError(
                "extended tournament results require cost variants and exact statistics"
            )
        variants = _canonical_cost_variants(
            cost_variant_metrics,
            validation_event_count=len(bound.event_ids),
        )
        statistics = validate_economic_tournament_statistics(
            registered_statistics.to_dict()
        ).to_dict()
    return _build_result_from_components(
        protocol_id=validated.protocol_id,
        validation_partition_id=bound.partition_id,
        validation_partition_sha256=bound.partition_sha256,
        validation_event_ids=bound.event_ids,
        arm_metrics=metrics,
        cost_variants=variants,
        registered_statistics=statistics,
    )


def _build_result_from_components(
    *,
    protocol_id: str,
    validation_partition_id: str,
    validation_partition_sha256: str,
    validation_event_ids: tuple[str, ...],
    arm_metrics: tuple[Mapping[str, object], ...],
    cost_variants: tuple[Mapping[str, object], ...] | None = None,
    registered_statistics: Mapping[str, object] | None = None,
) -> EconomicValidationResult:
    material = _result_material(
        protocol_id=protocol_id,
        validation_partition_id=validation_partition_id,
        validation_partition_sha256=validation_partition_sha256,
        validation_event_ids=validation_event_ids,
        arm_metrics=arm_metrics,
        cost_variants=cost_variants,
        registered_statistics=registered_statistics,
    )
    result_id = "economic-evaluation-result-" + _sha256(material)
    digest_material = _result_material(
        protocol_id=protocol_id,
        validation_partition_id=validation_partition_id,
        validation_partition_sha256=validation_partition_sha256,
        validation_event_ids=validation_event_ids,
        arm_metrics=arm_metrics,
        cost_variants=cost_variants,
        registered_statistics=registered_statistics,
        result_id=result_id,
    )
    return _new_result(
        result_id=result_id,
        result_sha256=_sha256(digest_material),
        protocol_id=protocol_id,
        validation_partition_id=validation_partition_id,
        validation_partition_sha256=validation_partition_sha256,
        validation_event_ids=validation_event_ids,
        arm_metrics=arm_metrics,
        cost_variants=cost_variants,
        registered_statistics=registered_statistics,
    )


def _build_legacy_result_from_components(
    *,
    protocol_id: str,
    validation_event_ids: tuple[str, ...],
    arm_metrics: tuple[Mapping[str, object], ...],
) -> LegacyEconomicValidationResult:
    material = _legacy_result_material(
        protocol_id=protocol_id,
        validation_event_ids=validation_event_ids,
        arm_metrics=arm_metrics,
    )
    result_id = "economic-evaluation-result-" + _sha256(material)
    digest_material = _legacy_result_material(
        protocol_id=protocol_id,
        validation_event_ids=validation_event_ids,
        arm_metrics=arm_metrics,
        result_id=result_id,
    )
    return _new_legacy_result(
        result_id=result_id,
        result_sha256=_sha256(digest_material),
        protocol_id=protocol_id,
        validation_event_ids=validation_event_ids,
        arm_metrics=arm_metrics,
    )


def _validated_result_identity(values: Mapping[str, object]) -> tuple[str, tuple[str, ...]]:
    if (
        type(values["result_id"]) is not str
        or not values["result_id"].startswith("economic-evaluation-result-")
        or _SHA256.fullmatch(
            values["result_id"].removeprefix("economic-evaluation-result-")
        )
        is None
    ):
        raise EconomicEvaluationResultError("validation result identity is invalid")
    if _SHA256.fullmatch(values["result_sha256"]) is None:
        raise EconomicEvaluationResultError("validation result digest is invalid")
    if (
        type(values["protocol_id"]) is not str
        or not values["protocol_id"].startswith("economic-evaluation-protocol-")
    ):
        raise EconomicEvaluationResultError("validation result protocol identity is invalid")
    raw_ids = values["validation_event_ids"]
    if type(raw_ids) is not list or not raw_ids or any(type(item) is not str for item in raw_ids):
        raise EconomicEvaluationResultError("validation event identifiers are invalid")
    event_ids = tuple(raw_ids)
    if event_ids != tuple(sorted(event_ids)) or len(set(event_ids)) != len(event_ids):
        raise EconomicEvaluationResultError("validation event identifiers are not canonical")
    return values["protocol_id"], event_ids  # type: ignore[return-value]


def _validated_result_metrics(
    values: Mapping[str, object],
    *,
    event_count: int,
    legacy: bool = False,
) -> tuple[dict[str, object], ...]:
    raw_arms = values["arm_metrics"]
    if type(raw_arms) is not list or len(raw_arms) != len(CONTROL_ARM_IDS):
        raise EconomicEvaluationResultError("validation arm metrics are invalid")
    arm_input: dict[str, Mapping[str, str]] = {}
    for raw_arm in raw_arms:
        arm = _exact_fields(raw_arm, frozenset({"arm_id", "metrics"}), label="arm result")
        if type(arm["arm_id"]) is not str or arm["arm_id"] in arm_input:
            raise EconomicEvaluationResultError("validation arm identity is invalid")
        if not isinstance(arm["metrics"], Mapping):
            raise EconomicEvaluationResultError("validation arm metrics are invalid")
        arm_input[arm["arm_id"]] = arm["metrics"]
    builder = _legacy_canonical_arm_metrics if legacy else _canonical_arm_metrics
    return builder(arm_input, validation_event_count=event_count)


def _validated_cost_variants(
    value: object,
    *,
    event_count: int,
) -> tuple[Mapping[str, object], ...]:
    if type(value) is not list or len(value) != len(_COST_VARIANT_BPS):
        raise EconomicEvaluationResultError("validation cost variants are invalid")
    variants: dict[str, Mapping[str, Mapping[str, str]]] = {}
    expected = frozenset(
        {
            "cost_bps_per_side",
            "commission_bps_per_side",
            "half_spread_bps_per_side",
            "slippage_bps_per_side",
            "arm_metrics",
        }
    )
    for raw_variant in value:
        variant = _exact_fields(raw_variant, expected, label="cost variant")
        cost = variant["cost_bps_per_side"]
        if type(cost) is not str or cost in variants:
            raise EconomicEvaluationResultError("cost variant identity is invalid")
        if (
            variant["commission_bps_per_side"] != "0"
            or variant["half_spread_bps_per_side"] != _canonical_decimal_half(cost)
            or variant["slippage_bps_per_side"] != _canonical_decimal_half(cost)
        ):
            raise EconomicEvaluationResultError("cost variant components are invalid")
        raw_arms = variant["arm_metrics"]
        if type(raw_arms) is not list:
            raise EconomicEvaluationResultError("cost variant arm metrics are invalid")
        arm_map: dict[str, Mapping[str, str]] = {}
        for raw_arm in raw_arms:
            arm = _exact_fields(
                raw_arm,
                frozenset({"arm_id", "metrics"}),
                label="cost variant arm",
            )
            if type(arm["arm_id"]) is not str or not isinstance(arm["metrics"], Mapping):
                raise EconomicEvaluationResultError("cost variant arm is invalid")
            arm_map[arm["arm_id"]] = arm["metrics"]  # type: ignore[assignment]
        variants[cost] = arm_map
    return _canonical_cost_variants(
        variants,
        validation_event_count=event_count,
    )


def _validate_legacy_economic_validation_result(
    value: object,
) -> LegacyEconomicValidationResult:
    values = _exact_fields(value, _LEGACY_RESULT_SERIALIZED_FIELDS, label="legacy validation result")
    if values["schema_version"] != _LEGACY_ECONOMIC_VALIDATION_RESULT_SCHEMA:
        raise EconomicEvaluationResultError("legacy validation result schema is invalid")
    if values["phase"] != "validation" or values["status"] != _RESULT_STATUS:
        raise EconomicEvaluationResultError("legacy validation result must be completed validation")
    _require_authority(values, label="legacy validation result")
    protocol_id, event_ids = _validated_result_identity(values)
    metrics = _validated_result_metrics(
        values,
        event_count=len(event_ids),
        legacy=True,
    )
    rebuilt = _build_legacy_result_from_components(
        protocol_id=protocol_id,
        validation_event_ids=event_ids,
        arm_metrics=metrics,
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(values):
        raise EconomicEvaluationResultError(
            "legacy validation result bytes do not match canonical rebuild"
        )
    return rebuilt


def validate_economic_validation_result(
    value: object,
) -> EconomicValidationResult | LegacyEconomicValidationResult:
    """Validate result bytes by rebuilding its exact arm and metric material."""

    if not isinstance(value, Mapping):
        raise EconomicEvaluationResultError("validation result must be a JSON object")
    if value.get("schema_version") == _LEGACY_ECONOMIC_VALIDATION_RESULT_SCHEMA:
        return _validate_legacy_economic_validation_result(value)
    extended = value.get("schema_version") == ECONOMIC_TOURNAMENT_RESULT_SCHEMA
    expected_fields = (
        _TOURNAMENT_RESULT_SERIALIZED_FIELDS
        if extended
        else _RESULT_SERIALIZED_FIELDS
    )
    values = _exact_fields(value, expected_fields, label="validation result")
    if values["schema_version"] not in {
        ECONOMIC_VALIDATION_RESULT_SCHEMA,
        ECONOMIC_TOURNAMENT_RESULT_SCHEMA,
    }:
        raise EconomicEvaluationResultError("validation result schema is invalid")
    if values["phase"] != "validation" or values["status"] != _RESULT_STATUS:
        raise EconomicEvaluationResultError("validation result must be completed validation")
    _require_authority(values, label="validation result")
    protocol_id, event_ids = _validated_result_identity(values)
    if (
        type(values["validation_partition_id"]) is not str
        or not values["validation_partition_id"].startswith("market-date-partitions-")
        or _SHA256.fullmatch(
            values["validation_partition_id"].removeprefix("market-date-partitions-")
        )
        is None
    ):
        raise EconomicEvaluationResultError("validation partition identity is invalid")
    if _SHA256.fullmatch(values["validation_partition_sha256"]) is None:
        raise EconomicEvaluationResultError("validation partition digest is invalid")
    rebuilt_metrics = _validated_result_metrics(values, event_count=len(event_ids))
    variants = None
    statistics = None
    if extended:
        variants = _validated_cost_variants(
            values["cost_variants"],
            event_count=len(event_ids),
        )
        statistics = validate_economic_tournament_statistics(
            values["registered_statistics"]
        ).to_dict()
    rebuilt = _build_result_from_components(
        protocol_id=protocol_id,
        validation_partition_id=values["validation_partition_id"],  # type: ignore[arg-type]
        validation_partition_sha256=values["validation_partition_sha256"],  # type: ignore[arg-type]
        validation_event_ids=event_ids,
        arm_metrics=rebuilt_metrics,
        cost_variants=variants,
        registered_statistics=statistics,
    )
    submitted = _canonical_json_bytes(values)
    if rebuilt.canonical_json_bytes() != submitted:
        raise EconomicEvaluationResultError(
            "validation result bytes do not match canonical rebuild"
        )
    return rebuilt
