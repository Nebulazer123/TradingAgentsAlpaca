#!/usr/bin/env python3
"""Read-only launch-path integrity checks for MiroFish Stage 03.

This script does not import OASIS, start a runner, call external services, send
email, or update cloud files. It validates the pure launch-context helpers, the
patched API/service/runner/telemetry wiring, and accepts either the original
pre-launch locked state or completed post-run evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

HELPER_PATH = BACKEND / "app" / "utils" / "round_event_context.py"
spec = importlib.util.spec_from_file_location("round_event_context", HELPER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load helper: {HELPER_PATH}")
round_event_context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(round_event_context)

format_round_event_context_post = round_event_context.format_round_event_context_post
get_round_event_context = round_event_context.get_round_event_context
max_rounds_source = round_event_context.max_rounds_source
resolve_effective_max_rounds = round_event_context.resolve_effective_max_rounds
select_context_poster_agent_id = round_event_context.select_context_poster_agent_id


SIMULATION_ID = "sim_974459649906"
PROJECT_ID = "proj_8ece728e49fe"
GRAPH_ID = "mirofish_4a9df9ae8b184878"
SIM_DIR = ROOT / "backend" / "uploads" / "simulations" / SIMULATION_ID


def read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def contains_all(text: str, required: List[str]) -> Dict[str, bool]:
    lower = text.lower()
    return {item: item.lower() in lower for item in required}


def check(name: str, passed: bool, evidence: str) -> Dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def build_integrity_report() -> Dict[str, Any]:
    cfg = read_json(SIM_DIR / "simulation_config.json")
    state = read_json(SIM_DIR / "state.json")
    run_state = read_json(SIM_DIR / "run_state.json")
    postrun = read_json(SIM_DIR / "postrun_telemetry.json")

    runner_text = (ROOT / "backend" / "scripts" / "run_parallel_simulation.py").read_text(encoding="utf-8", errors="replace")
    api_text = (ROOT / "backend" / "app" / "api" / "simulation.py").read_text(encoding="utf-8", errors="replace")
    service_text = (ROOT / "backend" / "app" / "services" / "simulation_runner.py").read_text(encoding="utf-8", errors="replace")
    telemetry_text = (ROOT / "docs" / "mirror_fish" / "mirofish_postrun_telemetry.py").read_text(encoding="utf-8", errors="replace")

    scheduled_events = cfg.get("event_config", {}).get("scheduled_events", [])
    forecast_rounds = cfg.get("predictive_quality_upgrade", {}).get("forecast_ballot_rounds", [])
    default_max_rounds = resolve_effective_max_rounds(cfg, None)
    requested_30_rounds = resolve_effective_max_rounds(cfg, 30)
    stress_cap_2 = resolve_effective_max_rounds(cfg, 2)
    default_source = max_rounds_source(cfg, None)
    prelaunch_locked = (
        state.get("status") == "ready"
        and int(state.get("current_round", 0) or 0) == 0
        and state.get("twitter_status") == "not_started"
        and state.get("reddit_status") == "not_started"
    )
    stage03_completed = (
        run_state.get("runner_status") in {"completed", "stopped"}
        and int(run_state.get("total_rounds", 0) or 0) == 30
        and int(run_state.get("max_rounds_applied", 0) or 0) == 30
        and run_state.get("twitter_completed") is True
        and run_state.get("reddit_completed") is True
        and int(run_state.get("total_actions_count", 0) or 0) > 0
        and postrun.get("status") == "ready"
    )
    lifecycle_mode = (
        "postrun_completed"
        if stage03_completed
        else "prelaunch_locked"
        if prelaunch_locked
        else "unexpected"
    )

    contexts: Dict[str, Dict[str, Any]] = {}
    context_terms = [
        "stage03 runtime event beat",
        "state-variable focus",
        "causal attribution",
        "macro/rates",
        "treasury auctions",
        "oil/geopolitics",
        "ai/semiconductor catalysts",
        "options-expiration mechanics",
        "institutional liquidity response",
        "broker/platform rollout differences",
        "cash vs margin",
        "0dte",
        "spy/qqq/tsla/aapl",
        "control branch",
        "tradingagents purpose",
    ]
    for platform in ("twitter", "reddit"):
        platform_contexts: Dict[str, Any] = {}
        for round_num in (1, 3, 30):
            event = get_round_event_context(cfg, round_num, platform)
            content = format_round_event_context_post(cfg, round_num, platform)
            platform_contexts[str(round_num)] = {
                "event_beat_id": event.get("event_beat_id"),
                "beat": event.get("beat"),
                "forecast_ballot_required": event.get("forecast_ballot_required"),
                "forecast_ballot_phrase": "forecast ballot required" in content.lower(),
                "poster_agent_id": select_context_poster_agent_id(cfg, platform),
                "contains": contains_all(content, context_terms),
                "preview": content[:500],
            }
        contexts[platform] = platform_contexts

    checks = [
        check(
            "simulation_lifecycle_state",
            prelaunch_locked or stage03_completed,
            (
                f"mode={lifecycle_mode} state_status={state.get('status')} "
                f"run_status={run_state.get('runner_status')} total_rounds={run_state.get('total_rounds')} "
                f"actions={run_state.get('total_actions_count')} telemetry={postrun.get('status')}"
            ),
        ),
        check(
            "project_graph_identity",
            cfg.get("project_id") == PROJECT_ID and cfg.get("graph_id") == GRAPH_ID,
            f"project={cfg.get('project_id')} graph={cfg.get('graph_id')}",
        ),
        check(
            "scheduled_events_default_cap_30",
            default_max_rounds == 30 and default_source == "scheduled_events_default",
            f"default_max_rounds={default_max_rounds} source={default_source}",
        ),
        check(
            "explicit_real_cap_30",
            requested_30_rounds == 30,
            f"requested_30_rounds={requested_30_rounds}",
        ),
        check(
            "stress_cap_still_honored",
            stress_cap_2 == 2,
            f"stress_cap_2={stress_cap_2}",
        ),
        check(
            "scheduled_event_count",
            len(scheduled_events) == 30,
            f"scheduled_events={len(scheduled_events)}",
        ),
        check(
            "forecast_ballot_rounds",
            set(int(item) for item in forecast_rounds) == {3, 6, 11, 18, 22, 25, 30},
            f"forecast_rounds={forecast_rounds}",
        ),
        check(
            "runner_publishes_event_context",
            "publish_round_event_context" in runner_text
            and "format_round_event_context_post" in runner_text
            and "round_event=round_event" in runner_text,
            "runner contains context publisher and round_event logging",
        ),
        check(
            "runner_passes_resolved_cap",
            "resolve_effective_max_rounds" in runner_text
            and "--max-rounds" in runner_text
            and "effective_max_rounds" in runner_text,
            "runner resolves and forwards effective_max_rounds",
        ),
        check(
            "service_persists_launch_controls",
            "max_rounds_applied" in service_text
            and "graph_memory_update_enabled" in service_text
            and "launch_command" in service_text,
            "run_state includes cap, graph memory, graph id, command",
        ),
        check(
            "api_graph_memory_default_on_when_graph_exists",
            "_parse_bool" in api_text
            and "default=bool(graph_id)" in api_text
            and "requested_graph_memory_update" in api_text,
            "api defaults graph memory on when graph_id is present",
        ),
        check(
            "api_accepts_and_validates_explicit_graph_id",
            "requested_graph_id" in api_text
            and "known_graph_ids" in api_text
            and "graph_id does not match simulation/project graph" in api_text,
            "api payload can name graph_id and rejects mismatches",
        ),
        check(
            "telemetry_reads_event_markers",
            "round_event_markers" in telemetry_text
            and "event_marker_ballot_rounds" in telemetry_text,
            "postrun telemetry extracts round_event markers",
        ),
    ]

    for platform in ("twitter", "reddit"):
        for round_num in ("1", "3", "30"):
            contains = contexts[platform][round_num]["contains"]
            checks.append(check(
                f"{platform}_round_{round_num}_context_contains_required_terms",
                all(contains.values()),
                json.dumps(contains, sort_keys=True),
            ))
    for platform in ("twitter", "reddit"):
        checks.append(check(
            f"{platform}_round_3_ballot_marker",
            contexts[platform]["3"]["forecast_ballot_required"] is True
            and contexts[platform]["3"]["forecast_ballot_phrase"] is True,
            f"beat_id={contexts[platform]['3']['event_beat_id']} phrase={contexts[platform]['3']['forecast_ballot_phrase']}",
        ))

    visibility_matrix = {
        "event beat map": "runtime-visible to Twitter/common and Reddit/boost via per-round context post; logged as round_event",
        "state variables": "runtime-visible via state-variable focus and all-state metadata; logged as round_event",
        "forecast ballots": "runtime-visible on rounds 3, 6, 11, 18, 22, 25, 30; telemetry extracts ballot markers",
        "causal attribution": "runtime-visible via causal attribution prompt; report still owns full ledger",
        "options/microstructure brief": "runtime-visible via per-round context post",
        "live context patch": "runtime-visible via per-round context post and seed prompt",
        "broker/account segmentation": "runtime-visible via context post and profile fields",
        "validation thresholds": "mostly ReportAgent/telemetry-focused; agents see branch/false-attribution cues",
        "control/counterfactual branch": "runtime-visible via every round context post",
        "TradingAgents advisory purpose": "runtime-visible via context post and simulation requirement",
    }

    return {
        "status": "pass" if all(item["passed"] for item in checks) else "fail",
        "simulation_id": SIMULATION_ID,
        "project_id": cfg.get("project_id"),
        "graph_id": cfg.get("graph_id"),
        "default_max_rounds": default_max_rounds,
        "default_max_rounds_source": default_source,
        "lifecycle_mode": lifecycle_mode,
        "stage03_completed": stage03_completed,
        "requested_30_rounds": requested_30_rounds,
        "stress_cap_2": stress_cap_2,
        "scheduled_event_count": len(scheduled_events),
        "forecast_ballot_rounds": forecast_rounds,
        "contexts": contexts,
        "visibility_matrix": visibility_matrix,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check MiroFish launch-path integrity without starting Stage 03.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    report = build_integrity_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"MiroFish launch-path integrity: {report['status'].upper()}")
        for item in report["checks"]:
            marker = "PASS" if item["passed"] else "FAIL"
            print(f"- {marker}: {item['name']} ({item['evidence']})")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
