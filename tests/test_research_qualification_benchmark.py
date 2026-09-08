"""Source-verification and paired-selection benchmark contracts."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.research.qualification_benchmark import (
    LANE_ORDER,
    ResearchQualificationBenchmarkError,
    build_research_qualification_registration,
    run_registered_research_benchmark,
)


def _fixture(tmp_path: Path, *, wrong_expected: int = 0):
    root = tmp_path / "artifacts"
    root.mkdir()
    xbrl = json.dumps({"facts": {"revenue": "42"}}, separators=(",", ":")).encode()
    text = b"registered answer source document"
    (root / "xbrl.json").write_bytes(xbrl)
    (root / "document.txt").write_bytes(text)
    media = ("text", "table", "pdf_image", "repository_document", "tool_output")
    kinds = (("filing_document_page", 500), ("temporal_restatement_contradiction_cutoff_question", 300), ("workflow_grounded_case", 400), ("injection_case", 200))
    cases, serial = [], 0
    for kind, count in kinds:
        for index in range(count):
            use_xbrl = serial % 2 == 0
            raw = xbrl if use_xbrl else text
            actual = "42" if use_xbrl else text.decode()
            expected = "wrong" if 2 <= serial < 2 + wrong_expected else actual
            cases.append(
                {
                    "case_id": f"case-{serial:04d}",
                    "case_kind": kind,
                    "medium": media[index % len(media)] if kind == "injection_case" else media[serial % len(media)],
                    "severity": "high" if index == 0 else "critical",
                    "ambiguous": index == 1,
                    "artifact_id": f"retained-artifact-{'xbrl' if use_xbrl else 'text'}",
                    "artifact_path": "xbrl.json" if use_xbrl else "document.txt",
                    "artifact_sha256": hashlib.sha256(raw).hexdigest(),
                    "byte_start": 0,
                    "byte_end": len(raw),
                    "adapter_kind": "sec_xbrl_json_path" if use_xbrl else "fts5_bm25",
                    "adapter_query": '["facts","revenue"]' if use_xbrl else "registered",
                    "expected_answer": expected,
                    "expected_answer_sha256": hashlib.sha256(expected.encode()).hexdigest(),
                }
            )
            serial += 1
    budgets = {lane: "10" for lane in LANE_ORDER}
    registration = build_research_qualification_registration(cases, minimum_accuracy_gain="0.001", lane_cost_budgets_usd=budgets)
    return root, cases, registration


def _answer(case):
    return "42" if case["adapter_kind"] == "sec_xbrl_json_path" else "registered answer source document"


def _output(case, answer):
    return {"case_id": case["case_id"], "answer": answer, "source_artifact_id": case["artifact_id"], "byte_start": case["byte_start"], "byte_end": case["byte_end"]}


def _lane(lane_id, cases, *, cost="0", model="registered-model", wrong=0):
    selected = [case for case in cases if case["ambiguous"]] if lane_id.removesuffix("_no_text") == "different_model_reviewer" else cases
    model_lane = lane_id.removesuffix("_no_text") in {"openrouter_source_bound", "tradingagents_full_graph", "different_model_reviewer"}
    wrong_ids = {case["case_id"] for case in [row for row in selected if row["severity"] != "high"][:wrong]}
    return {
        "lane_id": lane_id,
        "requested_provider": "openrouter" if model_lane else "none",
        "requested_model": model if model_lane else "none",
        "requested_revision": "fixture-v1",
        "actual_provider": "openrouter" if model_lane else "none",
        "actual_model": model if model_lane else "none",
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
        "case_outputs": [_output(case, "definitely-wrong" if case["case_id"] in wrong_ids else (case["expected_answer"] if model_lane else _answer(case))) for case in selected],
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _adapter(outputs):
    by_id = {row["case_id"]: row for row in outputs}
    return lambda case, _raw: by_id[case["case_id"]]


def test_runner_executes_retained_sec_and_fts5_and_computes_scores(tmp_path):
    root, cases, registration = _fixture(tmp_path)
    deterministic = _lane("deterministic_sec_xbrl", cases)
    receipt = run_registered_research_benchmark(registration=registration, lane_results=[deterministic], artifact_root=root)
    assert receipt["selected_lane"] == "deterministic_sec_xbrl"
    assert receipt["lane_results"][0]["critical_field_accuracy"] == "1"
    assert receipt["analysis_only"] is True and receipt["can_submit_orders"] is False
    forged = json.loads(json.dumps(deterministic))
    forged["case_outputs"][0]["answer"] = "forged"
    with pytest.raises(ResearchQualificationBenchmarkError, match="source-bound"):
        run_registered_research_benchmark(registration=registration, lane_results=[forged], artifact_root=root)
    claimed = json.loads(json.dumps(deterministic))
    claimed["case_results"] = [{"case_id": case["case_id"], "critical_fields_correct": True} for case in cases]
    del claimed["case_outputs"]
    with pytest.raises(ResearchQualificationBenchmarkError, match="fields"):
        run_registered_research_benchmark(registration=registration, lane_results=[claimed], artifact_root=root)
    (root / "xbrl.json").write_text("tampered")
    with pytest.raises(ResearchQualificationBenchmarkError, match="digest mismatch"):
        run_registered_research_benchmark(registration=registration, lane_results=[deterministic], artifact_root=root)
    outside = tmp_path / "outside.json"
    outside.write_text('{"facts":{"revenue":"42"}}')
    (root / "xbrl.json").unlink()
    (root / "xbrl.json").symlink_to(outside)
    with pytest.raises(ResearchQualificationBenchmarkError, match="escapes root"):
        run_registered_research_benchmark(
            registration=registration,
            lane_results=[deterministic],
            artifact_root=root,
        )


def test_retention_requires_registered_gain_twin_and_budget(tmp_path):
    root, cases, registration = _fixture(tmp_path, wrong_expected=7)
    deterministic = _lane("deterministic_sec_xbrl", cases)
    model = _lane("openrouter_source_bound", cases, cost="1000000")
    twin = _lane("openrouter_source_bound_no_text", cases, wrong=30)
    adapters = {model["lane_id"]: _adapter(model["case_outputs"]), twin["lane_id"]: _adapter(twin["case_outputs"])}
    receipt = run_registered_research_benchmark(registration=registration, lane_results=[deterministic, model, twin], artifact_root=root, lane_adapters=adapters)
    assert receipt["selected_lane"] == "deterministic_sec_xbrl"
    within_budget = json.loads(json.dumps(model))
    within_budget["cost_usd"] = "1"
    adapters[within_budget["lane_id"]] = _adapter(within_budget["case_outputs"])
    receipt = run_registered_research_benchmark(registration=registration, lane_results=[deterministic, within_budget, twin], artifact_root=root, lane_adapters=adapters)
    assert receipt["selected_lane"] == "openrouter_source_bound"


def test_reviewer_is_distinct_and_compared_on_paired_ambiguous_cases(tmp_path):
    root, cases, registration = _fixture(tmp_path, wrong_expected=7)
    deterministic = _lane("deterministic_sec_xbrl", cases)
    model = _lane("openrouter_source_bound", cases)
    ambiguous_ids = {case["case_id"] for case in cases if case["ambiguous"]}
    for output in model["case_outputs"]:
        if output["case_id"] in ambiguous_ids:
            output["answer"] = "definitely-wrong"
    model_twin = _lane("openrouter_source_bound_no_text", cases, wrong=20)
    reviewer = _lane("different_model_reviewer", cases, model="reviewer-model")
    reviewer_twin = _lane("different_model_reviewer_no_text", cases, model="reviewer-model", wrong=4)
    lanes = [deterministic, model, model_twin, reviewer, reviewer_twin]
    adapters = {lane["lane_id"]: _adapter(lane["case_outputs"]) for lane in lanes[1:]}
    receipt = run_registered_research_benchmark(registration=registration, lane_results=lanes, artifact_root=root, lane_adapters=adapters)
    assert receipt["selected_lane"] == "different_model_reviewer"
    same = json.loads(json.dumps(reviewer))
    same["requested_model"] = same["actual_model"] = "registered-model"
    adapters[same["lane_id"]] = _adapter(same["case_outputs"])
    with pytest.raises(ResearchQualificationBenchmarkError, match="distinct model"):
        run_registered_research_benchmark(registration=registration, lane_results=[deterministic, model, model_twin, same, reviewer_twin], artifact_root=root, lane_adapters=adapters)


def test_injection_media_must_be_covered_inside_injection_subset(tmp_path):
    root, cases, _registration = _fixture(tmp_path)
    for case in cases:
        if case["case_kind"] == "injection_case":
            case["medium"] = "text"
    with pytest.raises(ResearchQualificationBenchmarkError, match="injection cases"):
        build_research_qualification_registration(cases, minimum_accuracy_gain="0.001", lane_cost_budgets_usd={lane: "10" for lane in LANE_ORDER})
    assert root.exists()


def test_cli_writes_owner_only_verified_receipt(tmp_path):
    root, cases, registration = _fixture(tmp_path)
    registration_path, lanes_path, output = tmp_path / "registration.json", tmp_path / "lanes.json", tmp_path / "receipt.json"
    registration_path.write_text(json.dumps(registration))
    lanes_path.write_text(json.dumps([_lane("deterministic_sec_xbrl", cases)]))
    result = CliRunner().invoke(app, ["research", "research-stack-benchmark", "--registration-path", str(registration_path), "--lane-results-path", str(lanes_path), "--artifact-root", str(root), "--output-path", str(output), "--json-output"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["selected_lane"] == "deterministic_sec_xbrl"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
