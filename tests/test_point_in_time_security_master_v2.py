"""Synthetic original-backed assertions; no real market identity qualification."""

from __future__ import annotations

import datetime as dt
import json
from decimal import localcontext

import pytest

from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError, validate_security_identity
from tradingagents.dataflows.pit.security_master import (
    SecurityMasterAssertionArchive,
    SecurityMasterAssertionV2,
    build_security_master_assertion,
    build_security_master_assertions,
    new_security_master_entity_id,
    reconcile_security_master_assertions,
    verify_security_master_assertions,
)

NOW = dt.datetime(2026, 10, 2, 8, tzinfo=dt.timezone.utc)
ALIAS = "alias-00000000-0000-0000-0000-000000000001"
SECURITY = "security-00000000-0000-0000-0000-000000000001"


@pytest.fixture
def archive(tmp_path):
    return RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW)


def paths(**changes):
    return {"value": ["value"], "effective_from": ["from"], "effective_to": ["to"], "coverage_through": ["through"],
            "source_published_at": ["published"], "source_recorded_at": None, **changes}


def assertion(archive, *, subject_kind="alias", subject_id=ALIAS, field="symbol", value="OLD", host="issuer.example", changes=None, **kwargs):
    payload = {"value": value, "from": "2020-01-01", "to": None, "through": "2026-10-02", "published": "2026-10-01T12:00:00Z", **(changes or {})}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    original = archive.admit(raw_bytes=raw, source_uri=f"https://{host}/synthetic/record", content_type="application/json", retrieved_at=NOW.isoformat())
    return build_security_master_assertion(archive=archive, subject_kind=subject_kind, subject_id=subject_id, field=field,
                                         raw_artifact_id=original.raw_artifact_id, source_field_paths=paths(), **kwargs)


def query(archive, records, **kwargs):
    return reconcile_security_master_assertions(records, archive=archive, subject_kind="alias", subject_id=ALIAS, field="symbol",
                                               effective_on="2026-10-02", known_at="2026-10-02T09:00:00Z", **kwargs)


def test_assertion_json_reopens_original_and_is_immutable(archive):
    record = assertion(archive)
    payload = json.loads(record.canonical_json_bytes())
    (rebuilt,) = verify_security_master_assertions([payload], archive=archive)
    assert rebuilt.canonical_json_bytes() == record.canonical_json_bytes()
    with pytest.raises(TypeError):
        record.record["value"] = "FORGED"
    with pytest.raises(TypeError):
        SecurityMasterAssertionV2(record={})
    with pytest.raises(PointInTimeDataError):
        validate_security_identity(payload)


@pytest.mark.parametrize("kind", ["issuer", "security", "listing", "alias", "external_identifier", "event"])
def test_internal_id_allocation_keeps_layers_distinct(kind):
    first, second = new_security_master_entity_id(kind), new_security_master_entity_id(kind)
    assert first.startswith(kind + "-") and first != second


def test_ticker_reuse_does_not_merge_independent_aliases(archive):
    first = assertion(archive, value="SAME")
    second_id = "alias-00000000-0000-0000-0000-000000000002"
    second = assertion(archive, subject_id=second_id, value="SAME")
    result = query(archive, [first, second])
    assert result["assertion_ids"] == [first.assertion_id]
    assert result["state"] == "observed" and result["cohort_qualified"] is False


def test_independent_share_classes_are_not_issuer_identity(archive):
    first = assertion(archive, subject_kind="security", subject_id=SECURITY, field="share_class", value="Class A")
    second = assertion(archive, subject_kind="security", subject_id="security-00000000-0000-0000-0000-000000000002", field="share_class", value="Class C")
    assert first.to_dict()["subject_id"] != second.to_dict()["subject_id"]
    assert len(verify_security_master_assertions([first, second], archive=archive)) == 2
    with pytest.raises(PointInTimeDataError):
        assertion(archive, subject_kind="security", subject_id="00000000-0000-0000-0000-000000000001", field="share_class", value="Class A")


def test_name_and_vendor_id_change_are_separate_from_internal_security(archive):
    old = assertion(archive, subject_kind="security", subject_id=SECURITY, field="name", value="Old issuer name", changes={"to": "2026-10-02"})
    new = assertion(archive, subject_kind="security", subject_id=SECURITY, field="name", value="New issuer name", changes={"from": "2026-10-02"})
    external = assertion(archive, subject_kind="external_identifier", subject_id="external_identifier-00000000-0000-0000-0000-000000000003", field="alpaca_asset_id", value="00000000-0000-0000-0000-000000000009")
    assert old.to_dict()["subject_id"] == new.to_dict()["subject_id"]
    assert external.to_dict()["subject_id"] != SECURITY
    assert len(verify_security_master_assertions([old, new, external], archive=archive)) == 3


def test_interval_end_is_exclusive_and_unknown_open_end_needs_coverage(archive):
    ended = assertion(archive, changes={"to": "2026-10-02"})
    assert query(archive, [ended])["state"] == "unknown"
    unknown = assertion(archive, changes={"through": None})
    assert query(archive, [unknown])["state"] == "unknown"
    covered = assertion(archive)
    assert query(archive, [covered])["state"] == "observed"


def test_conflicting_sources_retain_all_values(archive):
    first = assertion(archive, host="issuer.example")
    second = assertion(archive, value="NEW", host="exchange.test")
    result = query(archive, [first, second])
    assert result["state"] == "conflicting" and set(result["values"]) == {"OLD", "NEW"}
    assert len(result["assertion_ids"]) == 2


def test_agreement_and_provider_subdomains_do_not_fabricate_independence(archive):
    first = assertion(archive, host="www.sec.gov")
    same = assertion(archive, host="data.sec.gov")
    assert query(archive, [first, same])["state"] == "observed"
    other = assertion(archive, host="exchange.test")
    assert query(archive, [first, same, other])["state"] == "corroborated"


def test_late_custody_cannot_reconstruct_historical_knowledge(archive):
    record = assertion(archive, derivation_mode="historical_reconstruction")
    result = reconcile_security_master_assertions([record], archive=archive, subject_kind="alias", subject_id=ALIAS, field="symbol",
                                                  effective_on="2026-09-01", known_at="2026-10-01T23:59:59Z")
    assert result["state"] == "unknown"
    assert query(archive, [record])["state"] == "reconstructed"


def test_delisting_does_not_require_or_invent_proceeds(archive):
    record = assertion(archive, subject_kind="security", subject_id=SECURITY, field="status", value="delisted")
    assert record.to_dict()["value"] == "delisted"
    assert "terminal_proceeds" not in record.to_dict()
    result = reconcile_security_master_assertions([], archive=archive, subject_kind="event", subject_id="event-00000000-0000-0000-0000-000000000001", field="consideration",
                                                  effective_on="2026-10-02", known_at=NOW.isoformat(), coverage_state="data_unavailable")
    assert result["state"] == "data_unavailable" and not result["values"]


@pytest.mark.parametrize("state", ["unknown", "data_unavailable", "not_requested"])
def test_missing_events_preserve_coverage_state(archive, state):
    assert query(archive, [], coverage_state=state)["state"] == state


def test_asset_class_and_name_cannot_be_asserted_as_common_stock(archive):
    for value in ("us_equity", "Example Common Stock Company", True, 1):
        with pytest.raises(PointInTimeDataError):
            assertion(archive, subject_kind="security", subject_id=SECURITY, field="security_type", value=value)


def test_correction_is_append_only_and_earlier_knowledge_is_preserved(tmp_path):
    old_archive = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW)
    old = assertion(old_archive)
    later = NOW + dt.timedelta(hours=1)
    new_archive = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: later)
    new = assertion(new_archive, value="NEW", correction_parents=[old.assertion_id], prior_assertions=[old])
    before = reconcile_security_master_assertions([old, new], archive=new_archive, subject_kind="alias", subject_id=ALIAS, field="symbol", effective_on="2026-10-02", known_at=NOW.isoformat())
    after = query(new_archive, [old, new])
    assert before["values"] == ["OLD"] and after["values"] == ["NEW"]
    assert old.assertion_id != new.assertion_id
    with pytest.raises(PointInTimeDataError):
        verify_security_master_assertions([new], archive=new_archive)


def test_interval_removing_correction_does_not_revive_old_fact(tmp_path):
    first = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW)
    old = assertion(first)
    later = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW + dt.timedelta(hours=1))
    correction = assertion(later, changes={"to": "2026-10-02"}, correction_parents=[old.assertion_id], prior_assertions=[old])
    assert query(later, [old, correction])["state"] == "unknown"


def test_correction_cannot_replace_another_subject_or_an_earlier_clock(tmp_path):
    first = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW)
    old = assertion(first)
    with pytest.raises(PointInTimeDataError):
        assertion(first, value="NEW", correction_parents=[old.assertion_id], prior_assertions=[old])
    later = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW + dt.timedelta(hours=1))
    with pytest.raises(PointInTimeDataError):
        assertion(later, subject_id="alias-00000000-0000-0000-0000-000000000002", value="NEW", correction_parents=[old.assertion_id], prior_assertions=[old])


@pytest.mark.parametrize("field,value", [("value", "FORGED"), ("retrieved_at", "2020-01-01T00:00:00+00:00"), ("effective_from", "2000-01-01"), ("analysis_only", 1), ("parser_version", "new/unreviewed")])
def test_altered_assertion_or_clock_is_rejected(archive, field, value):
    payload = assertion(archive).to_dict()
    payload[field] = value
    with pytest.raises(PointInTimeDataError):
        verify_security_master_assertions([payload], archive=archive)


def test_wrong_path_types_and_changed_paths_are_rejected(archive):
    record = assertion(archive)
    payload = record.to_dict()
    payload["source_field_paths"]["value"] = [True]
    with pytest.raises(PointInTimeDataError):
        verify_security_master_assertions([payload], archive=archive)
    payload["source_field_paths"]["value"] = ["published"]
    with pytest.raises(PointInTimeDataError):
        verify_security_master_assertions([payload], archive=archive)


@pytest.mark.parametrize("raw", [b'{"value":"A","value":"B"}', b'{"value":NaN}', b'{"value":1e999}', b'[]bad'])
def test_malformed_originals_cannot_mint_assertions(archive, raw):
    original = archive.admit(raw_bytes=raw, source_uri="https://fixture.example/bad", content_type="application/json", retrieved_at=NOW.isoformat())
    with pytest.raises(PointInTimeDataError):
        build_security_master_assertion(archive=archive, subject_kind="alias", subject_id=ALIAS, field="symbol", raw_artifact_id=original.raw_artifact_id, source_field_paths=paths())


def test_source_consideration_preserves_precision_without_implying_coverage(archive):
    raw = b'{"value":{"cash":1.234567890123456789,"successor":{"ratio":"0.25","id":"B"}},"from":"2026-10-01","to":null,"through":"2026-10-02","published":null}'
    original = archive.admit(raw_bytes=raw, source_uri="https://fixture.example/action", content_type="application/json", retrieved_at=NOW.isoformat())
    with localcontext() as context:
        context.prec = 2
        record = build_security_master_assertion(archive=archive, subject_kind="event", subject_id="event-00000000-0000-0000-0000-000000000001", field="consideration", raw_artifact_id=original.raw_artifact_id, source_field_paths=paths())
    assert record.to_dict()["value"]["cash"] == "1.234567890123456789"
    assert record.to_dict()["value"]["successor"]["ratio"] == "0.25"


def test_batch_derivation_reopens_shared_page_once(archive, monkeypatch):
    original = archive.admit(raw_bytes=b'[{"symbol":"A"},{"symbol":"B"}]', source_uri="https://fixture.example/page", content_type="application/json", retrieved_at=NOW.isoformat())
    calls = []
    read = archive.read_bytes

    def counted(artifact):
        calls.append(artifact.raw_artifact_id)
        return read(artifact)

    monkeypatch.setattr(archive, "read_bytes", counted)
    requests = [{"subject_kind": "alias", "subject_id": f"alias-00000000-0000-0000-0000-{index + 1:012d}", "field": "symbol", "raw_artifact_id": original.raw_artifact_id,
                 "source_field_paths": paths(value=[index, "symbol"], effective_from=None, effective_to=None, coverage_through=None, source_published_at=None),
                 "derivation_mode": "direct", "correction_parents": []} for index in range(2)]
    result = build_security_master_assertions(requests, archive=archive)
    assert len(calls) == 1 and [record.to_dict()["value"] for record in result] == ["A", "B"]


def test_assertion_store_preserves_original_and_correction(tmp_path):
    originals = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW)
    old = assertion(originals)
    store = SecurityMasterAssertionArchive(tmp_path / "master", originals=originals)
    assert store.append(old).assertion_id == old.assertion_id
    original_bytes = (tmp_path / "master" / f"{old.assertion_id}.json").read_bytes()
    later = RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: NOW + dt.timedelta(hours=1))
    new = assertion(later, value="NEW", correction_parents=[old.assertion_id], prior_assertions=[old])
    store.append(new)
    store.append(old)
    assert (tmp_path / "master" / f"{old.assertion_id}.json").read_bytes() == original_bytes
    assert store.read(new.assertion_id).to_dict()["value"] == "NEW"


def test_store_rejects_tampered_original_and_partial_or_symlinked_records(archive, tmp_path):
    record = assertion(archive)
    store = SecurityMasterAssertionArchive(tmp_path / "master", originals=archive)
    store.append(record)
    target = tmp_path / "master" / f"{record.assertion_id}.json"
    target.write_bytes(b'{')
    with pytest.raises(PointInTimeDataError):
        store.read(record.assertion_id)
    with pytest.raises(PointInTimeDataError):
        store.append(record)
    target.unlink()
    outside = tmp_path / "outside.json"
    outside.write_bytes(record.canonical_json_bytes())
    target.symlink_to(outside)
    with pytest.raises(PointInTimeDataError):
        store.read(record.assertion_id)


def test_raw_source_tampering_invalidates_assertion_replay(archive):
    record = assertion(archive)
    payload = record.to_dict()
    (archive.root / "objects" / f"{payload['raw_artifact']['raw_artifact_id']}.raw").write_bytes(b'{"value":"FORGED"}')
    with pytest.raises(PointInTimeDataError):
        verify_security_master_assertions([record], archive=archive)
