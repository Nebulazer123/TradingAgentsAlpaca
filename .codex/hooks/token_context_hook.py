from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from tradingagents.orchestration.token_context import (
    classify_pre_tool_use_warning,
    classify_raw_context_need,
    load_compact_context,
)


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


def main() -> int:
    payload = _read_payload()
    event = _detect_event(payload)
    # Lifecycle events describe a conversation, not a runtime input change.
    # Source work needs no snapshot, status recap, or hook receipt.
    if event != "PreToolUse":
        return 0
    repo_root = Path.cwd()
    compact = load_compact_context(repo_root)
    decision = classify_raw_context_need(compact.flags)
    warning = classify_pre_tool_use_warning(payload, decision=decision)
    if warning.should_warn:
        print(warning.guidance or "Use relevant compact context before broad raw-packet reads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
