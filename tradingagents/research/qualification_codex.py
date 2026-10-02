"""Versioned Codex-subscription benchmark execution, never call permission."""
from __future__ import annotations

import re
import time
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from tradingagents.llm_clients.codex_client import CODEX_MODELS, CODEX_ROUTE, build_codex_application_prompt
from tradingagents.research.qualification_benchmark import (
    AUTHORITY,
    LANE_SPEC_FIELDS,
    OPENROUTER_INSTRUCTION,
    OPENROUTER_PROMPT_SHA256,
    REVIEWER_INSTRUCTION,
    REVIEWER_PROMPT_SHA256,
    ResearchQualificationBenchmarkError,
    _adapter_input,
    _bm25_answers,
    _digest,
    _lane_order,
    _map,
    _metadata_fts5_lane_result,
    _openrouter_prompt,
    _registration,
    _sensitive_outbound_value,
    _source,
    _text,
    build_research_qualification_registration,
    run_registered_research_benchmark,
)

SCHEMA = "research_qualification_registration/v7"
CODEX_SOURCE_LANE = "codex_subscription_source_bound"
CODEX_GRAPH_LANE = "codex_subscription_full_graph"
CODEX_REVIEWER_LANE = "codex_subscription_reviewer"
CODEX_LANE_ORDER = ("deterministic_sec_xbrl", "metadata_fts5_bm25", CODEX_SOURCE_LANE, CODEX_GRAPH_LANE, CODEX_REVIEWER_LANE)
RUNNER_FIELDS = {"runner_contract", "runner_version", "billing_kind", "reasoning_effort", "max_input_bytes", "max_output_chars", "timeout_seconds"}
CODEX_SPEC_FIELDS = LANE_SPEC_FIELDS | RUNNER_FIELDS
CODEX_RESULT_FIELDS = RUNNER_FIELDS | {"returned_provider_identity", "model_identity_source", "provider_output_token_cap_enforced", "cost_status"}


def migrate_codex_subscription_registration(*, previous_registration: object, lane_specs: Mapping) -> dict:
    """New identity, exact unchanged v6 cases/gold; no model or source replay."""
    old = _registration(previous_registration)
    if old["schema_version"] != "research_qualification_registration/v6":
        raise ResearchQualificationBenchmarkError("Codex source-bundle migration requires accepted v6 inputs")
    old_order = _lane_order(old["lane_specs"])
    return build_research_qualification_registration(
        old["cases"], minimum_accuracy_gain=old["comparison_policy"]["minimum_accuracy_gain"],
        lane_cost_budgets_usd={new: old["comparison_policy"]["lane_cost_budgets_usd"][prior] for new, prior in zip(CODEX_LANE_ORDER, old_order, strict=True)},
        lane_specs=lane_specs, schema_version=SCHEMA,
    )


def validate_codex_lane_spec(value: object) -> dict:
    spec = _map(value, CODEX_SPEC_FIELDS, "Codex lane spec")
    if spec["provider"] != "codex" or type(spec["model"]) is not str or spec["model"] not in CODEX_MODELS or spec["revision"] is not None or spec["route"] != CODEX_ROUTE:
        raise ResearchQualificationBenchmarkError("Codex lane provider/model/revision/route differs")
    if spec["runner_contract"] != "codex-exec-chat/v1" or spec["billing_kind"] != "chatgpt_subscription" or type(spec["runner_version"]) is not str or re.fullmatch(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", spec["runner_version"]) is None:
        raise ResearchQualificationBenchmarkError("Codex runner and subscription identity is invalid")
    if type(spec["reasoning_effort"]) is not str or spec["reasoning_effort"] not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
        raise ResearchQualificationBenchmarkError("Codex registered reasoning effort is invalid")
    for key, limit in (("max_input_bytes", 262144), ("max_output_chars", 65536), ("timeout_seconds", 600)):
        if type(spec[key]) is not int or not 1 <= spec[key] <= limit:
            raise ResearchQualificationBenchmarkError("Codex registered bounds are invalid")
    if any(spec[key] is not None for key in ("input_price_per_million_usd", "output_price_per_million_usd")):
        raise ResearchQualificationBenchmarkError("subscription allocation prices must remain unknown")
    if type(spec["prompt_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", spec["prompt_sha256"]) is None:
        raise ResearchQualificationBenchmarkError("registered prompt digest is invalid")
    return spec


def codex_factory_kwargs(spec: Mapping) -> dict:
    registered = validate_codex_lane_spec(spec)
    return {"provider": "codex", "model": registered["model"], "reasoning_effort": registered["reasoning_effort"],
            "max_input_bytes": registered["max_input_bytes"], "max_output_chars": registered["max_output_chars"],
            "timeout": registered["timeout_seconds"], "temperature": 0, "max_retries": 0}


def validate_codex_response(metadata: object, usage: object, spec: Mapping) -> dict:
    """Local request identity is observed; remote serving identity stays unknown."""
    validate_codex_lane_spec(spec)
    if not isinstance(metadata, Mapping) or not isinstance(usage, Mapping):
        raise ResearchQualificationBenchmarkError("Codex response telemetry is unavailable")
    expected = {"provider": "codex", "route": CODEX_ROUTE, "backend_url": CODEX_ROUTE,
                "requested_model": spec["model"], "model_name": spec["model"], "serving_revision": None,
                "runner_contract": spec["runner_contract"], "runner_version": spec["runner_version"],
                "billing_mode": spec["billing_kind"], "reasoning_effort": spec["reasoning_effort"],
                "max_input_bytes": spec["max_input_bytes"], "max_output_chars": spec["max_output_chars"],
                "returned_provider_identity": None, "returned_model_name": None,
                "model_identity_source": "requested_cli_argument_only", "fallback_used": False,
                "provider_output_token_cap_enforced": False, "subscription_cost_usd": None,
                "subscription_cost_status": "unknown_subscription_allocation"}
    if any(key not in metadata or type(metadata[key]) is not type(value) or metadata[key] != value for key, value in expected.items()):
        raise ResearchQualificationBenchmarkError("Codex response identity differs from registration")
    timeout = metadata.get("timeout_seconds")
    if type(timeout) not in {int, float} or timeout != spec["timeout_seconds"]:
        raise ResearchQualificationBenchmarkError("Codex timeout differs from registration")
    counts = [usage.get(key) for key in ("input_tokens", "output_tokens")]
    if any(type(count) is not int or count < 0 for count in counts):
        raise ResearchQualificationBenchmarkError("Codex response usage is invalid")
    observed = metadata.get("subscription_usage")
    if not isinstance(observed, Mapping) or any(type(observed.get(key)) is not int or observed[key] != count for key, count in zip(("input_tokens", "output_tokens"), counts, strict=True)):
        raise ResearchQualificationBenchmarkError("Codex subscription usage differs from returned usage")
    cached = observed.get("cached_input_tokens", 0)
    if type(cached) is not int or not 0 <= cached <= counts[0]:
        raise ResearchQualificationBenchmarkError("Codex cached token usage is invalid")
    outcome = metadata.get("runner_outcome")
    if not isinstance(outcome, Mapping) or set(outcome) != {"thread_id", "item_id"} or any(type(item) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,200}", item) is None for item in outcome.values()):
        raise ResearchQualificationBenchmarkError("Codex returned outcome identity is unavailable")
    identifier = _text(metadata.get("id"), "Codex outcome id")
    if identifier != f"codex:{outcome['thread_id']}:{outcome['item_id']}":
        raise ResearchQualificationBenchmarkError("Codex outcome is not bound to returned runner events")
    return {"actual_provider": "codex", "actual_model": None, "actual_revision": None, "route": CODEX_ROUTE,
            "input_tokens": counts[0], "output_tokens": counts[1], "outcome_id": identifier,
            **codex_result_identity(spec)}


def codex_result_identity(spec: Mapping) -> dict:
    return {**{key: spec[key] for key in RUNNER_FIELDS}, "returned_provider_identity": None,
            "model_identity_source": "requested_cli_argument_only", "provider_output_token_cap_enforced": False,
            "cost_status": "unknown_subscription_allocation"}


def validate_codex_result(lane: Mapping, spec: Mapping) -> None:
    if lane["requested_provider"] != "codex" or lane["actual_provider"] != "codex" or lane["requested_model"] != spec["model"] or lane["requested_revision"] is not None or lane["actual_model"] is not None or lane["actual_revision"] is not None or lane["cost_usd"] is not None or lane["route"] != CODEX_ROUTE:
        raise ResearchQualificationBenchmarkError("Codex result request or unknown serving/cost fields differ")
    expected = codex_result_identity(spec)
    if any(type(lane[key]) is not type(value) or lane[key] != value for key, value in expected.items()):
        raise ResearchQualificationBenchmarkError("Codex result runner/usage identity differs")


def _finish(receipt: dict, execution: dict) -> dict:
    receipt["codex_subscription_execution"] = execution
    receipt["receipt_id"] = receipt["receipt_sha256"] = None
    digest = _digest(receipt)
    receipt.update(receipt_id=f"research-qualification-benchmark-{digest}", receipt_sha256=digest)
    return receipt


def execute_registered_codex_benchmark(*, registration: object, deterministic_result: Mapping, artifact_root: str | Path,
                                      llm_factory=None, execute_reviewer=False, execute_full_graph=False,
                                      full_graph_registration=None, full_graph_run_root=None) -> dict:
    """Explicit executor after local gates; caller must separately hold authority."""
    frozen = _registration(registration)
    from langchain_core.messages import AIMessage, HumanMessage, message_to_dict
    if frozen["schema_version"] != SCHEMA:
        raise ResearchQualificationBenchmarkError("Codex execution requires a new v7 registration")
    if execute_full_graph != (full_graph_registration is not None and full_graph_run_root is not None) or (not execute_full_graph and (full_graph_registration is not None or full_graph_run_root is not None)):
        raise ResearchQualificationBenchmarkError("full-graph execution requires its explicit registration and new run root")
    local = run_registered_research_benchmark(registration=frozen, lane_results=[deterministic_result], artifact_root=artifact_root)
    gain = Decimal(frozen["comparison_policy"]["minimum_accuracy_gain"])
    if Decimal(local["lane_results"][0]["source_accuracy"]) + gain > 1:
        return _finish(local, {"status": "not_run", "reason": "registered_accuracy_gain_unattainable", **AUTHORITY})
    root = Path(artifact_root).expanduser().resolve(strict=True)
    cases = {case["case_id"]: case for case in frozen["cases"]}
    cache = {}
    sources = {cid: _source(root, case, artifact_cache=cache) for cid, case in cases.items()}
    began = time.monotonic_ns()
    answers = _bm25_answers(cases, sources)
    elapsed = max(0, (time.monotonic_ns() - began) // 1_000_000)
    local_rows = [_metadata_fts5_lane_result(lane_id=lane, cases=cases, sources=sources, answers=answers,
                                           spec=frozen["lane_specs"][lane], registration_sha256=frozen["registration_sha256"], latency_ms=elapsed if not lane.endswith("_no_text") else 0)
                  for lane in ("metadata_fts5_bm25", "metadata_fts5_bm25_no_text")]
    local = run_registered_research_benchmark(registration=frozen, lane_results=[deterministic_result, *local_rows], artifact_root=root)
    selected = next(row for row in local["lane_results"] if row["lane_id"] == local["selected_lane"])
    if Decimal(selected["source_accuracy"]) + gain > 1:
        return _finish(local, {"status": "not_run", "reason": "registered_accuracy_gain_unattainable", **AUTHORITY})
    ambiguous = {cid: case for cid, case in cases.items() if case["ambiguous"]}
    lane_ids = [CODEX_SOURCE_LANE, CODEX_SOURCE_LANE + "_no_text"]
    if execute_reviewer and ambiguous:
        if frozen["lane_specs"][CODEX_REVIEWER_LANE]["model"] == frozen["lane_specs"][CODEX_SOURCE_LANE]["model"]:
            raise ResearchQualificationBenchmarkError("reviewer must use a distinct model")
        lane_ids += [CODEX_REVIEWER_LANE, CODEX_REVIEWER_LANE + "_no_text"]
    prompts = {}
    for lane in lane_ids:
        reviewer = lane.startswith(CODEX_REVIEWER_LANE)
        spec = frozen["lane_specs"][lane]
        if spec["prompt_sha256"] != (REVIEWER_PROMPT_SHA256 if reviewer else OPENROUTER_PROMPT_SHA256):
            raise ResearchQualificationBenchmarkError("Codex execution prompt identity is not registered")
        prompts[lane] = {cid: _openrouter_prompt(*_adapter_input(cases[cid], lane, sources[cid]), REVIEWER_INSTRUCTION if reviewer else OPENROUTER_INSTRUCTION)
                         for cid in sorted(ambiguous if reviewer else cases)}
        if any(len(build_codex_application_prompt([HumanMessage(content=prompt)], tools=[], tool_choice=None).encode()) > spec["max_input_bytes"]
               for prompt in prompts[lane].values()):
            raise ResearchQualificationBenchmarkError("registered Codex input byte bound is exceeded before execution")
    from tradingagents.llm_clients.codex_client import codex_runner_version

    installed = codex_runner_version()
    requested_lanes = lane_ids + ([CODEX_GRAPH_LANE, CODEX_GRAPH_LANE + "_no_text"] if execute_full_graph else [])
    if any(frozen["lane_specs"][lane]["runner_version"] != installed for lane in requested_lanes):
        raise ResearchQualificationBenchmarkError("installed Codex runner differs from registration")
    prepared = None
    if execute_full_graph:
        from tradingagents.research.qualification_full_graph import prepare_full_graph_execution
        prepared = prepare_full_graph_execution(research_registration=frozen, graph_registration=full_graph_registration, artifact_root=root, run_root=full_graph_run_root)
    if llm_factory is None:
        from tradingagents.llm_clients.factory import create_llm_client
        llm_factory = create_llm_client
    rows, captured, seen, call_receipts = [dict(deterministic_result), *local_rows], {}, set(), []
    for lane in lane_ids:
        spec = frozen["lane_specs"][lane]
        model = llm_factory(**codex_factory_kwargs(spec)).get_llm()
        outputs, ids, incoming, outgoing, latency = [], [], 0, 0, 0
        for cid, prompt in prompts[lane].items():
            safe, _ = _adapter_input(cases[cid], lane, sources[cid])
            began = time.monotonic_ns()
            response = model.invoke(prompt)
            latency += max(0, (time.monotonic_ns() - began) // 1_000_000)
            if not isinstance(response, AIMessage) or response.tool_calls or response.invalid_tool_calls:
                raise ResearchQualificationBenchmarkError("Codex plain benchmark response requested tools")
            observed = validate_codex_response(getattr(response, "response_metadata", None), getattr(response, "usage_metadata", None), spec)
            if observed["outcome_id"] in seen:
                raise ResearchQualificationBenchmarkError("Codex provider outcome repeated across cases or lanes")
            seen.add(observed["outcome_id"])
            ids.append(observed["outcome_id"])
            incoming += observed["input_tokens"]
            outgoing += observed["output_tokens"]
            message = message_to_dict(response)
            if _sensitive_outbound_value(message):
                raise ResearchQualificationBenchmarkError("Codex returned benchmark message contains sensitive text")
            call_receipts.append({"case_id": cid, "lane_id": lane, "input_sha256": safe["input_sha256"],
                                  "outcome_id": observed["outcome_id"], "message": message})
            outputs.append({"case_id": cid, "answer": _text(getattr(response, "content", None), "Codex answer"), "source_artifact_id": cases[cid]["artifact_id"],
                            "byte_start": cases[cid]["byte_start"], "byte_end": cases[cid]["byte_end"], "input_sha256": safe["input_sha256"], "pair_id": safe["pair_id"]})
        captured[lane] = outputs
        rows.append({"lane_id": lane, "requested_provider": "codex", "requested_model": spec["model"], "requested_revision": None,
                     "actual_provider": "codex", "actual_model": None, "actual_revision": None, "route": spec["route"], "prompt_sha256": spec["prompt_sha256"],
                     "fallback_used": False, "input_tokens": incoming, "output_tokens": outgoing, "latency_ms": latency, "cost_usd": None,
                     "privacy_mode": "registered_retained_source", "outcome_ids": ids, "checkpoint_id": f"registered-codex-{frozen['registration_sha256']}",
                     "case_outputs": outputs, **codex_result_identity(spec), **AUTHORITY})
    adapters = {lane: (lambda case, source, indexed={row['case_id']: row for row in outputs}: indexed[case['case_id']]) for lane, outputs in captured.items()}
    result = run_registered_research_benchmark(registration=frozen, lane_results=rows, artifact_root=root, lane_adapters=adapters)
    if prepared is not None:
        from tradingagents.research.qualification_full_graph import execute_prepared_full_graph
        best = max(Decimal(row["source_accuracy"]) for row in result["lane_results"] if row["qualified"] and not row["lane_id"].endswith("_no_text"))
        if best + gain > 1:
            execution = {"status": "not_run", "reason": "registered_accuracy_gain_unattainable", **AUTHORITY}
        else:
            graph_rows, graph_outputs, execution = execute_prepared_full_graph(prepared, llm_factory=llm_factory)
            if seen.intersection(identifier for row in graph_rows for identifier in row["outcome_ids"]):
                raise ResearchQualificationBenchmarkError("Codex graph outcome duplicates a source-lane outcome")
            rows += graph_rows
            for lane, outputs in graph_outputs.items():
                indexed = {row["case_id"]: row for row in outputs}
                adapters[lane] = lambda case, source, indexed=indexed: indexed[case["case_id"]]
            result = run_registered_research_benchmark(registration=frozen, lane_results=rows, artifact_root=root, lane_adapters=adapters)
        result["full_graph_execution"] = execution
    return _finish(result, {"status": "completed", "lanes": lane_ids, "case_calls": call_receipts,
                            "cost_status": "unknown_subscription_allocation", **AUTHORITY})
