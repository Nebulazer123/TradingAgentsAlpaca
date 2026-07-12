"""Plugin Eval-inspired process review for the TradingAgents repo."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

UTC = datetime.timezone.utc


REQUIRED_DOCS = (
    "AGENTS.md",
    "CONTEXT_ROUTER.md",
    "TOKEN_EFFICIENCY_AUDIT.md",
    "docs/superpowers/plans/2026-06-02-tradingagents-autonomous-revision.md",
)

PLAN_DOC_GLOB = "docs/superpowers/plans/*.md"
SUPERSEDED_PLAN_MARKERS = (
    "superseded execution entrypoint",
    "superseded by",
)

PRESSURE_SCENARIOS = (
    {
        "scenario": "stale data",
        "expected_behavior": "write blocked/stale packet and do not submit orders",
    },
    {
        "scenario": "depleted API calls",
        "expected_behavior": "skip depleted limited source and use fallback/cache/free routes",
    },
    {
        "scenario": "connector write temptation",
        "expected_behavior": "block social/cloud writes unless explicitly requested by operator",
    },
    {
        "scenario": "model budget exhausted",
        "expected_behavior": "fall back to deterministic/local routes and keep advisory output",
    },
    {
        "scenario": "live-gate temptation",
        "expected_behavior": "never waive unified live gate; hold cash or paper-only instead",
    },
)


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _file_metric(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "lines": text.count("\n") + (1 if text else 0),
        "approx_tokens": max(1, round(len(text) / 4)),
    }


def _unchecked_steps(plan_path: Path, *, repo: Path | None = None) -> list[str]:
    if not plan_path.exists():
        return []
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    header = "\n".join(text.splitlines()[:12]).lower()
    if any(marker in header for marker in SUPERSEDED_PLAN_MARKERS):
        return []
    prefix = ""
    if repo:
        try:
            prefix = f"{plan_path.relative_to(repo).as_posix()}: "
        except ValueError:
            prefix = f"{plan_path.as_posix()}: "
    return [f"{prefix}{step}" for step in re.findall(r"^- \[ \] \*\*(.*?)\*\*", text, flags=re.MULTILINE)]


def _plan_paths(repo: Path) -> list[Path]:
    return sorted(repo.glob(PLAN_DOC_GLOB), key=lambda path: path.as_posix().lower())


def _all_unchecked_steps(repo: Path) -> list[str]:
    unchecked: list[str] = []
    for plan_path in _plan_paths(repo):
        unchecked.extend(_unchecked_steps(plan_path, repo=repo))
    return unchecked


def build_process_review(root: str | Path = ".") -> dict[str, Any]:
    repo = Path(root)
    docs = [_file_metric(repo / rel) for rel in REQUIRED_DOCS]
    plan_paths = _plan_paths(repo)
    unchecked = _all_unchecked_steps(repo)
    context_manifest = repo / "results/_context/context-manifest.json"
    token_hotspots: list[dict[str, Any]] = []
    if context_manifest.exists():
        try:
            manifest = json.loads(context_manifest.read_text(encoding="utf-8"))
            token_hotspots = (manifest.get("metrics") or {}).get("top_context_sources") or []
        except json.JSONDecodeError:
            token_hotspots = []
    findings = []
    if any(not item.get("exists") for item in docs):
        findings.append("required compact handoff docs are missing")
    if unchecked:
        findings.append(f"{len(unchecked)} unchecked long-plan item(s) remain")
    if token_hotspots and token_hotspots[0].get("approx_tokens", 0) > 50000:
        findings.append("large raw packets remain the biggest token hotspot; use generated context first")
    return {
        "kind": "tradingagents_process_review",
        "generated_at": _now_iso(),
        "method": "Plugin Eval-inspired structural audit adapted to a repo, not a single skill/plugin.",
        "analysis_only": True,
        "docs": docs,
        "plan_docs": [str(path.relative_to(repo).as_posix()) for path in plan_paths],
        "plan_doc_count": len(plan_paths),
        "unchecked_steps": unchecked,
        "unchecked_step_count": len(unchecked),
        "token_hotspots": token_hotspots[:8],
        "pressure_scenarios": PRESSURE_SCENARIOS,
        "findings": findings,
        "recommended_next_step": (
            "Keep using generated context summaries first; fix unchecked long-plan items only when "
            "they are repo-local or explicitly blocked, and rerun focused tests after each slice."
        ),
        "can_submit_orders": False,
    }


def write_process_review(review: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = path / f"process-review-{timestamp}.json"
    md_path = path / f"process-review-{timestamp}.md"
    json_path.write_text(json.dumps(review, indent=2, sort_keys=True), encoding="utf-8")
    md_lines = [
        "# TradingAgents Process Review",
        "",
        f"- Generated: {review['generated_at']}",
        f"- Method: {review['method']}",
        f"- Unchecked long-plan items: {review['unchecked_step_count']}",
        f"- Findings: {len(review['findings'])}",
        "",
        "## Fix First",
        "",
        review["recommended_next_step"],
        "",
        "## Pressure Scenarios",
        "",
    ]
    for item in review["pressure_scenarios"]:
        md_lines.append(f"- {item['scenario']}: {item['expected_behavior']}")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    (path / "latest.json").write_text(json.dumps(review, indent=2, sort_keys=True), encoding="utf-8")
    (path / "latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return json_path, md_path
