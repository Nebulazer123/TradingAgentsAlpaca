#!/usr/bin/env python3
"""Collect a read-only MiroFish readiness snapshot.

This helper calls the other local readiness helpers and summarizes their JSON
outputs. It does not call LLM APIs, does not write to Zep, does not edit .env,
and does not start a MiroFish simulation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
DOC_DIR = ROOT / "docs" / "mirror_fish"
TRADING_AGENTS_SCAFFOLD = (
    ROOT.parent
    / "TradingAgents-main"
    / "reports"
    / "mirofish"
    / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
)
PREPARED_SIMULATION_ID = "sim_974459649906"
PREPARED_CONFIG = ROOT / "backend" / "uploads" / "simulations" / PREPARED_SIMULATION_ID / "simulation_config.json"


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def has_text(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def run_json_command(name: str, args: List[str]) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    parsed: Any = None
    parse_error = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    return {
        "name": name,
        "returncode": proc.returncode,
        "ok": proc.returncode == 0 and parse_error is None,
        "json": parsed,
        "parse_error": parse_error,
        "stderr": proc.stderr.strip()[:1000],
    }


def summarize(commands: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    env = commands["env_gate"]["json"] or {}
    workflow = commands["workflow_audit"]["json"] or {}
    preflight = commands["preflight"]["json"] or {}
    cost = commands["cost_estimate"]["json"] or {}
    actor = commands["actor_population_audit"]["json"] or {}
    completion = commands.get("completion_audit", {}).get("json") or {}
    readiness_text = read_text(DOC_DIR / "MIRROR_FISH_TRADING_RUN_READINESS.md")
    approval_text = read_text(DOC_DIR / "MIRROR_FISH_PRE_START_APPROVAL_PACKET.md")
    seed_text = read_text(DOC_DIR / "MIRROR_FISH_PDT_REALITY_SEED.md")
    scaffold_text = read_text(TRADING_AGENTS_SCAFFOLD)
    app_setup_exists = (DOC_DIR / "mirofish_app_path_setup.py").exists()

    health = preflight.get("health", {})
    cost_stage03 = cost.get("estimated_stage03_cost_usd", {})
    actions = cost.get("actions", {})
    key_status = preflight.get("key_status_redacted", {})
    prepared = preflight.get("prepared_run", {})
    env_ready = bool(env.get("all_recommended"))
    backend_refreshed = bool(preflight.get("backend_env_refreshed_after_env_write"))
    local_health = {
        "backend": bool(health.get("backend", {}).get("ok")),
        "frontend": bool(health.get("frontend", {}).get("ok")),
    }

    return {
        "bundle_ok": all(item["ok"] for item in commands.values()),
        "ready_for_stage03": False,
        "handoff_sendable": False,
        "stage03_gate": "closed until explicit user approval for the real stage 03 simulation",
        "handoff_gate": "final TradingAgents handoff remains draft-only until stage 03 run, stage 04 report, stage 05 deep interactions, Codex synthesis, and this chat's final decisions are complete",
        "prepared_run": prepared,
        "env_all_recommended": env_ready,
        "preflight_passed": bool(preflight.get("passed_readiness_preflight")),
        "actor_population_audit_ok": bool(actor.get("audit_ok")),
        "actor_population": {
            "agent_count": actor.get("agent_count"),
            "non_retail_quota": actor.get("non_retail_quota"),
            "non_retail_entity_count": actor.get("non_retail_entity_count"),
            "entity_type_counts": actor.get("entity_type_counts"),
            "initial_post_type_counts": actor.get("initial_post_type_counts"),
            "prompt_requirements": actor.get("prompt_requirements"),
            "layers": {
                layer: {
                    "ok": item.get("ok"),
                    "entity_count": item.get("entity_count"),
                    "quota": item.get("quota"),
                    "initial_post_count": item.get("initial_post_count"),
                    "missing_anchors": item.get("missing_anchors"),
                    "missing_prompt_terms": item.get("missing_prompt_terms"),
                }
                for layer, item in (actor.get("layers") or {}).items()
                if isinstance(item, dict)
            },
        },
        "completion_audit_ok": bool(completion.get("audit_ok")),
        "goal_complete": bool(completion.get("goal_complete")),
        "safe_to_mark_goal_complete": bool(completion.get("safe_to_mark_goal_complete")),
        "completion_goal_blockers": [
            {
                "requirement": item.get("requirement"),
                "status": item.get("status"),
                "evidence": item.get("evidence"),
            }
            for item in completion.get("goal_blockers", [])
        ],
        "workflow_ok": bool(workflow.get("ok")),
        "workflow_checks": {
            "passed": workflow.get("passed"),
            "total": workflow.get("total"),
        },
        "local_health": local_health,
        "backend_env_refreshed_after_env_write": backend_refreshed,
        "approval_gate_ledger": [
            {
                "gate": "env_model_route",
                "status": "complete" if env_ready else "needs_user_approval",
                "can_run_without_user": True,
                "evidence": "quality-first .env route matches Qwen3.6 Plus plus DeepSeek V4 Pro" if env_ready else "env route does not match the recommended quality-first route",
            },
            {
                "gate": "backend_refresh",
                "status": "complete" if backend_refreshed and local_health["backend"] else "needs_refresh",
                "can_run_without_user": True,
                "evidence": "backend listener was created after the .env write and health is ok" if backend_refreshed and local_health["backend"] else "backend health/refresh proof is incomplete",
            },
            {
                "gate": "stage01_app_path_graph_build",
                "status": "complete" if prepared.get("prepared_stage01_stage02_ok") else "check",
                "can_run_without_user": True,
                "evidence": f"project={prepared.get('project_id')} graph={prepared.get('graph_id')}",
            },
            {
                "gate": "stage02_prepare_profiles_config",
                "status": "complete" if prepared.get("prepared_stage01_stage02_ok") else "check",
                "can_run_without_user": True,
                "evidence": f"simulation={prepared.get('simulation_id')} profiles={prepared.get('profiles_count')} expanded={prepared.get('expanded')}",
            },
            {
                "gate": "population_expansion",
                "status": "complete" if prepared.get("agent_count") == 1000 else "check",
                "can_run_without_user": True,
                "evidence": f"agent_count={prepared.get('agent_count')} quotas={sorted((prepared.get('category_quotas') or {}).keys())}",
            },
            {
                "gate": "actor_population_audit",
                "status": "complete" if actor.get("audit_ok") else "check",
                "can_run_without_user": True,
                "evidence": f"non_retail_quota={actor.get('non_retail_quota')} non_retail_entity_count={actor.get('non_retail_entity_count')}",
            },
            {
                "gate": "actual_config_cost_estimate",
                "status": "complete" if cost.get("mode") == "config" else "check",
                "can_run_without_user": True,
                "evidence": f"cost mode={cost.get('mode')} mid=${cost_stage03.get('mid')} worst=${cost_stage03.get('worst')}",
            },
            {
                "gate": "capped_stage03_stress_copy",
                "status": "complete" if prepared.get("stress_stage03_capped_ok") else "check",
                "can_run_without_user": True,
                "evidence": f"stress={prepared.get('stress_simulation_id')} rounds={prepared.get('stress_total_rounds')} actions={prepared.get('stress_total_actions')}",
            },
            {
                "gate": "stage03_real_simulation_start",
                "status": "locked_until_explicit_user_approval",
                "can_run_without_user": False,
                "evidence": "stage 03 real run remains closed until the user explicitly approves launch",
            },
            {
                "gate": "stage04_report_generation",
                "status": "locked_until_stage03_complete",
                "can_run_without_user": False,
                "evidence": "report requires completed simulation artifacts",
            },
            {
                "gate": "stage05_deep_interaction",
                "status": "locked_until_stage04_complete",
                "can_run_without_user": False,
                "evidence": "deep interaction requires ReportAgent output and preserved simulation environment",
            },
            {
                "gate": "final_tradingagents_handoff",
                "status": "not_sendable",
                "can_run_without_user": False,
                "evidence": "final handoff waits for run, report, deep interactions, Codex synthesis, and chat closeout",
            },
        ],
        "cost_estimate": {
            "mode": cost.get("mode"),
            "models": cost.get("models"),
            "per_platform_actions": actions.get("per_platform_actions"),
            "dual_platform_actions": actions.get("dual_platform_actions"),
            "stage03_cost_usd": cost_stage03,
            "notes": cost.get("notes", []),
        },
        "objective_alignment": [
            {
                "requirement": "Prepare only; do not start the real simulation.",
                "status": "gated",
                "evidence": "the real simulation remains gated; only a capped stress copy has been run.",
            },
            {
                "requirement": "Use the creators' five-stage MiroFish workflow.",
                "status": "source_covered" if workflow.get("ok") else "check",
                "evidence": f"workflow audit {workflow.get('passed')}/{workflow.get('total')} static source checks.",
            },
            {
                "requirement": "Integrate Deep Research seed and scenario branches.",
                "status": "documented" if has_text(seed_text, "June 4", "broker", "Bot-correlation") else "check",
                "evidence": "MIRROR_FISH_PDT_REALITY_SEED.md is the upload source and contains the PDT/broker/macro/bot branch framing.",
            },
            {
                "requirement": "Use direct Zep/OpenRouter routes without relying on Composio monthly calls.",
                "status": "keyed_and_documented"
                if all(key_status.get(key, {}).get("present") for key in ["LLM_API_KEY", "LLM_BOOST_API_KEY", "ZEP_API_KEY", "OPENROUTER_MANAGEMENT_API_KEY"])
                and "openrouter_admin" in readiness_text
                and "zep_cloud_admin" in readiness_text
                else "check",
                "evidence": "redacted key presence plus local MCP/admin tooling documentation.",
            },
            {
                "requirement": "Route non-retail entities into the real run.",
                "status": "prepared" if actor.get("audit_ok") else "check",
                "evidence": f"actor audit confirms non-retail quota={actor.get('non_retail_quota')} and non-retail entity count={actor.get('non_retail_entity_count')} across broker/platform, developer, media, policy/regulatory, institutional/liquidity, and tech-company/executive layers.",
            },
            {
                "requirement": "Model routing for the approved run.",
                "status": "current_quality_first_qwen",
                "evidence": "current docs record Qwen3.6 Plus as quality-first primary, DeepSeek V4 Pro as boost, Qwen Plus 0728 Thinking as cost-value fallback, and Gemini 3 Flash Preview as quality fallback.",
            },
            {
                "requirement": "TradingAgents output must remain advisory only.",
                "status": "documented"
                if has_text(scaffold_text, "DRAFT ONLY", "Do not use this file as trade truth", "Do not send")
                and "advisory evidence packet" in approval_text
                else "check",
                "evidence": "TradingAgents scaffold and approval packet keep MiroFish output out of order authority.",
            },
            {
                "requirement": "Final handoff must not be sendable yet.",
                "status": "closed",
                "evidence": "handoff_sendable=false until run, report, deep interactions, synthesis, and chat closeout complete.",
            },
        ],
        "remaining_gates": [
            *preflight.get("remaining_gates", []),
            "write final TradingAgents handoff only after the run, report, deep interactions, synthesis, and chat closeout",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MiroFish readiness snapshot bundle.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON bundle.")
    parser.add_argument("--agents", type=int, default=1000)
    parser.add_argument("--max-rounds", type=int, default=30)
    parser.add_argument("--cost-config", type=Path, help="Optional prepared simulation_config.json.")
    parser.add_argument("--skip-health", action="store_true", help="Skip local backend/frontend health checks.")
    args = parser.parse_args()

    preflight_args = [str(DOC_DIR / "mirofish_preflight.py"), "--json"]
    if args.skip_health:
        preflight_args.append("--skip-health")

    cost_args = [str(DOC_DIR / "mirofish_cost_estimator.py"), "--max-rounds", str(args.max_rounds)]
    effective_cost_config = args.cost_config
    if effective_cost_config is None and PREPARED_CONFIG.exists():
        effective_cost_config = PREPARED_CONFIG

    if effective_cost_config:
        cost_args.extend(["--config", str(effective_cost_config)])
    else:
        cost_args.extend(["--agents", str(args.agents)])

    commands = {
        "env_gate": run_json_command("env_gate", [str(DOC_DIR / "mirofish_env_gate.py"), "--json"]),
        "workflow_audit": run_json_command("workflow_audit", [str(DOC_DIR / "mirofish_workflow_audit.py"), "--json"]),
        "preflight": run_json_command("preflight", preflight_args),
        "actor_population_audit": run_json_command("actor_population_audit", [str(DOC_DIR / "mirofish_actor_population_audit.py"), "--json"]),
        "cost_estimate": run_json_command("cost_estimate", cost_args),
        "completion_audit": run_json_command("completion_audit", [str(DOC_DIR / "mirofish_completion_audit.py"), "--json", *(["--skip-health"] if args.skip_health else [])]),
    }

    result = {
        "root": str(ROOT),
        "read_only": True,
        "side_effects": "none; local helper subprocesses only",
        "summary": summarize(commands),
        "commands": commands,
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        summary = result["summary"]
        print(f"MiroFish readiness bundle: {'PASS' if summary['bundle_ok'] else 'CHECK'}")
        print(f"Stage 03 gate: {summary['stage03_gate']}")
        print(f"Final handoff: {'sendable' if summary['handoff_sendable'] else 'not sendable'}")
        print(f"Env route recommended: {summary['env_all_recommended']}")
        print(f"Preflight: {summary['preflight_passed']}")
        actor = summary["actor_population"]
        print(f"Actor population audit: {summary['actor_population_audit_ok']} non-retail quota={actor.get('non_retail_quota')} non-retail entities={actor.get('non_retail_entity_count')}")
        print(f"Completion audit: {summary['completion_audit_ok']}")
        print(f"Goal complete: {summary['goal_complete']}")
        print(f"Safe to mark goal complete: {summary['safe_to_mark_goal_complete']}")
        checks = summary["workflow_checks"]
        print(f"Workflow audit: {summary['workflow_ok']} ({checks['passed']}/{checks['total']})")
        health = summary["local_health"]
        print(f"Local health: backend={health['backend']} frontend={health['frontend']}")
        print(f"Backend env refreshed: {summary['backend_env_refreshed_after_env_write']}")
        cost_summary = summary["cost_estimate"]
        cost = cost_summary["stage03_cost_usd"]
        print(f"Stage 03 active-agent cost ({cost_summary['mode']}): mid=${cost.get('mid')} worst=${cost.get('worst')}")
        print("Objective alignment:")
        for item in summary["objective_alignment"]:
            print(f"- {item['status']}: {item['requirement']}")
        print("Approval gates:")
        for item in summary["approval_gate_ledger"]:
            print(f"- {item['gate']}: {item['status']}")
        print("Goal blockers:")
        for item in summary["completion_goal_blockers"]:
            print(f"- {item['status']}: {item['requirement']}")
        print("Remaining gates:")
        for gate in summary["remaining_gates"]:
            print(f"- {gate}")

    return 0 if result["summary"]["bundle_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
