"""Pure, source-bound inputs for qualifying TA-Control evaluation.

The evaluator deliberately receives simple candidate and return values.  This
module is the immutable boundary that makes those values auditable: every
candidate is bound to a PIT security and observation, every non-null signal is
bound to a cutoff-safe observation, and every realized return is rebuilt from a
complete total-return-adjusted price-window receipt.  It has no archive, store,
filesystem, network, broker, or execution dependency.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from tradingagents.dataflows.pit.records import (
    PointInTimeObservation,
    SecurityIdentity,
    validate_point_in_time_observation,
    validate_security_identity,
)
from tradingagents.evals.economic_evaluation_partition_binding import (
    ValidationPhaseEligibility,
    validate_validation_phase_eligibility,
)
from tradingagents.evals.economic_evaluation_protocol import (
    FrozenEvaluationProtocol,
    validate_frozen_evaluation_protocol,
)
from tradingagents.evals.economic_tournament import (
    EconomicTournamentCandidate,
    EconomicTournamentOutcome,
)
from tradingagents.sleeves.pullback_support import PullbackFeatures

__all__ = [
    "SourceBoundTournamentFeatures",
    "EconomicTournamentInputEvidenceError",
    "SourceBoundTournamentOutcomes",
    "SourceBoundTournamentInput",
    "build_source_bound_tournament_features",
    "build_source_bound_tournament_input",
    "build_source_bound_tournament_outcomes",
    "validate_source_bound_tournament_features",
    "validate_source_bound_tournament_input",
    "validate_source_bound_tournament_outcomes",
]


_FEATURE_SCHEMA = "source_bound_economic_tournament_features/v1"
_OUTCOME_SCHEMA = "source_bound_economic_tournament_outcomes/v1"
_SCHEMA = "source_bound_economic_tournament_input/v2"
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CANDIDATE_FIELDS = frozenset(
    {
        "symbol",
        "available_at",
        "close_t_21",
        "close_t_252",
        "trailing_operating_income",
        "average_total_assets",
        "pullback_features",
    }
)
_PULLBACK_FIELDS = frozenset(
    {
        "symbol",
        "current_price",
        "support_level",
        "atr",
        "pullback_atr",
        "above_rising_50d",
        "above_rising_200d",
        "sell_volume_state",
        "gap_state",
        "sector_relative_strength",
        "regime_state",
        "earnings_blackout",
        "fresh_negative_event",
        "green_spike_atr",
        "evidence_trend",
        "reward_risk_ratio",
        "notional_usd",
    }
)
_SIGNAL_FIELDS = frozenset(
    {
        "close_t_21",
        "close_t_252",
        "trailing_operating_income",
        "average_total_assets",
        "pullback_features",
    }
)
_FEATURE_DATE_FIELDS = frozenset({"market_date", "candidates", "benchmark"})
_CANDIDATE_EVIDENCE_FIELDS = frozenset(
    {
        "decision_event_id",
        "candidate",
        "security",
        "security_observation",
        "candidate_observation",
        "field_sources",
    }
)
_BENCHMARK_FIELDS = frozenset(
    {"security", "security_observation", "benchmark_observation"}
)
_FIELD_SOURCE_FIELDS = frozenset({"field", "value", "observation"})
_PULLBACK_SOURCE_FIELDS = frozenset({"field", "value_sha256", "observation"})
_OUTCOME_FIELDS = frozenset({"symbol", "return", "price_window"})
_OUTCOME_DATE_FIELDS = frozenset({"market_date", "outcomes"})
_PRICE_WINDOW_FIELDS = frozenset(
    {
        "schema_version",
        "window_id",
        "window_sha256",
        "security_id",
        "symbol",
        "requested_start",
        "requested_end",
        "decision_cutoff",
        "entry_date",
        "entry_close",
        "exit_date",
        "exit_close",
        "session_count",
        "daily_closes",
        "raw_artifact_id",
        "raw_artifact_sha256",
        "retrieved_at",
        "feed",
        "adjustment_mode",
        "adjustment_status",
        "source_span",
        *_AUTHORITY,
    }
)
_SOURCE_MAX_AGE_SECONDS = {
    "security_identity_json": 366 * 24 * 60 * 60,
    "economic_candidate_json": 7 * 24 * 60 * 60,
    "economic_benchmark_json": 7 * 24 * 60 * 60,
    "fixture_json": 366 * 24 * 60 * 60,
    "sec_json_xbrl": 366 * 24 * 60 * 60,
    "alpaca_market_data": 7 * 24 * 60 * 60,
}


class EconomicTournamentInputEvidenceError(ValueError):
    """A qualifying tournament input lacks immutable source evidence."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _thaw_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _freeze_json(value: object, *, label: str) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        raise EconomicTournamentInputEvidenceError(f"{label} cannot contain floats")
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise EconomicTournamentInputEvidenceError(f"{label} keys must be strings")
        return MappingProxyType(
            {key: _freeze_json(item, label=f"{label}.{key}") for key, item in value.items()}
        )
    if type(value) in (list, tuple):
        return tuple(
            _freeze_json(item, label=f"{label}[{index}]")
            for index, item in enumerate(value)
        )
    raise EconomicTournamentInputEvidenceError(f"{label} contains an unsupported value")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


def _exact_mapping(value: object, fields: frozenset[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise EconomicTournamentInputEvidenceError(f"{label} must be a JSON object")
    keys = set(value)
    if keys != fields:
        raise EconomicTournamentInputEvidenceError(
            f"{label} fields mismatch: missing={sorted(fields - keys)} extra={sorted(keys - fields)}"
        )
    return {key: value[key] for key in fields}


def _canonical_decimal(value: object, *, label: str, allow_negative: bool = True) -> str:
    if type(value) is not str:
        raise EconomicTournamentInputEvidenceError(f"{label} must be a canonical decimal")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise EconomicTournamentInputEvidenceError(f"{label} must be a canonical decimal") from exc
    if not parsed.is_finite() or (not allow_negative and parsed <= 0):
        raise EconomicTournamentInputEvidenceError(f"{label} has an invalid value")
    canonical = "0" if parsed.is_zero() else format(parsed.normalize(), "f")
    if value != canonical:
        raise EconomicTournamentInputEvidenceError(f"{label} must be a canonical decimal")
    return value


def _pullback_to_dict(value: PullbackFeatures) -> dict[str, object]:
    return {
        "symbol": value.symbol,
        "current_price": _decimal_text(value.current_price),
        "support_level": _decimal_text(value.support_level),
        "atr": _decimal_text(value.atr),
        "pullback_atr": _decimal_text(value.pullback_atr),
        "above_rising_50d": value.above_rising_50d,
        "above_rising_200d": value.above_rising_200d,
        "sell_volume_state": value.sell_volume_state,
        "gap_state": value.gap_state,
        "sector_relative_strength": _decimal_text(value.sector_relative_strength),
        "regime_state": value.regime_state,
        "earnings_blackout": value.earnings_blackout,
        "fresh_negative_event": value.fresh_negative_event,
        "green_spike_atr": _decimal_text(value.green_spike_atr),
        "evidence_trend": value.evidence_trend,
        "reward_risk_ratio": _decimal_text(value.reward_risk_ratio),
        "notional_usd": _decimal_text(value.notional_usd),
    }


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text


def _pullback_from_dict(value: object, *, symbol: str, label: str) -> PullbackFeatures | None:
    if value is None:
        return None
    payload = _exact_mapping(value, _PULLBACK_FIELDS, label=label)
    if payload["symbol"] != symbol:
        raise EconomicTournamentInputEvidenceError(f"{label}.symbol does not match candidate")
    for field in (
        "current_price",
        "support_level",
        "atr",
        "pullback_atr",
        "sector_relative_strength",
        "green_spike_atr",
        "reward_risk_ratio",
        "notional_usd",
    ):
        _canonical_decimal(payload[field], label=f"{label}.{field}")
    if any(type(payload[field]) is not bool for field in (
        "above_rising_50d",
        "above_rising_200d",
        "earnings_blackout",
        "fresh_negative_event",
    )):
        raise EconomicTournamentInputEvidenceError(f"{label} boolean fields are invalid")
    if any(type(payload[field]) is not str or not payload[field] for field in (
        "symbol",
        "sell_volume_state",
        "gap_state",
        "regime_state",
        "evidence_trend",
    )):
        raise EconomicTournamentInputEvidenceError(f"{label} string fields are invalid")
    return PullbackFeatures(
        symbol=symbol,
        current_price=Decimal(payload["current_price"]),
        support_level=Decimal(payload["support_level"]),
        atr=Decimal(payload["atr"]),
        pullback_atr=Decimal(payload["pullback_atr"]),
        above_rising_50d=payload["above_rising_50d"],  # type: ignore[arg-type]
        above_rising_200d=payload["above_rising_200d"],  # type: ignore[arg-type]
        sell_volume_state=payload["sell_volume_state"],  # type: ignore[arg-type]
        gap_state=payload["gap_state"],  # type: ignore[arg-type]
        sector_relative_strength=Decimal(payload["sector_relative_strength"]),
        regime_state=payload["regime_state"],  # type: ignore[arg-type]
        earnings_blackout=payload["earnings_blackout"],  # type: ignore[arg-type]
        fresh_negative_event=payload["fresh_negative_event"],  # type: ignore[arg-type]
        green_spike_atr=Decimal(payload["green_spike_atr"]),
        evidence_trend=payload["evidence_trend"],  # type: ignore[arg-type]
        reward_risk_ratio=Decimal(payload["reward_risk_ratio"]),
        notional_usd=Decimal(payload["notional_usd"]),
    )


def _candidate_from_dict(value: object, *, label: str) -> EconomicTournamentCandidate:
    payload = _exact_mapping(value, _CANDIDATE_FIELDS, label=label)
    if type(payload["symbol"]) is not str or type(payload["available_at"]) is not str:
        raise EconomicTournamentInputEvidenceError(f"{label} identity is invalid")
    for field in (
        "close_t_21",
        "close_t_252",
        "trailing_operating_income",
        "average_total_assets",
    ):
        if payload[field] is not None:
            _canonical_decimal(
                payload[field],
                label=f"{label}.{field}",
                allow_negative=field == "trailing_operating_income",
            )
    try:
        return EconomicTournamentCandidate(
            symbol=payload["symbol"],
            available_at=payload["available_at"],
            close_t_21=payload["close_t_21"],
            close_t_252=payload["close_t_252"],
            trailing_operating_income=payload["trailing_operating_income"],
            average_total_assets=payload["average_total_assets"],
            pullback_features=_pullback_from_dict(
                payload["pullback_features"],
                symbol=payload["symbol"],
                label=f"{label}.pullback_features",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise EconomicTournamentInputEvidenceError(f"{label} is invalid: {exc}") from exc


def _candidate_to_dict(value: EconomicTournamentCandidate) -> dict[str, object]:
    return {
        "symbol": value.symbol,
        "available_at": value.available_at,
        "close_t_21": value.close_t_21,
        "close_t_252": value.close_t_252,
        "trailing_operating_income": value.trailing_operating_income,
        "average_total_assets": value.average_total_assets,
        "pullback_features": (
            None if value.pullback_features is None else _pullback_to_dict(value.pullback_features)
        ),
    }


def _security_source_value(value: SecurityIdentity) -> dict[str, object]:
    """Identity fields reconstructed from one named retained source."""

    payload = value.to_dict()
    payload.pop("source_hashes")
    return payload


def _observation(
    value: object,
    *,
    label: str,
    decision_at: str,
    security: SecurityIdentity,
    expected_value: object,
) -> PointInTimeObservation:
    try:
        observation = validate_point_in_time_observation(value)
    except (TypeError, ValueError) as exc:
        raise EconomicTournamentInputEvidenceError(f"{label} is invalid") from exc
    if observation.security_id != security.security_id:
        raise EconomicTournamentInputEvidenceError(f"{label} security identity does not match")
    if (
        observation.identity_effective_from != security.effective_from
        or observation.identity_effective_to != security.effective_to
    ):
        raise EconomicTournamentInputEvidenceError(
            f"{label} identity-effective dates do not match"
        )
    if observation.availability_time > decision_at or observation.retrieval_time > decision_at:
        raise EconomicTournamentInputEvidenceError(f"{label} is not available by the decision cutoff")
    if _canonical_json_bytes(observation.observed_value) != _canonical_json_bytes(
        expected_value
    ):
        raise EconomicTournamentInputEvidenceError(
            f"{label} observed value does not match its bound value"
        )
    source_kind = observation.source_span.get("source_kind")
    max_age = _SOURCE_MAX_AGE_SECONDS.get(source_kind)
    if max_age is None:
        raise EconomicTournamentInputEvidenceError(
            f"{label} source kind is not registered"
        )
    decision = dt.datetime.fromisoformat(decision_at)
    availability = dt.datetime.fromisoformat(observation.availability_time)
    if (decision - availability).total_seconds() > max_age:
        raise EconomicTournamentInputEvidenceError(f"{label} is stale")
    return observation


def _field_sources(
    value: object,
    *,
    candidate: EconomicTournamentCandidate,
    decision_at: str,
    security: SecurityIdentity,
    label: str,
) -> tuple[dict[str, object], ...]:
    if type(value) is not list:
        raise EconomicTournamentInputEvidenceError(f"{label} must be a list")
    sources: list[dict[str, object]] = []
    expected_fields = {
        field for field in _SIGNAL_FIELDS if getattr(candidate, field) is not None
    }
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or type(item.get("field")) is not str:
            raise EconomicTournamentInputEvidenceError(f"{label}[{index}] is invalid")
        field = item["field"]
        if field not in expected_fields or field in seen:
            raise EconomicTournamentInputEvidenceError(f"{label}[{index}] field is invalid")
        seen.add(field)
        if field == "pullback_features":
            source = _exact_mapping(item, _PULLBACK_SOURCE_FIELDS, label=f"{label}[{index}]")
            candidate_value = _candidate_to_dict(candidate)[field]
            assert candidate_value is not None
            expected_digest = _sha256(candidate_value)
            if source["value_sha256"] != expected_digest:
                raise EconomicTournamentInputEvidenceError(
                    f"{label}[{index}] pullback feature digest does not match candidate"
                )
        else:
            source = _exact_mapping(item, _FIELD_SOURCE_FIELDS, label=f"{label}[{index}]")
            candidate_value = getattr(candidate, field)
            if source["value"] != candidate_value:
                raise EconomicTournamentInputEvidenceError(
                    f"{label}[{index}] field source value does not match candidate"
                )
        observation = _observation(
            source["observation"],
            label=f"{label}[{index}] observation",
            decision_at=decision_at,
            security=security,
            expected_value=candidate_value,
        )
        source["observation"] = observation.to_dict()
        sources.append(source)
    if seen != expected_fields:
        raise EconomicTournamentInputEvidenceError(f"{label} must cover every non-null candidate signal")
    if tuple(item["field"] for item in sources) != tuple(sorted(seen)):
        raise EconomicTournamentInputEvidenceError(f"{label} must be in canonical field order")
    return tuple(sources)


def _outcome(
    value: object,
    *,
    security: SecurityIdentity,
    event_market_date: str,
    event_decision_at: str,
    label: str,
) -> tuple[tuple[str, str], dict[str, object]]:
    payload = _exact_mapping(value, _OUTCOME_FIELDS, label=label)
    if payload["symbol"] != security.symbol:
        raise EconomicTournamentInputEvidenceError(f"{label}.symbol is invalid")
    returned = _canonical_decimal(payload["return"], label=f"{label}.return")
    window = _exact_mapping(
        payload["price_window"],
        _PRICE_WINDOW_FIELDS,
        label=f"{label}.price_window",
    )
    if (
        window["schema_version"] != "source_bound_adjusted_price_window/v1"
        or any(window[key] != expected for key, expected in _AUTHORITY.items())
        or window["symbol"] != security.symbol
        or window["security_id"] != security.security_id
        or type(window["entry_date"]) is not str
        or type(window["decision_cutoff"]) is not str
    ):
        raise EconomicTournamentInputEvidenceError(
            f"{label} price window security identity does not match"
        )
    if window["entry_date"] <= event_market_date or window["decision_cutoff"] <= event_decision_at:
        raise EconomicTournamentInputEvidenceError(f"{label} price window is not a post-decision outcome")
    if (
        type(window["window_id"]) is not str
        or not window["window_id"].startswith("source-bound-adjusted-price-window-")
        or type(window["window_sha256"]) is not str
        or _SHA256.fullmatch(window["window_sha256"]) is None
        or type(window["raw_artifact_sha256"]) is not str
        or _SHA256.fullmatch(window["raw_artifact_sha256"]) is None
    ):
        raise EconomicTournamentInputEvidenceError(
            f"{label} price window identity is invalid"
        )
    expected = (Decimal(window["exit_close"]) - Decimal(window["entry_close"])) / Decimal(
        window["entry_close"]
    )
    expected_text = _decimal_text(expected)
    if returned != expected_text:
        raise EconomicTournamentInputEvidenceError(
            f"{label} outcome return does not match source-bound price window"
        )
    payload["price_window"] = window
    return (payload["symbol"], returned), payload  # type: ignore[return-value]


def _feature_date(
    value: object,
    *,
    market_date: str,
    events: tuple[object, ...],
    primary_universe: tuple[str, ...],
    primary_security_ids: Mapping[str, str],
    label: str,
) -> tuple[
    dict[str, object],
    tuple[EconomicTournamentCandidate, ...],
    dict[str, SecurityIdentity],
]:
    payload = _exact_mapping(value, _FEATURE_DATE_FIELDS, label=label)
    if payload["market_date"] != market_date or type(payload["candidates"]) is not list:
        raise EconomicTournamentInputEvidenceError(
            f"{label} market date or candidates are invalid"
        )
    if len(events) != 75 or len(payload["candidates"]) != 75:
        raise EconomicTournamentInputEvidenceError(
            f"{label} must bind exactly 75 symbol events"
        )
    normalized_candidates: list[dict[str, object]] = []
    candidates: list[EconomicTournamentCandidate] = []
    identities: dict[str, SecurityIdentity] = {}
    for index, (raw_candidate, event) in enumerate(
        zip(payload["candidates"], events, strict=True)
    ):
        row = _exact_mapping(
            raw_candidate,
            _CANDIDATE_EVIDENCE_FIELDS,
            label=f"{label}.candidates[{index}]",
        )
        event_id = getattr(event, "decision_event_id", None)
        event_symbol = getattr(event, "symbol", None)
        event_decision_at = getattr(event, "decision_at", None)
        if row["decision_event_id"] != event_id or type(event_decision_at) is not str:
            raise EconomicTournamentInputEvidenceError(
                f"{label}.candidates[{index}] decision event does not match"
            )
        candidate = _candidate_from_dict(row["candidate"], label=f"{label}.candidates[{index}].candidate")
        try:
            security = validate_security_identity(row["security"])
        except (TypeError, ValueError) as exc:
            raise EconomicTournamentInputEvidenceError(
                f"{label}.candidates[{index}] security is invalid"
            ) from exc
        if security.symbol != candidate.symbol or candidate.symbol != event_symbol:
            raise EconomicTournamentInputEvidenceError(
                f"{label}.candidates[{index}] security symbol does not match candidate"
            )
        if security.security_id != primary_security_ids[event_symbol]:
            raise EconomicTournamentInputEvidenceError(
                f"{label}.candidates[{index}] security does not match the sealed cohort"
            )
        if not (
            security.effective_from <= market_date
            and (security.effective_to is None or market_date <= security.effective_to)
        ):
            raise EconomicTournamentInputEvidenceError(
                f"{label}.candidates[{index}] security is ineffective for market date"
            )
        security_observation = _observation(
            row["security_observation"],
            label=f"{label}.candidates[{index}] security observation",
            decision_at=event_decision_at,
            security=security,
            expected_value=_security_source_value(security),
        )
        if security_observation.raw_artifact_sha256 not in security.source_hashes.values():
            raise EconomicTournamentInputEvidenceError(
                f"{label}.candidates[{index}] security source is not bound"
            )
        observation = _observation(
            row["candidate_observation"],
            label=f"{label}.candidates[{index}] candidate observation",
            decision_at=event_decision_at,
            security=security,
            expected_value=_candidate_to_dict(candidate),
        )
        sources = _field_sources(
            row["field_sources"],
            candidate=candidate,
            decision_at=event_decision_at,
            security=security,
            label=f"{label}.candidates[{index}] field_sources",
        )
        source_availability = [observation.availability_time]
        for source in sources:
            nested = validate_point_in_time_observation(source["observation"])
            source_availability.append(nested.availability_time)
        if candidate.available_at != max(source_availability):
            raise EconomicTournamentInputEvidenceError(
                f"{label}.candidates[{index}] candidate availability does not match source evidence"
            )
        normalized_candidates.append(
            {
                "decision_event_id": event_id,
                "candidate": _candidate_to_dict(candidate),
                "security": security.to_dict(),
                "security_observation": security_observation.to_dict(),
                "candidate_observation": observation.to_dict(),
                "field_sources": list(sources),
            }
        )
        candidates.append(candidate)
        identities[candidate.symbol] = security
    if tuple(item.symbol for item in candidates) != primary_universe:
        raise EconomicTournamentInputEvidenceError(f"{label} candidates must match the frozen primary universe")
    benchmark = _exact_mapping(
        payload["benchmark"],
        _BENCHMARK_FIELDS,
        label=f"{label}.benchmark",
    )
    try:
        benchmark_security = validate_security_identity(benchmark["security"])
    except (TypeError, ValueError) as exc:
        raise EconomicTournamentInputEvidenceError(
            f"{label} benchmark security is invalid"
        ) from exc
    first_decision_at = min(event.decision_at for event in events)
    if benchmark_security.symbol != "SPY" or not (
        benchmark_security.effective_from <= market_date
        and (
            benchmark_security.effective_to is None
            or market_date <= benchmark_security.effective_to
        )
    ):
        raise EconomicTournamentInputEvidenceError(
            f"{label} benchmark security identity is invalid"
        )
    if benchmark_security.security_id in set(primary_security_ids.values()):
        raise EconomicTournamentInputEvidenceError(
            f"{label} benchmark security collides with the sealed primary cohort"
        )
    security_observation = _observation(
        benchmark["security_observation"],
        label=f"{label}.benchmark security observation",
        decision_at=first_decision_at,
        security=benchmark_security,
        expected_value=_security_source_value(benchmark_security),
    )
    if security_observation.raw_artifact_sha256 not in benchmark_security.source_hashes.values():
        raise EconomicTournamentInputEvidenceError(
            f"{label} benchmark security source is not bound"
        )
    benchmark_value = {
        "security_id": benchmark_security.security_id,
        "symbol": "SPY",
        "market_date": market_date,
    }
    benchmark_observation = _observation(
        benchmark["benchmark_observation"],
        label=f"{label}.benchmark observation",
        decision_at=first_decision_at,
        security=benchmark_security,
        expected_value=benchmark_value,
    )
    identities["SPY"] = benchmark_security
    return (
        {
            "market_date": market_date,
            "candidates": normalized_candidates,
            "benchmark": {
                "security": benchmark_security.to_dict(),
                "security_observation": security_observation.to_dict(),
                "benchmark_observation": benchmark_observation.to_dict(),
            },
        },
        tuple(candidates),
        identities,
    )


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class SourceBoundTournamentFeatures:
    """Immutable pre-outcome feature evidence grouped once per market date."""

    feature_id: str
    feature_sha256: str
    protocol_id: str
    validation_partition_id: str
    validation_partition_sha256: str
    validation_event_ids: tuple[str, ...]
    market_dates: tuple[str, ...]
    date_evidence: tuple[Mapping[str, object], ...]
    candidates_by_event: Mapping[str, tuple[EconomicTournamentCandidate, ...]]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("SourceBoundTournamentFeatures instances require its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _FEATURE_SCHEMA,
            "feature_id": self.feature_id,
            "feature_sha256": self.feature_sha256,
            "protocol_id": self.protocol_id,
            "validation_partition_id": self.validation_partition_id,
            "validation_partition_sha256": self.validation_partition_sha256,
            "validation_event_ids": list(self.validation_event_ids),
            "market_dates": [_thaw_json(item) for item in self.date_evidence],
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class SourceBoundTournamentOutcomes:
    """Post-outcome evidence that references, but cannot rewrite, features."""

    input_id: str
    input_sha256: str
    feature_id: str
    feature_sha256: str
    protocol_id: str
    validation_partition_id: str
    validation_partition_sha256: str
    validation_event_ids: tuple[str, ...]
    market_dates: tuple[str, ...]
    date_evidence: tuple[Mapping[str, object], ...]
    outcomes: tuple[EconomicTournamentOutcome, ...]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("SourceBoundTournamentOutcomes instances require its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _OUTCOME_SCHEMA,
            "input_id": self.input_id,
            "input_sha256": self.input_sha256,
            "feature_id": self.feature_id,
            "feature_sha256": self.feature_sha256,
            "protocol_id": self.protocol_id,
            "validation_partition_id": self.validation_partition_id,
            "validation_partition_sha256": self.validation_partition_sha256,
            "validation_event_ids": list(self.validation_event_ids),
            "market_dates": [_thaw_json(item) for item in self.date_evidence],
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class SourceBoundTournamentInput:
    """Derived evaluator view over separate feature and outcome receipts."""

    input_id: str
    input_sha256: str
    features: SourceBoundTournamentFeatures
    outcome_receipt: SourceBoundTournamentOutcomes
    candidates_by_event: Mapping[str, tuple[EconomicTournamentCandidate, ...]]
    outcomes: tuple[EconomicTournamentOutcome, ...]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("SourceBoundTournamentInput instances require its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA,
            "features": self.features.to_dict(),
            "outcomes": self.outcome_receipt.to_dict(),
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def _new_value(value_type: type[object], **fields: object) -> object:
    value = object.__new__(value_type)
    for field in dataclasses.fields(value_type):
        object.__setattr__(value, field.name, fields[field.name])
    return value


def _context(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
) -> tuple[
    FrozenEvaluationProtocol,
    ValidationPhaseEligibility,
    tuple[tuple[str, tuple[object, ...]], ...],
    Mapping[str, str],
]:
    if type(protocol) is not FrozenEvaluationProtocol:
        raise EconomicTournamentInputEvidenceError("protocol must be an exact frozen value")
    frozen = validate_frozen_evaluation_protocol(protocol.to_dict())
    try:
        bound = validate_validation_phase_eligibility(protocol=frozen, eligibility=eligibility)
    except (TypeError, ValueError) as exc:
        raise EconomicTournamentInputEvidenceError("validation eligibility is invalid") from exc
    primary_ranking = frozen.cohort.ranking[: len(frozen.primary_universe)]
    primary_symbols = tuple(row.symbol for row in primary_ranking)
    primary_ids = tuple(row.security_id for row in primary_ranking)
    if primary_symbols != frozen.primary_universe:
        raise EconomicTournamentInputEvidenceError(
            "sealed cohort ranking does not match the frozen primary universe"
        )
    if len(set(primary_ids)) != len(primary_ids):
        raise EconomicTournamentInputEvidenceError(
            "sealed primary cohort security identities collide"
        )
    primary_security_ids = MappingProxyType(dict(zip(primary_symbols, primary_ids, strict=True)))
    events_by_id = {event.decision_event_id: event for event in frozen.input_manifest.events}
    grouped: OrderedDict[str, list[object]] = OrderedDict()
    for event_id in bound.event_ids:
        event = events_by_id[event_id]
        grouped.setdefault(event.market_date, []).append(event)
    result: list[tuple[str, tuple[object, ...]]] = []
    for market_date, date_events in grouped.items():
        events_by_symbol = {item.symbol: item for item in date_events}
        if len(date_events) != 75 or set(events_by_symbol) != set(frozen.primary_universe):
            raise EconomicTournamentInputEvidenceError(
                "every validation market date must bind the ranked 75-symbol universe"
            )
        events = tuple(events_by_symbol[symbol] for symbol in frozen.primary_universe)
        result.append((market_date, events))
    return frozen, bound, tuple(result), primary_security_ids


def _build_features(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    market_date_inputs: object,
) -> SourceBoundTournamentFeatures:
    frozen, bound, grouped, primary_security_ids = _context(
        protocol=protocol,
        eligibility=eligibility,
    )
    if type(market_date_inputs) not in (list, tuple):
        raise EconomicTournamentInputEvidenceError(
            "feature market dates must be an exact ordered sequence"
        )
    raw_dates = tuple(market_date_inputs)
    if len(raw_dates) != len(grouped):
        raise EconomicTournamentInputEvidenceError(
            "features must be grouped once per validation market date"
        )
    canonical_dates: list[Mapping[str, object]] = []
    candidates_by_event: dict[str, tuple[EconomicTournamentCandidate, ...]] = {}
    for index, ((market_date, events), raw_date) in enumerate(
        zip(grouped, raw_dates, strict=True)
    ):
        canonical, candidates, _identities = _feature_date(
            raw_date,
            market_date=market_date,
            events=events,
            primary_universe=frozen.primary_universe,
            primary_security_ids=primary_security_ids,
            label=f"market_dates[{index}]",
        )
        canonical_dates.append(
            _freeze_json(canonical, label=f"market_dates[{index}]")
        )
        for event in events:
            candidates_by_event[event.decision_event_id] = candidates
    material = {
        "schema_version": _FEATURE_SCHEMA,
        "protocol_id": frozen.protocol_id,
        "validation_partition_id": bound.partition_id,
        "validation_partition_sha256": bound.partition_sha256,
        "validation_event_ids": list(bound.event_ids),
        "market_dates": [_thaw_json(item) for item in canonical_dates],
        **_AUTHORITY,
    }
    feature_id = "economic-tournament-feature-" + _sha256(material)
    digest = _sha256({**material, "feature_id": feature_id})
    return _new_value(
        SourceBoundTournamentFeatures,
        feature_id=feature_id,
        feature_sha256=digest,
        protocol_id=frozen.protocol_id,
        validation_partition_id=bound.partition_id,
        validation_partition_sha256=bound.partition_sha256,
        validation_event_ids=bound.event_ids,
        market_dates=tuple(item[0] for item in grouped),
        date_evidence=tuple(canonical_dates),
        candidates_by_event=MappingProxyType(candidates_by_event),
    )  # type: ignore[return-value]


def _build_outcomes(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    features: SourceBoundTournamentFeatures,
    market_date_inputs: object,
) -> SourceBoundTournamentOutcomes:
    frozen, bound, grouped, _primary_security_ids = _context(
        protocol=protocol,
        eligibility=eligibility,
    )
    if type(features) is not SourceBoundTournamentFeatures:
        raise EconomicTournamentInputEvidenceError(
            "features must be an exact pre-outcome receipt"
        )
    if features.protocol_id != frozen.protocol_id or features.validation_event_ids != bound.event_ids:
        raise EconomicTournamentInputEvidenceError(
            "feature receipt does not match validation eligibility"
        )
    if type(market_date_inputs) not in (list, tuple):
        raise EconomicTournamentInputEvidenceError(
            "outcome market dates must be an exact ordered sequence"
        )
    raw_dates = tuple(market_date_inputs)
    if len(raw_dates) != len(grouped):
        raise EconomicTournamentInputEvidenceError(
            "outcomes must be grouped once per validation market date"
        )
    canonical_dates: list[Mapping[str, object]] = []
    evaluator_outcomes: dict[str, EconomicTournamentOutcome] = {}
    for index, ((market_date, events), raw_date, feature_date) in enumerate(
        zip(grouped, raw_dates, features.date_evidence, strict=True)
    ):
        payload = _exact_mapping(
            raw_date,
            _OUTCOME_DATE_FIELDS,
            label=f"market_dates[{index}]",
        )
        if payload["market_date"] != market_date or type(payload["outcomes"]) is not list:
            raise EconomicTournamentInputEvidenceError(
                f"market_dates[{index}] is not the matching outcome date"
            )
        identities: dict[str, SecurityIdentity] = {}
        feature_candidates = feature_date.get("candidates")
        feature_benchmark = feature_date.get("benchmark")
        if type(feature_candidates) is not tuple or not isinstance(feature_benchmark, Mapping):
            raise EconomicTournamentInputEvidenceError(
                "canonical feature identities are invalid"
            )
        for candidate_row in feature_candidates:
            if not isinstance(candidate_row, Mapping):
                raise EconomicTournamentInputEvidenceError(
                    "canonical feature candidate is invalid"
                )
            security = validate_security_identity(_thaw_json(candidate_row["security"]))
            identities[security.symbol] = security
        benchmark_security = validate_security_identity(
            _thaw_json(feature_benchmark["security"])
        )
        identities[benchmark_security.symbol] = benchmark_security
        returns: list[tuple[str, str]] = []
        normalized: list[dict[str, object]] = []
        decision_at = max(event.decision_at for event in events)
        for outcome_index, raw_outcome in enumerate(payload["outcomes"]):
            if not isinstance(raw_outcome, Mapping) or type(raw_outcome.get("symbol")) is not str:
                raise EconomicTournamentInputEvidenceError(
                    f"market_dates[{index}].outcomes[{outcome_index}] is invalid"
                )
            symbol = raw_outcome["symbol"]
            if symbol not in identities:
                raise EconomicTournamentInputEvidenceError(
                    f"market_dates[{index}].outcomes[{outcome_index}] lacks feature identity"
                )
            returned, evidence = _outcome(
                raw_outcome,
                security=identities[symbol],
                event_market_date=market_date,
                event_decision_at=decision_at,
                label=f"market_dates[{index}].outcomes[{outcome_index}]",
            )
            returns.append(returned)
            normalized.append(evidence)
        expected_symbols = tuple(sorted((*frozen.primary_universe, "SPY")))
        if tuple(symbol for symbol, _value in returns) != expected_symbols:
            raise EconomicTournamentInputEvidenceError(
                "outcomes must cover the primary universe and SPY exactly"
            )
        shared_returns = tuple(returns)
        for event in events:
            event_id = event.decision_event_id
            evaluator_outcomes[event_id] = EconomicTournamentOutcome(
                decision_event_id=event_id,
                realized_returns=shared_returns,
            )
        canonical_dates.append(
            _freeze_json(
                {"market_date": market_date, "outcomes": normalized},
                label=f"market_dates[{index}]",
            )
        )
    material = {
        "schema_version": _OUTCOME_SCHEMA,
        "feature_id": features.feature_id,
        "feature_sha256": features.feature_sha256,
        "protocol_id": frozen.protocol_id,
        "validation_partition_id": bound.partition_id,
        "validation_partition_sha256": bound.partition_sha256,
        "validation_event_ids": list(bound.event_ids),
        "market_dates": [_thaw_json(item) for item in canonical_dates],
        **_AUTHORITY,
    }
    input_id = "economic-tournament-input-" + _sha256(material)
    digest = _sha256({**material, "input_id": input_id})
    return _new_value(
        SourceBoundTournamentOutcomes,
        input_id=input_id,
        input_sha256=digest,
        feature_id=features.feature_id,
        feature_sha256=features.feature_sha256,
        protocol_id=frozen.protocol_id,
        validation_partition_id=bound.partition_id,
        validation_partition_sha256=bound.partition_sha256,
        validation_event_ids=bound.event_ids,
        market_dates=tuple(item[0] for item in grouped),
        date_evidence=tuple(canonical_dates),
        outcomes=tuple(evaluator_outcomes[event_id] for event_id in bound.event_ids),
    )  # type: ignore[return-value]


def build_source_bound_tournament_features(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    market_date_inputs: tuple[Mapping[str, object], ...],
) -> SourceBoundTournamentFeatures:
    """Freeze the pre-outcome feature receipt once per eligible market date."""

    return _build_features(
        protocol=protocol,
        eligibility=eligibility,
        market_date_inputs=market_date_inputs,
    )


def build_source_bound_tournament_outcomes(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    features: SourceBoundTournamentFeatures,
    market_date_inputs: tuple[Mapping[str, object], ...],
) -> SourceBoundTournamentOutcomes:
    """Build post-outcome evidence against an immutable feature receipt."""

    return _build_outcomes(
        protocol=protocol,
        eligibility=eligibility,
        features=features,
        market_date_inputs=market_date_inputs,
    )


def build_source_bound_tournament_input(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    features: SourceBoundTournamentFeatures,
    outcomes: SourceBoundTournamentOutcomes,
) -> SourceBoundTournamentInput:
    """Create the evaluator view from separately frozen receipts."""

    rebuilt_features = validate_source_bound_tournament_features(
        features.to_dict(),
        protocol=protocol,
        eligibility=eligibility,
    )
    rebuilt_outcomes = validate_source_bound_tournament_outcomes(
        outcomes.to_dict(),
        protocol=protocol,
        eligibility=eligibility,
        features=rebuilt_features,
    )
    return _new_value(
        SourceBoundTournamentInput,
        input_id=rebuilt_outcomes.input_id,
        input_sha256=rebuilt_outcomes.input_sha256,
        features=rebuilt_features,
        outcome_receipt=rebuilt_outcomes,
        candidates_by_event=rebuilt_features.candidates_by_event,
        outcomes=rebuilt_outcomes.outcomes,
    )  # type: ignore[return-value]


_FEATURE_SERIALIZED_FIELDS = frozenset(
    {
        "schema_version",
        "feature_id",
        "feature_sha256",
        "protocol_id",
        "validation_partition_id",
        "validation_partition_sha256",
        "validation_event_ids",
        "market_dates",
        *_AUTHORITY,
    }
)
_OUTCOME_SERIALIZED_FIELDS = frozenset(
    {
        "schema_version",
        "input_id",
        "input_sha256",
        "feature_id",
        "feature_sha256",
        "protocol_id",
        "validation_partition_id",
        "validation_partition_sha256",
        "validation_event_ids",
        "market_dates",
        *_AUTHORITY,
    }
)
_SERIALIZED_FIELDS = frozenset(
    {"schema_version", "features", "outcomes", *_AUTHORITY}
)


def validate_source_bound_tournament_features(
    value: object,
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
) -> SourceBoundTournamentFeatures:
    """Canonical-rebuild one pre-outcome feature receipt."""

    payload = _exact_mapping(
        value,
        _FEATURE_SERIALIZED_FIELDS,
        label="source-bound tournament features",
    )
    if payload["schema_version"] != _FEATURE_SCHEMA or any(
        payload[key] != expected for key, expected in _AUTHORITY.items()
    ):
        raise EconomicTournamentInputEvidenceError(
            "source-bound tournament feature schema or authority is invalid"
        )
    rebuilt = _build_features(
        protocol=protocol,
        eligibility=eligibility,
        market_date_inputs=payload["market_dates"],
    )
    if (
        payload["feature_id"] != rebuilt.feature_id
        or payload["feature_sha256"] != rebuilt.feature_sha256
        or rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload)
    ):
        raise EconomicTournamentInputEvidenceError(
            "source-bound tournament feature bytes do not match canonical rebuild"
        )
    return rebuilt


def validate_source_bound_tournament_outcomes(
    value: object,
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    features: SourceBoundTournamentFeatures,
) -> SourceBoundTournamentOutcomes:
    """Canonical-rebuild outcomes and their exact immutable feature reference."""

    payload = _exact_mapping(
        value,
        _OUTCOME_SERIALIZED_FIELDS,
        label="source-bound tournament outcomes",
    )
    if payload["schema_version"] != _OUTCOME_SCHEMA or any(
        payload[key] != expected for key, expected in _AUTHORITY.items()
    ):
        raise EconomicTournamentInputEvidenceError(
            "source-bound tournament outcome schema or authority is invalid"
        )
    rebuilt = _build_outcomes(
        protocol=protocol,
        eligibility=eligibility,
        features=features,
        market_date_inputs=payload["market_dates"],
    )
    if (
        payload["input_id"] != rebuilt.input_id
        or payload["input_sha256"] != rebuilt.input_sha256
        or payload["feature_id"] != rebuilt.feature_id
        or payload["feature_sha256"] != rebuilt.feature_sha256
        or rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload)
    ):
        raise EconomicTournamentInputEvidenceError(
            "source-bound tournament outcome bytes do not match canonical rebuild"
        )
    return rebuilt


def validate_source_bound_tournament_input(
    value: object,
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
) -> SourceBoundTournamentInput:
    """Canonical-rebuild source-bound tournament inputs before evaluation."""

    payload = _exact_mapping(value, _SERIALIZED_FIELDS, label="source-bound tournament input")
    if payload["schema_version"] != _SCHEMA or any(
        payload[key] != expected for key, expected in _AUTHORITY.items()
    ):
        raise EconomicTournamentInputEvidenceError("source-bound tournament input schema or authority is invalid")
    features = validate_source_bound_tournament_features(
        payload["features"],
        protocol=protocol,
        eligibility=eligibility,
    )
    outcomes = validate_source_bound_tournament_outcomes(
        payload["outcomes"],
        protocol=protocol,
        eligibility=eligibility,
        features=features,
    )
    rebuilt = build_source_bound_tournament_input(
        protocol=protocol,
        eligibility=eligibility,
        features=features,
        outcomes=outcomes,
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise EconomicTournamentInputEvidenceError(
            "source-bound tournament input bytes do not match canonical rebuild"
        )
    return rebuilt
