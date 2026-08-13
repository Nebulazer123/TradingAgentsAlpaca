"""Immutable, decision-only autonomous loss BOARD records.

This module deliberately establishes a decision boundary, not an execution
boundary.  A recorded ``SELL`` is only an evidence-backed portfolio decision;
it cannot create an order or grant submission authority.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from tradingagents.orchestration.decision_ledger import DecisionLedger
from tradingagents.orchestration.work_packets import EvidenceRef, WorkPacket

SCHEMA_VERSION = "tradingagents.autonomous_loss_board_decision.v1"
_UTC = dt.timezone.utc
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,15}$")
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
_ACCEPTED_QUALITY = frozenset({"high", "medium"})
_MAX_EVIDENCE_AGE = dt.timedelta(minutes=15)
_CLOSED_SESSION = frozenset({"closed", "non_tradeable", "non-tradeable"})
_GAP_MARKERS = ("gap", "missing", "unavailable", "connector")
_INDEX_MARKERS = ("submissions_index", "submissions index", "sec index")


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _utc_now(value: dt.datetime | None) -> dt.datetime:
    current = value if value is not None else dt.datetime.now(tz=_UTC)
    if not isinstance(current, dt.datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    return current.astimezone(_UTC).replace(microsecond=0)


def _parse_utc(value: Any, *, field_name: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UTC ISO-8601 seconds string")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UTC ISO-8601 seconds string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    normalized = parsed.astimezone(_UTC)
    if normalized.microsecond or normalized.isoformat(timespec="seconds") != value:
        raise ValueError(f"{field_name} must be canonical UTC seconds")
    return normalized


def _utc_text(value: dt.datetime) -> str:
    return _utc_now(value).isoformat(timespec="seconds")


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise ValueError(f"{field_name} must be a nonempty canonical string")
    return value


def _canonical_decimal(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{field_name} must use canonical decimal syntax")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must use canonical decimal syntax") from exc
    if not parsed.is_finite() or Decimal(value) != parsed:
        raise ValueError(f"{field_name} must be finite")
    return value


def _has_decimal(value: Any) -> bool:
    try:
        text = str(value).strip().removesuffix("%")
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return False
    return parsed.is_finite()


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


@dataclass(frozen=True)
class BoundEvidence:
    """A source-root-relative immutable evidence binding."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or Path(self.path).is_absolute():
            raise ValueError("bound evidence path must be a nonempty relative path")
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("bound evidence sha256 must be lowercase SHA-256")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ValueError("bound evidence size_bytes must be a nonnegative integer")

    def compact(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size_bytes": self.size_bytes}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BoundEvidence:
        if set(payload) != {"path", "sha256", "size_bytes"}:
            raise ValueError("bound evidence fields are invalid")
        return cls(
            path=payload["path"], sha256=payload["sha256"], size_bytes=payload["size_bytes"]
        )

    def verify(self, evidence_root: str | Path) -> bool:
        try:
            root = Path(evidence_root).resolve()
            path = (root / self.path).resolve()
            path.relative_to(root)
            payload = path.read_bytes()
        except (OSError, ValueError):
            return False
        return len(payload) == self.size_bytes and hashlib.sha256(payload).hexdigest() == self.sha256


@dataclass(frozen=True)
class BoundSourceEvidence:
    """A canonical binding to accepted source evidence described in the raw packet."""

    source_name: str
    evidence_type: str
    source_ref: str
    as_of: str
    quality: str
    source_sha256: str

    def __post_init__(self) -> None:
        for field_name in ("source_name", "evidence_type", "source_ref", "quality"):
            _text(getattr(self, field_name), field_name=field_name)
        _parse_utc(self.as_of, field_name="source as_of")
        if _SHA256.fullmatch(self.source_sha256) is None:
            raise ValueError("source_sha256 must be lowercase SHA-256")

    def compact(self) -> dict[str, str]:
        return {
            "source_name": self.source_name,
            "evidence_type": self.evidence_type,
            "source_ref": self.source_ref,
            "as_of": self.as_of,
            "quality": self.quality,
            "source_sha256": self.source_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BoundSourceEvidence:
        expected = {"source_name", "evidence_type", "source_ref", "as_of", "quality", "source_sha256"}
        if set(payload) != expected:
            raise ValueError("bound source evidence fields are invalid")
        return cls(**dict(payload))


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
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("schema_version is invalid")
        if self.decision not in {"HOLD", "SELL"}:
            raise ValueError("decision must be HOLD or SELL")
        if not isinstance(self.symbol, str) or _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("symbol must be uppercase ticker")
        _text(self.supervisor_decision_id, field_name="supervisor_decision_id")
        if not isinstance(self.supervisor_packet, BoundEvidence) or not isinstance(self.loss_evidence_packet, BoundEvidence):
            raise ValueError("decision evidence bindings are invalid")
        if not isinstance(self.accepted_sources, tuple):
            raise ValueError("accepted_sources must be a tuple")
        if not all(isinstance(item, BoundSourceEvidence) for item in self.accepted_sources):
            raise ValueError("accepted_sources must contain source bindings")
        source_keys = tuple(_canonical_json_bytes(item.compact()) for item in self.accepted_sources)
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("accepted_sources must be unique exact bindings")
        if _REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("source_revision must be lowercase 40-hex")
        generated = _parse_utc(self.generated_at, field_name="generated_at")
        expires = _parse_utc(self.expires_at, field_name="expires_at")
        if not generated < expires <= generated + _MAX_EVIDENCE_AGE:
            raise ValueError("expires_at must be within 15 minutes after generated_at")
        _text(self.thesis_verdict, field_name="thesis_verdict")
        _text(self.reason_code, field_name="reason_code")
        confidence = Decimal(_canonical_decimal(self.confidence, field_name="confidence"))
        if not isinstance(self.evidence_complete, bool):
            raise ValueError("evidence_complete must be an exact boolean")
        if not isinstance(self.trade_decision_resolved, bool) or self.trade_decision_resolved is not True:
            raise ValueError("trade_decision_resolved must be true")
        if not isinstance(self.exit_allowed, bool):
            raise ValueError("exit_allowed must be an exact boolean")
        if not isinstance(self.evidence_gaps, tuple) or not all(_nonempty(item) for item in self.evidence_gaps):
            raise ValueError("evidence_gaps must be a tuple of nonempty strings")
        if len(self.evidence_gaps) != len(set(self.evidence_gaps)):
            raise ValueError("evidence_gaps must be unique")
        sell = self.decision == "SELL"
        if sell is not self.exit_allowed or sell is not self.evidence_complete:
            raise ValueError("decision, exit_allowed, and evidence_complete must agree")
        if sell and (self.evidence_gaps or confidence < Decimal("0.75")):
            raise ValueError("SELL requires complete evidence, no gaps, and confidence at least 0.75")
        if not self.evidence_complete and not self.evidence_gaps:
            raise ValueError("incomplete evidence requires a nonempty evidence gap")
        expected = hashlib.sha256(_canonical_json_bytes(self._identity_payload())).hexdigest()
        if _SHA256.fullmatch(self.decision_id) is None or self.decision_id != expected:
            raise ValueError("decision_id does not match canonical decision material")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision,
            "symbol": self.symbol,
            "supervisor_decision_id": self.supervisor_decision_id,
            "supervisor_packet": self.supervisor_packet.compact(),
            "loss_evidence_packet": self.loss_evidence_packet.compact(),
            "accepted_sources": [item.compact() for item in self.accepted_sources],
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
        return {"decision_id": self.decision_id, **self._identity_payload()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AutonomousLossBoardDecision:
        expected = {
            "schema_version", "decision_id", "decision", "symbol", "supervisor_decision_id",
            "supervisor_packet", "loss_evidence_packet", "accepted_sources", "source_revision",
            "generated_at", "expires_at", "thesis_verdict", "reason_code", "confidence",
            "evidence_complete", "evidence_gaps", "trade_decision_resolved", "exit_allowed",
            "producer_role", "analysis_only", "execution_authority", "can_submit_orders",
        }
        if set(payload) != expected:
            raise ValueError("decision fields are invalid")
        if payload["producer_role"] != "portfolio_executive" or payload["analysis_only"] is not True or payload["execution_authority"] != "none" or payload["can_submit_orders"] is not False:
            raise ValueError("decision execution authority is invalid")
        if not isinstance(payload["supervisor_packet"], Mapping) or not isinstance(payload["loss_evidence_packet"], Mapping):
            raise ValueError("decision evidence bindings are invalid")
        if not isinstance(payload["accepted_sources"], list) or not isinstance(payload["evidence_gaps"], list):
            raise ValueError("decision collection fields are invalid")
        return cls(
            schema_version=payload["schema_version"],
            decision_id=payload["decision_id"],
            decision=payload["decision"],
            symbol=payload["symbol"],
            supervisor_decision_id=payload["supervisor_decision_id"],
            supervisor_packet=BoundEvidence.from_dict(payload["supervisor_packet"]),
            loss_evidence_packet=BoundEvidence.from_dict(payload["loss_evidence_packet"]),
            accepted_sources=tuple(BoundSourceEvidence.from_dict(item) for item in payload["accepted_sources"] if isinstance(item, Mapping)),
            source_revision=payload["source_revision"],
            generated_at=payload["generated_at"],
            expires_at=payload["expires_at"],
            thesis_verdict=payload["thesis_verdict"],
            reason_code=payload["reason_code"],
            confidence=payload["confidence"],
            evidence_complete=payload["evidence_complete"],
            evidence_gaps=tuple(payload["evidence_gaps"]),
            trade_decision_resolved=payload["trade_decision_resolved"],
            exit_allowed=payload["exit_allowed"],
        )


@dataclass(frozen=True)
class RecordedLossBoardDecision:
    decision: AutonomousLossBoardDecision
    packet: WorkPacket
    packet_path: Path
    decision_evidence_path: Path


def _capture_bound_json(path: str | Path, evidence_root: Path) -> tuple[BoundEvidence, Mapping[str, Any]]:
    supplied = Path(path)
    try:
        resolved_root = evidence_root.resolve()
        resolved = supplied.resolve()
        relative = resolved.relative_to(resolved_root)
        payload_bytes = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("bound evidence path must be a readable file beneath evidence_root") from exc
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bound evidence must contain a JSON object") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("bound evidence must contain a JSON object")
    return (
        BoundEvidence(path=relative.as_posix(), sha256=hashlib.sha256(payload_bytes).hexdigest(), size_bytes=len(payload_bytes)),
        payload,
    )


def _source_bindings(loss_payload: Mapping[str, Any]) -> tuple[BoundSourceEvidence, ...]:
    candidates = loss_payload.get("accepted_sources")
    if candidates is None:
        advisory = _mapping(loss_payload.get("advisory_analysis")) or {}
        candidates = advisory.get("source_refs")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes, bytearray)):
        return ()
    sources: list[BoundSourceEvidence] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        try:
            material = {
                "source_name": _text(item.get("source_name") or item.get("source") or "", field_name="source_name"),
                "evidence_type": _text(item.get("evidence_type") or "", field_name="evidence_type"),
                "source_ref": _text(item.get("source_ref") or item.get("path") or item.get("packet_id") or "", field_name="source_ref"),
                "as_of": item.get("as_of") or item.get("generated_at"),
                "quality": _text(item.get("quality") or "", field_name="quality"),
            }
            sources.append(BoundSourceEvidence(**material, source_sha256=hashlib.sha256(_canonical_json_bytes(material)).hexdigest()))
        except ValueError:
            continue
    return tuple(sources)


def _fresh_source(source: BoundSourceEvidence, now: dt.datetime) -> bool:
    try:
        observed = _parse_utc(source.as_of, field_name="source as_of")
    except ValueError:
        return False
    return observed <= now and now - observed <= _MAX_EVIDENCE_AGE


def _has_accepted_source(sources: Sequence[BoundSourceEvidence], *, category: str, now: dt.datetime) -> bool:
    for source in sources:
        descriptor = f"{source.source_name} {source.evidence_type}".lower()
        if source.quality not in _ACCEPTED_QUALITY or not _fresh_source(source, now):
            continue
        if any(marker in descriptor for marker in (*_GAP_MARKERS, *_INDEX_MARKERS)):
            continue
        if category == "market" and any(marker in descriptor for marker in ("market", "quote", "sector", "benchmark")):
            return True
        if category == "news" and "news" in descriptor:
            return True
        if category == "substance" and any(marker in descriptor for marker in ("earnings", "guidance", "filing", "transcript")):
            return True
    return False


def _actual_market_values(review: Mapping[str, Any]) -> bool:
    context = _mapping(review.get("broad_market_context")) or {}
    spy = context.get("SPY", context.get("spy"))
    qqq = context.get("QQQ", context.get("qqq"))
    sector = review.get("sector_or_peer_context")
    return _has_decimal(spy) and _has_decimal(qqq) and _nonempty(sector) and any(char.isdigit() for char in str(sector))


def _gaps(
    *, review: Mapping[str, Any], loss_payload: Mapping[str, Any], sources: Sequence[BoundSourceEvidence], now: dt.datetime
) -> tuple[str, ...]:
    gaps: list[str] = []
    if review.get("allowed") is not True:
        gaps.append("supervisor_loss_exit_not_exactly_allowed")
    if not _actual_market_values(review):
        gaps.append("spy_qqq_sector_values_missing")
    if not _has_accepted_source(sources, category="market", now=now):
        gaps.append("accepted_market_source_missing_or_stale")
    if not _nonempty(review.get("company_specific_negative_news_check")):
        gaps.append("company_specific_news_missing")
    if not _has_accepted_source(sources, category="news", now=now):
        gaps.append("accepted_company_news_missing_or_stale")
    filing = review.get("earnings_guidance_or_filing_check")
    if not _nonempty(filing) or any(marker in filing.lower() for marker in _INDEX_MARKERS):
        gaps.append("earnings_guidance_filing_substance_missing")
    if not _has_accepted_source(sources, category="substance", now=now):
        gaps.append("accepted_earnings_guidance_filing_source_missing_or_stale")
    reason = review.get("allowed_exit_reason")
    reason_source = review.get("allowed_exit_reason_source")
    if not _nonempty(reason) or not _nonempty(reason_source):
        gaps.append("recognized_loss_exit_reason_missing")
    thesis = review.get("current_thesis_status")
    hold_worse = review.get("why_hold_is_worse_than_sell")
    if not _nonempty(thesis) or not _nonempty(hold_worse):
        gaps.append("current_thesis_verdict_missing")
    try:
        confidence = Decimal(_canonical_decimal(review.get("confidence"), field_name="supervisor confidence"))
    except ValueError:
        confidence = Decimal("0")
        gaps.append("confidence_missing_or_noncanonical")
    if confidence < Decimal("0.75"):
        gaps.append("confidence_below_0_75")
    generated = review.get("evidence_generated_at")
    try:
        observed = _parse_utc(generated, field_name="evidence_generated_at")
        if observed > now or now - observed > _MAX_EVIDENCE_AGE:
            gaps.append("supervisor_evidence_stale")
    except ValueError:
        gaps.append("supervisor_evidence_timestamp_invalid")
    raw_blockers = loss_payload.get("remaining_blockers")
    if isinstance(raw_blockers, Sequence) and not isinstance(raw_blockers, (str, bytes, bytearray)):
        non_session = [item for item in raw_blockers if str(item).strip().lower() not in _CLOSED_SESSION]
        if non_session:
            gaps.append("remaining_loss_evidence_blockers")
    elif raw_blockers is not None:
        gaps.append("remaining_loss_evidence_blockers_invalid")
    session = str(review.get("market_session") or "").strip().lower()
    if session in _CLOSED_SESSION:
        # Closed session prevents execution later but does not invalidate a completed decision.
        pass
    return tuple(dict.fromkeys(gaps))


def _raw_loss_packet_gaps(loss_packet: Mapping[str, Any], now: dt.datetime) -> tuple[str, ...]:
    """Validate the authority and freshness envelope around loss payload content."""
    gaps: list[str] = []
    if loss_packet.get("analysis_only") is not True:
        gaps.append("loss_evidence_analysis_only_invalid")
    if loss_packet.get("execution_authority") != "none":
        gaps.append("loss_evidence_execution_authority_invalid")
    if loss_packet.get("can_submit_orders") is not False:
        gaps.append("loss_evidence_can_submit_orders_invalid")
    if loss_packet.get("source_name") != "loss_review_evidence" or loss_packet.get("evidence_type") != "loss_review_evidence":
        gaps.append("loss_evidence_packet_identity_invalid")
    try:
        generated = _parse_utc(loss_packet.get("generated_at"), field_name="loss evidence generated_at")
        if generated > now or now - generated > _MAX_EVIDENCE_AGE:
            gaps.append("loss_evidence_packet_stale")
    except ValueError:
        gaps.append("loss_evidence_packet_timestamp_invalid")
    return tuple(gaps)


def _decision_from_captured(
    *, supervisor: BoundEvidence, supervisor_payload: Mapping[str, Any], loss: BoundEvidence,
    loss_payload: Mapping[str, Any], source_revision: str, now: dt.datetime
) -> AutonomousLossBoardDecision:
    review_root = _mapping(supervisor_payload.get("evidence")) or {}
    review = _mapping(review_root.get("loss_exit_review"))
    if review is None:
        raise ValueError("supervisor packet does not contain evidence.loss_exit_review")
    symbol = review.get("symbol")
    raw_loss_payload = _mapping(loss_payload.get("payload")) or loss_payload
    loss_symbol = loss_payload.get("symbol", raw_loss_payload.get("symbol"))
    if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None or loss_symbol != symbol:
        raise ValueError("supervisor and loss evidence symbols must exactly match uppercase ticker")
    supervisor_decision_id = review.get("decision_id")
    if not _nonempty(supervisor_decision_id):
        raise ValueError("supervisor decision_id is required")
    if _REVISION.fullmatch(source_revision) is None:
        raise ValueError("source_revision must be lowercase 40-hex")
    sources = _source_bindings(raw_loss_payload)
    gaps = tuple(
        dict.fromkeys(
            (*_gaps(review=review, loss_payload=raw_loss_payload, sources=sources, now=now), *_raw_loss_packet_gaps(loss_payload, now))
        )
    )
    confidence = review.get("confidence")
    try:
        confidence_text = _canonical_decimal(confidence, field_name="supervisor confidence")
    except ValueError:
        confidence_text = "0"
    complete = not gaps
    sell = complete and Decimal(confidence_text) >= Decimal("0.75")
    decision = "SELL" if sell else "HOLD"
    reason_code = "evidence_incomplete" if decision == "HOLD" else "loss_exit_evidence_complete"
    thesis = review.get("current_thesis_status") or review.get("why_hold_is_worse_than_sell") or "Evidence is incomplete; HOLD remains the safe decision."
    generated_at = _utc_text(now)
    expires_at = _utc_text(now + _MAX_EVIDENCE_AGE)
    base = {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "symbol": symbol,
        "supervisor_decision_id": supervisor_decision_id,
        "supervisor_packet": supervisor.compact(),
        "loss_evidence_packet": loss.compact(),
        "accepted_sources": [item.compact() for item in sources],
        "source_revision": source_revision,
        "generated_at": generated_at,
        "expires_at": expires_at,
        "thesis_verdict": thesis,
        "reason_code": reason_code,
        "confidence": confidence_text,
        "evidence_complete": complete,
        "evidence_gaps": list(gaps),
        "trade_decision_resolved": True,
        "exit_allowed": sell,
        "producer_role": "portfolio_executive",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }
    return AutonomousLossBoardDecision.from_dict({"decision_id": hashlib.sha256(_canonical_json_bytes(base)).hexdigest(), **base})


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise ValueError("decision evidence object is unreadable") from exc
        if existing != content:
            raise ValueError("decision evidence object conflicts with immutable bytes") from None
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with suppress(OSError):
            path.unlink()
        raise


def record_autonomous_loss_board_decision(
    *, supervisor_packet_path: str | Path, loss_evidence_packet_path: str | Path,
    source_revision: str, ledger_root: str | Path, evidence_root: str | Path,
    now: dt.datetime | None = None,
) -> RecordedLossBoardDecision:
    """Record one verified HOLD/SELL decision without granting execution authority."""
    current = _utc_now(now)
    root = Path(evidence_root)
    supervisor, supervisor_payload = _capture_bound_json(supervisor_packet_path, root)
    loss, loss_payload = _capture_bound_json(loss_evidence_packet_path, root)
    decision = _decision_from_captured(
        supervisor=supervisor, supervisor_payload=supervisor_payload, loss=loss,
        loss_payload=loss_payload, source_revision=source_revision, now=current,
    )
    relative_decision_path = Path("autonomous_loss_board_decisions") / f"{decision.decision_id}.json"
    decision_path = root / relative_decision_path
    decision_bytes = _canonical_json_bytes({"decision": decision.compact()})
    _write_immutable(decision_path, decision_bytes)
    decision_ref = EvidenceRef(
        path=relative_decision_path.as_posix(),
        sha256=hashlib.sha256(decision_bytes).hexdigest(),
        size_bytes=len(decision_bytes),
    )
    packet = WorkPacket.create(
        kind="portfolio_decision",
        producer_role="portfolio_executive",
        run_id=decision.decision_id,
        subject=decision.symbol,
        evidence_refs=(
            EvidenceRef(
                path=str(decision_path.resolve()),
                sha256=decision_ref.sha256,
                size_bytes=decision_ref.size_bytes,
            ),
            EvidenceRef(
                path=str((root / decision.supervisor_packet.path).resolve()),
                sha256=decision.supervisor_packet.sha256,
                size_bytes=decision.supervisor_packet.size_bytes,
            ),
            EvidenceRef(
                path=str((root / decision.loss_evidence_packet.path).resolve()),
                sha256=decision.loss_evidence_packet.sha256,
                size_bytes=decision.loss_evidence_packet.size_bytes,
            ),
        ),
        claims=(f"Autonomous loss BOARD resolved {decision.symbol} as {decision.decision}.",),
        assumptions=(),
        recommendation=("autonomous_sell_authorized_pending_execution_intent" if decision.decision == "SELL" else "autonomous_hold"),
        confidence=float(Decimal(decision.confidence)),
        expires_at=_parse_utc(decision.expires_at, field_name="expires_at"),
        allowed_effects=("record_trade_decision",),
        now=current,
    )
    ledger = DecisionLedger(ledger_root)
    packet_path = ledger.record(packet, evidence_root=root, now=current)
    ledger.verify(evidence_root=root)
    return RecordedLossBoardDecision(decision=decision, packet=packet, packet_path=packet_path, decision_evidence_path=decision_path)


def verify_autonomous_loss_board_decision(
    decision_evidence_path: str | Path, *, evidence_root: str | Path, now: dt.datetime | None = None
) -> AutonomousLossBoardDecision:
    """Verify canonical bytes and every immutable evidence binding for a decision."""
    _utc_now(now)
    root = Path(evidence_root).resolve()
    path = Path(decision_evidence_path).resolve()
    try:
        path.relative_to(root)
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("decision evidence is unreadable or invalid JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"decision"} or not isinstance(payload["decision"], Mapping):
        raise ValueError("decision evidence payload is invalid")
    decision = AutonomousLossBoardDecision.from_dict(payload["decision"])
    if not decision.supervisor_packet.verify(root) or not decision.loss_evidence_packet.verify(root):
        raise ValueError("bound evidence verification failed")
    return decision
