"""Crawler policy and packet helpers for research-only web evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from tradingagents.schemas.research import CrawlerRunPacket

DEFAULT_CRAWLER = "crawlee_playwright"


@dataclass(frozen=True)
class CrawlerPolicy:
    allowed_domains: tuple[str, ...]
    max_pages: int = 25
    max_bytes: int = 5_000_000
    rate_limit_per_minute: int = 30
    robots_policy: str = "respect"


@dataclass(frozen=True)
class CrawlerDecision:
    allowed: bool
    reason: str
    hostname: str


def hostname_for_url(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().strip(".")


def domain_allowed(hostname: str, allowed_domains: tuple[str, ...]) -> bool:
    normalized_host = hostname.lower().strip(".")
    for domain in allowed_domains:
        normalized_domain = domain.lower().strip(".")
        if not normalized_domain:
            continue
        if normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}"):
            return True
    return False


def evaluate_crawler_target(url: str, policy: CrawlerPolicy) -> CrawlerDecision:
    hostname = hostname_for_url(url)
    if not hostname:
        return CrawlerDecision(False, "target URL has no hostname", hostname)
    if not domain_allowed(hostname, policy.allowed_domains):
        return CrawlerDecision(False, "target domain is not allowlisted", hostname)
    return CrawlerDecision(True, "target domain is allowlisted", hostname)


def crawler_run_packet(
    *,
    run_id: str,
    target: str,
    policy: CrawlerPolicy,
    fetched_urls: list[str] | None = None,
    blocked_urls: list[str] | None = None,
    crawler: str = DEFAULT_CRAWLER,
) -> CrawlerRunPacket:
    decision = evaluate_crawler_target(target, policy)
    fetched = list(fetched_urls or [])
    blocked = list(blocked_urls or [])
    status: Literal["success", "partial", "blocked", "failed"] = "success"
    if not decision.allowed:
        status = "blocked"
        blocked.append(target)
    elif blocked:
        status = "partial"
    return CrawlerRunPacket(
        run_id=run_id,
        crawler=crawler,
        target=target,
        status=status,
        fetched_urls=fetched[: policy.max_pages],
        blocked_urls=blocked,
        max_pages=policy.max_pages,
        robots_policy=policy.robots_policy,
        source_refs=[target],
        freshness={
            "target_policy": {
                "allowed": decision.allowed,
                "reason": decision.reason,
                "hostname": decision.hostname,
                "allowed_domains": list(policy.allowed_domains),
                "max_bytes": policy.max_bytes,
                "rate_limit_per_minute": policy.rate_limit_per_minute,
            }
        },
        tool_route="crawler:crawlee_playwright",
        redaction_status="redacted",
    )
