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

from tradingagents.orchestration.decision_ledger import DecisionLedger
from tradingagents.orchestration.work_packets import EvidenceRef, WorkPacket

SCHEMA_VERSION = "tradingagents.autonomous_loss_board_decision.v1"
_UTC = dt.timezone.utc
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,15}$")
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
_MAX_AGE = dt.timedelta(minutes=15)
_QUALITIES = frozenset({"high", "medium"})
_EXIT_REASONS = frozenset({"thesis_invalidated", "guidance_cut", "fundamental_deterioration", "risk_limit_breach"})
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_GENERIC = frozenset({"ok", "good", "news", "filing", "update", "available", "none", "n/a", "unknown"})


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


def _meaningful(value: Any) -> bool:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    return len(normalized) >= 20 and normalized not in _GENERIC and not any(marker in normalized for marker in ("news update", "information available", "generic update", "no material change"))


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
    try:
        state = target.lstat()
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
            raise ValueError(f"{label} must be a regular non-symlink file")
        descriptor = os.open(target, os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            payload = handle.read()
    except OSError as exc:
        raise ValueError(f"{label} is unreadable") from exc
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

    def verify(self, root: Path) -> bool:
        if not self.packet.verify(root):
            return False
        try:
            _, _, raw = _read_contained(root, self.packet.path, label="source packet")
        except ValueError:
            return False
        return raw.get("packet_id") == self.packet_id and raw.get("source_name") == self.source_name and raw.get("evidence_type") == self.evidence_type and raw.get("as_of") == self.as_of and raw.get("quality") == self.quality


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


def _sources(root: Path, raw: Any, symbol: str) -> tuple[BoundSourceEvidence, ...]:
    if not isinstance(raw, list) or not raw:
        return ()
    result: list[BoundSourceEvidence] = []
    exact = {"path", "sha256", "size_bytes", "packet_id", "source_name", "evidence_type", "as_of", "quality"}
    for descriptor in raw:
        if not isinstance(descriptor, Mapping) or set(descriptor) != exact or not isinstance(descriptor.get("path"), str):
            return ()
        try:
            bound, packet = _bound(root, descriptor["path"], "accepted source packet")
            if bound.compact() != {"path": descriptor["path"], "sha256": descriptor["sha256"], "size_bytes": descriptor["size_bytes"]}:
                return ()
            if packet.get("symbol") != symbol or packet.get("subject") != symbol or any(packet.get(key) != descriptor[key] for key in ("packet_id", "source_name", "evidence_type", "as_of", "quality")):
                return ()
            result.append(BoundSourceEvidence(packet=bound, packet_id=descriptor["packet_id"], source_name=descriptor["source_name"], evidence_type=descriptor["evidence_type"], as_of=descriptor["as_of"], quality=descriptor["quality"]))
        except (ValueError, TypeError):
            return ()
    return tuple(result)


def _semantic_gaps(review: Mapping[str, Any], payload: Mapping[str, Any], sources: tuple[BoundSourceEvidence, ...], root: Path, now: dt.datetime) -> tuple[str, ...]:
    gaps: list[str] = []
    for blocker_field in ("blockers", "blocked_reasons"):
        value = review.get(blocker_field)
        if not _sequence_of_text(value) or value:
            gaps.append(f"supervisor_{blocker_field}_not_exact_empty_list")
    remaining = payload.get("remaining_blockers")
    if not _sequence_of_text(remaining) or remaining:
        gaps.append("remaining_blockers_not_exact_empty_list")
    context = review.get("broad_market_context")
    sector = review.get("sector_or_peer_context")
    if (
        not isinstance(context, Mapping)
        or not all(_is_decimal(context.get(x), x) for x in ("SPY", "QQQ"))
        or not all(_is_decimal(review.get(x), x) for x in ("relative_performance_vs_SPY", "relative_performance_vs_QQQ"))
        or not isinstance(sector, Mapping)
        or not _meaningful(sector.get("sector"))
        or not _is_decimal(sector.get("relative_performance"), "sector relative_performance")
    ):
        gaps.append("actual_spy_qqq_sector_relative_values_missing")
    if review.get("allowed") is not True or review.get("allowed_exit_reason") not in _EXIT_REASONS or not _meaningful(review.get("allowed_exit_reason_source")):
        gaps.append("recognized_exit_reason_missing")
    filing = review.get("earnings_guidance_or_filing_check")
    if not _meaningful(review.get("current_thesis_status")) or not _meaningful(review.get("why_hold_is_worse_than_sell")) or not _meaningful(review.get("company_specific_negative_news_check")) or not _meaningful(filing) or "submissions index" in filing.lower():
        gaps.append("meaningful_thesis_news_or_filing_missing")
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
        or not _meaningful(candidate.get("reason_summary"))
        or candidate.get("reason_summary") != review.get("why_hold_is_worse_than_sell")
        or advisory.get("current_thesis_status_candidate") != review.get("current_thesis_status")
    ):
        gaps.append("advisory_candidate_contradiction")
    categories: set[str] = set()
    for source in sources:
        if not source.verify(root):
            gaps.append("source_binding_invalid")
            continue
        try:
            _, _, raw = _read_contained(root, source.packet.path, label="source packet")
            observed = _time(source.as_of, "source as_of")
        except ValueError:
            gaps.append("source_binding_invalid")
            continue
        if observed > now or now - observed > _MAX_AGE:
            gaps.append("source_stale")
        payload_text = json.dumps(raw.get("payload"), sort_keys=True).lower()
        descriptor = f"{source.source_name} {source.evidence_type}".lower()
        if any(x in descriptor or x in payload_text for x in ("gap", "connector", "submissions_index", "submissions index")):
            gaps.append("source_gap_or_index")
        if source.evidence_type == "market_context":
            categories.add("market")
        elif source.evidence_type == "company_news" and _meaningful((raw.get("payload") or {}).get("headline")):
            categories.add("news")
        elif source.evidence_type in {"earnings_guidance_filing", "earnings_transcript"} and _meaningful((raw.get("payload") or {}).get("summary")):
            categories.add("substance")
    if categories != {"market", "news", "substance"}:
        gaps.append("required_source_substance_missing")
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
    sources = _sources(root, payload.get("accepted_sources"), review["symbol"])
    gaps = list(_semantic_gaps(review, payload, sources, root, now))
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
        "thesis_verdict": review.get("current_thesis_status") if _meaningful(review.get("current_thesis_status")) else "Evidence is incomplete; HOLD remains safer.",
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
        os.fsync(directory)
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


def verify_autonomous_loss_board_decision(decision_evidence_path: str | Path, *, evidence_root: str | Path, now: dt.datetime | None = None) -> AutonomousLossBoardDecision:
    current, root = _now(now), _root(evidence_root)
    _, content, raw = _read_contained(root, decision_evidence_path, label="decision evidence")
    if set(raw) != {"decision"} or not isinstance(raw["decision"], Mapping) or content != _canon(raw):
        raise ValueError("decision evidence is not exact canonical bytes")
    decision = AutonomousLossBoardDecision.from_dict(raw["decision"])
    generated, expires = _time(decision.generated_at, "generated_at"), _time(decision.expires_at, "expires_at")
    if not generated <= current < expires:
        raise ValueError("decision is not currently valid")
    if not decision.supervisor_packet.verify(root) or not decision.loss_evidence_packet.verify(root) or not all(item.verify(root) for item in decision.accepted_sources):
        raise ValueError("bound evidence verification failed")
    return decision
