"""Research evidence schemas.

These packets are advisory by construction. They can explain why a ticker is
interesting, record sources, and track model/crawler/memory work, but they
cannot carry broker actions or trade intents.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tradingagents.schemas.trading import SCHEMA_VERSION, SourceProvenance

UTC = datetime.timezone.utc


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _packet_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class ResearchPacketBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    packet_id: str = Field(default_factory=lambda: _packet_id("research"))
    generated_at: str = Field(default_factory=_now_iso)
    analysis_only: Literal[True] = True
    sources: list[SourceProvenance] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    tool_route: str = "local"
    redaction_status: Literal["redacted", "no_secrets_seen", "blocked"] = "redacted"

    @field_validator("source_refs")
    @classmethod
    def strip_source_refs(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class SourceEvidencePacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("source-evidence"))
    source_name: str
    evidence_type: str
    subject: str
    symbol: str | None = None
    as_of: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    quality: Literal["high", "medium", "low", "unknown"] = "unknown"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class ResearchIntelligencePacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("research-intel"))
    subject: str
    summary: str
    symbols: list[str] = Field(default_factory=list)
    signals: list[dict[str, Any]] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol and symbol.strip()]


class MarketActorProfile(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("market-actor"))
    actor_id: str
    actor_type: str
    stance: str = "unknown"
    thesis: str = ""
    invalidators: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class MarketMirrorScenarioPacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("market-mirror"))
    scenario_id: str
    symbol: str
    actor_profile_refs: list[str] = Field(default_factory=list)
    consensus: str = ""
    disagreements: list[str] = Field(default_factory=list)
    watch_items: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    usefulness_label: Literal["unknown", "pending", "useful", "mixed", "not_useful", "harmful"] = "pending"
    outcome_label: Literal["unresolved", "helped", "neutral", "hurt", "not_evaluable"] = "unresolved"
    quality_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    outcome_notes: str | None = None
    resolved_at: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ModelRunTelemetryPacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("model-telemetry"))
    run_id: str
    provider: str
    model: str
    route: str
    context_window_tokens: int | None = None
    status: Literal["success", "fallback", "blocked", "failed"]
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: str | None = None
    latency_seconds: float | None = None
    budget_ref: str | None = None
    error_summary: str | None = None
    usefulness_label: Literal["unknown", "pending", "useful", "mixed", "not_useful", "harmful"] = "pending"
    outcome_label: Literal["unresolved", "helped", "neutral", "hurt", "not_evaluable"] = "unresolved"
    quality_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    outcome_notes: str | None = None
    resolved_at: str | None = None


class CrawlerRunPacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("crawler-run"))
    run_id: str
    crawler: str
    target: str
    status: Literal["success", "partial", "blocked", "failed"]
    fetched_urls: list[str] = Field(default_factory=list)
    blocked_urls: list[str] = Field(default_factory=list)
    max_pages: int = 0
    robots_policy: str = "respect"


class KnowledgeGraphNodePacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("kg-node"))
    node_id: str
    node_type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphEdgePacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("kg-edge"))
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphMemoryQueryPacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("graph-query"))
    query_id: str
    query: str
    status: Literal["success", "fallback", "blocked", "failed"]
    result_refs: list[str] = Field(default_factory=list)
    local_fallback_used: bool = False


class SocialAnomalyPacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("social-anomaly"))
    symbol: str | None = None
    platform: str
    anomaly_type: str
    severity: Literal["high", "medium", "low", "unknown"] = "unknown"
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class PromptRegistryPacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("prompt-registry"))
    prompt_id: str
    prompt_hash: str
    prompt_role: str
    allowed_outputs: list[str] = Field(default_factory=list)
    forbidden_outputs: list[str] = Field(default_factory=list)


class ResearchBatchRunPacket(ResearchPacketBase):
    packet_id: str = Field(default_factory=lambda: _packet_id("research-batch"))
    batch_id: str
    status: Literal["success", "partial", "blocked", "failed"]
    candidate_symbols: list[str] = Field(default_factory=list)
    orchestration_lanes: list[dict[str, Any]] = Field(default_factory=list)
    quality_gates: dict[str, Any] = Field(default_factory=dict)
    fallback_actions: list[str] = Field(default_factory=list)
    source_packet_refs: list[str] = Field(default_factory=list)
    crawler_packet_refs: list[str] = Field(default_factory=list)
    social_packet_refs: list[str] = Field(default_factory=list)
    model_telemetry_refs: list[str] = Field(default_factory=list)
    mirror_packet_refs: list[str] = Field(default_factory=list)
    graph_memory_refs: list[str] = Field(default_factory=list)
    output_packet_refs: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    execution_authority: str = "none"
    forbidden_effects: list[str] = Field(
        default_factory=lambda: [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
        ]
    )

    @field_validator("candidate_symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [symbol.strip().upper() for symbol in value if symbol and symbol.strip()]
