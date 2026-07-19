from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tradingagents.orchestration.decision_ledger import (
    DECISION_LEDGER_SCHEMA_VERSION,
    DecisionLedger,
    LedgerCorruptionError,
    LedgerEvent,
    PacketCollisionError,
)
from tradingagents.orchestration.work_packets import EvidenceRef, WorkPacket

UTC = dt.timezone.utc
NOW = dt.datetime(2030, 1, 2, 15, 4, 5, tzinfo=UTC)
HISTORICAL_NOW = dt.datetime(2020, 1, 2, 15, 4, 5, tzinfo=UTC)
EVENT_KEYS = {
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
POINTER_KEYS = {
    "schema_version",
    "sequence",
    "packet_id",
    "kind",
    "packet_sha256",
    "journal_path",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
}
SENSITIVE_KEYS = {
    "claims",
    "assumptions",
    "recommendation",
    "confidence",
    "raw_transcript",
    "prompt",
    "model_output",
    "credentials",
    "order",
    "broker",
}


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _packet(
    tmp_path: Path,
    *,
    run_id: str = "run-1",
    kind: str = "research_synthesis",
    recommendation: str = "hold_cash",
    evidence_name: str | None = None,
    evidence_payload: bytes = b'{"stance":"bullish"}',
    now: dt.datetime = NOW,
) -> WorkPacket:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    source = evidence_dir / (evidence_name or f"{run_id}.json")
    source.write_bytes(evidence_payload)
    return WorkPacket.create(
        kind=kind,
        producer_role="research_manager",
        run_id=run_id,
        subject="NFLX",
        evidence_refs=[EvidenceRef.from_path(source)],
        parent_packet_ids=[],
        claims=["price held support"],
        assumptions=["regular market session"],
        recommendation=recommendation,
        confidence=0.62,
        allowed_effects=["recommend_hold_cash"],
        forbidden_effects=[],
        expires_at=now + dt.timedelta(hours=2),
        now=now,
    )


def _event_payload(root: Path, index: int = 0) -> dict:
    lines = (root / "events.jsonl").read_bytes().splitlines()
    return json.loads(lines[index])


def _pointer_payload(root: Path, kind: str = "research_synthesis") -> dict:
    return json.loads((root / "latest" / f"{kind}.json").read_bytes())


def _recorded(
    tmp_path: Path,
) -> tuple[DecisionLedger, Path, WorkPacket, Path]:
    root = tmp_path / "ledger"
    packet = _packet(tmp_path)
    ledger = DecisionLedger(root)
    packet_path = ledger.record(packet, now=NOW)
    return ledger, root, packet, packet_path


def test_record_writes_exact_canonical_layout_and_analysis_only_shapes(tmp_path):
    root_argument = tmp_path / "nested" / ".." / "ledger"
    packet = _packet(tmp_path)
    ledger = DecisionLedger(root_argument)

    packet_path = ledger.record(packet, now=NOW)
    events = ledger.verify()

    root = root_argument.resolve()
    assert ledger.root == root
    assert packet_path == root / "packets" / f"{packet.packet_id}.json"
    assert packet_path.read_bytes() == packet.canonical_json_bytes()
    assert not packet_path.read_bytes().endswith(b"\n")
    assert hashlib.sha256(packet_path.read_bytes()).hexdigest() == packet.payload_digest()

    assert len(events) == 1
    event = events[0]
    assert event.schema_version == DECISION_LEDGER_SCHEMA_VERSION == 1
    assert event.compact() == {
        "schema_version": 1,
        "sequence": 1,
        "packet_id": packet.packet_id,
        "kind": packet.kind,
        "packet_sha256": packet.payload_digest(),
        "created_at": packet.created_at,
        "run_id": packet.run_id,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    assert (root / "events.jsonl").read_bytes() == event.canonical_json_bytes() + b"\n"

    pointer = _pointer_payload(root)
    assert pointer == {
        "schema_version": 1,
        "sequence": 1,
        "packet_id": packet.packet_id,
        "kind": packet.kind,
        "packet_sha256": packet.payload_digest(),
        "journal_path": "events.jsonl",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    pointer_bytes = root.joinpath("latest", f"{packet.kind}.json").read_bytes()
    assert pointer_bytes == _canonical(pointer)
    assert not pointer_bytes.endswith(b"\n")
    assert set(event.compact()) == EVENT_KEYS
    assert set(pointer) == POINTER_KEYS
    assert not (set(event.compact()) & SENSITIVE_KEYS)
    assert not (set(pointer) & SENSITIVE_KEYS)

    for path in (
        root / ".ledger.lock",
        root / "events.jsonl",
        packet_path,
        root / "latest" / f"{packet.kind}.json",
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("sequence", True),
        ("sequence", 0),
        ("packet_sha256", "A" * 64),
        ("analysis_only", False),
        ("execution_authority", "live"),
        ("can_submit_orders", True),
    ],
)
def test_ledger_event_rejects_invalid_shape_and_authority(tmp_path, field, value):
    _, root, _, _ = _recorded(tmp_path)
    payload = _event_payload(root)
    payload[field] = value

    with pytest.raises(LedgerCorruptionError):
        LedgerEvent.from_dict(payload)


def test_ledger_event_rejects_unknown_or_missing_fields(tmp_path):
    _, root, _, _ = _recorded(tmp_path)
    unknown = _event_payload(root)
    unknown["claims"] = ["not allowed"]
    with pytest.raises(LedgerCorruptionError):
        LedgerEvent.from_dict(unknown)

    missing = _event_payload(root)
    missing.pop("run_id")
    with pytest.raises(LedgerCorruptionError):
        LedgerEvent.from_dict(missing)


def test_same_packet_is_idempotent_and_keeps_one_event(tmp_path):
    root = tmp_path / "ledger"
    packet = _packet(tmp_path)
    ledger = DecisionLedger(root)

    first = ledger.record(packet, now=NOW)
    event_bytes = (root / "events.jsonl").read_bytes()
    pointer_bytes = (root / "latest" / f"{packet.kind}.json").read_bytes()
    second = ledger.record(packet, now=NOW)

    assert second == first
    assert (root / "events.jsonl").read_bytes() == event_bytes
    assert (root / "latest" / f"{packet.kind}.json").read_bytes() == pointer_bytes
    assert len(ledger.verify()) == 1


def test_same_packet_retry_repairs_missing_pointer_without_second_event(tmp_path):
    ledger, root, packet, packet_path = _recorded(tmp_path)
    journal_before = (root / "events.jsonl").read_bytes()
    (root / "latest" / f"{packet.kind}.json").unlink()

    assert ledger.record(packet, now=NOW) == packet_path
    assert (root / "events.jsonl").read_bytes() == journal_before
    assert len(ledger.verify()) == 1


@pytest.mark.parametrize("change", ["recommendation", "evidence"])
def test_same_id_changed_payload_collides_without_mutating_journal_or_pointer(
    tmp_path,
    change,
):
    ledger, root, packet, packet_path = _recorded(tmp_path)
    journal_before = (root / "events.jsonl").read_bytes()
    pointer_path = root / "latest" / f"{packet.kind}.json"
    pointer_before = pointer_path.read_bytes()
    object_before = packet_path.read_bytes()
    if change == "recommendation":
        changed = _packet(tmp_path, recommendation="request_more_research")
    else:
        changed = _packet(
            tmp_path,
            evidence_name="changed.json",
            evidence_payload=b'{"stance":"bearish"}',
        )

    with pytest.raises(PacketCollisionError):
        ledger.record(changed, now=NOW)

    assert (root / "events.jsonl").read_bytes() == journal_before
    assert pointer_path.read_bytes() == pointer_before
    assert packet_path.read_bytes() == object_before


def test_concurrent_distinct_records_allocate_contiguous_unique_sequences(tmp_path):
    root = tmp_path / "ledger"
    ledger = DecisionLedger(root)
    packets = [_packet(tmp_path, run_id=f"run-{index}") for index in range(12)]

    with ThreadPoolExecutor(max_workers=6) as executor:
        paths = list(executor.map(lambda packet: ledger.record(packet, now=NOW), packets))

    events = ledger.verify()
    assert len(set(paths)) == len(packets)
    assert [event.sequence for event in events] == list(range(1, 13))
    assert len({event.packet_id for event in events}) == 12
    assert len((root / "events.jsonl").read_bytes().splitlines()) == 12


def test_concurrent_same_packet_retries_create_one_object_and_event(tmp_path):
    root = tmp_path / "ledger"
    ledger = DecisionLedger(root)
    packet = _packet(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(
            executor.map(
                lambda _: ledger.record(packet, now=NOW),
                range(16),
            )
        )

    assert len(set(paths)) == 1
    assert len(list((root / "packets").iterdir())) == 1
    assert len((root / "events.jsonl").read_bytes().splitlines()) == 1
    assert len(ledger.verify()) == 1


def test_crash_after_packet_fsync_retries_orphan_object_cleanly(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "ledger"
    packet = _packet(tmp_path)
    ledger = DecisionLedger(root)

    def crash(_packet_path):
        raise RuntimeError("injected after packet fsync")

    monkeypatch.setattr(ledger, "_after_packet_fsync", crash)
    with pytest.raises(RuntimeError, match="after packet fsync"):
        ledger.record(packet, now=NOW)

    object_path = root / "packets" / f"{packet.packet_id}.json"
    assert object_path.read_bytes() == packet.canonical_json_bytes()
    assert not (root / "events.jsonl").exists()
    assert not (root / "latest" / f"{packet.kind}.json").exists()

    recovered = DecisionLedger(root)
    assert recovered.record(packet, now=NOW) == object_path
    assert [event.sequence for event in recovered.verify()] == [1]


def test_crash_after_event_fsync_rebuilds_pointer_without_duplicate(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "ledger"
    packet = _packet(tmp_path)
    ledger = DecisionLedger(root)

    def crash(_event):
        raise RuntimeError("injected after event fsync")

    monkeypatch.setattr(ledger, "_after_event_fsync", crash)
    with pytest.raises(RuntimeError, match="after event fsync"):
        ledger.record(packet, now=NOW)

    journal_before = (root / "events.jsonl").read_bytes()
    assert len(journal_before.splitlines()) == 1
    assert not (root / "latest" / f"{packet.kind}.json").exists()

    recovered = DecisionLedger(root)
    assert [event.sequence for event in recovered.rebuild()] == [1]
    assert len(recovered.verify()) == 1
    assert recovered.record(packet, now=NOW).is_file()
    assert (root / "events.jsonl").read_bytes() == journal_before


def test_historical_objects_verify_but_expired_new_admission_rejects(tmp_path):
    root = tmp_path / "ledger"
    ledger = DecisionLedger(root)
    historical = _packet(
        tmp_path,
        run_id="historical-run",
        now=HISTORICAL_NOW,
    )
    ledger.record(
        historical,
        now=HISTORICAL_NOW + dt.timedelta(minutes=1),
    )

    assert [event.packet_id for event in ledger.verify()] == [historical.packet_id]
    pointer_path = root / "latest" / f"{historical.kind}.json"
    pointer_path.unlink()
    assert [event.packet_id for event in ledger.rebuild()] == [historical.packet_id]

    expired_new = _packet(
        tmp_path,
        run_id="expired-new",
        now=HISTORICAL_NOW,
    )
    journal_before = (root / "events.jsonl").read_bytes()
    with pytest.raises(ValueError, match="packet expired"):
        ledger.record(
            expired_new,
            now=HISTORICAL_NOW + dt.timedelta(hours=3),
        )
    assert (root / "events.jsonl").read_bytes() == journal_before
    assert not root.joinpath("packets", f"{expired_new.packet_id}.json").exists()


def test_invalid_admission_does_not_create_ledger_root(tmp_path):
    root = tmp_path / "ledger"
    ledger = DecisionLedger(root)

    with pytest.raises(ValueError, match="packet must be a WorkPacket"):
        ledger.record(object())  # type: ignore[arg-type]

    assert not root.exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "mutated_packet",
        "truncated_packet",
        "missing_packet",
        "digest_mismatch",
        "sequence_gap",
        "malformed_line",
        "torn_final_line",
        "noncanonical_event",
        "mutated_evidence",
    ],
)
def test_journal_or_object_corruption_fails_closed(tmp_path, corruption):
    ledger, root, packet, packet_path = _recorded(tmp_path)
    journal_path = root / "events.jsonl"
    evidence_path = Path(packet.evidence_refs[0].path)
    if corruption == "mutated_packet":
        packet_path.write_bytes(packet_path.read_bytes() + b" ")
    elif corruption == "truncated_packet":
        packet_path.write_bytes(packet_path.read_bytes()[:32])
    elif corruption == "missing_packet":
        packet_path.unlink()
    elif corruption == "digest_mismatch":
        payload = _event_payload(root)
        payload["packet_sha256"] = "0" * 64
        journal_path.write_bytes(_canonical(payload) + b"\n")
    elif corruption == "sequence_gap":
        payload = _event_payload(root)
        payload["sequence"] = 2
        journal_path.write_bytes(_canonical(payload) + b"\n")
    elif corruption == "malformed_line":
        journal_path.write_bytes(b"{not-json}\n")
    elif corruption == "torn_final_line":
        journal_path.write_bytes(journal_path.read_bytes()[:-5])
    elif corruption == "noncanonical_event":
        payload = _event_payload(root)
        journal_path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    elif corruption == "mutated_evidence":
        evidence_path.write_bytes(b'{"stance":"mutated"}')

    journal_before = journal_path.read_bytes()
    pointer_before = (root / "latest" / f"{packet.kind}.json").read_bytes()
    with pytest.raises(LedgerCorruptionError):
        ledger.verify()
    with pytest.raises(LedgerCorruptionError):
        ledger.rebuild()
    assert journal_path.read_bytes() == journal_before
    assert (root / "latest" / f"{packet.kind}.json").read_bytes() == pointer_before


@pytest.mark.parametrize(
    "pointer_state",
    ["missing", "stale", "malformed", "extra_authority"],
)
def test_rebuild_repairs_derived_pointer_without_changing_journal_or_object(
    tmp_path,
    pointer_state,
):
    ledger, root, packet, packet_path = _recorded(tmp_path)
    pointer_path = root / "latest" / f"{packet.kind}.json"
    if pointer_state == "missing":
        pointer_path.unlink()
    elif pointer_state == "stale":
        payload = _pointer_payload(root)
        payload["packet_sha256"] = "0" * 64
        pointer_path.write_bytes(_canonical(payload))
    elif pointer_state == "malformed":
        pointer_path.write_bytes(b"{")
    elif pointer_state == "extra_authority":
        payload = _pointer_payload(root)
        payload["can_cancel_orders"] = True
        pointer_path.write_bytes(_canonical(payload))

    journal_before = (root / "events.jsonl").read_bytes()
    object_before = packet_path.read_bytes()
    with pytest.raises(LedgerCorruptionError):
        ledger.verify()

    events = ledger.rebuild()

    assert len(events) == 1
    assert (root / "events.jsonl").read_bytes() == journal_before
    assert packet_path.read_bytes() == object_before
    assert pointer_path.read_bytes() == _canonical(
        {
            "schema_version": 1,
            "sequence": 1,
            "packet_id": packet.packet_id,
            "kind": packet.kind,
            "packet_sha256": packet.payload_digest(),
            "journal_path": "events.jsonl",
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }
    )
    assert len(ledger.verify()) == 1


@pytest.mark.parametrize("managed_name", ["packets", "latest"])
def test_symlinked_managed_directory_is_rejected(tmp_path, managed_name):
    root = tmp_path / "ledger"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / managed_name)
    packet = _packet(tmp_path)

    with pytest.raises(LedgerCorruptionError, match="symlink"):
        DecisionLedger(root).record(packet, now=NOW)

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("managed_name", [".ledger.lock", "events.jsonl"])
def test_symlinked_managed_file_is_rejected(tmp_path, managed_name):
    root = tmp_path / "ledger"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    os.symlink(outside, root / managed_name)
    packet = _packet(tmp_path)

    with pytest.raises(LedgerCorruptionError, match="symlink"):
        DecisionLedger(root).record(packet, now=NOW)

    assert outside.read_bytes() == b"outside"


def test_symlinked_packet_object_and_pointer_are_rejected(tmp_path):
    ledger, root, packet, packet_path = _recorded(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_bytes(packet_path.read_bytes())
    packet_path.unlink()
    os.symlink(outside, packet_path)
    with pytest.raises(LedgerCorruptionError, match="symlink"):
        ledger.verify()

    packet_path.unlink()
    packet_path.write_bytes(outside.read_bytes())
    pointer_path = root / "latest" / f"{packet.kind}.json"
    outside_pointer = tmp_path / "outside-pointer.json"
    outside_pointer.write_bytes(pointer_path.read_bytes())
    pointer_path.unlink()
    os.symlink(outside_pointer, pointer_path)
    with pytest.raises(LedgerCorruptionError, match="symlink"):
        ledger.verify()


def test_rebuild_preserves_unknown_latest_path(tmp_path):
    ledger, root, _, _ = _recorded(tmp_path)
    unknown = root / "latest" / "operator-note.txt"
    unknown.write_bytes(b"do not touch")

    ledger.rebuild()

    assert unknown.read_bytes() == b"do not touch"


def test_rebuild_removes_stale_allowed_kind_pointer_without_event(tmp_path):
    ledger, root, _, _ = _recorded(tmp_path)
    stale = root / "latest" / "risk_review.json"
    stale.write_bytes(b"stale")

    ledger.rebuild()

    assert not stale.exists()


def test_replay_accepts_exact_duplicate_event_and_rebuilds_last_pointer(tmp_path):
    ledger, root, packet, _ = _recorded(tmp_path)
    first = ledger.verify()[0]
    duplicate = dataclasses.replace(first, sequence=2)
    journal_path = root / "events.jsonl"
    journal_path.write_bytes(
        journal_path.read_bytes() + duplicate.canonical_json_bytes() + b"\n"
    )

    events = ledger.rebuild()

    assert [event.sequence for event in events] == [1, 2]
    assert _pointer_payload(root)["sequence"] == 2
    assert _pointer_payload(root)["packet_id"] == packet.packet_id


def test_repeated_packet_id_with_changed_material_event_is_corruption(tmp_path):
    ledger, root, _, _ = _recorded(tmp_path)
    first = ledger.verify()[0]
    changed = dataclasses.replace(
        first,
        sequence=2,
        packet_sha256="0" * 64,
    )
    journal_path = root / "events.jsonl"
    journal_path.write_bytes(
        journal_path.read_bytes() + changed.canonical_json_bytes() + b"\n"
    )

    with pytest.raises(LedgerCorruptionError):
        ledger.verify()
