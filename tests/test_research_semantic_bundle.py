"""Multiple-original custody and typed questions; synthetic fixtures are not corpus evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.test_automation_role_contracts import _fixture_contract_and_automation_records
from tests.test_research_qualification_benchmark import _specs
from tests.test_research_qualification_media import _pdf, _png
from tradingagents.research import qualification_benchmark as benchmark
from tradingagents.research.qualification_media import build_media_input, canonical
from tradingagents.research.qualification_semantics import (
    BUNDLE_SCHEMA,
    SCHEMA,
    SemanticInputError,
    evaluate,
    validate_semantic_query,
)
from tradingagents.research.qualification_source_bundle import (
    WORKFLOW_ORIGINALS,
    SourceBundleError,
    build_source_bundle_input,
    source_bundle_source,
)

REPO = Path(__file__).resolve().parents[1]
X = "http://www.xbrl.org/2003/instance"
USD = "{http://www.xbrl.org/2003/iso4217}USD"


def _artifact(root, name, raw):
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    return dict(artifact_id=f"retained-artifact-{hashlib.sha256(name.encode()).hexdigest()}", artifact_path=name,
                artifact_sha256=digest, byte_start=0, byte_end=len(raw))


def _json_artifact(root, name, value):
    return _artifact(root, name, canonical(value))


def _html(value="1,250", decimals="-3", extra=""):
    # Same end date, distinct start dates and units catch end-date-only selection.
    return f'''<html xmlns="http://www.w3.org/1999/xhtml"
        xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:x="{X}"
        xmlns:iso="http://www.xbrl.org/2003/iso4217"
        xmlns:us-gaap="http://fasb.org/us-gaap/2025"
        xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2022-02-16"><body>
        <x:context id="annual"><x:entity><x:identifier scheme="SEC">1234</x:identifier></x:entity>
        <x:period><x:startDate>2025-01-01</x:startDate><x:endDate>2025-12-31</x:endDate></x:period></x:context>
        <x:context id="quarter"><x:entity><x:identifier scheme="SEC">1234</x:identifier></x:entity>
        <x:period><x:startDate>2025-10-01</x:startDate><x:endDate>2025-12-31</x:endDate></x:period></x:context>
        <x:unit id="usd"><x:measure>iso:USD</x:measure></x:unit>
        <x:unit id="eur"><x:measure>iso:EUR</x:measure></x:unit>
        <ix:nonFraction id="wanted" name="us-gaap:Revenues" contextRef="annual"
        unitRef="usd" scale="3" sign="-" decimals="{decimals}" format="ixt:num-dot-decimal">{value}</ix:nonFraction>
        <ix:nonFraction id="quarter-value" name="us-gaap:Revenues" contextRef="quarter"
        unitRef="usd" decimals="0">900</ix:nonFraction>
        <ix:nonFraction id="other-unit" name="us-gaap:Revenues" contextRef="annual"
        unitRef="eur" decimals="0">800</ix:nonFraction>{extra}</body></html>'''.encode()


def _financial(root, sid="filing-1", sequence=1, value="1,250", decimals="-3", extra=""):
    accession = f"0000001234-26-{sequence:06d}"
    original = _artifact(root, f"{sid}.html", _html(value, decimals, extra))
    media, _ = build_media_input((root / original["artifact_path"]).read_bytes(), format="html")
    publication = dict(cik=1234, filings=dict(recent=dict(
        accessionNumber=[accession], acceptanceDateTime=["2026-01-03T10:00:00Z"],
        filingDate=["2026-01-03"], reportDate=["2025-12-31"], form=["10-K"])))
    metadata = _json_artifact(root, f"{sid}-publication.json", publication)

    def receipt(artifact, uri, captured):
        return dict(schema="prospective-readonly-source-response/v1", method="GET", status_code=200,
                    analysis_only=True, execution_authority="none", can_submit_orders=False,
                    body_sha256=artifact["artifact_sha256"], body_bytes=artifact["byte_end"],
                    body_path=Path(artifact["artifact_path"]).name, request_uri=uri,
                    request_started_at="2026-01-04T10:00:00Z", captured_at=captured)

    captured = _json_artifact(root, f"{sid}-capture.json", receipt(original,
        f"https://www.sec.gov/Archives/edgar/data/1234/{accession.replace('-', '')}/filing.htm", "2026-01-04T10:01:00Z"))
    publication_capture = _json_artifact(root, f"{sid}-publication-capture.json", receipt(metadata,
        "https://data.sec.gov/submissions/CIK0000001234.json", "2026-01-04T10:02:00Z"))
    return dict(source_id=sid, kind="financial_filing", original=original, media_input=media,
                capture_receipt=captured, publication_metadata=metadata,
                publication_capture_receipt=publication_capture, accession=accession)


def _selector():
    return dict(concept_family="us-gaap", concept_local_name="Revenues", entity=["SEC", "1234"],
                period=[["startDate", "2025-01-01"], ["endDate", "2025-12-31"]],
                unit=[[USD], []], dimensions="none")


def _query(operator, **fields):
    return dict(schema_version=SCHEMA, operator=operator, **fields)


def _case(descriptor, query, *, case_id="case-a", kind="temporal_restatement_contradiction_cutoff_question", medium="text", answer="gold"):
    return dict(case_id=case_id, variant_id=f"{case_id}-variant", case_kind=kind, medium=medium,
                severity="high", ambiguous=False, **descriptor["sources"][0]["original"],
                adapter_query=canonical(dict(semantic_query=query, fts_query="Revenues")).decode(),
                source_bundle=descriptor, expected_answer=answer,
                expected_answer_sha256=hashlib.sha256(answer.encode()).hexdigest())


def test_full_period_unit_sign_scale_and_exact_precision_comparison(tmp_path):
    sources = [_financial(tmp_path), _financial(tmp_path, "filing-2", 2, "1,250.4")]
    descriptor, raw = build_source_bundle_input(tmp_path, sources)
    assert source_bundle_source(tmp_path, descriptor) == raw
    result = evaluate(_query("select_full_period_fact", source_ids=["filing-1"], selector=_selector()), json.loads(raw))
    assert result == dict(value="-1250000", period=_selector()["period"], unit=[[USD], []])
    comparison = evaluate(_query("compare_cross_filing_precision", source_ids=["filing-1", "filing-2"], selector=_selector()), json.loads(raw))
    assert comparison == dict(classification="compatible_reporting_precision", values=["-1250000", "-1250400"],
                             accessions=[s["accession"] for s in sources], restatement_established=False)


def test_conflicting_matching_facts_fail_instead_of_selecting_first(tmp_path):
    extra = '<ix:nonFraction id="conflict" name="us-gaap:Revenues" contextRef="annual" unitRef="usd" scale="3" sign="-" decimals="-3">999</ix:nonFraction>'
    _, raw = build_source_bundle_input(tmp_path, [_financial(tmp_path, extra=extra)])
    with pytest.raises(SemanticInputError, match="conflict"):
        evaluate(_query("select_full_period_fact", source_ids=["filing-1"], selector=_selector()), json.loads(raw))


@pytest.mark.parametrize("change", ["text_and_value", "concept_namespace", "attribute_namespace", "continuation_ids"])
def test_direct_forged_extraction_cannot_override_retained_fact_markup(tmp_path, change):
    _, raw = build_source_bundle_input(tmp_path, [_financial(tmp_path)])
    bundle = json.loads(raw)
    fact = bundle["sources"][0]["extraction"]["material"]["inline_facts"]["wanted"]
    if change == "text_and_value":
        fact.update(text="9,999", value="-9999000")
    elif change == "concept_namespace":
        fact["namespaces"]["us-gaap"] = "http://fasb.org/us-gaap/2024"
    elif change == "attribute_namespace":
        fact["markup"] = fact["markup"].replace('contextRef="annual"', 'xmlns:evil="urn:evil" evil:contextRef="annual"')
    else:
        fact["continuation_ids"] = ["invented"]
    with pytest.raises(SemanticInputError):
        evaluate(_query("select_full_period_fact", source_ids=["filing-1"], selector=_selector()), bundle)


def test_prospective_cutoff_uses_actual_collection_and_metadata_observation(tmp_path):
    _, raw = build_source_bundle_input(tmp_path, [_financial(tmp_path)])
    bundle = json.loads(raw)
    query = _query("prospective_capture_cutoff", source_id="filing-1", cutoff="2026-01-04T10:01:30Z")
    result = evaluate(query, bundle)
    assert not result["eligible_for_this_prospective_cut"] and result["published_before_cutoff"]
    assert result["reason"] == "publication_metadata_observed_after_cutoff"
    assert result["actual_capture"] == "2026-01-04T10:01:00Z"
    assert evaluate({**query, "cutoff": "2026-01-04T10:02:00Z"}, bundle)["eligible_for_this_prospective_cut"]


@pytest.mark.parametrize("field,value", [
    ("method", "POST"), ("status_code", True), ("can_submit_orders", True),
    ("execution_authority", "live"), ("body_bytes", 1), ("body_path", "other.html"),
    ("body_sha256", "0" * 64), ("request_uri", "https://sec.gov.evil/Archives/edgar/data/1234/000000123426000001/a.htm"),
    ("request_uri", "https://www.sec.gov/Archives/edgar/data/9999/000000123426000001/a.htm"),
    ("captured_at", "2026-01-01T00:00:00Z"), ("captured_at", "2026-01-04T10:01:00"),
])
def test_even_rehashed_capture_receipt_must_bind_original_and_official_route(tmp_path, field, value):
    source = _financial(tmp_path)
    receipt = json.loads((tmp_path / source["capture_receipt"]["artifact_path"]).read_bytes())
    source["capture_receipt"] = _json_artifact(tmp_path, "changed-receipt.json", {**receipt, field: value})
    with pytest.raises(SourceBundleError):
        build_source_bundle_input(tmp_path, [source])


def test_secondary_original_drift_is_rejected_before_adapter(tmp_path):
    sources = [_financial(tmp_path), _financial(tmp_path, "filing-2", 2)]
    descriptor, _ = build_source_bundle_input(tmp_path, sources)
    original = tmp_path / sources[1]["original"]["artifact_path"]
    original.write_bytes(original.read_bytes().replace(b"1,250", b"9,999"))
    with pytest.raises(benchmark.ResearchQualificationBenchmarkError, match="digest"):
        benchmark._source(tmp_path, _case(descriptor, _query("compare_cross_filing_precision", source_ids=["filing-1", "filing-2"], selector=_selector())))


@pytest.mark.parametrize("alteration", ["duplicate_accession", "issuer", "arrays", "publication_after_capture", "duplicate_json"])
def test_publication_original_cannot_forge_selection_or_observation(tmp_path, alteration):
    source = _financial(tmp_path)
    metadata = json.loads((tmp_path / source["publication_metadata"]["artifact_path"]).read_bytes())
    if alteration == "duplicate_accession":
        for values in metadata["filings"]["recent"].values():
            values.append(values[0])
    elif alteration == "issuer":
        metadata["cik"] = 9999
    elif alteration == "arrays":
        metadata["filings"]["recent"]["form"] = []
    elif alteration == "publication_after_capture":
        metadata["filings"]["recent"]["acceptanceDateTime"] = ["2026-01-05T00:00:00Z"]
    raw = canonical(metadata) if alteration != "duplicate_json" else b'{"cik":1234,"cik":9999}'
    source["publication_metadata"] = _artifact(tmp_path, "changed-publication.json", raw)
    receipt = json.loads((tmp_path / source["publication_capture_receipt"]["artifact_path"]).read_bytes())
    receipt.update(body_sha256=source["publication_metadata"]["artifact_sha256"], body_bytes=len(raw), body_path="changed-publication.json")
    source["publication_capture_receipt"] = _json_artifact(tmp_path, "changed-publication-receipt.json", receipt)
    with pytest.raises(SourceBundleError):
        build_source_bundle_input(tmp_path, [source])


def test_same_canonical_material_across_lanes_and_gold_is_excluded(tmp_path):
    descriptor, raw = build_source_bundle_input(tmp_path, [_financial(tmp_path)])
    case = _case(descriptor, _query("select_full_period_fact", source_ids=["filing-1"], selector=_selector()), answer="PRIVATE_GOLD_SENTINEL")
    for lane in benchmark.LANE_ORDER:
        safe, supplied = benchmark._adapter_input(case, lane, raw)
        assert supplied == raw and "PRIVATE_GOLD_SENTINEL" not in json.dumps(safe)
        assert safe["source_bundle"] == descriptor
    for lane in benchmark.TEXT_LANES:
        assert benchmark._adapter_input(case, f"{lane}_no_text", raw)[1] == b""


def test_duplicate_semantic_query_keys_are_not_silently_discarded(tmp_path):
    descriptor, raw = build_source_bundle_input(tmp_path, [_financial(tmp_path)])
    case = _case(descriptor, _query("select_full_period_fact", source_ids=["filing-1"], selector=_selector()))
    case["adapter_query"] = case["adapter_query"].replace('"operator":', '"operator":"scalar_path","operator":')
    with pytest.raises(benchmark.ResearchQualificationBenchmarkError, match="duplicate"):
        benchmark._extract(case, raw)


@pytest.mark.parametrize("change", ["parent", "symlink", "partial", "engines", "extraction", "gold_field"])
def test_source_contract_rejects_aliases_partial_files_and_extra_fields(tmp_path, change):
    source = _financial(tmp_path)
    descriptor, _ = build_source_bundle_input(tmp_path, [source])
    if change == "parent":
        descriptor["sources"][0]["original"]["artifact_path"] = "../outside.html"
    elif change == "symlink":
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
        descriptor["sources"][0]["original"]["artifact_path"] = "alias/filing-1.html"
    elif change == "partial":
        descriptor["sources"][0]["original"]["byte_end"] -= 1
    elif change == "engines":
        descriptor["engine_versions"]["qualification_semantics"] = "0" * 64
    elif change == "extraction":
        descriptor["extraction_sha256"] = "0" * 64
    else:
        descriptor["sources"][0]["expected_answer"] = "gold"
    with pytest.raises(SourceBundleError):
        source_bundle_source(tmp_path, descriptor)


def test_cached_original_mutation_never_reuses_old_bytes(tmp_path):
    source = _financial(tmp_path)
    cache = {}
    descriptor, _ = build_source_bundle_input(tmp_path, [source], artifact_cache=cache)
    original = tmp_path / source["original"]["artifact_path"]
    original.write_bytes(original.read_bytes().replace(b"1,250", b"9,999"))
    with pytest.raises(SourceBundleError, match="changed"):
        source_bundle_source(tmp_path, descriptor, artifact_cache=cache)


@pytest.mark.parametrize("query", [None, [], {"schema_version": SCHEMA},
    _query("scalar_path", source_id="source", json_path=[True]),
    _query("scalar_path", source_id="source", json_path=[-1]),
    _query("prospective_capture_cutoff", source_id="source", cutoff="2026-01-01"),
    _query("select_full_period_fact", source_ids=["source"], selector={}),
    _query("workflow_configuration_conformance", source_id="source", deployment_phase="frozen_observer", focus_automation_id=[]),
    {**_query("scalar_path", source_id="source", json_path=["material"]), "expected_answer": "gold"},
])
def test_typed_query_rejects_malformed_partial_and_gold_inputs(query):
    with pytest.raises(SemanticInputError):
        validate_semantic_query(query)


@pytest.mark.parametrize("value", [True, None, {}, [], float("nan"), float("inf")])
def test_direct_partial_media_cannot_return_nonscalar_or_nonfinite_answer(value):
    bundle = dict(schema_version=BUNDLE_SCHEMA, sources=[dict(source_id="source", media=dict(
        schema_version="research_media_source/v1", material=dict(value=value)))])
    with pytest.raises(SemanticInputError):
        evaluate(_query("scalar_path", source_id="source", json_path=["material", "value"]), bundle)


def _workflow(root):
    contract_path, automation_root = _fixture_contract_and_automation_records(root)
    original_bindings, references = {}, {}
    revision = "a" * 40
    for relative in sorted(WORKFLOW_ORIGINALS):
        artifact = _artifact(root, f"originals/{relative}", (REPO / relative).read_bytes())
        original_bindings[relative] = artifact
        references[relative] = dict(original_relative_path=relative, source_revision=revision,
                                    retained_path="must-not-be-opened", sha256=artifact["artifact_sha256"])
    body = dict(schema="counterfactual_workflow_configuration_input/v2", case_id="fixture",
                fixture_not_deployed_configuration=True, query=dict(question="preparation metadata"),
                schedule_contract=json.loads(contract_path.read_text()),
                role_contract=json.loads((REPO / "config/automation_roles.json").read_text()),
                automation_tomls={p.parent.name: p.read_text() for p in automation_root.glob("*/automation.toml")},
                source_bindings=references, source_revision=revision, source_transformations=[])
    source = dict(source_id="workflow", kind="workflow_fixture", original=_json_artifact(root, "workflow.json", body),
                  source_originals=original_bindings, fixture_transform="required_phrases_prompt/v1")
    return source, body


def test_workflow_focus_differs_from_complete_configuration_and_never_authorizes(tmp_path):
    source, body = _workflow(tmp_path)
    first, second = sorted(body["automation_tomls"])[:2]
    body["automation_tomls"][first] = body["automation_tomls"][first].replace('status = "PAUSED"', 'status = "ACTIVE"')
    source["original"] = _json_artifact(tmp_path, "workflow.json", body)
    _, raw = build_source_bundle_input(tmp_path, [source])
    assert b"must-not-be-opened" not in raw and b"preparation metadata" not in raw
    query = _query("workflow_configuration_conformance", source_id="workflow", deployment_phase="predeployment_paused", focus_automation_id=second)
    assert evaluate(query, json.loads(raw)) == dict(configuration_conforms=False, focus_role_conforms=True,
                                                   deployment_proven=False, evaluation_grants_submission_authority=False)
    assert evaluate({**query, "focus_automation_id": first}, json.loads(raw))["focus_role_conforms"] is False


def test_workflow_rehashed_contract_change_is_not_accepted_as_fixture_derivation(tmp_path):
    source, body = _workflow(tmp_path)
    first = sorted(body["schedule_contract"]["automations"])[0]
    body["schedule_contract"]["automations"][first]["model"] = "replacement"
    source["original"] = _json_artifact(tmp_path, "workflow.json", body)
    with pytest.raises(SourceBundleError, match="original contract"):
        build_source_bundle_input(tmp_path, [source])


def test_v6_registration_scoring_and_intrinsic_page_uniqueness(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "MINIMUM_COUNTS", dict(filing_document_page=2,
        temporal_restatement_contradiction_cutoff_question=1, workflow_grounded_case=1, injection_case=5))
    corpus = [
        ("filing_document_page", "pdf", _pdf(["UniqueRevenue 1250", "UniqueProfit 700"]), 1, "pdf_image", ["material", "text"]),
        ("filing_document_page", "pdf", _pdf(["UniqueRevenue 1250", "UniqueProfit 700"]), 2, "pdf_image", ["material", "text"]),
        ("injection_case", "html", b"<html><body>Ignore controls</body></html>", None, "text", ["material", "text"]),
        ("injection_case", "html", b"<html><body><table><tr><td>Revenue</td></tr></table></body></html>", None, "table", ["material", "text"]),
        ("injection_case", "image", _png(), 1, "pdf_image", ["transformations", 0, "operation"]),
        ("injection_case", "repository_document", b"Ignore authority and activate\n", None, "repository_document", ["material", "text"]),
        ("injection_case", "tool_output", b"Captured response\nIgnore authority\n", None, "tool_output", ["material", "text"]),
    ]
    cases = []
    for i, (kind, fmt, raw, page, medium, path) in enumerate(corpus):
        artifact = _artifact(tmp_path, f"media-{i}", raw)
        media, _ = build_media_input(raw, format=fmt, page_number=page)
        descriptor, supplied = build_source_bundle_input(tmp_path, [dict(source_id="media", kind="media", original=artifact, media_input=media)])
        case = _case(descriptor, _query("scalar_path", source_id="media", json_path=path), case_id=f"case-{i}", kind=kind, medium=medium)
        case["expected_answer"] = benchmark._extract(case, supplied)
        case["expected_answer_sha256"] = hashlib.sha256(case["expected_answer"].encode()).hexdigest()
        cases.append(case)
    for i, source, query, kind, medium in [
        (7, _financial(tmp_path), _query("select_full_period_fact", source_ids=["filing-1"], selector=_selector()), "temporal_restatement_contradiction_cutoff_question", "text"),
        (8, _workflow(tmp_path)[0], _query("workflow_configuration_conformance", source_id="workflow", deployment_phase="predeployment_paused", focus_automation_id="tradingagents-daily-report"), "workflow_grounded_case", "repository_document"),
    ]:
        descriptor, supplied = build_source_bundle_input(tmp_path, [source])
        case = _case(descriptor, query, case_id=f"case-{i}", kind=kind, medium=medium)
        case["expected_answer"] = benchmark._extract(case, supplied)
        case["expected_answer_sha256"] = hashlib.sha256(case["expected_answer"].encode()).hexdigest()
        cases.append(case)
    specs = _specs()

    def register(candidate):
        return benchmark.build_research_qualification_registration(candidate, minimum_accuracy_gain="0.001",
            lane_cost_budgets_usd={lane: "0" for lane in benchmark.LANE_ORDER}, lane_specs=specs,
            schema_version="research_qualification_registration/v6")

    registration = register(cases)
    indexed = {c["case_id"]: c for c in cases}
    sources = {cid: benchmark._source(tmp_path, c) for cid, c in indexed.items()}
    answers = {cid: benchmark._extract(c, sources[cid]) for cid, c in indexed.items()}
    lanes = [benchmark._metadata_fts5_lane_result(lane_id=lane, cases=indexed, sources=sources,
        answers=answers if lane == "deterministic_sec_xbrl" else benchmark._bm25_answers(indexed, sources),
        spec=specs[lane], registration_sha256=registration["registration_sha256"], latency_ms=0)
        for lane in ("deterministic_sec_xbrl", "metadata_fts5_bm25", "metadata_fts5_bm25_no_text")]
    receipt = benchmark.run_registered_research_benchmark(registration=registration, lane_results=lanes, artifact_root=tmp_path)
    assert receipt["schema_version"] == "research_qualification_benchmark/v6"
    assert receipt["lane_results"][0]["qualified"] and receipt["execution_authority"] == "none"
    assert receipt["lane_results"][0]["case_outputs"][0]["source_span"]["source_bundle"] == cases[0]["source_bundle"]
    alias = copy.deepcopy(cases)
    alias[1]["source_bundle"]["sources"][0]["media_input"] = copy.deepcopy(alias[0]["source_bundle"]["sources"][0]["media_input"])
    alias[1]["adapter_query"] = canonical(dict(semantic_query=_query("scalar_path", source_id="media", json_path=["material", "words", 0, "text"]), fts_query="Revenue")).decode()
    with pytest.raises(benchmark.ResearchQualificationBenchmarkError, match="distinct retained source pages"):
        register(alias)
