#!/usr/bin/env python3
"""Guarded MiroFish model-env switch helper.

Default mode is read-only. Applying the recommended model route requires both
``--apply`` and an exact confirmation phrase, and writes a timestamped backup.
This helper never starts MiroFish, never calls LLM APIs, and never prints keys.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = ROOT / ".env"
CONFIRM_SWITCH = "switch-mirofish-models"
CONFIRM_RESTORE = "restore-mirofish-env"

RECOMMENDED = {
    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
    "LLM_MODEL_NAME": "qwen/qwen3.6-plus",
    "LLM_BOOST_BASE_URL": "https://openrouter.ai/api/v1",
    "LLM_BOOST_MODEL_NAME": "deepseek/deepseek-v4-pro",
}


def read_env(path: Path) -> Tuple[List[str], Dict[str, str]]:
    if not path.exists():
        return [], {}

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    env: Dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return lines, env


def build_changes(env: Dict[str, str]) -> List[Dict[str, str]]:
    changes: List[Dict[str, str]] = []
    for key, target in RECOMMENDED.items():
        current = env.get(key, "")
        changes.append({
            "key": key,
            "current": current,
            "recommended": target,
            "status": "ok" if current == target else "pending",
        })
    return changes


def update_lines(lines: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen = set()

    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in RECOMMENDED:
                output.append(f"{key}={RECOMMENDED[key]}")
                seen.add(key)
                continue
        output.append(raw)

    missing = [key for key in RECOMMENDED if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# MiroFish approved run model route")
        for key in missing:
            output.append(f"{key}={RECOMMENDED[key]}")

    return output


def backup_path(env_path: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return env_path.with_name(f"{env_path.name}.mirofish-backup-{stamp}")


def print_text(result: Dict[str, object]) -> None:
    print(f"Env file: {result['env_file']}")
    print(f"Mode: {result['mode']}")
    print("Recommended route:")
    for change in result["changes"]:  # type: ignore[index]
        marker = "ok" if change["status"] == "ok" else "pending"
        print(
            f"- {change['key']}: {change['current'] or '<missing>'} -> "
            f"{change['recommended']} ({marker})"
        )
    if result.get("backup"):
        print(f"Backup: {result['backup']}")
    print(f"Stage 03 gate: {result['stage03_gate']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded MiroFish env model switch helper.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Write recommended model route.")
    parser.add_argument("--confirm", default="", help=f"Required phrase: {CONFIRM_SWITCH}")
    parser.add_argument("--restore", type=Path, help="Restore .env from a backup file.")
    args = parser.parse_args()

    env_path = args.env_file.resolve()

    if args.restore:
        restore_path = args.restore.resolve()
        if args.confirm != CONFIRM_RESTORE:
            print(f"Restore requires --confirm {CONFIRM_RESTORE!r}", file=sys.stderr)
            return 2
        if not restore_path.exists():
            print(f"Backup not found: {restore_path}", file=sys.stderr)
            return 2
        env_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(restore_path, env_path)
        result = {
            "mode": "restore",
            "env_file": str(env_path),
            "restored_from": str(restore_path),
            "stage03_gate": "still closed; restore does not approve or start simulation",
        }
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"Restored {env_path} from {restore_path}")
        return 0

    lines, env = read_env(env_path)
    changes = build_changes(env)
    result: Dict[str, object] = {
        "mode": "preview",
        "env_file": str(env_path),
        "changes": changes,
        "all_recommended": all(change["status"] == "ok" for change in changes),
        "stage03_gate": "closed; this helper only previews or applies model routing",
    }

    if args.apply:
        if args.confirm != CONFIRM_SWITCH:
            print(f"Apply requires --confirm {CONFIRM_SWITCH!r}", file=sys.stderr)
            return 2
        backup = backup_path(env_path)
        if env_path.exists():
            shutil.copy2(env_path, backup)
        else:
            backup.write_text("", encoding="utf-8")
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(update_lines(lines)) + "\n", encoding="utf-8")
        _, new_env = read_env(env_path)
        result.update({
            "mode": "apply",
            "backup": str(backup),
            "changes": build_changes(new_env),
            "all_recommended": True,
            "stage03_gate": "closed; refresh backend and run app-path stage 01/02 checks before stage 03 approval",
        })

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
