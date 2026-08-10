from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tradingagents.orchestration.token_context import (
    classify_pre_tool_use_warning,
    classify_raw_context_need,
    load_compact_context,
    write_hook_event,
)

SNAPSHOT_EVENTS = {"SessionStart", "SubagentStart", "PostCompact", "Stop"}


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_stdin_prefix": raw[:300], "parse_error": "json_decode_failed"}
    return payload if isinstance(payload, dict) else {"payload_type": type(payload).__name__}


def _detect_event(payload: dict[str, Any]) -> str:
    hook = payload.get("hook")
    hook_payload = hook if isinstance(hook, dict) else {}
    return str(
        os.environ.get("CODEX_HOOK_EVENT")
        or payload.get("hook_event_name")
        or payload.get("hookEventName")
        or payload.get("hook_event")
        or payload.get("event")
        or payload.get("event_name")
        or hook_payload.get("event")
        or hook_payload.get("name")
        or "unknown"
    )


def _run_snapshot(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            [sys.executable, "scripts/automation_context_snapshot.py", "--write"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=25,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - hook defensive boundary
        return f"snapshot_error={exc}"
    if completed.returncode:
        return f"snapshot_exit={completed.returncode}"
    return "snapshot=refreshed"


def main() -> int:
    payload = _read_payload()
    event = _detect_event(payload)
    repo_root = Path.cwd()
    snapshot_status = _run_snapshot(repo_root) if event in SNAPSHOT_EVENTS else "snapshot=skipped"
    compact = load_compact_context(repo_root)
    decision = classify_raw_context_need(compact.flags)
    pre_tool_warning = classify_pre_tool_use_warning(payload, decision=decision) if event == "PreToolUse" else None
    out_path = write_hook_event(
        repo_root,
        event=str(event),
        payload=payload,
        decision=decision,
        pre_tool_warning=pre_tool_warning,
    )
    print(f"TradingAgents hook: {event}")
    print(snapshot_status)
    print(f"raw_context_required={decision.required}; reasons={','.join(decision.reasons) or 'none'}")
    if pre_tool_warning and pre_tool_warning.should_warn:
        print(f"pre_tool_warning=warning_only; reasons={','.join(pre_tool_warning.reasons)}")
        print(pre_tool_warning.guidance or "Use compact context before raw packets.")
    print(f"event_packet={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
