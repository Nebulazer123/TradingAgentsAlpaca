"""Audit the final MiroFish Step 4 review packet.

This is a read-only guard for the handoff zip. It checks that the packet is
fresh against the accepted report artifacts and that stale evidence footers did
not leak back into embedded report metadata.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import zipfile
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ID = "report_44fb26ddc574"

FORBIDDEN_FULL_REPORT_PATTERNS = [
    "unavailable_rate_limited",
    "source=pending",
    "Rate limit exceeded",
    "0 nodes",
    "0 edges",
    "status=stopped",
    "0 / 1000 interviewed",
    "真实API",
    "深度采访",
    "Section 01 Evidence",
]

REQUIRED_ZIP_ENTRIES = [
    "report/full_report.md",
    "report/meta.json",
    "report/progress.json",
    "report/step5_deep_interaction.json",
    "report/step5_deep_interaction.md",
    "report/step4_diagnostics.json",
    "report/step4_diagnostics.md",
    "report/console_log.txt",
    "report/agent_log.jsonl",
    "report/machine_readable_summary.json",
    "simulation/postrun_telemetry.json",
    "simulation/postrun_telemetry.md",
    "zep_cache/hydration_summary.json",
    "zep_cache/hydration_summary.md",
    "zep_graph_panorama/zep_graph_panorama.json",
    "zep_graph_panorama/zep_graph_panorama.md",
    "docs/MIRROR_FISH_STEP4_FINAL_QUALITY_AUDIT.md",
    "docs/MIRROR_FISH_STEP4_ENRICHMENT_DECISION.md",
    "docs/MIRROR_FISH_REAL_MARKET_VALIDATION_PACKET.md",
    "docs/MIRROR_FISH_EXTERNAL_ENRICHMENT_PACKET.md",
    "docs/MIRROR_FISH_OPTIONAL_ZEP_ENRICHMENT_PLAN.md",
    "docs/MIRROR_FISH_FINAL_ACCEPTANCE_DECISION.md",
    "docs/MIRROR_FISH_FULL_PANORAMA_AND_LIVE_STEP5_REPAIR.md",
    "docs/MIRROR_FISH_FINAL_MIRRORUN_DELTA_REPORT.md",
    "docs/MIRROR_FISH_FINAL_COMPLETION_AUDIT.md",
    "docs/MIRROR_FISH_LAUNCH_PATH_INTEGRITY_AUDIT.md",
    "docs/MIRROR_FISH_STEP4_REPORT_RERUN_PLAN.md",
    "docs/mirofish_build_review_packet.py",
    "docs/mirofish_review_packet_audit.py",
]

FORBIDDEN_QUALITY_SMOKE_PATTERNS = [
    r"[\u4e00-\u9fff]",
    r"```",
    r"post_tweet",
    r"Bro what",
    r"Rate limit exceeded",
    r"status=stopped",
    r"Traceback",
    r"Exception",
]


def _read_zip_text(zf: zipfile.ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8", errors="replace")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def audit_packet(repo_root: Path, report_id: str) -> dict:
    report_dir = repo_root / "backend" / "uploads" / "reports" / report_id
    zip_path = report_dir / f"review_packet_{report_id}.zip"
    full_path = report_dir / "full_report.md"
    meta_path = report_dir / "meta.json"
    progress_path = report_dir / "progress.json"

    issues: list[str] = []
    if not zip_path.exists():
        raise FileNotFoundError(f"Review packet missing: {zip_path}")

    full_text = _normalize_newlines(full_path.read_text(encoding="utf-8", errors="replace"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    metadata_markdown = meta.get("markdown_content") or ""

    if metadata_markdown != full_text:
        issues.append("filesystem meta.json markdown_content does not match full_report.md")
    if progress.get("status") != "completed" or progress.get("progress") != 100:
        issues.append("filesystem progress.json is not completed/100")
    for pattern in FORBIDDEN_FULL_REPORT_PATTERNS:
        if pattern.lower() in full_text.lower():
            issues.append(f"full_report.md contains forbidden reader-facing pattern: {pattern}")

    section_files = sorted(
        p for p in report_dir.glob("section_*.md") if re.fullmatch(r"section_\d+\.md", p.name)
    )
    evidence_json_files = sorted(report_dir.glob("section_*_evidence.json"))
    evidence_md_files = sorted(report_dir.glob("section_*_evidence.md"))
    if len(section_files) != 20:
        issues.append(f"expected 20 section markdown files, found {len(section_files)}")
    if len(evidence_json_files) != 20:
        issues.append(f"expected 20 section evidence JSON files, found {len(evidence_json_files)}")
    if len(evidence_md_files) != 20:
        issues.append(f"expected 20 section evidence markdown files, found {len(evidence_md_files)}")

    with zipfile.ZipFile(zip_path) as zf:
        name_list = zf.namelist()
        names = set(name_list)
        duplicates = sorted(name for name, count in collections.Counter(name_list).items() if count > 1)
        if duplicates:
            issues.append(f"zip contains duplicate entries: {duplicates}")
        missing = [name for name in REQUIRED_ZIP_ENTRIES if name not in names]
        if missing:
            issues.append(f"zip missing required entries: {missing}")
        if not any(name.startswith("step5_live/step5_live_interviews_") and name.endswith(".json") for name in names):
            issues.append("zip missing Step 5 live interview attempt JSON")
        if not any(name.startswith("step5_live/step5_live_interviews_") and name.endswith(".md") for name in names):
            issues.append("zip missing Step 5 live interview attempt markdown")
        if "step5_live_smoke/live_step5_smoke_summary.json" not in names:
            issues.append("zip missing live Step 5 smoke summary JSON")
        if "step5_live_smoke/live_step5_smoke_summary.md" not in names:
            issues.append("zip missing live Step 5 smoke summary markdown")
        if not any(
            name.startswith("step5_live_smoke/step5_live/step5_live_interviews_") and name.endswith(".json")
            for name in names
        ):
            issues.append("zip missing live Step 5 smoke transcript JSON")
        if not any(
            name.startswith("step5_live_smoke/step5_live/step5_live_interviews_") and name.endswith(".md")
            for name in names
        ):
            issues.append("zip missing live Step 5 smoke transcript markdown")
        if "step5_live_smoke_quality/live_step5_smoke_summary.json" not in names:
            issues.append("zip missing quality live Step 5 smoke summary JSON")
        if "step5_live_smoke_quality/live_step5_smoke_summary.md" not in names:
            issues.append("zip missing quality live Step 5 smoke summary markdown")
        quality_json_names = sorted(
            name
            for name in names
            if name.startswith("step5_live_smoke_quality/step5_live/step5_live_interviews_")
            and name.endswith(".json")
        )
        quality_md_names = sorted(
            name
            for name in names
            if name.startswith("step5_live_smoke_quality/step5_live/step5_live_interviews_")
            and name.endswith(".md")
        )
        if not quality_json_names:
            issues.append("zip missing quality live Step 5 smoke transcript JSON")
        if not quality_md_names:
            issues.append("zip missing quality live Step 5 smoke transcript markdown")
        if "step5_live_smoke_quality/live_step5_smoke_summary.json" in names:
            quality_summary = json.loads(_read_zip_text(zf, "step5_live_smoke_quality/live_step5_smoke_summary.json"))
            quality_attempt = quality_summary.get("interview_attempt") or {}
            quality_readiness = quality_attempt.get("readiness") or {}
            if quality_summary.get("status") != "completed":
                issues.append("quality live Step 5 smoke did not complete")
            if quality_readiness.get("live_interviews_available") is not True:
                issues.append("quality live Step 5 smoke did not prove live interviews available")
            if quality_attempt.get("status") != "completed":
                issues.append("quality live Step 5 interview attempt did not complete")
            if len(quality_attempt.get("targets") or []) < 3:
                issues.append("quality live Step 5 smoke has fewer than 3 targets")
            close_result = quality_summary.get("close_result") or {}
            if close_result.get("success") is not True:
                issues.append("quality live Step 5 smoke did not close cleanly")
        for name in quality_md_names:
            quality_text = _read_zip_text(zf, name)
            for pattern in FORBIDDEN_QUALITY_SMOKE_PATTERNS:
                if re.search(pattern, quality_text, flags=re.IGNORECASE):
                    issues.append(f"{name} contains forbidden quality-smoke pattern: {pattern}")

        zip_full = _normalize_newlines(_read_zip_text(zf, "report/full_report.md")) if "report/full_report.md" in names else ""
        if zip_full != full_text:
            issues.append("zip report/full_report.md does not match filesystem full_report.md")

        if "report/meta.json" in names:
            zip_meta = json.loads(_read_zip_text(zf, "report/meta.json"))
            if (zip_meta.get("markdown_content") or "") != full_text:
                issues.append("zip report/meta.json markdown_content does not match clean full_report.md")
            if "Section 01 Evidence" in (zip_meta.get("markdown_content") or ""):
                issues.append("zip report/meta.json still contains evidence footer text")

        if "report/progress.json" in names:
            zip_progress = json.loads(_read_zip_text(zf, "report/progress.json"))
            if zip_progress.get("status") != "completed" or zip_progress.get("progress") != 100:
                issues.append("zip report/progress.json is not completed/100")

    return {
        "report_id": report_id,
        "zip_path": str(zip_path),
        "zip_size": zip_path.stat().st_size,
        "full_report_chars": len(full_text),
        "section_count": len(section_files),
        "evidence_json_count": len(evidence_json_files),
        "evidence_md_count": len(evidence_md_files),
        "issues": issues,
        "passed": not issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the MiroFish Step 4 review packet.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--report-id", default=DEFAULT_REPORT_ID)
    args = parser.parse_args()

    result = audit_packet(Path(args.repo_root), args.report_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
