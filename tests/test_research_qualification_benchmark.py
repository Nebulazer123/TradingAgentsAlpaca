"""Source-verification and paired-selection benchmark contracts."""

from __future__ import annotations

import hashlib
import json
import stat
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.research import qualification_benchmark
from tradingagents.research.qualification_benchmark import LANE_ORDER, OPENROUTER_PROMPT_SHA256, ResearchQualificationBenchmarkError, _adapter_input, build_research_qualification_registration, execute_registered_openrouter_benchmark, run_registered_research_benchmark


def _specs():
    specs = {}
    for base in LANE_ORDER:
        for lane_id in (base,) if base == "deterministic_sec_xbrl" else (base, f"{base}_no_text"):
            model_lane = base in {"openrouter_source_bound", "tradingagents_full_graph", "different_model_reviewer"}
            specs[lane_id] = {
                "provider": "openrouter" if model_lane else "none",
                "model": ("reviewer-model" if base == "different_model_reviewer" else "registered-model") if model_lane else "none",
                "revision": "fixture-v1",
                "route": "synthetic-source-adapter",
                "prompt_sha256": OPENROUTER_PROMPT_SHA256 if base == "openrouter_source_bound" else hashlib.sha256(lane_id.encode()).hexdigest(),
                "input_price_per_million_usd": "1" if model_lane else "0",
                "output_price_per_million_usd": "2" if model_lane else "0",
            }
    return specs


def _fixture(tmp_path: Path, *, wrong_expected: int = 0):
    root = tmp_path / "artifacts"
    root.mkdir()
    media = ("text", "table", "pdf_image", "repository_document", "tool_output")
    kinds = (("filing_document_page", 500), ("temporal_restatement_contradiction_cutoff_question", 300), ("workflow_grounded_case", 400), ("injection_case", 200))
    chunks, rows, offset, serial = [], [], 0, 0
    for kind, count in kinds:
        for index in range(count):
            token, actual = f"unique{serial:04d}", f"answer-{serial:04d}"
            raw = json.dumps({"facts": {"answer": actual}, "search_token": token}, separators=(",", ":")).encode()
            chunks.append(raw)
            rows.append((kind, index, serial, token, actual, offset, offset + len(raw)))
            offset += len(raw)
            serial += 1
    corpus = b"".join(chunks)
    (root / "corpus.jsonl").write_bytes(corpus)
    corpus_sha = hashlib.sha256(corpus).hexdigest()
    cases = []
    for kind, index, serial, token, actual, start, end in rows:
        expected = "wrong" if 2 <= serial < 2 + wrong_expected else actual
        query = json.dumps({"fts_query": token, "json_path": ["facts", "answer"]}, sort_keys=True, separators=(",", ":"))
        cases.append(
            {
                "case_id": f"case-{serial:04d}",
                "variant_id": f"variant-{kind}-{serial:04d}",
                "case_kind": kind,
                "medium": media[index % 5] if kind == "injection_case" else media[serial % 5],
                "severity": "high" if index == 0 else "critical",
                "ambiguous": index == 1,
                "artifact_id": "retained-artifact-corpus",
                "artifact_path": "corpus.jsonl",
                "artifact_sha256": corpus_sha,
                "byte_start": start,
                "byte_end": end,
                "adapter_query": query,
                "expected_answer": expected,
                "expected_answer_sha256": hashlib.sha256(expected.encode()).hexdigest(),
            }
        )
    registration = build_research_qualification_registration(cases, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER}, lane_specs=_specs())
    return root, cases, registration


def _source(root, case):
    return (root / case["artifact_path"]).read_bytes()[case["byte_start"] : case["byte_end"]]


def _output(case, answer, lane_id, root):
    safe, _ = _adapter_input(case, lane_id, _source(root, case))
    return {"case_id": case["case_id"], "answer": answer, "source_artifact_id": case["artifact_id"], "byte_start": case["byte_start"], "byte_end": case["byte_end"], "input_sha256": safe["input_sha256"], "pair_id": safe["pair_id"]}


def _lane(lane_id, cases, root, *, cost="0", model="registered-model", wrong=0):
    selected = [c for c in cases if c["ambiguous"]] if lane_id.removesuffix("_no_text") == "different_model_reviewer" else cases
    model_lane = lane_id.removesuffix("_no_text") in {"openrouter_source_bound", "tradingagents_full_graph", "different_model_reviewer"}
    wrong_ids = {c["case_id"] for c in [r for r in selected if r["severity"] != "high"][:wrong]}
    outputs = []
    for case in selected:
        actual = json.loads(_source(root, case))["facts"]["answer"]
        answer = "definitely-wrong" if case["case_id"] in wrong_ids else (case["expected_answer"] if model_lane else actual)
        outputs.append(_output(case, answer, lane_id, root))
    provider = "openrouter" if model_lane else "none"
    selected_model = model if model_lane else "none"
    input_tokens = int(Decimal(cost) * Decimal(1_000_000)) if model_lane else 0
    return {
        "lane_id": lane_id,
        "requested_provider": provider,
        "requested_model": selected_model,
        "requested_revision": "fixture-v1",
        "actual_provider": provider,
        "actual_model": selected_model,
        "actual_revision": "fixture-v1",
        "route": "synthetic-source-adapter",
        "prompt_sha256": _specs()[lane_id]["prompt_sha256"],
        "fallback_used": False,
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "latency_ms": 1,
        "cost_usd": cost,
        "privacy_mode": "synthetic_local",
        "outcome_ids": [f"outcome-{lane_id}"],
        "checkpoint_id": "checkpoint-fixture-v1",
        "case_outputs": outputs,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _adapter(outputs, seen=None):
    by_id = {row["case_id"]: row for row in outputs}

    def invoke(case, raw):
        if seen is not None:
            seen.append((dict(case), raw))
        return by_id[case["case_id"]]

    return invoke


def test_runner_executes_distinct_sec_extraction_and_cohort_fts5_routes(tmp_path):
    root, cases, registration = _fixture(tmp_path)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    metadata = _lane("metadata_fts5_bm25", cases, root)
    twin = _lane("metadata_fts5_bm25_no_text", cases, root)
    receipt = run_registered_research_benchmark(registration=registration, lane_results=[deterministic, metadata, twin], artifact_root=root, lane_adapters={twin["lane_id"]: _adapter(twin["case_outputs"])})
    assert receipt["selected_lane"] == "deterministic_sec_xbrl"
    assert all(row["critical_field_accuracy"] == "1" for row in receipt["lane_results"])
    forged = json.loads(json.dumps(deterministic))
    forged["case_outputs"][0]["answer"] = "forged"
    with pytest.raises(ResearchQualificationBenchmarkError, match="source-bound"):
        run_registered_research_benchmark(registration=registration, lane_results=[forged], artifact_root=root)


def test_failed_deterministic_prerequisite_calls_no_adapters_regardless_order(tmp_path):
    root, cases, registration = _fixture(tmp_path, wrong_expected=8)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    model = _lane("openrouter_source_bound", cases, root)
    twin = _lane("openrouter_source_bound_no_text", cases, root)
    calls = []
    with pytest.raises(ResearchQualificationBenchmarkError, match="prerequisites"):
        run_registered_research_benchmark(registration=registration, lane_results=[model, twin, deterministic], artifact_root=root, lane_adapters={model["lane_id"]: _adapter(model["case_outputs"], calls), twin["lane_id"]: _adapter(twin["case_outputs"], calls)})
    assert calls == []


def test_adapter_projection_hides_gold_and_no_text_receives_no_source(tmp_path):
    root, cases, registration = _fixture(tmp_path, wrong_expected=7)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    model = _lane("openrouter_source_bound", cases, root)
    twin = _lane("openrouter_source_bound_no_text", cases, root, wrong=20)
    seen_source, seen_twin = [], []
    run_registered_research_benchmark(registration=registration, lane_results=[deterministic, model, twin], artifact_root=root, lane_adapters={model["lane_id"]: _adapter(model["case_outputs"], seen_source), twin["lane_id"]: _adapter(twin["case_outputs"], seen_twin)})
    assert all("expected_answer" not in case and "expected_answer_sha256" not in case and "severity" not in case for case, _ in seen_source + seen_twin)
    assert all(raw for _, raw in seen_source) and all(raw == b"" for _, raw in seen_twin)
    assert seen_source[0][0]["pair_id"] == seen_twin[0][0]["pair_id"] and seen_source[0][0]["input_sha256"] != seen_twin[0][0]["input_sha256"]


def test_registration_rejects_duplicate_source_pages_and_case_units(tmp_path):
    _root, cases, _registration = _fixture(tmp_path)
    inflated = json.loads(json.dumps(cases))
    for case in inflated[:500]:
        case["byte_start"], case["byte_end"] = inflated[0]["byte_start"], inflated[0]["byte_end"]
        case["artifact_id"] = f"retained-artifact-alias-{case['case_id']}"
        case["adapter_query"] = json.dumps({"fts_query": f"fake{case['case_id']}", "json_path": ["facts", "answer"]}, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ResearchQualificationBenchmarkError, match="distinct retained source pages"):
        build_research_qualification_registration(inflated, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER}, lane_specs=_specs())
    duplicate = json.loads(json.dumps(cases))
    duplicate[1]["byte_start"], duplicate[1]["byte_end"], duplicate[1]["adapter_query"] = duplicate[0]["byte_start"], duplicate[0]["byte_end"], duplicate[0]["adapter_query"]
    duplicate[1]["artifact_id"] = "retained-artifact-alias-whitespace"
    duplicate[1]["adapter_query"] = "   " + duplicate[1]["adapter_query"]
    with pytest.raises(ResearchQualificationBenchmarkError, match="duplicate case content/query"):
        build_research_qualification_registration(duplicate, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER}, lane_specs=_specs())


def test_reviewer_gain_uses_paired_full_cohort_denominator(tmp_path):
    root, cases, registration = _fixture(tmp_path, wrong_expected=7)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    model = _lane("openrouter_source_bound", cases, root)
    ambiguous_ids = {case["case_id"] for case in cases if case["ambiguous"]}
    for output in model["case_outputs"]:
        if output["case_id"] in ambiguous_ids:
            output["answer"] = "definitely-wrong"
    model_twin = _lane("openrouter_source_bound_no_text", cases, root, wrong=30)
    reviewer = _lane("different_model_reviewer", cases, root, model="reviewer-model")
    reviewer_twin = _lane("different_model_reviewer_no_text", cases, root, model="reviewer-model", wrong=1)
    lanes = [deterministic, model, model_twin, reviewer, reviewer_twin]
    receipt = run_registered_research_benchmark(
        registration=registration,
        lane_results=lanes,
        artifact_root=root,
        lane_adapters={lane["lane_id"]: _adapter(lane["case_outputs"]) for lane in lanes[1:]},
    )
    assert receipt["selected_lane"] == "openrouter_source_bound"
    assert "different_model_reviewer" not in receipt["retained_improving_lanes"]
    reviewer_result = next(row for row in receipt["lane_results"] if row["lane_id"] == "different_model_reviewer")
    reviewer_twin_result = next(row for row in receipt["lane_results"] if row["lane_id"] == "different_model_reviewer_no_text")
    assert reviewer_result["critical_field_accuracy"] == "1"
    assert Decimal(reviewer_twin_result["critical_field_accuracy"]) == Decimal(1399) / Decimal(1400)


def test_cost_budget_distinct_reviewer_and_injection_media_policies(tmp_path):
    root, cases, registration = _fixture(tmp_path, wrong_expected=7)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    model = _lane("openrouter_source_bound", cases, root, cost="1000000")
    twin = _lane("openrouter_source_bound_no_text", cases, root, wrong=30)
    adapters = {model["lane_id"]: _adapter(model["case_outputs"]), twin["lane_id"]: _adapter(twin["case_outputs"])}
    receipt = run_registered_research_benchmark(registration=registration, lane_results=[deterministic, model, twin], artifact_root=root, lane_adapters=adapters)
    assert receipt["selected_lane"] == "deterministic_sec_xbrl"
    model["cost_usd"] = "1"
    model["input_tokens"] = 1_000_000
    receipt = run_registered_research_benchmark(registration=registration, lane_results=[deterministic, model, twin], artifact_root=root, lane_adapters=adapters)
    assert receipt["selected_lane"] == "openrouter_source_bound"
    reviewer = _lane("different_model_reviewer", cases, root, model="registered-model")
    reviewer_twin = _lane("different_model_reviewer_no_text", cases, root, model="registered-model")
    adapters.update({reviewer["lane_id"]: _adapter(reviewer["case_outputs"]), reviewer_twin["lane_id"]: _adapter(reviewer_twin["case_outputs"])})
    same_specs = _specs()
    same_specs["different_model_reviewer"]["model"] = "registered-model"
    same_specs["different_model_reviewer_no_text"]["model"] = "registered-model"
    same_registration = build_research_qualification_registration(cases, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER}, lane_specs=same_specs)
    with pytest.raises(ResearchQualificationBenchmarkError, match="distinct model"):
        run_registered_research_benchmark(registration=same_registration, lane_results=[deterministic, model, twin, reviewer, reviewer_twin], artifact_root=root, lane_adapters=adapters)
    uncovered = json.loads(json.dumps(cases))
    for case in uncovered:
        if case["case_kind"] == "injection_case":
            case["medium"] = "text"
    with pytest.raises(ResearchQualificationBenchmarkError, match="injection cases"):
        build_research_qualification_registration(uncovered, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER}, lane_specs=_specs())


def test_retained_bytes_tamper_and_symlink_are_rejected(tmp_path):
    root, cases, registration = _fixture(tmp_path)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    corpus = root / "corpus.jsonl"
    original = corpus.read_bytes()
    corpus.write_bytes(b"tampered" + original)
    with pytest.raises(ResearchQualificationBenchmarkError, match="digest mismatch"):
        run_registered_research_benchmark(registration=registration, lane_results=[deterministic], artifact_root=root)
    corpus.unlink()
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(original)
    corpus.symlink_to(outside)
    with pytest.raises(ResearchQualificationBenchmarkError, match="escapes root"):
        run_registered_research_benchmark(registration=registration, lane_results=[deterministic], artifact_root=root)


def test_bm25_miss_records_losing_lane_and_retains_baseline(tmp_path):
    root, cases, _registration = _fixture(tmp_path)
    missed = json.loads(json.dumps(cases))
    query = json.loads(missed[0]["adapter_query"])
    query["fts_query"] = "absenttoken"
    missed[0]["adapter_query"] = json.dumps(query, sort_keys=True, separators=(",", ":"))
    registration = build_research_qualification_registration(missed, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER}, lane_specs=_specs())
    deterministic = _lane("deterministic_sec_xbrl", missed, root)
    metadata = _lane("metadata_fts5_bm25", missed, root)
    metadata["case_outputs"][0]["answer"] = None
    twin = _lane("metadata_fts5_bm25_no_text", missed, root)
    receipt = run_registered_research_benchmark(registration=registration, lane_results=[deterministic, metadata, twin], artifact_root=root, lane_adapters={twin["lane_id"]: _adapter(twin["case_outputs"])})
    assert receipt["selected_lane"] == "deterministic_sec_xbrl"
    metadata_result = next(row for row in receipt["lane_results"] if row["lane_id"] == "metadata_fts5_bm25")
    assert metadata_result["qualified"] is False
    assert metadata_result["case_outputs"][0]["answer_sha256"] is None


def test_no_text_twin_cannot_change_the_registered_model(tmp_path):
    _root, cases, _registration = _fixture(tmp_path)
    specs = _specs()
    specs["openrouter_source_bound_no_text"]["model"] = "different-model"
    with pytest.raises(ResearchQualificationBenchmarkError, match="paired lane identity"):
        build_research_qualification_registration(
            cases, minimum_accuracy_gain="0.001",
            lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER},
            lane_specs=specs,
        )


def test_openrouter_execution_uses_production_factory_telemetry_and_safe_pair(
    tmp_path,
    monkeypatch,
):
    root, cases, registration = _fixture(tmp_path, wrong_expected=7)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    calls = []

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(request):
        request_payload = json.loads(request.content)
        prompt = request_payload["messages"][0]["content"]
        payload = json.loads(prompt)
        calls.append(payload)
        source = payload["retained_source"]
        answer = json.loads(source)["facts"]["answer"] if source else "no-source-answer"
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(calls)}",
                "object": "chat.completion",
                "created": 1,
                "model": "registered-model",
                "provider": "openrouter",
                "route": "synthetic-source-adapter",
                "fallback_used": False,
                "system_fingerprint": "fixture-v1",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": answer},
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    transport = httpx.MockTransport(handler)
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return create_llm_client(
            **kwargs,
            base_url="https://benchmark.test/v1",
            http_client=httpx.Client(transport=transport),
        )

    receipt = execute_registered_openrouter_benchmark(registration=registration, deterministic_result=deterministic, artifact_root=root, llm_factory=factory)
    assert factory_calls == [{"provider": "openrouter", "model": "registered-model"}] * 2
    assert len(calls) == 2800
    assert all("expected_answer" not in call["case"] and "severity" not in call["case"] for call in calls)
    assert all(call["retained_source"] for call in calls[:1400])
    assert all(call["retained_source"] == "" for call in calls[1400:])
    assert [row["lane_id"] for row in receipt["lane_results"]] == [
        "deterministic_sec_xbrl",
        "metadata_fts5_bm25",
        "metadata_fts5_bm25_no_text",
        "openrouter_source_bound",
        "openrouter_source_bound_no_text",
    ]
    model = next(row for row in receipt["lane_results"] if row["lane_id"] == "openrouter_source_bound")
    assert model["input_tokens"] == 2800 and model["output_tokens"] == 1400 and model["cost_usd"] == "0.0056"


def test_openrouter_client_does_not_invent_missing_routing_telemetry(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(_request):
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "object": "chat.completion",
                "created": 1,
                "model": "registered-model",
                "system_fingerprint": "fixture-v1",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "answer"},
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    client = create_llm_client(
        provider="openrouter",
        model="registered-model",
        base_url="https://benchmark.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = client.get_llm().invoke("source-free test")
    assert response.response_metadata["model_name"] == "registered-model"
    assert "provider" not in response.response_metadata
    assert "route" not in response.response_metadata
    assert "fallback_used" not in response.response_metadata


def test_openrouter_executes_retained_fts_before_any_model_factory(tmp_path, monkeypatch):
    root, cases, registration = _fixture(tmp_path, wrong_expected=7)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    original_bm25 = qualification_benchmark._bm25_answers
    retrieval_calls = []

    def tracked_bm25(*args, **kwargs):
        retrieval_calls.append("fts5_bm25")
        return original_bm25(*args, **kwargs)

    monkeypatch.setattr(qualification_benchmark, "_bm25_answers", tracked_bm25)
    factory_calls = []

    def factory(**kwargs):
        assert retrieval_calls
        factory_calls.append(kwargs)
        raise RuntimeError("stop after ordering check")

    with pytest.raises(RuntimeError, match="ordering check"):
        execute_registered_openrouter_benchmark(
            registration=registration,
            deterministic_result=deterministic,
            artifact_root=root,
            llm_factory=factory,
        )
    assert retrieval_calls == ["fts5_bm25", "fts5_bm25"]
    assert factory_calls == [{"provider": "openrouter", "model": "registered-model"}]


def test_perfect_local_score_cannot_justify_any_model_calls(tmp_path):
    root, cases, registration = _fixture(tmp_path)
    calls = []
    receipt = execute_registered_openrouter_benchmark(
        registration=registration,
        deterministic_result=_lane("deterministic_sec_xbrl", cases, root),
        artifact_root=root,
        llm_factory=lambda **kwargs: calls.append(kwargs),
    )
    assert calls == []
    assert receipt["selected_lane"] == "deterministic_sec_xbrl"
    assert len(receipt["lane_results"]) == 1
    assert receipt["openrouter_execution"] == {
        "status": "not_run",
        "reason": "registered_accuracy_gain_unattainable",
    }
    material = {**receipt, "receipt_id": None, "receipt_sha256": None}
    digest = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    assert receipt["receipt_sha256"] == digest


def test_openrouter_factory_is_not_constructed_before_deterministic_admission(tmp_path):
    root, cases, registration = _fixture(tmp_path, wrong_expected=8)
    deterministic = _lane("deterministic_sec_xbrl", cases, root)
    factory_calls = []
    with pytest.raises(ResearchQualificationBenchmarkError, match="prerequisites"):
        execute_registered_openrouter_benchmark(registration=registration, deterministic_result=deterministic, artifact_root=root, llm_factory=lambda **kwargs: factory_calls.append(kwargs))
    assert factory_calls == []


def test_cli_writes_owner_only_verified_receipt(tmp_path):
    root, cases, registration = _fixture(tmp_path)
    registration_path, lanes_path, output = tmp_path / "registration.json", tmp_path / "lanes.json", tmp_path / "receipt.json"
    registration_path.write_text(json.dumps(registration))
    lanes_path.write_text(json.dumps([_lane("deterministic_sec_xbrl", cases, root)]))
    result = CliRunner().invoke(app, ["research", "research-stack-benchmark", "--registration-path", str(registration_path), "--lane-results-path", str(lanes_path), "--artifact-root", str(root), "--output-path", str(output), "--json-output"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["selected_lane"] == "deterministic_sec_xbrl"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
