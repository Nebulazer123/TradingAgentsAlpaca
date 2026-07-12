#!/usr/bin/env python3
"""Read-only preflight checks for the MiroFish PDT simulation prep.

This script does not call LLM APIs, does not write to Zep, and does not start a
simulation. It checks local files, redacted env shape, and local health endpoints.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
DOC_DIR = ROOT / "docs" / "mirror_fish"

EXPECTED_FILES = {
    "seed": DOC_DIR / "MIRROR_FISH_PDT_REALITY_SEED.md",
    "simulation_prompt": DOC_DIR / "MIRROR_FISH_PDT_SIMULATION_PROMPT.md",
    "pre_start_manifest": DOC_DIR / "MIROFISH_PRE_START_PACKET_MANIFEST.md",
    "readiness": DOC_DIR / "MIRROR_FISH_TRADING_RUN_READINESS.md",
    "runbook": DOC_DIR / "MIRROR_FISH_OPERATOR_RUNBOOK.md",
    "approval_packet": DOC_DIR / "MIRROR_FISH_PRE_START_APPROVAL_PACKET.md",
    "cost_estimator": DOC_DIR / "mirofish_cost_estimator.py",
    "env_gate": DOC_DIR / "mirofish_env_gate.py",
    "workflow_audit": DOC_DIR / "mirofish_workflow_audit.py",
    "readiness_bundle": DOC_DIR / "mirofish_readiness_bundle.py",
    "completion_audit": DOC_DIR / "mirofish_completion_audit.py",
    "app_path_setup": DOC_DIR / "mirofish_app_path_setup.py",
    "agent_expander": DOC_DIR / "mirofish_agent_expander.py",
    "model_config_helper": ROOT / "backend" / "app" / "utils" / "model_config.py",
}

PREPARED_PROJECT_ID = "proj_8ece728e49fe"
PREPARED_GRAPH_ID = "mirofish_4a9df9ae8b184878"
PREPARED_SIMULATION_ID = "sim_974459649906"
STRESS_SIMULATION_ID = "sim_974459649906_stress2"
TARGET_AGENT_COUNT = 1000

RECOMMENDED = {
    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
    "LLM_MODEL_NAME": "qwen/qwen3.6-plus",
    "LLM_BOOST_BASE_URL": "https://openrouter.ai/api/v1",
    "LLM_BOOST_MODEL_NAME": "deepseek/deepseek-v4-pro",
}

SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]+"),
    re.compile(r"z_1d[A-Za-z0-9._-]+"),
    re.compile(r"AQ\.Ab[A-Za-z0-9._-]+"),
    re.compile(r"AIza[A-Za-z0-9._-]+"),
]

OPTIONAL_MODEL_CONTROLS = [
    "LLM_MODEL_PLATFORM",
    "LLM_MAX_TOKENS",
    "LLM_MAX_COMPLETION_TOKENS",
    "LLM_TEMPERATURE",
    "LLM_MODEL_CONFIG_JSON",
    "LLM_EXTRA_BODY_JSON",
    "LLM_REASONING_JSON",
    "LLM_BOOST_MODEL_PLATFORM",
    "LLM_BOOST_MAX_TOKENS",
    "LLM_BOOST_MAX_COMPLETION_TOKENS",
    "LLM_BOOST_TEMPERATURE",
    "LLM_BOOST_MODEL_CONFIG_JSON",
    "LLM_BOOST_EXTRA_BODY_JSON",
    "LLM_BOOST_REASONING_JSON",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_env_file(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def health(url: str, timeout: float) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {"ok": True, "status": response.status, "body": body[:500]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def backend_listener_info() -> Dict[str, Any]:
    if os.name != "nt":
        return {"available": False, "reason": "non-windows"}

    script = r"""
$listener = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $listener) {
  [pscustomobject]@{available=$false; reason="no-listener"} | ConvertTo-Json -Compress
  exit 0
}
$proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
if ($null -eq $proc) {
  [pscustomobject]@{available=$true; pid=$listener.OwningProcess; process_found=$false} | ConvertTo-Json -Compress
  exit 0
}
[pscustomobject]@{
  available=$true
  pid=$listener.OwningProcess
  process_found=$true
  creation_time_utc=$proc.CreationDate.ToUniversalTime().ToString("o")
  command_line=$proc.CommandLine
} | ConvertTo-Json -Compress
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return {"available": False, "reason": proc.stderr.strip()[:500]}
        data = json.loads(proc.stdout)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    return {"available": False, "reason": "unparseable"}


def backend_refreshed_after_env(env_path: Path, listener: Dict[str, Any]) -> bool:
    creation_raw = listener.get("creation_time_utc")
    if not creation_raw:
        return False
    try:
        process_time = dt.datetime.fromisoformat(str(creation_raw).replace("Z", "+00:00"))
        env_time = dt.datetime.fromtimestamp(env_path.stat().st_mtime, tz=dt.timezone.utc)
        return process_time >= env_time
    except Exception:
        return False


def scan_for_secrets(paths: List[Path]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                hits.append({"path": str(path), "pattern": pattern.pattern, "offset": match.start()})
    return hits


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def prepared_run_audit() -> Dict[str, Any]:
    """Read-only audit of the current prepared real-run simulation directory."""
    sim_dir = ROOT / "backend" / "uploads" / "simulations" / PREPARED_SIMULATION_ID
    stress_dir = ROOT / "backend" / "uploads" / "simulations" / STRESS_SIMULATION_ID
    cfg = read_json(sim_dir / "simulation_config.json")
    state = read_json(sim_dir / "state.json")
    stress_state = read_json(stress_dir / "run_state.json")

    agent_configs = cfg.get("agent_configs") if isinstance(cfg.get("agent_configs"), list) else []
    expansion = cfg.get("expansion_metadata") if isinstance(cfg.get("expansion_metadata"), dict) else {}
    quotas = expansion.get("category_quotas") if isinstance(expansion.get("category_quotas"), dict) else {}
    anchors = expansion.get("anchors_added") if isinstance(expansion.get("anchors_added"), list) else []

    required_anchors = {
        "SEC Market Structure Staff",
        "Citadel Securities Market Maker Desk",
        "Bloomberg Market Structure Desk",
        "Open-source Trading Bot Maintainers",
        "Fintech Brokerage CEO Roundtable",
    }
    required_quota_keys = {
        "retail_new_traders",
        "broker_platform_clearing",
        "developer_automation",
        "media_narrative",
        "policy_regulatory",
        "institutional_liquidity",
        "tech_company_exec",
    }

    prepared_ok = (
        sim_dir.exists()
        and cfg.get("project_id") == PREPARED_PROJECT_ID
        and cfg.get("graph_id") == PREPARED_GRAPH_ID
        and len(agent_configs) == TARGET_AGENT_COUNT
        and state.get("status") == "ready"
        and state.get("agent_population_expanded") is True
        and state.get("profiles_count") == TARGET_AGENT_COUNT
        and expansion.get("target_agents") == TARGET_AGENT_COUNT
        and required_anchors.issubset(set(str(item) for item in anchors))
        and required_quota_keys.issubset(set(str(key) for key in quotas.keys()))
    )

    stress_ok = (
        stress_dir.exists()
        and stress_state.get("runner_status") == "completed"
        and stress_state.get("total_rounds") == 2
        and stress_state.get("progress_percent") == 100.0
        and stress_state.get("total_actions_count") == 24
        and stress_state.get("twitter_completed") is True
        and stress_state.get("reddit_completed") is True
        and stress_state.get("error") is None
    )

    return {
        "project_id": PREPARED_PROJECT_ID,
        "graph_id": PREPARED_GRAPH_ID,
        "simulation_id": PREPARED_SIMULATION_ID,
        "simulation_dir": str(sim_dir),
        "prepared_stage01_stage02_ok": prepared_ok,
        "simulation_status": state.get("status"),
        "agent_count": len(agent_configs),
        "profiles_count": state.get("profiles_count"),
        "expanded": state.get("agent_population_expanded"),
        "expansion_target": expansion.get("target_agents"),
        "category_quotas": quotas,
        "anchors_added": anchors,
        "stress_simulation_id": STRESS_SIMULATION_ID,
        "stress_simulation_dir": str(stress_dir),
        "stress_stage03_capped_ok": stress_ok,
        "stress_runner_status": stress_state.get("runner_status"),
        "stress_total_rounds": stress_state.get("total_rounds"),
        "stress_total_actions": stress_state.get("total_actions_count"),
        "stress_completed_at": stress_state.get("completed_at"),
    }


def validate_optional_model_controls(env: Dict[str, str]) -> Dict[str, Any]:
    controls: Dict[str, Any] = {}
    for key in OPTIONAL_MODEL_CONTROLS:
        value = env.get(key) or os.environ.get(key)
        if not value:
            controls[key] = {"present": False, "valid": True}
            continue

        status: Dict[str, Any] = {"present": True, "valid": True}
        try:
            if key.endswith("_JSON"):
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise ValueError("must be a JSON object")
                status["keys"] = sorted(parsed.keys())
            elif key.endswith("_MAX_TOKENS") or key.endswith("_MAX_COMPLETION_TOKENS"):
                parsed_int = int(value)
                if parsed_int <= 0:
                    raise ValueError("must be positive")
                status["kind"] = "positive_int"
            elif key.endswith("_TEMPERATURE"):
                parsed_float = float(value)
                if parsed_float < 0 or parsed_float > 2:
                    raise ValueError("must be between 0 and 2")
                status["kind"] = "float_0_to_2"
            elif key.endswith("_MODEL_PLATFORM"):
                platform = value.strip().upper()
                if platform not in {"OPENAI", "OPENROUTER"}:
                    raise ValueError("must be OPENAI or OPENROUTER")
                status["platform"] = platform
        except Exception as exc:
            status["valid"] = False
            status["error"] = str(exc)
        controls[key] = status
    return controls


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MiroFish PDT preflight.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text summary.")
    parser.add_argument("--health-timeout", type=float, default=5.0)
    parser.add_argument("--skip-health", action="store_true")
    args = parser.parse_args()

    env_path = ROOT / ".env"
    env = read_env_file(env_path)
    files = {}
    for name, path in EXPECTED_FILES.items():
        files[name] = {
            "path": str(path),
            "exists": path.exists(),
            "sha256": sha256(path) if path.exists() else None,
            "bytes": path.stat().st_size if path.exists() else None,
        }

    env_status = {}
    for key, expected in RECOMMENDED.items():
        actual = env.get(key)
        env_status[key] = {
            "actual": actual,
            "recommended": expected,
            "matches_recommended": actual == expected,
        }
    env_all_recommended = all(item["matches_recommended"] for item in env_status.values())

    key_status = {}
    for key in ["LLM_API_KEY", "LLM_BOOST_API_KEY", "ZEP_API_KEY", "OPENROUTER_MANAGEMENT_API_KEY"]:
        value = env.get(key) or os.environ.get(key) or os.environ.get("OPENROUTER_API_KEY" if key == "LLM_API_KEY" else "")
        key_status[key] = {"present": bool(value), "length": len(value) if value else 0}

    model_controls = validate_optional_model_controls(env)

    health_status = {}
    if not args.skip_health:
        health_status = {
            "backend": health("http://localhost:5001/health", args.health_timeout),
            "frontend": health("http://localhost:3000", args.health_timeout),
        }
    listener_status = backend_listener_info()
    backend_env_refreshed = backend_refreshed_after_env(env_path, listener_status)

    secret_hits = scan_for_secrets(list(EXPECTED_FILES.values()))
    prepared = prepared_run_audit()

    passed = (
        all(item["exists"] for item in files.values())
        and all(item["present"] for item in key_status.values())
        and all(item["valid"] for item in model_controls.values())
        and prepared["prepared_stage01_stage02_ok"]
        and prepared["stress_stage03_capped_ok"]
        and not secret_hits
        and (args.skip_health or (health_status["backend"]["ok"] and health_status["frontend"]["ok"]))
    )
    ready_for_stage03 = False

    remaining_gates = []
    if not env_all_recommended:
        remaining_gates.extend([
            "approve .env model switch to quality-first Qwen/DeepSeek",
            "apply guarded .env model switch with backup",
        ])
    elif not backend_env_refreshed:
        remaining_gates.append("refresh/restart backend so the running server loads the approved .env model route")
    if not prepared["prepared_stage01_stage02_ok"]:
        remaining_gates.extend([
            "repair or rerun app-path ontology/graph build and stage 02 prepare",
            "confirm prepared simulation has 1,000 expanded agents",
        ])
    if not prepared["stress_stage03_capped_ok"]:
        remaining_gates.append("rerun capped stage 03 stress test on a copy before real launch")
    remaining_gates.extend([
        "review actual config cost estimate and actor-population audit",
        "obtain explicit user approval before the real stage 03 simulation",
        "after real stage 03, generate stage 04 report and run stage 05 deep interactions/interviews",
    ])

    result = {
        "passed_readiness_preflight": passed,
        "ready_for_stage03": ready_for_stage03,
        "stage03_gate": "closed until the user explicitly approves the real stage 03 simulation",
        "root": str(ROOT),
        "files": files,
        "env_status": env_status,
        "env_all_recommended": env_all_recommended,
        "key_status_redacted": key_status,
        "optional_model_controls": model_controls,
        "health": health_status,
        "backend_listener": listener_status,
        "backend_env_refreshed_after_env_write": backend_env_refreshed,
        "prepared_run": prepared,
        "secret_hits": secret_hits,
        "remaining_gates": remaining_gates,
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"MiroFish preflight: {'PASS' if passed else 'CHECK'}")
        print(f"Stage 03 gate: {result['stage03_gate']}")
        print("\nFiles:")
        for name, item in files.items():
            print(f"- {name}: {'ok' if item['exists'] else 'missing'} {item['path']}")
        print("\nEnv model shape:")
        for key, item in env_status.items():
            marker = "matches" if item["matches_recommended"] else "pending"
            print(f"- {key}: {item['actual']} ({marker}; recommended {item['recommended']})")
        print("\nKeys:")
        for key, item in key_status.items():
            print(f"- {key}: {'present' if item['present'] else 'missing'} length={item['length']}")
        print("\nOptional model controls:")
        for key, item in model_controls.items():
            if not item["present"]:
                continue
            detail = item.get("platform") or item.get("kind") or f"keys={item.get('keys', [])}"
            print(f"- {key}: {'valid' if item['valid'] else 'invalid'} {detail}")
        if health_status:
            print("\nHealth:")
            for name, item in health_status.items():
                status = item.get("status") if item.get("ok") else item.get("error")
                print(f"- {name}: {'ok' if item.get('ok') else 'fail'} {status}")
        print("\nSecret scan:")
        print("- no raw key patterns found" if not secret_hits else f"- hits: {len(secret_hits)}")
        print("\nPrepared run:")
        print(f"- project_id: {prepared['project_id']}")
        print(f"- graph_id: {prepared['graph_id']}")
        print(f"- simulation_id: {prepared['simulation_id']}")
        print(f"- stage01/stage02 prepared: {prepared['prepared_stage01_stage02_ok']}")
        print(f"- expanded agents: {prepared['agent_count']}")
        print(f"- capped stage03 stress ok: {prepared['stress_stage03_capped_ok']} actions={prepared['stress_total_actions']}")
        print("\nRemaining gates:")
        for gate in result["remaining_gates"]:
            print(f"- {gate}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
