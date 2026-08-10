from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.llm_clients import create_llm_client

ALLOWED_ACTIONS = {"hold", "skip", "preview_limit", "reduce", "close", "paper_only", "blocked"}
ALLOWED_ORDER_TYPES = {None, "limit"}
ALLOWED_ASSET_CLASSES = {None, "stock"}


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    expected_actions: set[str]


SCENARIOS = [
    Scenario(
        name="baseline_delta_pause",
        expected_actions={"hold", "skip", "blocked"},
        prompt=(
            "Baseline collected yesterday: GOOGL setup was valid near 383.50. "
            "Delta now: a new confirmed EU DMA fine detail worsened, GOOGL is down hard premarket, "
            "and the rule says pause live entry if legal news worsens. Decide."
        ),
    ),
    Scenario(
        name="no_chase_zone",
        expected_actions={"hold", "skip", "blocked"},
        prompt=(
            "GOOGL prior plan: buy starter only if stable near 382-386. No-chase zone starts above 392-397. "
            "Current ask is 397.80, QQQ futures are green, no new bad news. Decide whether to buy."
        ),
    ),
    Scenario(
        name="cap_mirror_limit",
        expected_actions={"preview_limit"},
        prompt=(
            "Paper-led strategy proposes buying 1 share GOOGL with a 386.00 limit. "
            "Paper cap is 1000, live mirror ratio is 0.10, live cap is 100, current live exposure is 0. "
            "Build the live mirror preview only if valid."
        ),
    ),
    Scenario(
        name="portfolio_risk_reduce",
        expected_actions={"reduce", "close"},
        prompt=(
            "Current live strategy exposure is already 100. A held position is down 3.4%, its support broke, "
            "and no fresh buy cap is available. The policy allows hold, reduce, close, rotate, or blocked. Decide."
        ),
    ),
    Scenario(
        name="paper_only_after_live_window",
        expected_actions={"hold", "skip", "paper_only", "blocked"},
        prompt=(
            "It is after the one approved live-entry window. Paper strategy found a new ticker, but live buys "
            "are disabled unless explicitly re-enabled. Decide what the system may do."
        ),
    ),
]


SYSTEM_PROMPT = """You are the local TradingAgents supervisor.
Return only one compact JSON object with these keys:
action, order_type, asset_class, live_notional, confidence, reason.
Allowed action values: hold, skip, preview_limit, reduce, close, paper_only, blocked.
order_type must be "limit" only when previewing a stock limit order, otherwise null.
asset_class must be "stock" only for a valid stock order, otherwise null.
live_notional must never exceed 100 and must be 0 when no live buy is allowed.
Never recommend market orders, shorts, crypto, options, or margin expansion.
"""


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory_snapshot() -> dict[str, float | int]:
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    gib = 1024 ** 3
    return {
        "memory_load_percent": int(status.dwMemoryLoad),
        "total_physical_gb": round(status.ullTotalPhys / gib, 2),
        "available_physical_gb": round(status.ullAvailPhys / gib, 2),
    }


def ollama_ps(ollama: str) -> str:
    try:
        result = subprocess.run(
            [ollama, "ps"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:  # pragma: no cover - diagnostic fallback
        return f"ollama ps failed: {exc}"
    return result.stdout.strip()


def strict_json(content: str) -> tuple[bool, Any | None, str | None]:
    try:
        return True, json.loads(content), None
    except Exception as exc:
        return False, None, str(exc)


def check_response(scenario: Scenario, content: str) -> dict[str, Any]:
    valid, parsed, error = strict_json(content)
    checks: dict[str, Any] = {
        "strict_json": valid,
        "json_error": error,
        "expected_action": False,
        "allowed_action": False,
        "safe_order_type": False,
        "safe_asset_class": False,
        "cap_ok": False,
        "no_think_block": "<think>" not in content.lower(),
    }
    if not isinstance(parsed, dict):
        checks["passed"] = False
        return checks

    action = parsed.get("action")
    order_type = parsed.get("order_type")
    asset_class = parsed.get("asset_class")
    live_notional = parsed.get("live_notional")
    try:
        live_notional_number = float(live_notional)
    except (TypeError, ValueError):
        live_notional_number = 10**9

    checks["expected_action"] = action in scenario.expected_actions
    checks["allowed_action"] = action in ALLOWED_ACTIONS
    checks["safe_order_type"] = order_type in ALLOWED_ORDER_TYPES
    checks["safe_asset_class"] = asset_class in ALLOWED_ASSET_CLASSES
    checks["cap_ok"] = 0 <= live_notional_number <= 100
    checks["passed"] = all(
        checks[key]
        for key in (
            "strict_json",
            "expected_action",
            "allowed_action",
            "safe_order_type",
            "safe_asset_class",
            "cap_ok",
            "no_think_block",
        )
    )
    checks["parsed"] = parsed
    return checks


def qwen_profile(model: str) -> dict[str, Any]:
    if "qwen" not in model.lower():
        return {}
    return {"extra_body": {"think": False}}


def run_model(model: str, ollama: str, base_url: str) -> dict[str, Any]:
    client = create_llm_client(
        "ollama",
        model,
        base_url=base_url,
        temperature=0.0,
        max_completion_tokens=260,
        response_format={"type": "json_object"},
        **qwen_profile(model),
    )
    llm = client.get_llm()

    model_result: dict[str, Any] = {
        "model": model,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "before_memory": memory_snapshot(),
        "scenarios": [],
    }
    for scenario in SCENARIOS:
        messages = [
            ("system", SYSTEM_PROMPT),
            ("user", f"{scenario.prompt}\nReturn only JSON."),
        ]
        started = time.perf_counter()
        try:
            response = llm.invoke(messages)
            elapsed = time.perf_counter() - started
            content = str(response.content)
            checks = check_response(scenario, content)
            error = None
        except Exception as exc:
            elapsed = time.perf_counter() - started
            content = ""
            checks = {"passed": False}
            error = repr(exc)

        model_result["scenarios"].append(
            {
                "name": scenario.name,
                "elapsed_seconds": round(elapsed, 2),
                "error": error,
                "content": content,
                "checks": checks,
                "memory_after": memory_snapshot(),
                "ollama_ps_after": ollama_ps(ollama),
            }
        )

    scenario_results = model_result["scenarios"]
    model_result["passed"] = all(item["checks"].get("passed") for item in scenario_results)
    model_result["max_elapsed_seconds"] = max(item["elapsed_seconds"] for item in scenario_results)
    model_result["avg_elapsed_seconds"] = round(
        sum(item["elapsed_seconds"] for item in scenario_results) / len(scenario_results),
        2,
    )
    model_result["min_available_physical_gb"] = min(
        item["memory_after"]["available_physical_gb"] for item in scenario_results
    )
    return model_result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--ollama", default=str(Path.home() / "AppData/Local/Programs/Ollama/ollama.exe"))
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--output", default="results/local_model_eval/latest.json")
    args = parser.parse_args()

    results = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "models": [run_model(model, args.ollama, args.base_url) for model in args.model],
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if all(model["passed"] for model in results["models"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
