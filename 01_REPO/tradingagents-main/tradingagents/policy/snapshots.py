"""C6: checksum-verified snapshots of the safety-critical control-plane files.

``snapshot_state`` copies the two money-gating JSONs (and the risk envelope) plus
their integrity sidecars into a timestamped folder with a sha256 manifest.
``restore_state`` verifies the manifest before writing anything and is dry-run by
default (a real restore needs ``confirm=True``). This is disaster recovery, not an
order path: nothing here can trade, and restore refuses on a checksum mismatch.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc

DEFAULT_SNAPSHOT_SOURCES: tuple[str, ...] = (
    "results/policy/live_control.json",
    "results/policy/promotion_state.json",
    "config/risk_envelope.yaml",
)
MANIFEST_NAME = "manifest.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class RestoreReport:
    dry_run: bool
    verified: bool
    issues: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)


def _sidecar_name(name: str) -> str:
    return f"{name}.integrity.json"


def snapshot_state(
    *,
    sources: tuple[str, ...] = DEFAULT_SNAPSHOT_SOURCES,
    dest_root: str | Path = "results/policy/snapshots",
    now: datetime.datetime | None = None,
    label: str | None = None,
) -> Path:
    """Copy existing safety files + sidecars into a timestamped, checksummed folder."""

    current = now or datetime.datetime.now(tz=UTC)
    stamp = current.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    if label:
        stamp = f"{stamp}-{label}"
    dest = Path(dest_root) / stamp
    dest.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "created_at": current.astimezone(UTC).isoformat(timespec="seconds"),
        "files": {},
    }
    files: dict[str, dict[str, str]] = {}
    for source in sources:
        src_path = Path(source)
        if not src_path.exists():
            continue
        for path in (src_path, src_path.with_name(_sidecar_name(src_path.name))):
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            atomic_write_text(dest / path.name, text)
            files[path.name] = {
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "original_path": str(path),
            }
    manifest["files"] = files
    atomic_write_text(dest / MANIFEST_NAME, json.dumps(manifest, indent=2))
    return dest


def verify_snapshot(snapshot_dir: str | Path) -> list[str]:
    """Return issues if any snapshot file's checksum no longer matches the manifest."""

    root = Path(snapshot_dir)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        return [f"snapshot manifest missing at {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"snapshot manifest is invalid JSON: {exc}"]

    issues: list[str] = []
    for name, meta in (manifest.get("files") or {}).items():
        path = root / name
        if not path.exists():
            issues.append(f"snapshot file missing: {name}")
            continue
        if _sha256_file(path) != str(meta.get("sha256")):
            issues.append(f"snapshot file checksum mismatch: {name}")
    return issues


def restore_state(
    snapshot_dir: str | Path,
    *,
    dry_run: bool = True,
    confirm: bool = False,
) -> RestoreReport:
    """Verify the snapshot, then (only if not dry_run and confirm) write files back."""

    root = Path(snapshot_dir)
    issues = verify_snapshot(root)
    verified = not issues
    if not verified:
        return RestoreReport(dry_run=dry_run, verified=False, issues=issues)

    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    if dry_run or not confirm:
        return RestoreReport(
            dry_run=True, verified=True,
            restored=[str(meta.get("original_path")) for meta in files.values()],
        )

    restored: list[str] = []
    for name, meta in files.items():
        original = meta.get("original_path")
        if not original:
            continue
        text = (root / name).read_text(encoding="utf-8")
        atomic_write_text(Path(original), text)
        restored.append(str(original))
    return RestoreReport(dry_run=False, verified=True, restored=restored)
