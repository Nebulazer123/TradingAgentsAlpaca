"""Deterministic, isolated virtual-capital evaluation of strategy genomes."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from pathlib import Path
from typing import Any

from tradingagents.strategy.compiler import (
    PaperCandidateState,
    PaperDecisionAction,
    StrategyObservation,
    compile_genome_paper_decision,
)
from tradingagents.strategy.genome import (
    StrategyEvolutionPolicy,
    StrategyFamily,
    StrategyGenome,
)

STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION = 1
GENOME_WINDOW_RESULT_SCHEMA_VERSION = 1
EVALUATOR_DECIMAL_PRECISION = 50
EVALUATOR_VERSION = "strategy-evaluator-v1"

_DECIMAL_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_GENOME_ID_PATTERN = re.compile(
    r"genome-(?:hold-cash|current-aggressive|pullback-support|"
    r"catalyst-relative-strength)-[0-9a-f]{64}"
)
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TRADEABLE_SESSIONS = frozenset({"pre_open", "open_window", "regular", "pre_close"})
_MAX_PRICE = Decimal("1000000000000")
_MAX_PRICE_SIGNIFICANT_DIGITS = 34
_MAX_PRICE_DECIMAL_PLACES = 12
_EVALUATOR_DECIMAL_EMIN = -999
_EVALUATOR_DECIMAL_EMAX = 999
_CENT = Decimal("0.01")


def _new_decimal_context() -> Context:
    return Context(
        prec=EVALUATOR_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
        Emin=_EVALUATOR_DECIMAL_EMIN,
        Emax=_EVALUATOR_DECIMAL_EMAX,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("canonical decimal must be finite")
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _require_exact_fields(
    payload: object,
    expected: set[str],
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError(f"{field_name} must be an object")
    actual = set(payload)
    if actual != expected:
        raise ValueError(f"{field_name} fields do not match; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    return payload


def _validate_symbol(value: object, *, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    if not 1 <= len(value) <= 15 or not "A" <= value[0] <= "Z":
        raise ValueError(f"{field_name} must be an uppercase ASCII ticker token")
    if any(not ("A" <= character <= "Z" or "0" <= character <= "9" or character in ".-") for character in value[1:]):
        raise ValueError(f"{field_name} must be an uppercase ASCII ticker token")


def _canonical_bps(
    value: object,
    *,
    field_name: str,
) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a decimal string")
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must use canonical decimal syntax")
    parsed = Decimal(value)
    if parsed < 0 or parsed > 1000:
        raise ValueError(f"{field_name} must be between 0 and 1000")
    canonical = _decimal_text(parsed)
    if canonical != value:
        raise ValueError(f"{field_name} must be a canonical decimal string")
    return canonical


def _validate_price(value: object, *, field_name: str) -> None:
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    if value > _MAX_PRICE:
        raise ValueError(f"{field_name} magnitude is too large")
    decimal_tuple = value.as_tuple()
    if len(decimal_tuple.digits) > _MAX_PRICE_SIGNIFICANT_DIGITS:
        raise ValueError(f"{field_name} must have at most {_MAX_PRICE_SIGNIFICANT_DIGITS} significant digits")
    exponent = decimal_tuple.exponent
    if type(exponent) is not int or exponent < -_MAX_PRICE_DECIMAL_PLACES:
        raise ValueError(f"{field_name} must have at most {_MAX_PRICE_DECIMAL_PLACES} decimal places")
    if value.adjusted() > 12:
        raise ValueError(f"{field_name} adjusted exponent is too large")


def _validate_utc_datetime(value: object, *, field_name: str) -> None:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _datetime_text(value: datetime) -> str:
    _validate_utc_datetime(value, field_name="datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc_datetime_text(
    value: object,
    *,
    field_name: str,
) -> datetime:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO UTC datetime") from exc
    _validate_utc_datetime(parsed, field_name=field_name)
    if _datetime_text(parsed) != value:
        raise ValueError(f"{field_name} must be canonical UTC")
    return parsed


def _validate_hash(value: object, *, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _validate_genome_id(
    value: object,
    *,
    family: StrategyFamily | None = None,
) -> None:
    if type(value) is not str:
        raise TypeError("genome_id must be a string")
    if _GENOME_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("genome_id must have the canonical identity shape")
    if family is not None and not value.startswith(f"genome-{family.value}-"):
        raise ValueError("genome_id does not match family")


def _validate_canonical_decimal_text(
    value: object,
    *,
    field_name: str,
    nonnegative: bool = False,
) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a decimal string") from exc
    if not parsed.is_finite() or _decimal_text(parsed) != value:
        raise ValueError(f"{field_name} must be canonical fixed-point decimal")
    if nonnegative and parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _validate_compiler_money_text(
    value: object,
    *,
    field_name: str,
    positive: bool,
) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    pieces = value.split(".")
    if len(pieces) != 2:
        raise ValueError(f"{field_name} must have exactly two decimals")
    whole, cents = pieces
    if not whole or (whole != "0" and whole.startswith("0")) or not whole.isascii() or not whole.isdigit() or len(cents) != 2 or not cents.isascii() or not cents.isdigit():
        raise ValueError(f"{field_name} must be canonical compiler money")
    parsed = Decimal(value)
    if positive and parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _validate_date_text(value: object, *, field_name: str) -> None:
    if type(value) is not str or _DATE_PATTERN.fullmatch(value) is None:
        raise TypeError(f"{field_name} must be an ISO date string")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string") from exc


@dataclass(frozen=True, slots=True)
class StrategyEvaluationPolicy:
    benchmark_symbol: str
    holding_sessions: int
    commission_bps_per_side: str
    half_spread_bps_per_side: str
    slippage_bps_per_side: str
    round_trip_sides: int
    schema_version: int = field(
        init=False,
        default=STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _validate_symbol(self.benchmark_symbol, field_name="benchmark_symbol")
        if type(self.holding_sessions) is not int:
            raise TypeError("holding_sessions must be an integer")
        if not 1 <= self.holding_sessions <= 252:
            raise ValueError("holding_sessions must be between 1 and 252")
        object.__setattr__(
            self,
            "commission_bps_per_side",
            _canonical_bps(
                self.commission_bps_per_side,
                field_name="commission_bps_per_side",
            ),
        )
        object.__setattr__(
            self,
            "half_spread_bps_per_side",
            _canonical_bps(
                self.half_spread_bps_per_side,
                field_name="half_spread_bps_per_side",
            ),
        )
        object.__setattr__(
            self,
            "slippage_bps_per_side",
            _canonical_bps(
                self.slippage_bps_per_side,
                field_name="slippage_bps_per_side",
            ),
        )
        if type(self.round_trip_sides) is not int:
            raise TypeError("round_trip_sides must be an integer")
        if self.round_trip_sides != 2:
            raise ValueError("round_trip_sides is fixed at 2")
        if self.schema_version != STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION:
            raise ValueError("schema_version is fixed")
        if self.analysis_only is not True:
            raise ValueError("analysis_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("can_submit_orders is fixed")
        if self.round_trip_cost_fraction <= 0:
            raise ValueError("total round-trip cost must be positive")

    @property
    def per_side_cost_fraction(self) -> Decimal:
        with localcontext(_new_decimal_context()):
            return (Decimal(self.commission_bps_per_side) + Decimal(self.half_spread_bps_per_side) + Decimal(self.slippage_bps_per_side)) / Decimal("10000")

    @property
    def round_trip_cost_fraction(self) -> Decimal:
        with localcontext(_new_decimal_context()):
            return self.per_side_cost_fraction * self.round_trip_sides

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "benchmark_symbol": self.benchmark_symbol,
            "holding_sessions": self.holding_sessions,
            "commission_bps_per_side": self.commission_bps_per_side,
            "half_spread_bps_per_side": self.half_spread_bps_per_side,
            "slippage_bps_per_side": self.slippage_bps_per_side,
            "round_trip_sides": self.round_trip_sides,
            "analysis_only": self.analysis_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def load_strategy_evaluation_policy(
    path: str | Path,
) -> StrategyEvaluationPolicy:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_strict_json_object,
    )
    values = _require_exact_fields(
        payload,
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
        },
        field_name="strategy evaluation policy",
    )
    if type(values["schema_version"]) is not int:
        raise TypeError("schema_version must be an integer")
    if values["schema_version"] != STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION:
        raise ValueError("schema_version does not match")
    if values["analysis_only"] is not True:
        raise ValueError("analysis_only must be true")
    if values["execution_authority"] != "none":
        raise ValueError("execution_authority must be none")
    if values["can_submit_orders"] is not False:
        raise ValueError("can_submit_orders must be false")
    return StrategyEvaluationPolicy(
        benchmark_symbol=values["benchmark_symbol"],
        holding_sessions=values["holding_sessions"],
        commission_bps_per_side=values["commission_bps_per_side"],
        half_spread_bps_per_side=values["half_spread_bps_per_side"],
        slippage_bps_per_side=values["slippage_bps_per_side"],
        round_trip_sides=values["round_trip_sides"],
    )


@dataclass(frozen=True, slots=True)
class EvaluationMark:
    symbol: str
    price: Decimal

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol, field_name="symbol")
        _validate_price(self.price, field_name="price")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvaluationMark:
        values = _require_exact_fields(
            payload,
            {"symbol", "price"},
            field_name="evaluation mark",
        )
        price = _validate_canonical_decimal_text(
            values["price"],
            field_name="price",
        )
        return cls(
            symbol=values["symbol"],
            price=price,
        )

    def to_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "price": _decimal_text(self.price)}


def _strategy_observation_from_dict(
    payload: Mapping[str, object],
) -> StrategyObservation:
    values = _require_exact_fields(
        payload,
        {
            "symbol",
            "score",
            "current_price",
            "daily_change_fraction",
            "volume_ratio",
            "time_sensitive",
        },
        field_name="strategy observation",
    )
    if type(values["time_sensitive"]) is not bool:
        raise TypeError("time_sensitive must be a boolean")
    return StrategyObservation(
        symbol=values["symbol"],
        score=_validate_canonical_decimal_text(
            values["score"],
            field_name="score",
        ),
        current_price=_validate_canonical_decimal_text(
            values["current_price"],
            field_name="current_price",
        ),
        daily_change_fraction=_validate_canonical_decimal_text(
            values["daily_change_fraction"],
            field_name="daily_change_fraction",
        ),
        volume_ratio=_validate_canonical_decimal_text(
            values["volume_ratio"],
            field_name="volume_ratio",
        ),
        time_sensitive=values["time_sensitive"],
    )


@dataclass(frozen=True, slots=True)
class EvaluationFrame:
    session_date: date
    effective_at: datetime
    recorded_at: datetime
    market_session: str
    observations: tuple[StrategyObservation, ...]
    marks: tuple[EvaluationMark, ...]
    benchmark_price: Decimal

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise TypeError("session_date must be a date")
        _validate_utc_datetime(self.effective_at, field_name="effective_at")
        _validate_utc_datetime(self.recorded_at, field_name="recorded_at")
        if self.effective_at.date() != self.session_date:
            raise ValueError("effective_at date must match session_date")
        if self.effective_at > self.recorded_at:
            raise ValueError("effective_at cannot be after recorded_at")
        if type(self.market_session) is not str:
            raise TypeError("market_session must be a string")
        if self.market_session not in _TRADEABLE_SESSIONS:
            raise ValueError("market_session must be tradeable")
        if type(self.observations) is not tuple:
            raise TypeError("observations must be an exact tuple")
        if any(type(observation) is not StrategyObservation for observation in self.observations):
            raise TypeError("observations must contain StrategyObservation objects")
        observation_symbols = [observation.symbol for observation in self.observations]
        if len(set(observation_symbols)) != len(observation_symbols):
            raise ValueError("duplicate observation symbol")
        if type(self.marks) is not tuple:
            raise TypeError("marks must be an exact tuple")
        if any(type(mark) is not EvaluationMark for mark in self.marks):
            raise TypeError("marks must contain EvaluationMark objects")
        mark_symbols = [mark.symbol for mark in self.marks]
        if len(set(mark_symbols)) != len(mark_symbols):
            raise ValueError("duplicate mark symbol")
        marks_by_symbol = {mark.symbol: mark.price for mark in self.marks}
        for observation in self.observations:
            if observation.symbol not in marks_by_symbol:
                raise ValueError("every observation must have a same-frame mark")
            if marks_by_symbol[observation.symbol] != observation.current_price:
                raise ValueError("observation price must match same-frame mark")
        _validate_price(self.benchmark_price, field_name="benchmark_price")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvaluationFrame:
        values = _require_exact_fields(
            payload,
            {
                "session_date",
                "effective_at",
                "recorded_at",
                "market_session",
                "observations",
                "marks",
                "benchmark_price",
            },
            field_name="evaluation frame",
        )
        _validate_date_text(
            values["session_date"],
            field_name="session_date",
        )
        if type(values["observations"]) is not list:
            raise TypeError("observations must be a list")
        if type(values["marks"]) is not list:
            raise TypeError("marks must be a list")
        return cls(
            session_date=date.fromisoformat(values["session_date"]),
            effective_at=_parse_utc_datetime_text(
                values["effective_at"],
                field_name="effective_at",
            ),
            recorded_at=_parse_utc_datetime_text(
                values["recorded_at"],
                field_name="recorded_at",
            ),
            market_session=values["market_session"],
            observations=tuple(
                _strategy_observation_from_dict(observation)
                for observation in values["observations"]
            ),
            marks=tuple(
                EvaluationMark.from_dict(mark)
                for mark in values["marks"]
            ),
            benchmark_price=_validate_canonical_decimal_text(
                values["benchmark_price"],
                field_name="benchmark_price",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "effective_at": _datetime_text(self.effective_at),
            "recorded_at": _datetime_text(self.recorded_at),
            "market_session": self.market_session,
            "observations": [
                {
                    "symbol": observation.symbol,
                    "score": _decimal_text(observation.score),
                    "current_price": _decimal_text(observation.current_price),
                    "daily_change_fraction": _decimal_text(observation.daily_change_fraction),
                    "volume_ratio": _decimal_text(observation.volume_ratio),
                    "time_sensitive": observation.time_sensitive,
                }
                for observation in self.observations
            ],
            "marks": [mark.to_dict() for mark in self.marks],
            "benchmark_price": _decimal_text(self.benchmark_price),
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def evaluation_frames_from_dict(
    payload: object,
) -> tuple[EvaluationFrame, ...]:
    if type(payload) is not list:
        raise TypeError("evaluation frames must be a list")
    frames = tuple(EvaluationFrame.from_dict(frame) for frame in payload)
    previous_date: date | None = None
    previous_effective: datetime | None = None
    for frame in frames:
        if previous_date is not None and frame.session_date <= previous_date:
            raise ValueError("evaluation frame dates must be strictly increasing")
        if previous_effective is not None and frame.effective_at <= previous_effective:
            raise ValueError("evaluation frame times must be strictly increasing")
        previous_date = frame.session_date
        previous_effective = frame.effective_at
    return frames


def evaluation_frames_sha256(
    frames: Sequence[EvaluationFrame],
) -> str:
    if isinstance(frames, (str, bytes)) or not isinstance(frames, Sequence):
        raise TypeError("frames must be a sequence")
    frames_snapshot = tuple(frames)
    if any(type(frame) is not EvaluationFrame for frame in frames_snapshot):
        raise TypeError("frames must contain EvaluationFrame objects")
    return _sha256(_canonical_json_bytes([frame.to_dict() for frame in frames_snapshot]))


@dataclass(frozen=True, slots=True)
class EvaluatedTrade:
    genome_id: str
    symbol: str
    entry_session: str
    exit_session: str
    holding_sessions: int
    decision_sha256: str
    decision_limit_price: str
    evaluation_fill_assumption: str
    entry_reference_price: str
    exit_reference_price: str
    entry_budget_usd: str
    entry_cost_usd: str
    entry_exposure_usd: str
    gross_exit_value_usd: str
    exit_cost_usd: str
    net_exit_proceeds_usd: str
    gross_pnl_usd: str
    gross_return_fraction: str
    modeled_round_trip_cost_fraction: str
    realized_cost_drag_fraction: str
    net_return_fraction: str
    pnl_usd: str
    benchmark_return_fraction: str
    excess_return_fraction: str
    won: bool
    false_positive: bool
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _validate_genome_id(self.genome_id)
        _validate_symbol(self.symbol, field_name="symbol")
        _validate_date_text(self.entry_session, field_name="entry_session")
        _validate_date_text(self.exit_session, field_name="exit_session")
        if date.fromisoformat(self.entry_session) >= date.fromisoformat(self.exit_session):
            raise ValueError("entry_session must precede exit_session")
        if type(self.holding_sessions) is not int:
            raise TypeError("holding_sessions must be an integer")
        if self.holding_sessions < 1:
            raise ValueError("holding_sessions must be positive")
        _validate_hash(self.decision_sha256, field_name="decision_sha256")
        if self.evaluation_fill_assumption != "mid_price_counterfactual":
            raise ValueError("evaluation_fill_assumption is fixed")
        _validate_compiler_money_text(
            self.decision_limit_price,
            field_name="decision_limit_price",
            positive=True,
        )
        decimal_fields = {
            "entry_reference_price": self.entry_reference_price,
            "exit_reference_price": self.exit_reference_price,
            "entry_budget_usd": self.entry_budget_usd,
            "entry_cost_usd": self.entry_cost_usd,
            "entry_exposure_usd": self.entry_exposure_usd,
            "gross_exit_value_usd": self.gross_exit_value_usd,
            "exit_cost_usd": self.exit_cost_usd,
            "net_exit_proceeds_usd": self.net_exit_proceeds_usd,
            "gross_pnl_usd": self.gross_pnl_usd,
            "gross_return_fraction": self.gross_return_fraction,
            "modeled_round_trip_cost_fraction": (self.modeled_round_trip_cost_fraction),
            "realized_cost_drag_fraction": self.realized_cost_drag_fraction,
            "net_return_fraction": self.net_return_fraction,
            "pnl_usd": self.pnl_usd,
            "benchmark_return_fraction": self.benchmark_return_fraction,
            "excess_return_fraction": self.excess_return_fraction,
        }
        values = {
            name: _validate_canonical_decimal_text(
                value,
                field_name=name,
                nonnegative=name
                in {
                    "decision_limit_price",
                    "entry_reference_price",
                    "exit_reference_price",
                    "entry_budget_usd",
                    "entry_cost_usd",
                    "entry_exposure_usd",
                    "gross_exit_value_usd",
                    "exit_cost_usd",
                    "net_exit_proceeds_usd",
                    "modeled_round_trip_cost_fraction",
                    "realized_cost_drag_fraction",
                },
            )
            for name, value in decimal_fields.items()
        }
        if values["entry_reference_price"] <= 0:
            raise ValueError("entry_reference_price must be positive")
        if values["exit_reference_price"] <= 0:
            raise ValueError("exit_reference_price must be positive")
        if values["entry_budget_usd"] <= 0:
            raise ValueError("entry_budget_usd must be positive")
        with localcontext(_new_decimal_context()):
            budget = values["entry_budget_usd"]
            entry_price = values["entry_reference_price"]
            exit_price = values["exit_reference_price"]
            entry_cost = values["entry_cost_usd"]
            exposure = values["entry_exposure_usd"]
            gross_exit = values["gross_exit_value_usd"]
            exit_cost = values["exit_cost_usd"]
            proceeds = values["net_exit_proceeds_usd"]
            gross_return = exit_price / entry_price - 1
            net_return = proceeds / budget - 1
            expected = {
                "entry_exposure_usd": budget - entry_cost,
                "gross_exit_value_usd": exposure / entry_price * exit_price,
                "net_exit_proceeds_usd": gross_exit - exit_cost,
                "gross_return_fraction": gross_return,
                "gross_pnl_usd": budget * gross_return,
                "net_return_fraction": net_return,
                "realized_cost_drag_fraction": gross_return - net_return,
                "pnl_usd": proceeds - budget,
                "excess_return_fraction": (net_return - values["benchmark_return_fraction"]),
            }
            for name, expected_value in expected.items():
                if values[name] != expected_value:
                    raise ValueError(f"{name} does not recompute exactly")
            per_side = entry_cost / budget
            if exit_cost != gross_exit * per_side:
                raise ValueError("exit_cost_usd does not match entry cost rate")
            if values["modeled_round_trip_cost_fraction"] != per_side * Decimal("2"):
                raise ValueError("modeled_round_trip_cost_fraction does not match costs")
        if type(self.won) is not bool or type(self.false_positive) is not bool:
            raise TypeError("trade outcome flags must be booleans")
        if self.won is not (values["net_return_fraction"] > 0):
            raise ValueError("won does not match net return")
        if self.false_positive is not (values["net_return_fraction"] <= 0):
            raise ValueError("false_positive does not match net return")
        if self.analysis_only is not True:
            raise ValueError("analysis_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("can_submit_orders is fixed")

    def to_dict(self) -> dict[str, object]:
        return {item.name: getattr(self, item.name) for item in self.__dataclass_fields__.values()}

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> EvaluatedTrade:
        expected = set(cls.__dataclass_fields__)
        values = _require_exact_fields(
            payload,
            expected,
            field_name="evaluated trade",
        )
        if values["analysis_only"] is not True:
            raise ValueError("analysis_only must be true")
        if values["execution_authority"] != "none":
            raise ValueError("execution_authority must be none")
        if values["can_submit_orders"] is not False:
            raise ValueError("can_submit_orders must be false")
        constructor_fields = expected - {
            "analysis_only",
            "execution_authority",
            "can_submit_orders",
        }
        return cls(**{name: values[name] for name in constructor_fields})


def _window_binding_payload(
    *,
    evaluator_version: str,
    genome_canonical_sha256: str,
    evolution_policy_sha256: str,
    evaluation_policy_sha256: str,
    input_frames_sha256: str,
    ordered_decision_sha256s: Sequence[str],
    evaluation_as_of: str,
) -> dict[str, object]:
    return {
        "evaluator_version": evaluator_version,
        "genome_canonical_sha256": genome_canonical_sha256,
        "evolution_policy_sha256": evolution_policy_sha256,
        "evaluation_policy_sha256": evaluation_policy_sha256,
        "input_frames_sha256": input_frames_sha256,
        "ordered_decision_sha256s": list(ordered_decision_sha256s),
        "evaluation_as_of": evaluation_as_of,
    }


@dataclass(frozen=True, slots=True)
class GenomeWindowResult:
    window_id: str
    genome_id: str
    family: StrategyFamily
    evaluator_version: str
    window_start: str
    window_end: str
    evaluation_as_of: str
    tracked_sessions: int
    starting_cash_usd: str
    gross_ending_equity_usd: str
    ending_equity_usd: str
    closed_trade_count: int
    winning_trade_count: int
    false_positive_count: int
    gross_return_fraction: str
    net_return_fraction: str
    benchmark_return_fraction: str
    benchmark_excess_return_fraction: str
    max_drawdown_fraction: str
    positive_after_costs: bool
    trades: tuple[EvaluatedTrade, ...]
    equity_curve_usd: tuple[str, ...]
    input_frames_sha256: str
    genome_canonical_sha256: str
    ordered_decision_sha256s: tuple[str, ...]
    evolution_policy_sha256: str
    evaluation_policy_sha256: str
    schema_version: int = field(
        init=False,
        default=GENOME_WINDOW_RESULT_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _validate_hash(self.window_id, field_name="window_id")
        if type(self.family) is not StrategyFamily:
            raise TypeError("family must be a StrategyFamily")
        _validate_genome_id(self.genome_id, family=self.family)
        if self.evaluator_version != EVALUATOR_VERSION:
            raise ValueError("evaluator_version is fixed")
        _validate_date_text(self.window_start, field_name="window_start")
        _validate_date_text(self.window_end, field_name="window_end")
        if date.fromisoformat(self.window_start) >= date.fromisoformat(self.window_end):
            raise ValueError("window_start must precede window_end")
        try:
            parsed_as_of = datetime.fromisoformat(self.evaluation_as_of.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("evaluation_as_of must be an ISO UTC datetime") from exc
        _validate_utc_datetime(parsed_as_of, field_name="evaluation_as_of")
        if _datetime_text(parsed_as_of) != self.evaluation_as_of:
            raise ValueError("evaluation_as_of must be canonical UTC")
        for name, value in {
            "tracked_sessions": self.tracked_sessions,
            "closed_trade_count": self.closed_trade_count,
            "winning_trade_count": self.winning_trade_count,
            "false_positive_count": self.false_positive_count,
        }.items():
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.tracked_sessions < 2:
            raise ValueError("tracked_sessions must be at least two")
        if type(self.trades) is not tuple or any(type(trade) is not EvaluatedTrade for trade in self.trades):
            raise TypeError("trades must be an exact tuple of EvaluatedTrade")
        if self.closed_trade_count != len(self.trades):
            raise ValueError("closed_trade_count does not match trades")
        if type(self.ordered_decision_sha256s) is not tuple:
            raise TypeError("ordered_decision_sha256s must be an exact tuple")
        for digest in self.ordered_decision_sha256s:
            _validate_hash(digest, field_name="ordered decision digest")
        if len(self.trades) > len(self.ordered_decision_sha256s):
            raise ValueError("trade count cannot exceed decision count")
        if self.winning_trade_count != sum(trade.won for trade in self.trades):
            raise ValueError("winning_trade_count does not match trades")
        if self.false_positive_count != sum(trade.false_positive for trade in self.trades):
            raise ValueError("false_positive_count does not match trades")
        if any(trade.genome_id != self.genome_id for trade in self.trades):
            raise ValueError("trade genome_id does not match window")
        window_start = date.fromisoformat(self.window_start)
        window_end = date.fromisoformat(self.window_end)
        previous_exit: date | None = None
        for trade in self.trades:
            entry_session = date.fromisoformat(trade.entry_session)
            exit_session = date.fromisoformat(trade.exit_session)
            if entry_session < window_start or exit_session > window_end:
                raise ValueError("trade sessions must remain inside the window")
            if previous_exit is not None and entry_session < previous_exit:
                raise ValueError(
                    "trades must be chronological and may not overlap"
                )
            previous_exit = exit_session
        decision_index = 0
        for trade in self.trades:
            while (
                decision_index < len(self.ordered_decision_sha256s)
                and self.ordered_decision_sha256s[decision_index]
                != trade.decision_sha256
            ):
                decision_index += 1
            if decision_index == len(self.ordered_decision_sha256s):
                raise ValueError(
                    "trade decision hashes must be an ordered subsequence"
                )
            decision_index += 1
        result_values = {
            name: _validate_canonical_decimal_text(
                getattr(self, name),
                field_name=name,
                nonnegative=name
                in {
                    "starting_cash_usd",
                    "gross_ending_equity_usd",
                    "ending_equity_usd",
                },
            )
            for name in (
                "starting_cash_usd",
                "gross_ending_equity_usd",
                "ending_equity_usd",
                "gross_return_fraction",
                "net_return_fraction",
                "benchmark_return_fraction",
                "benchmark_excess_return_fraction",
                "max_drawdown_fraction",
            )
        }
        if result_values["starting_cash_usd"] <= 0:
            raise ValueError("starting_cash_usd must be positive")
        if type(self.equity_curve_usd) is not tuple:
            raise TypeError("equity_curve_usd must be an exact tuple")
        curve = tuple(
            _validate_canonical_decimal_text(
                value,
                field_name="equity_curve_usd",
                nonnegative=True,
            )
            for value in self.equity_curve_usd
        )
        if len(curve) != self.tracked_sessions + 1:
            raise ValueError("equity_curve_usd must contain start plus each frame end")
        if curve[0] != result_values["starting_cash_usd"]:
            raise ValueError("equity curve must begin with starting cash")
        if curve[-1] != result_values["ending_equity_usd"]:
            raise ValueError("equity curve must end with ending equity")
        with localcontext(_new_decimal_context()):
            starting = result_values["starting_cash_usd"]
            replayed_cash = starting
            for trade in self.trades:
                entry_budget = Decimal(trade.entry_budget_usd)
                if entry_budget > replayed_cash:
                    raise ValueError(
                        "trade entry budget exceeds then-available cash"
                    )
                if replayed_cash - entry_budget < 0:
                    raise ValueError("virtual cash cannot be negative at entry")
                replayed_cash += Decimal(trade.pnl_usd)
                if replayed_cash < 0:
                    raise ValueError("virtual cash cannot be negative after close")
            if replayed_cash != result_values["ending_equity_usd"]:
                raise ValueError(
                    "ending_equity_usd does not match sequential cash replay"
                )
            expected_gross = starting + sum(
                (Decimal(trade.gross_pnl_usd) for trade in self.trades),
                start=Decimal("0"),
            )
            expected = {
                "gross_ending_equity_usd": expected_gross,
                "gross_return_fraction": expected_gross / starting - 1,
                "net_return_fraction": (result_values["ending_equity_usd"] / starting - 1),
                "benchmark_excess_return_fraction": (result_values["net_return_fraction"] - result_values["benchmark_return_fraction"]),
                "max_drawdown_fraction": _maximum_drawdown(curve),
            }
            for name, expected_value in expected.items():
                if result_values[name] != expected_value:
                    raise ValueError(f"{name} does not recompute exactly")
        if type(self.positive_after_costs) is not bool:
            raise TypeError("positive_after_costs must be a boolean")
        if self.positive_after_costs is not (result_values["net_return_fraction"] > 0):
            raise ValueError("positive_after_costs does not match net return")
        for name in (
            "input_frames_sha256",
            "genome_canonical_sha256",
            "evolution_policy_sha256",
            "evaluation_policy_sha256",
        ):
            _validate_hash(getattr(self, name), field_name=name)
        expected_window_id = _sha256(
            _canonical_json_bytes(
                _window_binding_payload(
                    evaluator_version=self.evaluator_version,
                    genome_canonical_sha256=self.genome_canonical_sha256,
                    evolution_policy_sha256=self.evolution_policy_sha256,
                    evaluation_policy_sha256=self.evaluation_policy_sha256,
                    input_frames_sha256=self.input_frames_sha256,
                    ordered_decision_sha256s=self.ordered_decision_sha256s,
                    evaluation_as_of=self.evaluation_as_of,
                )
            )
        )
        if self.window_id != expected_window_id:
            raise ValueError("window_id does not match bound inputs")
        if self.schema_version != GENOME_WINDOW_RESULT_SCHEMA_VERSION:
            raise ValueError("schema_version is fixed")
        if self.analysis_only is not True:
            raise ValueError("analysis_only is fixed")
        if self.paper_only is not True:
            raise ValueError("paper_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("can_submit_orders is fixed")

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "genome_id": self.genome_id,
            "family": self.family.value,
            "evaluator_version": self.evaluator_version,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "evaluation_as_of": self.evaluation_as_of,
            "tracked_sessions": self.tracked_sessions,
            "starting_cash_usd": self.starting_cash_usd,
            "gross_ending_equity_usd": self.gross_ending_equity_usd,
            "ending_equity_usd": self.ending_equity_usd,
            "closed_trade_count": self.closed_trade_count,
            "winning_trade_count": self.winning_trade_count,
            "false_positive_count": self.false_positive_count,
            "gross_return_fraction": self.gross_return_fraction,
            "net_return_fraction": self.net_return_fraction,
            "benchmark_return_fraction": self.benchmark_return_fraction,
            "benchmark_excess_return_fraction": (self.benchmark_excess_return_fraction),
            "max_drawdown_fraction": self.max_drawdown_fraction,
            "positive_after_costs": self.positive_after_costs,
            "trades": [trade.to_dict() for trade in self.trades],
            "equity_curve_usd": list(self.equity_curve_usd),
            "input_frames_sha256": self.input_frames_sha256,
            "genome_canonical_sha256": self.genome_canonical_sha256,
            "ordered_decision_sha256s": list(self.ordered_decision_sha256s),
            "evolution_policy_sha256": self.evolution_policy_sha256,
            "evaluation_policy_sha256": self.evaluation_policy_sha256,
            "schema_version": self.schema_version,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> GenomeWindowResult:
        expected = set(cls.__dataclass_fields__)
        values = _require_exact_fields(
            payload,
            expected,
            field_name="genome window result",
        )
        if type(values["schema_version"]) is not int:
            raise TypeError("schema_version must be an integer")
        if values["schema_version"] != GENOME_WINDOW_RESULT_SCHEMA_VERSION:
            raise ValueError("schema_version does not match")
        if values["analysis_only"] is not True:
            raise ValueError("analysis_only must be true")
        if values["paper_only"] is not True:
            raise ValueError("paper_only must be true")
        if values["execution_authority"] != "none":
            raise ValueError("execution_authority must be none")
        if values["can_submit_orders"] is not False:
            raise ValueError("can_submit_orders must be false")
        if type(values["family"]) is not str:
            raise TypeError("family must be a string")
        try:
            family = StrategyFamily(values["family"])
        except ValueError as exc:
            raise ValueError("family is not recognized") from exc
        if type(values["trades"]) is not list:
            raise TypeError("trades must be a list")
        if type(values["equity_curve_usd"]) is not list:
            raise TypeError("equity_curve_usd must be a list")
        if type(values["ordered_decision_sha256s"]) is not list:
            raise TypeError("ordered_decision_sha256s must be a list")
        excluded = {
            "schema_version",
            "analysis_only",
            "paper_only",
            "execution_authority",
            "can_submit_orders",
            "family",
            "trades",
            "equity_curve_usd",
            "ordered_decision_sha256s",
        }
        constructor = {name: values[name] for name in expected - excluded}
        return cls(
            **constructor,
            family=family,
            trades=tuple(EvaluatedTrade.from_dict(trade) for trade in values["trades"]),
            equity_curve_usd=tuple(values["equity_curve_usd"]),
            ordered_decision_sha256s=tuple(values["ordered_decision_sha256s"]),
        )


@dataclass(frozen=True, slots=True)
class _OpenPosition:
    symbol: str
    entry_frame_index: int
    entry_session: str
    decision_sha256: str
    decision_limit_price: str
    entry_reference_price: Decimal
    entry_benchmark_price: Decimal
    entry_budget: Decimal
    entry_cost: Decimal
    entry_exposure: Decimal
    fractional_shares: Decimal


def _marks_by_symbol(frame: EvaluationFrame) -> dict[str, Decimal]:
    return {mark.symbol: mark.price for mark in frame.marks}


def _maximum_drawdown(equity_curve: Sequence[Decimal]) -> Decimal:
    peak = equity_curve[0]
    maximum_drawdown = Decimal("0")
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        drawdown = equity / peak - 1
        if drawdown < maximum_drawdown:
            maximum_drawdown = drawdown
    return maximum_drawdown


def _validate_window_inputs(
    frames: tuple[EvaluationFrame, ...],
    *,
    holding_sessions: int,
    evaluation_as_of: datetime,
) -> None:
    if len(frames) < holding_sessions + 1:
        raise ValueError("insufficient frame horizon")
    previous_date: date | None = None
    previous_effective: datetime | None = None
    for frame in frames:
        if type(frame) is not EvaluationFrame:
            raise TypeError("frames must contain EvaluationFrame objects")
        if previous_date is not None and frame.session_date <= previous_date:
            raise ValueError("session dates must be unique and increasing")
        if previous_effective is not None and frame.effective_at <= previous_effective:
            raise ValueError("effective times must be strictly increasing")
        if frame.recorded_at > evaluation_as_of:
            raise ValueError("frame recorded_at exceeds evaluation_as_of")
        previous_date = frame.session_date
        previous_effective = frame.effective_at


def evaluate_genome_window(
    genome: StrategyGenome,
    evolution_policy: StrategyEvolutionPolicy,
    evaluation_policy: StrategyEvaluationPolicy,
    frames: Sequence[EvaluationFrame],
    *,
    evaluation_as_of: datetime,
) -> GenomeWindowResult:
    if type(genome) is not StrategyGenome:
        raise TypeError("genome must be a StrategyGenome")
    if type(evolution_policy) is not StrategyEvolutionPolicy:
        raise TypeError("evolution_policy must be a StrategyEvolutionPolicy")
    if type(evaluation_policy) is not StrategyEvaluationPolicy:
        raise TypeError("evaluation_policy must be a StrategyEvaluationPolicy")
    if isinstance(frames, (str, bytes)) or not isinstance(frames, Sequence):
        raise TypeError("frames must be a sequence")
    frames_snapshot = tuple(frames)
    _validate_utc_datetime(
        evaluation_as_of,
        field_name="evaluation_as_of",
    )
    _validate_window_inputs(
        frames_snapshot,
        holding_sessions=evaluation_policy.holding_sessions,
        evaluation_as_of=evaluation_as_of,
    )

    frame_digest = evaluation_frames_sha256(frames_snapshot)
    genome_digest = _sha256(genome.canonical_json_bytes())
    evolution_policy_digest = _sha256(evolution_policy.canonical_json_bytes())
    evaluation_policy_digest = _sha256(evaluation_policy.canonical_json_bytes())
    decision_digests: list[str] = []
    trades: list[EvaluatedTrade] = []

    with localcontext(_new_decimal_context()):
        starting_cash = Decimal(evolution_policy.experiment_starting_cash_usd)
        cash = starting_cash
        per_side_cost = evaluation_policy.per_side_cost_fraction
        round_trip_cost = evaluation_policy.round_trip_cost_fraction
        open_position: _OpenPosition | None = None
        equity_curve = [starting_cash]

        for frame_index, frame in enumerate(frames_snapshot):
            marks = _marks_by_symbol(frame)

            if open_position is not None and frame_index - open_position.entry_frame_index == evaluation_policy.holding_sessions:
                if open_position.symbol not in marks:
                    raise ValueError("missing mark for open position")
                exit_price = marks[open_position.symbol]
                gross_exit = open_position.fractional_shares * exit_price
                exit_cost = gross_exit * per_side_cost
                proceeds = gross_exit - exit_cost
                if proceeds < 0:
                    raise ValueError("modeled exit proceeds cannot be negative")
                cash += proceeds
                gross_return = exit_price / open_position.entry_reference_price - 1
                net_return = proceeds / open_position.entry_budget - 1
                benchmark_return = frame.benchmark_price / open_position.entry_benchmark_price - 1
                trade = EvaluatedTrade(
                    genome_id=genome.genome_id,
                    symbol=open_position.symbol,
                    entry_session=open_position.entry_session,
                    exit_session=frame.session_date.isoformat(),
                    holding_sessions=evaluation_policy.holding_sessions,
                    decision_sha256=open_position.decision_sha256,
                    decision_limit_price=(open_position.decision_limit_price),
                    evaluation_fill_assumption="mid_price_counterfactual",
                    entry_reference_price=_decimal_text(open_position.entry_reference_price),
                    exit_reference_price=_decimal_text(exit_price),
                    entry_budget_usd=_decimal_text(open_position.entry_budget),
                    entry_cost_usd=_decimal_text(open_position.entry_cost),
                    entry_exposure_usd=_decimal_text(open_position.entry_exposure),
                    gross_exit_value_usd=_decimal_text(gross_exit),
                    exit_cost_usd=_decimal_text(exit_cost),
                    net_exit_proceeds_usd=_decimal_text(proceeds),
                    gross_pnl_usd=_decimal_text(open_position.entry_budget * gross_return),
                    gross_return_fraction=_decimal_text(gross_return),
                    modeled_round_trip_cost_fraction=_decimal_text(round_trip_cost),
                    realized_cost_drag_fraction=_decimal_text(gross_return - net_return),
                    net_return_fraction=_decimal_text(net_return),
                    pnl_usd=_decimal_text(proceeds - open_position.entry_budget),
                    benchmark_return_fraction=_decimal_text(benchmark_return),
                    excess_return_fraction=_decimal_text(net_return - benchmark_return),
                    won=net_return > 0,
                    false_positive=net_return <= 0,
                )
                trades.append(trade)
                open_position = None

            enough_frames_remain = frame_index + evaluation_policy.holding_sessions < len(frames_snapshot)
            if open_position is None and enough_frames_remain:
                compiler_cash = cash.quantize(_CENT, rounding=ROUND_DOWN)
                decision = compile_genome_paper_decision(
                    genome,
                    evolution_policy,
                    frame.observations,
                    PaperCandidateState(
                        cash_usd=compiler_cash,
                        reserved_buy_notional_usd=Decimal("0.00"),
                        held_symbols=(),
                        open_buy_symbols=(),
                    ),
                    market_session=frame.market_session,
                )
                decision_digest = _sha256(decision.canonical_json_bytes())
                decision_digests.append(decision_digest)
                if decision.action is PaperDecisionAction.BUY:
                    if decision.symbol is None or decision.limit_price is None:
                        raise ValueError("buy decision lacks required fields")
                    observation_by_symbol = {observation.symbol: observation for observation in frame.observations}
                    selected = observation_by_symbol[decision.symbol]
                    budget = Decimal(decision.notional_usd)
                    if budget > cash:
                        raise ValueError("compiler budget exceeds isolated virtual cash")
                    entry_cost = budget * per_side_cost
                    exposure = budget - entry_cost
                    if entry_cost < 0 or exposure < 0:
                        raise ValueError("modeled entry components cannot be negative")
                    shares = exposure / selected.current_price
                    cash -= budget
                    open_position = _OpenPosition(
                        symbol=selected.symbol,
                        entry_frame_index=frame_index,
                        entry_session=frame.session_date.isoformat(),
                        decision_sha256=decision_digest,
                        decision_limit_price=decision.limit_price,
                        entry_reference_price=selected.current_price,
                        entry_benchmark_price=frame.benchmark_price,
                        entry_budget=budget,
                        entry_cost=entry_cost,
                        entry_exposure=exposure,
                        fractional_shares=shares,
                    )

            marked_equity = cash
            if open_position is not None:
                if open_position.symbol not in marks:
                    raise ValueError("missing mark for open position")
                gross_mark_value = open_position.fractional_shares * marks[open_position.symbol]
                marked_equity += gross_mark_value * (Decimal("1") - per_side_cost)
            if marked_equity < 0:
                raise ValueError("marked virtual equity cannot be negative")
            equity_curve.append(marked_equity)

        if open_position is not None:
            raise ValueError("evaluation left an orphan open position")

        gross_ending_equity = starting_cash + sum(
            (Decimal(trade.gross_pnl_usd) for trade in trades),
            start=Decimal("0"),
        )
        gross_return = gross_ending_equity / starting_cash - 1
        net_return = cash / starting_cash - 1
        benchmark_return = frames_snapshot[-1].benchmark_price / frames_snapshot[0].benchmark_price - 1
        maximum_drawdown = _maximum_drawdown(equity_curve)

        evaluation_as_of_text = _datetime_text(evaluation_as_of)
        binding = _window_binding_payload(
            evaluator_version=EVALUATOR_VERSION,
            genome_canonical_sha256=genome_digest,
            evolution_policy_sha256=evolution_policy_digest,
            evaluation_policy_sha256=evaluation_policy_digest,
            input_frames_sha256=frame_digest,
            ordered_decision_sha256s=decision_digests,
            evaluation_as_of=evaluation_as_of_text,
        )
        window_id = _sha256(_canonical_json_bytes(binding))

        return GenomeWindowResult(
            window_id=window_id,
            genome_id=genome.genome_id,
            family=genome.family,
            evaluator_version=EVALUATOR_VERSION,
            window_start=frames_snapshot[0].session_date.isoformat(),
            window_end=frames_snapshot[-1].session_date.isoformat(),
            evaluation_as_of=evaluation_as_of_text,
            tracked_sessions=len(frames_snapshot),
            starting_cash_usd=_decimal_text(starting_cash),
            gross_ending_equity_usd=_decimal_text(gross_ending_equity),
            ending_equity_usd=_decimal_text(cash),
            closed_trade_count=len(trades),
            winning_trade_count=sum(trade.won for trade in trades),
            false_positive_count=sum(trade.false_positive for trade in trades),
            gross_return_fraction=_decimal_text(gross_return),
            net_return_fraction=_decimal_text(net_return),
            benchmark_return_fraction=_decimal_text(benchmark_return),
            benchmark_excess_return_fraction=_decimal_text(net_return - benchmark_return),
            max_drawdown_fraction=_decimal_text(maximum_drawdown),
            positive_after_costs=net_return > 0,
            trades=tuple(trades),
            equity_curve_usd=tuple(_decimal_text(value) for value in equity_curve),
            input_frames_sha256=frame_digest,
            genome_canonical_sha256=genome_digest,
            ordered_decision_sha256s=tuple(decision_digests),
            evolution_policy_sha256=evolution_policy_digest,
            evaluation_policy_sha256=evaluation_policy_digest,
        )
