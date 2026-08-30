"""Pure immutable records for point-in-time evaluation source provenance.

The records deliberately hold hashes and source spans, not source credentials,
endpoints, broker state, or mutable cached market data. Raw artifact storage and
retrieval remain separate concerns; these values provide the canonical identity
and timing material required to prove an observation was available before use.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

_UTC = dt.timezone.utc
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}")
_FIGI = re.compile(r"[A-Z0-9]{12}")
_EXCHANGE = re.compile(r"[A-Z0-9_-]{1,32}")
_SESSION_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:00")
_MARKET_FEEDS = frozenset({"iex", "sip"})
_ADJUSTMENT_MODES = {
    "raw": "unadjusted",
    "split": "split_adjusted",
    "all": "total_return_adjusted",
}
_ALPACA_TIMEFRAME_SECONDS = {
    "1Min": 60,
    "5Min": 300,
    "15Min": 900,
    "30Min": 1_800,
    "1Hour": 3_600,
}
_MARKET_TZ = ZoneInfo("America/New_York")
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}


class PointInTimeDataError(ValueError):
    """Raised when a point-in-time record lacks canonical provenance or timing."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _identifier(value: object, *, field_name: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise PointInTimeDataError(f"{field_name} must be a canonical nonempty identifier")
    return value


def _digest(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PointInTimeDataError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _date(value: object, *, field_name: str) -> dt.date:
    if type(value) is not str:
        raise PointInTimeDataError(f"{field_name} must be an ISO date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError(f"{field_name} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise PointInTimeDataError(f"{field_name} must be an ISO date")
    return parsed


def _timestamp(value: object, *, field_name: str) -> dt.datetime:
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise PointInTimeDataError(
            f"{field_name} must use canonical UTC seconds with +00:00"
        )
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as exc:
        raise PointInTimeDataError(
            f"{field_name} must be a real canonical UTC timestamp"
        ) from exc
    if parsed.tzinfo != _UTC:
        raise PointInTimeDataError(f"{field_name} must be UTC")
    return parsed


def _freeze_json(value: object, *, field_name: str) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise PointInTimeDataError(f"{field_name} must be a finite JSON number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise PointInTimeDataError(f"{field_name} keys must be strings")
            frozen[key] = _freeze_json(item, field_name=f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if type(value) in (list, tuple):
        return tuple(
            _freeze_json(item, field_name=f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    raise PointInTimeDataError(f"{field_name} must contain exact JSON values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


def _source_hashes(value: object) -> MappingProxyType:
    frozen = _freeze_json(value, field_name="source_hashes")
    if not isinstance(frozen, MappingProxyType) or not frozen:
        raise PointInTimeDataError("source_hashes must be a nonempty mapping")
    for name, digest in frozen.items():
        _identifier(name, field_name="source_hashes key")
        _digest(digest, field_name=f"source_hashes.{name}")
    return frozen


def _validate_json_paths(
    paths: object,
    *,
    expected_roles: frozenset[str] | None,
) -> None:
    if not isinstance(paths, MappingProxyType) or not paths:
        raise PointInTimeDataError("source_span.paths must be a nonempty mapping")
    if expected_roles is not None and set(paths) != expected_roles:
        raise PointInTimeDataError("source_span.paths roles are invalid for source_kind")
    for label, path in paths.items():
        _identifier(label, field_name="source_span.paths key")
        if type(path) is not tuple or not path:
            raise PointInTimeDataError(f"source_span.paths.{label} must be a nonempty JSON path")
        for component in path:
            if type(component) is str and component:
                continue
            if type(component) is int and component >= 0:
                continue
            raise PointInTimeDataError(
                f"source_span.paths.{label} contains an invalid JSON path component"
            )


def _validate_alpaca_derivation(
    frozen: MappingProxyType,
    *,
    event_time: dt.datetime,
    publication_time: dt.datetime,
) -> None:
    _identifier(
        frozen["market_calendar_id"],
        field_name="source_span.market_calendar_id",
    )
    _digest(
        frozen["market_calendar_sha256"],
        field_name="source_span.market_calendar_sha256",
    )
    timeframe = frozen["timeframe"]
    if type(timeframe) is not str or timeframe not in {
        *_ALPACA_TIMEFRAME_SECONDS,
        "1Day",
    }:
        raise PointInTimeDataError("source_span.timeframe is not supported")
    derivation = frozen["publication_derivation"]
    expected_fields = frozenset(
        {
            "method",
            "completion_time",
            "market_timezone",
            "regular_session_open",
            "regular_session_close",
            "bar_duration_seconds",
            "calendar_raw_artifact_id",
            "calendar_raw_artifact_sha256",
            "calendar_date_path",
            "calendar_open_path",
            "calendar_close_path",
        }
    )
    if not isinstance(derivation, MappingProxyType) or set(derivation) != expected_fields:
        raise PointInTimeDataError("source_span publication derivation fields are invalid")
    if derivation["market_timezone"] != "America/New_York":
        raise PointInTimeDataError("source_span publication derivation session is invalid")
    calendar_artifact_id = _identifier(
        derivation["calendar_raw_artifact_id"],
        field_name="source_span.publication_derivation.calendar_raw_artifact_id",
    )
    if not calendar_artifact_id.startswith("pit-raw-artifact-"):
        raise PointInTimeDataError("calendar raw artifact identity is invalid")
    _digest(
        derivation["calendar_raw_artifact_sha256"],
        field_name="source_span.publication_derivation.calendar_raw_artifact_sha256",
    )
    row_indexes: set[int] = set()
    for field_name, source_field in (
        ("calendar_date_path", "date"),
        ("calendar_open_path", "open"),
        ("calendar_close_path", "close"),
    ):
        path = derivation[field_name]
        if (
            type(path) is not tuple
            or len(path) != 2
            or type(path[0]) is not int
            or path[0] < 0
            or path[1] != source_field
        ):
            raise PointInTimeDataError(
                f"source_span.publication_derivation.{field_name} is invalid"
            )
        row_indexes.add(path[0])
    if len(row_indexes) != 1:
        raise PointInTimeDataError("calendar session paths must select one source row")
    source_open = derivation["regular_session_open"]
    source_close = derivation["regular_session_close"]
    if (
        type(source_open) is not str
        or _SESSION_TIME.fullmatch(source_open) is None
        or type(source_close) is not str
        or _SESSION_TIME.fullmatch(source_close) is None
    ):
        raise PointInTimeDataError("source-derived regular session hours are invalid")
    regular_open = dt.time.fromisoformat(source_open)
    regular_close = dt.time.fromisoformat(source_close)
    if regular_open >= regular_close:
        raise PointInTimeDataError("source-derived session open must precede close")

    local_event = event_time.astimezone(_MARKET_TZ)
    local_date = local_event.date()
    local_time = local_event.timetz().replace(tzinfo=None)
    if timeframe == "1Day":
        if (
            local_time != dt.time(0, 0)
            or derivation["method"] != "registered_regular_session_close"
            or derivation["bar_duration_seconds"] is not None
        ):
            raise PointInTimeDataError("daily publication derivation is invalid")
        expected_publication = dt.datetime.combine(
            local_date,
            regular_close,
            tzinfo=_MARKET_TZ,
        ).astimezone(_UTC)
    else:
        duration = _ALPACA_TIMEFRAME_SECONDS[timeframe]
        if (
            derivation["method"] != "bar_start_plus_timeframe"
            or derivation["bar_duration_seconds"] != duration
            or not (regular_open <= local_time < regular_close)
        ):
            raise PointInTimeDataError("intraday publication derivation is invalid")
        expected_publication = event_time + dt.timedelta(seconds=duration)
        local_completion = expected_publication.astimezone(_MARKET_TZ)
        if (
            local_completion.date() != local_date
            or local_completion.timetz().replace(tzinfo=None) > regular_close
        ):
            raise PointInTimeDataError("intraday bar overruns the regular session")

    completion = _timestamp(
        derivation["completion_time"],
        field_name="source_span.publication_derivation.completion_time",
    )
    if completion != expected_publication or publication_time != expected_publication:
        raise PointInTimeDataError("publication time does not match its bound derivation")


def _source_span(
    value: object,
    *,
    raw_artifact_sha256: str,
    event_time: dt.datetime,
    publication_time: dt.datetime,
    is_market: bool,
) -> MappingProxyType:
    frozen = _freeze_json(value, field_name="source_span")
    if not isinstance(frozen, MappingProxyType):
        raise PointInTimeDataError("source_span must be a nonempty mapping")
    common_fields = frozenset({"source_kind", "span_type", "source_sha256"})
    if not common_fields.issubset(frozen):
        raise PointInTimeDataError("source_span lacks canonical source binding fields")
    _identifier(frozen["source_kind"], field_name="source_span.source_kind")
    span_digest = _digest(
        frozen["source_sha256"],
        field_name="source_span.source_sha256",
    )
    if span_digest != raw_artifact_sha256:
        raise PointInTimeDataError("source_span is not bound to raw_artifact_sha256")

    span_type = frozen["span_type"]
    if span_type == "byte_range":
        if frozen["source_kind"] in {"sec_json_xbrl", "alpaca_market_data"}:
            raise PointInTimeDataError(
                "official observation source_kind requires exact JSON paths"
            )
        expected = common_fields | frozenset({"start_byte", "end_byte"})
        if set(frozen) != expected:
            raise PointInTimeDataError("byte-range source_span fields are invalid")
        start = frozen["start_byte"]
        end = frozen["end_byte"]
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise PointInTimeDataError("byte-range source_span bounds are invalid")
        return frozen

    if span_type != "json_paths":
        raise PointInTimeDataError("source_span must be an exact byte range or JSON path set")
    source_kind = frozen["source_kind"]
    if source_kind == "sec_json_xbrl":
        if is_market or set(frozen) != common_fields | {"paths"}:
            raise PointInTimeDataError("SEC source_span fields are invalid")
        expected_roles = frozenset(
            {"source_identity", "observed_value", "event_time", "publication_time"}
        )
    elif source_kind == "alpaca_market_data":
        expected = common_fields | frozenset(
            {
                "paths",
                "market_calendar_id",
                "market_calendar_sha256",
                "timeframe",
                "publication_derivation",
            }
        )
        if not is_market or set(frozen) != expected:
            raise PointInTimeDataError("Alpaca source_span fields are invalid")
        expected_roles = frozenset({"observed_value", "event_time"})
        _validate_alpaca_derivation(
            frozen,
            event_time=event_time,
            publication_time=publication_time,
        )
    else:
        if set(frozen) != common_fields | {"paths"}:
            raise PointInTimeDataError("JSON-path source_span fields are invalid")
        expected_roles = None
    _validate_json_paths(frozen["paths"], expected_roles=expected_roles)
    return frozen


def _validate_authority(values: Mapping[str, object], *, field_name: str) -> None:
    if values["analysis_only"] is not True:
        raise PointInTimeDataError(f"{field_name}.analysis_only must be true")
    if type(values["execution_authority"]) is not str or values["execution_authority"] != "none":
        raise PointInTimeDataError(f"{field_name}.execution_authority must be none")
    if values["can_submit_orders"] is not False:
        raise PointInTimeDataError(f"{field_name}.can_submit_orders must be false")


def _exact_fields(value: object, expected: frozenset[str], *, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PointInTimeDataError(f"{field_name} must be a JSON object")
    if any(type(key) is not str for key in value):
        raise PointInTimeDataError(f"{field_name} field names must be strings")
    keys = set(value)
    if keys != expected:
        raise PointInTimeDataError(
            f"{field_name} fields mismatch: missing={sorted(expected - keys)} extra={sorted(keys - expected)}"
        )
    return {key: value[key] for key in expected}


@dataclasses.dataclass(frozen=True, slots=True)
class SecurityIdentity:
    """Stable security-master identity with source-hash provenance."""

    security_id: str
    symbol: str
    cik: str | None
    figi: str | None
    exchange: str
    security_type: str
    effective_from: str
    effective_to: str | None
    status: str
    successor_security_id: str | None
    terminal_proceeds_artifact_id: str | None
    source_hashes: Mapping[str, str]
    schema_version: str = dataclasses.field(init=False, default="security_identity/v1")
    analysis_only: bool = dataclasses.field(init=False, default=True)
    execution_authority: str = dataclasses.field(init=False, default="none")
    can_submit_orders: bool = dataclasses.field(init=False, default=False)

    def __post_init__(self) -> None:
        _identifier(self.security_id, field_name="security_id")
        if type(self.symbol) is not str or _SYMBOL.fullmatch(self.symbol) is None:
            raise PointInTimeDataError("symbol must be normalized uppercase")
        if self.cik is not None and (type(self.cik) is not str or re.fullmatch(r"[0-9]{10}", self.cik) is None):
            raise PointInTimeDataError("cik must be a ten-digit string or null")
        if self.figi is not None and (type(self.figi) is not str or _FIGI.fullmatch(self.figi) is None):
            raise PointInTimeDataError("figi must be a twelve-character FIGI or null")
        if type(self.exchange) is not str or _EXCHANGE.fullmatch(self.exchange) is None:
            raise PointInTimeDataError("exchange must be normalized uppercase")
        if self.security_type != "common_stock":
            raise PointInTimeDataError("security_type must be common_stock")
        start = _date(self.effective_from, field_name="effective_from")
        end = None if self.effective_to is None else _date(self.effective_to, field_name="effective_to")
        if end is not None and end < start:
            raise PointInTimeDataError("effective_to cannot precede effective_from")
        if self.status not in {"active", "delisted"}:
            raise PointInTimeDataError("status must be active or delisted")
        if self.status == "active":
            if end is not None or self.successor_security_id is not None or self.terminal_proceeds_artifact_id is not None:
                raise PointInTimeDataError("active securities cannot carry terminal identity fields")
        else:
            if end is None:
                raise PointInTimeDataError("delisted securities require effective_to")
            if self.successor_security_id is None and self.terminal_proceeds_artifact_id is None:
                raise PointInTimeDataError("delisted securities require successor or terminal proceeds identity")
            if self.successor_security_id is not None:
                _identifier(self.successor_security_id, field_name="successor_security_id")
            if self.terminal_proceeds_artifact_id is not None:
                _identifier(self.terminal_proceeds_artifact_id, field_name="terminal_proceeds_artifact_id")
        object.__setattr__(self, "source_hashes", _source_hashes(self.source_hashes))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "cik": self.cik,
            "figi": self.figi,
            "exchange": self.exchange,
            "security_type": self.security_type,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "status": self.status,
            "successor_security_id": self.successor_security_id,
            "terminal_proceeds_artifact_id": self.terminal_proceeds_artifact_id,
            "source_hashes": _thaw_json(self.source_hashes),
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_SECURITY_FIELDS = frozenset(
    {
        "schema_version",
        "security_id",
        "symbol",
        "cik",
        "figi",
        "exchange",
        "security_type",
        "effective_from",
        "effective_to",
        "status",
        "successor_security_id",
        "terminal_proceeds_artifact_id",
        "source_hashes",
        *_AUTHORITY,
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class PointInTimeObservation:
    """One raw-artifact observation with event, publication, and availability times."""

    security_id: str
    identity_effective_from: str
    identity_effective_to: str | None
    event_time: str
    publication_time: str
    availability_time: str
    retrieval_time: str
    raw_artifact_id: str
    raw_artifact_sha256: str
    observed_value: object
    market_data_feed: str | None
    adjustment_mode: str | None
    market_session: str | None
    session_date: str | None
    adjustment_status: str
    source_span: Mapping[str, object]
    schema_version: str = dataclasses.field(init=False, default="point_in_time_observation/v2")
    analysis_only: bool = dataclasses.field(init=False, default=True)
    execution_authority: str = dataclasses.field(init=False, default="none")
    can_submit_orders: bool = dataclasses.field(init=False, default=False)

    def __post_init__(self) -> None:
        _identifier(self.security_id, field_name="security_id")
        identity_start = _date(
            self.identity_effective_from,
            field_name="identity_effective_from",
        )
        identity_end = (
            None
            if self.identity_effective_to is None
            else _date(self.identity_effective_to, field_name="identity_effective_to")
        )
        if identity_end is not None and identity_end < identity_start:
            raise PointInTimeDataError(
                "identity_effective_to cannot precede identity_effective_from"
            )
        event = _timestamp(self.event_time, field_name="event_time")
        publication = _timestamp(self.publication_time, field_name="publication_time")
        availability = _timestamp(self.availability_time, field_name="availability_time")
        retrieval = _timestamp(self.retrieval_time, field_name="retrieval_time")
        if event > publication or publication > availability or availability > retrieval:
            raise PointInTimeDataError("observation times must be event <= publication <= availability <= retrieval")
        if event.date() < identity_start or (
            identity_end is not None and event.date() > identity_end
        ):
            raise PointInTimeDataError("observation event is outside the bound security identity")
        _identifier(self.raw_artifact_id, field_name="raw_artifact_id")
        raw_digest = _digest(
            self.raw_artifact_sha256,
            field_name="raw_artifact_sha256",
        )
        if self.adjustment_status not in {
            "unadjusted",
            "split_adjusted",
            "total_return_adjusted",
            "corporate_action_adjusted",
        }:
            raise PointInTimeDataError("adjustment_status is not recognized")
        if self.market_data_feed is None:
            if any(
                value is not None
                for value in (
                    self.adjustment_mode,
                    self.market_session,
                    self.session_date,
                )
            ):
                raise PointInTimeDataError(
                    "nonmarket observations cannot carry partial market identity"
                )
        else:
            if self.market_data_feed not in _MARKET_FEEDS:
                raise PointInTimeDataError("market_data_feed is not recognized")
            expected_status = _ADJUSTMENT_MODES.get(self.adjustment_mode)
            if expected_status is None or expected_status != self.adjustment_status:
                raise PointInTimeDataError(
                    "adjustment_mode does not match adjustment_status"
                )
            if self.market_session != "regular":
                raise PointInTimeDataError("market_session must bind the regular session")
            session = _date(self.session_date, field_name="session_date")
            if session != event.date():
                raise PointInTimeDataError(
                    "session_date does not match the selected market observation"
                )
            if session < identity_start or (
                identity_end is not None and session > identity_end
            ):
                raise PointInTimeDataError(
                    "session_date is outside the bound security identity"
                )
        object.__setattr__(
            self,
            "observed_value",
            _freeze_json(self.observed_value, field_name="observed_value"),
        )
        object.__setattr__(
            self,
            "source_span",
            _source_span(
                self.source_span,
                raw_artifact_sha256=raw_digest,
                event_time=event,
                publication_time=publication,
                is_market=self.market_data_feed is not None,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "security_id": self.security_id,
            "identity_effective_from": self.identity_effective_from,
            "identity_effective_to": self.identity_effective_to,
            "event_time": self.event_time,
            "publication_time": self.publication_time,
            "availability_time": self.availability_time,
            "retrieval_time": self.retrieval_time,
            "raw_artifact_id": self.raw_artifact_id,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "observed_value": _thaw_json(self.observed_value),
            "market_data_feed": self.market_data_feed,
            "adjustment_mode": self.adjustment_mode,
            "market_session": self.market_session,
            "session_date": self.session_date,
            "adjustment_status": self.adjustment_status,
            "source_span": _thaw_json(self.source_span),
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "security_id",
        "identity_effective_from",
        "identity_effective_to",
        "event_time",
        "publication_time",
        "availability_time",
        "retrieval_time",
        "raw_artifact_id",
        "raw_artifact_sha256",
        "observed_value",
        "market_data_feed",
        "adjustment_mode",
        "market_session",
        "session_date",
        "adjustment_status",
        "source_span",
        *_AUTHORITY,
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class CorporateAction:
    """Source-bound corporate action required for adjusted economic outcomes."""

    security_id: str
    action_type: str
    effective_date: str
    terms: Mapping[str, object]
    source_artifact_id: str
    source_artifact_sha256: str
    schema_version: str = dataclasses.field(init=False, default="corporate_action/v1")
    analysis_only: bool = dataclasses.field(init=False, default=True)
    execution_authority: str = dataclasses.field(init=False, default="none")
    can_submit_orders: bool = dataclasses.field(init=False, default=False)

    def __post_init__(self) -> None:
        _identifier(self.security_id, field_name="security_id")
        if self.action_type not in {"split", "dividend", "merger", "acquisition", "symbol_change", "delisting"}:
            raise PointInTimeDataError("action_type is not recognized")
        _date(self.effective_date, field_name="effective_date")
        frozen = _freeze_json(self.terms, field_name="terms")
        if not isinstance(frozen, MappingProxyType) or not frozen:
            raise PointInTimeDataError("terms must be a nonempty mapping")
        _identifier(self.source_artifact_id, field_name="source_artifact_id")
        _digest(self.source_artifact_sha256, field_name="source_artifact_sha256")
        object.__setattr__(self, "terms", frozen)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "security_id": self.security_id,
            "action_type": self.action_type,
            "effective_date": self.effective_date,
            "terms": _thaw_json(self.terms),
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_sha256": self.source_artifact_sha256,
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_ACTION_FIELDS = frozenset(
    {
        "schema_version",
        "security_id",
        "action_type",
        "effective_date",
        "terms",
        "source_artifact_id",
        "source_artifact_sha256",
        *_AUTHORITY,
    }
)


def validate_security_identity(value: object) -> SecurityIdentity:
    values = _exact_fields(value, _SECURITY_FIELDS, field_name="security identity")
    if values["schema_version"] != "security_identity/v1":
        raise PointInTimeDataError("security identity schema_version is fixed")
    _validate_authority(values, field_name="security identity")
    rebuilt = SecurityIdentity(
        security_id=values["security_id"],
        symbol=values["symbol"],
        cik=values["cik"],
        figi=values["figi"],
        exchange=values["exchange"],
        security_type=values["security_type"],
        effective_from=values["effective_from"],
        effective_to=values["effective_to"],
        status=values["status"],
        successor_security_id=values["successor_security_id"],
        terminal_proceeds_artifact_id=values["terminal_proceeds_artifact_id"],
        source_hashes=values["source_hashes"],
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(values):
        raise PointInTimeDataError("security identity bytes do not match canonical rebuild")
    return rebuilt


def validate_point_in_time_observation(value: object) -> PointInTimeObservation:
    values = _exact_fields(value, _OBSERVATION_FIELDS, field_name="point-in-time observation")
    if values["schema_version"] != "point_in_time_observation/v2":
        raise PointInTimeDataError("point-in-time observation schema_version is fixed")
    _validate_authority(values, field_name="point-in-time observation")
    rebuilt = PointInTimeObservation(
        security_id=values["security_id"],
        identity_effective_from=values["identity_effective_from"],
        identity_effective_to=values["identity_effective_to"],
        event_time=values["event_time"],
        publication_time=values["publication_time"],
        availability_time=values["availability_time"],
        retrieval_time=values["retrieval_time"],
        raw_artifact_id=values["raw_artifact_id"],
        raw_artifact_sha256=values["raw_artifact_sha256"],
        observed_value=values["observed_value"],
        market_data_feed=values["market_data_feed"],
        adjustment_mode=values["adjustment_mode"],
        market_session=values["market_session"],
        session_date=values["session_date"],
        adjustment_status=values["adjustment_status"],
        source_span=values["source_span"],
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(values):
        raise PointInTimeDataError("point-in-time observation bytes do not match canonical rebuild")
    return rebuilt


def validate_corporate_action(value: object) -> CorporateAction:
    values = _exact_fields(value, _ACTION_FIELDS, field_name="corporate action")
    if values["schema_version"] != "corporate_action/v1":
        raise PointInTimeDataError("corporate action schema_version is fixed")
    _validate_authority(values, field_name="corporate action")
    rebuilt = CorporateAction(
        security_id=values["security_id"], action_type=values["action_type"], effective_date=values["effective_date"], terms=values["terms"], source_artifact_id=values["source_artifact_id"], source_artifact_sha256=values["source_artifact_sha256"],
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(values):
        raise PointInTimeDataError("corporate action bytes do not match canonical rebuild")
    return rebuilt
