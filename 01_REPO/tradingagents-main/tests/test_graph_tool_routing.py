from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from tradingagents.graph.trading_graph import TradingAgentsGraph


def _tool_names(node) -> set[str]:
    return set(getattr(node, "tools_by_name", {}))


def test_graph_exposes_macro_and_sentiment_context_tools_without_llm_init():
    graph = object.__new__(TradingAgentsGraph)
    nodes = TradingAgentsGraph._create_tool_nodes(graph)

    assert "get_macro_context" in _tool_names(nodes["market"])
    assert "get_macro_context" in _tool_names(nodes["news"])
    assert "get_sentiment_context" in _tool_names(nodes["social"])
    assert "get_supplemental_market_context" in _tool_names(nodes["market"])
    assert "get_supplemental_market_context" in _tool_names(nodes["news"])


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


def test_graph_setup_skips_dead_social_tool_branch(monkeypatch):
    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    factory_names = (
        "create_sentiment_analyst",
        "create_news_analyst",
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
        monkeypatch.setattr(setup_module, factory_name, lambda *_args, **_kwargs: object())
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
    ).setup_graph(["social", "news"])

    assert "tools_social" not in graph.nodes
    assert ("Sentiment Analyst", "Msg Clear Sentiment") in graph.edges
    assert not any(source == "Sentiment Analyst" for source, _path, _map in graph.conditional_edges)

    assert "tools_news" in graph.nodes
    assert ("tools_news", "News Analyst") in graph.edges
    assert any(source == "News Analyst" for source, _path, _map in graph.conditional_edges)


def test_graph_setup_uses_batched_analyst_fanout_when_concurrency_enabled(monkeypatch):
    from langgraph.graph import START

    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    factory_names = (
        "create_market_analyst",
        "create_sentiment_analyst",
        "create_news_analyst",
        "create_fundamentals_analyst",
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
        monkeypatch.setattr(setup_module, factory_name, lambda *_args, **_kwargs: object())
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
    assert all(item.arg["messages"] == [] for item in fanout)


def test_message_cleanup_skips_duplicate_and_empty_ids():
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
    assert [message.id for message in removals] == ["shared"]
    assert result["messages"][-1].content == "Continue"


def test_graph_setup_concurrent_analyst_shape_compiles(monkeypatch):
    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    def noop_node(_state):
        return {}

    factory_names = (
        "create_prefetched_market_analyst",
        "create_sentiment_analyst",
        "create_prefetched_news_analyst",
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
        monkeypatch.setattr(setup_module, factory_name, lambda *_args, **_kwargs: noop_node)

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
