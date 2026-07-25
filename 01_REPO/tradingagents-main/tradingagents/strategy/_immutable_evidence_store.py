"""Crash-safe immutable storage for analysis-only strategy evidence."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

STRATEGY_EVIDENCE_STORE_SCHEMA_VERSION = 1

_UTC = dt.timezone.utc
_ZERO_HASH = "0" * 64
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_KINDS = frozenset(
    {
        "evaluation-registration",
        "genome-window",
        "promotion-evidence",
        "baseline-genome",
        "mutation-record",
    }
)
_MAX_JSON_DEPTH = 16
_MAX_JSON_NODES = 10_000
_MAX_STRING_BYTES = 65_536
_MAX_CANONICAL_BYTES = 1_048_576
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_AUTHORITY_FIELDS = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "object_id",
        "effective_at",
        "recorded_at",
        "retry_material_sha256",
        "payload_sha256",
        "payload",
        *_AUTHORITY_FIELDS,
    }
)
_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "sequence",
        "kind",
        "object_id",
        "object_sha256",
        "retry_material_sha256",
        "effective_at",
        "recorded_at",
        "previous_event_sha256",
        *_AUTHORITY_FIELDS,
    }
)
_POINTER_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "sequence",
        "object_id",
        "object_sha256",
        "event_sha256",
        "recorded_at",
        *_AUTHORITY_FIELDS,
    }
)


class StrategyEvidenceStoreError(ValueError):
    """Base class for immutable strategy-evidence failures."""


class EvidenceCorruptionError(StrategyEvidenceStoreError):
    """Durable evidence is malformed, unsafe, or internally inconsistent."""


class EvidenceCollisionError(EvidenceCorruptionError):
    """A content-derived identity names different durable bytes."""


class EvidenceBackdatingError(StrategyEvidenceStoreError):
    """The store clock moved before durable first-seen evidence."""


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyEvidenceStoreError(
            "evidence must contain supported JSON values"
        ) from exc
    if len(encoded) > _MAX_CANONICAL_BYTES:
        raise StrategyEvidenceStoreError("canonical evidence is too large")
    return encoded


def _require_exact_fields(
    payload: Mapping[str, object],
    fields: frozenset[str],
    *,
    label: str,
) -> None:
    raw_keys = tuple(payload)
    if not all(isinstance(key, str) for key in raw_keys):
        raise EvidenceCorruptionError(f"{label} field names must be strings")
    keys = set(raw_keys)
    missing = sorted(fields - keys)
    unknown = sorted(keys - fields)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise EvidenceCorruptionError(f"{label} " + "; ".join(details))


def _require_authority(payload: Mapping[str, object], *, label: str) -> None:
    if payload["analysis_only"] is not True:
        raise EvidenceCorruptionError(f"{label} analysis_only must be true")
    if payload["execution_authority"] != "none":
        raise EvidenceCorruptionError(
            f"{label} execution_authority must be none"
        )
    if payload["can_submit_orders"] is not False:
        raise EvidenceCorruptionError(
            f"{label} can_submit_orders must be false"
        )


def _require_schema_version(value: object, *, label: str) -> None:
    if type(value) is not int or value != STRATEGY_EVIDENCE_STORE_SCHEMA_VERSION:
        raise EvidenceCorruptionError(f"{label} schema_version must equal 1")


def _require_kind(value: object) -> str:
    if not isinstance(value, str) or value not in _ALLOWED_KINDS:
        raise StrategyEvidenceStoreError("evidence kind is not allowed")
    return value


def _require_digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _LOWER_SHA256.fullmatch(value) is None:
        raise EvidenceCorruptionError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _parse_canonical_utc(value: object, *, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise StrategyEvidenceStoreError(
            f"{label} must be canonical UTC ISO-8601 seconds"
        )
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise StrategyEvidenceStoreError(
            f"{label} must be canonical UTC ISO-8601 seconds"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StrategyEvidenceStoreError(
            f"{label} must be canonical UTC ISO-8601 seconds"
        )
    normalized = parsed.astimezone(_UTC)
    if (
        normalized.microsecond != 0
        or normalized.isoformat(timespec="seconds") != value
    ):
        raise StrategyEvidenceStoreError(
            f"{label} must be canonical UTC ISO-8601 seconds"
        )
    return normalized


def _clock_stamp(clock: Callable[[], dt.datetime]) -> tuple[dt.datetime, str]:
    value = clock()
    if not isinstance(value, dt.datetime):
        raise StrategyEvidenceStoreError("store clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise StrategyEvidenceStoreError("store clock must be timezone-aware")
    normalized = value.astimezone(_UTC).replace(microsecond=0)
    return normalized, normalized.isoformat(timespec="seconds")


def _freeze_json(
    value: object,
    *,
    depth: int = 0,
    counter: list[int] | None = None,
) -> object:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > _MAX_JSON_NODES:
        raise StrategyEvidenceStoreError("evidence JSON contains too many values")
    if depth > _MAX_JSON_DEPTH:
        raise StrategyEvidenceStoreError("evidence JSON nesting is too deep")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > _MAX_STRING_BYTES:
            raise StrategyEvidenceStoreError("evidence string is too large")
        return value
    if isinstance(value, float):
        raise StrategyEvidenceStoreError("floats are not supported in evidence")
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrategyEvidenceStoreError(
                    "evidence JSON object keys must be strings"
                )
            if len(key.encode("utf-8")) > _MAX_STRING_BYTES:
                raise StrategyEvidenceStoreError("evidence key is too large")
            frozen[key] = _freeze_json(
                item,
                depth=depth + 1,
                counter=counter,
            )
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, depth=depth + 1, counter=counter)
            for item in value
        )
    raise StrategyEvidenceStoreError(
        f"unsupported evidence JSON value: {type(value).__name__}"
    )


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_payload(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise StrategyEvidenceStoreError("evidence payload must be a JSON object")
    frozen = _freeze_json(payload)
    if not isinstance(frozen, Mapping):
        raise StrategyEvidenceStoreError("evidence payload must be a JSON object")
    plain = _thaw_json(frozen)
    if not isinstance(plain, dict):
        raise StrategyEvidenceStoreError("evidence payload must be a JSON object")
    _canonical_json(plain)
    return frozen


def _payload_bytes(payload: Mapping[str, object]) -> bytes:
    thawed = _thaw_json(payload)
    if not isinstance(thawed, dict):
        raise StrategyEvidenceStoreError("evidence payload must be a JSON object")
    return _canonical_json(thawed)


def _retry_material_bytes(
    *,
    kind: str,
    effective_at: str,
    payload: Mapping[str, object],
) -> bytes:
    thawed = _thaw_json(payload)
    if not isinstance(thawed, dict):
        raise StrategyEvidenceStoreError("evidence payload must be a JSON object")
    return _canonical_json(
        {
            "kind": kind,
            "effective_at": effective_at,
            "payload": thawed,
        }
    )


def _require_object_id(
    value: object,
    *,
    kind: str,
    retry_material_sha256: str,
) -> str:
    expected = f"{kind}-{retry_material_sha256}"
    if not isinstance(value, str) or value != expected:
        raise EvidenceCorruptionError(
            "object_id does not match kind and retry material"
        )
    return value


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    kind: str
    object_id: str
    effective_at: str
    recorded_at: str
    retry_material_sha256: str
    payload_sha256: str
    payload: Mapping[str, object]
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        kind = _require_kind(self.kind)
        _parse_canonical_utc(self.effective_at, label="effective_at")
        _parse_canonical_utc(self.recorded_at, label="recorded_at")
        retry_digest = _require_digest(
            self.retry_material_sha256,
            label="retry_material_sha256",
        )
        payload_digest = _require_digest(
            self.payload_sha256,
            label="payload_sha256",
        )
        frozen = _freeze_payload(self.payload)
        object.__setattr__(self, "payload", frozen)
        expected_payload_digest = hashlib.sha256(
            _payload_bytes(frozen)
        ).hexdigest()
        if payload_digest != expected_payload_digest:
            raise EvidenceCorruptionError("payload_sha256 does not match payload")
        expected_retry_digest = hashlib.sha256(
            _retry_material_bytes(
                kind=kind,
                effective_at=self.effective_at,
                payload=frozen,
            )
        ).hexdigest()
        if retry_digest != expected_retry_digest:
            raise EvidenceCorruptionError(
                "retry_material_sha256 does not match evidence material"
            )
        _require_object_id(
            self.object_id,
            kind=kind,
            retry_material_sha256=retry_digest,
        )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvidenceEnvelope:
        if not isinstance(payload, Mapping):
            raise EvidenceCorruptionError("evidence envelope must be an object")
        _require_exact_fields(payload, _ENVELOPE_FIELDS, label="envelope")
        _require_schema_version(payload["schema_version"], label="envelope")
        _require_authority(payload, label="envelope")
        try:
            return cls(
                kind=payload["kind"],  # type: ignore[arg-type]
                object_id=payload["object_id"],  # type: ignore[arg-type]
                effective_at=payload["effective_at"],  # type: ignore[arg-type]
                recorded_at=payload["recorded_at"],  # type: ignore[arg-type]
                retry_material_sha256=payload[
                    "retry_material_sha256"
                ],  # type: ignore[arg-type]
                payload_sha256=payload["payload_sha256"],  # type: ignore[arg-type]
                payload=payload["payload"],  # type: ignore[arg-type]
            )
        except StrategyEvidenceStoreError as exc:
            if isinstance(exc, EvidenceCorruptionError):
                raise
            raise EvidenceCorruptionError(
                f"evidence envelope schema is invalid: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        payload = _thaw_json(self.payload)
        if not isinstance(payload, dict):
            raise EvidenceCorruptionError("envelope payload is invalid")
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "object_id": self.object_id,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "retry_material_sha256": self.retry_material_sha256,
            "payload_sha256": self.payload_sha256,
            "payload": payload,
            **_AUTHORITY_FIELDS,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    kind: str
    effective_at: str
    payload: Mapping[str, object]
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _require_kind(self.kind)
        _parse_canonical_utc(self.effective_at, label="effective_at")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    sequence: int
    kind: str
    object_id: str
    object_sha256: str
    retry_material_sha256: str
    effective_at: str
    recorded_at: str
    previous_event_sha256: str
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise EvidenceCorruptionError("event sequence must be positive")
        kind = _require_kind(self.kind)
        retry_digest = _require_digest(
            self.retry_material_sha256,
            label="retry_material_sha256",
        )
        _require_object_id(
            self.object_id,
            kind=kind,
            retry_material_sha256=retry_digest,
        )
        _require_digest(self.object_sha256, label="object_sha256")
        _require_digest(
            self.previous_event_sha256,
            label="previous_event_sha256",
        )
        _parse_canonical_utc(self.effective_at, label="effective_at")
        _parse_canonical_utc(self.recorded_at, label="recorded_at")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvidenceEvent:
        if not isinstance(payload, Mapping):
            raise EvidenceCorruptionError("evidence event must be an object")
        _require_exact_fields(payload, _EVENT_FIELDS, label="event")
        _require_schema_version(payload["schema_version"], label="event")
        _require_authority(payload, label="event")
        try:
            return cls(
                sequence=payload["sequence"],  # type: ignore[arg-type]
                kind=payload["kind"],  # type: ignore[arg-type]
                object_id=payload["object_id"],  # type: ignore[arg-type]
                object_sha256=payload["object_sha256"],  # type: ignore[arg-type]
                retry_material_sha256=payload[
                    "retry_material_sha256"
                ],  # type: ignore[arg-type]
                effective_at=payload["effective_at"],  # type: ignore[arg-type]
                recorded_at=payload["recorded_at"],  # type: ignore[arg-type]
                previous_event_sha256=payload[
                    "previous_event_sha256"
                ],  # type: ignore[arg-type]
            )
        except StrategyEvidenceStoreError as exc:
            if isinstance(exc, EvidenceCorruptionError):
                raise
            raise EvidenceCorruptionError(
                f"evidence event schema is invalid: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "kind": self.kind,
            "object_id": self.object_id,
            "object_sha256": self.object_sha256,
            "retry_material_sha256": self.retry_material_sha256,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "previous_event_sha256": self.previous_event_sha256,
            **_AUTHORITY_FIELDS,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvidencePointer:
    kind: str
    sequence: int
    object_id: str
    object_sha256: str
    event_sha256: str
    recorded_at: str
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise EvidenceCorruptionError("pointer sequence must be positive")
        kind = _require_kind(self.kind)
        object_digest = _require_digest(
            self.object_sha256,
            label="object_sha256",
        )
        _require_digest(self.event_sha256, label="event_sha256")
        _parse_canonical_utc(self.recorded_at, label="recorded_at")
        prefix = f"{kind}-"
        if (
            not isinstance(self.object_id, str)
            or not self.object_id.startswith(prefix)
            or _LOWER_SHA256.fullmatch(self.object_id[len(prefix) :]) is None
        ):
            raise EvidenceCorruptionError("pointer object_id is invalid")
        if not object_digest:
            raise EvidenceCorruptionError("pointer object digest is invalid")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> EvidencePointer:
        if not isinstance(payload, Mapping):
            raise EvidenceCorruptionError("evidence pointer must be an object")
        _require_exact_fields(payload, _POINTER_FIELDS, label="pointer")
        _require_schema_version(payload["schema_version"], label="pointer")
        _require_authority(payload, label="pointer")
        try:
            return cls(
                kind=payload["kind"],  # type: ignore[arg-type]
                sequence=payload["sequence"],  # type: ignore[arg-type]
                object_id=payload["object_id"],  # type: ignore[arg-type]
                object_sha256=payload["object_sha256"],  # type: ignore[arg-type]
                event_sha256=payload["event_sha256"],  # type: ignore[arg-type]
                recorded_at=payload["recorded_at"],  # type: ignore[arg-type]
            )
        except StrategyEvidenceStoreError as exc:
            if isinstance(exc, EvidenceCorruptionError):
                raise
            raise EvidenceCorruptionError(
                f"evidence pointer schema is invalid: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "sequence": self.sequence,
            "object_id": self.object_id,
            "object_sha256": self.object_sha256,
            "event_sha256": self.event_sha256,
            "recorded_at": self.recorded_at,
            **_AUTHORITY_FIELDS,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvidenceAdmission:
    envelope: EvidenceEnvelope
    path: Path
    event: EvidenceEvent
    created: bool


class ImmutableStrategyEvidenceStore:
    """Persist and replay immutable strategy evidence under one exclusive lock."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        lexical_root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
        self._reject_symlink_components(lexical_root)
        state = self._lstat_uncontained(lexical_root, label="evidence root")
        if state is not None:
            self._require_directory_state(state, label="evidence root")
        self.root = lexical_root
        self._clock = clock or (lambda: dt.datetime.now(_UTC))
        self._lock_path = self.root / ".strategy-evidence.lock"
        self._events_path = self.root / "events.jsonl"
        self._objects_dir = self.root / "objects"
        self._latest_dir = self.root / "latest"
        self._callback_state = threading.local()

    def admit_checked(
        self,
        candidate: EvidenceCandidate,
        *,
        validate: Callable[
            [tuple[EvidenceEnvelope, ...], EvidenceEnvelope],
            None,
        ],
    ) -> EvidenceAdmission:
        if not isinstance(candidate, EvidenceCandidate):
            raise StrategyEvidenceStoreError(
                "candidate must be an EvidenceCandidate"
            )
        if not callable(validate):
            raise StrategyEvidenceStoreError("validate must be callable")
        self._reject_callback_reentry()
        retry_bytes = _retry_material_bytes(
            kind=candidate.kind,
            effective_at=candidate.effective_at,
            payload=candidate.payload,
        )
        retry_digest = hashlib.sha256(retry_bytes).hexdigest()
        object_id = f"{candidate.kind}-{retry_digest}"
        payload_digest = hashlib.sha256(
            _payload_bytes(candidate.payload)
        ).hexdigest()

        with self._locked(create=True):
            self._ensure_managed_directories(create=True)
            events, snapshot = self._replay()
            event_by_id = {event.object_id: event for event in events}
            now, recorded_at = _clock_stamp(self._clock)
            valid_orphans = self._valid_orphan_envelopes(
                admitted_object_ids=frozenset(event_by_id)
            )
            for existing in (*snapshot, *valid_orphans):
                if now < _parse_canonical_utc(
                    existing.recorded_at,
                    label="recorded_at",
                ):
                    raise EvidenceBackdatingError(
                        "store clock is earlier than durable first-seen evidence"
                    )

            object_path = self._object_path(candidate.kind, object_id)
            object_state = self._path_state(object_path, label="evidence object")
            prior_event = event_by_id.get(object_id)
            object_existed = object_state is not None
            if prior_event is not None:
                envelope = next(
                    item for item in snapshot if item.object_id == object_id
                )
            elif object_existed:
                try:
                    envelope, _ = self._read_envelope(
                        object_path,
                        expected_kind=candidate.kind,
                        expected_id=object_id,
                    )
                except EvidenceCorruptionError as exc:
                    raise EvidenceCollisionError(
                        f"evidence object collision: {object_id}"
                    ) from exc
            else:
                envelope = EvidenceEnvelope(
                    kind=candidate.kind,
                    object_id=object_id,
                    effective_at=candidate.effective_at,
                    recorded_at=recorded_at,
                    retry_material_sha256=retry_digest,
                    payload_sha256=payload_digest,
                    payload=candidate.payload,
                )

            if (
                envelope.kind != candidate.kind
                or envelope.object_id != object_id
                or envelope.effective_at != candidate.effective_at
                or envelope.retry_material_sha256 != retry_digest
                or envelope.payload_sha256 != payload_digest
                or envelope.payload != candidate.payload
            ):
                raise EvidenceCollisionError(
                    f"evidence object collision: {object_id}"
                )
            if now < _parse_canonical_utc(
                envelope.recorded_at,
                label="recorded_at",
            ):
                raise EvidenceBackdatingError(
                    "store clock is earlier than object first-seen evidence"
                )

            self._callback_state.active = True
            try:
                validate(snapshot, envelope)
            finally:
                self._callback_state.active = False

            if prior_event is not None:
                self._redurable_journal_if_present()
                self._repair_latest(events)
                return EvidenceAdmission(
                    envelope=envelope,
                    path=object_path,
                    event=prior_event,
                    created=False,
                )

            self._redurable_journal_if_present()
            self._ensure_kind_directory(candidate.kind, create=True)
            if not object_existed:
                self._write_immutable_object(
                    object_path,
                    envelope.canonical_json_bytes(),
                )
                self._after_object_fsync(object_path)
            else:
                self._redurable_regular_file(
                    object_path,
                    label="evidence object",
                )
                self._fsync_directory(self._kind_directory(candidate.kind))
                self._fsync_directory(self._objects_dir)

            object_sha256 = hashlib.sha256(
                envelope.canonical_json_bytes()
            ).hexdigest()
            previous_hash = (
                hashlib.sha256(events[-1].canonical_json_bytes()).hexdigest()
                if events
                else _ZERO_HASH
            )
            event = EvidenceEvent(
                sequence=len(events) + 1,
                kind=envelope.kind,
                object_id=envelope.object_id,
                object_sha256=object_sha256,
                retry_material_sha256=envelope.retry_material_sha256,
                effective_at=envelope.effective_at,
                recorded_at=envelope.recorded_at,
                previous_event_sha256=previous_hash,
            )
            self._append_event(event)
            self._after_event_fsync(event)
            self._repair_latest((*events, event))
            return EvidenceAdmission(
                envelope=envelope,
                path=object_path,
                event=event,
                created=True,
            )

    def verify(self) -> tuple[EvidenceEnvelope, ...]:
        self._reject_callback_reentry()
        if self._root_is_absent():
            return ()
        with self._locked(create=False):
            self._ensure_managed_directories(create=False)
            events, envelopes = self._replay()
            self._verify_latest(events)
            return envelopes

    def rebuild(self) -> tuple[EvidenceEnvelope, ...]:
        self._reject_callback_reentry()
        if self._root_is_absent():
            return ()
        with self._locked(create=False):
            self._ensure_managed_directories(create=False)
            events, envelopes = self._replay()
            self._repair_latest(events)
            return envelopes

    def envelopes(
        self,
        *,
        kind: str | None = None,
    ) -> tuple[EvidenceEnvelope, ...]:
        if kind is not None:
            _require_kind(kind)
        envelopes = self.verify()
        if kind is None:
            return envelopes
        return tuple(item for item in envelopes if item.kind == kind)

    def _after_object_fsync(self, object_path: Path) -> None:
        """Protected deterministic seam after an immutable object is durable."""

    def _after_event_fsync(self, event: EvidenceEvent) -> None:
        """Protected deterministic seam after a journal event is durable."""

    def _reject_callback_reentry(self) -> None:
        if getattr(self._callback_state, "active", False):
            raise StrategyEvidenceStoreError(
                "validation callback must not call the evidence store"
            )

    def _root_is_absent(self) -> bool:
        state = self._lstat_uncontained(self.root, label="evidence root")
        return state is None

    @contextmanager
    def _locked(self, *, create: bool) -> Iterator[None]:
        self._ensure_root(create=create)
        state = self._path_state(self._lock_path, label="evidence lock")
        if state is None and not create:
            raise EvidenceCorruptionError("evidence lock is missing")
        if state is not None:
            self._require_regular_state(state, label="evidence lock")
        flags = os.O_RDWR | _NOFOLLOW
        if create:
            flags |= os.O_CREAT
        try:
            descriptor = os.open(self._lock_path, flags, 0o600)
        except OSError as exc:
            raise EvidenceCorruptionError(
                "evidence lock could not be opened safely"
            ) from exc
        try:
            descriptor_state = self._require_regular_descriptor(
                descriptor,
                label="evidence lock",
            )
            if state is None:
                self._fsync_directory(self.root)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = self._path_state(self._lock_path, label="evidence lock")
            if current is None:
                raise EvidenceCorruptionError("evidence lock disappeared")
            self._require_regular_state(current, label="evidence lock")
            if (
                current.st_dev != descriptor_state.st_dev
                or current.st_ino != descriptor_state.st_ino
            ):
                raise EvidenceCorruptionError(
                    "evidence lock changed while being acquired"
                )
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _ensure_root(self, *, create: bool) -> None:
        self._reject_symlink_components(self.root)
        state = self._path_state(self.root, label="evidence root")
        if state is None:
            if not create:
                raise EvidenceCorruptionError("evidence root is missing")
            try:
                self.root.mkdir(mode=0o700, parents=True)
            except FileExistsError:
                pass
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "evidence root could not be created"
                ) from exc
            state = self._path_state(self.root, label="evidence root")
        self._require_directory_state(state, label="evidence root")

    def _ensure_managed_directories(self, *, create: bool) -> None:
        created = False
        for path, label in (
            (self._objects_dir, "objects directory"),
            (self._latest_dir, "latest directory"),
        ):
            state = self._path_state(path, label=label)
            if state is None:
                if not create:
                    raise EvidenceCorruptionError(f"{label} is missing")
                try:
                    path.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise EvidenceCorruptionError(
                        f"{label} could not be created"
                    ) from exc
                state = self._path_state(path, label=label)
                created = True
            self._require_directory_state(state, label=label)
        if created:
            self._fsync_directory(self.root)
        self._inspect_object_directory_entries()
        self._inspect_latest_directory_entries()

    def _ensure_kind_directory(self, kind: str, *, create: bool) -> Path:
        path = self._kind_directory(kind)
        state = self._path_state(path, label="object kind directory")
        if state is None:
            if not create:
                raise EvidenceCorruptionError("object kind directory is missing")
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "object kind directory could not be created"
                ) from exc
            state = self._path_state(path, label="object kind directory")
            self._fsync_directory(self._objects_dir)
        self._require_directory_state(state, label="object kind directory")
        return path

    def _inspect_object_directory_entries(self) -> None:
        try:
            kind_entries = tuple(self._objects_dir.iterdir())
        except OSError as exc:
            raise EvidenceCorruptionError(
                "objects directory could not be listed"
            ) from exc
        for kind_path in kind_entries:
            if kind_path.name not in _ALLOWED_KINDS:
                raise EvidenceCorruptionError(
                    f"unknown object kind path: {kind_path.name}"
                )
            state = self._path_state(kind_path, label="object kind directory")
            self._require_directory_state(state, label="object kind directory")
            try:
                children = tuple(kind_path.iterdir())
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "object kind directory could not be listed"
                ) from exc
            pattern = re.compile(
                rf"^{re.escape(kind_path.name)}-[0-9a-f]{{64}}\.json$"
            )
            for child in children:
                if pattern.fullmatch(child.name) is None:
                    raise EvidenceCorruptionError(
                        f"unknown evidence object path: {child.name}"
                    )
                child_state = self._path_state(child, label="evidence object")
                if child_state is None:
                    raise EvidenceCorruptionError("evidence object disappeared")
                self._require_regular_state(
                    child_state,
                    label="evidence object",
                )

    def _inspect_latest_directory_entries(self) -> None:
        allowed_names = {f"{kind}.json" for kind in _ALLOWED_KINDS}
        try:
            entries = tuple(self._latest_dir.iterdir())
        except OSError as exc:
            raise EvidenceCorruptionError(
                "latest directory could not be listed"
            ) from exc
        for path in entries:
            if path.name not in allowed_names:
                raise EvidenceCorruptionError(
                    f"unknown latest pointer path: {path.name}"
                )
            state = self._path_state(path, label="latest pointer")
            if state is None:
                raise EvidenceCorruptionError("latest pointer disappeared")
            self._require_regular_state(state, label="latest pointer")

    def _lstat_uncontained(
        self,
        path: Path,
        *,
        label: str,
    ) -> os.stat_result | None:
        try:
            return path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise EvidenceCorruptionError(
                f"{label} could not be inspected"
            ) from exc

    def _path_state(
        self,
        path: Path,
        *,
        label: str,
    ) -> os.stat_result | None:
        self._require_contained(path)
        return self._lstat_uncontained(path, label=label)

    def _require_contained(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise EvidenceCorruptionError(
                "managed path escapes evidence root"
            ) from exc

    def _reject_symlink_components(self, path: Path) -> None:
        absolute = Path(os.path.abspath(os.fspath(path)))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current /= part
            try:
                state = current.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "evidence path component could not be inspected"
                ) from exc
            if stat.S_ISLNK(state.st_mode):
                raise EvidenceCorruptionError(
                    f"evidence path must not contain a symlink: {current.name}"
                )

    def _require_directory_state(
        self,
        state: os.stat_result | None,
        *,
        label: str,
    ) -> None:
        if state is None:
            raise EvidenceCorruptionError(f"{label} is missing")
        if stat.S_ISLNK(state.st_mode):
            raise EvidenceCorruptionError(f"{label} must not be a symlink")
        if not stat.S_ISDIR(state.st_mode):
            raise EvidenceCorruptionError(f"{label} must be a directory")
        if stat.S_IMODE(state.st_mode) & 0o022:
            raise EvidenceCorruptionError(f"{label} has an unsafe mode")

    def _require_regular_state(
        self,
        state: os.stat_result,
        *,
        label: str,
    ) -> None:
        if stat.S_ISLNK(state.st_mode):
            raise EvidenceCorruptionError(f"{label} must not be a symlink")
        if not stat.S_ISREG(state.st_mode):
            raise EvidenceCorruptionError(f"{label} must be a regular file")
        if state.st_nlink != 1:
            raise EvidenceCorruptionError(
                f"{label} must have exactly one hard link"
            )
        if stat.S_IMODE(state.st_mode) != 0o600:
            raise EvidenceCorruptionError(f"{label} has an unsafe mode")

    def _require_regular_descriptor(
        self,
        descriptor: int,
        *,
        label: str,
    ) -> os.stat_result:
        try:
            state = os.fstat(descriptor)
        except OSError as exc:
            raise EvidenceCorruptionError(
                f"{label} descriptor could not be inspected"
            ) from exc
        self._require_regular_state(state, label=label)
        return state

    def _require_real_directory(self, path: Path, *, label: str) -> None:
        state = self._path_state(path, label=label)
        self._require_directory_state(state, label=label)

    def _fsync_directory(self, path: Path) -> None:
        self._require_real_directory(path, label=f"{path.name} directory")
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW,
            )
        except OSError as exc:
            raise EvidenceCorruptionError(
                f"directory could not be opened: {path.name}"
            ) from exc
        try:
            try:
                state = os.fstat(descriptor)
                if not stat.S_ISDIR(state.st_mode):
                    raise OSError("directory descriptor is invalid")
                os.fsync(descriptor)
            except OSError as exc:
                raise EvidenceCorruptionError(
                    f"directory could not be made durable: {path.name}"
                ) from exc
        finally:
            os.close(descriptor)

    def _read_regular(self, path: Path, *, label: str) -> bytes:
        state = self._path_state(path, label=label)
        if state is None:
            raise EvidenceCorruptionError(f"{label} is missing")
        self._require_regular_state(state, label=label)
        try:
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise EvidenceCorruptionError(
                f"{label} could not be opened safely"
            ) from exc
        try:
            descriptor_state = self._require_regular_descriptor(
                descriptor,
                label=label,
            )
            if (
                state.st_dev != descriptor_state.st_dev
                or state.st_ino != descriptor_state.st_ino
            ):
                raise EvidenceCorruptionError(f"{label} changed while opening")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        except OSError as exc:
            raise EvidenceCorruptionError(f"{label} could not be read") from exc
        finally:
            os.close(descriptor)

    def _redurable_regular_file(self, path: Path, *, label: str) -> None:
        state = self._path_state(path, label=label)
        if state is None:
            raise EvidenceCorruptionError(f"{label} is missing")
        self._require_regular_state(state, label=label)
        try:
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise EvidenceCorruptionError(
                f"{label} could not be reopened safely"
            ) from exc
        try:
            descriptor_state = self._require_regular_descriptor(
                descriptor,
                label=label,
            )
            if (
                state.st_dev != descriptor_state.st_dev
                or state.st_ino != descriptor_state.st_ino
            ):
                raise EvidenceCorruptionError(f"{label} changed while opening")
            try:
                os.fsync(descriptor)
            except OSError as exc:
                raise EvidenceCorruptionError(
                    f"{label} could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)

    def _redurable_journal_if_present(self) -> None:
        state = self._path_state(self._events_path, label="event journal")
        if state is None:
            return
        self._require_regular_state(state, label="event journal")
        self._redurable_regular_file(
            self._events_path,
            label="event journal",
        )
        self._fsync_directory(self.root)

    def _kind_directory(self, kind: str) -> Path:
        _require_kind(kind)
        path = self._objects_dir / kind
        self._require_contained(path)
        return path

    def _object_path(self, kind: str, object_id: str) -> Path:
        retry_digest = object_id.removeprefix(f"{kind}-")
        _require_object_id(
            object_id,
            kind=kind,
            retry_material_sha256=_require_digest(
                retry_digest,
                label="object identity digest",
            ),
        )
        path = self._kind_directory(kind) / f"{object_id}.json"
        self._require_contained(path)
        return path

    def _pointer_path(self, kind: str) -> Path:
        _require_kind(kind)
        path = self._latest_dir / f"{kind}.json"
        self._require_contained(path)
        return path

    def _write_immutable_object(self, path: Path, payload: bytes) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise EvidenceCollisionError(
                "evidence object appeared during locked creation"
            ) from exc
        except OSError as exc:
            raise EvidenceCorruptionError(
                "evidence object could not be created"
            ) from exc
        try:
            self._require_regular_descriptor(
                descriptor,
                label="evidence object",
            )
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise OSError("incomplete evidence object write")
                    offset += written
                os.fsync(descriptor)
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "evidence object could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)
        self._fsync_directory(path.parent)
        self._fsync_directory(self._objects_dir)

    def _read_envelope(
        self,
        path: Path,
        *,
        expected_kind: str,
        expected_id: str,
    ) -> tuple[EvidenceEnvelope, bytes]:
        raw = self._read_regular(path, label="evidence object")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceCorruptionError(
                "evidence object is not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise EvidenceCorruptionError(
                "evidence object must be a JSON object"
            )
        envelope = EvidenceEnvelope.from_dict(decoded)
        if envelope.canonical_json_bytes() != raw:
            raise EvidenceCorruptionError(
                "evidence object bytes are noncanonical"
            )
        if envelope.kind != expected_kind or envelope.object_id != expected_id:
            raise EvidenceCorruptionError(
                "evidence object path and identity mismatch"
            )
        if path != self._object_path(envelope.kind, envelope.object_id):
            raise EvidenceCorruptionError(
                "evidence object path and identity mismatch"
            )
        return envelope, raw

    def _replay(
        self,
    ) -> tuple[tuple[EvidenceEvent, ...], tuple[EvidenceEnvelope, ...]]:
        state = self._path_state(self._events_path, label="event journal")
        if state is None:
            return (), ()
        raw = self._read_regular(self._events_path, label="event journal")
        if not raw:
            return (), ()
        if not raw.endswith(b"\n"):
            raise EvidenceCorruptionError("event journal has a torn final line")
        lines = raw[:-1].split(b"\n")
        if any(not line for line in lines):
            raise EvidenceCorruptionError("event journal contains a blank line")

        events: list[EvidenceEvent] = []
        envelopes: list[EvidenceEnvelope] = []
        object_ids: set[str] = set()
        expected_previous = _ZERO_HASH
        for expected_sequence, line in enumerate(lines, start=1):
            try:
                decoded = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceCorruptionError(
                    f"event journal line {expected_sequence} is malformed"
                ) from exc
            if not isinstance(decoded, Mapping):
                raise EvidenceCorruptionError(
                    f"event journal line {expected_sequence} is malformed"
                )
            try:
                event = EvidenceEvent.from_dict(decoded)
            except EvidenceCorruptionError as exc:
                raise EvidenceCorruptionError(
                    f"event journal line {expected_sequence}: {exc}"
                ) from exc
            if event.canonical_json_bytes() != line:
                raise EvidenceCorruptionError(
                    f"event journal line {expected_sequence} is noncanonical"
                )
            if event.sequence != expected_sequence:
                raise EvidenceCorruptionError(
                    f"event sequence gap at {expected_sequence}"
                )
            if event.previous_event_sha256 != expected_previous:
                raise EvidenceCorruptionError(
                    f"event chain break at sequence {event.sequence}"
                )
            if event.object_id in object_ids:
                raise EvidenceCorruptionError(
                    f"repeated evidence event: {event.object_id}"
                )
            object_path = self._object_path(event.kind, event.object_id)
            envelope, object_bytes = self._read_envelope(
                object_path,
                expected_kind=event.kind,
                expected_id=event.object_id,
            )
            object_digest = hashlib.sha256(object_bytes).hexdigest()
            if object_digest != event.object_sha256:
                raise EvidenceCorruptionError(
                    f"object digest mismatch at sequence {event.sequence}"
                )
            if (
                event.kind != envelope.kind
                or event.object_id != envelope.object_id
                or event.retry_material_sha256
                != envelope.retry_material_sha256
                or event.effective_at != envelope.effective_at
                or event.recorded_at != envelope.recorded_at
            ):
                raise EvidenceCorruptionError(
                    f"event and object binding mismatch at sequence {event.sequence}"
                )
            object_ids.add(event.object_id)
            events.append(event)
            envelopes.append(envelope)
            expected_previous = hashlib.sha256(line).hexdigest()
        return tuple(events), tuple(envelopes)

    def _valid_orphan_envelopes(
        self,
        *,
        admitted_object_ids: frozenset[str],
    ) -> tuple[EvidenceEnvelope, ...]:
        orphans: list[EvidenceEnvelope] = []
        for kind in sorted(_ALLOWED_KINDS):
            kind_path = self._kind_directory(kind)
            state = self._path_state(
                kind_path,
                label="object kind directory",
            )
            if state is None:
                continue
            self._require_directory_state(
                state,
                label="object kind directory",
            )
            try:
                children = tuple(sorted(kind_path.iterdir()))
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "object kind directory could not be listed"
                ) from exc
            pattern = re.compile(
                rf"^{re.escape(kind)}-[0-9a-f]{{64}}\.json$"
            )
            for object_path in children:
                if pattern.fullmatch(object_path.name) is None:
                    continue
                object_id = object_path.name.removesuffix(".json")
                if object_id in admitted_object_ids:
                    continue
                try:
                    envelope, _ = self._read_envelope(
                        object_path,
                        expected_kind=kind,
                        expected_id=object_id,
                    )
                except EvidenceCorruptionError:
                    continue
                orphans.append(envelope)
        return tuple(orphans)

    def _append_event(self, event: EvidenceEvent) -> None:
        state = self._path_state(self._events_path, label="event journal")
        if state is not None:
            self._require_regular_state(state, label="event journal")
        line = event.canonical_json_bytes() + b"\n"
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | _NOFOLLOW
        try:
            descriptor = os.open(self._events_path, flags, 0o600)
        except OSError as exc:
            raise EvidenceCorruptionError(
                "event journal could not be opened safely"
            ) from exc
        try:
            self._require_regular_descriptor(
                descriptor,
                label="event journal",
            )
            try:
                if os.write(descriptor, line) != len(line):
                    raise OSError("incomplete evidence event append")
                os.fsync(descriptor)
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "event journal could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)
        self._fsync_directory(self.root)

    def _pointer_for(self, event: EvidenceEvent) -> EvidencePointer:
        return EvidencePointer(
            kind=event.kind,
            sequence=event.sequence,
            object_id=event.object_id,
            object_sha256=event.object_sha256,
            event_sha256=hashlib.sha256(
                event.canonical_json_bytes()
            ).hexdigest(),
            recorded_at=event.recorded_at,
        )

    def _last_events(
        self,
        events: tuple[EvidenceEvent, ...],
    ) -> dict[str, EvidenceEvent]:
        latest: dict[str, EvidenceEvent] = {}
        for event in events:
            latest[event.kind] = event
        return latest

    def _publish_pointer(self, pointer: EvidencePointer) -> None:
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        path = self._pointer_path(pointer.kind)
        state = self._path_state(path, label="latest pointer")
        if state is not None:
            self._require_regular_state(state, label="latest pointer")
        payload = pointer.canonical_json_bytes()
        temp_path = self._latest_dir / (
            f".{pointer.kind}.{os.getpid()}.{threading.get_ident()}."
            f"{time.time_ns()}.tmp"
        )
        self._require_contained(temp_path)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temp_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
                0o600,
            )
            self._require_regular_descriptor(
                descriptor,
                label="staged latest pointer",
            )
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("incomplete pointer write")
                offset += written
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            self._require_real_directory(
                self._latest_dir,
                label="latest directory",
            )
            os.replace(temp_path, path)
            self._redurable_regular_file(path, label="latest pointer")
            self._fsync_directory(self._latest_dir)
            self._fsync_directory(self.root)
        except EvidenceCorruptionError:
            raise
        except OSError as exc:
            raise EvidenceCorruptionError(
                f"latest pointer could not be published for {pointer.kind}"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:
                raise EvidenceCorruptionError(
                    "staged latest pointer could not be cleaned"
                ) from exc
        if self._read_regular(path, label="latest pointer") != payload:
            raise EvidenceCorruptionError(
                f"latest pointer publication failed for {pointer.kind}"
            )

    def _repair_latest(self, events: tuple[EvidenceEvent, ...]) -> None:
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        expected = self._last_events(events)
        removed = False
        redurable_existing = False
        for kind in sorted(_ALLOWED_KINDS):
            path = self._pointer_path(kind)
            state = self._path_state(path, label="latest pointer")
            event = expected.get(kind)
            if event is None:
                if state is not None:
                    self._require_regular_state(
                        state,
                        label="latest pointer",
                    )
                    try:
                        path.unlink()
                    except OSError as exc:
                        raise EvidenceCorruptionError(
                            f"stale latest pointer could not be removed: {kind}"
                        ) from exc
                    removed = True
                continue
            pointer = self._pointer_for(event)
            expected_bytes = pointer.canonical_json_bytes()
            if state is not None:
                current = self._read_regular(path, label="latest pointer")
                if current == expected_bytes:
                    self._redurable_regular_file(
                        path,
                        label="latest pointer",
                    )
                    redurable_existing = True
                    continue
            self._publish_pointer(pointer)
        if removed or redurable_existing:
            self._fsync_directory(self._latest_dir)
            self._fsync_directory(self.root)

    def _verify_latest(self, events: tuple[EvidenceEvent, ...]) -> None:
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        expected = self._last_events(events)
        for kind in sorted(_ALLOWED_KINDS):
            path = self._pointer_path(kind)
            state = self._path_state(path, label="latest pointer")
            event = expected.get(kind)
            if event is None:
                if state is not None:
                    raise EvidenceCorruptionError(
                        f"unexpected latest pointer for {kind}"
                    )
                continue
            if state is None:
                raise EvidenceCorruptionError(
                    f"latest pointer is missing for {kind}"
                )
            raw = self._read_regular(path, label="latest pointer")
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceCorruptionError(
                    f"latest pointer is malformed for {kind}"
                ) from exc
            if not isinstance(decoded, Mapping):
                raise EvidenceCorruptionError(
                    f"latest pointer is malformed for {kind}"
                )
            try:
                pointer = EvidencePointer.from_dict(decoded)
            except EvidenceCorruptionError as exc:
                raise EvidenceCorruptionError(
                    f"latest pointer is malformed for {kind}: {exc}"
                ) from exc
            expected_pointer = self._pointer_for(event)
            if (
                pointer != expected_pointer
                or raw != expected_pointer.canonical_json_bytes()
            ):
                raise EvidenceCorruptionError(
                    f"latest pointer is stale or malformed for {kind}"
                )
