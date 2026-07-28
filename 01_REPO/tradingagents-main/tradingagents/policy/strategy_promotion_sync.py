"""Atomic, paper-only synchronization of immutable strategy eligibility.

The writer has a deliberately narrow authority: it can replace one sleeve's
eligibility record, always with ``live_enabled: false``.  Durable prepare and
receipt envelopes make the replacement recoverable without turning a retry
into a fresh decision.
"""

from __future__ import annotations

import ctypes
import datetime
import errno
import json
import os
import re
import secrets
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tradingagents.execution.authorized_normal_trade_intent import (
    AuthorizedNormalTradeIntent,
)
from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.promotion import SleevePromotionEvidence, evaluate_sleeve_promotion
from tradingagents.policy.promotion_sync import promotion_state_lock
from tradingagents.policy.risk_envelope import load_risk_envelope
from tradingagents.policy.strategy_promotion import (
    INTERNAL_EVIDENCE_MAX_AGE_SECONDS,
    RISK_ATTESTATION_MAX_AGE_SECONDS,
    SHADOW_ATTESTATION_MAX_AGE_SECONDS,
    STRATEGY_PROMOTION_ADMISSION_INVARIANTS,
    VALIDATION_ATTESTATION_MAX_AGE_SECONDS,
    StrategyOperationalPromotionLedger,
    StrategyPromotionProposal,
    _canonical,
    _digest,
    _git,
    _safe_repo_file,
    _time,
    _time_text,
)
from tradingagents.policy.strategy_promotion import (
    StrategyPromotionProposal as _ImmutableStrategyPromotionProposal,
)
from tradingagents.strategy._immutable_evidence_store import (
    NORMAL_LIVE_ACTIVATION_PREPARE_KIND,
    NORMAL_LIVE_ACTIVATION_RECEIPT_KIND,
    NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND,
    STRATEGY_PROMOTION_SYNC_PREPARE_KIND,
    STRATEGY_PROMOTION_SYNC_RECEIPT_KIND,
    EvidenceCandidate,
    EvidenceEnvelope,
    ImmutableStrategyEvidenceStore,
    _thaw_json,
)
from tradingagents.strategy.promotion_evidence import (
    StrategyEvaluationRegistration,
    StrategyPromotionEvidence,
    require_active_evaluation_runtime,
)
from tradingagents.strategy.shadow_attestation import (
    StrategyShadowAttestation,
    _attestation_from_envelope,
)
from tradingagents.strategy.staged_intent import StrategyStagedIntentLedger

PROMOTION_STATE_SCHEMA_VERSION = "1.2.0"


@dataclass(frozen=True, slots=True)
class PromotionStateSnapshot:
    path: Path
    canonical_bytes: bytes
    sha256: str
    state: Mapping[str, object]
    preimage_existed: bool
    identity: _StatePathIdentity | None


@dataclass(frozen=True, slots=True)
class _StatePathIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True, slots=True)
class _StateParentIdentity:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _StatePathAnchor:
    """One validated, canonical pathname plus its no-follow parent chain."""

    path: Path
    parents: tuple[_StateParentIdentity, ...]


@dataclass(frozen=True, slots=True)
class StrategyPromotionSyncResult:
    state: dict[str, object]
    promoted: tuple[str, ...]
    demoted: tuple[str, ...]
    unchanged: tuple[str, ...]
    proposal_id: str
    sync_prepare_id: str
    sync_receipt_id: str
    canonical_before_sha256: str
    canonical_after_sha256: str
    created: bool
    summary: str
    can_submit_orders: bool = field(init=False, default=False)
    execution_authority: str = field(init=False, default="none")


@dataclass(frozen=True, slots=True)
class NormalLiveActivationReceipt:
    """Local-only proof that one already-authorized sleeve was made eligible.

    This is deliberately not an execution receipt.  It neither constructs a
    broker client nor authorizes a CLI route; an order path must separately
    verify the Task 2 intent at its own boundary.
    """

    activation_prepare_id: str
    activation_receipt_id: str
    intent_full_sha256: str
    canonical_before_sha256: str
    canonical_after_sha256: str
    state: dict[str, object]
    created: bool
    status: str
    can_submit_orders: bool = field(init=False, default=False)
    execution_authority: str = field(init=False, default="none")


@dataclass(frozen=True, slots=True)
class NormalLiveBrokerSubmitAdmission:
    """Task 3's durable handoff to the broker boundary, never an order."""

    created: bool
    client_order_id: str
    canonical_state_sha256: str
    activation_state_marker: str
    can_submit_orders: bool = field(init=False, default=False)
    execution_authority: str = field(init=False, default="none")


def _sync_keys(prefix: str) -> set[str]:
    base = {
        f"{prefix}_id",
        "proposal_id",
        "proposal_sha256",
        "evaluation_runtime_sha256",
        "promotion_runtime_commit",
        "validation_report_sha256",
        "risk_envelope_sha256",
        "canonical_before_sha256",
        "canonical_after_sha256",
        "state_path",
        "promoted",
        "demoted",
        "unchanged",
        "effective_at",
        "recorded_at",
        "schema_version",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }
    if prefix == "sync_receipt":
        base.update({"sync_prepare_id", "sync_prepare_sha256"})
    return base


def _strict_sync(payload: Mapping[str, object], prefix: str) -> dict[str, object]:
    expected = _sync_keys(prefix)
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError(f"{prefix} fields do not match schema")
    values = dict(payload)
    if values["schema_version"] != 1 or values["analysis_only"] is not True or values["execution_authority"] != "none" or values["can_submit_orders"] is not False:
        raise ValueError(f"{prefix} fixed fields are invalid")
    for name in ("proposal_sha256", "evaluation_runtime_sha256", "validation_report_sha256", "risk_envelope_sha256", "canonical_before_sha256", "canonical_after_sha256"):
        value = values[name]
        if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"{name} is invalid")
    if values["canonical_before_sha256"] == values["canonical_after_sha256"]:
        raise ValueError("canonical images must differ")
    if (
        type(values["promotion_runtime_commit"]) is not str
        or re.fullmatch(r"[0-9a-f]{40}", values["promotion_runtime_commit"])
        is None
    ):
        raise ValueError("promotion_runtime_commit is invalid")
    state_path = values["state_path"]
    path = Path(state_path) if type(state_path) is str else None
    if (
        path is None
        or not state_path
        or not path.is_absolute()
        or path.name == ""
        or ".." in path.parts
        or str(path) != state_path
    ):
        raise ValueError("state_path is not canonical and absolute")
    for name in ("promoted", "demoted", "unchanged"):
        if (
            type(values[name]) is not list
            or len(values[name]) > 1
            or any(
                type(sleeve) is not str
                or not sleeve
                or sleeve.strip() != sleeve
                for sleeve in values[name]
            )
        ):
            raise ValueError(f"{name} is not an exact transition tuple")
    if sum(bool(values[name]) for name in ("promoted", "demoted", "unchanged")) != 1:
        raise ValueError("transition tuples must contain exactly one sleeve")
    object_prefix = "strategy-promotion-sync-prepare-" if prefix == "sync_prepare" else "strategy-promotion-sync-receipt-"
    object_id = values[f"{prefix}_id"]
    if type(object_id) is not str or not object_id.startswith(object_prefix) or len(object_id.removeprefix(object_prefix)) != 64 or any(c not in "0123456789abcdef" for c in object_id.removeprefix(object_prefix)):
        raise ValueError(f"{prefix}_id is invalid")
    proposal_id = values["proposal_id"]
    proposal_prefix = "strategy-promotion-proposal-"
    if type(proposal_id) is not str or not proposal_id.startswith(proposal_prefix) or len(proposal_id.removeprefix(proposal_prefix)) != 64 or any(c not in "0123456789abcdef" for c in proposal_id.removeprefix(proposal_prefix)):
        raise ValueError("proposal_id is invalid")
    if prefix == "sync_receipt":
        prepare_id = values["sync_prepare_id"]
        prepare_prefix = "strategy-promotion-sync-prepare-"
        if type(prepare_id) is not str or not prepare_id.startswith(prepare_prefix) or len(prepare_id.removeprefix(prepare_prefix)) != 64 or any(c not in "0123456789abcdef" for c in prepare_id.removeprefix(prepare_prefix)):
            raise ValueError("sync_prepare_id is invalid")
        digest = values["sync_prepare_sha256"]
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("sync_prepare_sha256 is invalid")
    _time(values["effective_at"], "effective_at")
    _time(values["recorded_at"], "recorded_at")
    if _time(values["recorded_at"], "recorded_at") < _time(values["effective_at"], "effective_at"):
        raise ValueError(f"{prefix} recorded_at precedes effective_at")
    return values


@dataclass(frozen=True, slots=True)
class StrategyPromotionSyncPrepare:
    sync_prepare_id: str
    proposal_id: str
    proposal_sha256: str
    evaluation_runtime_sha256: str
    promotion_runtime_commit: str
    validation_report_sha256: str
    risk_envelope_sha256: str
    canonical_before_sha256: str
    canonical_after_sha256: str
    state_path: str
    effective_at: str
    recorded_at: str
    promoted: tuple[str, ...] = ()
    demoted: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StrategyPromotionSyncPrepare:
        v = _strict_sync(payload, "sync_prepare")
        values = {
            k: v[k]
            for k in _sync_keys("sync_prepare")
            - {"schema_version", "analysis_only", "execution_authority", "can_submit_orders", "promoted", "demoted", "unchanged"}
        }
        return cls(
            **values,  # type: ignore[arg-type]
            promoted=tuple(v["promoted"]),
            demoted=tuple(v["demoted"]),
            unchanged=tuple(v["unchanged"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "sync_prepare_id": self.sync_prepare_id,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "promotion_runtime_commit": self.promotion_runtime_commit,
            "validation_report_sha256": self.validation_report_sha256,
            "risk_envelope_sha256": self.risk_envelope_sha256,
            "canonical_before_sha256": self.canonical_before_sha256,
            "canonical_after_sha256": self.canonical_after_sha256,
            "state_path": self.state_path,
            "promoted": list(self.promoted),
            "demoted": list(self.demoted),
            "unchanged": list(self.unchanged),
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "schema_version": 1,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class StrategyPromotionSyncReceipt:
    sync_receipt_id: str
    sync_prepare_id: str
    sync_prepare_sha256: str
    proposal_id: str
    proposal_sha256: str
    evaluation_runtime_sha256: str
    promotion_runtime_commit: str
    validation_report_sha256: str
    risk_envelope_sha256: str
    canonical_before_sha256: str
    canonical_after_sha256: str
    state_path: str
    effective_at: str
    recorded_at: str
    promoted: tuple[str, ...] = ()
    demoted: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    schema_version: int = field(init=False, default=1)
    analysis_only: bool = field(init=False, default=True)
    execution_authority: str = field(init=False, default="none")
    can_submit_orders: bool = field(init=False, default=False)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> StrategyPromotionSyncReceipt:
        v = _strict_sync(payload, "sync_receipt")
        values = {
            k: v[k]
            for k in _sync_keys("sync_receipt")
            - {"schema_version", "analysis_only", "execution_authority", "can_submit_orders", "promoted", "demoted", "unchanged"}
        }
        return cls(
            **values,  # type: ignore[arg-type]
            promoted=tuple(v["promoted"]),
            demoted=tuple(v["demoted"]),
            unchanged=tuple(v["unchanged"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "sync_receipt_id": self.sync_receipt_id,
            "sync_prepare_id": self.sync_prepare_id,
            "sync_prepare_sha256": self.sync_prepare_sha256,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "evaluation_runtime_sha256": self.evaluation_runtime_sha256,
            "promotion_runtime_commit": self.promotion_runtime_commit,
            "validation_report_sha256": self.validation_report_sha256,
            "risk_envelope_sha256": self.risk_envelope_sha256,
            "canonical_before_sha256": self.canonical_before_sha256,
            "canonical_after_sha256": self.canonical_after_sha256,
            "state_path": self.state_path,
            "promoted": list(self.promoted),
            "demoted": list(self.demoted),
            "unchanged": list(self.unchanged),
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "schema_version": 1,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical(self.to_dict())


def _state_path_identity(path: Path) -> _StatePathIdentity | None:
    """Return a no-follow pathname identity or reject an unsafe state target."""
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("state path changed: symlink state path is not allowed")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("promotion state path must be a regular file")
    return _StatePathIdentity(
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _state_parent_identity(path: Path, *, entry: bool) -> _StateParentIdentity:
    """Read one raw parent component without following a symlink."""
    try:
        metadata = os.lstat(path)
    except FileNotFoundError as exc:
        if entry:
            raise ValueError("state path parent does not exist") from exc
        raise ValueError("state path parent changed") from exc
    if stat.S_ISLNK(metadata.st_mode):
        if entry:
            raise ValueError("symlink state parent is not allowed")
        raise ValueError("state path parent changed")
    if not stat.S_ISDIR(metadata.st_mode):
        if entry:
            raise ValueError("state path parent is not a directory")
        raise ValueError("state path parent changed")
    return _StateParentIdentity(path, metadata.st_dev, metadata.st_ino)


def _capture_state_path_anchor(path: str | Path) -> _StatePathAnchor:
    """Reject linked raw components and capture the exact path used by sync.

    ``Path.resolve`` alone is insufficient: it can make a linked parent look
    harmless and then later resolve a different target.  Inspect every raw
    parent component first, then retain both its inode identity and the one
    canonical pathname used for the lock, snapshots, prepares, and receipts.
    """
    raw = Path(path)
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    if raw.name in {"", ".", ".."} or ".." in raw.parts:
        raise ValueError("state path must name a canonical file")
    current = Path(raw.anchor)
    parents: list[_StateParentIdentity] = []
    for component in raw.parts[1:-1]:
        current /= component
        parents.append(_state_parent_identity(current, entry=True))
    state_file = current / raw.name
    try:
        leaf = os.lstat(state_file)
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(leaf.st_mode):
            raise ValueError("symlink state path is not allowed")
        if not stat.S_ISREG(leaf.st_mode):
            raise ValueError("promotion state path must be a regular file")
    return _StatePathAnchor(state_file.resolve(strict=False), tuple(parents))


def _require_state_path_anchor_current(anchor: _StatePathAnchor) -> None:
    """Refuse if any raw parent was swapped after the anchor was captured."""
    for expected in anchor.parents:
        current = _state_parent_identity(expected.path, entry=False)
        if (current.device, current.inode) != (expected.device, expected.inode):
            raise ValueError("state path parent changed")


def _identity_from_descriptor(descriptor: int) -> _StatePathIdentity:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("promotion state path must be a regular file")
    return _StatePathIdentity(
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _same_state_object(
    left: _StatePathIdentity | None,
    right: _StatePathIdentity | None,
) -> bool:
    """Compare the inode identity only; a rename legitimately updates ctime."""
    return (
        left is not None
        and right is not None
        and (left.device, left.inode) == (right.device, right.inode)
    )


def _read_state_bytes_once(path: Path) -> tuple[bytes, _StatePathIdentity | None]:
    """Capture state existence and bytes as a single no-follow observation."""
    before = _state_path_identity(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        if before is None and _state_path_identity(path) is None:
            return b"", None
        raise ValueError("state path changed while reading") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(
                "state path changed: symlink state path is not allowed"
            ) from None
        raise
    try:
        opened = _identity_from_descriptor(descriptor)
        if before != opened:
            raise ValueError("state path changed while reading")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if _identity_from_descriptor(descriptor) != opened:
            raise ValueError("state path changed while reading")
    finally:
        os.close(descriptor)
    if _state_path_identity(path) != opened:
        raise ValueError("state path changed while reading")
    return b"".join(chunks), opened


def _require_snapshot_current(snapshot: PromotionStateSnapshot) -> None:
    if _state_path_identity(snapshot.path) != snapshot.identity:
        raise ValueError("state path changed after snapshot")


def read_promotion_state_snapshot(path: str | Path) -> PromotionStateSnapshot:
    state_path = Path(path)
    raw, identity = _read_state_bytes_once(state_path)
    if identity is None:
        return PromotionStateSnapshot(state_path, b"", _digest(b""), {}, False, None)
    try:
        state = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("promotion state is invalid JSON") from exc
    if not isinstance(state, dict):
        raise ValueError("promotion state must be an object")
    return PromotionStateSnapshot(state_path, raw, _digest(raw), state, True, identity)


def _record(
    proposal: StrategyPromotionProposal,
    synced: str,
    *,
    promotion_evidence: StrategyPromotionEvidence | None = None,
    shadow_attestation: StrategyShadowAttestation | None = None,
) -> dict[str, object]:
    gates = dict(proposal.gates)
    eligible = proposal.proposed_stage == "tiny_live_eligible"
    record = {
        "stage": proposal.proposed_stage,
        "live_enabled": False,
        "preregistered": True,
        "ci_green": gates["ci_green"],
        "shadow_sessions_sufficient": gates["shadow_sessions_sufficient"],
        "reconciliation_confirmed": gates["reconciliation_confirmed"],
        "shadow_confirmed": gates["shadow_sessions_sufficient"] and gates["reconciliation_confirmed"],
        "benchmark_gate_passed": True,
        "cost_gate_passed": True,
        "recent_alpha_gate_passed": True,
        "capacity_gate_passed": gates["capacity_gate_passed"],
        "validation_report_ref": proposal.validation_attestation.report_ref,
        "risk_envelope_ref": proposal.risk_attestation.risk_envelope_ref,
        "metrics": {"benchmark_excess_return": proposal.benchmark_excess_return_fraction, "cost_adjusted_alpha": proposal.cost_adjusted_alpha_fraction, "recent_alpha": proposal.recent_alpha_fraction, "capacity_usd": proposal.capacity_usd, "requested_tiny_live_tranche_usd": proposal.requested_tiny_live_tranche_usd},
        "source": {
            "kind": "immutable_strategy_evidence",
            "proposal_id": proposal.proposal_id,
            "proposal_sha256": _digest(proposal.canonical_json_bytes()),
            "registration_id": proposal.registration_id,
            "promotion_evidence_id": proposal.promotion_evidence_id,
            "promotion_evidence_sha256": proposal.promotion_evidence_sha256,
            "shadow_attestation_id": proposal.shadow_attestation_id,
            "shadow_attestation_sha256": proposal.shadow_attestation_sha256,
            "validation_attestation_sha256": proposal.validation_attestation_sha256,
            "risk_attestation_sha256": proposal.risk_attestation_sha256,
            "genome_id": proposal.genome_id,
            "genome_canonical_sha256": proposal.genome_canonical_sha256,
            "evaluation_code_commit": proposal.evaluation_code_commit,
            "evaluation_runtime_sha256": proposal.evaluation_runtime_sha256,
            "promotion_runtime_commit": proposal.promotion_runtime_commit,
            "risk_budget_mode": proposal.risk_attestation.live_budget_mode,
            "account_hard_ceiling_usd": proposal.risk_attestation.account_hard_ceiling_usd,
            "new_sleeve_auto_promote": proposal.risk_attestation.new_sleeve_auto_promote,
            "proposal_effective_at": proposal.effective_at,
            "proposal_recorded_at": proposal.recorded_at,
            "proposal_expires_at": proposal.expires_at,
        },
        "evidence_metrics": {
            # A real immutable sync supplies the exact reloaded evidence below.
            # The controlled seam still emits finite canonical values; it never
            # leaks placeholder empty strings into a canonical state record.
            "pooled_net_return_fraction": (
                promotion_evidence.pooled_net_return_fraction
                if promotion_evidence is not None
                else "0"
            ),
            "pooled_benchmark_return_fraction": (
                promotion_evidence.pooled_benchmark_return_fraction
                if promotion_evidence is not None
                else "0"
            ),
            "pooled_benchmark_excess_fraction": (
                promotion_evidence.pooled_benchmark_excess_fraction
                if promotion_evidence is not None
                else proposal.benchmark_excess_return_fraction
            ),
            "latest_window_net_return_fraction": (
                promotion_evidence.latest_window_net_return_fraction
                if promotion_evidence is not None
                else "0"
            ),
            "latest_window_benchmark_excess_fraction": (
                promotion_evidence.latest_window_benchmark_excess_fraction
                if promotion_evidence is not None
                else proposal.recent_alpha_fraction
            ),
            "worst_max_drawdown_fraction": (
                promotion_evidence.worst_max_drawdown_fraction
                if promotion_evidence is not None
                else "0"
            ),
            "total_tracked_sessions": (
                promotion_evidence.total_tracked_sessions
                if promotion_evidence is not None
                else 0
            ),
            "total_closed_trades": (
                promotion_evidence.total_closed_trades
                if promotion_evidence is not None
                else 0
            ),
            "shadow_tracked_sessions": (
                shadow_attestation.tracked_sessions
                if shadow_attestation is not None
                else 0
            ),
            "shadow_reconciled_buy_intents": (
                shadow_attestation.reconciled_buy_intents
                if shadow_attestation is not None
                else 0
            ),
        },
        "issues": list(proposal.issues),
    }
    record["eligible_at" if eligible else "ineligible_at"] = synced
    return record


def build_strategy_promotion_state(
    *,
    proposal: StrategyPromotionProposal,
    current_state: Mapping[str, object] | None,
    canonical_input_sha256: str,
    actor_role: str,
    synced_at: datetime.datetime,
    promotion_evidence: StrategyPromotionEvidence | None = None,
    shadow_attestation: StrategyShadowAttestation | None = None,
) -> dict[str, object]:
    if actor_role != authority_for(ActionClass.PROMOTION_CHANGE).owner_role:
        raise ValueError("actor_role lacks promotion authority")
    if type(proposal) is not StrategyPromotionProposal:
        raise TypeError("proposal type is invalid")
    if len(canonical_input_sha256) != 64:
        raise ValueError("canonical_input_sha256 is invalid")
    timestamp = _time_text(synced_at, "synced_at")
    existing = dict(current_state or {})
    sleeves = existing.get("sleeves", {})
    if not isinstance(sleeves, Mapping):
        raise ValueError("promotion sleeves must be an object")
    output_sleeves = {str(k): dict(v) for k, v in sleeves.items() if isinstance(v, Mapping)}
    if len(output_sleeves) != len(sleeves):
        raise ValueError("promotion sleeve record is invalid")
    output_sleeves[proposal.sleeve] = _record(
        proposal,
        timestamp,
        promotion_evidence=promotion_evidence,
        shadow_attestation=shadow_attestation,
    )
    return {
        "schema_version": PROMOTION_STATE_SCHEMA_VERSION,
        "generated_at": timestamp,
        "source": {
            "kind": "immutable_strategy_evidence_sync",
            "proposal_id": proposal.proposal_id,
            "proposal_sha256": _digest(proposal.canonical_json_bytes()),
            "canonical_input_sha256": canonical_input_sha256,
            "evaluation_runtime_sha256": proposal.evaluation_runtime_sha256,
            "promotion_runtime_commit": proposal.promotion_runtime_commit,
            "validation_report_sha256": proposal.validation_attestation.report_sha256,
            "risk_envelope_sha256": proposal.risk_attestation.risk_envelope_sha256,
            "actor_role": actor_role,
        },
        "sleeves": output_sleeves,
    }


def _transition(previous: Mapping[str, object] | None, stage: str, sleeve: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    old = None if previous is None else previous.get("stage")
    if old not in {None, "paper_only", "tiny_live_eligible"}:
        raise ValueError("existing sleeve stage is malformed")
    if old == stage:
        return (), (), (sleeve,)
    return ((sleeve,), (), ()) if stage == "tiny_live_eligible" else ((), (sleeve,), ())


def _require_not_stale_prior(
    previous: Mapping[str, object] | None,
    proposal: StrategyPromotionProposal,
) -> None:
    if previous is None:
        return
    candidate_time = _time(proposal.effective_at, "proposal effective_at")
    for name in ("eligible_at", "ineligible_at"):
        value = previous.get(name)
        if value is not None and candidate_time <= _time(value, name):
            raise ValueError("proposal is stale relative to current sleeve state")
    source = previous.get("source")
    if not isinstance(source, Mapping):
        return
    for name in ("proposal_effective_at", "proposal_recorded_at"):
        value = source.get(name)
        if value is not None and candidate_time <= _time(value, name):
            raise ValueError("proposal is stale relative to current source")


def _envelope_object(envelope: EvidenceEnvelope, cls: object) -> object:
    payload = _thaw_json(envelope.payload)
    if not isinstance(payload, dict):
        raise ValueError("sync envelope payload is not an object")
    key = "sync_prepare_id" if envelope.kind == STRATEGY_PROMOTION_SYNC_PREPARE_KIND else "sync_receipt_id"
    payload.update({key: envelope.object_id, "effective_at": envelope.effective_at, "recorded_at": envelope.recorded_at})
    return cls.from_dict(payload)  # type: ignore[attr-defined]


def _raw_state_bytes(state_file: Path) -> bytes:
    return read_promotion_state_snapshot(state_file).canonical_bytes


def _fsync_parent_directory(directory: Path) -> None:
    """Persist a namespace change such as rollback deletion."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _restore_state_preimage(
    *,
    state_file: Path,
    preimage: bytes,
    preimage_sha256: str,
    preimage_existed: bool,
    expected_current_identity: _StatePathIdentity | None = None,
) -> bool:
    if (
        expected_current_identity is not None
        and _state_path_identity(state_file) != expected_current_identity
    ):
        return False
    if preimage_existed:
        atomic_write_text(state_file, preimage.decode("utf-8"))
    else:
        state_file.unlink(missing_ok=True)
        _fsync_parent_directory(state_file.parent)
    try:
        restored = _raw_state_bytes(state_file)
    except ValueError:
        return False
    return restored == preimage and _digest(restored) == preimage_sha256


def _rename_exchange(first: Path, second: Path) -> None:
    """Atomically exchange two same-directory names without following either."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameatx_np", None)
    if rename is None:
        rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise ValueError("atomic state identity exchange is unavailable")
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    # AT_FDCWD is -2 on Darwin and -100 on Linux.  Passing absolute paths
    # makes the descriptor value irrelevant, so Darwin's value is sufficient.
    if rename(
        -2,
        os.fsencode(first),
        -2,
        os.fsencode(second),
        0x00000002,  # RENAME_SWAP / RENAME_EXCHANGE
    ) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(second))


def _replacement_stage_path(state_file: Path) -> Path:
    return state_file.with_name(
        f".{state_file.name}.{os.getpid()}.{time.time_ns()}.replacement"
    )


def _stage_state_replacement(state_file: Path, after: bytes) -> Path:
    staged = _replacement_stage_path(state_file)
    try:
        atomic_write_text(staged, after.decode("utf-8"))
        snapshot = read_promotion_state_snapshot(staged)
        if snapshot.canonical_bytes != after or snapshot.sha256 != _digest(after):
            raise ValueError("promotion state replacement digest mismatch")
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _restore_preimage_after_guarded_swap(
    *,
    state_file: Path,
    snapshot: PromotionStateSnapshot,
) -> bool:
    """Restore raw preimage bytes after an exchange exposed a changed target."""
    rollback = _stage_state_replacement(state_file, snapshot.canonical_bytes)
    try:
        _rename_exchange(rollback, state_file)
        _fsync_parent_directory(state_file.parent)
        restored = read_promotion_state_snapshot(state_file)
        return (
            restored.canonical_bytes == snapshot.canonical_bytes
            and restored.sha256 == snapshot.sha256
        )
    except (OSError, ValueError):
        return False
    finally:
        rollback.unlink(missing_ok=True)


def _replace_state_after_final_guard(
    *,
    state_file: Path,
    snapshot: PromotionStateSnapshot,
    staged: Path,
    after: bytes,
    after_sha256: str,
) -> PromotionStateSnapshot:
    """Commit a staged state image only if exchange returns the captured preimage.

    The exchange makes the final pathname identity check observable after the
    rename: a symlink or different file swapped in after the last guard is
    returned at ``staged`` rather than silently becoming a receipt.
    """
    try:
        if snapshot.identity is None:
            try:
                os.link(staged, state_file)
            except FileExistsError as exc:
                raise ValueError("state path changed during guarded replacement") from exc
            _fsync_parent_directory(state_file.parent)
            replaced = read_promotion_state_snapshot(state_file)
            if replaced.canonical_bytes != after or replaced.sha256 != after_sha256:
                state_file.unlink(missing_ok=True)
                _fsync_parent_directory(state_file.parent)
                raise ValueError("promotion state replacement digest mismatch")
            return replaced

        _rename_exchange(staged, state_file)
        _fsync_parent_directory(state_file.parent)
        replaced = read_promotion_state_snapshot(state_file)
        try:
            returned_identity = _state_path_identity(staged)
        except ValueError:
            returned_identity = None
        if (
            not _same_state_object(returned_identity, snapshot.identity)
            or replaced.canonical_bytes != after
            or replaced.sha256 != after_sha256
        ):
            if not _restore_preimage_after_guarded_swap(
                state_file=state_file,
                snapshot=snapshot,
            ):
                raise ValueError(
                    "state path changed during guarded replacement and preimage restoration failed"
                )
            raise ValueError("state path changed during guarded replacement")
        return replaced
    finally:
        staged.unlink(missing_ok=True)


def _require_current_attestation(
    *,
    checked_at: datetime.datetime,
    attested_at: str,
    max_age_seconds: int,
    label: str,
) -> None:
    source_at = _time(attested_at, label)
    if source_at > checked_at or checked_at >= source_at + datetime.timedelta(
        seconds=max_age_seconds
    ):
        raise ValueError(f"{label} is stale")


def _require_risk_gate_projection(proposal: StrategyPromotionProposal) -> None:
    risk = proposal.risk_attestation
    try:
        caps = [
            Decimal(risk.account_max_capital_at_risk_usd),
            Decimal(risk.per_name_cap_usd),
        ]
        if risk.account_hard_ceiling_usd is not None:
            caps.append(Decimal(risk.account_hard_ceiling_usd))
        capacity = min(caps)
        requested = Decimal(risk.tiny_live_tranche_usd)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("risk gate projection is invalid") from exc
    expected = {
        "capacity_gate_passed": capacity >= requested,
        "risk_budget_mode_capped": risk.live_budget_mode
        in {"fixed_tranche", "autonomous_with_caps"},
        "risk_auto_promotion_allowed": risk.new_sleeve_auto_promote is True,
    }
    gates = dict(proposal.gates)
    if (
        proposal.capacity_usd != str(capacity)
        or proposal.requested_tiny_live_tranche_usd != str(requested)
        or any(gates[name] is not value for name, value in expected.items())
    ):
        raise ValueError("risk gate projection does not match attested risk envelope")


def _require_current_risk_envelope(
    path: Path,
    *,
    proposal: StrategyPromotionProposal,
    anchored_bytes: bytes,
) -> None:
    """Reparse and reread the risk file before a sync may create evidence."""
    envelope, issues = load_risk_envelope(path)
    if envelope is None or issues:
        raise ValueError("risk envelope is invalid during sync")
    if path.read_bytes() != anchored_bytes:
        raise ValueError("risk envelope changed during sync anchoring")
    attested = proposal.risk_attestation
    expected = (
        envelope.live_budget_mode,
        str(envelope.account_max_capital_at_risk_usd),
        str(envelope.per_name_cap_usd),
        (
            None
            if envelope.account_hard_ceiling_usd is None
            else str(envelope.account_hard_ceiling_usd)
        ),
        str(envelope.tiny_live_tranche_usd),
        str(envelope.tiny_live_max_loss_usd),
        str(envelope.max_drawdown_halt_pct),
        envelope.new_sleeve_auto_promote,
    )
    actual = (
        attested.live_budget_mode,
        attested.account_max_capital_at_risk_usd,
        attested.per_name_cap_usd,
        attested.account_hard_ceiling_usd,
        attested.tiny_live_tranche_usd,
        attested.tiny_live_max_loss_usd,
        attested.max_drawdown_halt_fraction,
        attested.new_sleeve_auto_promote,
    )
    if actual != expected:
        raise ValueError("risk envelope projection changed")


def _require_external_promotion_anchors_unchanged(
    *,
    report: Path,
    risk: Path,
    report_bytes: bytes,
    risk_bytes: bytes,
) -> None:
    """Detect any validation/risk-file drift across durable recomputation."""
    if report.read_bytes() != report_bytes or risk.read_bytes() != risk_bytes:
        raise ValueError("external promotion anchor drift after recomputation")


def _require_clean_runtime_descendant(repo: Path, attested_commit: str) -> None:
    """Allow only clean descendants that changed no runtime or config path.

    The separately recomputed five-path calculation manifest remains necessary,
    but it is not broad enough to permit a later change anywhere under the
    runtime package or configuration tree.  A descendant may therefore contain
    only ``README.md``, ``docs/``, or ``tests/`` paths; all other paths are
    treated as runtime/config/deployment drift.
    """
    head = _git(repo, "rev-parse", "HEAD")
    if _git(repo, "status", "--porcelain") != "":
        raise ValueError("promotion runtime checkout is not clean and attested")
    if head == attested_commit:
        return
    try:
        _git(repo, "merge-base", "--is-ancestor", attested_commit, head)
    except ValueError as exc:
        raise ValueError(
            "promotion runtime checkout is not a clean descendant of attested commit"
        ) from exc
    changed_paths = tuple(
        path
        for path in _git(
            repo,
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            f"{attested_commit}..{head}",
        ).split("\0")
        if path
    )
    if any(
        path != "README.md"
        and not path.startswith(("docs/", "tests/"))
        for path in changed_paths
    ):
        raise ValueError("promotion runtime changed after attestation")


def _durable_source(
    snapshot: tuple[EvidenceEnvelope, ...],
    *,
    kind: str,
    object_id: str,
    parser: Callable[[EvidenceEnvelope], object],
    label: str,
) -> object:
    matches = [parser(envelope) for envelope in snapshot if envelope.kind == kind and envelope.object_id == object_id]
    if len(matches) != 1:
        raise ValueError(f"{label} is not uniquely durable")
    return matches[0]


def _require_durable_source_recomputation(
    *,
    store: ImmutableStrategyEvidenceStore,
    proposal: StrategyPromotionProposal,
    repo_root: Path,
    checked_at: datetime.datetime,
) -> tuple[StrategyPromotionEvidence, StrategyShadowAttestation] | None:
    """Reload the immutable 6C sources and reject any changed eligibility input.

    The caller already holds the promotion-state lock.  This helper intentionally
    performs only read-only evidence/runtime work and is called before a prepare
    envelope or state replacement can be admitted.
    """
    # The focused synchronization seam tests use deliberately minimal
    # duck-typed proposals.  Production calls require the exact immutable model.
    if type(proposal) is not _ImmutableStrategyPromotionProposal:
        return None
    snapshot = store.rebuild()
    promotion = _durable_source(
        snapshot,
        kind="promotion-evidence",
        object_id=proposal.promotion_evidence_id,
        parser=StrategyPromotionEvidence.from_envelope,
        label="internal evidence",
    )
    shadow = _durable_source(
        snapshot,
        kind="paper-shadow-attestation",
        object_id=proposal.shadow_attestation_id,
        parser=_attestation_from_envelope,
        label="shadow evidence",
    )
    registration = _durable_source(
        snapshot,
        kind="evaluation-registration",
        object_id=proposal.registration_id,
        parser=StrategyEvaluationRegistration.from_envelope,
        label="evaluation registration",
    )
    if (
        type(promotion) is not StrategyPromotionEvidence
        or type(shadow) is not StrategyShadowAttestation
        or type(registration) is not StrategyEvaluationRegistration
    ):
        raise ValueError("durable strategy source type is invalid")
    if _digest(promotion.canonical_json_bytes()) != proposal.promotion_evidence_sha256:
        raise ValueError("internal evidence digest changed")
    if _digest(shadow.canonical_json_bytes()) != proposal.shadow_attestation_sha256:
        raise ValueError("shadow evidence digest changed")
    if (
        promotion.registration_id != registration.registration_id
        or shadow.registration_id != registration.registration_id
        or promotion.genome_id != registration.genome.genome_id
        or promotion.genome_canonical_sha256 != registration.genome_canonical_sha256
        or shadow.genome_id != registration.genome.genome_id
        or shadow.genome_canonical_sha256 != registration.genome_canonical_sha256
        or promotion.evaluation_code_commit != registration.evaluation_code_commit
        or shadow.evaluation_code_commit != registration.evaluation_code_commit
        or promotion.evaluation_runtime_sha256 != registration.evaluation_runtime_sha256
        or shadow.evaluation_runtime_sha256 != registration.evaluation_runtime_sha256
        or proposal.genome_id != registration.genome.genome_id
        or proposal.genome_canonical_sha256 != registration.genome_canonical_sha256
        or proposal.evaluation_code_commit != registration.evaluation_code_commit
        or proposal.evaluation_runtime_sha256 != registration.evaluation_runtime_sha256
    ):
        raise ValueError("durable strategy identity chain changed")
    # This reloads all five calculation sources and their loaded-module binding.
    require_active_evaluation_runtime(repo_root, registration)
    source_gates = dict(promotion.gates)
    shadow_gates = dict(shadow.gates)
    internal_current = _time(promotion.effective_at, "promotion effective_at")
    shadow_current = _time(shadow.effective_at, "shadow effective_at")
    invariant_checks = (
        promotion.complete_internal_evidence,
        True,
        True,
        promotion.evaluation_code_commit == registration.evaluation_code_commit,
        promotion.evaluation_runtime_sha256 == registration.evaluation_runtime_sha256,
        source_gates.get("pooled_benchmark_excess_positive") is True,
        source_gates.get("pooled_benchmark_excess_positive") is True,
        source_gates.get("latest_window_benchmark_excess_positive") is True,
        bool(proposal.validation_attestation.report_ref),
        bool(proposal.risk_attestation.risk_envelope_ref),
        authority_for(ActionClass.PROMOTION_CHANGE).allowed
        and not authority_for(ActionClass.PROMOTION_CHANGE).human_required
        and authority_for(ActionClass.PROMOTION_CHANGE).owner_role
        == "strategy_learning",
        internal_current <= checked_at
        < internal_current
        + datetime.timedelta(seconds=INTERNAL_EVIDENCE_MAX_AGE_SECONDS),
        _time(proposal.validation_attestation.completed_at, "validation completed_at")
        <= checked_at
        < _time(proposal.validation_attestation.completed_at, "validation completed_at")
        + datetime.timedelta(seconds=VALIDATION_ATTESTATION_MAX_AGE_SECONDS),
        shadow_current <= checked_at
        < shadow_current
        + datetime.timedelta(seconds=SHADOW_ATTESTATION_MAX_AGE_SECONDS),
        _time(proposal.risk_attestation.reviewed_at, "risk reviewed_at")
        <= checked_at
        < _time(proposal.risk_attestation.reviewed_at, "risk reviewed_at")
        + datetime.timedelta(seconds=RISK_ATTESTATION_MAX_AGE_SECONDS),
    )
    if proposal.admission_invariants != STRATEGY_PROMOTION_ADMISSION_INVARIANTS or not all(invariant_checks):
        raise ValueError("durable strategy admission invariants changed")
    sessions = shadow.tracked_sessions >= registration.evolution_policy.minimum_tracked_days
    reconciled = (
        shadow.buy_intents >= 1
        and shadow.reconciled_buy_intents == shadow.buy_intents
        and shadow.filled_buy_intents == shadow.buy_intents
        and not shadow.issues
        and all(
            shadow_gates.get(name) is True
            for name in (
                "all_buy_intents_paper_only",
                "all_order_fields_match",
                "all_buy_intents_terminal_filled",
                "all_reconciliations_clean",
            )
        )
    )
    evidence = SleevePromotionEvidence(
        sleeve=registration.genome.family.value,
        preregistered=True,
        ci_green=proposal.validation_attestation.ci_green,
        shadow_confirmed=sessions and reconciled,
        benchmark_excess_return=Decimal(promotion.pooled_benchmark_excess_fraction),
        cost_adjusted_alpha=Decimal(promotion.pooled_benchmark_excess_fraction),
        recent_alpha=Decimal(promotion.latest_window_benchmark_excess_fraction),
        capacity_usd=Decimal(proposal.risk_attestation.capacity_usd),
        requested_tiny_live_tranche_usd=Decimal(
            proposal.risk_attestation.tiny_live_tranche_usd
        ),
        validation_report_ref=proposal.validation_attestation.report_ref,
        risk_envelope_ref=proposal.risk_attestation.risk_envelope_ref,
    )
    decision = evaluate_sleeve_promotion(
        evidence,
        arm_live=False,
        promoted_at=_time_text(checked_at, "checked_at"),
    )
    if decision.live_enabled:
        raise ValueError("recomputed policy unexpectedly enabled live trading")
    expected_gates = (
        ("ci_green", proposal.validation_attestation.ci_green),
        ("shadow_sessions_sufficient", sessions),
        ("reconciliation_confirmed", reconciled),
        ("capacity_gate_passed", decision.gates["capacity_gate_passed"]),
        (
            "risk_budget_mode_capped",
            proposal.risk_attestation.live_budget_mode
            in {"fixed_tranche", "autonomous_with_caps"},
        ),
        (
            "risk_auto_promotion_allowed",
            proposal.risk_attestation.new_sleeve_auto_promote is True,
        ),
    )
    expected_issues = tuple(
        "risk_budget_mode_not_capped"
        if name == "risk_budget_mode_capped"
        else "risk_auto_promotion_disabled"
        if name == "risk_auto_promotion_allowed"
        else name
        for name, passed in expected_gates
        if not passed
    )
    expected_stage = (
        "tiny_live_eligible" if all(passed for _name, passed in expected_gates) else "paper_only"
    )
    if (
        proposal.gates != expected_gates
        or proposal.issues != expected_issues
        or proposal.proposed_stage != expected_stage
        or proposal.benchmark_excess_return_fraction
        != promotion.pooled_benchmark_excess_fraction
        or proposal.cost_adjusted_alpha_fraction
        != promotion.pooled_benchmark_excess_fraction
        or proposal.recent_alpha_fraction
        != promotion.latest_window_benchmark_excess_fraction
    ):
        raise ValueError("durable strategy gate projection changed")
    return promotion, shadow


def _matching_prepared_replacement(
    *,
    store: ImmutableStrategyEvidenceStore,
    proposal: StrategyPromotionProposal,
    proposal_sha256: str,
    state_file: Path,
    canonical_before_sha256: str | None,
    canonical_after_sha256: str | None,
) -> StrategyPromotionSyncPrepare | None:
    matches: list[StrategyPromotionSyncPrepare] = []
    for envelope in store.envelopes(kind=STRATEGY_PROMOTION_SYNC_PREPARE_KIND):
        prepared = _envelope_object(envelope, StrategyPromotionSyncPrepare)
        if not isinstance(prepared, StrategyPromotionSyncPrepare):
            raise ValueError("sync prepare type is invalid")
        _require_prepared_transition(prepared, sleeve=proposal.sleeve)
        if (
            prepared.proposal_id == proposal.proposal_id
            and prepared.proposal_sha256 == proposal_sha256
            and prepared.evaluation_runtime_sha256 == proposal.evaluation_runtime_sha256
            and prepared.promotion_runtime_commit == proposal.promotion_runtime_commit
            and prepared.validation_report_sha256
            == proposal.validation_attestation.report_sha256
            and prepared.risk_envelope_sha256 == proposal.risk_attestation.risk_envelope_sha256
            and prepared.state_path == str(state_file)
            and (
                canonical_before_sha256 is None
                or prepared.canonical_before_sha256 == canonical_before_sha256
            )
            and (
                canonical_after_sha256 is None
                or prepared.canonical_after_sha256 == canonical_after_sha256
            )
        ):
            matches.append(prepared)
    if len(matches) > 1:
        raise ValueError("multiple matching durable sync prepares")
    return matches[0] if matches else None


def _require_prepared_transition(
    prepared: StrategyPromotionSyncPrepare,
    *,
    sleeve: str,
) -> None:
    transitions = (prepared.promoted, prepared.demoted, prepared.unchanged)
    if (
        sum(bool(items) for items in transitions) != 1
        or any(len(items) > 1 for items in transitions)
        or any(item != sleeve for items in transitions for item in items)
    ):
        raise ValueError("prepared transition tuple is invalid")


def _receipt_candidate(
    *,
    prepared: StrategyPromotionSyncPrepare,
    proposal: StrategyPromotionProposal,
    proposal_sha256: str,
    canonical_before_sha256: str,
    canonical_after_sha256: str,
    state_file: Path,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        kind=STRATEGY_PROMOTION_SYNC_RECEIPT_KIND,
        effective_at=prepared.effective_at,
        payload={
            "schema_version": 1,
            "sync_prepare_id": prepared.sync_prepare_id,
            "sync_prepare_sha256": _digest(prepared.canonical_json_bytes()),
            "proposal_id": proposal.proposal_id,
            "proposal_sha256": proposal_sha256,
            "evaluation_runtime_sha256": proposal.evaluation_runtime_sha256,
            "promotion_runtime_commit": proposal.promotion_runtime_commit,
            "validation_report_sha256": proposal.validation_attestation.report_sha256,
            "risk_envelope_sha256": proposal.risk_attestation.risk_envelope_sha256,
            "canonical_before_sha256": canonical_before_sha256,
            "canonical_after_sha256": canonical_after_sha256,
            "state_path": str(state_file),
            "promoted": list(prepared.promoted),
            "demoted": list(prepared.demoted),
            "unchanged": list(prepared.unchanged),
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )


def _require_matching_receipt(
    *,
    receipt: StrategyPromotionSyncReceipt,
    prepared: StrategyPromotionSyncPrepare,
    proposal: StrategyPromotionProposal,
    proposal_sha256: str,
    canonical_before_sha256: str,
    canonical_after_sha256: str,
    state_file: Path,
) -> None:
    if (
        receipt.sync_prepare_id != prepared.sync_prepare_id
        or receipt.sync_prepare_sha256 != _digest(prepared.canonical_json_bytes())
        or receipt.proposal_id != proposal.proposal_id
        or receipt.proposal_sha256 != proposal_sha256
        or receipt.evaluation_runtime_sha256 != proposal.evaluation_runtime_sha256
        or receipt.promotion_runtime_commit != proposal.promotion_runtime_commit
        or receipt.validation_report_sha256
        != proposal.validation_attestation.report_sha256
        or receipt.risk_envelope_sha256 != proposal.risk_attestation.risk_envelope_sha256
        or receipt.canonical_before_sha256 != canonical_before_sha256
        or receipt.canonical_after_sha256 != canonical_after_sha256
        or receipt.state_path != str(state_file)
        or receipt.effective_at != prepared.effective_at
        or receipt.promoted != prepared.promoted
        or receipt.demoted != prepared.demoted
        or receipt.unchanged != prepared.unchanged
    ):
        raise ValueError("sync receipt does not match prepared replacement")


def sync_strategy_promotion_state_file(*, proposal_ledger_root: str | Path, repo_root: str | Path, proposal: StrategyPromotionProposal, state_path: str | Path, expected_current_state_sha256: str, actor_role: str, clock: Callable[[], datetime.datetime] | None = None) -> StrategyPromotionSyncResult:
    if actor_role != authority_for(ActionClass.PROMOTION_CHANGE).owner_role:
        raise ValueError("actor_role lacks promotion authority")
    if type(proposal) is not StrategyPromotionProposal or len(expected_current_state_sha256) != 64:
        raise ValueError("sync inputs are invalid")
    state_anchor = _capture_state_path_anchor(state_path)
    state_file = state_anchor.path
    repo = Path(repo_root).resolve()
    with promotion_state_lock(state_file):
        # The lock can be acquired before a hostile parent replacement.  The
        # no-follow parent chain proves this one captured pathname still names
        # the original state directory before any evidence work begins.
        _require_state_path_anchor_current(state_anchor)
        _state_path_identity(state_file)
        store = ImmutableStrategyEvidenceStore(proposal_ledger_root, clock=clock)
        # Lock order is state then evidence store.  The durable proposal must be exact.
        durable = StrategyOperationalPromotionLedger(proposal_ledger_root, clock=clock).rebuild()
        matches = [x for x in durable if x.proposal_id == proposal.proposal_id]
        if len(matches) != 1 or matches[0].canonical_json_bytes() != proposal.canonical_json_bytes():
            raise ValueError("proposal is not durable and byte-identical")
        snapshot = read_promotion_state_snapshot(state_file)
        proposal_sha = _digest(proposal.canonical_json_bytes())
        current_sleeves = snapshot.state.get("sleeves", {})
        previous = (
            current_sleeves.get(proposal.sleeve)
            if isinstance(current_sleeves, Mapping)
            else None
        )
        if previous is not None and not isinstance(previous, Mapping):
            raise ValueError("existing sleeve record is malformed")
        # A matching caller preimage requests a new transaction.  Refuse an
        # older proposal before consulting any old prepare, whose before-image
        # necessarily predates the current committed sleeve.
        if snapshot.sha256 == expected_current_state_sha256:
            _require_not_stale_prior(previous, proposal)
        if snapshot.sha256 != expected_current_state_sha256:
            _require_state_path_anchor_current(state_anchor)
            prepared = _matching_prepared_replacement(
                store=store,
                proposal=proposal,
                proposal_sha256=proposal_sha,
                state_file=state_file,
                canonical_before_sha256=expected_current_state_sha256,
                canonical_after_sha256=snapshot.sha256,
            )
            if prepared is not None:
                _require_state_path_anchor_current(state_anchor)
                _require_snapshot_current(snapshot)
                receipt = store.admit_checked(
                    _receipt_candidate(
                        prepared=prepared,
                        proposal=proposal,
                        proposal_sha256=proposal_sha,
                        canonical_before_sha256=prepared.canonical_before_sha256,
                        canonical_after_sha256=prepared.canonical_after_sha256,
                        state_file=state_file,
                    ),
                    validate=lambda s, e: _envelope_object(
                        e,
                        StrategyPromotionSyncReceipt,
                    ),
                )
                recorded = _envelope_object(
                    receipt.envelope,
                    StrategyPromotionSyncReceipt,
                )
                if not isinstance(recorded, StrategyPromotionSyncReceipt):
                    raise ValueError("sync receipt type is invalid")
                _require_matching_receipt(
                    receipt=recorded,
                    prepared=prepared,
                    proposal=proposal,
                    proposal_sha256=proposal_sha,
                    canonical_before_sha256=prepared.canonical_before_sha256,
                    canonical_after_sha256=prepared.canonical_after_sha256,
                    state_file=state_file,
                )
                return StrategyPromotionSyncResult(
                    dict(snapshot.state),
                    prepared.promoted,
                    prepared.demoted,
                    prepared.unchanged,
                    proposal.proposal_id,
                    prepared.sync_prepare_id,
                    recorded.sync_receipt_id,
                    prepared.canonical_before_sha256,
                    prepared.canonical_after_sha256,
                    receipt.created,
                    "immutable strategy eligibility receipt repaired",
                )
            related_prepare = _matching_prepared_replacement(
                store=store,
                proposal=proposal,
                proposal_sha256=proposal_sha,
                state_file=state_file,
                canonical_before_sha256=None,
                canonical_after_sha256=None,
            )
            if related_prepare is not None:
                raise ValueError(
                    "prepared sync transaction does not match state preimage or afterimage"
                )
            raise ValueError("stale promotion state preimage")
        prepared_before_replace = _matching_prepared_replacement(
            store=store,
            proposal=proposal,
            proposal_sha256=proposal_sha,
            state_file=state_file,
            canonical_before_sha256=snapshot.sha256,
            canonical_after_sha256=None,
        )
        if prepared_before_replace is None:
            related_prepare = _matching_prepared_replacement(
                store=store,
                proposal=proposal,
                proposal_sha256=proposal_sha,
                state_file=state_file,
                canonical_before_sha256=None,
                canonical_after_sha256=None,
            )
            if related_prepare is not None:
                raise ValueError(
                    "prepared sync transaction has no matching state preimage"
                )
        now = datetime.datetime.now(datetime.timezone.utc) if clock is None else clock()
        synced = _time_text(now, "synced_at")
        moment = _time(synced, "synced_at")
        if not (_time(proposal.recorded_at, "recorded_at") <= moment < _time(proposal.expires_at, "expires_at")):
            if prepared_before_replace is not None:
                raise ValueError("prepared promotion state transaction is expired")
            raise ValueError("proposal is inactive")
        _require_current_attestation(
            checked_at=moment,
            attested_at=proposal.validation_attestation.completed_at,
            max_age_seconds=VALIDATION_ATTESTATION_MAX_AGE_SECONDS,
            label="validation attestation",
        )
        _require_current_attestation(
            checked_at=moment,
            attested_at=proposal.risk_attestation.reviewed_at,
            max_age_seconds=RISK_ATTESTATION_MAX_AGE_SECONDS,
            label="risk attestation",
        )
        _require_risk_gate_projection(proposal)
        # Re-anchor the external files and deployment before computing output.
        _require_clean_runtime_descendant(repo, proposal.promotion_runtime_commit)
        report, _ = _safe_repo_file(repo, proposal.validation_attestation.report_ref, "validation report")
        risk, _ = _safe_repo_file(repo, proposal.risk_attestation.risk_envelope_ref, "risk envelope")
        report_bytes = report.read_bytes()
        risk_bytes = risk.read_bytes()
        if _digest(report_bytes) != proposal.validation_attestation.report_sha256 or _digest(risk_bytes) != proposal.risk_attestation.risk_envelope_sha256:
            raise ValueError("external promotion anchor changed")
        if type(proposal) is _ImmutableStrategyPromotionProposal:
            _require_current_risk_envelope(
                risk,
                proposal=proposal,
                anchored_bytes=risk_bytes,
            )
            if report.read_bytes() != report_bytes:
                raise ValueError("validation report changed during sync anchoring")
        durable_sources = _require_durable_source_recomputation(
            store=store,
            proposal=proposal,
            repo_root=repo,
            checked_at=moment,
        )
        _require_external_promotion_anchors_unchanged(
            report=report,
            risk=risk,
            report_bytes=report_bytes,
            risk_bytes=risk_bytes,
        )
        if type(proposal) is _ImmutableStrategyPromotionProposal:
            _require_current_risk_envelope(
                risk,
                proposal=proposal,
                anchored_bytes=risk_bytes,
            )
        promoted, demoted, unchanged = _transition(previous, proposal.proposed_stage, proposal.sleeve)
        state_moment = (
            _time(prepared_before_replace.effective_at, "prepared effective_at")
            if prepared_before_replace is not None
            else moment
        )
        state = build_strategy_promotion_state(
            proposal=proposal,
            current_state=snapshot.state,
            canonical_input_sha256=snapshot.sha256,
            actor_role=actor_role,
            synced_at=state_moment,
            promotion_evidence=(
                durable_sources[0] if durable_sources is not None else None
            ),
            shadow_attestation=(
                durable_sources[1] if durable_sources is not None else None
            ),
        )
        after = _canonical(state)
        after_sha = _digest(after)
        if prepared_before_replace is not None:
            if after_sha != prepared_before_replace.canonical_after_sha256:
                raise ValueError("prepared sync replacement does not match recomputed state")
            prepared = prepared_before_replace
            prepare_created = False
        else:
            _require_external_promotion_anchors_unchanged(
                report=report,
                risk=risk,
                report_bytes=report_bytes,
                risk_bytes=risk_bytes,
            )
            if type(proposal) is _ImmutableStrategyPromotionProposal:
                _require_current_risk_envelope(
                    risk,
                    proposal=proposal,
                    anchored_bytes=risk_bytes,
                )
            _require_snapshot_current(snapshot)
            prepare_payload = {
                "schema_version": 1,
                "proposal_id": proposal.proposal_id,
                "proposal_sha256": proposal_sha,
                "evaluation_runtime_sha256": proposal.evaluation_runtime_sha256,
                "promotion_runtime_commit": proposal.promotion_runtime_commit,
                "validation_report_sha256": proposal.validation_attestation.report_sha256,
                "risk_envelope_sha256": proposal.risk_attestation.risk_envelope_sha256,
                "canonical_before_sha256": snapshot.sha256,
                "canonical_after_sha256": after_sha,
                "state_path": str(state_file),
                "promoted": list(promoted),
                "demoted": list(demoted),
                "unchanged": list(unchanged),
                "analysis_only": True,
                "execution_authority": "none",
                "can_submit_orders": False,
            }
            prepare_candidate = EvidenceCandidate(kind=STRATEGY_PROMOTION_SYNC_PREPARE_KIND, effective_at=synced, payload=prepare_payload)
            _require_state_path_anchor_current(state_anchor)
            admission = store.admit_checked(prepare_candidate, validate=lambda s, e: _envelope_object(e, StrategyPromotionSyncPrepare))
            prepared = _envelope_object(admission.envelope, StrategyPromotionSyncPrepare)
            prepare_created = admission.created
        # A content-identical retry never changes state; a missing receipt is repaired below.
        if snapshot.sha256 != after_sha:
            staged = _stage_state_replacement(state_file, after)
            try:
                _require_state_path_anchor_current(state_anchor)
                _require_snapshot_current(snapshot)
                replaced_snapshot = _replace_state_after_final_guard(
                    state_file=state_file,
                    snapshot=snapshot,
                    staged=staged,
                    after=after,
                    after_sha256=after_sha,
                )
            finally:
                staged.unlink(missing_ok=True)
        else:
            replaced_snapshot = snapshot
        _require_state_path_anchor_current(state_anchor)
        _require_snapshot_current(replaced_snapshot)
        receipt = store.admit_checked(
            _receipt_candidate(
                prepared=prepared,
                proposal=proposal,
                proposal_sha256=proposal_sha,
                canonical_before_sha256=snapshot.sha256,
                canonical_after_sha256=after_sha,
                state_file=state_file,
            ),
            validate=lambda s, e: _envelope_object(e, StrategyPromotionSyncReceipt),
        )
        recorded = _envelope_object(receipt.envelope, StrategyPromotionSyncReceipt)
        if not isinstance(recorded, StrategyPromotionSyncReceipt):
            raise ValueError("sync receipt type is invalid")
        _require_matching_receipt(
            receipt=recorded,
            prepared=prepared,
            proposal=proposal,
            proposal_sha256=proposal_sha,
            canonical_before_sha256=snapshot.sha256,
            canonical_after_sha256=after_sha,
            state_file=state_file,
        )
        return StrategyPromotionSyncResult(state, promoted, demoted, unchanged, proposal.proposal_id, prepared.sync_prepare_id, recorded.sync_receipt_id, snapshot.sha256, after_sha, prepare_created or receipt.created, "immutable strategy eligibility synchronized")


_NORMAL_LIVE_PREPARE_FIELDS = frozenset(
    {
        "schema_version",
        "intent_full_sha256",
        "logical_order_sha256",
        "proposal_id",
        "proposal_sha256",
        "promotion_sync_receipt_id",
        "promotion_sync_receipt_sha256",
        "risk_snapshot_sha256",
        "risk_envelope_sha256",
        "evaluation_runtime_sha256",
        "promotion_runtime_commit",
        "canonical_before_sha256",
        "canonical_after_sha256",
        "activation_state_marker",
        "state_path",
        "promoted",
        "demoted",
        "unchanged",
        "live_enabled",
    }
)
_NORMAL_LIVE_RECEIPT_FIELDS = _NORMAL_LIVE_PREPARE_FIELDS | {
    "activation_prepare_id",
    "activation_prepare_sha256",
}


def _activation_digest(value: object, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _activation_payload(
    *,
    proposal: StrategyPromotionProposal,
    intent: AuthorizedNormalTradeIntent,
    intent_full_sha256: str,
    canonical_before_sha256: str,
    canonical_after_sha256: str,
    activation_state_marker: str,
    state_file: Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "intent_full_sha256": intent_full_sha256,
        "logical_order_sha256": intent.logical_order_sha256,
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": _digest(proposal.canonical_json_bytes()),
        "promotion_sync_receipt_id": intent.promotion_sync_receipt_id,
        "promotion_sync_receipt_sha256": intent.promotion_sync_receipt_sha256,
        "risk_snapshot_sha256": intent.risk_snapshot_sha256,
        "risk_envelope_sha256": proposal.risk_attestation.risk_envelope_sha256,
        "evaluation_runtime_sha256": proposal.evaluation_runtime_sha256,
        "promotion_runtime_commit": proposal.promotion_runtime_commit,
        "canonical_before_sha256": canonical_before_sha256,
        "canonical_after_sha256": canonical_after_sha256,
        "activation_state_marker": activation_state_marker,
        "state_path": str(state_file),
        "promoted": [proposal.sleeve],
        "demoted": [],
        "unchanged": [],
        "live_enabled": True,
    }


def _require_activation_payload(
    payload: object,
    *,
    expected: Mapping[str, object],
    receipt: bool,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("normal live activation evidence payload is invalid")
    expected_fields = (
        _NORMAL_LIVE_RECEIPT_FIELDS if receipt else _NORMAL_LIVE_PREPARE_FIELDS
    )
    if set(payload) != expected_fields:
        raise ValueError("normal live activation evidence fields are invalid")
    material = dict(payload)
    if receipt:
        prepare_id = material.pop("activation_prepare_id")
        prepare_sha = material.pop("activation_prepare_sha256")
        if type(prepare_id) is not str or not prepare_id.startswith(
            NORMAL_LIVE_ACTIVATION_PREPARE_KIND + "-"
        ):
            raise ValueError("normal live activation prepare id is invalid")
        _activation_digest(prepare_sha, "normal live activation prepare digest")
    for key, value in expected.items():
        if material.get(key) != value:
            raise ValueError("normal live activation evidence does not match intent")
    for key in (
        "intent_full_sha256",
        "logical_order_sha256",
        "proposal_sha256",
        "promotion_sync_receipt_sha256",
        "risk_snapshot_sha256",
        "risk_envelope_sha256",
        "evaluation_runtime_sha256",
        "canonical_before_sha256",
        "canonical_after_sha256",
    ):
        _activation_digest(material.get(key), key)
    if (
        material["schema_version"] != 1
        or material["live_enabled"] is not True
        or material["promoted"] != expected["promoted"]
        or material["demoted"] != []
        or material["unchanged"] != []
    ):
        raise ValueError("normal live activation transition is invalid")
    return dict(payload)


def _activation_collision_or_receipt(
    *,
    store: ImmutableStrategyEvidenceStore,
    logical_order_sha256: str,
    intent_full_sha256: str,
    canonical_after_sha256: str,
) -> EvidenceEnvelope | None:
    receipt: EvidenceEnvelope | None = None
    for kind in (
        NORMAL_LIVE_ACTIVATION_PREPARE_KIND,
        NORMAL_LIVE_ACTIVATION_RECEIPT_KIND,
    ):
        for envelope in store.envelopes(kind=kind):
            payload = _thaw_json(envelope.payload)
            if not isinstance(payload, Mapping):
                raise ValueError("normal live activation evidence payload is invalid")
            if payload.get("logical_order_sha256") != logical_order_sha256:
                continue
            if payload.get("intent_full_sha256") != intent_full_sha256:
                raise ValueError("logical order digest is already bound to different intent")
            if kind == NORMAL_LIVE_ACTIVATION_RECEIPT_KIND:
                if payload.get("canonical_after_sha256") != canonical_after_sha256:
                    raise ValueError("normal live activation receipt state is inconsistent")
                receipt = envelope
    return receipt


def _require_current_normal_live_sleeve(
    *, proposal: StrategyPromotionProposal, state: Mapping[str, object]
) -> Mapping[str, object]:
    sleeves = state.get("sleeves")
    if not isinstance(sleeves, Mapping):
        raise ValueError("promotion state has no eligible sleeve")
    sleeve = sleeves.get(proposal.sleeve)
    if not isinstance(sleeve, Mapping):
        raise ValueError("promotion state has no eligible sleeve")
    if (
        sleeve.get("stage") != "tiny_live_eligible"
        or sleeve.get("live_enabled") is not False
    ):
        raise ValueError("promotion state is not an eligible capped sleeve")
    return sleeve


def _require_current_normal_live_sources(
    *,
    store: ImmutableStrategyEvidenceStore,
    proposal: StrategyPromotionProposal,
    repo: Path,
    checked_at: datetime.datetime,
) -> None:
    """Revalidate the complete 6D source chain while the state lock is held."""

    _require_current_attestation(
        checked_at=checked_at,
        attested_at=proposal.validation_attestation.completed_at,
        max_age_seconds=VALIDATION_ATTESTATION_MAX_AGE_SECONDS,
        label="validation attestation",
    )
    _require_current_attestation(
        checked_at=checked_at,
        attested_at=proposal.risk_attestation.reviewed_at,
        max_age_seconds=RISK_ATTESTATION_MAX_AGE_SECONDS,
        label="risk attestation",
    )
    _require_risk_gate_projection(proposal)
    _require_clean_runtime_descendant(repo, proposal.promotion_runtime_commit)
    report, _ = _safe_repo_file(
        repo, proposal.validation_attestation.report_ref, "validation report"
    )
    risk, _ = _safe_repo_file(
        repo, proposal.risk_attestation.risk_envelope_ref, "risk envelope"
    )
    report_bytes = report.read_bytes()
    risk_bytes = risk.read_bytes()
    if (
        _digest(report_bytes) != proposal.validation_attestation.report_sha256
        or _digest(risk_bytes) != proposal.risk_attestation.risk_envelope_sha256
    ):
        raise ValueError("external promotion anchor changed")
    if type(proposal) is _ImmutableStrategyPromotionProposal:
        _require_current_risk_envelope(
            risk, proposal=proposal, anchored_bytes=risk_bytes
        )
        if report.read_bytes() != report_bytes:
            raise ValueError("validation report changed during sync anchoring")
    _require_durable_source_recomputation(
        store=store,
        proposal=proposal,
        repo_root=repo,
        checked_at=checked_at,
    )
    _require_external_promotion_anchors_unchanged(
        report=report,
        risk=risk,
        report_bytes=report_bytes,
        risk_bytes=risk_bytes,
    )
    if type(proposal) is _ImmutableStrategyPromotionProposal:
        _require_current_risk_envelope(
            risk, proposal=proposal, anchored_bytes=risk_bytes
        )


def _require_complete_normal_live_intent_chain(
    *,
    intent: AuthorizedNormalTradeIntent,
    proposal: StrategyPromotionProposal,
    proposal_ledger_root: str | Path,
    repo: Path,
) -> None:
    """Bind all Task 2 material to the durable staged-paper decision."""

    candidates = [
        staged
        for staged in StrategyStagedIntentLedger(
            proposal_ledger_root, repo_root=repo
        ).rebuild()
        if staged.staged_intent_id == intent.staged_intent_id
    ]
    if len(candidates) != 1:
        raise ValueError("activation requires the exact durable staged intent")
    staged = candidates[0]
    decision = staged.decision
    if (
        _digest(staged.canonical_json_bytes()) != intent.staged_intent_sha256
        or staged.promotion_evidence_id != proposal.promotion_evidence_id
        or staged.promotion_evidence_sha256 != proposal.promotion_evidence_sha256
        or staged.genome.genome_id != proposal.genome_id
        or staged.genome_canonical_sha256 != proposal.genome_canonical_sha256
        or staged.evaluation_code_commit != proposal.evaluation_code_commit
        or staged.evaluation_runtime_sha256 != proposal.evaluation_runtime_sha256
        or intent.market_observation_sha256 != staged.observations_sha256
        or intent.portfolio_snapshot_sha256 != staged.candidate_state_sha256
        or decision.action.value != "buy"
        or decision.symbol is None
        or decision.notional_usd is None
        or decision.limit_price is None
        or intent.symbol != decision.symbol
        or intent.notional_usd != decision.notional_usd
        or intent.limit_price != decision.limit_price
        or (intent.side, intent.order_type, intent.tif) != ("buy", "limit", "day")
    ):
        raise ValueError("activation Task 2 evidence chain is not current")


def _activation_state(
    *,
    state: Mapping[str, object],
    sleeve: str,
    intent_full_sha256: str,
    proposal_id: str,
    activation_state_marker: str,
) -> dict[str, object]:
    copied = json.loads(_canonical(state))
    sleeves = copied.get("sleeves")
    if not isinstance(sleeves, dict) or not isinstance(sleeves.get(sleeve), dict):
        raise ValueError("promotion state has no eligible sleeve")
    sleeves[sleeve]["live_enabled"] = True
    copied["normal_live_activation"] = {
        "schema_version": 1,
        "issuer": "strategy_promotion_sync",
        "marker": activation_state_marker,
        "intent_full_sha256": intent_full_sha256,
        "proposal_id": proposal_id,
        "sleeve": sleeve,
    }
    return copied


def _activation_state_marker(
    *,
    state: Mapping[str, object],
    intent_full_sha256: str,
    proposal_id: str,
    sleeve: str | None = None,
) -> str:
    link = state.get("normal_live_activation")
    if not isinstance(link, Mapping) or set(link) != {
        "schema_version",
        "issuer",
        "marker",
        "intent_full_sha256",
        "proposal_id",
        "sleeve",
    }:
        raise ValueError("activation receipt has no Task 3 state marker")
    marker = link.get("marker")
    if (
        link.get("schema_version") != 1
        or link.get("issuer") != "strategy_promotion_sync"
        or type(marker) is not str
        or re.fullmatch(r"[0-9a-f]{64}", marker) is None
        or link.get("intent_full_sha256") != intent_full_sha256
        or link.get("proposal_id") != proposal_id
        or type(link.get("sleeve")) is not str
        or (sleeve is not None and link.get("sleeve") != sleeve)
    ):
        raise ValueError("activation receipt Task 3 state marker is invalid")
    return marker


def _verify_normal_live_activation_receipt(
    intent: AuthorizedNormalTradeIntent,
    receipt: NormalLiveActivationReceipt,
    *,
    proposal_ledger_root: str | Path,
    repo_root: str | Path,
    checked_at: datetime.datetime | None = None,
    clock: Callable[[], datetime.datetime] | None = None,
    _accept: Callable[[ImmutableStrategyEvidenceStore, PromotionStateSnapshot, str], object]
    | None = None,
) -> object | None:
    """Read-only Task 3 provenance check for the broker-write boundary.

    This deliberately reuses the activation transaction's exact envelope and
    state validators. It creates no evidence and never enables a sleeve.
    """

    if (
        type(intent) is not AuthorizedNormalTradeIntent
        or type(receipt) is not NormalLiveActivationReceipt
        or (checked_at is None) == (clock is None)
    ):
        raise ValueError("activation receipt verification requires exact typed values")
    root = Path(proposal_ledger_root)
    repo = Path(repo_root).resolve()
    store = ImmutableStrategyEvidenceStore(root)
    try:
        durable_receipts = [
            envelope
            for envelope in store.envelopes(kind=NORMAL_LIVE_ACTIVATION_RECEIPT_KIND)
            if envelope.object_id == receipt.activation_receipt_id
        ]
    except ValueError as exc:
        raise ValueError("activation receipt evidence is unavailable") from exc
    if len(durable_receipts) != 1:
        raise ValueError("activation receipt is not durable")
    receipt_payload = _thaw_json(durable_receipts[0].payload)
    if not isinstance(receipt_payload, Mapping):
        raise ValueError("activation receipt payload is invalid")
    state_path_value = receipt_payload.get("state_path")
    if type(state_path_value) is not str or not Path(state_path_value).is_absolute():
        raise ValueError("activation receipt state path is not canonical")
    state_anchor = _capture_state_path_anchor(state_path_value)
    state_file = state_anchor.path
    with promotion_state_lock(state_file):
        raw_moment = checked_at if clock is None else clock()
        if (
            type(raw_moment) is not datetime.datetime
            or raw_moment.tzinfo is None
            or raw_moment.utcoffset() is None
            or raw_moment.microsecond
        ):
            raise ValueError("activation receipt verification requires exact typed values")
        moment = raw_moment.astimezone(datetime.timezone.utc)
        if not intent.is_active(at=moment):
            raise ValueError("activation receipt intent is not active")
        store = ImmutableStrategyEvidenceStore(root, clock=lambda: moment)
        _require_state_path_anchor_current(state_anchor)
        snapshot = read_promotion_state_snapshot(state_file)
        _require_snapshot_current(snapshot)
        if (
            snapshot.sha256 != receipt.canonical_after_sha256
            or receipt.state != dict(snapshot.state)
            or receipt.intent_full_sha256 != _digest(intent.canonical_json_bytes())
            or receipt.canonical_before_sha256 != intent.promotion_state_sha256
        ):
            raise ValueError("activation receipt state provenance is inconsistent")
        activation_state_marker = _activation_state_marker(
            state=snapshot.state,
            intent_full_sha256=_digest(intent.canonical_json_bytes()),
            proposal_id=intent.promotion_proposal_id,
        )
        durable = StrategyOperationalPromotionLedger(root, clock=lambda: moment).rebuild()
        proposals = [item for item in durable if item.proposal_id == intent.promotion_proposal_id]
        if len(proposals) != 1:
            raise ValueError("activation proposal is not durable")
        proposal = proposals[0]
        if (
            _digest(proposal.canonical_json_bytes()) != intent.promotion_proposal_sha256
            or intent.evaluation_runtime_sha256 != proposal.evaluation_runtime_sha256
            or intent.evaluation_code_commit != proposal.evaluation_code_commit
            or intent.genome_id != proposal.genome_id
            or intent.genome_canonical_sha256 != proposal.genome_canonical_sha256
            or intent.shadow_attestation_sha256 != proposal.shadow_attestation_sha256
            or intent.risk_snapshot_sha256 != proposal.risk_attestation.risk_envelope_sha256
        ):
            raise ValueError("activation receipt does not bind the durable proposal")
        if activation_state_marker != _activation_state_marker(
            state=snapshot.state,
            intent_full_sha256=_digest(intent.canonical_json_bytes()),
            proposal_id=proposal.proposal_id,
            sleeve=proposal.sleeve,
        ):
            raise ValueError("activation receipt Task 3 state marker changed")
        _require_current_normal_live_sources(
            store=store, proposal=proposal, repo=repo, checked_at=moment
        )
        _require_complete_normal_live_intent_chain(
            intent=intent, proposal=proposal, proposal_ledger_root=root, repo=repo
        )
        sleeves = snapshot.state.get("sleeves")
        sleeve = sleeves.get(proposal.sleeve) if isinstance(sleeves, Mapping) else None
        if (
            not isinstance(sleeve, Mapping)
            or sleeve.get("stage") != "tiny_live_eligible"
            or sleeve.get("live_enabled") is not True
        ):
            raise ValueError("activation receipt has no current live-eligible sleeve")
        expected_prepare = _activation_payload(
            proposal=proposal,
            intent=intent,
            intent_full_sha256=_digest(intent.canonical_json_bytes()),
            canonical_before_sha256=intent.promotion_state_sha256,
            canonical_after_sha256=snapshot.sha256,
            activation_state_marker=activation_state_marker,
            state_file=state_file,
        )
        prepares = [
            envelope
            for envelope in store.envelopes(kind=NORMAL_LIVE_ACTIVATION_PREPARE_KIND)
            if envelope.object_id == receipt.activation_prepare_id
        ]
        if len(prepares) != 1:
            raise ValueError("activation prepare is not durable")
        prepare = prepares[0]
        _require_activation_payload(
            _thaw_json(prepare.payload), expected=expected_prepare, receipt=False
        )
        expected_receipt = {
            **expected_prepare,
            "activation_prepare_id": prepare.object_id,
            "activation_prepare_sha256": _digest(prepare.canonical_json_bytes()),
        }
        _require_activation_payload(
            receipt_payload, expected=expected_prepare, receipt=True
        )
        if dict(receipt_payload) != expected_receipt:
            raise ValueError("activation receipt does not match the activation transaction")
        _require_snapshot_current(snapshot)
        _require_state_path_anchor_current(state_anchor)
        return (
            None
            if _accept is None
            else _accept(store, snapshot, activation_state_marker)
        )


def _normal_live_broker_submit_payload(
    *,
    intent: AuthorizedNormalTradeIntent,
    receipt: NormalLiveActivationReceipt,
    immutable_order_sha256: str,
    canonical_state_sha256: str,
    activation_state_marker: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "intent_full_sha256": _digest(intent.canonical_json_bytes()),
        "logical_order_sha256": intent.logical_order_sha256,
        "client_order_id": intent.client_order_id,
        "activation_prepare_id": receipt.activation_prepare_id,
        "activation_receipt_id": receipt.activation_receipt_id,
        "immutable_order_sha256": immutable_order_sha256,
        "canonical_state_sha256": canonical_state_sha256,
        "activation_state_marker": activation_state_marker,
    }


def _require_unique_normal_live_broker_submit(snapshot, envelope) -> None:
    payload = envelope.payload
    if not isinstance(payload, Mapping):
        raise ValueError("durable live submit record is invalid")
    logical = payload.get("logical_order_sha256")
    client_order_id = payload.get("client_order_id")
    if type(logical) is not str or type(client_order_id) is not str:
        raise ValueError("durable live submit record is invalid")
    for prior in snapshot:
        if prior.kind != NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND:
            continue
        prior_payload = prior.payload
        if not isinstance(prior_payload, Mapping):
            raise ValueError("durable live submit record is invalid")
        if (
            prior_payload.get("logical_order_sha256") == logical
            or prior_payload.get("client_order_id") == client_order_id
        ) and prior.payload != payload:
            raise ValueError("logical/client order ID is already consumed by different receipt")


def admit_normal_live_broker_submit(
    intent: AuthorizedNormalTradeIntent,
    receipt: NormalLiveActivationReceipt,
    *,
    proposal_ledger_root: str | Path,
    repo_root: str | Path,
    immutable_order_sha256: str,
    clock: Callable[[], datetime.datetime],
) -> NormalLiveBrokerSubmitAdmission:
    """Atomically verify Task 3 state and persist a broker-submit handoff.

    No network operation is performed while the promotion-state lock is held.
    The returned object is solely a durable, state-bound admission for Alpaca's
    subsequent read-first broker interaction.
    """

    if (
        type(intent) is not AuthorizedNormalTradeIntent
        or type(receipt) is not NormalLiveActivationReceipt
        or not callable(clock)
        or type(immutable_order_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", immutable_order_sha256) is None
    ):
        raise ValueError("normal live broker admission requires exact typed values")

    def admit(
        store: ImmutableStrategyEvidenceStore,
        snapshot: PromotionStateSnapshot,
        activation_state_marker: str,
    ) -> NormalLiveBrokerSubmitAdmission:
        candidate = EvidenceCandidate(
            kind=NORMAL_LIVE_BROKER_SUBMIT_PREPARE_KIND,
            effective_at=intent.recorded_at,
            payload=_normal_live_broker_submit_payload(
                intent=intent,
                receipt=receipt,
                immutable_order_sha256=immutable_order_sha256,
                canonical_state_sha256=snapshot.sha256,
                activation_state_marker=activation_state_marker,
            ),
        )
        admission = store.admit_checked(
            candidate,
            validate=_require_unique_normal_live_broker_submit,
        )
        return NormalLiveBrokerSubmitAdmission(
            created=admission.created,
            client_order_id=intent.client_order_id,
            canonical_state_sha256=snapshot.sha256,
            activation_state_marker=activation_state_marker,
        )

    admitted = _verify_normal_live_activation_receipt(
        intent,
        receipt,
        proposal_ledger_root=proposal_ledger_root,
        repo_root=repo_root,
        clock=clock,
        _accept=admit,
    )
    if type(admitted) is not NormalLiveBrokerSubmitAdmission:
        raise ValueError("normal live broker admission was not recorded")
    return admitted


def verify_normal_live_activation_receipt(
    intent: AuthorizedNormalTradeIntent,
    receipt: NormalLiveActivationReceipt,
    *,
    proposal_ledger_root: str | Path,
    repo_root: str | Path,
    checked_at: datetime.datetime,
) -> None:
    """Read-only Task 3 provenance check for a normal-live receipt."""

    _verify_normal_live_activation_receipt(
        intent,
        receipt,
        proposal_ledger_root=proposal_ledger_root,
        repo_root=repo_root,
        checked_at=checked_at,
    )


def activate_normal_live_intent(
    proposal: StrategyPromotionProposal,
    intent: AuthorizedNormalTradeIntent,
    *,
    proposal_ledger_root: str | Path,
    repo_root: str | Path,
    state_path: str | Path,
    clock: Callable[[], datetime.datetime] | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> NormalLiveActivationReceipt:
    """Atomically enable exactly one already-bound normal-live sleeve locally.

    The operation has no broker dependency and writes only the supplied local
    promotion state plus immutable analysis-only evidence.  It intentionally
    creates no order and exposes no live-capable command surface.
    """

    if type(proposal) is not StrategyPromotionProposal or type(intent) is not AuthorizedNormalTradeIntent:
        raise ValueError("activation requires exact current intent and proposal")
    state_anchor = _capture_state_path_anchor(state_path)
    state_file = state_anchor.path
    repo = Path(repo_root).resolve()
    intent_full_sha256 = _digest(intent.canonical_json_bytes())
    with promotion_state_lock(state_file):
        _require_state_path_anchor_current(state_anchor)
        # The caller can have waited on this lock for most or all of Task 2's
        # 900-second TTL.  Capture and canonicalize time only after acquiring
        # the lock, before any prepare or state mutation is possible.
        moment = datetime.datetime.now(datetime.timezone.utc) if clock is None else clock()
        activated_at = _time_text(moment, "activated_at")
        checked_at = _time(activated_at, "activated_at")
        snapshot = read_promotion_state_snapshot(state_file)
        store = ImmutableStrategyEvidenceStore(proposal_ledger_root, clock=clock)
        duplicate = _activation_collision_or_receipt(
            store=store,
            logical_order_sha256=intent.logical_order_sha256,
            intent_full_sha256=intent_full_sha256,
            canonical_after_sha256=snapshot.sha256,
        )
        if duplicate is not None:
            payload = _thaw_json(duplicate.payload)
            if not isinstance(payload, Mapping):
                raise ValueError("normal live activation receipt is invalid")
            return NormalLiveActivationReceipt(
                str(payload["activation_prepare_id"]),
                duplicate.object_id,
                intent_full_sha256,
                str(payload["canonical_before_sha256"]),
                snapshot.sha256,
                dict(snapshot.state),
                False,
                "read_only_retry",
            )
        repaired_activation_state_marker: str | None = None
        repaired_prepares: list[tuple[EvidenceEnvelope, dict[str, object]]] = []
        for envelope in store.envelopes(kind=NORMAL_LIVE_ACTIVATION_PREPARE_KIND):
            payload = _thaw_json(envelope.payload)
            if not isinstance(payload, Mapping) or payload.get("intent_full_sha256") != intent_full_sha256:
                continue
            after_sha256 = payload.get("canonical_after_sha256")
            if after_sha256 != snapshot.sha256:
                continue
            if repaired_activation_state_marker is None:
                repaired_activation_state_marker = _activation_state_marker(
                    state=snapshot.state,
                    intent_full_sha256=intent_full_sha256,
                    proposal_id=proposal.proposal_id,
                    sleeve=proposal.sleeve,
                )
            expected = _activation_payload(
                proposal=proposal,
                intent=intent,
                intent_full_sha256=intent_full_sha256,
                canonical_before_sha256=intent.promotion_state_sha256,
                canonical_after_sha256=after_sha256,
                activation_state_marker=repaired_activation_state_marker,
                state_file=state_file,
            )
            _require_activation_payload(payload, expected=expected, receipt=False)
            repaired_prepares.append((envelope, expected))
        if len(repaired_prepares) > 1:
            raise ValueError("multiple normal live activation prepares")
        if repaired_prepares:
            prepare, expected_prepare = repaired_prepares[0]
            expected_receipt = {
                **expected_prepare,
                "activation_prepare_id": prepare.object_id,
                "activation_prepare_sha256": _digest(prepare.canonical_json_bytes()),
            }
            repaired = store.admit_checked(
                EvidenceCandidate(
                    kind=NORMAL_LIVE_ACTIVATION_RECEIPT_KIND,
                    effective_at=prepare.effective_at,
                    payload=expected_receipt,
                ),
                validate=lambda _snapshot, envelope: _require_activation_payload(
                    _thaw_json(envelope.payload), expected=expected_prepare, receipt=True
                ),
            )
            return NormalLiveActivationReceipt(
                prepare.object_id,
                repaired.envelope.object_id,
                intent_full_sha256,
                intent.promotion_state_sha256,
                snapshot.sha256,
                dict(snapshot.state),
                repaired.created,
                "receipt_repaired",
            )
        if snapshot.sha256 != intent.promotion_state_sha256:
            raise ValueError("promotion state preimage does not match exact intent")
        if not intent.is_active(at=checked_at):
            raise ValueError("activation requires an active capped intent")
        durable = StrategyOperationalPromotionLedger(proposal_ledger_root, clock=clock).rebuild()
        matches = [item for item in durable if item.proposal_id == proposal.proposal_id]
        if len(matches) != 1 or matches[0].canonical_json_bytes() != proposal.canonical_json_bytes():
            raise ValueError("activation proposal is not durable and byte-identical")
        if (
            intent.promotion_proposal_id != proposal.proposal_id
            or intent.promotion_proposal_sha256 != _digest(proposal.canonical_json_bytes())
            or intent.evaluation_runtime_sha256 != proposal.evaluation_runtime_sha256
            or intent.evaluation_code_commit != proposal.evaluation_code_commit
            or intent.genome_id != proposal.genome_id
            or intent.genome_canonical_sha256 != proposal.genome_canonical_sha256
            or intent.shadow_attestation_sha256 != proposal.shadow_attestation_sha256
            or intent.risk_snapshot_sha256 != proposal.risk_attestation.risk_envelope_sha256
        ):
            raise ValueError("activation requires an active capped intent")
        _require_current_normal_live_sources(
            store=store,
            proposal=proposal,
            repo=repo,
            checked_at=checked_at,
        )
        _require_complete_normal_live_intent_chain(
            intent=intent,
            proposal=proposal,
            proposal_ledger_root=proposal_ledger_root,
            repo=repo,
        )
        # Durable source and staged-intent replay can take long enough for the
        # bounded Task 2 authorization to expire.  Refresh time under the same
        # state lock immediately before any prepare or replacement write.
        moment = datetime.datetime.now(datetime.timezone.utc) if clock is None else clock()
        activated_at = _time_text(moment, "activated_at")
        checked_at = _time(activated_at, "activated_at")
        if not intent.is_active(at=checked_at):
            raise ValueError("activation requires an active capped intent")
        _require_current_normal_live_sleeve(proposal=proposal, state=snapshot.state)
        sync_receipts = [
            envelope
            for envelope in store.envelopes(kind=STRATEGY_PROMOTION_SYNC_RECEIPT_KIND)
            if envelope.object_id == intent.promotion_sync_receipt_id
        ]
        if len(sync_receipts) != 1 or _digest(sync_receipts[0].canonical_json_bytes()) != intent.promotion_sync_receipt_sha256:
            raise ValueError("activation requires the exact Task 6D receipt")
        sync_receipt = _envelope_object(sync_receipts[0], StrategyPromotionSyncReceipt)
        if (
            not isinstance(sync_receipt, StrategyPromotionSyncReceipt)
            or sync_receipt.proposal_id != proposal.proposal_id
            or sync_receipt.proposal_sha256 != _digest(proposal.canonical_json_bytes())
            or sync_receipt.canonical_after_sha256 != snapshot.sha256
        ):
            raise ValueError("activation requires the exact Task 6D receipt")
        activation_state_marker = secrets.token_hex(32)
        after_state = _activation_state(
            state=snapshot.state,
            sleeve=proposal.sleeve,
            intent_full_sha256=intent_full_sha256,
            proposal_id=proposal.proposal_id,
            activation_state_marker=activation_state_marker,
        )
        after = _canonical(after_state)
        after_sha256 = _digest(after)
        expected_prepare = _activation_payload(
            proposal=proposal,
            intent=intent,
            intent_full_sha256=intent_full_sha256,
            canonical_before_sha256=snapshot.sha256,
            canonical_after_sha256=after_sha256,
            activation_state_marker=activation_state_marker,
            state_file=state_file,
        )
        prepares = []
        for envelope in store.envelopes(kind=NORMAL_LIVE_ACTIVATION_PREPARE_KIND):
            payload = _thaw_json(envelope.payload)
            if isinstance(payload, Mapping) and payload.get("intent_full_sha256") == intent_full_sha256:
                _require_activation_payload(payload, expected=expected_prepare, receipt=False)
                prepares.append(envelope)
        if len(prepares) > 1:
            raise ValueError("multiple normal live activation prepares")
        staged = _stage_state_replacement(state_file, after)
        try:
            # Staging validates and durably writes a replacement image.  If
            # Task 2 expires there, do not consume it with a prepare record.
            moment = datetime.datetime.now(datetime.timezone.utc) if clock is None else clock()
            activated_at = _time_text(moment, "activated_at")
            checked_at = _time(activated_at, "activated_at")
            if not intent.is_active(at=checked_at):
                raise ValueError("activation requires an active capped intent")
            if prepares:
                prepare = prepares[0]
                prepare_created = False
            else:
                prepare_admission = store.admit_checked(
                    EvidenceCandidate(
                        kind=NORMAL_LIVE_ACTIVATION_PREPARE_KIND,
                        effective_at=activated_at,
                        payload=expected_prepare,
                    ),
                    validate=lambda _snapshot, envelope: _require_activation_payload(
                        _thaw_json(envelope.payload), expected=expected_prepare, receipt=False
                    ),
                )
                prepare = prepare_admission.envelope
                prepare_created = prepare_admission.created
            if fault_hook is not None:
                fault_hook("after_prepare")
            _require_state_path_anchor_current(state_anchor)
            _require_snapshot_current(snapshot)
            # A recovered prepare still cannot enable a sleeve after the bound
            # authorization has expired while final file guards were running.
            moment = datetime.datetime.now(datetime.timezone.utc) if clock is None else clock()
            activated_at = _time_text(moment, "activated_at")
            checked_at = _time(activated_at, "activated_at")
            if not intent.is_active(at=checked_at):
                raise ValueError("activation requires an active capped intent")
            replaced = _replace_state_after_final_guard(
                state_file=state_file,
                snapshot=snapshot,
                staged=staged,
                after=after,
                after_sha256=after_sha256,
            )
            if fault_hook is not None:
                fault_hook("after_replace")
            expected_receipt = {
                **expected_prepare,
                "activation_prepare_id": prepare.object_id,
                "activation_prepare_sha256": _digest(prepare.canonical_json_bytes()),
            }
            receipt_admission = store.admit_checked(
                EvidenceCandidate(
                    kind=NORMAL_LIVE_ACTIVATION_RECEIPT_KIND,
                    effective_at=prepare.effective_at,
                    payload=expected_receipt,
                ),
                validate=lambda _snapshot, envelope: _require_activation_payload(
                    _thaw_json(envelope.payload), expected=expected_prepare, receipt=True
                ),
            )
            return NormalLiveActivationReceipt(
                prepare.object_id,
                receipt_admission.envelope.object_id,
                intent_full_sha256,
                snapshot.sha256,
                replaced.sha256,
                after_state,
                prepare_created or receipt_admission.created,
                "activated",
            )
        finally:
            staged.unlink(missing_ok=True)
