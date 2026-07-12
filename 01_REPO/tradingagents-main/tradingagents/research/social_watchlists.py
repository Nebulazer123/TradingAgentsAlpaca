"""Read-only social and official-account watchlists for research attention.

These URLs are targets to monitor, not accounts to control. They can create
research packets and anomaly prompts only; write/social actions are forbidden.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from tradingagents.dataflows._official_common import evidence_packet, request_hash
from tradingagents.research.tool_routing import validate_autonomous_research_route

DEFAULT_SOCIAL_WATCHLIST_PATH = Path("config/social_watchlists.json")
ALLOWED_EFFECTS = ("request_more_research", "downrank")
FORBIDDEN_EFFECTS = (
    "post",
    "comment",
    "vote",
    "like",
    "follow",
    "message",
    "send_email",
    "trade",
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
)
PLATFORM_ROUTES = {
    "x.com": ("x", "docker:twitter-research"),
    "twitter.com": ("x", "docker:twitter-research"),
    "facebook.com": ("facebook", "composio:facebook"),
    "instagram.com": ("instagram", "composio:instagram"),
    "linkedin.com": ("linkedin", "composio:linkedin"),
}


@dataclass(frozen=True)
class SocialWatchTarget:
    category: str
    url: str
    platform: str
    route: str
    hostname: str
    read_only: bool = True
    allowed_effects: tuple[str, ...] = ALLOWED_EFFECTS
    forbidden_effects: tuple[str, ...] = FORBIDDEN_EFFECTS

    def model_dump(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_effects"] = list(self.allowed_effects)
        payload["forbidden_effects"] = list(self.forbidden_effects)
        return payload


def _host_key(hostname: str) -> str:
    host = hostname.lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def classify_social_watch_url(url: str) -> tuple[str, str, str]:
    clean = url.strip()
    parsed = urlsplit(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("social watchlist URL must be an http(s) URL with a hostname")
    host = parsed.hostname.lower()
    key = _host_key(host)
    if key not in PLATFORM_ROUTES:
        raise ValueError(f"unsupported social watchlist host: {host}")
    platform, route = PLATFORM_ROUTES[key]
    decision = validate_autonomous_research_route(route, "read")
    if not decision.allowed:
        raise ValueError(decision.reason)
    return platform, route, host


def load_social_watchlist_config(path: str | Path = DEFAULT_SOCIAL_WATCHLIST_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def flatten_social_watchlists(config: dict[str, Any]) -> list[SocialWatchTarget]:
    raw_watchlists = config.get("social_watchlists", config)
    targets: list[SocialWatchTarget] = []
    for category, urls in raw_watchlists.items():
        if not isinstance(urls, list):
            raise ValueError(f"social watchlist category {category!r} must be a list")
        for url in urls:
            platform, route, host = classify_social_watch_url(str(url))
            targets.append(
                SocialWatchTarget(
                    category=str(category),
                    url=str(url).strip(),
                    platform=platform,
                    route=route,
                    hostname=host,
                )
            )
    return targets


def build_social_watchlist_packet(
    *,
    config: dict[str, Any] | None = None,
    path: str | Path = DEFAULT_SOCIAL_WATCHLIST_PATH,
) -> Any:
    loaded = config if config is not None else load_social_watchlist_config(path)
    targets = flatten_social_watchlists(loaded)
    counts_by_platform: dict[str, int] = {}
    counts_by_category: dict[str, int] = {}
    for target in targets:
        counts_by_platform[target.platform] = counts_by_platform.get(target.platform, 0) + 1
        counts_by_category[target.category] = counts_by_category.get(target.category, 0) + 1
    source_ref = f"local://{Path(path).as_posix()}"
    payload = {
        "read_only": True,
        "allowed_effects": list(ALLOWED_EFFECTS),
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "dynamic_research_suggestions": loaded.get("dynamic_research_suggestions", {}),
        "counts_by_platform": counts_by_platform,
        "counts_by_category": counts_by_category,
        "targets": [target.model_dump() for target in targets],
    }
    return evidence_packet(
        source_name="social_watchlist",
        evidence_type="attention_targets",
        subject="operator_social_watchlists",
        source_ref=source_ref,
        payload=payload,
        quality="low",
        request_fingerprint=request_hash("READ", source_ref, None, payload),
        tool_route="local_social_watchlist",
        redaction_status="no_secrets_seen",
        freshness_extra={"read_only": True, "target_count": len(targets)},
    )
