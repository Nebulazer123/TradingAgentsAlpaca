"""Run a tiny live MiroFish Step 5 smoke against a prepared simulation.

This is a proof harness, not a replacement for the accepted MiroFish report.
It starts a small prepared simulation for one capped round, waits for the
post-run command window, runs true live Step 5 interviews through IPC, and then
closes the smoke environment.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.simulation_runner import SimulationRunner  # noqa: E402
from mirofish_step5_live_interviews import run_step5_live_interviews  # noqa: E402


DEFAULT_SMOKE_SIMULATION_ID = "sim_763e1e31b320"
DEFAULT_ACCEPTED_REPORT_ID = "report_9c77ca2557ae"


def _write_artifacts(output_dir: Path, data: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "live_step5_smoke_summary.json"
    md_path = output_dir / "live_step5_smoke_summary.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    interview = data.get("interview_attempt") or {}
    readiness = interview.get("readiness") or {}
    close_result = data.get("close_result") or {}
    lines = [
        "# MiroFish Live Step 5 Smoke",
        "",
        f"- Smoke simulation ID: `{data.get('simulation_id')}`",
        f"- Status: `{data.get('status')}`",
        f"- Generated at: `{data.get('generated_at')}`",
        f"- Max rounds: `{data.get('max_rounds')}`",
        f"- Platform: `{data.get('platform')}`",
        f"- Live interviews available at interview time: `{readiness.get('live_interviews_available')}`",
        f"- Interview attempt status: `{interview.get('status')}`",
        f"- Interview result path: `{data.get('interview_json_path')}`",
        f"- Close result: `{close_result.get('success')}` {close_result.get('message') or ''}",
        "",
        "## Purpose",
        "",
        "This smoke proves the live IPC Step 5 interview path on a live, capped simulation environment. "
        "It does not replace the accepted 1,000-agent MiroFish report.",
        "",
    ]
    if data.get("error"):
        lines.extend(["## Error", "", f"`{data.get('error')}`", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def wait_for_live_interview_window(simulation_id: str, timeout: float, poll_interval: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_readiness: dict[str, Any] = {}
    while time.time() < deadline:
        readiness = SimulationRunner.get_live_interview_readiness(simulation_id)
        last_readiness = readiness
        if readiness.get("live_interviews_available"):
            return readiness
        state = SimulationRunner.get_run_state(simulation_id)
        if state and state.runner_status.value == "failed":
            return readiness | {"failed_before_live_window": True}
        time.sleep(poll_interval)
    return last_readiness | {"timed_out_waiting_for_live_window": True}


def run_smoke(
    *,
    simulation_id: str,
    output_dir: Path,
    max_rounds: int,
    platform: str,
    max_agents: int,
    agent_ids: list[int] | None,
    startup_timeout: float,
    interview_timeout: float,
    close_timeout: float,
    clean_logs: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "schema": "mirofish.live_step5_smoke.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "simulation_id": simulation_id,
        "status": "started",
        "max_rounds": max_rounds,
        "platform": platform,
        "clean_logs": clean_logs,
        "start_state": None,
        "live_window_readiness": None,
        "interview_attempt": None,
        "interview_json_path": None,
        "interview_markdown_path": None,
        "close_result": None,
        "error": None,
    }

    try:
        existing_readiness = SimulationRunner.get_live_interview_readiness(simulation_id)
        if existing_readiness.get("runner_process_alive"):
            raise RuntimeError(f"Smoke simulation already has a live runner: {existing_readiness}")

        if clean_logs:
            cleanup = SimulationRunner.cleanup_simulation_logs(simulation_id)
            if not cleanup.get("success"):
                raise RuntimeError(f"Could not clean smoke simulation logs: {cleanup}")

        start_state = SimulationRunner.start_simulation(
            simulation_id=simulation_id,
            platform=platform,
            max_rounds=max_rounds,
            enable_graph_memory_update=False,
            graph_id=None,
        )
        summary["start_state"] = start_state.to_dict()

        live_readiness = wait_for_live_interview_window(
            simulation_id=simulation_id,
            timeout=startup_timeout,
            poll_interval=2.0,
        )
        summary["live_window_readiness"] = live_readiness
        if not live_readiness.get("live_interviews_available"):
            summary["status"] = "failed_no_live_window"
            return summary

        interview_dir = output_dir / "step5_live"
        interview_data, interview_json, interview_md = run_step5_live_interviews(
            simulation_id=simulation_id,
            output_dir=interview_dir,
            max_agents=max_agents,
            timeout=interview_timeout,
            platform=None if platform == "parallel" else platform,
            agent_ids=agent_ids,
        )
        summary["interview_attempt"] = interview_data
        summary["interview_json_path"] = str(interview_json)
        summary["interview_markdown_path"] = str(interview_md)
        summary["status"] = "completed" if interview_data.get("status") == "completed" else "failed_interview"
        return summary
    except Exception as exc:  # noqa: BLE001 - smoke artifact must preserve exact failure reason.
        summary["status"] = "failed_exception"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary
    finally:
        try:
            summary["close_result"] = SimulationRunner.close_simulation_env(simulation_id, timeout=close_timeout)
        except Exception as exc:  # noqa: BLE001
            summary["close_result"] = {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        _write_artifacts(output_dir, summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a capped live Step 5 smoke and close the smoke env.")
    parser.add_argument("--simulation-id", default=DEFAULT_SMOKE_SIMULATION_ID)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "backend" / "uploads" / "reports" / DEFAULT_ACCEPTED_REPORT_ID / "step5_live_smoke"),
    )
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--platform", choices=["twitter", "reddit", "parallel"], default="parallel")
    parser.add_argument("--max-agents", type=int, default=2)
    parser.add_argument(
        "--agent-ids",
        default=None,
        help="Optional comma-separated agent ids to interview in this exact order.",
    )
    parser.add_argument("--startup-timeout", type=float, default=900.0)
    parser.add_argument("--interview-timeout", type=float, default=240.0)
    parser.add_argument("--close-timeout", type=float, default=60.0)
    parser.add_argument("--no-clean-logs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = run_smoke(
        simulation_id=args.simulation_id,
        output_dir=Path(args.output_dir),
        max_rounds=max(1, args.max_rounds),
        platform=args.platform,
        max_agents=max(1, args.max_agents),
        agent_ids=[int(item) for item in args.agent_ids.split(",")] if args.agent_ids else None,
        startup_timeout=args.startup_timeout,
        interview_timeout=args.interview_timeout,
        close_timeout=args.close_timeout,
        clean_logs=not args.no_clean_logs,
    )
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
