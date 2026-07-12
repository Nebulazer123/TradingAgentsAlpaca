from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph import START


class CapturingStateGraph:
    def __init__(self, state_type):
        self.state_type = state_type
        self.nodes = {}
        self.edges = []
        self.conditional_edges = []

    def add_node(self, name, node):
        self.nodes[name] = node

    def add_edge(self, source, target):
        self.edges.append((source, target))

    def add_conditional_edges(self, source, path, path_map=None):
        self.conditional_edges.append((source, path, path_map))


def _patch_graph_factories(monkeypatch, setup_module, node):
    factory_names = (
        "create_market_analyst",
        "create_prefetched_market_analyst",
        "create_sentiment_analyst",
        "create_news_analyst",
        "create_prefetched_news_analyst",
        "create_fundamentals_analyst",
        "create_prefetched_fundamentals_analyst",
        "create_bull_researcher",
        "create_bear_researcher",
        "create_research_manager",
        "create_trader",
        "create_aggressive_debator",
        "create_neutral_debator",
        "create_conservative_debator",
        "create_portfolio_manager",
        "create_msg_delete",
    )
    for factory_name in factory_names:
        monkeypatch.setattr(setup_module, factory_name, lambda *_args, **_kwargs: node)


def test_graph_setup_uses_batched_analyst_fanout_when_concurrency_enabled(monkeypatch):
    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    _patch_graph_factories(monkeypatch, setup_module, object())
    monkeypatch.setattr(setup_module, "StateGraph", CapturingStateGraph)

    graph = GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        tool_nodes={
            "market": object(),
            "social": object(),
            "news": object(),
            "fundamentals": object(),
        },
        conditional_logic=ConditionalLogic(),
        analyst_concurrency_limit=2,
    ).setup_graph(["market", "social", "news", "fundamentals"])

    assert (START, "Market Analyst") not in graph.edges
    assert any(source == START and path_map is None for source, _path, path_map in graph.conditional_edges)
    assert "Analyst Batch 1 Complete" in graph.nodes
    assert "Analyst Batch 2 Complete" in graph.nodes
    assert ("Msg Clear Market", "Analyst Batch 1 Complete") in graph.edges
    assert ("Msg Clear Sentiment", "Analyst Batch 1 Complete") in graph.edges
    assert ("Msg Clear News", "Analyst Batch 2 Complete") in graph.edges
    assert ("Msg Clear Fundamentals", "Analyst Batch 2 Complete") in graph.edges
    assert ("Analyst Batch 2 Complete", "Bull Researcher") in graph.edges
    assert "tools_social" not in graph.nodes

    start_route = next(path for source, path, _path_map in graph.conditional_edges if source == START)
    fanout = start_route({"messages": [HumanMessage(content="shared seed", id="seed-1")]})
    assert [item.node for item in fanout] == ["Market Analyst", "Sentiment Analyst"]
    assert all(len(item.arg["messages"]) == 1 for item in fanout)
    assert {item.arg["messages"][0].content for item in fanout} == {
        "Continue the market analysis for .",
        "Continue the social analysis for .",
    }
    assert {item.arg["messages"][0].id for item in fanout} == {
        "Market Analyst-seed",
        "Sentiment Analyst-seed",
    }


def test_message_cleanup_uses_remove_all_sentinel():
    from langgraph.graph.message import REMOVE_ALL_MESSAGES

    from tradingagents.agents.utils.agent_utils import create_msg_delete

    cleanup = create_msg_delete()
    result = cleanup(
        {
            "messages": [
                HumanMessage(content="one", id="shared"),
                AIMessage(content="two", id="shared"),
                HumanMessage(content="no id"),
            ]
        }
    )

    removals = [message for message in result["messages"] if isinstance(message, RemoveMessage)]
    assert [message.id for message in removals] == [REMOVE_ALL_MESSAGES]
    assert result["messages"][-1].content == "Continue"


def test_graph_setup_concurrent_analyst_shape_compiles(monkeypatch):
    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    def noop_node(_state):
        return {}

    _patch_graph_factories(monkeypatch, setup_module, noop_node)

    workflow = GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        tool_nodes={
            "market": noop_node,
            "social": noop_node,
            "news": noop_node,
            "fundamentals": noop_node,
        },
        conditional_logic=ConditionalLogic(),
        analyst_concurrency_limit=2,
        tool_free_analysts={"market", "news", "fundamentals"},
    ).setup_graph(["market", "social", "news", "fundamentals"])

    compiled = workflow.compile()
    assert compiled is not None


def test_concurrent_branch_cleanup_merges_without_missing_id_error():
    """Regression: 2026-07-11 overnight run failed 3/3 with LangGraph's
    "Attempting to delete a message with an ID that doesn't exist" because
    each parallel analyst branch emitted RemoveMessage ops for ids that only
    existed in its own ephemeral branch state. The REMOVE_ALL_MESSAGES
    sentinel must merge cleanly against a canonical channel that never saw
    those branch-local ids."""
    from langgraph.graph.message import add_messages

    from tradingagents.agents.utils.agent_utils import create_msg_delete

    cleanup = create_msg_delete()
    canonical = [HumanMessage(content="seed", id="seed-1")]

    branch_a = cleanup({"messages": [AIMessage(content="a", id="branch-a-only")]})
    branch_b = cleanup({"messages": [AIMessage(content="b", id="branch-b-only")]})

    merged = add_messages(canonical, branch_a["messages"])
    merged = add_messages(merged, branch_b["messages"])

    assert all(message.content == "Continue" for message in merged)


def _route_to_end_logic():
    """Real ConditionalLogic for analyst routing; debate/risk end at once."""
    from tradingagents.graph.conditional_logic import ConditionalLogic

    logic = ConditionalLogic()
    logic.should_continue_debate = lambda _state: "Research Manager"
    logic.should_continue_risk_analysis = lambda _state: "Portfolio Manager"
    return logic


def test_concurrent_graph_executes_end_to_end_with_branch_local_message_ids(monkeypatch):
    """Regression for the 2026-07-11 overnight 3/3 graph failure: run the
    REAL compiled LangGraph with analyst_concurrency_limit=2, stub analyst
    nodes that emit branch-local AI message ids (as Gemini does), and the
    REAL create_msg_delete cleanup. Before the REMOVE_ALL_MESSAGES fix this
    raised ValueError("Attempting to delete a message with an ID that
    doesn't exist") at the parallel merge."""
    import uuid

    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.setup import GraphSetup

    def make_analyst_node(report_field):
        def node(state):
            return {
                "messages": [AIMessage(content="analysis", id=str(uuid.uuid4()))],
                report_field: "stub report",
            }

        return node

    analyst_fields = {
        "create_market_analyst": "market_report",
        "create_prefetched_market_analyst": "market_report",
        "create_sentiment_analyst": "sentiment_report",
        "create_social_media_analyst": "sentiment_report",
        "create_prefetched_social_media_analyst": "sentiment_report",
        "create_news_analyst": "news_report",
        "create_prefetched_news_analyst": "news_report",
        "create_fundamentals_analyst": "fundamentals_report",
        "create_prefetched_fundamentals_analyst": "fundamentals_report",
    }
    for factory_name, report_field in analyst_fields.items():
        if hasattr(setup_module, factory_name):
            monkeypatch.setattr(
                setup_module,
                factory_name,
                lambda *_a, _field=report_field, **_k: make_analyst_node(_field),
            )

    def noop_node(_state):
        return {}

    for factory_name in (
        "create_bull_researcher",
        "create_bear_researcher",
        "create_research_manager",
        "create_trader",
        "create_aggressive_debator",
        "create_conservative_debator",
        "create_neutral_debator",
        "create_portfolio_manager",
    ):
        if hasattr(setup_module, factory_name):
            monkeypatch.setattr(
                setup_module, factory_name, lambda *_a, **_k: noop_node
            )

    workflow = GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        tool_nodes={
            "market": noop_node,
            "social": noop_node,
            "news": noop_node,
            "fundamentals": noop_node,
        },
        conditional_logic=_route_to_end_logic(),
        analyst_concurrency_limit=2,
        tool_free_analysts={"market", "social", "news", "fundamentals"},
    ).setup_graph(["market", "social", "news", "fundamentals"])

    compiled = workflow.compile()
    result = compiled.invoke(
        {"messages": [HumanMessage(content="seed", id="seed-1")]},
        {"recursion_limit": 50},
    )

    assert result["market_report"] == "stub report"
    assert result["fundamentals_report"] == "stub report"
