"""Pure chronological partitions for point-in-time economic evaluation."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from tradingagents.dataflows.pit.market_calendar import (
    MarketSessionCalendar,
    validate_market_session_calendar,
)
from tradingagents.dataflows.pit.records import PointInTimeDataError

if TYPE_CHECKING:
    from tradingagents.evals.economic_evaluation_protocol import DecisionEvent

_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_SCHEMA = "market_date_partitions/v2"
_PURGE_SESSIONS = 5
_CADENCE = "weekly"
_PRIMARY_UNIVERSE_SIZE = 75
_PROTOCOL_CONTRACTS: tuple[object, object, object] | None = None


def _protocol_contracts() -> tuple[object, object, object]:
    """Bind protocol contracts only after PIT package initialization completes."""

    global _PROTOCOL_CONTRACTS
    if _PROTOCOL_CONTRACTS is None:
        from tradingagents.evals.economic_evaluation_protocol import (
            DecisionEvent,
            canonical_universe_id,
            validate_decision_event,
        )

        _PROTOCOL_CONTRACTS = (
            DecisionEvent,
            canonical_universe_id,
            validate_decision_event,
        )
    return _PROTOCOL_CONTRACTS


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
    cadence: str
    registered_at: str
    primary_universe: tuple[str, ...]
    primary_universe_id: str
    decision_market_dates: tuple[str, ...]
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
            "cadence": self.cadence,
            "registered_at": self.registered_at,
            "primary_universe": list(self.primary_universe),
            "primary_universe_id": self.primary_universe_id,
            "decision_market_dates": list(self.decision_market_dates),
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


def _canonical_timestamp(value: object, *, label: str) -> tuple[str, dt.datetime]:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds") from exc
    if parsed.tzinfo != dt.timezone.utc or parsed.isoformat(timespec="seconds") != value:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    return value, parsed


def _weekly_decision_dates(
    value: object,
    *,
    market_dates: tuple[str, ...],
) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise PointInTimeDataError("decision_market_dates must be a nonempty exact tuple")
    known_market_dates = frozenset(market_dates)
    parsed_dates: list[dt.date] = []
    for index, raw_date in enumerate(value):
        if type(raw_date) is not str:
            raise PointInTimeDataError(
                f"decision_market_dates[{index}] must be an ISO market date"
            )
        try:
            parsed = dt.date.fromisoformat(raw_date)
        except ValueError as exc:
            raise PointInTimeDataError(
                f"decision_market_dates[{index}] must be an ISO market date"
            ) from exc
        if parsed.isoformat() != raw_date or raw_date not in known_market_dates:
            raise PointInTimeDataError(
                "every decision market date must be registered in the source calendar"
            )
        parsed_dates.append(parsed)
    dates = tuple(item.isoformat() for item in parsed_dates)
    if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
        raise PointInTimeDataError(
            "decision market dates must be unique and chronological"
        )

    sessions_by_week: dict[tuple[int, int], list[str]] = {}
    for market_date in market_dates:
        session = dt.date.fromisoformat(market_date)
        iso = session.isocalendar()
        sessions_by_week.setdefault((iso.year, iso.week), []).append(market_date)
    previous_week_start: dt.date | None = None
    for parsed, market_date in zip(parsed_dates, dates, strict=True):
        iso = parsed.isocalendar()
        week_key = (iso.year, iso.week)
        if market_date != sessions_by_week[week_key][-1]:
            raise PointInTimeDataError(
                "weekly decision dates must be the final registered market session of each week"
            )
        week_start = parsed - dt.timedelta(days=parsed.weekday())
        if (
            previous_week_start is not None
            and week_start - previous_week_start != dt.timedelta(days=7)
        ):
            raise PointInTimeDataError(
                "weekly decision dates must cover consecutive source-calendar weeks"
            )
        previous_week_start = week_start
    return dates


def _canonical_primary_universe(value: object) -> tuple[tuple[str, ...], str]:
    _, canonical_universe_id, _ = _protocol_contracts()

    if type(value) is not tuple or len(value) != _PRIMARY_UNIVERSE_SIZE:
        raise PointInTimeDataError("primary_universe must be an exact 75-symbol tuple")
    try:
        universe_id = canonical_universe_id(value)
    except (TypeError, ValueError) as exc:
        raise PointInTimeDataError("primary_universe is invalid") from exc
    return value, universe_id


def _canonical_events(
    value: object,
    *,
    decision_market_dates: tuple[str, ...],
    primary_universe: tuple[str, ...],
    primary_universe_id: str,
    registered_at: dt.datetime,
) -> tuple[DecisionEvent, ...]:
    DecisionEvent, _, validate_decision_event = _protocol_contracts()

    if type(value) is not tuple or not value:
        raise PointInTimeDataError("events must be a nonempty exact tuple")
    validated: list[DecisionEvent] = []
    event_ids: set[str] = set()
    known_dates = set(decision_market_dates)
    events_by_date: dict[str, list[DecisionEvent]] = {
        market_date: [] for market_date in decision_market_dates
    }
    for index, event in enumerate(value):
        if type(event) is not DecisionEvent:
            raise PointInTimeDataError(f"events[{index}] must be a DecisionEvent")
        parsed = validate_decision_event(event.to_dict())
        if parsed.market_date not in known_dates:
            raise PointInTimeDataError("event market_date is not a registered decision date")
        if parsed.decision_event_id in event_ids:
            raise PointInTimeDataError("events must not duplicate decision_event_id")
        if parsed.universe_id != primary_universe_id:
            raise PointInTimeDataError(
                "every event must use the registered primary universe identity"
            )
        if parsed.symbol not in primary_universe:
            raise PointInTimeDataError(
                "every event symbol must belong to the registered primary universe"
            )
        if dt.datetime.fromisoformat(parsed.decision_at) <= registered_at:
            raise PointInTimeDataError(
                "decision dates must be registered before their decision events"
            )
        event_ids.add(parsed.decision_event_id)
        validated.append(parsed)
        events_by_date[parsed.market_date].append(parsed)
    expected_symbols = set(primary_universe)
    for market_date, date_events in events_by_date.items():
        symbols = [event.symbol for event in date_events]
        if len(date_events) != _PRIMARY_UNIVERSE_SIZE or set(symbols) != expected_symbols:
            raise PointInTimeDataError(
                f"decision date {market_date} must contain exactly one event "
                "for each primary symbol"
            )
        if len(symbols) != len(set(symbols)):
            raise PointInTimeDataError(
                f"decision date {market_date} must not duplicate a primary symbol"
            )
    if len(validated) != len(decision_market_dates) * _PRIMARY_UNIVERSE_SIZE:
        raise PointInTimeDataError(
            "events must exhaust the 75-symbol primary universe on every decision date"
        )
    return tuple(
        sorted(validated, key=lambda event: (event.market_date, event.decision_event_id))
    )


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
    cadence: str,
    registered_at: str,
    primary_universe: tuple[str, ...],
    decision_market_dates: tuple[str, ...],
    events: tuple[DecisionEvent, ...],
) -> MarketDatePartitions:
    """Split preregistered weekly decisions and enforce boundary masks."""

    if type(market_calendar) is not MarketSessionCalendar:
        raise PointInTimeDataError("market_calendar must be an exact MarketSessionCalendar")
    if cadence != _CADENCE or type(cadence) is not str:
        raise PointInTimeDataError("cadence is fixed to 'weekly'")
    calendar = validate_market_session_calendar(market_calendar.to_dict())
    registration_text, registration = _canonical_timestamp(
        registered_at,
        label="registered_at",
    )
    primary, primary_id = _canonical_primary_universe(primary_universe)
    dates = _weekly_decision_dates(
        decision_market_dates,
        market_dates=calendar.market_dates,
    )
    validated_events = _canonical_events(
        events,
        decision_market_dates=dates,
        primary_universe=primary,
        primary_universe_id=primary_id,
        registered_at=registration,
    )
    total = len(dates)
    development_end = total * 60 // 100
    validation_end = development_end + total * 20 // 100
    development_dates = dates[:development_end]
    validation_dates = dates[development_end:validation_end]
    holdout_dates = dates[validation_end:]
    if not (
        development_dates
        and validation_dates
        and holdout_dates
        and development_dates[-1] < validation_dates[0] < holdout_dates[0]
    ):
        raise PointInTimeDataError(
            "partitions must be nonempty, chronological, and future-leak free"
        )
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
        "cadence": _CADENCE,
        "registered_at": registration_text,
        "primary_universe": primary,
        "primary_universe_id": primary_id,
        "decision_market_dates": dates,
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
        "cadence": _CADENCE,
        "registered_at": registration_text,
        "primary_universe": list(primary),
        "primary_universe_id": primary_id,
        "decision_market_dates": list(dates),
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

    _, _, validate_decision_event = _protocol_contracts()

    if not isinstance(value, Mapping) or set(value) != _SERIALIZED_FIELDS:
        raise PointInTimeDataError("market-date partition fields are invalid")
    payload = dict(value)
    if payload["schema_version"] != _SCHEMA or payload["purge_sessions"] != _PURGE_SESSIONS:
        raise PointInTimeDataError("market-date partition schema is invalid")
    _authority(payload, label="market-date partitions")
    if (
        type(payload["decision_market_dates"]) is not list
        or type(payload["primary_universe"]) is not list
        or type(payload["events"]) is not list
        or not isinstance(payload["market_calendar"], Mapping)
    ):
        raise PointInTimeDataError("market-date partition source material is invalid")
    calendar = validate_market_session_calendar(payload["market_calendar"])
    rebuilt = build_market_date_partitions(
        market_calendar=calendar,
        cadence=payload["cadence"],  # type: ignore[arg-type]
        registered_at=payload["registered_at"],  # type: ignore[arg-type]
        primary_universe=tuple(payload["primary_universe"]),  # type: ignore[arg-type]
        decision_market_dates=tuple(payload["decision_market_dates"]),  # type: ignore[arg-type]
        events=tuple(validate_decision_event(event) for event in payload["events"]),
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise PointInTimeDataError("market-date partition bytes do not match canonical rebuild")
    return rebuilt
