"""Fail-closed, broker-free recovery evidence and bounded re-arm coordination."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.live_control import (
    _write_live_control_state_locked,
    live_control_lock,
    load_live_control_state,
    parse_control_time,
)
from tradingagents.policy.promotion_sync import promotion_state_lock

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
    except Exception:
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
            try:
                digest = evidence.source_packet_sha256.get(key)
                path = evidence.source_packet_paths.get(key)
            except Exception:
                issues.append(f"source packet proof is unreadable for {key}")
                continue
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                issues.append(f"source packet hash is invalid for {key}")
            if not isinstance(path, str) or not Path(path).is_absolute() or str(Path(path).resolve()) != path:
                issues.append(f"source packet path is not absolute for {key}")
    if bindings_valid and evidence.source_bindings.get("incident_id") != evidence.incident_id:
        issues.append("source binding incident_id must match recovery evidence")
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
    publish_latest: bool = True,
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
        receipt_ref = {
            "receipt_path": str(path.resolve()),
            "receipt_sha256": digest,
        }
        if publish_latest:
            publish_rearm_receipt(
                receipt_ref,
                target_dir,
                now=current,
            )
        return receipt_ref
    raise OSError("could not allocate a unique recovery receipt path")


def publish_rearm_receipt(
    receipt_ref: Mapping[str, str],
    receipt_dir: str | Path,
    *,
    now: dt.datetime | None = None,
) -> Path:
    """Publish the non-authoritative pointer after control accepts the receipt."""

    current = _as_utc(now)
    receipt_path = receipt_ref.get("receipt_path")
    receipt_sha256 = receipt_ref.get("receipt_sha256")
    if (
        not isinstance(receipt_path, str)
        or not Path(receipt_path).is_absolute()
        or str(Path(receipt_path).resolve()) != receipt_path
        or not isinstance(receipt_sha256, str)
        or len(receipt_sha256) != 64
        or any(char not in "0123456789abcdef" for char in receipt_sha256)
    ):
        raise ValueError("rearm receipt reference is invalid")
    latest = {
        "kind": "verified_rearm_latest",
        "receipt_path": receipt_path,
        "receipt_sha256": receipt_sha256,
        "updated_at": current.isoformat(),
        "can_submit_orders": False,
    }
    latest_path = Path(receipt_dir) / "latest.json"
    return atomic_write_text(
        latest_path,
        json.dumps(latest, indent=2, sort_keys=True),
    )


def _promotion_closure_references(
    evidence: RecoveryEvidence,
    promotion: Mapping[str, Any],
) -> dict[str, tuple[Path, str]]:
    recovery_commit = promotion.get("recovery_commit")
    prepare_ref = promotion.get("promotion_prepare")
    commit_ref = promotion.get("promotion_commit")
    references: dict[str, tuple[object, object]] = {
        name: (
            evidence.source_packet_paths.get(name),
            evidence.source_packet_sha256.get(name),
        )
        for name in ("incident", "reconciliation", "promotion", "focused")
    }
    references["manifest"] = (
        evidence.recovery_manifest_path,
        evidence.recovery_manifest_sha256,
    )
    if isinstance(recovery_commit, Mapping):
        references["promotion_report"] = (
            recovery_commit.get("report_path"),
            recovery_commit.get("report_sha256"),
        )
        references["promotion_envelope"] = (
            recovery_commit.get("envelope_path"),
            recovery_commit.get("envelope_sha256"),
        )
    if isinstance(prepare_ref, Mapping):
        references["promotion_prepare"] = (
            prepare_ref.get("path"),
            prepare_ref.get("sha256"),
        )
    references["promotion_stage"] = (
        promotion.get("staged_state_path"),
        promotion.get("staged_state_sha256"),
    )
    if isinstance(commit_ref, Mapping):
        references["promotion_commit"] = (
            commit_ref.get("path"),
            commit_ref.get("sha256"),
        )
    references["promotion_canonical"] = (
        promotion.get("state_path"),
        promotion.get("canonical_after_sha256"),
    )
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
    if set(references) != required:
        raise ValueError(
            "rearm blocked: promotion transaction closure is incomplete"
        )
    closure: dict[str, tuple[Path, str]] = {}
    for name, (raw_path, raw_digest) in references.items():
        path = _canonical_reference(raw_path)
        digest = _sha256_reference(raw_digest)
        if path is None or digest is None:
            raise ValueError(
                "rearm blocked: promotion transaction closure reference is "
                f"invalid for {name}"
            )
        closure[name] = (path, digest)
    return closure


def _snapshot_promotion_closure(
    references: Mapping[str, tuple[Path, str]],
    *,
    receipt_path: Path,
) -> dict[str, dict[str, str]]:
    closure_dir = receipt_path.with_name(receipt_path.name + ".closure")
    closure_dir.mkdir(parents=True, exist_ok=False)
    snapshot: dict[str, dict[str, str]] = {}
    for name, (source_path, expected_digest) in references.items():
        try:
            raw = source_path.read_bytes()
        except OSError:
            raise ValueError(
                f"rearm blocked: promotion transaction closure is unavailable for {name}"
            ) from None
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError(
                f"rearm blocked: promotion transaction closure changed for {name}"
            )
        target = closure_dir / f"{name}.bin"
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                if written <= 0:
                    raise OSError(
                        "incomplete promotion closure snapshot write"
                    )
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        snapshot[name] = {
            "source_path": str(source_path),
            "snapshot_path": str(target.resolve()),
            "sha256": expected_digest,
        }
    parent_descriptor = os.open(closure_dir, os.O_RDONLY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return snapshot


def _control_accepts_exact_receipt(
    control_path: Path,
    *,
    receipt_ref: Mapping[str, str],
    evidence: RecoveryEvidence,
    reason: str,
    expires_at: dt.datetime,
    now: dt.datetime,
) -> bool:
    state, issues = load_live_control_state(control_path, now=now)
    return (
        state is not None
        and not issues
        and state.get("frozen") is False
        and state.get("reason") == reason
        and parse_control_time(str(state.get("dead_man_expires_at", "")))
        == expires_at.astimezone(UTC).replace(microsecond=0)
        and state.get("recovery_receipt_path")
        == receipt_ref.get("receipt_path")
        and state.get("recovery_receipt_sha256")
        == receipt_ref.get("receipt_sha256")
        and state.get("recovery_incident_id") == evidence.incident_id.strip()
        and state.get("recovery_mode") == "verified_recovery"
    )


def rearm_after_verified_recovery(
    *,
    evidence: RecoveryEvidence,
    control_path: str | Path,
    receipt_dir: str | Path,
    expected_control_preimage_sha256: str,
    ttl_minutes: int = MAX_REARM_TTL_MINUTES,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Re-arm only a currently frozen control after durable independent evidence."""
    if _sha256_reference(expected_control_preimage_sha256) is None:
        raise ValueError(
            "rearm blocked: expected frozen control preimage is required"
        )
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
    promotion_packet_path = evidence.source_packet_paths.get("promotion")
    promotion_canonical_path: Path | None = None
    try:
        promotion_packet = json.loads(
            Path(str(promotion_packet_path)).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(
            "rearm blocked: promotion packet is unreadable"
        ) from None
    if not isinstance(promotion_packet, Mapping):
        raise ValueError(
            "rearm blocked: promotion packet must be an object"
        )
    promotion_canonical_path = _canonical_reference(
        promotion_packet.get("state_path")
    )
    if promotion_canonical_path is None:
        raise ValueError(
            "rearm blocked: promotion canonical transaction reference is "
            "required"
        )
    closure_references = _promotion_closure_references(
        evidence,
        promotion_packet,
    )

    with promotion_state_lock(promotion_canonical_path):
        refreshed, refresh_issues = load_recovery_evidence(
            incident_path=evidence.source_packet_paths["incident"],
            reconciliation_path=evidence.source_packet_paths[
                "reconciliation"
            ],
            promotion_sync_path=evidence.source_packet_paths["promotion"],
            focused_proof_path=evidence.source_packet_paths["focused"],
            recovery_manifest_path=evidence.recovery_manifest_path,
            repairer_run_id=evidence.repairer_run_id,
            verifier_run_id=evidence.verifier_run_id,
            now=current,
        )
        if refreshed is None or refresh_issues or refreshed != evidence:
            detail = (
                "; ".join(refresh_issues)
                if refresh_issues
                else "recovery evidence changed before re-arm"
            )
            raise ValueError("rearm blocked: " + detail)

        for key, expected in evidence.source_packet_sha256.items():
            try:
                actual = hashlib.sha256(
                    Path(evidence.source_packet_paths[key]).read_bytes()
                ).hexdigest()
            except (OSError, TypeError):
                raise ValueError(
                    f"rearm blocked: source packet unavailable for {key}"
                ) from None
            if actual != expected:
                raise ValueError(
                    f"rearm blocked: source packet hash changed for {key}"
                )
        if evidence.recovery_manifest_path is not None:
            try:
                manifest_actual = hashlib.sha256(
                    Path(evidence.recovery_manifest_path).read_bytes()
                ).hexdigest()
            except OSError:
                raise ValueError(
                    "rearm blocked: recovery manifest unavailable"
                ) from None
            if manifest_actual != evidence.recovery_manifest_sha256:
                raise ValueError(
                    "rearm blocked: recovery manifest hash changed"
                )

        with live_control_lock(control_absolute_path):
            try:
                control_preimage = control_absolute_path.read_bytes()
            except OSError:
                raise ValueError(
                    "rearm blocked: existing live control is not valid"
                ) from None
            accepted_preimage_sha256 = hashlib.sha256(
                control_preimage
            ).hexdigest()
            if accepted_preimage_sha256 != expected_control_preimage_sha256:
                raise ValueError(
                    "rearm blocked: live control no longer matches the "
                    "recovery-owned freeze"
                )
            state, control_issues = load_live_control_state(
                control_absolute_path,
                now=current,
            )
            unsafe_control_issues = [
                issue
                for issue in control_issues
                if not issue.startswith("live control state is frozen:")
                and not issue.startswith("dead-man expired at ")
            ]
            if (
                state is None
                or _normalized_string(state.get("reason")) is None
                or parse_control_time(
                    str(state.get("dead_man_expires_at", ""))
                )
                is None
                or unsafe_control_issues
            ):
                raise ValueError(
                    "rearm blocked: existing live control is not valid"
                )
            if state.get("frozen") is not True:
                raise ValueError(
                    "rearm blocked: existing live control must be currently frozen"
                )

            expires_at = current + dt.timedelta(minutes=ttl)
            normalized_expiry = expires_at.astimezone(UTC).isoformat(
                timespec="seconds"
            )
            control_absolute = str(control_absolute_path)
            prepared_receipt_path = str(
                _receipt_path(Path(receipt_dir), current).resolve()
            )
            if Path(prepared_receipt_path) == control_absolute_path:
                raise ValueError(
                    "rearm blocked: control path collides with receipt path"
                )
            closure_snapshot = _snapshot_promotion_closure(
                closure_references,
                receipt_path=Path(prepared_receipt_path),
            )
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
                "control_preimage_sha256": accepted_preimage_sha256,
                "source_bindings": dict(evidence.source_bindings),
                "source_packet_sha256": dict(
                    evidence.source_packet_sha256
                ),
                "source_packet_paths": dict(evidence.source_packet_paths),
                "recovery_manifest_path": evidence.recovery_manifest_path,
                "recovery_manifest_sha256": evidence.recovery_manifest_sha256,
                "promotion_transaction_closure": closure_snapshot,
                "control_binding": {
                    "control_path": control_absolute,
                    "incident_id": evidence.incident_id.strip(),
                    "reason": reason,
                    "dead_man_expires_at": normalized_expiry,
                    "frozen": False,
                    "mode": "verified_recovery",
                    "receipt_path": prepared_receipt_path,
                },
            }
            receipt_ref = write_rearm_receipt(
                receipt,
                receipt_dir,
                now=current,
                prepared_path=Path(prepared_receipt_path),
                publish_latest=False,
            )
            latest_path = Path(receipt_dir) / "latest.json"
            prior_latest = (
                latest_path.read_bytes() if latest_path.exists() else None
            )
            publish_rearm_receipt(
                receipt_ref,
                receipt_dir,
                now=current,
            )
            try:
                written = _write_live_control_state_locked(
                    control_absolute_path,
                    frozen=False,
                    reason=reason,
                    dead_man_expires_at=expires_at,
                    recovery_receipt_path=receipt_ref["receipt_path"],
                    recovery_receipt_sha256=receipt_ref["receipt_sha256"],
                    recovery_incident_id=evidence.incident_id.strip(),
                    recovery_mode="verified_recovery",
                    expected_preimage_sha256=accepted_preimage_sha256,
                    now=current,
                )
            except Exception as write_error:
                if _control_accepts_exact_receipt(
                    control_absolute_path,
                    receipt_ref=receipt_ref,
                    evidence=evidence,
                    reason=reason,
                    expires_at=expires_at,
                    now=current,
                ):
                    try:
                        publish_rearm_receipt(
                            receipt_ref,
                            receipt_dir,
                            now=current,
                        )
                    except Exception:
                        try:
                            _write_live_control_state_locked(
                                control_absolute_path,
                                frozen=True,
                                reason=(
                                    "verified recovery frozen: receipt pointer "
                                    "repair failed"
                                ),
                                dead_man_expires_at=current
                                + dt.timedelta(hours=6),
                                now=current,
                            )
                        except Exception:
                            closed, _closed_issues = load_live_control_state(
                                control_absolute_path,
                                now=current,
                            )
                            if (
                                not isinstance(closed, Mapping)
                                or closed.get("frozen") is not True
                            ):
                                raise RuntimeError(
                                    "rearm opened control but could not repair "
                                    "the receipt pointer or restore a freeze"
                                ) from write_error
                        raise
                    else:
                        written = control_absolute_path
                else:
                    control_state, _control_issues = (
                        load_live_control_state(
                            control_absolute_path,
                            now=current,
                        )
                    )
                    if (
                        not isinstance(control_state, Mapping)
                        or control_state.get("frozen") is not True
                    ):
                        try:
                            _write_live_control_state_locked(
                                control_absolute_path,
                                frozen=True,
                                reason=(
                                    "verified recovery frozen: live-control "
                                    "transition failed"
                                ),
                                dead_man_expires_at=current
                                + dt.timedelta(hours=6),
                                now=current,
                            )
                        except Exception:
                            closed, _closed_issues = load_live_control_state(
                                control_absolute_path,
                                now=current,
                            )
                            if (
                                not isinstance(closed, Mapping)
                                or closed.get("frozen") is not True
                            ):
                                raise RuntimeError(
                                    "rearm blocked and live control could not "
                                    "be frozen"
                                ) from write_error
                    if prior_latest is None:
                        with suppress(FileNotFoundError):
                            latest_path.unlink()
                    else:
                        atomic_write_text(
                            latest_path,
                            prior_latest.decode("utf-8"),
                        )
                    raise
            return {
                **receipt_ref,
                "control_path": str(written),
                "expires_at": expires_at.isoformat(),
                "can_submit_orders": False,
            }


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


def _canonical_reference(value: object) -> Path | None:
    normalized = _normalized_string(value)
    if normalized is None:
        return None
    path = Path(normalized)
    if not path.is_absolute() or str(path.resolve()) != normalized:
        return None
    return path


def _sha256_reference(value: object) -> str | None:
    normalized = _normalized_string(value)
    if (
        normalized is None
        or len(normalized) != 64
        or any(char not in "0123456789abcdef" for char in normalized)
    ):
        return None
    return normalized


def _promotion_transaction_issues(
    *,
    promotion: Mapping[str, Any],
    promotion_sync_path: str | Path,
    focused_proof_path: str | Path,
    reconciliation_path: str | Path,
    focused: Mapping[str, Any],
    bindings: Mapping[str, str],
) -> list[str]:
    issues: list[str] = []
    phase_path = Path(promotion_sync_path).resolve()
    expected_prepare_path = phase_path.with_name("promotion_prepare.json")
    expected_commit_path = phase_path.with_name("promotion_commit.json")
    prepare_ref = promotion.get("promotion_prepare")
    commit_ref = promotion.get("promotion_commit")
    stage_request = promotion.get("promotion_stage_request")
    state_path = _canonical_reference(promotion.get("state_path"))
    staged_path = _canonical_reference(
        promotion.get("staged_state_path")
    )
    after_sha256 = _sha256_reference(
        promotion.get("canonical_after_sha256")
    )
    staged_sha256 = _sha256_reference(
        promotion.get("staged_state_sha256")
    )
    recovery_commit = promotion.get("recovery_commit")
    if (
        not isinstance(prepare_ref, Mapping)
        or set(prepare_ref) != {"path", "sha256"}
        or _canonical_reference(prepare_ref.get("path"))
        != expected_prepare_path
        or _sha256_reference(prepare_ref.get("sha256")) is None
    ):
        issues.append("promotion prepare receipt reference is invalid")
    if (
        not isinstance(commit_ref, Mapping)
        or set(commit_ref) != {"path", "sha256"}
        or _canonical_reference(commit_ref.get("path"))
        != expected_commit_path
        or _sha256_reference(commit_ref.get("sha256")) is None
    ):
        issues.append("promotion commit receipt reference is invalid")
    if state_path is None or staged_path is None:
        issues.append("promotion state references must be canonical absolute paths")
    if (
        after_sha256 is None
        or staged_sha256 is None
        or after_sha256 != staged_sha256
    ):
        issues.append("promotion staged and canonical digests are invalid")
    recovery_commit_keys = {
        "schema_version",
        "commit_id",
        "incident_id",
        "recovery_run_id",
        "source_revision",
        "focused_path",
        "focused_sha256",
        "verifier_run_id",
        "verifier_role_id",
        "reconciliation_path",
        "reconciliation_sha256",
        "report_path",
        "report_sha256",
        "envelope_path",
        "envelope_sha256",
        "canonical_path",
        "canonical_before_sha256",
        "candidate_payload_sha256",
    }
    if (
        not isinstance(recovery_commit, Mapping)
        or set(recovery_commit) != recovery_commit_keys
    ):
        issues.append("promotion recovery commit schema is invalid")
        return issues
    digest_fields = {
        "commit_id",
        "focused_sha256",
        "reconciliation_sha256",
        "report_sha256",
        "envelope_sha256",
        "canonical_before_sha256",
        "candidate_payload_sha256",
    }
    if any(
        _sha256_reference(recovery_commit.get(field)) is None
        for field in digest_fields
    ):
        issues.append("promotion recovery commit digest is invalid")
    commit_seed = dict(recovery_commit)
    commit_id = commit_seed.pop("commit_id")
    expected_commit_id = hashlib.sha256(
        _canonical_json(commit_seed) + b"\n"
    ).hexdigest()
    if commit_id != expected_commit_id:
        issues.append("promotion recovery commit identity is invalid")
    focused_path = Path(focused_proof_path).resolve()
    reconciliation_absolute = Path(reconciliation_path).resolve()
    if (
        recovery_commit.get("schema_version")
        != "tradingagents.promotion_recovery_commit.v1"
        or recovery_commit.get("incident_id") != bindings.get("incident_id")
        or recovery_commit.get("source_revision")
        != bindings.get("source_revision")
        or recovery_commit.get("focused_path") != str(focused_path)
        or recovery_commit.get("reconciliation_path")
        != str(reconciliation_absolute)
        or recovery_commit.get("verifier_run_id")
        != focused.get("verifier_run_id")
        or recovery_commit.get("verifier_role_id")
        != focused.get("verifier_role_id")
        or (
            state_path is not None
            and recovery_commit.get("canonical_path")
            != str(state_path)
        )
    ):
        issues.append("promotion recovery commit binding is invalid")
    try:
        if (
            hashlib.sha256(focused_path.read_bytes()).hexdigest()
            != recovery_commit.get("focused_sha256")
            or hashlib.sha256(
                reconciliation_absolute.read_bytes()
            ).hexdigest()
            != recovery_commit.get("reconciliation_sha256")
        ):
            issues.append("promotion proof digest binding is invalid")
    except OSError:
        issues.append("promotion proof binding is unreadable")

    report_path = _canonical_reference(recovery_commit.get("report_path"))
    envelope_path = _canonical_reference(
        recovery_commit.get("envelope_path")
    )
    if report_path is None or envelope_path is None:
        issues.append("promotion input references are not canonical")
    else:
        try:
            report_raw = report_path.read_bytes()
            envelope_raw = envelope_path.read_bytes()
            report = json.loads(report_raw)
        except (OSError, json.JSONDecodeError):
            issues.append("promotion input binding is unreadable")
        else:
            if (
                hashlib.sha256(report_raw).hexdigest()
                != recovery_commit.get("report_sha256")
                or hashlib.sha256(envelope_raw).hexdigest()
                != recovery_commit.get("envelope_sha256")
            ):
                issues.append("promotion input digest binding is invalid")
            report_payload = (
                report.get("latest_report")
                if isinstance(report, Mapping)
                and isinstance(report.get("latest_report"), Mapping)
                else report
            )
            candidate = (
                report_payload.get("live_strategy_candidate")
                if isinstance(report_payload, Mapping)
                and isinstance(
                    report_payload.get("live_strategy_candidate"),
                    Mapping,
                )
                else {}
            )
            candidate_sha256 = hashlib.sha256(
                _canonical_json(dict(candidate)) + b"\n"
            ).hexdigest()
            if (
                candidate_sha256
                != recovery_commit.get("candidate_payload_sha256")
            ):
                issues.append("promotion candidate digest binding is invalid")

    if (
        not isinstance(prepare_ref, Mapping)
        or set(prepare_ref) != {"path", "sha256"}
        or _canonical_reference(prepare_ref.get("path"))
        != expected_prepare_path
        or _sha256_reference(prepare_ref.get("sha256")) is None
        or not isinstance(commit_ref, Mapping)
        or set(commit_ref) != {"path", "sha256"}
        or _canonical_reference(commit_ref.get("path"))
        != expected_commit_path
        or _sha256_reference(commit_ref.get("sha256")) is None
        or state_path is None
        or staged_path is None
        or after_sha256 is None
        or staged_sha256 is None
    ):
        return issues
    try:
        prepare_raw = expected_prepare_path.read_bytes()
        commit_raw = expected_commit_path.read_bytes()
        staged_raw = staged_path.read_bytes()
        canonical_raw = state_path.read_bytes()
        prepare = json.loads(prepare_raw)
        receipt = json.loads(commit_raw)
        staged_state = json.loads(staged_raw)
        canonical_state = json.loads(canonical_raw)
    except (OSError, json.JSONDecodeError):
        issues.append("promotion transaction artifact is unreadable")
        return issues
    if (
        hashlib.sha256(prepare_raw).hexdigest()
        != prepare_ref.get("sha256")
        or hashlib.sha256(commit_raw).hexdigest()
        != commit_ref.get("sha256")
        or hashlib.sha256(staged_raw).hexdigest() != staged_sha256
        or hashlib.sha256(canonical_raw).hexdigest() != after_sha256
        or staged_raw != canonical_raw
    ):
        issues.append("promotion transaction artifact digest is invalid")
    expected_prepare = {
        "schema_version": "tradingagents.promotion_prepare.v1",
        "kind": "promotion_commit_prepare",
        "recovery_commit": dict(recovery_commit),
        "stage_path": str(staged_path),
        "generated_at": canonical_state.get("generated_at"),
        "arm_live": True,
        "ci_green": True,
        "expected_raw_stage_sha256": prepare.get(
            "expected_raw_stage_sha256"
        ),
        "expected_stage_sha256": staged_sha256,
        "can_submit_orders": False,
        "execution_authority": "none",
    }
    expected_stage_request = {
        "commit_id": recovery_commit.get("commit_id"),
        "prepare_path": str(expected_prepare_path),
        "prepare_sha256": prepare_ref["sha256"],
        "stage_path": str(staged_path),
        "expected_raw_stage_sha256": prepare.get(
            "expected_raw_stage_sha256"
        ),
        "expected_stage_sha256": staged_sha256,
        "generated_at": canonical_state.get("generated_at"),
        "canonical_path": str(state_path),
        "canonical_before_sha256": recovery_commit.get(
            "canonical_before_sha256"
        ),
        "report_sha256": recovery_commit.get("report_sha256"),
        "envelope_sha256": recovery_commit.get("envelope_sha256"),
        "focused_sha256": recovery_commit.get("focused_sha256"),
        "reconciliation_sha256": recovery_commit.get(
            "reconciliation_sha256"
        ),
        "arm_live": True,
        "ci_green": True,
    }
    expected_receipt = {
        "schema_version": "tradingagents.promotion_commit.v1",
        "kind": "verified_promotion_commit",
        "recovery_commit": dict(recovery_commit),
        "prepare_path": str(expected_prepare_path),
        "prepare_sha256": prepare_ref["sha256"],
        "staged_path": str(staged_path),
        "staged_sha256": staged_sha256,
        "canonical_path": str(state_path),
        "canonical_before_sha256": recovery_commit.get(
            "canonical_before_sha256"
        ),
        "canonical_after_sha256": after_sha256,
        "can_submit_orders": False,
        "execution_authority": "none",
    }
    if (
        _sha256_reference(prepare.get("expected_raw_stage_sha256")) is None
        or prepare != expected_prepare
    ):
        issues.append("promotion prepare receipt binding is invalid")
    if stage_request != expected_stage_request:
        issues.append("promotion stage request binding is invalid")
    if receipt != expected_receipt:
        issues.append("promotion commit receipt binding is invalid")
    source = (
        canonical_state.get("source")
        if isinstance(canonical_state, Mapping)
        else None
    )
    if (
        staged_state != canonical_state
        or promotion.get("state") != canonical_state
        or not isinstance(source, Mapping)
        or source.get("recovery_commit") != recovery_commit
        or source.get("canonical_input_sha256")
        != recovery_commit.get("canonical_before_sha256")
    ):
        issues.append("promotion canonical state binding is invalid")
    return issues


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
    issues.extend(
        _promotion_transaction_issues(
            promotion=promotion,
            promotion_sync_path=promotion_sync_path,
            focused_proof_path=focused_proof_path,
            reconciliation_path=reconciliation_path,
            focused=focused,
            bindings=bindings,
        )
    )
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
