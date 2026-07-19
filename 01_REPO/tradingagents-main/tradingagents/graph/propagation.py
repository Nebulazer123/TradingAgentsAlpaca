# TradingAgents/graph/propagation.py

import datetime as dt
from collections.abc import Callable
from typing import Any

from tradingagents.agents.utils.agent_states import (
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.graph.packet_nodes import build_graph_run_id

_UTC = dt.timezone.utc


def _canonical_run_start(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("run_started_at must be a canonical aware UTC-seconds string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            "run_started_at must be a canonical aware UTC-seconds string"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("run_started_at must be a canonical aware UTC-seconds string")
    normalized = parsed.astimezone(_UTC)
    if (
        normalized.microsecond != 0
        or normalized.isoformat(timespec="seconds") != value
    ):
        raise ValueError("run_started_at must be a canonical aware UTC-seconds string")
    return value


def _canonical_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(
        self,
        max_recur_limit=100,
        run_signature_factory: Callable[[str], str] | None = None,
    ):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit
        self.run_signature_factory = run_signature_factory

    def create_initial_state(
        self,
        company_name: str,
        trade_date: str,
        asset_type: str = "stock",
        past_context: str = "",
        run_id: str | None = None,
        run_started_at: str | None = None,
        learning_context: str = "",
    ) -> dict[str, Any]:
        """Create the initial state for the agent graph."""
        company = _canonical_text(company_name, field="company_name")
        canonical_date = _canonical_text(str(trade_date), field="trade_date")
        canonical_asset = _canonical_text(asset_type, field="asset_type")
        if not isinstance(learning_context, str):
            raise ValueError("learning_context must be a string")
        if run_id is None:
            signature = (
                self.run_signature_factory(canonical_asset)
                if self.run_signature_factory is not None
                else "standalone-v1"
            )
            stable_run_id = build_graph_run_id(
                company,
                canonical_date,
                canonical_asset,
                signature,
            )
        else:
            stable_run_id = _canonical_text(run_id, field="run_id")
        if run_started_at is None:
            stable_run_start = dt.datetime.now(tz=_UTC).replace(
                microsecond=0
            ).isoformat(timespec="seconds")
        else:
            stable_run_start = _canonical_run_start(run_started_at)

        return {
            "messages": [("human", company)],
            "company_of_interest": company,
            "asset_type": canonical_asset,
            "trade_date": canonical_date,
            "run_id": stable_run_id,
            "run_started_at": stable_run_start,
            "decision_packet_refs": [],
            "learning_context": learning_context,
            "past_context": past_context,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
            "investment_plan": "",
            "trader_investment_plan": "",
            "final_trade_decision": "",
        }

    def get_graph_args(self, callbacks: list | None = None) -> dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
