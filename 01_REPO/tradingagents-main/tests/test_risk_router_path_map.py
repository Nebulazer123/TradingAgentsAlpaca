import pytest

from tradingagents.graph.conditional_logic import ConditionalLogic


def _noop_node(_state):
    return {}


def _patch_graph_factories(monkeypatch, setup_module):
    factory_calls = []
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
        def factory(*_args, _factory_name=factory_name, **_kwargs):
            factory_calls.append(_factory_name)
            return _noop_node

        monkeypatch.setattr(setup_module, factory_name, factory)

    return factory_calls


def _reachable_router_destinations(logic):
    debate_states = (
        {
            "investment_debate_state": {
                "count": 0,
                "current_response": "Bull case",
            }
        },
        {
            "investment_debate_state": {
                "count": 0,
                "current_response": "Bear case",
            }
        },
        {
            "investment_debate_state": {
                "count": 2,
                "current_response": "Bull case",
            }
        },
    )
    risk_states = (
        {
            "risk_debate_state": {
                "count": 0,
                "latest_speaker": "Aggressive Analyst",
            }
        },
        {
            "risk_debate_state": {
                "count": 0,
                "latest_speaker": "Conservative Analyst",
            }
        },
        {
            "risk_debate_state": {
                "count": 0,
                "latest_speaker": "Neutral Analyst",
            }
        },
        {
            "risk_debate_state": {
                "count": 3,
                "latest_speaker": "Aggressive Analyst",
            }
        },
    )

    return {
        "should_continue_debate": {
            logic.should_continue_debate(state) for state in debate_states
        },
        "should_continue_risk_analysis": {
            logic.should_continue_risk_analysis(state) for state in risk_states
        },
    }


@pytest.mark.parametrize(
    (
        "selected_analysts",
        "concurrency_limit",
        "tool_free_analysts",
        "expected_analyst_factories",
    ),
    (
        pytest.param(
            ["market"],
            1,
            set(),
            {"create_market_analyst"},
            id="single-tool-backed-analyst",
        ),
        pytest.param(
            ["market", "social", "news", "fundamentals"],
            2,
            set(),
            {
                "create_market_analyst",
                "create_sentiment_analyst",
                "create_news_analyst",
                "create_fundamentals_analyst",
            },
            id="multi-analyst-send-fanout-with-tool-free-sentiment",
        ),
        pytest.param(
            ["market", "social", "news", "fundamentals"],
            2,
            {"market", "news", "fundamentals"},
            {
                "create_prefetched_market_analyst",
                "create_sentiment_analyst",
                "create_prefetched_news_analyst",
                "create_prefetched_fundamentals_analyst",
            },
            id="multi-analyst-send-fanout-with-prefetched-analysts",
        ),
    ),
)
def test_every_debate_and_risk_router_map_declares_each_reachable_destination(
    monkeypatch,
    selected_analysts,
    concurrency_limit,
    tool_free_analysts,
    expected_analyst_factories,
):
    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.setup import GraphSetup

    factory_calls = _patch_graph_factories(monkeypatch, setup_module)
    logic = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)
    workflow = GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        tool_nodes={
            "market": _noop_node,
            "social": _noop_node,
            "news": _noop_node,
            "fundamentals": _noop_node,
        },
        conditional_logic=logic,
        analyst_concurrency_limit=concurrency_limit,
        tool_free_analysts=tool_free_analysts,
    ).setup_graph(selected_analysts)

    assert workflow.compile() is not None
    assert expected_analyst_factories <= set(factory_calls)

    expected_router_edges = {
        ("Bull Researcher", "should_continue_debate"),
        ("Bear Researcher", "should_continue_debate"),
        ("Aggressive Analyst", "should_continue_risk_analysis"),
        ("Conservative Analyst", "should_continue_risk_analysis"),
        ("Neutral Analyst", "should_continue_risk_analysis"),
    }
    reachable_destinations = _reachable_router_destinations(logic)
    observed_router_edges = set()
    path_map_mismatches = {}

    for source, branches in workflow.branches.items():
        for router_name, branch in branches.items():
            if router_name not in reachable_destinations:
                continue
            observed_router_edges.add((source, router_name))
            expected_path_map = {
                destination: destination
                for destination in reachable_destinations[router_name]
            }
            if branch.ends != expected_path_map:
                path_map_mismatches[(source, router_name)] = {
                    "actual": branch.ends,
                    "expected": expected_path_map,
                }

    assert observed_router_edges == expected_router_edges
    mismatch_details = "\n".join(
        f"{source} / {router_name}: actual={maps['actual']!r}, "
        f"expected={maps['expected']!r}"
        for (source, router_name), maps in sorted(path_map_mismatches.items())
    )
    assert not path_map_mismatches, f"incorrect router maps:\n{mismatch_details}"
