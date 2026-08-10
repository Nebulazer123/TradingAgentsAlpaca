#!/usr/bin/env python3
"""Extract post-run MiroFish telemetry after Stage 03/04 artifacts exist.

The extractor is schema-tolerant: it inspects available JSONL logs, SQLite DBs,
run state, config, and ReportAgent markdown without assuming every artifact is
present. It is safe to run before Stage 03; missing artifacts are reported as
access issues instead of treated as failures.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIM_DIR = ROOT / "backend" / "uploads" / "simulations" / "sim_974459649906"
REPORTS_DIR = ROOT / "backend" / "uploads" / "reports"

TICKER_ALLOWLIST = {
    "SPY", "QQQ", "IWM", "DIA", "SPX", "XSP", "TQQQ", "SQQQ", "SOXL", "SOXS", "TSLL",
    "NVDA", "AVGO", "MRVL", "AAPL", "MSFT", "AMZN", "TSLA", "ORCL", "HOOD", "BULL",
    "IBKR", "SCHW", "FIS", "COIN", "MSTR", "SOXX", "SMH",
}

EVENT_PATTERNS = {
    "broker_confusion_events": re.compile(r"\b(broker|robinhood|alpaca|schwab|fidelity|webull|ibkr|support|ui|rollout)\b", re.I),
    "buying_power_margin_confusion_events": re.compile(r"\b(buying power|margin|intraday deficit|settled funds|cash account|rejected|blocked|restriction)\b", re.I),
    "AI_bot_copycat_events": re.compile(r"\b(ai agent|agentic|bot|copycat|prompt|mcp|claude|automation|api)\b", re.I),
    "options_0DTE_events": re.compile(r"\b(0dte|option|gamma|delta|iv|implied volatility|open interest|assignment|exercise)\b", re.I),
    "macro_override_events": re.compile(r"\b(payroll|jobs|cpi|ppi|fed|yield|treasury|auction|rates|inflation|sentiment)\b", re.I),
    "institutional_liquidity_events": re.compile(r"\b(institutional|liquidity|market maker|dealer|etf desk|quant|prop desk|hedge fund|absorb|fade)\b", re.I),
    "market_maker_response_events": re.compile(r"\b(market maker|dealer|spread|hedg|gamma|liquidity provider|order-flow toxicity)\b", re.I),
    "false_signal_events": re.compile(r"\b(false signal|false positive|misattribut|noise|overfit|chatter|rumor)\b", re.I),
}

CATEGORY_PATTERNS = {
    "index_etf": re.compile(r"\b(SPY|QQQ|IWM|DIA|index ETF|index)\b", re.I),
    "options_0dte": re.compile(r"\b(0DTE|option|gamma|IV|open interest|assignment|exercise)\b", re.I),
    "broker_platform": re.compile(r"\b(HOOD|BULL|Robinhood|Webull|Schwab|Fidelity|Alpaca|IBKR|Interactive Brokers)\b", re.I),
    "ai_semis": re.compile(r"\b(NVDA|AVGO|MRVL|semiconductor|AI infrastructure|capex|Broadcom|Marvell)\b", re.I),
    "macro_rates": re.compile(r"\b(CPI|PPI|jobs|payroll|Treasury|auction|yield|rates|Fed)\b", re.I),
    "oil_geopolitics": re.compile(r"\b(oil|Hormuz|Iran|Middle East|geopolitical|crude)\b", re.I),
    "meme_smallcap": re.compile(r"\b(meme|small cap|low float|short interest|IWM)\b", re.I),
}


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def positive_int(value: Any) -> Optional[int]:
    coerced = coerce_int(value)
    return coerced if coerced is not None and coerced > 0 else None


def config_total_rounds(config: Dict[str, Any]) -> int:
    time_config = config.get("time_config", {}) if isinstance(config.get("time_config"), dict) else {}
    total_hours = positive_int(time_config.get("total_simulation_hours")) or 72
    minutes_per_round = positive_int(time_config.get("minutes_per_round")) or 30
    return max((total_hours * 60) // minutes_per_round, 1)


def latest_report_dir() -> Optional[Path]:
    if not REPORTS_DIR.exists():
        return None
    dirs = [path for path in REPORTS_DIR.iterdir() if path.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda path: path.stat().st_mtime)


def inspect_sqlite(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"path": str(path), "exists": path.exists(), "tables": {}}
    if not path.exists():
        return info
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for (table,) in cursor.fetchall():
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            count = None
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = int(cursor.fetchone()[0])
            except Exception:
                pass
            info["tables"][table] = {"columns": columns, "row_count": count}
        conn.close()
    except Exception as exc:
        info["error"] = str(exc)
    return info


def text_from_action(action: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("content", "text", "query", "post_content", "comment_content", "original_content", "quote_content"):
        value = action.get(key)
        if isinstance(value, str):
            parts.append(value)
    args = action.get("action_args")
    if isinstance(args, dict):
        parts.append(text_from_action(args))
    return "\n".join(part for part in parts if part)


def normalize_action(raw: Dict[str, Any], platform: str) -> Dict[str, Any]:
    action_args = raw.get("action_args") if isinstance(raw.get("action_args"), dict) else {}
    merged = {**action_args, **raw}
    text = text_from_action(merged)
    round_event = raw.get("round_event")
    if not isinstance(round_event, dict):
        round_event = action_args.get("round_event") if isinstance(action_args.get("round_event"), dict) else {}
    event_beat_id = merged.get("event_beat_id") or round_event.get("event_beat_id")
    agent_id = merged.get("agent_id", merged.get("user_id"))
    try:
        agent_id = int(agent_id)
    except Exception:
        agent_id = None
    round_num = merged.get("round_num", merged.get("round", merged.get("current_round")))
    try:
        round_num = int(round_num)
    except Exception:
        round_num = None
    return {
        "platform": platform,
        "agent_id": agent_id,
        "agent_name": merged.get("agent_name") or merged.get("name") or merged.get("user_name"),
        "round": round_num,
        "action_type": str(merged.get("action_type") or merged.get("action") or "UNKNOWN"),
        "text": text,
        "event_type": raw.get("event_type"),
        "logged_total_rounds": coerce_int(raw.get("total_rounds")),
        "logged_total_actions": coerce_int(raw.get("total_actions")),
        "event_beat_id": event_beat_id,
        "round_event": round_event,
    }


def read_jsonl(path: Path, platform: str, access_issues: List[str]) -> List[Dict[str, Any]]:
    if not path.exists():
        access_issues.append(f"missing {path}")
        return []
    actions: List[Dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            access_issues.append(f"invalid JSONL line {line_no} in {path}")
            continue
        if isinstance(raw, dict):
            actions.append(normalize_action(raw, platform))
    return actions


def extract_tickers(text: str) -> List[str]:
    found = {match.group(0).upper() for match in re.finditer(r"\b[A-Z]{1,5}\b", text)}
    return sorted(found & TICKER_ALLOWLIST)


def counter_by_round(actions: Iterable[Dict[str, Any]], extractor) -> Dict[str, Dict[str, int]]:
    buckets: Dict[str, Counter[str]] = defaultdict(Counter)
    for action in actions:
        round_key = str(action.get("round") or "unknown")
        for item in extractor(action.get("text", "")):
            buckets[round_key][item] += 1
    return {round_key: dict(counter.most_common()) for round_key, counter in sorted(buckets.items())}


def extract_categories(text: str) -> List[str]:
    return [name for name, pattern in CATEGORY_PATTERNS.items() if pattern.search(text)]


def event_markers_by_round(actions: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    markers: Dict[str, Dict[str, Any]] = {}
    for action in actions:
        event = action.get("round_event") if isinstance(action.get("round_event"), dict) else {}
        beat_id = action.get("event_beat_id") or event.get("event_beat_id")
        if not beat_id:
            continue
        round_key = str(action.get("round") or event.get("round") or "unknown")
        existing = markers.setdefault(round_key, {
            "event_beat_id": beat_id,
            "date": event.get("date"),
            "beat": event.get("beat"),
            "forecast_ballot_required": bool(event.get("forecast_ballot_required")),
            "platforms": sorted({action.get("platform", "unknown")}),
            "records": 0,
        })
        existing["records"] += 1
        existing["platforms"] = sorted(set(existing.get("platforms", [])) | {action.get("platform", "unknown")})
        if event.get("forecast_ballot_required"):
            existing["forecast_ballot_required"] = True
    return markers


def summarize_report_text(report_text: str) -> Dict[str, Any]:
    validation_lines = []
    branch_lines = []
    for line in report_text.splitlines():
        lower = line.lower()
        if any(term in lower for term in ("expected_if_branch_true", "validation", "data_to_check", "false positive")):
            validation_lines.append(line.strip())
        if any(term in lower for term in ("branch", "probability", "scenario")):
            branch_lines.append(line.strip())
    return {
        "validation_lines": validation_lines[:80],
        "branch_probability_lines": branch_lines[:80],
    }


def summarize_round_integrity(
    config: Dict[str, Any],
    run_state: Dict[str, Any],
    actions: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    planned_config_total = config_total_rounds(config)
    run_state_total = positive_int(run_state.get("total_rounds")) if isinstance(run_state, dict) else None
    max_rounds_applied = positive_int(run_state.get("max_rounds_applied")) if isinstance(run_state, dict) else None

    if run_state_total is not None:
        effective_total = run_state_total
        source = "run_state.total_rounds"
    elif max_rounds_applied is not None:
        effective_total = max_rounds_applied
        source = "run_state.max_rounds_applied"
    else:
        effective_total = planned_config_total
        source = "config.time_config"

    simulation_start_total_rounds_by_platform: Dict[str, int] = {}
    simulation_end_total_rounds_by_platform: Dict[str, int] = {}
    for action in actions:
        logged_total_rounds = positive_int(action.get("logged_total_rounds"))
        if logged_total_rounds is None:
            continue
        platform = str(action.get("platform") or "unknown")
        if action.get("event_type") == "simulation_start" and platform not in simulation_start_total_rounds_by_platform:
            simulation_start_total_rounds_by_platform[platform] = logged_total_rounds
        if action.get("event_type") == "simulation_end" and platform not in simulation_end_total_rounds_by_platform:
            simulation_end_total_rounds_by_platform[platform] = logged_total_rounds

    return {
        "total_rounds": effective_total,
        "effective_total_rounds": effective_total,
        "planned_config_total_rounds": planned_config_total,
        "stale_config_round_horizon": source != "config.time_config" and planned_config_total != effective_total,
        "max_rounds_applied": max_rounds_applied,
        "total_rounds_source": source,
        "simulation_start_total_rounds_by_platform": simulation_start_total_rounds_by_platform,
        "simulation_end_total_rounds_by_platform": simulation_end_total_rounds_by_platform,
        "simulation_start_round_mismatches": sorted(
            platform
            for platform, logged_total in simulation_start_total_rounds_by_platform.items()
            if logged_total != effective_total
        ),
        "simulation_end_round_mismatches": sorted(
            platform
            for platform, logged_total in simulation_end_total_rounds_by_platform.items()
            if logged_total != effective_total
        ),
    }


def build_telemetry(simulation_dir: Path, report_dir: Optional[Path]) -> Dict[str, Any]:
    access_issues: List[str] = []
    config = read_json(simulation_dir / "simulation_config.json") or {}
    run_state = read_json(simulation_dir / "run_state.json") or read_json(simulation_dir / "state.json") or {}
    agent_configs = config.get("agent_configs") if isinstance(config.get("agent_configs"), list) else []
    agent_layer = {int(cfg.get("agent_id", -1)): str(cfg.get("entity_type", "Unknown")) for cfg in agent_configs}
    agent_name = {int(cfg.get("agent_id", -1)): str(cfg.get("entity_name", f"Agent_{cfg.get('agent_id')}")) for cfg in agent_configs}

    actions = []
    actions.extend(read_jsonl(simulation_dir / "twitter" / "actions.jsonl", "twitter", access_issues))
    actions.extend(read_jsonl(simulation_dir / "reddit" / "actions.jsonl", "reddit", access_issues))

    for action in actions:
        if action["agent_id"] in agent_layer:
            action["actor_layer"] = agent_layer[action["agent_id"]]
        else:
            action["actor_layer"] = "Unknown"
        if not action.get("agent_name") and action["agent_id"] in agent_name:
            action["agent_name"] = agent_name[action["agent_id"]]

    db_inspection = {
        "twitter_simulation.db": inspect_sqlite(simulation_dir / "twitter_simulation.db"),
        "reddit_simulation.db": inspect_sqlite(simulation_dir / "reddit_simulation.db"),
    }

    report_text = ""
    report_files: List[str] = []
    effective_report_dir = report_dir or latest_report_dir()
    if effective_report_dir and effective_report_dir.exists():
        for name in ("full_report.md", "agent_log.jsonl", "console_log.txt"):
            path = effective_report_dir / name
            if path.exists():
                report_files.append(str(path))
                if name.endswith(".md") or name.endswith(".txt"):
                    report_text += "\n" + path.read_text(encoding="utf-8", errors="replace")
    else:
        access_issues.append("no report directory found")

    action_texts = "\n".join(action.get("text", "") for action in actions)
    event_counts = {
        name: len(pattern.findall(action_texts))
        for name, pattern in EVENT_PATTERNS.items()
    }
    round_event_markers = event_markers_by_round(actions)
    branch_summary = summarize_report_text(report_text)
    round_integrity = summarize_round_integrity(config, run_state, actions)
    action_counter = Counter((action.get("agent_id"), action.get("agent_name")) for action in actions if action.get("agent_id") is not None)
    top_agents = [
        {
            "agent_id": agent_id,
            "agent_name": name or agent_name.get(agent_id, f"Agent_{agent_id}"),
            "actor_layer": agent_layer.get(agent_id, "Unknown"),
            "actions": count,
        }
        for (agent_id, name), count in action_counter.most_common(25)
    ]

    interview_targets = []
    seen_layers = set()
    for item in top_agents:
        layer = item["actor_layer"]
        if layer not in seen_layers or len(interview_targets) < 12:
            interview_targets.append(item)
            seen_layers.add(layer)
        if len(interview_targets) >= 14:
            break

    status = "ready" if actions and report_text else "partial"
    return {
        "status": status,
        "simulation_dir": str(simulation_dir),
        "report_dir": str(effective_report_dir) if effective_report_dir else None,
        "access_issues": access_issues,
        "total_rounds": round_integrity["total_rounds"],
        "effective_total_rounds": round_integrity["effective_total_rounds"],
        "planned_config_total_rounds": round_integrity["planned_config_total_rounds"],
        "stale_config_round_horizon": round_integrity["stale_config_round_horizon"],
        "max_rounds_applied": round_integrity["max_rounds_applied"],
        "total_rounds_source": round_integrity["total_rounds_source"],
        "simulation_start_total_rounds_by_platform": round_integrity["simulation_start_total_rounds_by_platform"],
        "simulation_end_total_rounds_by_platform": round_integrity["simulation_end_total_rounds_by_platform"],
        "simulation_start_round_mismatches": round_integrity["simulation_start_round_mismatches"],
        "simulation_end_round_mismatches": round_integrity["simulation_end_round_mismatches"],
        "round_integrity": round_integrity,
        "run_state": run_state,
        "db_inspection": db_inspection,
        "unique_active_agents": len({action["agent_id"] for action in actions if action.get("agent_id") is not None}),
        "active_agents_by_layer": dict(Counter(action.get("actor_layer", "Unknown") for action in actions if action.get("agent_id") is not None)),
        "actions_by_actor_layer": dict(Counter(action.get("actor_layer", "Unknown") for action in actions)),
        "actions_by_platform": dict(Counter(action.get("platform", "unknown") for action in actions)),
        "round_event_markers": round_event_markers,
        "event_beats_by_round": round_event_markers,
        "ticker_mentions_by_round": counter_by_round(actions, extract_tickers),
        "category_mentions_by_round": counter_by_round(actions, extract_categories),
        "narrative_clusters_by_round": counter_by_round(actions, extract_categories),
        "forecast_ballot_summary": {
            "detected_ballot_like_actions": sum(1 for action in actions if re.search(r"\b(forecast ballot|probability|would change my mind|confidence)\b", action.get("text", ""), re.I)),
            "event_marker_ballot_rounds": sorted(
                int(round_key)
                for round_key, marker in round_event_markers.items()
                if round_key.isdigit() and marker.get("forecast_ballot_required")
            ),
            "report_lines": branch_summary["branch_probability_lines"],
        },
        "branch_probability_history": branch_summary["branch_probability_lines"],
        "causal_attribution_counts": event_counts,
        "broker_confusion_events": event_counts["broker_confusion_events"],
        "buying_power_margin_confusion_events": event_counts["buying_power_margin_confusion_events"],
        "AI_bot_copycat_events": event_counts["AI_bot_copycat_events"],
        "options_0DTE_events": event_counts["options_0DTE_events"],
        "macro_override_events": event_counts["macro_override_events"],
        "institutional_liquidity_events": event_counts["institutional_liquidity_events"],
        "market_maker_response_events": event_counts["market_maker_response_events"],
        "false_signal_events": event_counts["false_signal_events"],
        "validation_tasks_extracted": branch_summary["validation_lines"],
        "top_influential_agents": top_agents,
        "agents_to_interview_in_stage05": interview_targets,
        "report_files_read": report_files,
    }


def write_markdown(path: Path, telemetry: Dict[str, Any]) -> None:
    lines = [
        "# MiroFish Post-Run Telemetry",
        "",
        f"- Status: `{telemetry['status']}`",
        f"- Simulation directory: `{telemetry['simulation_dir']}`",
        f"- Report directory: `{telemetry.get('report_dir')}`",
        f"- Total rounds (effective): `{telemetry['total_rounds']}` source=`{telemetry['total_rounds_source']}`",
    ]
    if telemetry.get("max_rounds_applied") is not None:
        lines.append(f"- Max rounds applied: `{telemetry['max_rounds_applied']}`")
    if telemetry.get("simulation_start_total_rounds_by_platform"):
        lines.append(f"- simulation_start total_rounds by platform: `{telemetry['simulation_start_total_rounds_by_platform']}`")
    if telemetry.get("simulation_end_total_rounds_by_platform"):
        lines.append(f"- simulation_end total_rounds by platform: `{telemetry['simulation_end_total_rounds_by_platform']}`")
    if telemetry.get("simulation_start_round_mismatches"):
        lines.append(f"- simulation_start mismatches vs effective total_rounds: `{telemetry['simulation_start_round_mismatches']}`")
    if telemetry.get("simulation_end_round_mismatches"):
        lines.append(f"- simulation_end mismatches vs effective total_rounds: `{telemetry['simulation_end_round_mismatches']}`")
    lines.extend([
        f"- Planned config round horizon: `{telemetry['planned_config_total_rounds']}`",
        f"- Stale config horizon differs from effective run: `{telemetry['stale_config_round_horizon']}`",
        f"- Unique active agents: `{telemetry['unique_active_agents']}`",
        f"- Actions by platform: `{telemetry['actions_by_platform']}`",
        f"- Actions by actor layer: `{telemetry['actions_by_actor_layer']}`",
        f"- Round event markers: `{len(telemetry.get('round_event_markers', {}))}`",
        "",
        "## Event Counts",
    ])
    for key in (
        "broker_confusion_events",
        "buying_power_margin_confusion_events",
        "AI_bot_copycat_events",
        "options_0DTE_events",
        "macro_override_events",
        "institutional_liquidity_events",
        "market_maker_response_events",
        "false_signal_events",
    ):
        lines.append(f"- {key}: `{telemetry[key]}`")
    lines.extend(["", "## Stage 05 Interview Candidates"])
    for item in telemetry["agents_to_interview_in_stage05"]:
        lines.append(f"- Agent {item['agent_id']} ({item['actor_layer']}): {item['agent_name']} actions={item['actions']}")
    if telemetry["access_issues"]:
        lines.extend(["", "## Access Issues"])
        for issue in telemetry["access_issues"]:
            lines.append(f"- {issue}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract MiroFish post-run telemetry without starting a simulation.")
    parser.add_argument("--simulation-dir", type=Path, default=DEFAULT_SIM_DIR)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--write", action="store_true", help="Write postrun_telemetry.json and postrun_telemetry.md into the simulation directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    telemetry = build_telemetry(args.simulation_dir, args.report_dir)
    if args.write:
        args.simulation_dir.mkdir(parents=True, exist_ok=True)
        (args.simulation_dir / "postrun_telemetry.json").write_text(
            json.dumps(telemetry, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        write_markdown(args.simulation_dir / "postrun_telemetry.md", telemetry)

    if args.json:
        print(json.dumps(telemetry, indent=2, sort_keys=True))
    else:
        print(f"MiroFish post-run telemetry status: {telemetry['status']}")
        print(f"Unique active agents: {telemetry['unique_active_agents']}")
        print(f"Actions by platform: {telemetry['actions_by_platform']}")
        if telemetry["access_issues"]:
            print("Access issues:")
            for issue in telemetry["access_issues"][:10]:
                print(f"- {issue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
