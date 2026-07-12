#!/usr/bin/env python3
"""Read-only completion audit for the MiroFish PDT run plan.

This audit exists to prevent a false "complete" signal. It checks whether the
planning artifacts, model route, local health, creator workflow coverage, and
approval gates are in the expected state, while keeping the real simulation
locked until the user approves the real stage 03 run.

It does not call external LLM APIs, does not write to Zep, and does not start
MiroFish stages.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


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


STALE_PATTERNS = [
    re.compile(r"anthropic", re.IGNORECASE),
    re.compile(r"\bClaude\b", re.IGNORECASE),
    re.compile(r"speed/cost balance", re.IGNORECASE),
    re.compile(r"fastest Qwen", re.IGNORECASE),
    re.compile(r"current primary recommendation due speed", re.IGNORECASE),
    re.compile(r"Primary/common swarm lane:\s*`qwen/qwen-plus-2025-07-28:thinking`"),
]


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


def stale_hits(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for path in paths:
        text = read_text(path)
        if not text:
            continue
        for pattern in STALE_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append({"path": str(path), "line": line, "pattern": pattern.pattern})
    return hits


def requirement(name: str, status: str, evidence: str, blocks_goal_complete: bool) -> Dict[str, Any]:
    return {
        "requirement": name,
        "status": status,
        "evidence": evidence,
        "blocks_goal_complete": blocks_goal_complete,
    }


def build_audit(skip_health: bool) -> Dict[str, Any]:
    preflight_args = [str(DOC_DIR / "mirofish_preflight.py"), "--json"]
    if skip_health:
        preflight_args.append("--skip-health")

    commands = {
        "preflight": run_json_command("preflight", preflight_args),
        "workflow_audit": run_json_command("workflow_audit", [str(DOC_DIR / "mirofish_workflow_audit.py"), "--json"]),
        "cost_estimate": run_json_command(
            "cost_estimate",
            [str(DOC_DIR / "mirofish_cost_estimator.py"), "--config", str(PREPARED_CONFIG), "--max-rounds", "30"],
        ),
        "app_path_setup_dry_run": run_json_command(
            "app_path_setup_dry_run",
            [str(DOC_DIR / "mirofish_app_path_setup.py"), "--json"],
        ),
    }

    preflight = commands["preflight"]["json"] or {}
    workflow = commands["workflow_audit"]["json"] or {}
    cost = commands["cost_estimate"]["json"] or {}
    app_setup = commands["app_path_setup_dry_run"]["json"] or {}

    readiness = read_text(DOC_DIR / "MIRROR_FISH_TRADING_RUN_READINESS.md")
    approval = read_text(DOC_DIR / "MIRROR_FISH_PRE_START_APPROVAL_PACKET.md")
    runbook = read_text(DOC_DIR / "MIRROR_FISH_OPERATOR_RUNBOOK.md")
    seed = read_text(DOC_DIR / "MIRROR_FISH_PDT_REALITY_SEED.md")
    scaffold = read_text(TRADING_AGENTS_SCAFFOLD)
    docs_to_scan = [
        DOC_DIR / "MIRROR_FISH_TRADING_RUN_READINESS.md",
        DOC_DIR / "MIRROR_FISH_PRE_START_APPROVAL_PACKET.md",
        DOC_DIR / "MIRROR_FISH_OPERATOR_RUNBOOK.md",
        TRADING_AGENTS_SCAFFOLD,
    ]
    stale = stale_hits(docs_to_scan)

    health = preflight.get("health", {})
    local_health_ok = skip_health or (
        bool(health.get("backend", {}).get("ok"))
        and bool(health.get("frontend", {}).get("ok"))
    )
    env = preflight.get("env_status", {})
    env_ok = bool(preflight.get("env_all_recommended"))
    env_model = env.get("LLM_MODEL_NAME", {}).get("actual")
    boost_model = env.get("LLM_BOOST_MODEL_NAME", {}).get("actual")
    prepared = preflight.get("prepared_run", {})
    prepared_ok = bool(prepared.get("prepared_stage01_stage02_ok"))
    stress_ok = bool(prepared.get("stress_stage03_capped_ok"))
    app_stage03_closed = "stage 03" in str(app_setup.get("stage03_gate", "")).lower()
    planning_guard_ok = not preflight.get("ready_for_stage03") and app_stage03_closed

    requirements = [
        requirement(
            "Do not start the real simulation during planning.",
            "complete" if planning_guard_ok else "incomplete",
            "preflight ready_for_stage03=false and app-path helper dry-run has no stage 03 action"
            if planning_guard_ok
            else "stage 03 guard evidence is incomplete",
            not planning_guard_ok,
        ),
        requirement(
            "Use the creators' full five-stage MiroFish workflow.",
            "source_covered" if workflow.get("ok") else "incomplete",
            f"workflow audit {workflow.get('passed')}/{workflow.get('total')} source checks",
            not bool(workflow.get("ok")),
        ),
        requirement(
            "Use the Deep Research seed and June 4-13 scenario branches.",
            "documented" if has_text(seed, "June 4", "Bot-correlation", "Broker-friction") else "incomplete",
            "seed contains PDT, broker-friction, bot-correlation, and macro/social branch framing",
            not has_text(seed, "June 4", "Bot-correlation", "Broker-friction"),
        ),
        requirement(
            "Include institutional, policy, media, developer, tech-executive, and retail actor layers.",
            "prepared"
            if prepared_ok
            and has_text(readiness, "government, regulator, and policy-maker reaction map", "institutional investor, market-maker, and liquidity-provider reaction map", "developer community, bot-framework")
            else "incomplete",
            "prepared simulation has 1,000 agents with expansion quotas for retail, broker/platform, developer, media, policy/regulatory, institutional/liquidity, and tech-company/executive layers",
            not prepared_ok,
        ),
        requirement(
            "Use direct OpenRouter and Zep routes without depending on Composio monthly calls.",
            "documented_and_keyed"
            if all(
                preflight.get("key_status_redacted", {}).get(key, {}).get("present")
                for key in ["LLM_API_KEY", "LLM_BOOST_API_KEY", "ZEP_API_KEY", "OPENROUTER_MANAGEMENT_API_KEY"]
            )
            and has_text(readiness, "openrouter_admin", "zep_cloud_admin")
            else "incomplete",
            "redacted key presence plus documented local OpenRouter/Zep admin MCP routes",
            not (
                all(
                    preflight.get("key_status_redacted", {}).get(key, {}).get("present")
                    for key in ["LLM_API_KEY", "LLM_BOOST_API_KEY", "ZEP_API_KEY", "OPENROUTER_MANAGEMENT_API_KEY"]
                )
                and has_text(readiness, "openrouter_admin", "zep_cloud_admin")
            ),
        ),
        requirement(
            "Route models as quality first and cost-value second.",
            "complete" if env_ok and env_model == "qwen/qwen3.6-plus" and boost_model == "deepseek/deepseek-v4-pro" and not stale else "incomplete",
            "env uses qwen/qwen3.6-plus plus deepseek/deepseek-v4-pro; stale model wording scan is clean"
            if not stale
            else f"stale wording hits: {len(stale)}",
            not (env_ok and env_model == "qwen/qwen3.6-plus" and boost_model == "deepseek/deepseek-v4-pro" and not stale),
        ),
        requirement(
            "Keep Gemini as a quality fallback, not an unapproved primary.",
            "documented" if has_text(readiness, "Gemini 3 Flash Preview", "quality fallback") else "incomplete",
            "readiness report records Gemini 3 Flash Preview as quality fallback and direct Gemini 3.5 as unpatched-failed",
            not has_text(readiness, "Gemini 3 Flash Preview", "quality fallback"),
        ),
        requirement(
            "Keep TradingAgents advisory-only and final handoff unsendable.",
            "documented"
            if has_text(scaffold, "DRAFT ONLY", "Do not use this file as trade truth", "Do not send")
            and has_text(approval, "advisory evidence packet", "handoff")
            else "incomplete",
            "TradingAgents scaffold and approval packet keep MiroFish evidence out of trade authority",
            not (
                has_text(scaffold, "DRAFT ONLY", "Do not use this file as trade truth", "Do not send")
                and has_text(approval, "advisory evidence packet", "handoff")
            ),
        ),
        requirement(
            "Verify local health and backend env refresh.",
            "complete" if local_health_ok and preflight.get("backend_env_refreshed_after_env_write") else "incomplete",
            "backend/frontend health ok and backend listener created after env write",
            not (local_health_ok and preflight.get("backend_env_refreshed_after_env_write")),
        ),
        requirement(
            "Run stage 01 app-path graph build and confirm Zep graph construction.",
            "complete" if prepared_ok else "incomplete",
            f"prepared project={prepared.get('project_id')} graph={prepared.get('graph_id')}",
            not prepared_ok,
        ),
        requirement(
            "Run stage 02 prepare/config/profile generation.",
            "complete" if prepared_ok else "incomplete",
            f"prepared simulation={prepared.get('simulation_id')} profiles={prepared.get('profiles_count')} expanded={prepared.get('expanded')}",
            not prepared_ok,
        ),
        requirement(
            "Expand the runnable OASIS population beyond the small extracted-entity count.",
            "complete" if prepared_ok and prepared.get("agent_count") == 1000 else "incomplete",
            f"agent_count={prepared.get('agent_count')} expansion_target={prepared.get('expansion_target')}",
            not (prepared_ok and prepared.get("agent_count") == 1000),
        ),
        requirement(
            "Estimate cost from the actual prepared simulation_config.json.",
            "complete" if commands["cost_estimate"]["ok"] and cost.get("mode") == "config" else "incomplete",
            f"actual config estimate mode={cost.get('mode')} mid={cost.get('estimated_stage03_cost_usd', {}).get('mid')} worst={cost.get('estimated_stage03_cost_usd', {}).get('worst')}",
            not (commands["cost_estimate"]["ok"] and cost.get("mode") == "config"),
        ),
        requirement(
            "Run a capped stage 03 proof on a copy without consuming the real simulation.",
            "complete" if stress_ok else "incomplete",
            f"stress={prepared.get('stress_simulation_id')} rounds={prepared.get('stress_total_rounds')} actions={prepared.get('stress_total_actions')}",
            not stress_ok,
        ),
        requirement(
            "Start stage 03 real simulation.",
            "locked_until_explicit_user_approval",
            "must remain locked until explicit real-run approval",
            True,
        ),
        requirement(
            "Generate stage 04 report and stage 05 deep interactions.",
            "locked_until_stage03_complete",
            "requires completed simulation artifacts; not part of pre-start planning",
            True,
        ),
        requirement(
            "Write final TradingAgents handoff.",
            "not_sendable",
            "handoff waits for run, report, deep interactions, Codex synthesis, and chat closeout",
            True,
        ),
    ]

    safety_violations = [
        item
        for item in requirements
        if item["status"] in {"incomplete"}
    ]
    goal_blockers = [
        item
        for item in requirements
        if item["blocks_goal_complete"]
        and item["status"] not in {"complete", "documented", "documented_and_keyed", "source_covered"}
    ]

    return {
        "root": str(ROOT),
        "read_only": True,
        "side_effects": "none; local helper subprocesses only",
        "audit_ok": all(command["ok"] for command in commands.values()) and not safety_violations,
        "goal_complete": False,
        "safe_to_start_stage03": False,
        "safe_to_mark_goal_complete": False,
        "reason_goal_not_complete": "the real stage 03 run, stage 04 report, stage 05 deep interactions, Codex synthesis, and final handoff remain gated",
        "requirements": requirements,
        "goal_blockers": goal_blockers,
        "stale_plan_hits": stale,
        "actual_config_cost_estimate": cost.get("estimated_stage03_cost_usd", {}),
        "prepared_run": prepared,
        "app_path_setup_preview": {
            "mode": app_setup.get("mode"),
            "read_only": app_setup.get("read_only"),
            "confirm_phrases": app_setup.get("confirm_phrases"),
            "stage03_gate": app_setup.get("stage03_gate"),
        },
        "commands": commands,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only completion audit for MiroFish PDT planning.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON audit.")
    parser.add_argument("--skip-health", action="store_true", help="Skip local backend/frontend health checks.")
    args = parser.parse_args()

    audit = build_audit(skip_health=args.skip_health)
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        print(f"MiroFish completion audit: {'PASS' if audit['audit_ok'] else 'CHECK'}")
        print(f"Goal complete: {audit['goal_complete']}")
        print(f"Safe to start stage 03: {audit['safe_to_start_stage03']}")
        print(f"Safe to mark goal complete: {audit['safe_to_mark_goal_complete']}")
        print(f"Reason: {audit['reason_goal_not_complete']}")
        print("\nRequirement statuses:")
        for item in audit["requirements"]:
            print(f"- {item['status']}: {item['requirement']}")
        print("\nGoal blockers:")
        for item in audit["goal_blockers"]:
            print(f"- {item['status']}: {item['requirement']}")
    return 0 if audit["audit_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
