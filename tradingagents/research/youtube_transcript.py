"""Read-only YouTube transcript bridge for earnings-call evidence."""

from __future__ import annotations

import datetime
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote_plus

import requests

from tradingagents.dataflows._official_common import (
    DataTransportError,
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
    evidence_packet,
    request_hash,
)
from tradingagents.schemas.research import SourceEvidencePacket

UTC = datetime.timezone.utc
DEFAULT_DOCKER_PROFILE = "profile"
YOUTUBE_TRANSCRIPT_TOOL = "youtube_transcript__get_transcript"
YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={query}"

EARNINGS_RELEVANCE_TERMS = (
    "earnings",
    "earnings call",
    "conference call",
    "quarter",
    "quarterly results",
    "results call",
    "q1",
    "q2",
    "q3",
    "q4",
)

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
        raise DataTransportError("youtube_transcript MCP returned no JSON object")
    try:
        payload = json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise DataTransportError("youtube_transcript MCP returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DataTransportError(
            "youtube_transcript MCP returned a non-object JSON payload"
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
            f"youtube_transcript MCP timed out after {timeout_seconds}s"
        ) from exc
    except OSError as exc:
        raise DataTransportError(
            f"youtube_transcript MCP command unavailable: {type(exc).__name__}"
        ) from exc
    if completed.returncode != 0:
        stderr = str(completed.stderr or completed.stdout or "").strip()
        detail = stderr[:240] if stderr else "docker MCP tool call failed"
        raise DataTransportError(f"youtube_transcript MCP failed: {detail}")
    return _extract_json_payload(str(completed.stdout or ""))


def _ticker(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise OfficialDataError("youtube transcript search requires a ticker symbol")
    return clean


def _search_query(symbol: str) -> str:
    return f"{symbol} earnings call transcript"


def _discover_youtube_video_urls(
    symbol: str,
    *,
    max_candidates: int = 5,
    session: Any = requests,
    timeout_seconds: int = 12,
) -> list[str]:
    query = _search_query(symbol)
    url = YOUTUBE_SEARCH_URL.format(query=quote_plus(query))
    try:
        response = session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 TradingAgents research bot"},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise DataTransportError(
            f"YouTube transcript discovery failed: {type(exc).__name__}"
        ) from exc
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code >= 400:
        raise DataTransportError(
            f"YouTube transcript discovery returned HTTP {status_code}"
        )
    html = str(getattr(response, "text", "") or "")
    video_ids: list[str] = []
    for match in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
        video_id = match.group(1)
        if video_id not in video_ids:
            video_ids.append(video_id)
        if len(video_ids) >= max(1, int(max_candidates)):
            break
    if not video_ids:
        raise DataUnavailableError(
            "YouTube transcript discovery found no video candidates"
        )
    return [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids]


def _transcript_text(result: dict[str, Any]) -> str:
    for key in ("transcript", "text", "content"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _title(result: dict[str, Any]) -> str:
    value = result.get("title")
    return value.strip() if isinstance(value, str) else ""


def _looks_like_earnings_call(*, title: str, transcript: str) -> bool:
    haystack = f"{title}\n{transcript[:5000]}".lower()
    return any(term in haystack for term in EARNINGS_RELEVANCE_TERMS)


def _fetch_transcript_json(
    youtube_url: str,
    *,
    timeout_seconds: int,
    run_func: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    result = _call_docker_mcp_tool(
        YOUTUBE_TRANSCRIPT_TOOL,
        [f"url={youtube_url}"],
        timeout_seconds=timeout_seconds,
        run_func=run_func,
    )
    transcript = _transcript_text(result)
    if not transcript:
        raise DataUnavailableError(
            "youtube_transcript MCP returned no transcript text"
        )
    return result


def fetch_youtube_earnings_transcript_packet(
    symbol: str,
    *,
    now: datetime.datetime | None = None,
    max_video_candidates: int = 3,
    min_transcript_chars: int = 500,
    max_transcript_chars: int = 50_000,
    session: Any = requests,
    timeout_seconds: int = 30,
    run_func: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SourceEvidencePacket:
    """Fetch a read-only earnings transcript through the Docker YouTube MCP route."""

    ticker = _ticker(symbol)
    urls = _discover_youtube_video_urls(
        ticker,
        max_candidates=max_video_candidates,
        session=session,
        timeout_seconds=min(timeout_seconds, 15),
    )
    errors: list[str] = []
    recoverable_failures: list[RecoverableDataflowError] = []
    for youtube_url in urls:
        try:
            result = _fetch_transcript_json(
                youtube_url,
                timeout_seconds=timeout_seconds,
                run_func=run_func,
            )
        except RecoverableDataflowError as exc:
            recoverable_failures.append(exc)
            errors.append(f"{youtube_url}: {exc}")
            continue
        transcript = _transcript_text(result)
        title = _title(result)
        if len(transcript) < max(1, int(min_transcript_chars)):
            errors.append(f"{youtube_url}: transcript shorter than minimum")
            continue
        if not _looks_like_earnings_call(title=title, transcript=transcript):
            errors.append(f"{youtube_url}: transcript did not look like an earnings call")
            continue
        bounded_chars = max(1, int(max_transcript_chars))
        truncated = len(transcript) > bounded_chars
        payload = {
            "symbol": ticker,
            "title": title,
            "youtube_url": youtube_url,
            "search_query": _search_query(ticker),
            "candidate_urls": urls,
            "transcript_text": transcript[:bounded_chars],
            "transcript_char_count": len(transcript),
            "transcript_truncated": truncated,
            "read_only": True,
            "analysis_only": True,
            "execution_authority": "none",
            "forbidden_effects": FORBIDDEN_EFFECTS,
            "operator_note": (
                "YouTube transcript evidence is useful for guidance-tone extraction, "
                "but validate it against filings, official IR, and price/volume context."
            ),
        }
        return evidence_packet(
            source_name="youtube_transcript",
            evidence_type="earnings_transcripts",
            subject=f"YouTube earnings-call transcript for {ticker}",
            symbol=ticker,
            source_ref=youtube_url,
            payload=payload,
            quality="medium",
            as_of=_now_iso(now),
            request_fingerprint=request_hash(
                "MCP_TOOLS_CALL",
                youtube_url,
                {
                    "symbol": ticker,
                    "search_query": _search_query(ticker),
                    "max_video_candidates": max_video_candidates,
                    "max_transcript_chars": bounded_chars,
                },
                None,
            ),
            tool_route="docker:youtube_transcript",
            redaction_status="redacted",
            freshness_extra={
                "read_only": True,
                "route": "docker:youtube_transcript",
                "blocked": False,
                "mcp_tool": YOUTUBE_TRANSCRIPT_TOOL,
                "candidate_count": len(urls),
                "transcript_truncated": truncated,
            },
        )
    detail = "; ".join(errors[:3]) if errors else "no transcript candidates were usable"
    if recoverable_failures and len(recoverable_failures) == len(urls) and all(
        isinstance(exc, DataTransportError) for exc in recoverable_failures
    ):
        raise DataTransportError(
            f"YouTube earnings transcript transport failed for {ticker}: {detail}"
        )
    raise DataUnavailableError(
        f"YouTube earnings transcript unavailable for {ticker}: {detail}"
    )
