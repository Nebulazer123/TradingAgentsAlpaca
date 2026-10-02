"""Exhaustive source-supported dispositions for a frozen directory population.

Alpaca's current us_equity directory does not establish common-share class or
historical identity. Every original row is retained; names are never type proof.
This receipt is an accounting boundary, not an admitted cohort or ranking.
"""

from __future__ import annotations

import json
from collections import Counter

from tradingagents.dataflows.alpaca_source_probe import _directory_asset, _load
from tradingagents.dataflows.pit.population_contract import (
    _AUTHORITY,
    PopulationContractError,
    _canonical,
    _sha,
    validate_population_contract,
    verify_discovery_coverage,
)
from tradingagents.dataflows.pit.security_master import _plain

SCHEMA = "prospective_population_accounting/v1"


def build_population_accounting(*, contract: object, discovery_coverage: object, archive) -> dict:
    """Reopen complete declared partitions and account for every row exactly once."""
    policy = validate_population_contract(contract).to_dict()
    coverage = verify_discovery_coverage(discovery_coverage, contract=contract, archive=archive)
    if coverage["discovery_state"] != "complete":
        raise PopulationContractError("complete declared discovery is required for full accounting")
    rows, counts, reasons = [], Counter(), Counter()
    exchanges = set(policy["policy"]["eligible_exchanges"])
    for partition, details in coverage["partitions"].items():
        original = details["originals"][0]
        payload = _load(archive.read_bytes(archive.read_artifact(original["raw_artifact_id"])))
        for index, source_row in enumerate(payload):
            asset = _directory_asset(source_row)
            source_row = _plain(source_row)
            exclusion = []
            if asset["status"] == "inactive":
                exclusion.append("source_listing_inactive")
            if asset["tradable"] is False:
                exclusion.append("source_not_tradable")
            if asset["exchange"] not in exchanges:
                exclusion.append("source_exchange_outside_policy")
            # Conflicting snapshots do not resolve which record was current.
            if coverage["snapshot_identity_conflicts"]:
                disposition, missing = "unresolved", ["conflicting_snapshot_identity"]
                exclusion = []
            elif exclusion:
                disposition, missing = "source_supported_ineligible", []
            else:
                disposition = "unresolved"
                missing = ["positive_common_or_ordinary_share_class", "independent_share_class_identity", "dated_listing_and_alias", "exact_60_session_prices"]
                if not asset["symbol_requestable"]:
                    missing.append("supported_requestable_alias")
            counts[disposition] += 1
            reasons.update(exclusion or missing)
            binding = {"partition": partition, "array_index": index, "raw_artifact_id": original["raw_artifact_id"],
                       "raw_artifact_sha256": original["raw_artifact_sha256"], "source_row_sha256": _sha(_canonical(source_row))}
            row = {"row_id": "population-row-" + _sha(_canonical(binding)), **binding,
                   "provider_asset_id": asset["id"], "original_symbol": asset["symbol"],
                   "symbol_requestable": asset["symbol_requestable"], "source_fields": source_row,
                   "source_row_projection": "exact_JSON_decimal_numbers_as_strings",
                   "internal_security_id": None, "disposition": disposition,
                   "source_supported_exclusion_reasons": exclusion, "unresolved_requirements": missing}
            rows.append(row)
    total = sum(details["record_count"] for details in coverage["partitions"].values())
    if len(rows) != total or len({row["row_id"] for row in rows}) != total:
        raise PopulationContractError("population accounting lost or duplicated a source row")
    material = {"schema_version": SCHEMA, "contract_id": policy["contract_id"], "contract_sha256": policy["contract_sha256"],
                "discovery_coverage_id": coverage["coverage_id"], "transport_mode": coverage["transport_mode"],
                "boundary": policy["policy"]["population_boundary"], "rows": rows, "total_records": total,
                "partition_counts": {name: value["record_count"] for name, value in coverage["partitions"].items()},
                "disposition_counts": {name: counts[name] for name in ("eligible", "source_supported_ineligible", "unresolved")},
                "reason_counts": dict(sorted(reasons.items())), "unsupported_alias_records": sum(not row["symbol_requestable"] for row in rows),
                "identity_type_alias_coverage": "NOT_ESTABLISHED", "population_price_coverage": "NOT_ESTABLISHED",
                "event_consideration_coverage": "NOT_ESTABLISHED", "global_ranking": None,
                "top_100": None, "primary_75": None, "sensitivity_50": None,
                "population_qualified": False, "cohort_qualified": False, **_AUTHORITY}
    digest = _sha(_canonical(material))
    return {**material, "accounting_id": "population-accounting-" + digest, "accounting_sha256": digest}


def verify_population_accounting(value: object, *, contract: object, discovery_coverage: object, archive) -> dict:
    """Rebuild all rows and counts from whole originals rather than trusting flags."""
    if type(value) is not dict:
        raise PopulationContractError("population accounting must be an object")
    rebuilt = build_population_accounting(contract=contract, discovery_coverage=discovery_coverage, archive=archive)
    try:
        matches = _canonical(value) == _canonical(rebuilt)
    except (TypeError, ValueError) as exc:
        raise PopulationContractError("population accounting contains invalid JSON") from exc
    if not matches:
        raise PopulationContractError("population accounting differs from original row replay")
    return rebuilt


def population_accounting_jsonl(value: dict) -> bytes:
    """Deterministic companion rows; the full receipt binds their source material."""
    return b"".join(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode() + b"\n" for row in value["rows"])
