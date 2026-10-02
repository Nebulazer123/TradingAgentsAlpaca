"""Synthetic campaign/custody fixtures only; never market population proof."""
from __future__ import annotations

import datetime as dt
import json
import socket
from uuid import UUID

import pytest

from tradingagents.dataflows import alpaca_source_probe as probe
from tradingagents.dataflows.pit.population_contract import (
    PopulationContractError,
    PopulationContractV2,
    freeze_population_contract,
    import_probe_discovery_coverage,
    read_population_contract,
    validate_population_contract,
    verify_discovery_coverage,
)
from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError

NOW = dt.datetime(2026, 10, 2, 8, tzinfo=dt.timezone.utc)
CUTOFF = "2026-10-05T13:00:00Z"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Campaign fixture attempted network access")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def contract(tmp_path, *, frozen=NOW, **kwargs):
    return freeze_population_contract(tmp_path / "policy.json", decision_cutoff=CUTOFF, ranking_start="2026-06-01", ranking_end="2026-10-02", clock=lambda: frozen, **kwargs)


def sessions():
    dates = []
    day = dt.date(2026, 1, 2)
    while len(dates) < 60:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return dates


def asset(index, status="active"):
    return {"id": str(UUID(int=index)), "symbol": "A" + str(index), "class": "us_equity", "exchange": "NASDAQ", "status": status, "tradable": status == "active"}


class FixtureTransport:
    def __init__(self, *, count=600, overrides=None):
        self.count, self.overrides = count, overrides or {}

    def get(self, request, **kwargs):
        if request.query_id in self.overrides:
            return self.overrides[request.query_id]
        if request.kind == "assets":
            status = dict(request.params)["status"]
            payload = [asset(index + 1) for index in range(self.count)] if status == "active" else [asset(10000, "inactive")]
        elif request.kind == "calendar":
            payload = [{"date": day, "open": "09:30", "close": "16:00"} for day in sessions()]
        elif request.kind == "asset":
            payload = {**asset(1), "symbol": request.symbol}
        elif request.kind == "bars":
            payload = {"symbol": request.symbol, "bars": [], "next_page_token": None}
        else:
            payload = {"corporate_actions": {}, "next_page_token": None}
        return probe.FetchResult(200, "application/json", json.dumps(payload, separators=(",", ":")).encode())


def captured(tmp_path, *, when=None, **kwargs):
    dates = sessions()
    plan = probe.ProbePlan(dates[0], dates[-1], "2026-10-02", ("A1",))
    root = tmp_path / "probe"
    probe.collect_probe(plan, root, FixtureTransport(**kwargs), allow_network_read=True, clock=lambda: when or NOW + dt.timedelta(minutes=1))
    return root


def archive(tmp_path, *, when=None):
    return RawPointInTimeArtifactArchive(tmp_path / "raw", clock=lambda: when or NOW + dt.timedelta(minutes=2))


def coverage(tmp_path, **kwargs):
    policy = contract(tmp_path)
    root = captured(tmp_path, **kwargs)
    originals = archive(tmp_path)
    result = import_probe_discovery_coverage(contract=policy, bundle=root, archive=originals)
    return policy, result, originals


def test_policy_freeze_roundtrip_bounds_authority_and_immutable_hash(tmp_path):
    record = contract(tmp_path)
    assert read_population_contract(tmp_path / "policy.json").to_dict() == record.to_dict()
    assert validate_population_contract(json.loads(record.canonical_json_bytes())).contract_id == record.contract_id
    assert record.to_dict()["policy"]["cohort_sizes"] == {"top": 100, "primary_prefix": 75, "sensitivity_prefix": 50}
    with pytest.raises(TypeError):
        record.record["policy"]["lookback_complete_sessions"] = 10
    with pytest.raises(TypeError):
        PopulationContractV2(record={})
    with pytest.raises(FileExistsError):
        contract(tmp_path)


@pytest.mark.parametrize("field,value", [("analysis_only", 1), ("can_submit_orders", 0), ("decision_cutoff", "2026-10-01T13:00:00Z"), ("frozen_at", "2020-01-01T00:00:00Z"), ("contract_id", "forged"), ("policy_sha256", "0" * 64)])
def test_policy_altered_value_or_integer_boolean_is_rejected(tmp_path, field, value):
    payload = contract(tmp_path).to_dict()
    payload[field] = value
    with pytest.raises(PopulationContractError):
        validate_population_contract(payload)


@pytest.mark.parametrize("cutoff,start,end", [("2026-10-02T08:00:00Z", "2026-01-01", "2026-10-01"), (CUTOFF, "2026-10-03", "2026-10-02"), (CUTOFF, "2026-06-01", "2026-10-05"), ("2026-10-05T13:00:00", "2026-06-01", "2026-10-02")])
def test_policy_refuses_nonprospective_or_invalid_dates(tmp_path, cutoff, start, end):
    with pytest.raises(PopulationContractError):
        freeze_population_contract(tmp_path / "policy.json", decision_cutoff=cutoff, ranking_start=start, ranking_end=end, clock=lambda: NOW)


def test_policy_requires_private_parent_and_rejects_symlink_or_duplicate_json(tmp_path):
    open_parent = tmp_path / "public"
    open_parent.mkdir(mode=0o755)
    # The source gate inherits umask 077; establish actual public permissions.
    open_parent.chmod(0o755)
    with pytest.raises(PopulationContractError):
        contract(open_parent)
    policy = contract(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(tmp_path / "policy.json")
    with pytest.raises(OSError):
        read_population_contract(link)
    (tmp_path / "policy.json").write_bytes(b'{"schema_version":"x","schema_version":"y"}')
    with pytest.raises(PopulationContractError):
        read_population_contract(tmp_path / "policy.json")
    assert policy.contract_id


def test_complete_large_original_arrays_replay_without_512_row_limit(tmp_path):
    policy, result, originals = coverage(tmp_path)
    assert result["partitions"]["assets_active"]["record_count"] == 600
    assert result["partitions"]["assets_inactive"]["record_count"] == 1
    assert result["discovery_state"] == "complete"
    assert result["transport_mode"] == "injected_fixture"
    assert result["population_qualified"] is False and result["cohort_qualified"] is False
    assert result["identity_type_alias_coverage"] == result["population_price_coverage"] == result["event_consideration_coverage"] == "NOT_ESTABLISHED"
    assert verify_discovery_coverage(json.loads(json.dumps(result)), contract=policy, archive=originals) == result


@pytest.mark.parametrize("reply", [probe.FetchResult(403, "application/json", b'{}'), probe.FetchResult(200, "text/plain", b'no-json'), probe.FetchResult(200, "application/json", b'[', False, "connection_closed")])
def test_denied_nonjson_and_partial_partitions_stay_unavailable(tmp_path, reply):
    policy, result, originals = coverage(tmp_path, overrides={"assets_active": reply})
    assert result["discovery_state"] == "incomplete"
    assert result["partitions"]["assets_active"]["state"] == "unavailable"
    assert result["partitions"]["assets_active"]["record_count"] is None
    assert verify_discovery_coverage(result, contract=policy, archive=originals) == result


def test_early_capture_and_late_admission_fail_closed(tmp_path):
    policy = contract(tmp_path)
    root = captured(tmp_path, when=NOW - dt.timedelta(seconds=1))
    with pytest.raises(PopulationContractError, match="capture window"):
        import_probe_discovery_coverage(contract=policy, bundle=root, archive=archive(tmp_path))
    late = archive(tmp_path / "late", when=dt.datetime(2026, 10, 5, 13, 0, 1, tzinfo=dt.timezone.utc))
    with pytest.raises(PopulationContractError, match="missed the cutoff"):
        import_probe_discovery_coverage(contract=policy, bundle=root, archive=late)


def test_microsecond_capture_retained_with_conservative_raw_v2_projection(tmp_path):
    policy = contract(tmp_path)
    moment = NOW + dt.timedelta(minutes=1, microseconds=123456)
    root = captured(tmp_path, when=moment)
    result = import_probe_discovery_coverage(contract=policy, bundle=root, archive=archive(tmp_path))
    partition = result["partitions"]["assets_active"]
    assert partition["upstream_http_receipts"][0]["capture_completed_at"] == moment.isoformat(timespec="microseconds")
    assert partition["originals"][0]["retrieved_at"] == "2026-10-02T08:01:01+00:00"
    assert verify_discovery_coverage(result, contract=policy, archive=archive(tmp_path)) == result


@pytest.mark.parametrize("field,value", [("discovery_state", "complete"), ("population_qualified", True), ("analysis_only", 1), ("transport_mode", "https"), ("snapshot_identity_conflicts", True)])
def test_coverage_flags_are_rederived_from_originals(tmp_path, field, value):
    policy, result, originals = coverage(tmp_path, overrides={"assets_active": probe.FetchResult(403, "application/json", b'{}')})
    result[field] = value
    with pytest.raises(PopulationContractError):
        verify_discovery_coverage(result, contract=policy, archive=originals)


def test_tampered_original_or_partition_counts_cannot_replay(tmp_path):
    policy, result, originals = coverage(tmp_path)
    changed = json.loads(json.dumps(result))
    changed["partitions"]["assets_active"]["record_count"] = 1
    with pytest.raises(PopulationContractError):
        verify_discovery_coverage(changed, contract=policy, archive=originals)
    receipt = result["partitions"]["assets_active"]["originals"][0]
    (originals.root / "objects" / f"{receipt['raw_artifact_id']}.raw").write_bytes(b'[]')
    with pytest.raises(PopulationContractError):
        verify_discovery_coverage(result, contract=policy, archive=originals)


def test_changed_manifest_after_initial_replay_is_rejected(tmp_path, monkeypatch):
    policy = contract(tmp_path)
    root = captured(tmp_path)
    original = probe.inspect_probe
    def changed(path):
        result = original(path)
        manifest = path / "manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b' ')
        return result
    monkeypatch.setattr(probe, "inspect_probe", changed)
    with pytest.raises(PopulationContractError, match="changed after replay"):
        import_probe_discovery_coverage(contract=policy, bundle=root, archive=archive(tmp_path))


def test_raw_projection_cannot_backdate_an_instantaneous_import(tmp_path):
    policy = contract(tmp_path)
    moment = NOW + dt.timedelta(minutes=1, microseconds=123)
    root = captured(tmp_path, when=moment)
    early_archive = archive(tmp_path, when=moment.replace(microsecond=0))
    with pytest.raises(PointInTimeDataError, match="before source retrieval"):
        import_probe_discovery_coverage(contract=policy, bundle=root, archive=early_archive)
