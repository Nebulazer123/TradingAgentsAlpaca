import json
import subprocess
from types import SimpleNamespace

import pytest
import requests

from tradingagents.dataflows._official_common import (
    DataTransportError,
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
)
from tradingagents.research.youtube_transcript import (
    _extract_json_payload,
    fetch_youtube_earnings_transcript_packet,
)


def _completed(stdout: str = "{}", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def _response(text: str, status_code: int = 200):
    return SimpleNamespace(text=text, status_code=status_code)


def test_extract_json_payload_ignores_docker_timing_prefix():
    payload = _extract_json_payload('Tool call took: 4s\n{"title": "Q1", "transcript": "text"}')

    assert payload == {"title": "Q1", "transcript": "text"}


def test_youtube_transcript_success_packet_is_read_only_earnings_evidence():
    calls = []
    transcript = "Q1 earnings call prepared remarks and quarterly results. " * 20

    def fake_get(url, **kwargs):
        assert "NVDA+earnings+call+transcript" in url
        return _response('"videoId":"abc123XYZ90"')

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _completed(
            'Tool call took: 1s\n'
            '{"title": "NVIDIA Q1 earnings call - YouTube", '
            f'"transcript": {json.dumps(transcript)}}}'
        )

    session = SimpleNamespace(get=fake_get)
    packet = fetch_youtube_earnings_transcript_packet(
        "nvda",
        session=session,
        run_func=fake_run,
        max_video_candidates=1,
    )

    assert packet.source_name == "youtube_transcript"
    assert packet.evidence_type == "earnings_transcripts"
    assert packet.symbol == "NVDA"
    assert packet.quality == "medium"
    assert packet.tool_route == "docker:youtube_transcript"
    assert packet.freshness["blocked"] is False
    assert packet.payload["execution_authority"] == "none"
    assert packet.payload["youtube_url"] == "https://www.youtube.com/watch?v=abc123XYZ90"
    assert packet.payload["transcript_char_count"] == len(transcript.strip())
    assert "submit_order" in packet.payload["forbidden_effects"]
    command = calls[0][0]
    assert command[:5] == [
        "docker",
        "mcp",
        "tools",
        "call",
        "youtube_transcript__get_transcript",
    ]
    assert "url=https://www.youtube.com/watch?v=abc123XYZ90" in command
    assert "--gateway-arg=profile" in command


def test_youtube_transcript_search_without_candidates_is_unavailable():
    session = SimpleNamespace(get=lambda *_args, **_kwargs: _response("no videos"))

    with pytest.raises(DataUnavailableError, match="found no video candidates"):
        fetch_youtube_earnings_transcript_packet("NVDA", session=session)


def test_youtube_transcript_timeout_is_transport_failure():
    session = SimpleNamespace(get=lambda *_args, **_kwargs: _response('"videoId":"abc123XYZ90"'))

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=15)

    with pytest.raises(DataTransportError, match="timed out"):
        fetch_youtube_earnings_transcript_packet("NVDA", session=session, run_func=fake_run)


def test_youtube_transcript_non_earnings_video_is_rejected():
    session = SimpleNamespace(get=lambda *_args, **_kwargs: _response('"videoId":"abc123XYZ90"'))

    def fake_run(*_args, **_kwargs):
        return _completed(
            'Tool call took: 1s\n'
            '{"title": "Random interview - YouTube", '
            '"transcript": "general market conversation about products and leadership"}'
        )

    with pytest.raises(DataUnavailableError, match="did not look like an earnings call"):
        fetch_youtube_earnings_transcript_packet(
            "NVDA",
            session=session,
            run_func=fake_run,
            min_transcript_chars=10,
        )


@pytest.mark.parametrize(
    "run_result",
    [
        _completed(stdout="not JSON"),
        _completed(stderr="docker gateway unavailable", returncode=1),
    ],
)
def test_youtube_unusable_external_mcp_response_is_transport_failure(run_result):
    session = SimpleNamespace(
        get=lambda *_args, **_kwargs: _response('"videoId":"abc123XYZ90"')
    )

    with pytest.raises(DataTransportError):
        fetch_youtube_earnings_transcript_packet(
            "NVDA",
            session=session,
            run_func=lambda *_args, **_kwargs: run_result,
        )


def test_youtube_http_transport_failure_is_typed():
    def fail_get(*_args, **_kwargs):
        raise requests.Timeout("timed out")

    with pytest.raises(DataTransportError, match="discovery failed"):
        fetch_youtube_earnings_transcript_packet(
            "NVDA",
            session=SimpleNamespace(get=fail_get),
        )


def test_youtube_missing_ticker_remains_terminal():
    with pytest.raises(OfficialDataError, match="ticker symbol") as exc_info:
        fetch_youtube_earnings_transcript_packet("")

    assert not isinstance(exc_info.value, RecoverableDataflowError)
