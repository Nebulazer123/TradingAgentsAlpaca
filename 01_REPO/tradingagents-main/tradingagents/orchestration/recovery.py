"""Fail-closed, broker-free recovery evidence and bounded re-arm coordination."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.live_control import load_live_control_state, write_live_control_state

UTC = dt.timezone.utc
MAX_REARM_TTL_MINUTES = 90
EVIDENCE_MAX_AGE_MINUTES = 30


@dataclass(frozen=True)
class RecoveryEvidence:
    incident_id: str
    repairer_run_id: str
    verifier_run_id: str
    root_cause_resolved: bool
    focused_tests_passed: bool
    promotion_evidence_fresh: bool
    promotion_issues: tuple[str, ...]
    broker_reconciliation_matched: bool
    broker_reconciliation_issues: tuple[str, ...]
    broker_write_calls: int
    external_blockers: tuple[str, ...]
    repairer_role_id: str = ""
    verifier_role_id: str = ""
    source_bindings: Mapping[str, str] = field(default_factory=dict)
    source_packet_sha256: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RecoveryVerdict:
    ready: bool
    issues: tuple[str, ...]


def _normalized_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _literal_bool(value: object) -> bool:
    return type(value) is bool


def _string_items(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    values = tuple(_normalized_string(item) for item in value)
    if any(item is None for item in values):
        return None
    return tuple(item for item in values if item is not None)


def evaluate_rearm_readiness(evidence: RecoveryEvidence) -> RecoveryVerdict:
    """Return all independently checkable reasons a recovery cannot re-arm."""
    issues: list[str] = []
    if _normalized_string(evidence.incident_id) is None:
        issues.append("incident_id must be a nonblank string")
    repairer_run = _normalized_string(evidence.repairer_run_id)
    verifier_run = _normalized_string(evidence.verifier_run_id)
    if repairer_run is None:
        issues.append("repairer_run_id must be a nonblank string")
    if verifier_run is None:
        issues.append("verifier_run_id must be a nonblank string")
    if repairer_run is not None and verifier_run is not None and repairer_run == verifier_run:
        issues.append("repairer and verifier run IDs must differ")
    repairer_role = _normalized_string(evidence.repairer_role_id)
    verifier_role = _normalized_string(evidence.verifier_role_id)
    if repairer_role is None:
        issues.append("repairer_role_id must be a nonblank string")
    if verifier_role is None:
        issues.append("verifier_role_id must be a nonblank string")
    if repairer_role is not None and verifier_role is not None and repairer_role == verifier_role:
        issues.append("repairer and verifier role IDs must differ")

    for field_name in (
        "root_cause_resolved",
        "focused_tests_passed",
        "promotion_evidence_fresh",
        "broker_reconciliation_matched",
    ):
        value = getattr(evidence, field_name)
        if not _literal_bool(value):
            issues.append(f"{field_name} must be a literal boolean")
        elif value is not True:
            issues.append(f"{field_name} is not true")
    for field_name in (
        "promotion_issues",
        "broker_reconciliation_issues",
        "external_blockers",
    ):
        value = _string_items(getattr(evidence, field_name))
        if value is None:
            issues.append(f"{field_name} must be a list or tuple of nonblank strings")
        elif value:
            issues.append(f"{field_name} is not empty")
    if type(evidence.broker_write_calls) is not int:
        issues.append("broker_write_calls must be a non-boolean integer")
    elif evidence.broker_write_calls != 0:
        issues.append("broker_write_calls must equal zero")
    return RecoveryVerdict(ready=not issues, issues=tuple(issues))


def _as_utc(now: dt.datetime | None) -> dt.datetime:
    current = now or dt.datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(UTC)


def _strict_ttl(ttl_minutes: object) -> int:
    if type(ttl_minutes) is not int or not 1 <= ttl_minutes <= MAX_REARM_TTL_MINUTES:
        raise ValueError(f"ttl_minutes must be a literal integer from 1 to {MAX_REARM_TTL_MINUTES}")
    return ttl_minutes


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _receipt_path(receipt_dir: Path, now: dt.datetime) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    return receipt_dir / f"verified-rearm-{stamp}-{secrets.token_hex(8)}.json"


def write_rearm_receipt(receipt: Mapping[str, Any], receipt_dir: str | Path, *, now: dt.datetime | None = None) -> dict[str, str]:
    """Durably create an immutable receipt, then update its non-authoritative pointer."""
    current = _as_utc(now)
    target_dir = Path(receipt_dir)
    payload = dict(receipt)
    encoded = _canonical_json(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    for _ in range(16):
        path = _receipt_path(target_dir, current)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise OSError("incomplete recovery receipt write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        latest = {
            "kind": "verified_rearm_latest",
            "receipt_path": str(path.resolve()),
            "receipt_sha256": digest,
            "updated_at": current.isoformat(),
            "can_submit_orders": False,
        }
        atomic_write_text(target_dir / "latest.json", json.dumps(latest, indent=2, sort_keys=True))
        return {"receipt_path": str(path.resolve()), "receipt_sha256": digest}
    raise OSError("could not allocate a unique recovery receipt path")


def rearm_after_verified_recovery(
    *,
    evidence: RecoveryEvidence,
    control_path: str | Path,
    receipt_dir: str | Path,
    ttl_minutes: int = MAX_REARM_TTL_MINUTES,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Re-arm only a currently frozen control after durable independent evidence."""
    verdict = evaluate_rearm_readiness(evidence)
    if not verdict.ready:
        raise ValueError("rearm blocked: " + "; ".join(verdict.issues))
    ttl = _strict_ttl(ttl_minutes)
    current = _as_utc(now)
    state, control_issues = load_live_control_state(control_path, now=current)
    non_freeze_issues = [issue for issue in control_issues if not issue.startswith("live control state is frozen:")]
    if state is None or non_freeze_issues:
        raise ValueError("rearm blocked: existing live control is not valid")
    if state.get("frozen") is not True:
        raise ValueError("rearm blocked: existing live control must be currently frozen")
    expires_at = current + dt.timedelta(minutes=ttl)
    receipt = {
        "schema_version": 1,
        "kind": "verified_rearm_receipt",
        "incident_id": evidence.incident_id.strip(),
        "repairer_run_id": evidence.repairer_run_id.strip(),
        "verifier_run_id": evidence.verifier_run_id.strip(),
        "repairer_role_id": evidence.repairer_role_id.strip(),
        "verifier_role_id": evidence.verifier_role_id.strip(),
        "issued_at": current.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_minutes": ttl,
        "broker_write_calls": 0,
        "can_submit_orders": False,
        "effective_only_when_control_matches_receipt_digest": True,
        "source_bindings": dict(evidence.source_bindings),
        "source_packet_sha256": dict(evidence.source_packet_sha256),
    }
    receipt_ref = write_rearm_receipt(receipt, receipt_dir, now=current)
    written = write_live_control_state(
        control_path,
        frozen=False,
        reason=f"verified recovery {evidence.incident_id.strip()}",
        dead_man_expires_at=expires_at,
        recovery_receipt_path=receipt_ref["receipt_path"],
        recovery_receipt_sha256=receipt_ref["receipt_sha256"],
    )
    return {**receipt_ref, "control_path": str(written), "expires_at": expires_at.isoformat(), "can_submit_orders": False}


def _parse_time(value: object, *, field: str, now: dt.datetime) -> tuple[dt.datetime | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, f"{field} missing timezone-aware timestamp"
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None, f"{field} has invalid timestamp"
    if parsed.tzinfo is None:
        return None, f"{field} must be timezone-aware"
    parsed = parsed.astimezone(UTC)
    if parsed > now:
        return None, f"{field} is in the future"
    if now - parsed > dt.timedelta(minutes=EVIDENCE_MAX_AGE_MINUTES):
        return None, f"{field} is stale"
    return parsed, None


def _read_packet(path: str | Path, label: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, f"{label} packet is unreadable JSON"
    if not isinstance(value, dict):
        return None, None, f"{label} packet must be a JSON object"
    return value, hashlib.sha256(raw).hexdigest(), None


def _binding(packet: Mapping[str, Any], key: str) -> str | None:
    aliases = {"broker_account": ("broker_account", "account"), "source_revision": ("source_revision", "revision", "git_sha")}
    for name in aliases.get(key, (key,)):
        candidate = _normalized_string(packet.get(name))
        if candidate is not None:
            return candidate
    return None


def load_recovery_evidence(
    *,
    incident_path: str | Path,
    reconciliation_path: str | Path,
    promotion_sync_path: str | Path,
    focused_proof_path: str | Path,
    recovery_manifest_path: str | Path | None = None,
    repairer_run_id: object,
    verifier_run_id: object,
    now: dt.datetime | None = None,
) -> tuple[RecoveryEvidence | None, tuple[str, ...]]:
    """Strictly parse four evidence packets; malformed data returns a safe verdict input."""
    current = _as_utc(now)
    packets: dict[str, dict[str, Any]] = {}
    digests: dict[str, str] = {}
    issues: list[str] = []
    for label, path in (("incident", incident_path), ("reconciliation", reconciliation_path), ("promotion", promotion_sync_path), ("focused proof", focused_proof_path)):
        packet, digest, issue = _read_packet(path, label)
        if issue:
            issues.append(issue)
        else:
            packets[label] = packet or {}
            digests[label] = digest or ""
    if issues:
        return None, tuple(issues)
    required_bindings = ("incident_id", "symbol", "broker_account", "environment")
    bindings: dict[str, str] = {}
    manifest = None
    if recovery_manifest_path is not None:
        manifest, _digest, manifest_issue = _read_packet(recovery_manifest_path, "recovery manifest")
        if manifest_issue:
            issues.append(manifest_issue)
        else:
            for key in (*required_bindings, "source_revision"):
                value = _binding(manifest or {}, key)
                if value is None:
                    issues.append(f"recovery manifest missing {key}")
                else:
                    bindings[key] = value
            packet_hashes = (manifest or {}).get("packet_sha256")
            if not isinstance(packet_hashes, dict):
                issues.append("recovery manifest packet_sha256 must be an object")
            else:
                for label, digest in digests.items():
                    manifest_key = "focused" if label == "focused proof" else label
                    if packet_hashes.get(manifest_key) != digest:
                        issues.append(f"recovery manifest hash mismatch for {manifest_key}")
            for label, packet in packets.items():
                for key, expected in bindings.items():
                    present = _binding(packet, key)
                    if present is not None and present != expected:
                        issues.append(f"{key} binding conflicts with recovery manifest in {label}")
    else:
        for key in required_bindings:
            values = {label: _binding(packet, key) for label, packet in packets.items()}
            if any(value is None for value in values.values()):
                issues.append(f"{key} binding missing from recovery evidence")
            elif len(set(values.values())) != 1:
                issues.append(f"{key} binding conflicts across recovery evidence")
            else:
                bindings[key] = next(iter(values.values())) or ""
        revisions = {label: _binding(packet, "source_revision") for label, packet in packets.items()}
        present_revisions = [value for value in revisions.values() if value is not None]
        if present_revisions and (len(present_revisions) != len(revisions) or len(set(present_revisions)) != 1):
            issues.append("source_revision binding conflicts or is missing across recovery evidence")
        elif present_revisions:
            bindings["source_revision"] = present_revisions[0]
    for label, packet in packets.items():
        timestamp = packet.get("generated_at", packet.get("updated_at", packet.get("issued_at")))
        _parsed, issue = _parse_time(timestamp, field=f"{label} timestamp", now=current)
        if issue:
            issues.append(issue)
    incident = packets["incident"]
    focused = packets["focused proof"]
    promotion = packets["promotion"]
    reconciliation = packets["reconciliation"]
    if incident.get("stage") != "ready":
        issues.append("incident is not ready")
    root_cause = incident.get("root_cause_resolved")
    focused_passed = focused.get("focused_tests_passed", focused.get("passed"))
    passing_tests = _string_items(focused.get("passing_tests"))
    promotion_fresh = promotion.get("promotion_evidence_fresh", promotion.get("fresh"))
    promotion_issues = _string_items(promotion.get("issues"))
    reconciliation_issues = _string_items(reconciliation.get("issues"))
    for field_name, value in (("root_cause_resolved", root_cause), ("focused_tests_passed", focused_passed), ("promotion_evidence_fresh", promotion_fresh), ("read_only", reconciliation.get("read_only")), ("can_submit_orders", reconciliation.get("can_submit_orders")), ("matched", reconciliation.get("matched"))):
        if not _literal_bool(value):
            issues.append(f"{field_name} must be a literal boolean")
    if focused_passed is not True or not passing_tests:
        issues.append("focused proof must name at least one passing test")
    if promotion_issues is None:
        issues.append("promotion issues must be a list of strings")
        promotion_issues = ()
    if reconciliation_issues is None:
        issues.append("reconciliation issues must be a list of strings")
        reconciliation_issues = ()
    if reconciliation.get("read_only") is not True:
        issues.append("reconciliation must be read_only")
    if reconciliation.get("execution_authority") != "none":
        issues.append("reconciliation execution_authority must be none")
    if reconciliation.get("can_submit_orders") is not False:
        issues.append("reconciliation can_submit_orders must be false")
    writes = reconciliation.get("broker_write_calls")
    if type(writes) is not int or writes != 0:
        issues.append("reconciliation broker_write_calls must equal zero")
    repairer_role = _normalized_string(incident.get("repairer_role_id"))
    verifier_role = _normalized_string(focused.get("verifier_role_id"))
    if issues:
        return None, tuple(issues)
    evidence = RecoveryEvidence(
        incident_id=bindings["incident_id"],
        repairer_run_id=repairer_run_id,
        verifier_run_id=verifier_run_id,
        repairer_role_id=repairer_role or "",
        verifier_role_id=verifier_role or "",
        root_cause_resolved=root_cause,
        focused_tests_passed=focused_passed,
        promotion_evidence_fresh=promotion_fresh,
        promotion_issues=promotion_issues,
        broker_reconciliation_matched=reconciliation.get("matched"),
        broker_reconciliation_issues=reconciliation_issues,
        broker_write_calls=writes,
        external_blockers=(),
        source_bindings=bindings,
        source_packet_sha256=digests,
    )
    return evidence, ()
