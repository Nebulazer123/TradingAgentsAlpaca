"""Read-only Docker MCP bridge for Twitter/X social research evidence."""

from __future__ import annotations

import datetime
import json
import subprocess
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

from tradingagents.dataflows._official_common import (
    DataTransportError,
    OfficialDataError,
    evidence_packet,
    request_hash,
)
from tradingagents.schemas.research import SourceEvidencePacket

UTC = datetime.timezone.utc
DEFAULT_DOCKER_PROFILE = "profile"
TWITTER_RECENT_SEARCH_TOOL = "twitter-research__twitter_recent_search"

FORBIDDEN_EFFECTS = [
    "post",
    "comment",
    "vote",
    "message",
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
]


def _now_iso(now: datetime.datetime | None = None) -> str:
    current = now or datetime.datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds")


def _extract_json_payload(stdout: str) -> dict[str, Any]:
    start = stdout.find("{")
    if start < 0:
        raise DataTransportError("twitter-research MCP returned no JSON object")
    try:
        payload = json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise DataTransportError("twitter-research MCP returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DataTransportError(
            "twitter-research MCP returned a non-object JSON payload"
        )
    return payload


def _call_docker_mcp_tool(
    tool_name: str,
    args: Sequence[str],
    *,
    profile: str = DEFAULT_DOCKER_PROFILE,
    timeout_seconds: int = 30,
    run_func: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    command = [
        "docker",
        "mcp",
        "tools",
        "call",
        tool_name,
        *args,
        "--gateway-arg=--profile",
        f"--gateway-arg={profile}",
        "--format",
        "json",
    ]
    try:
        completed = run_func(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DataTransportError(
            f"twitter-research MCP timed out after {timeout_seconds}s"
        ) from exc
    except OSError as exc:
        raise DataTransportError(
            f"twitter-research MCP command unavailable: {type(exc).__name__}"
        ) from exc
    if completed.returncode != 0:
        stderr = str(completed.stderr or "").strip()
        detail = stderr[:240] if stderr else "docker MCP tool call failed"
        raise DataTransportError(f"twitter-research MCP failed: {detail}")
    return _extract_json_payload(str(completed.stdout or ""))


def _twitter_query(symbol: str) -> str:
    ticker = symbol.strip().upper()
    return f"{ticker} stock -is:retweet lang:en"


def _blocked_twitter_packet(
    *,
    symbol: str,
    evidence_need: str,
    query: str,
    result: dict[str, Any],
    now: datetime.datetime | None,
) -> SourceEvidencePacket:
    reason = result.get("note") or result.get("error") or result.get("status") or "twitter recent search blocked"
    payload = {
        "symbol": symbol,
        "evidence_need": evidence_need,
        "query": query,
        "status": "blocked",
        "blocked_reason": reason,
        "twitter_result": result,
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "operator_note": (
            "Twitter/X bridge is reachable, but recent-search output is unavailable. "
            "Use this as a source-gap signal, not as market evidence."
        ),
    }
    source_ref = f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"
    return evidence_packet(
        source_name="twitter",
        evidence_type=evidence_need,
        subject=f"Docker MCP Twitter/X social context for {symbol}",
        symbol=symbol,
        source_ref=source_ref,
        payload=payload,
        quality="unknown",
        as_of=_now_iso(now),
        stale=True,
        request_fingerprint=request_hash(
            "MCP_TOOLS_CALL",
            source_ref,
            {"query": query, "max_results": result.get("max_results")},
            None,
        ),
        tool_route="docker:twitter-research",
        redaction_status="blocked",
        freshness_extra={
            "read_only": True,
            "route": "docker:twitter-research",
            "blocked": True,
            "mcp_tool": TWITTER_RECENT_SEARCH_TOOL,
            "status": result.get("status"),
        },
    )


def fetch_twitter_recent_search_packet(
    symbol: str,
    *,
    evidence_need: str = "social_sentiment",
    max_results: int = 10,
    now: datetime.datetime | None = None,
    timeout_seconds: int = 30,
    run_func: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SourceEvidencePacket:
    """Fetch read-only Twitter/X recent-search evidence through Docker MCP."""

    ticker = symbol.strip().upper()
    if not ticker:
        raise OfficialDataError("twitter-research MCP requires a ticker symbol")
    bounded_max = min(max(10, int(max_results)), 100)
    query = _twitter_query(ticker)
    result = _call_docker_mcp_tool(
        TWITTER_RECENT_SEARCH_TOOL,
        ["query", query, "max_results", str(bounded_max)],
        timeout_seconds=timeout_seconds,
        run_func=run_func,
    )
    result.setdefault("max_results", bounded_max)
    if result.get("ok") is False or result.get("status") in {401, 403, 429}:
        return _blocked_twitter_packet(
            symbol=ticker,
            evidence_need=evidence_need,
            query=query,
            result=result,
            now=now,
        )

    source_ref = f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"
    payload = {
        "symbol": ticker,
        "evidence_need": evidence_need,
        "query": query,
        "max_results": bounded_max,
        "twitter_result": result,
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": FORBIDDEN_EFFECTS,
        "operator_note": (
            "Low-authority social attention evidence. Validate against price, volume, "
            "options liquidity, broker execution, and independent news before using it."
        ),
    }
    return evidence_packet(
        source_name="twitter",
        evidence_type=evidence_need,
        subject=f"Docker MCP Twitter/X social context for {ticker}",
        symbol=ticker,
        source_ref=source_ref,
        payload=payload,
        quality="low",
        as_of=_now_iso(now),
        request_fingerprint=request_hash(
            "MCP_TOOLS_CALL",
            source_ref,
            {"query": query, "max_results": bounded_max},
            None,
        ),
        tool_route="docker:twitter-research",
        redaction_status="redacted",
        freshness_extra={
            "read_only": True,
            "route": "docker:twitter-research",
            "blocked": False,
            "mcp_tool": TWITTER_RECENT_SEARCH_TOOL,
            "status": result.get("status"),
        },
    )
