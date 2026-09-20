"""Scalar source types and multiple real questions over one retained page."""

from __future__ import annotations

import hashlib
import json

import pytest

from tradingagents.research.qualification_benchmark import (
    ResearchQualificationBenchmarkError,
    _bm25_answers,
    _extract,
)


def _case(raw, *, case_id="case-a", key="value", query="value", corpus=None, offset=0):
    return {
        "case_id": case_id,
        "artifact_id": "retained-artifact-source",
        "artifact_sha256": hashlib.sha256(raw if corpus is None else corpus).hexdigest(),
        "byte_start": offset,
        "byte_end": offset + len(raw),
        "medium": "text",
        "adapter_query": json.dumps({"json_path": [key], "fts_query": query}),
    }


@pytest.mark.parametrize(("raw", "expected"), [
    (b'{"value":1.2500}', "1.25"),
    (b'{"value":-1.2500}', "-1.25"),
    (b'{"value":3e2}', "300"),
    (b'{"value":0.0001}', "0.0001"),
    (b'{"value":-0.0}', "0"),
])
def test_extract_preserves_exact_finite_decimal_source_values(raw, expected):
    assert _extract(_case(raw), raw) == expected


@pytest.mark.parametrize("raw", [
    b'{"value":true}', b'{"value":null}', b'{"value":[]}',
    b'{"value":{}}', b'{"value":NaN}', b'{"value":Infinity}',
    b'{"value":1e999999}', b'{"value":0e999999}', b'{"value":1,"value":2}',
])
def test_extract_rejects_nonscalar_nonfinite_unbounded_or_duplicate_source(raw):
    with pytest.raises(ResearchQualificationBenchmarkError):
        _extract(_case(raw), raw)


def test_bm25_answers_two_different_questions_on_one_retained_source_unit():
    raw = b'{"revenue":123,"profit":7}'
    cases = {
        "case-a": _case(raw, key="revenue", query="revenue"),
        "case-b": _case(raw, case_id="case-b", key="profit", query="profit"),
    }
    assert _bm25_answers(cases, {key: raw for key in cases}) == {"case-a": "123", "case-b": "7"}


def test_bm25_keeps_distinct_spans_within_one_artifact_separate():
    first = b'{"value":123,"topic":"sales"}'
    second = b'{"value":7,"topic":"profits"}'
    corpus = first + second
    cases = {
        "case-a": _case(first, corpus=corpus, query="sales"),
        "case-b": _case(second, case_id="case-b", corpus=corpus, offset=len(first), query="profits"),
    }
    assert _bm25_answers(cases, {"case-a": first, "case-b": second}) == {"case-a": "123", "case-b": "7"}


def test_bm25_rejects_inconsistent_bytes_for_one_source_unit():
    raw = b'{"revenue":123,"profit":7}'
    cases = {
        "case-a": _case(raw, key="revenue", query="revenue"),
        "case-b": _case(raw, case_id="case-b", key="profit", query="profit"),
    }
    with pytest.raises(ResearchQualificationBenchmarkError, match="inconsistent"):
        _bm25_answers(cases, {"case-a": raw, "case-b": b'{"revenue":999,"profit":9}'})


def test_bm25_does_not_merge_identical_excerpts_from_different_originals():
    raw = b'{"value":123}'
    cases = {
        "case-a": _case(raw, corpus=raw + b'first-original'),
        "case-b": _case(raw, case_id="case-b", corpus=raw + b'second-original'),
    }
    answers = _bm25_answers(cases, {key: raw for key in cases})
    assert list(answers.values()).count("123") == 1
    assert list(answers.values()).count(None) == 1


def test_bm25_aliases_cannot_multiply_one_retained_page():
    raw = b'{"revenue":123,"profit":7}'
    first = _case(raw, key="revenue", query="revenue")
    second = _case(raw, case_id="case-b", key="profit", query="profit")
    second["artifact_id"] = "retained-artifact-alias"
    assert _bm25_answers({"case-a": first, "case-b": second}, {"case-a": raw, "case-b": raw}) == {"case-a": "123", "case-b": "7"}
