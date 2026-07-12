from __future__ import annotations

import pytest

from tradingagents.dataflows import _official_common as official_common
from tradingagents.research.alphainsider import (
    AlphaInsiderError,
    fetch_recommended_strategies,
    verify_alphainsider_token,
)


class JsonResponse:
    def __init__(self, payload, *, status_code: int = 200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            error = requests.HTTPError(f"{self.status_code} for url https://alphainsider.example.test/")
            error.response = self
            raise error

    def json(self):
        return self.payload


class SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_verify_alphainsider_token_uses_body_token_without_authorization_header(
    monkeypatch,
    tmp_path,
    request,
):
    official_common.reset_connector_health()
    request.addfinalizer(official_common.reset_connector_health)
    monkeypatch.setattr(official_common, "CONNECTOR_HEALTH_PATH", tmp_path / "connector-health.json")
    session = SequenceSession(
        [
            JsonResponse({"success": True, "response": {"valid": True, "plan": "pro"}}),
        ]
    )

    payload = verify_alphainsider_token(
        api_key="raw-jwt-secret",
        session=session,
        sleep_func=lambda _: None,
    )

    assert payload == {"valid": True, "plan": "pro"}
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url.endswith("/verifyToken")
    assert kwargs["json"] == {"token": "raw-jwt-secret"}
    assert "Authorization" not in kwargs["headers"]
    [health] = official_common.connector_health_snapshot()
    assert health["connector"] == "alphainsider"
    assert health["successes"] == 1


def test_fetch_recommended_strategies_uses_shared_json_client_and_retries(monkeypatch, tmp_path, request):
    official_common.reset_connector_health()
    request.addfinalizer(official_common.reset_connector_health)
    monkeypatch.setattr(official_common, "CONNECTOR_HEALTH_PATH", tmp_path / "connector-health.json")
    sleeps = []
    session = SequenceSession(
        [
            JsonResponse({"temporary": "down"}, status_code=503),
            JsonResponse(
                {
                    "success": True,
                    "response": {
                        "strategies": [
                            {"id": "s1", "name": "Mean reversion"},
                            {"id": "s2", "name": "Momentum chase"},
                        ]
                    },
                }
            ),
        ]
    )

    strategies = fetch_recommended_strategies(
        api_key="raw-jwt-secret",
        session=session,
        sleep_func=sleeps.append,
    )

    assert [item["id"] for item in strategies] == ["s1", "s2"]
    assert len(session.calls) == 2
    assert session.calls[0][1]["headers"]["Authorization"] == "raw-jwt-secret"
    assert session.calls[0][1]["params"] == {"type": "stock"}
    assert sleeps

    health_by_connector = {
        row["connector"]: row
        for row in official_common.connector_health_snapshot()
    }
    assert health_by_connector["alphainsider"]["rate_limit_count"] == 0
    assert health_by_connector["alphainsider"]["errors"] == 1
    assert health_by_connector["alphainsider"]["successes"] == 1


def test_fetch_recommended_strategies_surfaces_alphainsider_error_body(
    monkeypatch,
    tmp_path,
    request,
):
    official_common.reset_connector_health()
    request.addfinalizer(official_common.reset_connector_health)
    monkeypatch.setattr(official_common, "CONNECTOR_HEALTH_PATH", tmp_path / "connector-health.json")
    session = SequenceSession(
        [
            JsonResponse(
                {"success": False, "response": "token is invalid or plan lacks recommended-strategy access"},
                status_code=400,
            ),
            JsonResponse(
                {"success": False, "response": "token is invalid or plan lacks recommended-strategy access"},
                status_code=400,
            ),
            JsonResponse(
                {"success": False, "response": "token is invalid or plan lacks recommended-strategy access"},
                status_code=400,
            ),
        ]
    )

    with pytest.raises(AlphaInsiderError) as error:
        fetch_recommended_strategies(
            api_key="raw-jwt-secret",
            session=session,
            sleep_func=lambda _: None,
        )

    message = str(error.value)
    assert "token is invalid or plan lacks recommended-strategy access" in message
    assert "raw-jwt-secret" not in message

    [health] = official_common.connector_health_snapshot()
    assert health["connector"] == "alphainsider"
    assert "token is invalid or plan lacks recommended-strategy access" in health["last_error"]
    assert "raw-jwt-secret" not in health["last_error"]
