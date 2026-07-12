"""Analysis-only evidence packets for controller-style automations."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

UTC = dt.timezone.utc

CONTROLLER_ROLES = {
    "tradingagents-automation-wake-controller": {
        "role": "wake_controller",
        "file_prefix": "wake-controller",
    },
    "tradingagents-wake-verification": {
        "role": "wake_verification",
        "file_prefix": "wake-verification",
    },
    "tradingagents-automation-sleep-controller": {
        "role": "sleep_controller",
        "file_prefix": "sleep-controller",
    },
}
FORBIDDEN_EFFECTS = [
    "submit_order",
    "send_email",
    "edit_repo_files",
    "mutate_goals",
]


def _stamp(now: dt.datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%d-%H%M%S")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _status_counts(automation_root: Path) -> dict[str, int]:
    counts = {
        "managed_automation_count": 0,
        "active_count": 0,
        "paused_count": 0,
        "unknown_status_count": 0,
    }
    for config_path in sorted(automation_root.glob("*/automation.toml")):
        config = _read_toml(config_path)
        if not config:
            continue
        counts["managed_automation_count"] += 1
        status = str(config.get("status") or "").upper()
        if status == "ACTIVE":
            counts["active_count"] += 1
        elif status == "PAUSED":
            counts["paused_count"] += 1
        else:
            counts["unknown_status_count"] += 1
    return counts


def build_control_plane_patrol_packet(
    *,
    repo_root: Path,
    automation_root: Path,
    automation_id: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    controller = CONTROLLER_ROLES.get(automation_id)
    if controller is None:
        allowed = ", ".join(sorted(CONTROLLER_ROLES))
        raise ValueError(f"unsupported controller automation_id {automation_id!r}; expected one of: {allowed}")

    generated_at = (now or dt.datetime.now(UTC)).astimezone(UTC)
    summary_path = Path("results/_context/latest-summary.json")
    flags_path = Path("results/_context/latest-flags.json")
    counts = _status_counts(automation_root)

    return {
        "schema_version": 1,
        "kind": "tradingagents_control_plane_patrol",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "automation_id": automation_id,
        "controller_role": controller["role"],
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "submitted_count": 0,
        "issue_count": 0,
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "context_summary_path": str(summary_path).replace("\\", "/"),
        "context_summary_exists": (repo_root / summary_path).exists(),
        "context_flags_path": str(flags_path).replace("\\", "/"),
        "context_flags_exists": (repo_root / flags_path).exists(),
        "automation_root_path": str(automation_root),
        **counts,
        "next_action": (
            "Use this packet as controller schedule evidence only; it does not "
            "authorize orders, emails, goal mutation, or repo/source edits."
        ),
    }


def write_control_plane_patrol_packet(
    *,
    repo_root: Path,
    automation_root: Path,
    automation_id: str,
    output_dir: Path,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    packet = build_control_plane_patrol_packet(
        repo_root=repo_root,
        automation_root=automation_root,
        automation_id=automation_id,
        now=now,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.fromisoformat(str(packet["generated_at"]))
    file_prefix = str(CONTROLLER_ROLES[automation_id]["file_prefix"])
    path = output_dir / f"{file_prefix}-patrol-{_stamp(generated_at)}.json"
    packet["json_path"] = str(path)
    text = json.dumps(packet, indent=2)
    path.write_text(text, encoding="utf-8")
    latest_path = output_dir / f"{file_prefix}-latest.json"
    try:
        shutil.copyfile(path, latest_path)
    except OSError:
        latest_path.write_text(text, encoding="utf-8")
    packet["latest_path"] = str(latest_path)
    latest_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return packet
