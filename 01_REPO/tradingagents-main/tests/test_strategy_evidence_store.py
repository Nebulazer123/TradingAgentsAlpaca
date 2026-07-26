from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import gc
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import tradingagents.strategy._immutable_evidence_store as evidence_store_module
from tradingagents.strategy._immutable_evidence_store import (
    STRATEGY_EVIDENCE_STORE_SCHEMA_VERSION,
    EvidenceBackdatingError,
    EvidenceCandidate,
    EvidenceCollisionError,
    EvidenceCorruptionError,
    EvidenceEnvelope,
    EvidenceEvent,
    EvidencePointer,
    ImmutableStrategyEvidenceStore,
)

UTC = dt.timezone.utc
FIRST = dt.datetime(2030, 1, 2, 15, 4, 5, tzinfo=UTC)
LATER = FIRST + dt.timedelta(seconds=10)
EARLIER = FIRST - dt.timedelta(seconds=1)
ZERO_HASH = "0" * 64
ALLOWED_KINDS = (
    "evaluation-registration",
    "genome-window",
    "promotion-evidence",
    "baseline-genome",
    "mutation-record",
)
ENVELOPE_KEYS = {
    "schema_version",
    "kind",
    "object_id",
    "effective_at",
    "recorded_at",
    "retry_material_sha256",
    "payload_sha256",
    "payload",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
}
EVENT_KEYS = {
    "schema_version",
    "sequence",
    "kind",
    "object_id",
    "object_sha256",
    "retry_material_sha256",
    "effective_at",
    "recorded_at",
    "previous_event_sha256",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
}
POINTER_KEYS = {
    "schema_version",
    "kind",
    "sequence",
    "object_id",
    "object_sha256",
    "event_sha256",
    "recorded_at",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
}


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class _Clock:
    def __init__(self, *values: dt.datetime):
        self._values = list(values)
        self._lock = threading.Lock()

    def __call__(self) -> dt.datetime:
        with self._lock:
            if len(self._values) > 1:
                return self._values.pop(0)
            return self._values[0]


def _candidate(
    *,
    kind: str = "evaluation-registration",
    effective_at: str = "2030-01-02T14:00:00+00:00",
    payload: dict[str, object] | None = None,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        kind=kind,
        effective_at=effective_at,
        payload=payload
        or {
            "registration_key": "NFLX-primary",
            "windows": [
                {"start": "2029-01-01", "end": "2029-03-31"},
                {"start": "2029-04-01", "end": "2029-06-30"},
            ],
            "enabled": True,
            "attempt": 1,
            "note": None,
        },
    )


def _admit(
    tmp_path: Path,
    *,
    candidate: EvidenceCandidate | None = None,
    clock: _Clock | None = None,
) -> tuple[
    ImmutableStrategyEvidenceStore,
    Path,
    EvidenceCandidate,
    object,
]:
    root = tmp_path / "evidence"
    selected = candidate or _candidate()
    store = ImmutableStrategyEvidenceStore(root, clock=clock or _Clock(FIRST))
    admission = store.admit_checked(selected, validate=lambda _prior, _new: None)
    return store, root, selected, admission


def _journal_lines(root: Path) -> list[bytes]:
    return (root / "events.jsonl").read_bytes().splitlines()


def _event_dict(root: Path, index: int = 0) -> dict[str, object]:
    return json.loads(_journal_lines(root)[index])


def _pointer_dict(
    root: Path,
    kind: str = "evaluation-registration",
) -> dict[str, object]:
    return json.loads((root / "latest" / f"{kind}.json").read_bytes())


def _rewrite_event(root: Path, payload: dict[str, object]) -> None:
    (root / "events.jsonl").write_bytes(_canonical(payload) + b"\n")


def _tree_snapshot(root: Path) -> dict[str, tuple[bytes, int, int]]:
    snapshot: dict[str, tuple[bytes, int, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            state = path.stat()
            snapshot[str(path.relative_to(root))] = (
                path.read_bytes(),
                state.st_mtime_ns,
                state.st_size,
            )
    return snapshot


def test_candidate_deep_freezes_nested_payload_and_authority():
    source = {
        "items": [{"name": "alpha", "flags": [True, False]}],
        "nothing": None,
    }
    candidate = _candidate(payload=source)
    source["items"][0]["name"] = "changed"  # type: ignore[index]
    source["items"].append({"name": "late"})  # type: ignore[union-attr]

    assert candidate.payload["items"][0]["name"] == "alpha"  # type: ignore[index]
    assert candidate.payload["items"][0]["flags"] == (True, False)  # type: ignore[index]
    assert candidate.analysis_only is True
    assert candidate.execution_authority == "none"
    assert candidate.can_submit_orders is False
    with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
        candidate.kind = "mutation-record"  # type: ignore[misc]
    with pytest.raises(TypeError):
        candidate.payload["extra"] = "forbidden"  # type: ignore[index]


def test_admit_writes_exact_canonical_object_event_pointer_layout(tmp_path):
    store, root, candidate, admission = _admit(tmp_path)
    envelope = admission.envelope
    event = admission.event

    retry_material = {
        "kind": candidate.kind,
        "effective_at": candidate.effective_at,
        "payload": {
            "attempt": 1,
            "enabled": True,
            "note": None,
            "registration_key": "NFLX-primary",
            "windows": [
                {"end": "2029-03-31", "start": "2029-01-01"},
                {"end": "2029-06-30", "start": "2029-04-01"},
            ],
        },
    }
    retry_digest = hashlib.sha256(_canonical(retry_material)).hexdigest()
    expected_id = f"evaluation-registration-{retry_digest}"
    payload_digest = hashlib.sha256(
        _canonical(retry_material["payload"])
    ).hexdigest()

    assert STRATEGY_EVIDENCE_STORE_SCHEMA_VERSION == 1
    assert admission.created is True
    assert admission.path == (
        root / "objects" / candidate.kind / f"{expected_id}.json"
    )
    assert envelope.to_dict() == {
        "schema_version": 1,
        "kind": candidate.kind,
        "object_id": expected_id,
        "effective_at": candidate.effective_at,
        "recorded_at": "2030-01-02T15:04:05+00:00",
        "retry_material_sha256": retry_digest,
        "payload_sha256": payload_digest,
        "payload": retry_material["payload"],
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    assert set(envelope.to_dict()) == ENVELOPE_KEYS
    assert admission.path.read_bytes() == envelope.canonical_json_bytes()
    assert not admission.path.read_bytes().endswith(b"\n")
    assert EvidenceEnvelope.from_dict(envelope.to_dict()) == envelope

    object_digest = hashlib.sha256(envelope.canonical_json_bytes()).hexdigest()
    assert event.to_dict() == {
        "schema_version": 1,
        "sequence": 1,
        "kind": candidate.kind,
        "object_id": expected_id,
        "object_sha256": object_digest,
        "retry_material_sha256": retry_digest,
        "effective_at": candidate.effective_at,
        "recorded_at": envelope.recorded_at,
        "previous_event_sha256": ZERO_HASH,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    assert set(event.to_dict()) == EVENT_KEYS
    assert EvidenceEvent.from_dict(event.to_dict()) == event
    assert (root / "events.jsonl").read_bytes() == (
        event.canonical_json_bytes() + b"\n"
    )

    pointer = EvidencePointer.from_dict(_pointer_dict(root))
    assert pointer.to_dict() == {
        "schema_version": 1,
        "kind": candidate.kind,
        "sequence": 1,
        "object_id": expected_id,
        "object_sha256": object_digest,
        "event_sha256": hashlib.sha256(
            event.canonical_json_bytes()
        ).hexdigest(),
        "recorded_at": envelope.recorded_at,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    assert set(pointer.to_dict()) == POINTER_KEYS
    assert (root / "latest" / f"{candidate.kind}.json").read_bytes() == (
        pointer.canonical_json_bytes()
    )
    assert store.verify() == (envelope,)
    assert store.envelopes() == (envelope,)
    assert store.envelopes(kind=candidate.kind) == (envelope,)
    assert store.envelopes(kind="mutation-record") == ()

    for path in (
        root / ".strategy-evidence.lock",
        root / "events.jsonl",
        admission.path,
        root / "latest" / f"{candidate.kind}.json",
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        ("envelope", "schema_version", True),
        ("envelope", "analysis_only", False),
        ("envelope", "execution_authority", "live"),
        ("envelope", "can_submit_orders", True),
        ("envelope", "payload_sha256", "A" * 64),
        ("event", "sequence", 0),
        ("event", "previous_event_sha256", "A" * 64),
        ("event", "analysis_only", False),
        ("pointer", "sequence", True),
        ("pointer", "event_sha256", "bad"),
        ("pointer", "can_submit_orders", True),
    ],
)
def test_frozen_models_reject_bad_schema_or_authority(
    tmp_path,
    model,
    field,
    value,
):
    _, root, _, admission = _admit(tmp_path)
    if model == "envelope":
        parser = EvidenceEnvelope.from_dict
        payload = admission.envelope.to_dict()
    elif model == "event":
        parser = EvidenceEvent.from_dict
        payload = _event_dict(root)
    else:
        parser = EvidencePointer.from_dict
        payload = _pointer_dict(root)
    payload[field] = value

    with pytest.raises(ValueError):
        parser(payload)


@pytest.mark.parametrize("model", ["envelope", "event", "pointer"])
def test_frozen_models_reject_unknown_and_missing_fields(tmp_path, model):
    _, root, _, admission = _admit(tmp_path)
    if model == "envelope":
        parser = EvidenceEnvelope.from_dict
        payload = admission.envelope.to_dict()
    elif model == "event":
        parser = EvidenceEvent.from_dict
        payload = _event_dict(root)
    else:
        parser = EvidencePointer.from_dict
        payload = _pointer_dict(root)

    unknown = dict(payload, live=True)
    with pytest.raises(ValueError):
        parser(unknown)
    missing = dict(payload)
    missing.pop(next(iter(payload)))
    with pytest.raises(ValueError):
        parser(missing)


def test_second_event_binds_immediately_prior_event_hash(tmp_path):
    store, root, _, first = _admit(tmp_path)
    second_candidate = _candidate(
        kind="baseline-genome",
        payload={"genome_id": "g-1", "generation": 0},
    )
    second = store.admit_checked(
        second_candidate,
        validate=lambda _prior, _new: None,
    )

    assert second.event.sequence == 2
    assert second.event.previous_event_sha256 == hashlib.sha256(
        first.event.canonical_json_bytes()
    ).hexdigest()
    assert store.verify() == (first.envelope, second.envelope)


def test_exact_and_later_retry_are_event_silent_and_keep_first_seen_time(tmp_path):
    root = tmp_path / "evidence"
    clock = _Clock(FIRST, LATER)
    store = ImmutableStrategyEvidenceStore(root, clock=clock)
    candidate = _candidate()

    first = store.admit_checked(candidate, validate=lambda _prior, _new: None)
    second = store.admit_checked(candidate, validate=lambda _prior, _new: None)

    assert first.created is True
    assert second.created is False
    assert second.envelope == first.envelope
    assert second.event == first.event
    assert second.envelope.recorded_at == "2030-01-02T15:04:05+00:00"
    assert len(_journal_lines(root)) == 1


def test_retry_with_clock_before_stored_first_seen_fails_without_mutation(tmp_path):
    store, root, candidate, _ = _admit(tmp_path)
    before = _tree_snapshot(root)
    earlier_store = ImmutableStrategyEvidenceStore(root, clock=_Clock(EARLIER))

    with pytest.raises(EvidenceBackdatingError):
        earlier_store.admit_checked(
            candidate,
            validate=lambda _prior, _new: None,
        )

    assert _tree_snapshot(root) == before
    assert store.verify()


def test_changed_material_gets_distinct_identity(tmp_path):
    store, _, _, first = _admit(tmp_path)
    changed = _candidate(payload={"registration_key": "NFLX-secondary"})
    second = store.admit_checked(changed, validate=lambda _prior, _new: None)

    assert second.envelope.object_id != first.envelope.object_id
    assert second.envelope.retry_material_sha256 != (
        first.envelope.retry_material_sha256
    )


def test_existing_object_path_with_different_bytes_is_a_collision(tmp_path):
    root = tmp_path / "evidence"
    candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))
    with pytest.raises(RuntimeError):
        crashing.admit_checked(candidate, validate=lambda _prior, _new: None)
    object_path = next((root / "objects").rglob("*.json"))
    object_path.write_bytes(b"{}")

    with pytest.raises(EvidenceCollisionError):
        ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER)).admit_checked(
            candidate,
            validate=lambda _prior, _new: None,
        )

    assert not (root / "events.jsonl").exists()


def test_concurrent_identical_admissions_create_one_object_and_event(tmp_path):
    root = tmp_path / "evidence"
    candidate = _candidate()

    def worker(_index: int):
        store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))
        return store.admit_checked(
            candidate,
            validate=lambda _prior, _new: None,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        admissions = list(pool.map(worker, range(24)))

    assert sum(admission.created for admission in admissions) == 1
    assert len({item.envelope.object_id for item in admissions}) == 1
    assert len(_journal_lines(root)) == 1
    assert len(tuple((root / "objects").rglob("*.json"))) == 1
    assert len(ImmutableStrategyEvidenceStore(root).verify()) == 1


def test_validator_race_on_one_logical_slot_commits_only_one_candidate(tmp_path):
    root = tmp_path / "evidence"
    candidates = (
        _candidate(payload={"slot": "NFLX-primary", "choice": "alpha"}),
        _candidate(payload={"slot": "NFLX-primary", "choice": "beta"}),
    )

    def validate(
        prior: tuple[EvidenceEnvelope, ...],
        new: EvidenceEnvelope,
    ) -> None:
        if any(
            envelope.payload.get("slot") == new.payload.get("slot")
            for envelope in prior
        ):
            raise ValueError("logical slot is already occupied")

    def worker(candidate: EvidenceCandidate):
        store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))
        try:
            return store.admit_checked(candidate, validate=validate)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, candidates))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, ValueError) for item in outcomes) == 1
    assert len(_journal_lines(root)) == 1
    assert len(ImmutableStrategyEvidenceStore(root).verify()) == 1


class _CrashAfterObject(ImmutableStrategyEvidenceStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._crash = True

    def _after_object_fsync(self, _path: Path) -> None:
        if self._crash:
            self._crash = False
            raise RuntimeError("crash after object fsync")


class _CrashAfterEvent(ImmutableStrategyEvidenceStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._crash = True

    def _after_event_fsync(self, _event: EvidenceEvent) -> None:
        if self._crash:
            self._crash = False
            raise RuntimeError("crash after event fsync")


def test_crash_after_object_fsync_leaves_adoptable_orphan_with_original_time(
    tmp_path,
):
    root = tmp_path / "evidence"
    candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))

    with pytest.raises(RuntimeError, match="object fsync"):
        crashing.admit_checked(candidate, validate=lambda _prior, _new: None)

    objects = tuple((root / "objects").rglob("*.json"))
    assert len(objects) == 1
    assert not (root / "events.jsonl").exists()
    assert not tuple((root / "latest").glob("*.json"))

    repaired = ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER))
    admission = repaired.admit_checked(
        candidate,
        validate=lambda _prior, _new: None,
    )
    assert admission.created is True
    assert admission.envelope.recorded_at == "2030-01-02T15:04:05+00:00"
    assert len(_journal_lines(root)) == 1
    assert repaired.verify() == (admission.envelope,)


def test_validate_orphans_receives_only_strict_orphans_and_exact_candidate_under_lock(
    tmp_path,
):
    # Break caught: orphan validation sees malformed objects or runs outside the lock.
    root = tmp_path / "evidence"
    candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))
    with pytest.raises(RuntimeError, match="object fsync"):
        crashing.admit_checked(
            candidate,
            validate=lambda _prior, _new: None,
        )
    expected_orphan = EvidenceEnvelope.from_dict(
        json.loads(next((root / "objects").rglob("*.json")).read_bytes())
    )
    malformed_dir = root / "objects" / "baseline-genome"
    malformed_dir.mkdir()
    malformed_path = malformed_dir / f"baseline-genome-{'f' * 64}.json"
    malformed_path.write_bytes(b"{}")
    malformed_path.chmod(0o600)

    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER))
    observed: list[
        tuple[
            tuple[EvidenceEnvelope, ...],
            EvidenceEnvelope,
        ]
    ] = []

    def validate(
        admitted: tuple[EvidenceEnvelope, ...],
        new: EvidenceEnvelope,
    ) -> None:
        assert admitted == ()
        assert new == expected_orphan

    def validate_orphans(
        orphans: tuple[EvidenceEnvelope, ...],
        new: EvidenceEnvelope,
    ) -> None:
        process_lock = store._process_root_lock()
        assert process_lock.acquire(blocking=False) is False
        assert store._transaction().root_fd >= 0
        observed.append((orphans, new))

    admission = store.admit_checked(
        candidate,
        validate=validate,
        validate_orphans=validate_orphans,
    )

    assert observed == [((expected_orphan,), expected_orphan)]
    assert admission.envelope == expected_orphan
    assert store.verify() == (expected_orphan,)
    assert malformed_path.read_bytes() == b"{}"


def test_validate_orphans_rejection_precedes_candidate_object_event_and_pointer(
    tmp_path,
):
    # Break caught: a rejected orphan conflict leaves partial candidate durability.
    root = tmp_path / "evidence"
    orphan_candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))
    with pytest.raises(RuntimeError, match="object fsync"):
        crashing.admit_checked(
            orphan_candidate,
            validate=lambda _prior, _new: None,
        )
    before = _tree_snapshot(root)
    changed = _candidate(
        payload={"slot": "same-logical-slot", "choice": "changed"},
    )

    def reject(
        orphans: tuple[EvidenceEnvelope, ...],
        _new: EvidenceEnvelope,
    ) -> None:
        assert len(orphans) == 1
        raise ValueError("orphan slot conflict")

    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER))
    with pytest.raises(ValueError, match="orphan slot conflict"):
        store.admit_checked(
            changed,
            validate=lambda admitted, _new: admitted == (),
            validate_orphans=reject,
        )

    assert _tree_snapshot(root) == before
    assert not (root / "events.jsonl").exists()
    assert not tuple((root / "latest").glob("*.json"))


def test_validate_orphans_exception_cleans_up_and_omitted_callback_stays_compatible(
    tmp_path,
):
    # Break caught: an orphan callback exception wedges validation or adoption.
    root = tmp_path / "evidence"
    candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))
    with pytest.raises(RuntimeError, match="object fsync"):
        crashing.admit_checked(
            candidate,
            validate=lambda _prior, _new: None,
        )
    store = ImmutableStrategyEvidenceStore(
        root,
        clock=_Clock(LATER, LATER),
    )

    with pytest.raises(RuntimeError, match="orphan callback failed"):
        store.admit_checked(
            candidate,
            validate=lambda _prior, _new: None,
            validate_orphans=lambda _orphans, _new: (_ for _ in ()).throw(
                RuntimeError("orphan callback failed")
            ),
        )

    assert not hasattr(evidence_store_module._VALIDATOR_ACTIVITY, "depth")
    admission = store.admit_checked(
        candidate,
        validate=lambda _prior, _new: None,
    )
    assert admission.created is True
    assert store.verify() == (admission.envelope,)


def test_valid_unrelated_orphan_blocks_backdated_admission_without_journaling(
    tmp_path,
):
    root = tmp_path / "evidence"
    orphan_candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))
    with pytest.raises(RuntimeError, match="object fsync"):
        crashing.admit_checked(
            orphan_candidate,
            validate=lambda _prior, _new: None,
        )
    before = _tree_snapshot(root)
    different_candidate = _candidate(
        kind="baseline-genome",
        payload={"genome_id": "g-1", "generation": 0},
    )

    with pytest.raises(EvidenceBackdatingError):
        ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(EARLIER),
        ).admit_checked(
            different_candidate,
            validate=lambda _prior, _new: None,
        )

    assert _tree_snapshot(root) == before
    assert not (root / "events.jsonl").exists()
    assert ImmutableStrategyEvidenceStore(root).verify() == ()


def test_malformed_unrelated_orphan_cannot_forge_backdating_watermark(
    tmp_path,
):
    root = tmp_path / "evidence"
    orphan_candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))
    with pytest.raises(RuntimeError, match="object fsync"):
        crashing.admit_checked(
            orphan_candidate,
            validate=lambda _prior, _new: None,
        )
    orphan_path = next((root / "objects").rglob("*.json"))
    malformed = json.loads(orphan_path.read_bytes())
    malformed["recorded_at"] = "2099-01-01T00:00:00+00:00"
    malformed["payload_sha256"] = "f" * 64
    orphan_path.write_bytes(_canonical(malformed))
    different_candidate = _candidate(
        kind="baseline-genome",
        payload={"genome_id": "g-1", "generation": 0},
    )
    observed_snapshots: list[tuple[EvidenceEnvelope, ...]] = []

    admission = ImmutableStrategyEvidenceStore(
        root,
        clock=_Clock(EARLIER),
    ).admit_checked(
        different_candidate,
        validate=lambda prior, _new: observed_snapshots.append(prior),
    )

    assert admission.created is True
    assert admission.envelope.recorded_at == "2030-01-02T15:04:04+00:00"
    assert observed_snapshots == [()]
    assert ImmutableStrategyEvidenceStore(root).verify() == (
        admission.envelope,
    )
    with pytest.raises(EvidenceCollisionError):
        ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(LATER),
        ).admit_checked(
            orphan_candidate,
            validate=lambda _prior, _new: None,
        )


def test_crash_after_event_fsync_retry_is_event_silent_and_repairs_pointer(
    tmp_path,
):
    root = tmp_path / "evidence"
    candidate = _candidate()
    crashing = _CrashAfterEvent(root, clock=_Clock(FIRST))

    with pytest.raises(RuntimeError, match="event fsync"):
        crashing.admit_checked(candidate, validate=lambda _prior, _new: None)

    assert len(_journal_lines(root)) == 1
    assert not (root / "latest" / f"{candidate.kind}.json").exists()
    with pytest.raises(EvidenceCorruptionError, match="pointer"):
        ImmutableStrategyEvidenceStore(root).verify()

    repaired = ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER))
    admission = repaired.admit_checked(
        candidate,
        validate=lambda _prior, _new: None,
    )
    assert admission.created is False
    assert len(_journal_lines(root)) == 1
    assert repaired.verify() == (admission.envelope,)


@pytest.mark.parametrize("recovery", ["retry", "rebuild"])
def test_recovery_redurabilizes_visible_event_before_pointer_after_fsync_error(
    tmp_path,
    monkeypatch,
    recovery,
):
    root = tmp_path / "evidence"
    candidate = _candidate()
    journal_inode: list[int] = []
    fail_journal_fsync = True
    operations: list[str] = []
    real_write = evidence_store_module.os.write
    real_fsync = evidence_store_module.os.fsync

    def recording_write(descriptor: int, payload: bytes) -> int:
        written = real_write(descriptor, payload)
        if (
            payload.endswith(b"\n")
            and b'"previous_event_sha256"' in payload
        ):
            inode = os.fstat(descriptor).st_ino
            journal_inode[:] = [inode]
            operations.append("journal-write")
        elif b'"event_sha256"' in payload:
            operations.append("pointer-write")
        return written

    def failing_once_fsync(descriptor: int) -> None:
        nonlocal fail_journal_fsync
        state = os.fstat(descriptor)
        if journal_inode and state.st_ino == journal_inode[0]:
            if fail_journal_fsync:
                fail_journal_fsync = False
                operations.append("journal-fsync-error")
                raise OSError("injected journal fsync failure")
            operations.append("journal-fsync")
        elif stat.S_ISDIR(state.st_mode) and root.exists():
            if state.st_ino == root.stat().st_ino:
                operations.append("root-fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(evidence_store_module.os, "write", recording_write)
    monkeypatch.setattr(evidence_store_module.os, "fsync", failing_once_fsync)
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))

    with pytest.raises(
        EvidenceCorruptionError,
        match="event journal could not be made durable",
    ):
        store.admit_checked(candidate, validate=lambda _prior, _new: None)

    assert len(_journal_lines(root)) == 1
    assert not tuple((root / "latest").glob("*.json"))
    operations.clear()

    if recovery == "retry":
        admission = ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(LATER),
        ).admit_checked(candidate, validate=lambda _prior, _new: None)
        assert admission.created is False
        expected = (admission.envelope,)
    else:
        expected = store.rebuild()

    assert operations.index("journal-fsync") < operations.index("root-fsync")
    assert operations.index("root-fsync") < operations.index("pointer-write")
    assert len(_journal_lines(root)) == 1
    assert ImmutableStrategyEvidenceStore(root).verify() == expected


@pytest.mark.parametrize("recovery", ["retry", "rebuild"])
def test_process_crash_with_fsynced_staged_pointer_is_recoverable(
    tmp_path,
    recovery,
):
    root = tmp_path / "evidence"
    candidate = _candidate(
        payload={"registration_key": "NFLX-staged-pointer-crash"},
    )
    script = """
import datetime as dt
import os
import sys
from pathlib import Path

import tradingagents.strategy._immutable_evidence_store as evidence_store_module
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
)

root = Path(sys.argv[1])
candidate = EvidenceCandidate(
    kind="evaluation-registration",
    effective_at="2030-01-02T14:00:00+00:00",
    payload={"registration_key": "NFLX-staged-pointer-crash"},
)
real_replace = evidence_store_module.os.replace

def crash_before_pointer_replace(
    source,
    destination,
    *,
    src_dir_fd=None,
    dst_dir_fd=None,
):
    source_name = os.fspath(source)
    if (
        source_name.startswith(".evaluation-registration.")
        and source_name.endswith(".tmp")
        and src_dir_fd is not None
        and dst_dir_fd == src_dir_fd
    ):
        os._exit(73)
    real_replace(
        source,
        destination,
        src_dir_fd=src_dir_fd,
        dst_dir_fd=dst_dir_fd,
    )

evidence_store_module.os.replace = crash_before_pointer_replace
store = ImmutableStrategyEvidenceStore(
    root,
    clock=lambda: dt.datetime(
        2030,
        1,
        2,
        15,
        4,
        5,
        tzinfo=dt.timezone.utc,
    ),
)
store.admit_checked(candidate, validate=lambda _prior, _new: None)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(root)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 73, result.stderr
    staged = tuple((root / "latest").glob(".*.tmp"))
    assert len(staged) == 1
    staged_state = staged[0].lstat()
    assert stat.S_ISREG(staged_state.st_mode)
    assert stat.S_IMODE(staged_state.st_mode) == 0o600
    assert staged_state.st_nlink == 1
    assert len(_journal_lines(root)) == 1
    assert not (root / "latest" / f"{candidate.kind}.json").exists()
    before_verify = _tree_snapshot(root)

    with pytest.raises(EvidenceCorruptionError, match="latest pointer"):
        ImmutableStrategyEvidenceStore(root).verify()

    assert _tree_snapshot(root) == before_verify
    if recovery == "retry":
        admission = ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(LATER),
        ).admit_checked(candidate, validate=lambda _prior, _new: None)
        assert admission.created is False
        expected = (admission.envelope,)
    else:
        expected = ImmutableStrategyEvidenceStore(root).rebuild()

    assert not tuple((root / "latest").glob(".*.tmp"))
    assert ImmutableStrategyEvidenceStore(root).verify() == expected
    assert len(_journal_lines(root)) == 1


@pytest.mark.parametrize("recovery", ["retry", "rebuild"])
@pytest.mark.parametrize(
    "mutation",
    [
        "arbitrary",
        "malformed",
        "disallowed_kind",
        "symlink",
        "hardlink",
        "directory",
        "unsafe_mode",
    ],
)
def test_recovery_rejects_unowned_or_unsafe_staged_pointer_entries(
    tmp_path,
    recovery,
    mutation,
):
    store, root, candidate, _ = _admit(tmp_path)
    safe_name = ".evaluation-registration.1.2.3.tmp"
    if mutation == "arbitrary":
        staged = root / "latest" / ".unrelated.tmp"
        staged.write_bytes(b"unrelated")
    elif mutation == "malformed":
        staged = root / "latest" / ".evaluation-registration.1.2.bad.tmp"
        staged.write_bytes(b"malformed")
    elif mutation == "disallowed_kind":
        staged = root / "latest" / ".not-allowed.1.2.3.tmp"
        staged.write_bytes(b"disallowed")
    elif mutation == "symlink":
        target = tmp_path / "outside-symlink-target"
        target.write_bytes(b"outside")
        staged = root / "latest" / safe_name
        staged.symlink_to(target)
    elif mutation == "hardlink":
        target = tmp_path / "outside-hardlink-target"
        target.write_bytes(b"outside")
        target.chmod(0o600)
        staged = root / "latest" / safe_name
        os.link(target, staged)
    elif mutation == "directory":
        staged = root / "latest" / safe_name
        staged.mkdir(mode=0o700)
    else:
        staged = root / "latest" / safe_name
        staged.write_bytes(b"unsafe")
        staged.chmod(0o644)
    if mutation in {"arbitrary", "malformed", "disallowed_kind"}:
        staged.chmod(0o600)

    with pytest.raises(EvidenceCorruptionError):
        if recovery == "retry":
            store.admit_checked(
                candidate,
                validate=lambda _prior, _new: None,
            )
        else:
            store.rebuild()

    assert staged.exists() or staged.is_symlink()


@pytest.mark.parametrize("recovery", ["retry", "rebuild"])
def test_recovery_redurabilizes_visible_pointer_after_final_fsync_error(
    tmp_path,
    monkeypatch,
    recovery,
):
    root = tmp_path / "evidence"
    candidate = _candidate()
    pointer_path = root / "latest" / f"{candidate.kind}.json"
    pointer_inode: list[int] = []
    fail_final_pointer_fsync = True
    operations: list[str] = []
    real_replace = evidence_store_module.os.replace
    real_fsync = evidence_store_module.os.fsync

    def recording_replace(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        real_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        if destination == pointer_path.name and dst_dir_fd is not None:
            pointer_inode[:] = [pointer_path.stat().st_ino]

    def failing_final_pointer_fsync(descriptor: int) -> None:
        nonlocal fail_final_pointer_fsync
        state = os.fstat(descriptor)
        if pointer_inode and state.st_ino == pointer_inode[0]:
            if fail_final_pointer_fsync:
                fail_final_pointer_fsync = False
                operations.append("pointer-fsync-error")
                raise OSError("injected final pointer fsync failure")
            operations.append("pointer-fsync")
        elif stat.S_ISDIR(state.st_mode) and root.exists():
            latest = root / "latest"
            if latest.exists() and state.st_ino == latest.stat().st_ino:
                operations.append("latest-fsync")
            elif state.st_ino == root.stat().st_ino:
                operations.append("root-fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(
        evidence_store_module.os,
        "replace",
        recording_replace,
    )
    monkeypatch.setattr(
        evidence_store_module.os,
        "fsync",
        failing_final_pointer_fsync,
    )
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))

    with pytest.raises(
        EvidenceCorruptionError,
        match="latest pointer could not be made durable",
    ):
        store.admit_checked(candidate, validate=lambda _prior, _new: None)

    assert pointer_path.exists()
    assert EvidencePointer.from_dict(json.loads(pointer_path.read_bytes()))
    assert len(_journal_lines(root)) == 1
    operations.clear()
    assert ImmutableStrategyEvidenceStore(root).verify()
    assert operations == []

    if recovery == "retry":
        recovered = ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(LATER),
        ).admit_checked(candidate, validate=lambda _prior, _new: None)
        assert recovered.created is False
        expected = (recovered.envelope,)
    else:
        expected = store.rebuild()

    assert operations.index("pointer-fsync") < operations.index("latest-fsync")
    latest_fsync = operations.index("latest-fsync")
    assert any(
        index > latest_fsync and operation == "root-fsync"
        for index, operation in enumerate(operations)
    )
    operations.clear()
    assert ImmutableStrategyEvidenceStore(root).verify() == expected
    assert operations == []


def test_orphan_object_is_redurable_before_its_event_is_appended(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    candidate = _candidate()
    crashing = _CrashAfterObject(root, clock=_Clock(FIRST))
    with pytest.raises(RuntimeError):
        crashing.admit_checked(candidate, validate=lambda _prior, _new: None)
    orphan = next((root / "objects").rglob("*.json"))
    orphan_inode = orphan.stat().st_ino

    fsynced_inodes: list[int] = []
    real_fsync = evidence_store_module.os.fsync

    def recording_fsync(descriptor: int) -> None:
        state = os.fstat(descriptor)
        if stat.S_ISREG(state.st_mode):
            fsynced_inodes.append(state.st_ino)
        real_fsync(descriptor)

    monkeypatch.setattr(evidence_store_module.os, "fsync", recording_fsync)
    ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER)).admit_checked(
        candidate,
        validate=lambda _prior, _new: None,
    )

    assert orphan_inode in fsynced_inodes


def test_existing_journal_is_redurable_before_next_append(tmp_path, monkeypatch):
    store, root, _, _ = _admit(tmp_path)
    journal_inode = (root / "events.jsonl").stat().st_ino
    operations: list[tuple[str, int]] = []
    real_fsync = evidence_store_module.os.fsync
    real_write = evidence_store_module.os.write

    def recording_fsync(descriptor: int) -> None:
        state = os.fstat(descriptor)
        if stat.S_ISREG(state.st_mode):
            operations.append(("fsync", state.st_ino))
        real_fsync(descriptor)

    def recording_write(descriptor: int, payload: bytes) -> int:
        state = os.fstat(descriptor)
        if stat.S_ISREG(state.st_mode):
            operations.append(("write", state.st_ino))
        return real_write(descriptor, payload)

    monkeypatch.setattr(evidence_store_module.os, "fsync", recording_fsync)
    monkeypatch.setattr(evidence_store_module.os, "write", recording_write)
    store.admit_checked(
        _candidate(
            kind="baseline-genome",
            payload={"genome_id": "g-1", "generation": 0},
        ),
        validate=lambda _prior, _new: None,
    )

    first_journal_fsync = operations.index(("fsync", journal_inode))
    journal_write = operations.index(("write", journal_inode))
    assert first_journal_fsync < journal_write


def test_missing_journal_redurability_still_fsyncs_pinned_root(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))
    fsynced_inodes: list[int] = []
    real_fsync = evidence_store_module.os.fsync

    def recording_fsync(descriptor: int) -> None:
        fsynced_inodes.append(os.fstat(descriptor).st_ino)
        real_fsync(descriptor)

    with store._locked(create=True):
        store._ensure_managed_directories(
            create=True,
            recover_staged_pointers=True,
        )
        assert not (root / "events.jsonl").exists()
        root_inode = os.fstat(store._transaction().root_fd).st_ino
        monkeypatch.setattr(
            evidence_store_module.os,
            "fsync",
            recording_fsync,
        )

        store._redurable_journal_if_present()

    assert fsynced_inodes == [root_inode]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("torn", "torn"),
        ("blank", "blank"),
        ("malformed", "malformed"),
        ("noncanonical", "noncanonical"),
        ("sequence", "sequence"),
        ("prior_hash", "chain"),
        ("authority", "authority"),
        ("repeated", "repeated"),
    ],
)
def test_journal_corruption_fails_closed(tmp_path, mutation, message):
    store, root, _, _ = _admit(tmp_path)
    if mutation == "torn":
        path = root / "events.jsonl"
        path.write_bytes(path.read_bytes()[:-1])
    elif mutation == "blank":
        path = root / "events.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "malformed":
        (root / "events.jsonl").write_bytes(b"{bad}\n")
    elif mutation == "noncanonical":
        payload = _event_dict(root)
        (root / "events.jsonl").write_bytes(
            json.dumps(payload, sort_keys=False).encode() + b"\n"
        )
    elif mutation == "repeated":
        line = _journal_lines(root)[0]
        repeated = json.loads(line)
        repeated["sequence"] = 2
        repeated["previous_event_sha256"] = hashlib.sha256(line).hexdigest()
        (root / "events.jsonl").write_bytes(
            line + b"\n" + _canonical(repeated) + b"\n"
        )
    else:
        payload = _event_dict(root)
        if mutation == "sequence":
            payload["sequence"] = 2
        elif mutation == "prior_hash":
            payload["previous_event_sha256"] = "1" * 64
        else:
            payload["execution_authority"] = "live"
        _rewrite_event(root, payload)

    with pytest.raises(EvidenceCorruptionError, match=message):
        store.verify()


@pytest.mark.parametrize(
    "mutation",
    ["missing", "changed_payload", "changed_authority", "wrong_path"],
)
def test_object_corruption_or_missing_binding_fails_closed(tmp_path, mutation):
    store, root, _, admission = _admit(tmp_path)
    object_path = admission.path
    if mutation == "missing":
        object_path.unlink()
    elif mutation == "wrong_path":
        moved = object_path.with_name(
            "evaluation-registration-" + "f" * 64 + ".json"
        )
        object_path.rename(moved)
    else:
        payload = admission.envelope.to_dict()
        if mutation == "changed_payload":
            payload["payload"]["registration_key"] = "tampered"  # type: ignore[index]
        else:
            payload["can_submit_orders"] = True
        object_path.write_bytes(_canonical(payload))

    with pytest.raises(EvidenceCorruptionError):
        store.verify()


@pytest.mark.parametrize("mutation", ["missing", "stale", "corrupt"])
def test_verify_rejects_pointer_damage_without_repairing(tmp_path, mutation):
    store, root, candidate, _ = _admit(tmp_path)
    pointer = root / "latest" / f"{candidate.kind}.json"
    if mutation == "missing":
        pointer.unlink()
    elif mutation == "stale":
        payload = _pointer_dict(root)
        payload["sequence"] = 2
        pointer.write_bytes(_canonical(payload))
    else:
        pointer.write_bytes(b"{bad}")
    before = _tree_snapshot(root)

    with pytest.raises(EvidenceCorruptionError, match="pointer"):
        store.verify()

    assert _tree_snapshot(root) == before


@pytest.mark.parametrize("mutation", ["missing", "stale", "corrupt"])
def test_rebuild_repairs_only_derived_pointer_state(tmp_path, mutation):
    store, root, candidate, admission = _admit(tmp_path)
    pointer = root / "latest" / f"{candidate.kind}.json"
    object_before = admission.path.read_bytes()
    journal_before = (root / "events.jsonl").read_bytes()
    if mutation == "missing":
        pointer.unlink()
    elif mutation == "stale":
        payload = _pointer_dict(root)
        payload["sequence"] = 99
        pointer.write_bytes(_canonical(payload))
    else:
        pointer.write_bytes(b"{bad}")

    assert store.rebuild() == (admission.envelope,)

    assert admission.path.read_bytes() == object_before
    assert (root / "events.jsonl").read_bytes() == journal_before
    assert store.verify() == (admission.envelope,)


def test_rebuild_removes_stale_allowed_kind_pointer_without_event(tmp_path):
    store, root, _, _ = _admit(tmp_path)
    stale = root / "latest" / "mutation-record.json"
    payload = _pointer_dict(root)
    payload["kind"] = "mutation-record"
    stale.write_bytes(_canonical(payload))
    stale.chmod(0o600)

    store.rebuild()

    assert not stale.exists()
    assert store.verify()


def test_rebuild_redurabilizes_prior_stale_pointer_deletion_after_fsync_error(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))
    with pytest.raises(ValueError, match="initialize only"):
        store.admit_checked(
            _candidate(),
            validate=lambda _prior, _new: (_ for _ in ()).throw(
                ValueError("initialize only")
            ),
        )
    stale = root / "latest" / "mutation-record.json"
    stale.write_bytes(b"stale")
    stale.chmod(0o600)
    latest_inode = (root / "latest").stat().st_ino
    root_inode = root.stat().st_ino
    fail_latest_fsync = True
    operations: list[str] = []
    real_fsync = evidence_store_module.os.fsync

    def failing_once_fsync(descriptor: int) -> None:
        nonlocal fail_latest_fsync
        state = os.fstat(descriptor)
        if stat.S_ISDIR(state.st_mode) and state.st_ino == latest_inode:
            if fail_latest_fsync:
                fail_latest_fsync = False
                operations.append("latest-fsync-error")
                raise OSError("injected latest directory fsync failure")
            operations.append("latest-fsync")
        elif stat.S_ISDIR(state.st_mode) and state.st_ino == root_inode:
            operations.append("root-fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(evidence_store_module.os, "fsync", failing_once_fsync)
    with pytest.raises(EvidenceCorruptionError, match="latest"):
        store.rebuild()

    assert not stale.exists()
    operations.clear()
    assert store.rebuild() == ()
    latest_fsync = operations.index("latest-fsync")
    assert any(
        index > latest_fsync and operation == "root-fsync"
        for index, operation in enumerate(operations)
    )


def test_verify_on_missing_root_is_read_only(tmp_path):
    root = tmp_path / "never-created"
    store = ImmutableStrategyEvidenceStore(root)

    assert store.verify() == ()
    assert store.envelopes() == ()
    assert not root.exists()


@pytest.mark.parametrize(
    ("target", "replacement"),
    [
        ("lock", "symlink"),
        ("events", "symlink"),
        ("objects", "symlink"),
        ("latest", "symlink"),
        ("object", "symlink"),
        ("pointer", "symlink"),
        ("events", "fifo"),
    ],
)
def test_managed_paths_reject_symlinks_and_nonregular_files(
    tmp_path,
    target,
    replacement,
):
    store, root, candidate, admission = _admit(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("outside")
    paths = {
        "lock": root / ".strategy-evidence.lock",
        "events": root / "events.jsonl",
        "objects": root / "objects",
        "latest": root / "latest",
        "object": admission.path,
        "pointer": root / "latest" / f"{candidate.kind}.json",
    }
    selected = paths[target]
    if selected.is_dir():
        selected.rename(selected.with_name(selected.name + "-real"))
    else:
        selected.unlink()
    if replacement == "fifo":
        os.mkfifo(selected)
    else:
        selected.symlink_to(outside, target_is_directory=False)

    with pytest.raises(EvidenceCorruptionError):
        store.verify()


def test_root_and_symlinked_parent_are_rejected_without_touching_target(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(target, target_is_directory=True)

    with pytest.raises(EvidenceCorruptionError, match="symlink"):
        ImmutableStrategyEvidenceStore(root_link)
    assert not tuple(target.iterdir())

    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(target, target_is_directory=True)
    with pytest.raises(EvidenceCorruptionError, match="symlink"):
        ImmutableStrategyEvidenceStore(parent_link / "nested")
    assert not tuple(target.iterdir())


@pytest.mark.parametrize("target", ["lock", "events", "object", "pointer"])
def test_managed_regular_files_reject_hard_links(tmp_path, target):
    store, root, candidate, admission = _admit(tmp_path)
    paths = {
        "lock": root / ".strategy-evidence.lock",
        "events": root / "events.jsonl",
        "object": admission.path,
        "pointer": root / "latest" / f"{candidate.kind}.json",
    }
    os.link(paths[target], tmp_path / f"{target}-hardlink")

    with pytest.raises(EvidenceCorruptionError, match="link"):
        store.verify()


@pytest.mark.parametrize("target", ["lock", "events", "object", "pointer"])
def test_managed_regular_files_reject_unsafe_modes(tmp_path, target):
    store, root, candidate, admission = _admit(tmp_path)
    paths = {
        "lock": root / ".strategy-evidence.lock",
        "events": root / "events.jsonl",
        "object": admission.path,
        "pointer": root / "latest" / f"{candidate.kind}.json",
    }
    paths[target].chmod(0o666)

    with pytest.raises(EvidenceCorruptionError, match="mode"):
        store.verify()


@pytest.mark.parametrize("target", ["object", "pointer"])
def test_oversized_managed_files_fail_before_their_contents_are_read(
    tmp_path,
    monkeypatch,
    target,
):
    store, root, candidate, admission = _admit(tmp_path)
    paths = {
        "events": root / "events.jsonl",
        "object": admission.path,
        "pointer": root / "latest" / f"{candidate.kind}.json",
    }
    selected = paths[target]
    with selected.open("r+b") as stream:
        stream.truncate(1_048_577)
    selected_inode = selected.stat().st_ino
    selected_reads = 0
    real_read = evidence_store_module.os.read

    def recording_read(descriptor: int, size: int) -> bytes:
        nonlocal selected_reads
        if os.fstat(descriptor).st_ino == selected_inode:
            selected_reads += 1
        return real_read(descriptor, size)

    monkeypatch.setattr(evidence_store_module.os, "read", recording_read)
    with pytest.raises(EvidenceCorruptionError, match="too large"):
        store.verify()

    assert selected_reads == 0


def test_replay_rejects_one_oversized_journal_line(tmp_path):
    store, root, _, _ = _admit(tmp_path)
    (root / "events.jsonl").write_bytes(b"x" * 1_048_577 + b"\n")

    with pytest.raises(EvidenceCorruptionError, match="line.*too large"):
        store.verify()


def test_journal_can_grow_beyond_one_mebibyte_and_remain_replayable(tmp_path):
    root = tmp_path / "evidence"
    objects = root / "objects"
    kind = "evaluation-registration"
    kind_dir = objects / kind
    latest = root / "latest"
    root.mkdir(mode=0o700)
    objects.mkdir(mode=0o700)
    kind_dir.mkdir(mode=0o700)
    latest.mkdir(mode=0o700)
    lock = root / ".strategy-evidence.lock"
    lock.touch(mode=0o600)

    lines: list[bytes] = []
    journal_size = 0
    previous = ZERO_HASH
    last_event: EvidenceEvent | None = None
    sequence = 0
    while journal_size <= 1_048_576:
        sequence += 1
        candidate = _candidate(payload={"ordinal": sequence})
        retry_bytes = evidence_store_module._retry_material_bytes(
            kind=kind,
            effective_at=candidate.effective_at,
            payload=candidate.payload,
        )
        retry_digest = hashlib.sha256(retry_bytes).hexdigest()
        object_id = f"{kind}-{retry_digest}"
        envelope = EvidenceEnvelope(
            kind=kind,
            object_id=object_id,
            effective_at=candidate.effective_at,
            recorded_at="2030-01-02T15:04:05+00:00",
            retry_material_sha256=retry_digest,
            payload_sha256=hashlib.sha256(
                evidence_store_module._payload_bytes(candidate.payload)
            ).hexdigest(),
            payload=candidate.payload,
        )
        object_bytes = envelope.canonical_json_bytes()
        object_path = kind_dir / f"{object_id}.json"
        object_path.write_bytes(object_bytes)
        object_path.chmod(0o600)
        event = EvidenceEvent(
            sequence=sequence,
            kind=kind,
            object_id=object_id,
            object_sha256=hashlib.sha256(object_bytes).hexdigest(),
            retry_material_sha256=retry_digest,
            effective_at=envelope.effective_at,
            recorded_at=envelope.recorded_at,
            previous_event_sha256=previous,
        )
        line = event.canonical_json_bytes()
        lines.append(line)
        journal_size += len(line) + 1
        previous = hashlib.sha256(line).hexdigest()
        last_event = event

    assert last_event is not None
    journal = root / "events.jsonl"
    journal.write_bytes(b"".join(line + b"\n" for line in lines))
    journal.chmod(0o600)
    pointer = EvidencePointer(
        kind=kind,
        sequence=last_event.sequence,
        object_id=last_event.object_id,
        object_sha256=last_event.object_sha256,
        event_sha256=hashlib.sha256(
            last_event.canonical_json_bytes()
        ).hexdigest(),
        recorded_at=last_event.recorded_at,
    )
    pointer_path = latest / f"{kind}.json"
    pointer_path.write_bytes(pointer.canonical_json_bytes())
    pointer_path.chmod(0o600)

    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER))
    assert len(store.verify()) == len(lines)
    added = store.admit_checked(
        _candidate(
            kind="baseline-genome",
            payload={"genome_id": "large-journal-boundary"},
        ),
        validate=lambda _prior, _new: None,
    )
    assert added.event.sequence == len(lines) + 1
    assert (root / "events.jsonl").stat().st_size > 1_048_576
    assert len(store.verify()) == len(lines) + 1


def test_predictable_journal_line_rejection_creates_no_orphan(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    monkeypatch.setattr(
        evidence_store_module,
        "_MAX_JOURNAL_LINE_BYTES",
        1,
        raising=False,
    )
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))

    with pytest.raises(EvidenceCorruptionError, match="line.*too large"):
        store.admit_checked(
            _candidate(),
            validate=lambda _prior, _new: None,
        )

    assert not tuple((root / "objects").rglob("*.json"))
    assert not (root / "events.jsonl").exists()


def test_managed_path_escape_is_rejected(tmp_path):
    store, _, _, _ = _admit(tmp_path)
    store._events_path = tmp_path / "outside-events.jsonl"

    with pytest.raises(EvidenceCorruptionError, match="escapes"):
        store.verify()


def test_replaced_lock_cannot_split_two_store_transactions(tmp_path):
    root = tmp_path / "evidence"
    first = _candidate(payload={"slot": "first"})
    second = _candidate(payload={"slot": "second"})
    store_a = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))
    store_b = ImmutableStrategyEvidenceStore(root, clock=_Clock(LATER))
    b_started = threading.Event()
    b_finished = threading.Event()
    b_outcome: list[object] = []
    b_thread: list[threading.Thread] = []

    def run_b() -> None:
        b_started.set()
        try:
            b_outcome.append(
                store_b.admit_checked(
                    second,
                    validate=lambda _prior, _new: None,
                )
            )
        except Exception as exc:  # pragma: no cover - diagnostic capture
            b_outcome.append(exc)
        finally:
            b_finished.set()

    def displace_lock(
        _prior: tuple[EvidenceEnvelope, ...],
        _new: EvidenceEnvelope,
    ) -> None:
        lock_path = root / ".strategy-evidence.lock"
        lock_path.rename(root / ".strategy-evidence.lock.displaced")
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        thread = threading.Thread(target=run_b, daemon=True)
        b_thread.append(thread)
        thread.start()
        assert b_started.wait(timeout=1)
        assert not b_finished.wait(timeout=0.25)

    with pytest.raises(EvidenceCorruptionError, match="lock.*changed"):
        store_a.admit_checked(first, validate=displace_lock)

    assert b_finished.wait(timeout=2)
    b_thread[0].join(timeout=1)
    assert len(b_outcome) == 1
    assert not isinstance(b_outcome[0], Exception)
    assert b_outcome[0].event.sequence == 1  # type: ignore[union-attr]
    assert len(_journal_lines(root)) == 1
    assert ImmutableStrategyEvidenceStore(root).verify() == (
        b_outcome[0].envelope,  # type: ignore[union-attr]
    )


def test_replaced_lock_cannot_split_cross_process_transactions(tmp_path):
    root = tmp_path / "evidence"
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))
    child: list[subprocess.Popen[str]] = []
    script = """
import datetime as dt
import sys
from pathlib import Path
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
)
root = Path(sys.argv[1])
candidate = EvidenceCandidate(
    kind="baseline-genome",
    effective_at="2030-01-02T14:00:00+00:00",
    payload={"slot": "child"},
)
ImmutableStrategyEvidenceStore(
    root,
    clock=lambda: dt.datetime(
        2030, 1, 2, 15, 4, 15, tzinfo=dt.timezone.utc
    ),
).admit_checked(candidate, validate=lambda _prior, _new: None)
"""

    def displace_and_launch(
        _prior: tuple[EvidenceEnvelope, ...],
        _new: EvidenceEnvelope,
    ) -> None:
        lock_path = root / ".strategy-evidence.lock"
        lock_path.rename(root / ".strategy-evidence.lock.displaced")
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(root)],
            cwd=Path(evidence_store_module.__file__).resolve().parents[2],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        child.append(process)
        time.sleep(0.25)
        assert process.poll() is None

    with pytest.raises(EvidenceCorruptionError, match="lock.*changed"):
        store.admit_checked(
            _candidate(payload={"slot": "parent"}),
            validate=displace_and_launch,
        )

    stdout, stderr = child[0].communicate(timeout=2)
    assert child[0].returncode == 0, (stdout, stderr)
    assert len(_journal_lines(root)) == 1
    assert ImmutableStrategyEvidenceStore(root).verify()[0].payload == {
        "slot": "child"
    }


def test_kind_directory_swap_before_object_create_never_writes_outside(tmp_path):
    root = tmp_path / "evidence"
    outside = tmp_path / "outside"
    outside.mkdir()

    class SwappingStore(ImmutableStrategyEvidenceStore):
        def _write_immutable_object(self, path: Path, payload: bytes) -> None:
            kind_dir = path.parent
            kind_dir.rename(kind_dir.with_name(f"{kind_dir.name}-displaced"))
            kind_dir.symlink_to(outside, target_is_directory=True)
            super()._write_immutable_object(path, payload)

    store = SwappingStore(root, clock=_Clock(FIRST))
    with pytest.raises(EvidenceCorruptionError):
        store.admit_checked(
            _candidate(),
            validate=lambda _prior, _new: None,
        )

    assert not tuple(outside.iterdir())


def test_kind_directory_swap_at_object_open_leaves_no_outside_file(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    outside = tmp_path / "outside"
    outside.mkdir()
    displaced = outside / "kind-displaced"
    real_open = evidence_store_module.os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        name = os.fsdecode(path)
        if (
            not swapped
            and dir_fd is not None
            and flags & os.O_EXCL
            and name.endswith(".json")
        ):
            swapped = True
            kind_dir = root / "objects" / "evaluation-registration"
            kind_dir.rename(displaced)
            kind_dir.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(evidence_store_module.os, "open", swapping_open)
    with pytest.raises(EvidenceCorruptionError):
        ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(FIRST),
        ).admit_checked(
            _candidate(),
            validate=lambda _prior, _new: None,
        )

    assert displaced.is_dir()
    assert not tuple(displaced.glob("*.json"))


def test_kind_directory_swap_during_object_read_fails_closed(tmp_path):
    store, root, _, admission = _admit(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_copy = outside / admission.path.name
    outside_copy.write_bytes(admission.path.read_bytes())
    outside_copy.chmod(0o600)

    class SwappingReadStore(ImmutableStrategyEvidenceStore):
        swapped = False

        def _read_envelope(
            self,
            path: Path,
            *,
            expected_kind: str,
            expected_id: str,
        ) -> tuple[EvidenceEnvelope, bytes]:
            if not self.swapped:
                self.swapped = True
                kind_dir = path.parent
                kind_dir.rename(
                    kind_dir.with_name(f"{kind_dir.name}-displaced")
                )
                kind_dir.symlink_to(outside, target_is_directory=True)
            return super()._read_envelope(
                path,
                expected_kind=expected_kind,
                expected_id=expected_id,
            )

    with pytest.raises(EvidenceCorruptionError):
        SwappingReadStore(root).verify()

    assert outside_copy.read_bytes() == admission.envelope.canonical_json_bytes()


def test_latest_directory_swap_before_pointer_publish_never_writes_outside(
    tmp_path,
):
    root = tmp_path / "evidence"
    outside = tmp_path / "outside"
    outside.mkdir()

    class SwappingPointerStore(ImmutableStrategyEvidenceStore):
        swapped = False

        def _publish_pointer(self, pointer: EvidencePointer) -> None:
            if not self.swapped:
                self.swapped = True
                latest = self.root / "latest"
                latest.rename(self.root / "latest-displaced")
                latest.symlink_to(outside, target_is_directory=True)
            super()._publish_pointer(pointer)

    with pytest.raises(EvidenceCorruptionError):
        SwappingPointerStore(root, clock=_Clock(FIRST)).admit_checked(
            _candidate(),
            validate=lambda _prior, _new: None,
        )

    assert not tuple(outside.iterdir())


def test_latest_directory_swap_during_pointer_read_fails_closed(tmp_path):
    store, root, candidate, _ = _admit(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    pointer_name = f"{candidate.kind}.json"
    pointer_path = root / "latest" / pointer_name
    outside_pointer = outside / pointer_name
    pointer_bytes = pointer_path.read_bytes()
    outside_pointer.write_bytes(pointer_bytes)
    outside_pointer.chmod(0o600)

    class SwappingPointerReadStore(ImmutableStrategyEvidenceStore):
        swapped = False

        def _read_regular(self, path: Path, *, label: str) -> bytes:
            if label == "latest pointer" and not self.swapped:
                self.swapped = True
                latest = self.root / "latest"
                latest.rename(self.root / "latest-displaced")
                latest.symlink_to(outside, target_is_directory=True)
            return super()._read_regular(path, label=label)

    with pytest.raises(EvidenceCorruptionError):
        SwappingPointerReadStore(root).verify()

    assert outside_pointer.read_bytes() == pointer_bytes


def test_latest_directory_swap_at_staged_replace_cannot_publish_outside(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_replace = evidence_store_module.os.replace
    swapped = False

    def swapping_replace(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            latest = root / "latest"
            displaced = root / "latest-displaced"
            latest.rename(displaced)
            latest.symlink_to(outside, target_is_directory=True)
        real_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(
        evidence_store_module.os,
        "replace",
        swapping_replace,
    )
    candidate = _candidate()
    with pytest.raises(EvidenceCorruptionError):
        ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(FIRST),
        ).admit_checked(
            candidate,
            validate=lambda _prior, _new: None,
        )

    assert not (outside / f"{candidate.kind}.json").exists()


def test_first_admission_fsyncs_root_parent_before_managed_writes(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    parent_inode = tmp_path.stat().st_ino
    operations: list[tuple[str, int]] = []
    real_fsync = evidence_store_module.os.fsync
    real_write = evidence_store_module.os.write

    def recording_fsync(descriptor: int) -> None:
        operations.append(("fsync", os.fstat(descriptor).st_ino))
        real_fsync(descriptor)

    def recording_write(descriptor: int, payload: bytes) -> int:
        operations.append(("write", os.fstat(descriptor).st_ino))
        return real_write(descriptor, payload)

    monkeypatch.setattr(evidence_store_module.os, "fsync", recording_fsync)
    monkeypatch.setattr(evidence_store_module.os, "write", recording_write)
    ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST)).admit_checked(
        _candidate(),
        validate=lambda _prior, _new: None,
    )

    parent_fsync = operations.index(("fsync", parent_inode))
    first_write = next(
        index
        for index, operation in enumerate(operations)
        if operation[0] == "write"
    )
    assert parent_fsync < first_write


def test_root_parent_fsync_failure_cannot_report_success(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    parent_inode = tmp_path.stat().st_ino
    real_fsync = evidence_store_module.os.fsync

    def fail_parent_fsync(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == parent_inode:
            raise OSError("injected root parent fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(evidence_store_module.os, "fsync", fail_parent_fsync)
    with pytest.raises(EvidenceCorruptionError, match="root.*durable"):
        ImmutableStrategyEvidenceStore(
            root,
            clock=_Clock(FIRST),
        ).admit_checked(
            _candidate(),
            validate=lambda _prior, _new: None,
        )

    assert not (root / "events.jsonl").exists()
    assert not tuple((root / "objects").rglob("*.json"))


def test_validator_reentry_through_second_store_fails_fast(tmp_path):
    root = tmp_path / "evidence"
    script = f"""
import datetime as dt
from pathlib import Path
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
    StrategyEvidenceStoreError,
)
root = Path({str(root)!r})
clock = lambda: dt.datetime(2030, 1, 2, 15, 4, 5, tzinfo=dt.timezone.utc)
first = ImmutableStrategyEvidenceStore(root, clock=clock)
second = ImmutableStrategyEvidenceStore(root, clock=clock)
candidate = EvidenceCandidate(
    kind="evaluation-registration",
    effective_at="2030-01-02T14:00:00+00:00",
    payload={{"slot": "reentry"}},
)
observed = []
def validate(_prior, _new):
    try:
        second.verify()
    except StrategyEvidenceStoreError as exc:
        observed.append(str(exc))
    else:
        raise AssertionError("cross-instance reentry did not fail")
first.admit_checked(candidate, validate=validate)
assert observed and "callback" in observed[0]
"""
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(evidence_store_module.__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=2,
        check=False,
    )

    assert time.monotonic() - started < 2
    assert completed.returncode == 0, completed.stderr


def test_cross_root_validators_cannot_deadlock_each_other(tmp_path):
    root_a = tmp_path / "evidence-a"
    root_b = tmp_path / "evidence-b"
    script = f"""
import datetime as dt
import threading
from pathlib import Path
from tradingagents.strategy._immutable_evidence_store import (
    EvidenceCandidate,
    ImmutableStrategyEvidenceStore,
    StrategyEvidenceStoreError,
)
clock = lambda: dt.datetime(2030, 1, 2, 15, 4, 5, tzinfo=dt.timezone.utc)
store_a = ImmutableStrategyEvidenceStore(Path({str(root_a)!r}), clock=clock)
store_b = ImmutableStrategyEvidenceStore(Path({str(root_b)!r}), clock=clock)
barrier = threading.Barrier(2)
outcomes = []
outcomes_lock = threading.Lock()

def candidate(slot):
    return EvidenceCandidate(
        kind="evaluation-registration",
        effective_at="2030-01-02T14:00:00+00:00",
        payload={{"slot": slot}},
    )

def run(label, source, target):
    def validate(_prior, _new):
        barrier.wait(timeout=1)
        try:
            target.verify()
        except StrategyEvidenceStoreError as exc:
            with outcomes_lock:
                outcomes.append((label, "blocked", "callback" in str(exc)))
        else:
            with outcomes_lock:
                outcomes.append((label, "allowed", False))
    try:
        source.admit_checked(candidate(label), validate=validate)
    except Exception as exc:
        with outcomes_lock:
            outcomes.append((label, type(exc).__name__, str(exc)))
    else:
        with outcomes_lock:
            outcomes.append((label, "admitted", True))

threads = [
    threading.Thread(
        target=run,
        args=("a", store_a, store_b),
        daemon=True,
    ),
    threading.Thread(
        target=run,
        args=("b", store_b, store_a),
        daemon=True,
    ),
]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(timeout=1)
assert not any(thread.is_alive() for thread in threads), "validators deadlocked"
assert sorted(outcomes) == [
    ("a", "admitted", True),
    ("a", "blocked", True),
    ("b", "admitted", True),
    ("b", "blocked", True),
]
assert len(store_a.verify()) == 1
assert len(store_b.verify()) == 1
"""
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(evidence_store_module.__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )

    assert time.monotonic() - started < 3
    assert completed.returncode == 0, completed.stderr


def test_validator_rejects_every_public_entry_across_roots_and_clears(
    tmp_path,
):
    first = ImmutableStrategyEvidenceStore(
        tmp_path / "evidence-a",
        clock=_Clock(FIRST),
    )
    second = ImmutableStrategyEvidenceStore(
        tmp_path / "evidence-b",
        clock=_Clock(FIRST),
    )
    nested = _candidate(payload={"slot": "nested"})
    observed: list[str] = []

    def validate(
        _prior: tuple[EvidenceEnvelope, ...],
        _new: EvidenceEnvelope,
    ) -> None:
        calls = (
            lambda: second.admit_checked(
                nested,
                validate=lambda _prior, _new: None,
            ),
            second.verify,
            second.rebuild,
            second.envelopes,
        )
        for call in calls:
            with pytest.raises(
                evidence_store_module.StrategyEvidenceStoreError,
                match="validation callback",
            ) as raised:
                call()
            observed.append(str(raised.value))

    admitted = first.admit_checked(_candidate(), validate=validate)

    assert len(observed) == 4
    assert first.verify() == (admitted.envelope,)
    assert second.verify() == ()
    nested_admission = second.admit_checked(
        nested,
        validate=lambda _prior, _new: None,
    )
    assert second.envelopes() == (nested_admission.envelope,)
    assert second.rebuild() == (nested_admission.envelope,)


def test_process_root_lock_registry_releases_inactive_roots(tmp_path):
    before = frozenset(evidence_store_module._ROOT_PROCESS_LOCKS)
    created_keys: set[str] = set()

    for index in range(64):
        store = ImmutableStrategyEvidenceStore(tmp_path / f"evidence-{index}")
        created_keys.add(os.fspath(store.root))
        process_lock = store._process_root_lock()
        process_lock.acquire()
        process_lock.release()

    del process_lock
    del store
    gc.collect()

    assert created_keys.isdisjoint(evidence_store_module._ROOT_PROCESS_LOCKS)
    assert before.issubset(evidence_store_module._ROOT_PROCESS_LOCKS)


@pytest.mark.parametrize("failing_resource", ["kind", "objects", "root"])
def test_close_failure_attempts_every_later_release_and_store_recovers(
    tmp_path,
    monkeypatch,
    failing_resource,
):
    root = tmp_path / "evidence"
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))
    process_lock = store._process_root_lock()
    real_close = evidence_store_module.os.close
    real_flock = evidence_store_module.fcntl.flock
    close_attempts: list[int] = []
    unlock_attempts: list[int] = []
    failed = False

    with pytest.raises(
        OSError,
        match=f"forced {failing_resource} close failure",
    ), store._locked(create=True):
        store._ensure_managed_directories(
            create=True,
            recover_staged_pointers=True,
        )
        store._ensure_kind_directory(
            "evaluation-registration",
            create=True,
        )
        transaction = store._transaction()
        kind_fd = transaction.kind_fds["evaluation-registration"][0]
        assert transaction.latest_fd is not None
        assert transaction.objects_fd is not None
        descriptors = {
            "kind": kind_fd,
            "latest": transaction.latest_fd,
            "objects": transaction.objects_fd,
            "lock": transaction.lock_fd,
            "root": transaction.root_fd,
        }
        cleanup_order = [
            descriptors["kind"],
            descriptors["latest"],
            descriptors["objects"],
            descriptors["lock"],
            descriptors["root"],
        ]
        failing_descriptor = descriptors[failing_resource]

        def failing_close(descriptor: int) -> None:
            nonlocal failed
            if descriptor in cleanup_order:
                close_attempts.append(descriptor)
            real_close(descriptor)
            if descriptor == failing_descriptor and not failed:
                failed = True
                raise OSError(
                    f"forced {failing_resource} close failure"
                )

        def recording_flock(descriptor: int, operation: int) -> None:
            if operation == evidence_store_module.fcntl.LOCK_UN:
                unlock_attempts.append(descriptor)
            real_flock(descriptor, operation)

        monkeypatch.setattr(
            evidence_store_module.os,
            "close",
            failing_close,
        )
        monkeypatch.setattr(
            evidence_store_module.fcntl,
            "flock",
            recording_flock,
        )

    assert close_attempts == cleanup_order
    assert unlock_attempts == [descriptors["lock"], descriptors["root"]]
    with pytest.raises(
        EvidenceCorruptionError,
        match="requires a pinned transaction",
    ):
        store._transaction()
    acquired = process_lock.acquire(blocking=False)
    assert acquired, "process-root lock remained held after cleanup failure"
    process_lock.release()

    monkeypatch.setattr(evidence_store_module.os, "close", real_close)
    monkeypatch.setattr(evidence_store_module.fcntl, "flock", real_flock)
    admission = store.admit_checked(
        _candidate(payload={"slot": f"after-{failing_resource}-failure"}),
        validate=lambda _prior, _new: None,
    )
    assert store.verify() == (admission.envelope,)


def test_body_exception_precedes_cleanup_error_and_validator_state_clears(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "evidence"
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST, LATER))
    process_lock = store._process_root_lock()
    real_close = evidence_store_module.os.close
    failed = False

    def validate(
        _prior: tuple[EvidenceEnvelope, ...],
        _new: EvidenceEnvelope,
    ) -> None:
        transaction = store._transaction()
        assert transaction.latest_fd is not None
        failing_descriptor = transaction.latest_fd

        def failing_close(descriptor: int) -> None:
            nonlocal failed
            real_close(descriptor)
            if descriptor == failing_descriptor and not failed:
                failed = True
                raise OSError("forced cleanup failure")

        monkeypatch.setattr(
            evidence_store_module.os,
            "close",
            failing_close,
        )
        raise RuntimeError("validator body failure")

    with pytest.raises(RuntimeError, match="validator body failure") as raised:
        store.admit_checked(_candidate(), validate=validate)

    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "forced cleanup failure"
    assert not hasattr(evidence_store_module._VALIDATOR_ACTIVITY, "depth")
    with pytest.raises(
        EvidenceCorruptionError,
        match="requires a pinned transaction",
    ):
        store._transaction()
    acquired = process_lock.acquire(blocking=False)
    assert acquired, "process-root lock remained held after body failure"
    process_lock.release()

    monkeypatch.setattr(evidence_store_module.os, "close", real_close)
    admission = store.admit_checked(
        _candidate(payload={"slot": "after-body-and-cleanup-failure"}),
        validate=lambda _prior, _new: None,
    )
    assert store.verify() == (admission.envelope,)


@pytest.mark.parametrize(
    "candidate_factory",
    [
        lambda: EvidenceCandidate(
            kind="../registration",
            effective_at="2030-01-02T14:00:00+00:00",
            payload={},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T09:00:00-05:00",
            payload={},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T14:00:00.123456+00:00",
            payload={},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T14:00:00+00:00",
            payload={"bad": 1.5},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T14:00:00+00:00",
            payload={"bad": b"bytes"},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T14:00:00+00:00",
            payload={1: "non-string-key"},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T14:00:00+00:00",
            payload={"too_deep": [[[[[[[[[[[[[[[[[[[[None]]]]]]]]]]]]]]]]]]]]},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T14:00:00+00:00",
            payload={"too_long": "x" * 100_000},
        ),
        lambda: EvidenceCandidate(
            kind="evaluation-registration",
            effective_at="2030-01-02T14:00:00+00:00",
            payload={f"k-{index}": index for index in range(20_000)},
        ),
    ],
)
def test_invalid_candidate_inputs_do_not_create_root(tmp_path, candidate_factory):
    root = tmp_path / "evidence"
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))

    with pytest.raises(ValueError):
        candidate = candidate_factory()
        store.admit_checked(candidate, validate=lambda _prior, _new: None)

    assert not root.exists()


def test_callback_failure_writes_no_object_event_or_pointer(tmp_path):
    root = tmp_path / "evidence"
    store = ImmutableStrategyEvidenceStore(root, clock=_Clock(FIRST))

    with pytest.raises(ValueError, match="policy rejected"):
        store.admit_checked(
            _candidate(),
            validate=lambda _prior, _new: (_ for _ in ()).throw(
                ValueError("policy rejected")
            ),
        )

    assert not tuple((root / "objects").rglob("*.json"))
    assert not (root / "events.jsonl").exists()
    assert not tuple((root / "latest").glob("*.json"))
    assert store.verify() == ()
    admitted = store.admit_checked(
        _candidate(payload={"slot": "after-validator-failure"}),
        validate=lambda _prior, _new: None,
    )
    assert store.envelopes() == (admitted.envelope,)


def test_kind_filter_rejects_unknown_kind_without_mutating_store(tmp_path):
    store, root, _, _ = _admit(tmp_path)
    before = _tree_snapshot(root)

    with pytest.raises(ValueError):
        store.envelopes(kind="../bad")

    assert _tree_snapshot(root) == before


def test_import_and_literal_isolation_from_execution_surfaces():
    source_path = (
        Path(evidence_store_module.__file__).resolve()
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden_import_fragments = {
        "broker",
        "alpaca",
        "promotion",
        "live_gate",
        "execution",
        "order",
        "supervisor",
        "network",
        "requests",
        "httpx",
        "openai",
        "langgraph",
    }
    assert not any(
        fragment in imported_name
        for imported_name in imported
        for fragment in forbidden_import_fragments
    )

    string_literals = {
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    forbidden_authority_literals = {
        "submit_order",
        "submit_orders",
        "live_control",
        "broker_order",
    }
    assert string_literals.isdisjoint(forbidden_authority_literals)
