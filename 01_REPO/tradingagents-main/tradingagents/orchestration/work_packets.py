"""Compact, deterministic, analysis-only packets for agent handoffs."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORK_PACKET_SCHEMA_VERSION = 1
MAX_PACKET_BYTES = 16 * 1024
MAX_CLAIMS = 5
MAX_ASSUMPTIONS = 5
MAX_CLAIM_CHARS = 500
MAX_RECOMMENDATION_CHARS = 1_000
MAX_ROLE_SUBJECT_CHARS = 160

ALLOWED_PACKET_KINDS = frozenset(
    {
        "research_evidence",
        "research_synthesis",
        "trader_proposal",
        "risk_review",
        "portfolio_decision",
    }
)
ADVISORY_ALLOWED_EFFECTS = frozenset(
    {
        "request_more_research",
        "downrank_confidence",
        "recommend_hold_cash",
        "recommend_block",
        "recommend_trade_proposal",
        "recommend_strategy_candidate",
        "recommend_risk_envelope",
    }
)
REQUIRED_FORBIDDEN_EFFECTS = frozenset(
    {
        "submit_order",
        "cancel_order",
        "replace_order",
        "size_position",
        "waive_live_gate",
        "override_risk_envelope",
        "arm_live_control",
    }
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_EFFECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC = dt.timezone.utc
_AUTHORITY_FIELDS = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_DATACLASS_FIELDS = (
    "schema_version",
    "packet_id",
    "kind",
    "created_at",
    "expires_at",
    "producer_role",
    "run_id",
    "subject",
    "evidence_refs",
    "parent_packet_ids",
    "claims",
    "assumptions",
    "recommendation",
    "confidence",
    "allowed_effects",
    "forbidden_effects",
)
_COMPACT_FIELDS = frozenset((*_DATACLASS_FIELDS, *_AUTHORITY_FIELDS))
_COLLECTION_FIELDS = (
    "evidence_refs",
    "parent_packet_ids",
    "claims",
    "assumptions",
    "allowed_effects",
    "forbidden_effects",
)


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def _string_tuple(value: Sequence[str] | None, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a collection of strings")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} must contain only strings")
        normalized.append(item.strip())
    return tuple(normalized)


def _aware_utc(value: dt.datetime, *, field: str) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(_UTC).replace(microsecond=0)


def _utc_iso(value: dt.datetime, *, field: str) -> str:
    return _aware_utc(value, field=field).isoformat(timespec="seconds")


def _parse_stored_utc(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    normalized = parsed.astimezone(_UTC)
    if normalized.microsecond != 0:
        return None
    if normalized.isoformat(timespec="seconds") != value:
        return None
    return normalized


def _valid_packet_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    for kind in ALLOWED_PACKET_KINDS:
        suffix = f"-{kind}"
        if not value.startswith("wp-") or not value.endswith(suffix):
            continue
        run_id = value[3 : -len(suffix)]
        try:
            return build_packet_id(run_id, kind) == value
        except ValueError:
            return False
    return False


def _raise_for_issues(issues: Sequence[str]) -> None:
    if issues:
        raise ValueError("; ".join(issues))


def build_packet_id(run_id: str, kind: str) -> str:
    """Derive the stable packet identity for one graph run and packet kind."""

    clean_run_id = _required_text(run_id, field="run_id")
    clean_kind = _required_text(kind, field="kind")
    if _SAFE_RUN_ID.fullmatch(clean_run_id) is None:
        raise ValueError("run_id is not a safe packet token")
    if clean_kind not in ALLOWED_PACKET_KINDS:
        raise ValueError(f"unsupported work packet kind: {clean_kind}")
    return f"wp-{clean_run_id}-{clean_kind}"


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    sha256: str
    size_bytes: int

    @classmethod
    def from_path(cls, path: str | Path) -> EvidenceRef:
        source = Path(path)
        if not source.is_file():
            raise ValueError(f"evidence path is not a regular file: {source}")
        try:
            payload = source.read_bytes()
        except OSError as exc:
            raise ValueError(f"evidence file is unreadable: {source}") from exc
        return cls(
            path=str(source),
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )

    def resolve(self, root: str | Path | None = None) -> Path:
        stored = Path(self.path)
        if root is None:
            return stored
        resolved_root = Path(root).resolve()
        resolved = (
            stored.resolve()
            if stored.is_absolute()
            else (resolved_root / stored).resolve()
        )
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("evidence path escapes evidence root") from exc
        return resolved

    def verify(self, root: str | Path | None = None) -> bool:
        try:
            source = self.resolve(root)
            if not source.is_file():
                return False
            payload = source.read_bytes()
        except (OSError, ValueError):
            return False
        return (
            not isinstance(self.size_bytes, bool)
            and isinstance(self.size_bytes, int)
            and len(payload) == self.size_bytes
            and hashlib.sha256(payload).hexdigest() == self.sha256
        )


@dataclass(frozen=True)
class WorkPacket:
    schema_version: int
    packet_id: str
    kind: str
    created_at: str
    expires_at: str
    producer_role: str
    run_id: str
    subject: str
    evidence_refs: tuple[EvidenceRef, ...]
    parent_packet_ids: tuple[str, ...]
    claims: tuple[str, ...]
    assumptions: tuple[str, ...]
    recommendation: str
    confidence: float
    allowed_effects: tuple[str, ...]
    forbidden_effects: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        producer_role: str,
        run_id: str,
        subject: str,
        evidence_refs: Sequence[EvidenceRef],
        claims: Sequence[str],
        assumptions: Sequence[str],
        recommendation: str,
        confidence: float,
        expires_at: dt.datetime,
        parent_packet_ids: Sequence[str] | None = None,
        allowed_effects: Sequence[str] | None = None,
        forbidden_effects: Sequence[str] | None = None,
        now: dt.datetime | None = None,
    ) -> WorkPacket:
        current = _aware_utc(
            now if now is not None else dt.datetime.now(tz=_UTC),
            field="now",
        )
        expiry = _aware_utc(expires_at, field="expires_at")
        clean_kind = _required_text(kind, field="kind")
        clean_run_id = _required_text(run_id, field="run_id")
        clean_allowed = _string_tuple(allowed_effects, field="allowed_effects")
        clean_forbidden = _string_tuple(
            forbidden_effects,
            field="forbidden_effects",
        )
        if len(clean_allowed) != len(set(clean_allowed)):
            raise ValueError("allowed_effects must be unique")
        if len(clean_forbidden) != len(set(clean_forbidden)):
            raise ValueError("forbidden_effects must be unique")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("confidence must be an int or float")
        clean_confidence = float(confidence)
        packet = cls(
            schema_version=WORK_PACKET_SCHEMA_VERSION,
            packet_id=build_packet_id(clean_run_id, clean_kind),
            kind=clean_kind,
            created_at=_utc_iso(current, field="now"),
            expires_at=_utc_iso(expiry, field="expires_at"),
            producer_role=_required_text(producer_role, field="producer_role"),
            run_id=clean_run_id,
            subject=_required_text(subject, field="subject"),
            evidence_refs=tuple(evidence_refs),
            parent_packet_ids=_string_tuple(
                parent_packet_ids,
                field="parent_packet_ids",
            ),
            claims=_string_tuple(claims, field="claims"),
            assumptions=_string_tuple(assumptions, field="assumptions"),
            recommendation=_required_text(
                recommendation,
                field="recommendation",
            ),
            confidence=clean_confidence,
            allowed_effects=tuple(sorted(clean_allowed)),
            forbidden_effects=tuple(
                sorted(REQUIRED_FORBIDDEN_EFFECTS | set(clean_forbidden))
            ),
        )
        _raise_for_issues(
            packet.validate(
                now=current,
                verify_evidence=True,
            )
        )
        return packet

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        now: dt.datetime | None = None,
    ) -> WorkPacket:
        if not isinstance(payload, Mapping):
            raise ValueError("work packet payload must be a mapping")
        payload_keys = tuple(payload)
        if not all(isinstance(key, str) for key in payload_keys):
            raise ValueError("work packet field names must be strings")
        keys = set(payload_keys)
        missing = sorted(_COMPACT_FIELDS - keys)
        unknown = sorted(keys - _COMPACT_FIELDS)
        if missing or unknown:
            details = []
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown fields: {', '.join(unknown)}")
            raise ValueError("; ".join(details))
        if payload["analysis_only"] is not True:
            raise ValueError("analysis_only must be true")
        if payload["execution_authority"] != "none":
            raise ValueError("execution_authority must be none")
        if payload["can_submit_orders"] is not False:
            raise ValueError("can_submit_orders must be false")
        for field in _COLLECTION_FIELDS:
            if not isinstance(payload[field], list):
                raise ValueError(f"{field} must be a list")

        evidence_refs: list[EvidenceRef] = []
        evidence_fields = {"path", "sha256", "size_bytes"}
        for index, item in enumerate(payload["evidence_refs"]):
            if not isinstance(item, Mapping) or set(item) != evidence_fields:
                raise ValueError(
                    f"evidence_refs[{index}] must contain path, sha256, and size_bytes"
                )
            evidence_refs.append(
                EvidenceRef(
                    path=item["path"],
                    sha256=item["sha256"],
                    size_bytes=item["size_bytes"],
                )
            )

        packet = cls(
            schema_version=payload["schema_version"],
            packet_id=payload["packet_id"],
            kind=payload["kind"],
            created_at=payload["created_at"],
            expires_at=payload["expires_at"],
            producer_role=payload["producer_role"],
            run_id=payload["run_id"],
            subject=payload["subject"],
            evidence_refs=tuple(evidence_refs),
            parent_packet_ids=tuple(payload["parent_packet_ids"]),
            claims=tuple(payload["claims"]),
            assumptions=tuple(payload["assumptions"]),
            recommendation=payload["recommendation"],
            confidence=payload["confidence"],
            allowed_effects=tuple(payload["allowed_effects"]),
            forbidden_effects=tuple(payload["forbidden_effects"]),
        )
        _raise_for_issues(packet.validate(now=now, verify_evidence=False))
        return packet

    def compact(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "packet_id": self.packet_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "producer_role": self.producer_role,
            "run_id": self.run_id,
            "subject": self.subject,
            "evidence_refs": [
                {
                    "path": ref.path,
                    "sha256": ref.sha256,
                    "size_bytes": ref.size_bytes,
                }
                for ref in self.evidence_refs
            ],
            "parent_packet_ids": list(self.parent_packet_ids),
            "claims": list(self.claims),
            "assumptions": list(self.assumptions),
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "allowed_effects": list(self.allowed_effects),
            "forbidden_effects": list(self.forbidden_effects),
            **_AUTHORITY_FIELDS,
        }

    def canonical_json_bytes(self) -> bytes:
        return json.dumps(
            self.compact(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def payload_digest(self) -> str:
        return hashlib.sha256(self.canonical_json_bytes()).hexdigest()

    def validate(
        self,
        *,
        now: dt.datetime | None = None,
        evidence_root: str | Path | None = None,
        verify_evidence: bool = True,
    ) -> tuple[str, ...]:
        current = _aware_utc(
            now if now is not None else dt.datetime.now(tz=_UTC),
            field="now",
        )
        issues: list[str] = []

        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != WORK_PACKET_SCHEMA_VERSION
        ):
            issues.append("schema_version must equal 1")

        required_strings = (
            ("packet_id", self.packet_id),
            ("kind", self.kind),
            ("producer_role", self.producer_role),
            ("run_id", self.run_id),
            ("subject", self.subject),
            ("recommendation", self.recommendation),
        )
        for field, value in required_strings:
            if not isinstance(value, str) or not value.strip():
                issues.append(f"{field} must be a nonempty string")

        if isinstance(self.producer_role, str) and len(self.producer_role) > MAX_ROLE_SUBJECT_CHARS:
            issues.append("producer_role exceeds 160 characters")
        if isinstance(self.subject, str) and len(self.subject) > MAX_ROLE_SUBJECT_CHARS:
            issues.append("subject exceeds 160 characters")
        if (
            isinstance(self.recommendation, str)
            and len(self.recommendation) > MAX_RECOMMENDATION_CHARS
        ):
            issues.append("recommendation exceeds 1000 characters")

        try:
            expected_packet_id = build_packet_id(self.run_id, self.kind)
        except (TypeError, ValueError):
            issues.append("run_id or kind is invalid")
        else:
            if self.packet_id != expected_packet_id:
                issues.append("packet_id does not match run_id and kind")

        created = _parse_stored_utc(self.created_at)
        expiry = _parse_stored_utc(self.expires_at)
        if created is None:
            issues.append("created_at must be UTC ISO-8601 seconds")
        if expiry is None:
            issues.append("expires_at must be UTC ISO-8601 seconds")
        if created is not None and expiry is not None:
            if expiry <= created:
                issues.append("expires_at must be strictly after created_at")
            if expiry <= current:
                issues.append("packet expired")

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
        ):
            issues.append("confidence must be a finite number from 0.0 to 1.0")

        issues.extend(
            _validate_bounded_text_collection(
                self.claims,
                field="claims",
                maximum_count=MAX_CLAIMS,
            )
        )
        issues.extend(
            _validate_bounded_text_collection(
                self.assumptions,
                field="assumptions",
                maximum_count=MAX_ASSUMPTIONS,
            )
        )
        issues.extend(
            _validate_evidence_refs(
                self.evidence_refs,
                evidence_root=evidence_root,
                verify_evidence=verify_evidence,
            )
        )
        issues.extend(
            _validate_parent_packet_ids(
                self.parent_packet_ids,
                packet_id=self.packet_id,
            )
        )
        issues.extend(
            _validate_effects(
                self.allowed_effects,
                self.forbidden_effects,
            )
        )

        try:
            packet_size = len(self.canonical_json_bytes())
        except (TypeError, ValueError):
            issues.append("packet is not canonically serializable")
        else:
            if packet_size > MAX_PACKET_BYTES:
                issues.append("canonical packet exceeds 16 KiB")
        return tuple(issues)


def _validate_bounded_text_collection(
    values: Any,
    *,
    field: str,
    maximum_count: int,
) -> list[str]:
    issues: list[str] = []
    if not isinstance(values, tuple):
        return [f"{field} must be a tuple"]
    if len(values) > maximum_count:
        issues.append(f"{field} contains more than {maximum_count} items")
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{field}[{index}] must be a nonempty string")
        elif len(value) > MAX_CLAIM_CHARS:
            issues.append(f"{field}[{index}] exceeds 500 characters")
    return issues


def _validate_evidence_refs(
    values: Any,
    *,
    evidence_root: str | Path | None,
    verify_evidence: bool,
) -> list[str]:
    if not isinstance(values, tuple):
        return ["evidence_refs must be a tuple"]
    issues: list[str] = []
    triples: list[tuple[str, str, int]] = []
    for index, ref in enumerate(values):
        if not isinstance(ref, EvidenceRef):
            issues.append(f"evidence_refs[{index}] must be an EvidenceRef")
            continue
        shape_valid = True
        if not isinstance(ref.path, str) or not ref.path.strip():
            issues.append(f"evidence_refs[{index}].path must be nonempty")
            shape_valid = False
        if not isinstance(ref.sha256, str) or _LOWER_SHA256.fullmatch(ref.sha256) is None:
            issues.append(f"evidence_refs[{index}].sha256 must be lowercase SHA-256")
            shape_valid = False
        if (
            isinstance(ref.size_bytes, bool)
            or not isinstance(ref.size_bytes, int)
            or ref.size_bytes < 0
        ):
            issues.append(f"evidence_refs[{index}].size_bytes must be a nonnegative integer")
            shape_valid = False
        if shape_valid:
            triples.append((ref.path, ref.sha256, ref.size_bytes))
            if verify_evidence and not ref.verify(evidence_root):
                issues.append(f"evidence_refs[{index}] failed verification")
    if len(triples) != len(set(triples)):
        issues.append("evidence_refs contains duplicate references")
    return issues


def _validate_parent_packet_ids(values: Any, *, packet_id: Any) -> list[str]:
    if not isinstance(values, tuple):
        return ["parent_packet_ids must be a tuple"]
    issues: list[str] = []
    strings = [value for value in values if isinstance(value, str)]
    if len(strings) != len(values):
        issues.append("parent_packet_ids must contain only strings")
    if len(strings) != len(set(strings)):
        issues.append("parent_packet_ids must be unique")
    for index, value in enumerate(strings):
        if not _valid_packet_id(value):
            issues.append(f"parent_packet_ids[{index}] is not a safe packet ID")
        if value == packet_id:
            issues.append("parent_packet_ids cannot contain packet_id")
    return issues


def _validate_effects(allowed: Any, forbidden: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(allowed, tuple):
        issues.append("allowed_effects must be a tuple")
        allowed_values: tuple[Any, ...] = ()
    else:
        allowed_values = allowed
    if not isinstance(forbidden, tuple):
        issues.append("forbidden_effects must be a tuple")
        forbidden_values: tuple[Any, ...] = ()
    else:
        forbidden_values = forbidden

    allowed_strings = [value for value in allowed_values if isinstance(value, str)]
    forbidden_strings = [value for value in forbidden_values if isinstance(value, str)]
    if len(allowed_strings) != len(allowed_values):
        issues.append("allowed_effects must contain only strings")
    if len(forbidden_strings) != len(forbidden_values):
        issues.append("forbidden_effects must contain only strings")
    if len(allowed_strings) != len(set(allowed_strings)):
        issues.append("allowed_effects must be unique")
    if len(forbidden_strings) != len(set(forbidden_strings)):
        issues.append("forbidden_effects must be unique")
    if len(allowed_strings) == len(allowed_values) and allowed_values != tuple(
        sorted(allowed_strings)
    ):
        issues.append("allowed_effects must be sorted")
    if len(forbidden_strings) == len(forbidden_values) and forbidden_values != tuple(
        sorted(forbidden_strings)
    ):
        issues.append("forbidden_effects must be sorted")

    for index, value in enumerate(allowed_strings):
        if _SAFE_EFFECT.fullmatch(value) is None:
            issues.append(f"allowed_effects[{index}] is not a safe token")
        elif value not in ADVISORY_ALLOWED_EFFECTS:
            issues.append(f"allowed_effects[{index}] is not advisory")
    for index, value in enumerate(forbidden_strings):
        if _SAFE_EFFECT.fullmatch(value) is None:
            issues.append(f"forbidden_effects[{index}] is not a safe token")

    overlap = sorted(set(allowed_strings) & set(forbidden_strings))
    if overlap:
        issues.append(f"allowed and forbidden effects overlap: {', '.join(overlap)}")
    missing_required = sorted(REQUIRED_FORBIDDEN_EFFECTS - set(forbidden_strings))
    if missing_required:
        issues.append(
            "required forbidden effects missing: " + ", ".join(missing_required)
        )
    return issues


def validate_work_packet(
    packet: WorkPacket,
    *,
    now: dt.datetime | None = None,
    evidence_root: str | Path | None = None,
    verify_evidence: bool = True,
) -> list[str]:
    """Compatibility wrapper returning packet validation issues as a list."""

    if not isinstance(packet, WorkPacket):
        return ["packet must be a WorkPacket"]
    return list(
        packet.validate(
            now=now,
            evidence_root=evidence_root,
            verify_evidence=verify_evidence,
        )
    )
