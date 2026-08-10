"""ScrapingBee fallback evidence adapter.

The main production crawler remains Crawlee + Playwright. ScrapingBee is a
paid-credit fallback for allowed research pages when local crawling is blocked.
It writes compact metadata/preview packets instead of raw full-page archives.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from tradingagents.research.crawler_policy import domain_allowed

from ._official_common import (
    OfficialDataError,
    env_value,
    evidence_packet,
    get_text_response,
    request_hash,
    safe_source_ref,
)

BASE_URL = "https://app.scrapingbee.com/api/v1"
DEFAULT_ALLOWED_DOMAINS = (
    "news.google.com",
    "google.com",
    "sec.gov",
    "federalreserve.gov",
    "bls.gov",
    "bea.gov",
    "treasury.gov",
    "eia.gov",
    "cnbc.com",
    "finance.yahoo.com",
    "marketwatch.com",
    "reuters.com",
    "wsj.com",
    "finnhub.io",
    "financialmodelingprep.com",
    "eodhd.com",
    "marketaux.com",
)
MAX_PREVIEW_CHARS = 5_000


def _api_key(explicit: str | None = None) -> str:
    return env_value("SCRAPINGBEE_API_KEY", explicit, required=True) or ""


def _target_url(value: str) -> str:
    clean = value.strip()
    parsed = urlsplit(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OfficialDataError("ScrapingBee target must be an http(s) URL with a hostname")
    return clean


def _bool_param(value: bool) -> str:
    return str(bool(value))


def fetch_scrapingbee_html(
    target_url: str,
    *,
    api_key: str | None = None,
    session: Any | None = None,
    allowed_domains: tuple[str, ...] = DEFAULT_ALLOWED_DOMAINS,
    render_js: bool = False,
    block_ads: bool = True,
    timeout_ms: int = 10_000,
    wait_browser: str | None = None,
) -> Any:
    target = _target_url(target_url)
    host = urlsplit(target).hostname or ""
    if not domain_allowed(host, allowed_domains):
        raise OfficialDataError("ScrapingBee target domain is not allowlisted")

    params: dict[str, Any] = {
        "api_key": _api_key(api_key),
        "url": target,
        "render_js": _bool_param(render_js),
        "block_ads": _bool_param(block_ads),
        "timeout": max(1_000, min(int(timeout_ms), 60_000)),
    }
    if wait_browser:
        params["wait_browser"] = wait_browser

    response = get_text_response(
        BASE_URL,
        params=params,
        session=session,
        timeout=30,
        connector_name="scrapingbee",
    )
    text = response.text

    safe_target = safe_source_ref(target)
    safe_params = dict(params)
    safe_params["url"] = safe_target
    content_type = ""
    headers = response.headers
    if isinstance(headers, dict):
        content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    payload = {
        "target_url": safe_target,
        "status_code": response.status_code,
        "content_type": content_type,
        "content_length": len(text),
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_preview": text[:MAX_PREVIEW_CHARS],
    }
    return evidence_packet(
        source_name="scrapingbee",
        evidence_type="scraped_page",
        subject=safe_target,
        source_ref=safe_source_ref(BASE_URL, safe_params),
        payload=payload,
        quality="low",
        request_fingerprint=request_hash("GET", BASE_URL, safe_params, None),
        tool_route="scrapingbee_api",
        freshness_extra={
            "read_only": True,
            "allowed_domains": list(allowed_domains),
            "preview_truncated": len(text) > MAX_PREVIEW_CHARS,
        },
    )
