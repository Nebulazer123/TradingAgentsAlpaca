"""Retained-only analyst inputs in the real role and packet topology."""

import hashlib
import json

import pytest
from langchain_core.messages import AIMessage

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup
from tradingagents.orchestration.decision_ledger import DecisionLedger


class _RecordingModel:
    def __init__(self):
        self.prompts = []

    def with_structured_output(self, _schema):
        # This fake deliberately uses the ordinary free-text path.
        # It is not a production model adapter or a qualification receipt.
        raise NotImplementedError("synthetic free-text model")

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(
            content="Retained evidence reviewed. FINAL TRANSACTION PROPOSAL: **HOLD**",
            id=f"retained-model-{len(self.prompts)}",
        )


def _forbidden(*_args, **_kwargs):
    raise AssertionError("ordinary analyst factory or live route must not run")


@pytest.mark.parametrize("context", ["", '{"retained_marker":"SOURCE-ONLY-762"}'])
@pytest.mark.parametrize("concurrency", [1, 2])
def test_retained_inputs_run_actual_full_role_topology_without_live_analysts(
    tmp_path, monkeypatch, context, concurrency,
):
    from tradingagents.graph import setup as setup_module

    for name in (
        "create_market_analyst", "create_prefetched_market_analyst",
        "create_sentiment_analyst", "create_news_analyst",
        "create_prefetched_news_analyst", "create_fundamentals_analyst",
        "create_prefetched_fundamentals_analyst",
    ):
        monkeypatch.setattr(setup_module, name, _forbidden)
    model = _RecordingModel()
    evidence = tmp_path / "evidence"
    ledger = evidence / "decisions"
    workflow = GraphSetup(
        quick_thinking_llm=model, deep_thinking_llm=model, tool_nodes={},
        conditional_logic=ConditionalLogic(), analyst_concurrency_limit=concurrency,
        ledger_root=ledger, evidence_root=evidence,
        retained_analyst_context=context,
    ).setup_graph()
    assert not any(name.startswith("tools_") for name in workflow.nodes)
    graph = workflow.compile()
    initial = Propagator(
        run_signature_factory=lambda _asset: hashlib.sha256(context.encode()).hexdigest(),
    ).create_initial_state(
        "AAPL", "2026-09-11",
        run_started_at="2026-09-13T20:00:00+00:00", learning_context="",
    )
    updates = list(graph.stream(initial, {"recursion_limit": 100}, stream_mode="updates"))
    visited = {name for update in updates for name in update}
    assert {
        "Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst",
        "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
        "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager",
        "Research Evidence Packet", "Trader Proposal Packet", "Portfolio Decision Packet",
    } <= visited
    assert len(model.prompts) == 12
    inputs = [json.loads(prompt) for prompt in model.prompts[:4]]
    assert {row["analyst"] for row in inputs} == {"market", "social", "news", "fundamentals"}
    assert all(row["retained_input"] == context for row in inputs)
    assert all("untrusted" in row["instruction"] for row in inputs)
    events = DecisionLedger(ledger).verify(evidence_root=evidence)
    assert [event.kind for event in events] == [
        "research_evidence", "trader_proposal", "portfolio_decision",
    ]


@pytest.mark.parametrize("context", [True, {}, b"retained"])
def test_retained_context_type_is_rejected_before_any_factory(tmp_path, context):
    with pytest.raises(ValueError, match="retained_analyst_context"):
        GraphSetup(
            quick_thinking_llm=object(), deep_thinking_llm=object(), tool_nodes={},
            conditional_logic=ConditionalLogic(),
            ledger_root=tmp_path / "evidence/decisions", evidence_root=tmp_path / "evidence",
            retained_analyst_context=context,
        )
    assert list(tmp_path.iterdir()) == []


def test_retained_mode_rejects_tools_and_implicit_destinations(tmp_path):
    common = dict(
        quick_thinking_llm=object(), deep_thinking_llm=object(),
        conditional_logic=ConditionalLogic(), retained_analyst_context="",
    )
    with pytest.raises(ValueError, match="explicit absolute"):
        GraphSetup(**common, tool_nodes={})
    with pytest.raises(ValueError, match="tool nodes"):
        GraphSetup(
            **common, tool_nodes={"market": _forbidden},
            ledger_root=tmp_path / "evidence/decisions", evidence_root=tmp_path / "evidence",
        )
    with pytest.raises(ValueError, match="inside"):
        GraphSetup(
            **common, tool_nodes={}, ledger_root=tmp_path / "outside",
            evidence_root=tmp_path / "evidence",
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tool_calls,content", [
    ([{"name": "get_news", "args": {}, "id": "tool-1"}], "untrusted result"),
    ([], ""),
])
def test_retained_analyst_rejects_tool_requests_and_empty_reports(tool_calls, content):
    from tradingagents.agents.analysts.retained_analyst import create_retained_analyst

    model = _RecordingModel()
    model.invoke = lambda _prompt: AIMessage(content=content, tool_calls=tool_calls)
    analyst = create_retained_analyst(model, "market", "")
    with pytest.raises(ValueError, match="retained analyst"):
        analyst({"company_of_interest": "AAPL", "trade_date": "2026-09-11", "asset_type": "stock"})
