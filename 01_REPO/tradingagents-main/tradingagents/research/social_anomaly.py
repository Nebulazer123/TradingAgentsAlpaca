"""Build research-only social anomaly packets."""

from __future__ import annotations

from typing import Any

from tradingagents.schemas.research import SocialAnomalyPacket

READ_ONLY_SOCIAL_ROUTES = {
    "composio:reddit",
    "docker:twitter-research",
    "stocktwits:public",
    "composio:facebook",
    "composio:instagram",
    "composio:linkedin",
    "composio:youtube",
}


def social_anomaly_packet(
    *,
    platform: str,
    summary: str,
    anomaly_type: str,
    query: str,
    route: str,
    metrics: dict[str, Any] | None = None,
    symbol: str | None = None,
    evidence_refs: list[str] | None = None,
    severity: str = "unknown",
) -> SocialAnomalyPacket:
    if route not in READ_ONLY_SOCIAL_ROUTES:
        raise ValueError(f"social route is not approved for autonomous read-only research: {route}")
    packet_metrics = dict(metrics or {})
    packet_metrics["query"] = query
    packet_metrics["read_only_route"] = route
    return SocialAnomalyPacket(
        platform=platform,
        anomaly_type=anomaly_type,
        severity=severity,  # type: ignore[arg-type]
        summary=summary,
        symbol=symbol,
        metrics=packet_metrics,
        evidence_refs=list(evidence_refs or []),
        source_refs=list(evidence_refs or []),
        tool_route=route,
        redaction_status="redacted",
    )
