"""Deterministic, analysis-only packet handoffs in the real agent graph."""

from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from tradingagents.graph.packet_nodes import (
    DECISION_PACKET_REF_SCHEMA_VERSION,
    PACKET_HANDOFF_SCHEMA_VERSION,
    PACKET_HANDOFF_TTL,
    build_graph_run_id,
    create_portfolio_decision_packet_node,
    create_research_evidence_packet_node,
    create_trader_proposal_packet_node,
)
from tradingagents.graph.propagation import Propagator
from tradingagents.orchestration.decision_ledger import (
    DecisionLedger,
    PacketCollisionError,
)

UTC = dt.timezone.utc
RUN_STARTED = dt.datetime(2026, 7, 19, 10, 30, tzinfo=UTC)
RUN_STARTED_TEXT = RUN_STARTED.isoformat(timespec="seconds")
NOW = RUN_STARTED + dt.timedelta(minutes=5)


def _state(*, run_id: str = "graph-" + "1" * 64) -> dict:
    return {
        "messages": [HumanMessage(content="NFLX", id="seed")],
        "company_of_interest": "NFLX",
        "asset_type": "stock",
        "trade_date": "2026-07-19",
        "run_id": run_id,
        "run_started_at": RUN_STARTED_TEXT,
        "decision_packet_refs": [],
        "learning_context": "",
        "past_context": "",
        "market_report": "MARKET FULL TEXT",
        "sentiment_report": "SENTIMENT FULL TEXT",
        "news_report": "NEWS FULL TEXT",
        "fundamentals_report": "FUNDAMENTALS FULL TEXT",
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "history": "",
            "current_response": "",
            "judge_decision": "RESEARCH MANAGER FULL TEXT",
            "count": 0,
        },
        "investment_plan": "INVESTMENT PLAN FULL TEXT",
        "trader_investment_plan": "TRADER FULL TEXT",
        "risk_debate_state": {
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "RISK MANAGER FULL TEXT",
            "count": 0,
        },
        "final_trade_decision": "PORTFOLIO FULL TEXT",
    }


def _node_triplet(tmp_path, *, clock=lambda: NOW):
    ledger_root = tmp_path / "ledger"
    evidence_root = tmp_path / "evidence"
    return (
        ledger_root,
        evidence_root,
        (
            create_research_evidence_packet_node(
                ledger_root,
                evidence_root,
                clock=clock,
            ),
            create_trader_proposal_packet_node(
                ledger_root,
                evidence_root,
                clock=clock,
            ),
            create_portfolio_decision_packet_node(
                ledger_root,
                evidence_root,
                clock=clock,
            ),
        ),
    )


def _run_nodes(tmp_path, state=None, *, clock=lambda: NOW):
    current = copy.deepcopy(state or _state())
    ledger_root, evidence_root, nodes = _node_triplet(tmp_path, clock=clock)
    for node in nodes:
        current.update(node(current))
    return current, DecisionLedger(ledger_root), ledger_root, evidence_root


def _packet_payload(ledger_root: Path, packet_ref: dict) -> dict:
    return json.loads((ledger_root / packet_ref["packet_path"]).read_text())


def _evidence_payload(evidence_root: Path, packet_payload: dict) -> dict:
    return json.loads(
        (evidence_root / packet_payload["evidence_refs"][0]["path"]).read_text()
    )


def test_build_graph_run_id_is_stable_safe_sensitive_and_opaque():
    inputs = ("Netflix / NFLX", "2026-07-19", "stock", '{"shape":"frozen"}')
    first = build_graph_run_id(*inputs)

    assert first == build_graph_run_id(*inputs)
    assert re.fullmatch(r"graph-[0-9a-f]{64}", first)
    assert all(raw not in first for raw in inputs)
    for index in range(len(inputs)):
        changed = list(inputs)
        changed[index] += "-changed"
        assert build_graph_run_id(*changed) != first

    expected_payload = {
        "asset_type": "stock",
        "company": "Netflix / NFLX",
        "run_signature": '{"shape":"frozen"}',
        "schema_version": PACKET_HANDOFF_SCHEMA_VERSION,
        "trade_date": "2026-07-19",
    }
    expected = hashlib.sha256(
        json.dumps(
            expected_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    assert first == f"graph-{expected}"


@pytest.mark.parametrize(
    "values",
    (
        ("", "2026-07-19", "stock", "signature"),
        ("NFLX", "", "stock", "signature"),
        ("NFLX", "2026-07-19", "", "signature"),
        ("NFLX", "2026-07-19", "stock", ""),
        (" NFLX", "2026-07-19", "stock", "signature"),
        ("NFLX", "2026-07-19", "stock", "signature "),
    ),
)
def test_build_graph_run_id_requires_nonempty_canonical_strings(values):
    with pytest.raises(ValueError):
        build_graph_run_id(*values)


def test_initial_state_has_stable_identity_and_all_existing_empty_fields():
    propagator = Propagator(
        run_signature_factory=lambda asset: f"frozen-{asset}-signature"
    )
    first = propagator.create_initial_state(
        "NFLX",
        "2026-07-19",
        asset_type="stock",
    )
    second = propagator.create_initial_state(
        "NFLX",
        "2026-07-19",
        asset_type="stock",
        run_started_at=first["run_started_at"],
    )

    assert first["run_id"] == second["run_id"] == build_graph_run_id(
        "NFLX",
        "2026-07-19",
        "stock",
        "frozen-stock-signature",
    )
    assert dt.datetime.fromisoformat(first["run_started_at"]).tzinfo == UTC
    assert dt.datetime.fromisoformat(first["run_started_at"]).microsecond == 0
    assert first["decision_packet_refs"] == []
    assert first["learning_context"] == ""
    assert first["investment_plan"] == ""
    assert first["trader_investment_plan"] == ""
    assert first["final_trade_decision"] == ""
    assert first["market_report"] == ""
    assert first["sentiment_report"] == ""
    assert first["news_report"] == ""
    assert first["fundamentals_report"] == ""


def test_initial_state_accepts_explicit_identity_context_and_standalone_signature():
    explicit = "graph-" + "a" * 64
    state = Propagator().create_initial_state(
        "NFLX",
        "2026-07-19",
        run_id=explicit,
        run_started_at=RUN_STARTED_TEXT,
        learning_context="bounded historical context",
    )
    standalone = Propagator().create_initial_state(
        "NFLX",
        "2026-07-19",
        run_started_at=RUN_STARTED_TEXT,
    )

    assert state["run_id"] == explicit
    assert state["run_started_at"] == RUN_STARTED_TEXT
    assert state["learning_context"] == "bounded historical context"
    assert standalone["run_id"] == build_graph_run_id(
        "NFLX",
        "2026-07-19",
        "stock",
        "standalone-v1",
    )


@pytest.mark.parametrize(
    "timestamp",
    (
        "2026-07-19T10:30:00",
        "2026-07-19T10:30:00Z",
        "2026-07-19T11:30:00+01:00",
        "2026-07-19T10:30:00.100000+00:00",
        RUN_STARTED,
    ),
)
def test_initial_state_rejects_noncanonical_utc_seconds(timestamp):
    with pytest.raises(ValueError, match="run_started_at"):
        Propagator().create_initial_state(
            "NFLX",
            "2026-07-19",
            run_started_at=timestamp,
        )


class _CapturingStateGraph:
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


def _patch_agent_factories(monkeypatch, setup_module):
    def noop(_state):
        return {}

    for name in (
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
    ):
        monkeypatch.setattr(setup_module, name, lambda *_a, **_k: noop)
    return noop


@pytest.mark.parametrize("concurrency", (1, 2))
def test_graph_has_exact_packet_nodes_and_boundary_edges(
    monkeypatch,
    tmp_path,
    concurrency,
):
    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    noop = _patch_agent_factories(monkeypatch, setup_module)
    monkeypatch.setattr(setup_module, "StateGraph", _CapturingStateGraph)
    graph = GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        tool_nodes={
            "market": noop,
            "social": noop,
            "news": noop,
            "fundamentals": noop,
        },
        conditional_logic=ConditionalLogic(),
        analyst_concurrency_limit=concurrency,
        tool_free_analysts={"market", "news"},
        ledger_root=tmp_path / "ledger",
        evidence_root=tmp_path / "evidence",
    ).setup_graph(["market", "news"])

    packet_names = {
        "Research Evidence Packet",
        "Trader Proposal Packet",
        "Portfolio Decision Packet",
    }
    assert packet_names <= set(graph.nodes)
    assert ("Research Evidence Packet", "Bull Researcher") in graph.edges
    assert ("Research Manager", "Trader") in graph.edges
    assert ("Trader", "Trader Proposal Packet") in graph.edges
    assert ("Trader Proposal Packet", "Aggressive Analyst") in graph.edges
    assert ("Portfolio Manager", "Portfolio Decision Packet") in graph.edges
    assert ("Portfolio Decision Packet", END) in graph.edges
    assert ("Trader", "Aggressive Analyst") not in graph.edges
    assert ("Portfolio Manager", END) not in graph.edges

    if concurrency == 1:
        assert ("Msg Clear News", "Research Evidence Packet") in graph.edges
    else:
        assert (
            "Analyst Batch 1 Complete",
            "Research Evidence Packet",
        ) in graph.edges
        start_route = next(
            path
            for source, path, path_map in graph.conditional_edges
            if source == START and path_map is None
        )
        fanout = start_route(_state())
        assert all(item.node not in packet_names for item in fanout)


def test_real_concurrent_join_publishes_research_once(monkeypatch, tmp_path):
    from tradingagents.graph import setup as setup_module
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup

    report_fields = {
        "create_prefetched_market_analyst": "market_report",
        "create_prefetched_news_analyst": "news_report",
    }
    for factory, field in report_fields.items():
        monkeypatch.setattr(
            setup_module,
            factory,
            lambda *_a, _field=field, **_k: (
                lambda _state: {
                    _field: f"{_field} value",
                    "messages": [
                        AIMessage(
                            content=f"{_field} complete",
                            id=f"{_field}-complete",
                        )
                    ],
                }
            ),
        )
    monkeypatch.setattr(setup_module, "create_msg_delete", lambda: (lambda _s: {}))
    for name in (
        "create_bull_researcher",
        "create_bear_researcher",
        "create_research_manager",
        "create_trader",
        "create_aggressive_debator",
        "create_neutral_debator",
        "create_conservative_debator",
        "create_portfolio_manager",
    ):
        monkeypatch.setattr(setup_module, name, lambda *_a, **_k: (lambda _s: {}))

    logic = ConditionalLogic()
    logic.should_continue_debate = lambda _state: "Research Manager"
    logic.should_continue_risk_analysis = lambda _state: "Portfolio Manager"
    ledger_root = tmp_path / "ledger"
    workflow = GraphSetup(
        quick_thinking_llm=object(),
        deep_thinking_llm=object(),
        tool_nodes={
            "market": lambda _state: {},
            "news": lambda _state: {},
        },
        conditional_logic=logic,
        analyst_concurrency_limit=2,
        tool_free_analysts={"market", "news"},
        ledger_root=ledger_root,
        evidence_root=tmp_path / "evidence",
    ).setup_graph(["market", "news"])

    result = workflow.compile().invoke(_state(), {"recursion_limit": 50})

    events = DecisionLedger(ledger_root).verify(evidence_root=tmp_path / "evidence")
    assert [event.kind for event in events].count("research_evidence") == 1
    assert [ref["kind"] for ref in result["decision_packet_refs"]] == [
        "research_evidence",
        "trader_proposal",
        "portfolio_decision",
    ]


def test_direct_nodes_publish_three_linked_packets_and_compact_refs(tmp_path):
    result, ledger, ledger_root, evidence_root = _run_nodes(tmp_path)
    refs = result["decision_packet_refs"]
    events = ledger.verify(evidence_root=evidence_root)

    assert [event.kind for event in events] == [
        "research_evidence",
        "trader_proposal",
        "portfolio_decision",
    ]
    assert [ref["kind"] for ref in refs] == [event.kind for event in events]
    assert len(refs) == 3
    assert set(refs[0]) == {
        "schema_version",
        "packet_id",
        "kind",
        "packet_sha256",
        "packet_path",
        "evidence_sha256",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }
    assert all(ref["schema_version"] == DECISION_PACKET_REF_SCHEMA_VERSION for ref in refs)
    assert all(ref["analysis_only"] is True for ref in refs)
    assert all(ref["execution_authority"] == "none" for ref in refs)
    assert all(ref["can_submit_orders"] is False for ref in refs)

    packets = [_packet_payload(ledger_root, ref) for ref in refs]
    assert packets[0]["parent_packet_ids"] == []
    assert packets[1]["parent_packet_ids"] == [refs[0]["packet_id"]]
    assert packets[2]["parent_packet_ids"] == [refs[1]["packet_id"]]
    for packet, ref in zip(packets, refs, strict=True):
        assert packet["created_at"] == RUN_STARTED_TEXT
        assert packet["expires_at"] == (
            RUN_STARTED + PACKET_HANDOFF_TTL
        ).isoformat(timespec="seconds")
        assert packet["confidence"] == 0.0
        assert f"output_kind={packet['kind']}" in packet["claims"]
        assert "verification=DecisionLedger.verify" in packet["claims"]
        assert (
            "non_decisions=orders,order_changes,position_sizing,"
            "live_control,risk_overrides"
        ) in packet["assumptions"]
        assert "confidence=uncalibrated" in packet["assumptions"]
        assert ref["packet_sha256"] == hashlib.sha256(
            json.dumps(
                packet,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()


def test_evidence_is_exact_content_addressed_and_relative(tmp_path):
    result, _, ledger_root, evidence_root = _run_nodes(tmp_path)
    refs = result["decision_packet_refs"]
    packets = [_packet_payload(ledger_root, ref) for ref in refs]
    evidence = [_evidence_payload(evidence_root, packet) for packet in packets]

    assert evidence[0]["state_slice"] == {
        "fundamentals_report": "FUNDAMENTALS FULL TEXT",
        "market_report": "MARKET FULL TEXT",
        "news_report": "NEWS FULL TEXT",
        "sentiment_report": "SENTIMENT FULL TEXT",
    }
    assert evidence[1]["state_slice"] == {
        "investment_debate_state.judge_decision": "RESEARCH MANAGER FULL TEXT",
        "investment_plan": "INVESTMENT PLAN FULL TEXT",
        "trader_investment_plan": "TRADER FULL TEXT",
    }
    assert evidence[2]["state_slice"] == {
        "final_trade_decision": "PORTFOLIO FULL TEXT",
        "risk_debate_state.judge_decision": "RISK MANAGER FULL TEXT",
    }
    for packet, ref, payload in zip(packets, refs, evidence, strict=True):
        evidence_ref = packet["evidence_refs"][0]
        assert not Path(evidence_ref["path"]).is_absolute()
        assert evidence_ref["path"].startswith(
            f"control_plane/decision_evidence/{_state()['run_id']}/"
        )
        raw = (evidence_root / evidence_ref["path"]).read_bytes()
        assert raw == json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        assert evidence_ref["sha256"] == hashlib.sha256(raw).hexdigest()
        assert ref["evidence_sha256"] == evidence_ref["sha256"]
        assert Path(evidence_ref["path"]).name == (
            f"{packet['kind']}-{evidence_ref['sha256']}.json"
        )
        assert set(payload) == {
            "schema_version",
            "packet_kind",
            "run_id",
            "run_started_at",
            "company_of_interest",
            "trade_date",
            "asset_type",
            "parent_packet_ids",
            "state_slice",
            "analysis_only",
            "execution_authority",
            "can_submit_orders",
        }


def test_packets_and_refs_exclude_full_analysis_text(tmp_path):
    result, _, ledger_root, _ = _run_nodes(tmp_path)
    forbidden_text = (
        "MARKET FULL TEXT",
        "SENTIMENT FULL TEXT",
        "NEWS FULL TEXT",
        "FUNDAMENTALS FULL TEXT",
        "RESEARCH MANAGER FULL TEXT",
        "INVESTMENT PLAN FULL TEXT",
        "TRADER FULL TEXT",
        "RISK MANAGER FULL TEXT",
        "PORTFOLIO FULL TEXT",
    )
    compact_text = json.dumps(result["decision_packet_refs"])
    for ref in result["decision_packet_refs"]:
        compact_text += json.dumps(_packet_payload(ledger_root, ref))
    assert all(text not in compact_text for text in forbidden_text)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("market_report", None),
        ("investment_plan", ["not", "text"]),
        ("final_trade_decision", {"decision": "HOLD"}),
    ),
)
def test_selected_evidence_values_must_be_strings(tmp_path, field, value):
    state = _state()
    state[field] = value
    _, _, nodes = _node_triplet(tmp_path)
    node_index = {
        "market_report": 0,
        "investment_plan": 1,
        "final_trade_decision": 2,
    }[field]
    if node_index:
        current = _state()
        for prior in nodes[:node_index]:
            current.update(prior(current))
        current[field] = value
        state = current

    with pytest.raises(ValueError, match="must be a string"):
        nodes[node_index](state)


@pytest.mark.parametrize(
    "mutation",
    (
        "forged",
        "wrong_run",
        "extra",
        "duplicate",
        "out_of_order",
        "packet_digest",
        "packet_path",
        "evidence_digest",
        "authority",
    ),
)
def test_untrusted_parent_refs_fail_before_child_artifact_or_event(
    tmp_path,
    mutation,
):
    state = _state()
    ledger_root, evidence_root, nodes = _node_triplet(tmp_path)
    state.update(nodes[0](state))
    original = copy.deepcopy(state["decision_packet_refs"][0])
    if mutation == "forged":
        state["decision_packet_refs"][0]["packet_id"] = (
            "wp-" + state["run_id"] + "-research_synthesis"
        )
    elif mutation == "wrong_run":
        state["run_id"] = "graph-" + "2" * 64
    elif mutation == "extra":
        state["decision_packet_refs"].append(copy.deepcopy(original))
        state["decision_packet_refs"][1]["kind"] = "trader_proposal"
    elif mutation == "duplicate":
        state["decision_packet_refs"].append(copy.deepcopy(original))
    elif mutation == "out_of_order":
        state["decision_packet_refs"] = [
            {**original, "kind": "trader_proposal"},
            original,
        ]
    elif mutation == "packet_digest":
        state["decision_packet_refs"][0]["packet_sha256"] = "0" * 64
    elif mutation == "packet_path":
        state["decision_packet_refs"][0]["packet_path"] = "packets/forged.json"
    elif mutation == "evidence_digest":
        state["decision_packet_refs"][0]["evidence_sha256"] = "0" * 64
    elif mutation == "authority":
        state["decision_packet_refs"][0]["execution_authority"] = "live"

    event_bytes = (ledger_root / "events.jsonl").read_bytes()
    evidence_before = set(evidence_root.rglob("*"))
    with pytest.raises(ValueError):
        nodes[1](state)
    assert (ledger_root / "events.jsonl").read_bytes() == event_bytes
    assert set(evidence_root.rglob("*")) == evidence_before


def test_same_node_retry_is_event_and_ref_silent(tmp_path):
    state = _state()
    ledger_root, evidence_root, nodes = _node_triplet(tmp_path)
    first = nodes[0](state)
    state.update(first)
    event_bytes = (ledger_root / "events.jsonl").read_bytes()
    evidence_bytes = {
        path: path.read_bytes()
        for path in evidence_root.rglob("*.json")
    }

    second = nodes[0](state)

    assert second["decision_packet_refs"] == first["decision_packet_refs"]
    assert (ledger_root / "events.jsonl").read_bytes() == event_bytes
    assert {
        path: path.read_bytes()
        for path in evidence_root.rglob("*.json")
    } == evidence_bytes


def test_changed_retry_collides_without_mutating_durable_prior_state(tmp_path):
    state = _state()
    ledger_root, evidence_root, nodes = _node_triplet(tmp_path)
    state.update(nodes[0](state))
    ref = state["decision_packet_refs"][0]
    packet_path = ledger_root / ref["packet_path"]
    pointer_path = ledger_root / "latest" / "research_evidence.json"
    prior_evidence_path = (
        evidence_root
        / _packet_payload(ledger_root, ref)["evidence_refs"][0]["path"]
    )
    before = {
        "journal": (ledger_root / "events.jsonl").read_bytes(),
        "packet": packet_path.read_bytes(),
        "pointer": pointer_path.read_bytes(),
        "evidence": prior_evidence_path.read_bytes(),
    }
    state["market_report"] = "CHANGED MARKET REPORT"

    with pytest.raises(PacketCollisionError):
        nodes[0](state)

    assert (ledger_root / "events.jsonl").read_bytes() == before["journal"]
    assert packet_path.read_bytes() == before["packet"]
    assert pointer_path.read_bytes() == before["pointer"]
    assert prior_evidence_path.read_bytes() == before["evidence"]
    assert len(
        DecisionLedger(ledger_root).verify(evidence_root=evidence_root)
    ) == 1


def test_stale_retry_fails_before_new_event(tmp_path):
    current = RUN_STARTED + PACKET_HANDOFF_TTL
    state = _state()
    ledger_root, evidence_root, nodes = _node_triplet(
        tmp_path,
        clock=lambda: current,
    )

    with pytest.raises(ValueError, match="expired"):
        nodes[0](state)

    assert not (ledger_root / "events.jsonl").exists()
    assert DecisionLedger(ledger_root).verify(evidence_root=evidence_root) == ()


def test_crash_after_ledger_record_retries_same_packet_and_event(
    tmp_path,
    monkeypatch,
):
    from tradingagents.graph import packet_nodes as packet_nodes_module

    state = _state()
    ledger_root, evidence_root, nodes = _node_triplet(tmp_path)
    real_record = packet_nodes_module.DecisionLedger.record
    crashed = False

    def record_then_crash(self, packet, **kwargs):
        nonlocal crashed
        path = real_record(self, packet, **kwargs)
        if not crashed:
            crashed = True
            raise RuntimeError("injected after ledger record")
        return path

    monkeypatch.setattr(
        packet_nodes_module.DecisionLedger,
        "record",
        record_then_crash,
    )
    with pytest.raises(RuntimeError, match="after ledger record"):
        nodes[0](state)
    event_bytes = (ledger_root / "events.jsonl").read_bytes()

    result = nodes[0](state)

    assert result["decision_packet_refs"][0]["kind"] == "research_evidence"
    assert (ledger_root / "events.jsonl").read_bytes() == event_bytes
    assert len(
        DecisionLedger(ledger_root).verify(evidence_root=evidence_root)
    ) == 1


def test_real_checkpoint_resume_reuses_run_clock_packet_and_evidence(
    tmp_path,
    monkeypatch,
):
    from tradingagents.agents.utils.agent_states import AgentState
    from tradingagents.graph import packet_nodes as packet_nodes_module

    state = _state()
    ledger_root = tmp_path / "ledger"
    evidence_root = tmp_path / "evidence"
    node = create_research_evidence_packet_node(
        ledger_root,
        evidence_root,
        clock=lambda: NOW,
    )
    real_record = packet_nodes_module.DecisionLedger.record
    crashed = False

    def record_then_crash(self, packet, **kwargs):
        nonlocal crashed
        path = real_record(self, packet, **kwargs)
        if not crashed:
            crashed = True
            raise RuntimeError("injected after ledger record")
        return path

    monkeypatch.setattr(
        packet_nodes_module.DecisionLedger,
        "record",
        record_then_crash,
    )
    workflow = StateGraph(AgentState)
    workflow.add_node("Research Evidence Packet", node)
    workflow.set_entry_point("Research Evidence Packet")
    workflow.add_edge("Research Evidence Packet", END)
    graph = workflow.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "packet-crash-resume"}}

    with pytest.raises(RuntimeError, match="after ledger record"):
        graph.invoke(state, config=config)
    event_before = (ledger_root / "events.jsonl").read_bytes()
    evidence_before = {
        path.relative_to(evidence_root): path.read_bytes()
        for path in evidence_root.rglob("*.json")
    }

    result = graph.invoke(None, config=config)

    assert result["run_id"] == state["run_id"]
    assert result["run_started_at"] == RUN_STARTED_TEXT
    assert len(result["decision_packet_refs"]) == 1
    assert (ledger_root / "events.jsonl").read_bytes() == event_before
    assert {
        path.relative_to(evidence_root): path.read_bytes()
        for path in evidence_root.rglob("*.json")
    } == evidence_before
    assert len(
        DecisionLedger(ledger_root).verify(evidence_root=evidence_root)
    ) == 1


def test_packet_module_imports_no_execution_or_external_call_surface():
    import tradingagents.graph.packet_nodes as packet_nodes_module

    source = Path(packet_nodes_module.__file__).read_text()
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = (
        "broker",
        "order",
        "execution",
        "signal_processing",
        "live_control",
        "policy.authority",
        "langchain",
        "llm",
        "requests",
        "httpx",
        "yfinance",
    )

    assert not any(
        token in imported_name
        for imported_name in imported
        for token in forbidden
    )


def test_evidence_root_and_managed_symlinks_fail_closed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    evidence_link = tmp_path / "evidence-link"
    evidence_link.symlink_to(outside, target_is_directory=True)
    node = create_research_evidence_packet_node(
        tmp_path / "ledger-one",
        evidence_link,
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="symlink"):
        node(_state())
    assert list(outside.iterdir()) == []

    evidence_root = tmp_path / "evidence"
    (evidence_root / "control_plane").mkdir(parents=True)
    managed = evidence_root / "control_plane" / "decision_evidence"
    managed.symlink_to(outside, target_is_directory=True)
    node = create_research_evidence_packet_node(
        tmp_path / "ledger-two",
        evidence_root,
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="symlink"):
        node(_state())
    assert list(outside.iterdir()) == []
