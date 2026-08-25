"""Pure chronological partitions for point-in-time economic evaluation."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping

from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    validate_market_session_calendar,
)
from tradingagents.dataflows.pit.records import PointInTimeDataError
from tradingagents.evals.economic_evaluation_protocol import (
    DecisionEvent,
    validate_decision_event,
)

_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_SCHEMA = "market_date_partitions/v1"
_PURGE_SESSIONS = 5


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


def _authority(payload: Mapping[str, object], *, label: str) -> None:
    if (
        payload["analysis_only"] is not True
        or payload["execution_authority"] != "none"
        or type(payload["execution_authority"]) is not str
        or payload["can_submit_orders"] is not False
    ):
        raise PointInTimeDataError(f"{label} authority fields are fixed")


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class MarketDatePartitions:
    """An exhaustive chronological split with explicit boundary protections."""

    partition_id: str
    partition_sha256: str
    market_calendar: MarketSessionCalendar
    market_dates: tuple[str, ...]
    events: tuple[DecisionEvent, ...]
    development_market_dates: tuple[str, ...]
    validation_market_dates: tuple[str, ...]
    holdout_market_dates: tuple[str, ...]
    development_event_ids: tuple[str, ...]
    validation_event_ids: tuple[str, ...]
    holdout_event_ids: tuple[str, ...]
    development_eligible_event_ids: tuple[str, ...]
    validation_eligible_event_ids: tuple[str, ...]
    holdout_eligible_event_ids: tuple[str, ...]
    development_validation_purge_dates: tuple[str, ...]
    development_validation_embargo_dates: tuple[str, ...]
    validation_holdout_purge_dates: tuple[str, ...]
    validation_holdout_embargo_dates: tuple[str, ...]
    development_validation_purge_event_ids: tuple[str, ...]
    development_validation_embargo_event_ids: tuple[str, ...]
    validation_holdout_purge_event_ids: tuple[str, ...]
    validation_holdout_embargo_event_ids: tuple[str, ...]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("MarketDatePartitions instances must be created by its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA,
            "partition_id": self.partition_id,
            "partition_sha256": self.partition_sha256,
            "market_calendar": self.market_calendar.to_dict(),
            "market_dates": list(self.market_dates),
            "events": [event.to_dict() for event in self.events],
            "development_market_dates": list(self.development_market_dates),
            "validation_market_dates": list(self.validation_market_dates),
            "holdout_market_dates": list(self.holdout_market_dates),
            "development_event_ids": list(self.development_event_ids),
            "validation_event_ids": list(self.validation_event_ids),
            "holdout_event_ids": list(self.holdout_event_ids),
            "development_eligible_event_ids": list(
                self.development_eligible_event_ids
            ),
            "validation_eligible_event_ids": list(self.validation_eligible_event_ids),
            "holdout_eligible_event_ids": list(self.holdout_eligible_event_ids),
            "development_validation_purge_dates": list(
                self.development_validation_purge_dates
            ),
            "development_validation_embargo_dates": list(
                self.development_validation_embargo_dates
            ),
            "validation_holdout_purge_dates": list(self.validation_holdout_purge_dates),
            "validation_holdout_embargo_dates": list(
                self.validation_holdout_embargo_dates
            ),
            "development_validation_purge_event_ids": list(
                self.development_validation_purge_event_ids
            ),
            "development_validation_embargo_event_ids": list(
                self.development_validation_embargo_event_ids
            ),
            "validation_holdout_purge_event_ids": list(
                self.validation_holdout_purge_event_ids
            ),
            "validation_holdout_embargo_event_ids": list(
                self.validation_holdout_embargo_event_ids
            ),
            "purge_sessions": _PURGE_SESSIONS,
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_FIELD_NAMES = tuple(field.name for field in dataclasses.fields(MarketDatePartitions))
_SERIALIZED_FIELDS = frozenset(
    _FIELD_NAMES + ("schema_version", "purge_sessions") + tuple(_AUTHORITY)
)


def _new_partitions(**fields: object) -> MarketDatePartitions:
    partitions = object.__new__(MarketDatePartitions)
    for name in _FIELD_NAMES:
        object.__setattr__(partitions, name, fields[name])
    return partitions


def _canonical_events(value: object, *, market_dates: tuple[str, ...]) -> tuple[DecisionEvent, ...]:
    if type(value) is not tuple or not value:
        raise PointInTimeDataError("events must be a nonempty exact tuple")
    validated: list[DecisionEvent] = []
    event_ids: set[str] = set()
    known_dates = set(market_dates)
    for index, event in enumerate(value):
        if type(event) is not DecisionEvent:
            raise PointInTimeDataError(f"events[{index}] must be a DecisionEvent")
        parsed = validate_decision_event(event.to_dict())
        if parsed.market_date not in known_dates:
            raise PointInTimeDataError("event market_date is not in the calendar")
        if parsed.decision_event_id in event_ids:
            raise PointInTimeDataError("events must not duplicate decision_event_id")
        event_ids.add(parsed.decision_event_id)
        validated.append(parsed)
    return tuple(sorted(validated, key=lambda event: event.decision_event_id))


def _event_ids_for_dates(
    events: tuple[DecisionEvent, ...],
    dates: tuple[str, ...],
) -> tuple[str, ...]:
    date_set = set(dates)
    return tuple(
        sorted(event.decision_event_id for event in events if event.market_date in date_set)
    )


def build_market_date_partitions(
    *,
    market_calendar: MarketSessionCalendar,
    events: tuple[DecisionEvent, ...],
) -> MarketDatePartitions:
    """Split one source-backed market calendar and enforce boundary masks."""

    if type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError("market_calendar must be an exact MarketSessionCalendar")
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    dates = calendar.market_dates
    validated_events = _canonical_events(events, market_dates=dates)
    total = len(dates)
    development_end = total * 60 // 100
    validation_end = development_end + total * 20 // 100
    development_dates = dates[:development_end]
    validation_dates = dates[development_end:validation_end]
    holdout_dates = dates[validation_end:]
    if (
        len(development_dates) <= _PURGE_SESSIONS
        or len(validation_dates) <= _PURGE_SESSIONS * 2
        or len(holdout_dates) <= _PURGE_SESSIONS
    ):
        raise PointInTimeDataError(
            "partitions must retain evaluable sessions after five-session guards"
        )
    development_ids = _event_ids_for_dates(validated_events, development_dates)
    validation_ids = _event_ids_for_dates(validated_events, validation_dates)
    holdout_ids = _event_ids_for_dates(validated_events, holdout_dates)
    if not development_ids or not validation_ids or not holdout_ids:
        raise PointInTimeDataError("each partition must contain at least one decision event")
    assigned = development_ids + validation_ids + holdout_ids
    if len(set(assigned)) != len(assigned) or set(assigned) != {
        event.decision_event_id for event in validated_events
    }:
        raise PointInTimeDataError("partition event assignment is not exhaustive and disjoint")
    development_validation_purge_dates = development_dates[-_PURGE_SESSIONS:]
    development_validation_embargo_dates = validation_dates[:_PURGE_SESSIONS]
    validation_holdout_purge_dates = validation_dates[-_PURGE_SESSIONS:]
    validation_holdout_embargo_dates = holdout_dates[:_PURGE_SESSIONS]
    development_validation_purge_ids = _event_ids_for_dates(
        validated_events, development_validation_purge_dates
    )
    development_validation_embargo_ids = _event_ids_for_dates(
        validated_events, development_validation_embargo_dates
    )
    validation_holdout_purge_ids = _event_ids_for_dates(
        validated_events, validation_holdout_purge_dates
    )
    validation_holdout_embargo_ids = _event_ids_for_dates(
        validated_events, validation_holdout_embargo_dates
    )
    development_eligible_ids = tuple(
        event_id
        for event_id in development_ids
        if event_id not in set(development_validation_purge_ids)
    )
    validation_eligible_ids = tuple(
        event_id
        for event_id in validation_ids
        if event_id
        not in set(development_validation_embargo_ids)
        | set(validation_holdout_purge_ids)
    )
    holdout_eligible_ids = tuple(
        event_id
        for event_id in holdout_ids
        if event_id not in set(validation_holdout_embargo_ids)
    )
    if not all(
        (development_eligible_ids, validation_eligible_ids, holdout_eligible_ids)
    ):
        raise PointInTimeDataError("each partition must retain an eligible decision event")
    fields: dict[str, object] = {
        "market_calendar": calendar,
        "market_dates": dates,
        "events": validated_events,
        "development_market_dates": development_dates,
        "validation_market_dates": validation_dates,
        "holdout_market_dates": holdout_dates,
        "development_event_ids": development_ids,
        "validation_event_ids": validation_ids,
        "holdout_event_ids": holdout_ids,
        "development_eligible_event_ids": development_eligible_ids,
        "validation_eligible_event_ids": validation_eligible_ids,
        "holdout_eligible_event_ids": holdout_eligible_ids,
        "development_validation_purge_dates": development_validation_purge_dates,
        "development_validation_embargo_dates": development_validation_embargo_dates,
        "validation_holdout_purge_dates": validation_holdout_purge_dates,
        "validation_holdout_embargo_dates": validation_holdout_embargo_dates,
        "development_validation_purge_event_ids": development_validation_purge_ids,
        "development_validation_embargo_event_ids": development_validation_embargo_ids,
        "validation_holdout_purge_event_ids": validation_holdout_purge_ids,
        "validation_holdout_embargo_event_ids": validation_holdout_embargo_ids,
    }
    identity = {
        "schema_version": _SCHEMA,
        "market_calendar": calendar.to_dict(),
        "market_dates": list(dates),
        "events": [event.to_dict() for event in validated_events],
        "development_market_dates": list(development_dates),
        "validation_market_dates": list(validation_dates),
        "holdout_market_dates": list(holdout_dates),
        "development_event_ids": list(development_ids),
        "validation_event_ids": list(validation_ids),
        "holdout_event_ids": list(holdout_ids),
        "development_eligible_event_ids": list(development_eligible_ids),
        "validation_eligible_event_ids": list(validation_eligible_ids),
        "holdout_eligible_event_ids": list(holdout_eligible_ids),
        "development_validation_purge_dates": list(
            fields["development_validation_purge_dates"]
        ),
        "development_validation_embargo_dates": list(
            fields["development_validation_embargo_dates"]
        ),
        "validation_holdout_purge_dates": list(fields["validation_holdout_purge_dates"]),
        "validation_holdout_embargo_dates": list(
            fields["validation_holdout_embargo_dates"]
        ),
        "development_validation_purge_event_ids": list(
            development_validation_purge_ids
        ),
        "development_validation_embargo_event_ids": list(
            development_validation_embargo_ids
        ),
        "validation_holdout_purge_event_ids": list(validation_holdout_purge_ids),
        "validation_holdout_embargo_event_ids": list(
            validation_holdout_embargo_ids
        ),
        "purge_sessions": _PURGE_SESSIONS,
        **_AUTHORITY,
    }
    partition_id = "market-date-partitions-" + _sha256(identity)
    digest = _sha256({**identity, "partition_id": partition_id})
    return _new_partitions(
        partition_id=partition_id,
        partition_sha256=digest,
        **fields,
    )


def validate_market_date_partitions(value: object) -> MarketDatePartitions:
    """Rebuild full market-date partitions from source-bound decision events."""

    if not isinstance(value, Mapping) or set(value) != _SERIALIZED_FIELDS:
        raise PointInTimeDataError("market-date partition fields are invalid")
    payload = dict(value)
    if payload["schema_version"] != _SCHEMA or payload["purge_sessions"] != _PURGE_SESSIONS:
        raise PointInTimeDataError("market-date partition schema is invalid")
    _authority(payload, label="market-date partitions")
    if (
        type(payload["market_dates"]) is not list
        or type(payload["events"]) is not list
        or not isinstance(payload["market_calendar"], Mapping)
    ):
        raise PointInTimeDataError("market-date partition source material is invalid")
    calendar = validate_market_session_calendar(payload["market_calendar"])
    if tuple(payload["market_dates"]) != calendar.market_dates:
        raise PointInTimeDataError("partition market dates do not match market calendar")
    rebuilt = build_market_date_partitions(
        market_calendar=calendar,
        events=tuple(validate_decision_event(event) for event in payload["events"]),
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise PointInTimeDataError("market-date partition bytes do not match canonical rebuild")
    return rebuilt
