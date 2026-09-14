"""Test checkpoint resume: crash mid-analysis, re-run resumes from last node."""

import hashlib
import json
import os
import stat
import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpoint_identity import build_checkpoint_run_identity
from tradingagents.graph.checkpoint_runtime_identity import capture_checkpoint_predecessors
from tradingagents.graph.checkpointer import (
    CheckpointCustodyError,
    checkpoint_retention_report,
    checkpoint_status,
    checkpoint_step,
    clear_all_checkpoints,
    clear_checkpoint,
    find_incompatible_checkpoint,
    get_checkpointer,
    has_checkpoint,
    thread_id,
)

# Mutable flag to simulate crash on first run
_should_crash = False


class _SimpleState(TypedDict):
    count: int


class _IdentityState(TypedDict):
    company_of_interest: str
    trade_date: str
    checkpoint_run_identity: dict[str, object]


class _CustodyState(TypedDict, total=False):
    company_of_interest: str
    trade_date: str
    checkpoint_run_identity: dict[str, object]
    run_id: str
    run_started_at: str
    final_trade_decision: str
    market_report: str


def _checkpoint_identity(*, results_dir=None, **changes: object):
    fields: dict[str, object] = {
        "identity_schema_version": 2,
        "clean_source_revision": "a" * 40,
        "source_tree_dirty": False,
        "uv_lock_sha256": "b" * 64,
        "selected_analysts": ("market", "news"),
        "asset_type": "stock",
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_analyst_tool_rounds": 8,
        "max_recur_limit": 100,
        "analyst_concurrency_limit": 1,
        "tool_free_analysts": (),
        "requested_provider": "openrouter",
        "requested_quick_model": "openai/gpt-5-mini",
        "requested_deep_model": "anthropic/claude-sonnet-4-5",
        "backend_route_identity": "https://router.example/v1?region=us",
        "output_language": "English",
        "provider_reasoning_settings": {"thinking": {"effort": "high"}},
        "graph_topology_sha256": "c" * 64,
        "agent_prompt_surface_sha256": "d" * 64,
        "bound_tool_surface_sha256": "e" * 64,
        "data_route_surface_sha256": "f" * 64,
        "packet_handoff_schema_version": 1,
        "learning_context_policy_identity": "learning-context-policy-v2",
        "trade_date_cutoff_policy_identity": "market-date-cutoff-v1",
        "learning_evidence_predecessor": "1" * 64,
        "decision_ledger_predecessor": "2" * 64,
    }
    if results_dir is not None:
        fields.update(capture_checkpoint_predecessors({"results_dir": str(results_dir)}))
    fields.update(changes)
    return build_checkpoint_run_identity(**fields)


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


def _build_identity_graph() -> StateGraph:
    builder = StateGraph(_IdentityState)
    builder.add_node("done", lambda _state: {})
    builder.set_entry_point("done")
    builder.add_edge("done", END)
    return builder


def _build_custody_graph() -> StateGraph:
    builder = StateGraph(_CustodyState)
    builder.add_node("done", lambda _state: {})
    builder.set_entry_point("done")
    builder.add_edge("done", END)
    return builder


def _write_custody_checkpoint(
    data_dir: Path,
    identity,
    *,
    ticker: str = "TEST",
    date: str = "2026-04-20",
    run_started_at: str = "2026-04-20T13:30:00+00:00",
    final_trade_decision: str = "HOLD",
    market_report: str = "safe report",
) -> None:
    with get_checkpointer(data_dir, ticker) as saver:
        graph = _build_custody_graph().compile(checkpointer=saver)
        graph.invoke(
            {
                "company_of_interest": ticker,
                "trade_date": date,
                "checkpoint_run_identity": identity.to_dict(),
                "run_id": "run-custody-test",
                "run_started_at": run_started_at,
                "final_trade_decision": final_trade_decision,
                "market_report": market_report,
            },
            config={"configurable": {"thread_id": thread_id(ticker, date, identity.identity_sha256)}},
        )


def test_incompatible_checkpoint_identity_is_preserved_for_inspection(tmp_path):
    ticker = "TEST"
    date = "2026-04-20"
    stored_identity = _checkpoint_identity()
    requested_identity = _checkpoint_identity(requested_provider="anthropic")
    config = {
        "configurable": {
            "thread_id": thread_id(
                ticker,
                date,
                stored_identity.identity_sha256,
            )
        }
    }
    with get_checkpointer(tmp_path, ticker) as saver:
        graph = _build_identity_graph().compile(checkpointer=saver)
        graph.invoke(
            {
                "company_of_interest": ticker.lower(),
                "trade_date": date,
                "checkpoint_run_identity": stored_identity.to_dict(),
            },
            config=config,
        )

    mismatch = find_incompatible_checkpoint(
        tmp_path,
        ticker,
        date,
        requested_identity,
    )

    assert mismatch == "requested_provider"
    assert has_checkpoint(
        tmp_path,
        ticker,
        date,
        stored_identity.identity_sha256,
    )


class TestCheckpointResume(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ticker = "TEST"
        self.date = "2026-04-20"
        self.signature = "a" * 64

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
        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature))
        step = checkpoint_step(self.tmpdir, self.ticker, self.date, self.signature)
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

        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature))

        # Clear it
        clear_checkpoint(self.tmpdir, self.ticker, self.date, self.signature)
        self.assertFalse(has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature))

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

        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature))

        # date2 should have no checkpoint
        self.assertFalse(has_checkpoint(self.tmpdir, self.ticker, date2, self.signature))

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
        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date, self.signature))


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
        "tool_free_analysts": tuple(sorted(set(graph.config["tool_free_analysts"]))),
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
    baseline = _bare_signature_graph(config_overrides={"tool_free_analysts": ["news", "market", "news"]})._run_signature("stock")
    reordered_set = _bare_signature_graph(config_overrides={"tool_free_analysts": ["market", "news"]})._run_signature("stock")
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
    assert captured["setup_kwargs"]["ledger_root"] == (tmp_path / "results" / "control_plane" / "decisions")
    assert captured["setup_kwargs"]["evidence_root"] == tmp_path / "results"
    assert captured["propagator_kwargs"]["run_signature_factory"].__self__ is graph
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
    graph = _bare_signature_graph(config_overrides={"checkpoint_source_revision": bad_revision})
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
    signature_a = "a" * 64
    signature_b = "b" * 64
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

    assert (
        thread_id(
            ticker,
            date,
            allow_legacy_empty_signature=True,
        )
        == legacy
    )
    assert (
        thread_id(
            ticker,
            date,
            "",
            allow_legacy_empty_signature=True,
        )
        == legacy
    )

    with pytest.raises(ValueError, match="identity digest"):
        thread_id(ticker, date)
    for operation in (has_checkpoint, checkpoint_step, clear_checkpoint):
        with pytest.raises(ValueError, match="identity digest"):
            operation(tmp_path, ticker, date)
    assert not (Path(tmp_path) / "checkpoints").exists()

    assert not has_checkpoint(
        tmp_path,
        ticker,
        date,
        allow_legacy_empty_signature=True,
    )


@pytest.mark.parametrize("bad_identity_digest", ("", " ", "not-a-digest", 3, False))
def test_malformed_checkpoint_identity_digests_fail_closed(bad_identity_digest):
    with pytest.raises((TypeError, ValueError), match="identity digest"):
        thread_id("TEST", "2026-04-20", bad_identity_digest)


def test_checkpoint_files_are_private_regular_files_under_the_checkpoint_root(tmp_path):
    identity = _checkpoint_identity()
    _write_custody_checkpoint(tmp_path, identity)

    checkpoint_root = tmp_path / "checkpoints"
    database = checkpoint_root / "TEST.db"
    root_stat = checkpoint_root.stat()
    db_stat = database.stat()

    assert stat.S_ISDIR(root_stat.st_mode)
    assert stat.S_ISREG(db_stat.st_mode)
    assert not database.is_symlink()
    assert database.resolve().is_relative_to(checkpoint_root.resolve())
    assert root_stat.st_mode & 0o077 == 0
    assert db_stat.st_mode & 0o077 == 0
    assert db_stat.st_uid == os.geteuid()


def test_checkpoint_custody_rejects_checkpoint_root_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "checkpoints").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CheckpointCustodyError, match="symlink"), get_checkpointer(tmp_path, "TEST"):
        pass

    assert not (outside / "TEST.db").exists()


def test_checkpoint_custody_rejects_nonregular_database_paths(tmp_path):
    checkpoint_root = tmp_path / "checkpoints"
    checkpoint_root.mkdir()
    (checkpoint_root / "TEST.db").mkdir()

    with pytest.raises(CheckpointCustodyError, match="regular"), get_checkpointer(tmp_path, "TEST"):
        pass


def test_checkpoint_custody_rejects_rollback_journal_symlinks(tmp_path):
    identity = _checkpoint_identity()
    _write_custody_checkpoint(tmp_path, identity)
    journal = tmp_path / "checkpoints" / "TEST.db-journal"
    journal.symlink_to(tmp_path / "outside-journal")

    with pytest.raises(CheckpointCustodyError, match="symlink"), get_checkpointer(
        tmp_path, "TEST"
    ):
        pass


def test_confirmed_broad_maintenance_removes_private_rollback_journals(tmp_path):
    identity = _checkpoint_identity()
    _write_custody_checkpoint(tmp_path, identity)
    journal = tmp_path / "checkpoints" / "TEST.db-journal"
    journal.write_bytes(b"sqlite rollback journal residue")
    journal.chmod(0o600)

    assert clear_all_checkpoints(tmp_path, confirm=True) == 1
    assert not journal.exists()


def test_checkpoint_status_is_exact_identity_bound_and_redacts_graph_state(tmp_path):
    identity = _checkpoint_identity()
    _write_custody_checkpoint(
        tmp_path,
        identity,
        market_report="Authorization: Bearer very-secret-checkpoint-report",
    )

    status = checkpoint_status(
        tmp_path,
        "TEST",
        "2026-04-20",
        identity.identity_sha256,
    )

    assert status.ticker == "TEST"
    assert status.trade_date == "2026-04-20"
    assert status.identity_digest == identity.identity_sha256
    assert status.compatibility == "compatible"
    assert status.source_revision == "a" * 40
    assert status.latest_step is not None
    assert status.recorded_at is not None
    assert "very-secret" not in json.dumps(status.to_dict())


def test_exact_clear_does_not_remove_a_different_identity_checkpoint(tmp_path):
    identity_a = _checkpoint_identity()
    identity_b = _checkpoint_identity(requested_provider="anthropic")
    _write_custody_checkpoint(tmp_path, identity_a)

    clear_checkpoint(tmp_path, "TEST", "2026-04-20", identity_b.identity_sha256)

    assert has_checkpoint(
        tmp_path,
        "TEST",
        "2026-04-20",
        identity_a.identity_sha256,
    )


def test_retention_report_only_reports_stale_completed_orphaned_checkpoints(tmp_path):
    identity = _checkpoint_identity()
    _write_custody_checkpoint(
        tmp_path,
        identity,
        run_started_at="2020-01-01T00:00:00+00:00",
    )

    report = checkpoint_retention_report(
        tmp_path,
        max_age_days=1,
        now="2026-04-20T00:00:00+00:00",
    )

    assert [candidate.category for candidate in report.candidates] == ["stale_completed"]
    assert report.candidates[0].identity_digest == identity.identity_sha256
    assert report.candidates[0].requires_exact_clear is True
    assert report.deleted_count == 0


def test_trading_graph_uses_one_signature_for_lookup_resume_and_clear(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    identity = _checkpoint_identity(results_dir=tmp_path / "results")
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
        "checkpoint_run_identity": identity,
        "results_dir": str(tmp_path / "results"),
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
    monkeypatch.setattr(
        trading_graph_module,
        "get_checkpointer",
        lambda *_args: _CheckpointerContext(),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "find_incompatible_checkpoint",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        trading_graph_module,
        "checkpoint_step",
        lambda _data, _ticker, _date, identity_digest: observed.append(("lookup", identity_digest)) or None,
    )
    monkeypatch.setattr(
        trading_graph_module,
        "thread_id",
        lambda _ticker, _date, identity_digest: observed.append(("resume", identity_digest)) or "thread",
    )
    monkeypatch.setattr(
        trading_graph_module,
        "clear_checkpoint",
        lambda _data, _ticker, _date, identity_digest: observed.append(("clear", identity_digest)),
    )

    result, signal = graph.propagate("TEST", "2026-04-20", asset_type="stock")

    assert result["final_trade_decision"] == "HOLD"
    assert signal == "HOLD"
    assert result["checkpoint_receipt"] == {
        "mode": "fresh",
        "identity_digest": identity.identity_sha256,
        "checkpoint_step": None,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    assert observed == [
        ("lookup", identity.identity_sha256),
        ("resume", identity.identity_sha256),
        ("clear", identity.identity_sha256),
    ]


def test_checkpoint_graph_constructor_rejects_missing_identity_before_setup(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    configured = []
    clients = []
    config = dict(DEFAULT_CONFIG)
    config.update(
        {
            "checkpoint_enabled": True,
            "data_cache_dir": str(tmp_path / "cache"),
            "results_dir": str(tmp_path / "results"),
        }
    )
    monkeypatch.setattr(
        trading_graph_module,
        "set_config",
        lambda *_args: configured.append(True),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "create_llm_client",
        lambda **_kwargs: clients.append(True),
    )

    with pytest.raises(ValueError, match="complete canonical identity"):
        TradingAgentsGraph(["market", "news"], config=config)

    assert configured == []
    assert clients == []
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "results").exists()


def test_checkpoint_graph_constructor_rejects_config_mismatch_before_setup(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    identity = _checkpoint_identity()
    expected = _checkpoint_identity(requested_provider="anthropic")
    configured = []
    clients = []
    config = dict(DEFAULT_CONFIG)
    config.update(
        {
            "checkpoint_enabled": True,
            "checkpoint_run_identity": identity,
            "llm_provider": "anthropic",
            "data_cache_dir": str(tmp_path / "cache"),
            "results_dir": str(tmp_path / "results"),
        }
    )
    monkeypatch.setattr(
        trading_graph_module,
        "build_analysis_checkpoint_identity",
        lambda **_kwargs: expected,
    )
    monkeypatch.setattr(
        trading_graph_module,
        "set_config",
        lambda *_args: configured.append(True),
    )
    monkeypatch.setattr(
        trading_graph_module,
        "create_llm_client",
        lambda **_kwargs: clients.append(True),
    )

    with pytest.raises(ValueError, match="requested_provider"):
        TradingAgentsGraph(["market", "news"], config=config)

    assert configured == []
    assert clients == []
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "results").exists()


def test_checkpoint_propagate_rejects_an_asset_type_mismatch_before_side_effects(
    tmp_path,
):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "checkpoint_run_identity": _checkpoint_identity(asset_type="stock"),
    }
    graph._resolve_pending_entries = lambda _ticker: (_ for _ in ()).throw(
        AssertionError("identity mismatch must precede pending-entry resolution")
    )

    with pytest.raises(ValueError, match="asset_type"):
        graph.propagate("TEST", "2026-04-20", asset_type="crypto")


def test_run_graph_resumes_saved_state_with_none_and_preserves_all_fields(
    monkeypatch,
    tmp_path,
):
    from datetime import datetime

    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.packet_nodes import build_graph_run_id, create_research_evidence_packet_node
    from tradingagents.graph.propagation import Propagator
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    identity = _checkpoint_identity(results_dir=tmp_path / "results")
    run_id = build_graph_run_id("TEST", "2026-04-20", "stock", identity.identity_sha256)
    saved = {
        **Propagator().create_initial_state("TEST", "2026-04-20", run_id=run_id, learning_context="saved bounded context"),
        "messages": [HumanMessage(content="TEST")],
        "run_id": run_id,
        "run_started_at": "2026-04-20T13:30:00+00:00",
        "decision_packet_refs": [],
        "learning_context": "saved bounded context",
        "company_of_interest": "TEST",
        "trade_date": "2026-04-20",
        "asset_type": "stock",
        "checkpoint_run_identity": identity.to_dict(),
        "market_report": "saved market report",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "final_trade_decision": "HOLD",
    }
    saved["investment_debate_state"]["judge_decision"] = "saved debate"
    root = tmp_path / "results"
    saved.update(create_research_evidence_packet_node(
        root / "control_plane/decisions", root,
        clock=lambda: datetime.fromisoformat(saved["run_started_at"]),
    )(saved))
    packet_ref = saved["decision_packet_refs"][0]
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
        "results_dir": str(tmp_path / "results"),
    }
    graph.graph = _RuntimeGraph()
    graph.propagator = _Propagator()
    graph.debug = False
    graph.memory_log = type(
        "_Memory",
        (),
        {
            "get_past_context": staticmethod(lambda _ticker: (_ for _ in ()).throw(AssertionError("resume must preserve saved context"))),
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
        checkpoint_identity=identity,
    )

    assert invocations[0][0] == "get_state"
    assert invocations[1][0:2] == ("invoke", None)
    assert result == saved
    assert result["decision_packet_refs"] == [packet_ref]
    assert result["learning_context"] == "saved bounded context"
    assert result["market_report"] == "saved market report"
    assert result["investment_debate_state"]["judge_decision"] == "saved debate"
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

    identity = _checkpoint_identity()
    run_id = build_graph_run_id("TEST", "2026-04-20", "stock", identity.identity_sha256)
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
        "checkpoint_run_identity": identity.to_dict(),
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
            "create_initial_state": staticmethod(lambda *_args, **_kwargs: invoked.append("fresh")),
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
            checkpoint_identity=identity,
        )

    assert invoked == []


def _propagate_saved_state_fixture(monkeypatch, tmp_path, *, corruption=None, fresh=False, with_packet=False):
    from tradingagents.graph import trading_graph as module
    from tradingagents.graph.packet_nodes import build_graph_run_id
    from tradingagents.graph.propagation import Propagator

    identity = _checkpoint_identity(results_dir=tmp_path / "results")
    saved = Propagator().create_initial_state(
        "TEST", "2026-04-20", run_id=build_graph_run_id(
            "TEST", "2026-04-20", "stock", identity.identity_sha256,
        ), run_started_at="2026-04-20T13:30:00+00:00", learning_context="saved context",
    )
    saved["checkpoint_run_identity"] = identity.to_dict()
    saved["messages"] = [HumanMessage(content="TEST")]
    saved["final_trade_decision"] = "HOLD"
    if with_packet:
        from tradingagents.graph.packet_nodes import create_research_evidence_packet_node

        root = tmp_path / "results"
        saved.update(create_research_evidence_packet_node(
            root / "control_plane/decisions", root,
            clock=lambda: module.datetime.fromisoformat(saved["run_started_at"]),
        )(saved))
    corruptions = {
        "checkpoint_run_identity": {},
        "run_id": "wrong-run",
        "run_started_at": "2026-04-20T13:30:00Z",
        "decision_packet_refs": ["not-a-reference"],
        "learning_context": 3,
        "company_of_interest": "OTHER",
        "trade_date": "2026-04-21",
        "asset_type": "crypto",
    }
    if corruption in corruptions:
        saved[corruption] = corruptions[corruption]
    elif fresh or corruption == "empty_state":
        saved = {}
    elif corruption == "missing_state":
        saved = None
    elif corruption == "nonmapping_state":
        saved = []
    events = []
    closed = []

    class Runtime:
        def get_state(self, _config):
            events.append("inspect")
            return SimpleNamespace(values=saved)

        def invoke(self, state, **_kwargs):
            events.append("invoke-resume" if state is None else "invoke-fresh")
            return {**((saved or {}) if state is None else state), "final_trade_decision": "HOLD"}

    @contextmanager
    def checkpointer(*_args):
        try:
            yield object()
        finally:
            closed.append(True)

    def initial_state(*args, **kwargs):
        events.append("fresh")
        return Propagator().create_initial_state(*args, **kwargs)

    runtime = Runtime()
    graph = object.__new__(module.TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": True, "data_cache_dir": str(tmp_path),
                    "checkpoint_run_identity": identity, "results_dir": str(tmp_path / "results")}
    graph.workflow = SimpleNamespace(compile=lambda **_kwargs: runtime)
    graph.graph = runtime
    graph._checkpointer_ctx = None
    graph.debug = False
    graph.propagator = SimpleNamespace(get_graph_args=lambda: {}, create_initial_state=initial_state)
    graph._resolve_pending_entries = lambda _ticker: events.append("resolve")
    graph._log_state = lambda *_args: events.append("log")
    graph.memory_log = SimpleNamespace(store_decision=lambda **_kwargs: events.append("store"))
    graph.process_signal = lambda value: value
    monkeypatch.setattr(module, "get_checkpointer", checkpointer)
    monkeypatch.setattr(module, "find_incompatible_checkpoint", lambda *_args: None)
    monkeypatch.setattr(module, "checkpoint_step", lambda *_args: None if fresh else 2)
    monkeypatch.setattr(module, "clear_checkpoint", lambda *_args: events.append("clear"))
    return graph, saved, events, closed


@pytest.mark.parametrize("corruption", [
    "checkpoint_run_identity", "run_id", "run_started_at", "decision_packet_refs",
    "learning_context", "company_of_interest", "trade_date", "asset_type",
    "empty_state", "missing_state", "nonmapping_state",
])
def test_propagate_rejects_saved_state_before_pending_resolution(
    monkeypatch, tmp_path, corruption,
):
    graph, saved, events, closed = _propagate_saved_state_fixture(
        monkeypatch, tmp_path, corruption=corruption,
    )
    before = deepcopy(saved)
    with pytest.raises(ValueError, match="checkpoint"):
        graph.propagate("TEST", "2026-04-20")
    assert events == ["inspect"]
    assert saved == before
    assert closed == [True]


@pytest.mark.parametrize("fresh", [False, True], ids=["resume", "fresh"])
def test_propagate_resolves_pending_once_only_for_a_fresh_checkpoint_run(
    monkeypatch, tmp_path, fresh,
):
    graph, saved, events, closed = _propagate_saved_state_fixture(
        monkeypatch, tmp_path, fresh=fresh,
    )
    before = deepcopy(saved)
    result, signal = graph.propagate("TEST", "2026-04-20")
    expected = ["inspect"] + (["resolve", "fresh", "invoke-fresh"] if fresh else ["invoke-resume"])
    assert events == [*expected, "log", "store", "clear"]
    assert result["checkpoint_receipt"]["mode"] == ("fresh" if fresh else "resumed")
    assert signal == "HOLD" and saved == before and closed == [True]


@pytest.mark.parametrize("field", ["learning_evidence_predecessor", "decision_ledger_predecessor"])
@pytest.mark.parametrize("fresh", [False, True], ids=["resume", "fresh"])
def test_propagate_rejects_unproven_predecessor_before_any_run_effect(monkeypatch, tmp_path, field, fresh):
    from tradingagents.graph.packet_nodes import build_graph_run_id

    graph, saved, events, closed = _propagate_saved_state_fixture(monkeypatch, tmp_path, fresh=fresh)
    identity = _checkpoint_identity(results_dir=tmp_path / "results", **{field: "f" * 64})
    graph.config["checkpoint_run_identity"] = identity
    if not fresh:
        saved["checkpoint_run_identity"] = identity.to_dict()
        saved["run_id"] = build_graph_run_id("TEST", "2026-04-20", "stock", identity.identity_sha256)
    before = deepcopy(saved)
    with pytest.raises(ValueError, match=field):
        graph.propagate("TEST", "2026-04-20")
    assert events == ["inspect"] and closed == [True] and saved == before
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("corruption", ["packet_sha256", "evidence_sha256", "evidence_bytes"])
def test_propagate_authenticates_saved_packet_references_before_resume(monkeypatch, tmp_path, corruption):
    graph, saved, events, closed = _propagate_saved_state_fixture(monkeypatch, tmp_path, with_packet=True)
    reference = saved["decision_packet_refs"][0]
    if corruption == "evidence_bytes":
        packet = json.loads((tmp_path / "results/control_plane/decisions" / reference["packet_path"]).read_bytes())
        (tmp_path / "results" / packet["evidence_refs"][0]["path"]).write_bytes(b"changed evidence")
    else:
        reference[corruption] = "0" * 64
    before = deepcopy(saved)
    files_before = {path: path.read_bytes() for path in (tmp_path / "results").rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="checkpoint"):
        graph.propagate("TEST", "2026-04-20")
    assert events == ["inspect"] and closed == [True] and saved == before
    assert {path: path.read_bytes() for path in (tmp_path / "results").rglob("*") if path.is_file()} == files_before


def test_propagate_resumes_with_authenticated_own_packet_without_rewriting_evidence(monkeypatch, tmp_path):
    graph, saved, events, closed = _propagate_saved_state_fixture(monkeypatch, tmp_path, with_packet=True)
    before = deepcopy(saved)
    files_before = {path: path.read_bytes() for path in (tmp_path / "results").rglob("*") if path.is_file()}
    state, _ = graph.propagate("TEST", "2026-04-20")
    assert events == ["inspect", "invoke-resume", "log", "store", "clear"]
    assert closed == [True] and saved == before and state["decision_packet_refs"] == saved["decision_packet_refs"]
    assert {path: path.read_bytes() for path in (tmp_path / "results").rglob("*") if path.is_file()} == files_before


_CANONICAL_STATE_FIELDS = [
    "market_report", "sentiment_report", "news_report", "fundamentals_report",
    "investment_plan", "trader_investment_plan", "final_trade_decision", "past_context",
    "messages", "sender", "investment_debate_state", "risk_debate_state",
    *[f"investment_debate_state.{key}" for key in (
        "bull_history", "bear_history", "history", "current_response", "judge_decision", "count",
    )],
    *[f"risk_debate_state.{key}" for key in (
        "aggressive_history", "conservative_history", "neutral_history", "history", "latest_speaker",
        "current_aggressive_response", "current_conservative_response", "current_neutral_response", "judge_decision", "count",
    )],
]


@pytest.mark.parametrize("field", _CANONICAL_STATE_FIELDS)
def test_propagate_rejects_malformed_canonical_saved_fields_before_effects(monkeypatch, tmp_path, field):
    graph, saved, events, closed = _propagate_saved_state_fixture(monkeypatch, tmp_path)
    parent, separator, key = field.partition(".")
    if separator:
        saved[parent][key] = True if key == "count" else []
    else:
        saved[parent] = ["not-a-message"] if field == "messages" else None
    before = deepcopy(saved)
    with pytest.raises(ValueError, match="checkpoint"):
        graph.propagate("TEST", "2026-04-20")
    assert events == ["inspect"] and closed == [True] and saved == before


def test_propagate_accepts_real_mid_debate_shape_without_judge_fields(monkeypatch, tmp_path):
    graph, saved, events, _ = _propagate_saved_state_fixture(monkeypatch, tmp_path)
    saved["investment_debate_state"].pop("judge_decision")
    saved["risk_debate_state"].pop("judge_decision")
    graph.propagate("TEST", "2026-04-20")
    assert events == ["inspect", "invoke-resume", "log", "store", "clear"]


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
    graph._run_signature = lambda asset: order.append(("signature", asset)) or "frozen-signature"
    graph._resolve_pending_entries = lambda ticker: order.append(("resolve", ticker))
    graph._run_graph = lambda *_args, **kwargs: order.append(("run", kwargs["run_signature"])) or ("state", "signal")

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


def test_checkpoint_enabled_graph_requires_identity_before_side_effects(tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
    }
    graph._run_signature = lambda _asset: "a" * 64
    side_effects = []
    graph._resolve_pending_entries = lambda _ticker: side_effects.append("resolved")

    with pytest.raises(ValueError, match="checkpoint_run_identity"):
        graph.propagate("TEST", "2026-04-20")

    assert side_effects == []
    assert not (tmp_path / "checkpoints").exists()


def test_incompatible_checkpoint_rejects_before_pending_resolution(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
        "checkpoint_run_identity": _checkpoint_identity(),
    }
    resolved = []
    graph._resolve_pending_entries = lambda _ticker: resolved.append(True)
    monkeypatch.setattr(
        trading_graph_module,
        "find_incompatible_checkpoint",
        lambda *_args: "requested_provider",
    )

    with pytest.raises(ValueError, match="requested_provider"):
        graph.propagate("TEST", "2026-04-20")

    assert resolved == []


def test_mutated_identity_object_rejects_before_pending_resolution(tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    identity = _checkpoint_identity()
    object.__setattr__(identity, "requested_provider", "anthropic")
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
        "checkpoint_run_identity": identity,
    }
    resolved = []
    graph._resolve_pending_entries = lambda _ticker: resolved.append(True)

    with pytest.raises(ValueError, match="checkpoint_run_identity"):
        graph.propagate("TEST", "2026-04-20")

    assert resolved == []


def test_run_graph_rejects_persisted_identity_mismatch_before_invocation(
    monkeypatch,
    tmp_path,
):
    from tradingagents.graph import trading_graph as trading_graph_module
    from tradingagents.graph.packet_nodes import build_graph_run_id
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    expected_identity = _checkpoint_identity()
    stored_identity = _checkpoint_identity(requested_provider="anthropic")
    run_id = build_graph_run_id(
        "TEST",
        "2026-04-20",
        "stock",
        expected_identity.identity_sha256,
    )
    saved = {
        "run_id": run_id,
        "run_started_at": "2026-04-20T13:30:00+00:00",
        "decision_packet_refs": [],
        "learning_context": "saved context",
        "checkpoint_run_identity": stored_identity.to_dict(),
    }
    invoked = []

    class _RuntimeGraph:
        def get_state(self, _config):
            return type("_Snapshot", (), {"values": saved})()

        def invoke(self, _state, **_kwargs):
            invoked.append(True)
            return saved

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": True, "data_cache_dir": str(tmp_path)}
    graph.graph = _RuntimeGraph()
    graph.propagator = type(
        "_Propagator",
        (),
        {
            "get_graph_args": staticmethod(lambda: {}),
            "create_initial_state": staticmethod(lambda *_args, **_kwargs: invoked.append("fresh")),
        },
    )()
    graph.debug = False
    graph.memory_log = type("_Memory", (), {})()
    monkeypatch.setattr(trading_graph_module, "thread_id", lambda *_args: "thread")

    with pytest.raises(ValueError, match="requested_provider"):
        graph._run_graph(
            "TEST",
            "2026-04-20",
            checkpoint_identity=expected_identity,
        )

    assert invoked == []


@pytest.mark.parametrize(
    ("changes", "field"),
    (
        ({"clean_source_revision": "0" * 40}, "clean_source_revision"),
        ({"uv_lock_sha256": "0" * 64}, "uv_lock_sha256"),
        ({"selected_analysts": ("news", "market")}, "selected_analysts"),
        ({"asset_type": "crypto"}, "asset_type"),
        ({"max_debate_rounds": 2}, "max_debate_rounds"),
        ({"max_risk_discuss_rounds": 2}, "max_risk_discuss_rounds"),
        ({"max_analyst_tool_rounds": 9}, "max_analyst_tool_rounds"),
        ({"max_recur_limit": 101}, "max_recur_limit"),
        ({"analyst_concurrency_limit": 2}, "analyst_concurrency_limit"),
        ({"tool_free_analysts": ("market",)}, "tool_free_analysts"),
        ({"requested_provider": "anthropic"}, "requested_provider"),
        ({"requested_quick_model": "anthropic/claude-haiku-4-5"}, "requested_quick_model"),
        ({"requested_deep_model": "anthropic/claude-opus-4-5"}, "requested_deep_model"),
        ({"backend_route_identity": "https://router.example/v2?region=us"}, "backend_route_identity"),
        ({"output_language": "Spanish"}, "output_language"),
        ({"provider_reasoning_settings": {"thinking": {"effort": "low"}}}, "provider_reasoning_settings"),
        ({"graph_topology_sha256": "0" * 64}, "graph_topology_sha256"),
        ({"agent_prompt_surface_sha256": "0" * 64}, "agent_prompt_surface_sha256"),
        ({"bound_tool_surface_sha256": "0" * 64}, "bound_tool_surface_sha256"),
        ({"data_route_surface_sha256": "0" * 64}, "data_route_surface_sha256"),
        ({"packet_handoff_schema_version": 2}, "packet_handoff_schema_version"),
        ({"learning_context_policy_identity": "learning-context-policy-v3"}, "learning_context_policy_identity"),
        ({"trade_date_cutoff_policy_identity": "market-date-cutoff-v2"}, "trade_date_cutoff_policy_identity"),
        ({"learning_evidence_predecessor": "0" * 64}, "learning_evidence_predecessor"),
        ({"decision_ledger_predecessor": "0" * 64}, "decision_ledger_predecessor"),
    ),
)
def test_every_complete_identity_change_rejects_saved_state_before_resume(
    changes,
    field,
):
    from tradingagents.graph.trading_graph import _validate_checkpoint_identity_state

    expected = _checkpoint_identity()
    saved = {"checkpoint_run_identity": _checkpoint_identity(**changes).to_dict()}

    with pytest.raises(ValueError, match=field):
        _validate_checkpoint_identity_state(saved, expected=expected)


def test_invalid_checkpoint_identity_fails_before_run_side_effects(tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": True,
        "data_cache_dir": str(tmp_path),
        "checkpoint_run_identity": {},
    }
    side_effects = []
    graph._resolve_pending_entries = lambda _ticker: side_effects.append("resolved")

    with pytest.raises(
        ValueError,
        match="checkpoint_run_identity",
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
