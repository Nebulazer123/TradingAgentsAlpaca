"""Build the final MiroFish Step 4 review packet zip.

This script packages the accepted Step 4 report artifacts, telemetry, Zep cache
summary, and handoff docs into a deterministic zip for external review.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ID = "report_44fb26ddc574"
DEFAULT_SIMULATION_ID = "sim_974459649906"
DEFAULT_GRAPH_ID = "mirofish_4a9df9ae8b184878"

REQUIRED_REPORT_FILES = [
    "agent_log.jsonl",
    "console_log.txt",
    "full_report.md",
    "machine_readable_summary.json",
    "meta.json",
    "outline.json",
    "progress.json",
    "step5_deep_interaction.json",
    "step5_deep_interaction.md",
    "step4_diagnostics.json",
    "step4_diagnostics.md",
]

REQUIRED_SIMULATION_FILES = [
    "postrun_telemetry.json",
    "postrun_telemetry.md",
    "run_state.json",
    "simulation_config.json",
]

REQUIRED_DOCS = [
    "MIRROR_FISH_LAUNCH_PATH_INTEGRITY_AUDIT.md",
    "MIRROR_FISH_STEP4_FINAL_QUALITY_AUDIT.md",
    "MIRROR_FISH_STEP4_REPORT_RERUN_PLAN.md",
    "MIRROR_FISH_STEP4_ENRICHMENT_DECISION.md",
    "MIRROR_FISH_REAL_MARKET_VALIDATION_PACKET.md",
    "MIRROR_FISH_EXTERNAL_ENRICHMENT_PACKET.md",
    "MIRROR_FISH_OPTIONAL_ZEP_ENRICHMENT_PLAN.md",
    "MIRROR_FISH_FINAL_ACCEPTANCE_DECISION.md",
    "MIRROR_FISH_FULL_PANORAMA_AND_LIVE_STEP5_REPAIR.md",
    "MIRROR_FISH_FINAL_MIRRORUN_DELTA_REPORT.md",
    "MIRROR_FISH_FINAL_COMPLETION_AUDIT.md",
    "MIRROR_FISH_TRADING_RUN_READINESS.md",
    "mirofish_build_review_packet.py",
    "mirofish_review_packet_audit.py",
]


def _add_file(zf: zipfile.ZipFile, path: Path, arcname: str, missing: list[str]) -> None:
    if not path.exists():
        missing.append(str(path))
        return
    zf.write(path, arcname)


def build_packet(repo_root: Path, report_id: str, simulation_id: str, graph_id: str) -> dict:
    report_dir = repo_root / "backend" / "uploads" / "reports" / report_id
    simulation_dir = repo_root / "backend" / "uploads" / "simulations" / simulation_id
    zep_cache_dir = repo_root / "backend" / "uploads" / "reports" / "_zep_cache" / graph_id
    docs_dir = repo_root / "docs" / "mirror_fish"
    zip_path = report_dir / f"review_packet_{report_id}.zip"
    tmp_path = zip_path.with_suffix(".zip.tmp")

    missing: list[str] = []
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename in REQUIRED_REPORT_FILES:
            _add_file(zf, report_dir / filename, f"report/{filename}", missing)

        section_markdown = [
            path
            for path in sorted(report_dir.glob("section_*.md"))
            if re.fullmatch(r"section_\d+\.md", path.name)
        ]
        for path in section_markdown:
            _add_file(zf, path, f"report/{path.name}", missing)
        for pattern in ("section_*_evidence.json", "section_*_evidence.md"):
            for path in sorted(report_dir.glob(pattern)):
                _add_file(zf, path, f"report/{path.name}", missing)

        for filename in REQUIRED_SIMULATION_FILES:
            _add_file(zf, simulation_dir / filename, f"simulation/{filename}", missing)

        for filename in ("hydration_summary.json", "hydration_summary.md"):
            _add_file(zf, zep_cache_dir / filename, f"zep_cache/{filename}", missing)

        for filename in ("zep_graph_panorama.json", "zep_graph_panorama.md"):
            _add_file(
                zf,
                report_dir / "zep_graph_panorama" / filename,
                f"zep_graph_panorama/{filename}",
                missing,
            )
        step5_live_dir = report_dir / "step5_live"
        step5_live_files = sorted(step5_live_dir.glob("step5_live_interviews_*.json"))
        step5_live_files.extend(sorted(step5_live_dir.glob("step5_live_interviews_*.md")))
        if not step5_live_files:
            missing.append(str(step5_live_dir / "step5_live_interviews_*.json|md"))
        for path in step5_live_files:
            _add_file(zf, path, f"step5_live/{path.name}", missing)

        step5_smoke_dir = report_dir / "step5_live_smoke"
        step5_smoke_files = sorted(path for path in step5_smoke_dir.rglob("*") if path.is_file())
        if not step5_smoke_files:
            missing.append(str(step5_smoke_dir / "**/*"))
        for path in step5_smoke_files:
            _add_file(zf, path, f"step5_live_smoke/{path.relative_to(step5_smoke_dir).as_posix()}", missing)

        step5_quality_smoke_dir = report_dir / "step5_live_smoke_quality"
        step5_quality_smoke_files = sorted(path for path in step5_quality_smoke_dir.rglob("*") if path.is_file())
        if not step5_quality_smoke_files:
            missing.append(str(step5_quality_smoke_dir / "**/*"))
        for path in step5_quality_smoke_files:
            _add_file(
                zf,
                path,
                f"step5_live_smoke_quality/{path.relative_to(step5_quality_smoke_dir).as_posix()}",
                missing,
            )

        for filename in REQUIRED_DOCS:
            _add_file(zf, docs_dir / filename, f"docs/{filename}", missing)

    if missing:
        tmp_path.unlink(missing_ok=True)
        raise FileNotFoundError("Missing required packet files:\n" + "\n".join(missing))

    tmp_path.replace(zip_path)
    return {
        "report_id": report_id,
        "zip_path": str(zip_path),
        "zip_size": zip_path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the MiroFish Step 4 review packet.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--report-id", default=DEFAULT_REPORT_ID)
    parser.add_argument("--simulation-id", default=DEFAULT_SIMULATION_ID)
    parser.add_argument("--graph-id", default=DEFAULT_GRAPH_ID)
    args = parser.parse_args()

    result = build_packet(Path(args.repo_root), args.report_id, args.simulation_id, args.graph_id)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
