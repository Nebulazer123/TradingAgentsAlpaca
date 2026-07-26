"""Immutable, paper-only multi-window strategy promotion evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from pathlib import Path

from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
)
from tradingagents.strategy.evaluator import (
    EVALUATOR_DECIMAL_PRECISION,
    EVALUATOR_MAX_CLOSED_TRADE_OPPORTUNITIES,
    EVALUATOR_VERSION,
    STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION,
    EvaluationFrame,
    GenomeWindowResult,
    StrategyEvaluationPolicy,
    evaluate_genome_window,
    evaluation_frames_from_dict,
    evaluation_frames_sha256,
)
from tradingagents.strategy.genome import (
    STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION,
    CatalystRelativeStrengthMutationBounds,
    CurrentAggressiveMutationBounds,
    PullbackSupportMutationBounds,
    StrategyEvolutionPolicy,
    StrategyGenome,
    StrategyMutationBounds,
)

EVALUATION_WINDOW_SPEC_SCHEMA_VERSION = 1
EVALUATION_SOURCE_MANIFEST_SCHEMA_VERSION = 1
STRATEGY_EVALUATION_REGISTRATION_SCHEMA_VERSION = 1
ADMITTED_GENOME_WINDOW_SCHEMA_VERSION = 1
STRATEGY_PROMOTION_EVIDENCE_SCHEMA_VERSION = 1

EVALUATION_SOURCE_PATHS = (
    "tradingagents/strategy/compiler.py",
    "tradingagents/strategy/evaluator.py",
    "tradingagents/strategy/genome.py",
    "config/strategy_evolution.json",
    "config/strategy_evaluation.json",
)
_CALCULATION_MODULE_PATHS = (
    (
        "tradingagents.strategy.compiler",
        "tradingagents/strategy/compiler.py",
    ),
    (
        "tradingagents.strategy.evaluator",
        "tradingagents/strategy/evaluator.py",
    ),
    (
        "tradingagents.strategy.genome",
        "tradingagents/strategy/genome.py",
    ),
)

_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOWER_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_UTC = dt.timezone.utc
# All provenance Git reads are local and must fail closed instead of freezing.
_LOCAL_GIT_TIMEOUT_SECONDS = 10
_PROMOTION_DECIMAL_MAX_SIGNIFICANT_DIGITS = EVALUATOR_DECIMAL_PRECISION
_PROMOTION_DECIMAL_MAX_ADJUSTED_EXPONENT = 995
# Task 6B's Emin -999 and precision 50 allow exact subnormals through -1048.
_PROMOTION_DECIMAL_MIN_EXPONENT = -1048
# Sign, "0.", and the finest accepted fixed-point value fit within this bound.
_PROMOTION_DECIMAL_MAX_TEXT_LENGTH = 1051


class StrategyPromotionEvidenceError(ValueError):
    """Base failure for immutable strategy promotion evidence."""


@dataclass(frozen=True, slots=True)
class _LoadedCalculationSource:
    module_name: str
    relative_path: str
    canonical_path: Path
    sha256: str


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _require_exact_fields(
    payload: object,
    fields: frozenset[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise TypeError(f"{label} must be an object")
    keys = tuple(payload)
    if not all(type(key) is str for key in keys):
        raise TypeError(f"{label} field names must be strings")
    if set(keys) != set(fields):
        raise ValueError(f"{label} fields do not match schema")
    return payload


def _require_digest(value: object, *, label: str) -> str:
    if type(value) is not str or _LOWER_SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full lowercase SHA-256")
    return value


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _new_decimal_context() -> Context:
    return Context(
        prec=EVALUATOR_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
        Emin=-999,
        Emax=999,
        capitals=1,
        clamp=0,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _require_object_id(value: object, *, kind: str, label: str) -> str:
    if type(value) is not str or re.fullmatch(rf"{re.escape(kind)}-[0-9a-f]{{64}}", value) is None:
        raise ValueError(f"{label} must be a full {kind} object ID")
    return value


def _expected_object_id(
    *,
    kind: str,
    effective_at: str,
    payload: Mapping[str, object],
) -> str:
    digest = _sha256(
        _canonical_json_bytes(
            {
                "kind": kind,
                "effective_at": effective_at,
                "payload": payload,
            }
        )
    )
    return f"{kind}-{digest}"


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("canonical decimal must be finite")
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _require_decimal_text(value: object, *, label: str) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{label} must be canonical decimal text")
    if len(value) > _PROMOTION_DECIMAL_MAX_TEXT_LENGTH:
        raise ValueError(f"{label} must be canonical decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be canonical decimal text") from exc
    if not parsed.is_finite():
        raise ValueError(f"{label} must be canonical decimal text")
    decimal_tuple = parsed.as_tuple()
    exponent = decimal_tuple.exponent
    if type(exponent) is not int:
        raise ValueError(f"{label} must be canonical decimal text")
    significant_digits = len(decimal_tuple.digits)
    while (
        significant_digits > 1
        and decimal_tuple.digits[significant_digits - 1] == 0
    ):
        significant_digits -= 1
    if (
        significant_digits > _PROMOTION_DECIMAL_MAX_SIGNIFICANT_DIGITS
        or parsed.adjusted() > _PROMOTION_DECIMAL_MAX_ADJUSTED_EXPONENT
        or exponent < _PROMOTION_DECIMAL_MIN_EXPONENT
    ):
        raise ValueError(f"{label} must be canonical decimal text")
    canonical = _decimal_text(parsed)
    if (
        len(canonical) > _PROMOTION_DECIMAL_MAX_TEXT_LENGTH
        or canonical != value
    ):
        raise ValueError(f"{label} must be canonical decimal text")
    return parsed


def _require_canonical_utc(value: object, *, label: str) -> dt.datetime:
    if type(value) is not str:
        raise TypeError(f"{label} must be canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be canonical UTC seconds") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be canonical UTC seconds")
    normalized = parsed.astimezone(_UTC)
    if normalized.microsecond != 0 or normalized.isoformat(timespec="seconds") != value:
        raise ValueError(f"{label} must be canonical UTC seconds")
    return normalized


def _require_evaluator_utc(value: object, *, label: str) -> dt.datetime:
    if type(value) is not str:
        raise TypeError(f"{label} must be canonical evaluator UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be canonical evaluator UTC seconds") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be canonical evaluator UTC seconds")
    normalized = parsed.astimezone(_UTC)
    canonical = normalized.isoformat(timespec="seconds").replace("+00:00", "Z")
    if normalized.microsecond != 0 or canonical != value:
        raise ValueError(f"{label} must be canonical evaluator UTC seconds")
    return normalized


def _store_text_for_evaluator_time(value: str, *, label: str) -> str:
    return _require_evaluator_utc(value, label=label).isoformat(timespec="seconds")


def _datetime_text(value: object, *, label: str) -> str:
    if not isinstance(value, dt.datetime):
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    normalized = value.astimezone(_UTC)
    if normalized.microsecond != 0:
        raise ValueError(f"{label} must use whole seconds")
    return normalized.isoformat(timespec="seconds")


def _require_date(value: object, *, label: str) -> dt.date:
    if type(value) is not str:
        raise TypeError(f"{label} must be an ISO date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be an ISO date")
    return parsed


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_authority(payload: Mapping[str, object], *, label: str) -> None:
    if payload["analysis_only"] is not True:
        raise ValueError(f"{label} analysis_only must be true")
    if payload["execution_authority"] != "none":
        raise ValueError(f"{label} execution_authority must be none")
    if payload["can_submit_orders"] is not False:
        raise ValueError(f"{label} can_submit_orders must be false")


def _require_schema(value: object, expected: int, *, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ValueError(f"{label} schema_version does not match")


@dataclass(frozen=True, slots=True)
class EvaluationSourceFile:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if type(self.path) is not str or self.path not in EVALUATION_SOURCE_PATHS:
            raise ValueError("source path is not in the frozen manifest")
        _require_digest(self.sha256, label="source sha256")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvaluationSourceFile:
        values = _require_exact_fields(
            payload,
            frozenset({"path", "sha256"}),
            label="evaluation source file",
        )
        return cls(
            path=values["path"],  # type: ignore[arg-type]
            sha256=values["sha256"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256}

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvaluationSourceManifest:
    files: tuple[EvaluationSourceFile, ...]
    schema_version: int = field(
        init=False,
        default=EVALUATION_SOURCE_MANIFEST_SCHEMA_VERSION,
    )

    def __post_init__(self) -> None:
        if type(self.files) is not tuple:
            raise TypeError("manifest files must be a tuple")
        if any(type(item) is not EvaluationSourceFile for item in self.files):
            raise TypeError("manifest files must contain EvaluationSourceFile")
        if tuple(item.path for item in self.files) != EVALUATION_SOURCE_PATHS:
            raise ValueError("manifest paths must match the frozen order")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvaluationSourceManifest:
        values = _require_exact_fields(
            payload,
            frozenset({"schema_version", "files"}),
            label="evaluation source manifest",
        )
        if type(values["schema_version"]) is not int or values["schema_version"] != EVALUATION_SOURCE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("manifest schema_version does not match")
        raw_files = values["files"]
        if type(raw_files) is not list:
            raise TypeError("manifest files must be a list")
        return cls(files=tuple(EvaluationSourceFile.from_dict(item) for item in raw_files))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "files": [item.to_dict() for item in self.files],
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvaluationWindowSpec:
    ordinal: int
    window_start: str
    window_end: str
    first_effective_at: str
    last_effective_at: str
    evaluation_as_of: str
    expected_tracked_sessions: int
    schema_version: int = field(
        init=False,
        default=EVALUATION_WINDOW_SPEC_SCHEMA_VERSION,
    )

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("window ordinal must be a positive integer")
        start = _require_date(self.window_start, label="window_start")
        end = _require_date(self.window_end, label="window_end")
        if start > end:
            raise ValueError("window_start cannot be after window_end")
        first = _require_evaluator_utc(
            self.first_effective_at,
            label="first_effective_at",
        )
        last = _require_evaluator_utc(
            self.last_effective_at,
            label="last_effective_at",
        )
        as_of = _require_evaluator_utc(
            self.evaluation_as_of,
            label="evaluation_as_of",
        )
        if first.date() != start or last.date() != end:
            raise ValueError("window effective dates must match window dates")
        if first > last:
            raise ValueError("first_effective_at cannot be after last_effective_at")
        if as_of < last:
            raise ValueError("evaluation_as_of cannot precede last_effective_at")
        if type(self.expected_tracked_sessions) is not int or self.expected_tracked_sessions < 2:
            raise ValueError("expected_tracked_sessions must be at least two")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvaluationWindowSpec:
        values = _require_exact_fields(
            payload,
            frozenset(
                {
                    "schema_version",
                    "ordinal",
                    "window_start",
                    "window_end",
                    "first_effective_at",
                    "last_effective_at",
                    "evaluation_as_of",
                    "expected_tracked_sessions",
                }
            ),
            label="evaluation window spec",
        )
        _require_schema(
            values["schema_version"],
            EVALUATION_WINDOW_SPEC_SCHEMA_VERSION,
            label="evaluation window spec",
        )
        return cls(
            ordinal=values["ordinal"],  # type: ignore[arg-type]
            window_start=values["window_start"],  # type: ignore[arg-type]
            window_end=values["window_end"],  # type: ignore[arg-type]
            first_effective_at=values["first_effective_at"],  # type: ignore[arg-type]
            last_effective_at=values["last_effective_at"],  # type: ignore[arg-type]
            evaluation_as_of=values["evaluation_as_of"],  # type: ignore[arg-type]
            expected_tracked_sessions=values["expected_tracked_sessions"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ordinal": self.ordinal,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "first_effective_at": self.first_effective_at,
            "last_effective_at": self.last_effective_at,
            "evaluation_as_of": self.evaluation_as_of,
            "expected_tracked_sessions": self.expected_tracked_sessions,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def build_evaluation_window_spec(
    *,
    ordinal: int,
    window_start: str,
    window_end: str,
    first_effective_at: str,
    last_effective_at: str,
    evaluation_as_of: str,
    expected_tracked_sessions: int,
) -> EvaluationWindowSpec:
    """Build a preregistered window without outcome or frame material."""

    return EvaluationWindowSpec(
        ordinal=ordinal,
        window_start=window_start,
        window_end=window_end,
        first_effective_at=first_effective_at,
        last_effective_at=last_effective_at,
        evaluation_as_of=evaluation_as_of,
        expected_tracked_sessions=expected_tracked_sessions,
    )


def _evolution_policy_from_dict(
    payload: object,
) -> StrategyEvolutionPolicy:
    values = _require_exact_fields(
        payload,
        frozenset(
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
            }
        ),
        label="strategy evolution policy",
    )
    _require_schema(
        values["schema_version"],
        STRATEGY_EVOLUTION_POLICY_SCHEMA_VERSION,
        label="strategy evolution policy",
    )
    _require_authority(values, label="strategy evolution policy")
    bounds = _require_exact_fields(
        values["mutation_bounds"],
        frozenset(
            {
                "current-aggressive",
                "pullback-support",
                "catalyst-relative-strength",
            }
        ),
        label="mutation bounds",
    )
    aggressive = _require_exact_fields(
        bounds["current-aggressive"],
        frozenset({"min_score"}),
        label="current aggressive bounds",
    )
    pullback = _require_exact_fields(
        bounds["pullback-support"],
        frozenset(
            {
                "min_daily_change_fraction",
                "max_daily_change_fraction",
                "max_volume_ratio",
            }
        ),
        label="pullback support bounds",
    )
    catalyst = _require_exact_fields(
        bounds["catalyst-relative-strength"],
        frozenset({"min_score"}),
        label="catalyst relative strength bounds",
    )
    return StrategyEvolutionPolicy(
        enabled=values["enabled"],  # type: ignore[arg-type]
        experiment_starting_cash_usd=values["experiment_starting_cash_usd"],  # type: ignore[arg-type]
        candidate_min_order_usd=values["candidate_min_order_usd"],  # type: ignore[arg-type]
        max_active_candidates=values["max_active_candidates"],  # type: ignore[arg-type]
        mutations_per_cycle=values["mutations_per_cycle"],  # type: ignore[arg-type]
        minimum_tracked_days=values["minimum_tracked_days"],  # type: ignore[arg-type]
        minimum_closed_trades=values["minimum_closed_trades"],  # type: ignore[arg-type]
        minimum_walk_forward_windows=values["minimum_walk_forward_windows"],  # type: ignore[arg-type]
        maximum_paper_drawdown_pct=values["maximum_paper_drawdown_pct"],  # type: ignore[arg-type]
        mutation_bounds=StrategyMutationBounds(
            current_aggressive=CurrentAggressiveMutationBounds(
                min_score=aggressive["min_score"],  # type: ignore[arg-type]
            ),
            pullback_support=PullbackSupportMutationBounds(
                min_daily_change_fraction=pullback["min_daily_change_fraction"],  # type: ignore[arg-type]
                max_daily_change_fraction=pullback["max_daily_change_fraction"],  # type: ignore[arg-type]
                max_volume_ratio=pullback["max_volume_ratio"],  # type: ignore[arg-type]
            ),
            catalyst_relative_strength=CatalystRelativeStrengthMutationBounds(
                min_score=catalyst["min_score"],  # type: ignore[arg-type]
            ),
        ),
    )


def _evaluation_policy_from_dict(
    payload: object,
) -> StrategyEvaluationPolicy:
    values = _require_exact_fields(
        payload,
        frozenset(
            {
                "schema_version",
                "benchmark_symbol",
                "holding_sessions",
                "commission_bps_per_side",
                "half_spread_bps_per_side",
                "slippage_bps_per_side",
                "round_trip_sides",
                "analysis_only",
                "execution_authority",
                "can_submit_orders",
            }
        ),
        label="strategy evaluation policy",
    )
    _require_schema(
        values["schema_version"],
        STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION,
        label="strategy evaluation policy",
    )
    _require_authority(values, label="strategy evaluation policy")
    return StrategyEvaluationPolicy(
        benchmark_symbol=values["benchmark_symbol"],  # type: ignore[arg-type]
        holding_sessions=values["holding_sessions"],  # type: ignore[arg-type]
        commission_bps_per_side=values["commission_bps_per_side"],  # type: ignore[arg-type]
        half_spread_bps_per_side=values["half_spread_bps_per_side"],  # type: ignore[arg-type]
        slippage_bps_per_side=values["slippage_bps_per_side"],  # type: ignore[arg-type]
        round_trip_sides=values["round_trip_sides"],  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class StrategyEvaluationRegistration:
    registration_id: str
    genome: StrategyGenome
    genome_canonical_sha256: str
    evaluation_code_commit: str
    evaluation_source_manifest: EvaluationSourceManifest
    evaluation_runtime_sha256: str
    evolution_policy: StrategyEvolutionPolicy
    evolution_policy_sha256: str
    evaluation_policy: StrategyEvaluationPolicy
    evaluation_policy_sha256: str
    evaluator_version: str
    windows: tuple[EvaluationWindowSpec, ...]
    effective_at: str
    recorded_at: str
    schema_version: int = field(
        init=False,
        default=STRATEGY_EVALUATION_REGISTRATION_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _require_object_id(
            self.registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        if type(self.genome) is not StrategyGenome:
            raise TypeError("genome must be a StrategyGenome")
        if self.genome_canonical_sha256 != _sha256(self.genome.canonical_json_bytes()):
            raise ValueError("genome_canonical_sha256 does not match genome")
        if type(self.evaluation_code_commit) is not str or _LOWER_COMMIT.fullmatch(self.evaluation_code_commit) is None:
            raise ValueError("evaluation_code_commit must be lowercase 40-hex")
        if type(self.evaluation_source_manifest) is not EvaluationSourceManifest:
            raise TypeError("evaluation_source_manifest type does not match")
        if self.evaluation_runtime_sha256 != _sha256(self.evaluation_source_manifest.canonical_json_bytes()):
            raise ValueError("evaluation_runtime_sha256 does not match manifest")
        if type(self.evolution_policy) is not StrategyEvolutionPolicy:
            raise TypeError("evolution_policy type does not match")
        if self.evolution_policy_sha256 != _sha256(self.evolution_policy.canonical_json_bytes()):
            raise ValueError("evolution_policy_sha256 does not match policy")
        if type(self.evaluation_policy) is not StrategyEvaluationPolicy:
            raise TypeError("evaluation_policy type does not match")
        if self.evaluation_policy_sha256 != _sha256(self.evaluation_policy.canonical_json_bytes()):
            raise ValueError("evaluation_policy_sha256 does not match policy")
        if self.evaluator_version != EVALUATOR_VERSION:
            raise ValueError("evaluator_version does not match")
        _validate_window_schedule(
            self.windows,
            evolution_policy=self.evolution_policy,
            evaluation_policy=self.evaluation_policy,
        )
        effective = _require_canonical_utc(
            self.effective_at,
            label="registration effective_at",
        )
        recorded = _require_canonical_utc(
            self.recorded_at,
            label="registration recorded_at",
        )
        first_window = _require_evaluator_utc(
            self.windows[0].first_effective_at,
            label="first window effective_at",
        )
        if effective > recorded:
            raise ValueError("registration effective_at exceeds recorded_at")
        if recorded > first_window:
            raise ValueError("registration first seen after first window")
        if self.analysis_only is not True:
            raise ValueError("registration analysis_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("registration execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("registration can_submit_orders is fixed")
        if self.registration_id != _expected_object_id(
            kind="evaluation-registration",
            effective_at=self.effective_at,
            payload=self._evidence_payload(),
        ):
            raise ValueError("registration_id does not match evidence identity")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> StrategyEvaluationRegistration:
        expected = frozenset(
            {
                "schema_version",
                "registration_id",
                "genome",
                "genome_canonical_sha256",
                "evaluation_code_commit",
                "evaluation_source_manifest",
                "evaluation_runtime_sha256",
                "evolution_policy",
                "evolution_policy_sha256",
                "evaluation_policy",
                "evaluation_policy_sha256",
                "evaluator_version",
                "windows",
                "effective_at",
                "recorded_at",
                "analysis_only",
                "execution_authority",
                "can_submit_orders",
            }
        )
        values = _require_exact_fields(
            payload,
            expected,
            label="strategy evaluation registration",
        )
        _require_schema(
            values["schema_version"],
            STRATEGY_EVALUATION_REGISTRATION_SCHEMA_VERSION,
            label="strategy evaluation registration",
        )
        _require_authority(values, label="strategy evaluation registration")
        raw_windows = values["windows"]
        if type(raw_windows) is not list:
            raise TypeError("registration windows must be a list")
        return cls(
            registration_id=values["registration_id"],  # type: ignore[arg-type]
            genome=StrategyGenome.from_dict(values["genome"]),  # type: ignore[arg-type]
            genome_canonical_sha256=values["genome_canonical_sha256"],  # type: ignore[arg-type]
            evaluation_code_commit=values["evaluation_code_commit"],  # type: ignore[arg-type]
            evaluation_source_manifest=EvaluationSourceManifest.from_dict(
                values["evaluation_source_manifest"]  # type: ignore[arg-type]
            ),
            evaluation_runtime_sha256=values["evaluation_runtime_sha256"],  # type: ignore[arg-type]
            evolution_policy=_evolution_policy_from_dict(values["evolution_policy"]),
            evolution_policy_sha256=values["evolution_policy_sha256"],  # type: ignore[arg-type]
            evaluation_policy=_evaluation_policy_from_dict(values["evaluation_policy"]),
            evaluation_policy_sha256=values["evaluation_policy_sha256"],  # type: ignore[arg-type]
            evaluator_version=values["evaluator_version"],  # type: ignore[arg-type]
            windows=tuple(EvaluationWindowSpec.from_dict(item) for item in raw_windows),
            effective_at=values["effective_at"],  # type: ignore[arg-type]
            recorded_at=values["recorded_at"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_envelope(
        cls,
        envelope: EvidenceEnvelope,
    ) -> StrategyEvaluationRegistration:
        if type(envelope) is not EvidenceEnvelope:
            raise TypeError("registration envelope type does not match")
        if envelope.kind != "evaluation-registration":
            raise ValueError("envelope kind is not evaluation-registration")
        raw_payload = _thaw_json(envelope.payload)
        if not isinstance(raw_payload, dict):
            raise ValueError("registration payload is not an object")
        full = {
            **raw_payload,
            "registration_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
        }
        registration = cls.from_dict(full)
        if registration._evidence_payload() != raw_payload:
            raise ValueError("registration payload round trip is not exact")
        return registration

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for field_name in ("registration_id", "effective_at", "recorded_at"):
            del payload[field_name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "registration_id": self.registration_id,
            "genome": self.genome.to_dict(),
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "evaluation_code_commit": self.evaluation_code_commit,
            "evaluation_source_manifest": (self.evaluation_source_manifest.to_dict()),
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "evolution_policy": self.evolution_policy.to_dict(),
            "evolution_policy_sha256": self.evolution_policy_sha256,
            "evaluation_policy": self.evaluation_policy.to_dict(),
            "evaluation_policy_sha256": self.evaluation_policy_sha256,
            "evaluator_version": self.evaluator_version,
            "windows": [window.to_dict() for window in self.windows],
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": self.analysis_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _validate_window_schedule(
    windows: object,
    *,
    evolution_policy: StrategyEvolutionPolicy,
    evaluation_policy: StrategyEvaluationPolicy,
) -> None:
    if type(windows) is not tuple:
        raise TypeError("windows must be an exact tuple")
    if any(type(window) is not EvaluationWindowSpec for window in windows):
        raise TypeError("windows must contain EvaluationWindowSpec")
    if len(windows) < evolution_policy.minimum_walk_forward_windows:
        raise ValueError("too few walk-forward windows")
    maximum_possible_closed_trades = 0
    previous: EvaluationWindowSpec | None = None
    for expected_ordinal, window in enumerate(windows, start=1):
        if window.ordinal != expected_ordinal:
            raise ValueError("window ordinals must be exact sequence 1..N")
        if window.expected_tracked_sessions < evaluation_policy.holding_sessions + 1:
            raise ValueError("window cannot close one holding-period trade")
        capacity = (window.expected_tracked_sessions - 1) // evaluation_policy.holding_sessions
        if capacity > EVALUATOR_MAX_CLOSED_TRADE_OPPORTUNITIES:
            raise ValueError("window exceeds evaluator closed-trade capacity")
        maximum_possible_closed_trades += capacity
        if previous is not None:
            if _require_date(
                window.window_start,
                label="window_start",
            ) <= _require_date(previous.window_end, label="window_end"):
                raise ValueError("walk-forward windows overlap")
            if _require_evaluator_utc(
                window.first_effective_at,
                label="first_effective_at",
            ) <= _require_evaluator_utc(
                previous.last_effective_at,
                label="last_effective_at",
            ):
                raise ValueError("walk-forward effective times overlap")
        previous = window
    if maximum_possible_closed_trades < evolution_policy.minimum_closed_trades:
        raise ValueError("schedule cannot reach minimum closed trades")


def _reject_symlink_components(path: Path, *, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            state = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(state.st_mode):
            raise ValueError(f"{label} cannot contain symlink components")


def _canonical_repo_root(repo_root: str | Path) -> Path:
    lexical = Path(os.path.abspath(os.fspath(Path(repo_root).expanduser())))
    _reject_symlink_components(lexical, label="repo_root")
    try:
        state = lexical.stat()
    except FileNotFoundError as exc:
        raise ValueError("repo_root must exist") from exc
    if not stat.S_ISDIR(state.st_mode):
        raise ValueError("repo_root must be a directory")
    try:
        inside_worktree = subprocess.run(
            ("git", "rev-parse", "--is-inside-work-tree"),
            cwd=lexical,
            check=False,
            capture_output=True,
            text=True,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        ).stdout.strip()
        if inside_worktree != "true":
            raise ValueError("repo_root must be a Git worktree")
        top = subprocess.run(
            ("git", "rev-parse", "--show-toplevel"),
            cwd=lexical,
            check=True,
            capture_output=True,
            text=True,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        ).stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise StrategyPromotionEvidenceError(
            "Git worktree preflight timed out"
        ) from exc
    try:
        lexical.resolve().relative_to(Path(top).resolve())
    except ValueError as exc:
        raise ValueError("repo_root must be inside its Git worktree") from exc
    return lexical


def _git_text(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ("git", *args),
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        ).stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise StrategyPromotionEvidenceError("Git preflight timed out") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Git preflight failed") from exc


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ("git", *args),
            cwd=repo_root,
            check=True,
            capture_output=True,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        ).stdout
    except subprocess.TimeoutExpired as exc:
        raise StrategyPromotionEvidenceError(
            "Git object preflight timed out"
        ) from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Git object preflight failed") from exc


def _read_regular_source(repo_root: Path, relative: str) -> bytes:
    path = repo_root / relative
    _reject_symlink_components(path, label=f"calculation source {relative}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(repo_root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"calculation source is missing or escapes repo_root: {relative}") from exc
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"calculation source cannot be opened safely: {relative}") from exc
    try:
        state = os.fstat(descriptor)
        lexical_state = path.lstat()
        if not stat.S_ISREG(state.st_mode):
            raise ValueError(f"calculation source must be regular: {relative}")
        if (state.st_dev, state.st_ino) != (
            lexical_state.st_dev,
            lexical_state.st_ino,
        ):
            raise ValueError(f"calculation source changed during open: {relative}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1_048_576)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _capture_loaded_calculation_sources() -> tuple[_LoadedCalculationSource, ...]:
    captured: list[_LoadedCalculationSource] = []
    for module_name, relative in _CALCULATION_MODULE_PATHS:
        module = sys.modules.get(module_name)
        module_file = getattr(module, "__file__", None)
        if module is None or type(module_file) is not str:
            raise RuntimeError(
                f"loaded calculation module is unavailable: {module_name}"
            )
        lexical = Path(os.path.abspath(module_file))
        _reject_symlink_components(
            lexical,
            label=f"loaded calculation source {module_name}",
        )
        try:
            canonical = lexical.resolve(strict=True)
            state = canonical.stat()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"loaded calculation source is missing: {module_name}"
            ) from exc
        if not stat.S_ISREG(state.st_mode) or canonical.suffix != ".py":
            raise RuntimeError(
                f"loaded calculation source must be a Python source file: {module_name}"
            )
        try:
            source_bytes = canonical.read_bytes()
        except OSError as exc:
            raise RuntimeError(
                f"loaded calculation source cannot be read: {module_name}"
            ) from exc
        captured.append(
            _LoadedCalculationSource(
                module_name=module_name,
                relative_path=relative,
                canonical_path=canonical,
                sha256=_sha256(source_bytes),
            )
        )
    return tuple(captured)


_LOADED_CALCULATION_SOURCES = _capture_loaded_calculation_sources()


def _require_loaded_source_binding(
    repo_root: Path,
    active_manifest: EvaluationSourceManifest,
    *,
    registered_manifest: EvaluationSourceManifest | None = None,
) -> None:
    active_by_path = {
        source.path: source.sha256 for source in active_manifest.files
    }
    registered_by_path = (
        {
            source.path: source.sha256
            for source in registered_manifest.files
        }
        if registered_manifest is not None
        else None
    )
    for captured in _LOADED_CALCULATION_SOURCES:
        module = sys.modules.get(captured.module_name)
        module_file = getattr(module, "__file__", None)
        if module is None or type(module_file) is not str:
            raise ValueError(
                f"loaded calculation module is unavailable: {captured.module_name}"
            )
        try:
            current_loaded_path = Path(
                os.path.abspath(module_file)
            ).resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError(
                f"loaded calculation source is missing: {captured.module_name}"
            ) from exc
        if current_loaded_path != captured.canonical_path:
            raise ValueError(
                "loaded calculation module path changed after provenance capture"
            )
        try:
            expected = (repo_root / captured.relative_path).resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError(
                f"loaded calculation source is missing: {captured.relative_path}"
            ) from exc
        if expected != captured.canonical_path:
            raise ValueError(
                "loaded calculation source path does not match repo_root"
            )
        if active_by_path.get(captured.relative_path) != captured.sha256:
            raise ValueError(
                "loaded calculation source fingerprint does not match active manifest bytes"
            )
        if (
            registered_by_path is not None
            and registered_by_path.get(captured.relative_path)
            != captured.sha256
        ):
            raise ValueError(
                "loaded calculation source fingerprint does not match registration"
            )


def _active_source_snapshot(
    repo_root: Path,
) -> tuple[EvaluationSourceManifest, tuple[bytes, ...]]:
    files: list[EvaluationSourceFile] = []
    source_bytes: list[bytes] = []
    for relative in EVALUATION_SOURCE_PATHS:
        active = _read_regular_source(repo_root, relative)
        source_bytes.append(active)
        files.append(
            EvaluationSourceFile(
                path=relative,
                sha256=_sha256(active),
            )
        )
    return EvaluationSourceManifest(files=tuple(files)), tuple(source_bytes)


def _active_source_manifest(repo_root: Path) -> EvaluationSourceManifest:
    manifest, _source_bytes = _active_source_snapshot(repo_root)
    _require_loaded_source_binding(repo_root, manifest)
    return manifest


def build_evaluation_source_manifest(
    repo_root: str | Path,
) -> EvaluationSourceManifest:
    """Build the fixed active calculation-source manifest."""

    return _active_source_manifest(_canonical_repo_root(repo_root))


def _registration_preflight(
    repo_root: Path,
    evaluation_code_commit: str,
) -> EvaluationSourceManifest:
    if type(evaluation_code_commit) is not str or _LOWER_COMMIT.fullmatch(evaluation_code_commit) is None:
        raise ValueError("evaluation_code_commit must be lowercase 40-hex")
    if _git_text(repo_root, "rev-parse", "HEAD") != evaluation_code_commit:
        raise ValueError("evaluation_code_commit must equal current HEAD")
    if _git_text(repo_root, "status", "--porcelain") != "":
        raise ValueError("evaluation checkout must be clean")
    manifest, active_files = _active_source_snapshot(repo_root)
    _require_loaded_source_binding(repo_root, manifest)
    git_prefix = _git_text(repo_root, "rev-parse", "--show-prefix")
    if git_prefix.startswith("/") or any(
        part == ".." for part in Path(git_prefix).parts
    ):
        raise ValueError("Git worktree prefix is invalid")
    for source, active in zip(manifest.files, active_files, strict=True):
        committed = _git_bytes(
            repo_root,
            "show",
            f"{evaluation_code_commit}:{git_prefix}{source.path}",
        )
        if active != committed:
            raise ValueError("active bytes do not match Git object bytes")
        if _sha256(committed) != source.sha256:
            raise ValueError("Git object digest does not match manifest")
    return manifest


@dataclass(frozen=True, slots=True)
class AdmittedGenomeWindow:
    admitted_window_id: str
    registration_id: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    ordinal: int
    window_id: str
    result_sha256: str
    input_frames: tuple[EvaluationFrame, ...]
    result: GenomeWindowResult
    effective_at: str
    recorded_at: str
    schema_version: int = field(
        init=False,
        default=ADMITTED_GENOME_WINDOW_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _require_object_id(
            self.admitted_window_id,
            kind="genome-window",
            label="admitted_window_id",
        )
        _require_object_id(
            self.registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        if type(self.evaluation_code_commit) is not str or _LOWER_COMMIT.fullmatch(self.evaluation_code_commit) is None:
            raise ValueError("evaluation_code_commit must be lowercase 40-hex")
        _require_digest(
            self.evaluation_runtime_sha256,
            label="evaluation_runtime_sha256",
        )
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("window ordinal must be positive")
        _require_digest(self.window_id, label="window_id")
        if type(self.result) is not GenomeWindowResult:
            raise TypeError("result must be a GenomeWindowResult")
        if self.window_id != self.result.window_id:
            raise ValueError("window_id does not match result")
        if self.result_sha256 != _sha256(self.result.canonical_json_bytes()):
            raise ValueError("result_sha256 does not match result")
        if type(self.input_frames) is not tuple:
            raise TypeError("input_frames must be an exact tuple")
        if any(type(frame) is not EvaluationFrame for frame in self.input_frames):
            raise TypeError("input_frames must contain EvaluationFrame")
        reparsed = evaluation_frames_from_dict([frame.to_dict() for frame in self.input_frames])
        if reparsed != self.input_frames:
            raise ValueError("input_frames do not round trip exactly")
        if evaluation_frames_sha256(self.input_frames) != self.result.input_frames_sha256:
            raise ValueError("input frame hash does not match result")
        effective = _require_canonical_utc(
            self.effective_at,
            label="window effective_at",
        )
        recorded = _require_canonical_utc(
            self.recorded_at,
            label="window recorded_at",
        )
        if effective != _require_evaluator_utc(
            self.result.evaluation_as_of,
            label="result evaluation_as_of",
        ):
            raise ValueError("window effective_at must equal evaluation_as_of")
        if recorded < effective:
            raise ValueError("window recorded_at precedes effective_at")
        if self.analysis_only is not True:
            raise ValueError("window analysis_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("window execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("window can_submit_orders is fixed")
        if self.admitted_window_id != _expected_object_id(
            kind="genome-window",
            effective_at=self.effective_at,
            payload=self._evidence_payload(),
        ):
            raise ValueError("admitted_window_id does not match evidence identity")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> AdmittedGenomeWindow:
        expected = frozenset(
            {
                "schema_version",
                "admitted_window_id",
                "registration_id",
                "evaluation_code_commit",
                "evaluation_runtime_sha256",
                "ordinal",
                "window_id",
                "result_sha256",
                "input_frames",
                "result",
                "effective_at",
                "recorded_at",
                "analysis_only",
                "execution_authority",
                "can_submit_orders",
            }
        )
        values = _require_exact_fields(
            payload,
            expected,
            label="admitted genome window",
        )
        _require_schema(
            values["schema_version"],
            ADMITTED_GENOME_WINDOW_SCHEMA_VERSION,
            label="admitted genome window",
        )
        _require_authority(values, label="admitted genome window")
        raw_frames = values["input_frames"]
        if type(raw_frames) is not list:
            raise TypeError("input_frames must be a list")
        frames = evaluation_frames_from_dict(raw_frames)
        raw_result = values["result"]
        if not isinstance(raw_result, Mapping):
            raise TypeError("result must be an object")
        return cls(
            admitted_window_id=values["admitted_window_id"],  # type: ignore[arg-type]
            registration_id=values["registration_id"],  # type: ignore[arg-type]
            evaluation_code_commit=values["evaluation_code_commit"],  # type: ignore[arg-type]
            evaluation_runtime_sha256=values["evaluation_runtime_sha256"],  # type: ignore[arg-type]
            ordinal=values["ordinal"],  # type: ignore[arg-type]
            window_id=values["window_id"],  # type: ignore[arg-type]
            result_sha256=values["result_sha256"],  # type: ignore[arg-type]
            input_frames=frames,
            result=GenomeWindowResult.from_dict(raw_result),
            effective_at=values["effective_at"],  # type: ignore[arg-type]
            recorded_at=values["recorded_at"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_envelope(
        cls,
        envelope: EvidenceEnvelope,
    ) -> AdmittedGenomeWindow:
        if type(envelope) is not EvidenceEnvelope:
            raise TypeError("window envelope type does not match")
        if envelope.kind != "genome-window":
            raise ValueError("envelope kind is not genome-window")
        raw_payload = _thaw_json(envelope.payload)
        if not isinstance(raw_payload, dict):
            raise ValueError("window payload is not an object")
        full = {
            **raw_payload,
            "admitted_window_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
        }
        admitted = cls.from_dict(full)
        if admitted._evidence_payload() != raw_payload:
            raise ValueError("window payload round trip is not exact")
        return admitted

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for field_name in ("admitted_window_id", "effective_at", "recorded_at"):
            del payload[field_name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "admitted_window_id": self.admitted_window_id,
            "registration_id": self.registration_id,
            "evaluation_code_commit": self.evaluation_code_commit,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "ordinal": self.ordinal,
            "window_id": self.window_id,
            "result_sha256": self.result_sha256,
            "input_frames": [frame.to_dict() for frame in self.input_frames],
            "result": self.result.to_dict(),
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": self.analysis_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _registrations_from_snapshot(
    snapshot: Sequence[EvidenceEnvelope],
) -> tuple[StrategyEvaluationRegistration, ...]:
    return tuple(StrategyEvaluationRegistration.from_envelope(envelope) for envelope in snapshot if envelope.kind == "evaluation-registration")


def _windows_from_snapshot(
    snapshot: Sequence[EvidenceEnvelope],
) -> tuple[AdmittedGenomeWindow, ...]:
    return tuple(AdmittedGenomeWindow.from_envelope(envelope) for envelope in snapshot if envelope.kind == "genome-window")


def _registered_by_id(
    snapshot: Sequence[EvidenceEnvelope],
    registration_id: str,
) -> StrategyEvaluationRegistration:
    matches = tuple(item for item in _registrations_from_snapshot(snapshot) if item.registration_id == registration_id)
    if len(matches) != 1:
        raise ValueError("registration must already be durable")
    return matches[0]


def _require_active_manifest(
    repo_root: Path,
    registration: StrategyEvaluationRegistration,
) -> EvaluationSourceManifest:
    active = _active_source_manifest(repo_root)
    _require_loaded_source_binding(
        repo_root,
        active,
        registered_manifest=registration.evaluation_source_manifest,
    )
    if active.canonical_json_bytes() != registration.evaluation_source_manifest.canonical_json_bytes() or _sha256(active.canonical_json_bytes()) != registration.evaluation_runtime_sha256:
        raise ValueError("active calculation manifest does not match registration")
    return active


def _validate_result_against_registration(
    *,
    registration: StrategyEvaluationRegistration,
    spec: EvaluationWindowSpec,
    frames: tuple[EvaluationFrame, ...],
    result: GenomeWindowResult,
) -> None:
    if len(frames) != spec.expected_tracked_sessions:
        raise ValueError("frame count does not match preregistered window")
    if frames[0].session_date.isoformat() != spec.window_start or frames[-1].session_date.isoformat() != spec.window_end:
        raise ValueError("frame dates do not match preregistered window")
    if frames[0].effective_at.isoformat(timespec="seconds").replace("+00:00", "Z") != spec.first_effective_at or frames[-1].effective_at.isoformat(timespec="seconds").replace("+00:00", "Z") != spec.last_effective_at:
        raise ValueError("frame effective times do not match preregistered window")
    if evaluation_frames_sha256(frames) != result.input_frames_sha256:
        raise ValueError("frame hash does not match result")
    if result.window_start != spec.window_start or result.window_end != spec.window_end or result.evaluation_as_of != spec.evaluation_as_of or result.tracked_sessions != spec.expected_tracked_sessions:
        raise ValueError("result window does not match preregistered window")
    bindings = {
        "genome_id": registration.genome.genome_id,
        "genome_canonical_sha256": registration.genome_canonical_sha256,
        "evaluator_version": registration.evaluator_version,
        "evolution_policy_sha256": registration.evolution_policy_sha256,
        "evaluation_policy_sha256": registration.evaluation_policy_sha256,
        "starting_cash_usd": (registration.evolution_policy.experiment_starting_cash_usd),
    }
    for name, expected in bindings.items():
        if getattr(result, name) != expected:
            raise ValueError(f"result {name} does not match registration")
    with localcontext(_new_decimal_context()):
        per_side = registration.evaluation_policy.per_side_cost_fraction
        round_trip = registration.evaluation_policy.round_trip_cost_fraction
        for trade in result.trades:
            if trade.holding_sessions != registration.evaluation_policy.holding_sessions:
                raise ValueError("trade holding horizon does not match policy")
            if Decimal(trade.modeled_round_trip_cost_fraction) != round_trip:
                raise ValueError("trade round-trip cost does not match policy")
            if Decimal(trade.entry_cost_usd) != Decimal(trade.entry_budget_usd) * per_side:
                raise ValueError("trade entry cost does not match policy")
            if Decimal(trade.exit_cost_usd) != Decimal(trade.gross_exit_value_usd) * per_side:
                raise ValueError("trade exit cost does not match policy")


_ADMISSION_INVARIANTS = (
    "preregistered_complete_schedule",
    "ordered_window_dependencies",
    "exact_calculation_provenance",
    "byte_identical_evaluator_replay",
    "analysis_only_authority",
)
_OUTCOME_GATE_NAMES = (
    "minimum_closed_trades",
    "maximum_drawdown_within_policy",
    "pooled_net_return_positive",
    "pooled_benchmark_excess_positive",
    "latest_window_net_return_positive",
    "latest_window_benchmark_excess_positive",
)


@dataclass(frozen=True, slots=True)
class StrategyPromotionEvidence:
    evidence_id: str
    registration_id: str
    evaluation_code_commit: str
    evaluation_runtime_sha256: str
    genome_id: str
    genome_canonical_sha256: str
    admitted_window_ids: tuple[str, ...]
    result_sha256s: tuple[str, ...]
    total_windows: int
    total_tracked_sessions: int
    total_closed_trades: int
    total_winning_trades: int
    total_false_positives: int
    pooled_starting_cash_usd: str
    pooled_ending_equity_usd: str
    pooled_net_return_fraction: str
    pooled_benchmark_return_fraction: str
    pooled_benchmark_excess_fraction: str
    latest_window_net_return_fraction: str
    latest_window_benchmark_excess_fraction: str
    worst_max_drawdown_fraction: str
    admission_invariants: tuple[str, ...]
    gates: tuple[tuple[str, bool], ...]
    issues: tuple[str, ...]
    complete_internal_evidence: bool
    effective_at: str
    recorded_at: str
    schema_version: int = field(
        init=False,
        default=STRATEGY_PROMOTION_EVIDENCE_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _require_object_id(
            self.evidence_id,
            kind="promotion-evidence",
            label="evidence_id",
        )
        _require_object_id(
            self.registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        if type(self.evaluation_code_commit) is not str or _LOWER_COMMIT.fullmatch(self.evaluation_code_commit) is None:
            raise ValueError("evaluation_code_commit must be lowercase 40-hex")
        _require_digest(
            self.evaluation_runtime_sha256,
            label="evaluation_runtime_sha256",
        )
        if type(self.genome_id) is not str or not self.genome_id.startswith("genome-"):
            raise ValueError("genome_id is invalid")
        _require_digest(
            self.genome_canonical_sha256,
            label="genome_canonical_sha256",
        )
        if type(self.admitted_window_ids) is not tuple:
            raise TypeError("admitted_window_ids must be an exact tuple")
        for value in self.admitted_window_ids:
            _require_object_id(
                value,
                kind="genome-window",
                label="admitted_window_id",
            )
        if type(self.result_sha256s) is not tuple:
            raise TypeError("result_sha256s must be an exact tuple")
        for value in self.result_sha256s:
            _require_digest(value, label="result_sha256")
        if len(self.admitted_window_ids) != len(self.result_sha256s):
            raise ValueError("window and result identity counts differ")
        for name in (
            "total_windows",
            "total_tracked_sessions",
            "total_closed_trades",
            "total_winning_trades",
            "total_false_positives",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.total_windows != len(self.admitted_window_ids):
            raise ValueError("total_windows does not match window identities")
        if self.total_winning_trades > self.total_closed_trades:
            raise ValueError("winning trades exceed closed trades")
        if self.total_false_positives > self.total_closed_trades:
            raise ValueError("false positives exceed closed trades")
        for name in (
            "pooled_starting_cash_usd",
            "pooled_ending_equity_usd",
            "pooled_net_return_fraction",
            "pooled_benchmark_return_fraction",
            "pooled_benchmark_excess_fraction",
            "latest_window_net_return_fraction",
            "latest_window_benchmark_excess_fraction",
            "worst_max_drawdown_fraction",
        ):
            _require_decimal_text(getattr(self, name), label=name)
        if self.admission_invariants != _ADMISSION_INVARIANTS:
            raise ValueError("admission_invariants do not match fixed audit names")
        if type(self.gates) is not tuple:
            raise TypeError("gates must be an exact tuple")
        if tuple(name for name, _passed in self.gates) != _OUTCOME_GATE_NAMES:
            raise ValueError("outcome gates do not match fixed order")
        if any(type(passed) is not bool for _name, passed in self.gates):
            raise TypeError("gate results must be booleans")
        expected_issues = tuple(name for name, passed in self.gates if not passed)
        if self.issues != expected_issues:
            raise ValueError("issues must be failed gate reason codes in order")
        if type(self.complete_internal_evidence) is not bool:
            raise TypeError("complete_internal_evidence must be boolean")
        if self.complete_internal_evidence is not all(passed for _name, passed in self.gates):
            raise ValueError("complete_internal_evidence does not match gates")
        effective = _require_canonical_utc(
            self.effective_at,
            label="promotion evidence effective_at",
        )
        recorded = _require_canonical_utc(
            self.recorded_at,
            label="promotion evidence recorded_at",
        )
        if recorded < effective:
            raise ValueError("promotion evidence recorded_at precedes effective_at")
        if self.analysis_only is not True:
            raise ValueError("promotion evidence analysis_only is fixed")
        if self.paper_only is not True:
            raise ValueError("promotion evidence paper_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("promotion evidence execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("promotion evidence can_submit_orders is fixed")
        if self.evidence_id != _expected_object_id(
            kind="promotion-evidence",
            effective_at=self.effective_at,
            payload=self._evidence_payload(),
        ):
            raise ValueError("evidence_id does not match evidence identity")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> StrategyPromotionEvidence:
        expected = frozenset(
            {
                "schema_version",
                "evidence_id",
                "registration_id",
                "evaluation_code_commit",
                "evaluation_runtime_sha256",
                "genome_id",
                "genome_canonical_sha256",
                "admitted_window_ids",
                "result_sha256s",
                "total_windows",
                "total_tracked_sessions",
                "total_closed_trades",
                "total_winning_trades",
                "total_false_positives",
                "pooled_starting_cash_usd",
                "pooled_ending_equity_usd",
                "pooled_net_return_fraction",
                "pooled_benchmark_return_fraction",
                "pooled_benchmark_excess_fraction",
                "latest_window_net_return_fraction",
                "latest_window_benchmark_excess_fraction",
                "worst_max_drawdown_fraction",
                "admission_invariants",
                "gates",
                "issues",
                "complete_internal_evidence",
                "effective_at",
                "recorded_at",
                "analysis_only",
                "paper_only",
                "execution_authority",
                "can_submit_orders",
            }
        )
        values = _require_exact_fields(
            payload,
            expected,
            label="strategy promotion evidence",
        )
        _require_schema(
            values["schema_version"],
            STRATEGY_PROMOTION_EVIDENCE_SCHEMA_VERSION,
            label="strategy promotion evidence",
        )
        _require_authority(values, label="strategy promotion evidence")
        if values["paper_only"] is not True:
            raise ValueError("strategy promotion evidence paper_only must be true")
        sequence_fields = (
            "admitted_window_ids",
            "result_sha256s",
            "admission_invariants",
            "gates",
            "issues",
        )
        for name in sequence_fields:
            if type(values[name]) is not list:
                raise TypeError(f"{name} must be a list")
        raw_gates = values["gates"]
        gates: list[tuple[str, bool]] = []
        for item in raw_gates:
            if type(item) is not list or len(item) != 2:
                raise TypeError("each gate must be a two-item list")
            gates.append((item[0], item[1]))  # type: ignore[arg-type]
        excluded = {
            "schema_version",
            "analysis_only",
            "paper_only",
            "execution_authority",
            "can_submit_orders",
            *sequence_fields,
        }
        constructor = {name: values[name] for name in expected - excluded}
        return cls(
            **constructor,  # type: ignore[arg-type]
            admitted_window_ids=tuple(values["admitted_window_ids"]),
            result_sha256s=tuple(values["result_sha256s"]),
            admission_invariants=tuple(values["admission_invariants"]),
            gates=tuple(gates),
            issues=tuple(values["issues"]),
        )

    @classmethod
    def from_envelope(
        cls,
        envelope: EvidenceEnvelope,
    ) -> StrategyPromotionEvidence:
        if type(envelope) is not EvidenceEnvelope:
            raise TypeError("promotion evidence envelope type does not match")
        if envelope.kind != "promotion-evidence":
            raise ValueError("envelope kind is not promotion-evidence")
        raw_payload = _thaw_json(envelope.payload)
        if not isinstance(raw_payload, dict):
            raise ValueError("promotion evidence payload is not an object")
        full = {
            **raw_payload,
            "evidence_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
        }
        evidence = cls.from_dict(full)
        if evidence._evidence_payload() != raw_payload:
            raise ValueError("promotion evidence payload round trip is not exact")
        return evidence

    def _evidence_payload(self) -> dict[str, object]:
        payload = self.to_dict()
        for field_name in ("evidence_id", "effective_at", "recorded_at"):
            del payload[field_name]
        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "registration_id": self.registration_id,
            "evaluation_code_commit": self.evaluation_code_commit,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "genome_id": self.genome_id,
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "admitted_window_ids": list(self.admitted_window_ids),
            "result_sha256s": list(self.result_sha256s),
            "total_windows": self.total_windows,
            "total_tracked_sessions": self.total_tracked_sessions,
            "total_closed_trades": self.total_closed_trades,
            "total_winning_trades": self.total_winning_trades,
            "total_false_positives": self.total_false_positives,
            "pooled_starting_cash_usd": self.pooled_starting_cash_usd,
            "pooled_ending_equity_usd": self.pooled_ending_equity_usd,
            "pooled_net_return_fraction": self.pooled_net_return_fraction,
            "pooled_benchmark_return_fraction": (self.pooled_benchmark_return_fraction),
            "pooled_benchmark_excess_fraction": (self.pooled_benchmark_excess_fraction),
            "latest_window_net_return_fraction": (self.latest_window_net_return_fraction),
            "latest_window_benchmark_excess_fraction": (self.latest_window_benchmark_excess_fraction),
            "worst_max_drawdown_fraction": self.worst_max_drawdown_fraction,
            "admission_invariants": list(self.admission_invariants),
            "gates": [[name, passed] for name, passed in self.gates],
            "issues": list(self.issues),
            "complete_internal_evidence": self.complete_internal_evidence,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _promotion_payload(
    registration: StrategyEvaluationRegistration,
    windows: Sequence[AdmittedGenomeWindow],
) -> dict[str, object]:
    ordered = tuple(sorted(windows, key=lambda item: item.ordinal))
    if len(ordered) != len(registration.windows):
        raise ValueError("complete registered window schedule is required")
    if tuple(item.ordinal for item in ordered) != tuple(range(1, len(registration.windows) + 1)):
        raise ValueError("complete ordered window schedule is required")
    for admitted, spec in zip(ordered, registration.windows, strict=True):
        if admitted.registration_id != registration.registration_id:
            raise ValueError("window registration dependency does not match")
        if admitted.evaluation_code_commit != registration.evaluation_code_commit or admitted.evaluation_runtime_sha256 != registration.evaluation_runtime_sha256:
            raise ValueError("window calculation provenance does not match")
        _validate_result_against_registration(
            registration=registration,
            spec=spec,
            frames=admitted.input_frames,
            result=admitted.result,
        )
    results = tuple(item.result for item in ordered)
    with localcontext(_new_decimal_context()):
        pooled_starting = sum(
            (Decimal(item.starting_cash_usd) for item in results),
            start=Decimal("0"),
        )
        pooled_ending = sum(
            (Decimal(item.ending_equity_usd) for item in results),
            start=Decimal("0"),
        )
        pooled_net = (pooled_ending - pooled_starting) / pooled_starting
        pooled_benchmark = (
            sum(
                (Decimal(item.starting_cash_usd) * Decimal(item.benchmark_return_fraction) for item in results),
                start=Decimal("0"),
            )
            / pooled_starting
        )
        pooled_excess = pooled_net - pooled_benchmark
        latest_net = Decimal(results[-1].net_return_fraction)
        latest_excess = Decimal(results[-1].benchmark_excess_return_fraction)
        worst_drawdown = min(Decimal(item.max_drawdown_fraction) for item in results)
        maximum_drawdown_fraction = Decimal(registration.evolution_policy.maximum_paper_drawdown_pct) / Decimal("100")
        gates = (
            (
                "minimum_closed_trades",
                sum(item.closed_trade_count for item in results) >= registration.evolution_policy.minimum_closed_trades,
            ),
            (
                "maximum_drawdown_within_policy",
                worst_drawdown >= maximum_drawdown_fraction,
            ),
            ("pooled_net_return_positive", pooled_net > 0),
            ("pooled_benchmark_excess_positive", pooled_excess > 0),
            ("latest_window_net_return_positive", latest_net > 0),
            ("latest_window_benchmark_excess_positive", latest_excess > 0),
        )
        return {
            "schema_version": STRATEGY_PROMOTION_EVIDENCE_SCHEMA_VERSION,
            "registration_id": registration.registration_id,
            "evaluation_code_commit": registration.evaluation_code_commit,
            "evaluation_runtime_sha256": (registration.evaluation_runtime_sha256),
            "genome_id": registration.genome.genome_id,
            "genome_canonical_sha256": registration.genome_canonical_sha256,
            "admitted_window_ids": [item.admitted_window_id for item in ordered],
            "result_sha256s": [item.result_sha256 for item in ordered],
            "total_windows": len(results),
            "total_tracked_sessions": sum(item.tracked_sessions for item in results),
            "total_closed_trades": sum(item.closed_trade_count for item in results),
            "total_winning_trades": sum(item.winning_trade_count for item in results),
            "total_false_positives": sum(item.false_positive_count for item in results),
            "pooled_starting_cash_usd": _decimal_text(pooled_starting),
            "pooled_ending_equity_usd": _decimal_text(pooled_ending),
            "pooled_net_return_fraction": _decimal_text(pooled_net),
            "pooled_benchmark_return_fraction": _decimal_text(pooled_benchmark),
            "pooled_benchmark_excess_fraction": _decimal_text(pooled_excess),
            "latest_window_net_return_fraction": _decimal_text(latest_net),
            "latest_window_benchmark_excess_fraction": _decimal_text(latest_excess),
            "worst_max_drawdown_fraction": _decimal_text(worst_drawdown),
            "admission_invariants": list(_ADMISSION_INVARIANTS),
            "gates": [[name, passed] for name, passed in gates],
            "issues": [name for name, passed in gates if not passed],
            "complete_internal_evidence": all(passed for _name, passed in gates),
            "analysis_only": True,
            "paper_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }


def _replay_persisted_windows(
    repo_root: Path,
    registration: StrategyEvaluationRegistration,
    windows: Sequence[AdmittedGenomeWindow],
) -> None:
    for admitted in sorted(windows, key=lambda item: item.ordinal):
        if admitted.registration_id != registration.registration_id:
            raise ValueError("persisted window registration does not match")
        if admitted.evaluation_code_commit != registration.evaluation_code_commit or admitted.evaluation_runtime_sha256 != registration.evaluation_runtime_sha256:
            raise ValueError("persisted window provenance does not match")
        if not 1 <= admitted.ordinal <= len(registration.windows):
            raise ValueError("persisted window ordinal is outside registration")
        before = _require_active_manifest(repo_root, registration)
        spec = registration.windows[admitted.ordinal - 1]
        recomputed = evaluate_genome_window(
            registration.genome,
            registration.evolution_policy,
            registration.evaluation_policy,
            admitted.input_frames,
            evaluation_as_of=dt.datetime.fromisoformat(spec.evaluation_as_of),
        )
        after = _require_active_manifest(repo_root, registration)
        if before.canonical_json_bytes() != after.canonical_json_bytes():
            raise ValueError("calculation manifest changed during evaluator replay")
        if recomputed.canonical_json_bytes() != admitted.result.canonical_json_bytes():
            raise ValueError("persisted result is not byte-identical to replay")
        _validate_result_against_registration(
            registration=registration,
            spec=spec,
            frames=admitted.input_frames,
            result=admitted.result,
        )


class StrategyPromotionEvidenceLedger:
    def __init__(
        self,
        root: str | Path,
        *,
        repo_root: str | Path,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        self._repo_root = _canonical_repo_root(repo_root)
        self._store = ImmutableStrategyEvidenceStore(root, clock=clock)

    def register(
        self,
        *,
        genome: StrategyGenome,
        evolution_policy: StrategyEvolutionPolicy,
        evaluation_policy: StrategyEvaluationPolicy,
        windows: Sequence[EvaluationWindowSpec],
        evaluation_code_commit: str,
        effective_at: dt.datetime,
    ) -> StrategyEvaluationRegistration:
        if type(genome) is not StrategyGenome:
            raise TypeError("genome must be a StrategyGenome")
        if type(evolution_policy) is not StrategyEvolutionPolicy:
            raise TypeError("evolution_policy type does not match")
        if type(evaluation_policy) is not StrategyEvaluationPolicy:
            raise TypeError("evaluation_policy type does not match")
        if isinstance(windows, (str, bytes)) or not isinstance(windows, Sequence):
            raise TypeError("windows must be a sequence")
        windows_snapshot = tuple(windows)
        _validate_window_schedule(
            windows_snapshot,
            evolution_policy=evolution_policy,
            evaluation_policy=evaluation_policy,
        )
        effective_text = _datetime_text(
            effective_at,
            label="registration effective_at",
        )
        first_manifest = _registration_preflight(
            self._repo_root,
            evaluation_code_commit,
        )
        runtime_digest = _sha256(first_manifest.canonical_json_bytes())
        material = {
            "schema_version": STRATEGY_EVALUATION_REGISTRATION_SCHEMA_VERSION,
            "genome": genome.to_dict(),
            "genome_canonical_sha256": _sha256(genome.canonical_json_bytes()),
            "evaluation_code_commit": evaluation_code_commit,
            "evaluation_source_manifest": first_manifest.to_dict(),
            "evaluation_runtime_sha256": runtime_digest,
            "evolution_policy": evolution_policy.to_dict(),
            "evolution_policy_sha256": _sha256(evolution_policy.canonical_json_bytes()),
            "evaluation_policy": evaluation_policy.to_dict(),
            "evaluation_policy_sha256": _sha256(evaluation_policy.canonical_json_bytes()),
            "evaluator_version": EVALUATOR_VERSION,
            "windows": [window.to_dict() for window in windows_snapshot],
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }
        second_manifest = _registration_preflight(
            self._repo_root,
            evaluation_code_commit,
        )
        if second_manifest.canonical_json_bytes() != first_manifest.canonical_json_bytes():
            raise ValueError("calculation manifest changed during preflight")
        candidate = EvidenceCandidate(
            kind="evaluation-registration",
            effective_at=effective_text,
            payload=material,
        )

        def validate(
            _snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            StrategyEvaluationRegistration.from_envelope(envelope)

        admission = self._store.admit_checked(candidate, validate=validate)
        return StrategyEvaluationRegistration.from_envelope(admission.envelope)

    def admit_window(
        self,
        registration_id: str,
        ordinal: int,
        frames: Sequence[EvaluationFrame],
        result: GenomeWindowResult,
    ) -> AdmittedGenomeWindow:
        _require_object_id(
            registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        if type(ordinal) is not int or ordinal < 1:
            raise ValueError("ordinal must be positive")
        if isinstance(frames, (str, bytes)) or not isinstance(frames, Sequence):
            raise TypeError("frames must be a sequence")
        if any(type(frame) is not EvaluationFrame for frame in frames):
            raise TypeError("frames must contain EvaluationFrame")
        frames_material = [frame.to_dict() for frame in frames]
        frames_snapshot = evaluation_frames_from_dict(frames_material)
        if [frame.to_dict() for frame in frames_snapshot] != frames_material:
            raise ValueError("frame material does not round trip exactly")
        if type(result) is not GenomeWindowResult:
            raise TypeError("result must be a GenomeWindowResult")
        parsed_result = GenomeWindowResult.from_dict(result.to_dict())
        if parsed_result.canonical_json_bytes() != result.canonical_json_bytes():
            raise ValueError("result material does not round trip exactly")

        _active_source_manifest(self._repo_root)
        preflight_snapshot = self._store.rebuild()
        registration = _registered_by_id(
            preflight_snapshot,
            registration_id,
        )
        if ordinal > len(registration.windows):
            raise ValueError("ordinal is outside preregistered schedule")
        spec = registration.windows[ordinal - 1]
        _validate_result_against_registration(
            registration=registration,
            spec=spec,
            frames=frames_snapshot,
            result=parsed_result,
        )
        first_manifest = _require_active_manifest(
            self._repo_root,
            registration,
        )
        recomputed = evaluate_genome_window(
            registration.genome,
            registration.evolution_policy,
            registration.evaluation_policy,
            frames_snapshot,
            evaluation_as_of=dt.datetime.fromisoformat(spec.evaluation_as_of),
        )
        second_manifest = _require_active_manifest(
            self._repo_root,
            registration,
        )
        if first_manifest.canonical_json_bytes() != second_manifest.canonical_json_bytes():
            raise ValueError("calculation manifest changed during evaluator replay")
        if recomputed.canonical_json_bytes() != parsed_result.canonical_json_bytes():
            raise ValueError("result is not byte-identical to evaluator replay")

        payload = {
            "schema_version": ADMITTED_GENOME_WINDOW_SCHEMA_VERSION,
            "registration_id": registration.registration_id,
            "evaluation_code_commit": registration.evaluation_code_commit,
            "evaluation_runtime_sha256": (registration.evaluation_runtime_sha256),
            "ordinal": ordinal,
            "window_id": parsed_result.window_id,
            "result_sha256": _sha256(parsed_result.canonical_json_bytes()),
            "input_frames": [frame.to_dict() for frame in frames_snapshot],
            "result": parsed_result.to_dict(),
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }
        candidate = EvidenceCandidate(
            kind="genome-window",
            effective_at=_store_text_for_evaluator_time(
                parsed_result.evaluation_as_of,
                label="result evaluation_as_of",
            ),
            payload=payload,
        )

        def validate(
            snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            durable_registration = _registered_by_id(
                snapshot,
                registration_id,
            )
            if durable_registration.canonical_json_bytes() != registration.canonical_json_bytes():
                raise ValueError("registration changed during window admission")
            admitted = AdmittedGenomeWindow.from_envelope(envelope)
            if admitted.registration_id != registration_id or admitted.evaluation_code_commit != durable_registration.evaluation_code_commit or admitted.evaluation_runtime_sha256 != durable_registration.evaluation_runtime_sha256:
                raise ValueError("window provenance does not match registration")
            prior = sorted(
                (item for item in _windows_from_snapshot(snapshot) if item.registration_id == registration_id),
                key=lambda item: item.ordinal,
            )
            same_ordinal = tuple(item for item in prior if item.ordinal == admitted.ordinal)
            if same_ordinal:
                if len(same_ordinal) != 1 or same_ordinal[0].admitted_window_id != admitted.admitted_window_id:
                    raise ValueError("conflicting window ordinal")
            elif admitted.ordinal != len(prior) + 1:
                raise ValueError("window is not the next ordinal")
            if admitted.ordinal > len(durable_registration.windows):
                raise ValueError("window ordinal is outside registration")
            expected_spec = durable_registration.windows[admitted.ordinal - 1]
            _validate_result_against_registration(
                registration=durable_registration,
                spec=expected_spec,
                frames=admitted.input_frames,
                result=admitted.result,
            )
            recorded = _require_canonical_utc(
                admitted.recorded_at,
                label="window recorded_at",
            )
            if recorded < _require_canonical_utc(
                durable_registration.recorded_at,
                label="registration recorded_at",
            ):
                raise ValueError("window first seen before registration")
            earlier = tuple(item for item in prior if item.ordinal < admitted.ordinal)
            if earlier and recorded < _require_canonical_utc(
                earlier[-1].recorded_at,
                label="prior window recorded_at",
            ):
                raise ValueError("window first seen before prior ordinal")

        admission = self._store.admit_checked(candidate, validate=validate)
        return AdmittedGenomeWindow.from_envelope(admission.envelope)

    def assemble(
        self,
        registration_id: str,
    ) -> StrategyPromotionEvidence:
        _require_object_id(
            registration_id,
            kind="evaluation-registration",
            label="registration_id",
        )
        _active_source_manifest(self._repo_root)
        preflight_snapshot = self._store.rebuild()
        registration = _registered_by_id(
            preflight_snapshot,
            registration_id,
        )
        windows = tuple(
            sorted(
                (item for item in _windows_from_snapshot(preflight_snapshot) if item.registration_id == registration_id),
                key=lambda item: item.ordinal,
            )
        )
        if len(windows) != len(registration.windows):
            raise ValueError("complete registered window schedule is required")
        _replay_persisted_windows(
            self._repo_root,
            registration,
            windows,
        )
        payload = _promotion_payload(registration, windows)
        candidate = EvidenceCandidate(
            kind="promotion-evidence",
            effective_at=_store_text_for_evaluator_time(
                windows[-1].result.evaluation_as_of,
                label="latest result evaluation_as_of",
            ),
            payload=payload,
        )

        def validate(
            snapshot: tuple[EvidenceEnvelope, ...],
            envelope: EvidenceEnvelope,
        ) -> None:
            durable_registration = _registered_by_id(
                snapshot,
                registration_id,
            )
            if durable_registration.canonical_json_bytes() != registration.canonical_json_bytes():
                raise ValueError("registration changed during evidence assembly")
            durable_windows = tuple(
                sorted(
                    (item for item in _windows_from_snapshot(snapshot) if item.registration_id == registration_id),
                    key=lambda item: item.ordinal,
                )
            )
            expected_payload = _promotion_payload(
                durable_registration,
                durable_windows,
            )
            raw_payload = _thaw_json(envelope.payload)
            if raw_payload != expected_payload:
                raise ValueError("promotion evidence does not match dependencies")
            evidence = StrategyPromotionEvidence.from_envelope(envelope)
            recorded = _require_canonical_utc(
                evidence.recorded_at,
                label="promotion evidence recorded_at",
            )
            dependency_times = (
                durable_registration.recorded_at,
                *(item.recorded_at for item in durable_windows),
            )
            if any(
                recorded
                < _require_canonical_utc(
                    value,
                    label="dependency recorded_at",
                )
                for value in dependency_times
            ):
                raise ValueError("promotion evidence predates a dependency")

        admission = self._store.admit_checked(candidate, validate=validate)
        return StrategyPromotionEvidence.from_envelope(admission.envelope)

    def verify(self) -> tuple[StrategyPromotionEvidence, ...]:
        _active_source_manifest(self._repo_root)
        snapshot = self._store.verify()
        return self._verify_snapshot(snapshot)

    def rebuild(self) -> tuple[StrategyPromotionEvidence, ...]:
        _active_source_manifest(self._repo_root)
        snapshot = self._store.rebuild()
        return self._verify_snapshot(snapshot)

    def _verify_snapshot(
        self,
        snapshot: tuple[EvidenceEnvelope, ...],
    ) -> tuple[StrategyPromotionEvidence, ...]:
        registrations = _registrations_from_snapshot(snapshot)
        windows = _windows_from_snapshot(snapshot)
        evidence = tuple(StrategyPromotionEvidence.from_envelope(envelope) for envelope in snapshot if envelope.kind == "promotion-evidence")
        registration_by_id = {item.registration_id: item for item in registrations}
        if len(registration_by_id) != len(registrations):
            raise ValueError("duplicate durable registration identity")
        for window in windows:
            if window.registration_id not in registration_by_id:
                raise ValueError("persisted window registration is missing")
        for registration in registrations:
            registered_windows = tuple(
                sorted(
                    (item for item in windows if item.registration_id == registration.registration_id),
                    key=lambda item: item.ordinal,
                )
            )
            if tuple(item.ordinal for item in registered_windows) != tuple(range(1, len(registered_windows) + 1)):
                raise ValueError("durable window ordinals are not contiguous")
            _require_active_manifest(self._repo_root, registration)
            _replay_persisted_windows(
                self._repo_root,
                registration,
                registered_windows,
            )
            previous_recorded = _require_canonical_utc(
                registration.recorded_at,
                label="registration recorded_at",
            )
            for window in registered_windows:
                recorded = _require_canonical_utc(
                    window.recorded_at,
                    label="window recorded_at",
                )
                if recorded < previous_recorded:
                    raise ValueError("persisted window predates its durable dependency")
                previous_recorded = recorded
        for item in evidence:
            registration = registration_by_id.get(item.registration_id)
            if registration is None:
                raise ValueError("promotion evidence registration is missing")
            registered_windows = tuple(
                sorted(
                    (window for window in windows if window.registration_id == item.registration_id),
                    key=lambda window: window.ordinal,
                )
            )
            if item._evidence_payload() != _promotion_payload(
                registration,
                registered_windows,
            ):
                raise ValueError("promotion evidence does not match replay")
            recorded = _require_canonical_utc(
                item.recorded_at,
                label="promotion evidence recorded_at",
            )
            if any(
                recorded
                < _require_canonical_utc(
                    value,
                    label="dependency recorded_at",
                )
                for value in (
                    registration.recorded_at,
                    *(window.recorded_at for window in registered_windows),
                )
            ):
                raise ValueError("promotion evidence predates a dependency")
        return evidence
