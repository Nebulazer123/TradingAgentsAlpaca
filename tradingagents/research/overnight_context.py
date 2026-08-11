"""Build analysis-only research context for overnight planning."""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingagents.dataflows._official_common import blocked_evidence_packet
from tradingagents.evals.agent_intelligence_ledger import render_agent_influence_context
from tradingagents.evals.hypothesis_factory import render_research_priors_context
from tradingagents.policy.packets import write_research_packet
from tradingagents.research.deep_research_protocol import (
    build_deep_research_protocol_packet,
)
from tradingagents.research.market_structure import (
    build_intraday_margin_market_structure_packet,
)
from tradingagents.research.methodology_cards import build_methodology_cards_packet
from tradingagents.research.mirofish_handoff import build_mirofish_source_context_packet
from tradingagents.research.provider_fallbacks import (
    DEFAULT_PROVIDER_FALLBACK_PATH,
    build_provider_fallback_packet,
)
from tradingagents.research.reddit_watchlists import (
    DEFAULT_REDDIT_WATCHLIST_PATH,
    build_reddit_watchlist_packet,
)
from tradingagents.research.release_calendar import (
    DEFAULT_RELEASE_CALENDAR_PATH,
    build_release_calendar_packet,
)
from tradingagents.research.social_watchlists import (
    DEFAULT_SOCIAL_WATCHLIST_PATH,
    build_social_watchlist_packet,
)
from tradingagents.research.source_quality import load_source_quality_strengths
from tradingagents.schemas.research import SourceEvidencePacket

DEFAULT_OVERNIGHT_EVIDENCE_NEEDS = (
    "market_news",
    "quote_price_context",
    "fundamentals_profile",
    "macro_official",
    "social_sentiment",
    "crawler_research",
)
FORBIDDEN_CONTEXT_EFFECTS = (
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
)
DEFAULT_SOURCE_QUALITY_REVIEW_PATH = Path("results/source_quality/latest.json")
DEFAULT_AGENT_INTELLIGENCE_SUMMARY_PATH = Path("results/agent_intelligence/summary.json")
DEFAULT_RESEARCH_PRIORS_PATH = Path("results/hypothesis_factory/priors.json")


@dataclass(frozen=True)
class OvernightResearchContextResult:
    packets: list[SourceEvidencePacket]
    summary: dict[str, Any]
    prior_feed: dict[str, Any] | None = None
    prior_feed_path: Path | None = None


def _safe_provider_packet(
    evidence_need: str,
    *,
    provider_config_path: str | Path,
    depleted_sources: set[str],
    disabled_sources: set[str],
    source_quality_strengths: Mapping[str, Any] | None = None,
) -> SourceEvidencePacket:
    try:
        return build_provider_fallback_packet(
            evidence_need=evidence_need,
            path=provider_config_path,
            depleted_sources=depleted_sources,
            disabled_sources=disabled_sources,
            source_quality_strengths=source_quality_strengths,
        )
    except Exception as exc:
        return blocked_evidence_packet(
            source_name="provider_fallback_policy",
            evidence_type="research_provider_fallbacks",
            subject=evidence_need,
            reason=f"{type(exc).__name__}: provider fallback policy unavailable",
            source_ref=f"local://{Path(provider_config_path).as_posix()}#{evidence_need}",
        )


def _safe_watchlist_packet(
    *,
    source_name: str,
    evidence_type: str,
    subject: str,
    path: str | Path,
    builder,
) -> SourceEvidencePacket:
    try:
        return builder(path=path)
    except Exception as exc:
        return blocked_evidence_packet(
            source_name=source_name,
            evidence_type=evidence_type,
            subject=subject,
            reason=f"{type(exc).__name__}: watchlist policy unavailable",
            source_ref=f"local://{Path(path).as_posix()}",
        )


def _safe_source_quality_packet(
    source_quality_review_path: str | Path,
    *,
    ordering_enabled: bool,
    scored_source_count: int,
    load_error: str | None = None,
) -> SourceEvidencePacket:
    path = Path(source_quality_review_path)
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(review, dict):
            raise ValueError("source-quality review is not a JSON object")
        counts = {
            "source_count": int(review.get("source_count") or 0),
            "stale_count": int(review.get("stale_count") or 0),
            "stale_downrank_count": int(review.get("stale_downrank_count") or 0),
            "stale_safe_count": int(review.get("stale_safe_count") or 0),
            "stale_needs_refresh_count": int(review.get("stale_needs_refresh_count") or 0),
            "blocked_count": int(review.get("blocked_count") or 0),
            "missing_or_invalid_count": int(review.get("missing_or_invalid_count") or 0),
            "unreadable_count": int(review.get("unreadable_count") or 0),
        }
        needs_refresh = (
            counts["stale_needs_refresh_count"]
            or counts["missing_or_invalid_count"]
            or counts["unreadable_count"]
        )
        payload = {
            "status": "available",
            "review_path": str(path),
            "source_quality_ordering_enabled": ordering_enabled,
            "scored_source_count": scored_source_count,
            "counts": counts,
            "quality_counts": dict(review.get("quality_counts") or {}),
            "freshness_counts": dict(review.get("freshness_counts") or {}),
            "next_action": "refresh_or_downrank_flagged_sources" if needs_refresh else "use_review_for_downranking",
            "can_submit_orders": False,
            "execution_authority": "none",
            "forbidden_effects": list(FORBIDDEN_CONTEXT_EFFECTS),
        }
        return SourceEvidencePacket(
            source_name="source_quality_review",
            evidence_type="research_source_quality_guardrail",
            subject="latest_research_source_quality",
            as_of=str(review.get("generated_at") or ""),
            source_refs=[f"local://{path.as_posix()}"],
            payload=payload,
            quality="medium" if not needs_refresh else "low",
            redaction_status="no_secrets_seen",
            tool_route="local_source_quality_review",
            freshness={
                **counts,
                "source_quality_ordering_enabled": ordering_enabled,
                "scored_source_count": scored_source_count,
                "needs_refresh": bool(needs_refresh),
                "load_error": load_error,
            },
        )
    except Exception as exc:
        reason = load_error or f"{type(exc).__name__}: source-quality review unavailable"
        return blocked_evidence_packet(
            source_name="source_quality_review",
            evidence_type="research_source_quality_guardrail",
            subject="latest_research_source_quality",
            reason=reason,
            source_ref=f"local://{path.as_posix()}",
        )


def _load_source_quality_strengths(
    source_quality_review_path: str | Path,
    *,
    source_quality_ordering: bool,
) -> tuple[Mapping[str, Any] | None, str | None]:
    if not source_quality_ordering:
        return None, None
    path = Path(source_quality_review_path)
    if not path.exists():
        return None, f"FileNotFoundError: source-quality review not found at {path}"
    try:
        return load_source_quality_strengths(path), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: source-quality strengths unavailable"


def _load_json_with_status(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "malformed"
    if not isinstance(loaded, dict):
        return None, "malformed"
    return loaded, "ok"


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_agent_intelligence_packet(
    *,
    agent_summary_path: str | Path = DEFAULT_AGENT_INTELLIGENCE_SUMMARY_PATH,
    research_priors_path: str | Path = DEFAULT_RESEARCH_PRIORS_PATH,
) -> SourceEvidencePacket:
    """Bridge earned agent intelligence into future research context.

    Reads the Agent Intelligence Ledger summary (resolved counts, earned
    influence weights, label-quality tiers) and the Hypothesis Factory priors
    (out-of-sample supported research priors) and emits one advisory packet.
    Missing or malformed source files degrade to explicit status fields; this
    builder never raises. Everything emitted is analysis-only.
    """

    summary_path = Path(agent_summary_path)
    priors_path = Path(research_priors_path)
    summary, summary_status = _load_json_with_status(summary_path)
    priors_packet, priors_status = _load_json_with_status(priors_path)
    influence_raw = summary.get("influence_weights") if summary else None
    influence = influence_raw if isinstance(influence_raw, Mapping) else {}
    agents_raw = influence.get("agents") if isinstance(influence.get("agents"), Mapping) else {}
    influence_weights = {
        agent: str(item.get("weight", "1.00"))
        for agent, item in agents_raw.items()
        if isinstance(item, Mapping)
    }
    influence_states = {
        agent: str(item.get("state", "unknown"))
        for agent, item in agents_raw.items()
        if isinstance(item, Mapping)
    }
    prior_rows_raw = priors_packet.get("priors") if priors_packet else None
    prior_rows = [
        row for row in (prior_rows_raw if isinstance(prior_rows_raw, list) else [])
        if isinstance(row, Mapping)
    ]
    if priors_status == "ok" and not prior_rows:
        priors_status = "no_supported_priors"
    outcome_counts = (
        dict(summary.get("outcome_counts") or {}) if summary else {}
    )
    label_quality_counts = (
        dict(summary.get("label_quality_counts") or {}) if summary else {}
    )
    resolved_forecast_count = _optional_int((summary or {}).get("resolved_forecast_count"))
    payload = {
        "status": "ok" if summary_status == "ok" else "agent_intelligence_unavailable",
        "summary_status": summary_status,
        "priors_status": priors_status,
        "source_paths": {
            "agent_summary": str(summary_path),
            "research_priors": str(priors_path),
        },
        "forecast_count": _optional_int((summary or {}).get("forecast_count")),
        "resolved_forecast_count": resolved_forecast_count,
        "pending_forecast_count": _optional_int(outcome_counts.get("pending")),
        "outcome_counts": outcome_counts,
        "label_quality_counts": label_quality_counts,
        "influence_weights": influence_weights,
        "influence_states": influence_states,
        "influence_context": render_agent_influence_context(influence),
        "research_priors": [dict(row) for row in prior_rows],
        "prior_count": len(prior_rows),
        "priors_context": render_research_priors_context(
            {**(priors_packet or {}), "priors": [dict(row) for row in prior_rows]}
        ),
        "advisory_note": (
            "Advisory only: earned influence weights and supported hypothesis "
            "priors may steer research attention; they cannot change live "
            "gates, position sizing, or order authority."
        ),
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_CONTEXT_EFFECTS),
    }
    return SourceEvidencePacket(
        source_name="agent_intelligence_ledger",
        evidence_type="agent_intelligence_advisory",
        subject="earned_agent_influence_and_research_priors",
        source_refs=[
            f"local://{summary_path.as_posix()}",
            f"local://{priors_path.as_posix()}",
        ],
        payload=payload,
        quality="medium" if summary_status == "ok" else "low",
        redaction_status="no_secrets_seen",
        tool_route="local_agent_intelligence",
        freshness={
            "summary_status": summary_status,
            "priors_status": priors_status,
            "resolved_forecast_count": resolved_forecast_count,
            "prior_count": len(prior_rows),
        },
    )


def _safe_agent_intelligence_packet(
    *,
    agent_summary_path: str | Path,
    research_priors_path: str | Path,
) -> SourceEvidencePacket:
    try:
        return build_agent_intelligence_packet(
            agent_summary_path=agent_summary_path,
            research_priors_path=research_priors_path,
        )
    except Exception as exc:
        return blocked_evidence_packet(
            source_name="agent_intelligence_ledger",
            evidence_type="agent_intelligence_advisory",
            subject="earned_agent_influence_and_research_priors",
            reason=f"{type(exc).__name__}: agent intelligence context unavailable",
            source_ref=f"local://{Path(agent_summary_path).as_posix()}",
        )


def _safe_mirofish_packet() -> SourceEvidencePacket:
    try:
        return build_mirofish_source_context_packet()
    except Exception as exc:
        return blocked_evidence_packet(
            source_name="mirofish_handoff",
            evidence_type="external_market_simulation_handoff",
            subject="mirofish_external_run_advisory_context",
            reason=f"{type(exc).__name__}: MiroFish handoff discovery unavailable",
            source_ref="local://reports/mirofish/MIROFISH_PENDING_LEARNING_SCAFFOLD.md",
        )


def build_overnight_research_context_packets(
    *,
    provider_config_path: str | Path = DEFAULT_PROVIDER_FALLBACK_PATH,
    source_quality_review_path: str | Path = DEFAULT_SOURCE_QUALITY_REVIEW_PATH,
    reddit_config_path: str | Path = DEFAULT_REDDIT_WATCHLIST_PATH,
    release_calendar_config_path: str | Path = DEFAULT_RELEASE_CALENDAR_PATH,
    social_config_path: str | Path = DEFAULT_SOCIAL_WATCHLIST_PATH,
    agent_intelligence_summary_path: str | Path = DEFAULT_AGENT_INTELLIGENCE_SUMMARY_PATH,
    research_priors_path: str | Path = DEFAULT_RESEARCH_PRIORS_PATH,
    evidence_needs: tuple[str, ...] = DEFAULT_OVERNIGHT_EVIDENCE_NEEDS,
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    source_quality_ordering: bool = True,
    include_source_quality: bool = True,
    include_reddit: bool = True,
    include_release_calendar: bool = True,
    include_social_watchlists: bool = True,
    include_methodology: bool = True,
    include_market_structure: bool = True,
    include_mirofish_handoff: bool = True,
    include_agent_intelligence: bool = True,
) -> list[SourceEvidencePacket]:
    depleted = {source.strip().lower() for source in depleted_sources or set() if source.strip()}
    disabled = {source.strip().lower() for source in disabled_sources or set() if source.strip()}
    source_quality_strengths, source_quality_error = _load_source_quality_strengths(
        source_quality_review_path,
        source_quality_ordering=source_quality_ordering,
    )
    packets: list[SourceEvidencePacket] = [
        _safe_provider_packet(
            evidence_need,
            provider_config_path=provider_config_path,
            depleted_sources=depleted,
            disabled_sources=disabled,
            source_quality_strengths=source_quality_strengths,
        )
        for evidence_need in evidence_needs
    ]
    if include_source_quality:
        packets.append(
            _safe_source_quality_packet(
                source_quality_review_path,
                ordering_enabled=source_quality_strengths is not None,
                scored_source_count=len(source_quality_strengths or {}),
                load_error=source_quality_error,
            )
        )
    if include_reddit:
        packets.append(
            _safe_watchlist_packet(
                source_name="reddit_watchlist",
                evidence_type="market_sentiment_watchlist",
                subject="reddit_recent_market_sentiment",
                path=reddit_config_path,
                builder=build_reddit_watchlist_packet,
            )
        )
    if include_release_calendar:
        packets.append(
            _safe_watchlist_packet(
                source_name="official_release_calendar",
                evidence_type="macro_release_calendar",
                subject="official_macro_event_risk",
                path=release_calendar_config_path,
                builder=build_release_calendar_packet,
            )
        )
    if include_market_structure:
        packets.append(build_intraday_margin_market_structure_packet())
    if include_mirofish_handoff:
        packets.append(_safe_mirofish_packet())
    if include_agent_intelligence:
        packets.append(
            _safe_agent_intelligence_packet(
                agent_summary_path=agent_intelligence_summary_path,
                research_priors_path=research_priors_path,
            )
        )
    if include_social_watchlists:
        packets.append(
            _safe_watchlist_packet(
                source_name="social_watchlist",
                evidence_type="attention_targets",
                subject="operator_social_watchlists",
                path=social_config_path,
                builder=build_social_watchlist_packet,
            )
        )
    if include_methodology:
        packets.append(build_methodology_cards_packet())
        packets.append(build_deep_research_protocol_packet())
    return packets


def _packet_ref(packet: SourceEvidencePacket, path: Path | None = None) -> dict[str, Any]:
    return {
        "packet_id": packet.packet_id,
        "source_name": packet.source_name,
        "evidence_type": packet.evidence_type,
        "subject": packet.subject,
        "quality": packet.quality,
        "redaction_status": packet.redaction_status,
        "analysis_only": packet.analysis_only,
        "path": str(path) if path else None,
    }


def summarize_overnight_research_context(
    packets: list[SourceEvidencePacket],
    *,
    packet_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    provider_fallbacks: dict[str, Any] = {}
    watchlists: dict[str, Any] = {}
    blocked_packets: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    methodology: dict[str, Any] = {}
    mirofish_handoff: dict[str, Any] = {}
    agent_intelligence: dict[str, Any] = {}
    paths = packet_paths or {}
    for packet in packets:
        refs.append(_packet_ref(packet, paths.get(packet.packet_id)))
        if packet.redaction_status == "blocked" or packet.payload.get("status") == "blocked":
            blocked_packets.append(_packet_ref(packet, paths.get(packet.packet_id)))
        if packet.source_name == "provider_fallback_policy":
            active_routes = packet.payload.get("active_routes", [])
            provider_fallbacks[packet.subject] = {
                "active_source_names": packet.payload.get("active_source_names", []),
                "limited_sources_active": packet.payload.get("limited_sources_active", []),
                "source_quality_ordering_enabled": any(
                    isinstance(route, dict) and route.get("source_quality_score") is not None
                    for route in active_routes
                ),
                "scored_active_source_count": sum(
                    1
                    for route in active_routes
                    if isinstance(route, dict) and route.get("source_quality_score") is not None
                ),
                "skipped_source_names": [
                    item.get("source_name")
                    for item in packet.payload.get("skipped_routes", [])
                    if isinstance(item, dict)
                ],
                "preferred_free_or_mcp_count": len(
                    packet.payload.get("preferred_free_or_mcp_routes", [])
                ),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "source_quality_review":
            counts = packet.payload.get("counts") if isinstance(packet.payload.get("counts"), dict) else {}
            watchlists["source_quality"] = {
                "status": packet.payload.get("status"),
                "review_path": packet.payload.get("review_path"),
                "source_quality_ordering_enabled": packet.payload.get("source_quality_ordering_enabled"),
                "scored_source_count": packet.payload.get("scored_source_count"),
                "source_count": counts.get("source_count"),
                "stale_count": counts.get("stale_count"),
                "stale_downrank_count": counts.get("stale_downrank_count"),
                "stale_needs_refresh_count": counts.get("stale_needs_refresh_count"),
                "blocked_count": counts.get("blocked_count"),
                "missing_or_invalid_count": counts.get("missing_or_invalid_count"),
                "unreadable_count": counts.get("unreadable_count"),
                "next_action": packet.payload.get("next_action"),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "reddit_watchlist":
            watchlists["reddit"] = {
                "target_count": packet.freshness.get("target_count"),
                "required_buckets": packet.payload.get("required_buckets", []),
                "allowed_context_flags": packet.payload.get("allowed_context_flags", []),
                "raw_comment_threads_by_default": (
                    packet.payload.get("policy", {}).get("raw_comment_threads_by_default")
                ),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "official_release_calendar":
            watchlists["release_calendar"] = {
                "event_risk_state": packet.payload.get("event_risk_state"),
                "upcoming_event_count": len(packet.payload.get("upcoming_events") or []),
                "active_event_window_count": len(
                    packet.payload.get("active_event_windows") or []
                ),
                "high_impact_count": packet.payload.get("high_impact_count", 0),
                "planner_flags": packet.payload.get("planner_flags", {}),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "market_structure_policy":
            watchlists["market_structure"] = {
                "evidence_type": packet.evidence_type,
                "subject": packet.subject,
                "regulatory_status": packet.payload.get("regulatory_status"),
                "reform_active_for_account": packet.payload.get(
                    "reform_active_for_account"
                ),
                "adoption_evidence_source": packet.payload.get(
                    "adoption_evidence_source"
                ),
                "adoption_evidence_as_of": packet.payload.get(
                    "adoption_evidence_as_of"
                ),
                "effective_date": packet.payload.get("effective_date"),
                "planner_flags": packet.payload.get("planner_flags", {}),
                "rule_interpretation": packet.payload.get("rule_interpretation", {}),
                "source_urls": packet.payload.get("source_urls", []),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "mirofish_handoff":
            mirofish_handoff = {
                "status": packet.payload.get("status"),
                "final_handoff_available": packet.payload.get("final_handoff_available"),
                "final_handoff_paths": packet.payload.get("final_handoff_paths", []),
                "advisory_valid_window": packet.payload.get("advisory_valid_window"),
                "advisory_expires_after": packet.payload.get("advisory_expires_after"),
                "advisory_requires_refresh": packet.payload.get("advisory_requires_refresh", [])[:6],
                "available_artifact_count": packet.freshness.get("available_artifact_count"),
                "candidate_artifact_count": packet.freshness.get("candidate_artifact_count"),
                "available_artifacts": packet.freshness.get("available_artifacts", [])[:20],
                "source_artifacts": packet.payload.get("source_artifacts", {}),
                "review_packet_zip": packet.payload.get("review_packet_zip"),
                "acceptance_decision_path": packet.payload.get("acceptance_decision_path"),
                "full_report_highlights": packet.payload.get("full_report_highlights", {}),
                "full_report_core_filter": packet.freshness.get("full_report_core_filter"),
                "mirofish_advisory_gate_action": packet.freshness.get("mirofish_advisory_gate_action"),
                "mirofish_advisory_triggered_gates": packet.freshness.get(
                    "mirofish_advisory_triggered_gates",
                    [],
                ),
                "deep_research_review": packet.payload.get("deep_research_review", {}),
                "deep_research_review_available": packet.freshness.get(
                    "deep_research_review_available",
                    False,
                ),
                "deep_research_review_report_id": packet.freshness.get("deep_research_review_report_id"),
                "deep_research_review_source_path": packet.freshness.get(
                    "deep_research_review_source_path"
                ),
                "deep_research_review_core_filter": packet.freshness.get(
                    "deep_research_review_core_filter"
                ),
                "deep_research_review_market_regime": packet.freshness.get(
                    "deep_research_review_market_regime",
                    {},
                ),
                "deep_research_review_stock_selection_biases": packet.freshness.get(
                    "deep_research_review_stock_selection_biases",
                    {},
                ),
                "deep_research_review_selection_rules": packet.freshness.get(
                    "deep_research_review_selection_rules",
                    [],
                )[:8],
                "deep_research_review_risk_controls": packet.freshness.get(
                    "deep_research_review_risk_controls",
                    [],
                )[:8],
                "final_advisory_available": packet.freshness.get("final_advisory_available"),
                "scenario_branch_count": packet.freshness.get("scenario_branch_count", 0),
                "validation_task_count": packet.freshness.get("validation_task_count", 0),
                "false_signal_filter_count": packet.freshness.get("false_signal_filter_count", 0),
                "ticker_attention_count": packet.freshness.get("ticker_attention_count", 0),
                "category_attention_count": packet.freshness.get("category_attention_count", 0),
                "retail_flow_hypothesis_count": packet.freshness.get("retail_flow_hypothesis_count", 0),
                "attention_symbols": packet.freshness.get("attention_symbols", []),
                "forecast_symbols": packet.freshness.get("forecast_symbols", []),
                "ticker_attention_symbols": packet.payload.get("ticker_attention_symbols", []),
                "ticker_attention_map": packet.payload.get("ticker_attention_map", {}),
                "category_attention_map": packet.payload.get("category_attention_map", {}),
                "retail_flow_hypotheses": packet.payload.get("retail_flow_hypotheses", [])[:6],
                "validation_tasks": packet.payload.get("validation_tasks", [])[:6],
                "false_signal_filters": packet.payload.get("false_signal_filters", [])[:6],
                "execution_authority": packet.payload.get("execution_authority"),
                "forbidden_effects": packet.payload.get("forbidden_effects", []),
                "morning_bot_instruction": packet.payload.get("morning_bot_instruction"),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "agent_intelligence_ledger":
            agent_intelligence = {
                "status": packet.payload.get("status"),
                "summary_status": packet.payload.get("summary_status"),
                "priors_status": packet.payload.get("priors_status"),
                "source_paths": packet.payload.get("source_paths", {}),
                "forecast_count": packet.payload.get("forecast_count"),
                "resolved_forecast_count": packet.payload.get("resolved_forecast_count"),
                "pending_forecast_count": packet.payload.get("pending_forecast_count"),
                "outcome_counts": packet.payload.get("outcome_counts", {}),
                "label_quality_counts": packet.payload.get("label_quality_counts", {}),
                "influence_weights": packet.payload.get("influence_weights", {}),
                "influence_states": packet.payload.get("influence_states", {}),
                "influence_context": packet.payload.get("influence_context"),
                "prior_count": packet.payload.get("prior_count", 0),
                "research_priors": packet.payload.get("research_priors", []),
                "priors_context": packet.payload.get("priors_context"),
                "execution_authority": packet.payload.get("execution_authority"),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "social_watchlist":
            watchlists["social"] = {
                "target_count": packet.freshness.get("target_count"),
                "counts_by_platform": packet.payload.get("counts_by_platform", {}),
                "dynamic_suggestion_groups": sorted(
                    (packet.payload.get("dynamic_research_suggestions") or {}).keys()
                ),
                "blocked": packet.redaction_status == "blocked",
            }
        elif packet.source_name == "strategy_methodology_cards":
            methodology["strategy_card_count"] = len(packet.payload.get("cards") or [])
            methodology["default_build_order"] = packet.payload.get("default_build_order", [])
            methodology["execution_authority"] = packet.payload.get("execution_authority")
            methodology["forbidden_effects"] = packet.payload.get("forbidden_effects", [])
            methodology["blocked"] = packet.redaction_status == "blocked"
        elif packet.source_name == "chatgpt_deep_research_protocol":
            methodology["deep_research"] = {
                "primary_route": packet.payload.get("primary_route", {}).get("name"),
                "use_cases": [
                    item.get("use_case")
                    for item in packet.payload.get("use_cases", [])
                    if isinstance(item, dict)
                ],
                "execution_authority": packet.payload.get("execution_authority"),
                "forbidden_effects": packet.payload.get("forbidden_effects", []),
                "backup_routes": packet.payload.get("backup_routes", []),
                "blocked": packet.redaction_status == "blocked",
            }
    return {
        "analysis_only": True,
        "source_role": "advisory overnight research context",
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_CONTEXT_EFFECTS),
        "packet_count": len(packets),
        "packet_refs": refs,
        "provider_fallbacks": provider_fallbacks,
        "watchlists": watchlists,
        "mirofish_handoff": mirofish_handoff,
        "agent_intelligence": agent_intelligence,
        "methodology": methodology,
        "blocked_packets": blocked_packets,
    }


def build_overnight_prior_feed(summary: dict[str, Any]) -> dict[str, Any]:
    """Build a compact, analysis-only prior feed for automation/n8n readers."""

    provider_fallbacks = summary.get("provider_fallbacks") or {}
    watchlists = summary.get("watchlists") or {}
    mirofish = summary.get("mirofish_handoff") or {}
    agent_intelligence = summary.get("agent_intelligence") or {}
    methodology = summary.get("methodology") or {}
    raw_packet_refs = summary.get("packet_refs") or []
    if isinstance(raw_packet_refs, Sequence) and not isinstance(raw_packet_refs, (str, bytes)):
        packet_ref_values = [str(item).strip() for item in raw_packet_refs if str(item).strip()]
    else:
        packet_ref_values = [str(raw_packet_refs).strip()] if str(raw_packet_refs).strip() else []
    packet_refs = list(dict.fromkeys(packet_ref_values))
    input_packet_ref_count = len(packet_ref_values)
    duplicate_packet_ref_count = input_packet_ref_count - len(packet_refs)
    carry_forward_scope = []
    if packet_refs:
        carry_forward_scope.append("source_packet_refs")
    if provider_fallbacks:
        carry_forward_scope.append("provider_fallbacks")
    if watchlists:
        carry_forward_scope.append("watchlists")
    if mirofish:
        carry_forward_scope.append("mirofish")
    if agent_intelligence:
        carry_forward_scope.append("agent_intelligence")
    if methodology:
        carry_forward_scope.append("methodology")
    return {
        "schema": "overnight_prior_feed_v1",
        "analysis_only": True,
        "source_role": "compact advisory priors for overnight research",
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_CONTEXT_EFFECTS),
        "packet_count": summary.get("packet_count", 0),
        "blocked_count": len(summary.get("blocked_packets") or []),
        "packet_refs": packet_refs,
        "prior_applied": bool(carry_forward_scope),
        "dedupe_applied": True,
        "input_packet_ref_count": input_packet_ref_count,
        "unique_packet_ref_count": len(packet_refs),
        "duplicate_packet_ref_count": duplicate_packet_ref_count,
        "carry_forward_scope": carry_forward_scope,
        "provider_needs": {
            need: {
                "active_source_names": details.get("active_source_names", []),
                "limited_sources_active": details.get("limited_sources_active", []),
                "skipped_source_names": details.get("skipped_source_names", []),
                "preferred_free_or_mcp_count": details.get("preferred_free_or_mcp_count", 0),
                "blocked": details.get("blocked", False),
            }
            for need, details in provider_fallbacks.items()
            if isinstance(details, dict)
        },
        "watchlists": {
            "available": sorted(watchlists.keys()),
            "source_quality": watchlists.get("source_quality", {}),
            "reddit": watchlists.get("reddit", {}),
            "social": watchlists.get("social", {}),
            "market_structure": watchlists.get("market_structure", {}),
            "release_calendar": watchlists.get("release_calendar", {}),
        },
        "mirofish": {
            "status": mirofish.get("status"),
            "final_advisory_available": mirofish.get("final_advisory_available"),
            "advisory_valid_window": mirofish.get("advisory_valid_window"),
            "advisory_expires_after": mirofish.get("advisory_expires_after"),
            "attention_symbols": mirofish.get("attention_symbols", []),
            "ticker_attention_symbols": mirofish.get("ticker_attention_symbols", []),
            "validation_task_count": mirofish.get("validation_task_count", 0),
            "false_signal_filter_count": mirofish.get("false_signal_filter_count", 0),
            "retail_flow_hypothesis_count": mirofish.get("retail_flow_hypothesis_count", 0),
            "full_report_core_filter": mirofish.get("full_report_core_filter"),
            "deep_research_review_available": mirofish.get("deep_research_review_available", False),
            "deep_research_review_core_filter": mirofish.get("deep_research_review_core_filter"),
            "deep_research_review_stock_selection_biases": mirofish.get(
                "deep_research_review_stock_selection_biases",
                {},
            ),
            "deep_research_review_selection_rules": mirofish.get(
                "deep_research_review_selection_rules",
                [],
            ),
            "deep_research_review_risk_controls": mirofish.get(
                "deep_research_review_risk_controls",
                [],
            ),
            "mirofish_advisory_gate_action": mirofish.get("mirofish_advisory_gate_action"),
            "blocked": mirofish.get("blocked", False),
        },
        "agent_intelligence": {
            "status": agent_intelligence.get("status"),
            "summary_status": agent_intelligence.get("summary_status"),
            "priors_status": agent_intelligence.get("priors_status"),
            "resolved_forecast_count": agent_intelligence.get("resolved_forecast_count"),
            "pending_forecast_count": agent_intelligence.get("pending_forecast_count"),
            "outcome_counts": agent_intelligence.get("outcome_counts", {}),
            "label_quality_counts": agent_intelligence.get("label_quality_counts", {}),
            "influence_weights": agent_intelligence.get("influence_weights", {}),
            "prior_count": agent_intelligence.get("prior_count", 0),
            "research_priors": (agent_intelligence.get("research_priors") or [])[:8],
            "blocked": agent_intelligence.get("blocked", False),
        },
        "methodology": {
            "strategy_card_count": methodology.get("strategy_card_count", 0),
            "default_build_order": methodology.get("default_build_order", []),
            "deep_research": methodology.get("deep_research", {}),
        },
    }


def write_overnight_prior_feed(
    prior_feed: dict[str, Any],
    *,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = root / f"overnight-prior-feed-{stamp}.json"
    latest_path = root / "overnight-prior-feed-latest.json"
    payload = dict(prior_feed)
    payload["path"] = str(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_overnight_research_context(
    *,
    output_dir: str | Path,
    provider_config_path: str | Path = DEFAULT_PROVIDER_FALLBACK_PATH,
    source_quality_review_path: str | Path = DEFAULT_SOURCE_QUALITY_REVIEW_PATH,
    reddit_config_path: str | Path = DEFAULT_REDDIT_WATCHLIST_PATH,
    release_calendar_config_path: str | Path = DEFAULT_RELEASE_CALENDAR_PATH,
    social_config_path: str | Path = DEFAULT_SOCIAL_WATCHLIST_PATH,
    agent_intelligence_summary_path: str | Path = DEFAULT_AGENT_INTELLIGENCE_SUMMARY_PATH,
    research_priors_path: str | Path = DEFAULT_RESEARCH_PRIORS_PATH,
    evidence_needs: tuple[str, ...] = DEFAULT_OVERNIGHT_EVIDENCE_NEEDS,
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    source_quality_ordering: bool = True,
    include_source_quality: bool = True,
    include_reddit: bool = True,
    include_release_calendar: bool = True,
    include_social_watchlists: bool = True,
    include_methodology: bool = True,
    include_market_structure: bool = True,
    include_mirofish_handoff: bool = True,
    include_agent_intelligence: bool = True,
) -> OvernightResearchContextResult:
    packets = build_overnight_research_context_packets(
        provider_config_path=provider_config_path,
        source_quality_review_path=source_quality_review_path,
        reddit_config_path=reddit_config_path,
        release_calendar_config_path=release_calendar_config_path,
        social_config_path=social_config_path,
        agent_intelligence_summary_path=agent_intelligence_summary_path,
        research_priors_path=research_priors_path,
        evidence_needs=evidence_needs,
        depleted_sources=depleted_sources,
        disabled_sources=disabled_sources,
        source_quality_ordering=source_quality_ordering,
        include_source_quality=include_source_quality,
        include_reddit=include_reddit,
        include_release_calendar=include_release_calendar,
        include_social_watchlists=include_social_watchlists,
        include_methodology=include_methodology,
        include_market_structure=include_market_structure,
        include_mirofish_handoff=include_mirofish_handoff,
        include_agent_intelligence=include_agent_intelligence,
    )
    packet_paths = {
        packet.packet_id: write_research_packet(packet, output_dir)
        for packet in packets
    }
    summary = summarize_overnight_research_context(
        packets,
        packet_paths=packet_paths,
    )
    prior_feed = build_overnight_prior_feed(summary)
    prior_feed_path = write_overnight_prior_feed(prior_feed, output_dir=output_dir)
    summary["prior_feed"] = {
        "schema": prior_feed["schema"],
        "path": str(prior_feed_path),
        "latest_path": str(Path(output_dir) / "overnight-prior-feed-latest.json"),
        "packet_count": prior_feed["packet_count"],
        "blocked_count": prior_feed["blocked_count"],
        "prior_applied": prior_feed["prior_applied"],
        "dedupe_applied": prior_feed["dedupe_applied"],
        "input_packet_ref_count": prior_feed["input_packet_ref_count"],
        "unique_packet_ref_count": prior_feed["unique_packet_ref_count"],
        "duplicate_packet_ref_count": prior_feed["duplicate_packet_ref_count"],
        "carry_forward_scope": list(prior_feed["carry_forward_scope"]),
        "analysis_only": prior_feed["analysis_only"],
        "execution_authority": "none",
        "forbidden_effects": list(prior_feed["forbidden_effects"]),
    }
    return OvernightResearchContextResult(
        packets=packets,
        summary=summary,
        prior_feed=prior_feed,
        prior_feed_path=prior_feed_path,
    )
