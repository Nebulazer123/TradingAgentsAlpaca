from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from cli.stats_handler import (
    ModelBudgetExceededError,
    StatsCallbackHandler,
    stats_callback_handler_from_env,
)


def _llm_result(input_tokens: int, output_tokens: int):
    message = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    generation = MagicMock(message=message)
    return MagicMock(generations=[[generation]])


def test_stats_handler_has_no_budget_halt_without_explicit_caps():
    handler = StatsCallbackHandler()

    for _ in range(5):
        handler.on_llm_start({}, ["prompt"])
    handler.on_llm_end(_llm_result(1_000_000, 1_000_000))

    stats = handler.get_stats()
    assert stats["llm_calls"] == 5
    assert stats["tokens_in"] == 1_000_000
    assert stats["tokens_out"] == 1_000_000
    assert stats["budget_exceeded"] is False
    assert stats["budget_issues"] == []


def test_stats_handler_raises_when_model_call_cap_is_exceeded():
    handler = StatsCallbackHandler(max_llm_calls_per_run=1)

    handler.on_llm_start({}, ["prompt"])
    with pytest.raises(ModelBudgetExceededError, match="model calls 2 exceed"):
        handler.on_llm_start({}, ["prompt"])

    stats = handler.get_stats()
    assert stats["budget_exceeded"] is True
    assert "model calls 2 exceed per-run cap 1" in stats["budget_issues"]


def test_stats_handler_raises_when_token_caps_are_exceeded():
    handler = StatsCallbackHandler(
        max_input_tokens_per_run=10,
        max_output_tokens_per_run=5,
    )

    with pytest.raises(ModelBudgetExceededError, match="input tokens 11 exceed"):
        handler.on_llm_end(_llm_result(11, 6))

    stats = handler.get_stats()
    assert stats["tokens_in"] == 11
    assert stats["tokens_out"] == 6
    assert any("input tokens 11" in issue for issue in stats["budget_issues"])
    assert any("output tokens 6" in issue for issue in stats["budget_issues"])


def test_stats_handler_from_env_uses_only_explicit_positive_caps():
    handler = stats_callback_handler_from_env(
        {
            "TRADINGAGENTS_MODEL_MAX_CALLS_PER_RUN": "2",
            "TRADINGAGENTS_MODEL_MAX_INPUT_TOKENS_PER_RUN": "0",
            "TRADINGAGENTS_MODEL_MAX_OUTPUT_TOKENS_PER_RUN": "bad",
        }
    )

    assert handler.max_llm_calls_per_run == 2
    assert handler.max_input_tokens_per_run is None
    assert handler.max_output_tokens_per_run is None
