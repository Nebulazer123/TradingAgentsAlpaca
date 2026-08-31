"""Evidence-first economic evaluation protocol objects.

This pure module freezes an arm-neutral market-decision identity, a
bitemporal input manifest, and a frozen TA-control evaluation protocol.
It never runs an experiment, fetches data, calls a model, touches a
broker, or grants execution authority; every public object serializes
the exact fixed authority fields ``analysis_only=true``,
``execution_authority="none"``, and ``can_submit_orders=false``.

Canonical hashing domains (frozen):

- ``DecisionEvent.decision_event_id`` hashes exactly the arm-neutral
  decision material (schema, universe_id, symbol, decision_at,
  market_date, horizon_sessions, benchmark). It excludes arm, model,
  agent, forecast, outcome, source-artifact, and promotion material.
- ``packet_event_cluster_id`` / ``market_event_cluster_id`` hash the
  tuples returned by the existing pure reconciliation key functions.
- ``BitemporalInputManifest.manifest_id`` hashes the full serialized
  manifest material except ``manifest_id`` and ``manifest_sha256``
  itself; that domain includes ``captured_at``, the dataset identity,
  cutoffs, authority fields, the ordered payload digest, and the full
  nested event dictionaries.
- ``BitemporalInputManifest.manifest_sha256`` hashes the complete
  serialized manifest payload except ``manifest_sha256`` itself; that
  domain therefore also includes ``manifest_id``.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from tradingagents.dataflows.pit.cohort import (
    PointInTimeCohort,
    validate_nonqualifying_point_in_time_cohort_record,
)

from tradingagents.evals.agent_intelligence_reconciliation import (
    market_event_key,
    packet_event_key,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy

if TYPE_CHECKING:
    from tradingagents.dataflows.pit.partitions import MarketDatePartitions

__all__: list[str] = [
    "EconomicEvaluationProtocolError",
    "DecisionEvent",
    "BitemporalInputManifest",
    "EvaluationSearchBudget",
    "FrozenEvaluationProtocol",
    "canonical_universe_id",
    "build_decision_event",
    "validate_decision_event",
    "build_bitemporal_input_manifest",
    "validate_bitemporal_input_manifest",
    "build_frozen_evaluation_protocol",
    "validate_frozen_evaluation_protocol",
]

DECISION_EVENT_SCHEMA = "decision_event/v1"
BITEMPORAL_INPUT_MANIFEST_SCHEMA = "bitemporal_input_manifest/v1"
EVALUATION_SEARCH_BUDGET_SCHEMA = "evaluation_search_budget/v1"
FROZEN_EVALUATION_PROTOCOL_SCHEMA = "frozen_economic_evaluation_protocol/v2"
AUTHORITY_FIELDS: dict[str, object] = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
CONTROL_ARM_IDS = (
    "cash",
    "spy",
    "equal_weight",
    "momentum_quality",
    "pullback_support",
)
REQUIRED_METRICS = (
    "net_return_after_costs",
    "benchmark_excess_after_costs",
    "max_drawdown",
    "turnover",
    "false_positive_rate",
    "decision_event_count",
    "packet_event_cluster_count",
    "market_event_cluster_count",
    "cost_per_useful_decision",
)
_PROTOCOL_ROUTE_ID = "ta-control/v1"
_PROTOCOL_CADENCE = "weekly"
_PROTOCOL_MAX_LEVERAGE = "1"
_PROTOCOL_HOLDOUT_STATUS = "sealed"
_PROTOCOL_DEPENDENCE_METHOD = "market_event_cluster_count_provisional_bound"


class EconomicEvaluationProtocolError(ValueError):
    """Raised when protocol input violates the frozen contract."""


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


_TIMESTAMP_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _require_exact_fields(
    value: object,
    expected: frozenset[str],
    *,
    context: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EconomicEvaluationProtocolError(f"{context} must be a JSON mapping")
    keys = set(value.keys())
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise EconomicEvaluationProtocolError(
            f"{context} field set mismatch: missing={missing} extra={extra}"
        )
    return {key: value[key] for key in expected}


def _exact_str(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        raise EconomicEvaluationProtocolError(f"{field_name} must be a string")
    return value


def _identifier(value: object, *, field_name: str) -> str:
    text = _exact_str(value, field_name=field_name)
    if not text or text.strip() != text:
        raise EconomicEvaluationProtocolError(
            f"{field_name} must be a nonempty string without surrounding whitespace"
        )
    return text


def _lower_sha256(value: object, *, field_name: str) -> str:
    text = _exact_str(value, field_name=field_name)
    if not _SHA256_PATTERN.fullmatch(text):
        raise EconomicEvaluationProtocolError(
            f"{field_name} must be a lowercase 64-hex SHA-256 digest"
        )
    return text


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise EconomicEvaluationProtocolError(f"{field_name} must be a positive integer")
    return value


def _prefixed_digest(value: object, *, prefix: str, field_name: str) -> str:
    text = _exact_str(value, field_name=field_name)
    if not text.startswith(prefix) or not _SHA256_PATTERN.fullmatch(text[len(prefix):]):
        raise EconomicEvaluationProtocolError(
            f"{field_name} must be {prefix}<64 lowercase hex digits>"
        )
    return text


def _normalized_symbol(value: object, *, field_name: str) -> str:
    text = _exact_str(value, field_name=field_name)
    if (
        not text
        or len(text) > 15
        or not ("A" <= text[0] <= "Z")
        or any(not ("A" <= ch <= "Z" or "0" <= ch <= "9" or ch in ".-") for ch in text[1:])
    ):
        raise EconomicEvaluationProtocolError(
            f"{field_name} must already be a normalized uppercase ticker token"
        )
    return text


def _canonical_utc_timestamp(value: object, *, field_name: str) -> datetime.datetime:
    text = _exact_str(value, field_name=field_name)
    if not _TIMESTAMP_PATTERN.fullmatch(text):
        raise EconomicEvaluationProtocolError(
            f"{field_name} must use canonical UTC seconds format "
            f"YYYY-MM-DDTHH:MM:SS+00:00: {text!r}"
        )
    try:
        parsed = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as exc:
        raise EconomicEvaluationProtocolError(
            f"{field_name} is not a real UTC timestamp: {text!r}"
        ) from exc
    return parsed


def _iso_date(value: object, *, field_name: str) -> datetime.date:
    text = _exact_str(value, field_name=field_name)
    if not _DATE_PATTERN.fullmatch(text):
        raise EconomicEvaluationProtocolError(
            f"{field_name} must use YYYY-MM-DD format: {text!r}"
        )
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise EconomicEvaluationProtocolError(
            f"{field_name} is not a real calendar date: {text!r}"
        ) from exc


def _freeze_json(value: object, *, field_name: str) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise EconomicEvaluationProtocolError(
                f"{field_name} must be a finite JSON number"
            )
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise EconomicEvaluationProtocolError(
                    f"{field_name} mapping keys must be strings"
                )
            if key in frozen:
                raise EconomicEvaluationProtocolError(
                    f"{field_name} mapping has duplicate key {key!r}"
                )
            frozen[key] = _freeze_json(item, field_name=f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        items: list[Any] = list(value)  # type: ignore[arg-type]
        return tuple(
            _freeze_json(item, field_name=f"{field_name}[{index}]")
            for index, item in enumerate(items)
        )
    raise EconomicEvaluationProtocolError(
        f"{field_name} is not a JSON scalar, string-keyed mapping, or array"
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


def canonical_universe_id(symbols: tuple[str, ...]) -> str:
    """Return ``universe-`` plus the SHA-256 of the ordered symbol list."""

    if type(symbols) is not tuple or not symbols:
        raise EconomicEvaluationProtocolError(
            "universe symbols must be a nonempty exact tuple"
        )
    validated = [
        _normalized_symbol(symbol, field_name=f"universe symbol [{index}]")
        for index, symbol in enumerate(symbols)
    ]
    if len(set(validated)) != len(validated):
        raise EconomicEvaluationProtocolError("universe symbols must be unique")
    return "universe-" + _sha256(validated)


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class DecisionEvent:
    """Arm-neutral record of one market decision opportunity."""

    decision_event_id: str
    universe_id: str
    symbol: str
    decision_at: str
    market_date: str
    horizon_sessions: int
    horizon: str
    benchmark: str
    created_at: str
    resolution_window: Mapping[str, object]
    observation_start: str
    observation_end: str
    available_at: str
    recorded_at: str
    source_packet_id: str
    source_artifact_id: str
    source_artifact_sha256: str
    packet_event_cluster_id: str
    market_event_cluster_id: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("DecisionEvent instances must be created by build_decision_event")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"schema_version": DECISION_EVENT_SCHEMA}
        payload.update(AUTHORITY_FIELDS)
        for declared in dataclasses.fields(self):
            value = getattr(self, declared.name)
            if declared.name == "resolution_window":
                value = _thaw_json(value)
            payload[declared.name] = value
        return payload

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_EVENT_FIELD_NAMES = tuple(declared.name for declared in dataclasses.fields(DecisionEvent))
DECISION_EVENT_SERIALIZED_FIELDS = frozenset(
    _EVENT_FIELD_NAMES + ("schema_version",) + tuple(AUTHORITY_FIELDS)
)


def _new_decision_event(**fields: object) -> DecisionEvent:
    event = object.__new__(DecisionEvent)
    for field_name in _EVENT_FIELD_NAMES:
        object.__setattr__(event, field_name, fields[field_name])
    return event


def build_decision_event(
    *,
    universe_id: str,
    symbol: str,
    decision_at: str,
    market_date: str,
    horizon_sessions: int,
    horizon: str,
    benchmark: str,
    created_at: str,
    resolution_window: Mapping[str, object],
    observation_start: str,
    observation_end: str,
    available_at: str,
    recorded_at: str,
    source_packet_id: str,
    source_artifact_id: str,
    source_artifact_sha256: str,
) -> DecisionEvent:
    """Build one immutable arm-neutral decision event."""

    universe = _prefixed_digest(universe_id, prefix="universe-", field_name="universe_id")
    normalized_symbol = _normalized_symbol(symbol, field_name="symbol")
    normalized_benchmark = _normalized_symbol(benchmark, field_name="benchmark")
    sessions = _positive_int(horizon_sessions, field_name="horizon_sessions")
    horizon_token = _identifier(horizon, field_name="horizon")
    if horizon_token != f"{sessions}_sessions":
        raise EconomicEvaluationProtocolError(
            "horizon must equal '{horizon_sessions}_sessions'"
        )
    decision_moment = _canonical_utc_timestamp(decision_at, field_name="decision_at")
    created_moment = _canonical_utc_timestamp(created_at, field_name="created_at")
    observation_start_moment = _canonical_utc_timestamp(
        observation_start, field_name="observation_start"
    )
    observation_end_moment = _canonical_utc_timestamp(
        observation_end, field_name="observation_end"
    )
    available_moment = _canonical_utc_timestamp(available_at, field_name="available_at")
    recorded_moment = _canonical_utc_timestamp(recorded_at, field_name="recorded_at")
    event_market_date = _iso_date(market_date, field_name="market_date")

    if created_moment > decision_moment:
        raise EconomicEvaluationProtocolError("created_at cannot follow decision_at")
    if observation_start_moment > observation_end_moment:
        raise EconomicEvaluationProtocolError(
            "observation_start cannot follow observation_end"
        )
    if observation_end_moment > available_moment:
        raise EconomicEvaluationProtocolError(
            "observation_end cannot follow available_at"
        )
    if available_moment > decision_moment:
        raise EconomicEvaluationProtocolError("available_at cannot follow decision_at")
    if recorded_moment < available_moment:
        raise EconomicEvaluationProtocolError("recorded_at cannot precede available_at")
    if event_market_date.isoformat() != created_moment.date().isoformat():
        raise EconomicEvaluationProtocolError(
            "market_date must equal the UTC calendar date of created_at"
        )

    window_snapshot = _freeze_json(resolution_window, field_name="resolution_window")
    if not isinstance(window_snapshot, MappingProxyType):
        raise EconomicEvaluationProtocolError(
            "resolution_window must be a JSON mapping"
        )
    packet_identity = _identifier(source_packet_id, field_name="source_packet_id")
    reconciliation_row = {
        "source_packet_id": packet_identity,
        "ticker": normalized_symbol,
        "benchmark": normalized_benchmark,
        "horizon": horizon_token,
        "created_at": created_at,
        "resolution_window": _thaw_json(window_snapshot),
    }
    packet_key = packet_event_key(reconciliation_row)
    market_key = market_event_key(reconciliation_row)
    if packet_key is None:
        raise EconomicEvaluationProtocolError(
            "event material is not packet-event clusterable"
        )
    if market_key is None:
        raise EconomicEvaluationProtocolError(
            "event material is not market-event clusterable"
        )

    decision_material = {
        "schema_version": DECISION_EVENT_SCHEMA,
        "universe_id": universe,
        "symbol": normalized_symbol,
        "decision_at": decision_at,
        "market_date": event_market_date.isoformat(),
        "horizon_sessions": sessions,
        "benchmark": normalized_benchmark,
    }
    return _new_decision_event(
        decision_event_id="decision-event-" + _sha256(decision_material),
        universe_id=universe,
        symbol=normalized_symbol,
        decision_at=decision_at,
        market_date=event_market_date.isoformat(),
        horizon_sessions=sessions,
        horizon=horizon_token,
        benchmark=normalized_benchmark,
        created_at=created_at,
        resolution_window=window_snapshot,
        observation_start=observation_start,
        observation_end=observation_end,
        available_at=available_at,
        recorded_at=recorded_at,
        source_packet_id=packet_identity,
        source_artifact_id=_identifier(source_artifact_id, field_name="source_artifact_id"),
        source_artifact_sha256=_lower_sha256(
            source_artifact_sha256, field_name="source_artifact_sha256"
        ),
        packet_event_cluster_id="packet-event-cluster-" + _sha256(list(packet_key)),
        market_event_cluster_id="market-event-cluster-" + _sha256(list(market_key)),
    )


def validate_decision_event(value: object) -> DecisionEvent:
    """Validate one serialized decision event and return a fresh object."""

    values = _require_exact_fields(
        value,
        DECISION_EVENT_SERIALIZED_FIELDS,
        context="decision event",
    )
    if values["schema_version"] != DECISION_EVENT_SCHEMA:
        raise EconomicEvaluationProtocolError(
            f"schema_version must be {DECISION_EVENT_SCHEMA!r}"
        )
    _validate_authority_fields(values, context="decision event")
    rebuilt = build_decision_event(
        **{
            name: values[name]
            for name in _EVENT_FIELD_NAMES
            if name
            not in {
                "decision_event_id",
                "packet_event_cluster_id",
                "market_event_cluster_id",
                "resolution_window",
            }
        },
        resolution_window=values["resolution_window"],
    )
    try:
        submitted_bytes = _canonical_json_bytes(values)
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationProtocolError(
            f"decision event is not canonically serializable: {exc}"
        ) from exc
    if rebuilt.canonical_json_bytes() != submitted_bytes:
        raise EconomicEvaluationProtocolError(
            "decision event bytes do not match rebuilt canonical material"
        )
    return rebuilt


def _validate_authority_fields(values: Mapping[str, object], *, context: str) -> None:
    for authority_field, expected in AUTHORITY_FIELDS.items():
        actual = values[authority_field]
        if type(expected) is bool:
            valid = actual is expected
        else:
            valid = type(actual) is type(expected) and actual == expected
        if not valid:
            raise EconomicEvaluationProtocolError(
                f"{context}.{authority_field} is fixed to {expected!r}"
            )


def _serialized_list(value: object, *, field_name: str) -> list[object]:
    if type(value) is not list:
        raise EconomicEvaluationProtocolError(f"{field_name} must be a JSON array")
    return value


def _canonical_universe(
    value: object,
    *,
    field_name: str,
    expected_size: int,
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) != expected_size:
        raise EconomicEvaluationProtocolError(
            f"{field_name} must be an exact tuple of {expected_size} symbols"
        )
    symbols = tuple(
        _normalized_symbol(symbol, field_name=f"{field_name}[{index}]")
        for index, symbol in enumerate(value)
    )
    canonical_universe_id(symbols)
    return symbols


def _universe_sha256(symbols: tuple[str, ...]) -> str:
    return _sha256(list(symbols))


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class BitemporalInputManifest:
    """Immutable point-in-time cohort of canonical decision events."""

    manifest_id: str
    manifest_sha256: str
    dataset_id: str
    as_of_cutoff: str
    captured_at: str
    events: tuple[DecisionEvent, ...]
    ordered_event_payload_sha256: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError(
            "BitemporalInputManifest instances must be created by "
            "build_bitemporal_input_manifest"
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": BITEMPORAL_INPUT_MANIFEST_SCHEMA,
        }
        payload.update(AUTHORITY_FIELDS)
        payload.update(
            {
                "manifest_id": self.manifest_id,
                "manifest_sha256": self.manifest_sha256,
                "dataset_id": self.dataset_id,
                "as_of_cutoff": self.as_of_cutoff,
                "captured_at": self.captured_at,
                "events": [event.to_dict() for event in self.events],
                "ordered_event_payload_sha256": self.ordered_event_payload_sha256,
            }
        )
        return payload

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_MANIFEST_FIELD_NAMES = tuple(declared.name for declared in dataclasses.fields(BitemporalInputManifest))
BITEMPORAL_INPUT_MANIFEST_SERIALIZED_FIELDS = frozenset(
    _MANIFEST_FIELD_NAMES + ("schema_version",) + tuple(AUTHORITY_FIELDS)
)


def _new_bitemporal_input_manifest(**fields: object) -> BitemporalInputManifest:
    manifest = object.__new__(BitemporalInputManifest)
    for field_name in _MANIFEST_FIELD_NAMES:
        object.__setattr__(manifest, field_name, fields[field_name])
    return manifest


def _manifest_payload(
    *,
    dataset_id: str,
    as_of_cutoff: str,
    captured_at: str,
    events: tuple[DecisionEvent, ...],
    ordered_event_payload_sha256: str,
    manifest_id: str | None = None,
    manifest_sha256: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": BITEMPORAL_INPUT_MANIFEST_SCHEMA,
    }
    payload.update(AUTHORITY_FIELDS)
    if manifest_id is not None:
        payload["manifest_id"] = manifest_id
    if manifest_sha256 is not None:
        payload["manifest_sha256"] = manifest_sha256
    payload.update(
        {
            "dataset_id": dataset_id,
            "as_of_cutoff": as_of_cutoff,
            "captured_at": captured_at,
            "events": [event.to_dict() for event in events],
            "ordered_event_payload_sha256": ordered_event_payload_sha256,
        }
    )
    return payload


def build_bitemporal_input_manifest(
    *,
    dataset_id: str,
    as_of_cutoff: str,
    captured_at: str,
    events: tuple[DecisionEvent, ...],
) -> BitemporalInputManifest:
    """Bind a canonical event cohort without retaining caller-owned objects."""

    dataset = _identifier(dataset_id, field_name="dataset_id")
    cutoff_moment = _canonical_utc_timestamp(as_of_cutoff, field_name="as_of_cutoff")
    captured_moment = _canonical_utc_timestamp(captured_at, field_name="captured_at")
    if type(events) is not tuple or not events:
        raise EconomicEvaluationProtocolError("events must be a nonempty exact tuple")

    validated_events: list[DecisionEvent] = []
    artifact_digests: dict[str, str] = {}
    event_ids: set[str] = set()
    for index, event in enumerate(events):
        if type(event) is not DecisionEvent:
            raise EconomicEvaluationProtocolError(f"events[{index}] must be a DecisionEvent")
        validated = validate_decision_event(event.to_dict())
        if validated.decision_event_id in event_ids:
            raise EconomicEvaluationProtocolError("events must not duplicate decision_event_id")
        event_ids.add(validated.decision_event_id)
        decision_moment = _canonical_utc_timestamp(
            validated.decision_at, field_name=f"events[{index}].decision_at"
        )
        recorded_moment = _canonical_utc_timestamp(
            validated.recorded_at, field_name=f"events[{index}].recorded_at"
        )
        if decision_moment > cutoff_moment:
            raise EconomicEvaluationProtocolError(
                "as_of_cutoff cannot precede an event decision_at"
            )
        if captured_moment < recorded_moment:
            raise EconomicEvaluationProtocolError(
                "captured_at cannot precede an event recorded_at"
            )
        prior_digest = artifact_digests.setdefault(
            validated.source_artifact_id,
            validated.source_artifact_sha256,
        )
        if prior_digest != validated.source_artifact_sha256:
            raise EconomicEvaluationProtocolError(
                "one source_artifact_id cannot bind inconsistent artifact digests"
            )
        validated_events.append(validated)

    ordered_events = tuple(sorted(validated_events, key=lambda event: event.decision_event_id))
    ordered_payload_sha256 = _sha256([event.to_dict() for event in ordered_events])
    id_payload = _manifest_payload(
        dataset_id=dataset,
        as_of_cutoff=as_of_cutoff,
        captured_at=captured_at,
        events=ordered_events,
        ordered_event_payload_sha256=ordered_payload_sha256,
    )
    manifest_id = "input-manifest-" + _sha256(id_payload)
    sha_payload = _manifest_payload(
        dataset_id=dataset,
        as_of_cutoff=as_of_cutoff,
        captured_at=captured_at,
        events=ordered_events,
        ordered_event_payload_sha256=ordered_payload_sha256,
        manifest_id=manifest_id,
    )
    return _new_bitemporal_input_manifest(
        manifest_id=manifest_id,
        manifest_sha256=_sha256(sha_payload),
        dataset_id=dataset,
        as_of_cutoff=as_of_cutoff,
        captured_at=captured_at,
        events=ordered_events,
        ordered_event_payload_sha256=ordered_payload_sha256,
    )


def validate_bitemporal_input_manifest(value: object) -> BitemporalInputManifest:
    """Validate a serialized manifest through every nested event contract."""

    values = _require_exact_fields(
        value,
        BITEMPORAL_INPUT_MANIFEST_SERIALIZED_FIELDS,
        context="bitemporal input manifest",
    )
    if values["schema_version"] != BITEMPORAL_INPUT_MANIFEST_SCHEMA:
        raise EconomicEvaluationProtocolError(
            f"schema_version must be {BITEMPORAL_INPUT_MANIFEST_SCHEMA!r}"
        )
    _validate_authority_fields(values, context="bitemporal input manifest")
    _prefixed_digest(values["manifest_id"], prefix="input-manifest-", field_name="manifest_id")
    _lower_sha256(values["manifest_sha256"], field_name="manifest_sha256")
    _lower_sha256(
        values["ordered_event_payload_sha256"],
        field_name="ordered_event_payload_sha256",
    )
    raw_events = _serialized_list(values["events"], field_name="events")
    rebuilt = build_bitemporal_input_manifest(
        dataset_id=values["dataset_id"],
        as_of_cutoff=values["as_of_cutoff"],
        captured_at=values["captured_at"],
        events=tuple(validate_decision_event(raw_event) for raw_event in raw_events),
    )
    try:
        submitted_bytes = _canonical_json_bytes(values)
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationProtocolError(
            f"bitemporal input manifest is not canonically serializable: {exc}"
        ) from exc
    if rebuilt.canonical_json_bytes() != submitted_bytes:
        raise EconomicEvaluationProtocolError(
            "bitemporal input manifest bytes do not match rebuilt canonical material"
        )
    return rebuilt


@dataclasses.dataclass(frozen=True, slots=True)
class EvaluationSearchBudget:
    """Finite preregistered search budget for every TA-Control arm."""

    max_candidates_per_arm: int
    max_parameterizations_per_family: int
    max_total_evaluations: int

    def __post_init__(self) -> None:
        _positive_int(self.max_candidates_per_arm, field_name="max_candidates_per_arm")
        _positive_int(
            self.max_parameterizations_per_family,
            field_name="max_parameterizations_per_family",
        )
        _positive_int(self.max_total_evaluations, field_name="max_total_evaluations")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"schema_version": EVALUATION_SEARCH_BUDGET_SCHEMA}
        payload.update(AUTHORITY_FIELDS)
        payload.update(
            {
                "max_candidates_per_arm": self.max_candidates_per_arm,
                "max_parameterizations_per_family": self.max_parameterizations_per_family,
                "max_total_evaluations": self.max_total_evaluations,
            }
        )
        return payload

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_BUDGET_FIELD_NAMES = tuple(declared.name for declared in dataclasses.fields(EvaluationSearchBudget))
EVALUATION_SEARCH_BUDGET_SERIALIZED_FIELDS = frozenset(
    _BUDGET_FIELD_NAMES + ("schema_version",) + tuple(AUTHORITY_FIELDS)
)


def _validated_search_budget(value: object) -> EvaluationSearchBudget:
    values = _require_exact_fields(
        value,
        EVALUATION_SEARCH_BUDGET_SERIALIZED_FIELDS,
        context="evaluation search budget",
    )
    if values["schema_version"] != EVALUATION_SEARCH_BUDGET_SCHEMA:
        raise EconomicEvaluationProtocolError(
            f"search budget schema_version must be {EVALUATION_SEARCH_BUDGET_SCHEMA!r}"
        )
    _validate_authority_fields(values, context="evaluation search budget")
    budget = EvaluationSearchBudget(
        max_candidates_per_arm=values["max_candidates_per_arm"],
        max_parameterizations_per_family=values["max_parameterizations_per_family"],
        max_total_evaluations=values["max_total_evaluations"],
    )
    if budget.canonical_json_bytes() != _canonical_json_bytes(values):
        raise EconomicEvaluationProtocolError(
            "evaluation search budget bytes do not match canonical material"
        )
    return budget


def _validated_policy(value: object) -> StrategyEvaluationPolicy:
    policy_fields = frozenset(
        (
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
        )
    )
    values = _require_exact_fields(value, policy_fields, context="evaluation policy")
    try:
        policy = StrategyEvaluationPolicy(
            benchmark_symbol=values["benchmark_symbol"],
            holding_sessions=values["holding_sessions"],
            commission_bps_per_side=values["commission_bps_per_side"],
            half_spread_bps_per_side=values["half_spread_bps_per_side"],
            slippage_bps_per_side=values["slippage_bps_per_side"],
            round_trip_sides=values["round_trip_sides"],
        )
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationProtocolError(
            f"evaluation policy is invalid: {exc}"
        ) from exc
    if policy.canonical_json_bytes() != _canonical_json_bytes(values):
        raise EconomicEvaluationProtocolError(
            "evaluation policy bytes do not match canonical material"
        )
    return policy


def _frozen_policy_snapshot(policy: StrategyEvaluationPolicy) -> MappingProxyType:
    if type(policy) is not StrategyEvaluationPolicy:
        raise EconomicEvaluationProtocolError(
            "evaluation_policy must be an exact StrategyEvaluationPolicy"
        )
    validated = _validated_policy(policy.to_dict())
    snapshot = _freeze_json(validated.to_dict(), field_name="evaluation_policy")
    if not isinstance(snapshot, MappingProxyType):
        raise EconomicEvaluationProtocolError("evaluation policy must serialize to a mapping")
    if _canonical_json_bytes(_thaw_json(snapshot)) != validated.canonical_json_bytes():
        raise EconomicEvaluationProtocolError("evaluation policy snapshot is not canonical")
    return snapshot


def _ordered_partition_ids(value: object, *, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise EconomicEvaluationProtocolError(f"{field_name} must be a nonempty exact tuple")
    identifiers = tuple(
        _prefixed_digest(
            identifier,
            prefix="decision-event-",
            field_name=f"{field_name}[{index}]",
        )
        for index, identifier in enumerate(value)
    )
    if identifiers != tuple(sorted(identifiers)):
        raise EconomicEvaluationProtocolError(f"{field_name} must be canonically ordered")
    if len(set(identifiers)) != len(identifiers):
        raise EconomicEvaluationProtocolError(f"{field_name} must not contain duplicates")
    return identifiers


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class FrozenEvaluationProtocol:
    """Complete immutable TA-Control preregistration and sealed cohort binding."""

    protocol_id: str
    cohort: PointInTimeCohort
    cohort_id: str
    cohort_sha256: str
    market_date_partitions: "MarketDatePartitions"
    partition_id: str
    partition_sha256: str
    input_manifest: BitemporalInputManifest
    input_manifest_id: str
    input_manifest_sha256: str
    primary_universe: tuple[str, ...]
    primary_universe_sha256: str
    sensitivity_universe_50: tuple[str, ...]
    sensitivity_universe_50_sha256: str
    sensitivity_universe_100: tuple[str, ...]
    sensitivity_universe_100_sha256: str
    evaluation_policy: Mapping[str, object]
    evaluation_policy_sha256: str
    search_budget: EvaluationSearchBudget
    development_event_ids: tuple[str, ...]
    validation_event_ids: tuple[str, ...]
    holdout_event_ids: tuple[str, ...]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError(
            "FrozenEvaluationProtocol instances must be created by "
            "build_frozen_evaluation_protocol"
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": FROZEN_EVALUATION_PROTOCOL_SCHEMA,
        }
        payload.update(AUTHORITY_FIELDS)
        payload.update(
            {
                "protocol_id": self.protocol_id,
                "cohort": self.cohort.to_dict(),
                "cohort_id": self.cohort_id,
                "cohort_sha256": self.cohort_sha256,
                "market_date_partitions": self.market_date_partitions.to_dict(),
                "partition_id": self.partition_id,
                "partition_sha256": self.partition_sha256,
                "input_manifest": self.input_manifest.to_dict(),
                "input_manifest_id": self.input_manifest_id,
                "input_manifest_sha256": self.input_manifest_sha256,
                "primary_universe": list(self.primary_universe),
                "primary_universe_sha256": self.primary_universe_sha256,
                "sensitivity_universe_50": list(self.sensitivity_universe_50),
                "sensitivity_universe_50_sha256": self.sensitivity_universe_50_sha256,
                "sensitivity_universe_100": list(self.sensitivity_universe_100),
                "sensitivity_universe_100_sha256": self.sensitivity_universe_100_sha256,
                "evaluation_policy": _thaw_json(self.evaluation_policy),
                "evaluation_policy_sha256": self.evaluation_policy_sha256,
                "search_budget": self.search_budget.to_dict(),
                "control_arm_ids": list(CONTROL_ARM_IDS),
                "required_metrics": list(REQUIRED_METRICS),
                "route_id": _PROTOCOL_ROUTE_ID,
                "cadence": _PROTOCOL_CADENCE,
                "long_only": True,
                "cash_allowed": True,
                "max_leverage": _PROTOCOL_MAX_LEVERAGE,
                "holdout_status": _PROTOCOL_HOLDOUT_STATUS,
                "dependence_method": _PROTOCOL_DEPENDENCE_METHOD,
                "development_event_ids": list(self.development_event_ids),
                "validation_event_ids": list(self.validation_event_ids),
                "holdout_event_ids": list(self.holdout_event_ids),
            }
        )
        return payload

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_PROTOCOL_FIELD_NAMES = tuple(declared.name for declared in dataclasses.fields(FrozenEvaluationProtocol))
FROZEN_EVALUATION_PROTOCOL_SERIALIZED_FIELDS = frozenset(
    _PROTOCOL_FIELD_NAMES
    + (
        "schema_version",
        "control_arm_ids",
        "required_metrics",
        "route_id",
        "cadence",
        "long_only",
        "cash_allowed",
        "max_leverage",
        "holdout_status",
        "dependence_method",
    )
    + tuple(AUTHORITY_FIELDS)
)


def _new_frozen_evaluation_protocol(**fields: object) -> FrozenEvaluationProtocol:
    protocol = object.__new__(FrozenEvaluationProtocol)
    for field_name in _PROTOCOL_FIELD_NAMES:
        object.__setattr__(protocol, field_name, fields[field_name])
    return protocol


def _protocol_payload_without_id(protocol: FrozenEvaluationProtocol) -> dict[str, object]:
    payload = protocol.to_dict()
    payload.pop("protocol_id")
    return payload


def build_frozen_evaluation_protocol(
    *,
    cohort: PointInTimeCohort,
    market_date_partitions: "MarketDatePartitions",
    input_manifest: BitemporalInputManifest,
    primary_universe: tuple[str, ...],
    sensitivity_universe_50: tuple[str, ...],
    sensitivity_universe_100: tuple[str, ...],
    evaluation_policy: StrategyEvaluationPolicy,
    search_budget: EvaluationSearchBudget,
    development_event_ids: tuple[str, ...],
    validation_event_ids: tuple[str, ...],
    holdout_event_ids: tuple[str, ...],
) -> FrozenEvaluationProtocol:
    """Build the closed TA-Control protocol without executing any evaluation."""

    from tradingagents.dataflows.pit.partitions import (
        MarketDatePartitions,
        validate_market_date_partitions,
    )

    if type(cohort) is not PointInTimeCohort:
        raise EconomicEvaluationProtocolError(
            "cohort must be an exact PointInTimeCohort receipt"
        )
    try:
        frozen_cohort = validate_nonqualifying_point_in_time_cohort_record(
            cohort.to_dict()
        )
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationProtocolError("cohort canonical validation failed") from exc
    if type(market_date_partitions) is not MarketDatePartitions:
        raise EconomicEvaluationProtocolError(
            "market_date_partitions must be an exact MarketDatePartitions receipt"
        )
    try:
        partitioned = validate_market_date_partitions(
            market_date_partitions.to_dict()
        )
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationProtocolError(
            "market-date partition canonical validation failed"
        ) from exc
    if type(input_manifest) is not BitemporalInputManifest:
        raise EconomicEvaluationProtocolError(
            "input_manifest must be an exact BitemporalInputManifest"
        )
    manifest = validate_bitemporal_input_manifest(input_manifest.to_dict())
    primary = _canonical_universe(
        primary_universe,
        field_name="primary_universe",
        expected_size=75,
    )
    sensitivity_50 = _canonical_universe(
        sensitivity_universe_50,
        field_name="sensitivity_universe_50",
        expected_size=50,
    )
    sensitivity_100 = _canonical_universe(
        sensitivity_universe_100,
        field_name="sensitivity_universe_100",
        expected_size=100,
    )
    if primary != frozen_cohort.primary_universe_75:
        raise EconomicEvaluationProtocolError(
            "primary_universe must be the literal ranked cohort prefix of 75"
        )
    if sensitivity_50 != frozen_cohort.sensitivity_universe_50:
        raise EconomicEvaluationProtocolError(
            "sensitivity_universe_50 must be the literal ranked cohort prefix of 50"
        )
    if sensitivity_100 != frozen_cohort.sensitivity_universe_100:
        raise EconomicEvaluationProtocolError(
            "sensitivity_universe_100 must be the complete ranked cohort of 100"
        )
    if sensitivity_50 != sensitivity_100[:50] or primary != sensitivity_100[:75]:
        raise EconomicEvaluationProtocolError(
            "protocol universes must preserve literal ranked cohort prefixes"
        )
    if not set(sensitivity_50) < set(primary):
        raise EconomicEvaluationProtocolError(
            "sensitivity_universe_50 must be a strict subset of primary_universe"
        )
    if not set(primary) < set(sensitivity_100):
        raise EconomicEvaluationProtocolError(
            "sensitivity_universe_100 must be a strict superset of primary_universe"
        )
    policy_snapshot = _frozen_policy_snapshot(evaluation_policy)
    if policy_snapshot["benchmark_symbol"] != "SPY":
        raise EconomicEvaluationProtocolError("evaluation policy benchmark_symbol must be SPY")
    if policy_snapshot["holding_sessions"] != 5:
        raise EconomicEvaluationProtocolError("evaluation policy holding_sessions must be 5")
    if type(search_budget) is not EvaluationSearchBudget:
        raise EconomicEvaluationProtocolError(
            "search_budget must be an exact EvaluationSearchBudget"
        )
    budget = _validated_search_budget(search_budget.to_dict())
    if budget.max_total_evaluations < budget.max_candidates_per_arm * len(CONTROL_ARM_IDS):
        raise EconomicEvaluationProtocolError(
            "max_total_evaluations cannot be below candidates-per-arm times control arms"
        )

    primary_universe_id = canonical_universe_id(primary)
    if (
        partitioned.primary_universe != primary
        or partitioned.primary_universe_id != primary_universe_id
    ):
        raise EconomicEvaluationProtocolError(
            "market-date partitions do not bind the ranked primary cohort"
        )
    if datetime.datetime.fromisoformat(
        frozen_cohort.selection_time
    ) > datetime.datetime.fromisoformat(partitioned.registered_at):
        raise EconomicEvaluationProtocolError(
            "cohort must be frozen before weekly decision-date registration"
        )
    partition_events = tuple(
        sorted(partitioned.events, key=lambda event: event.decision_event_id)
    )
    if manifest.events != partition_events:
        raise EconomicEvaluationProtocolError(
            "input manifest must contain the complete partition decision events"
        )
    for event in manifest.events:
        if event.universe_id != primary_universe_id:
            raise EconomicEvaluationProtocolError(
                "every manifest event must use the canonical primary universe ID"
            )
        if event.symbol not in primary:
            raise EconomicEvaluationProtocolError(
                "every manifest event symbol must belong to primary_universe"
            )
        if event.benchmark != policy_snapshot["benchmark_symbol"]:
            raise EconomicEvaluationProtocolError(
                "every manifest event benchmark must match evaluation policy"
            )
        if event.horizon_sessions != policy_snapshot["holding_sessions"]:
            raise EconomicEvaluationProtocolError(
                "every manifest event horizon must match evaluation policy"
            )

    development_ids = _ordered_partition_ids(
        development_event_ids,
        field_name="development_event_ids",
    )
    validation_ids = _ordered_partition_ids(
        validation_event_ids,
        field_name="validation_event_ids",
    )
    holdout_ids = _ordered_partition_ids(
        holdout_event_ids,
        field_name="holdout_event_ids",
    )
    manifest_ids = {event.decision_event_id for event in manifest.events}
    partition_ids = development_ids + validation_ids + holdout_ids
    if len(set(partition_ids)) != len(partition_ids):
        raise EconomicEvaluationProtocolError("protocol partitions must be pairwise disjoint")
    if set(partition_ids) != manifest_ids:
        raise EconomicEvaluationProtocolError(
            "protocol partitions must be exhaustive for exactly the manifest events"
        )
    if (
        development_ids != partitioned.development_event_ids
        or validation_ids != partitioned.validation_event_ids
        or holdout_ids != partitioned.holdout_event_ids
    ):
        raise EconomicEvaluationProtocolError(
            "protocol partitions must match the complete market-date partition receipt"
        )

    provisional = _new_frozen_evaluation_protocol(
        protocol_id="",
        cohort=frozen_cohort,
        cohort_id=frozen_cohort.cohort_id,
        cohort_sha256=frozen_cohort.cohort_sha256,
        market_date_partitions=partitioned,
        partition_id=partitioned.partition_id,
        partition_sha256=partitioned.partition_sha256,
        input_manifest=manifest,
        input_manifest_id=manifest.manifest_id,
        input_manifest_sha256=manifest.manifest_sha256,
        primary_universe=primary,
        primary_universe_sha256=_universe_sha256(primary),
        sensitivity_universe_50=sensitivity_50,
        sensitivity_universe_50_sha256=_universe_sha256(sensitivity_50),
        sensitivity_universe_100=sensitivity_100,
        sensitivity_universe_100_sha256=_universe_sha256(sensitivity_100),
        evaluation_policy=policy_snapshot,
        evaluation_policy_sha256=_sha256(_thaw_json(policy_snapshot)),
        search_budget=budget,
        development_event_ids=development_ids,
        validation_event_ids=validation_ids,
        holdout_event_ids=holdout_ids,
    )
    return _new_frozen_evaluation_protocol(
        protocol_id="economic-evaluation-protocol-"
        + _sha256(_protocol_payload_without_id(provisional)),
        cohort=provisional.cohort,
        cohort_id=provisional.cohort_id,
        cohort_sha256=provisional.cohort_sha256,
        market_date_partitions=provisional.market_date_partitions,
        partition_id=provisional.partition_id,
        partition_sha256=provisional.partition_sha256,
        input_manifest=provisional.input_manifest,
        input_manifest_id=provisional.input_manifest_id,
        input_manifest_sha256=provisional.input_manifest_sha256,
        primary_universe=provisional.primary_universe,
        primary_universe_sha256=provisional.primary_universe_sha256,
        sensitivity_universe_50=provisional.sensitivity_universe_50,
        sensitivity_universe_50_sha256=provisional.sensitivity_universe_50_sha256,
        sensitivity_universe_100=provisional.sensitivity_universe_100,
        sensitivity_universe_100_sha256=provisional.sensitivity_universe_100_sha256,
        evaluation_policy=provisional.evaluation_policy,
        evaluation_policy_sha256=provisional.evaluation_policy_sha256,
        search_budget=provisional.search_budget,
        development_event_ids=provisional.development_event_ids,
        validation_event_ids=provisional.validation_event_ids,
        holdout_event_ids=provisional.holdout_event_ids,
    )


def _tuple_from_serialized_symbols(
    value: object,
    *,
    field_name: str,
    expected_size: int,
) -> tuple[str, ...]:
    raw_values = _serialized_list(value, field_name=field_name)
    return _canonical_universe(
        tuple(raw_values),
        field_name=field_name,
        expected_size=expected_size,
    )


def _tuple_from_serialized_partition_ids(
    value: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    return _ordered_partition_ids(
        tuple(_serialized_list(value, field_name=field_name)),
        field_name=field_name,
    )


def validate_frozen_evaluation_protocol(value: object) -> FrozenEvaluationProtocol:
    """Validate a complete serialized TA-Control protocol by canonical rebuild."""

    values = _require_exact_fields(
        value,
        FROZEN_EVALUATION_PROTOCOL_SERIALIZED_FIELDS,
        context="frozen evaluation protocol",
    )
    if values["schema_version"] != FROZEN_EVALUATION_PROTOCOL_SCHEMA:
        raise EconomicEvaluationProtocolError(
            f"schema_version must be {FROZEN_EVALUATION_PROTOCOL_SCHEMA!r}"
        )
    _validate_authority_fields(values, context="frozen evaluation protocol")
    _prefixed_digest(
        values["protocol_id"],
        prefix="economic-evaluation-protocol-",
        field_name="protocol_id",
    )
    if values["control_arm_ids"] != list(CONTROL_ARM_IDS):
        raise EconomicEvaluationProtocolError("control_arm_ids must be the exact frozen arm list")
    if values["required_metrics"] != list(REQUIRED_METRICS):
        raise EconomicEvaluationProtocolError("required_metrics must be the exact frozen metric list")
    fixed_values = {
        "route_id": _PROTOCOL_ROUTE_ID,
        "cadence": _PROTOCOL_CADENCE,
        "max_leverage": _PROTOCOL_MAX_LEVERAGE,
        "holdout_status": _PROTOCOL_HOLDOUT_STATUS,
        "dependence_method": _PROTOCOL_DEPENDENCE_METHOD,
    }
    for field_name, expected in fixed_values.items():
        if values[field_name] != expected:
            raise EconomicEvaluationProtocolError(f"{field_name} is fixed to {expected!r}")
    if values["long_only"] is not True or values["cash_allowed"] is not True:
        raise EconomicEvaluationProtocolError("long_only and cash_allowed are fixed true")
    _prefixed_digest(
        values["input_manifest_id"],
        prefix="input-manifest-",
        field_name="input_manifest_id",
    )
    _lower_sha256(values["input_manifest_sha256"], field_name="input_manifest_sha256")
    _prefixed_digest(
        values["cohort_id"],
        prefix="point-in-time-cohort-",
        field_name="cohort_id",
    )
    _lower_sha256(values["cohort_sha256"], field_name="cohort_sha256")
    _prefixed_digest(
        values["partition_id"],
        prefix="market-date-partitions-",
        field_name="partition_id",
    )
    _lower_sha256(values["partition_sha256"], field_name="partition_sha256")
    for field_name in (
        "primary_universe_sha256",
        "sensitivity_universe_50_sha256",
        "sensitivity_universe_100_sha256",
        "evaluation_policy_sha256",
    ):
        _lower_sha256(values[field_name], field_name=field_name)

    from tradingagents.dataflows.pit.partitions import validate_market_date_partitions

    try:
        cohort = validate_nonqualifying_point_in_time_cohort_record(values["cohort"])
        partitions = validate_market_date_partitions(values["market_date_partitions"])
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationProtocolError(
            "nested cohort or partition receipt is invalid"
        ) from exc
    manifest = validate_bitemporal_input_manifest(values["input_manifest"])
    policy = _validated_policy(values["evaluation_policy"])
    budget = _validated_search_budget(values["search_budget"])
    rebuilt = build_frozen_evaluation_protocol(
        cohort=cohort,
        market_date_partitions=partitions,
        input_manifest=manifest,
        primary_universe=_tuple_from_serialized_symbols(
            values["primary_universe"],
            field_name="primary_universe",
            expected_size=75,
        ),
        sensitivity_universe_50=_tuple_from_serialized_symbols(
            values["sensitivity_universe_50"],
            field_name="sensitivity_universe_50",
            expected_size=50,
        ),
        sensitivity_universe_100=_tuple_from_serialized_symbols(
            values["sensitivity_universe_100"],
            field_name="sensitivity_universe_100",
            expected_size=100,
        ),
        evaluation_policy=policy,
        search_budget=budget,
        development_event_ids=_tuple_from_serialized_partition_ids(
            values["development_event_ids"],
            field_name="development_event_ids",
        ),
        validation_event_ids=_tuple_from_serialized_partition_ids(
            values["validation_event_ids"],
            field_name="validation_event_ids",
        ),
        holdout_event_ids=_tuple_from_serialized_partition_ids(
            values["holdout_event_ids"],
            field_name="holdout_event_ids",
        ),
    )
    try:
        submitted_bytes = _canonical_json_bytes(values)
    except (TypeError, ValueError) as exc:
        raise EconomicEvaluationProtocolError(
            f"frozen evaluation protocol is not canonically serializable: {exc}"
        ) from exc
    if rebuilt.canonical_json_bytes() != submitted_bytes:
        raise EconomicEvaluationProtocolError(
            "frozen evaluation protocol bytes do not match rebuilt canonical material"
        )
    return rebuilt
