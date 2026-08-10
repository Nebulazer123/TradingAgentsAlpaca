#!/usr/bin/env python3
"""Estimate OpenRouter cost for the MiroFish PDT simulation.

This is a readiness helper only. It does not call any API and does not start a
MiroFish simulation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


DEFAULT_PRICES = {
    "qwen/qwen-plus-2025-07-28:thinking": {"prompt": 0.00000026, "completion": 0.00000078},
    "qwen/qwen3.6-plus": {"prompt": 0.000000325, "completion": 0.00000195},
    "qwen/qwen3.5-plus-20260420": {"prompt": 0.0000003, "completion": 0.0000018},
    "deepseek/deepseek-v4-pro": {"prompt": 0.000000435, "completion": 0.00000087},
    "deepseek/deepseek-v4-flash": {"prompt": 0.0000000983, "completion": 0.0000001966},
    "google/gemini-3-flash-preview": {"prompt": 0.0000005, "completion": 0.000003},
}


def _hours(value: Any) -> List[int]:
    if isinstance(value, list):
        return [int(v) for v in value]
    return []


def _load_config(path: Path | None, agents: int) -> Dict[str, Any]:
    if path:
        return json.loads(path.read_text(encoding="utf-8"))

    return {
        "time_config": {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,
            "agents_per_hour_min": max(1, agents // 15),
            "agents_per_hour_max": max(5, agents // 5),
            "peak_hours": [9, 10, 11, 14, 15, 20, 21, 22],
            "peak_activity_multiplier": 1.5,
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "off_peak_activity_multiplier": 0.3,
        },
        "agent_configs": [
            {
                "agent_id": idx,
                "activity_level": 0.5,
                "active_hours": list(range(8, 23)),
            }
            for idx in range(agents)
        ],
    }


def _round_hours(time_config: Dict[str, Any], max_rounds: int | None) -> List[int]:
    total_hours = int(time_config.get("total_simulation_hours", 72))
    minutes_per_round = max(int(time_config.get("minutes_per_round", 60)), 1)
    total_rounds = int(total_hours * 60 / minutes_per_round)
    if max_rounds and max_rounds > 0:
        total_rounds = min(total_rounds, max_rounds)
    return [int((round_num * minutes_per_round) // 60) % 24 for round_num in range(total_rounds)]


def _target_range_for_hour(time_config: Dict[str, Any], hour: int) -> Tuple[int, float, int]:
    base_min = int(time_config.get("agents_per_hour_min", 5))
    base_max = int(time_config.get("agents_per_hour_max", 20))
    peak_hours = set(_hours(time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])))
    off_peak_hours = set(_hours(time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])))
    if hour in peak_hours:
        multiplier = float(time_config.get("peak_activity_multiplier", 1.5))
    elif hour in off_peak_hours:
        multiplier = float(time_config.get("off_peak_activity_multiplier", 0.3))
    else:
        multiplier = 1.0

    low = int(base_min * multiplier)
    mid = ((base_min + base_max) / 2.0) * multiplier
    high = int(base_max * multiplier)
    return low, mid, high


def _expected_candidates(agent_configs: Iterable[Dict[str, Any]], hour: int) -> float:
    total = 0.0
    for cfg in agent_configs:
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        if hour not in active_hours:
            continue
        total += float(cfg.get("activity_level", 0.5))
    return total


def _possible_candidates(agent_configs: Iterable[Dict[str, Any]], hour: int) -> int:
    total = 0
    for cfg in agent_configs:
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        if hour in active_hours:
            total += 1
    return total


def _estimate_actions(config: Dict[str, Any], max_rounds: int | None) -> Dict[str, Any]:
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])
    hours = _round_hours(time_config, max_rounds)

    low_total = 0
    mid_total = 0.0
    high_total = 0
    by_hour: Dict[int, Dict[str, float]] = {}

    for hour in hours:
        target_low, target_mid, target_high = _target_range_for_hour(time_config, hour)
        expected_candidates = _expected_candidates(agent_configs, hour)
        possible_candidates = _possible_candidates(agent_configs, hour)
        round_low = min(target_low, int(expected_candidates))
        round_mid = min(target_mid, expected_candidates)
        round_high = min(target_high, possible_candidates)

        low_total += max(round_low, 0)
        mid_total += max(round_mid, 0.0)
        high_total += max(round_high, 0)

        bucket = by_hour.setdefault(hour, {"rounds": 0, "mid_actions": 0.0})
        bucket["rounds"] += 1
        bucket["mid_actions"] += max(round_mid, 0.0)

    return {
        "rounds": len(hours),
        "agents": len(agent_configs),
        "per_platform_actions": {
            "low": low_total,
            "mid": round(mid_total),
            "high": high_total,
        },
        "dual_platform_actions": {
            "low": low_total * 2,
            "mid": round(mid_total * 2),
            "high": high_total * 2,
        },
        "hour_distribution": by_hour,
    }


def _price_for(model: str, kind: str) -> float:
    try:
        return float(DEFAULT_PRICES[model][kind])
    except KeyError as exc:
        raise SystemExit(f"Missing default price for {model!r} {kind!r}; pass a known model or update this script.") from exc


def _cost_for_actions(actions: int, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    return actions * (
        prompt_tokens * _price_for(model, "prompt")
        + completion_tokens * _price_for(model, "completion")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate MiroFish OpenRouter simulation cost without starting a run.")
    parser.add_argument("--config", type=Path, help="Path to simulation_config.json after stage 02 prepare.")
    parser.add_argument("--agents", type=int, default=1000, help="Synthetic agent count when --config is not supplied.")
    parser.add_argument("--max-rounds", type=int, default=30, help="Stage 03 max_rounds cap. Use 0 for no cap.")
    parser.add_argument("--primary-model", default="qwen/qwen3.6-plus")
    parser.add_argument("--boost-model", default="deepseek/deepseek-v4-pro")
    parser.add_argument("--prompt-tokens", type=int, default=1200, help="Estimated prompt tokens per active-agent action.")
    parser.add_argument("--completion-tokens", type=int, default=280, help="Estimated completion tokens per active-agent action.")
    parser.add_argument("--worst-prompt-tokens", type=int, default=2200)
    parser.add_argument("--worst-completion-tokens", type=int, default=650)
    args = parser.parse_args()

    config = _load_config(args.config, args.agents)
    max_rounds = args.max_rounds if args.max_rounds > 0 else None
    actions = _estimate_actions(config, max_rounds)

    primary_mid = _cost_for_actions(
        actions["per_platform_actions"]["mid"],
        args.primary_model,
        args.prompt_tokens,
        args.completion_tokens,
    )
    boost_mid = _cost_for_actions(
        actions["per_platform_actions"]["mid"],
        args.boost_model,
        args.prompt_tokens,
        args.completion_tokens,
    )
    primary_worst = _cost_for_actions(
        actions["per_platform_actions"]["high"],
        args.primary_model,
        args.worst_prompt_tokens,
        args.worst_completion_tokens,
    )
    boost_worst = _cost_for_actions(
        actions["per_platform_actions"]["high"],
        args.boost_model,
        args.worst_prompt_tokens,
        args.worst_completion_tokens,
    )

    result = {
        "mode": "config" if args.config else "synthetic",
        "config": str(args.config) if args.config else None,
        "models": {
            "primary": args.primary_model,
            "boost": args.boost_model,
        },
        "token_assumptions": {
            "mid_per_action": {
                "prompt_tokens": args.prompt_tokens,
                "completion_tokens": args.completion_tokens,
            },
            "worst_per_action": {
                "prompt_tokens": args.worst_prompt_tokens,
                "completion_tokens": args.worst_completion_tokens,
            },
        },
        "actions": actions,
        "estimated_stage03_cost_usd": {
            "mid": round(primary_mid + boost_mid, 4),
            "worst": round(primary_worst + boost_worst, 4),
            "primary_mid": round(primary_mid, 4),
            "boost_mid": round(boost_mid, 4),
            "primary_worst": round(primary_worst, 4),
            "boost_worst": round(boost_worst, 4),
        },
        "notes": [
            "Estimate covers stage 03 active-agent LLM actions only.",
            "Stage 01 graph build, stage 02 profile/config generation, stage 04 report generation, and stage 05 interviews add separate LLM/Zep cost.",
            "Use this again with --config after /api/simulation/prepare creates simulation_config.json.",
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
