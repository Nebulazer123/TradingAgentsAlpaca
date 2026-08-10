"""Compact context helpers for Codex hooks and lightweight runners."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_KEY_PARTS = ("api_key", "apikey", "secret", "token", "password", "bearer")
RAW_CONTEXT_REASONS = {
    "actions",
    "submitted",
    "blocker",
    "issues",
    "stale",
    "graph_failure",
    "candidate_change",
    "changed_candidates",
    "changed_tournament_leader",
    "schema",
    "quality",
    "model_telemetry",
    "crawler",
    "notify",
    "abnormal_pl",
    "unexplained_action",
}


@dataclass(frozen=True)
class CompactContext:
    repo_root: Path
    summary_path: Path
    flags_path: Path
    summary: dict[str, Any]
    flags: dict[str, Any]


@dataclass(frozen=True)
class RawContextDecision:
    required: bool
    reasons: list[str]
    paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "reasons": self.reasons,
            "paths": self.paths,
        }


@dataclass(frozen=True)
class PreToolUseWarning:
    warning_only: bool
    should_warn: bool
    block_execution: bool
    reasons: list[str]
    command_excerpt: str | None
    guidance: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "warning_only": self.warning_only,
            "should_warn": self.should_warn,
            "block_execution": self.block_execution,
            "reasons": self.reasons,
            "command_excerpt": self.command_excerpt,
            "guidance": self.guidance,
        }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_compact_context(repo_root: str | Path) -> CompactContext:
    root = Path(repo_root)
    context_dir = root / "results" / "_context"
    summary_path = context_dir / "latest-summary.json"
    flags_path = context_dir / "latest-flags.json"
    return CompactContext(
        repo_root=root,
        summary_path=summary_path,
        flags_path=flags_path,
        summary=_read_json(summary_path),
        flags=_read_json(flags_path),
    )


def classify_raw_context_need(flags: Mapping[str, Any]) -> RawContextDecision:
    reasons: list[str] = []
    paths: list[str] = []

    def add(reason: str, path: str | None = None) -> None:
        if reason not in RAW_CONTEXT_REASONS:
            return
        if reason not in reasons:
            reasons.append(reason)
        if path and path not in paths:
            paths.append(path)

    flag_items = flags.get("flags")
    if isinstance(flag_items, list):
        for item in flag_items:
            if not isinstance(item, Mapping):
                continue
            reason = str(item.get("reason") or "")
            path = item.get("path")
            add(reason, str(path) if path else None)
    else:
        for key, value in flags.items():
            if value:
                add(str(key))

    return RawContextDecision(required=bool(reasons), reasons=reasons, paths=paths)


def _normalize_command_text(command: str) -> str:
    return command.lower().replace("\\", "/")


def _extract_tool_command(payload: Mapping[str, Any]) -> str | None:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input")
    if isinstance(tool_input, Mapping):
        for key in ("cmd", "command", "shell_command", "script"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        args = tool_input.get("args")
        if isinstance(args, list) and all(isinstance(item, str) for item in args):
            return " ".join(args).strip()
    for key in ("cmd", "command", "shell_command"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _path_in_command(path: str, normalized_command: str) -> bool:
    normalized_path = path.lower().replace("\\", "/")
    return normalized_path in normalized_command


def classify_pre_tool_use_warning(
    payload: Mapping[str, Any],
    *,
    decision: RawContextDecision,
) -> PreToolUseWarning:
    command = _extract_tool_command(payload)
    command_excerpt, _ = _compact_text(command, limit=240)
    if not command:
        return PreToolUseWarning(
            warning_only=True,
            should_warn=False,
            block_execution=False,
            reasons=[],
            command_excerpt=None,
            guidance=None,
        )

    normalized = _normalize_command_text(command)
    if "scripts/automation_context_snapshot.py" in normalized and "--write" in normalized:
        return PreToolUseWarning(
            warning_only=True,
            should_warn=False,
            block_execution=False,
            reasons=[],
            command_excerpt=command_excerpt,
            guidance=None,
        )
    if any(_path_in_command(path, normalized) for path in decision.paths):
        return PreToolUseWarning(
            warning_only=True,
            should_warn=False,
            block_execution=False,
            reasons=[],
            command_excerpt=command_excerpt,
            guidance=None,
        )

    reasons: list[str] = []

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if "deep-research-report" in normalized:
        add("deep_research_report")
    if ".env" in normalized:
        add("env_file")
    if "/automations/" in normalized and "memory.md" in normalized:
        add("automation_memory")
    if "rg " in normalized and " results" in normalized:
        add("broad_results_search")
    if "results/" in normalized and ".json" in normalized and "results/_context/" not in normalized:
        add("raw_context_packet_read")
    if "results/" in normalized and not reasons and any(
        token in normalized for token in ("get-childitem", "dir ", "ls ", "rg ")
    ):
        add("broad_results_read")

    guidance = None
    if reasons:
        guidance = (
            "Warning only: start from results/_context/latest-summary.json and latest-flags.json; "
            "open raw packets only when compact flags name a reason or exact path."
        )

    return PreToolUseWarning(
        warning_only=True,
        should_warn=bool(reasons),
        block_execution=False,
        reasons=reasons,
        command_excerpt=command_excerpt,
        guidance=guidance,
    )


def redact_hook_payload(payload: Any, *, key_hint: str = "") -> Any:
    lower_key = key_hint.lower()
    if any(part in lower_key for part in SECRET_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(payload, Mapping):
        return {str(key): redact_hook_payload(value, key_hint=str(key)) for key, value in payload.items()}
    if isinstance(payload, list):
        redacted = [redact_hook_payload(item, key_hint=key_hint) for item in payload[:25]]
        if len(payload) > 25:
            redacted.append(f"...[{len(payload) - 25} more omitted]")
        return redacted
    if isinstance(payload, str):
        lower_value = payload.lower()
        if any(part in lower_value for part in SECRET_KEY_PARTS):
            return "[REDACTED]"
        if len(payload) > 300:
            return payload[:300] + "...[truncated]"
        return payload
    return payload


def _compact_text(value: Any, *, limit: int = 240) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    text = str(value).strip()
    if not text:
        return None, False
    if len(text) <= limit:
        return text, False
    return text[:limit] + "...[truncated]", True


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def compact_hook_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract tiny goal/thread/subagent metadata from a hook payload."""
    goal = _mapping(payload.get("goal"))
    subagent = _mapping(payload.get("subagent") or payload.get("agent"))
    run = _mapping(payload.get("run"))
    thread = _mapping(payload.get("thread"))
    objective_excerpt, objective_truncated = _compact_text(
        goal.get("objective") or payload.get("goal_objective") or payload.get("objective")
    )
    return {
        "thread_id": payload.get("thread_id") or thread.get("id"),
        "goal_status": goal.get("status") or payload.get("goal_status"),
        "goal_objective_excerpt": objective_excerpt,
        "goal_objective_truncated": objective_truncated,
        "agent_id": subagent.get("id") or payload.get("agent_id"),
        "agent_name": subagent.get("name") or payload.get("agent_name"),
        "agent_role": subagent.get("role") or payload.get("agent_role"),
        "run_id": run.get("id") or payload.get("run_id"),
    }


def write_hook_event(
    repo_root: str | Path,
    *,
    event: str,
    payload: Mapping[str, Any],
    decision: RawContextDecision | None = None,
    pre_tool_warning: PreToolUseWarning | None = None,
) -> Path:
    root = Path(repo_root)
    compact = load_compact_context(root)
    raw_decision = decision or classify_raw_context_need(compact.flags)
    out_dir = root / "results" / "_context" / "hook-events"
    out_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    packet = {
        "schema_version": 1,
        "event": event,
        "created_at": created.isoformat(),
        "cwd": str(root),
        "summary_path": str(compact.summary_path),
        "flags_path": str(compact.flags_path),
        "summary_generated_at": compact.summary.get("generated_at"),
        "raw_context": raw_decision.to_dict(),
        "hook_context": compact_hook_context(payload),
        "pre_tool_warning": pre_tool_warning.to_dict() if pre_tool_warning else None,
        "payload_keys": sorted(str(key) for key in payload),
        "payload_sample": redact_hook_payload(dict(payload)),
    }
    out_path = out_dir / f"hook-event-{created.strftime('%Y%m%d-%H%M%S-%f')}.json"
    out_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    latest_packet = dict(packet)
    latest_packet["packet_path"] = str(out_path)
    (out_dir / "latest.json").write_text(json.dumps(latest_packet, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
