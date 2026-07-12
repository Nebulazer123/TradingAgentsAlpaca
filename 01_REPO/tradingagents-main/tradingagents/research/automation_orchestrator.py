"""Research automation orchestration packets.

This module coordinates advisory research lanes. It does not execute trades,
grant cloud-app write access, or bypass any broker/live gate.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from tradingagents.evals.replay_ablation import build_replay_ablation_plan_packet
from tradingagents.policy.packets import write_research_packet
from tradingagents.research.knowledge_graph import GraphMemoryStore
from tradingagents.research.market_mirror import build_market_mirror_panel
from tradingagents.research.model_routing import (
    ModelRoute,
    select_parallel_research_model_routes,
)
from tradingagents.research.model_telemetry import model_route_telemetry_packet
from tradingagents.research.overnight_context import (
    OvernightResearchContextResult,
    write_overnight_research_context,
)
from tradingagents.schemas.research import ModelRunTelemetryPacket, ResearchBatchRunPacket

UTC = datetime.timezone.utc


LANE_LABELS = {
    "deterministic_helpers": "Deterministic helpers",
    "windows_local": "Windows local model",
    "mac_ollama": "Mac local model",
    "intelligent_judgment": "ChatGPT/Codex or capped paid judge",
}
LANE_JOBS = {
    "deterministic_helpers": (
        "collect compact source packets",
        "check fallback/source policy",
        "validate schemas and safety fields",
    ),
    "windows_local": (
        "summarize broad source overlap",
        "draft quick ticker context",
        "flag contradictions for review",
    ),
    "mac_ollama": (
        "triage stale source packets",
        "hunt thesis contradictions",
        "compress overnight report drafts",
    ),
    "intelligent_judgment": (
        "grade research quality",
        "resolve contradictions",
        "write Codex-ready self-improvement handoffs",
    ),
}


@dataclass(frozen=True)
class ResearchAutomationOrchestrationResult:
    batch_packet: ResearchBatchRunPacket
    batch_packet_path: Path
    model_telemetry_packets: list[ModelRunTelemetryPacket]
    model_telemetry_paths: dict[str, Path]
    research_context_summary: dict[str, Any] | None = None
    replay_plan_packet: ResearchBatchRunPacket | None = None
    replay_plan_path: Path | None = None


def _now_id() -> str:
    return datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")


def _symbols(values: Sequence[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        pieces = values.replace(";", ",").split(",")
    else:
        pieces = list(values)
    return sorted({piece.strip().upper() for piece in pieces if piece and piece.strip()})


def _source_refs_from_context(context_summary: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for ref in (context_summary or {}).get("packet_refs") or []:
        if not isinstance(ref, dict):
            continue
        packet_id = str(ref.get("packet_id") or "").strip()
        if packet_id:
            refs.append(packet_id)
    return refs


def _hash_payload(payload: Mapping[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _route_lane(name: str, route: ModelRoute) -> dict[str, Any]:
    payload = cast(dict[str, Any], route.model_dump())
    payload.update(
        {
            "lane": name,
            "label": LANE_LABELS.get(name, name.replace("_", " ").title()),
            "jobs": list(LANE_JOBS.get(name, route.preferred_tasks)),
            "quality_role": (
                "must_pass"
                if name == "deterministic_helpers"
                else "preferred"
                if name in {"windows_local", "mac_ollama"}
                else "judge"
            ),
            "plain_english": _plain_route_explanation(name, route),
        }
    )
    return payload


def _plain_route_explanation(name: str, route: ModelRoute) -> str:
    if route.status == "selected":
        if name == "deterministic_helpers":
            return "This lane does the simple, reliable checklist work without spending model tokens."
        if name == "windows_local":
            return "This lane uses the Windows local model for quick research drafts."
        if name == "mac_ollama":
            return "This lane uses the 32 GB Mac DeepSeek model for cheap offloaded helper work."
        if name == "intelligent_judgment":
            return "This lane uses the best available judge route for final research quality checks."
    if route.status == "external":
        return "This lane stays with Codex/ChatGPT in the current thread unless a capped API route is armed."
    return f"This lane is not ready yet: {route.reason}"


def _quality_gates(
    *,
    routes: Mapping[str, ModelRoute],
    context_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    selected_local = [
        name
        for name in ("windows_local", "mac_ollama")
        if routes.get(name) and routes[name].status == "selected"
    ]
    packet_refs = _source_refs_from_context(context_summary)
    blocked_packets = (context_summary or {}).get("blocked_packets") or []
    deterministic_ok = routes["deterministic_helpers"].status == "selected"
    judgment = routes["intelligent_judgment"]
    judgment_ok = judgment.status in {"selected", "external"}
    degraded_helpers = [
        name
        for name in ("windows_local", "mac_ollama")
        if routes.get(name) and routes[name].status != "selected"
    ]
    local_ok = bool(selected_local)
    source_breadth_ok = len(packet_refs) >= 3
    blocked_packet_ok = len(blocked_packets) == 0
    route_plan_runnable = deterministic_ok and judgment_ok
    high_quality = route_plan_runnable and (local_ok or source_breadth_ok) and source_breadth_ok and blocked_packet_ok
    return {
        "deterministic_helpers_ready": deterministic_ok,
        "at_least_one_local_worker_ready": local_ok,
        "selected_local_workers": selected_local,
        "optional_helper_degraded": bool(degraded_helpers),
        "degraded_helper_lanes": degraded_helpers,
        "judgment_route_ready": judgment_ok,
        "route_plan_runnable": route_plan_runnable,
        "source_breadth_ready": source_breadth_ok,
        "source_packet_count": len(packet_refs),
        "blocked_source_packet_count": len(blocked_packets),
        "research_quality_high_enough": high_quality,
        "fallback_required": not high_quality,
        "fallback_rule": (
            "If quality is not high enough, keep the run analysis-only, use deterministic packets, "
            "request more research, and do not let the supervisor treat the packet as fresh trade truth."
        ),
    }


def _fallback_actions(routes: Mapping[str, ModelRoute], quality_gates: Mapping[str, Any]) -> list[str]:
    actions: list[str] = []
    if routes["windows_local"].status != "selected":
        actions.append("skip Windows local model lane and use deterministic summaries")
    if routes["mac_ollama"].status != "selected":
        actions.append("skip Mac DeepSeek helper lane until the Ollama tags endpoint is configured")
    if routes["intelligent_judgment"].status == "blocked":
        actions.append("skip paid judgment model and keep Codex/ChatGPT review out-of-band")
    if quality_gates.get("fallback_required"):
        actions.append("mark research as needs_revision before supervisor consumption")
    return actions


def build_research_automation_orchestration(
    *,
    candidate_symbols: Sequence[str] | str | None = None,
    env: Mapping[str, str] | None = None,
    route_health: Mapping[str, Mapping[str, Any]] | None = None,
    batch_id: str | None = None,
    estimated_judgment_cost_usd: Decimal | str = Decimal("0"),
    include_research_context: bool = True,
    research_context_dir: str | Path = "results/research_evidence/orchestration_context",
    model_telemetry_dir: str | Path = "results/model_telemetry",
    batch_output_dir: str | Path = "results/research_batches",
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    include_replay_plan: bool = True,
    replay_sleeve: str = "pullback-support",
    include_market_mirror: bool = True,
    market_mirror_dir: str | Path | None = None,
    graph_memory_path: str | Path | None = None,
) -> ResearchAutomationOrchestrationResult:
    active_env = os.environ if env is None else env
    run_id = batch_id or f"research-orchestration-{_now_id()}"
    cost = Decimal(str(estimated_judgment_cost_usd or "0"))
    context_result: OvernightResearchContextResult | None = None
    if include_research_context:
        context_result = write_overnight_research_context(
            output_dir=research_context_dir,
            depleted_sources=depleted_sources,
            disabled_sources=disabled_sources,
        )
    context_summary = context_result.summary if context_result else None
    symbols = _symbols(candidate_symbols)
    routes = select_parallel_research_model_routes(
        env=active_env,
        estimated_judgment_cost_usd=cost,
        route_health=route_health,
    )
    model_packets = [
        model_route_telemetry_packet(
            run_id=f"{run_id}-{lane_name}",
            route=route,
            error_summary=None if route.status in {"selected", "external"} else route.reason,
        )
        for lane_name, route in routes.items()
    ]
    model_paths = {
        packet.run_id: write_research_packet(packet, model_telemetry_dir)
        for packet in model_packets
    }
    replay_plan_packet = None
    replay_plan_path = None
    if include_replay_plan:
        replay_plan_packet = build_replay_ablation_plan_packet(
            candidate_symbols=symbols,
            sleeve=replay_sleeve,
        )
        replay_plan_path = write_research_packet(replay_plan_packet, batch_output_dir)
    batch_dir = Path(batch_output_dir)
    graph_dir = batch_dir / "graph_memory"
    graph_path = Path(graph_memory_path or graph_dir / "graph_memory.jsonl")
    graph_store = GraphMemoryStore(graph_path)
    graph_packet_refs: list[str] = []
    for symbol in symbols[:5]:
        node = graph_store.upsert_node(
            node_type="symbol",
            label=symbol,
            properties={
                "batch_id": run_id,
                "source": "research_automation_orchestrator",
                "stage": "candidate_universe",
            },
        )
        query = graph_store.query_symbol_context(symbol)
        write_research_packet(node, graph_dir)
        write_research_packet(query, graph_dir)
        graph_packet_refs.extend([node.packet_id, query.packet_id])
    mirror_packet_refs: list[str] = []
    if include_market_mirror and symbols:
        mirror_output_dir = Path(market_mirror_dir or batch_dir / "market_mirror")
        mirror_result = build_market_mirror_panel(
            symbol=symbols[0],
            evidence_refs=_source_refs_from_context(context_summary)[:8],
            rounds=2,
            max_actors=5,
        )
        for packet in mirror_result.packets:
            write_research_packet(packet, mirror_output_dir)
            mirror_packet_refs.append(packet.packet_id)
    gates = _quality_gates(routes=routes, context_summary=context_summary)
    blockers = []
    for lane_name, route in routes.items():
        if route.status != "blocked":
            continue
        if lane_name in {"windows_local", "mac_ollama"}:
            continue
        blockers.append(f"{lane_name}: {route.reason}")
    if gates.get("blocked_source_packet_count"):
        blockers.append("one or more research context packets were blocked")
    status: Literal["success", "partial", "blocked", "failed"] = (
        "success"
        if gates["research_quality_high_enough"]
        else "partial"
        if gates.get("route_plan_runnable")
        else "blocked"
    )
    if not gates["deterministic_helpers_ready"]:
        status = "blocked"
    batch_packet = ResearchBatchRunPacket(
        batch_id=run_id,
        status=status,
        candidate_symbols=symbols,
        orchestration_lanes=[
            _route_lane(lane_name, route)
            for lane_name, route in routes.items()
        ],
        quality_gates=gates,
        fallback_actions=_fallback_actions(routes, gates),
        input_hashes={
            "candidate_symbols": _hash_payload({"candidate_symbols": symbols}),
            "research_context": _hash_payload(context_summary or {}),
            "model_routes": _hash_payload({name: route.model_dump() for name, route in routes.items()}),
            "cache_key": _hash_payload(
                {
                    "candidate_symbols": symbols,
                    "context_refs": _source_refs_from_context(context_summary),
                    "estimated_judgment_cost_usd": str(cost),
                    "replay_sleeve": replay_sleeve,
                    "include_market_mirror": include_market_mirror,
                }
            ),
        },
        freshness={
            "input_stages": [
                "candidate_universe",
                "official_evidence_fetch",
                "crawler_public_evidence_fetch",
                "social_anomaly_fetch",
                "feature_packet",
                "graph_memory_query",
                "optional_market_mirror",
                "optional_llm_or_gemini_summary",
                "replay_ablation_plan",
            ],
            "cache_policy": "reuse prior model/crawler/mirror packets only when source and thesis hashes match; otherwise refresh",
            "toolful_research_boundary": "Codex/Composio/Browser/Crawlee fetch evidence; local/Gemini see sanitized packets only and cannot access broker/connectors.",
            "market_mirror_analysis_only": True,
            "route_health_probe": dict(route_health or {}),
        },
        source_packet_refs=_source_refs_from_context(context_summary),
        social_packet_refs=[
            ref["packet_id"]
            for ref in (context_summary or {}).get("packet_refs") or []
            if isinstance(ref, dict)
            and str(ref.get("source_name") or "") in {"reddit_watchlist", "social_watchlist"}
            and str(ref.get("packet_id") or "").strip()
        ],
        model_telemetry_refs=[packet.packet_id for packet in model_packets],
        mirror_packet_refs=mirror_packet_refs,
        graph_memory_refs=graph_packet_refs,
        output_packet_refs=(
            [replay_plan_packet.packet_id]
            if replay_plan_packet is not None
            else []
        ),
        blockers=blockers,
        execution_authority="none",
        tool_route="research_automation_orchestrator",
        redaction_status="redacted",
    )
    batch_path = write_research_packet(batch_packet, batch_output_dir)
    return ResearchAutomationOrchestrationResult(
        batch_packet=batch_packet,
        batch_packet_path=batch_path,
        model_telemetry_packets=model_packets,
        model_telemetry_paths=model_paths,
        research_context_summary=context_summary,
        replay_plan_packet=replay_plan_packet,
        replay_plan_path=replay_plan_path,
    )
