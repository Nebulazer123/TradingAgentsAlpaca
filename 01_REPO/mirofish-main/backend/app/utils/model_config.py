"""Optional LLM request configuration helpers.

The repo normally leaves model request controls alone. These helpers only add
settings when explicit non-secret environment variables are present.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


def _json_object_env(name: str) -> Dict[str, Any]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _int_env(name: str) -> Optional[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return int(raw)


def _float_env(name: str) -> Optional[float]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return float(raw)


def _merge_extra_body(config: Dict[str, Any], prefix: str) -> None:
    extra_body = dict(config.get("extra_body") or {})
    extra_body.update(_json_object_env(f"{prefix}_EXTRA_BODY_JSON"))

    reasoning = _json_object_env(f"{prefix}_REASONING_JSON")
    if reasoning:
        existing_reasoning = extra_body.get("reasoning")
        if existing_reasoning is not None and not isinstance(existing_reasoning, dict):
            raise ValueError(f"{prefix}_EXTRA_BODY_JSON.reasoning must be a JSON object")
        merged_reasoning = dict(existing_reasoning or {})
        merged_reasoning.update(reasoning)
        extra_body["reasoning"] = merged_reasoning

    if extra_body:
        config["extra_body"] = extra_body


def build_model_request_config(
    prefix: str = "LLM",
    *,
    default_temperature: Optional[float] = None,
    default_max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build OpenAI-compatible request kwargs from opt-in env controls.

    Supported variables for prefix ``LLM`` or ``LLM_BOOST``:
    - ``<prefix>_MODEL_CONFIG_JSON``: JSON object merged first.
    - ``<prefix>_TEMPERATURE``: float override.
    - ``<prefix>_MAX_TOKENS``: integer ``max_tokens`` override.
    - ``<prefix>_MAX_COMPLETION_TOKENS``: integer override.
    - ``<prefix>_EXTRA_BODY_JSON``: JSON object passed as OpenAI SDK extra_body.
    - ``<prefix>_REASONING_JSON``: JSON object merged into extra_body.reasoning.
    """

    config = _json_object_env(f"{prefix}_MODEL_CONFIG_JSON")

    if default_temperature is not None:
        config.setdefault("temperature", default_temperature)
    if default_max_tokens is not None:
        config.setdefault("max_tokens", default_max_tokens)
    if response_format is not None:
        config["response_format"] = response_format

    temperature = _float_env(f"{prefix}_TEMPERATURE")
    if temperature is not None:
        config["temperature"] = temperature

    max_tokens = _int_env(f"{prefix}_MAX_TOKENS")
    if max_tokens is not None:
        config["max_tokens"] = max_tokens

    max_completion_tokens = _int_env(f"{prefix}_MAX_COMPLETION_TOKENS")
    if max_completion_tokens is not None:
        config["max_completion_tokens"] = max_completion_tokens

    _merge_extra_body(config, prefix)
    return config


def infer_model_platform(base_url: str, explicit: str = "") -> str:
    """Return a Camel model platform name for a configured base URL."""

    explicit = explicit.strip().upper()
    if explicit:
        return explicit
    if "openrouter.ai" in (base_url or "").lower():
        return "OPENROUTER"
    return "OPENAI"
