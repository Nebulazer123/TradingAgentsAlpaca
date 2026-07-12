"""Read-only AlphaInsider helpers for paper strategy comparison.

The helpers follow the AlphaInsider skill contract:

* Load the JWT from ``ALPHAINSIDER_API_KEY`` only.
* Send the raw JWT in the Authorization header, with no Bearer prefix.
* Never print, return, or store the token.
* Do not guess missing strategy or bot ids.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tradingagents.dataflows._official_common import OfficialDataError, get_json, post_json

BASE_URL = "https://alphainsider.com/api"


class AlphaInsiderError(RuntimeError):
    """Raised when a read-only AlphaInsider request cannot be completed."""


def alphainsider_env_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    active_env = env or os.environ
    return {
        "api_key_present": bool(str(active_env.get("ALPHAINSIDER_API_KEY", "")).strip()),
        "strategy_id_pinned": bool(str(active_env.get("ALPHAINSIDER_STRATEGY_ID", "")).strip()),
        "bot_id_pinned": bool(str(active_env.get("ALPHAINSIDER_BOT_ID", "")).strip()),
        "will_not_guess_missing_strategy_or_bot_id": True,
    }


def _api_key(explicit: str | None = None) -> str:
    value = (explicit if explicit is not None else os.getenv("ALPHAINSIDER_API_KEY") or "").strip()
    if not value:
        raise AlphaInsiderError("ALPHAINSIDER_API_KEY is missing")
    return value


def _response_payload(response: Any) -> Any:
    try:
        data = response.json()
    except ValueError as exc:
        raise AlphaInsiderError("AlphaInsider returned non-JSON data") from exc
    if not isinstance(data, dict):
        raise AlphaInsiderError("AlphaInsider response shape is invalid")
    if data.get("success") is False:
        raise AlphaInsiderError(str(data.get("response") or "AlphaInsider request failed"))
    return data.get("response")


def verify_alphainsider_token(
    *,
    api_key: str | None = None,
    session: Any | None = None,
    sleep_func: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Verify the configured AlphaInsider token without returning or logging it."""

    try:
        data = post_json(
            f"{BASE_URL}/verifyToken",
            body={"token": _api_key(api_key)},
            headers={"Content-Type": "application/json"},
            connector_name="alphainsider",
            session=session,
            timeout=20,
            sleep_func=sleep_func or time.sleep,
        )
    except OfficialDataError as exc:
        raise AlphaInsiderError(f"AlphaInsider token verification failed: {exc}") from exc
    payload = _response_payload(_JsonPayload(data))
    return payload if isinstance(payload, dict) else {"status": str(payload)}


def fetch_recommended_strategies(
    *,
    api_key: str | None = None,
    strategy_type: str = "stock",
    limit: int = 10,
    session: Any | None = None,
    sleep_func: Callable[[float], None] | None = None,
) -> list[dict[str, Any]]:
    params = {"type": strategy_type.strip() or "stock"}
    try:
        data = get_json(
            f"{BASE_URL}/getRecommendedStrategies",
            params=params,
            headers={"Authorization": _api_key(api_key)},
            connector_name="alphainsider",
            session=session,
            timeout=20,
            sleep_func=sleep_func or time.sleep,
        )
    except OfficialDataError as exc:
        raise AlphaInsiderError(
            f"AlphaInsider recommended strategies request failed: {exc}"
        ) from exc
    payload = _response_payload(_JsonPayload(data))
    if isinstance(payload, dict):
        strategies = payload.get("strategies") or payload.get("data") or payload.get("items") or []
    else:
        strategies = payload
    if not isinstance(strategies, list):
        raise AlphaInsiderError("AlphaInsider recommended strategies response is not a list")
    return [
        item
        for item in strategies[: max(1, min(int(limit), 50))]
        if isinstance(item, dict)
    ]


class _JsonPayload:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def json(self) -> dict[str, Any]:
        return self._data


def compact_strategy_summary(strategy: Mapping[str, Any], *, rank: int) -> dict[str, Any]:
    strategy_id = (
        strategy.get("strategy_id")
        or strategy.get("id")
        or strategy.get("_id")
        or strategy.get("uuid")
    )
    return {
        "rank": rank,
        "strategy_id": str(strategy_id or ""),
        "name": str(strategy.get("name") or strategy.get("title") or "unnamed strategy")[:160],
        "type": str(strategy.get("type") or strategy.get("strategy_type") or "unknown"),
        "visibility": str(strategy.get("visibility") or strategy.get("status") or "unknown"),
        "return_percent": str(
            strategy.get("return_percent")
            or strategy.get("return")
            or strategy.get("return_pct")
            or ""
        ),
        "subscribers": strategy.get("subscribers")
        or strategy.get("subscriber_count")
        or strategy.get("subscriptions"),
    }


def compact_strategy_summaries(strategies: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        compact_strategy_summary(strategy, rank=index)
        for index, strategy in enumerate(strategies, start=1)
    ]
