"""Core schemas for research-to-paper-to-live policy packets."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.0.0"
UTC = datetime.timezone.utc


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _packet_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class SourceProvenance(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source: str
    as_of: str
    path: str | None = None
    quality: Literal["high", "medium", "low", "unknown"] = "unknown"


class CandidatePacket(BaseModel):
    schema_version: str = SCHEMA_VERSION
    packet_id: str = Field(default_factory=lambda: _packet_id("candidate"))
    candidate_id: str | None = None
    symbol: str
    as_of: str
    universe_bucket: str
    eligibility: dict[str, bool] = Field(default_factory=dict)
    routing_hints: list[str] = Field(default_factory=list)
    event_flags: dict[str, bool] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    code_version: str | None = None
    config_version: str | None = None
    sources: list[SourceProvenance] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class FeaturePacket(BaseModel):
    schema_version: str = SCHEMA_VERSION
    packet_id: str = Field(default_factory=lambda: _packet_id("feature"))
    feature_id: str | None = None
    symbol: str
    as_of: str
    features: dict[str, Any] = Field(default_factory=dict)
    completeness: float = 1.0
    feature_completeness: dict[str, bool] = Field(default_factory=dict)
    data_integrity_ref: str | None = None
    freshness: dict[str, Any] = Field(default_factory=dict)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    code_version: str | None = None
    config_version: str | None = None
    sources: list[SourceProvenance] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class Hypothesis(BaseModel):
    schema_version: str = SCHEMA_VERSION
    hypothesis_id: str | None = None
    symbol: str
    sleeve_candidates: list[str] = Field(default_factory=list)
    thesis: str
    counter_thesis: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    invalidators: list[str] = Field(default_factory=list)
    entry_trigger: str = ""
    exit_trigger: str = ""
    data_confidence: float = 0.0
    risk_flags: list[str] = Field(default_factory=list)


class TradeIntent(BaseModel):
    schema_version: str = SCHEMA_VERSION
    packet_id: str = Field(default_factory=lambda: _packet_id("intent"))
    intent_id: str | None = None
    idempotency_key: str
    symbol: str
    sleeve: str
    environment: Literal["paper", "tiny_live", "full_live"]
    side: Literal["buy"] = "buy"
    order_type: Literal["limit"] = "limit"
    limit_price: str
    limit_low: str | None = None
    limit_high: str | None = None
    tif: str = "day"
    size_usd: str
    size_shares: str | None = None
    size_context: dict[str, Any] = Field(default_factory=dict)
    entry_plan: dict[str, Any] = Field(default_factory=dict)
    exit_plan: dict[str, Any] = Field(default_factory=dict)
    invalidator: dict[str, Any] = Field(default_factory=dict)
    gate_trace: list[dict[str, Any]] = Field(default_factory=list)
    code_version: str | None = None
    config_version: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class RiskGateDecision(BaseModel):
    schema_version: str = SCHEMA_VERSION
    gate_id: str | None = None
    intent_id: str | None = None
    hard_gates: dict[str, bool] = Field(default_factory=dict)
    soft_gates: dict[str, bool] = Field(default_factory=dict)
    final_action: Literal["paper_enter", "live_enter", "hold_cash", "reject", "watch"]
    rejection_reasons: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    schema_version: str = SCHEMA_VERSION
    validation_report_id: str
    sleeve: str
    rule_version: str
    sample_summary: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    promotion_recommendation: str = "research_only"


class PaperTournamentState(BaseModel):
    schema_version: str = SCHEMA_VERSION
    tournament_state_id: str
    sleeves: dict[str, Any] = Field(default_factory=dict)
    last_updated: str = Field(default_factory=_now_iso)


class RunPacket(BaseModel):
    schema_version: str = SCHEMA_VERSION
    packet_id: str = Field(default_factory=lambda: _packet_id("run"))
    run_id: str
    run_type: str
    decision: Literal["order", "hold_cash", "watch", "reject"]
    timestamp: str = Field(default_factory=_now_iso)
    candidate: CandidatePacket | None = None
    features: FeaturePacket | None = None
    hypothesis: Hypothesis | None = None
    intent: TradeIntent | None = None
    gate: RiskGateDecision | None = None
    input_hashes: dict[str, str] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
