"""Pinned immutable evidence ledger for the non-authorizing shadow-day trial.

The manual-shadow root is a single :class:`ImmutableStrategyEvidenceStore`.
Callers can supply observation content (calendar and local artifacts), but not
the ledger, authority-source paths, event timestamps, object identifiers, or
state-machine phase.  Every read replays the store journal before using an
object; a JSON file under the root is never evidence merely because it exists.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.evals.automation_health_audit import (
    PREDEPLOYMENT_PAUSED_PHASE,
    default_automation_root,
    evaluate_schedule_contract,
)
from tradingagents.strategy._immutable_evidence_store import (
    MANUAL_SHADOW_DAY_RESULT_KIND,
    MANUAL_SHADOW_DAY_START_KIND,
    MANUAL_SHADOW_FINAL_REPORT_KIND,
    EvidenceAdmission,
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
    StrategyEvidenceStoreError,
)

UTC = dt.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
START_SCHEMA = "manual_shadow_day_start_v1"
DAY_SCHEMA = "manual_shadow_day_result_v1"
REPORT_SCHEMA = "manual_shadow_final_report_v1"
ARTIFACT_KEYS = ("safety_sentinel", "paper_tournament")
EXPECTED_AUTOMATION_IDS = frozenset(
    {
        "tradingagents-automation-sleep-controller",
        "tradingagents-automation-wake-controller",
        "tradingagents-autonomous-execution-board",
        "tradingagents-autonomous-safety-sentinel",
        "tradingagents-autonomous-self-healer",
        "tradingagents-daily-report",
        "tradingagents-market-supervisor",
        "tradingagents-overnight-research",
        "tradingagents-paper-tournament",
        "tradingagents-preopen-validation",
    }
)
_START_FIELDS = frozenset(
    {
        "payload_schema",
        "run_id",
        "market_date",
        "role",
        "phase",
        "predecessor_object_id",
        "live_control",
        "schedule",
        "calendar",
    }
)
_DAY_FIELDS = frozenset(
    {
        "payload_schema",
        "start_object_id",
        "run_id",
        "market_date",
        "role",
        "status",
        "phase",
        "predecessor_object_id",
        "live_control",
        "schedule",
        "calendar",
        "artifacts",
        "reasons",
    }
)
_REPORT_FIELDS = frozenset(
    {
        "payload_schema",
        "ledger_head_object_id",
        "day_object_ids",
        "status",
        "phase",
        "clean_trial_streak",
        "required_clean_trial_days",
        "reasons",
    }
)
_CONTROL_FIELDS = frozenset(
    {
        "path",
        "status",
        "sha256",
        "canonical_sha256",
        "size_bytes",
        "modified_at",
        "frozen",
        "reason",
        "dead_man_expires_at",
        "payload",
    }
)
_SCHEDULE_FIELDS = frozenset(
    {
        "contract_path",
        "automation_root",
        "role_contract_path",
        "result",
        "canonical_sha256",
    }
)
_CALENDAR_FIELDS = frozenset(
    {
        "kind",
        "market_date",
        "observed_at",
        "sessions",
        "canonical_sha256",
    }
)
_ARTIFACT_FIELDS = frozenset(
    {
        "path",
        "status",
        "sha256",
        "canonical_sha256",
        "size_bytes",
        "modified_at",
        "kind",
        "run_id",
        "market_date",
        "generated_at",
        "payload",
    }
)


def _utc_now() -> dt.datetime:
    """Private trusted-clock seam; production commands expose no time option."""

    return dt.datetime.now(tz=UTC)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _manual_shadow_root() -> Path:
    return _repo_root() / "results" / "manual_shadow"


def _canonical_live_control_path() -> Path:
    return _repo_root() / "results" / "policy" / "live_control.json"


def _canonical_schedule_contract_path() -> Path:
    return _repo_root() / "config" / "automation_schedule_contract.json"


def _canonical_role_contract_path() -> Path:
    return _repo_root() / "config" / "automation_roles.json"


def _canonical_automation_root() -> Path:
    return default_automation_root()


def _as_utc(value: dt.datetime) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("trusted clock must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0)


def _now_stamp() -> tuple[dt.datetime, str]:
    now = _as_utc(_utc_now())
    return now, now.isoformat(timespec="seconds")


def _parse_timestamp(value: object) -> dt.datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _parse_market_date(value: object) -> dt.date | None:
    if type(value) is not str:
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _current_central_date(moment: dt.datetime) -> str:
    return moment.astimezone(CENTRAL).date().isoformat()


def _plain_json(value: object) -> object:
    """Thaw store-frozen mappings/tuples before canonical JSON validation."""

    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _plain_json(value),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc


def canonical_json_sha256(value: object) -> str:
    """Digest canonical JSON for bound local observation evidence."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_regular_json(path_value: str | Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Capture one regular JSON file with descriptor/no-follow semantics."""

    path = _absolute(path_value)
    evidence: dict[str, Any] = {
        "path": str(path),
        "status": "missing",
        "sha256": None,
        "canonical_sha256": None,
        "size_bytes": None,
        "modified_at": None,
    }
    if path.is_symlink():
        evidence["status"] = "symlink"
        return evidence, None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return evidence, None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            evidence["status"] = "not_regular_file"
            return evidence, None
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read()
        descriptor = -1
    except OSError:
        return evidence, None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    evidence.update(
        {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "modified_at": dt.datetime.fromtimestamp(metadata.st_mtime, tz=UTC).isoformat(
                timespec="seconds"
            ),
        }
    )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        evidence["status"] = "malformed_json"
        return evidence, None
    if type(payload) is not dict:
        evidence["status"] = "invalid_top_level"
        return evidence, None
    evidence["status"] = "captured"
    evidence["canonical_sha256"] = canonical_json_sha256(payload)
    return evidence, payload


def _require_exact_fields(value: object, fields: frozenset[str], *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    keys = set(value)
    if not all(type(key) is str for key in value) or keys != fields:
        missing = sorted(fields - keys)
        unknown = sorted(keys - fields)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise ValueError(f"{label} fields are invalid" + (": " + "; ".join(detail) if detail else ""))
    return value


def _require_text(value: object, *, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a nonblank string")
    return value


def _is_non_authorizing(payload: Mapping[str, object]) -> bool:
    return (
        payload.get("analysis_only") is True
        and payload.get("execution_authority") == "none"
        and payload.get("can_submit_orders") is False
    )


def _store() -> ImmutableStrategyEvidenceStore:
    return ImmutableStrategyEvidenceStore(_manual_shadow_root(), clock=_utc_now)


def _store_envelopes() -> tuple[EvidenceEnvelope, ...]:
    try:
        return _store().envelopes()
    except StrategyEvidenceStoreError as exc:
        raise ValueError(f"shadow ledger is invalid: {exc}") from exc


def _admit(
    *,
    kind: str,
    effective_at: str,
    payload: Mapping[str, object],
    validate,
) -> EvidenceAdmission:
    try:
        return _store().admit_checked(
            EvidenceCandidate(kind=kind, effective_at=effective_at, payload=payload),
            validate=validate,
        )
    except StrategyEvidenceStoreError as exc:
        raise ValueError(f"shadow ledger admission failed: {exc}") from exc


def _control_binding(now: dt.datetime) -> tuple[dict[str, object], bool]:
    path = _absolute(_canonical_live_control_path())
    evidence, payload = _read_regular_json(path)
    mapping: dict[str, object] = {
        **evidence,
        "frozen": payload.get("frozen") if isinstance(payload, Mapping) else None,
        "reason": payload.get("reason") if isinstance(payload, Mapping) else None,
        "dead_man_expires_at": payload.get("dead_man_expires_at") if isinstance(payload, Mapping) else None,
        "payload": dict(payload) if isinstance(payload, Mapping) else None,
    }
    return mapping, _valid_control_binding(mapping, now=now)


def _valid_control_binding(value: object, *, now: dt.datetime) -> bool:
    try:
        binding = _require_exact_fields(value, _CONTROL_FIELDS, label="live control binding")
    except ValueError:
        return False
    expected_path = str(_absolute(_canonical_live_control_path()))
    expiry = _parse_timestamp(binding["dead_man_expires_at"])
    payload = _plain_json(binding["payload"])
    return (
        binding["path"] == expected_path
        and binding["status"] == "captured"
        and _is_sha256(binding["sha256"])
        and _is_sha256(binding["canonical_sha256"])
        and type(binding["size_bytes"]) is int
        and binding["size_bytes"] >= 0
        and _parse_timestamp(binding["modified_at"]) is not None
        and isinstance(payload, Mapping)
        and binding["canonical_sha256"] == canonical_json_sha256(payload)
        and binding["frozen"] == payload.get("frozen")
        and binding["reason"] == payload.get("reason")
        and binding["dead_man_expires_at"] == payload.get("dead_man_expires_at")
        and binding["frozen"] is True
        and type(binding["reason"]) is str
        and bool(binding["reason"].strip())
        and expiry is not None
        and expiry > now
    )


def _schedule_binding() -> tuple[dict[str, object], bool]:
    contract = _absolute(_canonical_schedule_contract_path())
    roles = _absolute(_canonical_role_contract_path())
    automations = _absolute(_canonical_automation_root())
    try:
        result = evaluate_schedule_contract(
            contract_path=contract,
            automation_root=automations,
            role_contract_path=roles,
            deployment_phase=PREDEPLOYMENT_PAUSED_PHASE,
        )
    except Exception as exc:  # noqa: BLE001 - source-read failure is an unsafe schedule proof.
        result = {"error": f"schedule evaluator failed: {type(exc).__name__}"}
    binding: dict[str, object] = {
        "contract_path": str(contract),
        "automation_root": str(automations),
        "role_contract_path": str(roles),
        "result": dict(result) if isinstance(result, Mapping) else {"error": "invalid evaluator result"},
        "canonical_sha256": canonical_json_sha256(result),
    }
    return binding, _valid_schedule_binding(binding)


def _valid_schedule_binding(value: object) -> bool:
    try:
        binding = _require_exact_fields(value, _SCHEDULE_FIELDS, label="schedule binding")
    except ValueError:
        return False
    if (
        binding["contract_path"] != str(_absolute(_canonical_schedule_contract_path()))
        or binding["role_contract_path"] != str(_absolute(_canonical_role_contract_path()))
        or binding["automation_root"] != str(_absolute(_canonical_automation_root()))
        or not isinstance(binding["result"], Mapping)
        or not _is_sha256(binding["canonical_sha256"])
        or binding["canonical_sha256"] != canonical_json_sha256(binding["result"])
    ):
        return False
    result = _plain_json(binding["result"])
    if not isinstance(result, Mapping):
        return False
    rows = result.get("automations")
    if not isinstance(rows, list):
        return False
    row_ids = [row.get("automation_id") for row in rows if isinstance(row, Mapping)]
    return (
        result.get("contract_status") == "pass"
        and result.get("safe_predeployment") is True
        and result.get("deployment_proven") is False
        and result.get("automation_count") == 10
        and result.get("configured_count") == 10
        and result.get("paused_count") == 10
        and result.get("issues") == []
        and len(rows) == 10
        and len(row_ids) == 10
        and set(row_ids) == EXPECTED_AUTOMATION_IDS
        and len(set(row_ids)) == 10
        and all(
            isinstance(row, Mapping)
            and row.get("status") == "match"
            and row.get("config_status") == "PAUSED"
            and row.get("mismatches") == []
            for row in rows
        )
    )


def _calendar_binding(
    evidence: Mapping[str, object] | None,
    *,
    market_date: str,
) -> dict[str, object]:
    source = dict(evidence) if isinstance(evidence, Mapping) else {}
    return {
        "kind": source.get("kind"),
        "market_date": source.get("market_date"),
        "observed_at": source.get("observed_at"),
        "sessions": source.get("sessions"),
        "canonical_sha256": canonical_json_sha256(source),
    }


def _valid_calendar_binding(value: object, *, market_date: str, now: dt.datetime) -> bool:
    try:
        binding = _require_exact_fields(value, _CALENDAR_FIELDS, label="calendar binding")
    except ValueError:
        return False
    observed_at = _parse_timestamp(binding["observed_at"])
    sessions = _plain_json(binding["sessions"])
    exact_session = (
        isinstance(sessions, list)
        and len(sessions) == 1
        and isinstance(sessions[0], Mapping)
        and sessions[0].get("date") == market_date
    )
    source = {
        "kind": binding["kind"],
        "market_date": binding["market_date"],
        "observed_at": binding["observed_at"],
        "sessions": sessions,
    }
    return (
        binding["canonical_sha256"] == canonical_json_sha256(source)
        and binding["kind"] == "alpaca_regular_equities_calendar"
        and binding["market_date"] == market_date
        and observed_at is not None
        and observed_at <= now
        and _current_central_date(observed_at) == market_date
        and exact_session
    )


def _artifact_binding(path_value: object) -> dict[str, object]:
    if not isinstance(path_value, (str, Path)):
        path: Path | None = None
        evidence: dict[str, object] = {
            "path": None,
            "status": "missing",
            "sha256": None,
            "canonical_sha256": None,
            "size_bytes": None,
            "modified_at": None,
        }
        payload: dict[str, object] | None = None
    else:
        path = _absolute(path_value)
        evidence, payload = _read_regular_json(path)
    return {
        **evidence,
        "kind": payload.get("kind") if isinstance(payload, Mapping) else None,
        "run_id": payload.get("run_id") if isinstance(payload, Mapping) else None,
        "market_date": payload.get("market_date") if isinstance(payload, Mapping) else None,
        "generated_at": payload.get("generated_at") if isinstance(payload, Mapping) else None,
        "payload": dict(payload) if isinstance(payload, Mapping) else None,
    }


def _artifact_reasons(
    key: str,
    binding: object,
    *,
    run_id: str,
    market_date: str,
    start_at: dt.datetime,
    now: dt.datetime,
) -> tuple[list[str], list[str]]:
    failed: list[str] = []
    incomplete: list[str] = []
    try:
        record = _require_exact_fields(binding, _ARTIFACT_FIELDS, label=f"{key} artifact binding")
    except ValueError:
        return [], [f"{key}_binding_invalid"]
    payload = _plain_json(record["payload"])
    if (
        record["status"] != "captured"
        or not _is_sha256(record["sha256"])
        or not _is_sha256(record["canonical_sha256"])
        or type(record["size_bytes"]) is not int
        or record["size_bytes"] < 0
        or _parse_timestamp(record["modified_at"]) is None
        or not isinstance(payload, Mapping)
        or record["canonical_sha256"] != canonical_json_sha256(payload)
    ):
        return [], [f"{key}_unreadable_or_unbound"]
    expected_kind = "safety_sentinel_audit" if key == "safety_sentinel" else "paper_tournament_run"
    if record["kind"] != expected_kind or payload.get("kind") != expected_kind:
        failed.append(f"{key}_kind_invalid")
    if record["run_id"] != run_id or payload.get("run_id") != run_id:
        failed.append(f"{key}_cross_run")
    if record["market_date"] != market_date or payload.get("market_date") != market_date:
        failed.append(f"{key}_market_date_mismatch")
    if not _is_non_authorizing(payload):
        failed.append(f"{key}_authority_invalid")
    generated_at = _parse_timestamp(record["generated_at"])
    if generated_at is None or payload.get("generated_at") != record["generated_at"]:
        incomplete.append(f"{key}_timestamp_invalid")
    elif generated_at < start_at or generated_at > now or _current_central_date(generated_at) != market_date:
        incomplete.append(f"{key}_timestamp_out_of_window")
    if key == "safety_sentinel":
        if payload.get("status") not in {"FROZEN", "HOLD"}:
            failed.append("safety_sentinel_not_frozen_or_hold")
    else:
        count = payload.get("submitted_count")
        if type(count) is not int or count < 0:
            failed.append("paper_tournament_submission_count_invalid")
        elif not isinstance(payload.get("submitted"), (list, tuple)) or len(payload["submitted"]) != count:
            failed.append("paper_tournament_submissions_invalid")
        if payload.get("status") not in {"HOLD", "NO_PAPER_SIGNAL", "COMPLETE"}:
            failed.append("paper_tournament_status_invalid")
        if payload.get("status") in {"HOLD", "NO_PAPER_SIGNAL"} and count != 0:
            failed.append("paper_tournament_hold_has_submissions")
    return failed, incomplete


def _start_spec(previous: EvidenceEnvelope | None) -> tuple[str, str, str | None]:
    if previous is None:
        return "qualification_pending", "qualification", None
    payload = previous.payload
    if payload.get("status") != "clean":
        return "repair_in_progress", "repair", previous.object_id
    phase = payload.get("phase")
    if phase == "repair_in_progress":
        return "qualification_pending", "qualification", previous.object_id
    if phase in {"qualification_clean", "five_day_trial"}:
        return "five_day_trial", "trial", previous.object_id
    raise ValueError("shadow ledger cannot start after terminal trial")


def _day_phase(
    *,
    start: EvidenceEnvelope,
    status: str,
    earlier_days: tuple[EvidenceEnvelope, ...],
) -> str:
    if status != "clean":
        return "repair_required"
    role = start.payload["role"]
    if role == "qualification":
        return "qualification_clean"
    if role == "repair":
        return "repair_in_progress"
    trial_count = sum(
        1
        for day in earlier_days
        if day.payload.get("phase") in {"five_day_trial", "trial_complete"}
        and day.payload.get("status") == "clean"
    )
    return "trial_complete" if trial_count == 4 else "five_day_trial"


def _validate_start_envelope(envelope: EvidenceEnvelope, *, now: dt.datetime) -> None:
    payload = _require_exact_fields(envelope.payload, _START_FIELDS, label="shadow start payload")
    if payload["payload_schema"] != START_SCHEMA:
        raise ValueError("shadow start payload schema is invalid")
    _require_text(payload["run_id"], label="shadow start run_id")
    market_date = payload["market_date"]
    if _parse_market_date(market_date) is None:
        raise ValueError("shadow start market date is invalid")
    recorded_at = _parse_timestamp(envelope.recorded_at)
    effective_at = _parse_timestamp(envelope.effective_at)
    if (
        recorded_at is None
        or effective_at is None
        or recorded_at > now
        or _current_central_date(recorded_at) != market_date
        or _current_central_date(effective_at) != market_date
    ):
        raise ValueError("shadow start is backfilled or future")
    if not _valid_control_binding(payload["live_control"], now=recorded_at):
        raise ValueError("shadow start live control proof is invalid")
    if not _valid_schedule_binding(payload["schedule"]):
        raise ValueError("shadow start schedule proof is invalid")
    if not _valid_calendar_binding(payload["calendar"], market_date=market_date, now=recorded_at):
        raise ValueError("shadow start calendar proof is invalid")


def _evaluate_day_payload(
    start: EvidenceEnvelope,
    payload: Mapping[str, object],
    *,
    now: dt.datetime,
) -> tuple[list[str], list[str]]:
    failed: list[str] = []
    incomplete: list[str] = []
    start_payload = start.payload
    if payload["start_object_id"] != start.object_id:
        failed.append("start_reference_invalid")
    for field in ("run_id", "market_date", "role", "predecessor_object_id"):
        if payload[field] != start_payload[field]:
            failed.append(f"{field}_start_binding_mismatch")
    market_date = start_payload["market_date"]
    if not isinstance(market_date, str):
        return ["start_market_date_invalid"], incomplete
    if _current_central_date(now) != market_date:
        incomplete.append("current_central_date_mismatch")
    control = payload["live_control"]
    if not _valid_control_binding(control, now=now):
        failed.append("live_control_not_frozen_or_malformed")
    elif not isinstance(control, Mapping) or control.get("sha256") != start_payload["live_control"].get("sha256"):
        failed.append("live_control_hash_changed")
    schedule = payload["schedule"]
    if not _valid_schedule_binding(schedule):
        failed.append("schedule_contract_not_exact_ten_paused")
    elif not isinstance(schedule, Mapping) or schedule.get("canonical_sha256") != start_payload["schedule"].get("canonical_sha256"):
        failed.append("schedule_evaluation_hash_changed")
    if not _valid_calendar_binding(payload["calendar"], market_date=market_date, now=now):
        incomplete.append("calendar_evidence_unavailable_or_invalid")
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(ARTIFACT_KEYS):
        incomplete.append("artifact_roster_invalid")
    else:
        start_at = _parse_timestamp(start.recorded_at) or now
        run_id = start_payload["run_id"]
        if not isinstance(run_id, str):
            failed.append("start_run_id_invalid")
        else:
            for key in ARTIFACT_KEYS:
                item_failed, item_incomplete = _artifact_reasons(
                    key,
                    artifacts[key],
                    run_id=run_id,
                    market_date=market_date,
                    start_at=start_at,
                    now=now,
                )
                failed.extend(item_failed)
                incomplete.extend(item_incomplete)
    return sorted(set(failed)), sorted(set(incomplete))


def _validate_day_envelope(
    envelope: EvidenceEnvelope,
    *,
    start: EvidenceEnvelope,
    earlier_days: tuple[EvidenceEnvelope, ...],
    now: dt.datetime,
) -> None:
    payload = _require_exact_fields(envelope.payload, _DAY_FIELDS, label="shadow day payload")
    if payload["payload_schema"] != DAY_SCHEMA:
        raise ValueError("shadow day payload schema is invalid")
    recorded_at = _parse_timestamp(envelope.recorded_at)
    if recorded_at is None or recorded_at > now:
        raise ValueError("shadow day is backfilled or future")
    market_date = payload["market_date"]
    if _parse_market_date(market_date) is None or _current_central_date(recorded_at) != market_date:
        raise ValueError("shadow day date is invalid")
    if not isinstance(payload["reasons"], (list, tuple)) or any(type(item) is not str for item in payload["reasons"]):
        raise ValueError("shadow day reasons are invalid")
    failed, incomplete = _evaluate_day_payload(start, payload, now=recorded_at)
    expected_status = "failed" if failed else ("incomplete" if incomplete else "clean")
    if payload["status"] != expected_status:
        raise ValueError("shadow day status does not match bound evidence")
    expected_reasons = sorted(set([*failed, *incomplete]))
    if list(payload["reasons"]) != expected_reasons:
        raise ValueError("shadow day reasons do not match bound evidence")
    expected_phase = _day_phase(start=start, status=expected_status, earlier_days=earlier_days)
    if payload["phase"] != expected_phase:
        raise ValueError("shadow day phase does not match state transition")


def _candidate_state(days: tuple[EvidenceEnvelope, ...]) -> tuple[bool, int]:
    if len(days) < 6:
        return False, 0
    terminal = days[-1].payload
    if terminal.get("status") != "clean" or terminal.get("phase") != "trial_complete":
        return False, 0
    trials = days[-5:]
    if any(day.payload.get("status") != "clean" for day in trials):
        return False, 0
    if [day.payload.get("phase") for day in trials] != [
        "five_day_trial",
        "five_day_trial",
        "five_day_trial",
        "five_day_trial",
        "trial_complete",
    ]:
        return False, 0
    qualification = days[-6].payload
    if qualification.get("status") != "clean" or qualification.get("phase") != "qualification_clean":
        return False, 0
    return True, 5


def _LedgerState(envelopes: tuple[EvidenceEnvelope, ...], *, now: dt.datetime) -> tuple[tuple[EvidenceEnvelope, ...], EvidenceEnvelope | None, EvidenceEnvelope | None, EvidenceEnvelope | None]:
    """Replay all admitted events; return day events, pending start, last day, report."""

    days: list[EvidenceEnvelope] = []
    pending: EvidenceEnvelope | None = None
    last_day: EvidenceEnvelope | None = None
    report: EvidenceEnvelope | None = None
    dates: set[str] = set()
    for envelope in envelopes:
        if envelope.kind == MANUAL_SHADOW_DAY_START_KIND:
            if report is not None or pending is not None:
                raise ValueError("shadow ledger has an invalid start transition")
            _validate_start_envelope(envelope, now=now)
            payload = envelope.payload
            market_date = payload["market_date"]
            if not isinstance(market_date, str) or market_date in dates:
                raise ValueError("shadow ledger has duplicate market date")
            phase, role, predecessor = _start_spec(last_day)
            if payload["phase"] != phase or payload["role"] != role or payload["predecessor_object_id"] != predecessor:
                raise ValueError("shadow ledger start predecessor transition is invalid")
            pending = envelope
        elif envelope.kind == MANUAL_SHADOW_DAY_RESULT_KIND:
            if report is not None or pending is None:
                raise ValueError("shadow ledger has an unbound day result")
            _validate_day_envelope(envelope, start=pending, earlier_days=tuple(days), now=now)
            payload = envelope.payload
            market_date = payload["market_date"]
            if not isinstance(market_date, str) or market_date in dates:
                raise ValueError("shadow ledger has duplicate market date")
            dates.add(market_date)
            days.append(envelope)
            last_day = envelope
            pending = None
        elif envelope.kind == MANUAL_SHADOW_FINAL_REPORT_KIND:
            if report is not None or pending is not None:
                raise ValueError("shadow ledger final report is not terminal")
            report = envelope
        else:
            raise ValueError("shadow ledger contains a disallowed evidence kind")
    if report is not None:
        _validate_report_envelope(report, days=tuple(days), now=now)
    return tuple(days), pending, last_day, report


def _validate_report_envelope(
    envelope: EvidenceEnvelope,
    *,
    days: tuple[EvidenceEnvelope, ...],
    now: dt.datetime,
) -> None:
    payload = _require_exact_fields(envelope.payload, _REPORT_FIELDS, label="shadow report payload")
    if payload["payload_schema"] != REPORT_SCHEMA:
        raise ValueError("shadow report payload schema is invalid")
    recorded_at = _parse_timestamp(envelope.recorded_at)
    if recorded_at is None or recorded_at > now or not days:
        raise ValueError("shadow report timestamp or ledger is invalid")
    candidate, streak = _candidate_state(days)
    expected = {
        "ledger_head_object_id": days[-1].object_id,
        "day_object_ids": [day.object_id for day in days],
        "status": "candidate" if candidate else "no_go",
        "phase": "readiness_candidate" if candidate else "readiness_no_go",
        "clean_trial_streak": streak if candidate else 0,
        "required_clean_trial_days": 5,
        "reasons": [] if candidate else ["full_ledger_not_terminal_candidate"],
    }
    for key, expected_value in expected.items():
        actual_value = list(payload[key]) if key in {"day_object_ids", "reasons"} and isinstance(payload[key], tuple) else payload[key]
        if actual_value != expected_value:
            raise ValueError("shadow report does not match complete ledger")


def _require_known_start(envelopes: tuple[EvidenceEnvelope, ...], object_id: str) -> EvidenceEnvelope:
    for envelope in envelopes:
        if envelope.object_id == object_id and envelope.kind == MANUAL_SHADOW_DAY_START_KIND:
            return envelope
    raise ValueError("shadow start record is not an admitted ledger object")


def _record_view(envelope: EvidenceEnvelope, *, path: Path | None = None) -> dict[str, object]:
    plain_payload = _plain_json(envelope.payload)
    if not isinstance(plain_payload, dict):
        raise ValueError("shadow record payload is invalid")
    view = plain_payload
    view.update(
        {
            "schema_version": envelope.schema_version,
            "kind": envelope.kind,
            "object_id": envelope.object_id,
            "effective_at": envelope.effective_at,
            "recorded_at": envelope.recorded_at,
            "analysis_only": envelope.analysis_only,
            "execution_authority": envelope.execution_authority,
            "can_submit_orders": envelope.can_submit_orders,
        }
    )
    if path is not None:
        view["record_path"] = str(path)
    return view


def admitted_shadow_record_view(admission: EvidenceAdmission) -> dict[str, object]:
    """Render a just-admitted immutable shadow object for analysis-only CLI output."""

    if not isinstance(admission, EvidenceAdmission):
        raise ValueError("shadow admission is invalid")
    return _record_view(admission.envelope, path=admission.path)


def load_shadow_record(object_id: str, *, expected_kind: str | None = None) -> EvidenceEnvelope:
    """Load one exact object only after verifying the pinned store journal."""

    if type(object_id) is not str or not object_id:
        raise ValueError("shadow record identity is invalid")
    envelopes = _store_envelopes()
    _LedgerState(envelopes, now=_as_utc(_utc_now()))
    matches = [item for item in envelopes if item.object_id == object_id]
    if len(matches) != 1:
        raise ValueError("shadow record is not an admitted ledger object")
    record = matches[0]
    if expected_kind is not None and record.kind != expected_kind:
        raise ValueError("shadow record kind is invalid")
    return record


def create_shadow_day_start_manifest(
    *,
    run_id: str,
    market_date: str,
    calendar_evidence: Mapping[str, object] | None,
    predecessor_object_id: str | None = None,
) -> EvidenceAdmission:
    """Admit a current-day start only from the canonical local source helpers."""

    now, effective_at = _now_stamp()
    _require_text(run_id, label="run_id")
    if _parse_market_date(market_date) is None:
        raise ValueError("market_date is invalid")
    if market_date != _current_central_date(now):
        raise ValueError("market_date must be the current Central date")
    control, control_valid = _control_binding(now)
    if not control_valid:
        raise ValueError("live control gate failed")
    schedule, schedule_valid = _schedule_binding()
    if not schedule_valid:
        raise ValueError("schedule gate failed")
    calendar = _calendar_binding(calendar_evidence, market_date=market_date)
    if not _valid_calendar_binding(calendar, market_date=market_date, now=now):
        raise ValueError("calendar gate failed")
    prior = _store_envelopes()
    days, pending, last_day, report = _LedgerState(prior, now=now)
    if pending is not None or report is not None:
        raise ValueError("shadow ledger does not allow another start")
    phase, role, expected_predecessor = _start_spec(last_day)
    if predecessor_object_id != expected_predecessor:
        raise ValueError("shadow predecessor record is missing or invalid")
    payload: dict[str, object] = {
        "payload_schema": START_SCHEMA,
        "run_id": run_id,
        "market_date": market_date,
        "role": role,
        "phase": phase,
        "predecessor_object_id": predecessor_object_id,
        "live_control": control,
        "schedule": schedule,
        "calendar": calendar,
    }

    def validate(snapshot: tuple[EvidenceEnvelope, ...], candidate: EvidenceEnvelope) -> None:
        replay_days, replay_pending, replay_last, replay_report = _LedgerState(snapshot, now=_as_utc(_utc_now()))
        if replay_pending is not None or replay_report is not None:
            raise ValueError("shadow ledger does not allow another start")
        _validate_start_envelope(candidate, now=_as_utc(_utc_now()))
        expected_phase, expected_role, expected_parent = _start_spec(replay_last)
        candidate_payload = candidate.payload
        if (
            candidate_payload["phase"] != expected_phase
            or candidate_payload["role"] != expected_role
            or candidate_payload["predecessor_object_id"] != expected_parent
            or candidate_payload["market_date"] in {day.payload["market_date"] for day in replay_days}
        ):
            raise ValueError("shadow start transition is invalid")

    return _admit(kind=MANUAL_SHADOW_DAY_START_KIND, effective_at=effective_at, payload=payload, validate=validate)


def adjudicate_shadow_day(
    *,
    start_object_id: str,
    artifacts: Mapping[str, Path] | None,
    calendar_evidence: Mapping[str, object] | None,
) -> EvidenceAdmission:
    """Admit exactly one current-day result for an authenticated pending start."""

    now, effective_at = _now_stamp()
    prior = _store_envelopes()
    days, pending, _last_day, report = _LedgerState(prior, now=now)
    if report is not None or pending is None or pending.object_id != start_object_id:
        raise ValueError("shadow start has no admissible pending transition")
    start = _require_known_start(prior, start_object_id)
    start_payload = start.payload
    market_date = start_payload["market_date"]
    run_id = start_payload["run_id"]
    if not isinstance(market_date, str) or not isinstance(run_id, str):
        raise ValueError("shadow start payload is invalid")
    if _current_central_date(now) != market_date:
        raise ValueError("shadow day must be adjudicated on its current Central date")
    control, _ = _control_binding(now)
    schedule, _ = _schedule_binding()
    calendar = _calendar_binding(calendar_evidence, market_date=market_date)
    artifact_paths = artifacts if isinstance(artifacts, Mapping) else {}
    artifact_bindings = {key: _artifact_binding(artifact_paths.get(key)) for key in ARTIFACT_KEYS}
    provisional: dict[str, object] = {
        "payload_schema": DAY_SCHEMA,
        "start_object_id": start.object_id,
        "run_id": run_id,
        "market_date": market_date,
        "role": start_payload["role"],
        "status": "incomplete",
        "phase": "repair_required",
        "predecessor_object_id": start_payload["predecessor_object_id"],
        "live_control": control,
        "schedule": schedule,
        "calendar": calendar,
        "artifacts": artifact_bindings,
        "reasons": [],
    }
    failed, incomplete = _evaluate_day_payload(start, provisional, now=now)
    unknown_artifacts = set(artifact_paths) - set(ARTIFACT_KEYS)
    if unknown_artifacts:
        incomplete.append("unknown_artifact_keys")
    status = "failed" if failed else ("incomplete" if incomplete else "clean")
    provisional["status"] = status
    provisional["phase"] = _day_phase(start=start, status=status, earlier_days=days)
    provisional["reasons"] = sorted(set([*failed, *incomplete]))

    def validate(snapshot: tuple[EvidenceEnvelope, ...], candidate: EvidenceEnvelope) -> None:
        replay_days, replay_pending, _replay_last, replay_report = _LedgerState(snapshot, now=_as_utc(_utc_now()))
        if replay_report is not None or replay_pending is None or replay_pending.object_id != start_object_id:
            raise ValueError("shadow start already has a day successor")
        _validate_day_envelope(candidate, start=replay_pending, earlier_days=replay_days, now=_as_utc(_utc_now()))

    return _admit(kind=MANUAL_SHADOW_DAY_RESULT_KIND, effective_at=effective_at, payload=provisional, validate=validate)


def build_shadow_streak_report() -> dict[str, object]:
    """Replay the complete pinned ledger and admit one terminal non-authorizing report."""

    now, effective_at = _now_stamp()
    prior = _store_envelopes()
    days, pending, _last_day, existing_report = _LedgerState(prior, now=now)
    if existing_report is not None:
        return _record_view(existing_report)
    if pending is not None or not days:
        raise ValueError("shadow ledger has no terminal day chain")
    candidate, streak = _candidate_state(days)
    payload: dict[str, object] = {
        "payload_schema": REPORT_SCHEMA,
        "ledger_head_object_id": days[-1].object_id,
        "day_object_ids": [day.object_id for day in days],
        "status": "candidate" if candidate else "no_go",
        "phase": "readiness_candidate" if candidate else "readiness_no_go",
        "clean_trial_streak": streak if candidate else 0,
        "required_clean_trial_days": 5,
        "reasons": [] if candidate else ["full_ledger_not_terminal_candidate"],
    }

    def validate(snapshot: tuple[EvidenceEnvelope, ...], candidate_envelope: EvidenceEnvelope) -> None:
        replay_days, replay_pending, _replay_last, replay_report = _LedgerState(snapshot, now=_as_utc(_utc_now()))
        if replay_pending is not None or replay_report is not None or not replay_days:
            raise ValueError("shadow ledger is not reportable")
        _validate_report_envelope(candidate_envelope, days=replay_days, now=_as_utc(_utc_now()))

    admission = _admit(kind=MANUAL_SHADOW_FINAL_REPORT_KIND, effective_at=effective_at, payload=payload, validate=validate)
    return _record_view(admission.envelope, path=admission.path)
