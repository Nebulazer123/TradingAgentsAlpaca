"""Hermetic full-role adapter proof; no real model or corpus qualification."""

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from cli.main import app
from tests.test_research_qualification_benchmark import _fixture, _lane, _output, _specs
from tradingagents.graph import checkpoint_runtime_identity
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.research.qualification_benchmark import (
    LANE_ORDER,
    ResearchQualificationBenchmarkError,
    build_research_qualification_registration,
    execute_registered_openrouter_benchmark,
)
from tradingagents.research.qualification_full_graph import (
    FULL_GRAPH_PROMPT_SHA256,
    GRAPH_MODEL_ROLES,
    bind_full_graph_case_identity,
    build_full_graph_registration,
    build_full_graph_source_identity,
    execute_full_graph_case,
    graph_case_directory,
    prepare_full_graph_execution,
    validate_full_graph_registration,
)


def _registered(tmp_path, monkeypatch, *, wrong_expected=0):
    root, cases, _ = _fixture(tmp_path, wrong_expected=wrong_expected)
    specs = _specs()
    for lane in ("tradingagents_full_graph", "tradingagents_full_graph_no_text"):
        specs[lane]["prompt_sha256"] = FULL_GRAPH_PROMPT_SHA256
    research = build_research_qualification_registration(
        cases, minimum_accuracy_gain="0.001",
        lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER}, lane_specs=specs,
    )
    contexts = [dict(case_id=c["case_id"], company_of_interest="AAPL", trade_date="2026-09-11", asset_type="stock") for c in cases]
    graph = build_full_graph_registration(
        research_registration=research, case_contexts=contexts, clean_source_revision="a" * 40,
        uv_lock_sha256=hashlib.sha256((Path(__file__).resolve().parents[1] / "uv.lock").read_bytes()).hexdigest(),
    )
    # Only the source-revision probe is synthetic. Role implementations, source
    # surfaces, predecessor binding, client, callbacks and SQLite are real.
    monkeypatch.setattr(checkpoint_runtime_identity, "_clean_source_revision", lambda _root: "a" * 40)
    return root, cases, research, graph


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown", "bad_date", "symbol", "asset"])
def test_full_graph_context_must_cover_exact_registered_cohort(tmp_path, monkeypatch, change):
    _root, _cases, research, graph = _registered(tmp_path, monkeypatch)
    contexts = [dict(row) for row in graph["case_contexts"]]
    if change == "missing":
        contexts.pop()
    elif change == "duplicate":
        contexts[-1] = contexts[0]
    else:
        key, value = {
            "unknown": ("case_id", "unregistered"), "bad_date": ("trade_date", "20260911"),
            "symbol": ("company_of_interest", "../AAPL"), "asset": ("asset_type", "crypto"),
        }[change]
        contexts[0][key] = value
    with pytest.raises(ResearchQualificationBenchmarkError):
        build_full_graph_registration(
            research_registration=research, case_contexts=contexts,
            clean_source_revision="a" * 40, uv_lock_sha256=graph["uv_lock_sha256"],
        )


def _case_inputs(tmp_path, monkeypatch):
    root, cases, research, graph = _registered(tmp_path, monkeypatch)
    run_root = tmp_path / "graph-runs"
    run_root.mkdir()
    lane = "tradingagents_full_graph"
    spec = research["lane_specs"][lane]
    source_identity = build_full_graph_source_identity(graph, spec, run_root)
    case = cases[0]
    raw = (root / case["artifact_path"]).read_bytes()[case["byte_start"]:case["byte_end"]]
    return dict(
        source_identity=source_identity, graph_registration=graph, case=case,
        graph_context=graph["case_contexts"][0], source=raw, lane_id=lane,
        case_root=graph_case_directory(run_root, case["case_id"], lane), spec=spec,
    )


def test_full_graph_identity_binds_exact_context_input_variant_and_predecessors(tmp_path, monkeypatch):
    args = _case_inputs(tmp_path, monkeypatch)
    first, safe, _ = bind_full_graph_case_identity(**args)
    twin, no_text, _ = bind_full_graph_case_identity(**{**args, "lane_id": "tradingagents_full_graph_no_text"})
    assert first.identity_sha256 != twin.identity_sha256
    assert safe["pair_id"] == no_text["pair_id"] and safe["input_sha256"] != no_text["input_sha256"]
    changed, _, _ = bind_full_graph_case_identity(**{**args, "graph_context": {**args["graph_context"], "trade_date": "2026-09-10"}})
    assert changed.identity_sha256 != first.identity_sha256
    moved, _, _ = bind_full_graph_case_identity(**{**args, "case_root": args["case_root"].with_name("another-case")})
    assert moved.learning_evidence_predecessor != first.learning_evidence_predecessor
    assert moved.decision_ledger_predecessor != first.decision_ledger_predecessor
    assert not args["case_root"].exists()


def _factory(monkeypatch, calls, *, fault=None):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(request):
        payload = json.loads(request.content)
        framed = json.loads(payload["messages"][0]["content"])
        calls.append(framed)
        prompt = framed.get("role_prompt")
        if prompt is None:
            source = framed["retained_source"]
            prompt = json.dumps({"retained_input": json.dumps({"retained_source": source})})
        if not isinstance(prompt, str):
            prompt = json.dumps(prompt)
        if prompt.startswith("{"):
            analyst = json.loads(prompt)
            source = json.loads(analyst["retained_input"])["retained_source"]
            answer = json.loads(source)["facts"]["answer"] if source else "UNAVAILABLE"
        else:
            matches = re.findall(r"ANSWER: (answer-\d+|UNAVAILABLE)", prompt)
            answer = matches[-1] if matches else "UNAVAILABLE"
        report = f"ANSWER: {answer}"
        message = {"role": "assistant", "content": report}
        if payload.get("tools"):
            name = payload["tools"][0]["function"]["name"]
            arguments = {
                "ResearchPlan": {"recommendation": "Hold", "rationale": report, "strategic_actions": report},
                "TraderProposal": {"action": "Hold", "reasoning": report},
                "BenchmarkPortfolioDecision": {"rating": "Hold", "executive_summary": report, "investment_thesis": report, "benchmark_answer": answer},
            }[name]
            if fault == "structured" and len(calls) == 7:
                arguments = {"recommendation": "not-a-rating"}
            if fault == "sensitive_final" and len(calls) == 12:
                arguments["executive_summary"] = "api_key=synthetic-private-key-1234567890"
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"tool-{len(calls)}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)},
            }]}
        reply = {
            "id": f"response-{len(calls)}", "object": "chat.completion", "created": 1,
            "model": payload["model"], "provider": "openrouter", "route": "synthetic-source-adapter",
            "fallback_used": False, "system_fingerprint": "fixture-v1",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if payload.get("tools") else "stop", "message": message}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
        if fault == "telemetry":
            reply.pop("provider")
        return httpx.Response(200, json=reply)

    def factory(**kwargs):
        if "max_retries" in kwargs:
            assert kwargs["max_retries"] == 0 and kwargs["temperature"] == 0
        return create_llm_client(**kwargs, base_url="https://benchmark.test/v1", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    return factory


@pytest.mark.parametrize("no_text", [False, True])
def test_actual_full_graph_model_calls_checkpoints_and_answer_without_extra_model(tmp_path, monkeypatch, no_text):
    args = _case_inputs(tmp_path, monkeypatch)
    if no_text:
        args["lane_id"] = "tradingagents_full_graph_no_text"
    calls = []
    output, receipt = execute_full_graph_case(**args, llm_factory=_factory(monkeypatch, calls))
    assert output["answer"] == ("UNAVAILABLE" if no_text else "answer-0000")
    assert len(calls) == 12
    assert all("expected_answer" not in json.dumps(call) for call in calls)
    assert [row["role"] for row in receipt["model_calls"]] == list(GRAPH_MODEL_ROLES)
    assert sum(row["input_tokens"] for row in receipt["model_calls"]) == 24
    assert sum(row["output_tokens"] for row in receipt["model_calls"]) == 12
    assert len(receipt["decision_packet_refs"]) == 3
    assert receipt["checkpoint_id"] and receipt["thread_id"]
    assert receipt["analysis_only"] and not receipt["can_submit_orders"]
    assert (args["case_root"] / "case-receipt.json").is_file()
    for row in receipt["model_calls"]:
        path = args["case_root"] / row["response_path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["response_sha256"]
        assert path.stat().st_mode & 0o777 == 0o600
        retained = json.loads(path.read_bytes())
        assert retained["outcome_id"] == row["outcome_id"]
    assert retained["message"]["data"]["tool_calls"][0]["args"]["benchmark_answer"] == output["answer"]
    with pytest.raises(ResearchQualificationBenchmarkError, match="destination"):
        execute_full_graph_case(**args, llm_factory=lambda **_: pytest.fail("existing case reexecuted"))


@pytest.mark.parametrize("fault,count", [("telemetry", 1), ("structured", 7), ("sensitive_final", 12)])
def test_graph_telemetry_or_structured_failure_never_silently_retries(tmp_path, monkeypatch, fault, count):
    args = _case_inputs(tmp_path, monkeypatch)
    calls = []
    with pytest.raises(ResearchQualificationBenchmarkError):
        execute_full_graph_case(**args, llm_factory=_factory(monkeypatch, calls, fault=fault))
    assert len(calls) == count
    assert not (args["case_root"] / "case-receipt.json").exists()


def test_graph_registration_cannot_be_rebound_or_mutated(tmp_path, monkeypatch):
    _root, _cases, research, graph = _registered(tmp_path, monkeypatch)
    with pytest.raises(ResearchQualificationBenchmarkError, match="identity"):
        validate_full_graph_registration({**graph, "research_registration_sha256": "f" * 64}, research)
    with pytest.raises(ResearchQualificationBenchmarkError, match="digest"):
        validate_full_graph_registration({**graph, "clean_source_revision": "b" * 40}, research)


@pytest.mark.parametrize("location", ["existing", "source_child", "source_parent", "symlink"])
def test_graph_namespace_preflight_preserves_sources_and_creates_nothing(tmp_path, monkeypatch, location):
    root, _cases, research, graph = _registered(tmp_path, monkeypatch)
    destination = tmp_path / "runs"
    if location == "existing":
        destination.mkdir()
    elif location == "source_child":
        destination = root / "runs"
    elif location == "source_parent":
        destination = root.parent
    else:
        destination.symlink_to(root, target_is_directory=True)
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    with pytest.raises(ResearchQualificationBenchmarkError, match="run root"):
        prepare_full_graph_execution(
            research_registration=research, graph_registration=graph,
            artifact_root=root, run_root=destination,
        )
    assert {p.relative_to(tmp_path) for p in tmp_path.rglob("*")} == before


def test_full_graph_privacy_is_checked_for_every_case_before_any_model(tmp_path, monkeypatch):
    root, cases, research, graph = _registered(tmp_path, monkeypatch, wrong_expected=7)
    cases[-1] = {**cases[-1], "variant_id": "api_key=sk-test-sensitive-outbound-value"}
    research = build_research_qualification_registration(
        cases, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER},
        lane_specs=research["lane_specs"],
    )
    graph = build_full_graph_registration(
        research_registration=research, case_contexts=graph["case_contexts"],
        clean_source_revision="a" * 40, uv_lock_sha256=graph["uv_lock_sha256"],
    )
    destination = tmp_path / "runs"
    with pytest.raises(ResearchQualificationBenchmarkError, match="sensitive"):
        execute_registered_openrouter_benchmark(
            registration=research, deterministic_result=_lane("deterministic_sec_xbrl", cases, root),
            artifact_root=root, execute_full_graph=True, full_graph_registration=graph,
            full_graph_run_root=destination, llm_factory=lambda **_: pytest.fail("client built before all-case privacy admission"),
        )
    assert not destination.exists()


def test_perfect_local_lane_skips_full_graph_without_client_or_namespace(tmp_path, monkeypatch):
    root, cases, research, graph = _registered(tmp_path, monkeypatch)
    destination = tmp_path / "runs"
    receipt = execute_registered_openrouter_benchmark(
        registration=research, deterministic_result=_lane("deterministic_sec_xbrl", cases, root),
        artifact_root=root, execute_full_graph=True, full_graph_registration=graph,
        full_graph_run_root=destination, llm_factory=lambda **_: pytest.fail("unattainable graph improvement executed"),
    )
    assert receipt["full_graph_execution"]["status"] == "not_run"
    assert receipt["full_graph_execution"]["reason"] == "registered_accuracy_gain_unattainable"
    assert not destination.exists()


def test_cli_executes_full_registered_cohort_orchestration_without_reducing_minimums(tmp_path, monkeypatch):
    """Stub per-case graph execution only; separate tests execute its real 12 roles."""
    from tradingagents.llm_clients import factory as factory_module
    from tradingagents.research import qualification_full_graph as full_graph

    root, cases, research, graph = _registered(tmp_path, monkeypatch, wrong_expected=7)
    calls, graph_cases = [], []
    monkeypatch.setattr(factory_module, "create_llm_client", _factory(monkeypatch, calls))

    def observed_case(**kwargs):
        case, lane = kwargs["case"], kwargs["lane_id"]
        graph_cases.append((lane, case["case_id"]))
        answer = "UNAVAILABLE" if lane.endswith("_no_text") else json.loads(kwargs["source"])["facts"]["answer"]
        output = _output(case, answer, lane, root)
        model_calls = [{
            "role": role, "outcome_id": f"{lane}-{case['case_id']}-{role}",
            "actual_provider": "openrouter", "actual_model": "registered-model", "actual_revision": "fixture-v1",
            "route": "synthetic-source-adapter", "input_tokens": 2, "output_tokens": 1, "cost_usd": "0.000004",
        } for role in GRAPH_MODEL_ROLES]
        return output, {"case_id": case["case_id"], "lane_id": lane, "model_calls": model_calls, "latency_ms": 1, "checkpoint_id": f"synthetic-{lane}-{case['case_id']}"}

    monkeypatch.setattr(full_graph, "execute_full_graph_case", observed_case)
    registration_path, graph_path, lanes_path = (tmp_path / name for name in ("registration.json", "graph.json", "lanes.json"))
    registration_path.write_text(json.dumps(research))
    graph_path.write_text(json.dumps(graph))
    lanes_path.write_text(json.dumps([_lane("deterministic_sec_xbrl", cases, root)]))
    result_path, run_root = tmp_path / "result.json", tmp_path / "runs"
    result = CliRunner().invoke(app, [
        "research", "research-stack-benchmark", "--registration-path", str(registration_path),
        "--lane-results-path", str(lanes_path), "--artifact-root", str(root), "--output-path", str(result_path),
        "--execute-openrouter", "--execute-full-graph", "--full-graph-registration-path", str(graph_path),
        "--full-graph-run-root", str(run_root),
    ])
    assert result.exit_code == 0, result.output
    receipt = json.loads(result_path.read_bytes())
    assert graph_cases == [(lane, c["case_id"]) for lane in ("tradingagents_full_graph", "tradingagents_full_graph_no_text") for c in cases]
    assert len(graph_cases) == 2800 and len(calls) == 2800
    assert receipt["full_graph_execution"]["status"] == "completed"
    for lane in receipt["lane_results"]:
        if lane["lane_id"].startswith("tradingagents_full_graph"):
            assert len(lane["case_outputs"]) == 1400 and len(lane["outcome_ids"]) == 16800
            assert lane["input_tokens"] == 33600 and lane["output_tokens"] == 16800
            assert Decimal(lane["cost_usd"]) == Decimal("0.0672")
    assert receipt["selected_lane"] == "deterministic_sec_xbrl"
    assert (run_root / "execution-receipt.json").is_file()


def test_cli_graph_execution_needs_explicit_flags_and_protected_output_preflight(tmp_path, monkeypatch):
    import cli.main as cli_module

    monkeypatch.setattr(cli_module, "execute_registered_openrouter_benchmark", lambda **_: pytest.fail("unsafe CLI inputs reached model runner"))
    common = ["research", "research-stack-benchmark", "--registration-path", "missing.json", "--lane-results-path", "missing-lanes.json", "--artifact-root", str(tmp_path)]
    result = CliRunner().invoke(app, [*common, "--execute-full-graph"])
    assert result.exit_code == 2 and "requires" in result.output and "execute-openrouter" in result.output
    result = CliRunner().invoke(app, [*common, "--execute-openrouter", "--execute-full-graph"])
    assert result.exit_code == 2 and "registration" in result.output
    protected = tmp_path / "source.json"
    protected.write_text("unchanged")
    result = CliRunner().invoke(app, [*common, "--execute-openrouter", "--output-path", str(protected)])
    assert result.exit_code == 2 and "output path" in result.output
    assert protected.read_text() == "unchanged"


def test_all_benchmark_model_routes_disable_hidden_sdk_retries(tmp_path, monkeypatch):
    from openai import APIStatusError

    root, cases, research, _graph = _registered(tmp_path, monkeypatch, wrong_expected=7)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    requests = []

    def failure(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"message": "synthetic unavailable"}})

    def factory(**kwargs):
        return create_llm_client(**kwargs, base_url="https://benchmark.test/v1", http_client=httpx.Client(transport=httpx.MockTransport(failure)))

    with pytest.raises(APIStatusError):
        execute_registered_openrouter_benchmark(
            registration=research, deterministic_result=_lane("deterministic_sec_xbrl", cases, root),
            artifact_root=root, llm_factory=factory,
        )
    assert len(requests) == 1


def test_full_graph_rejects_ambient_language_drift_without_changing_it(tmp_path, monkeypatch):
    from tradingagents.dataflows import config as data_config

    args = _case_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(data_config, "_config", {**data_config.get_config(), "output_language": "Spanish"})
    with pytest.raises(ResearchQualificationBenchmarkError, match="language"):
        execute_full_graph_case(**args, llm_factory=lambda **_: pytest.fail("language mismatch constructed a client"))
    assert data_config.get_config()["output_language"] == "Spanish"
    assert not args["case_root"].exists()
