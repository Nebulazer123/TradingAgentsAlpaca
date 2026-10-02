"""Additive original-backed security assertions; no v1 or cohort reinterpretation.

An assertion proves what its retained JSON source says. It does not prove source
coverage, a reviewed issuer/security/listing crosswalk, or trading authority.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError

SCHEMA = "security_master/v2"
PARSER_VERSION = "security_master_json_fields/v1"
_AUTHORITY = {"analysis_only": True, "execution_authority": "none", "can_submit_orders": False}
_KINDS = {
    "issuer": {"name", "cik"},
    "security": {"security_type", "share_class", "status", "name"},
    "listing": {"exchange", "status"},
    "alias": {"symbol", "name"},
    "external_identifier": {"alpaca_asset_id", "cik", "figi", "cusip", "isin"},
    "event": {"action_type", "source_status", "effective_date", "process_date", "consideration", "successor_identifier"},
}
_PATH_FIELDS = frozenset({"value", "effective_from", "effective_to", "coverage_through", "source_published_at", "source_recorded_at"})
_FIELDS = frozenset({"schema_version", "assertion_id", "subject_kind", "subject_id", "field", "value", "effective_from", "effective_to", "coverage_through",
                     "source_published_at", "source_recorded_at", "retrieved_at", "archive_recorded_at", "raw_artifact", "source_field_paths", "parser_version",
                     "derivation_mode", "correction_parents", "derivation_parent_hashes", *_AUTHORITY})
_ASSERTION_ID = re.compile(r"security-master-assertion-[0-9a-f]{64}")
_MAX_BYTES = 32 * 1024 * 1024
_MAX_RECORDS = 250_000


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _timestamp(value: object) -> dt.datetime:
    if type(value) is not str:
        raise PointInTimeDataError("security-master timestamp must be a string")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PointInTimeDataError("invalid security-master timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PointInTimeDataError("security-master timestamp requires a timezone")
    return result.astimezone(dt.timezone.utc)


def _date(value: object) -> dt.date:
    if type(value) is not str:
        raise PointInTimeDataError("security-master date must be an ISO string")
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError("invalid security-master date") from exc
    if result.isoformat() != value:
        raise PointInTimeDataError("security-master date must be canonical")
    return result


def _subject(kind: object, identifier: object) -> None:
    if type(kind) is not str or kind not in _KINDS or type(identifier) is not str or not identifier.startswith(kind + "-"):
        raise PointInTimeDataError("security-master subject requires a distinct internal kind and UUID")
    try:
        parsed = UUID(identifier[len(kind) + 1:])
    except ValueError as exc:
        raise PointInTimeDataError("invalid security-master internal UUID") from exc
    if identifier != f"{kind}-{parsed}":
        raise PointInTimeDataError("security-master internal UUID must be canonical")


def new_security_master_entity_id(kind: str) -> str:
    """Allocate a local identity; a reviewed source-bound crosswalk is separate."""
    if type(kind) is not str or kind not in _KINDS:
        raise PointInTimeDataError("unknown security-master entity kind")
    return f"{kind}-{uuid4()}"


def _paths(value: object) -> dict[str, list[str | int] | None]:
    if type(value) is not dict or set(value) != _PATH_FIELDS or value["value"] is None:
        raise PointInTimeDataError("security-master source paths must declare every field")
    output = {}
    for name, path in value.items():
        if path is not None and (type(path) is not list or len(path) > 32 or any(
            not ((type(part) is str and 0 < len(part) <= 512) or (type(part) is int and 0 <= part <= 1_000_000)) for part in path
        )):
            raise PointInTimeDataError("invalid security-master JSON path")
        output[name] = None if path is None else list(path)
    return output


def _select(payload: object, path: list[str | int]) -> object:
    selected = payload
    for part in path:
        if (type(part) is str and type(selected) is dict and part in selected) or (type(part) is int and type(selected) is list and part < len(selected)):
            selected = selected[part]
        else:
            raise PointInTimeDataError("security-master source path is unavailable")
    return selected


def _plain(value: object) -> object:
    if type(value) is Decimal:
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if type(value) is dict:
        return {key: _plain(item) for key, item in value.items()}
    if type(value) is list:
        return [_plain(item) for item in value]
    return value


def _json(raw: bytes) -> object:
    if len(raw) > _MAX_BYTES:
        raise PointInTimeDataError("security-master source exceeds byte bound")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PointInTimeDataError("duplicate security-master source JSON key")
            result[key] = value
        return result

    def number(text):
        result = Decimal(text)
        if len(text) > 128 or not result.is_finite() or abs(result.as_tuple().exponent) > 100:
            raise PointInTimeDataError("security-master source numeric bound")
        return result

    def integer(text):
        if len(text) > 128:
            raise PointInTimeDataError("security-master source numeric bound")
        return int(text)

    def constant(_):
        raise PointInTimeDataError("security-master source cannot contain nonfinite values")

    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_float=number, parse_int=integer, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PointInTimeDataError("invalid security-master source JSON") from exc
    stack = [(result, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 32 or count > 1_000_000 or (type(item) is str and len(item) > 16_384):
            raise PointInTimeDataError("security-master source shape bound")
        if type(item) is dict:
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
    return result


def _value(kind: str, field: str, value: object) -> object:
    if type(field) is not str or field not in _KINDS[kind]:
        raise PointInTimeDataError("unsupported security-master assertion field")
    if field == "consideration":
        if type(value) not in {dict, list}:
            raise PointInTimeDataError("consideration must preserve structured source legs")
        return _plain(value)
    if type(value) is not str or not value or len(value) > 4096:
        raise PointInTimeDataError("security-master factual field requires an original string")
    if field == "security_type" and value not in {"common_stock", "preferred_stock", "etf", "etn", "fund", "adr", "warrant", "right", "unit", "test", "unknown"}:
        raise PointInTimeDataError("asset class or name cannot establish security type")
    if field == "symbol" and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value) is None:
        raise PointInTimeDataError("invalid source ticker alias")
    if field == "cik" and re.fullmatch(r"[0-9]{10}", value) is None:
        raise PointInTimeDataError("CIK must remain a source-supported ten-digit issuer identifier")
    if field in {"effective_date", "process_date"}:
        _date(value)
    return value


@dataclass(frozen=True, slots=True, init=False)
class SecurityMasterAssertionV2:
    record: Mapping[str, object]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("security-master assertions must be built from archived originals")

    @property
    def assertion_id(self) -> str:
        return self.record["assertion_id"]

    def to_dict(self) -> dict[str, object]:
        return _thaw(self.record)

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())


def _assertion(record: dict[str, object]) -> SecurityMasterAssertionV2:
    result = object.__new__(SecurityMasterAssertionV2)
    object.__setattr__(result, "record", _freeze(record))
    return result


class _Replay:
    def __init__(self, archive: RawPointInTimeArtifactArchive, registry: Mapping[str, dict] | None = None):
        if type(archive) is not RawPointInTimeArtifactArchive:
            raise PointInTimeDataError("security-master requires the PIT original archive")
        self.archive = archive
        self.registry = dict(registry or {})
        self.sources: dict[str, tuple[dict, object]] = {}
        self.verified: dict[str, SecurityMasterAssertionV2] = {}
        self.visiting: set[str] = set()

    def source(self, identifier: str) -> tuple[dict, object]:
        if identifier not in self.sources:
            artifact = self.archive.read_artifact(identifier)
            if artifact.content_type != "application/json":
                raise PointInTimeDataError("security-master JSON parser requires an original JSON artifact")
            self.sources[identifier] = (artifact.to_dict(), _json(self.archive.read_bytes(artifact)))
        return self.sources[identifier]

    def derive(self, *, subject_kind: str, subject_id: str, field: str, raw_artifact_id: str, source_field_paths: dict,
               derivation_mode: str, correction_parents: Sequence[str]) -> SecurityMasterAssertionV2:
        _subject(subject_kind, subject_id)
        paths = _paths(source_field_paths)
        if type(derivation_mode) is not str or derivation_mode not in {"direct", "historical_reconstruction"}:
            raise PointInTimeDataError("unsupported security-master derivation mode")
        if type(correction_parents) not in {list, tuple} or len(correction_parents) > 128 or any(type(item) is not str or _ASSERTION_ID.fullmatch(item) is None for item in correction_parents):
            raise PointInTimeDataError("invalid security-master correction parents")
        if list(correction_parents) != sorted(set(correction_parents)):
            raise PointInTimeDataError("security-master correction parents must be unique and sorted")
        artifact, payload = self.source(raw_artifact_id)
        facts = {name: None if path is None else _plain(_select(payload, path)) for name, path in paths.items()}
        facts["value"] = _value(subject_kind, field, facts["value"])
        for name in ("effective_from", "effective_to", "coverage_through"):
            if facts[name] is not None:
                _date(facts[name])
        if facts["effective_to"] is not None and (facts["effective_from"] is None or facts["effective_to"] <= facts["effective_from"]):
            raise PointInTimeDataError("security-master intervals require a positive exclusive-end interval")
        if facts["coverage_through"] is not None and facts["effective_from"] is not None and facts["coverage_through"] < facts["effective_from"]:
            raise PointInTimeDataError("security-master coverage cannot precede its effective start")
        for name in ("source_published_at", "source_recorded_at"):
            if facts[name] is not None:
                facts[name] = _timestamp(facts[name]).isoformat()
        parents = []
        for parent_id in correction_parents:
            parent = self.verify(parent_id).to_dict()
            if (parent["subject_kind"], parent["subject_id"], parent["field"]) != (subject_kind, subject_id, field):
                raise PointInTimeDataError("a correction cannot replace another subject or field")
            if _timestamp(parent["archive_recorded_at"]) >= _timestamp(artifact["archive_recorded_at"]):
                raise PointInTimeDataError("a correction must be archived after its parent")
            parents.append({"assertion_id": parent_id, "assertion_sha256": hashlib.sha256(_canonical(parent)).hexdigest(),
                            "original_sha256": parent["raw_artifact"]["raw_artifact_sha256"]})
        record = {"schema_version": SCHEMA, "subject_kind": subject_kind, "subject_id": subject_id, "field": field, **facts,
                  "retrieved_at": artifact["retrieved_at"], "archive_recorded_at": artifact["archive_recorded_at"], "raw_artifact": artifact,
                  "source_field_paths": paths, "parser_version": PARSER_VERSION, "derivation_mode": derivation_mode,
                  "correction_parents": list(correction_parents), "derivation_parent_hashes": parents, **_AUTHORITY}
        record["assertion_id"] = "security-master-assertion-" + hashlib.sha256(_canonical(record)).hexdigest()
        return _assertion(record)

    def verify(self, identifier: str) -> SecurityMasterAssertionV2:
        if identifier in self.verified:
            return self.verified[identifier]
        if identifier not in self.registry or identifier in self.visiting or len(self.visiting) >= 64:
            raise PointInTimeDataError("missing, cyclic or excessive security-master correction lineage")
        payload = self.registry[identifier]
        self.visiting.add(identifier)
        try:
            artifact = payload["raw_artifact"]
            if type(artifact) is not dict or type(artifact.get("raw_artifact_id")) is not str:
                raise PointInTimeDataError("security-master requires an exact original artifact receipt")
            rebuilt = self.derive(subject_kind=payload["subject_kind"], subject_id=payload["subject_id"], field=payload["field"],
                                  raw_artifact_id=artifact["raw_artifact_id"], source_field_paths=payload["source_field_paths"],
                                  derivation_mode=payload["derivation_mode"], correction_parents=payload["correction_parents"])
            if rebuilt.canonical_json_bytes() != _canonical(payload):
                raise PointInTimeDataError("security-master assertion differs from its reopened original derivation")
            self.verified[identifier] = rebuilt
            return rebuilt
        finally:
            self.visiting.remove(identifier)


def _registry(records: Sequence[object]) -> dict[str, dict]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or len(records) > _MAX_RECORDS:
        raise PointInTimeDataError("security-master assertion inventory bound")
    result = {}
    for value in records:
        payload = value.to_dict() if type(value) is SecurityMasterAssertionV2 else value
        if type(payload) is not dict or set(payload) != _FIELDS or payload["schema_version"] != SCHEMA or payload["parser_version"] != PARSER_VERSION:
            raise PointInTimeDataError("security-master assertion fields or version differ")
        if any(type(payload[name]) is not type(expected) or payload[name] != expected for name, expected in _AUTHORITY.items()):
            raise PointInTimeDataError("security-master assertion authority is fixed")
        identifier = payload["assertion_id"]
        if type(identifier) is not str or _ASSERTION_ID.fullmatch(identifier) is None or identifier in result:
            raise PointInTimeDataError("duplicate or invalid security-master assertion ID")
        result[identifier] = payload
    return result


def build_security_master_assertion(*, archive: RawPointInTimeArtifactArchive, subject_kind: str, subject_id: str, field: str,
                                    raw_artifact_id: str, source_field_paths: dict, derivation_mode: str = "direct",
                                    correction_parents: Sequence[str] = (), prior_assertions: Sequence[object] = ()) -> SecurityMasterAssertionV2:
    replay = _Replay(archive, _registry(prior_assertions))
    return replay.derive(subject_kind=subject_kind, subject_id=subject_id, field=field, raw_artifact_id=raw_artifact_id,
                         source_field_paths=source_field_paths, derivation_mode=derivation_mode, correction_parents=correction_parents)


def verify_security_master_assertions(records: Sequence[object], *, archive: RawPointInTimeArtifactArchive) -> tuple[SecurityMasterAssertionV2, ...]:
    """Reopen each original once per verification, including every parent chain."""
    registry = _registry(records)
    replay = _Replay(archive, registry)
    return tuple(replay.verify(identifier) for identifier in registry)


def build_security_master_assertions(requests: Sequence[dict], *, archive: RawPointInTimeArtifactArchive,
                                     prior_assertions: Sequence[object] = ()) -> tuple[SecurityMasterAssertionV2, ...]:
    """Batch derivation shares one original replay across all selected page rows."""
    if type(requests) not in {list, tuple} or len(requests) > _MAX_RECORDS:
        raise PointInTimeDataError("security-master batch bound")
    replay = _Replay(archive, _registry(prior_assertions))
    records = []
    expected = {"subject_kind", "subject_id", "field", "raw_artifact_id", "source_field_paths", "derivation_mode", "correction_parents"}
    for request in requests:
        if type(request) is not dict or set(request) != expected:
            raise PointInTimeDataError("security-master batch request fields differ")
        record = replay.derive(**request)
        if record.assertion_id in replay.registry:
            raise PointInTimeDataError("duplicate security-master batch assertion")
        replay.registry[record.assertion_id] = record.to_dict()
        records.append(record)
    return tuple(records)


class SecurityMasterAssertionArchive:
    """Append-only derived records; the existing PIT archive retains originals."""

    def __init__(self, root: str | Path, *, originals: RawPointInTimeArtifactArchive):
        if type(originals) is not RawPointInTimeArtifactArchive:
            raise PointInTimeDataError("security-master store requires the original archive")
        self.root = Path(root).absolute()
        self.originals = originals

    def _read_payload(self, identifier: str) -> dict:
        if type(identifier) is not str or _ASSERTION_ID.fullmatch(identifier) is None or self.root.is_symlink():
            raise PointInTimeDataError("invalid security-master stored identity")
        try:
            fd = os.open(self.root / f"{identifier}.json", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise PointInTimeDataError("security-master stored assertion unavailable") from exc
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_BYTES:
                raise PointInTimeDataError("security-master stored record type or byte bound")
            raw = handle.read(_MAX_BYTES + 1)
        payload = _json(raw)
        checked = _registry([payload])
        if identifier not in checked or _canonical(payload) != raw:
            raise PointInTimeDataError("security-master stored record is not canonical")
        return payload

    def _closure(self, initial: dict) -> dict[str, dict]:
        registry = _registry([initial])
        pending = [initial["assertion_id"]]
        while pending:
            record = registry[pending.pop()]
            parents = record["correction_parents"]
            if type(parents) is not list or len(parents) > 128:
                raise PointInTimeDataError("invalid stored security-master lineage")
            for identifier in parents:
                if type(identifier) is not str or _ASSERTION_ID.fullmatch(identifier) is None:
                    raise PointInTimeDataError("invalid stored security-master parent")
                if identifier not in registry:
                    if len(registry) >= _MAX_RECORDS:
                        raise PointInTimeDataError("stored security-master lineage bound")
                    registry[identifier] = self._read_payload(identifier)
                    pending.append(identifier)
        return registry

    def read(self, identifier: str) -> SecurityMasterAssertionV2:
        registry = self._closure(self._read_payload(identifier))
        return _Replay(self.originals, registry).verify(identifier)

    def append(self, value: object) -> SecurityMasterAssertionV2:
        payload = value.to_dict() if type(value) is SecurityMasterAssertionV2 else value
        registry = self._closure(payload)
        record = _Replay(self.originals, registry).verify(payload["assertion_id"])
        if self.root.is_symlink():
            raise PointInTimeDataError("security-master store cannot be a symlink")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.root / f"{record.assertion_id}.json"
        raw = record.canonical_json_bytes()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            if self.read(record.assertion_id).canonical_json_bytes() != raw:
                raise PointInTimeDataError("existing security-master assertion differs") from None
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            directory = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return self.read(record.assertion_id)


def reconcile_security_master_assertions(records: Sequence[object], *, archive: RawPointInTimeArtifactArchive,
                                        subject_kind: str, subject_id: str, field: str, effective_on: str, known_at: str,
                                        coverage_state: str = "unknown") -> dict[str, object]:
    """Reproduce as-known facts; no response or null end never proves coverage."""
    _subject(subject_kind, subject_id)
    day, cutoff = _date(effective_on), _timestamp(known_at)
    if type(field) is not str or field not in _KINDS[subject_kind]:
        return {"state": "unsupported", "assertion_ids": [], "values": [], **_AUTHORITY}
    if type(coverage_state) is not str or coverage_state not in {"unknown", "data_unavailable", "not_requested"}:
        raise PointInTimeDataError("coverage absence must remain explicit")
    verified = verify_security_master_assertions(records, archive=archive)
    available, known = [], []
    for assertion in verified:
        value = assertion.to_dict()
        if (value["subject_kind"], value["subject_id"], value["field"]) != (subject_kind, subject_id, field):
            continue
        clocks = [value[name] for name in ("retrieved_at", "archive_recorded_at", "source_published_at", "source_recorded_at") if value[name] is not None]
        if any(_timestamp(clock) > cutoff for clock in clocks):
            continue
        known.append(value)
        start, end, through = (value[name] for name in ("effective_from", "effective_to", "coverage_through"))
        if start is None or day < _date(start) or (end is not None and day >= _date(end)):
            continue
        if end is None and (through is None or day > _date(through)):
            continue
        available.append(value)
    # A known correction can remove an interval; it still supersedes the older
    # fact on dates outside the corrected interval rather than reviving it.
    superseded = {parent for value in known for parent in value["correction_parents"]}
    current = [value for value in available if value["assertion_id"] not in superseded]
    unique = {_canonical(value["value"]): value["value"] for value in current}
    state = coverage_state
    if current:
        # Provider subdomains are one origin. This is conservative for public
        # suffixes with more than two labels; source-profile qualification is
        # still separate from agreeing JSON values.
        origins = {".".join(urlsplit(value["raw_artifact"]["source_uri"]).hostname.split(".")[-2:]) for value in current}
        if len(unique) > 1:
            state = "conflicting"
        elif len(origins) > 1:
            state = "corroborated"
        else:
            state = "reconstructed" if any(value["derivation_mode"] == "historical_reconstruction" for value in current) else "observed"
    return {"schema_version": "security_master_reconciliation/v2", "subject_kind": subject_kind, "subject_id": subject_id, "field": field,
            "effective_on": day.isoformat(), "known_at": cutoff.isoformat(), "state": state, "assertion_ids": sorted(value["assertion_id"] for value in current),
            "values": [unique[key] for key in sorted(unique)], "historical_custody_asserted": False, "cohort_qualified": False, **_AUTHORITY}
