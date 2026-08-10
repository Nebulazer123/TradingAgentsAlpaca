"""Analysis-only evidence packet for the TradingAgents night-shift patrol."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

UTC = dt.timezone.utc

NIGHT_SHIFT_AUTOMATION_ID = "tradingagents-night-shift-supervisor"
FORBIDDEN_EFFECTS = [
    "submit_order",
    "send_email",
    "modify_automation_status",
    "edit_repo_files",
    "mutate_goals",
]


def _stamp(now: dt.datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%d-%H%M%S")


def build_night_shift_patrol_packet(
    *,
    repo_root: Path,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    generated_at = (now or dt.datetime.now(UTC)).astimezone(UTC)
    summary_path = Path("results/_context/latest-summary.json")
    flags_path = Path("results/_context/latest-flags.json")
    recent_deltas_path = Path("results/_context/recent-deltas.md")

    flag_count = 0
    flag_labels: list[str] = []
    full_flags_path = repo_root / flags_path
    if full_flags_path.exists():
        try:
            data = json.loads(full_flags_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        flags = data.get("flags") if isinstance(data, dict) else []
        if isinstance(flags, list):
            flag_count = len(flags)
            flag_labels = [
                str(item.get("label"))
                for item in flags
                if isinstance(item, dict) and item.get("label")
            ][:12]

    return {
        "schema_version": 1,
        "kind": "tradingagents_night_shift_patrol",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "automation_id": NIGHT_SHIFT_AUTOMATION_ID,
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "submitted_count": 0,
        "issue_count": 0,
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "context_summary_path": str(summary_path).replace("\\", "/"),
        "context_summary_exists": (repo_root / summary_path).exists(),
        "context_flags_path": str(flags_path).replace("\\", "/"),
        "context_flags_exists": full_flags_path.exists(),
        "context_flag_count": flag_count,
        "context_flag_labels": flag_labels,
        "recent_deltas_path": str(recent_deltas_path).replace("\\", "/"),
        "recent_deltas_exists": (repo_root / recent_deltas_path).exists(),
        "next_action": (
            "Use compact context flags to decide which regular automation should handle "
            "the next issue; do not trade, email, mutate automation status, or edit repo files."
        ),
    }


def write_night_shift_patrol_packet(
    *,
    repo_root: Path,
    output_dir: Path,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    packet = build_night_shift_patrol_packet(repo_root=repo_root, now=now)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.fromisoformat(str(packet["generated_at"]))
    path = output_dir / f"night-shift-patrol-{_stamp(generated_at)}.json"
    packet["json_path"] = str(path)
    text = json.dumps(packet, indent=2)
    path.write_text(text, encoding="utf-8")
    latest_path = output_dir / "latest.json"
    try:
        shutil.copyfile(path, latest_path)
    except OSError:
        latest_path.write_text(text, encoding="utf-8")
    packet["latest_path"] = str(latest_path)
    latest_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return packet
