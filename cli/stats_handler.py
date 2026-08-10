import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult


class ModelBudgetExceededError(RuntimeError):
    """Raised when an explicitly configured model call/token cap is exceeded."""


def _positive_int_env(env: dict[str, str] | None, name: str) -> int | None:
    if env is None:
        return None
    raw = str(env.get(name, "")).strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


class StatsCallbackHandler(BaseCallbackHandler):
    """Callback handler that tracks LLM calls, tool calls, and token usage."""

    def __init__(
        self,
        *,
        max_llm_calls_per_run: int | None = None,
        max_input_tokens_per_run: int | None = None,
        max_output_tokens_per_run: int | None = None,
    ) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.max_llm_calls_per_run = max_llm_calls_per_run
        self.max_input_tokens_per_run = max_input_tokens_per_run
        self.max_output_tokens_per_run = max_output_tokens_per_run
        self.budget_issues: list[str] = []

    def _budget_issues_locked(self) -> list[str]:
        issues: list[str] = []
        if (
            self.max_llm_calls_per_run is not None
            and self.llm_calls > self.max_llm_calls_per_run
        ):
            issues.append(
                f"model calls {self.llm_calls} exceed per-run cap {self.max_llm_calls_per_run}"
            )
        if (
            self.max_input_tokens_per_run is not None
            and self.tokens_in > self.max_input_tokens_per_run
        ):
            issues.append(
                f"input tokens {self.tokens_in} exceed per-run cap {self.max_input_tokens_per_run}"
            )
        if (
            self.max_output_tokens_per_run is not None
            and self.tokens_out > self.max_output_tokens_per_run
        ):
            issues.append(
                f"output tokens {self.tokens_out} exceed per-run cap {self.max_output_tokens_per_run}"
            )
        return issues

    def _raise_if_budget_exceeded_locked(self) -> None:
        issues = self._budget_issues_locked()
        if not issues:
            return
        for issue in issues:
            if issue not in self.budget_issues:
                self.budget_issues.append(issue)
        raise ModelBudgetExceededError("; ".join(issues))

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when an LLM starts."""
        with self._lock:
            self.llm_calls += 1
            self._raise_if_budget_exceeded_locked()

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when a chat model starts."""
        with self._lock:
            self.llm_calls += 1
            self._raise_if_budget_exceeded_locked()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token usage from LLM response."""
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return

        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata

        if usage_metadata:
            with self._lock:
                self.tokens_in += usage_metadata.get("input_tokens", 0)
                self.tokens_out += usage_metadata.get("output_tokens", 0)
                self._raise_if_budget_exceeded_locked()

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Increment tool call counter when a tool starts."""
        with self._lock:
            self.tool_calls += 1

    def get_stats(self) -> dict[str, Any]:
        """Return current statistics."""
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "budget_exceeded": bool(self.budget_issues),
                "budget_issues": list(self.budget_issues),
            }


def stats_callback_handler_from_env(env: dict[str, str] | None) -> StatsCallbackHandler:
    """Build a mid-run budget-enforcing stats handler from explicit env caps."""

    return StatsCallbackHandler(
        max_llm_calls_per_run=_positive_int_env(
            env,
            "TRADINGAGENTS_MODEL_MAX_CALLS_PER_RUN",
        ),
        max_input_tokens_per_run=_positive_int_env(
            env,
            "TRADINGAGENTS_MODEL_MAX_INPUT_TOKENS_PER_RUN",
        ),
        max_output_tokens_per_run=_positive_int_env(
            env,
            "TRADINGAGENTS_MODEL_MAX_OUTPUT_TOKENS_PER_RUN",
        ),
    )
