"""Operator-facing email clarity checks for TradingAgents reports."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

UTC = datetime.timezone.utc

DAILY_REQUIRED_HEADINGS = (
    "Plain English",
    "What happened",
    "Money today",
    "Live account",
    "Paper account",
    "Open orders",
    "Submitted orders",
    "Need from you",
)

URGENT_REQUIRED_HEADINGS = (
    "Plain English",
    "What happened",
    "Need from you",
)

FORBIDDEN_PHRASES = (
    "go fix",
    "fix this file",
    "open this file",
    "open file",
    "run this command",
    "debug this",
    "traceback",
    "stack trace",
    "notify:",
    "live_exposure_limit",
    "dynamic_cap",
    "execution_mode",
    "projected $",
    "cap $100",
    "approve this trade",
    "approve trade",
    "per-trade approval",
)


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _line_after(lines: list[str], header: str) -> str | None:
    try:
        index = lines.index(header)
    except ValueError:
        return None
    for line in lines[index + 1 :]:
        if line.strip():
            return line.strip()
    return None


def _first_line_with_prefix(lines: list[str], prefix: str) -> str | None:
    for line in lines:
        if line.startswith(prefix):
            return line
    return None


def _contains_heading(lines: list[str], heading: str) -> bool:
    return heading in lines


def evaluate_email_clarity(
    body: str,
    *,
    subject: str | None = None,
    report_type: str = "daily",
) -> dict[str, Any]:
    """Score whether an operator email is short, plain, and actionable."""

    normalized_report_type = report_type.lower().strip() or "daily"
    lines = body.splitlines()
    nonempty_lines = [line for line in lines if line.strip()]
    lowered = body.lower()
    issues: list[str] = []
    warnings: list[str] = []

    if normalized_report_type == "urgent":
        required_headings = URGENT_REQUIRED_HEADINGS
        max_line_count = 40
    else:
        required_headings = DAILY_REQUIRED_HEADINGS
        max_line_count = 60

    if len(lines) > max_line_count:
        issues.append(f"email is too long: {len(lines)} lines, limit {max_line_count}")

    missing_headings = [
        heading for heading in required_headings if not _contains_heading(lines, heading)
    ]
    if missing_headings:
        issues.append("missing required section(s): " + ", ".join(missing_headings))

    problem_line = _first_line_with_prefix(lines, "Problem:")
    if problem_line is None:
        issues.append("missing plain Problem line")

    plain_line = _line_after(lines, "Plain English")
    if not plain_line:
        issues.append("Plain English section has no summary line")

    need_line = _line_after(lines, "Need from you")
    if not need_line:
        issues.append("Need from you section has no operator ask")
    elif any(phrase in need_line.lower() for phrase in ("approve trade", "approve this trade")):
        issues.append("Need from you asks for trade-level approval instead of ops-level approval")

    if normalized_report_type != "urgent":
        for prefix in ("- Live spent today:", "- Paper spent today:"):
            if _first_line_with_prefix(lines, prefix) is None:
                issues.append(f"missing money line: {prefix}")
        if not any(line.startswith("- Holdings:") for line in lines):
            issues.append("missing holdings summary line")

    forbidden_found = [phrase for phrase in FORBIDDEN_PHRASES if phrase in lowered]
    if forbidden_found:
        issues.append("contains confusing/programmer wording: " + ", ".join(forbidden_found))

    if any(line.strip() == "None" for line in lines):
        warnings.append("contains raw Python-style None; prefer none/unknown with context")

    max_line_length = max((len(line) for line in lines), default=0)
    if max_line_length > 260:
        warnings.append(f"very long line found: {max_line_length} characters")

    current_problem = problem_line is not None and problem_line.strip().lower() not in {
        "problem: none",
        "problem: no current blocker",
    }
    if current_problem and not any(
        phrase in lowered for phrase in ("self-heal", "stay blocked", "board/codex")
    ):
        issues.append("current blocker email does not explain Codex self-heal, BOARD/Codex review, or safe block behavior")

    score = 100
    score -= 20 * len(issues)
    score -= 5 * len(warnings)
    score = max(0, score)
    status = "pass" if not issues else "fail"

    return {
        "kind": "email_clarity_eval",
        "schema_version": 1,
        "generated_at": _now_iso(),
        "analysis_only": True,
        "report_type": normalized_report_type,
        "subject": subject,
        "status": status,
        "score": score,
        "line_count": len(lines),
        "nonempty_line_count": len(nonempty_lines),
        "max_line_count": max_line_count,
        "max_line_length": max_line_length,
        "problem_line": problem_line,
        "plain_english_line": plain_line,
        "need_from_you_line": need_line,
        "issues": issues,
        "warnings": warnings,
        "can_submit_orders": False,
    }


def write_email_clarity_eval(
    evaluation: dict[str, Any],
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Write JSON/Markdown clarity artifacts without storing the email body."""

    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = path / f"email-clarity-{timestamp}.json"
    md_path = path / f"email-clarity-{timestamp}.md"
    json_path.write_text(json.dumps(evaluation, indent=2, sort_keys=True), encoding="utf-8")
    md_lines = [
        "# TradingAgents Email Clarity Eval",
        "",
        f"- Generated: {evaluation['generated_at']}",
        f"- Report type: {evaluation['report_type']}",
        f"- Status: {evaluation['status']}",
        f"- Score: {evaluation['score']}",
        f"- Lines: {evaluation['line_count']} / {evaluation['max_line_count']}",
        f"- Problem: {evaluation.get('problem_line') or 'missing'}",
        f"- Need from you: {evaluation.get('need_from_you_line') or 'missing'}",
        "",
        "## Issues",
        "",
    ]
    issues = evaluation.get("issues") or []
    if issues:
        md_lines.extend(f"- {issue}" for issue in issues)
    else:
        md_lines.append("- none")
    md_lines.extend(["", "## Warnings", ""])
    warnings = evaluation.get("warnings") or []
    if warnings:
        md_lines.extend(f"- {warning}" for warning in warnings)
    else:
        md_lines.append("- none")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    (path / "latest.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (path / "latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return json_path, md_path
