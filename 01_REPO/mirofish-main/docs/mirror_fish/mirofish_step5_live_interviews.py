"""Run or audit true live MiroFish Step 5 interviews.

This script does not synthesize fake transcripts. It first checks whether the
simulation runner is actually alive and connected to IPC. If it is not, it
writes a live-unavailable artifact with the exact reason. If it is live, it
sends batch interview commands through the real SimulationRunner IPC path.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.simulation_runner import SimulationRunner  # noqa: E402


DEFAULT_SIMULATION_ID = "sim_974459649906"
DEFAULT_QUESTIONS = [
    "What is most likely wrong in this simulation?",
    "Which branch would most change tomorrow's trading assumptions?",
    "What real data would falsify the report fastest?",
    "Which signals are most likely false positives?",
    "What should TradingAgents watch first tomorrow?",
    "What should TradingAgents explicitly ignore?",
    "Which broker/API/macro/options evidence has the highest update value?",
]
QUALITY_INSTRUCTIONS = """You are answering a MiroFish Step 5 post-run interview.

Quality requirements:
- Answer in English only.
- Answer all seven numbered questions directly.
- Do not return JSON, tool-call syntax, code fences, or social-post wrappers.
- Keep the answer advisory-only: no trade orders, no direct buy/sell triggers.
- If you lack direct evidence, say what must be validated instead of refusing.
- Separate simulated evidence from real-market validation needs.
"""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _simulation_dir(simulation_id: str) -> Path:
    return REPO_ROOT / "backend" / "uploads" / "simulations" / simulation_id


def _select_targets(
    simulation_id: str,
    max_agents: int,
    agent_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    sim_dir = _simulation_dir(simulation_id)
    telemetry = _read_json(sim_dir / "postrun_telemetry.json")
    raw = telemetry.get("agents_to_interview_in_stage05") or telemetry.get("top_influential_agents") or []
    if not raw:
        config = _read_json(sim_dir / "simulation_config.json")
        raw = [
            {
                "agent_id": item.get("agent_id"),
                "agent_name": item.get("entity_name") or item.get("realname"),
                "actor_layer": item.get("entity_type"),
                "actions": None,
            }
            for item in config.get("agent_configs", [])
            if isinstance(item, dict) and item.get("agent_id") is not None
        ]
    if agent_ids:
        wanted = {int(agent_id): idx for idx, agent_id in enumerate(agent_ids)}
        raw = sorted(
            [item for item in raw if int(item.get("agent_id", -1)) in wanted],
            key=lambda item: wanted[int(item.get("agent_id"))],
        )
    targets: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            agent_id = int(item.get("agent_id"))
        except (TypeError, ValueError):
            continue
        if agent_id in seen:
            continue
        seen.add(agent_id)
        targets.append({
            "agent_id": agent_id,
            "agent_name": item.get("agent_name") or f"Agent {agent_id}",
            "actor_layer": item.get("actor_layer"),
            "actions": item.get("actions"),
        })
        if len(targets) >= max_agents:
            break
    return targets


def _combined_prompt() -> str:
    questions = "\n".join(f"{idx}. {question}" for idx, question in enumerate(DEFAULT_QUESTIONS, 1))
    return f"{QUALITY_INSTRUCTIONS}\nQuestions:\n{questions}"


def _render_markdown(data: dict[str, Any]) -> str:
    readiness = data.get("readiness") or {}
    lines = [
        "# MiroFish Step 5 Live Interview Attempt",
        "",
        f"- Simulation ID: `{data.get('simulation_id')}`",
        f"- Status: `{data.get('status')}`",
        f"- Generated at: `{data.get('generated_at')}`",
        f"- Live interviews available: `{readiness.get('live_interviews_available')}`",
        f"- Reason: `{readiness.get('reason')}`",
        f"- Runner status: `{readiness.get('runner_status')}`",
        f"- Process PID: `{readiness.get('process_pid')}`",
        f"- Runner process alive: `{readiness.get('runner_process_alive')}`",
        f"- IPC env alive: `{readiness.get('ipc_env_alive')}`",
        f"- Stale env status: `{readiness.get('stale_env_status')}`",
        "",
        "## Questions",
        "",
    ]
    for idx, question in enumerate(data.get("questions") or [], 1):
        lines.append(f"{idx}. {question}")

    lines.extend(["", "## Targets", ""])
    targets = data.get("targets") or []
    if targets:
        for target in targets:
            lines.append(
                f"- Agent `{target.get('agent_id')}`: {target.get('agent_name')} "
                f"({target.get('actor_layer') or 'unknown layer'}, actions={target.get('actions')})"
            )
    else:
        lines.append("- No targets selected.")

    lines.extend(["", "## Interview Result", ""])
    if data.get("status") == "completed":
        result = data.get("result") or {}
        results = ((result.get("result") or {}).get("results") if isinstance(result.get("result"), dict) else {}) or {}
        if results:
            for key, value in results.items():
                response = value.get("response") if isinstance(value, dict) else value
                lines.extend([f"### {key}", "", str(response or "").strip() or "(empty response)", ""])
        else:
            lines.append("- Live call returned no transcript results.")
    else:
        lines.append("- No live transcript generated. The artifact is an availability proof, not a replay interview.")

    if data.get("error"):
        lines.extend(["", "## Error", "", f"`{data.get('error')}`"])

    return "\n".join(lines) + "\n"


def run_step5_live_interviews(
    *,
    simulation_id: str,
    output_dir: Path,
    max_agents: int,
    timeout: float,
    platform: str | None,
    agent_ids: list[int] | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"step5_live_interviews_{stamp}.json"
    md_path = output_dir / f"step5_live_interviews_{stamp}.md"

    readiness = SimulationRunner.get_live_interview_readiness(simulation_id)
    targets = _select_targets(simulation_id, max_agents=max_agents, agent_ids=agent_ids)
    data: dict[str, Any] = {
        "schema": "mirofish.step5_live_interviews.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "simulation_id": simulation_id,
        "status": "live_unavailable",
        "readiness": readiness,
        "questions": DEFAULT_QUESTIONS,
        "quality_instructions": QUALITY_INSTRUCTIONS.strip(),
        "targets": targets,
        "platform": platform,
        "timeout": timeout,
        "result": None,
        "error": None,
    }

    if readiness.get("live_interviews_available"):
        interviews = [{"agent_id": target["agent_id"], "prompt": _combined_prompt()} for target in targets]
        if not interviews:
            data["status"] = "failed"
            data["error"] = "No Stage 5 interview targets were available."
        else:
            try:
                result = SimulationRunner.interview_agents_batch(
                    simulation_id=simulation_id,
                    interviews=interviews,
                    platform=platform,
                    timeout=timeout,
                )
                data["result"] = result
                data["status"] = "completed" if result.get("success") else "failed"
                if not result.get("success"):
                    data["error"] = result.get("error") or "Live interview API returned unsuccessful result."
            except Exception as exc:  # noqa: BLE001 - artifact must preserve exact failed live reason.
                data["status"] = "failed"
                data["error"] = f"{type(exc).__name__}: {exc}"

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(data), encoding="utf-8")
    return data, json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attempt true live Step 5 interviews or write readiness proof.")
    parser.add_argument("--simulation-id", default=DEFAULT_SIMULATION_ID)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "backend" / "uploads" / "reports" / DEFAULT_SIMULATION_ID / "step5_live"),
    )
    parser.add_argument("--max-agents", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--platform", choices=["twitter", "reddit"], default=None)
    parser.add_argument(
        "--agent-ids",
        default=None,
        help="Optional comma-separated agent ids to interview in this exact order.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data, json_path, md_path = run_step5_live_interviews(
        simulation_id=args.simulation_id,
        output_dir=Path(args.output_dir),
        max_agents=max(1, args.max_agents),
        timeout=args.timeout,
        platform=args.platform,
        agent_ids=[int(item) for item in args.agent_ids.split(",")] if args.agent_ids else None,
    )
    print(json.dumps({
        "status": data["status"],
        "live_interviews_available": data["readiness"].get("live_interviews_available"),
        "reason": data["readiness"].get("reason"),
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }, ensure_ascii=False, indent=2))
    return 0 if data["status"] in {"completed", "live_unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
