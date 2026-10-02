"""Exhaustive synthetic directory accounting with whole-source replay."""

from __future__ import annotations

import copy
import json

import pytest

from tests.test_prospective_population_contract import (
    archive,
    asset,
    captured,
    contract,
    coverage,
    no_network,  # noqa: F401 -- keep source calls blocked in this module
)
from tradingagents.dataflows import alpaca_source_probe as probe
from tradingagents.dataflows.pit.population_accounting import (
    build_population_accounting,
    population_accounting_jsonl,
    verify_population_accounting,
)
from tradingagents.dataflows.pit.population_contract import (
    PopulationContractError,
    import_probe_discovery_coverage,
)


def test_every_row_over_512_is_retained_without_identity_or_cohort_invention(tmp_path):
    policy, discovery, originals = coverage(tmp_path, count=700)
    value = build_population_accounting(contract=policy, discovery_coverage=discovery, archive=originals)
    assert value["total_records"] == 701
    assert value["disposition_counts"] == {"eligible": 0, "source_supported_ineligible": 1, "unresolved": 700}
    assert all(row["internal_security_id"] is None for row in value["rows"])
    assert value["top_100"] is value["primary_75"] is value["sensitivity_50"] is None
    assert value["cohort_qualified"] is False
    assert len(population_accounting_jsonl(value).splitlines()) == 701
    assert verify_population_accounting(json.loads(json.dumps(value)), contract=policy, discovery_coverage=discovery, archive=originals) == value


def test_exclusions_are_source_supported_names_are_not_share_class_evidence(tmp_path):
    rows = [{**asset(1), "name": "Example Common Stock", "maintenance_margin_requirement": 30.5},
            {**asset(2), "tradable": False}, {**asset(3), "exchange": "OTC"},
            {**asset(4), "symbol": "123456789_DELISTED"}]
    policy, discovery, originals = coverage(tmp_path, overrides={"assets_active": probe.FetchResult(200, "application/json", json.dumps(rows).encode())})
    value = build_population_accounting(contract=policy, discovery_coverage=discovery, archive=originals)
    assert value["disposition_counts"] == {"eligible": 0, "source_supported_ineligible": 3, "unresolved": 2}
    assert value["rows"][0]["disposition"] == "unresolved"
    assert value["rows"][0]["source_fields"]["maintenance_margin_requirement"] == "30.5"
    assert value["rows"][3]["original_symbol"] == "123456789_DELISTED"
    assert value["rows"][3]["symbol_requestable"] is False
    assert "supported_requestable_alias" in value["rows"][3]["unresolved_requirements"]
    assert value["unsupported_alias_records"] == 1


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "count", "eligible", "identity", "authority", "source"])
def test_omitted_altered_or_qualified_rows_fail_original_replay(tmp_path, mutation):
    policy, discovery, originals = coverage(tmp_path, count=3)
    value = build_population_accounting(contract=policy, discovery_coverage=discovery, archive=originals)
    changed = copy.deepcopy(value)
    if mutation == "omit":
        changed["rows"].pop()
    elif mutation == "duplicate":
        changed["rows"].append(changed["rows"][0])
    elif mutation == "count":
        changed["total_records"] = 3
    elif mutation == "eligible":
        changed["rows"][0]["disposition"] = "eligible"
    elif mutation == "identity":
        changed["rows"][0]["internal_security_id"] = "security-guess"
    elif mutation == "authority":
        changed["analysis_only"] = 1
    else:
        changed["rows"][0]["source_fields"]["tradable"] = False
    with pytest.raises(PopulationContractError, match="original row replay"):
        verify_population_accounting(changed, contract=policy, discovery_coverage=discovery, archive=originals)


def test_incomplete_directory_cannot_claim_full_population_accounting(tmp_path):
    policy, discovery, originals = coverage(tmp_path, overrides={"assets_active": probe.FetchResult(403, "application/json", b'{}')})
    with pytest.raises(PopulationContractError, match="complete declared discovery"):
        build_population_accounting(contract=policy, discovery_coverage=discovery, archive=originals)


def test_original_body_tamper_cannot_replay_accounting(tmp_path):
    policy, discovery, originals = coverage(tmp_path, count=3)
    value = build_population_accounting(contract=policy, discovery_coverage=discovery, archive=originals)
    identifier = discovery["partitions"]["assets_active"]["originals"][0]["raw_artifact_id"]
    (originals.root / "objects" / f"{identifier}.raw").write_bytes(b'[]')
    with pytest.raises(PopulationContractError):
        verify_population_accounting(value, contract=policy, discovery_coverage=discovery, archive=originals)


def test_legacy_v2_policy_keeps_original_profile_and_replay(tmp_path):
    from tradingagents.dataflows.pit.population_contract import _LEGACY_SCHEMA, _canonical, _material, _sha, validate_population_contract
    policy = contract(tmp_path).to_dict()
    material = _material(campaign_id=policy["campaign_id"], frozen_at=policy["frozen_at"], decision_cutoff=policy["decision_cutoff"], ranking_request_dates=policy["ranking_request_dates"], schema_version=_LEGACY_SCHEMA)
    digest = _sha(_canonical(material))
    legacy = validate_population_contract({**material, "contract_id": "population-contract-" + digest, "contract_sha256": digest})
    assert "unsupported_directory_alias_disposition" not in legacy.to_dict()["policy"]
    assert legacy.to_dict()["policy"]["source_profiles"]["discovery"].startswith("alpaca_source_probe_parser/v2:")
    originals = archive(tmp_path)
    discovery = import_probe_discovery_coverage(contract=legacy, bundle=captured(tmp_path, count=2), archive=originals)
    assert discovery["parser_version"] == "alpaca_asset_directory_probe/v2"
    assert build_population_accounting(contract=legacy, discovery_coverage=discovery, archive=originals)["total_records"] == 3
