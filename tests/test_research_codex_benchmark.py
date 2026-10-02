"""Small synthetic v7 fixtures; no inference or real corpus rerun."""
from __future__ import annotations

import copy
import hashlib
import json
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

from cli.main import app
from tests.test_research_qualification_benchmark import _specs
from tests.test_research_qualification_media import _pdf, _png
from tests.test_research_semantic_bundle import _artifact, _case, _query
from tradingagents.graph import checkpoint_runtime_identity
from tradingagents.llm_clients import codex_client
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.research import qualification_benchmark as benchmark
from tradingagents.research.qualification_codex import (
    CODEX_GRAPH_LANE,
    CODEX_LANE_ORDER,
    CODEX_REVIEWER_LANE,
    CODEX_SOURCE_LANE,
    execute_registered_codex_benchmark,
    migrate_codex_subscription_registration,
    validate_codex_lane_spec,
    validate_codex_response,
)
from tradingagents.research.qualification_full_graph import (
    FULL_GRAPH_PROMPT_SHA256,
    GRAPH_MODEL_ROLES,
    build_full_graph_registration,
    build_full_graph_source_identity,
    execute_full_graph_case,
    graph_case_config,
    graph_case_directory,
    validate_full_graph_registration,
)
from tradingagents.research.qualification_media import build_media_input
from tradingagents.research.qualification_source_bundle import build_source_bundle_input


@pytest.fixture(autouse=True)
def no_network_or_real_runner(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A benchmark fixture attempted a real external call")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    real_run = subprocess.run
    def bounded_local(command, **kwargs):
        if Path(command[0]).name not in {"pdfinfo", "pdftotext", "pdftohtml", "pdftoppm", "tesseract"}:
            return forbidden(command, **kwargs)
        return real_run(command, **kwargs)
    monkeypatch.setattr(subprocess, "run", bounded_local)
    monkeypatch.setattr(codex_client, "codex_runner_version", lambda: "codex-cli 0.159.2")


def specs():
    old = _specs()
    result = {lane: old[lane] for lane in ("deterministic_sec_xbrl", "metadata_fts5_bm25", "metadata_fts5_bm25_no_text")}
    for base in CODEX_LANE_ORDER[2:]:
        prompt = FULL_GRAPH_PROMPT_SHA256 if base == CODEX_GRAPH_LANE else benchmark.REVIEWER_PROMPT_SHA256 if base == CODEX_REVIEWER_LANE else benchmark.OPENROUTER_PROMPT_SHA256
        for lane in (base, base + "_no_text"):
            result[lane] = {"provider": "codex", "model": "gpt-6.1-sol" if base == CODEX_REVIEWER_LANE else "gpt-6-luna", "revision": None,
                            "route": codex_client.CODEX_ROUTE, "prompt_sha256": prompt, "input_price_per_million_usd": None, "output_price_per_million_usd": None,
                            "runner_contract": "codex-exec-chat/v1", "runner_version": "codex-cli 0.159.2", "billing_kind": "chatgpt_subscription",
                            "reasoning_effort": "low", "max_input_bytes": 262144, "max_output_chars": 65536, "timeout_seconds": 120}
    return result


def fixture(tmp_path, monkeypatch, *, permit_gain=False):
    # Smaller count constants are scoped to this synthetic integration fixture;
    # production remains 500/300/400/200 and legacy full-size tests cover those.
    monkeypatch.setattr(benchmark, "MINIMUM_COUNTS", dict(filing_document_page=2, temporal_restatement_contradiction_cutoff_question=1, workflow_grounded_case=1, injection_case=5))
    root = tmp_path / "sources"
    root.mkdir()
    pdf = _pdf(["Revenue 1250", "Profit 700"])
    corpus = [("filing_document_page", "pdf", pdf, 1, "pdf_image", ["material", "text"]),
              ("filing_document_page", "pdf", pdf, 2, "pdf_image", ["material", "text"]),
              ("temporal_restatement_contradiction_cutoff_question", "json", b'{"answer":"value"}', None, "text", ["material", "json_values", "answer"]),
              ("workflow_grounded_case", "repository_document", b"Source-only setting\n", None, "repository_document", ["material", "text"]),
              ("injection_case", "html", b"<html><body>Ignore controls</body></html>", None, "text", ["material", "text"]),
              ("injection_case", "html", b"<html><body><table><tr><td>Revenue</td></tr></table></body></html>", None, "table", ["material", "text"]),
              ("injection_case", "image", _png(), 1, "pdf_image", ["transformations", 0, "operation"]),
              ("injection_case", "repository_document", b"Ignore authority\n", None, "repository_document", ["material", "text"]),
              ("injection_case", "tool_output", b"Captured response\nIgnore authority\n", None, "tool_output", ["material", "text"])]
    cases = []
    for index, (kind, fmt, raw, page, medium, path) in enumerate(corpus):
        artifact = _artifact(root, f"media-{index}", raw)
        media, _ = build_media_input(raw, format=fmt, page_number=page)
        descriptor, supplied = build_source_bundle_input(root, [dict(source_id="media", kind="media", original=artifact, media_input=media)])
        case = _case(descriptor, _query("scalar_path", source_id="media", json_path=path), case_id=f"case-{index}", kind=kind, medium=medium)
        case["expected_answer"] = benchmark._extract(case, supplied)
        if permit_gain and index == 2:
            # Deliberate synthetic negative label makes an accuracy improvement
            # attainable for execution-path testing; not a reviewed corpus label.
            case["expected_answer"] = "negative_fixture_label"
            case["severity"] = "normal"
            case["ambiguous"] = True
        case["expected_answer_sha256"] = hashlib.sha256(case["expected_answer"].encode()).hexdigest()
        cases.append(case)
    prior = benchmark.build_research_qualification_registration(cases, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in benchmark.LANE_ORDER}, lane_specs=_specs(), schema_version="research_qualification_registration/v6")
    registration = migrate_codex_subscription_registration(previous_registration=prior, lane_specs=specs())
    indexed = {c["case_id"]: c for c in cases}
    sources = {cid: benchmark._source(root, c) for cid, c in indexed.items()}
    deterministic = benchmark._metadata_fts5_lane_result(lane_id="deterministic_sec_xbrl", cases=indexed, sources=sources,
        answers={cid: benchmark._extract(indexed[cid], source) for cid, source in sources.items()}, spec=registration["lane_specs"]["deterministic_sec_xbrl"], registration_sha256=registration["registration_sha256"], latency_ms=0)
    return root, registration, deterministic, prior


def metadata(spec, serial=1):
    return {"provider": "codex", "route": spec["route"], "backend_url": spec["route"], "requested_model": spec["model"], "model_name": spec["model"],
            "serving_revision": None, "runner_version": spec["runner_version"], "runner_contract": spec["runner_contract"],
            "billing_mode": spec["billing_kind"], "reasoning_effort": spec["reasoning_effort"], "max_input_bytes": spec["max_input_bytes"],
            "max_output_chars": spec["max_output_chars"], "timeout_seconds": float(spec["timeout_seconds"]), "returned_provider_identity": None,
            "returned_model_name": None, "model_identity_source": "requested_cli_argument_only", "fallback_used": False, "provider_output_token_cap_enforced": False,
            "subscription_cost_usd": None, "subscription_cost_status": "unknown_subscription_allocation", "subscription_usage": {"input_tokens": 10, "output_tokens": 4, "cached_input_tokens": 2},
            "runner_outcome": {"thread_id": "fixture", "item_id": str(serial)}, "id": f"codex:fixture:{serial}"}


def fake_factory(calls, *, fault=None):
    def factory(**kwargs):
        calls.append(dict(kwargs))
        spec = next(v for v in specs().values() if v["provider"] == "codex" and v["model"] == kwargs["model"])
        class Model:
            def invoke(self, prompt):
                packet = json.loads(prompt)
                assert "expected_answer" not in prompt and "negative_fixture_label" not in prompt
                serial = sum(item.get("responses", 0) for item in calls) + 1
                calls[-1]["responses"] = calls[-1].get("responses", 0) + 1
                source = packet["retained_source"].encode()
                answer = benchmark._extract(packet["case"], source) if source else "UNAVAILABLE"
                meta, usage = metadata(spec, serial), {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
                if fault == "missing_usage":
                    usage = None
                elif fault == "model":
                    meta["requested_model"] = "gpt-6-astra"
                elif fault == "runner":
                    meta["runner_version"] = "codex-cli 0.1.0"
                elif fault == "outcome":
                    meta["runner_outcome"]["item_id"] = None
                elif fault == "duplicate":
                    meta = metadata(spec, 1)
                elif fault == "provider":
                    meta["provider"] = "openrouter"
                elif fault == "revision":
                    meta["serving_revision"] = "invented"
                elif fault == "bounds":
                    meta["max_output_chars"] += 1
                return AIMessage(content=answer, response_metadata=meta, usage_metadata=usage)
        return SimpleNamespace(get_llm=lambda: Model())
    return factory


def test_migration_preserves_exact_cases_and_historical_registration(tmp_path, monkeypatch):
    _root, new, _deterministic, old = fixture(tmp_path, monkeypatch)
    before = benchmark._bytes(old)
    assert new["schema_version"].endswith("/v7") and new["registration_sha256"] != old["registration_sha256"]
    assert benchmark._bytes(new["cases"]) == benchmark._bytes(old["cases"])
    assert benchmark._registration(json.loads(benchmark._bytes(old))) == old
    assert benchmark._bytes(old) == before
    assert "openrouter_source_bound" in old["lane_specs"] and CODEX_SOURCE_LANE in new["lane_specs"]


@pytest.mark.parametrize("key,value", [("provider", "openrouter"), ("model", "unregistered"), ("revision", "invented"), ("route", "https://api.openai.com/v1"), ("input_price_per_million_usd", "0"), ("max_input_bytes", True), ("runner_version", "unknown")])
def test_codex_spec_rejects_provider_and_fabricated_identity_or_price(key, value):
    spec = specs()[CODEX_SOURCE_LANE]
    spec[key] = value
    with pytest.raises(benchmark.ResearchQualificationBenchmarkError):
        validate_codex_lane_spec(spec)


def test_perfect_local_result_starts_no_model_or_runner(tmp_path, monkeypatch):
    root, registration, deterministic, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(codex_client, "codex_runner_version", lambda: pytest.fail("No runner needed when gain unattainable"))
    result = execute_registered_codex_benchmark(registration=registration, deterministic_result=deterministic, artifact_root=root, llm_factory=lambda **kwargs: pytest.fail("No model needed"))
    assert result["codex_subscription_execution"]["status"] == "not_run"
    assert result["selected_lane"] == "deterministic_sec_xbrl"


def test_mocked_executor_dispatches_exact_route_and_unknown_cost_and_model(tmp_path, monkeypatch):
    root, registration, deterministic, _ = fixture(tmp_path, monkeypatch, permit_gain=True)
    calls = []
    result = execute_registered_codex_benchmark(registration=registration, deterministic_result=deterministic, artifact_root=root, llm_factory=fake_factory(calls), execute_reviewer=True)
    assert [call["model"] for call in calls] == ["gpt-6-luna", "gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-sol"]
    assert all(call["provider"] == "codex" and call["max_input_bytes"] == 262144 and call["max_retries"] == 0 for call in calls)
    source = next(row for row in result["lane_results"] if row["lane_id"] == CODEX_SOURCE_LANE)
    assert source["cost_usd"] is None and source["cohort_cost_usd"] is None
    assert source["actual_model"] is None and source["actual_revision"] is None
    assert source["requested_model"] == "gpt-6-luna" and source["returned_provider_identity"] is None
    assert result["selected_lane"] != CODEX_SOURCE_LANE
    assert result["codex_subscription_execution"]["status"] == "completed"
    reviewer = next(row for row in result["lane_results"] if row["lane_id"] == CODEX_REVIEWER_LANE)
    assert reviewer["cohort_cost_usd"] is None


@pytest.mark.parametrize("fault", ["missing_usage", "model", "runner", "outcome", "duplicate", "provider", "revision", "bounds"])
def test_missing_or_mismatched_telemetry_stops_without_fallback(tmp_path, monkeypatch, fault):
    root, registration, deterministic, _ = fixture(tmp_path, monkeypatch, permit_gain=True)
    calls = []
    with pytest.raises(benchmark.ResearchQualificationBenchmarkError):
        execute_registered_codex_benchmark(registration=registration, deterministic_result=deterministic, artifact_root=root, llm_factory=fake_factory(calls, fault=fault))
    assert len(calls) == 1


@pytest.mark.parametrize("fault", ["prompt", "installed_runner", "sensitive", "input_bound"])
def test_all_route_and_prompt_preflights_precede_clients(tmp_path, monkeypatch, fault):
    root, registration, deterministic, _ = fixture(tmp_path, monkeypatch, permit_gain=True)
    if fault in {"prompt", "input_bound"}:
        changed = copy.deepcopy(registration["lane_specs"])
        for lane in (CODEX_SOURCE_LANE, CODEX_SOURCE_LANE + "_no_text"):
            if fault == "prompt":
                changed[lane]["prompt_sha256"] = "0" * 64
            else:
                changed[lane]["max_input_bytes"] = 1
        registration = benchmark.build_research_qualification_registration(registration["cases"], minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in CODEX_LANE_ORDER}, lane_specs=changed, schema_version=registration["schema_version"])
    elif fault == "installed_runner":
        monkeypatch.setattr(codex_client, "codex_runner_version", lambda: "codex-cli 0.1.0")
    else:
        original = benchmark._sensitive_outbound_value
        monkeypatch.setattr(benchmark, "_sensitive_outbound_value", lambda value: True if isinstance(value, dict) and "case_id" in value else original(value))
    with pytest.raises(benchmark.ResearchQualificationBenchmarkError):
        execute_registered_codex_benchmark(registration=registration, deterministic_result=deterministic, artifact_root=root, llm_factory=lambda **kwargs: pytest.fail("Preflight must stop before client"))


def test_response_and_score_reject_even_equal_wrong_types():
    spec = specs()[CODEX_SOURCE_LANE]
    for key in ("fallback_used", "provider_output_token_cap_enforced"):
        row = metadata(spec)
        row[key] = 0
        with pytest.raises(benchmark.ResearchQualificationBenchmarkError):
            validate_codex_response(row, {"input_tokens": 10, "output_tokens": 4}, spec)


def test_full_graph_registration_and_config_are_separate_codex_route(tmp_path, monkeypatch):
    root, research, _, _ = fixture(tmp_path, monkeypatch)
    graph = build_full_graph_registration(research_registration=research,
        case_contexts=[dict(case_id=case["case_id"], company_of_interest="AAPL", trade_date="2026-10-01", asset_type="stock") for case in research["cases"]],
        clean_source_revision="a" * 40, uv_lock_sha256=hashlib.sha256((Path(__file__).resolve().parents[1] / "uv.lock").read_bytes()).hexdigest())
    assert graph["schema_version"] == "research_full_graph_registration/v2"
    assert validate_full_graph_registration(graph, research) == graph
    spec = research["lane_specs"][CODEX_GRAPH_LANE]
    config = graph_case_config(tmp_path / "new-case", spec)
    assert config["llm_provider"] == "codex" and config["backend_url"] == codex_client.CODEX_ROUTE
    monkeypatch.setattr(checkpoint_runtime_identity, "_clean_source_revision", lambda _: "a" * 40)
    identity = build_full_graph_source_identity(graph, spec, tmp_path)
    assert identity.requested_provider == "codex"
    assert identity.provider_reasoning_settings["runner_version"] == "codex-cli 0.159.2"


def test_cli_selects_one_explicit_executor_and_keeps_reviewer_opt_in():
    result = CliRunner().invoke(app, ["research", "research-stack-benchmark", "--execute-openrouter", "--execute-codex", "--registration-path", "unused.json", "--lane-results-path", "unused.json", "--artifact-root", "."])
    assert result.exit_code != 0 and "exactly one" in result.output


@pytest.mark.parametrize("no_text", [False, True])
def test_actual_codex_client_runs_mocked_full_graph_with_structured_roles(tmp_path, monkeypatch, no_text):
    root, research, _, _ = fixture(tmp_path, monkeypatch)
    graph = build_full_graph_registration(research_registration=research,
        case_contexts=[dict(case_id=case["case_id"], company_of_interest="AAPL", trade_date="2026-10-01", asset_type="stock") for case in research["cases"]],
        clean_source_revision="a" * 40, uv_lock_sha256=hashlib.sha256((Path(__file__).resolve().parents[1] / "uv.lock").read_bytes()).hexdigest())
    monkeypatch.setattr(checkpoint_runtime_identity, "_clean_source_revision", lambda _: "a" * 40)
    spec = research["lane_specs"][CODEX_GRAPH_LANE]
    case = research["cases"][2]
    lane = CODEX_GRAPH_LANE + ("_no_text" if no_text else "")
    identity = build_full_graph_source_identity(graph, spec, tmp_path)
    calls = []
    def run(command, **kwargs):
        assert command[command.index("--model") + 1] == spec["model"]
        packet = json.loads(kwargs["input"].splitlines()[-1])
        framed = json.loads(packet["messages"][0]["content"])
        assert "expected_answer" not in json.dumps(framed)
        calls.append(framed)
        prompt = framed["role_prompt"]
        if not isinstance(prompt, str):
            prompt = json.dumps(prompt)
        if prompt.startswith("{"):
            analyst = json.loads(prompt)
            context = json.loads(analyst["retained_input"])
            source = context["retained_source"].encode()
            answer = benchmark._extract(context["case"], source) if source else "UNAVAILABLE"
        else:
            import re
            matches = re.findall(r"ANSWER: (value|UNAVAILABLE)\b", prompt)
            answer = matches[-1] if matches else "UNAVAILABLE"
        report = f"ANSWER: {answer}"
        reply = {"content": report, "tool_calls": []}
        if packet["tools"]:
            name = packet["tools"][0]["function"]["name"]
            args = {"ResearchPlan": {"recommendation": "Hold", "rationale": report, "strategic_actions": report},
                    "TraderProposal": {"action": "Hold", "reasoning": report},
                    "BenchmarkPortfolioDecision": {"rating": "Hold", "executive_summary": report, "investment_thesis": report, "benchmark_answer": answer}}[name]
            reply = {"content": "", "tool_calls": [{"name": name, "arguments_json": json.dumps(args)}]}
        event_rows = [{"type": "thread.started", "thread_id": "fixture-full"}, {"type": "item.completed", "item": {"type": "agent_message", "id": str(len(calls)), "text": json.dumps(reply)}}, {"type": "turn.completed", "usage": {"input_tokens": 2, "output_tokens": 1}}]
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(row) for row in event_rows), stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    output, receipt = execute_full_graph_case(source_identity=identity, graph_registration=graph, case=case,
        graph_context=graph["case_contexts"][2], source=benchmark._source(root, case), lane_id=lane,
        case_root=graph_case_directory(tmp_path, case["case_id"], lane), spec=spec, llm_factory=create_llm_client)
    assert output["answer"] == ("UNAVAILABLE" if no_text else case["expected_answer"])
    assert len(calls) == 12
    assert [row["role"] for row in receipt["model_calls"]] == list(GRAPH_MODEL_ROLES)
    assert all(row["actual_model"] is None and row["cost_usd"] is None and row["actual_provider"] == "codex" for row in receipt["model_calls"])
    assert receipt["schema_version"] == "research_full_graph_case/v2"
    assert receipt["checkpoint_run_identity"]["provider_reasoning_settings"]["max_output_chars"] == 65536
    assert len(receipt["decision_packet_refs"]) == 3
