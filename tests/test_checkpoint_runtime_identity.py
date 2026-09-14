"""Runtime-adapter tests for analysis-only checkpoint identities."""

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import checkpoint_runtime_identity as runtime_identity
from tradingagents.graph.checkpointer import get_checkpointer, thread_id
from tradingagents.graph.packet_nodes import build_graph_run_id
from tradingagents.orchestration.decision_ledger import DecisionLedger
from tradingagents.orchestration.work_packets import EvidenceRef, WorkPacket


def _config() -> dict:
    config = dict(DEFAULT_CONFIG)
    config.update(
        {
            "llm_provider": "openrouter",
            "quick_think_llm": "openai/gpt-5-mini",
            "deep_think_llm": "anthropic/claude-sonnet-4-5",
            "backend_url": "https://router.example/v1?region=us",
            "results_dir": "/tmp/checkpoint-runtime-results",
            "data_vendors": {"core_stock_apis": "yfinance"},
            "tool_vendors": {},
        }
    )
    return config


def test_runtime_adapter_builds_a_complete_identity_from_resolved_inputs(
    monkeypatch,
):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        runtime_identity,
        "_clean_source_revision",
        lambda _root: "a" * 40,
    )

    identity = runtime_identity.build_analysis_checkpoint_identity(
        config=_config(),
        selected_analysts=("market", "news"),
        asset_type="stock",
        project_root=root,
    )

    assert identity.clean_source_revision == "a" * 40
    assert identity.source_tree_dirty is False
    assert identity.requested_provider == "openrouter"
    assert identity.selected_analysts == ("market", "news")
    assert identity.identity_sha256


def test_runtime_adapter_fails_closed_when_source_is_not_clean(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        runtime_identity,
        "_clean_source_revision",
        lambda _root: (_ for _ in ()).throw(
            runtime_identity.CheckpointRuntimeIdentityError("source tree is dirty")
        ),
    )

    with pytest.raises(runtime_identity.CheckpointRuntimeIdentityError, match="dirty"):
        runtime_identity.build_analysis_checkpoint_identity(
            config=_config(),
            selected_analysts=("market",),
            asset_type="stock",
            project_root=root,
        )


def test_runtime_adapter_rejects_an_unresolved_backend_route(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        runtime_identity,
        "_clean_source_revision",
        lambda _root: "a" * 40,
    )
    config = _config()
    config["backend_url"] = None

    with pytest.raises(runtime_identity.CheckpointRuntimeIdentityError, match="backend_url"):
        runtime_identity.build_analysis_checkpoint_identity(
            config=config,
            selected_analysts=("market",),
            asset_type="stock",
            project_root=root,
        )


def test_clean_source_identity_ignores_git_location_overrides(monkeypatch, tmp_path):
    observed_environments = []
    monkeypatch.setenv("GIT_DIR", "/untrusted/git-dir")
    monkeypatch.setenv("GIT_WORK_TREE", "/untrusted/worktree")
    monkeypatch.setenv("GIT_INDEX_FILE", "/untrusted/index")

    def fake_run(command, **kwargs):
        observed_environments.append(kwargs["env"])
        if command[-1] == "--show-toplevel":
            return SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n")
        if command[-1] == "HEAD":
            return SimpleNamespace(returncode=0, stdout=f"{'a' * 40}\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(runtime_identity.subprocess, "run", fake_run)

    assert runtime_identity._clean_source_revision(tmp_path) == "a" * 40
    for environment in observed_environments:
        assert "GIT_DIR" not in environment
        assert "GIT_WORK_TREE" not in environment
        assert "GIT_INDEX_FILE" not in environment


def test_clean_source_identity_rejects_a_git_root_mismatch(monkeypatch, tmp_path):
    other_root = tmp_path / "other"
    other_root.mkdir()

    def fake_run(command, **_kwargs):
        if command[-1] == "--show-toplevel":
            return SimpleNamespace(returncode=0, stdout=f"{other_root}\n")
        return SimpleNamespace(returncode=0, stdout=f"{'a' * 40}\n")

    monkeypatch.setattr(runtime_identity.subprocess, "run", fake_run)

    with pytest.raises(runtime_identity.CheckpointRuntimeIdentityError, match="project root"):
        runtime_identity._clean_source_revision(tmp_path)


def _local_identity(monkeypatch, tmp_path):
    config = _config()
    config.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr(runtime_identity, "_clean_source_revision", lambda _root: "a" * 40)
    identity = runtime_identity.build_analysis_checkpoint_identity(
        config=config, selected_analysts=("market",), asset_type="stock",
    )
    return config, identity


def _record_decision(config, run_id):
    root = Path(config["results_dir"])
    root.mkdir(exist_ok=True)
    source = root / f"{run_id}.json"
    source.write_bytes(b'{"analysis_only":true}')
    now = dt.datetime(2026, 4, 20, 13, 30, tzinfo=dt.timezone.utc)
    packet = WorkPacket.create(
        kind="research_synthesis", producer_role="research_manager", run_id=run_id,
        subject="TEST", evidence_refs=[EvidenceRef.from_path(source)], parent_packet_ids=[],
        claims=["Retained test evidence"], assumptions=[], recommendation="hold_cash", confidence=0.5,
        allowed_effects=["recommend_hold_cash"], forbidden_effects=[],
        expires_at=now + dt.timedelta(hours=2), now=now,
    )
    ledger = DecisionLedger(root / "control_plane/decisions")
    return ledger, ledger.record(packet, now=now)


class _ResumeState(TypedDict):
    company_of_interest: str
    trade_date: str
    checkpoint_run_identity: dict


def _save_identity(config, identity):
    builder = StateGraph(_ResumeState)
    builder.add_node("done", lambda _state: {})
    builder.set_entry_point("done")
    builder.add_edge("done", END)
    with get_checkpointer(config["data_cache_dir"], "TEST") as saver:
        builder.compile(checkpointer=saver).invoke(
            {"company_of_interest": "TEST", "trade_date": "2026-04-20", "checkpoint_run_identity": identity.to_dict()},
            config={"configurable": {"thread_id": thread_id("TEST", "2026-04-20", identity.identity_sha256)}},
        )


def test_runtime_predecessor_capture_is_separate_destination_bound_and_nonmutating(tmp_path):
    config = {"results_dir": str(tmp_path / "results")}
    heads = runtime_identity.capture_checkpoint_predecessors(config)
    assert set(heads) == {"learning_evidence_predecessor", "decision_ledger_predecessor"}
    assert all(len(value) == 64 for value in heads.values())
    assert len(set(heads.values())) == 2
    assert not (tmp_path / "results").exists()
    other = runtime_identity.capture_checkpoint_predecessors({"results_dir": str(tmp_path / "other")})
    assert all(heads[key] != other[key] for key in heads)


def test_runtime_resume_keeps_the_pre_run_identity_after_own_authenticated_event(monkeypatch, tmp_path):
    config, identity = _local_identity(monkeypatch, tmp_path)
    _save_identity(config, identity)
    run_id = build_graph_run_id("TEST", "2026-04-20", "stock", identity.identity_sha256)
    ledger, _ = _record_decision(config, run_id)
    before = {path: path.read_bytes() for path in ledger.root.rglob("*") if path.is_file()}
    resumed = runtime_identity.build_analysis_checkpoint_identity(
        config=config, selected_analysts=("market",), asset_type="stock", ticker="TEST", trade_date="2026-04-20",
    )
    assert resumed == identity
    assert {path: path.read_bytes() for path in ledger.root.rglob("*") if path.is_file()} == before
    runtime_identity.validate_checkpoint_predecessors(config, identity, run_id=run_id, resuming=True)
    with pytest.raises(runtime_identity.CheckpointRuntimeIdentityError, match="decision_ledger_predecessor"):
        runtime_identity.validate_checkpoint_predecessors(config, identity, run_id=run_id, resuming=False)


@pytest.mark.parametrize("corruption", ["foreign", "rollback", "collision", "missing_packet", "learning_advance"])
def test_runtime_resume_rejects_foreign_or_unproven_history(monkeypatch, tmp_path, corruption):
    config, identity = _local_identity(monkeypatch, tmp_path)
    if corruption == "rollback":
        ledger, _ = _record_decision(config, "prior-run")
        identity = runtime_identity.build_analysis_checkpoint_identity(
            config=config, selected_analysts=("market",), asset_type="stock",
        )
        (ledger.root / "events.jsonl").write_bytes(b"")
    elif corruption == "learning_advance":
        events = Path(config["results_dir"]) / "learning_availability/events.jsonl"
        events.parent.mkdir(parents=True)
        events.write_bytes(b'{"changed":true}\n')
    else:
        run_id = build_graph_run_id("TEST", "2026-04-20", "stock", identity.identity_sha256)
        _, packet_path = _record_decision(config, "foreign-run" if corruption == "foreign" else run_id)
        if corruption == "collision":
            packet_path.write_bytes(b"{}")
        elif corruption == "missing_packet":
            packet_path.unlink()
    _save_identity(config, identity)
    before = {path: path.read_bytes() for path in Path(config["results_dir"]).rglob("*") if path.is_file()}
    with pytest.raises(runtime_identity.CheckpointRuntimeIdentityError, match="checkpoint"):
        runtime_identity.build_analysis_checkpoint_identity(
            config=config, selected_analysts=("market",), asset_type="stock", ticker="TEST", trade_date="2026-04-20",
        )
    assert {path: path.read_bytes() for path in Path(config["results_dir"]).rglob("*") if path.is_file()} == before


def test_real_sqlite_resume_retains_own_packet_and_skips_pending_resolution(monkeypatch, tmp_path):
    from tradingagents.agents.utils.agent_states import AgentState
    from tradingagents.graph.packet_nodes import create_research_evidence_packet_node
    from tradingagents.graph.propagation import Propagator
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config, identity = _local_identity(monkeypatch, tmp_path)
    config.update(checkpoint_enabled=True, checkpoint_run_identity=identity)
    root = Path(config["results_dir"])
    now = dt.datetime(2026, 4, 20, 13, 30, tzinfo=dt.timezone.utc)
    calls = []

    def crash_once(_state):
        calls.append("barrier")
        if calls.count("barrier") == 1:
            raise RuntimeError("intentional crash after the durable packet")
        return {"final_trade_decision": "HOLD"}

    workflow = StateGraph(AgentState)
    workflow.add_node("packet", create_research_evidence_packet_node(root / "control_plane/decisions", root, clock=lambda: now))
    workflow.add_node("barrier", crash_once)
    workflow.set_entry_point("packet")
    workflow.add_edge("packet", "barrier")
    workflow.add_edge("barrier", END)
    graph = object.__new__(TradingAgentsGraph)
    graph.config = config
    graph.workflow = workflow
    graph.graph = workflow.compile()
    graph._checkpointer_ctx = None
    graph.debug = False
    graph.propagator = SimpleNamespace(
        get_graph_args=lambda: Propagator().get_graph_args(),
        create_initial_state=lambda *args, **kwargs: Propagator().create_initial_state(
            *args, **kwargs, run_started_at=now.isoformat(timespec="seconds"), learning_context="",
        ),
    )
    graph._resolve_pending_entries = lambda _ticker: calls.append("resolve")
    graph._log_state = lambda *_args: calls.append("log")
    graph.memory_log = SimpleNamespace(store_decision=lambda **_kwargs: calls.append("store"))
    graph.process_signal = lambda value: value

    with pytest.raises(RuntimeError, match="intentional crash"):
        graph.propagate("TEST", "2026-04-20")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    config["checkpoint_run_identity"] = runtime_identity.build_analysis_checkpoint_identity(
        config=config, selected_analysts=("market",), asset_type="stock", ticker="TEST", trade_date="2026-04-20",
    )
    assert config["checkpoint_run_identity"] == identity

    final, signal = graph.propagate("TEST", "2026-04-20")

    assert signal == "HOLD" and final["checkpoint_receipt"]["mode"] == "resumed"
    assert calls == ["resolve", "barrier", "barrier", "log", "store"]
    assert len(final["decision_packet_refs"]) == 1
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert len(DecisionLedger(root / "control_plane/decisions").read_authenticated_events()) == 1
