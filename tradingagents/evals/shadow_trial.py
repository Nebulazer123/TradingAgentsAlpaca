"""Sealed, non-authorizing evidence for the manual shadow-day trial.

This module deliberately has no broker, provider, scheduler, live-control, or
order-writing client.  It only consumes caller-supplied local evidence and the
public source-read-only schedule evaluator, then publishes immutable records
under the repository's ``results/manual_shadow`` root.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.evals.automation_health_audit import (
    PREDEPLOYMENT_PAUSED_PHASE,
    default_automation_root,
    evaluate_schedule_contract,
)
from tradingagents.policy.live_control import load_live_control_state

UTC = dt.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
START_SCHEMA = "shadow_day_start_v2"
DAY_SCHEMA = "shadow_day_adjudication_v2"
STREAK_SCHEMA = "shadow_streak_report_v2"
ARTIFACT_KEYS = ("safety_sentinel", "paper_tournament")
PHASES = (
    "qualification_pending",
    "qualification_clean",
    "repair_required",
    "repair_in_progress",
    "five_day_trial",
    "trial_complete",
    "readiness_no_go",
    "readiness_candidate",
)
_KIND_SCHEMA = {
    "shadow_day_start": START_SCHEMA,
    "shadow_day_adjudication": DAY_SCHEMA,
    "shadow_streak_report": STREAK_SCHEMA,
}
_KIND_PREFIX = {
    "shadow_day_start": "shadow-day-start",
    "shadow_day_adjudication": "shadow-day-adjudication",
    "shadow_streak_report": "shadow-streak-report",
}
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


def _utc_now() -> dt.datetime:
    """Private clock seam. Production commands never expose a time override."""

    return dt.datetime.now(tz=UTC)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _manual_shadow_root() -> Path:
    return _repo_root() / "results" / "manual_shadow"


def _default_schedule_contract_path() -> Path:
    return _repo_root() / "config" / "automation_schedule_contract.json"


def _default_role_contract_path() -> Path:
    return _repo_root() / "config" / "automation_roles.json"


def _record_id() -> str:
    return uuid.uuid4().hex


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError("trusted clock must be timezone-aware")
    return value.astimezone(UTC)


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _parse_market_date(value: Any) -> dt.date | None:
    if type(value) is not str:
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc


def canonical_json_sha256(value: Any) -> str:
    """Return the SHA-256 of unambiguous canonical JSON."""

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


def _read_regular_json(path_value: str | Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Read a regular non-symlink file once via no-follow descriptor semantics."""

    path = Path(path_value).expanduser().absolute()
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
    evidence["canonical_sha256"] = canonical_json_sha256(payload)
    evidence["status"] = "captured"
    return evidence, payload


def _evidence_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: evidence.get(key)
        for key in ("path", "status", "sha256", "canonical_sha256", "size_bytes", "modified_at")
    }


def _is_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _non_authorizing(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("analysis_only") is True
        and payload.get("execution_authority") == "none"
        and payload.get("can_submit_orders") is False
    )


def _current_central_date(now: dt.datetime) -> str:
    return now.astimezone(CENTRAL).date().isoformat()


def _calendar_binding(
    calendar_evidence: Mapping[str, Any] | None,
    *,
    market_date: str,
    now: dt.datetime,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(calendar_evidence, Mapping):
        return {"status": "invalid", "reason": "calendar_evidence_missing"}, False
    observed_at = _parse_timestamp(calendar_evidence.get("observed_at"))
    sessions = calendar_evidence.get("sessions")
    exact_session = (
        isinstance(sessions, list)
        and len(sessions) == 1
        and isinstance(sessions[0], Mapping)
        and sessions[0].get("date") == market_date
    )
    valid = (
        calendar_evidence.get("kind") == "alpaca_regular_equities_calendar"
        and calendar_evidence.get("market_date") == market_date
        and observed_at is not None
        and observed_at <= now
        and _current_central_date(observed_at) == market_date
        and exact_session
    )
    return {
        "status": "captured" if valid else "invalid",
        "market_date": market_date,
        "observed_at": calendar_evidence.get("observed_at"),
        "sessions": sessions if isinstance(sessions, list) else None,
        "canonical_sha256": canonical_json_sha256(dict(calendar_evidence)),
    }, valid


def _control_binding(path: str | Path) -> tuple[dict[str, Any], bool]:
    evidence, payload = _read_regular_json(path)
    loaded_state, issues = load_live_control_state(path, now=_utc_now())
    frozen_issue_only = bool(issues) and all(
        isinstance(issue, str) and issue.startswith("live control state is frozen:")
        for issue in issues
    )
    valid = (
        evidence["status"] == "captured"
        and isinstance(payload, Mapping)
        and payload.get("frozen") is True
        and type(payload.get("reason")) is str
        and bool(payload["reason"].strip())
        and _parse_timestamp(payload.get("dead_man_expires_at")) is not None
        and loaded_state is not None
        and frozen_issue_only
    )
    bound = _evidence_projection(evidence)
    bound["frozen"] = payload.get("frozen") if isinstance(payload, Mapping) else None
    return bound, valid


def _schedule_binding(
    *,
    contract_path: str | Path,
    automation_root: str | Path,
    role_contract_path: str | Path,
) -> tuple[dict[str, Any], bool]:
    """Use Task 2's public, source-read-only evaluator exactly once per check."""

    try:
        result = evaluate_schedule_contract(
            contract_path=contract_path,
            automation_root=automation_root,
            role_contract_path=role_contract_path,
            deployment_phase=PREDEPLOYMENT_PAUSED_PHASE,
        )
    except Exception as exc:  # noqa: BLE001 - a source read failure is a failed gate.
        result = {"error": f"schedule evaluator failed: {type(exc).__name__}"}
    rows = result.get("automations") if isinstance(result, Mapping) else None
    row_ids = [row.get("automation_id") for row in rows] if isinstance(rows, list) else []
    valid = (
        isinstance(result, Mapping)
        and result.get("contract_status") == "pass"
        and result.get("safe_predeployment") is True
        and result.get("deployment_proven") is False
        and result.get("automation_count") == 10
        and result.get("configured_count") == 10
        and result.get("paused_count") == 10
        and result.get("issues") == []
        and isinstance(rows, list)
        and len(rows) == 10
        and set(row_ids) == EXPECTED_AUTOMATION_IDS
        and all(
            isinstance(row, Mapping)
            and row.get("status") == "match"
            and row.get("config_status") == "PAUSED"
            and row.get("mismatches") == []
            for row in rows
        )
    )
    return {
        "status": "captured" if valid else "invalid",
        "contract_path": str(Path(contract_path).absolute()),
        "automation_root": str(Path(automation_root).absolute()),
        "role_contract_path": str(Path(role_contract_path).absolute()),
        "result": dict(result),
        "canonical_sha256": canonical_json_sha256(result),
    }, valid


def _seal(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    schema = _KIND_SCHEMA[kind]
    record = {
        "schema_version": schema,
        "kind": kind,
        "record_id": _record_id(),
        "recorded_at": _as_utc(_utc_now()).isoformat(timespec="seconds"),
        **dict(payload),
    }
    record["payload_sha256"] = canonical_json_sha256(record)
    return record


def _validate_sealed_record(record: Mapping[str, Any], *, expected_kind: str | None = None) -> None:
    kind = record.get("kind")
    if kind not in _KIND_SCHEMA or (expected_kind is not None and kind != expected_kind):
        raise ValueError("sealed record kind is invalid")
    if record.get("schema_version") != _KIND_SCHEMA[kind]:
        raise ValueError("sealed record schema is invalid")
    record_id = record.get("record_id")
    if type(record_id) is not str or len(record_id) != 32 or any(
        character not in "0123456789abcdef" for character in record_id
    ):
        raise ValueError("sealed record id is invalid")
    if _parse_timestamp(record.get("recorded_at")) is None:
        raise ValueError("sealed record timestamp is invalid")
    digest = record.get("payload_sha256")
    unsigned = {key: value for key, value in record.items() if key != "payload_sha256"}
    if not _is_sha256(digest) or digest != canonical_json_sha256(unsigned):
        raise ValueError("sealed record digest is invalid")
    if not _non_authorizing(record):
        raise ValueError("sealed record authority is invalid")


def _open_manual_shadow_root(*, create: bool) -> tuple[Path, int]:
    """Open the private root component-by-component without following links."""

    root = _manual_shadow_root().expanduser().absolute()
    if not root.is_absolute():
        raise ValueError("manual shadow root is invalid")
    try:
        descriptor = os.open(
            root.anchor,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ValueError("manual shadow root is unavailable") from exc
    try:
        for component in root.parts[1:]:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
            try:
                child = os.open(
                    component,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except OSError as exc:
                raise ValueError("manual shadow root contains a symlink or is unavailable") from exc
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child)
                raise ValueError("manual shadow root is not a directory")
            os.close(descriptor)
            descriptor = child
    except Exception:
        os.close(descriptor)
        raise
    return root, descriptor


def _record_filename(record: Mapping[str, Any]) -> str:
    kind = record.get("kind")
    prefix = _KIND_PREFIX.get(kind)
    if prefix is None:
        raise ValueError("sealed record kind is invalid")
    return f"{prefix}-{record['record_id']}.json"


def write_shadow_trial_packet(packet: Mapping[str, Any]) -> Path:
    """Publish exactly one sealed record under the fixed no-follow root."""

    _validate_sealed_record(packet)
    root, root_descriptor = _open_manual_shadow_root(create=True)
    filename = _record_filename(packet)
    try:
        descriptor = os.open(
            filename,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=root_descriptor,
        )
    except FileExistsError as exc:
        os.close(root_descriptor)
        raise ValueError("manual shadow record already exists") from exc
    except OSError as exc:
        os.close(root_descriptor)
        raise ValueError("manual shadow record cannot be published") from exc
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write((json.dumps(dict(packet), sort_keys=True, indent=2) + "\n").encode("utf-8"))
            destination.flush()
            os.fsync(destination.fileno())
        with suppress(OSError):
            os.fsync(root_descriptor)
    finally:
        os.close(root_descriptor)
    return root / filename


def load_shadow_record(path_value: str | Path, *, expected_kind: str | None = None) -> dict[str, Any]:
    """Load only a sealed immutable record directly beneath the private root."""

    root, root_descriptor = _open_manual_shadow_root(create=False)
    path = Path(path_value).expanduser().absolute()
    if path.parent != root:
        os.close(root_descriptor)
        raise ValueError("shadow record is outside the manual shadow root")
    if path.is_symlink():
        os.close(root_descriptor)
        raise ValueError("shadow record symlink is invalid")
    try:
        descriptor = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_descriptor)
    except OSError as exc:
        os.close(root_descriptor)
        raise ValueError("shadow record is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("shadow record is not a regular file")
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read()
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_descriptor)
    try:
        record = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("sealed shadow record is malformed") from exc
    if type(record) is not dict:
        raise ValueError("sealed shadow record is malformed")
    _validate_sealed_record(record, expected_kind=expected_kind)
    if path.name != _record_filename(record):
        raise ValueError("sealed shadow record filename is invalid")
    if record["kind"] == "shadow_day_adjudication":
        _validate_day_parent_binding(record)
    return record


def _record_binding(path: Path, record: Mapping[str, Any]) -> dict[str, str]:
    return {
        "path": str(path.absolute()),
        "record_id": str(record["record_id"]),
        "payload_sha256": str(record["payload_sha256"]),
    }


def _load_bound_record(binding: Any, *, expected_kind: str) -> tuple[dict[str, Any], Path]:
    if not isinstance(binding, Mapping) or set(binding) != {"path", "record_id", "payload_sha256"}:
        raise ValueError("immutable parent binding is invalid")
    if not isinstance(binding.get("path"), str) or not _is_sha256(binding.get("payload_sha256")):
        raise ValueError("immutable parent binding is invalid")
    path = Path(binding["path"])
    record = load_shadow_record(path, expected_kind=expected_kind)
    if record.get("record_id") != binding["record_id"] or record.get("payload_sha256") != binding["payload_sha256"]:
        raise ValueError("immutable parent binding does not match record")
    return record, path


def _validate_day_parent_binding(record: Mapping[str, Any]) -> None:
    binding = record.get("start_manifest")
    start, _ = _load_bound_record(binding, expected_kind="shadow_day_start")
    if record.get("start_manifest_sha256") != start.get("payload_sha256"):
        raise ValueError("immutable start-manifest digest does not match")
    if record.get("ledger_id") != start.get("ledger_id") or record.get("run_id") != start.get("run_id"):
        raise ValueError("immutable start-manifest ledger binding does not match")


def _predecessor_binding(path_value: Path | None) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    if path_value is None:
        return None, None
    record = load_shadow_record(path_value, expected_kind="shadow_day_adjudication")
    return _record_binding(path_value, record), record


def _valid_predecessor(phase: str, predecessor: Mapping[str, Any] | None) -> bool:
    if phase == "qualification_pending":
        return predecessor is None or (
            predecessor.get("status") == "clean" and predecessor.get("phase") == "repair_in_progress"
        )
    if phase == "five_day_trial":
        return predecessor is not None and predecessor.get("status") == "clean" and predecessor.get(
            "phase"
        ) in {"qualification_clean", "five_day_trial"}
    if phase == "repair_in_progress":
        return predecessor is not None and predecessor.get("phase") == "repair_required" and predecessor.get(
            "status"
        ) in {"failed", "incomplete"}
    return False


def _start_predecessor_valid(start: Mapping[str, Any]) -> bool:
    """Authenticate the predecessor record before it can drive a transition."""

    binding = start.get("predecessor")
    if binding is None:
        return start.get("phase") == "qualification_pending"
    try:
        predecessor, _ = _load_bound_record(binding, expected_kind="shadow_day_adjudication")
    except ValueError:
        return False
    return predecessor.get("ledger_id") == start.get("ledger_id") and _valid_predecessor(
        str(start.get("phase")), predecessor
    )


def create_shadow_day_start_manifest(
    *,
    run_id: str,
    ledger_id: str,
    market_date: str,
    live_control_path: str | Path,
    schedule_contract_path: str | Path | None = None,
    automation_root: str | Path | None = None,
    role_contract_path: str | Path | None = None,
    calendar_evidence: Mapping[str, Any] | None,
    phase: str = "qualification_pending",
    predecessor_path: Path | None = None,
) -> dict[str, Any]:
    """Create a sealed, current-day start record without mutating any source."""

    now = _as_utc(_utc_now())
    if type(run_id) is not str or not run_id.strip() or type(ledger_id) is not str or not ledger_id.strip():
        raise ValueError("run_id and ledger_id are required")
    if phase not in {"qualification_pending", "five_day_trial", "repair_in_progress"}:
        raise ValueError("start phase is invalid")
    if _parse_market_date(market_date) is None:
        raise ValueError("market_date is invalid")
    if market_date != _current_central_date(now):
        raise ValueError("market_date must be the current Central date")
    contract = schedule_contract_path or _default_schedule_contract_path()
    roles = role_contract_path or _default_role_contract_path()
    automations = automation_root or default_automation_root()
    control, control_valid = _control_binding(live_control_path)
    schedule, schedule_valid = _schedule_binding(
        contract_path=contract,
        automation_root=automations,
        role_contract_path=roles,
    )
    calendar, calendar_valid = _calendar_binding(calendar_evidence, market_date=market_date, now=now)
    predecessor_binding, predecessor = _predecessor_binding(predecessor_path)
    predecessor_valid = _valid_predecessor(phase, predecessor)
    if predecessor is not None and predecessor.get("ledger_id") != ledger_id:
        predecessor_valid = False
    return _seal(
        "shadow_day_start",
        {
            "run_id": run_id,
            "ledger_id": ledger_id,
            "market_date": market_date,
            "phase": phase,
            "role": {"qualification_pending": "qualification", "five_day_trial": "trial", "repair_in_progress": "repair"}[phase],
            "predecessor": predecessor_binding,
            "live_control": control,
            "schedule": schedule,
            "calendar": calendar,
            "start_gates": {
                "current_date": "pass",
                "live_control": "pass" if control_valid else "fail",
                "schedule": "pass" if schedule_valid else "fail",
                "calendar": "pass" if calendar_valid else "fail",
                "predecessor": "pass" if predecessor_valid else "fail",
            },
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )


def _artifact_reasons(
    key: str,
    payload: Mapping[str, Any],
    *,
    run_id: str,
    market_date: str,
    start_at: dt.datetime,
    now: dt.datetime,
) -> tuple[list[str], list[str]]:
    failed: list[str] = []
    incomplete: list[str] = []
    expected_kind = "safety_sentinel_audit" if key == "safety_sentinel" else "paper_tournament_run"
    if payload.get("kind") != expected_kind:
        failed.append(f"{key}_kind_invalid")
    if payload.get("run_id") != run_id:
        failed.append(f"{key}_cross_run")
    if payload.get("market_date") != market_date:
        failed.append(f"{key}_market_date_mismatch")
    if not _non_authorizing(payload):
        failed.append(f"{key}_authority_invalid")
    generated_at = _parse_timestamp(payload.get("generated_at"))
    if generated_at is None:
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
        elif not isinstance(payload.get("submitted"), list) or len(payload["submitted"]) != count:
            failed.append("paper_tournament_submissions_invalid")
        if payload.get("status") not in {"HOLD", "NO_PAPER_SIGNAL", "COMPLETE"}:
            failed.append("paper_tournament_status_invalid")
        if payload.get("status") in {"HOLD", "NO_PAPER_SIGNAL"} and count != 0:
            failed.append("paper_tournament_hold_has_submissions")
    return failed, incomplete


def _day_phase(start_phase: str, status: str) -> str:
    if status != "clean":
        return "repair_required"
    if start_phase == "qualification_pending":
        return "qualification_clean"
    if start_phase == "repair_in_progress":
        return "repair_in_progress"
    return "five_day_trial"


def adjudicate_shadow_day(
    *,
    start_manifest_path: Path,
    artifacts: Mapping[str, Path],
    calendar_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Adjudicate a sealed current-day start record and exactly two artifacts."""

    start = load_shadow_record(start_manifest_path, expected_kind="shadow_day_start")
    now = _as_utc(_utc_now())
    failed: list[str] = []
    incomplete: list[str] = []
    market_date = start["market_date"]
    if market_date != _current_central_date(now):
        incomplete.append("current_central_date_mismatch")
    start_at = _parse_timestamp(start.get("recorded_at"))
    if start_at is None or start_at > now or _current_central_date(start_at or now) != market_date:
        incomplete.append("start_manifest_timestamp_invalid_or_not_current")
    start_gates = start.get("start_gates") if isinstance(start.get("start_gates"), Mapping) else {}
    for gate_name, gate_status in start_gates.items():
        if gate_status != "pass":
            failed.append(f"{gate_name}_start_gate_failed")
    if not _start_predecessor_valid(start):
        failed.append("predecessor_start_lineage_invalid")
    control = start.get("live_control")
    if not isinstance(control, Mapping) or not isinstance(control.get("path"), str):
        failed.append("live_control_start_binding_invalid")
        current_control: dict[str, Any] = {"status": "invalid"}
    else:
        current_control, current_control_valid = _control_binding(control["path"])
        if not current_control_valid:
            failed.append("live_control_not_frozen_or_malformed")
        elif (
            current_control.get("sha256") != control.get("sha256")
            or current_control.get("size_bytes") != control.get("size_bytes")
        ):
            failed.append("live_control_hash_changed")
    schedule = start.get("schedule")
    if not isinstance(schedule, Mapping):
        failed.append("schedule_start_binding_invalid")
        current_schedule: dict[str, Any] = {"status": "invalid"}
    else:
        current_schedule, schedule_valid = _schedule_binding(
            contract_path=str(schedule.get("contract_path") or ""),
            automation_root=str(schedule.get("automation_root") or ""),
            role_contract_path=str(schedule.get("role_contract_path") or ""),
        )
        if not schedule_valid:
            failed.append("schedule_contract_not_exact_ten_paused")
        elif current_schedule.get("canonical_sha256") != schedule.get("canonical_sha256"):
            failed.append("schedule_evaluation_hash_changed")
    calendar, calendar_valid = _calendar_binding(calendar_evidence, market_date=market_date, now=now)
    if not calendar_valid:
        incomplete.append("calendar_evidence_unavailable_or_invalid")
    keys = set(artifacts) if isinstance(artifacts, Mapping) else set()
    if keys - set(ARTIFACT_KEYS):
        incomplete.append("unknown_artifact_keys")
    if set(ARTIFACT_KEYS) - keys:
        incomplete.append("missing_artifact_keys")
    artifact_evidence: dict[str, Any] = {}
    for key in ARTIFACT_KEYS:
        if key not in keys:
            continue
        evidence, payload = _read_regular_json(artifacts[key])
        artifact_evidence[key] = _evidence_projection(evidence)
        if evidence["status"] != "captured" or payload is None:
            incomplete.append(f"{key}_unreadable")
            continue
        artifact_evidence[key].update(
            {
                "kind": payload.get("kind"),
                "run_id": payload.get("run_id"),
                "market_date": payload.get("market_date"),
                "generated_at": payload.get("generated_at"),
            }
        )
        artifact_failed, artifact_incomplete = _artifact_reasons(
            key,
            payload,
            run_id=start["run_id"],
            market_date=market_date,
            start_at=start_at or now,
            now=now,
        )
        failed.extend(artifact_failed)
        incomplete.extend(artifact_incomplete)
    status = "failed" if failed else ("incomplete" if incomplete else "clean")
    phase = _day_phase(start["phase"], status)
    return _seal(
        "shadow_day_adjudication",
        {
            "run_id": start["run_id"],
            "ledger_id": start["ledger_id"],
            "market_date": market_date,
            "role": start["role"],
            "status": status,
            "phase": phase,
            "start_manifest": _record_binding(start_manifest_path, start),
            "start_manifest_sha256": start["payload_sha256"],
            "predecessor": start.get("predecessor"),
            "live_control": current_control,
            "schedule": current_schedule,
            "calendar": calendar,
            "artifacts": artifact_evidence,
            "reasons": sorted(set([*failed, *incomplete])),
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "phase_catalog": list(PHASES),
        },
    )


def _record_current_date_valid(record: Mapping[str, Any], start: Mapping[str, Any]) -> bool:
    recorded_at = _parse_timestamp(record.get("recorded_at"))
    return (
        recorded_at is not None
        and recorded_at <= _utc_now()
        and _current_central_date(recorded_at) == record.get("market_date")
        and start.get("market_date") == record.get("market_date")
    )


def build_shadow_streak_report(day_record_paths: Sequence[Path]) -> dict[str, Any]:
    """Validate a sealed lineage and count only the final clean five-day segment."""

    reasons: list[str] = []
    accepted: list[dict[str, Any]] = []
    dates: set[str] = set()
    previous_path: Path | None = None
    active_qualification = False
    streak = 0
    ledger_id: str | None = None
    for path in day_record_paths:
        try:
            day = load_shadow_record(path, expected_kind="shadow_day_adjudication")
            start, start_path = _load_bound_record(day.get("start_manifest"), expected_kind="shadow_day_start")
        except ValueError as exc:
            reasons.append(f"invalid_day_record:{exc}")
            active_qualification = False
            streak = 0
            continue
        if not _record_current_date_valid(day, start):
            reasons.append("backfilled_or_future_day_record")
            active_qualification = False
            streak = 0
            continue
        date = day.get("market_date")
        if date in dates:
            reasons.append("duplicate_market_date")
            active_qualification = False
            streak = 0
            continue
        dates.add(str(date))
        if ledger_id is None:
            ledger_id = day.get("ledger_id")
        if day.get("ledger_id") != ledger_id or start.get("ledger_id") != ledger_id:
            reasons.append("cross_ledger_record")
            active_qualification = False
            streak = 0
            continue
        predecessor = start.get("predecessor")
        if previous_path is None:
            if predecessor is not None:
                reasons.append("initial_predecessor_invalid")
        else:
            try:
                _predecessor_record, predecessor_path = _load_bound_record(
                    predecessor,
                    expected_kind="shadow_day_adjudication",
                )
            except ValueError:
                reasons.append("predecessor_chain_invalid")
            else:
                if predecessor_path != previous_path.absolute():
                    reasons.append("predecessor_chain_invalid")
        previous_path = Path(path).absolute()
        accepted.append(
            {
                "path": str(Path(path).absolute()),
                "record_id": day["record_id"],
                "payload_sha256": day["payload_sha256"],
                "market_date": date,
                "start_manifest_path": str(start_path),
            }
        )
        if day.get("status") != "clean":
            if day.get("phase") != "repair_required":
                reasons.append("failed_day_transition_invalid")
            active_qualification = False
            streak = 0
            continue
        if day.get("phase") == "repair_in_progress":
            active_qualification = False
            streak = 0
            continue
        if day.get("phase") == "qualification_clean":
            active_qualification = True
            streak = 0
            continue
        if day.get("phase") == "five_day_trial" and active_qualification:
            streak += 1
            continue
        reasons.append("clean_day_transition_invalid")
        active_qualification = False
        streak = 0
    candidate = bool(day_record_paths) and not reasons and active_qualification and streak == 5
    phase = "readiness_candidate" if candidate else "readiness_no_go"
    return _seal(
        "shadow_streak_report",
        {
            "ledger_id": ledger_id,
            "status": "candidate" if candidate else "no_go",
            "phase": phase,
            "phase_history": ["qualification_pending", "qualification_clean", "five_day_trial", "trial_complete", phase]
            if candidate
            else ["qualification_pending", "repair_required", "readiness_no_go"],
            "clean_trial_streak": streak if candidate else 0,
            "required_clean_trial_days": 5,
            "day_records": accepted,
            "reasons": sorted(set(reasons)),
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "phase_catalog": list(PHASES),
        },
    )
