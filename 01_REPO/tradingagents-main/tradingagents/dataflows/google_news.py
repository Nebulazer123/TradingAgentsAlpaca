"""Google News RSS evidence adapter.

Google News RSS is used as a lightweight, no-key news context source. It is
not treated as official market data and cannot drive trade execution.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

from ._official_common import (
    DataTransportError,
    OfficialDataError,
    evidence_packet,
    get_text,
    request_hash,
    safe_source_ref,
)

BASE_URL = "https://news.google.com/rss"


def _parse_date_bound(value: str | None, *, end_of_day: bool) -> dt.datetime | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            date_value = dt.date.fromisoformat(value)
            time_value = dt.time.max if end_of_day else dt.time.min
            return dt.datetime.combine(date_value, time_value, tzinfo=dt.timezone.utc)
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfficialDataError(f"Invalid Google News RSS date filter: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _parse_item_date(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _item_in_date_window(
    item: dict[str, str],
    *,
    start: dt.datetime | None,
    end: dt.datetime | None,
) -> bool:
    if start is None and end is None:
        return True
    published = _parse_item_date(item.get("published", ""))
    if published is None:
        return False
    if start is not None and published < start:
        return False
    return not (end is not None and published > end)


def _parse_rss(
    text: str,
    *,
    limit: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise DataTransportError("Google News RSS returned invalid XML") from exc
    channel = root.find("channel")
    if channel is None:
        raise DataTransportError("Google News RSS response has no channel")
    start = _parse_date_bound(start_date, end_of_day=False)
    end = _parse_date_bound(end_date, end_of_day=True)
    raw_items = []
    for item in channel.findall("item"):
        raw_items.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
                "source": (item.findtext("source") or "").strip(),
            }
        )
    filtered_items = [
        item
        for item in raw_items
        if _item_in_date_window(item, start=start, end=end)
    ]
    items = filtered_items[: max(1, min(int(limit), 100))]
    return {
        "channel": {
            "title": (channel.findtext("title") or "").strip(),
            "link": (channel.findtext("link") or "").strip(),
            "description": (channel.findtext("description") or "").strip(),
        },
        "items": items,
        "unfiltered_item_count": len(raw_items),
        "filtered_out_count": max(0, len(raw_items) - len(filtered_items)),
        "date_filter": {
            "start_date": start_date,
            "end_date": end_date,
        },
    }


def fetch_google_news_rss(
    *,
    query: str | None = None,
    hl: str = "en-US",
    gl: str = "US",
    ceid: str = "US:en",
    limit: int = 50,
    start_date: str | None = None,
    end_date: str | None = None,
    session: Any | None = None,
) -> Any:
    params = {"hl": hl, "gl": gl, "ceid": ceid}
    url = BASE_URL
    subject = "top_stories"
    if query and query.strip():
        url = f"{BASE_URL}/search"
        params["q"] = query.strip()
        subject = query.strip()
    text = get_text(
        url,
        params=params,
        session=session,
        timeout=20,
        connector_name="google_news_rss",
    )
    payload = _parse_rss(text, limit=limit, start_date=start_date, end_date=end_date)
    return evidence_packet(
        source_name="google_news_rss",
        evidence_type="news_rss",
        subject=subject,
        source_ref=safe_source_ref(url, params),
        payload=payload,
        quality="low",
        request_fingerprint=request_hash("GET", url, params, None),
        tool_route="google_news_rss",
        freshness_extra={
            "item_count": len(payload["items"]),
            "unfiltered_item_count": payload["unfiltered_item_count"],
            "filtered_out_count": payload["filtered_out_count"],
            "date_filter": payload["date_filter"],
        },
    )
