"""Test checkpoint resume: crash mid-analysis, re-run resumes from last node."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpointer import (
    checkpoint_step,
    clear_checkpoint,
    get_checkpointer,
    has_checkpoint,
    thread_id,
)

# Mutable flag to simulate crash on first run
_should_crash = False


class _SimpleState(TypedDict):
    count: int


def _node_a(state: _SimpleState) -> dict:
    return {"count": state["count"] + 1}


def _node_b(state: _SimpleState) -> dict:
    if _should_crash:
        raise RuntimeError("simulated mid-analysis crash")
    return {"count": state["count"] + 10}


def _build_graph() -> StateGraph:
    builder = StateGraph(_SimpleState)
    builder.add_node("analyst", _node_a)
    builder.add_node("trader", _node_b)
    builder.set_entry_point("analyst")
    builder.add_edge("analyst", "trader")
    builder.add_edge("trader", END)
    return builder


class TestCheckpointResume(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ticker = "TEST"
        self.date = "2026-04-20"
        self.signature = '{"schema_version":1,"shape":"test"}'

    def test_crash_and_resume(self):
        """Crash at 'trader' node, then resume from checkpoint."""
        global _should_crash
        builder = _build_graph()
        tid = thread_id(self.ticker, self.date, self.signature)
        cfg = {"configurable": {"thread_id": tid}}

        # Run 1: crash at trader node
        _should_crash = True
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config=cfg)

        # Checkpoint should exist at step 1 (analyst completed)
        self.assertTrue(
            has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature)
        )
        step = checkpoint_step(
            self.tmpdir, self.ticker, self.date, self.signature
        )
        self.assertEqual(step, 1)

        # Run 2: resume — trader succeeds this time
        _should_crash = False
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke(None, config=cfg)

        # analyst added 1, trader added 10 → 11
        self.assertEqual(result["count"], 11)

    def test_clear_checkpoint_allows_fresh_start(self):
        """After clearing, the graph starts from scratch."""
        global _should_crash
        builder = _build_graph()
        tid = thread_id(self.ticker, self.date, self.signature)
        cfg = {"configurable": {"thread_id": tid}}

        # Create a checkpoint by crashing
        _should_crash = True
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config=cfg)

        self.assertTrue(
            has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature)
        )

        # Clear it
        clear_checkpoint(self.tmpdir, self.ticker, self.date, self.signature)
        self.assertFalse(
            has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature)
        )

        # Fresh run succeeds from scratch
        _should_crash = False
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke({"count": 0}, config=cfg)

        self.assertEqual(result["count"], 11)


    def test_different_date_starts_fresh(self):
        """A different date must NOT resume from an existing checkpoint."""
        global _should_crash
        builder = _build_graph()
        date2 = "2026-04-21"

        # Run with date1 — crash to leave a checkpoint
        _should_crash = True
        tid1 = thread_id(self.ticker, self.date, self.signature)
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config={"configurable": {"thread_id": tid1}})

        self.assertTrue(
            has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature)
        )

        # date2 should have no checkpoint
        self.assertFalse(
            has_checkpoint(self.tmpdir, self.ticker, date2, self.signature)
        )

        # Run with date2 — should start fresh and succeed
        _should_crash = False
        tid2 = thread_id(self.ticker, date2, self.signature)
        self.assertNotEqual(tid1, tid2)

        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke({"count": 0}, config={"configurable": {"thread_id": tid2}})

        # Fresh run: analyst +1, trader +10 = 11
        self.assertEqual(result["count"], 11)

        # Original date checkpoint still exists (untouched)
        self.assertTrue(
            has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature)
        )


def _bare_signature_graph(
    *,
    selected_analysts=("market", "news"),
    config_overrides=None,
):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = tuple(selected_analysts)
    graph.config = {
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_analyst_tool_rounds": 8,
        "analyst_concurrency_limit": 2,
        "tool_free_analysts": ["news", "market"],
    }
    graph.config.update(config_overrides or {})
    graph._checkpoint_shape = {
        "schema_version": graph.config.get(
            "checkpoint_signature_schema_version",
            1,
        ),
        "selected_analysts": graph.selected_analysts,
        "max_debate_rounds": graph.config["max_debate_rounds"],
        "max_risk_discuss_rounds": graph.config["max_risk_discuss_rounds"],
        "max_analyst_tool_rounds": graph.config["max_analyst_tool_rounds"],
        "analyst_concurrency_limit": graph.config["analyst_concurrency_limit"],
        "tool_free_analysts": tuple(
            sorted(set(graph.config["tool_free_analysts"]))
        ),
        "source_revision": graph.config.get("checkpoint_source_revision"),
        "packet_handoff_schema_version": graph.config.get(
            "packet_handoff_schema_version",
            1,
        ),
    }
    return graph


def test_run_signature_is_stable_canonical_and_allowlisted():
    graph = _bare_signature_graph(
        config_overrides={
            "started_at": "2026-07-19T01:00:00Z",
            "project_dir": "/private/tmp/first-worktree",
            "data_cache_dir": "/private/tmp/cache-one",
            "results_dir": "/private/tmp/results-one",
            "last_model_response": "BUY EVERYTHING",
            "prompt_text": "volatile prompt",
            "api_key": "must-not-enter-signature",
        }
    )

    first = graph._run_signature("stock")
    second = graph._run_signature("stock")
    assert first == second
    assert set(json.loads(first)) == {
        "analyst_concurrency_limit",
        "asset_type",
        "max_debate_rounds",
        "max_analyst_tool_rounds",
        "max_risk_discuss_rounds",
        "packet_handoff_schema_version",
        "schema_version",
        "selected_analysts",
        "source_revision",
        "tool_free_analysts",
    }

    graph.config.update(
        {
            "started_at": "2099-12-31T23:59:59Z",
            "project_dir": "/different/absolute/worktree",
            "data_cache_dir": "/different/cache",
            "results_dir": "/different/results",
            "last_model_response": "SELL EVERYTHING",
            "prompt_text": "different prompt",
            "api_key": "different-secret",
        }
    )
    assert graph._run_signature("stock") == first


@pytest.mark.parametrize(
    ("selected_analysts", "asset_type", "config_override"),
    (
        (("news", "market"), "stock", {}),
        (("market", "news"), "crypto", {}),
        (("market", "news"), "stock", {"max_debate_rounds": 2}),
        (("market", "news"), "stock", {"max_risk_discuss_rounds": 2}),
        (("market", "news"), "stock", {"max_analyst_tool_rounds": 2}),
        (("market", "news"), "stock", {"analyst_concurrency_limit": 1}),
        (
            ("market", "news"),
            "stock",
            {"tool_free_analysts": ["market"]},
        ),
        (
            ("market", "news"),
            "stock",
            {"checkpoint_signature_schema_version": 2},
        ),
        (
            ("market", "news"),
            "stock",
            {"checkpoint_source_revision": "a" * 40},
        ),
        (
            ("market", "news"),
            "stock",
            {"packet_handoff_schema_version": 2},
        ),
    ),
)
def test_run_signature_changes_for_every_graph_shape_input(
    selected_analysts,
    asset_type,
    config_override,
):
    baseline = _bare_signature_graph()._run_signature("stock")
    changed = _bare_signature_graph(
        selected_analysts=selected_analysts,
        config_overrides=config_override,
    )._run_signature(asset_type)
    assert changed != baseline


def test_run_signature_sorts_only_set_semantics():
    baseline = _bare_signature_graph(
        config_overrides={"tool_free_analysts": ["news", "market", "news"]}
    )._run_signature("stock")
    reordered_set = _bare_signature_graph(
        config_overrides={"tool_free_analysts": ["market", "news"]}
    )._run_signature("stock")
    reordered_analysts = _bare_signature_graph(
        selected_analysts=("news", "market"),
        config_overrides={"tool_free_analysts": ["market", "news"]},
    )._run_signature("stock")

    assert reordered_set == baseline
    assert reordered_analysts != baseline


def test_run_signature_tracks_the_frozen_graph_not_later_config_mutation():
    graph = _bare_signature_graph()
    baseline = graph._run_signature("stock")

    graph.config.update(
        {
            "max_debate_rounds": 99,
            "max_risk_discuss_rounds": 99,
            "analyst_concurrency_limit": 99,
            "tool_free_analysts": [],
            "checkpoint_signature_schema_version": 99,
            "checkpoint_source_revision": "b" * 40,
        }
    )

    assert graph._run_signature("stock") == baseline


def test_constructor_consumes_analyst_generator_once_and_freezes_same_order(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module

    captured = {}

    class _Client:
        def get_llm(self):
            return object()

    class _Workflow:
        def compile(self):
            return object()

    class _GraphSetup:
        def __init__(self, *_args, **kwargs):
            captured["setup_kwargs"] = kwargs

        def setup_graph(self, analysts):
            captured["workflow_analysts"] = analysts
            return _Workflow()

    monkeypatch.setattr(trading_graph_module, "set_config", lambda _config: None)
    monkeypatch.setattr(
        trading_graph_module,
        "create_llm_client",
        lambda **_kwargs: _Client(),
    )
    monkeypatch.setattr(
        trading_graph_module.TradingAgentsGraph,
        "_create_tool_nodes",
        lambda _self: {},
    )
    monkeypatch.setattr(
        trading_graph_module,
        "TradingMemoryLog",
        lambda _config: object(),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "GraphSetup",
        _GraphSetup,
    )

    def _propagator(**kwargs):
        captured["propagator_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(
        trading_graph_module,
        "Propagator",
        _propagator,
    )
    monkeypatch.setattr(
        trading_graph_module,
        "Reflector",
        lambda _llm: object(),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "SignalProcessor",
        lambda _llm: object(),
    )

    config = dict(DEFAULT_CONFIG)
    config.update(
        {
            "data_cache_dir": str(tmp_path / "cache"),
            "results_dir": str(tmp_path / "results"),
            "analyst_concurrency_limit": 2,
            "tool_free_analysts": ["news", "market"],
        }
    )
    selected = (analyst for analyst in ("news", "market"))
    graph = trading_graph_module.TradingAgentsGraph(
        selected_analysts=selected,
        config=config,
    )

    assert graph.selected_analysts == ("news", "market")
    assert captured["workflow_analysts"] == ("news", "market")
    assert graph._checkpoint_shape["selected_analysts"] == ("news", "market")
    assert graph._checkpoint_shape["packet_handoff_schema_version"] == 1
    assert captured["setup_kwargs"]["ledger_root"] == (
        tmp_path / "results" / "control_plane" / "decisions"
    )
    assert captured["setup_kwargs"]["evidence_root"] == tmp_path / "results"
    assert (
        captured["propagator_kwargs"]["run_signature_factory"].__self__
        is graph
    )
    assert json.loads(graph._run_signature("stock"))["selected_analysts"] == [
        "news",
        "market",
    ]
    assert list(selected) == []


@pytest.mark.parametrize(
    "bad_revision",
    (
        "/private/tmp/worktree",
        "abc1234-dirty",
        "revision with spaces",
        "",
    ),
)
def test_run_signature_rejects_non_clean_source_revision(bad_revision):
    graph = _bare_signature_graph(
        config_overrides={"checkpoint_source_revision": bad_revision}
    )
    with pytest.raises(ValueError, match="checkpoint_source_revision"):
        graph._run_signature("stock")


@pytest.mark.parametrize("bad_version", (True, False, 0, -1, 1.0, "1"))
def test_run_signature_rejects_invalid_packet_handoff_version(bad_version):
    graph = _bare_signature_graph()
    graph._checkpoint_shape["packet_handoff_schema_version"] = bad_version

    with pytest.raises(ValueError, match="packet_handoff_schema_version"):
        graph._run_signature("stock")


def test_checkpoint_shape_isolation_and_targeted_clear(tmp_path):
    global _should_crash
    ticker = "TEST"
    date = "2026-04-20"
    signature_a = '{"schema_version":1,"selected_analysts":["market"]}'
    signature_b = '{"schema_version":1,"selected_analysts":["news"]}'
    builder = _build_graph()

    _should_crash = True
    tid_a = thread_id(ticker, date, signature_a)
    with get_checkpointer(tmp_path, ticker) as saver:
        graph = builder.compile(checkpointer=saver)
        with pytest.raises(RuntimeError, match="simulated mid-analysis crash"):
            graph.invoke(
                {"count": 0},
                config={"configurable": {"thread_id": tid_a}},
            )

    assert has_checkpoint(tmp_path, ticker, date, signature_a)
    assert checkpoint_step(tmp_path, ticker, date, signature_a) == 1
    assert not has_checkpoint(tmp_path, ticker, date, signature_b)
    assert checkpoint_step(tmp_path, ticker, date, signature_b) is None

    _should_crash = False
    with get_checkpointer(tmp_path, ticker) as saver:
        graph = builder.compile(checkpointer=saver)
        result = graph.invoke(
            None,
            config={"configurable": {"thread_id": tid_a}},
        )
    assert result["count"] == 11

    clear_checkpoint(tmp_path, ticker, date, signature_b)
    assert has_checkpoint(tmp_path, ticker, date, signature_a)
    clear_checkpoint(tmp_path, ticker, date, signature_a)
    assert not has_checkpoint(tmp_path, ticker, date, signature_a)


def test_unsigned_checkpoints_require_explicit_legacy_compatibility(tmp_path):
    ticker = "TEST"
    date = "2026-04-20"
    legacy = hashlib.sha256(f"{ticker}:{date}".encode()).hexdigest()[:16]

    assert thread_id(
        ticker,
        date,
        allow_legacy_empty_signature=True,
    ) == legacy
    assert thread_id(
        ticker,
        date,
        "",
        allow_legacy_empty_signature=True,
    ) == legacy

    with pytest.raises(ValueError, match="signature"):
        thread_id(ticker, date)
    for operation in (has_checkpoint, checkpoint_step, clear_checkpoint):
        with pytest.raises(ValueError, match="signature"):
            operation(tmp_path, ticker, date)
    assert not (Path(tmp_path) / "checkpoints").exists()

    assert not has_checkpoint(
        tmp_path,
        ticker,
        date,
        allow_legacy_empty_signature=True,
    )


@pytest.mark.parametrize("bad_signature", ("", " ", "\tsigned", 3, False))
def test_malformed_checkpoint_signatures_fail_closed(bad_signature):
    with pytest.raises((TypeError, ValueError), match="signature"):
        thread_id("TEST", "2026-04-20", bad_signature)


def test_trading_graph_uses_one_signature_for_lookup_resume_and_clear(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    signature_calls = []
    observed = []

    class _RuntimeGraph:
        def get_state(self, _config):
            return type("_Snapshot", (), {"values": {}})()

        def invoke(self, _state, **_kwargs):
            return {"final_trade_decision": "HOLD"}

    class _Workflow:
        def compile(self, **_kwargs):
            return _RuntimeGraph()

    class _CheckpointerContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return None

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
    }
    graph.workflow = _Workflow()
    graph.graph = _RuntimeGraph()
    graph._checkpointer_ctx = None
    graph.debug = False
    graph.propagator = type(
        "_Propagator",
        (),
        {
            "create_initial_state": staticmethod(lambda *_args, **_kwargs: {}),
            "get_graph_args": staticmethod(lambda: {}),
        },
    )()
    graph.memory_log = type(
        "_Memory",
        (),
        {
            "get_past_context": staticmethod(lambda _ticker: ""),
            "store_decision": staticmethod(lambda **_kwargs: None),
        },
    )()
    graph._resolve_pending_entries = lambda _ticker: None
    graph._log_state = lambda _date, _state: None
    graph.process_signal = lambda signal: signal
    graph._run_signature = lambda asset: (
        signature_calls.append(asset) or "one-canonical-signature"
    )

    monkeypatch.setattr(
        trading_graph_module,
        "get_checkpointer",
        lambda *_args: _CheckpointerContext(),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "checkpoint_step",
        lambda _data, _ticker, _date, signature: (
            observed.append(("lookup", signature)) or None
        ),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "thread_id",
        lambda _ticker, _date, signature: (
            observed.append(("resume", signature)) or "thread"
        ),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "clear_checkpoint",
        lambda _data, _ticker, _date, signature: observed.append(
            ("clear", signature)
        ),
    )

    result, signal = graph.propagate("TEST", "2026-04-20", asset_type="stock")

    assert result["final_trade_decision"] == "HOLD"
    assert signal == "HOLD"
    assert signature_calls == ["stock"]
    assert observed == [
        ("lookup", "one-canonical-signature"),
        ("resume", "one-canonical-signature"),
        ("clear", "one-canonical-signature"),
    ]


def test_run_graph_resumes_saved_state_with_none_and_preserves_all_fields(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.packet_nodes import build_graph_run_id
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.orchestration.work_packets import build_packet_id

    signature = '{"packet_handoff_schema_version":1,"shape":"saved"}'
    run_id = build_graph_run_id("TEST", "2026-04-20", "stock", signature)
    packet_id = build_packet_id(run_id, "research_evidence")
    packet_ref = {
        "schema_version": 1,
        "packet_id": packet_id,
        "kind": "research_evidence",
        "packet_sha256": "a" * 64,
        "packet_path": f"packets/{packet_id}.json",
        "evidence_sha256": "b" * 64,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    saved = {
        "run_id": run_id,
        "run_started_at": "2026-04-20T13:30:00+00:00",
        "decision_packet_refs": [packet_ref],
        "learning_context": "saved bounded context",
        "market_report": "saved market report",
        "investment_debate_state": {"judge_decision": "saved debate"},
        "final_trade_decision": "HOLD",
    }
    invocations = []

    class _RuntimeGraph:
        def get_state(self, config):
            invocations.append(("get_state", config))
            return type("_Snapshot", (), {"values": saved})()

        def invoke(self, state, **kwargs):
            invocations.append(("invoke", state, kwargs))
            return dict(saved)

    class _Propagator:
        @staticmethod
        def get_graph_args():
            return {"config": {"recursion_limit": 100}}

        @staticmethod
        def create_initial_state(*_args, **_kwargs):
            raise AssertionError("resume must not construct fresh state")

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
    }
    graph.graph = _RuntimeGraph()
    graph.propagator = _Propagator()
    graph.debug = False
    graph.memory_log = type(
        "_Memory",
        (),
        {
            "get_past_context": staticmethod(
                lambda _ticker: (_ for _ in ()).throw(
                    AssertionError("resume must preserve saved context")
                )
            ),
            "store_decision": staticmethod(lambda **_kwargs: None),
        },
    )()
    graph._log_state = lambda _date, _state: None
    graph.process_signal = lambda signal: signal
    cleared = []
    monkeypatch.setattr(
        trading_graph_module,
        "thread_id",
        lambda *_args: "saved-thread",
    )
    monkeypatch.setattr(
        trading_graph_module,
        "clear_checkpoint",
        lambda *_args: cleared.append(True),
    )

    result, signal = graph._run_graph(
        "TEST",
        "2026-04-20",
        checkpoint_signature=signature,
    )

    assert invocations[0][0] == "get_state"
    assert invocations[1][0:2] == ("invoke", None)
    assert result == saved
    assert result["decision_packet_refs"] == [packet_ref]
    assert result["learning_context"] == "saved bounded context"
    assert result["market_report"] == "saved market report"
    assert result["investment_debate_state"] == {
        "judge_decision": "saved debate"
    }
    assert signal == "HOLD"
    assert cleared == [True]


@pytest.mark.parametrize(
    "corruption",
    ("run_id", "run_started_at", "packet_refs", "learning_context"),
)
def test_run_graph_rejects_malformed_saved_identity_before_invocation(
    monkeypatch,
    tmp_path,
    corruption,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.packet_nodes import build_graph_run_id
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.orchestration.work_packets import build_packet_id

    signature = '{"packet_handoff_schema_version":1,"shape":"saved"}'
    run_id = build_graph_run_id("TEST", "2026-04-20", "stock", signature)
    packet_id = build_packet_id(run_id, "research_evidence")
    saved = {
        "run_id": run_id,
        "run_started_at": "2026-04-20T13:30:00+00:00",
        "decision_packet_refs": [
            {
                "schema_version": 1,
                "packet_id": packet_id,
                "kind": "research_evidence",
                "packet_sha256": "a" * 64,
                "packet_path": f"packets/{packet_id}.json",
                "evidence_sha256": "b" * 64,
                "analysis_only": True,
                "execution_authority": "none",
                "can_submit_orders": False,
            }
        ],
        "learning_context": "saved context",
        "final_trade_decision": "HOLD",
    }
    if corruption == "run_id":
        saved["run_id"] = "graph-" + "f" * 64
    elif corruption == "run_started_at":
        saved["run_started_at"] = "2026-04-20T13:30:00Z"
    elif corruption == "packet_refs":
        saved["decision_packet_refs"][0]["execution_authority"] = "live"
    else:
        saved["learning_context"] = 3
    invoked = []

    class _RuntimeGraph:
        def get_state(self, _config):
            return type("_Snapshot", (), {"values": saved})()

        def invoke(self, _state, **_kwargs):
            invoked.append(True)
            return saved

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
    }
    graph.graph = _RuntimeGraph()
    graph.propagator = type(
        "_Propagator",
        (),
        {
            "get_graph_args": staticmethod(lambda: {}),
            "create_initial_state": staticmethod(
                lambda *_args, **_kwargs: invoked.append("fresh")
            ),
        },
    )()
    graph.debug = False
    graph.memory_log = type("_Memory", (), {})()
    monkeypatch.setattr(
        trading_graph_module,
        "thread_id",
        lambda *_args: "saved-thread",
    )

    with pytest.raises(ValueError, match="checkpoint"):
        graph._run_graph(
            "TEST",
            "2026-04-20",
            checkpoint_signature=signature,
        )

    assert invoked == []


def test_propagate_freezes_signature_before_noncheckpoint_side_effects():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": False}
    graph._checkpointer_ctx = None
    graph.workflow = type(
        "_Workflow",
        (),
        {"compile": staticmethod(lambda: object())},
    )()
    order = []
    graph._run_signature = lambda asset: (
        order.append(("signature", asset)) or "frozen-signature"
    )
    graph._resolve_pending_entries = lambda ticker: order.append(
        ("resolve", ticker)
    )
    graph._run_graph = lambda *_args, **kwargs: (
        order.append(("run", kwargs["checkpoint_signature"]))
        or ("state", "signal")
    )

    assert graph.propagate("TEST", "2026-04-20") == ("state", "signal")
    assert order == [
        ("signature", "stock"),
        ("resolve", "TEST"),
        ("run", "frozen-signature"),
    ]


def test_real_graph_rejects_nonstring_signature_before_side_effects():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": False}
    graph._run_signature = lambda _asset: object()
    side_effects = []
    graph._resolve_pending_entries = lambda _ticker: side_effects.append(True)

    with pytest.raises(ValueError, match="graph run signature"):
        graph.propagate("TEST", "2026-04-20")

    assert side_effects == []


def test_invalid_signature_config_fails_before_run_side_effects(tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
    }
    graph._checkpoint_shape = {
        "schema_version": 0,
        "selected_analysts": ("market",),
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "analyst_concurrency_limit": 1,
        "tool_free_analysts": (),
        "source_revision": None,
        "packet_handoff_schema_version": 1,
    }
    side_effects = []
    graph._resolve_pending_entries = lambda _ticker: side_effects.append("resolved")

    with pytest.raises(
        ValueError,
        match="checkpoint_signature_schema_version",
    ):
        graph.propagate("TEST", "2026-04-20")

    assert side_effects == []
    assert not (tmp_path / "checkpoints").exists()


def test_llm_retry_default_and_explicit_zero():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    assert DEFAULT_CONFIG["llm_max_retries"] == 2
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"llm_provider": "openai", "llm_max_retries": 0}
    assert graph._get_provider_kwargs()["max_retries"] == 0


@pytest.mark.parametrize(
    "bad_value",
    (True, False, -1, 1.0, 1.5, "0", "2", [], {}),
)
def test_invalid_programmatic_llm_retry_values_fail_closed(bad_value):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "openai",
        "llm_max_retries": bad_value,
    }
    with pytest.raises(ValueError, match="llm_max_retries"):
        graph._get_provider_kwargs()


def test_none_llm_retry_value_is_not_forwarded():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "openai",
        "llm_max_retries": None,
    }
    assert "max_retries" not in graph._get_provider_kwargs()


if __name__ == "__main__":
    unittest.main()
