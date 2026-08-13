# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState


class AnalystToolRoundLimitExceeded(RuntimeError):
    """Raised before an analyst can exceed its deterministic tool-call budget."""


def _safe_tool_name(value: object) -> str:
    name = str(value)
    if not name or len(name) > 64:
        return "unknown_tool"
    if not all(character.isalnum() or character in "_.-" for character in name):
        return "unknown_tool"
    return name


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(
        self,
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        max_analyst_tool_rounds=8,
    ):
        """Initialize with configuration parameters."""
        if type(max_analyst_tool_rounds) is not int or max_analyst_tool_rounds < 1:
            raise ValueError("max_analyst_tool_rounds must be a positive integer")
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.max_analyst_tool_rounds = max_analyst_tool_rounds

    def _analyst_tool_route(
        self,
        state: AgentState,
        *,
        analyst: str,
        tool_node: str,
        clear_node: str,
    ) -> str:
        messages = state["messages"]
        last_message = messages[-1]
        tool_calls = list(getattr(last_message, "tool_calls", None) or [])
        if not tool_calls:
            return clear_node

        observed = sum(
            bool(getattr(message, "tool_calls", None))
            for message in messages
        )
        if observed > self.max_analyst_tool_rounds:
            tool_names = sorted(
                {
                    _safe_tool_name(
                        call.get("name", "unknown_tool")
                        if isinstance(call, dict)
                        else getattr(call, "name", "unknown_tool")
                    )
                    for call in tool_calls
                }
            )[:8]
            raise AnalystToolRoundLimitExceeded(
                "analyst_tool_round_limit_exceeded "
                f"analyst={analyst} limit={self.max_analyst_tool_rounds} "
                f"observed={observed} last_tools={','.join(tool_names)}"
            )
        return tool_node

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        return self._analyst_tool_route(
            state,
            analyst="market",
            tool_node="tools_market",
            clear_node="Msg Clear Market",
        )

    def should_continue_social(self, state: AgentState):
        """Route the prefetch-only sentiment analyst to cleanup.

        Method name keeps the legacy ``social`` suffix to match the
        ``AnalystType.SOCIAL = "social"`` wire value (saved-config
        back-compat); the returned ``clear_node`` label uses the v0.2.5
        rename so it matches the node registered by the execution plan.
        """
        return "Msg Clear Sentiment"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        return self._analyst_tool_route(
            state,
            analyst="news",
            tool_node="tools_news",
            clear_node="Msg Clear News",
        )

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        return self._analyst_tool_route(
            state,
            analyst="fundamentals",
            tool_node="tools_fundamentals",
            clear_node="Msg Clear Fundamentals",
        )

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
