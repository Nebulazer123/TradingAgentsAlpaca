# TradingAgents/graph/setup.py

from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Send

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .analyst_execution import build_analyst_execution_plan
from .conditional_logic import ConditionalLogic
from .packet_nodes import (
    create_portfolio_decision_packet_node,
    create_research_evidence_packet_node,
    create_trader_proposal_packet_node,
)


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        analyst_concurrency_limit: int = 1,
        tool_free_analysts: set[str] | None = None,
        ledger_root: str | Path = "results/control_plane/decisions",
        evidence_root: str | Path = "results",
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.analyst_concurrency_limit = analyst_concurrency_limit
        self.tool_free_analysts = tool_free_analysts or set()
        self.ledger_root = Path(ledger_root)
        self.evidence_root = Path(evidence_root)

    def setup_graph(
        self, selected_analysts=None
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        if selected_analysts is None:
            selected_analysts = ["market", "social", "news", "fundamentals"]

        plan = build_analyst_execution_plan(
            selected_analysts,
            concurrency_limit=self.analyst_concurrency_limit,
        )

        analyst_factories = {
            "market": lambda: (
                create_prefetched_market_analyst(self.quick_thinking_llm)
                if "market" in self.tool_free_analysts
                else create_market_analyst(self.quick_thinking_llm)
            ),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: (
                create_prefetched_news_analyst(self.quick_thinking_llm)
                if "news" in self.tool_free_analysts
                else create_news_analyst(self.quick_thinking_llm)
            ),
            "fundamentals": lambda: (
                create_prefetched_fundamentals_analyst(self.quick_thinking_llm)
                if "fundamentals" in self.tool_free_analysts
                else create_fundamentals_analyst(self.quick_thinking_llm)
            ),
        }

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)
        research_evidence_packet_node = create_research_evidence_packet_node(
            self.ledger_root,
            self.evidence_root,
        )
        trader_proposal_packet_node = create_trader_proposal_packet_node(
            self.ledger_root,
            self.evidence_root,
        )
        portfolio_decision_packet_node = create_portfolio_decision_packet_node(
            self.ledger_root,
            self.evidence_root,
        )

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for spec in plan.specs:
            workflow.add_node(spec.agent_node, analyst_factories[spec.key]())
            workflow.add_node(spec.clear_node, create_msg_delete())
            if spec.tool_node is not None:
                workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)
        workflow.add_node(
            "Research Evidence Packet",
            research_evidence_packet_node,
        )
        workflow.add_node(
            "Trader Proposal Packet",
            trader_proposal_packet_node,
        )
        workflow.add_node(
            "Portfolio Decision Packet",
            portfolio_decision_packet_node,
        )

        def _wire_analyst_body(spec):
            current_analyst = spec.agent_node
            current_tools = spec.tool_node
            current_clear = spec.clear_node

            # Prefetch-only analysts do not bind tools, so route them straight
            # to their cleanup node instead of registering an unreachable tool
            # loop.
            if current_tools is None:
                workflow.add_edge(current_analyst, current_clear)
            else:
                workflow.add_conditional_edges(
                    current_analyst,
                    getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                    [current_tools, current_clear],
                )
                workflow.add_edge(current_tools, current_analyst)

        # Define edges. Keep the default sequential shape unchanged; only use
        # Send fan-out when the caller explicitly asks for analyst concurrency.
        if plan.concurrency_limit == 1:
            workflow.add_edge(START, plan.specs[0].agent_node)

            for i, spec in enumerate(plan.specs):
                _wire_analyst_body(spec)

                # Connect to next analyst or to Bull Researcher if this is the last analyst
                if i < len(plan.specs) - 1:
                    workflow.add_edge(spec.clear_node, plan.specs[i + 1].agent_node)
                else:
                    workflow.add_edge(spec.clear_node, "Research Evidence Packet")
        else:
            def _send_batch(batch):
                def route(state):
                    branch_state = dict(state)
                    # Analyst fan-out branches share the parent state. If each
                    # branch receives the same message list, their cleanup
                    # nodes can emit duplicate RemoveMessage operations when
                    # the branch updates are merged. Analysts use the explicit
                    # ticker/date/report fields, so give each branch a unique
                    # human kickoff message instead of sharing the parent
                    # message list. Google Gemini also needs at least one
                    # non-system content item, so this keeps the branch valid
                    # without reintroducing duplicate cleanup state.
                    return [
                        Send(
                            spec.agent_node,
                            {
                                **branch_state,
                                "messages": [
                                    HumanMessage(
                                        content=(
                                            f"Continue the {spec.key} analysis for "
                                            f"{branch_state.get('company_of_interest', '')}."
                                        ),
                                        id=f"{spec.agent_node}-seed",
                                    )
                                ],
                            },
                        )
                        for spec in batch
                    ]

                return route

            workflow.add_conditional_edges(START, _send_batch(plan.batches[0]))

            for batch_index, batch in enumerate(plan.batches):
                join_node = f"Analyst Batch {batch_index + 1} Complete"
                workflow.add_node(join_node, lambda _state: {})

                for spec in batch:
                    _wire_analyst_body(spec)
                    workflow.add_edge(spec.clear_node, join_node)

                if batch_index < len(plan.batches) - 1:
                    workflow.add_conditional_edges(
                        join_node,
                        _send_batch(plan.batches[batch_index + 1]),
                    )
                else:
                    workflow.add_edge(join_node, "Research Evidence Packet")

        # Add remaining edges
        debate_path_map = {
            "Bull Researcher": "Bull Researcher",
            "Bear Researcher": "Bear Researcher",
            "Research Manager": "Research Manager",
        }
        risk_path_map = {
            "Aggressive Analyst": "Aggressive Analyst",
            "Conservative Analyst": "Conservative Analyst",
            "Neutral Analyst": "Neutral Analyst",
            "Portfolio Manager": "Portfolio Manager",
        }
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            debate_path_map,
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            debate_path_map,
        )
        workflow.add_edge("Research Evidence Packet", "Bull Researcher")
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Trader Proposal Packet")
        workflow.add_edge("Trader Proposal Packet", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            risk_path_map,
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            risk_path_map,
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            risk_path_map,
        )

        workflow.add_edge("Portfolio Manager", "Portfolio Decision Packet")
        workflow.add_edge("Portfolio Decision Packet", END)

        return workflow
