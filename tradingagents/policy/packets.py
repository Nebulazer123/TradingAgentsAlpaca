"""Shadow packet writing for deterministic policy development."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tradingagents.schemas import research as research_schemas
from tradingagents.schemas.trading import RunPacket

_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS: tuple[float, ...] = (
    0.05,
    0.1,
    0.2,
    0.5,
    1.0,
)

RESEARCH_PACKET_ROUTES: tuple[tuple[type[research_schemas.ResearchPacketBase], str, str], ...] = (
    (research_schemas.SourceEvidencePacket, "results/research_evidence", "source-evidence"),
    (research_schemas.ResearchIntelligencePacket, "results/research_evidence", "research-intel"),
    (research_schemas.MarketActorProfile, "results/research_simulations", "market-actor"),
    (research_schemas.MarketMirrorScenarioPacket, "results/research_simulations", "market-mirror"),
    (research_schemas.ModelRunTelemetryPacket, "results/model_telemetry", "model-telemetry"),
    (research_schemas.CrawlerRunPacket, "results/crawler_runs", "crawler-run"),
    (research_schemas.KnowledgeGraphNodePacket, "results/research_memory", "kg-node"),
    (research_schemas.KnowledgeGraphEdgePacket, "results/research_memory", "kg-edge"),
    (research_schemas.GraphMemoryQueryPacket, "results/research_memory", "graph-query"),
    (research_schemas.SocialAnomalyPacket, "results/research_evidence", "social-anomaly"),
    (research_schemas.PromptRegistryPacket, "results/prompt_registry", "prompt-registry"),
    (research_schemas.ResearchBatchRunPacket, "results/research_batches", "research-batch"),
)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    for delay in (*_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS, None):
        try:
            tmp_path.replace(path)
            return
        except PermissionError:
            if delay is None:
                try:
                    tmp_path.unlink(missing_ok=True)
                finally:
                    raise
            time.sleep(delay)


def _unique_packet_path(output_dir: Path, stem: str) -> Path:
    candidate = output_dir / f"{stem}.json"
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = output_dir / f"{stem}-{index:03d}.json"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique shadow packet path for {stem}.json")


def _safe_stem(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in value
    ).strip("-") or "packet"


def write_shadow_run_packet(
    packet: RunPacket,
    output_dir: str | Path = "results/shadow_policy_packets",
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    safe_run_id = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in packet.run_id
    ).strip("-") or "run"
    packet_path = _unique_packet_path(output_path, f"shadow-policy-{safe_run_id}")
    _atomic_write_text(packet_path, packet.model_dump_json(indent=2))
    _atomic_write_text(output_path / "latest.json", json.dumps(packet.model_dump(), indent=2))
    return packet_path


def _compact_research_quality_gates(gates: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key, value in gates.items():
        if key == "walk_forward_metrics" and isinstance(value, list):
            compact[key] = [
                {
                    metric_key: metric.get(metric_key)
                    for metric_key in (
                        "arm_id",
                        "status",
                        "scored_count",
                        "directional_accuracy",
                        "average_action_relative_return",
                        "false_positive_rate",
                        "sample_floor_met",
                        "execution_authority",
                    )
                    if isinstance(metric, dict) and metric.get(metric_key) is not None
                }
                for metric in value[:8]
                if isinstance(metric, dict)
            ]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
        elif key.endswith("_count") and isinstance(value, (list, tuple, set)):
            compact[key] = len(value)
    return compact


def _failed_research_quality_gates(gates: dict[str, object]) -> tuple[list[str], list[str]]:
    raw_failed_gates = [
        key
        for key, value in gates.items()
        if isinstance(value, bool)
        and value is False
        and key != "fallback_required"
    ]
    if gates.get("fallback_required") is True:
        raw_failed_gates.append("fallback_required")

    advisory_missing_gates: list[str] = []
    failed_gates: list[str] = []
    for key in raw_failed_gates:
        if (
            key == "at_least_one_local_worker_ready"
            and gates.get("fallback_required") is False
            and gates.get("research_quality_high_enough") is True
        ):
            advisory_missing_gates.append(key)
        else:
            failed_gates.append(key)
    return failed_gates, advisory_missing_gates


def compact_research_batch_payload(
    packet: research_schemas.ResearchBatchRunPacket,
    *,
    raw_packet_path: str | Path | None = None,
) -> dict[str, object]:
    gates = dict(packet.quality_gates or {})
    failed_gates, advisory_missing_gates = _failed_research_quality_gates(gates)
    execution_authority = packet.execution_authority
    return {
        "schema": "compact_research_batch_v1",
        "packet_id": packet.packet_id,
        "batch_id": packet.batch_id,
        "generated_at": packet.generated_at,
        "status": packet.status,
        "analysis_only": packet.analysis_only,
        "execution_authority": execution_authority,
        "can_submit_orders": False,
        "redaction_status": packet.redaction_status,
        "tool_route": packet.tool_route,
        "candidate_symbols": packet.candidate_symbols[:8],
        "candidate_symbol_count": len(packet.candidate_symbols),
        "lane_count": len(packet.orchestration_lanes),
        "source_packet_ref_count": len(packet.source_packet_refs),
        "crawler_packet_ref_count": len(packet.crawler_packet_refs),
        "social_packet_ref_count": len(packet.social_packet_refs),
        "model_telemetry_ref_count": len(packet.model_telemetry_refs),
        "mirror_packet_ref_count": len(packet.mirror_packet_refs),
        "graph_memory_ref_count": len(packet.graph_memory_refs),
        "output_packet_ref_count": len(packet.output_packet_refs),
        "fallback_action_count": len(packet.fallback_actions),
        "blocker_count": len(packet.blockers),
        "failed_quality_gates": failed_gates[:8],
        "advisory_missing_gates": advisory_missing_gates[:8],
        "quality_gates": _compact_research_quality_gates(gates),
        "raw_packet_path": str(raw_packet_path) if raw_packet_path is not None else None,
        "next_open": (
            "Open the raw research batch when status is not success, failed_quality_gates "
            "is non-empty, fallback_action_count changes, or a candidate changed."
        ),
    }


def compact_loss_review_evidence_payload(
    packet: research_schemas.SourceEvidencePacket,
    *,
    raw_packet_path: str | Path | None = None,
) -> dict[str, object]:
    payload = dict(packet.payload or {})
    advisory_analysis = (
        payload.get("advisory_analysis")
        if isinstance(payload.get("advisory_analysis"), dict)
        else {}
    )
    source_packet_ids = [
        str(item)
        for item in payload.get("source_packet_ids") or []
        if str(item).strip()
    ]
    route_summary = [
        item
        for item in advisory_analysis.get("route_summary") or []
        if isinstance(item, dict)
    ]
    blocked_route_count = sum(1 for item in route_summary if item.get("blocked") is True)
    source_refs = [
        item
        for item in advisory_analysis.get("source_refs") or []
        if isinstance(item, dict)
    ]
    entry_context = (
        payload.get("entry_context") if isinstance(payload.get("entry_context"), dict) else {}
    )
    entry_reason = str(entry_context.get("entry_reason") or "")
    entry_summary = {
        key: entry_context.get(key)
        for key in (
            "source",
            "packet_path",
            "packet_generated_at",
            "symbol",
            "account",
            "holding_period_trading_days",
            "order_status",
            "notional",
            "limit_price",
        )
        if entry_context.get(key) is not None
    }
    if entry_reason:
        entry_summary["entry_reason"] = entry_reason[:220]
    compact_payload = {
        "symbol": payload.get("symbol") or packet.symbol,
        "hourly_packet_path": payload.get("hourly_packet_path"),
        "hourly_generated_at": payload.get("hourly_generated_at"),
        "hourly_decision": payload.get("hourly_decision"),
        "submitted_order_count": payload.get("submitted_order_count"),
        "review_allowed": payload.get("review_allowed"),
        "supervisor_review_authority": payload.get("supervisor_review_authority") or {},
        "source_packet_ids": source_packet_ids,
        "provider_summary_packet_id": payload.get("provider_summary_packet_id"),
        "evidence_needs": payload.get("evidence_needs") or [],
        "evidence_coverage_by_need": payload.get("evidence_coverage_by_need") or {},
        "route_attempt_count": payload.get("route_attempt_count"),
        "blocked_route_count": blocked_route_count,
        "entry_context_found": payload.get("entry_context_found") is True,
        "entry_context": entry_summary,
        "advisory_summary": {
            "purpose": advisory_analysis.get("purpose"),
            "review_allowed_after_refresh": advisory_analysis.get(
                "review_allowed_after_refresh"
            ),
            "authority_source": advisory_analysis.get("authority_source"),
            "requires_board_decision": advisory_analysis.get(
                "requires_board_decision"
            ),
            "decision_owner": advisory_analysis.get("decision_owner"),
            "current_thesis_status_candidate": advisory_analysis.get(
                "current_thesis_status_candidate"
            ),
            "thesis_status_evidence": advisory_analysis.get("thesis_status_evidence")
            or {},
            "loss_exit_candidate": advisory_analysis.get("loss_exit_candidate") or {},
            "market_context_attached": advisory_analysis.get("market_context_attached"),
            "company_context_attached": advisory_analysis.get("company_context_attached"),
            "source_ref_count": len(source_refs),
            "route_attempt_count": len(route_summary),
            "blocked_route_count": blocked_route_count,
            "hold_vs_sell_frame": advisory_analysis.get("hold_vs_sell_frame"),
            "broad_market_noise_frame": advisory_analysis.get(
                "broad_market_noise_frame"
            ),
            "current_candidate_context": advisory_analysis.get(
                "current_candidate_context"
            )
            or {},
            "position_snapshot": advisory_analysis.get("position_snapshot") or {},
        },
        "remaining_blockers_before_refresh": (
            payload.get("remaining_blockers_before_refresh") or []
        ),
        "resolved_blockers_by_refresh": payload.get("resolved_blockers_by_refresh") or [],
        "remaining_blockers": payload.get("remaining_blockers") or [],
        "review_snapshot": payload.get("review_snapshot") or {},
        "next_action": payload.get("next_action"),
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": payload.get("forbidden_effects") or [],
    }
    return {
        "schema": "compact_loss_review_evidence_v1",
        "packet_id": packet.packet_id,
        "generated_at": packet.generated_at,
        "analysis_only": packet.analysis_only,
        "can_submit_orders": False,
        "execution_authority": "none",
        "source_name": packet.source_name,
        "evidence_type": packet.evidence_type,
        "subject": packet.subject,
        "symbol": packet.symbol,
        "quality": packet.quality,
        "tool_route": packet.tool_route,
        "redaction_status": packet.redaction_status,
        "freshness": {
            **dict(packet.freshness or {}),
            "can_submit_orders": False,
            "source_packet_count": len(source_packet_ids),
        },
        "payload": compact_payload,
        "raw_packet_path": str(raw_packet_path) if raw_packet_path is not None else None,
        "next_open": (
            "Open the raw loss-review evidence packet when BOARD/manual review "
            "needs full source refs or provider route details."
        ),
    }


def _research_packet_route(packet: research_schemas.ResearchPacketBase) -> tuple[str, str]:
    for packet_type, output_dir, prefix in RESEARCH_PACKET_ROUTES:
        if isinstance(packet, packet_type):
            return output_dir, prefix
    return "results/research_packets", "research"


def write_research_packet(
    packet: research_schemas.ResearchPacketBase,
    output_dir: str | Path | None = None,
) -> Path:
    default_dir, prefix = _research_packet_route(packet)
    output_path = Path(output_dir or default_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    packet_path = _unique_packet_path(
        output_path,
        _safe_stem(f"{prefix}-{packet.packet_id}"),
    )
    text = packet.model_dump_json(indent=2)
    _atomic_write_text(packet_path, text)
    _atomic_write_text(output_path / "latest.json", json.dumps(packet.model_dump(), indent=2))
    if isinstance(packet, research_schemas.ResearchBatchRunPacket):
        compact = compact_research_batch_payload(packet, raw_packet_path=packet_path)
        compact_text = json.dumps(compact, indent=2, sort_keys=True)
        _atomic_write_text(packet_path.with_suffix(".compact.json"), compact_text)
        _atomic_write_text(output_path / "latest-compact.json", compact_text)
    elif (
        isinstance(packet, research_schemas.SourceEvidencePacket)
        and packet.evidence_type == "loss_review_evidence"
    ):
        compact = compact_loss_review_evidence_payload(packet, raw_packet_path=packet_path)
        compact_text = json.dumps(compact, indent=2, sort_keys=True)
        _atomic_write_text(packet_path.with_suffix(".compact.json"), compact_text)
        _atomic_write_text(output_path / "latest-compact.json", compact_text)
    return packet_path
