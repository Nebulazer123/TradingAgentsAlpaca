"""C6: snapshot / verify / restore of safety state."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from tradingagents.policy import snapshots

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _seed(tmp_path: Path) -> tuple[Path, Path]:
    control = tmp_path / "live_control.json"
    control.write_text('{"frozen": false}')
    control.with_name("live_control.json.integrity.json").write_text('{"sha256": "abc"}')
    envelope = tmp_path / "risk_envelope.yaml"
    envelope.write_text("tiny_live_tranche_usd: 25.00\n")
    return control, envelope


def test_snapshot_captures_files_and_manifest(tmp_path: Path) -> None:
    control, envelope = _seed(tmp_path)
    dest_root = tmp_path / "snaps"
    snap = snapshots.snapshot_state(
        sources=(str(control), str(envelope)), dest_root=dest_root, now=NOW
    )
    assert snap.name == "20260715T120000Z"
    manifest = json.loads((snap / "manifest.json").read_text())
    assert "live_control.json" in manifest["files"]
    assert "live_control.json.integrity.json" in manifest["files"]  # sidecar captured
    assert "risk_envelope.yaml" in manifest["files"]
    assert snapshots.verify_snapshot(snap) == []


def test_verify_detects_tampered_snapshot(tmp_path: Path) -> None:
    control, envelope = _seed(tmp_path)
    snap = snapshots.snapshot_state(sources=(str(control),), dest_root=tmp_path / "s", now=NOW)
    (snap / "live_control.json").write_text('{"frozen": true}')  # tamper the snapshot copy
    issues = snapshots.verify_snapshot(snap)
    assert any("checksum mismatch" in i for i in issues)


def test_restore_is_dry_run_by_default(tmp_path: Path) -> None:
    control, _ = _seed(tmp_path)
    snap = snapshots.snapshot_state(sources=(str(control),), dest_root=tmp_path / "s", now=NOW)
    control.write_text('{"frozen": true, "changed": true}')  # drift the live file
    report = snapshots.restore_state(snap)  # default dry-run
    assert report.dry_run is True
    assert json.loads(control.read_text())["changed"] is True  # unchanged by dry-run


def test_restore_with_confirm_rewrites_original(tmp_path: Path) -> None:
    control, _ = _seed(tmp_path)
    snap = snapshots.snapshot_state(sources=(str(control),), dest_root=tmp_path / "s", now=NOW)
    control.write_text('{"frozen": true, "changed": true}')
    report = snapshots.restore_state(snap, dry_run=False, confirm=True)
    assert report.dry_run is False and report.verified is True
    assert json.loads(control.read_text()) == {"frozen": False}  # restored original


def test_restore_refuses_on_bad_checksum(tmp_path: Path) -> None:
    control, _ = _seed(tmp_path)
    snap = snapshots.snapshot_state(sources=(str(control),), dest_root=tmp_path / "s", now=NOW)
    (snap / "live_control.json").write_text('{"frozen": true}')  # corrupt the snapshot
    report = snapshots.restore_state(snap, dry_run=False, confirm=True)
    assert report.verified is False
    assert report.restored == []
