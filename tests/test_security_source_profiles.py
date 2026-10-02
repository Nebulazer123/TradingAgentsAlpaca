"""Offline source-profile and normalized assertion checks; no network calls."""

from __future__ import annotations

import copy
import datetime as dt
import json

import pytest

from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError
from tradingagents.dataflows.pit.security_master import (
    build_security_master_assertion,
    new_security_master_entity_id,
    reconcile_security_master_assertions,
    verify_security_master_assertions,
)
from tradingagents.dataflows.pit.security_source_profiles import (
    build_nasdaq_directory_source_profile,
    build_openfigi_mapping_source_profile,
    verify_security_source_profile,
)

STAMP = "2026-10-02T12:00:00+00:00"
URI = "https://api.openfigi.com/v3/mapping"
NASDAQ = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


@pytest.fixture
def archive(tmp_path, monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("source-profile check attempted a network call")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    return RawPointInTimeArtifactArchive(tmp_path / "pit", clock=lambda: dt.datetime.fromisoformat(STAMP))


def original(archive, value, uri=URI, content_type="application/json"):
    raw = value if type(value) is bytes else json.dumps(value).encode()
    return archive.admit(raw_bytes=raw, source_uri=uri, content_type=content_type, retrieved_at=STAMP).raw_artifact_id


def job(symbol="IBM"):
    return {"idType": "TICKER", "idValue": symbol, "exchCode": "US", "marketSecDes": "Equity"}


def row(**changes):
    return {"figi": "BBG000BLNNH6", "name": "FIXTURE COMPANY", "ticker": "IBM", "exchCode": "US",
            "marketSector": "Equity", "compositeFIGI": "BBG000BLNNH6", "shareClassFIGI": "BBG001S5S399",
            "securityType": "Common Stock", "securityType2": "Common Stock", "securityDescription": "IBM", **changes}


def profile(archive, *, jobs=None, replies=None):
    request = original(archive, jobs if jobs is not None else [job()])
    response = original(archive, replies if replies is not None else [{"data": [row()]}])
    return build_openfigi_mapping_source_profile(archive=archive, request_artifact_id=request, response_artifact_id=response)


def assertion(archive, value, *, subject=None, paths=None, binding_changes=None):
    binding = {"profile_family": "openfigi_current_us_ticker/v1", "request_artifact_id": value["original_request"]["raw_artifact_id"],
               "response_artifact_id": value["original_response"]["raw_artifact_id"], "profile_id": value["profile_id"],
               "profile_sha256": value["profile_sha256"], "mapping_job_index": 0, "mapping_record_index": 0, **(binding_changes or {})}
    return build_security_master_assertion(archive=archive, subject_kind="security", subject_id=subject or new_security_master_entity_id("security"),
        field="security_type", raw_artifact_id=value["original_response"]["raw_artifact_id"],
        source_field_paths=paths or {"value": [0, "data", 0, "securityType"], "effective_from": None, "effective_to": None,
                                   "coverage_through": None, "source_published_at": None, "source_recorded_at": None},
        derivation_mode="source_profile_normalization", source_profile_binding=binding)


def test_real_label_pair_reopens_as_normalized_assertion_without_dated_identity(archive):
    value = profile(archive)
    record = assertion(archive, value)
    assert record.to_dict()["value"] == "common_stock"
    assert record.to_dict()["parser_version"] == "security_master_openfigi_label_pair/v1"
    assert verify_security_source_profile(json.loads(json.dumps(value)), archive=archive) == value
    assert verify_security_master_assertions([record], archive=archive)[0].canonical_json_bytes() == record.canonical_json_bytes()
    state = reconcile_security_master_assertions([record], archive=archive, subject_kind="security", subject_id=record.to_dict()["subject_id"],
        field="security_type", effective_on="2026-10-02", known_at=STAMP)
    assert state["state"] == "unknown" and state["cohort_qualified"] is False
    assert value["dated_identity_coverage"] == "NOT_ESTABLISHED" and value["cohort_qualified"] is False


@pytest.mark.parametrize("changes,expected", [({"securityType": "ADR", "securityType2": "Depositary Receipt"}, "adr"),
    ({"securityType": "ETP", "securityType2": "Mutual Fund"}, "unknown"),
    ({"securityType": "Common Stock", "securityType2": "Preferred Stock"}, "unknown"),
    ({"securityType": None, "securityType2": None}, "unknown")])
def test_only_observed_documented_label_pairs_normalize_without_etp_guessing(archive, changes, expected):
    value = profile(archive, replies=[{"data": [row(**changes)]}])
    assert value["results"][0]["records"][0]["normalized_security_type"] == expected
    assert assertion(archive, value).to_dict()["value"] == expected


def test_ambiguous_results_are_all_retained_and_cannot_choose_first_for_assertion(archive):
    value = profile(archive, replies=[{"data": [row(), row(figi="BBG000B9XRY4", shareClassFIGI="BBG001S5N8V8")]}])
    assert len(value["results"][0]["records"]) == 2 and value["results"][0]["result_status"] == "ambiguous"
    with pytest.raises(PointInTimeDataError, match="ambiguous"):
        assertion(archive, value)


@pytest.mark.parametrize("reply", [{"warning": "No FIGI found"}, {"error": "Mapping unavailable"}])
def test_empty_or_error_result_does_not_prove_ineligibility_or_absence(archive, reply):
    value = profile(archive, replies=[reply])
    assert value["results"][0]["result_status"] == "unavailable"
    assert value["relationship_coverage"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("changes", [{"ticker": "OTHER"}, {"exchCode": "LN"}, {"marketSector": "Corp"},
                                      {"shareClassFIGI": "not-figi"}, {"figi": True}, {"metadata": "Metadata N/A"}, {"metadata": None}])
def test_wrong_scope_malformed_or_unavailable_provider_fields_reject(archive, changes):
    with pytest.raises(PointInTimeDataError):
        profile(archive, replies=[{"data": [row(**changes)]}])


@pytest.mark.parametrize("jobs,replies", [([job()], []), ([job(), job()], [{"data": [row()]}, {"data": [row()]}]),
                                        ([job(str(index)) for index in range(6)], []), ([{**job(), "securityType": "Common Stock"}], [{"data": [row()]}])])
def test_request_slots_and_conservative_scope_cannot_be_changed(archive, jobs, replies):
    with pytest.raises(PointInTimeDataError):
        profile(archive, jobs=jobs, replies=replies)


@pytest.mark.parametrize("changes", [{"mapping_job_index": True}, {"mapping_record_index": -1},
                                      {"profile_sha256": "a" * 64}, {"profile_family": "invented"}])
def test_assertion_normalization_cannot_trust_altered_binding(archive, changes):
    with pytest.raises(PointInTimeDataError):
        assertion(archive, profile(archive), binding_changes=changes)


def test_original_bytes_and_derived_classification_are_reopened(archive):
    value = profile(archive)
    record = assertion(archive, value)
    changed = copy.deepcopy(value)
    changed["results"][0]["records"][0]["normalized_security_type"] = "adr"
    with pytest.raises(PointInTimeDataError, match="replay"):
        verify_security_source_profile(changed, archive=archive)
    changed_record = record.to_dict()
    changed_record["value"] = "adr"
    with pytest.raises(PointInTimeDataError):
        verify_security_master_assertions([changed_record], archive=archive)
    raw_id = value["original_request"]["raw_artifact_id"]
    (archive.root / "objects" / f"{raw_id}.raw").write_bytes(b"[]")
    with pytest.raises(PointInTimeDataError):
        verify_security_master_assertions([record], archive=archive)


def test_normalization_cannot_invent_effective_dates_or_omit_its_parser_binding(archive):
    value = profile(archive)
    paths = {"value": [0, "data", 0, "securityType"], "effective_from": [0, "data", 0, "ticker"],
             "effective_to": None, "coverage_through": None, "source_published_at": None, "source_recorded_at": None}
    with pytest.raises(PointInTimeDataError, match="scope"):
        assertion(archive, value, paths=paths)
    record = assertion(archive, value).to_dict()
    for changed in ({**record, "parser_version": []}, {key: item for key, item in record.items() if key != "source_profile_binding"},
                    {**record, "parser_version": "security_master_json_fields/v1"}, {**record, "derivation_mode": "direct"}):
        with pytest.raises(PointInTimeDataError):
            verify_security_master_assertions([changed], archive=archive)


def test_request_custody_cannot_arrive_after_response_and_hide_late_dependency(tmp_path):
    times = iter([dt.datetime.fromisoformat("2026-10-02T12:01:00+00:00"), dt.datetime.fromisoformat(STAMP)])
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit", clock=lambda: next(times))
    request = original(archive, [job()])
    response = original(archive, [{"data": [row()]}])
    with pytest.raises(PointInTimeDataError, match="precedes"):
        build_openfigi_mapping_source_profile(archive=archive, request_artifact_id=request, response_artifact_id=response)


def nasdaq_text(*, other=False, rows=None):
    if other:
        header = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol"
        rows = rows or ["SPY|Fixture Fund|P|SPY|Y|100|N|SPY"]
        footer = "File Creation Time: 1002202606:00||||||"
    else:
        header = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares"
        rows = rows or ["IBM|Fixture Common Stock|Q|N|N|100|N|N", "ZTEST|Fixture Test|G|Y|N|100|N|N"]
        footer = "File Creation Time: 1002202606:00|||||||"
    return (header + "\r\n" + "\r\n".join(rows) + "\r\n" + footer + "\r\n").encode()


@pytest.mark.parametrize("other", [False, True])
def test_whole_directory_rows_flags_and_unknown_generation_timezone_reopen(archive, other):
    identifier = original(archive, nasdaq_text(other=other), OTHER if other else NASDAQ, "text/plain")
    value = build_nasdaq_directory_source_profile(archive=archive, raw_artifact_id=identifier)
    assert verify_security_source_profile(value, archive=archive) == value
    assert value["source_generation_wall_time"] == "2026-10-02T06:00:00" and value["source_generation_timezone"] is None
    assert value["cohort_qualified"] is False and value["common_share_class_inferred_from_name"] is False
    assert value["record_count"] == (1 if other else 2)
    assert value["rows"][0]["observed_etf"] is other


@pytest.mark.parametrize("transform", [lambda text: text.replace(b"ETF|", b"invented|", 1),
    lambda text: text.rsplit(b"File Creation Time:", 1)[0],
    lambda text: text.replace(b"1002202606:00", b"1002202626:00"),
    lambda text: text.replace(b"Q|N|N|100|N|N", b"Q|N|N|100|unknown|N"),
    lambda text: text.replace(b"ZTEST|Fixture Test|G|Y|N|100|N|N", b"IBM|Duplicate|Q|N|N|100|N|N")])
def test_changed_headers_footer_flags_and_duplicate_rows_reject(archive, transform):
    identifier = original(archive, transform(nasdaq_text()), NASDAQ, "text/plain")
    with pytest.raises(PointInTimeDataError):
        build_nasdaq_directory_source_profile(archive=archive, raw_artifact_id=identifier)


def test_directory_omissions_or_fabricated_crosswalk_cannot_replay(archive):
    identifier = original(archive, nasdaq_text(), NASDAQ, "text/plain")
    value = build_nasdaq_directory_source_profile(archive=archive, raw_artifact_id=identifier)
    for change in (lambda row: row["rows"].pop(), lambda row: row.update(cohort_qualified=True),
                   lambda row: row["rows"][0].update(reviewed_crosswalk=True)):
        changed = copy.deepcopy(value)
        change(changed)
        with pytest.raises(PointInTimeDataError, match="replay"):
            verify_security_source_profile(changed, archive=archive)


def test_undocumented_exchange_codes_remain_accounted_without_venue_guessing(archive):
    raw = nasdaq_text(other=True, rows=["NEW|Fixture Security|F|NEW|N|100|N|NEW", "ALT|Fixture Security|M|ALT|N|100|N|ALT"])
    identifier = original(archive, raw, OTHER, "text/plain")
    value = build_nasdaq_directory_source_profile(archive=archive, raw_artifact_id=identifier)
    assert value["record_count"] == 2
    assert all(row["source_field_gaps"] == ["undocumented_exchange_code"] for row in value["rows"])
    assert [row["source_fields"]["Exchange"] for row in value["rows"]] == ["F", "M"]
    assert value["cohort_qualified"] is False
