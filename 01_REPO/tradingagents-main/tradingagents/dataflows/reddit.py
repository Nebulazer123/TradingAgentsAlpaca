"""Reddit search fetcher for ticker-specific discussion posts.

Uses Reddit's public JSON endpoints (``reddit.com/r/{sub}/search.json``)
which do not require an API key. Public throughput is ~10 requests per
minute per IP, well within budget for a single agent run that queries
a handful of finance subreddits per ticker.

Returns formatted plaintext blocks ready for prompt injection. Degrades
gracefully — returns a placeholder string rather than raising, so callers
never have to special-case missing data.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import urlencode

from tradingagents.dataflows._official_common import (
    OfficialDataError,
    get_text_response,
    record_connector_health,
)

logger = logging.getLogger(__name__)

_API = "https://www.reddit.com/r/{sub}/search.json?{qs}"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# Default subreddits ordered roughly by signal density for ticker-specific
# discussion. wallstreetbets has the most volume but most noise; stocks /
# investing trend more measured. Caller can override.
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


def _fetch_subreddit(
    ticker: str,
    sub: str,
    limit: int,
    timeout: float,
    time_filter: str,
) -> list[dict] | None:
    qs = urlencode({
        "q": ticker,
        "restrict_sr": "on",
        "sort": "new",
        "t": time_filter,
        "limit": limit,
    })
    url = _API.format(sub=sub, qs=qs)
    try:
        result = get_text_response(
            url,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=timeout,
            connector_name="reddit_public",
        )
        payload = json.loads(result.text)
    except OfficialDataError as exc:
        if "HTTP 403" in str(exc):
            logger.warning("Reddit public endpoint blocked for r/%s · %s: %s", sub, ticker, exc)
            return None
        logger.warning("Reddit fetch failed for r/%s · %s: %s", sub, ticker, exc)
        return []
    except json.JSONDecodeError as exc:
        record_connector_health(
            "reddit_public",
            success=False,
            error="JSONDecodeError: Reddit public endpoint returned invalid JSON",
            write=True,
        )
        logger.warning("Reddit fetch failed for r/%s · %s: %s", sub, ticker, exc)
        return []
    children = (payload.get("data") or {}).get("children") or []
    return [c.get("data", {}) for c in children if isinstance(c, dict)]


def _parse_window_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _created_utc_date(value: object) -> datetime.date | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


def _date_window_label(start_date: str | None, end_date: str | None) -> str:
    if start_date and end_date:
        return f"{start_date} to {end_date}"
    if start_date:
        return f"since {start_date}"
    if end_date:
        return f"through {end_date}"
    return "the past 7 days"


def _reddit_time_filter(start_date: str | None, end_date: str | None) -> str:
    start = _parse_window_date(start_date)
    end = _parse_window_date(end_date)
    if start and end:
        days = max(0, (end - start).days)
        if days <= 1:
            return "day"
        if days <= 7:
            return "week"
        if days <= 31:
            return "month"
        if days <= 366:
            return "year"
        return "all"
    return "week"


def _in_date_window(post: dict, start_date: str | None, end_date: str | None) -> bool:
    created = _created_utc_date(post.get("created_utc"))
    if created is None:
        return True
    start = _parse_window_date(start_date)
    end = _parse_window_date(end_date)
    if start and created < start:
        return False
    return not (end and created > end)


def fetch_reddit_posts(
    ticker: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 0.4,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Fetch recent Reddit posts mentioning ``ticker`` across finance
    subreddits and return them as a formatted plaintext block.

    ``inter_request_delay`` keeps us under Reddit's public rate limit
    (~10 req/min per IP) even if the caller queries many subreddits.
    """
    blocks = []
    total_posts = 0
    time_filter = _reddit_time_filter(start_date, end_date)
    window_label = _date_window_label(start_date, end_date)
    for i, sub in enumerate(subreddits):
        if i > 0:
            time.sleep(inter_request_delay)
        posts = _fetch_subreddit(ticker, sub, limit_per_sub, timeout, time_filter)
        if posts is None:
            blocks.append(
                "Reddit public endpoint returned HTTP 403 for "
                f"r/{sub} while fetching {ticker.upper()}; skipped remaining "
                "public Reddit queries. Add official Reddit API credentials "
                "or use another social data vendor to restore this source."
            )
            break
        posts = [post for post in posts if _in_date_window(post, start_date, end_date)]
        total_posts += len(posts)
        if not posts:
            blocks.append(f"r/{sub}: <no posts found mentioning {ticker.upper()} in {window_label}>")
            continue

        lines = [f"r/{sub} — {len(posts)} posts mentioning {ticker.upper()} in {window_label}:"]
        for p in posts:
            title = (p.get("title") or "").replace("\n", " ").strip()
            score = p.get("score", 0)
            comments = p.get("num_comments", 0)
            created = p.get("created_utc")
            created_str = (
                time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "?"
            )
            selftext = (p.get("selftext") or "").replace("\n", " ").strip()
            if len(selftext) > 240:
                selftext = selftext[:240] + "…"
            lines.append(
                f"  [{created_str} · {score:>4}↑ · {comments:>3}c] {title}"
                + (f"\n    body excerpt: {selftext}" if selftext else "")
            )
        blocks.append("\n".join(lines))

    if total_posts == 0 and any("HTTP 403" in block for block in blocks):
        return "\n\n".join(blocks)
    if total_posts == 0:
        return (
            f"<no Reddit posts found mentioning {ticker.upper()} across "
            f"{', '.join(f'r/{s}' for s in subreddits)} in {window_label}>"
        )
    return "\n\n".join(blocks)
