"""Overnight-plan packet IO and validation helpers."""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tradingagents.brokers.supervisor.candidates import CandidateSignal
from tradingagents.brokers.supervisor.session import CENTRAL, UTC
from tradingagents.policy.io import atomic_write_text


def _parse_generated_at(value: object) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _unique_packet_path(output_path: Path, stem: str, suffix: str = ".json") -> Path:
    candidate = output_path / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = output_path / f"{stem}-{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique packet path for {stem}{suffix}")


def _is_future_timestamp(
    generated_at: datetime.datetime,
    current_time: datetime.datetime,
    *,
    tolerance_minutes: int = 5,
) -> bool:
    return generated_at - current_time > datetime.timedelta(minutes=tolerance_minutes)


def _normalize_symbol(value: object) -> str | None:
    symbol = str(value or "").upper().strip()
    if not symbol:
        return None
    return symbol


def write_overnight_plan_packet(
    packet: Mapping,
    *,
    output_dir: str | Path = "results/overnight_plans",
    write_latest: bool = True,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_generated_at(packet.get("generated_at")) or datetime.datetime.now(tz=UTC)
    stem = f"overnight-plan-{generated_at:%Y%m%d-%H%M%S-%f}"
    packet_path = _unique_packet_path(output_path, stem)
    data = dict(packet)
    data.setdefault("generated_at", generated_at.isoformat(timespec="seconds"))
    data.setdefault("analysis_only", True)
    data["latest_alias_written"] = bool(write_latest)
    data["packet_path"] = str(packet_path)
    packet_text = json.dumps(data, indent=2)
    atomic_write_text(packet_path, packet_text)
    compact_packet = compact_overnight_plan_payload(data, packet_path)
    compact_text = json.dumps(compact_packet, indent=2)
    compact_path = packet_path.with_name(f"{packet_path.stem}.compact.json")
    atomic_write_text(compact_path, compact_text)
    markdown = render_overnight_plan_markdown(data)
    markdown_path = _unique_packet_path(output_path, stem, ".md")
    atomic_write_text(markdown_path, markdown)
    if write_latest:
        atomic_write_text(output_path / "latest.json", packet_text)
        atomic_write_text(output_path / "latest-compact.json", compact_text)
        atomic_write_text(output_path / "latest.md", markdown)
    return packet_path


def compact_overnight_plan_payload(packet: Mapping[str, Any], packet_path: Path | str) -> dict[str, Any]:
    ranked = packet.get("ranked_candidates") or []
    ticker_results = packet.get("ticker_results") or []
    research_context = packet.get("research_context") or {}
    top_provider_bundles = packet.get("top_provider_bundles") or {}
    overnight_quality = packet.get("overnight_quality") or {}
    ticker_status_counts: dict[str, int] = {}
    creator_workflows: list[dict[str, Any]] = []
    if isinstance(ticker_results, list):
        for item in ticker_results:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "unknown"))
            ticker_status_counts[status] = ticker_status_counts.get(status, 0) + 1
            workflow = item.get("creator_workflow")
            if not isinstance(workflow, dict):
                continue
            packet_ref = str(workflow.get("packet_path") or "").strip()
            if not packet_ref:
                continue
            creator_workflows.append(
                {
                    "symbol": str(item.get("symbol") or "").upper(),
                    "packet_path": packet_ref,
                    "complete_report_path": str(workflow.get("complete_report_path") or ""),
                    "role_count": int(workflow.get("role_count") or 0),
                    "execution_authority": workflow.get("execution_authority"),
                }
            )
    creator_role_counts = [
        int(item["role_count"]) for item in creator_workflows if item.get("role_count") is not None
    ]
    top_candidate = ranked[0] if isinstance(ranked, list) and ranked else {}
    return {
        "schema": "compact_overnight_plan_v1",
        "analysis_only": True,
        "raw_packet_path": str(packet_path),
        "generated_at": packet.get("generated_at"),
        "trade_date": packet.get("trade_date"),
        "methodology_ref": "raw_packet_path.methodology",
        "execution_authority": "none",
        "submitted_count": len(packet.get("submitted") or []),
        "counts": {
            "candidate_universe": len(packet.get("candidate_universe") or []),
            "tradable_universe": len(packet.get("tradable_universe") or []),
            "rejected_symbols": len(packet.get("rejected_symbols") or []),
            "ranked_candidates": len(ranked) if isinstance(ranked, list) else 0,
            "ticker_results": len(ticker_results) if isinstance(ticker_results, list) else 0,
        },
        "top_candidate": {
            "symbol": top_candidate.get("symbol"),
            "rating": top_candidate.get("rating"),
            "score": top_candidate.get("score"),
            "method": top_candidate.get("method"),
        }
        if isinstance(top_candidate, dict)
        else {},
        "ticker_status_counts": ticker_status_counts,
        "creator_workflow_summary": {
            "workflow_count": len(creator_workflows),
            "symbols": [item["symbol"] for item in creator_workflows[:5] if item.get("symbol")],
            "role_count_min": min(creator_role_counts) if creator_role_counts else None,
            "packet_paths": [item["packet_path"] for item in creator_workflows[:5]],
            "complete_report_paths": [
                item["complete_report_path"] for item in creator_workflows[:5]
            ],
            "bad_authority_count": sum(
                1 for item in creator_workflows if item.get("execution_authority") not in {None, "none"}
            ),
        },
        "overnight_quality": {
            "full_graph_limit": overnight_quality.get("full_graph_limit"),
            "requested_full_graph_limit": overnight_quality.get("requested_full_graph_limit"),
            "full_graph_count": overnight_quality.get("full_graph_count"),
            "full_graph_attempt_count": overnight_quality.get("full_graph_attempt_count"),
            "full_graph_success_count": overnight_quality.get("full_graph_success_count"),
            "fallback_count": overnight_quality.get("fallback_count"),
            "graph_failure_count": overnight_quality.get("graph_failure_count"),
            "completion_status": overnight_quality.get("completion_status"),
            "completion_reasons": overnight_quality.get("completion_reasons"),
            "tradable_count": overnight_quality.get("tradable_count"),
            "ranked_count": overnight_quality.get("ranked_count"),
            "research_context_packet_count": overnight_quality.get("research_context_packet_count"),
            "research_context_blocked_count": overnight_quality.get("research_context_blocked_count"),
            "top_provider_bundle_count": overnight_quality.get("top_provider_bundle_count"),
            "top_provider_bundle_symbols": overnight_quality.get("top_provider_bundle_symbols"),
            "top_provider_bundle_gap_count": overnight_quality.get("top_provider_bundle_gap_count"),
            "top_provider_bundle_error_count": overnight_quality.get("top_provider_bundle_error_count"),
            "top_provider_bundle_missing_non_gap_needs": overnight_quality.get(
                "top_provider_bundle_missing_non_gap_needs"
            ),
            "graph_config": overnight_quality.get("graph_config"),
            "completed_at": overnight_quality.get("completed_at"),
        },
        "top_provider_bundle_summary": {
            "enabled": top_provider_bundles.get("enabled")
            if isinstance(top_provider_bundles, dict)
            else None,
            "symbols": top_provider_bundles.get("symbols", [])
            if isinstance(top_provider_bundles, dict)
            else [],
            "bundle_count": top_provider_bundles.get("bundle_count")
            if isinstance(top_provider_bundles, dict)
            else None,
            "source_packet_count": top_provider_bundles.get("source_packet_count")
            if isinstance(top_provider_bundles, dict)
            else None,
            "summary_packet_paths": top_provider_bundles.get("summary_packet_paths", {})
            if isinstance(top_provider_bundles, dict)
            else {},
            "evidence_needs_without_non_gap_packets": top_provider_bundles.get(
                "evidence_needs_without_non_gap_packets",
                [],
            )
            if isinstance(top_provider_bundles, dict)
            else [],
            "symbols_with_missing_non_gap": top_provider_bundles.get(
                "symbols_with_missing_non_gap",
                [],
            )
            if isinstance(top_provider_bundles, dict)
            else [],
            "error_count": top_provider_bundles.get("error_count")
            if isinstance(top_provider_bundles, dict)
            else None,
        },
        "research_context_summary": {
            "packet_count": research_context.get("packet_count") if isinstance(research_context, dict) else None,
            "blocked_count": len(research_context.get("blocked_packets") or [])
            if isinstance(research_context, dict)
            else None,
            "stale_warning_count": len(research_context.get("stale_warnings") or [])
            if isinstance(research_context, dict)
            else None,
            "prior_feed": research_context.get("prior_feed")
            if isinstance(research_context, dict)
            else None,
        },
        "raw_field_groups": [
            "accounts",
            "candidate_universe",
            "tradable_universe",
            "rejected_symbols",
            "ranked_candidates",
            "ticker_results",
            "research_context",
            "top_provider_bundles",
            "agent_intelligence_ledger",
            "submitted",
        ],
    }


def render_overnight_plan_markdown(packet: Mapping) -> str:
    quality = packet.get("overnight_quality") or {}
    lines = [
        "# TradingAgents Overnight Plan",
        "",
        f"- Generated at: {packet.get('generated_at', 'unknown')}",
        f"- Analysis only: {packet.get('analysis_only', True)}",
        f"- Universe size: {len(packet.get('candidate_universe') or [])}",
    ]
    if quality:
        lines.extend(
            [
                f"- Full graph analyzed: {quality.get('full_graph_count', 0)}",
                f"- Fallback scored: {quality.get('fallback_count', 0)}",
                f"- Graph failures: {quality.get('graph_failure_count', 0)}",
            ]
        )
        if "research_context_packet_count" in quality:
            lines.append(
                f"- Research context packets: {quality.get('research_context_packet_count', 0)} "
                f"(blocked {quality.get('research_context_blocked_count', 0)})"
            )
    research_context = packet.get("research_context") or {}
    if research_context:
        lines.extend(["", "## Research Context"])
        lines.append(f"- Execution authority: {research_context.get('execution_authority', 'none')}")
        provider_needs = sorted((research_context.get("provider_fallbacks") or {}).keys())
        lines.append(
            "- Provider fallback needs: "
            + (", ".join(provider_needs) if provider_needs else "none")
        )
        watchlists = sorted((research_context.get("watchlists") or {}).keys())
        lines.append(
            "- Watchlists: "
            + (", ".join(watchlists) if watchlists else "none")
        )
        blocked_count = len(research_context.get("blocked_packets") or [])
        if blocked_count:
            lines.append(f"- Blocked research-context packets: {blocked_count}")
    top_provider_bundles = packet.get("top_provider_bundles") or {}
    if isinstance(top_provider_bundles, Mapping) and top_provider_bundles.get("enabled"):
        symbols = top_provider_bundles.get("symbols") or []
        missing = top_provider_bundles.get("evidence_needs_without_non_gap_packets") or []
        lines.extend(["", "## Top Provider Bundles"])
        lines.append("- Symbols: " + (", ".join(symbols) if symbols else "none"))
        lines.append(f"- Bundle summaries: {top_provider_bundles.get('bundle_count', 0)}")
        lines.append(f"- Source packets: {top_provider_bundles.get('source_packet_count', 0)}")
        if missing:
            lines.append("- Evidence needs still missing non-gap packets: " + ", ".join(missing))
    lines.extend(["", "## Ranked Candidates"])
    ranked = packet.get("ranked_candidates") or []
    if ranked:
        for candidate in ranked:
            lines.append(
                "- "
                f"{candidate.get('symbol')}: score {candidate.get('score')}, "
                f"rating {candidate.get('rating', 'unknown')}, "
                f"status {candidate.get('status', 'unknown')}"
            )
    else:
        lines.append("- none")
    fallback_items = [
        item
        for item in packet.get("ticker_results") or []
        if isinstance(item, Mapping) and item.get("status") == "fallback"
    ]
    if fallback_items:
        lines.extend(["", "## Fallback Tickers"])
        for item in fallback_items:
            lines.append(f"- {item.get('symbol')}: {item.get('fallback_reason', 'fallback scoring used')}")
    failures = [
        item
        for item in packet.get("ticker_results") or []
        if isinstance(item, Mapping) and item.get("status") == "failed"
    ]
    if failures:
        lines.extend(["", "## Failed Tickers"])
        for item in failures:
            lines.append(f"- {item.get('symbol')}: {item.get('error', 'unknown error')}")
    return "\n".join(lines)


def load_latest_overnight_plan(
    output_dir: str | Path = "results/overnight_plans",
) -> dict | None:
    path = Path(output_dir)
    if not path.exists():
        return None
    candidates = [path / "latest.json"] if (path / "latest.json").exists() else []
    candidates.extend(
        candidate
        for candidate in path.glob("overnight-plan-*.json")
        if not candidate.name.endswith(".compact.json")
    )
    readable: list[tuple[tuple[int, float], dict]] = []
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if candidate.name != "latest.json" and payload.get("latest_alias_written") is False:
            continue
        generated_at = _parse_generated_at(payload.get("generated_at"))
        if generated_at is not None:
            sort_key = (1, generated_at.timestamp())
        else:
            try:
                sort_key = (0, candidate.stat().st_mtime)
            except OSError:
                continue
        readable.append((sort_key, payload))
    if not readable:
        return None
    readable.sort(key=lambda item: item[0], reverse=True)
    return readable[0][1]
    return None


def validate_overnight_plan_against_candidates(
    overnight_plan: Mapping | None,
    current_candidates: Sequence[CandidateSignal],
    *,
    now: datetime.datetime | None = None,
    stale_after_hours: int = 18,
    saturday_retention_hours: int = 48,
) -> dict:
    if not overnight_plan:
        return {
            "status": "stale_or_missing",
            "reason": "No overnight plan packet was found.",
        }
    generated_at = _parse_generated_at(overnight_plan.get("generated_at"))
    current_time = now or datetime.datetime.now(tz=UTC)
    if generated_at and _is_future_timestamp(generated_at, current_time):
        return {
            "status": "stale_or_missing",
            "reason": "Latest overnight plan timestamp is in the future relative to this run.",
            "generated_at": overnight_plan.get("generated_at"),
        }
    if not generated_at:
        return {
            "status": "stale_or_missing",
            "reason": "Latest overnight plan is missing a usable timestamp or is stale.",
            "generated_at": overnight_plan.get("generated_at"),
        }
    overnight_ranked = overnight_plan.get("ranked_candidates") or []
    overnight_top = _normalize_symbol(
        overnight_ranked[0].get("symbol") if overnight_ranked and isinstance(overnight_ranked[0], Mapping) else None
    )
    if not overnight_top:
        return {
            "status": "stale_or_missing",
            "reason": "Latest overnight plan has no ranked candidates.",
            "generated_at": overnight_plan.get("generated_at"),
        }
    plan_age = current_time - generated_at
    local_now = current_time.astimezone(CENTRAL)
    if plan_age > datetime.timedelta(hours=stale_after_hours):
        if local_now.weekday() == 5 and plan_age <= datetime.timedelta(hours=saturday_retention_hours):
            return {
                "status": "not_required",
                "reason": (
                    "Saturday has no regular U.S. market morning; the latest overnight plan is retained as prior context."
                ),
                "generated_at": overnight_plan.get("generated_at"),
                "overnight_top_symbol": overnight_top,
                "validation_skipped": True,
                "skip_reason": "saturday_no_regular_market_morning",
            }
        return {
            "status": "stale_or_missing",
            "reason": "Latest overnight plan is missing a usable timestamp or is stale.",
            "generated_at": overnight_plan.get("generated_at"),
        }
    current_ranked = sorted(current_candidates, key=lambda candidate: candidate.score, reverse=True)
    current_top = current_ranked[0].symbol if current_ranked else None
    current_symbols = {candidate.symbol for candidate in current_ranked}
    if overnight_top == current_top:
        status = "confirmed"
        reason = "Fresh pre-open candidate ranking still agrees with the overnight top idea."
    elif overnight_top in current_symbols:
        status = "amended"
        reason = "Fresh pre-open ranking changed the order but the overnight top idea remains viable."
    else:
        status = "invalidated"
        reason = "Fresh pre-open ranking no longer supports the overnight top idea."
    return {
        "status": status,
        "reason": reason,
        "generated_at": overnight_plan.get("generated_at"),
        "overnight_top_symbol": overnight_top,
        "current_top_symbol": current_top,
    }
