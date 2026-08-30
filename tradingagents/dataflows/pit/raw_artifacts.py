"""Immutable raw source artifacts for point-in-time evaluation inputs.

The archive deliberately stores source bytes without parsing or normalizing them.
It is not a database or an evidence ledger: each content-bound receipt points to
one write-once raw object and a matching canonical JSON sidecar.  Derived
manifests or an optional search index can therefore be deleted and rebuilt from
these exact source bytes.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from tradingagents.dataflows.pit.records import PointInTimeDataError

__all__ = [
    "RawPointInTimeArtifact",
    "RawPointInTimeArtifactArchive",
    "build_raw_point_in_time_artifact",
    "validate_raw_point_in_time_artifact",
]


_SCHEMA = "raw_point_in_time_artifact/v2"
_AUTHORITY = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/x-ndjson",
        "application/xhtml+xml",
        "application/xml",
        "text/html",
        "text/xml",
    }
)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_RAW_ARTIFACT_ID = re.compile(r"pit-raw-artifact-[0-9a-f]{64}")


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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_timestamp(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    try:
        parsed = dt.datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise PointInTimeDataError(
            f"{label} must use canonical UTC seconds"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    if parsed.tzinfo != dt.UTC or parsed.strftime(_TIMESTAMP_FORMAT) != value:
        raise PointInTimeDataError(f"{label} must use canonical UTC seconds")
    return value


def _clock_timestamp(value: object) -> str:
    if (
        type(value) is not dt.datetime
        or value.tzinfo != dt.UTC
        or value.microsecond != 0
    ):
        raise PointInTimeDataError(
            "archive clock must return an exact UTC datetime at whole-second precision"
        )
    return value.isoformat(timespec="seconds")


def _exact_utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _source_uri(value: object) -> str:
    if type(value) is not str:
        raise PointInTimeDataError("source_uri must be a canonical HTTPS URI")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not parsed.path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise PointInTimeDataError("source_uri must be a safe canonical HTTPS URI")
    return value


def _content_type(value: object) -> str:
    if type(value) is not str or value not in _CONTENT_TYPES:
        raise PointInTimeDataError("content_type is not supported for raw PIT evidence")
    return value


def _digest(value: object, *, label: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise PointInTimeDataError(f"{label} must be a lowercase SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PointInTimeDataError(
            f"{label} must be a lowercase SHA-256 digest"
        ) from exc
    if value != value.lower():
        raise PointInTimeDataError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _authority(payload: Mapping[str, object]) -> None:
    if (
        payload["analysis_only"] is not True
        or type(payload["execution_authority"]) is not str
        or payload["execution_authority"] != "none"
        or payload["can_submit_orders"] is not False
    ):
        raise PointInTimeDataError("raw artifact authority fields are fixed")


@dataclasses.dataclass(frozen=True, slots=True, init=False)
class RawPointInTimeArtifact:
    """Canonical receipt for exact, local immutable source bytes."""

    raw_artifact_id: str
    raw_artifact_sha256: str
    record_sha256: str
    source_uri: str
    content_type: str
    retrieved_at: str
    archive_recorded_at: str
    byte_count: int

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError(
            "RawPointInTimeArtifact instances must be created by its builder"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA,
            "raw_artifact_id": self.raw_artifact_id,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "record_sha256": self.record_sha256,
            "source_uri": self.source_uri,
            "content_type": self.content_type,
            "retrieved_at": self.retrieved_at,
            "archive_recorded_at": self.archive_recorded_at,
            "byte_count": self.byte_count,
            **_AUTHORITY,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


_FIELDS = tuple(field.name for field in dataclasses.fields(RawPointInTimeArtifact))
_SERIALIZED_FIELDS = frozenset(_FIELDS + ("schema_version",) + tuple(_AUTHORITY))


def _new_artifact(**fields: object) -> RawPointInTimeArtifact:
    artifact = object.__new__(RawPointInTimeArtifact)
    for field in _FIELDS:
        object.__setattr__(artifact, field, fields[field])
    return artifact


def _from_material(
    *,
    raw_artifact_sha256: object,
    source_uri: object,
    content_type: object,
    retrieved_at: object,
    archive_recorded_at: object,
    byte_count: object,
) -> RawPointInTimeArtifact:
    raw_digest = _digest(raw_artifact_sha256, label="raw_artifact_sha256")
    uri = _source_uri(source_uri)
    mime = _content_type(content_type)
    retrieval_timestamp = _canonical_timestamp(retrieved_at, label="retrieved_at")
    recorded_timestamp = _canonical_timestamp(
        archive_recorded_at,
        label="archive_recorded_at",
    )
    if dt.datetime.strptime(recorded_timestamp, _TIMESTAMP_FORMAT) < dt.datetime.strptime(
        retrieval_timestamp,
        _TIMESTAMP_FORMAT,
    ):
        raise PointInTimeDataError(
            "archive_recorded_at cannot be before source retrieval"
        )
    if type(byte_count) is not int or byte_count <= 0:
        raise PointInTimeDataError("byte_count must be a positive exact integer")
    identity = {
        "schema_version": _SCHEMA,
        "raw_artifact_sha256": raw_digest,
        "source_uri": uri,
        "content_type": mime,
        "retrieved_at": retrieval_timestamp,
        "archive_recorded_at": recorded_timestamp,
        "byte_count": byte_count,
        **_AUTHORITY,
    }
    artifact_id = "pit-raw-artifact-" + _sha256(identity)
    record_sha256 = _sha256({**identity, "raw_artifact_id": artifact_id})
    return _new_artifact(
        raw_artifact_id=artifact_id,
        raw_artifact_sha256=raw_digest,
        record_sha256=record_sha256,
        source_uri=uri,
        content_type=mime,
        retrieved_at=retrieval_timestamp,
        archive_recorded_at=recorded_timestamp,
        byte_count=byte_count,
    )


def build_raw_point_in_time_artifact(
    *,
    raw_bytes: bytes,
    source_uri: str,
    content_type: str,
    retrieved_at: str,
    archive_recorded_at: str,
) -> RawPointInTimeArtifact:
    """Create a receipt while preserving the supplied bytes exactly."""

    if type(raw_bytes) is not bytes or not raw_bytes:
        raise PointInTimeDataError("raw_bytes must be a nonempty exact bytes value")
    return _from_material(
        raw_artifact_sha256=_sha256_bytes(raw_bytes),
        source_uri=source_uri,
        content_type=content_type,
        retrieved_at=retrieved_at,
        archive_recorded_at=archive_recorded_at,
        byte_count=len(raw_bytes),
    )


def validate_raw_point_in_time_artifact(value: object) -> RawPointInTimeArtifact:
    """Rebuild a raw artifact receipt from its canonical serialized record."""

    if not isinstance(value, Mapping) or set(value) != _SERIALIZED_FIELDS:
        raise PointInTimeDataError("raw artifact fields are invalid")
    payload = dict(value)
    if payload["schema_version"] != _SCHEMA:
        raise PointInTimeDataError("raw artifact schema is invalid")
    _authority(payload)
    rebuilt = _from_material(
        raw_artifact_sha256=payload["raw_artifact_sha256"],
        source_uri=payload["source_uri"],
        content_type=payload["content_type"],
        retrieved_at=payload["retrieved_at"],
        archive_recorded_at=payload["archive_recorded_at"],
        byte_count=payload["byte_count"],
    )
    if rebuilt.canonical_json_bytes() != _canonical_json_bytes(payload):
        raise PointInTimeDataError("raw artifact bytes do not match canonical rebuild")
    return rebuilt


def _decode_canonical_receipt(raw_bytes: bytes) -> RawPointInTimeArtifact:
    """Decode one receipt without accepting ambiguous or reformatted JSON."""

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PointInTimeDataError(
                    "raw artifact receipt contains a duplicate JSON key"
                )
            result[key] = value
        return result

    def reject_nonfinite_constant(_value: str) -> object:
        raise PointInTimeDataError(
            "raw artifact receipt contains a nonfinite JSON number"
        )

    try:
        payload = json.loads(
            raw_bytes,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_constant,
        )
    except PointInTimeDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointInTimeDataError("raw artifact receipt cannot be read") from exc
    persisted = validate_raw_point_in_time_artifact(payload)
    if raw_bytes != persisted.canonical_json_bytes():
        raise PointInTimeDataError(
            "raw artifact receipt bytes are not exact canonical JSON"
        )
    return persisted


class RawPointInTimeArtifactArchive:
    """Write-once local archive of raw source bytes and canonical receipts."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().absolute()
        if clock is not None and not callable(clock):
            raise PointInTimeDataError("archive clock must be callable")
        self._clock = _exact_utc_now if clock is None else clock

    @property
    def _objects_root(self) -> Path:
        return self.root / "objects"

    def admit(
        self,
        *,
        raw_bytes: bytes,
        source_uri: str,
        content_type: str,
        retrieved_at: str,
    ) -> RawPointInTimeArtifact:
        """Persist exact bytes once, or verify the identical prior object."""

        artifact = build_raw_point_in_time_artifact(
            raw_bytes=raw_bytes,
            source_uri=source_uri,
            content_type=content_type,
            retrieved_at=retrieved_at,
            archive_recorded_at=_clock_timestamp(self._clock()),
        )
        self._ensure_directories()
        raw_path, receipt_path = self._paths(artifact)
        if self._write_or_verify(raw_path, raw_bytes):
            self._fsync_directory(self._objects_root)
        if self._write_or_verify(receipt_path, artifact.canonical_json_bytes()):
            self._fsync_directory(self._objects_root)
        return self.read_receipt(artifact)

    def read_receipt(self, artifact: RawPointInTimeArtifact) -> RawPointInTimeArtifact:
        """Verify a stored receipt and its raw bytes before returning it."""

        if type(artifact) is not RawPointInTimeArtifact:
            raise PointInTimeDataError("artifact must be an exact RawPointInTimeArtifact")
        rebuilt = validate_raw_point_in_time_artifact(artifact.to_dict())
        raw_path, receipt_path = self._paths(rebuilt)
        persisted = _decode_canonical_receipt(self._read_regular(receipt_path))
        if persisted.canonical_json_bytes() != rebuilt.canonical_json_bytes():
            raise PointInTimeDataError("raw artifact receipt does not match requested record")
        raw_bytes = self._read_regular(raw_path)
        if (
            len(raw_bytes) != persisted.byte_count
            or _sha256_bytes(raw_bytes) != persisted.raw_artifact_sha256
        ):
            raise PointInTimeDataError("raw artifact bytes do not match immutable receipt")
        return persisted

    def read_bytes(self, artifact: RawPointInTimeArtifact) -> bytes:
        """Return exact source bytes only after receipt and digest verification."""

        persisted = self.read_receipt(artifact)
        raw_path, _receipt_path = self._paths(persisted)
        raw_bytes = self._read_regular(raw_path)
        if (
            len(raw_bytes) != persisted.byte_count
            or _sha256_bytes(raw_bytes) != persisted.raw_artifact_sha256
        ):
            raise PointInTimeDataError("raw artifact bytes do not match immutable receipt")
        return raw_bytes

    def read_artifact(self, raw_artifact_id: str) -> RawPointInTimeArtifact:
        """Load one retained artifact by its exact immutable identity."""

        if type(raw_artifact_id) is not str or _RAW_ARTIFACT_ID.fullmatch(raw_artifact_id) is None:
            raise PointInTimeDataError("raw artifact identity is invalid")
        receipt_path = self._objects_root / f"{raw_artifact_id}.json"
        artifact = _decode_canonical_receipt(self._read_regular(receipt_path))
        if artifact.raw_artifact_id != raw_artifact_id:
            raise PointInTimeDataError("raw artifact receipt identity does not match path")
        return self.read_receipt(artifact)

    def _paths(self, artifact: RawPointInTimeArtifact) -> tuple[Path, Path]:
        return (
            self._objects_root / f"{artifact.raw_artifact_id}.raw",
            self._objects_root / f"{artifact.raw_artifact_id}.json",
        )

    def _ensure_directories(self) -> None:
        created: list[Path] = []
        for path in (self.root, self._objects_root):
            try:
                existed = path.exists()
                path.mkdir(mode=0o700, parents=path == self.root, exist_ok=True)
                mode = os.lstat(path).st_mode
            except OSError as exc:
                raise PointInTimeDataError("raw artifact archive cannot create directory") from exc
            if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                raise PointInTimeDataError("raw artifact archive directory is unsafe")
            if not existed:
                created.append(path)
        for path in created:
            self._fsync_directory(path.parent)

    def _write_or_verify(self, path: Path, data: bytes) -> bool:
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            if self._read_regular(path) != data:
                raise PointInTimeDataError(
                    "immutable raw artifact path already differs"
                ) from exc
            return False
        except OSError as exc:
            raise PointInTimeDataError("raw artifact archive cannot write object") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            with suppress(OSError):
                path.unlink(missing_ok=True)
            raise
        return True

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise PointInTimeDataError("raw artifact archive cannot sync directory") from exc

    @staticmethod
    def _read_regular(path: Path) -> bytes:
        try:
            state = os.lstat(path)
            if not stat.S_ISREG(state.st_mode) or stat.S_ISLNK(state.st_mode):
                raise PointInTimeDataError("raw artifact path is not a regular file")
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
            with os.fdopen(descriptor, "rb") as handle:
                return handle.read()
        except PointInTimeDataError:
            raise
        except OSError as exc:
            raise PointInTimeDataError("raw artifact path cannot be read") from exc
