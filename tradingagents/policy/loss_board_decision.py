"""Fail-closed, immutable, decision-only autonomous loss BOARD records."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
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
# A four-symbol context is read sequentially.  Its individual provider times
# therefore need not be identical, but they must describe one bounded market
# observation rather than a stitched-together history.
_MARKET_COMPONENT_MAX_SKEW = dt.timedelta(seconds=120)
_QUALITIES = frozenset({"high", "medium", "low"})
_ADVERSE_NEWS_EVENTS = frozenset({"guidance_cut", "material_contract_loss", "regulatory_adverse_action", "thesis_invalidator"})
_ADVERSE_FILING_EVENTS = frozenset({"guidance_cut", "earnings_miss", "material_impairment", "adverse_filing_disclosure"})
AUTONOMOUS_BOARD_ELIGIBLE_LOSS_EXIT_REASONS = frozenset(
    {
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


def _raw_vendor_time(value: Any, field: str) -> dt.datetime:
    """Parse an RFC3339 vendor observation, then canonicalize to UTC seconds.

    This is deliberately narrower in use than ``_time``: authority envelopes
    remain strict canonical strings.  Only an authenticated raw vendor field
    (currently Alpaca's clock timestamp) may carry fractional seconds or ``Z``.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be RFC3339")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(_UTC).replace(microsecond=0)


def _canonical_raw_provider_time(value: Any, field: str) -> dt.datetime:
    """Parse an authenticated provider timestamp using the research contract."""
    # Kept as a local import so policy does not make provider orchestration a
    # module-load dependency.  It only translates already-bound raw evidence.
    from tradingagents.research.provider_orchestrator import canonical_provider_timestamp

    canonical = canonical_provider_timestamp(value)
    if canonical is None:
        raise ValueError(f"{field} must be a supported provider timestamp")
    return _time(canonical, field)


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


def _is_time(value: Any, field: str) -> bool:
    try:
        _time(value, field)
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
    execution_eligible: bool
    execution_blockers: tuple[str, ...]
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
            or type(self.execution_eligible) is not bool
            or not isinstance(self.execution_blockers, tuple)
            or not all(_text(x, "execution_blocker") for x in self.execution_blockers)
            or len(self.execution_blockers) != len(set(self.execution_blockers))
            or type(self.exit_allowed) is not bool
            or not isinstance(self.evidence_gaps, tuple)
            or not all(_text(x, "evidence_gap") for x in self.evidence_gaps)
            or len(self.evidence_gaps) != len(set(self.evidence_gaps))
        ):
            raise ValueError("invalid decision booleans or gaps")
        sell = self.decision == "SELL"
        if (
            sell is not self.evidence_complete
            or self.exit_allowed is not (sell and self.execution_eligible)
            or (self.execution_eligible and self.execution_blockers)
            or (not self.execution_eligible and not self.execution_blockers)
            or (sell and (self.evidence_gaps or confidence < Decimal("0.75")))
            or (not sell and not self.evidence_gaps)
        ):
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
            "execution_eligible": self.execution_eligible,
            "execution_blockers": list(self.execution_blockers),
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
            or not isinstance(value.get("execution_blockers"), list)
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
            execution_eligible=value["execution_eligible"],
            execution_blockers=tuple(value["execution_blockers"]),
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
    if source.quality not in {"high", "medium"}:
        return False
    if set(payload) != {
        "symbol", "as_of", "target", "spy", "qqq", "sector_relative",
        "target_relative_to_spy", "target_relative_to_qqq",
    }:
        return False
    context = review.get("broad_market_context")
    sector = review.get("sector_or_peer_context")
    target = payload.get("target")
    spy = payload.get("spy")
    qqq = payload.get("qqq")
    sector_relative = payload.get("sector_relative")
    if not isinstance(context, Mapping) or not isinstance(sector, Mapping):
        return False
    if not all(isinstance(value, Mapping) and set(value) == {"symbol", "value", "as_of"} for value in (target, spy, qqq, sector_relative)):
        return False
    return (
        target.get("symbol") == review.get("symbol")
        and _is_decimal(target.get("value"), "source target")
        and _is_time(target.get("as_of"), "target as_of")
        and spy.get("symbol") == "SPY"
        and spy.get("value") == context.get("SPY")
        and _is_time(spy.get("as_of"), "SPY as_of")
        and _is_decimal(spy.get("value"), "source SPY")
        and qqq.get("symbol") == "QQQ"
        and qqq.get("value") == context.get("QQQ")
        and _is_time(qqq.get("as_of"), "QQQ as_of")
        and _is_decimal(qqq.get("value"), "source QQQ")
        and sector_relative.get("symbol") == review.get("symbol")
        and sector_relative.get("value") == sector.get("relative_performance")
        and _is_time(sector_relative.get("as_of"), "sector as_of")
        and _is_decimal(sector_relative.get("value"), "source sector relative")
        and Decimal(sector_relative["value"]) <= Decimal("-0.01")
        and review.get("relative_performance_vs_SPY") == payload.get("target_relative_to_spy")
        and review.get("relative_performance_vs_QQQ") == payload.get("target_relative_to_qqq")
        and Decimal(review["relative_performance_vs_SPY"]) <= Decimal("-0.01")
        and Decimal(review["relative_performance_vs_QQQ"]) <= Decimal("-0.01")
    )


def _market_source_has_exact_component_provenance(
    capture: CapturedSourceEvidence, root: Path, symbol: str, now: dt.datetime
) -> bool:
    """Reopen each raw quote and verify values and weakest quality exactly.

    The normalized aggregate is merely a convenience view.  It cannot uplift a
    low-quality component or retain a price change after the raw packet has
    been tampered with.
    """
    provenance = capture.packet_object.get("provenance")
    components = provenance.get("components") if isinstance(provenance, Mapping) else None
    if not isinstance(components, list) or len(components) != 4:
        return False
    expected_symbols = {symbol, "SPY", "QQQ", "XLK"}
    seen: set[str] = set()
    quality_rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
    qualities: list[str] = []
    component_times: list[dt.datetime] = []
    payload = capture.packet_object.get("payload")
    if not isinstance(payload, Mapping):
        return False
    for component in components:
        if not isinstance(component, Mapping) or set(component) != {
            "packet_id", "path", "sha256", "symbol", "quality", "current",
            "previous", "current_sha256", "previous_sha256", "as_of", "evidence_type",
        }:
            return False
        raw_symbol = component.get("symbol")
        if not isinstance(raw_symbol, str) or raw_symbol in seen:
            return False
        seen.add(raw_symbol)
        try:
            _target, raw, stored = _read_contained(
                root, component.get("path"), label="market component packet"
            )
        except ValueError:
            return False
        if (
            hashlib.sha256(raw).hexdigest() != component.get("sha256")
            or not isinstance(stored, Mapping)
            or stored.get("packet_id") != component.get("packet_id")
            or stored.get("symbol") != raw_symbol
            or stored.get("evidence_type") != component.get("evidence_type")
            or stored.get("evidence_type") not in {"quote_price_context", "quote"}
            or stored.get("quality") != component.get("quality")
            # Raw provider packets may preserve RFC3339 fractional/Z forms,
            # Finnhub epoch values, or FMP date strings.  Their descriptor is
            # canonical UTC seconds, so compare parsed instants rather than
            # requiring textual equality.
            or _canonical_raw_provider_time(stored.get("as_of"), "component as_of")
            != _time(component.get("as_of"), "component as_of")
        ):
            return False
        if component.get("quality") not in quality_rank:
            return False
        try:
            component_time = _time(component.get("as_of"), "component as_of")
        except ValueError:
            return False
        if component_time > now or now - component_time > _MAX_AGE:
            return False
        component_times.append(component_time)
        from tradingagents.research.provider_orchestrator import configured_quote_components
        raw_payload = stored.get("payload")
        actual = configured_quote_components(
            source_name=str(stored.get("source_name") or ""),
            evidence_type=str(stored.get("evidence_type") or ""),
            raw_payload=raw_payload,
            expected_symbol=raw_symbol,
        )
        matched = next((item for item in actual if item.get("symbol") == raw_symbol), None)
        current = matched.get("current") if isinstance(matched, Mapping) else None
        previous = matched.get("previous") if isinstance(matched, Mapping) else None
        def canonical_scalar(value: Any) -> str:
            text = format(Decimal(str(value)), "f")
            return (text.rstrip("0").rstrip(".") if "." in text else text) or "0"

        try:
            normalized_current = canonical_scalar(current)
            normalized_previous = canonical_scalar(previous)
            if Decimal(normalized_previous) <= 0:
                return False
        except (InvalidOperation, ValueError, TypeError):
            return False
        def scalar_hash(value: str) -> str:
            return hashlib.sha256(
                json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        if (
            component.get("current") != normalized_current
            or component.get("previous") != normalized_previous
            or component.get("current_sha256") != scalar_hash(normalized_current)
            or component.get("previous_sha256") != scalar_hash(normalized_previous)
        ):
            return False
        qualities.append(str(component["quality"]))
    if seen != expected_symbols or len(qualities) != 4 or len(component_times) != 4:
        return False
    aggregate_time = max(component_times)
    try:
        aggregate_bound = _time(capture.source.as_of, "market source as_of")
        aggregate_payload = _time(payload.get("as_of"), "market payload as_of")
    except ValueError:
        return False
    if (
        aggregate_time - min(component_times) > _MARKET_COMPONENT_MAX_SKEW
        or aggregate_bound != aggregate_time
        or aggregate_payload != aggregate_time
    ):
        return False
    component_by_symbol = {str(item["symbol"]): item for item in components}
    expected_payload_times = {
        symbol: component_by_symbol[symbol]["as_of"],
        "SPY": component_by_symbol["SPY"]["as_of"],
        "QQQ": component_by_symbol["QQQ"]["as_of"],
        "sector_relative": max(
            _time(component_by_symbol[symbol]["as_of"], "target component as_of"),
            _time(component_by_symbol["XLK"]["as_of"], "sector component as_of"),
        ).isoformat(timespec="seconds"),
    }
    if (
        payload.get("target", {}).get("as_of") != expected_payload_times[symbol]
        or payload.get("spy", {}).get("as_of") != expected_payload_times["SPY"]
        or payload.get("qqq", {}).get("as_of") != expected_payload_times["QQQ"]
        or payload.get("sector_relative", {}).get("as_of") != expected_payload_times["sector_relative"]
    ):
        return False
    # Recompute every aggregate from the authenticated raw scalar values.  A
    # normalized packet cannot substitute an invented relative-return value.
    try:
        change = {
            name: (Decimal(str(item["current"])) - Decimal(str(item["previous"]))) / Decimal(str(item["previous"]))
            for name, item in component_by_symbol.items()
        }
        # The normalizer emits eight decimal places maximum; recompute with
        # the same deterministic precision before comparing, rather than
        # relying on binary floating-point or an unbounded repeating decimal.
        def canonical(value: Decimal) -> str:
            return (
                format(value.quantize(Decimal("0.00000001")), "f").rstrip("0").rstrip(".")
                or "0"
            )
        if (
            payload.get("target", {}).get("value") != canonical(change[symbol])
            or payload.get("spy", {}).get("value") != canonical(change["SPY"])
            or payload.get("qqq", {}).get("value") != canonical(change["QQQ"])
            or payload.get("sector_relative", {}).get("value") != canonical(change[symbol] - change["XLK"])
            or payload.get("target_relative_to_spy") != canonical(change[symbol] - change["SPY"])
            or payload.get("target_relative_to_qqq") != canonical(change[symbol] - change["QQQ"])
        ):
            return False
    except (InvalidOperation, TypeError, ValueError, KeyError):
        return False
    # Raw components, scalar hashes, and their minimum quality are authenticated
    # above.  `_market_source_proves_values` separately binds the already
    # normalized aggregate to the current review, so this routine does not
    # introduce a second floating-point formatting contract for the same
    # arithmetic.
    return capture.source.quality == min(qualities, key=lambda value: quality_rank[value])


_RAW_SOURCE_PROVENANCE_FIELDS = frozenset(
    {
        "raw_packet_path",
        "raw_packet_sha256",
        "raw_packet_id",
        "raw_evidence_type",
        "raw_source_name",
        "raw_symbol",
        "raw_subject",
        "raw_as_of",
        "raw_quality",
        "raw_generated_at",
    }
)
_NEWS_SELECTION_POLICY = "configured_provider_priority_then_newest_event_then_packet_id"
_NEWS_PROVIDER_PRIORITY = {"alpaca_news": 0, "finnhub": 1, "fmp": 2}
_NATIVE_NEWS_RAW_TYPES = {
    ("alpaca_news", "market_news"),
    ("finnhub", "company_news"),
    ("fmp", "stock_news"),
}


def _authenticate_raw_provider_packet(
    *,
    root: Path,
    provenance: Mapping[str, Any],
    symbol: str,
    cache: dict[str, tuple[bytes, Mapping[str, Any]]],
) -> Mapping[str, Any] | None:
    """Open one declared raw packet and prove its exact recorded identity.

    Manifest authentication intentionally precedes source semantics.  A raw
    packet that is stale or otherwise ineligible can be diagnostic, but a
    missing, substituted, malformed, or hash-mismatched declared packet makes
    the complete candidate manifest untrustworthy.
    """
    if set(provenance) != _RAW_SOURCE_PROVENANCE_FIELDS:
        return None
    raw_path = provenance.get("raw_packet_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    try:
        if raw_path in cache:
            raw, stored = cache[raw_path]
        else:
            _target, raw, stored = _read_contained(
                root, raw_path, label="raw provider source packet"
            )
            cache[raw_path] = (raw, stored)
    except ValueError:
        return None
    try:
        stored_as_of = _canonical_raw_provider_time(
            stored.get("as_of"), "raw provider as_of"
        )
        declared_as_of = _canonical_raw_provider_time(
            provenance.get("raw_as_of"), "raw provenance as_of"
        )
        stored_generated_at = _canonical_raw_provider_time(
            stored.get("generated_at"), "raw provider generated_at"
        )
        declared_generated_at = _canonical_raw_provider_time(
            provenance.get("raw_generated_at"), "raw provenance generated_at"
        )
    except ValueError:
        return None
    if (
        hashlib.sha256(raw).hexdigest() != provenance.get("raw_packet_sha256")
        or stored.get("packet_id") != provenance.get("raw_packet_id")
        or stored.get("evidence_type") != provenance.get("raw_evidence_type")
        or stored.get("source_name") != provenance.get("raw_source_name")
        or stored.get("symbol") != provenance.get("raw_symbol")
        or stored.get("subject") != provenance.get("raw_subject")
        or stored_as_of != declared_as_of
        or stored.get("quality") != provenance.get("raw_quality")
        or stored_generated_at != declared_generated_at
        # The complete manifest includes market-context components such as
        # SPY/QQQ/sector quotes.  Their symbol is authenticated against the
        # declared raw identity above; semantic admission of issuer-specific
        # news below still requires the reviewed symbol.
        or not isinstance(provenance.get("raw_symbol"), str)
        or not provenance["raw_symbol"].strip()
    ):
        return None
    return stored


def _replay_authenticated_raw_provider_packet(
    *,
    raw_packet: Mapping[str, Any],
    symbol: str,
    now: dt.datetime,
) -> tuple[str, dict[str, Any], str] | None:
    """Apply semantic eligibility only after raw packet authentication."""
    from tradingagents.research.loss_review_evidence import (
        replay_normalized_loss_review_source,
    )

    return replay_normalized_loss_review_source(
        raw_packet=raw_packet,
        symbol=symbol,
        now=now,
    )


def _capture_raw_provider_packet(
    *,
    root: Path,
    provenance: Mapping[str, Any],
    symbol: str,
    now: dt.datetime,
    cache: dict[str, tuple[bytes, Mapping[str, Any]]],
) -> tuple[Mapping[str, Any], tuple[str, dict[str, Any], str]] | None:
    """Authenticate one raw provider packet and replay it for source use."""
    stored = _authenticate_raw_provider_packet(
        root=root,
        provenance=provenance,
        symbol=symbol,
        cache=cache,
    )
    if stored is None:
        return None

    replayed = _replay_authenticated_raw_provider_packet(
        raw_packet=stored,
        symbol=symbol,
        now=now,
    )
    return (stored, replayed) if replayed is not None else None


def _authoritative_news_selection(
    payload: Mapping[str, Any],
    *,
    root: Path,
    symbol: str,
    now: dt.datetime,
    raw_cache: dict[str, tuple[bytes, Mapping[str, Any]]],
) -> Mapping[str, Any] | None:
    """Replay every native-news raw packet, never a normalized self-subset.

    ``source_packet_ids`` is the loss packet's complete direct-provider
    identity list.  Its matching raw manifest lets the recorder discover all
    configured native-news packets, authenticate them, and re-run the strict
    normalizer before considering the writer's eligible-candidate receipt.
    """
    source_ids = payload.get("source_packet_ids")
    raw_manifest = payload.get("raw_source_packet_manifest")
    declared_candidates = payload.get("news_candidate_manifest")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or not all(isinstance(item, str) and item for item in source_ids)
        or len(source_ids) != len(set(source_ids))
        or not isinstance(raw_manifest, list)
        or not isinstance(declared_candidates, list)
    ):
        return None

    raw_by_id: dict[str, Mapping[str, Any]] = {}
    for provenance in raw_manifest:
        if (
            not isinstance(provenance, Mapping)
            or set(provenance) != _RAW_SOURCE_PROVENANCE_FIELDS
        ):
            return None
        packet_id = provenance.get("raw_packet_id")
        if not isinstance(packet_id, str) or not packet_id or packet_id in raw_by_id:
            return None
        raw_by_id[packet_id] = provenance
    if set(raw_by_id) != set(source_ids):
        return None

    authenticated_raw: dict[str, Mapping[str, Any]] = {}
    for packet_id, provenance in raw_by_id.items():
        stored = _authenticate_raw_provider_packet(
            root=root,
            provenance=provenance,
            symbol=symbol,
            cache=raw_cache,
        )
        if stored is None:
            return None
        authenticated_raw[packet_id] = stored

    replayed_candidates: list[
        tuple[Mapping[str, Any], tuple[str, dict[str, Any], str]]
    ] = []
    for packet_id, provenance in raw_by_id.items():
        raw_type = (
            str(provenance.get("raw_source_name") or "").lower(),
            str(provenance.get("raw_evidence_type") or ""),
        )
        if raw_type not in _NATIVE_NEWS_RAW_TYPES:
            continue
        replayed = _replay_authenticated_raw_provider_packet(
            raw_packet=authenticated_raw[packet_id],
            symbol=symbol,
            now=now,
        )
        # Raw manifest authenticity was proved before this loop.  A stale,
        # low-quality, or non-adverse native event may therefore be skipped as
        # an ineligible diagnostic without masking a missing declared packet.
        if replayed is None:
            continue
        if replayed[0] == "company_news":
            replayed_candidates.append((provenance, replayed))

    declared_by_id: dict[str, Mapping[str, Any]] = {}
    for provenance in declared_candidates:
        if (
            not isinstance(provenance, Mapping)
            or set(provenance) != _RAW_SOURCE_PROVENANCE_FIELDS
        ):
            return None
        packet_id = provenance.get("raw_packet_id")
        if not isinstance(packet_id, str) or not packet_id or packet_id in declared_by_id:
            return None
        declared_by_id[packet_id] = provenance
    eligible_by_id = {
        str(provenance["raw_packet_id"]): provenance
        for provenance, _replayed in replayed_candidates
    }
    if declared_by_id != eligible_by_id or not replayed_candidates:
        return None

    def selection_key(
        candidate: tuple[Mapping[str, Any], tuple[str, dict[str, Any], str]]
    ) -> tuple[int, float, str]:
        provenance, replayed = candidate
        observed = _time(replayed[2], "replayed news as_of")
        return (
            _NEWS_PROVIDER_PRIORITY.get(
                str(provenance.get("raw_source_name")).lower(), 999
            ),
            -observed.timestamp(),
            str(provenance.get("raw_packet_id")),
        )

    return min(replayed_candidates, key=selection_key)[0]


def _replayed_normalized_source_matches_raw(
    capture: CapturedSourceEvidence,
    *,
    root: Path,
    symbol: str,
    now: dt.datetime,
    raw_cache: dict[str, tuple[bytes, Mapping[str, Any]]],
    selected_news_provenance: Mapping[str, Any] | None = None,
) -> bool:
    """Require exact raw-to-normalized replay, including news selection."""
    provenance = capture.packet_object.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    raw_provenance = {
        key: provenance.get(key) for key in _RAW_SOURCE_PROVENANCE_FIELDS
    }
    provenance_keys = set(provenance)
    if capture.source.evidence_type == "company_news":
        if (
            provenance.get("selection_policy") != _NEWS_SELECTION_POLICY
            or selected_news_provenance is None
            or provenance_keys
            not in (
                set(_RAW_SOURCE_PROVENANCE_FIELDS) | {"selection_policy"},
                # Read legacy packets without using their self-declared
                # candidate list.  It is deliberately ignored below.
                set(_RAW_SOURCE_PROVENANCE_FIELDS)
                | {"selection_policy", "candidate_raw_packets"},
            )
        ):
            return False
        if raw_provenance != dict(selected_news_provenance):
            return False
        captured = _capture_raw_provider_packet(
            root=root,
            provenance=raw_provenance,
            symbol=symbol,
            now=now,
            cache=raw_cache,
        )
        if captured is None:
            return False
        _stored, replayed = captured
    else:
        if provenance_keys != set(_RAW_SOURCE_PROVENANCE_FIELDS):
            return False
        captured = _capture_raw_provider_packet(
            root=root,
            provenance=raw_provenance,
            symbol=symbol,
            now=now,
            cache=raw_cache,
        )
        if captured is None:
            return False
        _stored, replayed = captured

    normalized_type, normalized_payload, normalized_as_of = replayed
    normalized = capture.packet_object
    return (
        normalized_type == capture.source.evidence_type
        and normalized.get("packet_id")
        == f"normalized-{raw_provenance['raw_packet_id']}-{normalized_type}"
        and normalized.get("source_name") == raw_provenance["raw_source_name"]
        and normalized.get("subject") == symbol
        and normalized.get("symbol") == symbol
        and normalized.get("as_of") == normalized_as_of == capture.source.as_of
        and normalized.get("quality") == raw_provenance["raw_quality"] == capture.source.quality
        and normalized.get("payload") == normalized_payload
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
    expected = {
        "symbol", "as_of", "event_category", "direction", "change_fraction"
    }
    if "event_at" in payload:
        expected.add("event_at")
    return (
        set(payload) == expected
        and payload.get("event_category") in _ADVERSE_FILING_EVENTS
        and payload.get("direction") == "adverse"
        and payload.get("change_fraction") is not None
        and _is_decimal(payload.get("change_fraction"), "filing change_fraction")
        and Decimal(payload["change_fraction"]) <= Decimal("-0.01")
        and ("event_at" not in payload or _is_time(payload.get("event_at"), "filing event_at"))
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
    return False


def _market_clock_is_current_and_bound(review: Mapping[str, Any], payload: Mapping[str, Any], now: dt.datetime) -> bool:
    """Require the captured read-only exchange clock, not a copied historic label."""
    clock = review.get("market_clock")
    if not isinstance(clock, Mapping) or clock != payload.get("market_clock_snapshot"):
        return False
    expected = {
        "source_name", "source_ref", "as_of", "captured_at", "market_session",
        "is_open", "raw_clock", "raw_clock_sha256",
    }
    if set(clock) != expected or clock.get("source_name") != "alpaca_clock" or clock.get("source_ref") != "alpaca:/v2/clock":
        return False
    if type(clock.get("is_open")) is not bool or clock.get("market_session") not in {"regular", "closed"}:
        return False
    if (clock["is_open"] and clock["market_session"] != "regular") or (not clock["is_open"] and clock["market_session"] != "closed"):
        return False
    raw = clock.get("raw_clock")
    if not isinstance(raw, Mapping) or not isinstance(clock.get("raw_clock_sha256"), str):
        return False
    expected_hash = hashlib.sha256(json.dumps(dict(raw), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if clock["raw_clock_sha256"] != expected_hash:
        return False
    try:
        observed, captured = _time(clock.get("as_of"), "clock as_of"), _time(clock.get("captured_at"), "clock captured_at")
    except ValueError:
        return False
    raw_timestamp = raw.get("timestamp")
    try:
        raw_observed = _raw_vendor_time(raw_timestamp, "raw clock timestamp")
    except ValueError:
        return False
    # All wrapper timestamps are canonical UTC whole seconds.  The raw provider
    # response may retain fractional seconds, but it must normalize exactly to
    # the wrapper's as_of value; it may not be replaced by a local clock.
    if (
        observed.microsecond != 0
        or captured.microsecond != 0
        or observed != raw_observed
        or raw.get("is_open") is not clock.get("is_open")
    ):
        return False
    return observed <= now and captured <= now and abs((observed - captured).total_seconds()) <= 15 * 60 and now - observed <= _MAX_AGE


def _semantic_gaps(
    review: Mapping[str, Any],
    payload: Mapping[str, Any],
    captures: tuple[CapturedSourceEvidence, ...],
    now: dt.datetime,
    root: Path,
) -> tuple[str, ...]:
    gaps: list[str] = []
    sources = tuple(capture.source for capture in captures)
    if not _market_clock_is_current_and_bound(review, payload, now):
        gaps.append("current_market_clock_missing_or_stale")
    for blocker_field in ("blockers", "blocked_reasons"):
        value = review.get(blocker_field)
        if not _sequence_of_text(value) or value:
            gaps.append(f"supervisor_{blocker_field}_not_exact_empty_list")
    remaining = payload.get("remaining_blockers")
    if not _sequence_of_text(remaining) or remaining:
        gaps.append("remaining_blockers_not_exact_empty_list")
    if review.get("trade_decision_allowed") is not True or review.get("allowed") is not True:
        gaps.append("trade_decision_not_allowed")
    execution_eligible = review.get("execution_eligible")
    execution_blockers = review.get("execution_blockers")
    expected_execution = review.get("market_session") == "regular"
    if type(execution_eligible) is not bool or execution_eligible is not expected_execution:
        gaps.append("execution_session_semantics_invalid")
    if not _sequence_of_text(execution_blockers) or (
        (execution_eligible and execution_blockers)
        or (not execution_eligible and execution_blockers != ["market session is not tradeable for a live loss exit"])
    ):
        gaps.append("execution_blockers_invalid")
    context = review.get("broad_market_context")
    sector = review.get("sector_or_peer_context")
    if (
        not isinstance(context, Mapping)
        or not all(_is_decimal(context.get(x), x) for x in ("SPY", "QQQ"))
        or not all(_is_decimal(review.get(x), x) for x in ("relative_performance_vs_SPY", "relative_performance_vs_QQQ"))
        or not isinstance(sector, Mapping)
        or not isinstance(sector.get("sector"), str)
        # The current review records the configured comparison proxy (XLK by
        # default), not an unreliable inferred industry label.
        or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,15}", sector.get("sector"))
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
    raw_source_cache: dict[str, tuple[bytes, Mapping[str, Any]]] = {}
    selected_news_provenance = _authoritative_news_selection(
        payload,
        root=root,
        symbol=review["symbol"],
        now=now,
        raw_cache=raw_source_cache,
    )
    if selected_news_provenance is None:
        gaps.append("news_candidate_manifest_invalid_or_incomplete")
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
            if (
                _market_source_proves_values(source_payload, review, source)
                and _market_source_has_exact_component_provenance(
                    capture, root, review["symbol"], now
                )
            ):
                categories.add("market")
            else:
                gaps.append("market_source_values_missing_or_unbound")
        elif source.evidence_type == "company_news":
            if (
                _news_source_proves_adverse_break(source_payload)
                and _replayed_normalized_source_matches_raw(
                    capture,
                    root=root,
                    symbol=review["symbol"],
                    now=now,
                    raw_cache=raw_source_cache,
                    selected_news_provenance=selected_news_provenance,
                )
            ):
                categories.add("news")
                source_payloads["company_news"] = source_payload
            else:
                gaps.append("company_news_raw_provenance_replay_failed")
        elif source.evidence_type == "earnings_guidance_filing":
            if (
                _filing_source_proves_adverse_fact(source_payload)
                and _replayed_normalized_source_matches_raw(
                    capture,
                    root=root,
                    symbol=review["symbol"],
                    now=now,
                    raw_cache=raw_source_cache,
                )
            ):
                categories.add("substance")
                source_payloads["earnings_guidance_filing"] = source_payload
            else:
                gaps.append("filing_raw_provenance_replay_failed")
    if (
        review.get("trade_decision_allowed") is not True
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
    historical_review = ((supervisor_raw.get("evidence") or {}).get("loss_exit_review")) if isinstance(supervisor_raw.get("evidence"), Mapping) else None
    payload = loss_raw.get("payload") if isinstance(loss_raw.get("payload"), Mapping) else None
    if (
        not isinstance(historical_review, Mapping)
        or not isinstance(payload, Mapping)
        or not isinstance(historical_review.get("symbol"), str)
        or _SYMBOL.fullmatch(historical_review["symbol"]) is None
        or loss_raw.get("symbol") != historical_review["symbol"]
        or payload.get("symbol") != historical_review["symbol"]
        or payload.get("supervisor_packet_path") != supervisor.path
        or payload.get("supervisor_decision_id") != historical_review.get("decision_id")
    ):
        raise ValueError("loss packet is not exactly bound to the supervisor decision")
    if _REVISION.fullmatch(revision) is None:
        raise ValueError("source_revision must be lowercase 40-hex")
    review = payload.get("current_loss_review")
    if not isinstance(review, Mapping) or review.get("schema") != "tradingagents.refreshed_loss_review.v1":
        # Legacy historical review fields are deliberately not an authority.
        review = {}
    original = review.get("original_supervisor") if isinstance(review, Mapping) else None
    if not isinstance(original, Mapping) or original != {
        "decision_id": historical_review.get("decision_id"),
        "path": supervisor.path,
        "sha256": supervisor.sha256,
        "size_bytes": supervisor.size_bytes,
    }:
        review = {}
    if review and review.get("symbol") != historical_review["symbol"]:
        review = {}
    if not review:
        review = {
            "symbol": historical_review["symbol"],
            "blockers": ["refreshed evidence is incomplete"],
            "blocked_reasons": ["refreshed evidence is incomplete"],
        }
    captures = _sources(root, payload.get("accepted_sources"), historical_review["symbol"])
    sources = tuple(capture.source for capture in captures)
    gaps = list(_semantic_gaps(review, payload, captures, now, root))
    # SourceEvidencePacket owns ``analysis_only`` at the envelope.  The
    # loss-review-specific no-execution fields live in its payload, which is
    # the actual configured packet shape written by the research route.
    if (
        loss_raw.get("analysis_only") is not True
        or not isinstance(payload, Mapping)
        or payload.get("execution_authority") != "none"
        or payload.get("can_submit_orders") is not False
        or loss_raw.get("source_name") != "loss_review_evidence"
        or loss_raw.get("evidence_type") != "loss_review_evidence"
    ):
        gaps.append("raw_loss_packet_authority_or_identity_invalid")
    try:
        # The immutable current review is the decision-time evidence.  The
        # envelope's writer timestamp may be later (or, in queued local runs,
        # earlier) than the provider observations, so verify the strict
        # source-bound review timestamp rather than a serializer clock.
        loss_generated = _time(
            review.get("evidence_generated_at"),
            "current loss review evidence_generated_at",
        )
        if loss_generated > now or now - loss_generated > _MAX_AGE:
            gaps.append("raw_loss_packet_stale")
    except ValueError:
        gaps.append("raw_loss_packet_timestamp_invalid")
    gaps = tuple(dict.fromkeys(gaps))
    confidence = review.get("confidence") if isinstance(review.get("confidence"), str) and _DECIMAL.fullmatch(review["confidence"]) else "0"
    sell = not gaps and Decimal(confidence) >= Decimal("0.75")
    decision_execution_eligible = review.get("execution_eligible") is True
    raw_execution_blockers = review.get("execution_blockers")
    decision_execution_blockers = (
        tuple(raw_execution_blockers)
        if isinstance(raw_execution_blockers, list)
        and all(isinstance(item, str) and item.strip() for item in raw_execution_blockers)
        else ("decision evidence is incomplete",)
    )
    if decision_execution_eligible:
        decision_execution_blockers = ()
    elif not decision_execution_blockers:
        decision_execution_blockers = ("market session is not tradeable for a live loss exit",)
    generated, expires = now.isoformat(timespec="seconds"), (now + _MAX_AGE).isoformat(timespec="seconds")
    base = {
        "schema_version": SCHEMA_VERSION,
        "decision": "SELL" if sell else "HOLD",
        "symbol": review["symbol"],
        "supervisor_decision_id": historical_review.get("decision_id"),
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
        "execution_eligible": decision_execution_eligible,
        "execution_blockers": list(decision_execution_blockers),
        "exit_allowed": sell and decision_execution_eligible,
        "producer_role": "portfolio_executive",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    return AutonomousLossBoardDecision.from_dict({"decision_id": hashlib.sha256(_canon(base)).hexdigest(), **base})


def _publish(root: Path, relative: Path, content: bytes) -> Path:
    target = _inside(root, relative, label="decision evidence")
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW)
    parent_fd = root_fd
    try:
        for part in relative.parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW, dir_fd=parent_fd)
            if parent_fd != root_fd:
                os.close(parent_fd)
            parent_fd = next_fd
        try:
            descriptor = os.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            descriptor = os.open(relative.name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode) or os.read(descriptor, len(content) + 1) != content:
                    raise ValueError("immutable decision evidence collision")
            finally:
                os.close(descriptor)
            return target
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(parent_fd)
        finally:
            if descriptor != -1:
                os.close(descriptor)
    finally:
        if parent_fd != root_fd:
            os.close(parent_fd)
        os.close(root_fd)
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
