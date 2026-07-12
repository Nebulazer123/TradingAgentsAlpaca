#!/usr/bin/env python3
"""Estimate active-agent coverage for a prepared MiroFish simulation config.

This helper is read-only. It does not call LLM APIs and does not start a
simulation. It mirrors the runner's active-agent selection inputs closely enough
to compare before/after config changes.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "backend" / "uploads" / "simulations" / "sim_974459649906" / "simulation_config.json"


def _hours(value: Any) -> List[int]:
    if isinstance(value, list):
        return [int(v) for v in value]
    return []


def _round_hours(time_config: Dict[str, Any], max_rounds: int | None) -> List[int]:
    total_hours = int(time_config.get("total_simulation_hours", 72))
    minutes_per_round = max(int(time_config.get("minutes_per_round", 60)), 1)
    total_rounds = int(total_hours * 60 / minutes_per_round)
    if max_rounds and max_rounds > 0:
        total_rounds = min(total_rounds, max_rounds)
    return [int((round_num * minutes_per_round) // 60) % 24 for round_num in range(total_rounds)]


def _target_range_for_hour(time_config: Dict[str, Any], hour: int) -> Dict[str, float]:
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
    return {
        "low": float(int(base_min * multiplier)),
        "mid": ((base_min + base_max) / 2.0) * multiplier,
        "high": float(int(base_max * multiplier)),
    }


def _active_agents(agent_configs: Iterable[Dict[str, Any]], hour: int) -> List[Dict[str, Any]]:
    active: List[Dict[str, Any]] = []
    for cfg in agent_configs:
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        if hour in active_hours:
            active.append(cfg)
    return active


def estimate_coverage(config: Dict[str, Any], max_rounds: int | None) -> Dict[str, Any]:
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs") if isinstance(config.get("agent_configs"), list) else []
    hours = _round_hours(time_config, max_rounds)

    survival_by_mode: Dict[str, Dict[int, float]] = {
        mode: {int(cfg.get("agent_id", idx)): 1.0 for idx, cfg in enumerate(agent_configs)}
        for mode in ("low", "mid", "high")
    }
    actions_by_mode = {mode: 0.0 for mode in ("low", "mid", "high")}
    by_round: List[Dict[str, Any]] = []
    layer_round_actions: Dict[str, Counter[str]] = {mode: Counter() for mode in ("low", "mid", "high")}

    for round_index, hour in enumerate(hours, start=1):
        active = _active_agents(agent_configs, hour)
        expected_candidate_weight = sum(float(cfg.get("activity_level", 0.5)) for cfg in active)
        possible_candidates = len(active)
        targets = _target_range_for_hour(time_config, hour)
        round_record: Dict[str, Any] = {
            "round": round_index,
            "hour": hour,
            "possible_candidates": possible_candidates,
            "expected_candidate_weight": round(expected_candidate_weight, 2),
        }

        for mode in ("low", "mid", "high"):
            target = targets[mode]
            denominator = float(possible_candidates) if mode == "high" else expected_candidate_weight
            selection_scale = min(target / denominator, 1.0) if denominator > 0 else 0.0
            expected_actions = min(target, denominator)
            actions_by_mode[mode] += expected_actions
            round_record[f"{mode}_expected_actions"] = round(expected_actions, 2)

            for cfg in active:
                agent_id = int(cfg.get("agent_id", 0))
                activity_level = float(cfg.get("activity_level", 0.5))
                if mode == "high":
                    per_platform_probability = min(target / possible_candidates, 1.0) if possible_candidates else 0.0
                else:
                    per_platform_probability = min(activity_level * selection_scale, 1.0)
                survival_by_mode[mode][agent_id] *= 1.0 - per_platform_probability
                layer_round_actions[mode][str(cfg.get("entity_type", "Unknown"))] += per_platform_probability

        by_round.append(round_record)

    layer_counts = Counter(str(cfg.get("entity_type", "Unknown")) for cfg in agent_configs)
    result = {
        "config": str(DEFAULT_CONFIG),
        "rounds": len(hours),
        "agents": len(agent_configs),
        "time_config": {
            "agents_per_hour_min": time_config.get("agents_per_hour_min"),
            "agents_per_hour_max": time_config.get("agents_per_hour_max"),
            "peak_activity_multiplier": time_config.get("peak_activity_multiplier"),
            "off_peak_activity_multiplier": time_config.get("off_peak_activity_multiplier"),
        },
        "per_platform_actions": {mode: round(value) for mode, value in actions_by_mode.items()},
        "dual_platform_actions": {mode: round(value * 2) for mode, value in actions_by_mode.items()},
        "expected_unique_active_agents": {},
        "entity_type_counts": dict(sorted(layer_counts.items())),
        "expected_actions_by_layer": {},
        "round_estimates": by_round,
        "notes": [
            "Unique counts are probability estimates from the runner's active_hours, activity_level, and per-hour target logic.",
            "Dual-platform unique assumes Twitter and Reddit selection are independent draws from the same population.",
            "This is a read-only estimator; the real run remains gated by explicit user approval.",
        ],
    }

    for mode, survival in survival_by_mode.items():
        per_platform_unique = sum(1.0 - value for value in survival.values())
        dual_platform_unique = sum(1.0 - (value * value) for value in survival.values())
        result["expected_unique_active_agents"][mode] = {
            "per_platform": round(per_platform_unique),
            "dual_platform": round(dual_platform_unique),
        }
        result["expected_actions_by_layer"][mode] = {
            layer: round(value, 1) for layer, value in sorted(layer_round_actions[mode].items())
        }

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate MiroFish active and unique-agent coverage without starting a run.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Prepared simulation_config.json.")
    parser.add_argument("--max-rounds", type=int, default=30, help="Stage 03 max_rounds cap. Use 0 for no cap.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = estimate_coverage(config, args.max_rounds if args.max_rounds > 0 else None)
    result["config"] = str(args.config)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    unique_mid = result["expected_unique_active_agents"]["mid"]
    print("MiroFish active coverage estimate")
    print(f"Config: {args.config}")
    print(f"Rounds: {result['rounds']} agents: {result['agents']}")
    print(f"Per-platform actions: {result['per_platform_actions']}")
    print(f"Dual-platform actions: {result['dual_platform_actions']}")
    print(f"Expected unique active agents, mid: per-platform={unique_mid['per_platform']} dual-platform={unique_mid['dual_platform']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
