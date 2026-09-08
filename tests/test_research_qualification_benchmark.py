"""Source-verification and paired-selection benchmark contracts."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.research.qualification_benchmark import LANE_ORDER, ResearchQualificationBenchmarkError, _adapter_input, build_research_qualification_registration, run_registered_research_benchmark


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
    registration = build_research_qualification_registration(cases, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER})
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
    return {
        "lane_id": lane_id,
        "requested_provider": provider,
        "requested_model": selected_model,
        "requested_revision": "fixture-v1",
        "actual_provider": provider,
        "actual_model": selected_model,
        "actual_revision": "fixture-v1",
        "route": "synthetic-source-adapter",
        "prompt_sha256": hashlib.sha256(lane_id.encode()).hexdigest(),
        "fallback_used": False,
        "input_tokens": 0,
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
        case["adapter_query"] = json.dumps({"fts_query": f"fake{case['case_id']}", "json_path": ["facts", "answer"]}, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ResearchQualificationBenchmarkError, match="distinct retained source pages"):
        build_research_qualification_registration(inflated, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER})
    duplicate = json.loads(json.dumps(cases))
    duplicate[1]["byte_start"], duplicate[1]["byte_end"], duplicate[1]["adapter_query"] = duplicate[0]["byte_start"], duplicate[0]["byte_end"], duplicate[0]["adapter_query"]
    with pytest.raises(ResearchQualificationBenchmarkError, match="duplicate case content/query"):
        build_research_qualification_registration(duplicate, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER})


def test_cli_writes_owner_only_verified_receipt(tmp_path):
    root, cases, registration = _fixture(tmp_path)
    registration_path, lanes_path, output = tmp_path / "registration.json", tmp_path / "lanes.json", tmp_path / "receipt.json"
    registration_path.write_text(json.dumps(registration))
    lanes_path.write_text(json.dumps([_lane("deterministic_sec_xbrl", cases, root)]))
    result = CliRunner().invoke(app, ["research", "research-stack-benchmark", "--registration-path", str(registration_path), "--lane-results-path", str(lanes_path), "--artifact-root", str(root), "--output-path", str(output), "--json-output"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["selected_lane"] == "deterministic_sec_xbrl"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
