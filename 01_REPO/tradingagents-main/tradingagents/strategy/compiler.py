"""Pure compilation of inert strategy genomes into paper-only decisions."""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from tradingagents.strategy.genome import (
    CatalystRelativeStrengthParameters,
    CurrentAggressiveParameters,
    PullbackSupportParameters,
    StrategyEvolutionPolicy,
    StrategyFamily,
    StrategyGenome,
)

PAPER_DECISION_SCHEMA_VERSION = 1

_MARKET_SESSIONS = frozenset(
    {"pre_open", "open_window", "regular", "pre_close", "closed"}
)
_REASON_CODES = frozenset(
    {
        "genome_hold_cash",
        "market_closed",
        "policy_disabled",
        "insufficient_virtual_cash",
        "no_eligible_observation",
        "eligible_current_aggressive",
        "eligible_pullback_support",
        "eligible_catalyst_relative_strength",
    }
)
_BUY_REASON_BY_FAMILY = {
    StrategyFamily.CURRENT_AGGRESSIVE: "eligible_current_aggressive",
    StrategyFamily.PULLBACK_SUPPORT: "eligible_pullback_support",
    StrategyFamily.CATALYST_RELATIVE_STRENGTH: (
        "eligible_catalyst_relative_strength"
    ),
}
_HOLD_REASONS = frozenset(
    {
        "genome_hold_cash",
        "market_closed",
        "policy_disabled",
        "insufficient_virtual_cash",
        "no_eligible_observation",
    }
)
_CENT = Decimal("0.01")


class PaperDecisionAction(str, enum.Enum):
    BUY = "buy"
    HOLD_CASH = "hold-cash"


def _validate_symbol(value: object, *, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value.strip() != value:
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    if not 1 <= len(value) <= 15 or not "A" <= value[0] <= "Z":
        raise ValueError(f"{field_name} must be an uppercase ASCII ticker token")
    if any(
        not (
            "A" <= character <= "Z"
            or "0" <= character <= "9"
            or character in ".-"
        )
        for character in value[1:]
    ):
        raise ValueError(f"{field_name} must be an uppercase ASCII ticker token")


def _validate_decimal(
    value: object,
    *,
    field_name: str,
    minimum: Decimal,
    maximum: Decimal | None = None,
    positive: bool = False,
) -> None:
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise ValueError(f"{field_name} must be at least {minimum}")
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum}"
        )


def _validate_money_decimal(value: object, *, field_name: str) -> None:
    _validate_decimal(
        value,
        field_name=field_name,
        minimum=Decimal("0"),
    )
    exponent = value.as_tuple().exponent
    if type(exponent) is not int or exponent < -2:
        raise ValueError(f"{field_name} must have two-decimal precision or less")


def _validate_symbol_tuple(value: object, *, field_name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be an exact tuple")
    for symbol in value:
        _validate_symbol(symbol, field_name=field_name)
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} must not contain duplicates")


def _validate_market_session(value: object) -> None:
    if type(value) is not str:
        raise TypeError("market_session must be a string")
    if value not in _MARKET_SESSIONS:
        raise ValueError(f"unknown market_session: {value}")


def _validate_canonical_money_string(
    value: object,
    *,
    field_name: str,
    positive: bool,
) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    pieces = value.split(".")
    if len(pieces) != 2:
        raise ValueError(f"{field_name} must contain exactly two decimals")
    whole, cents = pieces
    if (
        (whole != "0" and (not whole or whole[0] == "0"))
        or not whole.isascii()
        or not whole.isdigit()
        or len(cents) != 2
        or not cents.isascii()
        or not cents.isdigit()
    ):
        raise ValueError(f"{field_name} must be a canonical money string")
    if positive and Decimal(value) <= 0:
        raise ValueError(f"{field_name} must be positive")


def _validate_genome_identity(genome_id: object, family: object) -> None:
    if type(family) is not StrategyFamily:
        raise TypeError("family must be a StrategyFamily")
    if type(genome_id) is not str:
        raise TypeError("genome_id must be a string")
    prefix = f"genome-{family.value}-"
    digest = genome_id.removeprefix(prefix)
    if (
        not genome_id.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("genome_id shape does not match family")


@dataclass(frozen=True, slots=True)
class StrategyObservation:
    symbol: str
    score: Decimal
    current_price: Decimal
    daily_change_fraction: Decimal = Decimal("0")
    volume_ratio: Decimal = Decimal("1")
    time_sensitive: bool = False

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol, field_name="symbol")
        _validate_decimal(
            self.score,
            field_name="score",
            minimum=Decimal("0"),
            maximum=Decimal("1"),
        )
        _validate_decimal(
            self.current_price,
            field_name="current_price",
            minimum=Decimal("0"),
            positive=True,
        )
        _validate_decimal(
            self.daily_change_fraction,
            field_name="daily_change_fraction",
            minimum=Decimal("-1"),
            maximum=Decimal("10"),
        )
        _validate_decimal(
            self.volume_ratio,
            field_name="volume_ratio",
            minimum=Decimal("0"),
            maximum=Decimal("1000000"),
        )
        if type(self.time_sensitive) is not bool:
            raise TypeError("time_sensitive must be a boolean")


@dataclass(frozen=True, slots=True)
class PaperCandidateState:
    cash_usd: Decimal
    reserved_buy_notional_usd: Decimal
    held_symbols: tuple[str, ...]
    open_buy_symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_money_decimal(self.cash_usd, field_name="cash_usd")
        _validate_money_decimal(
            self.reserved_buy_notional_usd,
            field_name="reserved_buy_notional_usd",
        )
        _validate_symbol_tuple(self.held_symbols, field_name="held_symbols")
        _validate_symbol_tuple(
            self.open_buy_symbols,
            field_name="open_buy_symbols",
        )


@dataclass(frozen=True, slots=True)
class GenomePaperDecision:
    genome_id: str
    family: StrategyFamily
    action: PaperDecisionAction
    symbol: str | None
    notional_usd: str
    limit_price: str | None
    market_session: str
    extended_hours: bool
    reason_code: str
    rejected_observation_count: int
    schema_version: int = field(
        init=False,
        default=PAPER_DECISION_SCHEMA_VERSION,
    )
    analysis_only: bool = field(init=False, default=True)
    paper_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _validate_genome_identity(self.genome_id, self.family)
        if type(self.action) is not PaperDecisionAction:
            raise TypeError("action must be a PaperDecisionAction")
        _validate_market_session(self.market_session)
        if type(self.extended_hours) is not bool:
            raise TypeError("extended_hours must be a boolean")
        if self.extended_hours is not (self.market_session == "pre_open"):
            raise ValueError("extended_hours does not match market_session")
        if type(self.reason_code) is not str:
            raise TypeError("reason_code must be a string")
        if self.reason_code not in _REASON_CODES:
            raise ValueError("reason_code is not allowed")
        if (
            type(self.rejected_observation_count) is not int
            or self.rejected_observation_count != 0
        ):
            raise ValueError("rejected_observation_count is fixed at zero")
        if self.schema_version != PAPER_DECISION_SCHEMA_VERSION:
            raise ValueError("schema_version is fixed")
        if self.analysis_only is not True:
            raise ValueError("analysis_only is fixed")
        if self.paper_only is not True:
            raise ValueError("paper_only is fixed")
        if self.execution_authority != "none":
            raise ValueError("execution_authority is fixed")
        if self.can_submit_orders is not False:
            raise ValueError("can_submit_orders is fixed")

        if self.action is PaperDecisionAction.HOLD_CASH:
            if self.symbol is not None:
                raise ValueError("hold-cash symbol must be null")
            if self.notional_usd != "0.00":
                raise ValueError("hold-cash notional_usd must be 0.00")
            if self.limit_price is not None:
                raise ValueError("hold-cash limit_price must be null")
            if self.reason_code not in _HOLD_REASONS:
                raise ValueError("hold-cash reason_code does not match action")
            if (
                self.reason_code == "genome_hold_cash"
                and self.family is not StrategyFamily.HOLD_CASH
            ):
                raise ValueError("genome_hold_cash reason requires hold family")
            if (
                self.family is StrategyFamily.HOLD_CASH
                and self.reason_code != "genome_hold_cash"
            ):
                raise ValueError("hold family requires genome_hold_cash reason")
            return

        if self.family is StrategyFamily.HOLD_CASH:
            raise ValueError("hold family cannot produce a buy")
        if self.market_session == "closed":
            raise ValueError("closed market cannot produce a buy")
        _validate_symbol(self.symbol, field_name="symbol")
        _validate_canonical_money_string(
            self.notional_usd,
            field_name="notional_usd",
            positive=True,
        )
        _validate_canonical_money_string(
            self.limit_price,
            field_name="limit_price",
            positive=True,
        )
        if self.reason_code != _BUY_REASON_BY_FAMILY[self.family]:
            raise ValueError("buy reason_code does not match family")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "genome_id": self.genome_id,
            "family": self.family.value,
            "action": self.action.value,
            "symbol": self.symbol,
            "notional_usd": self.notional_usd,
            "limit_price": self.limit_price,
            "market_session": self.market_session,
            "extended_hours": self.extended_hours,
            "reason_code": self.reason_code,
            "rejected_observation_count": self.rejected_observation_count,
            "analysis_only": self.analysis_only,
            "paper_only": self.paper_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def canonical_json_bytes(self) -> bytes:
        limit_price = (
            "null" if self.limit_price is None else f'"{self.limit_price}"'
        )
        symbol = "null" if self.symbol is None else f'"{self.symbol}"'
        return (
            f'{{"action":"{self.action.value}"'
            ',"analysis_only":true'
            ',"can_submit_orders":false'
            ',"execution_authority":"none"'
            f',"extended_hours":{str(self.extended_hours).lower()}'
            f',"family":"{self.family.value}"'
            f',"genome_id":"{self.genome_id}"'
            f',"limit_price":{limit_price}'
            f',"market_session":"{self.market_session}"'
            f',"notional_usd":"{self.notional_usd}"'
            ',"paper_only":true'
            f',"reason_code":"{self.reason_code}"'
            ',"rejected_observation_count":0'
            f',"schema_version":{self.schema_version}'
            f',"symbol":{symbol}'
            "}"
        ).encode()


def _hold_decision(
    genome: StrategyGenome,
    *,
    market_session: str,
    reason_code: str,
) -> GenomePaperDecision:
    return GenomePaperDecision(
        genome_id=genome.genome_id,
        family=genome.family,
        action=PaperDecisionAction.HOLD_CASH,
        symbol=None,
        notional_usd="0.00",
        limit_price=None,
        market_session=market_session,
        extended_hours=market_session == "pre_open",
        reason_code=reason_code,
        rejected_observation_count=0,
    )


def compile_genome_paper_decision(
    genome: StrategyGenome,
    policy: StrategyEvolutionPolicy,
    observations: Sequence[StrategyObservation],
    state: PaperCandidateState,
    *,
    market_session: str,
) -> GenomePaperDecision:
    if type(genome) is not StrategyGenome:
        raise TypeError("genome must be a StrategyGenome")
    if type(policy) is not StrategyEvolutionPolicy:
        raise TypeError("policy must be a StrategyEvolutionPolicy")
    if isinstance(observations, (str, bytes)) or not isinstance(
        observations, Sequence
    ):
        raise TypeError("observations must be a sequence")
    observations_snapshot = tuple(observations)
    if any(
        type(observation) is not StrategyObservation
        for observation in observations_snapshot
    ):
        raise TypeError("observations must contain StrategyObservation objects")
    if type(state) is not PaperCandidateState:
        raise TypeError("state must be a PaperCandidateState")
    _validate_market_session(market_session)

    if genome.family is StrategyFamily.HOLD_CASH:
        return _hold_decision(
            genome,
            market_session=market_session,
            reason_code="genome_hold_cash",
        )
    if market_session == "closed":
        return _hold_decision(
            genome,
            market_session=market_session,
            reason_code="market_closed",
        )
    if not policy.enabled:
        return _hold_decision(
            genome,
            market_session=market_session,
            reason_code="policy_disabled",
        )

    available = state.cash_usd - state.reserved_buy_notional_usd
    if available < 0:
        available = Decimal("0")
    minimum_order = Decimal(policy.candidate_min_order_usd)
    notional = available
    if notional < minimum_order:
        return _hold_decision(
            genome,
            market_session=market_session,
            reason_code="insufficient_virtual_cash",
        )

    excluded_symbols = set(state.held_symbols) | set(state.open_buy_symbols)
    available_observations = [
        observation
        for observation in observations_snapshot
        if observation.symbol not in excluded_symbols
    ]

    eligible: list[StrategyObservation]
    if genome.family is StrategyFamily.CURRENT_AGGRESSIVE:
        parameters = genome.parameters
        if type(parameters) is not CurrentAggressiveParameters:
            raise TypeError("current-aggressive parameters do not match")
        minimum_score = Decimal(parameters.min_score)
        eligible = [
            observation
            for observation in available_observations
            if observation.score >= minimum_score
        ]
        eligible.sort(key=lambda observation: (-observation.score, observation.symbol))
    elif genome.family is StrategyFamily.PULLBACK_SUPPORT:
        parameters = genome.parameters
        if type(parameters) is not PullbackSupportParameters:
            raise TypeError("pullback-support parameters do not match")
        minimum_change = Decimal(parameters.min_daily_change_fraction)
        maximum_change = Decimal(parameters.max_daily_change_fraction)
        maximum_volume = Decimal(parameters.max_volume_ratio)
        eligible = [
            observation
            for observation in available_observations
            if minimum_change
            <= observation.daily_change_fraction
            <= maximum_change
            and observation.volume_ratio <= maximum_volume
        ]
        eligible.sort(
            key=lambda observation: (
                -observation.volume_ratio,
                abs(observation.daily_change_fraction),
                observation.symbol,
            )
        )
    else:
        parameters = genome.parameters
        if type(parameters) is not CatalystRelativeStrengthParameters:
            raise TypeError("catalyst-relative-strength parameters do not match")
        minimum_score = Decimal(parameters.min_score)
        eligible = [
            observation
            for observation in available_observations
            if observation.time_sensitive is True
            and observation.score >= minimum_score
        ]
        eligible.sort(key=lambda observation: (-observation.score, observation.symbol))

    if not eligible:
        return _hold_decision(
            genome,
            market_session=market_session,
            reason_code="no_eligible_observation",
        )

    selected = eligible[0]
    notional_usd = format(
        notional.quantize(_CENT, rounding=ROUND_DOWN),
        ".2f",
    )
    price_buffer = Decimal("1.003" if market_session == "pre_open" else "1.002")
    limit_price = selected.current_price * price_buffer
    limit_price = limit_price.quantize(_CENT, rounding=ROUND_DOWN)
    if limit_price <= 0:
        raise ValueError("limit_price must remain positive after rounding")
    return GenomePaperDecision(
        genome_id=genome.genome_id,
        family=genome.family,
        action=PaperDecisionAction.BUY,
        symbol=selected.symbol,
        notional_usd=notional_usd,
        limit_price=format(limit_price, ".2f"),
        market_session=market_session,
        extended_hours=market_session == "pre_open",
        reason_code=_BUY_REASON_BY_FAMILY[genome.family],
        rejected_observation_count=0,
    )
