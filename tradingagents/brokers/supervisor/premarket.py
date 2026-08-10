"""Premarket brief validation and blocker classification helpers."""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tradingagents.brokers.supervisor.candidates import CandidateSignal
from tradingagents.brokers.supervisor.session import UTC
from tradingagents.policy.io import atomic_write_text

_SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9.]{0,5}\b")
_NON_SYMBOL_WORDS = {
    "AI",
    "API",
    "BUY",
    "CASH",
    "ETF",
    "HOLD",
    "JSON",
    "LIVE",
    "MARKET",
    "NEWS",
    "ORDER",
    "PAPER",
    "QQQ",
    "SELL",
    "SPY",
    "USD",
}


def _read_json_packet(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_generated_at(value: object) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_future_timestamp(
    generated_at: datetime.datetime,
    now: datetime.datetime,
    *,
    tolerance: datetime.timedelta = datetime.timedelta(minutes=5),
) -> bool:
    return generated_at - now.astimezone(UTC) > tolerance


def _normalize_symbol(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw or raw in _NON_SYMBOL_WORDS:
        return None
    if not _SYMBOL_RE.fullmatch(raw):
        return None
    return raw


def _unique_packet_path(output_path: Path, stem: str, suffix: str = ".json") -> Path:
    candidate = output_path / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = output_path / f"{stem}-{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique packet path for {stem}{suffix}")


def render_premarket_brief_markdown(packet: Mapping) -> str:
    instructions = packet.get("premarket_instructions") or {}
    lines = [
        "# TradingAgents Premarket Brief",
        "",
        f"- Generated at: {packet.get('generated_at', 'unknown')}",
        f"- Analysis only: {packet.get('analysis_only', True)}",
        f"- Source packets: {len(packet.get('source_packets') or [])}",
        f"- Top symbol to validate: {instructions.get('top_symbol') or 'none'}",
        "",
        "## What Changed",
    ]
    for change in packet.get("material_changes") or []:
        lines.append(f"- {change.get('category')}: {change.get('summary')}")
    lines.extend(["", "## Timeline"])
    for item in packet.get("timeline") or []:
        lines.append(
            "- "
            f"{item.get('generated_at', 'unknown')} "
            f"[{item.get('kind', 'unknown')}]: "
            f"{item.get('summary', '')}"
        )
        if item.get("kind") == "overnight_plan" and item.get("research_context"):
            context = item.get("research_context") or {}
            lines.append(
                "  - Research context: "
                f"{context.get('packet_count', 0)} packet(s), "
                f"blocked {context.get('blocked_count', 0)}, "
                f"watchlists {', '.join(context.get('watchlists') or []) or 'none'}"
            )
    warnings = packet.get("stale_warnings") or []
    if warnings:
        lines.extend(["", "## Warnings"])
        for warning in warnings:
            lines.append(f"- {warning}")
    blockers = packet.get("unresolved_blockers") or []
    if blockers:
        lines.extend(["", "## Active Blockers"])
        for blocker in blockers:
            lines.append(f"- {blocker.get('summary') or blocker.get('reason') or 'unresolved blocker'}")
    locks = packet.get("control_plane_locks") or []
    if locks:
        lines.extend(["", "## Safety Locks"])
        for lock in locks:
            lines.append(
                "- "
                f"{lock.get('summary') or lock.get('reason') or 'live-control safety lock'} "
                "(expected: no orders submitted)"
            )
    lines.extend(["", "## Premarket Instructions"])
    lines.append(f"- {instructions.get('summary', '')}")
    if instructions.get("current_control_lock"):
        lines.append(f"- Current live-control lock: {instructions.get('current_control_lock')}")
    for item in instructions.get("must_validate_fresh") or []:
        lines.append(f"- Validate fresh: {item}")
    return "\n".join(lines)


def compact_premarket_brief_payload(packet: Mapping[str, Any], packet_path: Path | str) -> dict[str, Any]:
    """Build a compact, lossless-by-reference premarket brief summary."""

    instructions = packet.get("premarket_instructions") or {}
    timeline = packet.get("timeline") or []
    source_packets = packet.get("source_packets") or []
    return {
        "schema": "compact_premarket_brief_v1",
        "analysis_only": True,
        "raw_packet_path": str(packet_path),
        "generated_at": packet.get("generated_at"),
        "execution_authority": "none",
        "counts": {
            "source_packets": len(source_packets) if isinstance(source_packets, list) else 0,
            "timeline": len(timeline) if isinstance(timeline, list) else 0,
            "unresolved_blockers": len(packet.get("unresolved_blockers") or []),
            "control_plane_locks": len(packet.get("control_plane_locks") or []),
            "historical_blockers": len(packet.get("historical_blockers") or []),
            "stale_warnings": len(packet.get("stale_warnings") or []),
            "material_changes": len(packet.get("material_changes") or []),
        },
        "premarket_instructions": {
            "summary": instructions.get("summary") if isinstance(instructions, dict) else None,
            "top_symbol": instructions.get("top_symbol") if isinstance(instructions, dict) else None,
            "latest_hourly_decision": instructions.get("latest_hourly_decision")
            if isinstance(instructions, dict)
            else None,
            "latest_overnight_generated_at": instructions.get("latest_overnight_generated_at")
            if isinstance(instructions, dict)
            else None,
            "paper_tournament_leader": instructions.get("paper_tournament_leader")
            if isinstance(instructions, dict)
            else None,
            "current_control_lock": instructions.get("current_control_lock")
            if isinstance(instructions, dict)
            else None,
            "must_validate_fresh": list(instructions.get("must_validate_fresh") or [])
            if isinstance(instructions, dict)
            else [],
        },
        "stale_warnings": packet.get("stale_warnings") or [],
        "raw_field_groups": [
            "source_packets",
            "timeline",
            "unresolved_blockers",
            "control_plane_locks",
            "historical_blockers",
            "premarket_instructions",
            "material_changes",
        ],
    }


def write_premarket_brief_packet(
    packet: Mapping,
    *,
    output_dir: str | Path = "results/premarket_briefs",
    write_latest: bool = True,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_generated_at(packet.get("generated_at")) or datetime.datetime.now(tz=UTC)
    stem = f"premarket-brief-{generated_at:%Y%m%d-%H%M%S-%f}"
    packet_path = _unique_packet_path(output_path, stem)
    data = dict(packet)
    data.setdefault("generated_at", generated_at.isoformat(timespec="seconds"))
    data.setdefault("analysis_only", True)
    data["packet_path"] = str(packet_path)
    packet_text = json.dumps(data, indent=2)
    atomic_write_text(packet_path, packet_text)
    markdown = render_premarket_brief_markdown(data)
    markdown_path = _unique_packet_path(output_path, stem, ".md")
    atomic_write_text(markdown_path, markdown)
    compact = compact_premarket_brief_payload(data, packet_path)
    compact_text = json.dumps(compact, indent=2)
    compact_path = packet_path.with_suffix(".compact.json")
    atomic_write_text(compact_path, compact_text)
    if write_latest:
        atomic_write_text(output_path / "latest.json", packet_text)
        atomic_write_text(output_path / "latest.md", markdown)
        atomic_write_text(output_path / "latest-compact.json", compact_text)
    return packet_path


def load_latest_premarket_brief(
    output_dir: str | Path = "results/premarket_briefs",
) -> dict | None:
    path = Path(output_dir)
    if not path.exists():
        return None
    candidates = [path / "latest.json"] if (path / "latest.json").exists() else []
    candidates.extend(sorted(path.glob("premarket-brief-*.json"), reverse=True))
    for candidate in candidates:
        packet = _read_json_packet(candidate)
        if packet is not None:
            return packet
    return None


def _packet_generated_at(packet: Mapping, packet_path: Path) -> datetime.datetime:
    parsed = _parse_generated_at(packet.get("generated_at"))
    if parsed:
        return parsed
    return datetime.datetime.fromtimestamp(packet_path.stat().st_mtime, tz=UTC)


def _load_packet_records(
    output_dir: str | Path,
    *,
    pattern: str,
    kind: str,
    limit: int = 24,
) -> list[dict]:
    path = Path(output_dir)
    if not path.exists():
        return []
    records = []
    for packet_path in sorted(path.glob(pattern)):
        packet = _read_json_packet(packet_path)
        if packet is None:
            continue
        generated_at = _packet_generated_at(packet, packet_path)
        records.append(
            {
                "kind": kind,
                "path": str(packet_path),
                "generated_at": generated_at,
                "packet": packet,
            }
        )
    return sorted(records, key=lambda item: item["generated_at"])[-limit:]


def _load_latest_json_record(output_dir: str | Path, *, kind: str) -> list[dict]:
    packet_path = Path(output_dir) / "latest.json"
    if not packet_path.exists():
        return []
    packet = _read_json_packet(packet_path)
    if packet is None:
        return []
    return [
        {
            "kind": kind,
            "path": str(packet_path),
            "generated_at": _packet_generated_at(packet, packet_path),
            "packet": packet,
        }
    ]


def _candidate_symbols(candidates: Sequence[Mapping], *, limit: int = 5) -> list[str]:
    symbols = []
    for candidate in candidates[:limit]:
        if isinstance(candidate, Mapping) and candidate.get("symbol"):
            symbols.append(str(candidate.get("symbol")).upper())
    return symbols


def _source_packet(record: Mapping) -> dict:
    return {
        "kind": record.get("kind"),
        "path": record.get("path"),
        "generated_at": record.get("generated_at").isoformat(timespec="seconds")
        if isinstance(record.get("generated_at"), datetime.datetime)
        else str(record.get("generated_at")),
    }


def _hourly_timeline_item(record: Mapping) -> dict:
    packet = record["packet"]
    portfolio = packet.get("portfolio") or {}
    live = portfolio.get("live") or {}
    candidates = portfolio.get("ranked_candidates") or []
    issue_reasons = [
        str(issue.get("reason"))
        for issue in packet.get("issues") or []
        if isinstance(issue, Mapping) and issue.get("reason")
    ]
    return {
        **_source_packet(record),
        "decision": packet.get("decision", "unknown"),
        "reason": packet.get("reason", ""),
        "material": bool(packet.get("material")),
        "live_unrealized_pl": live.get("unrealized_pl"),
        "positions": [
            position.get("symbol")
            for position in live.get("positions") or []
            if isinstance(position, Mapping) and position.get("symbol")
        ],
        "open_order_count": len(live.get("open_orders") or []),
        "submitted_count": len(packet.get("submitted") or []),
        "issue_count": len(packet.get("issues") or []),
        "issue_reasons": issue_reasons,
        "top_candidates": _candidate_symbols(candidates),
        "summary": (
            f"Hourly supervisor {packet.get('decision', 'unknown')}: "
            f"{packet.get('reason', '')}"
        ),
    }


def _overnight_timeline_item(record: Mapping) -> dict:
    packet = record["packet"]
    ranked = packet.get("ranked_candidates") or []
    top_symbol = ranked[0].get("symbol") if ranked and isinstance(ranked[0], Mapping) else None
    ticker_results = packet.get("ticker_results") or []
    quality = packet.get("overnight_quality") or {}
    research_context = packet.get("research_context") or {}
    prior_feed = research_context.get("prior_feed") or {}
    provider_fallbacks = research_context.get("provider_fallbacks") or {}
    skipped_sources = sorted(
        {
            str(source)
            for fallback in provider_fallbacks.values()
            if isinstance(fallback, Mapping)
            for source in fallback.get("skipped_source_names", [])
            if source
        }
    )
    fallback_count = quality.get("fallback_count")
    if fallback_count is None:
        fallback_count = len(
            [
                item
                for item in ticker_results
                if isinstance(item, Mapping) and item.get("status") == "fallback"
            ]
        )
    graph_failure_count = quality.get("graph_failure_count")
    if graph_failure_count is None:
        graph_failure_count = len(
            [
                item
                for item in ticker_results
                if isinstance(item, Mapping) and item.get("status") not in {"ok", "fallback"}
            ]
        )
    return {
        **_source_packet(record),
        "analysis_only": bool(packet.get("analysis_only", True)),
        "top_candidates": _candidate_symbols(ranked),
        "ticker_count": len(ticker_results),
        "full_graph_count": quality.get("full_graph_count"),
        "fallback_count": fallback_count,
        "graph_failure_count": graph_failure_count,
        "failure_count": graph_failure_count,
        "research_context": {
            "packet_count": research_context.get("packet_count", quality.get("research_context_packet_count", 0)),
            "blocked_count": len(research_context.get("blocked_packets") or []),
            "prior_feed": compact_prior_feed_summary(prior_feed),
            "provider_fallback_needs": sorted(provider_fallbacks.keys()),
            "watchlists": sorted((research_context.get("watchlists") or {}).keys()),
            "skipped_source_names": skipped_sources,
            "execution_authority": research_context.get("execution_authority", "none"),
        },
        "summary": f"Overnight plan top candidate {top_symbol or 'none'}",
    }


def _paper_tournament_timeline_item(record: Mapping) -> dict:
    packet = record["packet"]
    report = packet.get("report") or packet.get("latest_report") or {}
    rankings = report.get("rankings") or []
    leader = rankings[0] if rankings and isinstance(rankings[0], Mapping) else {}
    candidate = report.get("live_strategy_candidate") or {}
    return {
        **_source_packet(record),
        "leader": leader.get("strategy_id"),
        "leader_equity": leader.get("equity"),
        "live_strategy_candidate_status": candidate.get("status"),
        "live_strategy_candidate": candidate.get("strategy_id"),
        "submitted_count": packet.get("submitted_count", len(packet.get("submitted") or [])),
        "summary": f"Paper tournament leader {leader.get('strategy_id') or 'none'}",
    }


def _premarket_timeline_item(record: Mapping) -> dict:
    if record.get("kind") == "hourly_supervisor":
        return _hourly_timeline_item(record)
    if record.get("kind") == "overnight_plan":
        return _overnight_timeline_item(record)
    return _paper_tournament_timeline_item(record)


def _brief_top_symbol(timeline: Sequence[Mapping]) -> str | None:
    for item in reversed(timeline):
        if item.get("kind") == "overnight_plan" and item.get("top_candidates"):
            return str(item["top_candidates"][0]).upper()
    for item in reversed(timeline):
        if item.get("top_candidates"):
            return str(item["top_candidates"][0]).upper()
    return None


def _latest_timeline_item(timeline: Sequence[Mapping], kind: str) -> Mapping | None:
    for item in reversed(timeline):
        if item.get("kind") == kind:
            return item
    return None


def _premarket_material_changes(packet: Mapping, previous_brief: Mapping | None) -> list[dict]:
    current_instruction = packet.get("premarket_instructions") or {}
    current_latest_hourly = _latest_timeline_item(packet.get("timeline") or [], "hourly_supervisor") or {}
    if not previous_brief:
        return [
            {
                "category": "initial_brief",
                "summary": "No previous premarket brief was found; this packet starts the rolling weekend baseline.",
            }
        ]
    previous_instruction = previous_brief.get("premarket_instructions") or {}
    previous_latest_hourly = _latest_timeline_item(previous_brief.get("timeline") or [], "hourly_supervisor") or {}
    changes = []
    if current_instruction.get("top_symbol") != previous_instruction.get("top_symbol"):
        changes.append(
            {
                "category": "top_symbol",
                "summary": (
                    f"Top symbol changed from {previous_instruction.get('top_symbol') or 'none'} "
                    f"to {current_instruction.get('top_symbol') or 'none'}."
                ),
            }
        )
    if current_latest_hourly.get("decision") != previous_latest_hourly.get("decision"):
        changes.append(
            {
                "category": "hourly_decision",
                "summary": (
                    f"Latest hourly decision changed from "
                    f"{previous_latest_hourly.get('decision') or 'none'} to "
                    f"{current_latest_hourly.get('decision') or 'none'}."
                ),
            }
        )
    if current_latest_hourly.get("live_unrealized_pl") != previous_latest_hourly.get("live_unrealized_pl"):
        changes.append(
            {
                "category": "live_unrealized_pl",
                "summary": (
                    f"Live unrealized P/L changed from "
                    f"{previous_latest_hourly.get('live_unrealized_pl') or 'none'} to "
                    f"{current_latest_hourly.get('live_unrealized_pl') or 'none'}."
                ),
            }
        )
    if not changes:
        changes.append(
            {
                "category": "no_material_change",
                "summary": "No material change from the previous premarket brief.",
            }
        )
    return changes


def build_premarket_brief_packet(
    *,
    hourly_log_dir: str | Path = "results/hourly_supervisor",
    overnight_log_dir: str | Path = "results/overnight_plans",
    paper_tournament_log_dir: str | Path = "results/paper_strategy_tournament",
    previous_brief: Mapping | None = None,
    generated_at: datetime.datetime | None = None,
) -> dict:
    generated = generated_at or datetime.datetime.now(tz=UTC)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    records = []
    records.extend(
        _load_packet_records(
            overnight_log_dir,
            pattern="overnight-plan-*.json",
            kind="overnight_plan",
            limit=5,
        )
    )
    records.extend(
        _load_packet_records(
            hourly_log_dir,
            pattern="hourly-supervisor-*.json",
            kind="hourly_supervisor",
            limit=48,
        )
    )
    tournament_records = _load_latest_json_record(
        paper_tournament_log_dir,
        kind="paper_tournament",
    )
    if not tournament_records:
        tournament_records = _load_packet_records(
            paper_tournament_log_dir,
            pattern="paper-tournament-*.json",
            kind="paper_tournament",
            limit=1,
        )
    records.extend(tournament_records)
    records = sorted(records, key=lambda item: item["generated_at"])
    timeline = [_premarket_timeline_item(record) for record in records]
    source_packets = [_source_packet(record) for record in records]
    top_symbol = _brief_top_symbol(timeline)
    latest_hourly = _latest_timeline_item(timeline, "hourly_supervisor") or {}
    latest_overnight = _latest_timeline_item(timeline, "overnight_plan") or {}
    latest_tournament = _latest_timeline_item(timeline, "paper_tournament") or {}
    unresolved_blockers, control_plane_locks, historical_blockers = split_premarket_blockers(timeline)
    stale_warnings = []
    if not latest_overnight:
        stale_warnings.append("No overnight plan packet was found for the rolling premarket brief.")
    if not latest_hourly:
        stale_warnings.append("No hourly supervisor packet was found for the rolling premarket brief.")
    packet = {
        "generated_at": generated.astimezone(UTC).isoformat(timespec="seconds"),
        "analysis_only": True,
        "source_packets": source_packets,
        "timeline": timeline,
        "unresolved_blockers": unresolved_blockers,
        "control_plane_locks": control_plane_locks,
        "historical_blockers": historical_blockers,
        "stale_warnings": stale_warnings,
        "premarket_instructions": {
            "summary": "Use this rolling brief as context only; validate fresh quotes, news, orders, and account state before any live action.",
            "top_symbol": top_symbol,
            "latest_hourly_decision": latest_hourly.get("decision"),
            "latest_overnight_generated_at": latest_overnight.get("generated_at"),
            "latest_research_context": latest_overnight.get("research_context", {}),
            "paper_tournament_leader": latest_tournament.get("leader"),
            "current_control_lock": control_plane_locks[0].get("summary") if control_plane_locks else None,
            "must_validate_fresh": [
                "premarket quotes and spreads",
                "overnight and morning news/social deltas",
                "open live and paper orders",
                "current positions and P/L",
                "live sizing room and buying power",
            ],
        },
    }
    packet["material_changes"] = _premarket_material_changes(packet, previous_brief)
    return packet


def compact_prior_feed_summary(prior_feed: Mapping) -> dict[str, Any] | None:
    if not isinstance(prior_feed, Mapping) or not prior_feed.get("path"):
        return None

    prior_feed_packet: dict[str, Any] | None = None
    needs_feed_enrichment = (
        prior_feed.get("analysis_only") is None
        or not prior_feed.get("forbidden_effects")
        or prior_feed.get("prior_applied") is None
        or prior_feed.get("dedupe_applied") is None
    )
    if needs_feed_enrichment:
        prior_feed_packet = _read_json_packet(Path(str(prior_feed.get("path"))))

    def feed_value(name: str) -> Any:
        value = prior_feed.get(name)
        if value is None and prior_feed_packet:
            return prior_feed_packet.get(name)
        return value

    forbidden_effects = prior_feed.get("forbidden_effects")
    if not forbidden_effects and prior_feed_packet:
        forbidden_effects = prior_feed_packet.get("forbidden_effects")
    if isinstance(forbidden_effects, Sequence) and not isinstance(forbidden_effects, (str, bytes)):
        forbidden_effect_values = [str(effect) for effect in forbidden_effects if effect]
    else:
        forbidden_effect_values = []

    analysis_only = prior_feed.get("analysis_only")
    if analysis_only is None and prior_feed_packet:
        analysis_only = prior_feed_packet.get("analysis_only")

    execution_authority = prior_feed.get("execution_authority")
    if execution_authority is None and prior_feed_packet:
        execution_authority = prior_feed_packet.get("execution_authority")

    return {
        "schema": prior_feed.get("schema") or (prior_feed_packet or {}).get("schema"),
        "path": prior_feed.get("path"),
        "latest_path": prior_feed.get("latest_path"),
        "packet_count": feed_value("packet_count"),
        "blocked_count": feed_value("blocked_count"),
        "prior_applied": feed_value("prior_applied"),
        "dedupe_applied": feed_value("dedupe_applied"),
        "input_packet_ref_count": feed_value("input_packet_ref_count"),
        "unique_packet_ref_count": feed_value("unique_packet_ref_count"),
        "duplicate_packet_ref_count": feed_value("duplicate_packet_ref_count"),
        "carry_forward_scope": feed_value("carry_forward_scope") or [],
        "analysis_only": analysis_only,
        "execution_authority": execution_authority or "none",
        "forbidden_effects": forbidden_effect_values,
    }


def compact_research_context_summary(research_context: Mapping) -> dict[str, Any]:
    if not isinstance(research_context, Mapping):
        return {}

    provider_fallbacks = research_context.get("provider_fallbacks") or {}
    provider_fallback_needs = research_context.get("provider_fallback_needs")
    if not provider_fallback_needs and isinstance(provider_fallbacks, Mapping):
        provider_fallback_needs = sorted(provider_fallbacks.keys())

    watchlists = research_context.get("watchlists") or []
    if isinstance(watchlists, Mapping):
        watchlist_values = sorted(str(key) for key in watchlists)
    elif isinstance(watchlists, Sequence) and not isinstance(watchlists, (str, bytes)):
        watchlist_values = sorted(str(item) for item in watchlists if item)
    else:
        watchlist_values = []

    skipped_sources = research_context.get("skipped_source_names") or []
    if isinstance(skipped_sources, Sequence) and not isinstance(skipped_sources, (str, bytes)):
        skipped_source_values = sorted(str(source) for source in skipped_sources if source)
    else:
        skipped_source_values = []

    provider_need_values = (
        sorted(str(need) for need in provider_fallback_needs if need)
        if isinstance(provider_fallback_needs, Sequence) and not isinstance(provider_fallback_needs, (str, bytes))
        else []
    )
    return {
        "packet_count": research_context.get("packet_count", 0),
        "blocked_count": research_context.get("blocked_count", 0),
        "prior_feed": compact_prior_feed_summary(research_context.get("prior_feed") or {}),
        "provider_fallback_needs": provider_need_values,
        "watchlists": watchlist_values,
        "skipped_source_names": skipped_source_values,
        "execution_authority": research_context.get("execution_authority", "none"),
    }


def timeline_item_has_blocker(item: Mapping) -> bool:
    return bool(item.get("issue_count", 0)) or str(item.get("decision", "")).lower() == "blocked"


def is_expected_hourly_safety_lock(item: Mapping) -> bool:
    """Return true for a correctly refused live-control action with no broker effect."""

    if item.get("kind") != "hourly_supervisor":
        return False
    if str(item.get("decision", "")).lower() != "blocked":
        return False
    if int(item.get("submitted_count") or 0) != 0:
        return False
    if int(item.get("open_order_count") or 0) != 0:
        return False
    text = " ".join(
        [
            str(item.get("reason") or ""),
            *[str(reason) for reason in item.get("issue_reasons") or []],
        ]
    ).lower()
    expected_markers = (
        "guard validation",
        "guardrail validation",
        "live-submit-guard",
        "risk envelope missing",
        "promotion state missing",
        "live control state missing",
        "tiny_live execution_mode",
    )
    return any(marker in text for marker in expected_markers)


def split_premarket_blockers(timeline: Sequence[Mapping]) -> tuple[list[dict], list[dict], list[dict]]:
    latest_by_kind: dict[str, Mapping] = {}
    for item in timeline:
        kind = str(item.get("kind") or "")
        if kind:
            latest_by_kind[kind] = item

    unresolved: list[dict] = []
    control_locks: list[dict] = []
    historical: list[dict] = []
    for item in timeline:
        if not timeline_item_has_blocker(item):
            continue
        item_dict = dict(item)
        is_latest = latest_by_kind.get(str(item.get("kind") or "")) is item
        if not is_latest:
            item_dict["blocker_status"] = "historical"
            historical.append(item_dict)
        elif is_expected_hourly_safety_lock(item):
            item_dict["blocker_status"] = "expected_safety_lock"
            control_locks.append(item_dict)
        else:
            item_dict["blocker_status"] = "unresolved"
            unresolved.append(item_dict)
    return unresolved, control_locks, historical


def validate_premarket_brief_against_candidates(
    premarket_brief: Mapping | None,
    current_candidates: Sequence[CandidateSignal],
    *,
    now: datetime.datetime | None = None,
    stale_after_hours: int = 72,
) -> dict[str, Any]:
    if not premarket_brief:
        return {
            "status": "stale_or_missing",
            "reason": "No premarket brief packet was found.",
        }
    generated_at = _parse_generated_at(premarket_brief.get("generated_at"))
    current_time = now or datetime.datetime.now(tz=UTC)
    if generated_at and _is_future_timestamp(generated_at, current_time):
        return {
            "status": "stale_or_missing",
            "reason": "Latest premarket brief timestamp is in the future relative to this run.",
            "generated_at": premarket_brief.get("generated_at"),
            "source_packet_count": len(premarket_brief.get("source_packets") or []),
        }
    if not generated_at or current_time - generated_at > datetime.timedelta(hours=stale_after_hours):
        return {
            "status": "stale_or_missing",
            "reason": "Latest premarket brief is missing a usable timestamp or is stale.",
            "generated_at": premarket_brief.get("generated_at"),
            "source_packet_count": len(premarket_brief.get("source_packets") or []),
        }
    instructions = premarket_brief.get("premarket_instructions") or {}
    latest_research_context = compact_research_context_summary(
        instructions.get("latest_research_context") or {}
    )
    brief_top = _normalize_symbol(instructions.get("top_symbol"))
    current_ranked = sorted(current_candidates, key=lambda candidate: candidate.score, reverse=True)
    current_top = current_ranked[0].symbol if current_ranked else None
    current_symbols = {candidate.symbol for candidate in current_ranked}
    if not brief_top:
        return {
            "status": "stale_or_missing",
            "reason": "Latest premarket brief has no top symbol to validate.",
            "generated_at": premarket_brief.get("generated_at"),
            "source_packet_count": len(premarket_brief.get("source_packets") or []),
        }
    if brief_top == current_top:
        status = "confirmed"
        reason = "Fresh pre-open candidate ranking still agrees with the rolling premarket brief."
    elif brief_top in current_symbols:
        status = "amended"
        reason = "Fresh pre-open ranking changed the order but the brief top idea remains viable."
    else:
        status = "invalidated"
        reason = "Fresh pre-open ranking no longer supports the brief top idea."
    return {
        "status": status,
        "reason": reason,
        "generated_at": premarket_brief.get("generated_at"),
        "brief_top_symbol": brief_top,
        "current_top_symbol": current_top,
        "source_packet_count": len(premarket_brief.get("source_packets") or []),
        "latest_research_context": latest_research_context,
    }
