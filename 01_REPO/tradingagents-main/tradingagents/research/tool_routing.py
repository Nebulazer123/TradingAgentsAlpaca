"""Research tool routing policy for autonomous jobs."""

from __future__ import annotations

from dataclasses import dataclass

WRITE_ACTIONS = {
    "post",
    "comment",
    "vote",
    "message",
    "send_email",
    "trade",
    "submit_order",
    "modify_account",
    "write_file_cloud",
}


@dataclass(frozen=True)
class ToolRouteDecision:
    allowed: bool
    route: str
    action: str
    reason: str


READ_ONLY_ROUTE_PREFIXES = (
    "composio:reddit",
    "composio:facebook",
    "composio:instagram",
    "composio:linkedin",
    "composio:youtube",
    "composio:github",
    "composio:benzinga",
    "composio:firecrawl",
    "docker:twitter-research",
    "docker:fetch",
    "docker:duckduckgo",
    "docker:playwright",
    "docker:youtube_transcript",
    "crawler:crawlee_playwright",
    "browser:inspection",
)


def validate_autonomous_research_route(route: str, action: str) -> ToolRouteDecision:
    normalized_action = action.strip().lower()
    normalized_route = route.strip().lower()
    if normalized_action in WRITE_ACTIONS:
        return ToolRouteDecision(
            allowed=False,
            route=route,
            action=action,
            reason="autonomous research cannot perform write/post/send/trade actions",
        )
    if not any(normalized_route.startswith(prefix) for prefix in READ_ONLY_ROUTE_PREFIXES):
        return ToolRouteDecision(
            allowed=False,
            route=route,
            action=action,
            reason="route is not approved for autonomous research",
        )
    return ToolRouteDecision(
        allowed=True,
        route=route,
        action=action,
        reason="route is approved for read-only evidence collection",
    )
