"""Tiny-live control state helpers for freeze/kill and dead-man checks."""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc
_NORMAL_LIVE_COMMITMENTS_FIELD = "normal_live_submission_commitments"
_NORMAL_LIVE_COMMITMENT_SCHEMA_VERSION = 2
_NORMAL_LIVE_COMMITMENT_PENDING = "pending"
_NORMAL_LIVE_COMMITMENT_RESOLVED = "resolved"
_NORMAL_LIVE_COMMITMENT_OUTCOMES = frozenset(
    {
        "submitted",
        "lookup_matched",
        "missing_refused",
        "admission_refused",
        "broker_terminal",
    }
)


def _expected_rearm_authority() -> dict[str, str] | None:
    try:
        request = authority_for(ActionClass.REARM_REQUEST)
        issue = authority_for(ActionClass.REARM_ISSUE)
    except (TypeError, ValueError):
        return None
    if (
        request.allowed is not True
        or request.human_required is not False
        or request.owner_role != "reliability_controller"
        or issue.allowed is not True
        or issue.human_required is not False
        or issue.owner_role != "integrity_verifier"
    ):
        return None
    return {
        "request_action": request.action.value,
        "request_owner_role": request.owner_role,
        "issue_action": issue.action.value,
        "issue_owner_role": issue.owner_role,
    }


class LiveControlPreimageMismatch(ValueError):
    """The live-control file changed after a caller accepted its preimage."""


def live_control_lock_path(state_path: str | Path) -> Path:
    state_file = Path(state_path).resolve()
    return state_file.with_name(f".{state_file.name}.control.lock")


@contextmanager
def live_control_lock(state_path: str | Path):
    """Serialize every cooperating live-control writer."""

    lock_path = live_control_lock_path(state_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield lock_path
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _commitment_time(value: object, *, label: str) -> datetime.datetime:
    if type(value) is not str:
        raise ValueError(f"normal live submission commitment {label} is invalid")
    parsed = parse_control_time(value)
    if parsed is None or parsed.microsecond:
        raise ValueError(f"normal live submission commitment {label} is invalid")
    return parsed


def _validate_normal_live_commitment(item: dict[str, Any]) -> dict[str, Any]:
    """Require a complete, self-derived, one-order commitment record."""

    required = {
        "schema_version",
        "commitment_id",
        "intent_full_sha256",
        "order_payload_sha256",
        "client_order_id",
        "control_preimage_sha256",
        "rate_reservation_sha256",
        "committed_at",
        "state",
        "outcome",
    }
    allowed = {*required, "resolved_at"}
    if set(item) - allowed or not required.issubset(item):
        raise ValueError("normal live submission commitment is invalid")
    if item["schema_version"] != _NORMAL_LIVE_COMMITMENT_SCHEMA_VERSION:
        raise ValueError("normal live submission commitment is invalid")
    if not all(
        _is_sha256(item[field])
        for field in (
            "commitment_id",
            "intent_full_sha256",
            "order_payload_sha256",
            "control_preimage_sha256",
            "rate_reservation_sha256",
        )
    ) or type(item["client_order_id"]) is not str or not item["client_order_id"]:
        raise ValueError("normal live submission commitment is invalid")
    expected_id = _commitment_id(
        intent_full_sha256=item["intent_full_sha256"],
        order_payload_sha256=item["order_payload_sha256"],
        client_order_id=item["client_order_id"],
        control_preimage_sha256=item["control_preimage_sha256"],
        rate_reservation_sha256=item["rate_reservation_sha256"],
    )
    if item["commitment_id"] != expected_id:
        raise ValueError("normal live submission commitment identity is invalid")
    committed_at = _commitment_time(item["committed_at"], label="committed_at")
    state = item["state"]
    outcome = item["outcome"]
    if state == _NORMAL_LIVE_COMMITMENT_PENDING:
        if outcome is not None or "resolved_at" in item:
            raise ValueError("normal live submission commitment state is invalid")
    elif state == _NORMAL_LIVE_COMMITMENT_RESOLVED:
        if outcome not in _NORMAL_LIVE_COMMITMENT_OUTCOMES:
            raise ValueError("normal live submission commitment outcome is invalid")
        resolved_at = _commitment_time(item.get("resolved_at"), label="resolved_at")
        if resolved_at < committed_at:
            raise ValueError("normal live submission commitment time order is invalid")
    else:
        raise ValueError("normal live submission commitment state is invalid")
    return dict(item)


def _read_normal_live_commitments(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only complete valid commitments; corrupted state always fails closed."""

    raw = state.get(_NORMAL_LIVE_COMMITMENTS_FIELD, [])
    if raw is None:
        return []
    if not isinstance(raw, list) or any(type(item) is not dict for item in raw):
        raise ValueError("normal live submission commitments are invalid")
    commitments = [_validate_normal_live_commitment(dict(item)) for item in raw]
    identities = [
        (
            item["commitment_id"],
            item["intent_full_sha256"],
            item["order_payload_sha256"],
            item["client_order_id"],
        )
        for item in commitments
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("normal live submission commitments contain a duplicate identity")
    return commitments


def _commitment_id(
    *,
    intent_full_sha256: str,
    order_payload_sha256: str,
    client_order_id: str,
    control_preimage_sha256: str,
    rate_reservation_sha256: str,
) -> str:
    payload = {
        "intent_full_sha256": intent_full_sha256,
        "order_payload_sha256": order_payload_sha256,
        "client_order_id": client_order_id,
        "control_preimage_sha256": control_preimage_sha256,
        "rate_reservation_sha256": rate_reservation_sha256,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def commit_normal_live_submission_locked(
    path: str | Path,
    *,
    intent_full_sha256: str,
    order_payload_sha256: str,
    client_order_id: str,
    rate_reservation_sha256: str,
    now: datetime.datetime,
) -> dict[str, str]:
    """Durably pre-commit one exact live POST while the control lock is held.

    The caller must hold :func:`live_control_lock`.  This is the irrevocable
    decision point: a freeze that wins before it is written prevents all
    broker I/O; a freeze that follows it preserves the exact in-flight record
    and cannot turn the already-committed action into an unrecorded POST.
    Network I/O is intentionally outside the control lock.
    """

    control_path = Path(path)
    try:
        raw = control_path.read_bytes()
        state = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("normal live submission control preimage is unavailable") from exc
    if not isinstance(state, dict):
        raise ValueError("normal live submission control preimage is invalid")
    current, issues = load_live_control_state(control_path, now=now)
    if current is None or issues or current.get("frozen") is not False:
        raise ValueError("normal live submission control is not open")
    if not all(
        _is_sha256(value)
        for value in (
            intent_full_sha256,
            order_payload_sha256,
            rate_reservation_sha256,
        )
    ) or (
        type(client_order_id) is not str or not client_order_id
    ):
        raise ValueError("normal live submission commitment is invalid")
    moment = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
    if moment.microsecond:
        raise ValueError("normal live submission commitment requires whole-second time")
    control_preimage_sha256 = hashlib.sha256(raw).hexdigest()
    commitment_id = _commitment_id(
        intent_full_sha256=intent_full_sha256,
        order_payload_sha256=order_payload_sha256,
        client_order_id=client_order_id,
        control_preimage_sha256=control_preimage_sha256,
        rate_reservation_sha256=rate_reservation_sha256,
    )
    commitments = _read_normal_live_commitments(state)
    active = [item for item in commitments if item["state"] == _NORMAL_LIVE_COMMITMENT_PENDING]
    if active:
        if len(active) != 1 or any(
            active[0].get(field) != expected
            for field, expected in (
                ("intent_full_sha256", intent_full_sha256),
                ("order_payload_sha256", order_payload_sha256),
                ("client_order_id", client_order_id),
                ("rate_reservation_sha256", rate_reservation_sha256),
            )
        ):
            raise ValueError("normal live submission already has an unresolved commitment")
        return dict(active[0])
    commitment = {
        "schema_version": _NORMAL_LIVE_COMMITMENT_SCHEMA_VERSION,
        "commitment_id": commitment_id,
        "intent_full_sha256": intent_full_sha256,
        "order_payload_sha256": order_payload_sha256,
        "client_order_id": client_order_id,
        "control_preimage_sha256": control_preimage_sha256,
        "rate_reservation_sha256": rate_reservation_sha256,
        "committed_at": moment.isoformat(timespec="seconds"),
        "state": _NORMAL_LIVE_COMMITMENT_PENDING,
        "outcome": None,
    }
    commitments.append(commitment)
    state[_NORMAL_LIVE_COMMITMENTS_FIELD] = commitments
    atomic_write_text(control_path, json.dumps(state, indent=2))
    return commitment


def resolve_normal_live_submission_commitment(
    path: str | Path,
    *,
    commitment_id: str,
    outcome: str,
    now: datetime.datetime,
) -> None:
    """Durably resolve one precommit after a matching lookup/post outcome."""

    if outcome not in _NORMAL_LIVE_COMMITMENT_OUTCOMES:
        raise ValueError("normal live submission outcome is invalid")
    with live_control_lock(path):
        control_path = Path(path)
        try:
            state = json.loads(control_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("normal live submission control outcome is unavailable") from exc
        if not isinstance(state, dict):
            raise ValueError("normal live submission control outcome is invalid")
        commitments = _read_normal_live_commitments(state)
        matched = [
            item
            for item in commitments
            if item.get("commitment_id") == commitment_id
        ]
        if len(matched) != 1:
            raise ValueError("normal live submission commitment is unavailable")
        commitment = matched[0]
        if commitment["state"] == _NORMAL_LIVE_COMMITMENT_RESOLVED:
            if commitment["outcome"] != outcome:
                raise ValueError("normal live submission commitment outcome conflicts")
            return
        moment = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
        if moment < _commitment_time(commitment["committed_at"], label="committed_at"):
            raise ValueError("normal live submission commitment time order is invalid")
        commitment["state"] = _NORMAL_LIVE_COMMITMENT_RESOLVED
        commitment["outcome"] = outcome
        commitment["resolved_at"] = moment.replace(microsecond=0).isoformat(
            timespec="seconds"
        )
        state[_NORMAL_LIVE_COMMITMENTS_FIELD] = commitments
        atomic_write_text(control_path, json.dumps(state, indent=2))


def verify_pending_normal_live_submission_commitment(
    path: str | Path,
    *,
    commitment: Mapping[str, object],
    intent_full_sha256: str,
    order_payload_sha256: str,
    client_order_id: str,
    rate_reservation_sha256: str,
) -> None:
    """Prove a specific pending commitment still survives in control state.

    This does not grant authority.  It is the narrow post-commit continuity
    check that lets the final gate distinguish a later *fresh freeze* from a
    missing, malformed, substituted, or already-resolved commitment.  It
    validates every commitment record while holding the shared control lock.
    """

    with live_control_lock(path):
        _verify_pending_normal_live_submission_commitment_locked(
            path,
            commitment=commitment,
            intent_full_sha256=intent_full_sha256,
            order_payload_sha256=order_payload_sha256,
            client_order_id=client_order_id,
            rate_reservation_sha256=rate_reservation_sha256,
        )


def _verify_pending_normal_live_submission_commitment_locked(
    path: str | Path,
    *,
    commitment: Mapping[str, object],
    intent_full_sha256: str,
    order_payload_sha256: str,
    client_order_id: str,
    rate_reservation_sha256: str,
) -> None:
    """Verify an exact pending record while the caller already owns control lock."""

    if not isinstance(commitment, Mapping):
        raise ValueError("normal live submission commitment is invalid")
    required = {
        "commitment_id",
        "intent_full_sha256",
        "order_payload_sha256",
        "client_order_id",
        "control_preimage_sha256",
        "rate_reservation_sha256",
    }
    if any(commitment.get(field) != expected for field, expected in (
        ("intent_full_sha256", intent_full_sha256),
        ("order_payload_sha256", order_payload_sha256),
        ("client_order_id", client_order_id),
        ("rate_reservation_sha256", rate_reservation_sha256),
    )) or not all(
        type(commitment.get(field)) is str for field in required
    ):
        raise ValueError("normal live submission commitment does not bind the exact order")
    control_path = Path(path)
    try:
        state = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("normal live submission commitment is unavailable") from exc
    if not isinstance(state, dict):
        raise ValueError("normal live submission commitment is unavailable")
    commitments = _read_normal_live_commitments(state)
    matches = [
        item
        for item in commitments
        if item["commitment_id"] == commitment["commitment_id"]
    ]
    if len(matches) != 1:
        raise ValueError("normal live submission commitment is unavailable")
    matched = matches[0]
    if matched["state"] != _NORMAL_LIVE_COMMITMENT_PENDING or any(
        matched[field] != commitment.get(field)
        for field in required
    ):
        raise ValueError("normal live submission commitment is unavailable")


def parse_control_time(value: str) -> datetime.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _recovery_closure_issues(
    receipt: dict[str, Any],
    *,
    receipt_path: Path,
    control_path: Path,
) -> list[str]:
    issues: list[str] = []
    required = {
        "incident",
        "reconciliation",
        "promotion",
        "focused",
        "manifest",
        "promotion_report",
        "promotion_envelope",
        "promotion_prepare",
        "promotion_stage",
        "promotion_commit",
        "promotion_canonical",
    }
    closure = receipt.get("promotion_transaction_closure")
    if not isinstance(closure, dict) or set(closure) != required:
        return ["verified recovery receipt lacks exact promotion closure"]
    closure_root = receipt_path.with_name(
        receipt_path.name + ".closure"
    ).resolve()
    snapshot_paths: set[Path] = set()
    source_paths: dict[str, Path] = {}
    digests: dict[str, str] = {}
    for name in required:
        record = closure.get(name)
        if not isinstance(record, dict) or set(record) != {
            "source_path",
            "snapshot_path",
            "sha256",
        }:
            issues.append(
                f"verified recovery closure record is invalid for {name}"
            )
            continue
        source_raw = record.get("source_path")
        snapshot_raw = record.get("snapshot_path")
        digest = record.get("sha256")
        if (
            not isinstance(source_raw, str)
            or not Path(source_raw).is_absolute()
            or str(Path(source_raw).resolve()) != source_raw
            or not isinstance(snapshot_raw, str)
            or not Path(snapshot_raw).is_absolute()
            or str(Path(snapshot_raw).resolve()) != snapshot_raw
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            issues.append(
                f"verified recovery closure reference is invalid for {name}"
            )
            continue
        source_path = Path(source_raw)
        snapshot_path = Path(snapshot_raw)
        if (
            snapshot_path.parent != closure_root
            or snapshot_path.name != f"{name}.bin"
            or snapshot_path in {receipt_path.resolve(), control_path.resolve()}
            or snapshot_path == source_path
        ):
            issues.append(
                f"verified recovery closure path is unsafe for {name}"
            )
            continue
        if snapshot_path in snapshot_paths:
            issues.append("verified recovery closure snapshot paths collide")
            continue
        snapshot_paths.add(snapshot_path)
        source_paths[name] = source_path
        digests[name] = digest
        try:
            actual = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        except OSError:
            issues.append(
                f"verified recovery closure snapshot is unavailable for {name}"
            )
        else:
            if actual != digest:
                issues.append(
                    f"verified recovery closure snapshot digest mismatch for {name}"
                )
    phase_paths = receipt.get("source_packet_paths")
    phase_hashes = receipt.get("source_packet_sha256")
    if isinstance(phase_paths, dict) and isinstance(phase_hashes, dict):
        for name in ("incident", "reconciliation", "promotion", "focused"):
            if (
                source_paths.get(name) != Path(str(phase_paths.get(name)))
                or digests.get(name) != phase_hashes.get(name)
            ):
                issues.append(
                    f"verified recovery closure source binding mismatch for {name}"
                )
    manifest_path = receipt.get("recovery_manifest_path")
    if (
        source_paths.get("manifest") != Path(str(manifest_path))
        or digests.get("manifest")
        != receipt.get("recovery_manifest_sha256")
    ):
        issues.append("verified recovery closure manifest binding mismatch")
    if snapshot_paths & set(source_paths.values()):
        issues.append("verified recovery closure source and snapshot paths collide")
    return issues


def load_live_control_state(
    path: str | Path,
    *,
    now: datetime.datetime | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    control_path = Path(path)
    if not control_path.exists():
        return None, [f"live control state missing at {control_path}"]
    try:
        state = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"live control state is invalid JSON: {exc}"]
    if not isinstance(state, dict):
        return None, ["live control state must be a JSON object"]

    issues: list[str] = []
    if type(state.get("frozen")) is not bool:
        issues.append("live control state frozen must be a literal boolean")
    if state.get("frozen") is True:
        reason = str(state.get("reason") or "no reason recorded")
        issues.append(f"live control state is frozen: {reason}")

    current = now or datetime.datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    expires_at = parse_control_time(str(state.get("dead_man_expires_at", "")))
    if expires_at is None:
        issues.append("live control state missing valid dead_man_expires_at")
    elif expires_at <= current:
        issues.append(f"dead-man expired at {expires_at.isoformat()}")

    recovery_fields = {"recovery_receipt_path", "recovery_receipt_sha256", "recovery_incident_id", "recovery_mode"}
    has_recovery_marker = any(key in state for key in recovery_fields) or (
        state.get("frozen") is False
        and isinstance(state.get("reason"), str)
        and state["reason"].startswith("verified recovery ")
    )
    if has_recovery_marker and (set(key for key in recovery_fields if key in state) != recovery_fields or state.get("recovery_mode") != "verified_recovery" or state.get("frozen") is not False or not isinstance(state.get("recovery_incident_id"), str) or not state["recovery_incident_id"].strip()):
        issues.append("verified recovery control has incomplete or unsafe markers")
    receipt_path = state.get("recovery_receipt_path")
    receipt_digest = state.get("recovery_receipt_sha256")
    if has_recovery_marker:
        if not isinstance(receipt_path, str) or not receipt_path.strip():
            issues.append("verified recovery control missing receipt path")
        elif not isinstance(receipt_digest, str) or len(receipt_digest) != 64 or any(char not in "0123456789abcdef" for char in receipt_digest):
            issues.append("verified recovery control missing receipt digest")
        elif not Path(receipt_path).is_absolute() or str(Path(receipt_path).resolve()) != receipt_path:
            issues.append("verified recovery receipt path must be absolute")
        else:
            candidate = Path(receipt_path)
            try:
                raw_receipt = candidate.read_bytes()
                actual_digest = hashlib.sha256(raw_receipt).hexdigest()
                receipt = json.loads(raw_receipt)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                issues.append("verified recovery receipt is missing or corrupt")
            else:
                expected_authority = _expected_rearm_authority()
                if actual_digest != receipt_digest:
                    issues.append("verified recovery receipt digest mismatch")
                if not isinstance(receipt, dict):
                    issues.append("verified recovery receipt must be a JSON object")
                elif receipt.get("schema_version") != 2:
                    issues.append("verified recovery receipt has wrong schema")
                elif receipt.get("kind") != "verified_rearm_receipt":
                    issues.append("verified recovery receipt has wrong kind")
                elif receipt.get("incident_id") != state.get("recovery_incident_id"):
                    issues.append("verified recovery receipt incident binding mismatch")
                elif (
                    expected_authority is None
                    or receipt.get("authority") != expected_authority
                ):
                    issues.append(
                        "verified recovery receipt has invalid authority binding"
                    )
                elif any(
                    not isinstance(receipt.get(key), str) or not receipt[key].strip()
                    for key in ("repairer_run_id", "verifier_run_id", "repairer_role_id", "verifier_role_id")
                ) or receipt["repairer_run_id"].strip().casefold() == receipt["verifier_run_id"].strip().casefold() or receipt.get("repairer_role_id") != "reliability_controller" or receipt.get("verifier_role_id") != "integrity_verifier":
                    issues.append("verified recovery receipt identities are unsafe")
                elif receipt.get("effective_only_when_control_matches_receipt_digest") is not True:
                    issues.append("verified recovery receipt lacks effective binding")
                elif receipt.get("can_submit_orders") is not False or type(receipt.get("broker_write_calls")) is not int or receipt.get("broker_write_calls") != 0:
                    issues.append("verified recovery receipt has unsafe authority fields")
                elif (
                    not isinstance(receipt.get("source_bindings"), dict)
                    or set(receipt["source_bindings"]) != {"incident_id", "symbol", "broker_account", "environment", "source_revision"}
                    or not isinstance(receipt.get("source_packet_sha256"), dict)
                    or not isinstance(receipt.get("source_packet_paths"), dict)
                    or set(receipt["source_packet_sha256"]) != {"incident", "reconciliation", "promotion", "focused"}
                    or set(receipt["source_packet_paths"]) != {"incident", "reconciliation", "promotion", "focused"}
                ):
                    issues.append("verified recovery receipt lacks source proof")
                else:
                    source_bindings = receipt["source_bindings"]
                    source_hashes = receipt["source_packet_sha256"]
                    source_paths = receipt["source_packet_paths"]
                    manifest_path = receipt.get("recovery_manifest_path")
                    manifest_sha256 = receipt.get("recovery_manifest_sha256")
                    if (
                        any(not isinstance(source_bindings[key], str) or not source_bindings[key].strip() for key in source_bindings)
                        or source_bindings.get("incident_id") != state.get("recovery_incident_id")
                        or any(not isinstance(source_hashes[key], str) or len(source_hashes[key]) != 64 or any(char not in "0123456789abcdef" for char in source_hashes[key]) for key in source_hashes)
                        or any(not isinstance(source_paths[key], str) or not source_paths[key] or not Path(source_paths[key]).is_absolute() or str(Path(source_paths[key]).resolve()) != source_paths[key] for key in source_paths)
                    ):
                        issues.append("verified recovery receipt has invalid source proof")
                    if (
                        not isinstance(manifest_path, str)
                        or not manifest_path
                        or not Path(manifest_path).is_absolute()
                        or str(Path(manifest_path).resolve()) != manifest_path
                        or not isinstance(manifest_sha256, str)
                        or len(manifest_sha256) != 64
                        or any(char not in "0123456789abcdef" for char in manifest_sha256)
                    ):
                        issues.append("verified recovery receipt has invalid manifest proof")
                    else:
                        try:
                            if hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest() != manifest_sha256:
                                issues.append("verified recovery manifest hash mismatch")
                        except OSError:
                            issues.append("verified recovery manifest is unavailable")
                    issues.extend(
                        _recovery_closure_issues(
                            receipt,
                            receipt_path=candidate,
                            control_path=control_path,
                        )
                    )
                    receipt_expires_raw = receipt.get("expires_at")
                    receipt_issued_raw = receipt.get("issued_at")
                    receipt_expires_at = parse_control_time(str(receipt_expires_raw or ""))
                    receipt_issued_at = parse_control_time(str(receipt_issued_raw or ""))
                    ttl_minutes = receipt.get("ttl_minutes")
                    if (
                        not isinstance(receipt_expires_raw, str)
                        or not isinstance(receipt_issued_raw, str)
                        or not (receipt_expires_raw.endswith("Z") or "+" in receipt_expires_raw[10:])
                        or not (receipt_issued_raw.endswith("Z") or "+" in receipt_issued_raw[10:])
                        or receipt_expires_at is None
                        or receipt_issued_at is None
                        or type(ttl_minutes) is not int
                        or not 1 <= ttl_minutes <= 90
                        or receipt_issued_at > current
                        or receipt_issued_at + datetime.timedelta(minutes=ttl_minutes) != receipt_expires_at
                        or receipt_expires_at <= current
                    ):
                        issues.append("verified recovery receipt is expired or invalid")
                    binding = receipt.get("control_binding")
                    if not isinstance(binding, dict) or binding != {
                        "control_path": str(control_path.resolve()),
                        "incident_id": state.get("recovery_incident_id"),
                        "reason": state.get("reason"),
                        "dead_man_expires_at": state.get("dead_man_expires_at"),
                        "frozen": False,
                        "mode": state.get("recovery_mode"),
                        "receipt_path": receipt_path,
                    }:
                        issues.append("verified recovery receipt control binding mismatch")

    return state, issues


def _write_live_control_state_locked(
    path: str | Path,
    *,
    frozen: bool,
    reason: str,
    dead_man_expires_at: datetime.datetime | None = None,
    recovery_receipt_path: str | None = None,
    recovery_receipt_sha256: str | None = None,
    recovery_incident_id: str | None = None,
    recovery_mode: str | None = None,
    expected_preimage_sha256: str | None = None,
    now: datetime.datetime | None = None,
) -> Path:
    """Replace live control while its interprocess lock is already held."""

    control_path = Path(path)
    control_path.parent.mkdir(parents=True, exist_ok=True)
    prior_state: dict[str, Any] = {}
    try:
        prior = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        prior = None
    if isinstance(prior, dict):
        prior_state = prior
    if expected_preimage_sha256 is not None:
        if (
            len(expected_preimage_sha256) != 64
            or any(
                char not in "0123456789abcdef"
                for char in expected_preimage_sha256
            )
        ):
            raise ValueError("expected_preimage_sha256 must be a SHA-256 digest")
        try:
            actual_preimage = hashlib.sha256(control_path.read_bytes()).hexdigest()
        except OSError:
            raise LiveControlPreimageMismatch(
                "live control preimage is unavailable"
            ) from None
        if actual_preimage != expected_preimage_sha256:
            raise LiveControlPreimageMismatch(
                "live control changed after its safety preimage was accepted"
            )
    updated_at = now or datetime.datetime.now(tz=UTC)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    updated_at = updated_at.astimezone(UTC)
    expires_at = dead_man_expires_at or (
        updated_at + datetime.timedelta(hours=6)
    )
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    payload = {
        "frozen": bool(frozen),
        "reason": reason,
        "dead_man_expires_at": expires_at.astimezone(UTC).isoformat(timespec="seconds"),
        "updated_at": updated_at.isoformat(timespec="seconds"),
    }
    # A freeze/re-arm writer must never erase a committed in-flight normal-live
    # action.  Preserving this durable record lets the writer observe the exact
    # committed client order without waiting for network I/O held by another
    # process.
    if _NORMAL_LIVE_COMMITMENTS_FIELD in prior_state:
        payload[_NORMAL_LIVE_COMMITMENTS_FIELD] = prior_state[
            _NORMAL_LIVE_COMMITMENTS_FIELD
        ]
        if frozen is True:
            raw_commitments = prior_state[_NORMAL_LIVE_COMMITMENTS_FIELD]
            if isinstance(raw_commitments, list):
                payload["normal_live_freeze_observed_committed_client_order_ids"] = [
                    item.get("client_order_id")
                    for item in raw_commitments
                    if isinstance(item, dict) and item.get("outcome") is None
                ]
    if recovery_receipt_path is not None or recovery_receipt_sha256 is not None:
        if not isinstance(recovery_receipt_path, str) or not recovery_receipt_path.strip():
            raise ValueError("recovery_receipt_path must be a nonblank string")
        if not isinstance(recovery_receipt_sha256, str) or len(recovery_receipt_sha256) != 64:
            raise ValueError("recovery_receipt_sha256 must be a SHA-256 digest")
        payload["recovery_receipt_path"] = recovery_receipt_path
        payload["recovery_receipt_sha256"] = recovery_receipt_sha256
        if not isinstance(recovery_incident_id, str) or not recovery_incident_id.strip() or recovery_mode != "verified_recovery":
            raise ValueError("verified recovery control requires incident and mode")
        payload["recovery_incident_id"] = recovery_incident_id.strip()
        payload["recovery_mode"] = recovery_mode
    atomic_write_text(control_path, json.dumps(payload, indent=2))
    return control_path


def write_live_control_state(
    path: str | Path,
    *,
    frozen: bool,
    reason: str,
    dead_man_expires_at: datetime.datetime | None = None,
    recovery_receipt_path: str | None = None,
    recovery_receipt_sha256: str | None = None,
    recovery_incident_id: str | None = None,
    recovery_mode: str | None = None,
    expected_preimage_sha256: str | None = None,
    now: datetime.datetime | None = None,
) -> Path:
    """Atomically update live control under its shared writer lock."""

    with live_control_lock(path):
        return _write_live_control_state_locked(
            path,
            frozen=frozen,
            reason=reason,
            dead_man_expires_at=dead_man_expires_at,
            recovery_receipt_path=recovery_receipt_path,
            recovery_receipt_sha256=recovery_receipt_sha256,
            recovery_incident_id=recovery_incident_id,
            recovery_mode=recovery_mode,
            expected_preimage_sha256=expected_preimage_sha256,
            now=now,
        )
