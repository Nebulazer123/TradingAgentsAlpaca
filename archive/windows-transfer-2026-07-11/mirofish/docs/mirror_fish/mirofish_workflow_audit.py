#!/usr/bin/env python3
"""Read-only source audit for MiroFish's five-stage workflow coverage.

This script inspects local source files for the endpoints and services that
back the creator workflow. It does not call APIs, write data, start simulation,
or contact LLM/Zep/OpenRouter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Check:
    label: str
    path: str
    pattern: str
    note: str = ""


STAGES: Dict[str, Dict[str, object]] = {
    "01_map_construction": {
        "creator_step": "Reality seed extraction, individual/group memory injection, GraphRAG construction",
        "checks": [
            Check("Upload and ontology endpoint", "backend/app/api/graph.py", r"@graph_bp\.route\('/ontology/generate'"),
            Check("File parsing and text extraction", "backend/app/api/graph.py", r"FileParser\.extract_text|save_extracted_text"),
            Check("LLM ontology generation", "backend/app/api/graph.py", r"OntologyGenerator\(\).*?generator\.generate", "dotall"),
            Check("Graph build endpoint", "backend/app/api/graph.py", r"@graph_bp\.route\('/build'"),
            Check("Zep graph creation", "backend/app/api/graph.py", r"builder\.create_graph"),
            Check("Ontology applied to graph", "backend/app/api/graph.py", r"builder\.set_ontology"),
            Check("Text batches added to graph", "backend/app/api/graph.py", r"builder\.add_text_batches"),
            Check("Graph data retrieval", "backend/app/api/graph.py", r"@graph_bp\.route\('/data/<graph_id>'"),
            Check("Zep graph builder service", "backend/app/services/graph_builder.py", r"class GraphBuilderService"),
        ],
    },
    "02_environment_setup": {
        "creator_step": "Entity relationship extraction, persona generation, environment configuration, agent injection, simulation parameters",
        "checks": [
            Check("Simulation create endpoint", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/create'"),
            Check("Simulation prepare endpoint", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/prepare'"),
            Check("Prepare status endpoint", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/prepare/status'"),
            Check("Zep entity reader", "backend/app/api/simulation.py", r"ZepEntityReader"),
            Check("Profile generator", "backend/app/services/oasis_profile_generator.py", r"class OasisProfileGenerator"),
            Check("Simulation config generator", "backend/app/services/simulation_config_generator.py", r"class SimulationConfigGenerator"),
            Check("Automatic requirement analysis", "backend/app/services/simulation_manager.py", r"analyzingRequirements|prepare_simulation"),
            Check("Generated time/event/agent configs", "backend/app/services/simulation_config_generator.py", r"time_config.*event_config.*agent_configs", "dotall"),
            Check("Profile/config artifacts", "backend/app/services/simulation_manager.py", r"reddit_profiles\.json|twitter_profiles\.csv|simulation_config\.json"),
        ],
    },
    "03_start_simulation": {
        "creator_step": "Dual-platform parallel simulation, automatic demand analysis, dynamic time-series memory updates",
        "checks": [
            Check("Start endpoint", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/start'"),
            Check("Graph memory flag accepted", "backend/app/api/simulation.py", r"enable_graph_memory_update"),
            Check("SimulationRunner start", "backend/app/services/simulation_runner.py", r"def start_simulation"),
            Check("Dual-platform runner script", "backend/app/services/simulation_runner.py", r"run_parallel_simulation\.py"),
            Check("Parallel Twitter and Reddit script", "backend/scripts/run_parallel_simulation.py", r"generate_twitter_agent_graph.*generate_reddit_agent_graph", "dotall"),
            Check("Dynamic Zep memory updater", "backend/app/services/zep_graph_memory_updater.py", r"class ZepGraphMemoryUpdater"),
            Check("Runner wires graph updater", "backend/app/services/simulation_runner.py", r"GraphMemoryUpdaterManager|enable_graph_memory_update"),
            Check("Frontend enables graph memory", "frontend/src/components/Step3Simulation.vue", r"enable_graph_memory_update:\s*true"),
            Check("Automatic demand/requirement analysis evidence", "backend/app/services/simulation_config_generator.py", r"hot_topics|narrative_direction|simulation_requirement"),
            Check("Time-series/action endpoints", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/<simulation_id>/(actions|timeline)'"),
        ],
    },
    "04_report_generation": {
        "creator_step": "ReportAgent toolset and in-depth interaction with simulated environments",
        "checks": [
            Check("Report generate endpoint", "backend/app/api/report.py", r"@report_bp\.route\('/generate'"),
            Check("Report status endpoint", "backend/app/api/report.py", r"@report_bp\.route\('/generate/status'"),
            Check("ReportAgent service", "backend/app/services/report_agent.py", r"class ReportAgent"),
            Check("ReportAgent tool surface", "backend/app/services/report_agent.py", r"insight_forge|panorama_search|quick_search|interview_agents"),
            Check("Zep tools backing report", "backend/app/services/zep_tools.py", r"def insight_forge|def panorama_search|def quick_search|def interview_agents"),
            Check("Report download/retrieval", "backend/app/api/report.py", r"@report_bp\.route\('/<report_id>/download'"),
            Check("Frontend report step", "frontend/src/components/Step4Report.vue", r"interview_agents|insight_forge|panorama_search|quick_search"),
        ],
    },
    "05_deep_interaction": {
        "creator_step": "Conversation with ReportAgent and individual simulated characters",
        "checks": [
            Check("ReportAgent chat endpoint", "backend/app/api/report.py", r"@report_bp\.route\('/chat'"),
            Check("Single interview endpoint", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/interview'"),
            Check("Batch interview endpoint", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/interview/batch'"),
            Check("All-agent interview endpoint", "backend/app/api/simulation.py", r"@simulation_bp\.route\('/interview/all'"),
            Check("Runner single interview", "backend/app/services/simulation_runner.py", r"def interview_agent"),
            Check("Runner batch/all interviews", "backend/app/services/simulation_runner.py", r"def interview_agents_batch|def interview_all_agents"),
            Check("Frontend interaction step", "frontend/src/components/Step5Interaction.vue", r"sendToReportAgent|interviewAgents"),
            Check("Interaction view", "frontend/src/views/InteractionView.vue", r"Step 5/5|Step5Interaction"),
        ],
    },
}


def find_pattern(path: Path, pattern: str, dotall: bool = False) -> Optional[int]:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    flags = re.MULTILINE | (re.DOTALL if dotall else 0)
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return text[: match.start()].count("\n") + 1


def run_audit() -> Dict[str, object]:
    stages: Dict[str, object] = {}
    total = 0
    passed = 0

    for stage_id, stage in STAGES.items():
        checks_out: List[Dict[str, object]] = []
        stage_passed = 0
        checks = stage["checks"]
        assert isinstance(checks, list)
        for check in checks:
            assert isinstance(check, Check)
            total += 1
            dotall = check.note == "dotall"
            line = find_pattern(ROOT / check.path, check.pattern, dotall=dotall)
            ok = line is not None
            if ok:
                passed += 1
                stage_passed += 1
            checks_out.append({
                "label": check.label,
                "path": check.path,
                "line": line,
                "ok": ok,
                "pattern": check.pattern,
            })
        stages[stage_id] = {
            "creator_step": stage["creator_step"],
            "passed": stage_passed,
            "total": len(checks),
            "ok": stage_passed == len(checks),
            "checks": checks_out,
        }

    return {
        "ok": passed == total,
        "passed": passed,
        "total": total,
        "root": str(ROOT),
        "stage03_gate": "closed; this audit is read-only and does not start simulation",
        "note": "Automatic demand analysis is not a single named endpoint; source evidence is requirement analysis plus generated time/event/agent configs, hot topics, narrative direction, and ReportAgent follow-up tools.",
        "stages": stages,
    }


def print_text(result: Dict[str, object]) -> None:
    print(f"MiroFish workflow audit: {'PASS' if result['ok'] else 'CHECK'} ({result['passed']}/{result['total']})")
    print(f"Stage 03 gate: {result['stage03_gate']}")
    print(f"Note: {result['note']}")
    stages = result["stages"]
    assert isinstance(stages, dict)
    for stage_id, stage in stages.items():
        assert isinstance(stage, dict)
        print(f"\n{stage_id}: {'ok' if stage['ok'] else 'check'} ({stage['passed']}/{stage['total']})")
        print(f"- creator step: {stage['creator_step']}")
        checks = stage["checks"]
        assert isinstance(checks, list)
        for check in checks:
            assert isinstance(check, dict)
            status = "ok" if check["ok"] else "missing"
            loc = f"{check['path']}:{check['line']}" if check["line"] else check["path"]
            print(f"- {status}: {check['label']} ({loc})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MiroFish workflow coverage audit.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_audit()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_text(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
