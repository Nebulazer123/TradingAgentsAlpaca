#!/usr/bin/env python3
"""Guarded app-path setup helper for MiroFish stage 01 and stage 02.

Default mode is dry-run and does not call MiroFish, LLMs, OpenRouter, or Zep.
Execution requires an exact confirmation phrase. This helper intentionally has
no stage 03 start command.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests


ROOT = Path(__file__).resolve().parents[2]
DOC_DIR = ROOT / "docs" / "mirror_fish"
SEED_FILE = DOC_DIR / "MIRROR_FISH_PDT_REALITY_SEED.md"
PROMPT_FILE = DOC_DIR / "MIRROR_FISH_PDT_SIMULATION_PROMPT.md"
READINESS_FILE = DOC_DIR / "MIRROR_FISH_TRADING_RUN_READINESS.md"
CONFIRM_STAGE01 = "run-mirofish-stage01-setup"
CONFIRM_STAGE02 = "run-mirofish-stage02-setup"


def extract_simulation_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8", errors="replace").strip()
    text = READINESS_FILE.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"## 9\. Final Simulation Prompt To Paste Into MiroFish\s+(.*?)\s+## 10\.",
        text,
        flags=re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return (
        "Simulate the market-social reaction around the June 4, 2026 U.S. "
        "PDT-to-intraday-margin transition through the June 13 macro/options window."
    )


def api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def require_success(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Non-JSON response {response.status_code}: {response.text[:500]}") from exc
    if response.status_code >= 400 or not payload.get("success", False):
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def post_json(base_url: str, path: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    response = requests.post(api_url(base_url, path), json=payload, timeout=timeout)
    return require_success(response)


def get_json(base_url: str, path: str, timeout: int) -> Dict[str, Any]:
    response = requests.get(api_url(base_url, path), timeout=timeout)
    return require_success(response)


def poll_graph_task(base_url: str, task_id: str, timeout_sec: int, interval_sec: int) -> Dict[str, Any]:
    deadline = time.time() + timeout_sec
    last: Optional[Dict[str, Any]] = None
    while time.time() < deadline:
        last = get_json(base_url, f"/api/graph/task/{task_id}", timeout=30)
        data = last.get("data", {})
        status = str(data.get("status", "")).lower()
        if status in {"completed", "success", "failed", "error"}:
            return last
        time.sleep(interval_sec)
    raise TimeoutError(f"Graph task did not finish within {timeout_sec}s; last={last}")


def poll_prepare_task(base_url: str, task_id: str, simulation_id: str, timeout_sec: int, interval_sec: int) -> Dict[str, Any]:
    deadline = time.time() + timeout_sec
    last: Optional[Dict[str, Any]] = None
    while time.time() < deadline:
        last = post_json(
            base_url,
            "/api/simulation/prepare/status",
            {"task_id": task_id, "simulation_id": simulation_id},
            timeout=30,
        )
        data = last.get("data", {})
        status = str(data.get("status", "")).lower()
        if status in {"ready", "completed", "failed", "error"}:
            return last
        time.sleep(interval_sec)
    raise TimeoutError(f"Prepare task did not finish within {timeout_sec}s; last={last}")


def run_stage01(args: argparse.Namespace) -> Dict[str, Any]:
    if args.confirm != CONFIRM_STAGE01:
        raise SystemExit(f"Stage 01 execution requires --confirm {CONFIRM_STAGE01!r}")

    prompt = extract_simulation_prompt()
    with SEED_FILE.open("rb") as handle:
        response = requests.post(
            api_url(args.base_url, "/api/graph/ontology/generate"),
            data={
                "project_name": args.project_name,
                "simulation_requirement": prompt,
                "additional_context": args.additional_context,
            },
            files={"files": (SEED_FILE.name, handle, "text/markdown")},
            timeout=args.request_timeout,
        )
    ontology = require_success(response)
    project_id = ontology["data"]["project_id"]

    build = post_json(
        args.base_url,
        "/api/graph/build",
        {
            "project_id": project_id,
            "graph_name": args.graph_name,
            "chunk_size": args.chunk_size,
            "chunk_overlap": args.chunk_overlap,
            "force": False,
        },
        timeout=args.request_timeout,
    )
    task_id = build["data"]["task_id"]
    result: Dict[str, Any] = {
        "stage": "stage01",
        "project_id": project_id,
        "graph_build_task_id": task_id,
        "ontology_response": ontology,
        "build_response": build,
        "stage03_gate": "closed; this helper does not start simulation",
    }
    if args.wait:
        result["graph_task_result"] = poll_graph_task(args.base_url, task_id, args.wait_timeout, args.poll_interval)
        project = get_json(args.base_url, f"/api/graph/project/{project_id}", timeout=args.request_timeout)
        result["project"] = project
        result["graph_id"] = project.get("data", {}).get("graph_id")
    return result


def run_stage02(args: argparse.Namespace) -> Dict[str, Any]:
    if args.confirm != CONFIRM_STAGE02:
        raise SystemExit(f"Stage 02 execution requires --confirm {CONFIRM_STAGE02!r}")
    if not args.project_id or not args.graph_id:
        raise SystemExit("Stage 02 execution requires --project-id and --graph-id")

    created = post_json(
        args.base_url,
        "/api/simulation/create",
        {
            "project_id": args.project_id,
            "graph_id": args.graph_id,
            "enable_twitter": True,
            "enable_reddit": True,
        },
        timeout=args.request_timeout,
    )
    simulation_id = created["data"]["simulation_id"]
    prepared = post_json(
        args.base_url,
        "/api/simulation/prepare",
        {
            "simulation_id": simulation_id,
            "use_llm_for_profiles": True,
            "parallel_profile_count": args.parallel_profile_count,
            "force_regenerate": False,
        },
        timeout=args.request_timeout,
    )
    result: Dict[str, Any] = {
        "stage": "stage02",
        "project_id": args.project_id,
        "graph_id": args.graph_id,
        "simulation_id": simulation_id,
        "create_response": created,
        "prepare_response": prepared,
        "stage03_gate": "closed; this helper does not start simulation",
    }
    task_id = prepared.get("data", {}).get("task_id")
    if args.wait and task_id:
        result["prepare_task_result"] = poll_prepare_task(
            args.base_url,
            task_id,
            simulation_id,
            args.wait_timeout,
            args.poll_interval,
        )
        result["config_path"] = str(ROOT / "backend" / "uploads" / "simulations" / simulation_id / "simulation_config.json")
    return result


def dry_run(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "mode": "dry_run",
        "read_only": True,
        "side_effects": "none",
        "base_url": args.base_url,
        "seed_file": str(SEED_FILE),
        "prompt_file": str(PROMPT_FILE),
        "project_name": args.project_name,
        "graph_name": args.graph_name,
        "quality_first_model_route": {
            "primary": "qwen/qwen3.6-plus",
            "boost": "deepseek/deepseek-v4-pro",
            "cost_value_fallback": "qwen/qwen-plus-2025-07-28:thinking",
            "quality_fallback": "google/gemini-3-flash-preview",
        },
        "stage01_when_approved": [
            "POST /api/graph/ontology/generate with seed file and simulation prompt",
            "POST /api/graph/build with project_id",
            "poll GET /api/graph/task/<task_id> if --wait is used",
            "record project_id and graph_id",
        ],
        "stage02_when_approved": [
            "POST /api/simulation/create with project_id and graph_id",
            "POST /api/simulation/prepare with use_llm_for_profiles=true",
            "poll POST /api/simulation/prepare/status if --wait is used",
            "record simulation_id and simulation_config.json path",
        ],
        "confirm_phrases": {
            "stage01": CONFIRM_STAGE01,
            "stage02": CONFIRM_STAGE02,
        },
        "stage03_gate": "closed; this helper intentionally has no stage 03 start action",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded MiroFish app-path setup helper.")
    parser.add_argument("--base-url", default="http://localhost:5001")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--execute-stage01", action="store_true")
    parser.add_argument("--execute-stage02", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--project-name", default="MiroFish PDT Intraday Margin 2026-06-04")
    parser.add_argument("--graph-name", default="MiroFish PDT Intraday Margin Graph")
    parser.add_argument("--additional-context", default="Quality-first setup for PDT/intraday-margin social-market simulation.")
    parser.add_argument("--project-id")
    parser.add_argument("--graph-id")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    parser.add_argument("--parallel-profile-count", type=int, default=5)
    parser.add_argument("--request-timeout", type=int, default=300)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--wait-timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=int, default=5)
    args = parser.parse_args()

    if args.execute_stage01 and args.execute_stage02:
        raise SystemExit("Run stage 01 and stage 02 separately so artifacts can be reviewed between gates.")

    if args.execute_stage01:
        result = run_stage01(args)
    elif args.execute_stage02:
        result = run_stage02(args)
    else:
        result = dry_run(args)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
