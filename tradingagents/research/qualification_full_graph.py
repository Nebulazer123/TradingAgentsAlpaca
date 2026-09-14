"""Registered, retained-only execution of the actual TradingAgents role graph.

The supplemental registration binds explicit graph context to the existing
research cohort. It is not market/source admission, model-call permission, or
trading authority. Existing v4 research registrations remain immutable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from tradingagents.research.qualification_benchmark import (
    AUTHORITY,
    ResearchQualificationBenchmarkError,
    _adapter_input,
    _digest,
    _map,
    _openrouter_prompt,
    _registration,
    _source,
)

GRAPH_ANALYSTS = ("market", "social", "news", "fundamentals")
FULL_GRAPH_INSTRUCTION = (
    "Use the actual retained-only analyst, researcher, manager, trader, risk, "
    "and portfolio-manager graph. The Portfolio Manager must return the answer "
    "to the registered adapter_query in benchmark_answer as part of its normal "
    "structured decision. Answer from the graph's retained evidence reports; "
    "return UNAVAILABLE if insufficient. Never use an answer key or fetch data."
)
FULL_GRAPH_PROMPT_SHA256 = _digest({
    "contract": "full-role-graph-benchmark-v1",
    "instruction": FULL_GRAPH_INSTRUCTION,
    "analysts": GRAPH_ANALYSTS,
    "debate_rounds": 1,
    "risk_rounds": 1,
    "concurrency": 1,
    "structured_output": "required",
    "temperature": 0,
    "max_retries": 0,
})
GRAPH_MODEL_ROLES = (
    "Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst",
    "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
    "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager",
)
_GRAPH_CASE_FIELDS = {"case_id", "company_of_interest", "trade_date", "asset_type"}
_REGISTRATION_FIELDS = {
    "schema_version", "graph_registration_id", "graph_registration_sha256",
    "research_registration_sha256", "clean_source_revision", "uv_lock_sha256",
    "case_contexts", *AUTHORITY,
}


def validate_full_graph_registration(raw: object, research_registration: object) -> dict:
    research = _registration(research_registration)
    row = _map(raw, _REGISTRATION_FIELDS, "full-graph registration")
    if (
        row["schema_version"] != "research_full_graph_registration/v1"
        or row["research_registration_sha256"] != research["registration_sha256"]
        or any(type(row[key]) is not type(value) or row[key] != value for key, value in AUTHORITY.items())
        or type(row["clean_source_revision"]) is not str
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", row["clean_source_revision"]) is None
        or type(row["uv_lock_sha256"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", row["uv_lock_sha256"]) is None
    ):
        raise ResearchQualificationBenchmarkError("full-graph registration identity is invalid")
    for lane in ("tradingagents_full_graph", "tradingagents_full_graph_no_text"):
        if research["lane_specs"][lane]["prompt_sha256"] != FULL_GRAPH_PROMPT_SHA256:
            raise ResearchQualificationBenchmarkError("full-graph prompt contract is not registered")
    if research["lane_specs"]["tradingagents_full_graph"] != research["lane_specs"]["tradingagents_full_graph_no_text"]:
        raise ResearchQualificationBenchmarkError("full-graph twin settings and pricing must match")
    contexts = row["case_contexts"]
    if type(contexts) is not list:
        raise ResearchQualificationBenchmarkError("full-graph case contexts must be a list")
    case_ids = []
    for context in contexts:
        context = _map(context, _GRAPH_CASE_FIELDS, "full-graph case context")
        symbol, date = context["company_of_interest"], context["trade_date"]
        if (
            type(context["case_id"]) is not str
            or type(symbol) is not str
            or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) is None
            or type(date) is not str
            or context["asset_type"] != "stock"
        ):
            raise ResearchQualificationBenchmarkError("full-graph instrument context is invalid")
        try:
            if dt.date.fromisoformat(date).isoformat() != date:
                raise ValueError("noncanonical date")
        except ValueError as exc:
            raise ResearchQualificationBenchmarkError("full-graph market date is invalid") from exc
        case_ids.append(context["case_id"])
    if case_ids != [case["case_id"] for case in research["cases"]]:
        raise ResearchQualificationBenchmarkError("full-graph context must cover the exact sorted cohort")
    material = {**row, "graph_registration_id": None, "graph_registration_sha256": None}
    digest = _digest(material)
    if row["graph_registration_id"] != f"research-full-graph-{digest}" or row["graph_registration_sha256"] != digest:
        raise ResearchQualificationBenchmarkError("full-graph registration digest is invalid")
    return row


def build_full_graph_registration(
    *, research_registration: object, case_contexts: Sequence[Mapping[str, object]],
    clean_source_revision: str, uv_lock_sha256: str,
) -> dict:
    research = _registration(research_registration)
    row = {
        "schema_version": "research_full_graph_registration/v1",
        "graph_registration_id": None, "graph_registration_sha256": None,
        "research_registration_sha256": research["registration_sha256"],
        "clean_source_revision": clean_source_revision, "uv_lock_sha256": uv_lock_sha256,
        "case_contexts": [dict(context) for context in case_contexts], **AUTHORITY,
    }
    digest = _digest(row)
    row.update(graph_registration_id=f"research-full-graph-{digest}", graph_registration_sha256=digest)
    return validate_full_graph_registration(row, research)


def graph_case_directory(run_root: Path, case_id: str, lane_id: str) -> Path:
    if lane_id not in {"tradingagents_full_graph", "tradingagents_full_graph_no_text"}:
        raise ResearchQualificationBenchmarkError("full-graph lane is invalid")
    return run_root / _digest({"case_id": case_id, "lane_id": lane_id})


def graph_case_config(case_root: Path, spec: Mapping[str, object]) -> dict:
    return {
        "llm_provider": "openrouter", "quick_think_llm": spec["model"], "deep_think_llm": spec["model"],
        "backend_url": "https://openrouter.ai/api/v1", "output_language": "English",
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1,
        "max_analyst_tool_rounds": 0, "max_recur_limit": 100, "analyst_concurrency_limit": 1,
        "tool_free_analysts": list(GRAPH_ANALYSTS), "data_vendors": {}, "tool_vendors": {},
        "results_dir": str(case_root / "evidence"), "data_cache_dir": str(case_root / "cache"),
        "learning_context_root": str(case_root / "evidence/learning_availability"),
    }


def build_full_graph_source_identity(graph_registration: Mapping[str, object], spec: Mapping[str, object], run_root: Path):
    """Verify the current clean source once, before any client or run directory."""
    from tradingagents.graph.checkpoint_runtime_identity import CheckpointRuntimeIdentityError, build_analysis_checkpoint_identity

    _require_registered_language()
    try:
        identity = build_analysis_checkpoint_identity(
            config=graph_case_config(run_root, spec), selected_analysts=GRAPH_ANALYSTS, asset_type="stock",
        )
    except CheckpointRuntimeIdentityError as exc:
        raise ResearchQualificationBenchmarkError(f"full-graph source preflight failed: {exc}") from exc
    if identity.clean_source_revision != graph_registration["clean_source_revision"] or identity.uv_lock_sha256 != graph_registration["uv_lock_sha256"]:
        raise ResearchQualificationBenchmarkError("full-graph source revision or lock differs from registration")
    return identity


def _require_registered_language() -> None:
    from tradingagents.dataflows.config import get_config

    language = get_config().get("output_language", "English")
    if type(language) is not str or language.strip().lower() != "english":
        raise ResearchQualificationBenchmarkError("full-graph ambient output language differs from its registered English contract")


def bind_full_graph_case_identity(
    *, source_identity, graph_registration: Mapping[str, object],
    case: Mapping[str, object], graph_context: Mapping[str, object], source: bytes,
    lane_id: str, case_root: Path, spec: Mapping[str, object],
):
    """Bind exact retained/no-text input and the actual isolated predecessor roots."""
    from tradingagents.graph.checkpoint_identity import build_checkpoint_run_identity
    from tradingagents.graph.checkpoint_runtime_identity import capture_checkpoint_predecessors

    safe, retained = _adapter_input(case, lane_id, source)
    context = _openrouter_prompt(safe, retained, FULL_GRAPH_INSTRUCTION)
    material = source_identity.to_dict()
    material.pop("identity_sha256")
    material.update(
        data_route_surface_sha256=_digest({
            "base": material["data_route_surface_sha256"],
            "graph_registration_sha256": graph_registration["graph_registration_sha256"],
            "graph_context": dict(graph_context), "safe_case": safe,
            "retained_context_sha256": hashlib.sha256(context.encode()).hexdigest(),
            "contract_sha256": FULL_GRAPH_PROMPT_SHA256,
        }),
        agent_prompt_surface_sha256=_digest({
            "base": material["agent_prompt_surface_sha256"],
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "contract_sha256": FULL_GRAPH_PROMPT_SHA256,
        }),
        learning_context_policy_identity=_digest({"contract": "benchmark-no-learning-v1", "context": ""}),
        provider_reasoning_settings={"temperature": 0, "max_retries": 0},
        **capture_checkpoint_predecessors(graph_case_config(case_root, spec)),
    )
    return build_checkpoint_run_identity(**material), safe, context


def execute_full_graph_case(
    *, source_identity, graph_registration: Mapping[str, object],
    case: Mapping[str, object], graph_context: Mapping[str, object], source: bytes,
    lane_id: str, case_root: Path, spec: Mapping[str, object], llm_factory=None,
) -> tuple[dict, dict]:
    """Run one new isolated case exactly once, retaining actual SQLite evidence.

    Cohort admission and all-case privacy preflight belong to the caller. Existing
    case directories are never resumed or overwritten by this execution route.
    """
    from tradingagents.graph.checkpoint_runtime_identity import validate_checkpoint_predecessors
    from tradingagents.graph.checkpointer import get_checkpointer, thread_id
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.packet_nodes import build_graph_run_id, validate_checkpoint_packet_references
    from tradingagents.graph.propagation import Propagator
    from tradingagents.graph.setup import GraphSetup
    from tradingagents.research.qualification_graph_model import GraphModelTelemetry, StrictGraphModel

    if not case_root.is_absolute() or case_root.exists() or case_root.is_symlink():
        raise ResearchQualificationBenchmarkError("full-graph case destination must be new and absolute")
    _require_registered_language()
    expected_context = next((row for row in graph_registration["case_contexts"] if row["case_id"] == case["case_id"]), None)
    if graph_context != expected_context or source_identity.requested_quick_model != spec["model"] or source_identity.requested_deep_model != spec["model"]:
        raise ResearchQualificationBenchmarkError("full-graph case context or model differs from its binding")
    identity, safe, retained_context = bind_full_graph_case_identity(
        source_identity=source_identity, graph_registration=graph_registration,
        case=case, graph_context=graph_context, source=source, lane_id=lane_id,
        case_root=case_root, spec=spec,
    )
    config = graph_case_config(case_root, spec)
    symbol, date = graph_context["company_of_interest"], graph_context["trade_date"]
    run_id = build_graph_run_id(symbol, date, "stock", identity.identity_sha256)
    validate_checkpoint_predecessors(config, identity, run_id=run_id, resuming=False)
    case_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    if llm_factory is None:
        from tradingagents.llm_clients.factory import create_llm_client

        llm_factory = create_llm_client
    telemetry = GraphModelTelemetry(spec, GRAPH_MODEL_ROLES, case_root)
    client = llm_factory(provider="openrouter", model=spec["model"], temperature=0, max_retries=0)
    model = StrictGraphModel(client.get_llm(), telemetry, str(safe["adapter_query"]))
    evidence_root = Path(config["results_dir"])
    ledger_root = evidence_root / "control_plane/decisions"
    workflow = GraphSetup(
        quick_thinking_llm=model, deep_thinking_llm=model, tool_nodes={},
        conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
        analyst_concurrency_limit=1, ledger_root=ledger_root, evidence_root=evidence_root,
        retained_analyst_context=retained_context,
    ).setup_graph(list(GRAPH_ANALYSTS))
    initial = Propagator().create_initial_state(
        symbol, date, "stock", run_id=run_id, learning_context="", past_context="",
    )
    initial["checkpoint_run_identity"] = identity.to_dict()
    tid = thread_id(symbol, date, identity.identity_sha256)
    invoke_config = {"configurable": {"thread_id": tid}, "recursion_limit": 100}
    started, visited = time.monotonic_ns(), []
    with get_checkpointer(config["data_cache_dir"], symbol) as saver:
        graph = workflow.compile(checkpointer=saver)
        if saver.get_tuple(invoke_config) is not None:
            raise ResearchQualificationBenchmarkError("full-graph fresh checkpoint unexpectedly exists")
        for update in graph.stream(initial, invoke_config, stream_mode="updates"):
            visited.extend(update)
        snapshot = graph.get_state(invoke_config)
        if snapshot.next or snapshot.values.get("checkpoint_run_identity") != identity.to_dict():
            raise ResearchQualificationBenchmarkError("full-graph checkpoint did not complete with its bound identity")
        state = snapshot.values
        checkpoint_id = snapshot.config["configurable"]["checkpoint_id"]
        events = validate_checkpoint_predecessors(config, identity, run_id=run_id, resuming=True)
        validate_checkpoint_packet_references(
            state, ledger_root=ledger_root, evidence_root=evidence_root, authenticated_events=events,
        )
    if (
        [row["role"] for row in telemetry.calls] != list(GRAPH_MODEL_ROLES)
        or any(role not in visited for role in GRAPH_MODEL_ROLES)
        or [event.kind for event in events] != ["research_evidence", "trader_proposal", "portfolio_decision"]
        or model.failed or model.benchmark_answer is None
    ):
        raise ResearchQualificationBenchmarkError("full-graph observed topology or completion is incomplete")
    output = {
        "case_id": case["case_id"], "answer": model.benchmark_answer,
        "source_artifact_id": case["artifact_id"], "byte_start": case["byte_start"], "byte_end": case["byte_end"],
        "input_sha256": safe["input_sha256"], "pair_id": safe["pair_id"],
    }
    receipt = {
        "schema_version": "research_full_graph_case/v1", "case_id": case["case_id"], "lane_id": lane_id,
        "graph_registration_sha256": graph_registration["graph_registration_sha256"],
        "case_directory": case_root.name, "graph_context": dict(graph_context),
        "run_id": run_id, "run_started_at": initial["run_started_at"],
        "checkpoint_run_identity": identity.to_dict(), "checkpoint_id": checkpoint_id, "thread_id": tid,
        "input_sha256": safe["input_sha256"], "pair_id": safe["pair_id"],
        "visited_nodes": visited, "model_calls": telemetry.calls,
        "decision_packet_refs": state["decision_packet_refs"],
        "answer_sha256": hashlib.sha256(model.benchmark_answer.encode()).hexdigest(),
        "latency_ms": max(0, (time.monotonic_ns() - started) // 1_000_000),
        "resume_policy": "exclusive_new_case_only", **AUTHORITY,
    }
    # The receipt binds private response files, including the final answer.
    # Role states also remain in the private checkpoint/evidence namespace.
    from tradingagents.research.qualification_benchmark import write_research_qualification_receipt

    write_research_qualification_receipt(receipt, case_root / "case-receipt.json")
    return output, receipt


def prepare_full_graph_execution(
    *, research_registration: object, graph_registration: object,
    artifact_root: str | Path, run_root: str | Path,
) -> dict:
    """Read-only all-case preflight, before any lane can construct a client."""
    research = _registration(research_registration)
    graph = validate_full_graph_registration(graph_registration, research)
    artifacts = Path(artifact_root).expanduser().resolve(strict=True)
    destination = Path(run_root).expanduser().absolute()
    if (
        destination != destination.resolve(strict=False)
        or destination.exists() or destination.is_symlink()
        or not destination.parent.is_dir()
        or destination.is_relative_to(artifacts) or artifacts.is_relative_to(destination)
    ):
        raise ResearchQualificationBenchmarkError("full-graph run root must be new, nonsymlinked and separate from source artifacts")
    cases = {case["case_id"]: case for case in research["cases"]}
    sources = {case_id: _source(artifacts, case) for case_id, case in cases.items()}
    for lane in ("tradingagents_full_graph", "tradingagents_full_graph_no_text"):
        for case_id, case in cases.items():
            _openrouter_prompt(*_adapter_input(case, lane, sources[case_id]), FULL_GRAPH_INSTRUCTION)
    identity = build_full_graph_source_identity(graph, research["lane_specs"]["tradingagents_full_graph"], destination)
    return {
        "research": research, "graph": graph, "run_root": destination,
        "cases": cases, "sources": sources, "source_identity": identity,
    }


def execute_prepared_full_graph(prepared: Mapping[str, object], *, llm_factory=None) -> tuple[list[dict], dict, dict]:
    """Execute both complete registered cohorts after the simpler-lane gates.

    This source function itself does not supply model-call authorization. Caller
    execution is explicit; failed/incomplete run namespaces are preserved and
    cannot be silently retried. No caller-supplied lane result replaces execution.
    """
    from decimal import Decimal

    from tradingagents.research.qualification_benchmark import write_research_qualification_receipt

    research, graph = prepared["research"], prepared["graph"]
    root, cases, sources = prepared["run_root"], prepared["cases"], prepared["sources"]
    source_identity = prepared["source_identity"]
    spec = research["lane_specs"]["tradingagents_full_graph"]
    if build_full_graph_source_identity(graph, spec, root) != source_identity:
        raise ResearchQualificationBenchmarkError("full-graph source changed after preflight")
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    contexts = {context["case_id"]: context for context in graph["case_contexts"]}
    lanes, captured, case_receipts, seen_outcomes = [], {}, [], set()
    for lane_id in ("tradingagents_full_graph", "tradingagents_full_graph_no_text"):
        outputs, call_rows, latency_ms = [], [], 0
        spec = research["lane_specs"][lane_id]
        for case_id, case in cases.items():
            output, receipt = execute_full_graph_case(
                source_identity=source_identity, graph_registration=graph, case=case,
                graph_context=contexts[case_id], source=sources[case_id], lane_id=lane_id,
                case_root=graph_case_directory(root, case_id, lane_id), spec=spec, llm_factory=llm_factory,
            )
            ids = [call["outcome_id"] for call in receipt["model_calls"]]
            if seen_outcomes.intersection(ids) or len(ids) != len(set(ids)):
                raise ResearchQualificationBenchmarkError("full-graph provider outcomes repeat across cases")
            seen_outcomes.update(ids)
            outputs.append(output)
            call_rows.extend(receipt["model_calls"])
            latency_ms += receipt["latency_ms"]
            case_receipts.append(receipt)
        cost = sum((Decimal(call["cost_usd"]) for call in call_rows), Decimal(0))
        captured[lane_id] = outputs
        lanes.append({
            "lane_id": lane_id, "requested_provider": spec["provider"], "requested_model": spec["model"],
            "requested_revision": spec["revision"], "actual_provider": call_rows[0]["actual_provider"],
            "actual_model": call_rows[0]["actual_model"], "actual_revision": call_rows[0]["actual_revision"],
            "route": call_rows[0]["route"], "prompt_sha256": spec["prompt_sha256"], "fallback_used": False,
            "input_tokens": sum(call["input_tokens"] for call in call_rows),
            "output_tokens": sum(call["output_tokens"] for call in call_rows), "latency_ms": latency_ms,
            "cost_usd": "0" if cost.is_zero() else format(cost.normalize(), "f"),
            "privacy_mode": "registered_retained_source",
            "outcome_ids": [call["outcome_id"] for call in call_rows],
            "checkpoint_id": f"registered-full-graph-{_digest([row['checkpoint_id'] for row in case_receipts if row['lane_id'] == lane_id])}",
            "case_outputs": outputs, **AUTHORITY,
        })
    if build_full_graph_source_identity(graph, spec, root) != source_identity:
        raise ResearchQualificationBenchmarkError("full-graph source changed during execution")
    execution = {
        "schema_version": "research_full_graph_execution/v1", "status": "completed",
        "graph_registration": graph, "run_root": str(root), "case_runs": case_receipts, **AUTHORITY,
    }
    write_research_qualification_receipt(execution, root / "execution-receipt.json")
    return lanes, captured, execution
