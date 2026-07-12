"""Research provider fallback policy.

This keeps paid or rate-limited APIs as optional enrichment. If a source is out
of calls, the research batch should mark it depleted, use free/local/MCP/cache
fallbacks where possible, and continue with lower confidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from tradingagents.dataflows._official_common import evidence_packet, request_hash

DEFAULT_PROVIDER_FALLBACK_PATH = Path("config/research_provider_fallbacks.json")
CostTier = Literal[
    "cache",
    "local_unlimited",
    "connected_mcp_read",
    "free_unmetered",
    "free_limited",
    "paid_limited",
]
DEFAULT_COST_ORDER = (
    "cache",
    "local_unlimited",
    "connected_mcp_read",
    "free_unmetered",
    "free_limited",
    "paid_limited",
)
LIMITED_TIERS = {"free_limited", "paid_limited"}


@dataclass(frozen=True)
class ProviderFallbackCandidate:
    evidence_need: str
    source_name: str
    route: str
    cost_tier: CostTier
    priority: int
    status: Literal["available", "depleted", "disabled"] = "available"
    source_quality_score: float | None = None
    source_quality_reason: str | None = None

    @property
    def is_limited(self) -> bool:
        return self.cost_tier in LIMITED_TIERS

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def load_provider_fallback_config(path: str | Path = DEFAULT_PROVIDER_FALLBACK_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _tier_rank(cost_tier: str, order: tuple[str, ...]) -> int:
    try:
        return order.index(cost_tier)
    except ValueError:
        return len(order)


def _is_research_gap(candidate: ProviderFallbackCandidate) -> bool:
    return candidate.route == "local:research_gap" or candidate.source_name.endswith("_gap")


def _quality_strength(
    source_name: str,
    strengths: Mapping[str, Any] | None,
) -> tuple[float | None, str | None]:
    if not strengths:
        return None, None
    raw = strengths.get(source_name) or strengths.get(source_name.lower())
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), None
    if isinstance(raw, Mapping):
        score = raw.get("score")
        reason = raw.get("reason")
    else:
        score = getattr(raw, "score", None)
        reason = getattr(raw, "reason", None)
    try:
        parsed_score = float(score)
    except (TypeError, ValueError):
        return None, str(reason) if reason else None
    return parsed_score, str(reason) if reason else None


def _ordering_strength(candidate: ProviderFallbackCandidate) -> float:
    if candidate.source_quality_score is None:
        return 50.0
    return candidate.source_quality_score


def _candidate_sort_key(
    candidate: ProviderFallbackCandidate,
    *,
    cost_order: tuple[str, ...],
    use_quality_ordering: bool,
) -> tuple[Any, ...]:
    base = (
        0 if candidate.status == "available" else 1,
        1 if _is_research_gap(candidate) else 0,
    )
    if use_quality_ordering:
        return (
            *base,
            -_ordering_strength(candidate),
            _tier_rank(candidate.cost_tier, cost_order),
            candidate.priority,
            candidate.source_name,
        )
    return (
        *base,
        _tier_rank(candidate.cost_tier, cost_order),
        candidate.priority,
        candidate.source_name,
    )


def fallback_candidates_for_need(
    evidence_need: str,
    *,
    config: dict[str, Any] | None = None,
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    source_quality_strengths: Mapping[str, Any] | None = None,
) -> list[ProviderFallbackCandidate]:
    loaded = config or load_provider_fallback_config()
    fallback_map = loaded.get("fallbacks", {})
    if evidence_need not in fallback_map:
        raise ValueError(f"unknown evidence need: {evidence_need}")
    depleted = {source.strip().lower() for source in depleted_sources or set()}
    disabled = {source.strip().lower() for source in disabled_sources or set()}
    cost_order = tuple(loaded.get("cost_tier_order") or DEFAULT_COST_ORDER)
    candidates: list[ProviderFallbackCandidate] = []
    for item in fallback_map[evidence_need]:
        source_name = str(item["source_name"]).strip().lower()
        quality_score, quality_reason = _quality_strength(source_name, source_quality_strengths)
        if source_name in disabled:
            status: Literal["available", "depleted", "disabled"] = "disabled"
        elif source_name in depleted:
            status = "depleted"
        else:
            status = "available"
        candidates.append(
            ProviderFallbackCandidate(
                evidence_need=evidence_need,
                source_name=source_name,
                route=str(item["route"]),
                cost_tier=item["cost_tier"],  # type: ignore[arg-type]
                priority=int(item.get("priority", 100)),
                status=status,
                source_quality_score=quality_score,
                source_quality_reason=quality_reason,
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: _candidate_sort_key(
            candidate,
            cost_order=cost_order,
            use_quality_ordering=source_quality_strengths is not None,
        ),
    )


def select_available_fallbacks(
    evidence_need: str,
    *,
    config: dict[str, Any] | None = None,
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    source_quality_strengths: Mapping[str, Any] | None = None,
    limit: int | None = None,
) -> list[ProviderFallbackCandidate]:
    candidates = fallback_candidates_for_need(
        evidence_need,
        config=config,
        depleted_sources=depleted_sources,
        disabled_sources=disabled_sources,
        source_quality_strengths=source_quality_strengths,
    )
    available = [candidate for candidate in candidates if candidate.status == "available"]
    return available[:limit] if limit else available


def build_provider_fallback_packet(
    *,
    evidence_need: str,
    config: dict[str, Any] | None = None,
    path: str | Path = DEFAULT_PROVIDER_FALLBACK_PATH,
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    source_quality_strengths: Mapping[str, Any] | None = None,
) -> Any:
    loaded = config if config is not None else load_provider_fallback_config(path)
    candidates = fallback_candidates_for_need(
        evidence_need,
        config=loaded,
        depleted_sources=depleted_sources,
        disabled_sources=disabled_sources,
        source_quality_strengths=source_quality_strengths,
    )
    active = [candidate for candidate in candidates if candidate.status == "available"]
    skipped = [candidate for candidate in candidates if candidate.status != "available"]
    source_ref = f"local://{Path(path).as_posix()}#{evidence_need}"
    payload = {
        "evidence_need": evidence_need,
        "policy": loaded.get("policy", {}),
        "depletion_safe": True,
        "limited_api_behavior": "skip_when_depleted",
        "active_routes": [candidate.model_dump() for candidate in active],
        "skipped_routes": [candidate.model_dump() for candidate in skipped],
        "active_source_names": [candidate.source_name for candidate in active],
        "limited_sources_active": [
            candidate.source_name for candidate in active if candidate.is_limited
        ],
        "preferred_free_or_mcp_routes": [
            candidate.model_dump()
            for candidate in active
            if candidate.cost_tier in {"cache", "local_unlimited", "connected_mcp_read", "free_unmetered"}
        ],
    }
    return evidence_packet(
        source_name="provider_fallback_policy",
        evidence_type="research_provider_fallbacks",
        subject=evidence_need,
        source_ref=source_ref,
        payload=payload,
        quality="medium",
        request_fingerprint=request_hash("READ", source_ref, None, payload),
        tool_route="local_provider_fallback_policy",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "depleted_sources": sorted(depleted_sources or set()),
            "disabled_sources": sorted(disabled_sources or set()),
        },
    )
