"""Fail-closed, immutable, decision-only autonomous loss BOARD records."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from tradingagents.brokers.supervisor.loss_review import ALLOWED_LOSS_EXIT_REASONS
from tradingagents.orchestration.decision_ledger import DecisionLedger
from tradingagents.orchestration.work_packets import (
    REQUIRED_FORBIDDEN_EFFECTS,
    WORK_PACKET_SCHEMA_VERSION,
    EvidenceRef,
    WorkPacket,
    build_packet_id,
)

SCHEMA_VERSION = "tradingagents.autonomous_loss_board_decision.v1"
_UTC = dt.timezone.utc
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,15}$")
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
_MAX_AGE = dt.timedelta(minutes=15)
_QUALITIES = frozenset({"high", "medium"})
_ADVERSE_NEWS_EVENTS = frozenset({"guidance_cut", "material_contract_loss", "regulatory_adverse_action", "thesis_invalidator"})
_ADVERSE_FILING_EVENTS = frozenset({"guidance_cut", "earnings_miss", "material_impairment", "adverse_filing_disclosure"})
AUTONOMOUS_BOARD_ELIGIBLE_LOSS_EXIT_REASONS = frozenset(
    {
        "thesis_invalidated",
        "company_specific_negative_news",
        "earnings_or_guidance_break",
    }
)
if not AUTONOMOUS_BOARD_ELIGIBLE_LOSS_EXIT_REASONS <= ALLOWED_LOSS_EXIT_REASONS:
    raise RuntimeError("autonomous BOARD loss-exit subset drifted from supervisor taxonomy")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _canon(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _now(value: dt.datetime | None) -> dt.datetime:
    result = value if value is not None else dt.datetime.now(tz=_UTC)
    if not isinstance(result, dt.datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return result.astimezone(_UTC).replace(microsecond=0)


def _time(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be UTC ISO-8601 seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be UTC ISO-8601 seconds") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    parsed = parsed.astimezone(_UTC)
    if parsed.microsecond or parsed.isoformat(timespec="seconds") != value:
        raise ValueError(f"{field} must be canonical UTC seconds")
    return parsed


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


def _decimal(value: Any, field: str) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{field} must be a canonical decimal string")
    try:
        decimal_value = Decimal(value)
        if not decimal_value.is_finite() or (decimal_value == 0 and value.startswith("-")):
            raise ValueError(f"{field} must be finite")
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a canonical decimal string") from exc
    return value


def _is_decimal(value: Any, field: str) -> bool:
    try:
        _decimal(value, field)
    except ValueError:
        return False
    return True


def _sequence_of_text(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _root(value: str | Path) -> Path:
    path = Path(value)
    try:
        state = path.lstat()
    except OSError as exc:
        raise ValueError("evidence_root must exist") from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise ValueError("evidence_root must be a real directory")
    return path.resolve()


def _trusted_ledger_root(value: str | Path, evidence_root: Path) -> Path:
    """Resolve the caller-configured ledger boundary for an authorizing read.

    The ledger root is configuration owned by the caller, never a path read
    from a decision packet.  It must already be a real directory and remain a
    separate trust boundary from mutable evidence; a nested copied ledger is
    not an authentication source for BOARD decisions.
    """

    path = Path(value).expanduser()
    try:
        state = path.lstat()
    except OSError as exc:
        raise ValueError("trusted ledger root must be a preexisting real directory") from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise ValueError("trusted ledger root must be a preexisting real directory")
    resolved = path.resolve()
    try:
        resolved.relative_to(evidence_root)
    except ValueError:
        pass
    else:
        raise ValueError("trusted ledger root must be outside evidence_root")
    try:
        evidence_root.relative_to(resolved)
    except ValueError:
        pass
    else:
        raise ValueError("trusted ledger root must not contain evidence_root")
    return resolved


def _inside(root: Path, relative: str | Path, *, label: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"{label} escapes evidence_root")
    candidate = root / relative_path
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes evidence_root") from exc
    current = root
    for part in Path(relative).parts[:-1]:
        current /= part
        if current.exists() and stat.S_ISLNK(current.lstat().st_mode):
            raise ValueError(f"{label} parent must not be a symlink")
    return candidate


def _read_contained(root: Path, path: str | Path, *, label: str) -> tuple[Path, bytes, Mapping[str, Any]]:
    supplied = Path(path)
    if supplied.is_absolute():
        supplied = supplied.resolve()
        try:
            relative = supplied.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{label} must be contained by evidence_root") from exc
    else:
        relative = supplied
    target = _inside(root, relative, label=label)
    # Do not validate a parent and then reopen it by name: a malicious or
    # merely racing writer could replace that parent with a symlink in between.
    # Walk from the already-trusted root descriptor instead.
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        current_fd = root_fd
        for part in relative.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW,
                dir_fd=current_fd,
            )
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        descriptor = os.open(relative.parts[-1], os.O_RDONLY | _NOFOLLOW, dir_fd=current_fd)
        try:
            state = os.fstat(descriptor)
            if not stat.S_ISREG(state.st_mode):
                raise ValueError(f"{label} must be a regular non-symlink file")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                payload = handle.read()
        finally:
            if descriptor != -1:
                os.close(descriptor)
            if current_fd != root_fd:
                os.close(current_fd)
    except OSError as exc:
        raise ValueError(f"{label} is unreadable") from exc
    finally:
        os.close(root_fd)
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain a JSON object") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    return target, payload, decoded


@dataclass(frozen=True)
class BoundEvidence:
    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or Path(self.path).is_absolute() or _SHA256.fullmatch(self.sha256) is None or type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("invalid bound evidence")

    def compact(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size_bytes": self.size_bytes}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BoundEvidence:
        if set(value) != {"path", "sha256", "size_bytes"}:
            raise ValueError("invalid bound evidence fields")
        return cls(**dict(value))

    def verify(self, root: Path) -> bool:
        try:
            target, payload, _ = _read_contained(root, self.path, label="bound evidence")
        except ValueError:
            return False
        return target == _inside(root, self.path, label="bound evidence") and len(payload) == self.size_bytes and hashlib.sha256(payload).hexdigest() == self.sha256


@dataclass(frozen=True)
class BoundSourceEvidence:
    packet: BoundEvidence
    packet_id: str
    source_name: str
    evidence_type: str
    as_of: str
    quality: str

    def __post_init__(self) -> None:
        if not isinstance(self.packet, BoundEvidence):
            raise ValueError("source packet binding is required")
        for name in ("packet_id", "source_name", "evidence_type"):
            _text(getattr(self, name), name)
        _time(self.as_of, "source as_of")
        if self.quality not in _QUALITIES:
            raise ValueError("source quality is not accepted")

    def compact(self) -> dict[str, Any]:
        return {"packet": self.packet.compact(), "packet_id": self.packet_id, "source_name": self.source_name, "evidence_type": self.evidence_type, "as_of": self.as_of, "quality": self.quality}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BoundSourceEvidence:
        expected = {"packet", "packet_id", "source_name", "evidence_type", "as_of", "quality"}
        if set(value) != expected or not isinstance(value["packet"], Mapping):
            raise ValueError("invalid source binding fields")
        return cls(packet=BoundEvidence.from_dict(value["packet"]), packet_id=value["packet_id"], source_name=value["source_name"], evidence_type=value["evidence_type"], as_of=value["as_of"], quality=value["quality"])


@dataclass(frozen=True)
class CapturedSourceEvidence:
    """One source read, whose bytes and decoded object stay bound together."""

    source: BoundSourceEvidence
    packet_bytes: bytes
    packet_object: Mapping[str, Any]


@dataclass(frozen=True)
class AutonomousLossBoardDecision:
    schema_version: str
    decision_id: str
    decision: Literal["HOLD", "SELL"]
    symbol: str
    supervisor_decision_id: str
    supervisor_packet: BoundEvidence
    loss_evidence_packet: BoundEvidence
    accepted_sources: tuple[BoundSourceEvidence, ...]
    source_revision: str
    generated_at: str
    expires_at: str
    thesis_verdict: str
    reason_code: str
    confidence: str
    evidence_complete: bool
    evidence_gaps: tuple[str, ...]
    trade_decision_resolved: bool
    exit_allowed: bool
    producer_role: str = field(init=False, default="portfolio_executive")
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.decision not in {"HOLD", "SELL"} or not isinstance(self.symbol, str) or _SYMBOL.fullmatch(self.symbol) is None or _REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("invalid decision identity")
        _text(self.supervisor_decision_id, "supervisor_decision_id")
        if not isinstance(self.supervisor_packet, BoundEvidence) or not isinstance(self.loss_evidence_packet, BoundEvidence) or not isinstance(self.accepted_sources, tuple) or not all(isinstance(item, BoundSourceEvidence) for item in self.accepted_sources):
            raise ValueError("invalid decision bindings")
        if len(self.accepted_sources) != len({json.dumps(item.compact(), sort_keys=True) for item in self.accepted_sources}):
            raise ValueError("source bindings must be unique")
        generated, expires = _time(self.generated_at, "generated_at"), _time(self.expires_at, "expires_at")
        if not generated < expires <= generated + _MAX_AGE:
            raise ValueError("invalid decision lifetime")
        _text(self.thesis_verdict, "thesis_verdict")
        _text(self.reason_code, "reason_code")
        confidence = Decimal(_decimal(self.confidence, "confidence"))
        if (
            type(self.evidence_complete) is not bool
            or type(self.trade_decision_resolved) is not bool
            or self.trade_decision_resolved is not True
            or type(self.exit_allowed) is not bool
            or not isinstance(self.evidence_gaps, tuple)
            or not all(_text(x, "evidence_gap") for x in self.evidence_gaps)
            or len(self.evidence_gaps) != len(set(self.evidence_gaps))
        ):
            raise ValueError("invalid decision booleans or gaps")
        sell = self.decision == "SELL"
        if sell is not self.evidence_complete or sell is not self.exit_allowed or (sell and (self.evidence_gaps or confidence < Decimal("0.75"))) or (not sell and not self.evidence_gaps):
            raise ValueError("decision must fail closed")
        if self.decision_id != hashlib.sha256(_canon(self._identity())).hexdigest():
            raise ValueError("decision_id does not match canonical material")

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision,
            "symbol": self.symbol,
            "supervisor_decision_id": self.supervisor_decision_id,
            "supervisor_packet": self.supervisor_packet.compact(),
            "loss_evidence_packet": self.loss_evidence_packet.compact(),
            "accepted_sources": [x.compact() for x in self.accepted_sources],
            "source_revision": self.source_revision,
            "generated_at": self.generated_at,
            "expires_at": self.expires_at,
            "thesis_verdict": self.thesis_verdict,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
            "evidence_complete": self.evidence_complete,
            "evidence_gaps": list(self.evidence_gaps),
            "trade_decision_resolved": self.trade_decision_resolved,
            "exit_allowed": self.exit_allowed,
            "producer_role": self.producer_role,
            "analysis_only": self.analysis_only,
            "execution_authority": self.execution_authority,
            "can_submit_orders": self.can_submit_orders,
        }

    def compact(self) -> dict[str, Any]:
        return {"decision_id": self.decision_id, **self._identity()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AutonomousLossBoardDecision:
        expected = set(cls.__dataclass_fields__) | {"producer_role", "analysis_only", "execution_authority", "can_submit_orders"}
        if (
            set(value) != expected
            or value.get("producer_role") != "portfolio_executive"
            or value.get("analysis_only") is not True
            or value.get("execution_authority") != "none"
            or value.get("can_submit_orders") is not False
            or not isinstance(value.get("accepted_sources"), list)
            or not isinstance(value.get("evidence_gaps"), list)
            or not isinstance(value.get("supervisor_packet"), Mapping)
            or not isinstance(value.get("loss_evidence_packet"), Mapping)
        ):
            raise ValueError("invalid exact decision schema")
        sources = value["accepted_sources"]
        if not all(isinstance(x, Mapping) for x in sources):
            raise ValueError("invalid source entry")
        return cls(
            schema_version=value["schema_version"],
            decision_id=value["decision_id"],
            decision=value["decision"],
            symbol=value["symbol"],
            supervisor_decision_id=value["supervisor_decision_id"],
            supervisor_packet=BoundEvidence.from_dict(value["supervisor_packet"]),
            loss_evidence_packet=BoundEvidence.from_dict(value["loss_evidence_packet"]),
            accepted_sources=tuple(BoundSourceEvidence.from_dict(x) for x in sources),
            source_revision=value["source_revision"],
            generated_at=value["generated_at"],
            expires_at=value["expires_at"],
            thesis_verdict=value["thesis_verdict"],
            reason_code=value["reason_code"],
            confidence=value["confidence"],
            evidence_complete=value["evidence_complete"],
            evidence_gaps=tuple(value["evidence_gaps"]),
            trade_decision_resolved=value["trade_decision_resolved"],
            exit_allowed=value["exit_allowed"],
        )


@dataclass(frozen=True)
class RecordedLossBoardDecision:
    decision: AutonomousLossBoardDecision
    packet: WorkPacket
    packet_path: Path
    decision_evidence_path: Path


def _bound(root: Path, path: str | Path, label: str) -> tuple[BoundEvidence, Mapping[str, Any]]:
    target, raw, decoded = _read_contained(root, path, label=label)
    return BoundEvidence(path=target.relative_to(root).as_posix(), sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw)), decoded


def _capture_source(root: Path, source: BoundSourceEvidence, symbol: str) -> CapturedSourceEvidence | None:
    try:
        target, packet_bytes, packet = _read_contained(root, source.packet.path, label="accepted source packet")
    except ValueError:
        return None
    captured = BoundEvidence(
        path=target.relative_to(root).as_posix(),
        sha256=hashlib.sha256(packet_bytes).hexdigest(),
        size_bytes=len(packet_bytes),
    )
    if captured != source.packet or packet.get("symbol") != symbol or packet.get("subject") != symbol or any(packet.get(key) != getattr(source, key) for key in ("packet_id", "source_name", "evidence_type", "as_of", "quality")):
        return None
    return CapturedSourceEvidence(source=source, packet_bytes=packet_bytes, packet_object=packet)


def _sources(root: Path, raw: Any, symbol: str) -> tuple[CapturedSourceEvidence, ...]:
    if not isinstance(raw, list) or not raw:
        return ()
    result: list[CapturedSourceEvidence] = []
    seen_descriptors: set[str] = set()
    exact = {"path", "sha256", "size_bytes", "packet_id", "source_name", "evidence_type", "as_of", "quality"}
    for descriptor in raw:
        if not isinstance(descriptor, Mapping) or set(descriptor) != exact or not isinstance(descriptor.get("path"), str):
            return ()
        descriptor_identity = json.dumps(dict(descriptor), sort_keys=True, separators=(",", ":"))
        if descriptor_identity in seen_descriptors:
            raise ValueError("source bindings must be unique")
        seen_descriptors.add(descriptor_identity)
        try:
            source = BoundSourceEvidence(
                packet=BoundEvidence.from_dict({key: descriptor[key] for key in ("path", "sha256", "size_bytes")}),
                packet_id=descriptor["packet_id"],
                source_name=descriptor["source_name"],
                evidence_type=descriptor["evidence_type"],
                as_of=descriptor["as_of"],
                quality=descriptor["quality"],
            )
        except (ValueError, TypeError):
            raise ValueError("accepted source packet binding is invalid") from None
        captured = _capture_source(root, source, symbol)
        if captured is None:
            raise ValueError("accepted source packet is unavailable or mismatched")
        result.append(captured)
    return tuple(result)


def _source_payload(raw: Mapping[str, Any], source: BoundSourceEvidence) -> Mapping[str, Any] | None:
    payload = raw.get("payload")
    if not isinstance(payload, Mapping):
        return None
    if payload.get("symbol") != raw.get("symbol") or payload.get("as_of") != source.as_of:
        return None
    return payload


def _market_source_proves_values(payload: Mapping[str, Any], review: Mapping[str, Any], source: BoundSourceEvidence) -> bool:
    if set(payload) != {"symbol", "as_of", "spy", "qqq", "sector_relative"}:
        return False
    context = review.get("broad_market_context")
    sector = review.get("sector_or_peer_context")
    spy = payload.get("spy")
    qqq = payload.get("qqq")
    sector_relative = payload.get("sector_relative")
    if not isinstance(context, Mapping) or not isinstance(sector, Mapping):
        return False
    if not all(isinstance(value, Mapping) and set(value) == {"symbol", "value", "as_of"} for value in (spy, qqq, sector_relative)):
        return False
    return (
        spy.get("symbol") == "SPY"
        and spy.get("value") == context.get("SPY")
        and spy.get("as_of") == source.as_of
        and _is_decimal(spy.get("value"), "source SPY")
        and qqq.get("symbol") == "QQQ"
        and qqq.get("value") == context.get("QQQ")
        and qqq.get("as_of") == source.as_of
        and _is_decimal(qqq.get("value"), "source QQQ")
        and sector_relative.get("symbol") == review.get("symbol")
        and sector_relative.get("value") == sector.get("relative_performance")
        and sector_relative.get("as_of") == source.as_of
        and _is_decimal(sector_relative.get("value"), "source sector relative")
        and Decimal(sector_relative["value"]) <= Decimal("-0.01")
        and Decimal(review["relative_performance_vs_SPY"]) <= Decimal("-0.01")
        and Decimal(review["relative_performance_vs_QQQ"]) <= Decimal("-0.01")
    )


def _news_source_proves_adverse_break(payload: Mapping[str, Any]) -> bool:
    return (
        set(payload) == {"symbol", "as_of", "event_category", "direction", "impact_fraction"}
        and payload.get("event_category") in _ADVERSE_NEWS_EVENTS
        and payload.get("direction") == "adverse"
        and payload.get("impact_fraction") is not None
        and _is_decimal(payload.get("impact_fraction"), "news impact_fraction")
        and Decimal(payload["impact_fraction"]) <= Decimal("-0.01")
    )


def _filing_source_proves_adverse_fact(payload: Mapping[str, Any]) -> bool:
    return (
        set(payload) == {"symbol", "as_of", "event_category", "direction", "change_fraction"}
        and payload.get("event_category") in _ADVERSE_FILING_EVENTS
        and payload.get("direction") == "adverse"
        and payload.get("change_fraction") is not None
        and _is_decimal(payload.get("change_fraction"), "filing change_fraction")
        and Decimal(payload["change_fraction"]) <= Decimal("-0.01")
    )


def _review_structured_events_match_sources(review: Mapping[str, Any], source_payloads: Mapping[str, Mapping[str, Any]]) -> bool:
    news = source_payloads.get("company_news")
    filing = source_payloads.get("earnings_guidance_filing")
    return (
        isinstance(news, Mapping)
        and isinstance(filing, Mapping)
        and review.get("company_news_event_category") == news.get("event_category")
        and review.get("company_news_direction") == news.get("direction")
        and review.get("company_news_impact_fraction") == news.get("impact_fraction")
        and review.get("filing_event_category") == filing.get("event_category")
        and review.get("filing_direction") == filing.get("direction")
        and review.get("filing_change_fraction") == filing.get("change_fraction")
    )


def _exact_source_reference(value: Any, sources: tuple[BoundSourceEvidence, ...]) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"packet_id", "path", "sha256"}:
        return False
    matches = [source for source in sources if value == {"packet_id": source.packet_id, "path": source.packet.path, "sha256": source.packet.sha256}]
    return len(matches) == 1


def _reason_source_semantics(
    reason: Any,
    reference: Any,
    sources: tuple[BoundSourceEvidence, ...],
    source_payloads: Mapping[str, Mapping[str, Any]],
) -> bool:
    """A reason is valid only when its cited exact packet proves that reason."""
    if not _exact_source_reference(reference, sources):
        return False
    referenced = next(
        source for source in sources
        if reference == {"packet_id": source.packet_id, "path": source.packet.path, "sha256": source.packet.sha256}
    )
    payload = source_payloads.get(referenced.evidence_type)
    if payload is None:
        return False
    if reason == "company_specific_negative_news":
        return referenced.evidence_type == "company_news" and _news_source_proves_adverse_break(payload)
    if reason == "earnings_or_guidance_break":
        return referenced.evidence_type == "earnings_guidance_filing" and _filing_source_proves_adverse_fact(payload)
    if reason == "thesis_invalidated":
        return (
            (referenced.evidence_type == "company_news" and payload.get("event_category") == "thesis_invalidator" and _news_source_proves_adverse_break(payload))
            or (referenced.evidence_type == "earnings_guidance_filing" and _filing_source_proves_adverse_fact(payload))
        )
    return False


def _semantic_gaps(review: Mapping[str, Any], payload: Mapping[str, Any], captures: tuple[CapturedSourceEvidence, ...], now: dt.datetime) -> tuple[str, ...]:
    gaps: list[str] = []
    sources = tuple(capture.source for capture in captures)
    session_blockers = {"market session is not tradeable for a live loss exit"}
    for blocker_field in ("blockers", "blocked_reasons"):
        value = review.get(blocker_field)
        if not _sequence_of_text(value) or any(item not in session_blockers for item in value):
            gaps.append(f"supervisor_{blocker_field}_not_exact_empty_list")
    remaining = payload.get("remaining_blockers")
    if not _sequence_of_text(remaining) or any(item not in session_blockers for item in remaining):
        gaps.append("remaining_blockers_not_exact_empty_list")
    context = review.get("broad_market_context")
    sector = review.get("sector_or_peer_context")
    if (
        not isinstance(context, Mapping)
        or not all(_is_decimal(context.get(x), x) for x in ("SPY", "QQQ"))
        or not all(_is_decimal(review.get(x), x) for x in ("relative_performance_vs_SPY", "relative_performance_vs_QQQ"))
        or not isinstance(sector, Mapping)
        or not isinstance(sector.get("sector"), str)
        or sector.get("sector") not in {"software", "semiconductors", "technology"}
        or not _is_decimal(sector.get("relative_performance"), "sector relative_performance")
    ):
        gaps.append("actual_spy_qqq_sector_relative_values_missing")
    if not all(isinstance(review.get(field), str) and review[field].strip() for field in ("current_thesis_status", "why_hold_is_worse_than_sell")):
        gaps.append("thesis_verdict_missing")
    try:
        if Decimal(_decimal(review.get("confidence"), "supervisor confidence")) < Decimal("0.75"):
            gaps.append("confidence_below_0_75")
        observed = _time(review.get("evidence_generated_at"), "supervisor evidence_generated_at")
        if observed > now or now - observed > _MAX_AGE:
            gaps.append("supervisor_evidence_stale")
    except ValueError:
        gaps.append("supervisor_confidence_or_timestamp_invalid")
    advisory = payload.get("advisory_analysis")
    candidate = advisory.get("loss_exit_candidate") if isinstance(advisory, Mapping) else None
    if (
        not isinstance(candidate, Mapping)
        or candidate.get("approval_effect") != "board_review_input_not_loss_exit_approval"
        or candidate.get("allowed_exit_reason_candidate") != review.get("allowed_exit_reason")
        or candidate.get("allowed_exit_reason_source") != review.get("allowed_exit_reason_source")
        or candidate.get("confidence") != review.get("confidence")
        or candidate.get("reason_summary") != review.get("why_hold_is_worse_than_sell")
        or advisory.get("current_thesis_status_candidate") != review.get("current_thesis_status")
    ):
        gaps.append("advisory_candidate_contradiction")
    categories: set[str] = set()
    source_payloads: dict[str, Mapping[str, Any]] = {}
    for capture in captures:
        source = capture.source
        try:
            observed = _time(source.as_of, "source as_of")
        except ValueError:
            gaps.append("source_binding_invalid")
            continue
        if observed > now or now - observed > _MAX_AGE:
            gaps.append("source_stale")
        descriptor = f"{source.source_name} {source.evidence_type}".lower()
        if any(x in descriptor for x in ("gap", "connector", "submissions_index", "submissions index")):
            gaps.append("source_gap_or_index")
        source_payload = _source_payload(capture.packet_object, source)
        if source_payload is None:
            gaps.append("source_payload_binding_invalid")
        elif source.evidence_type == "market_context":
            if _market_source_proves_values(source_payload, review, source):
                categories.add("market")
            else:
                gaps.append("market_source_values_missing_or_unbound")
        elif source.evidence_type == "company_news":
            if _news_source_proves_adverse_break(source_payload):
                categories.add("news")
                source_payloads["company_news"] = source_payload
            else:
                gaps.append("company_news_not_adverse_thesis_break")
        elif source.evidence_type == "earnings_guidance_filing":
            if _filing_source_proves_adverse_fact(source_payload):
                categories.add("substance")
                source_payloads["earnings_guidance_filing"] = source_payload
            else:
                gaps.append("filing_or_guidance_not_adverse_substantive_fact")
    if (
        review.get("allowed") is not True
        or review.get("allowed_exit_reason") not in AUTONOMOUS_BOARD_ELIGIBLE_LOSS_EXIT_REASONS
        or not _reason_source_semantics(
            review.get("allowed_exit_reason"),
            review.get("allowed_exit_reason_source"),
            sources,
            source_payloads,
        )
    ):
        gaps.append("recognized_exit_reason_missing_or_mismatched_source")
    if categories != {"market", "news", "substance"}:
        gaps.append("required_source_substance_missing")
    if not _review_structured_events_match_sources(review, source_payloads):
        gaps.append("review_structured_event_binding_invalid")
    return tuple(dict.fromkeys(gaps))


def _build(supervisor: BoundEvidence, supervisor_raw: Mapping[str, Any], loss: BoundEvidence, loss_raw: Mapping[str, Any], revision: str, root: Path, now: dt.datetime) -> AutonomousLossBoardDecision:
    review = ((supervisor_raw.get("evidence") or {}).get("loss_exit_review")) if isinstance(supervisor_raw.get("evidence"), Mapping) else None
    payload = loss_raw.get("payload") if isinstance(loss_raw.get("payload"), Mapping) else None
    if (
        not isinstance(review, Mapping)
        or not isinstance(payload, Mapping)
        or not isinstance(review.get("symbol"), str)
        or _SYMBOL.fullmatch(review["symbol"]) is None
        or loss_raw.get("symbol") != review["symbol"]
        or payload.get("symbol") != review["symbol"]
        or payload.get("supervisor_packet_path") != supervisor.path
        or payload.get("supervisor_decision_id") != review.get("decision_id")
    ):
        raise ValueError("loss packet is not exactly bound to the supervisor decision")
    if _REVISION.fullmatch(revision) is None:
        raise ValueError("source_revision must be lowercase 40-hex")
    captures = _sources(root, payload.get("accepted_sources"), review["symbol"])
    sources = tuple(capture.source for capture in captures)
    gaps = list(_semantic_gaps(review, payload, captures, now))
    if loss_raw.get("analysis_only") is not True or loss_raw.get("execution_authority") != "none" or loss_raw.get("can_submit_orders") is not False or loss_raw.get("source_name") != "loss_review_evidence" or loss_raw.get("evidence_type") != "loss_review_evidence":
        gaps.append("raw_loss_packet_authority_or_identity_invalid")
    try:
        loss_generated = _time(loss_raw.get("generated_at"), "loss evidence generated_at")
        if loss_generated > now or now - loss_generated > _MAX_AGE:
            gaps.append("raw_loss_packet_stale")
    except ValueError:
        gaps.append("raw_loss_packet_timestamp_invalid")
    gaps = tuple(dict.fromkeys(gaps))
    confidence = review.get("confidence") if isinstance(review.get("confidence"), str) and _DECIMAL.fullmatch(review["confidence"]) else "0"
    sell = not gaps and Decimal(confidence) >= Decimal("0.75")
    generated, expires = now.isoformat(timespec="seconds"), (now + _MAX_AGE).isoformat(timespec="seconds")
    base = {
        "schema_version": SCHEMA_VERSION,
        "decision": "SELL" if sell else "HOLD",
        "symbol": review["symbol"],
        "supervisor_decision_id": review.get("decision_id"),
        "supervisor_packet": supervisor.compact(),
        "loss_evidence_packet": loss.compact(),
        "accepted_sources": [x.compact() for x in sources],
        "source_revision": revision,
        "generated_at": generated,
        "expires_at": expires,
        "thesis_verdict": review.get("current_thesis_status") if isinstance(review.get("current_thesis_status"), str) and review["current_thesis_status"].strip() else "Evidence is incomplete; HOLD remains safer.",
        "reason_code": "loss_exit_evidence_complete" if sell else "evidence_incomplete",
        "confidence": confidence,
        "evidence_complete": sell,
        "evidence_gaps": [] if sell else list(gaps or ("evidence_incomplete",)),
        "trade_decision_resolved": True,
        "exit_allowed": sell,
        "producer_role": "portfolio_executive",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    return AutonomousLossBoardDecision.from_dict({"decision_id": hashlib.sha256(_canon(base)).hexdigest(), **base})


def _publish(root: Path, relative: Path, content: bytes) -> Path:
    target = _inside(root, relative, label="decision evidence")
    parent = target.parent
    if parent.exists():
        if stat.S_ISLNK(parent.lstat().st_mode) or not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError("decision evidence parent is unsafe")
    else:
        parent.mkdir(mode=0o700)
        root_descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
    if stat.S_ISLNK(parent.lstat().st_mode):
        raise ValueError("decision evidence parent is unsafe")
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    except FileExistsError:
        state = target.lstat()
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode) or target.read_bytes() != content:
            raise ValueError("immutable decision evidence collision") from None
        return target
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        with suppress(OSError):
            target.unlink()
        raise
    return target


def _after_decision_fsync(_path: Path) -> None:
    """Test seam: ledger publication starts only after this durable boundary."""


def record_autonomous_loss_board_decision(*, supervisor_packet_path: str | Path, loss_evidence_packet_path: str | Path, source_revision: str, ledger_root: str | Path, evidence_root: str | Path, now: dt.datetime | None = None) -> RecordedLossBoardDecision:
    current, root = _now(now), _root(evidence_root)
    supervisor, supervisor_raw = _bound(root, supervisor_packet_path, "supervisor packet")
    loss, loss_raw = _bound(root, loss_evidence_packet_path, "loss evidence packet")
    decision = _build(supervisor, supervisor_raw, loss, loss_raw, source_revision, root, current)
    relative = Path("autonomous_loss_board_decisions") / f"{decision.decision_id}.json"
    content = _canon({"decision": decision.compact()})
    decision_path = _publish(root, relative, content)
    _after_decision_fsync(decision_path)
    refs = (EvidenceRef(path=str(decision_path), sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)), EvidenceRef(path=str(root / supervisor.path), sha256=supervisor.sha256, size_bytes=supervisor.size_bytes), EvidenceRef(path=str(root / loss.path), sha256=loss.sha256, size_bytes=loss.size_bytes))
    packet = WorkPacket.create(
        kind="portfolio_decision",
        producer_role="portfolio_executive",
        run_id=decision.decision_id,
        subject=decision.symbol,
        evidence_refs=refs,
        claims=(f"Autonomous loss BOARD resolved {decision.symbol} as {decision.decision}.",),
        assumptions=(),
        recommendation="autonomous_sell_authorized_pending_execution_intent" if decision.decision == "SELL" else "autonomous_hold",
        confidence=float(Decimal(decision.confidence)),
        expires_at=_time(decision.expires_at, "expires_at"),
        allowed_effects=("record_trade_decision",),
        now=current,
    )
    ledger = DecisionLedger(ledger_root)
    packet_path = ledger.record(packet, evidence_root=root, now=current)
    ledger.verify(evidence_root=root)
    return RecordedLossBoardDecision(decision, packet, packet_path, decision_path)


def _capture_evidence_ref(root: Path, reference: EvidenceRef, *, label: str) -> tuple[Path, bytes, Mapping[str, Any]]:
    target, captured, decoded = _read_contained(root, reference.path, label=label)
    if reference.path != str(target) or reference.size_bytes != len(captured) or reference.sha256 != hashlib.sha256(captured).hexdigest():
        raise ValueError(f"{label} does not match its ledger evidence reference")
    return target, captured, decoded


def _expected_ledger_packet(
    decision: AutonomousLossBoardDecision,
    *,
    decision_path: Path,
    decision_bytes: bytes,
    root: Path,
    now: dt.datetime,
) -> WorkPacket:
    refs = (
        EvidenceRef(path=str(decision_path), sha256=hashlib.sha256(decision_bytes).hexdigest(), size_bytes=len(decision_bytes)),
        EvidenceRef(path=str(root / decision.supervisor_packet.path), sha256=decision.supervisor_packet.sha256, size_bytes=decision.supervisor_packet.size_bytes),
        EvidenceRef(path=str(root / decision.loss_evidence_packet.path), sha256=decision.loss_evidence_packet.sha256, size_bytes=decision.loss_evidence_packet.size_bytes),
    )
    # ``WorkPacket.create`` validates references by reopening their paths.  The
    # BOARD verifier already captured all three authoritative references above,
    # so reconstruct the known schema directly and compare canonical bytes
    # without creating a second read path.
    return WorkPacket(
        schema_version=WORK_PACKET_SCHEMA_VERSION,
        packet_id=build_packet_id(decision.decision_id, "portfolio_decision"),
        kind="portfolio_decision",
        created_at=now.isoformat(timespec="seconds"),
        expires_at=decision.expires_at,
        producer_role="portfolio_executive",
        run_id=decision.decision_id,
        subject=decision.symbol,
        evidence_refs=refs,
        parent_packet_ids=(),
        claims=(f"Autonomous loss BOARD resolved {decision.symbol} as {decision.decision}.",),
        assumptions=(),
        recommendation="autonomous_sell_authorized_pending_execution_intent" if decision.decision == "SELL" else "autonomous_hold",
        confidence=float(Decimal(decision.confidence)),
        allowed_effects=("record_trade_decision",),
        forbidden_effects=tuple(sorted(REQUIRED_FORBIDDEN_EFFECTS)),
    )


def verify_autonomous_loss_board_decision(*, ledger_root: str | Path, ledger_packet_id: str, evidence_root: str | Path, now: dt.datetime | None = None) -> AutonomousLossBoardDecision:
    """Authenticate a BOARD decision through its immutable ledger packet only.

    ``ledger_root`` is a caller-configured, preexisting trust boundary.  It is
    deliberately not obtained from the decision, supervisor, loss, or source
    packet.  Callers must supply the installed ledger root, not a copied or
    nested evidence directory.
    """

    current, root = _now(now), _root(evidence_root)
    trusted_ledger = _trusted_ledger_root(ledger_root, root)
    packet = DecisionLedger(trusted_ledger).read_authenticated_packet(ledger_packet_id, evidence_root=root)
    if len(packet.evidence_refs) != 3:
        raise ValueError("ledger packet must have exactly three BOARD evidence references")
    decision_path, content, raw = _capture_evidence_ref(root, packet.evidence_refs[0], label="decision evidence")
    if set(raw) != {"decision"} or not isinstance(raw["decision"], Mapping) or content != _canon(raw):
        raise ValueError("decision evidence is not exact canonical bytes")
    decision = AutonomousLossBoardDecision.from_dict(raw["decision"])
    generated, expires = _time(decision.generated_at, "generated_at"), _time(decision.expires_at, "expires_at")
    if not generated <= current < expires:
        raise ValueError("decision is not currently valid")
    expected_path = root / "autonomous_loss_board_decisions" / f"{decision.decision_id}.json"
    if decision_path != expected_path:
        raise ValueError("ledger packet does not reference the decision identity path")
    supervisor_path, supervisor_bytes, supervisor_raw = _capture_evidence_ref(root, packet.evidence_refs[1], label="supervisor packet")
    loss_path, loss_bytes, loss_raw = _capture_evidence_ref(root, packet.evidence_refs[2], label="loss evidence packet")
    supervisor = BoundEvidence(path=supervisor_path.relative_to(root).as_posix(), sha256=hashlib.sha256(supervisor_bytes).hexdigest(), size_bytes=len(supervisor_bytes))
    loss = BoundEvidence(path=loss_path.relative_to(root).as_posix(), sha256=hashlib.sha256(loss_bytes).hexdigest(), size_bytes=len(loss_bytes))
    expected_decision = _build(
        supervisor,
        supervisor_raw,
        loss,
        loss_raw,
        decision.source_revision,
        root,
        generated,
    )
    if expected_decision.compact() != decision.compact():
        raise ValueError("decision does not exactly match authenticated evidence")
    expected_packet = _expected_ledger_packet(
        decision,
        decision_path=decision_path,
        decision_bytes=content,
        root=root,
        now=generated,
    )
    if packet.packet_id != ledger_packet_id or packet.canonical_json_bytes() != expected_packet.canonical_json_bytes():
        raise ValueError("ledger packet is not exact autonomous BOARD provenance")
    return decision
