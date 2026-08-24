"""Promotion evidence policy for moving a sleeve toward tiny-live eligibility."""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc


def _owner_approval_authority_utc_now() -> datetime.datetime:
    """Return the policy-owned clock for fresh owner-approval authority.

    Public ``now`` is retained for deterministic promotion evidence and
    output timestamps only.  It must never make a stale signed artifact fresh.
    """

    return datetime.datetime.now(tz=UTC)


@dataclass(frozen=True)
class SleevePromotionEvidence:
    sleeve: str
    preregistered: bool
    ci_green: bool
    shadow_confirmed: bool
    benchmark_excess_return: Decimal
    cost_adjusted_alpha: Decimal
    recent_alpha: Decimal
    capacity_usd: Decimal
    requested_tiny_live_tranche_usd: Decimal
    validation_report_ref: str
    risk_envelope_ref: str
    min_benchmark_excess_return: Decimal = Decimal("0")
    min_cost_adjusted_alpha: Decimal = Decimal("0")
    min_recent_alpha: Decimal = Decimal("0")


@dataclass(frozen=True)
class SleevePromotionDecision:
    sleeve: str
    stage: str
    live_enabled: bool
    passed: bool
    gates: dict[str, bool]
    issues: list[str]
    state: dict


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _decimal_str(value: Decimal) -> str:
    return str(value)


def evaluate_sleeve_promotion(
    evidence: SleevePromotionEvidence,
    *,
    arm_live: bool = False,
    promoted_at: str | None = None,
) -> SleevePromotionDecision:
    gates = {
        "preregistered": evidence.preregistered,
        "ci_green": evidence.ci_green,
        "shadow_confirmed": evidence.shadow_confirmed,
        "benchmark_gate_passed": evidence.benchmark_excess_return >= evidence.min_benchmark_excess_return,
        "cost_gate_passed": evidence.cost_adjusted_alpha >= evidence.min_cost_adjusted_alpha,
        "recent_alpha_gate_passed": evidence.recent_alpha >= evidence.min_recent_alpha,
        "capacity_gate_passed": evidence.capacity_usd >= evidence.requested_tiny_live_tranche_usd,
        "validation_report_present": bool(evidence.validation_report_ref),
        "risk_envelope_ref_present": bool(evidence.risk_envelope_ref),
    }
    issues = [name for name, passed in gates.items() if not passed]
    passed = not issues
    stage = "tiny_live_eligible" if passed else "paper_only"
    live_enabled = bool(arm_live and passed)
    state = {
        "stage": stage,
        "live_enabled": live_enabled,
        "ci_green": evidence.ci_green,
        "shadow_confirmed": evidence.shadow_confirmed,
        "preregistered": evidence.preregistered,
        "benchmark_gate_passed": gates["benchmark_gate_passed"],
        "cost_gate_passed": gates["cost_gate_passed"],
        "recent_alpha_gate_passed": gates["recent_alpha_gate_passed"],
        "capacity_gate_passed": gates["capacity_gate_passed"],
        "validation_report_ref": evidence.validation_report_ref,
        "risk_envelope_ref": evidence.risk_envelope_ref,
        "promoted_at": promoted_at or _now_iso(),
        "metrics": {
            "benchmark_excess_return": _decimal_str(evidence.benchmark_excess_return),
            "cost_adjusted_alpha": _decimal_str(evidence.cost_adjusted_alpha),
            "recent_alpha": _decimal_str(evidence.recent_alpha),
            "capacity_usd": _decimal_str(evidence.capacity_usd),
            "requested_tiny_live_tranche_usd": _decimal_str(evidence.requested_tiny_live_tranche_usd),
        },
        "issues": issues,
    }
    return SleevePromotionDecision(
        sleeve=evidence.sleeve,
        stage=stage,
        live_enabled=live_enabled,
        passed=passed,
        gates=gates,
        issues=issues,
        state=state,
    )


def build_promotion_state(
    decisions: list[SleevePromotionDecision],
    *,
    generated_at: str | None = None,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "generated_at": generated_at or _now_iso(),
        "sleeves": {
            decision.sleeve: decision.state
            for decision in decisions
        },
    }


def _write_promotion_state_unlocked(
    path: str | Path,
    decisions: list[SleevePromotionDecision],
    *,
    owner_approval: dict | None = None,
    owner_approval_envelope_ref: str | None = None,
    owner_approval_envelope_sha256: str | None = None,
    now: datetime.datetime | None = None,
) -> Path:
    """Persist promotion decisions; live eligibility requires owner approval.

    Paper-only records stay autonomous.  Any decision that would mark a
    sleeve ``tiny_live_eligible`` or live-enabled refuses closed unless a
    current account_owner approval artifact verifies against the exact write:
    the resulting payload digest, the resolved output path, and every gated
    decision's full canonical state digest plus its requested privilege
    transition.  Nothing is written before full approval validation.
    """

    state_path = Path(path).resolve()
    moment = now or datetime.datetime.now(tz=UTC)
    payload = build_promotion_state(
        decisions, generated_at=moment.isoformat(timespec="seconds")
    )
    serialized = json.dumps(payload, indent=2)
    gated = [
        decision
        for decision in decisions
        if decision.stage == "tiny_live_eligible" or decision.live_enabled
    ]
    if gated:
        from tradingagents.policy.owner_approval import (
            OwnerApprovalError,
            consume_owner_approval,
            finalize_owner_approval_prepare,
            owner_approval_prepare_path,
            owner_approval_prepare_recovery_matches,
            owner_prepare_has_exact_consumption,
            prepared_transaction_binding_sha256,
            prepared_transaction_sha256,
            read_owner_approval_prepare,
            transaction_binding_sha256,
            verify_owner_approval_structure,
            write_owner_approval_prepare,
        )

        # ``moment`` remains the deterministic evidence/output timestamp.  A
        # fresh privileged write instead uses a private policy clock, which a
        # public caller cannot set through ``now``.
        authority_moment = _owner_approval_authority_utc_now()
        payload_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        before = state_path.read_bytes() if state_path.exists() else b""
        recovery_identity = {
            "operation": "promotion_state_write",
            "output_path": str(state_path),
            "risk_envelope_ref": owner_approval_envelope_ref,
            "risk_envelope_sha256": owner_approval_envelope_sha256,
            "canonical_before_sha256": hashlib.sha256(before).hexdigest(),
            "canonical_before_kind": "present" if state_path.exists() else "absent",
            "gated_decisions": [
                {
                    "sleeve": decision.sleeve,
                    "state_sha256": _decision_state_sha256(decision),
                    "stage": decision.stage,
                    "live_enabled": decision.live_enabled,
                }
                for decision in gated
            ],
        }
        prepare_path = owner_approval_prepare_path(state_path)
        prepared = read_owner_approval_prepare(prepare_path)
        recovery_prepare = owner_approval_prepare_recovery_matches(
            prepare_path, recovery_identity=recovery_identity
        )
        if prepared is not None and recovery_prepare is None:
            raise ValueError(
                "owner approval prepare does not match this promotion-state write"
            )
        if recovery_prepare is not None:
            if not owner_prepare_has_exact_consumption(prepare_path):
                raise OwnerApprovalError(
                    "prepared promotion-state write has no exact owner approval consumption"
                )
            stored_serialized = recovery_prepare["transaction"].get("serialized_output")
            stored_sha256 = recovery_prepare["transaction"].get(
                "canonical_after_sha256"
            )
            if (
                type(stored_serialized) is not str
                or hashlib.sha256(stored_serialized.encode("utf-8")).hexdigest()
                != stored_sha256
            ):
                raise OwnerApprovalError(
                    "prepared promotion-state output is malformed"
                )
            if state_path.exists() and state_path.read_bytes() != stored_serialized.encode(
                "utf-8"
            ):
                raise ValueError("prepared promotion-state output does not match")
            if not state_path.exists():
                atomic_write_text(state_path, stored_serialized)
            finalize_owner_approval_prepare(prepare_path)
            return state_path
        subject, source_binding, purpose = _write_promotion_subject_and_source(
            gated,
            output_path=state_path,
            payload_sha256=payload_sha256,
            envelope_ref=owner_approval_envelope_ref,
            envelope_sha256=owner_approval_envelope_sha256,
        )
        transaction = {
            "operation": "promotion_state_write",
            "subject": subject,
            "source_binding": source_binding,
            "risk_envelope_ref": owner_approval_envelope_ref,
            "risk_envelope_sha256": owner_approval_envelope_sha256,
            "canonical_before_sha256": hashlib.sha256(before).hexdigest(),
            "canonical_before_kind": "present" if state_path.exists() else "absent",
            "canonical_after_sha256": payload_sha256,
            "output_path": str(state_path),
            "serialized_output": serialized,
            "recovery_identity": recovery_identity,
        }
        try:
            if (
                owner_approval is None
                or not owner_approval_envelope_ref
                or not owner_approval_envelope_sha256
            ):
                raise OwnerApprovalError("owner approval required")
            parsed = verify_owner_approval_structure(
                approval=owner_approval,
                expected_action="live_promotion",
                subject=subject,
                source_binding=source_binding,
                now=authority_moment,
                purpose=purpose,
            )
            envelope = parsed["risk_envelope_binding"]
            if (
                envelope["ref"] != owner_approval_envelope_ref
                or envelope["sha256"] != owner_approval_envelope_sha256
            ):
                raise OwnerApprovalError(
                    "owner approval risk envelope binding does not match this request"
                )
            binding = transaction_binding_sha256(
                approval_id=parsed["approval_id"],
                action=parsed["action"],
                purpose=purpose,
                subject=subject,
                risk_envelope_ref=owner_approval_envelope_ref,
                risk_envelope_sha256=owner_approval_envelope_sha256,
            )
            prepared_binding = prepared_transaction_binding_sha256(
                transaction_binding_sha256=binding,
                transaction_sha256=prepared_transaction_sha256(transaction),
            )
            written_binding = write_owner_approval_prepare(
                prepare_path,
                approval_id=parsed["approval_id"],
                action=parsed["action"],
                purpose=purpose,
                transaction_binding_sha256=binding,
                transaction=transaction,
                now=authority_moment,
            )
            if written_binding != prepared_binding:
                raise OwnerApprovalError(
                    "owner approval prepare binding does not match this promotion-state write"
                )
            consume_owner_approval(
                approval_id=parsed["approval_id"],
                action=parsed["action"],
                purpose=purpose,
                transaction_binding_sha256=binding,
                prepared_transaction_binding_sha256=prepared_binding,
                now=authority_moment,
            )
        except OwnerApprovalError:
            raise
    atomic_write_text(state_path, serialized)
    if gated:
        finalize_owner_approval_prepare(prepare_path)
    return state_path


def write_promotion_state(
    path: str | Path,
    decisions: list[SleevePromotionDecision],
    *,
    owner_approval: dict | None = None,
    owner_approval_envelope_ref: str | None = None,
    owner_approval_envelope_sha256: str | None = None,
    now: datetime.datetime | None = None,
) -> Path:
    """Serialize every promotion-state replacement per output.

    The state lock covers paper-only writes as well as owner-gated prepare,
    consumption, output write, and prepare retirement.  A competing autonomous
    writer can therefore never land between one gated writer's bound before
    image and its output/recovery completion.
    """

    # Imported lazily to avoid a module-import cycle; the lock protocol is
    # already the canonical per-promotion-state descriptor-safe lock.
    from tradingagents.policy.promotion_sync import promotion_state_lock

    state_path = Path(path).resolve()
    with promotion_state_lock(state_path):
        return _write_promotion_state_unlocked(
            state_path,
            decisions,
            owner_approval=owner_approval,
            owner_approval_envelope_ref=owner_approval_envelope_ref,
            owner_approval_envelope_sha256=owner_approval_envelope_sha256,
            now=now,
        )


def _decision_state_sha256(decision) -> str:
    canonical = json.dumps(
        dict(decision.state), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_promotion_subject_and_source(
    gated: list,
    *,
    output_path: Path,
    payload_sha256: str,
    envelope_ref: str | None,
    envelope_sha256: str | None,
):
    subject = {
        "kind": "promotion_state_write",
        "output_path": str(output_path),
        "payload_sha256": payload_sha256,
        "decisions": sorted(
            (
                {
                    "sleeve": decision.sleeve,
                    "stage": decision.stage,
                    "live_enabled": bool(decision.live_enabled),
                    "state_sha256": _decision_state_sha256(decision),
                }
                for decision in gated
            ),
            key=lambda item: item["sleeve"],
        ),
    }
    source_binding = {
        "writer": "policy.promotion.write_promotion_state",
        "risk_envelope_ref": envelope_ref,
        "risk_envelope_sha256": envelope_sha256,
    }
    purpose = f"promotion_state_write:{output_path}:{payload_sha256}"
    return subject, source_binding, purpose


def _write_owner_approval_request(
    gated: list,
    *,
    output_path: Path,
    payload_sha256: str,
    owner_approval: dict | None,
    envelope_ref: str | None,
    envelope_sha256: str | None,
    now: datetime.datetime,
) -> tuple[dict, dict, str]:
    subject, source_binding, purpose = _write_promotion_subject_and_source(
        gated,
        output_path=output_path,
        payload_sha256=payload_sha256,
        envelope_ref=envelope_ref,
        envelope_sha256=envelope_sha256,
    )
    return subject, source_binding, purpose
