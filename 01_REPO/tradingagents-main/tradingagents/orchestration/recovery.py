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
from tradingagents.policy.live_control import (
    load_live_control_state,
    parse_control_time,
    write_live_control_state,
)

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
    source_packet_paths: Mapping[str, str] = field(default_factory=dict)
    recovery_manifest_path: str | None = None
    recovery_manifest_sha256: str | None = None


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
    if repairer_run is not None and verifier_run is not None and repairer_run.casefold() == verifier_run.casefold():
        issues.append("repairer and verifier run IDs must differ")
    repairer_role = _normalized_string(evidence.repairer_role_id)
    verifier_role = _normalized_string(evidence.verifier_role_id)
    if repairer_role is None:
        issues.append("repairer_role_id must be a nonblank string")
    if verifier_role is None:
        issues.append("verifier_role_id must be a nonblank string")
    if repairer_role is not None and verifier_role is not None and repairer_role.casefold() == verifier_role.casefold():
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
    required_bindings = {"incident_id", "symbol", "broker_account", "environment", "source_revision"}
    try:
        bindings_valid = isinstance(evidence.source_bindings, Mapping) and set(evidence.source_bindings) == required_bindings and all(_normalized_string(evidence.source_bindings.get(key)) is not None for key in required_bindings)
    except (AttributeError, KeyError, TypeError, ValueError):
        bindings_valid = False
    if not bindings_valid:
        issues.append("source bindings must contain canonical incident, symbol, account, environment, and source revision")
    packet_keys = {"incident", "reconciliation", "promotion", "focused"}
    try:
        packet_proof_complete = isinstance(evidence.source_packet_sha256, Mapping) and isinstance(evidence.source_packet_paths, Mapping) and set(evidence.source_packet_sha256) == packet_keys and set(evidence.source_packet_paths) == packet_keys
    except Exception:
        packet_proof_complete = False
    if not packet_proof_complete:
        issues.append("source packet path and hash proof is incomplete")
    else:
        for key in packet_keys:
            digest = evidence.source_packet_sha256.get(key)
            path = evidence.source_packet_paths.get(key)
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                issues.append(f"source packet hash is invalid for {key}")
            if not isinstance(path, str) or not Path(path).is_absolute():
                issues.append(f"source packet path is not absolute for {key}")
    if not isinstance(evidence.recovery_manifest_path, str) or not evidence.recovery_manifest_path or not Path(evidence.recovery_manifest_path).is_absolute() or str(Path(evidence.recovery_manifest_path).resolve()) != evidence.recovery_manifest_path:
        issues.append("recovery manifest path must be absolute")
    if not isinstance(evidence.recovery_manifest_sha256, str) or len(evidence.recovery_manifest_sha256) != 64 or any(char not in "0123456789abcdef" for char in evidence.recovery_manifest_sha256):
        issues.append("recovery manifest hash is invalid")
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


def write_rearm_receipt(
    receipt: Mapping[str, Any],
    receipt_dir: str | Path,
    *,
    now: dt.datetime | None = None,
    prepared_path: Path | None = None,
) -> dict[str, str]:
    """Durably create an immutable receipt, then update its non-authoritative pointer."""
    current = _as_utc(now)
    target_dir = Path(receipt_dir)
    payload = dict(receipt)
    encoded = _canonical_json(payload) + b"\n"
    digest = hashlib.sha256(encoded).hexdigest()
    for _ in range(16):
        path = prepared_path or _receipt_path(target_dir, current)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if prepared_path is not None:
                raise
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
    control_absolute_path = Path(control_path).resolve()
    receipt_root = Path(receipt_dir).resolve()
    if receipt_root.exists() and not receipt_root.is_dir():
        raise ValueError("rearm blocked: receipt_dir is not a directory")
    if control_absolute_path == receipt_root or control_absolute_path == receipt_root / "latest.json":
        raise ValueError("rearm blocked: control path collides with receipt path")
    proof_paths = {Path(path).resolve() for path in evidence.source_packet_paths.values()}
    if len(proof_paths) != len(evidence.source_packet_paths) or control_absolute_path in proof_paths or receipt_root / "latest.json" in proof_paths:
        raise ValueError("rearm blocked: proof paths collide with control authority")
    if evidence.recovery_manifest_path and Path(evidence.recovery_manifest_path).resolve() in proof_paths | {control_absolute_path, receipt_root / "latest.json"}:
        raise ValueError("rearm blocked: manifest path collides with control authority")
    state, _control_issues = load_live_control_state(control_path, now=current)
    if state is None or _normalized_string(state.get("reason")) is None or parse_control_time(str(state.get("dead_man_expires_at", ""))) is None:
        raise ValueError("rearm blocked: existing live control is not valid")
    if state.get("frozen") is not True:
        raise ValueError("rearm blocked: existing live control must be currently frozen")
    for key, expected in evidence.source_packet_sha256.items():
        try:
            actual = hashlib.sha256(Path(evidence.source_packet_paths[key]).read_bytes()).hexdigest()
        except (OSError, TypeError):
            raise ValueError(f"rearm blocked: source packet unavailable for {key}") from None
        if actual != expected:
            raise ValueError(f"rearm blocked: source packet hash changed for {key}")
    if evidence.recovery_manifest_path is not None:
        try:
            manifest_actual = hashlib.sha256(Path(evidence.recovery_manifest_path).read_bytes()).hexdigest()
        except OSError:
            raise ValueError("rearm blocked: recovery manifest unavailable") from None
        if manifest_actual != evidence.recovery_manifest_sha256:
            raise ValueError("rearm blocked: recovery manifest hash changed")
    expires_at = current + dt.timedelta(minutes=ttl)
    normalized_expiry = expires_at.astimezone(UTC).isoformat(timespec="seconds")
    control_absolute = str(control_absolute_path)
    prepared_receipt_path = str(_receipt_path(Path(receipt_dir), current).resolve())
    if Path(prepared_receipt_path) == control_absolute_path:
        raise ValueError("rearm blocked: control path collides with receipt path")
    reason = f"verified recovery {evidence.incident_id.strip()}"
    receipt = {
        "schema_version": 1,
        "kind": "verified_rearm_receipt",
        "incident_id": evidence.incident_id.strip(),
        "repairer_run_id": evidence.repairer_run_id.strip(),
        "verifier_run_id": evidence.verifier_run_id.strip(),
        "repairer_role_id": evidence.repairer_role_id.strip(),
        "verifier_role_id": evidence.verifier_role_id.strip(),
        "issued_at": current.isoformat(timespec="seconds"),
        "expires_at": normalized_expiry,
        "ttl_minutes": ttl,
        "broker_write_calls": 0,
        "can_submit_orders": False,
        "effective_only_when_control_matches_receipt_digest": True,
        "source_bindings": dict(evidence.source_bindings),
        "source_packet_sha256": dict(evidence.source_packet_sha256),
        "source_packet_paths": dict(evidence.source_packet_paths),
        "recovery_manifest_path": evidence.recovery_manifest_path,
        "recovery_manifest_sha256": evidence.recovery_manifest_sha256,
        "control_binding": {"control_path": control_absolute, "incident_id": evidence.incident_id.strip(), "reason": reason, "dead_man_expires_at": normalized_expiry, "frozen": False, "mode": "verified_recovery", "receipt_path": prepared_receipt_path},
    }
    receipt_ref = write_rearm_receipt(receipt, receipt_dir, now=current, prepared_path=Path(prepared_receipt_path))
    written = write_live_control_state(
        control_path,
        frozen=False,
        reason=reason,
        dead_man_expires_at=expires_at,
        recovery_receipt_path=receipt_ref["receipt_path"],
        recovery_receipt_sha256=receipt_ref["receipt_sha256"],
        recovery_incident_id=evidence.incident_id.strip(),
        recovery_mode="verified_recovery",
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
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("duplicate JSON key")
            output[key] = value
        return output
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, None, f"{label} packet is unreadable JSON"
    if not isinstance(value, dict):
        return None, None, f"{label} packet must be a JSON object"
    return value, hashlib.sha256(raw).hexdigest(), None


def _binding(packet: Mapping[str, Any], key: str) -> str | None:
    aliases = {"broker_account": ("broker_account", "account"), "source_revision": ("source_revision", "revision", "git_sha"), "symbol": ("symbol", "subject")}
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
    packet_paths: dict[str, str] = {}
    issues: list[str] = []
    for label, path in (("incident", incident_path), ("reconciliation", reconciliation_path), ("promotion", promotion_sync_path), ("focused proof", focused_proof_path)):
        packet, digest, issue = _read_packet(path, label)
        if issue:
            issues.append(issue)
        else:
            packets[label] = packet or {}
            digests[label] = digest or ""
            packet_paths["focused" if label == "focused proof" else label] = str(Path(path).resolve())
    if issues:
        return None, tuple(issues)
    required_bindings = ("incident_id", "symbol", "broker_account", "environment")
    bindings: dict[str, str] = {}
    manifest = None
    if recovery_manifest_path is not None:
        manifest, manifest_digest, manifest_issue = _read_packet(recovery_manifest_path, "recovery manifest")
        if manifest_issue:
            issues.append(manifest_issue)
        else:
            if manifest.get("schema_version") != "tradingagents.recovery_manifest.v1" or manifest.get("kind") != "verified_recovery_manifest":
                issues.append("recovery manifest has invalid schema or kind")
            _manifest_time, manifest_time_issue = _parse_time(manifest.get("generated_at"), field="recovery manifest timestamp", now=current)
            if manifest_time_issue:
                issues.append(manifest_time_issue)
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
            if _binding(packets["focused proof"], "source_revision") != bindings.get("source_revision"):
                issues.append("focused proof source_revision must match recovery manifest")
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
    blockers = _string_items(incident.get("external_blockers", []))
    if blockers is None:
        issues.append("incident external_blockers must be a list of strings")
        blockers = ()
    if incident.get("stage") != "ready":
        issues.append("incident is not ready")
    incident_repairer_run = _normalized_string(incident.get("repairer_run_id"))
    focused_verifier_run = _normalized_string(focused.get("verifier_run_id"))
    if incident_repairer_run is None or _normalized_string(repairer_run_id) is None or incident_repairer_run.casefold() != _normalized_string(repairer_run_id).casefold():
        issues.append("incident repairer_run_id does not bind CLI repairer")
    if focused_verifier_run is None or _normalized_string(verifier_run_id) is None or focused_verifier_run.casefold() != _normalized_string(verifier_run_id).casefold():
        issues.append("focused proof verifier_run_id does not bind CLI verifier")
    history = incident.get("history")
    lifecycle_ready = (
        incident.get("schema_version") == "tradingagents.incident.v1"
        and incident.get("stage") == "ready"
        and isinstance(history, list)
        and any(isinstance(event, dict) and event.get("to_stage") == "ready" for event in history)
        and bool(_string_items(incident.get("evidence_refs")))
    )
    root_cause = lifecycle_ready
    if incident.get("root_cause_resolved") is False:
        root_cause = False
    if not lifecycle_ready:
        issues.append("incident lacks canonical ready lifecycle proof")
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
    repairer_role = _normalized_string(incident.get("repairer_role_id") or incident.get("owner_role"))
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
        external_blockers=blockers,
        source_bindings=bindings,
        source_packet_sha256={"focused" if label == "focused proof" else label: digest for label, digest in digests.items()},
        source_packet_paths=packet_paths,
        recovery_manifest_path=str(Path(recovery_manifest_path).resolve()) if recovery_manifest_path else None,
        recovery_manifest_sha256=manifest_digest if recovery_manifest_path else None,
    )
    return evidence, ()
