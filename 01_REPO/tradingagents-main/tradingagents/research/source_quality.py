"""Source quality policy for research evidence.

This module is intentionally advisory. It labels evidence trust and freshness,
but it never grants permission to create orders, size positions, promote sleeves,
or bypass live gates.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from tradingagents.schemas.research import SourceEvidencePacket

UTC = datetime.timezone.utc
Quality = Literal["high", "medium", "low", "unknown"]
FreshnessStatus = Literal["fresh", "stale", "missing_or_invalid"]


@dataclass(frozen=True)
class SourceTrustProfile:
    source_name: str
    base_quality: Quality
    ttl_hours: int
    role: str
    allowed_effects: tuple[str, ...]


@dataclass(frozen=True)
class SourceQualityDecision:
    source_name: str
    quality: Quality
    freshness_status: FreshnessStatus
    ttl_hours: int
    role: str
    allowed_effects: tuple[str, ...]
    forbidden_effects: tuple[str, ...]
    reason: str

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SourceQualityStrength:
    source_name: str
    score: float
    decision_count: int
    fresh_count: int
    stale_count: int
    missing_or_invalid_count: int
    blocked_count: int
    high_count: int
    medium_count: int
    low_count: int
    unknown_count: int
    reason: str

    def model_dump(self) -> dict:
        return asdict(self)


FORBIDDEN_EFFECTS = (
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
)

SOURCE_TRUST_PROFILES: dict[str, SourceTrustProfile] = {
    "sec_edgar": SourceTrustProfile(
        source_name="sec_edgar",
        base_quality="high",
        ttl_hours=72,
        role="official_filing_context",
        allowed_effects=("veto", "downrank", "request_more_research"),
    ),
    "fred": SourceTrustProfile(
        source_name="fred",
        base_quality="high",
        ttl_hours=48,
        role="official_macro_context",
        allowed_effects=("veto", "downrank", "request_more_research"),
    ),
    "bls": SourceTrustProfile(
        source_name="bls",
        base_quality="high",
        ttl_hours=48,
        role="official_macro_context",
        allowed_effects=("veto", "downrank", "request_more_research"),
    ),
    "bea": SourceTrustProfile(
        source_name="bea",
        base_quality="high",
        ttl_hours=48,
        role="official_macro_context",
        allowed_effects=("veto", "downrank", "request_more_research"),
    ),
    "eia": SourceTrustProfile(
        source_name="eia",
        base_quality="high",
        ttl_hours=48,
        role="official_energy_context",
        allowed_effects=("veto", "downrank", "request_more_research"),
    ),
    "treasury_fiscal": SourceTrustProfile(
        source_name="treasury_fiscal",
        base_quality="high",
        ttl_hours=48,
        role="official_fiscal_context",
        allowed_effects=("veto", "downrank", "request_more_research"),
    ),
    "alpha_vantage": SourceTrustProfile(
        source_name="alpha_vantage",
        base_quality="medium",
        ttl_hours=24,
        role="supplemental_market_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "alpaca_news": SourceTrustProfile(
        source_name="alpaca_news",
        base_quality="medium",
        ttl_hours=3,
        role="execution_adjacent_read_only_news_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "newsapi": SourceTrustProfile(
        source_name="newsapi",
        base_quality="medium",
        ttl_hours=6,
        role="supplemental_broad_news_discovery_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "tiingo": SourceTrustProfile(
        source_name="tiingo",
        base_quality="medium",
        ttl_hours=12,
        role="supplemental_price_news_metadata_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "strategy_methodology_cards": SourceTrustProfile(
        source_name="strategy_methodology_cards",
        base_quality="medium",
        ttl_hours=168,
        role="local_methodology_contract_context",
        allowed_effects=("request_more_research",),
    ),
    "chatgpt_deep_research_protocol": SourceTrustProfile(
        source_name="chatgpt_deep_research_protocol",
        base_quality="medium",
        ttl_hours=168,
        role="external_deep_research_methodology_context",
        allowed_effects=("request_more_research",),
    ),
    "eodhd": SourceTrustProfile(
        source_name="eodhd",
        base_quality="medium",
        ttl_hours=12,
        role="supplemental_market_news_fundamentals_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "finnhub": SourceTrustProfile(
        source_name="finnhub",
        base_quality="medium",
        ttl_hours=6,
        role="supplemental_quote_news_profile_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "massive": SourceTrustProfile(
        source_name="massive",
        base_quality="medium",
        ttl_hours=6,
        role="supplemental_market_microstructure_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "fmp": SourceTrustProfile(
        source_name="fmp",
        base_quality="medium",
        ttl_hours=12,
        role="supplemental_fundamentals_news_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "google_news_rss": SourceTrustProfile(
        source_name="google_news_rss",
        base_quality="low",
        ttl_hours=3,
        role="supplemental_news_discovery_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "marketaux": SourceTrustProfile(
        source_name="marketaux",
        base_quality="medium",
        ttl_hours=6,
        role="supplemental_market_news_sentiment_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "scrapingbee": SourceTrustProfile(
        source_name="scrapingbee",
        base_quality="low",
        ttl_hours=3,
        role="fallback_scraped_page_context",
        allowed_effects=("request_more_research",),
    ),
    "social_watchlist": SourceTrustProfile(
        source_name="social_watchlist",
        base_quality="low",
        ttl_hours=24,
        role="read_only_attention_target_context",
        allowed_effects=("request_more_research",),
    ),
    "reddit_watchlist": SourceTrustProfile(
        source_name="reddit_watchlist",
        base_quality="low",
        ttl_hours=24,
        role="read_only_reddit_market_sentiment_watchlist",
        allowed_effects=("request_more_research",),
    ),
    "provider_fallback_policy": SourceTrustProfile(
        source_name="provider_fallback_policy",
        base_quality="medium",
        ttl_hours=24,
        role="read_only_research_source_fallback_policy",
        allowed_effects=("request_more_research",),
    ),
    "ticker_provider_orchestrator": SourceTrustProfile(
        source_name="ticker_provider_orchestrator",
        base_quality="medium",
        ttl_hours=24,
        role="read_only_ticker_provider_route_summary",
        allowed_effects=("request_more_research",),
    ),
    "official_cache": SourceTrustProfile(
        source_name="official_cache",
        base_quality="medium",
        ttl_hours=24,
        role="read_only_cached_evidence_context",
        allowed_effects=("request_more_research",),
    ),
    "crawlee": SourceTrustProfile(
        source_name="crawlee",
        base_quality="medium",
        ttl_hours=6,
        role="read_only_allowlisted_crawler_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "broker_snapshot": SourceTrustProfile(
        source_name="broker_snapshot",
        base_quality="medium",
        ttl_hours=1,
        role="read_only_sanitized_broker_account_context",
        allowed_effects=("request_more_research",),
    ),
    "yfinance": SourceTrustProfile(
        source_name="yfinance",
        base_quality="low",
        ttl_hours=6,
        role="prototype_convenience_context",
        allowed_effects=("request_more_research",),
    ),
    "yfinance_options": SourceTrustProfile(
        source_name="yfinance_options",
        base_quality="low",
        ttl_hours=3,
        role="supplemental_options_iv_open_interest_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "yfinance_short_interest": SourceTrustProfile(
        source_name="yfinance_short_interest",
        base_quality="low",
        ttl_hours=24,
        role="supplemental_short_interest_metadata_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "reddit": SourceTrustProfile(
        source_name="reddit",
        base_quality="low",
        ttl_hours=3,
        role="social_anomaly_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "stocktwits": SourceTrustProfile(
        source_name="stocktwits",
        base_quality="low",
        ttl_hours=3,
        role="social_anomaly_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
    "twitter": SourceTrustProfile(
        source_name="twitter",
        base_quality="low",
        ttl_hours=3,
        role="social_anomaly_context",
        allowed_effects=("downrank", "request_more_research"),
    ),
}

QUALITY_STRENGTH_WEIGHTS = {
    "high": 300,
    "medium": 200,
    "low": 75,
    "unknown": 0,
}
FRESHNESS_STRENGTH_PENALTIES = {
    "fresh": 0,
    "stale": 90,
    "missing_or_invalid": 180,
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=UTC)


def _parse_timestamp(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _downgrade_for_staleness(profile: SourceTrustProfile, freshness_status: FreshnessStatus) -> Quality:
    if freshness_status == "fresh":
        return profile.base_quality
    if freshness_status == "stale":
        if profile.base_quality == "high":
            return "medium"
        if profile.base_quality == "medium":
            return "low"
        return profile.base_quality
    return "unknown"


def assess_source_quality(
    source_name: str,
    *,
    as_of: str | None,
    current_time: datetime.datetime | None = None,
) -> SourceQualityDecision:
    normalized = source_name.strip().lower()
    profile = SOURCE_TRUST_PROFILES.get(
        normalized,
        SourceTrustProfile(
            source_name=normalized or "unknown",
            base_quality="unknown",
            ttl_hours=24,
            role="unclassified_context",
            allowed_effects=("request_more_research",),
        ),
    )
    now = current_time.astimezone(UTC) if current_time else _now()
    observed_at = _parse_timestamp(as_of)
    if observed_at is None:
        freshness_status: FreshnessStatus = "missing_or_invalid"
        reason = "source timestamp is missing or invalid"
    else:
        age_hours = max((now - observed_at).total_seconds() / 3600, 0)
        if age_hours <= profile.ttl_hours:
            freshness_status = "fresh"
            reason = f"source is fresh within {profile.ttl_hours}h policy"
        else:
            freshness_status = "stale"
            reason = f"source is older than {profile.ttl_hours}h policy"
    return SourceQualityDecision(
        source_name=profile.source_name,
        quality=_downgrade_for_staleness(profile, freshness_status),
        freshness_status=freshness_status,
        ttl_hours=profile.ttl_hours,
        role=profile.role,
        allowed_effects=profile.allowed_effects,
        forbidden_effects=FORBIDDEN_EFFECTS,
        reason=reason,
    )


def _quality_strength_weight(value: Any) -> int:
    return QUALITY_STRENGTH_WEIGHTS.get(str(value or "").lower(), 0)


def _freshness_strength_penalty(value: Any) -> int:
    return FRESHNESS_STRENGTH_PENALTIES.get(str(value or "").lower(), 180)


def build_source_quality_strengths(review: dict[str, Any] | None) -> dict[str, SourceQualityStrength]:
    """Summarize a source-quality review into route-ordering scores.

    Scores are advisory only. They help choose which read-only provider to try
    first, but they never grant execution authority or suppress gap packets.
    """
    decisions = review.get("decisions") if isinstance(review, dict) else None
    if not isinstance(decisions, list):
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in decisions:
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_name") or "").strip().lower()
        if not source_name:
            continue
        grouped.setdefault(source_name, []).append(item)

    strengths: dict[str, SourceQualityStrength] = {}
    for source_name, items in grouped.items():
        scores: list[float] = []
        fresh_count = stale_count = missing_count = 0
        blocked_count = 0
        high_count = medium_count = low_count = unknown_count = 0
        for item in items:
            quality = str(item.get("quality") or "unknown").lower()
            freshness = str(item.get("freshness_status") or "missing_or_invalid").lower()
            allowed_effects = item.get("allowed_effects") or ()
            blocked = bool(item.get("blocked"))
            if quality == "high":
                high_count += 1
            elif quality == "medium":
                medium_count += 1
            elif quality == "low":
                low_count += 1
            else:
                unknown_count += 1
            if freshness == "fresh":
                fresh_count += 1
            elif freshness == "stale":
                stale_count += 1
            else:
                missing_count += 1
            score = _quality_strength_weight(quality) - _freshness_strength_penalty(freshness)
            if freshness == "stale" and "downrank" in allowed_effects:
                score -= 20
            if blocked:
                blocked_count += 1
                score -= 260
            scores.append(max(score, -100))
        average_score = sum(scores) / len(scores) if scores else 0.0
        strengths[source_name] = SourceQualityStrength(
            source_name=source_name,
            score=round(average_score, 2),
            decision_count=len(items),
            fresh_count=fresh_count,
            stale_count=stale_count,
            missing_or_invalid_count=missing_count,
            blocked_count=blocked_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            unknown_count=unknown_count,
            reason=(
                f"{fresh_count} fresh, {stale_count} stale, "
                f"{missing_count} missing/invalid, {blocked_count} blocked "
                f"across {len(items)} packets"
            ),
        )
    return strengths


def load_source_quality_strengths(path: str | Path) -> dict[str, SourceQualityStrength]:
    source_path = Path(path)
    if not source_path.exists():
        return {}
    try:
        review = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return build_source_quality_strengths(review if isinstance(review, dict) else None)


def apply_source_quality(
    packet: SourceEvidencePacket,
    *,
    current_time: datetime.datetime | None = None,
) -> SourceEvidencePacket:
    decision = assess_source_quality(
        packet.source_name,
        as_of=packet.as_of or packet.generated_at,
        current_time=current_time,
    )
    freshness = dict(packet.freshness)
    freshness["source_quality"] = decision.model_dump()
    freshness["stale"] = decision.freshness_status != "fresh"
    sources = [
        source.model_copy(update={"quality": decision.quality})
        for source in packet.sources
    ]
    return packet.model_copy(
        update={
            "quality": decision.quality,
            "freshness": freshness,
            "sources": sources,
        }
    )
