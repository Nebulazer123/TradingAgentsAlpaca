"""Artifacts for the original TradingAgents creator workflow.

The creator workflow is useful research context, but it has no execution
authority in this repo. This module preserves the role-by-role output from
``TradingAgentsGraph.propagate(...)`` as markdown plus a compact JSON packet so
overnight runs can be inspected and scored without stuffing full reports into
compact context.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component

UTC = datetime.timezone.utc
FORBIDDEN_EFFECTS = [
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
    "cancel_order",
]

CREATOR_ROLE_SPECS = (
    {
        "role": "market_analyst",
        "team": "analyst_team",
        "title": "Market Analyst",
        "directory": "1_analysts",
        "filename": "market.md",
        "path": ("market_report",),
    },
    {
        "role": "sentiment_analyst",
        "team": "analyst_team",
        "title": "Sentiment Analyst",
        "directory": "1_analysts",
        "filename": "sentiment.md",
        "path": ("sentiment_report",),
    },
    {
        "role": "news_analyst",
        "team": "analyst_team",
        "title": "News Analyst",
        "directory": "1_analysts",
        "filename": "news.md",
        "path": ("news_report",),
    },
    {
        "role": "fundamentals_analyst",
        "team": "analyst_team",
        "title": "Fundamentals Analyst",
        "directory": "1_analysts",
        "filename": "fundamentals.md",
        "path": ("fundamentals_report",),
    },
    {
        "role": "bull_researcher",
        "team": "research_team",
        "title": "Bull Researcher",
        "directory": "2_research",
        "filename": "bull.md",
        "path": ("investment_debate_state", "bull_history"),
    },
    {
        "role": "bear_researcher",
        "team": "research_team",
        "title": "Bear Researcher",
        "directory": "2_research",
        "filename": "bear.md",
        "path": ("investment_debate_state", "bear_history"),
    },
    {
        "role": "research_manager",
        "team": "research_team",
        "title": "Research Manager",
        "directory": "2_research",
        "filename": "manager.md",
        "path": ("investment_debate_state", "judge_decision"),
    },
    {
        "role": "trader",
        "team": "trading_team",
        "title": "Trader",
        "directory": "3_trading",
        "filename": "trader.md",
        "path": ("trader_investment_plan",),
    },
    {
        "role": "aggressive_risk_analyst",
        "team": "risk_management_team",
        "title": "Aggressive Risk Analyst",
        "directory": "4_risk",
        "filename": "aggressive.md",
        "path": ("risk_debate_state", "aggressive_history"),
    },
    {
        "role": "neutral_risk_analyst",
        "team": "risk_management_team",
        "title": "Neutral Risk Analyst",
        "directory": "4_risk",
        "filename": "neutral.md",
        "path": ("risk_debate_state", "neutral_history"),
    },
    {
        "role": "conservative_risk_analyst",
        "team": "risk_management_team",
        "title": "Conservative Risk Analyst",
        "directory": "4_risk",
        "filename": "conservative.md",
        "path": ("risk_debate_state", "conservative_history"),
    },
    {
        "role": "portfolio_manager",
        "team": "portfolio_management",
        "title": "Portfolio Manager",
        "directory": "5_portfolio",
        "filename": "decision.md",
        "path": ("risk_debate_state", "judge_decision"),
        "fallback_path": ("final_trade_decision",),
    },
)

TEAM_TITLES = {
    "analyst_team": "I. Analyst Team Reports",
    "research_team": "II. Research Team Decision",
    "trading_team": "III. Trading Team Plan",
    "risk_management_team": "IV. Risk Management Team Decision",
    "portfolio_management": "V. Portfolio Manager Decision",
}


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _get_path(mapping: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _role_content(final_state: Mapping[str, Any], spec: Mapping[str, Any]) -> str:
    value = _get_path(final_state, tuple(spec["path"]))
    if not str(value or "").strip() and spec.get("fallback_path"):
        value = _get_path(final_state, tuple(spec["fallback_path"]))
    return str(value or "").strip()


def extract_creator_workflow_roles(final_state: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return non-empty creator workflow role outputs in display order."""

    roles: list[dict[str, str]] = []
    for spec in CREATOR_ROLE_SPECS:
        content = _role_content(final_state, spec)
        if not content:
            continue
        roles.append(
            {
                "role": str(spec["role"]),
                "team": str(spec["team"]),
                "title": str(spec["title"]),
                "directory": str(spec["directory"]),
                "filename": str(spec["filename"]),
                "content": content,
            }
        )
    return roles


def _render_complete_report(*, symbol: str, trade_date: str, roles: list[dict[str, str]]) -> str:
    sections: list[str] = []
    for team, team_title in TEAM_TITLES.items():
        team_roles = [role for role in roles if role["team"] == team]
        if not team_roles:
            continue
        body = "\n\n".join(
            f"### {role['title']}\n{role['content']}" for role in team_roles
        )
        sections.append(f"## {team_title}\n\n{body}")
    header = (
        f"# TradingAgents Creator Workflow Report: {symbol}\n\n"
        f"Trade date: {trade_date}\n\n"
        f"Generated: {_now_iso()}\n\n"
        "Execution authority: none\n\n"
    )
    return header + "\n\n".join(sections)


def write_creator_workflow_artifacts(
    final_state: Mapping[str, Any],
    *,
    symbol: str,
    trade_date: str,
    output_root: Path,
    rating: str | None = None,
    signal: str | None = None,
) -> dict[str, Any]:
    """Write role markdown and compact packet for one creator workflow run."""

    safe_symbol = safe_ticker_component(symbol.upper())
    symbol_root = Path(output_root) / safe_symbol
    symbol_root.mkdir(parents=True, exist_ok=True)

    roles = extract_creator_workflow_roles(final_state)
    role_artifacts: list[dict[str, Any]] = []
    for role in roles:
        role_dir = symbol_root / role["directory"]
        role_dir.mkdir(parents=True, exist_ok=True)
        role_path = role_dir / role["filename"]
        role_path.write_text(role["content"], encoding="utf-8")
        relative_path = role_path.relative_to(symbol_root).as_posix()
        role_artifacts.append(
            {
                "role": role["role"],
                "team": role["team"],
                "title": role["title"],
                "relative_path": relative_path,
                "path": str(role_path),
                "content_chars": len(role["content"]),
            }
        )

    complete_report_path = symbol_root / "complete_report.md"
    complete_report_path.write_text(
        _render_complete_report(symbol=safe_symbol, trade_date=trade_date, roles=roles),
        encoding="utf-8",
    )

    packet = {
        "schema_version": "1.0.0",
        "packet_id": f"creator-workflow-{uuid.uuid4().hex}",
        "generated_at": _now_iso(),
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "symbol": safe_symbol,
        "trade_date": trade_date,
        "rating": str(rating or ""),
        "signal": str(signal or ""),
        "role_count": len(role_artifacts),
        "role_artifacts": role_artifacts,
        "complete_report_path": str(complete_report_path),
    }
    packet_path = symbol_root / "creator_workflow_packet.json"
    packet["packet_path"] = str(packet_path)
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    return packet


def build_creator_workflow_status(overnight_packet: Mapping[str, Any] | None) -> dict[str, Any]:
    """Summarize creator workflow refs from an overnight packet for dashboards."""

    workflows: list[dict[str, Any]] = []
    for item in (overnight_packet or {}).get("ticker_results") or []:
        if not isinstance(item, Mapping):
            continue
        workflow = item.get("creator_workflow")
        if not isinstance(workflow, Mapping):
            continue
        packet_path = str(workflow.get("packet_path") or "").strip()
        if not packet_path:
            continue
        workflows.append(
            {
                "symbol": str(item.get("symbol") or "").upper(),
                "packet_path": packet_path,
                "complete_report_path": str(workflow.get("complete_report_path") or ""),
                "role_count": int(workflow.get("role_count") or 0),
                "execution_authority": workflow.get("execution_authority"),
            }
        )
    missing_role_count = sum(1 for item in workflows if int(item.get("role_count") or 0) < 4)
    bad_authority_count = sum(
        1 for item in workflows if item.get("execution_authority") not in {None, "none"}
    )
    return {
        "schema_version": "1.0.0",
        "kind": "creator_workflow_status",
        "generated_at": _now_iso(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "workflow_count": len(workflows),
        "symbols": [item["symbol"] for item in workflows if item.get("symbol")],
        "role_count_min": min((item["role_count"] for item in workflows), default=None),
        "missing_role_count": missing_role_count,
        "bad_authority_count": bad_authority_count,
        "packet_paths": [item["packet_path"] for item in workflows[:10]],
        "complete_report_paths": [item["complete_report_path"] for item in workflows[:10]],
        "workflows": workflows,
    }
