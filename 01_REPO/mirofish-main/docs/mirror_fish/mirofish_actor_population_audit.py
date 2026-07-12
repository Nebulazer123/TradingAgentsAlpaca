#!/usr/bin/env python3
"""Read-only actor-population audit for the prepared MiroFish PDT run.

This script only reads the prepared simulation_config.json. It does not call
LLM APIs, does not write to Zep, and does not start or mutate any simulation.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
PREPARED_SIMULATION_ID = "sim_974459649906"
DEFAULT_CONFIG = (
    ROOT
    / "backend"
    / "uploads"
    / "simulations"
    / PREPARED_SIMULATION_ID
    / "simulation_config.json"
)
TARGET_AGENT_COUNT = 1000

LAYER_RULES: Dict[str, Dict[str, Any]] = {
    "retail_new_traders": {
        "label": "Retail and individual traders",
        "entity_types": ["RetailTrader", "Person"],
        "min_entity_count": 400,
        "min_quota": 400,
        "anchors": ["Experienced traders", "FOMO buyers", "small margin accounts", "Reddit/social momentum chasers"],
        "prompt_terms": ["Retail and individual traders", "PDT-rule-confused", "0DTE traders"],
        "initial_post_types": ["RetailTrader", "Person"],
    },
    "broker_platform_clearing": {
        "label": "Broker/platform/clearing actors and companies",
        "entity_types": ["BrokerPlatform", "Organization"],
        "min_entity_count": 80,
        "min_quota": 100,
        "anchors": ["Fidelity", "Webull", "Alpaca", "Schwab"],
        "prompt_terms": ["Broker/platform/clearing actors", "clearing and settlement desks", "broker API/platform reliability teams"],
        "initial_post_types": ["BrokerPlatform", "Organization"],
    },
    "developer_automation": {
        "label": "Developer, automation, and API communities",
        "entity_types": ["DeveloperCommunity"],
        "min_entity_count": 120,
        "min_quota": 120,
        "anchors": ["Open-source Trading Bot Maintainers", "autonomous-broker users", "prompt-engineered bot users", "AI-bot hobbyists"],
        "prompt_terms": ["Developer, automation, and tech actors", "broker API developers", "bot-framework maintainers"],
        "initial_post_types": ["DeveloperCommunity"],
    },
    "media_narrative": {
        "label": "Media outlets and narrative amplifiers",
        "entity_types": ["MediaOutlet", "Finfluencer"],
        "min_entity_count": 75,
        "min_quota": 75,
        "anchors": ["CNBC Markets Desk", "Bloomberg Market Structure Desk", "YouTube explainers"],
        "prompt_terms": ["Media and narrative actors", "financial media outlets", "finfluencers"],
        "initial_post_types": ["MediaOutlet", "Finfluencer"],
    },
    "policy_regulatory": {
        "label": "Government, regulator, and policy actors",
        "entity_types": ["RegulatorAgency"],
        "min_entity_count": 60,
        "min_quota": 60,
        "anchors": ["FINRA", "FOMC", "SEC Market Structure Staff", "Congressional Market Structure Staff"],
        "prompt_terms": ["Government, regulator, and policy actors", "SEC market-structure staff", "congressional/policy-maker commentary"],
        "initial_post_types": ["RegulatorAgency"],
    },
    "institutional_liquidity": {
        "label": "Institutional investors, market makers, and liquidity desks",
        "entity_types": ["InstitutionalInvestor"],
        "min_entity_count": 120,
        "min_quota": 120,
        "anchors": ["Citadel Securities Market Maker Desk", "Jane Street ETF Quant Desk", "BlackRock iShares ETF Desk", "Volatility Market Maker Desk"],
        "prompt_terms": ["Institutional investor and market-structure actors", "market makers", "liquidity providers"],
        "initial_post_types": ["InstitutionalInvestor"],
    },
    "tech_company_exec": {
        "label": "Tech executives, fintech founders, and company leadership",
        "entity_types": ["TechExecutive"],
        "min_entity_count": 35,
        "min_quota": 35,
        "anchors": ["Fintech Brokerage CEO Roundtable", "AI Trading Infrastructure Founder"],
        "prompt_terms": ["broker/platform executives", "fintech founders", "AI-company executives"],
        "initial_post_types": ["TechExecutive"],
    },
}

REQUIRED_REPORT_SECTIONS = [
    "government, regulator, and policy-maker reaction map",
    "institutional investor, market-maker, and liquidity-provider reaction map",
    "media outlet and influencer narrative map",
    "developer community, bot-framework, and broker API behavior map",
    "company and tech-executive narrative map",
]

REQUIRED_SCENARIO_BRANCHES = [
    "Institutional-liquidity branch",
    "Policy/media-clarification branch",
    "Developer-infrastructure branch",
]

REQUIRED_PROMPT_GUARDS = [
    "Do not limit the world to retail people",
    "Not every actor trades",
    "Do not model June 4 as a universal broker switch",
    "Do not assume \"PDT is gone\" means unlimited leverage",
    "advisory only",
]


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def contains_all(text: str, terms: List[str]) -> List[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() not in lowered]


def audit_config(config_path: Path, target_agents: int) -> Dict[str, Any]:
    cfg = read_json(config_path)
    agents = cfg.get("agent_configs") if isinstance(cfg.get("agent_configs"), list) else []
    expansion = cfg.get("expansion_metadata") if isinstance(cfg.get("expansion_metadata"), dict) else {}
    quotas = expansion.get("category_quotas") if isinstance(expansion.get("category_quotas"), dict) else {}
    anchors_added = [str(item) for item in expansion.get("anchors_added", []) if item is not None]
    requirement = str(cfg.get("simulation_requirement") or "")
    generation_reasoning = str(cfg.get("generation_reasoning") or "")
    event_config = cfg.get("event_config") if isinstance(cfg.get("event_config"), dict) else {}
    initial_posts = event_config.get("initial_posts") if isinstance(event_config.get("initial_posts"), list) else []

    entity_counts = collections.Counter(str(agent.get("entity_type") or "") for agent in agents)
    names = [str(agent.get("entity_name") or "") for agent in agents]
    names_text = "\n".join([*names, *anchors_added])
    post_type_counts = collections.Counter(str(post.get("poster_type") or "") for post in initial_posts if isinstance(post, dict))

    layer_results: Dict[str, Dict[str, Any]] = {}
    for layer, rule in LAYER_RULES.items():
        entity_count = sum(entity_counts.get(entity_type, 0) for entity_type in rule["entity_types"])
        quota = int(quotas.get(layer, 0) or 0)
        missing_anchors = contains_all(names_text, rule["anchors"])
        missing_prompt_terms = contains_all(requirement, rule["prompt_terms"])
        initial_post_count = sum(post_type_counts.get(post_type, 0) for post_type in rule["initial_post_types"])
        checks = {
            "quota_ok": quota >= rule["min_quota"],
            "entity_count_ok": entity_count >= rule["min_entity_count"],
            "anchors_ok": not missing_anchors,
            "prompt_terms_ok": not missing_prompt_terms,
            "initial_posts_ok": initial_post_count > 0,
        }
        layer_results[layer] = {
            "label": rule["label"],
            "ok": all(checks.values()),
            "checks": checks,
            "quota": quota,
            "min_quota": rule["min_quota"],
            "entity_types": rule["entity_types"],
            "entity_count": entity_count,
            "min_entity_count": rule["min_entity_count"],
            "initial_post_types": rule["initial_post_types"],
            "initial_post_count": initial_post_count,
            "missing_anchors": missing_anchors,
            "missing_prompt_terms": missing_prompt_terms,
        }

    report_section_missing = contains_all(requirement, REQUIRED_REPORT_SECTIONS)
    scenario_branch_missing = contains_all(requirement, REQUIRED_SCENARIO_BRANCHES)
    guard_missing = contains_all(requirement, REQUIRED_PROMPT_GUARDS)

    non_retail_quota = sum(int(quotas.get(layer, 0) or 0) for layer in LAYER_RULES if layer != "retail_new_traders")
    non_retail_entity_count = sum(
        result["entity_count"]
        for layer, result in layer_results.items()
        if layer != "retail_new_traders"
    )

    cross_layer_terms = [
        "policy language becomes broker UI text",
        "broker UI text becomes retail screenshots",
        "screenshots become influencer content",
        "novice order flow becomes market-maker/quant signal",
        "regulator/broker clarification",
    ]
    cross_layer_missing = contains_all(requirement, cross_layer_terms)

    audit_ok = (
        config_path.exists()
        and len(agents) == target_agents
        and expansion.get("target_agents") == target_agents
        and all(result["ok"] for result in layer_results.values())
        and not report_section_missing
        and not scenario_branch_missing
        and not guard_missing
        and not cross_layer_missing
        and non_retail_quota >= 500
        and non_retail_entity_count >= 500
    )

    return {
        "audit_ok": audit_ok,
        "config": str(config_path),
        "simulation_id": cfg.get("simulation_id"),
        "project_id": cfg.get("project_id"),
        "graph_id": cfg.get("graph_id"),
        "agent_count": len(agents),
        "target_agent_count": target_agents,
        "expansion_target": expansion.get("target_agents"),
        "expansion_method": expansion.get("method"),
        "non_retail_quota": non_retail_quota,
        "non_retail_entity_count": non_retail_entity_count,
        "category_quotas": quotas,
        "entity_type_counts": dict(sorted(entity_counts.items())),
        "initial_post_type_counts": dict(sorted(post_type_counts.items())),
        "anchors_added": anchors_added,
        "layers": layer_results,
        "prompt_requirements": {
            "required_report_sections_missing": report_section_missing,
            "required_scenario_branches_missing": scenario_branch_missing,
            "guardrails_missing": guard_missing,
            "cross_layer_terms_missing": cross_layer_missing,
        },
        "generation_reasoning_mentions_population_expansion": "Population expansion" in generation_reasoning,
        "stage03_gate": "closed; this audit is read-only and never starts the real simulation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the prepared MiroFish actor population.")
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Prepared simulation_config.json.")
    parser.add_argument("--target-agents", type=int, default=TARGET_AGENT_COUNT)
    args = parser.parse_args()

    result = audit_config(args.config, args.target_agents)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"MiroFish actor-population audit: {'PASS' if result['audit_ok'] else 'CHECK'}")
        print(f"Simulation: {result.get('simulation_id')}")
        print(f"Agents: {result['agent_count']} / {result['target_agent_count']}")
        print(f"Non-retail quota: {result['non_retail_quota']}")
        print(f"Non-retail entity count: {result['non_retail_entity_count']}")
        print("Layers:")
        for layer, item in result["layers"].items():
            print(
                f"- {layer}: {'ok' if item['ok'] else 'check'} "
                f"count={item['entity_count']} quota={item['quota']} initial_posts={item['initial_post_count']}"
            )
        missing = result["prompt_requirements"]
        print("Prompt requirements:")
        for key, values in missing.items():
            print(f"- {key}: {'ok' if not values else 'missing ' + ', '.join(values)}")
        print(f"Stage 03 gate: {result['stage03_gate']}")

    return 0 if result["audit_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
