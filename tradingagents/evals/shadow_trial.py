"""Fail-closed, file-only evidence for a manual shadow qualification trial.

This module is deliberately an observer.  It never creates a broker client or
changes policy/scheduling state: callers provide already-written local evidence
files, which are captured once and bound by byte and canonical JSON digests.
"""

from __future__ import annotations

import datetime as dt
import errno
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")
START_SCHEMA = "shadow_day_start_v1"
DAY_SCHEMA = "shadow_day_adjudication_v1"
STREAK_SCHEMA = "shadow_streak_report_v1"
DEFAULT_MAX_EVIDENCE_AGE_MINUTES = 90.0
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


def _as_utc(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(tz=UTC)
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
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
    """Return a stable JSON representation or reject ambiguous/non-JSON data."""

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
    """Hash a canonical JSON value; exported for explicit evidence binding."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _read_json_evidence(path_value: str | Path) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    """Read one regular, non-symlink JSON source once and bind its exact bytes."""

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
        evidence["status"] = "not_regular_file"
        return evidence, None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return evidence, None
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
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
    evidence["sha256"] = hashlib.sha256(raw).hexdigest()
    evidence["size_bytes"] = len(raw)
    evidence["modified_at"] = dt.datetime.fromtimestamp(file_stat.st_mtime, tz=UTC).isoformat(
        timespec="seconds"
    )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        evidence["status"] = "malformed_json"
        return evidence, None
    if not isinstance(payload, dict):
        evidence["status"] = "invalid_top_level"
        return evidence, None
    try:
        evidence["canonical_sha256"] = canonical_json_sha256(payload)
    except ValueError:
        evidence["status"] = "noncanonical_json"
        return evidence, None
    evidence["status"] = "captured"
    return evidence, payload


def _is_regular_market_day(value: str, validator: Callable[[str], bool] | None = None) -> bool:
    parsed = _parse_market_date(value)
    if parsed is None:
        return False
    if validator is not None:
        try:
            return validator(value) is True
        except Exception:  # Fail closed if a supplied calendar cannot answer.
            return False
    # This deterministic local fallback can establish weekends as non-market;
    # callers with an exchange calendar may provide the stricter validator.
    return parsed.weekday() < 5


def _automation_status(payload: Mapping[str, Any] | None) -> str:
    if payload is None:
        return "invalid"
    entries = payload.get("automations")
    if not isinstance(entries, list) or not entries:
        return "invalid"
    statuses: list[str] = []
    for item in entries:
        if not isinstance(item, Mapping) or not isinstance(item.get("status"), str):
            return "invalid"
        statuses.append(item["status"].upper())
    return "paused" if all(item == "PAUSED" for item in statuses) else "unpaused"


def _bound_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: evidence.get(key)
        for key in ("path", "status", "sha256", "canonical_sha256", "size_bytes", "modified_at")
    }


def _non_authorizing(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("analysis_only") is True
        and payload.get("execution_authority") == "none"
        and payload.get("can_submit_orders") is False
    )


def create_shadow_day_start_manifest(
    *,
    run_id: str,
    market_date: str,
    live_control_path: str | Path,
    automation_evidence_path: str | Path,
    phase: str = "qualification_pending",
    artifact_paths: Mapping[str, str | Path] | None = None,
    now: dt.datetime | None = None,
    market_day_validator: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Capture immutable pre-run state without changing any state.

    ``artifact_paths`` is optional because later runtime artifacts generally do
    not exist at day start.  When supplied, it binds pre-existing evidence by
    exact path, raw digest, size, and canonical digest for replay detection.
    """

    generated_at = _as_utc(now)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id is required")
    if phase not in PHASES:
        raise ValueError("phase is invalid")
    if _parse_market_date(market_date) is None:
        raise ValueError("market_date is invalid")
    if market_date != generated_at.astimezone(CENTRAL).date().isoformat():
        raise ValueError("market_date must be the current Central date")
    if not _is_regular_market_day(market_date, market_day_validator):
        raise ValueError("market_date is not a regular market day")

    live_control, control_payload = _read_json_evidence(live_control_path)
    automation, automation_payload = _read_json_evidence(automation_evidence_path)
    artifacts: dict[str, dict[str, Any]] = {}
    if artifact_paths is not None:
        unknown = set(artifact_paths) - set(ARTIFACT_KEYS)
        if unknown:
            raise ValueError("artifact_paths contains unknown keys")
        for key, path in artifact_paths.items():
            evidence, _ = _read_json_evidence(path)
            artifacts[key] = _bound_evidence(evidence)
    return {
        "schema_version": START_SCHEMA,
        "kind": "shadow_day_start",
        "run_id": run_id,
        "market_date": market_date,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "phase": phase,
        "role": "qualification" if phase in {"qualification_pending", "repair_in_progress"} else "trial",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "start_state": {
            "live_control": _bound_evidence(live_control),
            "live_control_frozen": control_payload.get("frozen") if control_payload else None,
            "automation_evidence": _bound_evidence(automation),
            "automation_status": _automation_status(automation_payload),
        },
        "artifact_bindings": artifacts,
    }


def _validate_start_manifest(start_manifest: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if start_manifest.get("schema_version") != START_SCHEMA:
        reasons.append("start_manifest_schema_invalid")
    if not isinstance(start_manifest.get("run_id"), str) or not start_manifest["run_id"].strip():
        reasons.append("start_manifest_run_id_invalid")
    if _parse_market_date(start_manifest.get("market_date")) is None:
        reasons.append("start_manifest_market_date_invalid")
    if _parse_timestamp(start_manifest.get("generated_at")) is None:
        reasons.append("start_manifest_timestamp_invalid")
    if start_manifest.get("phase") not in PHASES:
        reasons.append("start_manifest_phase_invalid")
    if not _non_authorizing(start_manifest):
        reasons.append("start_manifest_authority_invalid")
    state = start_manifest.get("start_state")
    if not isinstance(state, Mapping):
        reasons.append("start_manifest_start_state_invalid")
        return reasons
    for key in ("live_control", "automation_evidence"):
        evidence = state.get(key)
        if not isinstance(evidence, Mapping) or not isinstance(evidence.get("path"), str):
            reasons.append(f"start_manifest_{key}_invalid")
    if state.get("automation_status") not in {"paused", "unpaused", "invalid"}:
        reasons.append("start_manifest_automation_status_invalid")
    if not isinstance(start_manifest.get("artifact_bindings"), Mapping):
        reasons.append("start_manifest_artifact_bindings_invalid")
    return reasons


def _compare_start_evidence(
    start_manifest: Mapping[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]], Mapping[str, Any] | None]:
    reasons: list[str] = []
    observed: dict[str, dict[str, Any]] = {}
    automation_payload: Mapping[str, Any] | None = None
    state = start_manifest.get("start_state")
    if not isinstance(state, Mapping):
        return ["start_manifest_start_state_invalid"], observed, None
    for key in ("live_control", "automation_evidence"):
        bound = state.get(key)
        if not isinstance(bound, Mapping) or not isinstance(bound.get("path"), str):
            reasons.append(f"start_manifest_{key}_invalid")
            continue
        evidence, payload = _read_json_evidence(bound["path"])
        observed[key] = _bound_evidence(evidence)
        if evidence.get("status") != "captured":
            reasons.append(f"{key}_unreadable")
        elif evidence.get("sha256") != bound.get("sha256") or evidence.get("size_bytes") != bound.get("size_bytes"):
            reasons.append(f"{key}_hash_changed")
        if key == "automation_evidence":
            automation_payload = payload
    if _automation_status(automation_payload) != "paused":
        reasons.append("automation_unpaused")
    return reasons, observed, automation_payload


def _artifact_reasons(
    key: str,
    payload: Mapping[str, Any],
    *,
    run_id: str,
    market_date: str,
    start_at: dt.datetime,
    now: dt.datetime,
    max_evidence_age_minutes: float,
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
    elif generated_at < start_at or generated_at > now + dt.timedelta(minutes=5):
        incomplete.append(f"{key}_timestamp_out_of_window")
    elif now - generated_at > dt.timedelta(minutes=max_evidence_age_minutes):
        incomplete.append(f"{key}_stale")
    if key == "safety_sentinel":
        if payload.get("status") not in {"CLEAR", "HOLD", "FROZEN"}:
            failed.append("safety_sentinel_status_invalid")
    else:
        if payload.get("status") not in {"HOLD", "NO_PAPER_SIGNAL", "COMPLETE"}:
            failed.append("paper_tournament_status_invalid")
        submitted = payload.get("submitted")
        if not isinstance(payload.get("submitted_count"), int) or payload["submitted_count"] < 0:
            failed.append("paper_tournament_submission_count_invalid")
        elif not isinstance(submitted, list) or len(submitted) != payload["submitted_count"]:
            failed.append("paper_tournament_submissions_invalid")
        if payload.get("status") in {"HOLD", "NO_PAPER_SIGNAL"} and payload.get("submitted_count") != 0:
            failed.append("paper_tournament_hold_has_submissions")
    return failed, incomplete


def _day_phase(start_phase: str, status: str) -> str:
    if status != "clean":
        return "repair_required"
    if start_phase == "qualification_pending":
        return "qualification_clean"
    if start_phase == "repair_required":
        return "repair_in_progress"
    return "five_day_trial"


def adjudicate_shadow_day(
    start_manifest: Mapping[str, Any],
    artifacts: Mapping[str, Path],
    *,
    now: dt.datetime | None = None,
    max_evidence_age_minutes: float = DEFAULT_MAX_EVIDENCE_AGE_MINUTES,
    market_day_validator: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Adjudicate exactly two immutable local artifacts; absence never means success."""

    generated_at = _as_utc(now)
    incomplete: list[str] = _validate_start_manifest(start_manifest)
    failed: list[str] = []
    if max_evidence_age_minutes <= 0:
        incomplete.append("max_evidence_age_minutes_invalid")
    market_date = start_manifest.get("market_date")
    if not _is_regular_market_day(market_date, market_day_validator):
        failed.append("nonmarket_date")
    start_at = _parse_timestamp(start_manifest.get("generated_at")) or generated_at
    if isinstance(market_date, str) and market_date != start_at.astimezone(CENTRAL).date().isoformat():
        failed.append("start_manifest_backfilled_date")

    start_reasons, start_observed, _ = _compare_start_evidence(start_manifest)
    failed.extend(start_reasons)
    artifact_evidence: dict[str, dict[str, Any]] = {}
    keys = set(artifacts) if isinstance(artifacts, Mapping) else set()
    unknown = keys - set(ARTIFACT_KEYS)
    missing = set(ARTIFACT_KEYS) - keys
    if unknown:
        incomplete.append("unknown_artifact_keys")
    if missing:
        incomplete.append("missing_artifact_keys")
    bindings = start_manifest.get("artifact_bindings")
    bindings = bindings if isinstance(bindings, Mapping) else {}
    for key in ARTIFACT_KEYS:
        if key not in keys:
            continue
        evidence, payload = _read_json_evidence(artifacts[key])
        artifact_evidence[key] = _bound_evidence(evidence)
        if evidence.get("status") != "captured" or payload is None:
            incomplete.append(f"{key}_unreadable")
            continue
        bound = bindings.get(key)
        if isinstance(bound, Mapping) and (
            evidence.get("path") != bound.get("path")
            or evidence.get("sha256") != bound.get("sha256")
            or evidence.get("size_bytes") != bound.get("size_bytes")
        ):
            failed.append(f"{key}_hash_changed")
        artifact_failed, artifact_incomplete = _artifact_reasons(
            key,
            payload,
            run_id=str(start_manifest.get("run_id") or ""),
            market_date=str(market_date or ""),
            start_at=start_at,
            now=generated_at,
            max_evidence_age_minutes=max_evidence_age_minutes,
        )
        failed.extend(artifact_failed)
        incomplete.extend(artifact_incomplete)
    status = "failed" if failed else ("incomplete" if incomplete else "clean")
    phase = _day_phase(str(start_manifest.get("phase") or "qualification_pending"), status)
    result = {
        "schema_version": DAY_SCHEMA,
        "kind": "shadow_day_adjudication",
        "run_id": start_manifest.get("run_id"),
        "market_date": market_date,
        "role": start_manifest.get("role", "qualification"),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "status": status,
        "phase": phase,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "reasons": sorted(set([*failed, *incomplete])),
        "gates": [
            {"name": "start_manifest", "status": "pass" if not _validate_start_manifest(start_manifest) else "fail"},
            {"name": "market_day", "status": "pass" if "nonmarket_date" not in failed else "fail"},
            {"name": "start_state", "status": "pass" if not start_reasons else "fail"},
            {"name": "artifact_set", "status": "pass" if not unknown and not missing else "fail"},
            {"name": "artifact_validation", "status": "pass" if not failed and not incomplete else "fail"},
        ],
        "start_state": start_observed,
        "artifacts": artifact_evidence,
        "phase_catalog": list(PHASES),
    }
    result["canonical_sha256"] = canonical_json_sha256(result)
    return result


def build_shadow_streak_report(
    days: Sequence[Mapping[str, Any]],
    *,
    now: dt.datetime | None = None,
    market_day_validator: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Require one clean qualification followed by five distinct clean market days."""

    generated_at = _as_utc(now)
    reasons: list[str] = []
    qualification_seen = False
    streak = 0
    accepted: list[dict[str, Any]] = []
    dates: set[str] = set()
    phase_history = ["qualification_pending"]
    for item in days:
        if not isinstance(item, Mapping):
            reasons.append("day_record_invalid")
            streak = 0
            continue
        date = item.get("market_date")
        if not _is_regular_market_day(date, market_day_validator):
            reasons.append("nonmarket_date")
            streak = 0
            continue
        item_time = _parse_timestamp(item.get("generated_at"))
        if item_time is None or item_time.astimezone(CENTRAL).date().isoformat() != date:
            reasons.append("backfilled_or_malformed_day")
            streak = 0
            continue
        if item_time > generated_at + dt.timedelta(minutes=5):
            reasons.append("future_day_record")
            streak = 0
            continue
        if date in dates:
            reasons.append("duplicate_market_date")
            streak = 0
            continue
        dates.add(date)
        if item.get("schema_version") != DAY_SCHEMA or not _non_authorizing(item):
            reasons.append("day_record_schema_or_authority_invalid")
            streak = 0
            continue
        if item.get("status") != "clean":
            reasons.append("failed_or_incomplete_day")
            streak = 0
            continue
        role = item.get("role")
        if not qualification_seen:
            if role != "qualification" or item.get("phase") != "qualification_clean":
                reasons.append("clean_qualification_required")
                streak = 0
                continue
            qualification_seen = True
            phase_history.append("qualification_clean")
        else:
            if role != "trial":
                reasons.append("trial_role_required")
                streak = 0
                continue
            streak += 1
            phase_history.append("five_day_trial")
        accepted.append(
            {
                "run_id": item.get("run_id"),
                "market_date": date,
                "canonical_sha256": canonical_json_sha256(item),
            }
        )
    if not qualification_seen or reasons:
        phase = "readiness_no_go"
        phase_history.append("repair_required" if qualification_seen else "readiness_no_go")
    elif streak >= 5:
        phase = "readiness_candidate"
        phase_history.extend(["trial_complete", "readiness_candidate"])
    else:
        phase = "five_day_trial"
    result = {
        "schema_version": STREAK_SCHEMA,
        "kind": "shadow_streak_report",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "status": "candidate" if phase == "readiness_candidate" else "no_go",
        "phase": phase,
        "phase_history": list(dict.fromkeys(phase_history)),
        "clean_trial_streak": streak if not reasons else 0,
        "required_clean_trial_days": 5,
        "accepted_days": accepted,
        "reasons": sorted(set(reasons)),
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "phase_catalog": list(PHASES),
    }
    result["canonical_sha256"] = canonical_json_sha256(result)
    return result


def load_shadow_json(path: str | Path) -> dict[str, Any]:
    """Load a canonical JSON object for CLI evidence input without mutation."""

    evidence, payload = _read_json_evidence(path)
    if evidence["status"] != "captured" or payload is None:
        raise ValueError(f"shadow evidence is unreadable: {path}")
    return dict(payload)


def _fsync_directory(path: Path) -> None:
    unsupported = {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)}
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as exc:
        if exc.errno in unsupported:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def write_shadow_trial_packet(
    packet: Mapping[str, Any],
    *,
    output_dir: str | Path = Path("results/manual_shadow"),
    prefix: str,
) -> Path:
    """Publish one collision-safe immutable JSON packet without a mutable latest alias."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_timestamp(packet.get("generated_at")) or dt.datetime.now(tz=UTC)
    stem = f"{prefix}-{generated_at.strftime('%Y%m%d-%H%M%S-%f')}"
    payload = dict(packet)
    temporary_descriptor, temporary_name = tempfile.mkstemp(dir=root, prefix=f".{stem}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(temporary_descriptor, "wb") as temporary:
            temporary.write((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            temporary.flush()
            os.fsync(temporary.fileno())
        for suffix in range(1000):
            output_path = root / f"{stem}{'' if suffix == 0 else f'-{suffix:03d}'}.json"
            try:
                os.link(temporary_path, output_path)
            except FileExistsError:
                continue
            _fsync_directory(root)
            return output_path
        raise RuntimeError("could not allocate immutable shadow-trial packet path")
    finally:
        temporary_path.unlink(missing_ok=True)
