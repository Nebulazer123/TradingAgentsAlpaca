"""Reddit market-sentiment watchlists and compact summary schema.

Reddit is useful as a mood sensor. It is not trade truth, cannot create trade
intents, and should default to recent listing/search pages.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tradingagents.dataflows._official_common import evidence_packet, request_hash
from tradingagents.research.tool_routing import validate_autonomous_research_route

DEFAULT_REDDIT_WATCHLIST_PATH = Path("config/reddit_market_watchlists.json")
REDDIT_ROUTE = "composio:reddit"
REQUIRED_BUCKETS = (
    "core_market_pulse",
    "retail_speculative_heat",
    "macro_fear_context",
    "ai_semiconductor_theme",
    "dynamic_ticker_pages",
    "reddit_search_queries",
)
ALLOWED_CONTEXT_FLAGS = (
    "retail_panic",
    "retail_euphoria",
    "buy_the_dip_chatter",
    "squeeze_hype",
    "macro_fear",
    "earnings_reaction",
    "no_signal",
)
DRILLDOWN_TRIGGERS = (
    "open_position",
    "overnight_top_candidate",
    "paper_tournament_candidate",
    "major_macro_event",
    "major_ticker_spike",
    "unusually_high_engagement",
)
COMPACT_FIELDS = (
    "source_url",
    "subreddit",
    "post_time",
    "post_title",
    "post_url",
    "ticker_mentions",
    "theme",
    "sentiment",
    "confidence",
    "engagement",
    "why_it_matters",
    "open_raw_thread",
)


@dataclass(frozen=True)
class RedditWatchTarget:
    bucket: str
    source_url: str
    mode: Literal["subreddit_new", "reddit_search_new_day"]
    subreddit: str | None
    query: str | None
    route: str = REDDIT_ROUTE
    recent_only: bool = True
    read_only: bool = True
    raw_thread_default: bool = False

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


class RedditEngagement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upvotes: int | None = None
    comments: int | None = None


class RedditCompactSummary(BaseModel):
    """Compact Reddit post summary stored for trading research context."""

    model_config = ConfigDict(extra="forbid")

    source_url: str
    subreddit: str
    post_time: str
    post_title: str
    post_url: str
    ticker_mentions: list[str] = Field(default_factory=list)
    theme: Literal[
        "macro_fear",
        "ticker_hype",
        "earnings_reaction",
        "buy_the_dip",
        "short_squeeze",
        "bearish_warning",
        "no_signal",
    ] = "no_signal"
    sentiment: Literal["panic", "bearish", "neutral", "bullish", "euphoric"] = "neutral"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    engagement: RedditEngagement = Field(default_factory=RedditEngagement)
    why_it_matters: str = ""
    open_raw_thread: bool = False

    @field_validator("ticker_mentions")
    @classmethod
    def normalize_tickers(cls, value: list[str]) -> list[str]:
        return [
            ticker.strip().upper().lstrip("$")
            for ticker in value
            if ticker and ticker.strip()
        ]

    @field_validator("why_it_matters")
    @classmethod
    def keep_one_sentence(cls, value: str) -> str:
        clean = " ".join(value.split())
        return clean[:280]


def load_reddit_watchlist_config(path: str | Path = DEFAULT_REDDIT_WATCHLIST_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _reddit_host(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host != "reddit.com":
        raise ValueError("Reddit watchlist URL must be an http(s) reddit.com URL")
    return host


def _subreddit_from_path(path: str) -> str | None:
    match = re.match(r"^/r/([^/]+)/", path, flags=re.IGNORECASE)
    return match.group(1) if match else None


def classify_reddit_watch_url(url: str) -> RedditWatchTarget:
    clean = url.strip()
    _reddit_host(clean)
    parsed = urlsplit(clean)
    path = parsed.path
    params = parse_qs(parsed.query)
    subreddit = _subreddit_from_path(path)
    if subreddit and path.rstrip("/").lower().endswith("/new"):
        mode: Literal["subreddit_new", "reddit_search_new_day"] = "subreddit_new"
        query = None
    elif path.rstrip("/").lower() in {"/search", "/r/" + (subreddit or "").lower() + "/search"} or path.rstrip("/").lower().endswith("/search"):
        if params.get("sort", [""])[0].lower() != "new" or params.get("t", [""])[0].lower() != "day":
            raise ValueError("Reddit search links must use sort=new&t=day by default")
        mode = "reddit_search_new_day"
        query = params.get("q", [""])[0].strip() or None
    else:
        raise ValueError("Reddit watchlist URL must be a /new listing or sort=new&t=day search")
    decision = validate_autonomous_research_route(REDDIT_ROUTE, "read")
    if not decision.allowed:
        raise ValueError(decision.reason)
    return RedditWatchTarget(
        bucket="unassigned",
        source_url=clean,
        mode=mode,
        subreddit=subreddit,
        query=query,
    )


def flatten_reddit_watchlists(config: dict[str, Any]) -> list[RedditWatchTarget]:
    raw_watchlists = config.get("reddit_watchlists", {})
    missing = [bucket for bucket in REQUIRED_BUCKETS if bucket not in raw_watchlists]
    if missing:
        raise ValueError(f"missing Reddit watchlist bucket(s): {', '.join(missing)}")
    targets: list[RedditWatchTarget] = []
    for bucket in REQUIRED_BUCKETS:
        urls = raw_watchlists.get(bucket)
        if not isinstance(urls, list):
            raise ValueError(f"Reddit watchlist bucket {bucket!r} must be a list")
        for url in urls:
            target = classify_reddit_watch_url(str(url))
            targets.append(
                RedditWatchTarget(
                    bucket=bucket,
                    source_url=target.source_url,
                    mode=target.mode,
                    subreddit=target.subreddit,
                    query=target.query,
                )
            )
    return targets


def compact_reddit_summary(**values: Any) -> RedditCompactSummary:
    """Validate and normalize a single compact Reddit post summary."""

    return RedditCompactSummary(**values)


def should_open_raw_thread(
    summary: RedditCompactSummary,
    *,
    trigger_reasons: list[str] | tuple[str, ...] | None = None,
) -> bool:
    triggers = {reason for reason in trigger_reasons or () if reason in DRILLDOWN_TRIGGERS}
    return bool(
        triggers
        or summary.open_raw_thread
        or (summary.engagement.comments is not None and summary.engagement.comments >= 250)
    )


def build_reddit_watchlist_packet(
    *,
    config: dict[str, Any] | None = None,
    path: str | Path = DEFAULT_REDDIT_WATCHLIST_PATH,
) -> Any:
    loaded = config if config is not None else load_reddit_watchlist_config(path)
    targets = flatten_reddit_watchlists(loaded)
    counts_by_bucket = {bucket: 0 for bucket in REQUIRED_BUCKETS}
    mode_counts: dict[str, int] = {}
    for target in targets:
        counts_by_bucket[target.bucket] = counts_by_bucket.get(target.bucket, 0) + 1
        mode_counts[target.mode] = mode_counts.get(target.mode, 0) + 1
    source_ref = f"local://{Path(path).as_posix()}"
    payload = {
        "read_only": True,
        "route": REDDIT_ROUTE,
        "source_role": "social/context feed, not trade truth",
        "required_buckets": list(REQUIRED_BUCKETS),
        "allowed_context_flags": list(ALLOWED_CONTEXT_FLAGS),
        "drilldown_triggers": list(DRILLDOWN_TRIGGERS),
        "compact_fields": list(COMPACT_FIELDS),
        "policy": loaded.get("policy", {}),
        "polling_cadence": loaded.get("polling_cadence", {}),
        "low_quality_or_historical_only": loaded.get("low_quality_or_historical_only", {}),
        "counts_by_bucket": counts_by_bucket,
        "mode_counts": mode_counts,
        "targets": [target.model_dump() for target in targets],
    }
    return evidence_packet(
        source_name="reddit_watchlist",
        evidence_type="market_sentiment_watchlist",
        subject="reddit_recent_market_sentiment",
        source_ref=source_ref,
        payload=payload,
        quality="low",
        request_fingerprint=request_hash("READ", source_ref, None, payload),
        tool_route="local_reddit_watchlist",
        redaction_status="no_secrets_seen",
        freshness_extra={"read_only": True, "target_count": len(targets)},
    )
