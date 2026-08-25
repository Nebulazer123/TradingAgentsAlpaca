"""Immutable, source-bound market-session calendars for PIT partitions."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import urlsplit

from tradingagents.dataflows.pit.raw_artifacts import (
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
)
from tradingagents.dataflows.pit.records import PointInTimeDataError

__all__ = [
    "MarketSessionCalendar",
    "build_market_session_calendar",
    "validate_market_session_calendar",
]


_SCHEMA = "market_session_calendar/v1"
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_SOURCE_SPAN_FIELDS = frozenset(
    {"span_type", "start_byte", "end_byte", "source_sha256"}
)
_ALPACA_CALENDAR_HOSTS = frozenset(
    {"api.alpaca.markets", "paper-api.alpaca.markets"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def _market_dates(value: object) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or len(value) < 1:
        raise PointInTimeDataError(
            "market calendar must contain a nonempty date sequence"
        )
    dates: list[str] = []
    for index, value_at_index in enumerate(value):
        if type(value_at_index) is not str:
            raise PointInTimeDataError(f"market_dates[{index}] must be an ISO date")
        try:
            parsed = dt.date.fromisoformat(value_at_index)
        except ValueError as exc:
            raise PointInTimeDataError(
                f"market_dates[{index}] must be an ISO date"
            ) from exc
        if parsed.isoformat() != value_at_index or parsed.weekday() >= 5:
            raise PointInTimeDataError(
                f"market_dates[{index}] must be a weekday market session"
            )
        dates.append(value_at_index)
    if tuple(dates) != tuple(sorted(dates)) or len(set(dates)) != len(dates):
        raise PointInTimeDataError("market calendar dates must be unique and chronological")
    return tuple(dates)


def _source_span_material(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_SPAN_FIELDS:
        raise PointInTimeDataError("market calendar source_span is invalid")
    start = value["start_byte"]
    end = value["end_byte"]
    if (
        value["span_type"] != "byte_range"
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end
        or type(value["source_sha256"]) is not str
        or _SHA256.fullmatch(value["source_sha256"]) is None
    ):
        raise PointInTimeDataError("market calendar source_span is invalid")
    return dict(value)


def _source_span(
    value: object,
    *,
    raw_artifact: RawPointInTimeArtifact,
    raw_bytes: bytes,
) -> dict[str, object]:
    span = _source_span_material(value)
    if (
        span["end_byte"] > len(raw_bytes)
        or span["source_sha256"] != raw_artifact.raw_artifact_sha256
    ):
        raise PointInTimeDataError("market calendar source_span is not bound to raw bytes")
    return span


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class MarketSessionCalendar:
    """One explicit source-backed sequence of regular market sessions."""

    calendar_id: str
    calendar_sha256: str
    venue: str
    market_dates: tuple[str, ...]
    raw_artifact_id: str
    raw_artifact_sha256: str
    source_span: Mapping[str, object]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("MarketSessionCalendar instances must be created by its builder")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA,
            "calendar_id": self.calendar_id,
            "calendar_sha256": self.calendar_sha256,
            "venue": self.venue,
            "market_dates": list(self.market_dates),
            "raw_artifact_id": self.raw_artifact_id,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "source_span": dict(self.source_span),
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_FIELDS = tuple(field.name for field in dataclasses.fields(MarketSessionCalendar))
_SERIALIZED_FIELDS = frozenset(_FIELDS + ("schema_version",) + tuple(_AUTHORITY))


def _new_calendar(**fields: object) -> MarketSessionCalendar:
    calendar = object.__new__(MarketSessionCalendar)
    for field in _FIELDS:
        object.__setattr__(calendar, field, fields[field])
    return calendar


def _from_material(
    *,
    venue: object,
    market_dates: object,
    raw_artifact_id: object,
    raw_artifact_sha256: object,
    source_span: object,
) -> MarketSessionCalendar:
    if venue != "XNYS":
        raise PointInTimeDataError("market calendar venue must be XNYS")
    dates = _market_dates(market_dates)
    if type(raw_artifact_id) is not str or not raw_artifact_id.startswith("pit-raw-artifact-"):
        raise PointInTimeDataError("market calendar raw artifact identity is invalid")
    if (
        type(raw_artifact_sha256) is not str
        or _SHA256.fullmatch(raw_artifact_sha256) is None
    ):
        raise PointInTimeDataError("market calendar raw artifact digest is invalid")
    span = _source_span_material(source_span)
    identity = {
        "schema_version": _SCHEMA,
        "venue": venue,
        "market_dates": list(dates),
        "raw_artifact_id": raw_artifact_id,
        "raw_artifact_sha256": raw_artifact_sha256,
        "source_span": span,
        **_AUTHORITY,
    }
    calendar_id = "market-session-calendar-" + _sha256(identity)
    calendar_sha256 = _sha256({**identity, "calendar_id": calendar_id})
    return _new_calendar(
        calendar_id=calendar_id,
        calendar_sha256=calendar_sha256,
        venue=venue,
        market_dates=dates,
        raw_artifact_id=raw_artifact_id,
        raw_artifact_sha256=raw_artifact_sha256,
        source_span=MappingProxyType(span),
    )


def build_market_session_calendar(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
) -> MarketSessionCalendar:
    """Read a sealed Alpaca XNYS session calendar from archived source bytes."""

    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    if type(raw_artifact) is not RawPointInTimeArtifact:
        raise PointInTimeDataError("raw_artifact must be an exact raw PIT artifact")
    raw_bytes = archive.read_bytes(raw_artifact)
    parsed = urlsplit(raw_artifact.source_uri)
    if (
        parsed.hostname not in _ALPACA_CALENDAR_HOSTS
        or parsed.path != "/v2/calendar"
        or raw_artifact.content_type != "application/json"
    ):
        raise PointInTimeDataError("market calendar must be an Alpaca calendar receipt")
    try:
        raw_calendar = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointInTimeDataError("market calendar source bytes are not JSON") from exc
    if type(raw_calendar) is not list:
        raise PointInTimeDataError("market calendar source must be a JSON list")
    market_dates = []
    for index, row in enumerate(raw_calendar):
        if not isinstance(row, Mapping) or type(row.get("date")) is not str:
            raise PointInTimeDataError(f"market calendar row {index} has no date")
        market_dates.append(row["date"])
    span = _source_span(
        {
            "span_type": "byte_range",
            "start_byte": 0,
            "end_byte": len(raw_bytes),
            "source_sha256": raw_artifact.raw_artifact_sha256,
        },
        raw_artifact=raw_artifact,
        raw_bytes=raw_bytes,
    )
    return _from_material(
        venue="XNYS",
        market_dates=market_dates,
        raw_artifact_id=raw_artifact.raw_artifact_id,
        raw_artifact_sha256=raw_artifact.raw_artifact_sha256,
        source_span=span,
    )


def validate_market_session_calendar(value: object) -> MarketSessionCalendar:
    """Rebuild a complete session calendar from its immutable receipt fields."""

    if not isinstance(value, Mapping) or set(value) != _SERIALIZED_FIELDS:
        raise PointInTimeDataError("market calendar fields are invalid")
    payload = dict(value)
    if payload["schema_version"] != _SCHEMA:
        raise PointInTimeDataError("market calendar schema is invalid")
    if (
        payload["analysis_only"] is not True
        or payload["execution_authority"] != "none"
        or payload["can_submit_orders"] is not False
    ):
        raise PointInTimeDataError("market calendar authority fields are fixed")
    rebuilt = _from_material(
        venue=payload["venue"],
        market_dates=payload["market_dates"],
        raw_artifact_id=payload["raw_artifact_id"],
        raw_artifact_sha256=payload["raw_artifact_sha256"],
        source_span=payload["source_span"],
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise PointInTimeDataError("market calendar bytes do not match canonical rebuild")
    return rebuilt
