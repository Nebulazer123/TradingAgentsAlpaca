"""Strict data models for inert strategy genomes and evolution policy."""

from __future__ import annotations

import enum
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

STRATEGY_GENOME_SCHEMA_VERSION = 1
STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION = 1

_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_PARENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _canonical_decimal(
    value: object,
    *,
    field_name: str,
    minimum: Decimal,
    maximum: Decimal,
    positive: bool = False,
) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a decimal string")
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must use canonical decimal syntax")
    decimal_value = Decimal(value)
    if decimal_value == 0 and value.startswith("-"):
        raise ValueError(f"{field_name} cannot use negative zero")
    if positive and decimal_value <= 0:
        raise ValueError(f"{field_name} must be positive")
    if decimal_value < minimum or decimal_value > maximum:
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    canonical = format(decimal_value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical == "-0":
        canonical = "0"
    return canonical


def _bounded_integer(
    value: object, *, field_name: str, minimum: int, maximum: int
) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _require_exact_fields(
    payload: object, expected: set[str], *, field_name: str
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError(f"{field_name} must be an object")
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{field_name} fields do not match; missing={missing}, extra={extra}"
        )
    return payload


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class StrategyFamily(str, enum.Enum):
    HOLD_CASH = "hold-cash"
    CURRENT_AGGRESSIVE = "current-aggressive"
    PULLBACK_SUPPORT = "pullback-support"
    CATALYST_RELATIVE_STRENGTH = "catalyst-relative-strength"


@dataclass(frozen=True, slots=True)
class HoldCashParameters:
    def to_dict(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True, slots=True)
class CurrentAggressiveParameters:
    min_score: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_score",
            _canonical_decimal(
                self.min_score,
                field_name="min_score",
                minimum=Decimal("0.50"),
                maximum=Decimal("1.00"),
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {"min_score": self.min_score}


@dataclass(frozen=True, slots=True)
class PullbackSupportParameters:
    min_daily_change_fraction: str
    max_daily_change_fraction: str
    max_volume_ratio: str

    def __post_init__(self) -> None:
        minimum = _canonical_decimal(
            self.min_daily_change_fraction,
            field_name="min_daily_change_fraction",
            minimum=Decimal("-0.20"),
            maximum=Decimal("0"),
        )
        maximum = _canonical_decimal(
            self.max_daily_change_fraction,
            field_name="max_daily_change_fraction",
            minimum=Decimal("-0.20"),
            maximum=Decimal("0.05"),
        )
        volume = _canonical_decimal(
            self.max_volume_ratio,
            field_name="max_volume_ratio",
            minimum=Decimal("0.10"),
            maximum=Decimal("10"),
        )
        if Decimal(minimum) > Decimal(maximum):
            raise ValueError(
                "min_daily_change_fraction minimum cannot exceed maximum"
            )
        object.__setattr__(self, "min_daily_change_fraction", minimum)
        object.__setattr__(self, "max_daily_change_fraction", maximum)
        object.__setattr__(self, "max_volume_ratio", volume)

    def to_dict(self) -> dict[str, str]:
        return {
            "min_daily_change_fraction": self.min_daily_change_fraction,
            "max_daily_change_fraction": self.max_daily_change_fraction,
            "max_volume_ratio": self.max_volume_ratio,
        }


@dataclass(frozen=True, slots=True)
class CatalystRelativeStrengthParameters:
    min_score: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_score",
            _canonical_decimal(
                self.min_score,
                field_name="min_score",
                minimum=Decimal("0.50"),
                maximum=Decimal("1.00"),
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {"min_score": self.min_score}


StrategyParameters = (
    HoldCashParameters
    | CurrentAggressiveParameters
    | PullbackSupportParameters
    | CatalystRelativeStrengthParameters
)

_PARAMETER_TYPES: dict[StrategyFamily, type[StrategyParameters]] = {
    StrategyFamily.HOLD_CASH: HoldCashParameters,
    StrategyFamily.CURRENT_AGGRESSIVE: CurrentAggressiveParameters,
    StrategyFamily.PULLBACK_SUPPORT: PullbackSupportParameters,
    StrategyFamily.CATALYST_RELATIVE_STRENGTH: CatalystRelativeStrengthParameters,
}


def _coerce_family(value: StrategyFamily | str) -> StrategyFamily:
    if type(value) is StrategyFamily:
        return value
    if type(value) is str:
        try:
            return StrategyFamily(value)
        except ValueError as exc:
            raise ValueError(f"unknown strategy family: {value}") from exc
    raise TypeError("family must be a StrategyFamily or exact string")


def _parameters_from_dict(
    family: StrategyFamily, payload: object
) -> StrategyParameters:
    if family is StrategyFamily.HOLD_CASH:
        _require_exact_fields(payload, set(), field_name="parameters")
        return HoldCashParameters()
    if family is StrategyFamily.CURRENT_AGGRESSIVE:
        values = _require_exact_fields(
            payload, {"min_score"}, field_name="parameters"
        )
        return CurrentAggressiveParameters(min_score=values["min_score"])
    if family is StrategyFamily.PULLBACK_SUPPORT:
        values = _require_exact_fields(
            payload,
            {
                "min_daily_change_fraction",
                "max_daily_change_fraction",
                "max_volume_ratio",
            },
            field_name="parameters",
        )
        return PullbackSupportParameters(
            min_daily_change_fraction=values["min_daily_change_fraction"],
            max_daily_change_fraction=values["max_daily_change_fraction"],
            max_volume_ratio=values["max_volume_ratio"],
        )
    values = _require_exact_fields(
        payload, {"min_score"}, field_name="parameters"
    )
    return CatalystRelativeStrengthParameters(min_score=values["min_score"])


@dataclass(frozen=True, slots=True)
class StrategyGenome:
    family: StrategyFamily
    parameters: StrategyParameters
    generation: int
    parent_id: str
    schema_version: int = field(
        init=False, default=STRATEGY_GENOME_SCHEMA_VERSION
    )
    genome_id: str = field(init=False)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if type(self.family) is not StrategyFamily:
            raise TypeError("family must be a StrategyFamily")
        expected_type = _PARAMETER_TYPES[self.family]
        if type(self.parameters) is not expected_type:
            raise TypeError(
                f"{self.family.value} requires {expected_type.__name__}"
            )
        _bounded_integer(
            self.generation,
            field_name="generation",
            minimum=0,
            maximum=1_000_000,
        )
        if type(self.parent_id) is not str:
            raise TypeError("parent_id must be a string")
        if _PARENT_ID_PATTERN.fullmatch(self.parent_id) is None:
            raise ValueError("parent_id must be a safe lineage token")
        if self.schema_version != STRATEGY_GENOME_SCHEMA_VERSION:
            raise ValueError("schema_version is fixed")
        if self.analysis_only is not True:
            raise ValueError("analysis_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("can_submit_orders is fixed")
        digest = hashlib.sha256(self.identity_json_bytes()).hexdigest()
        object.__setattr__(
            self,
            "genome_id",
            f"genome-{self.family.value}-{digest}",
        )

    @classmethod
    def create(
        cls,
        *,
        family: StrategyFamily | str,
        parameters: StrategyParameters,
        generation: int,
        parent_id: str,
    ) -> StrategyGenome:
        return cls(
            family=_coerce_family(family),
            parameters=parameters,
            generation=generation,
            parent_id=parent_id,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StrategyGenome:
        values = _require_exact_fields(
            payload,
            {
                "schema_version",
                "family",
                "parameters",
                "generation",
                "parent_id",
                "genome_id",
                "analysis_only",
                "execution_authority",
                "can_submit_orders",
            },
            field_name="genome",
        )
        if (
            type(values["schema_version"]) is not int
            or values["schema_version"] != STRATEGY_GENOME_SCHEMA_VERSION
        ):
            raise ValueError("schema_version does not match")
        if values["analysis_only"] is not True:
            raise ValueError("analysis_only must be true")
        if values["execution_authority"] != "none":
            raise ValueError("execution_authority must be none")
        if values["can_submit_orders"] is not False:
            raise ValueError("can_submit_orders must be false")
        family = _coerce_family(values["family"])
        genome = cls.create(
            family=family,
            parameters=_parameters_from_dict(family, values["parameters"]),
            generation=values["generation"],
            parent_id=values["parent_id"],
        )
        if (
            type(values["genome_id"]) is not str
            or values["genome_id"] != genome.genome_id
        ):
            raise ValueError("genome_id does not match computed identity")
        return genome

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "family": self.family.value,
            "parameters": self.parameters.to_dict(),
            "generation": self.generation,
            "parent_id": self.parent_id,
            "genome_id": self.genome_id,
            "analysis_only": self.analysis_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def identity_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            {
                "schema_version": self.schema_version,
                "family": self.family.value,
                "parameters": self.parameters.to_dict(),
            }
        )

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class CurrentAggressiveMutationBounds:
    min_score: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_score",
            _canonical_decimal(
                self.min_score,
                field_name="current-aggressive.min_score",
                minimum=Decimal("0"),
                maximum=Decimal("0.50"),
                positive=True,
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {"min_score": self.min_score}

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class PullbackSupportMutationBounds:
    min_daily_change_fraction: str
    max_daily_change_fraction: str
    max_volume_ratio: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_daily_change_fraction",
            _canonical_decimal(
                self.min_daily_change_fraction,
                field_name="pullback-support.min_daily_change_fraction",
                minimum=Decimal("0"),
                maximum=Decimal("0.20"),
                positive=True,
            ),
        )
        object.__setattr__(
            self,
            "max_daily_change_fraction",
            _canonical_decimal(
                self.max_daily_change_fraction,
                field_name="pullback-support.max_daily_change_fraction",
                minimum=Decimal("0"),
                maximum=Decimal("0.25"),
                positive=True,
            ),
        )
        object.__setattr__(
            self,
            "max_volume_ratio",
            _canonical_decimal(
                self.max_volume_ratio,
                field_name="pullback-support.max_volume_ratio",
                minimum=Decimal("0"),
                maximum=Decimal("9.90"),
                positive=True,
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "min_daily_change_fraction": self.min_daily_change_fraction,
            "max_daily_change_fraction": self.max_daily_change_fraction,
            "max_volume_ratio": self.max_volume_ratio,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class CatalystRelativeStrengthMutationBounds:
    min_score: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_score",
            _canonical_decimal(
                self.min_score,
                field_name="catalyst-relative-strength.min_score",
                minimum=Decimal("0"),
                maximum=Decimal("0.50"),
                positive=True,
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {"min_score": self.min_score}

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class StrategyMutationBounds:
    current_aggressive: CurrentAggressiveMutationBounds
    pullback_support: PullbackSupportMutationBounds
    catalyst_relative_strength: CatalystRelativeStrengthMutationBounds

    def __post_init__(self) -> None:
        if type(self.current_aggressive) is not CurrentAggressiveMutationBounds:
            raise TypeError("current_aggressive bounds type does not match")
        if type(self.pullback_support) is not PullbackSupportMutationBounds:
            raise TypeError("pullback_support bounds type does not match")
        if (
            type(self.catalyst_relative_strength)
            is not CatalystRelativeStrengthMutationBounds
        ):
            raise TypeError(
                "catalyst_relative_strength bounds type does not match"
            )

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            StrategyFamily.CURRENT_AGGRESSIVE.value: (
                self.current_aggressive.to_dict()
            ),
            StrategyFamily.PULLBACK_SUPPORT.value: (
                self.pullback_support.to_dict()
            ),
            StrategyFamily.CATALYST_RELATIVE_STRENGTH.value: (
                self.catalyst_relative_strength.to_dict()
            ),
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class StrategyEvolutionPolicy:
    enabled: bool
    experiment_starting_cash_usd: str
    candidate_min_order_usd: str
    max_active_candidates: int
    mutations_per_cycle: int
    minimum_tracked_days: int
    minimum_closed_trades: int
    minimum_walk_forward_windows: int
    maximum_paper_drawdown_pct: str
    mutation_bounds: StrategyMutationBounds
    schema_version: int = field(
        init=False, default=STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION
    )
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        starting_cash = _canonical_decimal(
            self.experiment_starting_cash_usd,
            field_name="experiment_starting_cash_usd",
            minimum=Decimal("1"),
            maximum=Decimal("1000000"),
        )
        minimum_order = _canonical_decimal(
            self.candidate_min_order_usd,
            field_name="candidate_min_order_usd",
            minimum=Decimal("0"),
            maximum=Decimal("1000000"),
            positive=True,
        )
        if Decimal(minimum_order) > Decimal(starting_cash):
            raise ValueError(
                "candidate_min_order_usd cannot exceed experiment starting cash"
            )
        max_candidates = _bounded_integer(
            self.max_active_candidates,
            field_name="max_active_candidates",
            minimum=1,
            maximum=64,
        )
        mutations = _bounded_integer(
            self.mutations_per_cycle,
            field_name="mutations_per_cycle",
            minimum=1,
            maximum=64,
        )
        if mutations > max_candidates:
            raise ValueError(
                "mutations_per_cycle cannot exceed max_active_candidates"
            )
        _bounded_integer(
            self.minimum_tracked_days,
            field_name="minimum_tracked_days",
            minimum=1,
            maximum=3650,
        )
        _bounded_integer(
            self.minimum_closed_trades,
            field_name="minimum_closed_trades",
            minimum=1,
            maximum=1_000_000,
        )
        _bounded_integer(
            self.minimum_walk_forward_windows,
            field_name="minimum_walk_forward_windows",
            minimum=1,
            maximum=10_000,
        )
        drawdown = _canonical_decimal(
            self.maximum_paper_drawdown_pct,
            field_name="maximum_paper_drawdown_pct",
            minimum=Decimal("-100"),
            maximum=Decimal("0"),
        )
        if type(self.mutation_bounds) is not StrategyMutationBounds:
            raise TypeError("mutation_bounds must be StrategyMutationBounds")
        if self.schema_version != STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION:
            raise ValueError("schema_version is fixed")
        if self.analysis_only is not True:
            raise ValueError("analysis_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("can_submit_orders is fixed")
        object.__setattr__(
            self, "experiment_starting_cash_usd", starting_cash
        )
        object.__setattr__(self, "candidate_min_order_usd", minimum_order)
        object.__setattr__(self, "maximum_paper_drawdown_pct", drawdown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "enabled": self.enabled,
            "experiment_starting_cash_usd": self.experiment_starting_cash_usd,
            "candidate_min_order_usd": self.candidate_min_order_usd,
            "max_active_candidates": self.max_active_candidates,
            "mutations_per_cycle": self.mutations_per_cycle,
            "minimum_tracked_days": self.minimum_tracked_days,
            "minimum_closed_trades": self.minimum_closed_trades,
            "minimum_walk_forward_windows": (
                self.minimum_walk_forward_windows
            ),
            "maximum_paper_drawdown_pct": self.maximum_paper_drawdown_pct,
            "mutation_bounds": self.mutation_bounds.to_dict(),
            "analysis_only": self.analysis_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _mutation_bounds_from_dict(payload: object) -> StrategyMutationBounds:
    values = _require_exact_fields(
        payload,
        {
            StrategyFamily.CURRENT_AGGRESSIVE.value,
            StrategyFamily.PULLBACK_SUPPORT.value,
            StrategyFamily.CATALYST_RELATIVE_STRENGTH.value,
        },
        field_name="mutation_bounds",
    )
    aggressive = _require_exact_fields(
        values[StrategyFamily.CURRENT_AGGRESSIVE.value],
        {"min_score"},
        field_name="mutation_bounds.current-aggressive",
    )
    pullback = _require_exact_fields(
        values[StrategyFamily.PULLBACK_SUPPORT.value],
        {
            "min_daily_change_fraction",
            "max_daily_change_fraction",
            "max_volume_ratio",
        },
        field_name="mutation_bounds.pullback-support",
    )
    catalyst = _require_exact_fields(
        values[StrategyFamily.CATALYST_RELATIVE_STRENGTH.value],
        {"min_score"},
        field_name="mutation_bounds.catalyst-relative-strength",
    )
    return StrategyMutationBounds(
        current_aggressive=CurrentAggressiveMutationBounds(
            min_score=aggressive["min_score"]
        ),
        pullback_support=PullbackSupportMutationBounds(
            min_daily_change_fraction=pullback[
                "min_daily_change_fraction"
            ],
            max_daily_change_fraction=pullback[
                "max_daily_change_fraction"
            ],
            max_volume_ratio=pullback["max_volume_ratio"],
        ),
        catalyst_relative_strength=CatalystRelativeStrengthMutationBounds(
            min_score=catalyst["min_score"]
        ),
    )


def load_strategy_evolution_policy(
    path: str | Path,
) -> StrategyEvolutionPolicy:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_strict_json_object,
    )
    values = _require_exact_fields(
        payload,
        {
            "schema_version",
            "enabled",
            "experiment_starting_cash_usd",
            "candidate_min_order_usd",
            "max_active_candidates",
            "mutations_per_cycle",
            "minimum_tracked_days",
            "minimum_closed_trades",
            "minimum_walk_forward_windows",
            "maximum_paper_drawdown_pct",
            "mutation_bounds",
            "analysis_only",
            "execution_authority",
            "can_submit_orders",
        },
        field_name="strategy evolution policy",
    )
    if (
        type(values["schema_version"]) is not int
        or values["schema_version"]
        != STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION
    ):
        raise ValueError("schema_version does not match")
    if values["analysis_only"] is not True:
        raise ValueError("analysis_only must be true")
    if values["execution_authority"] != "none":
        raise ValueError("execution_authority must be none")
    if values["can_submit_orders"] is not False:
        raise ValueError("can_submit_orders must be false")
    return StrategyEvolutionPolicy(
        enabled=values["enabled"],
        experiment_starting_cash_usd=values[
            "experiment_starting_cash_usd"
        ],
        candidate_min_order_usd=values["candidate_min_order_usd"],
        max_active_candidates=values["max_active_candidates"],
        mutations_per_cycle=values["mutations_per_cycle"],
        minimum_tracked_days=values["minimum_tracked_days"],
        minimum_closed_trades=values["minimum_closed_trades"],
        minimum_walk_forward_windows=values[
            "minimum_walk_forward_windows"
        ],
        maximum_paper_drawdown_pct=values[
            "maximum_paper_drawdown_pct"
        ],
        mutation_bounds=_mutation_bounds_from_dict(
            values["mutation_bounds"]
        ),
    )
