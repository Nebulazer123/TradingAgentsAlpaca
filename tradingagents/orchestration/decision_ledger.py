"""Crash-safe canonical journal for immutable analysis-only work packets."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingagents.orchestration.work_packets import (
    ALLOWED_PACKET_KINDS,
    WorkPacket,
    build_packet_id,
    validate_work_packet,
)
from tradingagents.policy.io import atomic_write_text

DECISION_LEDGER_SCHEMA_VERSION = 1

_UTC = dt.timezone.utc
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "sequence",
        "packet_id",
        "kind",
        "packet_sha256",
        "created_at",
        "run_id",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }
)
_AUTHORITY_FIELDS = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class DecisionLedgerError(ValueError):
    """Base class for decision-ledger contract failures."""


class PacketCollisionError(DecisionLedgerError):
    """An immutable packet ID already names different canonical bytes."""


class LedgerCorruptionError(DecisionLedgerError):
    """Stored ledger authority evidence is malformed or inconsistent."""


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _stored_utc(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    normalized = parsed.astimezone(_UTC)
    if normalized.microsecond != 0:
        return None
    if normalized.isoformat(timespec="seconds") != value:
        return None
    return normalized


@dataclass(frozen=True)
class LedgerEvent:
    schema_version: int
    sequence: int
    packet_id: str
    kind: str
    packet_sha256: str
    created_at: str
    run_id: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LedgerEvent:
        if not isinstance(payload, Mapping):
            raise LedgerCorruptionError("ledger event must be an object")
        raw_keys = tuple(payload)
        if not all(isinstance(key, str) for key in raw_keys):
            raise LedgerCorruptionError("ledger event field names must be strings")
        keys = set(raw_keys)
        missing = sorted(_EVENT_FIELDS - keys)
        unknown = sorted(keys - _EVENT_FIELDS)
        if missing or unknown:
            details = []
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown fields: {', '.join(unknown)}")
            raise LedgerCorruptionError("; ".join(details))
        if payload["analysis_only"] is not True:
            raise LedgerCorruptionError("analysis_only must be true")
        if payload["execution_authority"] != "none":
            raise LedgerCorruptionError("execution_authority must be none")
        if payload["can_submit_orders"] is not False:
            raise LedgerCorruptionError("can_submit_orders must be false")
        if type(payload["schema_version"]) is not int or (
            payload["schema_version"] != DECISION_LEDGER_SCHEMA_VERSION
        ):
            raise LedgerCorruptionError("schema_version must equal 1")
        if type(payload["sequence"]) is not int or payload["sequence"] < 1:
            raise LedgerCorruptionError("sequence must be a positive integer")

        string_fields = (
            "packet_id",
            "kind",
            "packet_sha256",
            "created_at",
            "run_id",
        )
        for field in string_fields:
            value = payload[field]
            if not isinstance(value, str) or not value or value.strip() != value:
                raise LedgerCorruptionError(
                    f"{field} must be a nonempty canonical string"
                )
        if payload["kind"] not in ALLOWED_PACKET_KINDS:
            raise LedgerCorruptionError("ledger event kind is not allowed")
        if _LOWER_SHA256.fullmatch(payload["packet_sha256"]) is None:
            raise LedgerCorruptionError(
                "packet_sha256 must be a lowercase SHA-256 digest"
            )
        if _stored_utc(payload["created_at"]) is None:
            raise LedgerCorruptionError(
                "created_at must be UTC ISO-8601 seconds"
            )
        try:
            expected_id = build_packet_id(payload["run_id"], payload["kind"])
        except ValueError as exc:
            raise LedgerCorruptionError(
                "ledger event run_id or kind is invalid"
            ) from exc
        if payload["packet_id"] != expected_id:
            raise LedgerCorruptionError(
                "ledger event packet_id does not match run_id and kind"
            )
        return cls(
            schema_version=payload["schema_version"],
            sequence=payload["sequence"],
            packet_id=payload["packet_id"],
            kind=payload["kind"],
            packet_sha256=payload["packet_sha256"],
            created_at=payload["created_at"],
            run_id=payload["run_id"],
        )

    def compact(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "packet_id": self.packet_id,
            "kind": self.kind,
            "packet_sha256": self.packet_sha256,
            "created_at": self.created_at,
            "run_id": self.run_id,
            **_AUTHORITY_FIELDS,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json(self.compact())


class DecisionLedger:
    """Persist and replay immutable work packets under one exclusive lock."""

    def __init__(self, root: str | Path):
        lexical_root = Path(
            os.path.abspath(os.fspath(Path(root).expanduser()))
        )
        try:
            lexical_state = lexical_root.lstat()
        except FileNotFoundError:
            lexical_state = None
        except OSError as exc:
            raise LedgerCorruptionError(
                "ledger root could not be inspected"
            ) from exc
        if lexical_state is not None and stat.S_ISLNK(lexical_state.st_mode):
            raise LedgerCorruptionError("ledger root must not be a symlink")
        self.root = lexical_root.resolve()
        self._lock_path = self.root / ".ledger.lock"
        self._events_path = self.root / "events.jsonl"
        self._packets_dir = self.root / "packets"
        self._latest_dir = self.root / "latest"

    def record(
        self,
        packet: WorkPacket,
        *,
        evidence_root: str | Path | None = None,
        now: dt.datetime | None = None,
    ) -> Path:
        issues = validate_work_packet(
            packet,
            now=now,
            evidence_root=evidence_root,
            verify_evidence=True,
        )
        if issues:
            raise ValueError("; ".join(issues))
        packet_bytes = packet.canonical_json_bytes()
        packet_digest = hashlib.sha256(packet_bytes).hexdigest()

        with self._locked():
            self._ensure_managed_directories()
            events = self._replay(evidence_root=evidence_root)
            self._redurable_journal_if_present()
            packet_path = self._packet_path(packet.packet_id)
            object_existed = (
                self._path_state(packet_path, label="packet object") is not None
            )
            if not object_existed:
                self._write_immutable_packet(packet_path, packet_bytes)
                self._after_packet_fsync(packet_path)
            else:
                stored_packet, stored_bytes = self._read_packet_object(
                    packet_path,
                    evidence_root=evidence_root,
                )
                if (
                    stored_packet.packet_id != packet.packet_id
                    or stored_bytes != packet_bytes
                    or hashlib.sha256(stored_bytes).hexdigest() != packet_digest
                ):
                    raise PacketCollisionError(
                        f"packet ID collision: {packet.packet_id}"
                    )

            prior = next(
                (event for event in events if event.packet_id == packet.packet_id),
                None,
            )
            if prior is not None:
                if prior.packet_sha256 != packet_digest:
                    raise PacketCollisionError(
                        f"packet ID collision: {packet.packet_id}"
                    )
                self._repair_latest(events)
                return packet_path

            if object_existed:
                self._redurable_regular_file(
                    packet_path,
                    label="packet object",
                )
                self._fsync_directory(self._packets_dir)

            event = LedgerEvent(
                schema_version=DECISION_LEDGER_SCHEMA_VERSION,
                sequence=len(events) + 1,
                packet_id=packet.packet_id,
                kind=packet.kind,
                packet_sha256=packet_digest,
                created_at=packet.created_at,
                run_id=packet.run_id,
            )
            self._append_event(event)
            self._after_event_fsync(event)
            self._repair_latest((*events, event))
            return packet_path

    def verify(
        self,
        *,
        evidence_root: str | Path | None = None,
    ) -> tuple[LedgerEvent, ...]:
        with self._locked():
            self._ensure_managed_directories()
            events = self._replay(evidence_root=evidence_root)
            self._verify_latest(events)
            return events

    def read_authenticated_packet(
        self,
        packet_id: str,
        *,
        evidence_root: str | Path | None = None,
    ) -> WorkPacket:
        """Return one journal-authenticated immutable packet, or fail closed."""

        if not isinstance(packet_id, str) or not packet_id:
            raise LedgerCorruptionError("packet_id must be a nonempty string")
        with self._locked():
            self._ensure_managed_directories()
            events = self._replay(evidence_root=evidence_root)
            self._verify_latest(events)
            matches = tuple(event for event in events if event.packet_id == packet_id)
            if len(matches) != 1:
                raise LedgerCorruptionError("packet must have exactly one ledger event")
            packet, packet_bytes = self._read_packet_object(
                self._packet_path(packet_id),
                evidence_root=evidence_root,
            )
            if hashlib.sha256(packet_bytes).hexdigest() != matches[0].packet_sha256:
                raise LedgerCorruptionError("authenticated packet digest mismatch")
            return packet

    def rebuild(
        self,
        *,
        evidence_root: str | Path | None = None,
    ) -> tuple[LedgerEvent, ...]:
        with self._locked():
            self._ensure_managed_directories()
            events = self._replay(evidence_root=evidence_root)
            self._redurable_journal_if_present()
            self._repair_latest(events)
            return events

    def _after_packet_fsync(self, packet_path: Path) -> None:
        """Protected deterministic seam after an immutable object is durable."""

    def _after_event_fsync(self, event: LedgerEvent) -> None:
        """Protected deterministic seam after a journal event is durable."""

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_root()
        state = self._path_state(self._lock_path, label="ledger lock")
        if state is not None:
            self._require_regular_state(state, label="ledger lock")
        flags = os.O_CREAT | os.O_RDWR | _NOFOLLOW
        try:
            descriptor = os.open(self._lock_path, flags, 0o600)
        except OSError as exc:
            raise LedgerCorruptionError(
                "ledger lock could not be opened safely"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label="ledger lock")
            if state is None:
                self._fsync_directory(self.root)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _ensure_root(self) -> None:
        state = self._path_state(self.root, label="ledger root")
        if state is None:
            try:
                self.root.mkdir(parents=True)
            except FileExistsError:
                pass
            except OSError as exc:
                raise LedgerCorruptionError(
                    "ledger root could not be created"
                ) from exc
            state = self._path_state(self.root, label="ledger root")
        if state is None or stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(
            state.st_mode
        ):
            raise LedgerCorruptionError(
                "ledger root must be a real directory, not a symlink"
            )

    def _ensure_managed_directories(self) -> None:
        created = False
        for path, label in (
            (self._packets_dir, "packets directory"),
            (self._latest_dir, "latest directory"),
        ):
            state = self._path_state(path, label=label)
            if state is None:
                try:
                    path.mkdir()
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise LedgerCorruptionError(
                        f"{label} could not be created"
                    ) from exc
                state = self._path_state(path, label=label)
                created = True
            self._require_directory_state(state, label=label)
        if created:
            self._fsync_directory(self.root)

    def _path_state(self, path: Path, *, label: str) -> os.stat_result | None:
        self._require_contained(path)
        try:
            return path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LedgerCorruptionError(
                f"{label} could not be inspected"
            ) from exc

    def _require_contained(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise LedgerCorruptionError(
                "managed path escapes ledger root"
            ) from exc

    def _require_directory_state(
        self,
        state: os.stat_result | None,
        *,
        label: str,
    ) -> None:
        if state is None:
            raise LedgerCorruptionError(f"{label} is missing")
        if stat.S_ISLNK(state.st_mode):
            raise LedgerCorruptionError(f"{label} must not be a symlink")
        if not stat.S_ISDIR(state.st_mode):
            raise LedgerCorruptionError(f"{label} must be a directory")

    def _require_regular_state(
        self,
        state: os.stat_result,
        *,
        label: str,
    ) -> None:
        if stat.S_ISLNK(state.st_mode):
            raise LedgerCorruptionError(f"{label} must not be a symlink")
        if not stat.S_ISREG(state.st_mode):
            raise LedgerCorruptionError(f"{label} must be a regular file")

    def _require_regular_descriptor(self, descriptor: int, *, label: str) -> None:
        try:
            state = os.fstat(descriptor)
        except OSError as exc:
            raise LedgerCorruptionError(
                f"{label} descriptor could not be inspected"
            ) from exc
        if not stat.S_ISREG(state.st_mode):
            raise LedgerCorruptionError(
                f"{label} descriptor must reference a regular file"
            )

    def _require_real_directory(self, path: Path, *, label: str) -> None:
        state = self._path_state(path, label=label)
        self._require_directory_state(state, label=label)

    def _fsync_directory(self, path: Path) -> None:
        self._require_real_directory(path, label=f"{path.name} directory")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise LedgerCorruptionError(
                f"directory could not be opened: {path.name}"
            ) from exc
        try:
            try:
                state = os.fstat(descriptor)
            except OSError as exc:
                raise LedgerCorruptionError(
                    f"directory descriptor could not be inspected: {path.name}",
                ) from exc
            if not stat.S_ISDIR(state.st_mode):
                raise LedgerCorruptionError(
                    f"directory descriptor is invalid: {path.name}"
                )
            try:
                os.fsync(descriptor)
            except OSError as exc:
                raise LedgerCorruptionError(
                    f"directory could not be made durable: {path.name}"
                ) from exc
        finally:
            os.close(descriptor)

    def _redurable_regular_file(self, path: Path, *, label: str) -> None:
        state = self._path_state(path, label=label)
        if state is None:
            raise LedgerCorruptionError(f"{label} is missing")
        self._require_regular_state(state, label=label)
        try:
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise LedgerCorruptionError(
                f"{label} could not be reopened safely"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label=label)
            try:
                os.fsync(descriptor)
            except OSError as exc:
                raise LedgerCorruptionError(
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

    def _read_regular(self, path: Path, *, label: str) -> bytes:
        state = self._path_state(path, label=label)
        if state is None:
            raise LedgerCorruptionError(f"{label} is missing")
        self._require_regular_state(state, label=label)
        try:
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise LedgerCorruptionError(
                f"{label} could not be opened safely"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label=label)
            chunks = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        except OSError as exc:
            raise LedgerCorruptionError(f"{label} could not be read") from exc
        finally:
            os.close(descriptor)

    def _packet_path(self, packet_id: str) -> Path:
        path = self._packets_dir / f"{packet_id}.json"
        self._require_contained(path)
        return path

    def _write_immutable_packet(self, path: Path, payload: bytes) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise LedgerCorruptionError(
                "packet object appeared during locked creation"
            ) from exc
        except OSError as exc:
            raise LedgerCorruptionError(
                "packet object could not be created"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label="packet object")
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise OSError("incomplete immutable packet write")
                    offset += written
                os.fsync(descriptor)
            except OSError as exc:
                raise LedgerCorruptionError(
                    "packet object could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)
        self._fsync_directory(self._packets_dir)

    def _read_packet_object(
        self,
        path: Path,
        *,
        evidence_root: str | Path | None,
    ) -> tuple[WorkPacket, bytes]:
        raw = self._read_regular(path, label="packet object")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LedgerCorruptionError(
                "packet object is not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise LedgerCorruptionError("packet object must be a JSON object")
        created_at = _stored_utc(decoded.get("created_at"))
        if created_at is None:
            raise LedgerCorruptionError(
                "packet object created_at is not canonical UTC"
            )
        try:
            packet = WorkPacket.from_dict(decoded, now=created_at)
        except ValueError as exc:
            raise LedgerCorruptionError(
                "packet object schema is invalid"
            ) from exc
        if packet.canonical_json_bytes() != raw:
            raise LedgerCorruptionError("packet object bytes are noncanonical")
        issues = validate_work_packet(
            packet,
            now=created_at,
            evidence_root=evidence_root,
            verify_evidence=True,
        )
        if issues:
            raise LedgerCorruptionError(
                "packet object evidence is invalid: " + "; ".join(issues)
            )
        return packet, raw

    def _replay(
        self,
        *,
        evidence_root: str | Path | None,
    ) -> tuple[LedgerEvent, ...]:
        state = self._path_state(self._events_path, label="event journal")
        if state is None:
            return ()
        raw = self._read_regular(self._events_path, label="event journal")
        if not raw:
            return ()
        if not raw.endswith(b"\n"):
            raise LedgerCorruptionError("event journal has a torn final line")
        lines = raw[:-1].split(b"\n")
        if any(not line for line in lines):
            raise LedgerCorruptionError("event journal contains a blank line")

        events: list[LedgerEvent] = []
        prior_by_packet: dict[str, LedgerEvent] = {}
        for expected_sequence, line in enumerate(lines, start=1):
            try:
                payload = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LedgerCorruptionError(
                    f"event journal line {expected_sequence} is malformed",
                ) from exc
            event = LedgerEvent.from_dict(payload)
            if event.canonical_json_bytes() != line:
                raise LedgerCorruptionError(
                    f"event journal line {expected_sequence} is noncanonical"
                )
            if event.sequence != expected_sequence:
                raise LedgerCorruptionError(
                    f"event sequence gap at {expected_sequence}"
                )
            packet, packet_bytes = self._read_packet_object(
                self._packet_path(event.packet_id),
                evidence_root=evidence_root,
            )
            digest = hashlib.sha256(packet_bytes).hexdigest()
            if digest != event.packet_sha256:
                raise LedgerCorruptionError(
                    f"packet digest mismatch at sequence {event.sequence}"
                )
            if (
                event.packet_id != packet.packet_id
                or event.kind != packet.kind
                or event.created_at != packet.created_at
                or event.run_id != packet.run_id
            ):
                raise LedgerCorruptionError(
                    f"event and packet binding mismatch at sequence {event.sequence}"
                )
            prior = prior_by_packet.get(event.packet_id)
            if prior is not None and self._event_material(prior) != (
                self._event_material(event)
            ):
                raise LedgerCorruptionError(
                    f"conflicting repeated packet event: {event.packet_id}"
                )
            prior_by_packet.setdefault(event.packet_id, event)
            events.append(event)
        return tuple(events)

    def _event_material(self, event: LedgerEvent) -> dict[str, Any]:
        material = event.compact()
        material.pop("sequence")
        return material

    def _append_event(self, event: LedgerEvent) -> None:
        state = self._path_state(self._events_path, label="event journal")
        if state is not None:
            self._require_regular_state(state, label="event journal")
        line = event.canonical_json_bytes() + b"\n"
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | _NOFOLLOW
        try:
            descriptor = os.open(self._events_path, flags, 0o600)
        except OSError as exc:
            raise LedgerCorruptionError(
                "event journal could not be opened safely"
            ) from exc
        try:
            self._require_regular_descriptor(descriptor, label="event journal")
            try:
                if os.write(descriptor, line) != len(line):
                    raise OSError("incomplete decision event append")
                os.fsync(descriptor)
            except OSError as exc:
                raise LedgerCorruptionError(
                    "event journal could not be made durable"
                ) from exc
        finally:
            os.close(descriptor)
        if state is None:
            self._fsync_directory(self.root)

    def _pointer_payload(self, event: LedgerEvent) -> dict[str, Any]:
        return {
            "schema_version": DECISION_LEDGER_SCHEMA_VERSION,
            "sequence": event.sequence,
            "packet_id": event.packet_id,
            "kind": event.kind,
            "packet_sha256": event.packet_sha256,
            "journal_path": "events.jsonl",
            **_AUTHORITY_FIELDS,
        }

    def _pointer_path(self, kind: str) -> Path:
        if kind not in ALLOWED_PACKET_KINDS:
            raise LedgerCorruptionError("latest pointer kind is not allowed")
        path = self._latest_dir / f"{kind}.json"
        self._require_contained(path)
        return path

    def _last_events(
        self,
        events: tuple[LedgerEvent, ...],
    ) -> dict[str, LedgerEvent]:
        latest: dict[str, LedgerEvent] = {}
        for event in events:
            latest[event.kind] = event
        return latest

    def _publish_pointer(self, event: LedgerEvent) -> None:
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        path = self._pointer_path(event.kind)
        state = self._path_state(path, label="latest pointer")
        if state is not None:
            self._require_regular_state(state, label="latest pointer")
        expected = _canonical_json(self._pointer_payload(event))
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        atomic_write_text(path, expected.decode("utf-8"))
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        if self._read_regular(path, label="latest pointer") != expected:
            raise LedgerCorruptionError(
                f"latest pointer publication failed for {event.kind}"
            )

    def _repair_latest(self, events: tuple[LedgerEvent, ...]) -> None:
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        expected = self._last_events(events)
        removed = False
        for kind in sorted(ALLOWED_PACKET_KINDS):
            path = self._pointer_path(kind)
            state = self._path_state(path, label="latest pointer")
            event = expected.get(kind)
            if event is None:
                if state is not None:
                    self._require_regular_state(state, label="latest pointer")
                    try:
                        path.unlink()
                    except OSError as exc:
                        raise LedgerCorruptionError(
                            f"stale latest pointer could not be removed: {kind}",
                        ) from exc
                    removed = True
                continue
            expected_bytes = _canonical_json(self._pointer_payload(event))
            if state is not None:
                current = self._read_regular(path, label="latest pointer")
                if current == expected_bytes:
                    continue
            self._publish_pointer(event)
        if removed:
            self._fsync_directory(self._latest_dir)

    def _verify_latest(self, events: tuple[LedgerEvent, ...]) -> None:
        self._require_real_directory(
            self._latest_dir,
            label="latest directory",
        )
        expected = self._last_events(events)
        for kind in sorted(ALLOWED_PACKET_KINDS):
            path = self._pointer_path(kind)
            state = self._path_state(path, label="latest pointer")
            event = expected.get(kind)
            if event is None:
                if state is not None:
                    raise LedgerCorruptionError(
                        f"unexpected latest pointer for {kind}"
                    )
                continue
            if state is None:
                raise LedgerCorruptionError(
                    f"latest pointer is missing for {kind}"
                )
            actual = self._read_regular(path, label="latest pointer")
            canonical = _canonical_json(self._pointer_payload(event))
            if actual != canonical:
                raise LedgerCorruptionError(
                    f"latest pointer is stale or malformed for {kind}"
                )
        try:
            children = tuple(self._latest_dir.iterdir())
        except OSError as exc:
            raise LedgerCorruptionError(
                "latest directory could not be listed"
            ) from exc
        allowed_names = {
            f"{kind}.json" for kind in ALLOWED_PACKET_KINDS
        }
        for child in children:
            if child.name.endswith(".json") and child.name not in allowed_names:
                raise LedgerCorruptionError(
                    f"unknown latest pointer path: {child.name}"
                )
