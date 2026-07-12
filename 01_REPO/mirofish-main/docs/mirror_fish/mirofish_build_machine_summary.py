"""Build a deterministic machine-readable MiroFish report summary.

This artifact is consumed by the review packet and downstream TradingAgents
handoff. It intentionally summarizes existing local artifacts only.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ID = "report_44fb26ddc574"
DEFAULT_SIMULATION_ID = "sim_974459649906"
DEFAULT_GRAPH_ID = "mirofish_4a9df9ae8b184878"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _section_titles(report_dir: Path) -> list[str]:
    titles: list[str] = []
    for path in sorted(report_dir.glob("section_??.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
        titles.append(match.group(1).strip() if match else path.stem)
    return titles


def _count_forbidden_reader_patterns(text: str) -> dict[str, int]:
    patterns = [
        "unavailable_rate_limited",
        "source=pending",
        "Rate limit exceeded",
        "0 nodes",
        "0 edges",
        "status=stopped",
        "0 / 1000 interviewed",
        "Section 01 Evidence",
    ]
    lower_text = text.lower()
    return {pattern: lower_text.count(pattern.lower()) for pattern in patterns}


def _quality_scan_markdown(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {"path": None, "exists": False}
    path = Path(path_value)
    if not path.is_absolute():
        path = DEFAULT_REPO_ROOT / path
    if not path.exists():
        return {"path": str(path), "exists": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path),
        "exists": True,
        "char_count": len(text),
        "cjk": bool(re.search(r"[\u4e00-\u9fff]", text)),
        "code_fence": "```" in text,
        "post_tweet_wrapper": "post_tweet" in text,
        "bro_refusal": "Bro what" in text,
        "raw_error": bool(re.search(r"Rate limit exceeded|status=stopped|Traceback|Exception", text, re.I)),
    }


def _smoke_summary(report_dir: Path, folder_name: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary_path = report_dir / folder_name / "live_step5_smoke_summary.json"
    summary = _read_json(summary_path)
    interview = summary.get("interview_attempt") if isinstance(summary.get("interview_attempt"), dict) else {}
    readiness = interview.get("readiness") if isinstance(interview.get("readiness"), dict) else {}
    return summary_path, summary, interview, readiness


def _smoke_summary_record(
    summary_path: Path,
    summary: dict[str, Any],
    interview: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "simulation_id": summary.get("simulation_id"),
        "max_rounds": summary.get("max_rounds"),
        "platform": summary.get("platform"),
        "live_interviews_available": readiness.get("live_interviews_available"),
        "interview_status": interview.get("status"),
        "interview_target_count": len(interview.get("targets") or []),
        "interview_json_path": summary.get("interview_json_path"),
        "interview_markdown_path": summary.get("interview_markdown_path"),
        "close_result_success": (summary.get("close_result") or {}).get("success")
        if isinstance(summary.get("close_result"), dict)
        else None,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "quality_scan": _quality_scan_markdown(summary.get("interview_markdown_path")),
    }


def build_summary(repo_root: Path, report_id: str, simulation_id: str, graph_id: str) -> dict[str, Any]:
    report_dir = repo_root / "backend" / "uploads" / "reports" / report_id
    sim_dir = repo_root / "backend" / "uploads" / "simulations" / simulation_id
    telemetry = _read_json(sim_dir / "postrun_telemetry.json")
    diagnostics = _read_json(report_dir / "step4_diagnostics.json")
    progress = _read_json(report_dir / "progress.json")
    full_report_path = report_dir / "full_report.md"
    full_report = full_report_path.read_text(encoding="utf-8", errors="replace") if full_report_path.exists() else ""
    section_files = sorted(report_dir.glob("section_??.md"))
    evidence_json_files = sorted(report_dir.glob("section_??_evidence.json"))
    evidence_md_files = sorted(report_dir.glob("section_??_evidence.md"))
    zep_diag = diagnostics.get("zep_diagnostics") if isinstance(diagnostics.get("zep_diagnostics"), dict) else {}
    panorama_path = report_dir / "zep_graph_panorama" / "zep_graph_panorama.json"
    panorama = _read_json(panorama_path)
    step5_live_json_files = sorted((report_dir / "step5_live").glob("step5_live_interviews_*.json"))
    latest_step5_live_path = step5_live_json_files[-1] if step5_live_json_files else None
    latest_step5_live = _read_json(latest_step5_live_path) if latest_step5_live_path else {}
    latest_step5_readiness = (
        latest_step5_live.get("readiness")
        if isinstance(latest_step5_live.get("readiness"), dict)
        else {}
    )
    step5_smoke_summary_path, step5_smoke_summary, step5_smoke_interview, step5_smoke_readiness = _smoke_summary(
        report_dir, "step5_live_smoke"
    )
    (
        step5_quality_summary_path,
        step5_quality_summary,
        step5_quality_interview,
        step5_quality_readiness,
    ) = _smoke_summary(report_dir, "step5_live_smoke_quality")

    return {
        "schema": "mirofish_machine_readable_summary.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "simulation_metadata": {
            "simulation_id": simulation_id,
            "graph_id": graph_id,
            "report_id": report_id,
            "total_rounds": telemetry.get("total_rounds") or telemetry.get("actual_total_rounds"),
            "configured_total_rounds": telemetry.get("configured_total_rounds"),
            "unique_active_agents": telemetry.get("unique_active_agents"),
            "actions_by_platform": telemetry.get("actions_by_platform", {}),
            "actions_by_actor_layer": telemetry.get("actions_by_actor_layer", {}),
            "active_agents_by_layer": telemetry.get("active_agents_by_layer", {}),
            "forecast_ballots": {
                "total_detected": (
                    telemetry.get("forecast_ballot_like_actions")
                    or telemetry.get("detected_ballot_like_actions")
                    or (telemetry.get("forecast_ballot_summary") or {}).get("detected_ballot_like_actions")
                ),
                "ballot_rounds": (
                    telemetry.get("ballot_rounds")
                    or (telemetry.get("forecast_ballot_summary") or {}).get("event_marker_ballot_rounds")
                    or []
                ),
            },
        },
        "report_artifacts": {
            "status": progress.get("status"),
            "progress": progress.get("progress"),
            "section_count": len(section_files),
            "evidence_json_count": len(evidence_json_files),
            "evidence_md_count": len(evidence_md_files),
            "section_titles": _section_titles(report_dir),
            "full_report_chars": len(full_report),
            "reader_forbidden_pattern_counts": _count_forbidden_reader_patterns(full_report),
        },
        "zep_provenance": {
            "mode_used": diagnostics.get("mode_used"),
            "zep_canonical": diagnostics.get("zep_canonical", True),
            "graph_search_worked": diagnostics.get("graph_search_worked"),
            "all_node_edge_skipped_deferred": diagnostics.get("all_node_edge_skipped_deferred"),
            "supplemental_graph_wide_panorama_completed": panorama.get("status") == "completed",
            "supplemental_graph_wide_panorama": {
                "status": panorama.get("status"),
                "truly_graph_wide": panorama.get("truly_graph_wide"),
                "node_count": panorama.get("node_count"),
                "edge_count": panorama.get("edge_count"),
                "active_fact_count": panorama.get("active_fact_count"),
                "historical_fact_count": panorama.get("historical_fact_count"),
                "errors": panorama.get("errors", []),
                "path": str(panorama_path) if panorama_path.exists() else None,
            },
            "interview_mode": diagnostics.get("interview_mode"),
            "latest_live_step5_attempt": {
                "status": latest_step5_live.get("status"),
                "live_interviews_available": latest_step5_readiness.get("live_interviews_available"),
                "reason": latest_step5_readiness.get("reason"),
                "target_count": len(latest_step5_live.get("targets") or []),
                "path": str(latest_step5_live_path) if latest_step5_live_path else None,
            },
            "live_step5_smoke": {
                **_smoke_summary_record(step5_smoke_summary_path, step5_smoke_summary, step5_smoke_interview, step5_smoke_readiness),
                "acceptance_note": "proof-only live IPC smoke; superseded for interview-quality review by live_step5_smoke_quality",
            },
            "live_step5_smoke_quality": {
                **_smoke_summary_record(
                    step5_quality_summary_path,
                    step5_quality_summary,
                    step5_quality_interview,
                    step5_quality_readiness,
                ),
                "acceptance_note": "accepted quality smoke transcript for live Step 5 output-quality evidence",
            },
            "calls_attempted": zep_diag.get("calls_attempted"),
            "calls_succeeded": zep_diag.get("calls_succeeded"),
            "calls_rate_limited": zep_diag.get("calls_rate_limited"),
            "calls_skipped": zep_diag.get("calls_skipped"),
            "cache_hits": zep_diag.get("cache_hits"),
            "cache_misses": zep_diag.get("cache_misses"),
            "outcomes_by_source": zep_diag.get("outcomes_by_source", {}),
        },
        "telemetry_indices_observed": telemetry.get("telemetry_indices_observed")
        or telemetry.get("state_variables_observed")
        or [],
        "event_and_signal_counts": {
            "AI_bot_copycat_events": telemetry.get("AI_bot_copycat_events"),
            "broker_confusion_events": telemetry.get("broker_confusion_events"),
            "buying_power_margin_confusion_events": telemetry.get("buying_power_margin_confusion_events"),
            "options_0DTE_events": telemetry.get("options_0DTE_events"),
            "macro_override_events": telemetry.get("macro_override_events"),
            "institutional_liquidity_events": telemetry.get("institutional_liquidity_events"),
            "market_maker_response_events": telemetry.get("market_maker_response_events"),
            "false_signal_events": telemetry.get("false_signal_events"),
        },
        "stage05_targets": telemetry.get("agents_to_interview_in_stage05", []),
        "source_paths": {
            "full_report": str(full_report_path),
            "postrun_telemetry": str(sim_dir / "postrun_telemetry.json"),
            "step4_diagnostics": str(report_dir / "step4_diagnostics.json"),
            "zep_graph_panorama": str(panorama_path) if panorama_path.exists() else None,
            "latest_step5_live_attempt": str(latest_step5_live_path) if latest_step5_live_path else None,
            "live_step5_smoke_summary": str(step5_smoke_summary_path) if step5_smoke_summary_path.exists() else None,
            "live_step5_smoke_quality_summary": str(step5_quality_summary_path)
            if step5_quality_summary_path.exists()
            else None,
            "console_log": str(report_dir / "console_log.txt"),
        },
        "provenance_hashes": {
            "full_report_sha256": _sha256(full_report_path),
            "postrun_telemetry_sha256": _sha256(sim_dir / "postrun_telemetry.json"),
            "step4_diagnostics_sha256": _sha256(report_dir / "step4_diagnostics.json"),
            "zep_graph_panorama_sha256": _sha256(panorama_path),
            "latest_step5_live_attempt_sha256": _sha256(latest_step5_live_path) if latest_step5_live_path else None,
            "live_step5_smoke_summary_sha256": _sha256(step5_smoke_summary_path),
            "live_step5_smoke_quality_summary_sha256": _sha256(step5_quality_summary_path),
        },
        "advisory_boundary": {
            "allowed_use": "advisory_only",
            "prohibited_use": "direct_trade_trigger",
            "execution_authority": "none",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build MiroFish machine-readable report summary.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--report-id", default=DEFAULT_REPORT_ID)
    parser.add_argument("--simulation-id", default=DEFAULT_SIMULATION_ID)
    parser.add_argument("--graph-id", default=DEFAULT_GRAPH_ID)
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    summary = build_summary(repo_root, args.report_id, args.simulation_id, args.graph_id)
    output_path = repo_root / "backend" / "uploads" / "reports" / args.report_id / "machine_readable_summary.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_path": str(output_path), "report_id": args.report_id}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
