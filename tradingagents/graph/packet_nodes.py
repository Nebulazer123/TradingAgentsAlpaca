"""Deterministic analysis-only packet compilers for graph role boundaries."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from tradingagents.orchestration.decision_ledger import (
    DecisionLedger,
    LedgerCorruptionError,
    LedgerEvent,
)
from tradingagents.orchestration.work_packets import (
    EvidenceRef,
    WorkPacket,
    build_packet_id,
)
from tradingagents.policy.io import atomic_write_text

PACKET_HANDOFF_SCHEMA_VERSION = 1
DECISION_PACKET_REF_SCHEMA_VERSION = 1
PACKET_HANDOFF_TTL = dt.timedelta(hours=24)

_UTC = dt.timezone.utc
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GRAPH_RUN_ID = re.compile(r"^graph-[0-9a-f]{64}$")
_AUTHORITY_FIELDS = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}
_REFERENCE_FIELDS = frozenset(
    {
        "schema_version",
        "packet_id",
        "kind",
        "packet_sha256",
        "packet_path",
        "evidence_sha256",
        *_AUTHORITY_FIELDS,
    }
)
_KIND_ORDER = (
    "research_evidence",
    "trader_proposal",
    "portfolio_decision",
)
_PARENT_KIND = {
    "research_evidence": None,
    "trader_proposal": "research_evidence",
    "portfolio_decision": "trader_proposal",
}
_STATE_FIELDS = {
    "research_evidence": (
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
    ),
    "trader_proposal": (
        "investment_debate_state.judge_decision",
        "investment_plan",
        "trader_investment_plan",
    ),
    "portfolio_decision": (
        "risk_debate_state.judge_decision",
        "final_trade_decision",
    ),
}
_PRODUCER_ROLES = {
    "research_evidence": "Analyst Team",
    "trader_proposal": "Trader",
    "portfolio_decision": "Portfolio Manager",
}
_TASK_BOUNDARIES = {
    "research_evidence": "analyst_reports_to_research_debate",
    "trader_proposal": "trader_proposal_to_risk_review",
    "portfolio_decision": "portfolio_decision_to_graph_completion",
}
_RECOMMENDATIONS = {
    "research_evidence": "Provide verified analyst evidence to the researcher team.",
    "trader_proposal": "Provide the verified trader proposal to the risk team.",
    "portfolio_decision": "Publish the verified portfolio decision for graph completion.",
}
_ALLOWED_EFFECTS = {
    "research_evidence": (
        "request_more_research",
        "downrank_confidence",
        "recommend_trade_proposal",
    ),
    "trader_proposal": (
        "request_more_research",
        "downrank_confidence",
        "recommend_block",
        "recommend_risk_envelope",
    ),
    "portfolio_decision": (
        "downrank_confidence",
        "recommend_block",
        "recommend_hold_cash",
    ),
}


def _canonical_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _canonical_utc_seconds(value: Any, *, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be canonical aware UTC seconds")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be canonical aware UTC seconds") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be canonical aware UTC seconds")
    normalized = parsed.astimezone(_UTC)
    if (
        normalized.microsecond != 0
        or normalized.isoformat(timespec="seconds") != value
    ):
        raise ValueError(f"{field} must be canonical aware UTC seconds")
    return normalized


def _clock_value(clock: Callable[[], dt.datetime]) -> dt.datetime:
    value = clock()
    if (
        not isinstance(value, dt.datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("clock must return an aware datetime")
    return value.astimezone(_UTC).replace(microsecond=0)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=_UTC).replace(microsecond=0)


def build_graph_run_id(
    company: str,
    trade_date: str,
    asset_type: str,
    run_signature: str,
) -> str:
    """Return the stable opaque identity for one logical graph run."""

    payload = {
        "company": _canonical_text(company, field="company"),
        "trade_date": _canonical_text(trade_date, field="trade_date"),
        "asset_type": _canonical_text(asset_type, field="asset_type"),
        "run_signature": _canonical_text(
            run_signature,
            field="run_signature",
        ),
        "schema_version": PACKET_HANDOFF_SCHEMA_VERSION,
    }
    return f"graph-{hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}"


def _lexical_root(root: str | Path, *, label: str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
    try:
        state = lexical.lstat()
    except FileNotFoundError:
        state = None
    except OSError as exc:
        raise ValueError(f"{label} could not be inspected") from exc
    if state is not None and stat.S_ISLNK(state.st_mode):
        raise ValueError(f"{label} must not be a symlink")
    try:
        lexical.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"{label} could not be created") from exc
    resolved = lexical.resolve()
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved


def _ensure_real_directory(path: Path, *, root: Path, label: str) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes evidence root") from exc
    current = root
    for component in relative.parts:
        current = current / component
        try:
            state = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir()
            except OSError as exc:
                raise ValueError(f"{label} could not be created") from exc
            state = current.lstat()
        except OSError as exc:
            raise ValueError(f"{label} could not be inspected") from exc
        if stat.S_ISLNK(state.st_mode):
            raise ValueError(f"{label} must not contain a symlink")
        if not stat.S_ISDIR(state.st_mode):
            raise ValueError(f"{label} must be a directory")
        try:
            current.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{label} escapes evidence root") from exc


def _read_regular_file(path: Path, *, label: str) -> bytes:
    try:
        state = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is missing") from exc
    except OSError as exc:
        raise ValueError(f"{label} could not be inspected") from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        raise ValueError(f"{label} must be a regular nonsymlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} could not be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{label} must be a regular file")
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as exc:
        raise ValueError(f"{label} could not be read") from exc
    finally:
        os.close(descriptor)


def _publish_evidence(
    *,
    evidence_root: Path,
    run_id: str,
    kind: str,
    payload: Mapping[str, Any],
) -> tuple[EvidenceRef, Path]:
    raw = _canonical_json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    directory = (
        evidence_root
        / "control_plane"
        / "decision_evidence"
        / run_id
    )
    _ensure_real_directory(
        directory,
        root=evidence_root,
        label="decision evidence directory",
    )
    path = directory / f"{kind}-{digest}.json"
    try:
        path.relative_to(evidence_root)
    except ValueError as exc:
        raise ValueError("evidence path escapes evidence root") from exc
    if path.exists() or path.is_symlink():
        if _read_regular_file(path, label="evidence artifact") != raw:
            raise ValueError("existing evidence artifact bytes do not match")
    else:
        atomic_write_text(path, raw.decode("utf-8"))
    if _read_regular_file(path, label="evidence artifact") != raw:
        raise ValueError("published evidence artifact bytes do not match")
    absolute_ref = EvidenceRef.from_path(path)
    relative_path = path.relative_to(evidence_root).as_posix()
    return replace(absolute_ref, path=relative_path), path


def _state_value(state: Mapping[str, Any], dotted_field: str) -> str:
    value: Any = state
    for component in dotted_field.split("."):
        if not isinstance(value, Mapping) or component not in value:
            raise ValueError(f"{dotted_field} is missing from graph state")
        value = value[component]
    if not isinstance(value, str):
        raise ValueError(f"{dotted_field} must be a string")
    return value


def _packet_reference(
    packet: WorkPacket,
    *,
    packet_digest: str,
) -> dict[str, Any]:
    return {
        "schema_version": DECISION_PACKET_REF_SCHEMA_VERSION,
        "packet_id": packet.packet_id,
        "kind": packet.kind,
        "packet_sha256": packet_digest,
        "packet_path": f"packets/{packet.packet_id}.json",
        "evidence_sha256": packet.evidence_refs[0].sha256,
        **_AUTHORITY_FIELDS,
    }


def _require_ref_shape(reference: Any) -> Mapping[str, Any]:
    if not isinstance(reference, Mapping) or set(reference) != _REFERENCE_FIELDS:
        raise ValueError("decision packet reference has invalid fields")
    if type(reference["schema_version"]) is not int or (
        reference["schema_version"] != DECISION_PACKET_REF_SCHEMA_VERSION
    ):
        raise ValueError("decision packet reference schema_version is invalid")
    for field in ("packet_id", "kind", "packet_sha256", "packet_path", "evidence_sha256"):
        if (
            not isinstance(reference[field], str)
            or not reference[field]
            or reference[field].strip() != reference[field]
        ):
            raise ValueError(f"decision packet reference {field} is invalid")
    if _LOWER_SHA256.fullmatch(reference["packet_sha256"]) is None:
        raise ValueError("decision packet reference packet_sha256 is invalid")
    if _LOWER_SHA256.fullmatch(reference["evidence_sha256"]) is None:
        raise ValueError("decision packet reference evidence_sha256 is invalid")
    if reference["analysis_only"] is not True:
        raise ValueError("decision packet reference analysis_only is invalid")
    if reference["execution_authority"] != "none":
        raise ValueError("decision packet reference execution_authority is invalid")
    if reference["can_submit_orders"] is not False:
        raise ValueError("decision packet reference can_submit_orders is invalid")
    return reference


def _event_for_packet(
    events: tuple[LedgerEvent, ...],
    packet_id: str,
) -> LedgerEvent:
    matches = [event for event in events if event.packet_id == packet_id]
    if not matches:
        raise ValueError(f"no durable ledger event for {packet_id}")
    first = matches[0]
    if any(
        event.kind != first.kind
        or event.run_id != first.run_id
        or event.packet_sha256 != first.packet_sha256
        for event in matches[1:]
    ):
        raise ValueError(f"conflicting durable ledger events for {packet_id}")
    return first


def _validate_durable_reference(
    reference: Any,
    *,
    expected_kind: str,
    expected_parent_ids: tuple[str, ...],
    run_id: str,
    run_started_at: dt.datetime,
    ledger_root: Path,
    evidence_root: Path,
    events: tuple[LedgerEvent, ...],
) -> dict[str, Any]:
    supplied = _require_ref_shape(reference)
    expected_id = build_packet_id(run_id, expected_kind)
    expected_path = f"packets/{expected_id}.json"
    if supplied["packet_id"] != expected_id or supplied["kind"] != expected_kind:
        raise ValueError("decision packet reference identity is invalid")
    if supplied["packet_path"] != expected_path:
        raise ValueError("decision packet reference path is invalid")
    event = _event_for_packet(events, expected_id)
    if event.run_id != run_id or event.kind != expected_kind:
        raise ValueError("decision packet ledger event belongs to another run")
    if supplied["packet_sha256"] != event.packet_sha256:
        raise ValueError("decision packet event digest does not match reference")

    packet_path = ledger_root / expected_path
    raw = _read_regular_file(packet_path, label="immutable work packet")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != event.packet_sha256:
        raise ValueError("immutable work packet digest does not match event")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("immutable work packet is not valid JSON") from exc
    try:
        packet = WorkPacket.from_dict(payload, now=run_started_at)
    except ValueError as exc:
        raise ValueError("immutable work packet schema is invalid") from exc
    if packet.canonical_json_bytes() != raw:
        raise ValueError("immutable work packet bytes are noncanonical")
    issues = packet.validate(
        now=run_started_at,
        evidence_root=evidence_root,
        verify_evidence=True,
    )
    if issues:
        raise ValueError("immutable work packet is invalid: " + "; ".join(issues))
    if (
        packet.run_id != run_id
        or packet.kind != expected_kind
        or packet.packet_id != expected_id
        or packet.parent_packet_ids != expected_parent_ids
        or len(packet.evidence_refs) != 1
    ):
        raise ValueError("immutable work packet lineage is invalid")
    expected_ref = _packet_reference(packet, packet_digest=digest)
    if dict(supplied) != expected_ref:
        raise ValueError("decision packet reference does not match durable packet")
    return expected_ref


def _validated_state_refs(
    state: Mapping[str, Any],
    *,
    kind: str,
    run_id: str,
    run_started_at: dt.datetime,
    ledger: DecisionLedger,
    ledger_root: Path,
    evidence_root: Path,
) -> tuple[list[dict[str, Any]], bool]:
    raw_refs = state.get("decision_packet_refs")
    if not isinstance(raw_refs, list):
        raise ValueError("decision_packet_refs must be a list")
    current_index = _KIND_ORDER.index(kind)
    prior_kinds = _KIND_ORDER[:current_index]
    if len(raw_refs) not in (len(prior_kinds), len(prior_kinds) + 1):
        raise ValueError("decision_packet_refs is not the exact prior prefix")
    supplied_kinds = [
        _require_ref_shape(reference)["kind"]
        for reference in raw_refs
    ]
    allowed_kinds = list(prior_kinds)
    has_current = len(raw_refs) == len(prior_kinds) + 1
    if has_current:
        allowed_kinds.append(kind)
    if supplied_kinds != allowed_kinds:
        raise ValueError("decision_packet_refs is out of order or contains extras")

    try:
        events = ledger.verify(evidence_root=evidence_root)
    except LedgerCorruptionError:
        raise
    validated = []
    for reference, reference_kind in zip(raw_refs, allowed_kinds, strict=True):
        parent_kind = _PARENT_KIND[reference_kind]
        expected_parents = (
            ()
            if parent_kind is None
            else (build_packet_id(run_id, parent_kind),)
        )
        validated.append(
            _validate_durable_reference(
                reference,
                expected_kind=reference_kind,
                expected_parent_ids=expected_parents,
                run_id=run_id,
                run_started_at=run_started_at,
                ledger_root=ledger_root,
                evidence_root=evidence_root,
                events=events,
            )
        )
    return validated, has_current


def _create_packet_node(
    kind: str,
    ledger_root: str | Path,
    evidence_root: str | Path,
    *,
    clock: Callable[[], dt.datetime] | None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    if kind not in _KIND_ORDER:
        raise ValueError(f"unsupported graph packet kind: {kind}")
    ledger = DecisionLedger(ledger_root)
    stable_ledger_root = ledger.root
    supplied_evidence_root = evidence_root
    current_clock = clock or _utc_now

    def compile_packet(state: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(state, Mapping):
            raise ValueError("graph state must be a mapping")
        run_id = _canonical_text(state.get("run_id"), field="run_id")
        if _GRAPH_RUN_ID.fullmatch(run_id) is None:
            raise ValueError("run_id must be a graph SHA-256 identity")
        run_started_at = _canonical_utc_seconds(
            state.get("run_started_at"),
            field="run_started_at",
        )
        company = _canonical_text(
            state.get("company_of_interest"),
            field="company_of_interest",
        )
        trade_date = _canonical_text(state.get("trade_date"), field="trade_date")
        asset_type = _canonical_text(state.get("asset_type"), field="asset_type")
        stable_evidence_root = _lexical_root(
            supplied_evidence_root,
            label="evidence root",
        )
        validated_refs, has_current = _validated_state_refs(
            state,
            kind=kind,
            run_id=run_id,
            run_started_at=run_started_at,
            ledger=ledger,
            ledger_root=stable_ledger_root,
            evidence_root=stable_evidence_root,
        )
        parent_kind = _PARENT_KIND[kind]
        parent_ids = (
            ()
            if parent_kind is None
            else (build_packet_id(run_id, parent_kind),)
        )
        state_slice = {
            field: _state_value(state, field)
            for field in _STATE_FIELDS[kind]
        }
        evidence_payload = {
            "schema_version": PACKET_HANDOFF_SCHEMA_VERSION,
            "packet_kind": kind,
            "run_id": run_id,
            "run_started_at": state["run_started_at"],
            "company_of_interest": company,
            "trade_date": trade_date,
            "asset_type": asset_type,
            "parent_packet_ids": list(parent_ids),
            "state_slice": state_slice,
            **_AUTHORITY_FIELDS,
        }
        evidence_ref, _ = _publish_evidence(
            evidence_root=stable_evidence_root,
            run_id=run_id,
            kind=kind,
            payload=evidence_payload,
        )
        creation_ref = replace(
            evidence_ref,
            path=str(stable_evidence_root / evidence_ref.path),
        )
        packet = WorkPacket.create(
            kind=kind,
            producer_role=_PRODUCER_ROLES[kind],
            run_id=run_id,
            subject=f"Verified {kind} graph handoff",
            evidence_refs=(creation_ref,),
            parent_packet_ids=parent_ids,
            claims=(
                f"task_boundary={_TASK_BOUNDARIES[kind]}",
                "input_packet_ids="
                + (",".join(parent_ids) if parent_ids else "none"),
                f"output_kind={kind}",
                "verification=DecisionLedger.verify",
            ),
            assumptions=(
                "non_decisions=orders,order_changes,position_sizing,"
                "live_control,risk_overrides",
                "confidence=uncalibrated",
            ),
            recommendation=_RECOMMENDATIONS[kind],
            confidence=0.0,
            expires_at=run_started_at + PACKET_HANDOFF_TTL,
            allowed_effects=_ALLOWED_EFFECTS[kind],
            now=run_started_at,
        )
        packet = replace(packet, evidence_refs=(evidence_ref,))
        admission_time = _clock_value(current_clock)
        packet_path = ledger.record(
            packet,
            evidence_root=stable_evidence_root,
            now=admission_time,
        )
        expected_packet_path = stable_ledger_root / "packets" / (
            f"{packet.packet_id}.json"
        )
        if packet_path != expected_packet_path:
            raise ValueError("decision ledger returned an unexpected packet path")
        packet_digest = packet.payload_digest()
        reference = _packet_reference(packet, packet_digest=packet_digest)
        events = ledger.verify(evidence_root=stable_evidence_root)
        _validate_durable_reference(
            reference,
            expected_kind=kind,
            expected_parent_ids=parent_ids,
            run_id=run_id,
            run_started_at=run_started_at,
            ledger_root=stable_ledger_root,
            evidence_root=stable_evidence_root,
            events=events,
        )
        if has_current:
            if validated_refs[-1] != reference:
                raise ValueError("checkpoint packet reference changed on retry")
            return {"decision_packet_refs": validated_refs}
        return {"decision_packet_refs": [*validated_refs, reference]}

    return compile_packet


def create_research_evidence_packet_node(
    ledger_root: str | Path,
    evidence_root: str | Path,
    *,
    clock: Callable[[], dt.datetime] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return _create_packet_node(
        "research_evidence",
        ledger_root,
        evidence_root,
        clock=clock,
    )


def create_trader_proposal_packet_node(
    ledger_root: str | Path,
    evidence_root: str | Path,
    *,
    clock: Callable[[], dt.datetime] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return _create_packet_node(
        "trader_proposal",
        ledger_root,
        evidence_root,
        clock=clock,
    )


def create_portfolio_decision_packet_node(
    ledger_root: str | Path,
    evidence_root: str | Path,
    *,
    clock: Callable[[], dt.datetime] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return _create_packet_node(
        "portfolio_decision",
        ledger_root,
        evidence_root,
        clock=clock,
    )
