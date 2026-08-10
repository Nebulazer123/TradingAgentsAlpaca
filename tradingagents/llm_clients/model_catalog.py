"""Shared model catalog for CLI selections and validation."""

from __future__ import annotations

from dataclasses import dataclass

ModelOption = tuple[str, str]
ProviderModeOptions = dict[str, dict[str, list[ModelOption]]]

_PROVIDER_METADATA_ALIASES = {
    "gemini": "google",
}


@dataclass(frozen=True)
class ModelMetadata:
    """Machine-readable metadata for known catalog models.

    Unknown/custom/local-build-dependent fields stay ``None``. Callers should
    never parse the human dropdown labels for routing decisions.
    """

    provider: str
    model: str
    context_window_tokens: int | None = None
    notes: str = ""


# Shared model list for GLM via Z.AI (international) and BigModel (China).
# Source: docs.z.ai (GLM Coding Plan supported models + LLM guides).
# All GLM 4.7+ entries support thinking mode via thinking={"type":"enabled"}.
_GLM_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("GLM-5-Turbo - Fast, switchable thinking modes", "glm-5-turbo"),
        ("GLM-4.7 - Previous-gen flagship", "glm-4.7"),
        ("GLM-4.5-Air - Lightweight, cost-efficient", "glm-4.5-air"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("GLM-5.1 - Latest flagship, 204K ctx", "glm-5.1"),
        ("GLM-5 - Flagship, 204K ctx", "glm-5"),
        ("GLM-4.7 - Previous-gen flagship", "glm-4.7"),
        ("Custom model ID", "custom"),
    ],
}


# Shared model list for Qwen's global (dashscope-intl) and CN (dashscope) endpoints.
# Source: modelstudio.console.alibabacloud.com (Featured Models — Flagship + Cost-optimized).
#
# Only versioned IDs are exposed in the dropdown. The version-less aliases
# (qwen-plus, qwen-flash) are documented by Alibaba as auto-upgrading
# pointers ("backbone, latest, and snapshot ... have been upgraded to the
# Qwen3 series"), which means their behavior shifts when Alibaba rotates
# the backing model. Users who want a specific generation pick it
# explicitly; users who really want auto-latest can enter the alias via
# "Custom model ID".
_QWEN_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("Qwen 3.6 Flash - Latest fast, agentic coding + vision-language", "qwen3.6-flash"),
        ("Qwen 3.5 Flash - Previous-gen fast", "qwen3.5-flash"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("Qwen 3.6 Plus - Flagship vision-language, agentic coding SOTA", "qwen3.6-plus"),
        ("Qwen 3.5 Plus - Previous-gen flagship", "qwen3.5-plus"),
        ("Qwen 3 Max - Specialized for agent programming + tool use", "qwen3-max"),
        ("Custom model ID", "custom"),
    ],
}


# Shared model list for MiniMax's global and CN endpoints (same IDs).
# Full official lineup per platform.minimax.io/docs/api-reference/text-openai-api.
# All M2.x models share a 204,800-token context window.
_MINIMAX_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("MiniMax-M2.7-highspeed - Faster M2.7, 204K ctx, ~100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5-highspeed - Previous-gen highspeed, 204K ctx", "MiniMax-M2.5-highspeed"),
        ("MiniMax-M2.1-highspeed - M2.1 highspeed, 204K ctx", "MiniMax-M2.1-highspeed"),
        ("Custom model ID", "custom"),
    ],
    "deep": [
        ("MiniMax-M2.7 - Flagship, SOTA on coding/agent benchmarks, 204K ctx", "MiniMax-M2.7"),
        ("MiniMax-M2.7-highspeed - Same quality as M2.7, ~100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5 - Previous-gen flagship, 204K ctx", "MiniMax-M2.5"),
        ("MiniMax-M2.1 - Earlier M2 line, 204K ctx", "MiniMax-M2.1"),
        ("MiniMax-M2 - Base M2, 204K ctx", "MiniMax-M2"),
        ("Custom model ID", "custom"),
    ],
}


MODEL_OPTIONS: ProviderModeOptions = {
    "openai": {
        "quick": [
            ("GPT-5.4 Mini - Fast, strong coding and tool use", "gpt-5.4-mini"),
            ("GPT-5.4 Nano - Cheapest, high-volume tasks", "gpt-5.4-nano"),
            ("GPT-5.5 - Latest frontier, 1M context", "gpt-5.5"),
            ("GPT-4.1 - Smartest non-reasoning model", "gpt-4.1"),
        ],
        "deep": [
            ("GPT-5.5 - Latest frontier, 1M context", "gpt-5.5"),
            ("GPT-5.4 - Previous-gen frontier, 1M context, cost-effective", "gpt-5.4"),
            ("GPT-5.2 - Strong reasoning, cost-effective", "gpt-5.2"),
            ("GPT-5.5 Pro - Most capable, expensive ($30/$180 per 1M tokens)", "gpt-5.5-pro"),
        ],
    },
    "anthropic": {
        "quick": [
            ("Claude Sonnet 4.6 - Best speed and intelligence balance", "claude-sonnet-4-6"),
            ("Claude Haiku 4.5 - Fastest with near-frontier intelligence", "claude-haiku-4-5"),
            ("Claude Sonnet 4.5 - High-performance for agents and coding", "claude-sonnet-4-5"),
        ],
        "deep": [
            ("Claude Opus 4.7 - Latest frontier, long-running agents and coding", "claude-opus-4-7"),
            ("Claude Opus 4.6 - Frontier intelligence, agents and coding", "claude-opus-4-6"),
            ("Claude Opus 4.5 - Premium, max intelligence", "claude-opus-4-5"),
            ("Claude Sonnet 4.6 - Best speed and intelligence balance", "claude-sonnet-4-6"),
        ],
    },
    "google": {
        "quick": [
            ("Gemini 3 Flash - Next-gen fast (preview)", "gemini-3-flash-preview"),
            ("Gemini 2.5 Flash - Balanced, stable", "gemini-2.5-flash"),
            ("Gemini 3.1 Flash Lite - Most cost-efficient (GA)", "gemini-3.1-flash-lite"),
            ("Gemini 2.5 Flash Lite - Fast, low-cost", "gemini-2.5-flash-lite"),
        ],
        "deep": [
            ("Gemini 3.1 Pro - Reasoning-first, complex workflows (preview)", "gemini-3.1-pro-preview"),
            ("Gemini 3 Flash - Next-gen fast (preview)", "gemini-3-flash-preview"),
            ("Gemini 2.5 Pro - Stable pro model", "gemini-2.5-pro"),
            ("Gemini 2.5 Flash - Balanced, stable", "gemini-2.5-flash"),
        ],
    },
    "xai": {
        "quick": [
            ("Grok 4.20 (Non-Reasoning) - Latest, speed-optimized", "grok-4.20-non-reasoning"),
            ("Grok 4 Fast (Non-Reasoning) - Speed optimized", "grok-4-fast-non-reasoning"),
            ("Grok 4 Fast (Reasoning) - High-performance", "grok-4-fast-reasoning"),
        ],
        "deep": [
            ("Grok 4.20 (Reasoning) - Latest frontier reasoning model", "grok-4.20-reasoning"),
            ("Grok 4 - Flagship (dated build)", "grok-4-0709"),
            ("Grok 4 Fast (Reasoning) - High-performance", "grok-4-fast-reasoning"),
            ("Grok 4.20 - Auto-select reasoning behavior", "grok-4.20"),
        ],
    },
    "deepseek": {
        "quick": [
            ("DeepSeek V4 Flash - Latest V4 fast model", "deepseek-v4-flash"),
            ("DeepSeek V3.2", "deepseek-chat"),
            ("Custom model ID", "custom"),
        ],
        "deep": [
            ("DeepSeek V4 Pro - Latest V4 flagship model", "deepseek-v4-pro"),
            ("DeepSeek V3.2 (thinking)", "deepseek-reasoner"),
            ("DeepSeek V3.2", "deepseek-chat"),
            ("Custom model ID", "custom"),
        ],
    },
    # Qwen: same model IDs across global (dashscope-intl) and China
    # (dashscope) endpoints, so the two provider keys share one model list.
    "qwen": _QWEN_MODELS,
    "qwen-cn": _QWEN_MODELS,
    # GLM: Z.AI (international) and BigModel (China) host the same model
    # IDs; the two provider keys share one model list.
    "glm": _GLM_MODELS,
    "glm-cn": _GLM_MODELS,
    # MiniMax: same model IDs across global (.io) and China (.com) regions,
    # so the two provider keys share one model list.
    "minimax": _MINIMAX_MODELS,
    "minimax-cn": _MINIMAX_MODELS,
    # OpenRouter: fetched dynamically. Azure: any deployed model name.
    # Ollama display labels intentionally omit a "local" marker — the
    # endpoint is now configurable via OLLAMA_BASE_URL, so the same labels
    # apply whether the user runs ollama-serve on localhost or against a
    # remote host. The actual resolved endpoint is surfaced separately by
    # cli.utils.confirm_ollama_endpoint() right after provider selection.
    # "Custom model ID" lets users pick any model they have pulled via
    # `ollama pull` beyond the three suggested defaults.
    "ollama": {
        "quick": [
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("Custom model ID", "custom"),
        ],
        "deep": [
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("Custom model ID", "custom"),
        ],
    },
}


MODEL_METADATA: dict[str, dict[str, ModelMetadata]] = {
    "openai": {
        "gpt-5.5": ModelMetadata("openai", "gpt-5.5", 1_000_000),
        "gpt-5.5-pro": ModelMetadata("openai", "gpt-5.5-pro", 1_000_000),
        "gpt-5.4": ModelMetadata("openai", "gpt-5.4", 1_000_000),
        "gpt-5.4-mini": ModelMetadata("openai", "gpt-5.4-mini", 1_000_000),
        "gpt-5.4-nano": ModelMetadata("openai", "gpt-5.4-nano", 1_000_000),
        "gpt-4.1": ModelMetadata("openai", "gpt-4.1", 1_000_000),
    },
    "google": {
        "gemini-2.5-flash": ModelMetadata("google", "gemini-2.5-flash", 1_048_576),
        "gemini-2.5-flash-lite": ModelMetadata(
            "google",
            "gemini-2.5-flash-lite",
            1_048_576,
        ),
        "gemini-2.5-pro": ModelMetadata("google", "gemini-2.5-pro", 1_048_576),
    },
    "ollama": {
        # Operational context windows for the repo's unattended local helper
        # aliases. These are conservative runtime windows, not theoretical model
        # maximums.
        "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k": ModelMetadata(
            "ollama",
            "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k",
            4_096,
        ),
        "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest": ModelMetadata(
            "ollama",
            "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest",
            4_096,
        ),
        "deepseek-r1:14b": ModelMetadata("ollama", "deepseek-r1:14b", 4_096),
    },
    "glm": {
        "glm-5.1": ModelMetadata("glm", "glm-5.1", 204_000),
        "glm-5": ModelMetadata("glm", "glm-5", 204_000),
    },
    "glm-cn": {
        "glm-5.1": ModelMetadata("glm-cn", "glm-5.1", 204_000),
        "glm-5": ModelMetadata("glm-cn", "glm-5", 204_000),
    },
    "minimax": {
        "MiniMax-M2.7": ModelMetadata("minimax", "MiniMax-M2.7", 204_800),
        "MiniMax-M2.7-highspeed": ModelMetadata(
            "minimax",
            "MiniMax-M2.7-highspeed",
            204_800,
        ),
        "MiniMax-M2.5": ModelMetadata("minimax", "MiniMax-M2.5", 204_800),
        "MiniMax-M2.5-highspeed": ModelMetadata(
            "minimax",
            "MiniMax-M2.5-highspeed",
            204_800,
        ),
        "MiniMax-M2.1": ModelMetadata("minimax", "MiniMax-M2.1", 204_800),
        "MiniMax-M2.1-highspeed": ModelMetadata(
            "minimax",
            "MiniMax-M2.1-highspeed",
            204_800,
        ),
        "MiniMax-M2": ModelMetadata("minimax", "MiniMax-M2", 204_800),
    },
    "minimax-cn": {
        "MiniMax-M2.7": ModelMetadata("minimax-cn", "MiniMax-M2.7", 204_800),
        "MiniMax-M2.7-highspeed": ModelMetadata(
            "minimax-cn",
            "MiniMax-M2.7-highspeed",
            204_800,
        ),
        "MiniMax-M2.5": ModelMetadata("minimax-cn", "MiniMax-M2.5", 204_800),
        "MiniMax-M2.5-highspeed": ModelMetadata(
            "minimax-cn",
            "MiniMax-M2.5-highspeed",
            204_800,
        ),
        "MiniMax-M2.1": ModelMetadata("minimax-cn", "MiniMax-M2.1", 204_800),
        "MiniMax-M2.1-highspeed": ModelMetadata(
            "minimax-cn",
            "MiniMax-M2.1-highspeed",
            204_800,
        ),
        "MiniMax-M2": ModelMetadata("minimax-cn", "MiniMax-M2", 204_800),
    },
}


def get_model_options(provider: str, mode: str) -> list[ModelOption]:
    """Return shared model options for a provider and selection mode."""
    return MODEL_OPTIONS[provider.lower()][mode]


def get_model_metadata(provider: str, model: str) -> ModelMetadata | None:
    """Return machine-readable metadata for a known provider/model pair."""
    provider_key = _PROVIDER_METADATA_ALIASES.get(provider.lower(), provider.lower())
    provider_metadata = MODEL_METADATA.get(provider_key, {})
    return provider_metadata.get(model)


def get_model_context_window_tokens(provider: str, model: str) -> int | None:
    """Return known context window tokens, or ``None`` for custom/unknown models."""
    metadata = get_model_metadata(provider, model)
    return metadata.context_window_tokens if metadata else None


def get_known_models() -> dict[str, list[str]]:
    """Build known model names from the shared CLI catalog."""
    return {
        provider: sorted(
            {
                value
                for options in mode_options.values()
                for _, value in options
            }
        )
        for provider, mode_options in MODEL_OPTIONS.items()
    }
