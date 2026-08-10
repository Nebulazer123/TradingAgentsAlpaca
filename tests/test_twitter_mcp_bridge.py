import subprocess
from types import SimpleNamespace

import pytest

from tradingagents.dataflows._official_common import OfficialDataError
from tradingagents.research.twitter_mcp import (
    _extract_json_payload,
    fetch_twitter_recent_search_packet,
)


def _completed(stdout: str = "{}", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def test_extract_json_payload_ignores_docker_timing_prefix():
    payload = _extract_json_payload('Tool call took: 3.1s\n{"ok": true, "data": []}')

    assert payload == {"ok": True, "data": []}


def test_twitter_mcp_success_packet_is_read_only_social_evidence():
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _completed(
            'Tool call took: 1s\n{"ok": true, "data": [{"id": "1", "text": "NVDA stock"}]}'
        )

    packet = fetch_twitter_recent_search_packet("nvda", run_func=fake_run)

    assert packet.source_name == "twitter"
    assert packet.evidence_type == "social_sentiment"
    assert packet.symbol == "NVDA"
    assert packet.quality == "low"
    assert packet.tool_route == "docker:twitter-research"
    assert packet.freshness["blocked"] is False
    assert packet.payload["execution_authority"] == "none"
    assert "submit_order" in packet.payload["forbidden_effects"]
    command = calls[0][0]
    assert command[:5] == [
        "docker",
        "mcp",
        "tools",
        "call",
        "twitter-research__twitter_recent_search",
    ]
    assert "query" in command
    assert "max_results" in command
    assert "--gateway-arg=profile" in command


def test_twitter_mcp_unauthorized_recent_search_becomes_blocked_packet():
    def fake_run(*_args, **_kwargs):
        return _completed(
            'Tool call took: 1s\n{"ok": false, "status": 401, '
            '"note": "Recent search requires Basic or higher."}'
        )

    packet = fetch_twitter_recent_search_packet("NVDA", run_func=fake_run)

    assert packet.source_name == "twitter"
    assert packet.redaction_status == "blocked"
    assert packet.quality == "unknown"
    assert packet.freshness["blocked"] is True
    assert packet.payload["status"] == "blocked"
    assert "Basic or higher" in packet.payload["blocked_reason"]
    assert packet.payload["execution_authority"] == "none"


def test_twitter_mcp_timeout_raises_official_data_error():
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=15)

    with pytest.raises(OfficialDataError, match="timed out"):
        fetch_twitter_recent_search_packet("NVDA", run_func=fake_run)
