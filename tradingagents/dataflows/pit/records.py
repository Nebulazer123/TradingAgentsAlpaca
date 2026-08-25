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

_UTC = dt.timezone.utc
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}")
_FIGI = re.compile(r"[A-Z0-9]{12}")
_EXCHANGE = re.compile(r"[A-Z0-9_-]{1,32}")
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
    event_time: str
    publication_time: str
    availability_time: str
    retrieval_time: str
    raw_artifact_id: str
    raw_artifact_sha256: str
    adjustment_status: str
    source_span: Mapping[str, object]
    schema_version: str = dataclasses.field(init=False, default="point_in_time_observation/v1")
    analysis_only: bool = dataclasses.field(init=False, default=True)
    execution_authority: str = dataclasses.field(init=False, default="none")
    can_submit_orders: bool = dataclasses.field(init=False, default=False)

    def __post_init__(self) -> None:
        _identifier(self.security_id, field_name="security_id")
        event = _timestamp(self.event_time, field_name="event_time")
        publication = _timestamp(self.publication_time, field_name="publication_time")
        availability = _timestamp(self.availability_time, field_name="availability_time")
        retrieval = _timestamp(self.retrieval_time, field_name="retrieval_time")
        if event > publication or publication > availability or availability > retrieval:
            raise PointInTimeDataError("observation times must be event <= publication <= availability <= retrieval")
        _identifier(self.raw_artifact_id, field_name="raw_artifact_id")
        _digest(self.raw_artifact_sha256, field_name="raw_artifact_sha256")
        if self.adjustment_status not in {
            "unadjusted",
            "split_adjusted",
            "total_return_adjusted",
            "corporate_action_adjusted",
        }:
            raise PointInTimeDataError("adjustment_status is not recognized")
        frozen = _freeze_json(self.source_span, field_name="source_span")
        if not isinstance(frozen, MappingProxyType) or not frozen:
            raise PointInTimeDataError("source_span must be a nonempty mapping")
        object.__setattr__(self, "source_span", frozen)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "security_id": self.security_id,
            "event_time": self.event_time,
            "publication_time": self.publication_time,
            "availability_time": self.availability_time,
            "retrieval_time": self.retrieval_time,
            "raw_artifact_id": self.raw_artifact_id,
            "raw_artifact_sha256": self.raw_artifact_sha256,
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
        "event_time",
        "publication_time",
        "availability_time",
        "retrieval_time",
        "raw_artifact_id",
        "raw_artifact_sha256",
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
    if values["schema_version"] != "point_in_time_observation/v1":
        raise PointInTimeDataError("point-in-time observation schema_version is fixed")
    _validate_authority(values, field_name="point-in-time observation")
    rebuilt = PointInTimeObservation(
        security_id=values["security_id"],
        event_time=values["event_time"],
        publication_time=values["publication_time"],
        availability_time=values["availability_time"],
        retrieval_time=values["retrieval_time"],
        raw_artifact_id=values["raw_artifact_id"],
        raw_artifact_sha256=values["raw_artifact_sha256"],
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
