"""Analysis-only rollup planning for large Codex automation memories."""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from tradingagents.evals.automation_health_audit import default_automation_root

UTC = datetime.timezone.utc

DEFAULT_AUTOMATION_ROOT = default_automation_root()
DEFAULT_OUTPUT_DIR = Path("results/token_efficiency")
DEFAULT_ARCHIVE_DIR = DEFAULT_OUTPUT_DIR / "automation_memory_archives"


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _approx_tokens(byte_count: int) -> int:
    return max(1, round(byte_count / 4))


def discover_automation_memory_paths(root: str | Path = DEFAULT_AUTOMATION_ROOT) -> list[Path]:
    automation_root = Path(root)
    if not automation_root.exists():
        return []
    return sorted(
        (path for path in automation_root.glob("*/memory.md") if path.is_file()),
        key=lambda path: path.as_posix().lower(),
    )


def _memory_metric(
    path: Path,
    *,
    automation_root: Path,
    archive_root: Path,
    max_tail_lines: int,
    candidate_bytes: int,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    tail_lines = lines[-max_tail_lines:] if max_tail_lines > 0 else []
    byte_count = path.stat().st_size
    try:
        automation_id = path.parent.relative_to(automation_root).as_posix()
    except ValueError:
        automation_id = path.parent.name
    candidate = byte_count >= candidate_bytes
    archive_path = archive_root / automation_id / f"memory-archive-{datetime.datetime.now(tz=UTC).strftime('%Y%m%d')}.md"
    return {
        "automation_id": automation_id,
        "path": str(path),
        "exists": True,
        "bytes": byte_count,
        "kb": round(byte_count / 1024, 1),
        "approx_tokens": _approx_tokens(byte_count),
        "line_count": len(lines),
        "last_modified_utc": datetime.datetime.fromtimestamp(
            path.stat().st_mtime, tz=UTC
        ).isoformat(timespec="seconds"),
        "full_sha256": _sha256_text(text),
        "tail_line_count": len(tail_lines),
        "tail_sha256": _sha256_text("\n".join(tail_lines)),
        "suggested_action": "rollup_candidate" if candidate else "keep_as_is",
        "proposed_archive_path": str(archive_path),
        "proposed_retained_tail_lines": max_tail_lines,
        "mutation_required": candidate,
    }


def build_automation_memory_rollup_plan(
    *,
    automation_root: str | Path = DEFAULT_AUTOMATION_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_DIR,
    max_tail_lines: int = 80,
    candidate_kb: int = 64,
    memory_paths: list[Path] | None = None,
) -> dict[str, Any]:
    root = Path(automation_root)
    archive = Path(archive_root)
    paths = memory_paths if memory_paths is not None else discover_automation_memory_paths(root)
    candidate_bytes = candidate_kb * 1024
    memories = [
        _memory_metric(
            path,
            automation_root=root,
            archive_root=archive,
            max_tail_lines=max_tail_lines,
            candidate_bytes=candidate_bytes,
        )
        for path in paths
    ]
    memories.sort(key=lambda item: item["bytes"], reverse=True)
    candidates = [item for item in memories if item["suggested_action"] == "rollup_candidate"]
    total_bytes = sum(item["bytes"] for item in memories)
    candidate_bytes_total = sum(item["bytes"] for item in candidates)
    return {
        "kind": "automation_memory_rollup_plan",
        "schema_version": 1,
        "generated_at": _now_iso(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "automation_root": str(root),
        "archive_root": str(archive),
        "candidate_threshold_kb": candidate_kb,
        "retained_tail_policy": {
            "tail_lines": max_tail_lines,
            "raw_history_policy": "archive first; keep only digest plus retained tail in live memory after explicit operator approval",
            "default_reader_policy": "read results/_context/latest-summary.json and latest-flags.json before any raw automation memory",
        },
        "mutation_mode": "dry_run_only",
        "apply_required_for_mutation": True,
        "forbidden_effects": [
            "submit_orders",
            "refresh_dead_man",
            "change_live_authority",
            "change_automation_status",
            "edit_credentials",
            "delete_history",
            "mutate_automation_memory_without_operator_approval",
        ],
        "summary": {
            "memory_count": len(memories),
            "rollup_candidate_count": len(candidates),
            "total_bytes": total_bytes,
            "total_approx_tokens": _approx_tokens(total_bytes),
            "candidate_bytes": candidate_bytes_total,
            "candidate_approx_tokens": _approx_tokens(candidate_bytes_total)
            if candidate_bytes_total
            else 0,
        },
        "memories": memories,
        "recommendations": [
            "Keep automation readers on compact context by default.",
            "For rollup candidates, archive full memory, replace live memory with a digest plus retained tail only after explicit approval.",
            "Never let hooks or n8n mutate automation memories; they may write/read this plan packet only.",
        ],
    }


def _compact_memory_text(
    *,
    original_text: str,
    metric: dict[str, Any],
    archive_path: Path,
    max_tail_lines: int,
) -> str:
    lines = original_text.splitlines()
    tail = lines[-max_tail_lines:] if max_tail_lines > 0 else []
    header = [
        "# Automation Memory Rollup Digest",
        "",
        "This live memory was compacted by the TradingAgents automation memory",
        "rollup tool. Full history was archived before this file was replaced.",
        "",
        f"- Automation: {metric['automation_id']}",
        f"- Original path: {metric['path']}",
        f"- Archive path: {archive_path}",
        f"- Original bytes: {metric['bytes']}",
        f"- Original approx tokens: {metric['approx_tokens']}",
        f"- Original line count: {metric['line_count']}",
        f"- Original sha256: {metric['full_sha256']}",
        f"- Retained tail lines: {len(tail)}",
        "",
        "## Reader Policy",
        "",
        "- Start with `results/_context/latest-summary.json` and `latest-flags.json`.",
        "- Open the archive only when debugging this exact automation history.",
        "- Do not infer trading authority from this memory file.",
        "",
        "## Retained Tail",
        "",
    ]
    return "\n".join(header + tail) + "\n"


def apply_automation_memory_rollup_plan(
    packet: dict[str, Any],
    *,
    confirm_apply: bool = False,
) -> dict[str, Any]:
    """Archive and compact rollup candidates from a prebuilt dry-run packet.

    This mutates automation memory files only when ``confirm_apply`` is true.
    The packet itself remains analysis-only/no-order-authority; this function is
    for operator-approved maintenance and does not trade or touch automation
    status, schedules, prompts, credentials, or live-control state.
    """

    if not confirm_apply:
        raise ValueError("confirm_apply=True is required to mutate automation memories")

    results: list[dict[str, Any]] = []
    for metric in packet.get("memories", []):
        if metric.get("suggested_action") != "rollup_candidate":
            continue
        memory_path = Path(metric["path"])
        archive_path = Path(metric["proposed_archive_path"])
        if not memory_path.exists():
            results.append(
                {
                    "automation_id": metric.get("automation_id"),
                    "status": "skipped_missing_memory",
                    "path": str(memory_path),
                }
            )
            continue
        original_text = memory_path.read_text(encoding="utf-8", errors="replace")
        current_hash = _sha256_text(original_text)
        if current_hash != metric.get("full_sha256"):
            results.append(
                {
                    "automation_id": metric.get("automation_id"),
                    "status": "skipped_hash_changed",
                    "path": str(memory_path),
                    "expected_sha256": metric.get("full_sha256"),
                    "actual_sha256": current_hash,
                }
            )
            continue
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(original_text, encoding="utf-8")
        compact_text = _compact_memory_text(
            original_text=original_text,
            metric=metric,
            archive_path=archive_path,
            max_tail_lines=int(packet["retained_tail_policy"]["tail_lines"]),
        )
        memory_path.write_text(compact_text, encoding="utf-8")
        results.append(
            {
                "automation_id": metric.get("automation_id"),
                "status": "compacted",
                "path": str(memory_path),
                "archive_path": str(archive_path),
                "before_bytes": metric.get("bytes"),
                "after_bytes": memory_path.stat().st_size,
                "before_approx_tokens": metric.get("approx_tokens"),
                "after_approx_tokens": _approx_tokens(memory_path.stat().st_size),
            }
        )

    compacted = [item for item in results if item["status"] == "compacted"]
    skipped = [item for item in results if item["status"] != "compacted"]
    return {
        "kind": "automation_memory_rollup_apply_result",
        "generated_at": _now_iso(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "compacted_count": len(compacted),
        "skipped_count": len(skipped),
        "results": results,
        "forbidden_effects": [
            "submit_orders",
            "refresh_dead_man",
            "change_live_authority",
            "change_automation_status",
            "edit_credentials",
            "delete_history",
        ],
    }


def _render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Automation Memory Rollup Plan",
        "",
        f"- Generated: {packet['generated_at']}",
        f"- Analysis only: {packet['analysis_only']}",
        f"- Can submit orders: {packet['can_submit_orders']}",
        f"- Mutation mode: {packet['mutation_mode']}",
        f"- Automation root: `{packet['automation_root']}`",
        "",
        "## Summary",
        "",
        f"- Memories inspected: {packet['summary']['memory_count']}",
        f"- Rollup candidates: {packet['summary']['rollup_candidate_count']}",
        f"- Total approx tokens: {packet['summary']['total_approx_tokens']}",
        f"- Candidate approx tokens: {packet['summary']['candidate_approx_tokens']}",
        "",
        "## Candidates",
        "",
        "| Automation | KB | Approx tokens | Action | Proposed archive |",
        "|---|---:|---:|---|---|",
    ]
    for item in packet["memories"]:
        if item["suggested_action"] != "rollup_candidate":
            continue
        lines.append(
            "| "
            f"`{item['automation_id']}` | {item['kb']} | {item['approx_tokens']} | "
            f"{item['suggested_action']} | `{item['proposed_archive_path']}` |"
        )
    if not any(item["suggested_action"] == "rollup_candidate" for item in packet["memories"]):
        lines.append("| none | 0 | 0 | keep_as_is | n/a |")
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- This packet does not edit automation memory files.",
            "- Full history must be archived before any live-memory compaction.",
            "- Hooks and n8n may read this packet, but must not mutate automation state.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_automation_memory_rollup_plan(
    packet: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = path / f"automation-memory-rollup-{timestamp}.json"
    md_path = path / f"automation-memory-rollup-{timestamp}.md"
    json_text = json.dumps(packet, indent=2, sort_keys=True)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(_render_markdown(packet), encoding="utf-8")
    (path / "latest-automation-memory-rollup.json").write_text(
        json_text,
        encoding="utf-8",
    )
    (path / "latest-automation-memory-rollup.md").write_text(
        md_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return json_path, md_path


def write_automation_memory_rollup_apply_result(
    result: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = path / f"automation-memory-rollup-apply-{timestamp}.json"
    json_text = json.dumps(result, indent=2, sort_keys=True)
    json_path.write_text(json_text, encoding="utf-8")
    (path / "latest-automation-memory-rollup-apply.json").write_text(
        json_text,
        encoding="utf-8",
    )
    return json_path
