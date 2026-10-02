"""Frozen population policy and original-backed discovery coverage.

Policy creation/readback uses only the standard library. Source imports are lazy
and reuse the reviewed probe and PIT custody owner; no network call is made here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

SCHEMA = "prospective_security_population/v3"
_LEGACY_SCHEMA = "prospective_security_population/v2"
_AUTHORITY = {"analysis_only": True, "execution_authority": "none", "can_submit_orders": False}
_FIELDS = {"schema_version", "contract_id", "contract_sha256", "campaign_id", "frozen_at", "decision_cutoff", "ranking_request_dates", "policy", "policy_sha256", *_AUTHORITY}


class PopulationContractError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _time(value: object) -> dt.datetime:
    if type(value) is not str:
        raise PopulationContractError("contract timestamp must be a string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PopulationContractError("invalid contract timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PopulationContractError("contract timestamp requires a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _stamp(value: dt.datetime) -> str:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() is None:
        raise PopulationContractError("contract clock requires an aware datetime")
    return value.astimezone(dt.timezone.utc).isoformat(timespec="microseconds")


def _date(value: object) -> dt.date:
    if type(value) is not str:
        raise PopulationContractError("ranking date must be a string")
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PopulationContractError("invalid ranking date") from exc
    if result.isoformat() != value:
        raise PopulationContractError("ranking date must be canonical")
    return result


def _policy(schema_version: str = SCHEMA) -> dict:
    policy = {
        "population_boundary": "all_rows_in_explicit_alpaca_active_and_inactive_us_equity_snapshots",
        "eligible_class": "positively_established_common_stock_or_ordinary_share_class",
        "eligible_exchanges": ["AMEX", "ARCA", "BATS", "NASDAQ", "NYSE", "NYSEARCA"],
        "must_be_alpaca_tradable": True,
        "excluded_classes": ["preferred_stock", "etf", "etn", "fund", "adr", "warrant", "right", "unit", "test"],
        "inactive_listing_disposition": "ineligible_but_retained",
        "unknown_class_or_identity_disposition": "unresolved",
        "share_class_identity": "independent_internal_security_id",
        "discovery_partitions": {
            f"assets_{status}": {"method": "GET", "host": "paper-api.alpaca.markets", "path": "/v2/assets",
                                "params": {"asset_class": "us_equity", "status": status}, "response_profile": "whole_json_array_snapshot"}
            for status in ("active", "inactive")
        },
        "required_record_families": ["discovery", "identity_type_listing_alias", "calendar", "prices", "events_consideration"],
        "source_profiles": {
            "discovery": "alpaca_source_probe_parser/v2:whole_assets_json_arrays",
            "identity": "security_master_json_fields/v1:exact_original_fields_and_dated_intervals",
            "calendar": "market_session_calendar/v1:original_alpaca_TRADING_calendar",
            "prices": "alpaca_daily_sip_raw:all_original_pages_exact_60_sessions",
            "actions": "alpaca_action_originals/v1:processing_scope_is_not_effective_event_absence",
            "action_emissions": "alpaca_source_probe_parser/v2:insert_update_delete_original_envelopes",
            "sec_issuer_metadata": "original_SEC_submissions_and_company_tickers_exchange:issuer_only",
        },
        "sec_metadata_templates": ["https://www.sec.gov/files/company_tickers_exchange.json", "https://data.sec.gov/submissions/CIK{cik}.json"],
        "identity_required_facts": ["positive_common_or_ordinary_class", "independent_share_class", "dated_listing", "dated_alias", "alpaca_asset_id", "tradable_at_cutoff"],
        "unknown_identity_type_interval": "unresolved_no_name_or_current_ticker_inference",
        "event_absence_rule": "requires_independently_qualified_effective_interval_coverage_not_empty_REST_pages",
        "coverage_dimensions_are_independent": True,
        "cutoff_basis": "trusted_local_custody_before_forecasts_and_outcomes",
        "lookback_complete_sessions": 60,
        "prior_complete_close_floor_usd": "5",
        "price_feed": "sip", "currency": "USD", "price_adjustment": "raw",
        "session_basis": "alpaca_provider_daily_not_certified_regular_only",
        "volume_metric": "exact_median_of_daily_close_times_volume",
        "missing_price_or_volume": "unresolved_no_imputation",
        "ranking_order": ["median_daily_dollar_volume_desc", "symbol_asc", "internal_security_id_asc"],
        "cohort_sizes": {"top": 100, "primary_prefix": 75, "sensitivity_prefix": 50},
        "candidate_accounting": ["eligible", "source_supported_ineligible", "unresolved"],
        "unresolved_candidate_that_can_change_ranking_blocks_admission": True,
        "global_ranking_across_all_partitions": True,
        "universal_historical_us_market_coverage_claimed": False,
        "holdout_release_required_separately": True,
    }
    if schema_version == SCHEMA:
        policy["source_profiles"]["discovery"] = "alpaca_source_probe_parser/v3:whole_assets_json_arrays_with_unsupported_alias_accounting"
        policy["source_profiles"]["action_emissions"] = "alpaca_source_probe_parser/v3:bounded_original_emission_envelopes"
        policy["unsupported_directory_alias_disposition"] = "retain_original_record_no_alias_normalization_or_request"
    return policy


def _material(*, campaign_id: str, frozen_at: str, decision_cutoff: str, ranking_request_dates: dict, schema_version: str = SCHEMA) -> dict:
    if type(schema_version) is not str or schema_version not in {SCHEMA, _LEGACY_SCHEMA}:
        raise PopulationContractError("unknown population policy version")
    if type(campaign_id) is not str or not campaign_id.startswith("population-campaign-"):
        raise PopulationContractError("campaign requires a local UUID identity")
    try:
        identifier = UUID(campaign_id.removeprefix("population-campaign-"))
    except ValueError as exc:
        raise PopulationContractError("invalid campaign identity") from exc
    if campaign_id != f"population-campaign-{identifier}":
        raise PopulationContractError("campaign identity must be canonical")
    frozen, cutoff = _time(frozen_at), _time(decision_cutoff)
    if cutoff <= frozen:
        raise PopulationContractError("prospective cutoff must follow the actual policy freeze")
    if type(ranking_request_dates) is not dict or set(ranking_request_dates) != {"start", "end"}:
        raise PopulationContractError("ranking query dates are required")
    start, end = (_date(ranking_request_dates[name]) for name in ("start", "end"))
    if not dt.timedelta(0) <= end - start <= dt.timedelta(days=370) or end >= cutoff.astimezone(ZoneInfo("America/New_York")).date():
        raise PopulationContractError("ranking request must precede the prospective decision date")
    policy = _policy(schema_version)
    return {"schema_version": schema_version, "campaign_id": campaign_id, "frozen_at": _stamp(frozen), "decision_cutoff": _stamp(cutoff),
            "ranking_request_dates": dict(ranking_request_dates), "policy": policy, "policy_sha256": _sha(_canonical(policy)), **_AUTHORITY}


@dataclass(frozen=True, slots=True, init=False)
class PopulationContractV2:
    record: object

    def __init__(self, *args, **kwargs):
        raise TypeError("population contracts must be frozen with their actual clock")

    @property
    def contract_id(self) -> str:
        return self.record["contract_id"]

    def to_dict(self) -> dict:
        return _thaw(self.record)

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())


def validate_population_contract(value: object) -> PopulationContractV2:
    payload = value.to_dict() if type(value) is PopulationContractV2 else value
    if type(payload) is not dict or set(payload) != _FIELDS:
        raise PopulationContractError("population contract fields differ")
    material = _material(campaign_id=payload["campaign_id"], frozen_at=payload["frozen_at"], decision_cutoff=payload["decision_cutoff"], ranking_request_dates=payload["ranking_request_dates"], schema_version=payload["schema_version"])
    digest = _sha(_canonical(material))
    expected = {**material, "contract_id": f"population-contract-{digest}", "contract_sha256": digest}
    if _canonical(payload) != _canonical(expected):
        raise PopulationContractError("population contract policy, authority, cutoff or digest differs")
    result = object.__new__(PopulationContractV2)
    object.__setattr__(result, "record", _freeze(expected))
    return result


def freeze_population_contract(destination: str | Path, *, decision_cutoff: str, ranking_start: str, ranking_end: str,
                               campaign_id: str | None = None, clock=None) -> PopulationContractV2:
    """Exclusive policy receipt, before source capture; never chooses a cohort."""
    moment = (clock or (lambda: dt.datetime.now(dt.timezone.utc)))()
    material = _material(campaign_id=campaign_id or f"population-campaign-{uuid4()}", frozen_at=_stamp(moment), decision_cutoff=decision_cutoff,
                         ranking_request_dates={"start": ranking_start, "end": ranking_end})
    digest = _sha(_canonical(material))
    contract = validate_population_contract({**material, "contract_id": f"population-contract-{digest}", "contract_sha256": digest})
    path = Path(destination)
    if not path.parent.is_dir() or path.parent.is_symlink() or path.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise PopulationContractError("contract destination requires an existing private parent")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(contract.canonical_json_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return read_population_contract(path)


def _read(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise PopulationContractError("source must be a bounded regular file")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise PopulationContractError("source byte bound")
    return raw


def read_population_contract(path: str | Path) -> PopulationContractV2:
    raw = _read(Path(path), 65536)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PopulationContractError("duplicate policy JSON key")
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=pairs)
        contract = validate_population_contract(payload)
    except (ValueError, TypeError, RecursionError) as exc:
        raise PopulationContractError("invalid population policy receipt") from exc
    if contract.canonical_json_bytes() != raw:
        raise PopulationContractError("population receipt is not canonical")
    return contract


def _custody_stamp(value: str) -> str:
    # Raw PIT v2 uses whole UTC seconds. Ceiling never backdates a capture;
    # the upstream receipt retains its exact microsecond clock independently.
    instant = _time(value)
    if instant.microsecond:
        instant += dt.timedelta(seconds=1)
    return instant.replace(microsecond=0).isoformat(timespec="seconds")


def _reopen(archive, value: object, *, uri: str, captured: str, cutoff: dt.datetime) -> bytes:
    from tradingagents.dataflows.pit.raw_artifacts import validate_raw_point_in_time_artifact

    original = validate_raw_point_in_time_artifact(value)
    raw = archive.read_bytes(original)
    if original.source_uri != uri or original.content_type != "application/json" or original.retrieved_at != _custody_stamp(captured):
        raise PopulationContractError("discovery source receipt or capture clock differs")
    if _time(original.archive_recorded_at) > cutoff:
        raise PopulationContractError("trusted discovery archive admission missed the cutoff")
    return raw


def _coverage_material(*, policy: dict, archive, plan_original: dict, manifest_original: dict, originals: dict) -> dict:
    from tradingagents.dataflows.alpaca_source_probe import (
        AUTHORITY,
        REPLAYABLE_CAPTURE_PARSERS,
        SCHEMA,
        FetchResult,
        ProbePlan,
        _asset,
        _directory_asset,
        _json_bytes,
        _load,
        _response_problem,
        build_requests,
    )
    from tradingagents.dataflows.pit.raw_artifacts import validate_raw_point_in_time_artifact

    cutoff, frozen = _time(policy["decision_cutoff"]), _time(policy["frozen_at"])
    manifest_artifact = validate_raw_point_in_time_artifact(manifest_original)
    manifest_raw = archive.read_bytes(manifest_artifact)
    manifest = _load(manifest_raw)
    fields = {"schema_version", "parser_version", "plan_sha256", "transport_mode", "entries", "completed_queries", "failures", "total_body_bytes", "capture_finished_at", *AUTHORITY}
    if type(manifest) is not dict or set(manifest) != fields or manifest["schema_version"] != SCHEMA or manifest["parser_version"] not in REPLAYABLE_CAPTURE_PARSERS or manifest["transport_mode"] not in {"https", "injected_fixture"}:
        raise PopulationContractError("invalid discovery manifest")
    if any(type(manifest[key]) is not type(value) or manifest[key] != value for key, value in AUTHORITY.items()):
        raise PopulationContractError("discovery manifest authority differs")
    finished = manifest["capture_finished_at"]
    base_uri = f"https://security-master.tradingagents.local/probe/{manifest['plan_sha256']}"
    _reopen(archive, manifest_original, uri=base_uri + "/manifest", captured=finished, cutoff=cutoff)
    plan_raw = _reopen(archive, plan_original, uri=base_uri + "/plan", captured=finished, cutoff=cutoff)
    if _sha(plan_raw) != manifest["plan_sha256"]:
        raise PopulationContractError("discovery manifest does not bind its original plan")
    plan = ProbePlan.from_dict(_load(plan_raw))
    requests = {item.query_id: item for item in build_requests(plan)}
    entries = manifest["entries"]
    completed, failures = manifest["completed_queries"], manifest["failures"]
    if type(entries) is not list or len(entries) > 64 or type(completed) is not list or type(failures) is not dict or type(manifest["total_body_bytes"]) is not int:
        raise PopulationContractError("invalid discovery manifest accounting")
    if any(type(key) is not str or key not in requests for key in completed) or len(completed) != len(set(completed)) or set(completed) & set(failures) or set(completed) | set(failures) != set(requests):
        raise PopulationContractError("invalid discovery query accounting")
    selected = {key: [] for key in policy["policy"]["discovery_partitions"]}
    receipt_fields = {"sequence", "query_id", "kind", "method", "url", "symbol", "page", "request_started_at", "capture_completed_at", "status", "content_type", "body_complete", "stop_reason", "body_path", "body_bytes", "body_sha256"}
    for index, entry in enumerate(entries, 1):
        if type(entry) is not dict or set(entry) != receipt_fields or type(entry["sequence"]) is not int or entry["sequence"] != index or entry["body_path"] != f"responses/{index:04d}.body":
            raise PopulationContractError("invalid original discovery receipt")
        if entry["query_id"] in selected:
            selected[entry["query_id"]].append(entry)
    partitions, all_ids, active_symbols = {}, set(), {}
    conflict = False
    for name, declared in policy["policy"]["discovery_partitions"].items():
        rows = selected[name]
        retained = originals[name]
        if type(retained) is not list or len(rows) > 1 or len(retained) > 1:
            raise PopulationContractError("whole-array discovery profile cannot hide page partitions")
        state, reason, count = "not_requested", "source_not_attempted", None
        if rows:
            entry = rows[0]
            began, ended = _time(entry["request_started_at"]), _time(entry["capture_completed_at"])
            if began < frozen or ended < began or ended > cutoff or ended > _time(finished):
                raise PopulationContractError("discovery original is outside the frozen campaign capture window")
            parsed = urlsplit(entry["url"])
            params = parse_qsl(parsed.query, keep_blank_values=True)
            if parsed.scheme != "https" or parsed.netloc != declared["host"] or parsed.path != declared["path"] or parsed.fragment or len(params) != 2 or dict(params) != declared["params"]:
                raise PopulationContractError("discovery request differs from frozen scope")
            if type(entry["page"]) is not int or entry["page"] != 1 or any(entry[key] != value for key, value in requests[name].to_dict().items()):
                raise PopulationContractError("discovery receipt request differs")
            if retained:
                raw = _reopen(archive, retained[0], uri=entry["url"], captured=entry["capture_completed_at"], cutoff=cutoff)
                if type(entry["body_bytes"]) is not int or len(raw) != entry["body_bytes"] or _sha(raw) != entry["body_sha256"]:
                    raise PopulationContractError("discovery original hash differs")
            else:
                raw = b""
            problem = _response_problem(FetchResult(entry["status"], entry["content_type"], raw, entry["body_complete"], entry["stop_reason"]))
            state, reason = "unavailable", problem or "unexpected_content_type"
            if not problem and entry["content_type"] == "application/json":
                if not retained or name not in completed:
                    raise PopulationContractError("complete discovery response lacks original custody")
                payload = _load(raw)
                if type(payload) is not list:
                    raise PopulationContractError("discovery original is not a whole array")
                parser = _asset if policy["schema_version"] == _LEGACY_SCHEMA else _directory_asset
                assets = [parser(row) for row in payload]
                if len({row["id"] for row in assets}) != len(assets):
                    raise PopulationContractError("duplicate discovery asset ID")
                expected_status = declared["params"]["status"]
                if any(row["class"] != "us_equity" or row["status"] != expected_status for row in assets):
                    raise PopulationContractError("discovery original request filter differs")
                for asset in assets:
                    conflict |= asset["id"] in all_ids
                    all_ids.add(asset["id"])
                    if expected_status == "active":
                        active_symbols.setdefault(asset["symbol"], set()).add(asset["id"])
                state, reason, count = "complete", None, len(assets)
        elif retained:
            raise PopulationContractError("discovery custody has no original HTTP receipt")
        partitions[name] = {"state": state, "record_count": count, "reason": reason, "originals": retained, "upstream_http_receipts": rows}
    conflict |= any(len(ids) > 1 for ids in active_symbols.values())
    material = {"schema_version": "security_master_coverage/v2", "contract_id": policy["contract_id"], "contract_sha256": policy["contract_sha256"],
                "dimension": "discovery", "parser_version": "alpaca_asset_directory_probe/v2" if policy["schema_version"] == _LEGACY_SCHEMA else "alpaca_asset_directory_probe/v3", "transport_mode": manifest["transport_mode"],
                "pit_retrieval_clock_projection": "capture_ceiling_to_UTC_second_original_microseconds_retained",
                "probe_plan_original": plan_original, "probe_manifest_original": manifest_original, "partitions": partitions,
                "discovery_state": "complete" if all(row["state"] == "complete" for row in partitions.values()) else "incomplete",
                "snapshot_identity_conflicts": conflict,
                "identity_type_alias_coverage": "NOT_ESTABLISHED", "population_price_coverage": "NOT_ESTABLISHED",
                "event_consideration_coverage": "NOT_ESTABLISHED", "population_qualified": False, "cohort_qualified": False, **_AUTHORITY}
    material["coverage_id"] = "security-master-coverage-" + _sha(_canonical(material))
    # Assert JSON serializability without altering original metadata.
    _json_bytes(material)
    return material


def import_probe_discovery_coverage(*, contract: object, bundle: str | Path, archive) -> dict:
    """Replay/import discovery originals only; samples never admit a cohort."""
    from tradingagents.dataflows.alpaca_source_probe import ProbeError, _load, inspect_probe
    from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive

    policy = validate_population_contract(contract).to_dict()
    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PopulationContractError("discovery import requires the trusted PIT archive")
    root = Path(bundle)
    try:
        report = inspect_probe(root)
        manifest_bytes = _read(root / "manifest.json", 2 * 1024 * 1024)
        if _sha(manifest_bytes) != report["manifest_sha256"]:
            raise PopulationContractError("probe manifest changed after replay")
        manifest = _load(manifest_bytes)
        plan_bytes = _read(root / "plan.json", 65536)
        if _sha(plan_bytes) != report["plan_sha256"]:
            raise PopulationContractError("probe plan changed after replay")
        finished = _custody_stamp(manifest["capture_finished_at"])
        base_uri = f"https://security-master.tradingagents.local/probe/{report['plan_sha256']}"
        plan_original = archive.admit(raw_bytes=plan_bytes, source_uri=base_uri + "/plan", content_type="application/json", retrieved_at=finished).to_dict()
        manifest_original = archive.admit(raw_bytes=manifest_bytes, source_uri=base_uri + "/manifest", content_type="application/json", retrieved_at=finished).to_dict()
        originals = {name: [] for name in policy["policy"]["discovery_partitions"]}
        for entry in manifest["entries"]:
            if entry["query_id"] not in originals or entry["content_type"] != "application/json" or entry["body_bytes"] == 0:
                continue
            raw = _read(root / entry["body_path"], 32 * 1024 * 1024)
            if _sha(raw) != entry["body_sha256"]:
                raise PopulationContractError("discovery original changed after probe replay")
            original = archive.admit(raw_bytes=raw, source_uri=entry["url"], content_type="application/json", retrieved_at=_custody_stamp(entry["capture_completed_at"]))
            originals[entry["query_id"]].append(original.to_dict())
        return _coverage_material(policy=policy, archive=archive, plan_original=plan_original, manifest_original=manifest_original, originals=originals)
    except ProbeError as exc:
        raise PopulationContractError("probe originals or receipts failed replay") from exc


def verify_discovery_coverage(value: object, *, contract: object, archive) -> dict:
    """Reproduce every discovery field from the immutable plan/manifest/bodies."""
    from tradingagents.dataflows.alpaca_source_probe import ProbeError
    from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
    from tradingagents.dataflows.pit.records import PointInTimeDataError

    policy = validate_population_contract(contract).to_dict()
    if type(value) is not dict or type(archive) is not RawPointInTimeArtifactArchive:
        raise PopulationContractError("discovery replay requires its coverage and trusted archive")
    try:
        originals = {name: value["partitions"][name]["originals"] for name in policy["policy"]["discovery_partitions"]}
        rebuilt = _coverage_material(policy=policy, archive=archive, plan_original=value["probe_plan_original"], manifest_original=value["probe_manifest_original"], originals=originals)
        if _canonical(value) != _canonical(rebuilt):
            raise PopulationContractError("discovery fields differ from source-original replay")
        return rebuilt
    except (ProbeError, PointInTimeDataError, KeyError, TypeError, ValueError) as exc:
        raise PopulationContractError("discovery coverage failed source-original replay") from exc
