from tradingagents.llm_clients.model_catalog import (
    get_model_context_window_tokens,
    get_model_metadata,
    get_model_options,
)
from tradingagents.research.model_routing import select_intelligent_model_route


def test_model_catalog_exposes_machine_readable_context_windows_without_label_parsing():
    assert get_model_context_window_tokens("openai", "gpt-5.5") == 1_000_000
    assert get_model_context_window_tokens("google", "gemini-2.5-flash-lite") == 1_048_576
    assert (
        get_model_context_window_tokens(
            "ollama",
            "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest",
        )
        == 4_096
    )
    assert get_model_context_window_tokens("ollama", "deepseek-r1:14b") == 4_096
    assert get_model_context_window_tokens("minimax", "MiniMax-M2.7") == 204_800
    assert get_model_context_window_tokens("glm", "glm-5") == 204_000
    assert get_model_context_window_tokens("ollama", "custom") is None

    metadata = get_model_metadata("openai", "gpt-5.5")
    assert metadata is not None
    assert metadata.context_window_tokens == 1_000_000


def test_catalog_dropdown_shape_stays_backward_compatible():
    option = get_model_options("openai", "deep")[0]
    assert isinstance(option, tuple)
    assert len(option) == 2


def test_model_routes_include_context_window_when_catalog_knows_model():
    route = select_intelligent_model_route(
        env={
            "GOOGLE_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
            "TRADINGAGENTS_GEMINI_RESEARCH_MODEL": "gemini-2.5-flash-lite",
        }
    )

    assert route.context_window_tokens == 1_048_576
    assert route.model_dump()["context_window_tokens"] == 1_048_576
