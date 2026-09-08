"""Synthetic contracts for the registered research-stack benchmark."""

from __future__ import annotations

import hashlib
import json
import stat

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.research.qualification_benchmark import (
    ResearchQualificationBenchmarkError,
    build_research_qualification_registration,
    run_registered_research_benchmark,
)


def _cases():
    counts = {
        "filing_document_page": 500,
        "temporal_restatement_contradiction_cutoff_question": 300,
        "workflow_grounded_case": 400,
        "injection_case": 200,
    }
    media = ("text", "table", "pdf_image", "repository_document", "tool_output")
    rows = []
    serial = 0
    for kind, count in counts.items():
        for index in range(count):
            rows.append(
                {
                    "case_id": f"case-{serial:04d}",
                    "case_kind": kind,
                    "medium": media[serial % len(media)],
                    "severity": "high" if index == 0 else "critical",
                    "ambiguous": index == 1,
                    "source_spans": [f"fixture://{kind}/{index}#value"],
                }
            )
            serial += 1
    return rows


def _lane(lane_id, cases, *, wrong=0, cost="0"):
    selected = cases
    if lane_id.removesuffix("_no_text") == "different_model_reviewer":
        selected = [case for case in cases if case["ambiguous"]]
    return {
        "lane_id": lane_id,
        "requested_provider": "none" if lane_id.startswith(("deterministic", "metadata")) else "openrouter",
        "requested_model": "none" if lane_id.startswith(("deterministic", "metadata")) else "registered-model",
        "requested_revision": "fixture-v1",
        "actual_provider": "none" if lane_id.startswith(("deterministic", "metadata")) else "openrouter",
        "actual_model": "none" if lane_id.startswith(("deterministic", "metadata")) else "registered-model",
        "actual_revision": "fixture-v1",
        "route": "synthetic-test-double",
        "prompt_sha256": hashlib.sha256(lane_id.encode()).hexdigest(),
        "fallback_used": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 1,
        "cost_usd": cost,
        "privacy_mode": "synthetic_local",
        "source_spans": ["fixture://registered-cohort"],
        "outcome_ids": [f"outcome-{lane_id}"],
        "checkpoint_id": "checkpoint-fixture-v1",
        "case_results": [
            {
                "case_id": case["case_id"],
                "critical_fields_correct": index >= wrong,
                "high_severity_correct": True,
                "source_contract_preserved": True,
                "secret_disclosed": False,
                "authority_changed": False,
            }
            for index, case in enumerate(selected)
        ],
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def test_registered_benchmark_selects_simplest_qualified_lane_and_binds_receipt():
    cases = _cases()
    registration = build_research_qualification_registration(cases)
    lane_results = [
        _lane("deterministic_sec_xbrl", cases, wrong=7),  # 99.5%, exactly green
        _lane("metadata_fts5_bm25", cases, wrong=0),
        _lane("metadata_fts5_bm25_no_text", cases, wrong=20),
        _lane("openrouter_source_bound", cases, wrong=0, cost="1.25"),
        _lane("openrouter_source_bound_no_text", cases, wrong=30),
    ]

    receipt = run_registered_research_benchmark(
        registration=registration,
        lane_results=lane_results,
    )

    assert receipt["selected_lane"] == "metadata_fts5_bm25"
    assert receipt["retained_improving_lanes"] == [
        "deterministic_sec_xbrl",
        "metadata_fts5_bm25",
    ]
    assert receipt["analysis_only"] is True
    assert receipt["execution_authority"] == "none"
    assert receipt["can_submit_orders"] is False
    assert receipt["receipt_id"].startswith("research-qualification-benchmark-")
    assert receipt["lane_results"][0]["critical_field_accuracy"] == "0.995"


def test_benchmark_fails_closed_for_prerequisite_twin_fallback_and_security():
    cases = _cases()
    registration = build_research_qualification_registration(cases)
    failed = _lane("deterministic_sec_xbrl", cases, wrong=8)
    with pytest.raises(ResearchQualificationBenchmarkError, match="prerequisites"):
        run_registered_research_benchmark(registration=registration, lane_results=[failed])

    model = _lane("openrouter_source_bound", cases)
    with pytest.raises(ResearchQualificationBenchmarkError, match="no-text twin"):
        run_registered_research_benchmark(
            registration=registration,
            lane_results=[_lane("deterministic_sec_xbrl", cases), model],
        )
    model["fallback_used"] = True
    with pytest.raises(ResearchQualificationBenchmarkError, match="fallback"):
        run_registered_research_benchmark(
            registration=registration,
            lane_results=[_lane("deterministic_sec_xbrl", cases), model],
        )

    unsafe = _lane("deterministic_sec_xbrl", cases)
    unsafe["case_results"][0]["authority_changed"] = True
    with pytest.raises(ResearchQualificationBenchmarkError, match="prerequisites"):
        run_registered_research_benchmark(registration=registration, lane_results=[unsafe])


def test_cli_writes_one_owner_only_synthetic_receipt_without_provider_call(tmp_path):
    cases = _cases()
    registration = build_research_qualification_registration(cases)
    registration_path = tmp_path / "registration.json"
    lanes_path = tmp_path / "lanes.json"
    output_path = tmp_path / "receipt.json"
    registration_path.write_text(json.dumps(registration))
    lanes_path.write_text(json.dumps([_lane("deterministic_sec_xbrl", cases)]))

    result = CliRunner().invoke(
        app,
        [
            "research", "research-stack-benchmark",
            "--registration-path", str(registration_path),
            "--lane-results-path", str(lanes_path),
            "--output-path", str(output_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["selected_lane"] == "deterministic_sec_xbrl"
    assert output_path.exists()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    duplicate = CliRunner().invoke(
        app,
        [
            "research", "research-stack-benchmark",
            "--registration-path", str(registration_path),
            "--lane-results-path", str(lanes_path),
            "--output-path", str(output_path),
        ],
    )
    assert duplicate.exit_code != 0
