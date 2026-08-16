"""Deterministic authority resolution for loss-exit decisions.

Research can add context to a loss review, but it cannot override a valid
pre-registered mechanical exit rule. This module is deliberately local-only:
it performs no network, broker, or model calls.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingagents.policy.exit_policy import (
    POLICY_REASON_CODES,
    POLICY_REASON_RULE_IDS,
    verify_pre_registered_exit_policy_review,
)

POLICY_EXIT_REASONS = POLICY_REASON_CODES
POLICY_EXIT_RULE_IDS = POLICY_REASON_RULE_IDS
AUTHORITY_RECORD_FIELDS = (
    "symbol",
    "decision_id",
    "allowed",
    "policy_rule_exit",
    "allowed_exit_reason",
    "allowed_exit_reason_source",
    "exit_policy_rule",
    "exit_policy_rationale",
    "current_price",
    "proposed_limit_price",
    "average_entry_price",
    "quantity",
    "unrealized_plpc",
    "holding_period_trading_days",
    "opened_at",
    "evidence_generated_at",
    "exit_policy_loss_pct",
    "blockers",
    "blocked_reasons",
    "source_packet_ids",
    "source_identity",
)


@dataclass(frozen=True)
class ExitAuthorityVerdict:
    exit_allowed: bool
    trade_decision_resolved: bool
    execution_eligible: bool
    execution_blockers: tuple[str, ...]
    authority_source: str
    requires_additional_decision: bool
    decision_owner: str
    reason: str

    @property
    def allowed(self) -> bool:
        """Compatibility alias for callers that predate BOARD decisions."""
        return self.exit_allowed


@dataclass(frozen=True)
class CurrentSupervisorReviewBinding:
    """One captured current supervisor packet, bound without a second read."""

    path: str
    sha256: str
    size_bytes: int
    review: Mapping[str, Any]


def capture_current_supervisor_review(
    *,
    packet_path: str | Path,
    packet_bytes: bytes,
    evidence_root: str | Path,
) -> CurrentSupervisorReviewBinding:
    """Capture the exact current review bytes for an authorizing comparison.

    The caller passes bytes it already read from the current supervisor packet.
    This function never opens the packet path, so a later file replacement
    cannot change the review that is compared with the authenticated decision.
    """
    if not isinstance(packet_bytes, bytes):
        raise ValueError("current supervisor packet must be captured as bytes")
    root = Path(evidence_root).resolve()
    supplied = Path(packet_path).resolve()
    try:
        relative = supplied.relative_to(root)
    except ValueError as exc:
        raise ValueError("current supervisor packet must be inside evidence root") from exc
    try:
        packet = json.loads(packet_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("current supervisor packet bytes are not JSON") from exc
    if not isinstance(packet, Mapping):
        raise ValueError("current supervisor packet bytes are not an object")
    evidence = packet.get("evidence")
    review = evidence.get("loss_exit_review") if isinstance(evidence, Mapping) else None
    if not isinstance(review, Mapping):
        raise ValueError("current supervisor packet lacks loss_exit_review")
    return CurrentSupervisorReviewBinding(
        path=relative.as_posix(),
        sha256=hashlib.sha256(packet_bytes).hexdigest(),
        size_bytes=len(packet_bytes),
        review=dict(review),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bounded_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item) for item in value if str(item).strip()]
    return []


def bounded_exit_authority_record(review: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the bounded authority facts that must survive packet compaction."""
    source = _mapping(review)
    return {
        "symbol": _text(source.get("symbol")).upper(),
        "decision_id": _text(source.get("decision_id")),
        "allowed": source.get("allowed") is True,
        "policy_rule_exit": source.get("policy_rule_exit") is True,
        "allowed_exit_reason": _text(source.get("allowed_exit_reason")),
        "allowed_exit_reason_source": _text(source.get("allowed_exit_reason_source")),
        "exit_policy_rule": _text(source.get("exit_policy_rule")),
        "exit_policy_rationale": _text(source.get("exit_policy_rationale")),
        "current_price": _text(source.get("current_price")),
        "proposed_limit_price": _text(source.get("proposed_limit_price")),
        "average_entry_price": _text(source.get("average_entry_price")),
        "quantity": _text(source.get("quantity")),
        "unrealized_plpc": _text(source.get("unrealized_plpc")),
        "holding_period_trading_days": _text(source.get("holding_period_trading_days")),
        "opened_at": _text(source.get("opened_at")),
        "evidence_generated_at": _text(source.get("evidence_generated_at")),
        "exit_policy_loss_pct": _text(source.get("exit_policy_loss_pct")),
        "blockers": _bounded_strings(source.get("blockers")),
        "blocked_reasons": _bounded_strings(source.get("blocked_reasons")),
        "source_packet_ids": _bounded_strings(source.get("source_packet_ids")),
        "source_identity": "hourly_supervisor.loss_exit_review",
    }


def _policy_blockers(review: Mapping[str, Any]) -> str | None:
    for key in ("blockers", "blocked_reasons"):
        if key not in review:
            return f"pre-registered policy exit is missing required {key}"
        value = review.get(key)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return f"pre-registered policy exit has malformed {key}"
        if any(str(item).strip() for item in value):
            return f"pre-registered policy exit has {key}"
    return None


def _source_packet_ids_issue(review: Mapping[str, Any]) -> str | None:
    if "source_packet_ids" not in review:
        return None
    value = review.get("source_packet_ids")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return "pre-registered policy exit has malformed source_packet_ids"
    return None


def _invalid_policy_verdict(reason: str) -> ExitAuthorityVerdict:
    return ExitAuthorityVerdict(
        exit_allowed=False,
        trade_decision_resolved=False,
        execution_eligible=False,
        execution_blockers=("pre-registered policy rule is invalid",),
        authority_source="invalid_pre_registered_policy_rule",
        requires_additional_decision=False,
        decision_owner="portfolio_executive",
        reason=reason,
    )


def parse_pre_registered_exit_policy_candidate(
    supervisor_review: Mapping[str, Any] | Any,
) -> dict[str, str] | None:
    """Parse a review-only mechanical-policy *candidate*, never authority.

    Research and recovery evidence sometimes need to preserve the stated
    policy rule for lineage.  They must not call :func:`resolve_exit_authority`
    with a detached review just to obtain an ``allowed`` result: final
    authorization additionally binds a fresh broker position and clock.  This
    helper deliberately returns only static candidate facts and has no
    ``allowed`` field.
    """
    review = _mapping(supervisor_review)
    reason = _text(review.get("allowed_exit_reason"))
    if (
        review.get("allowed") is not True
        or review.get("policy_rule_exit") is not True
        or reason not in POLICY_EXIT_RULE_IDS
    ):
        return None
    if any(
        not _text(review.get(field))
        for field in (
            "symbol",
            "decision_id",
            "allowed_exit_reason_source",
            "exit_policy_rule",
            "exit_policy_rationale",
        )
    ):
        return None
    if _policy_blockers(review) is not None or _source_packet_ids_issue(review) is not None:
        return None
    rule = _text(review.get("exit_policy_rule"))
    if rule not in POLICY_EXIT_RULE_IDS[reason]:
        return None
    return {
        "symbol": _text(review.get("symbol")).upper(),
        "decision_id": _text(review.get("decision_id")),
        "allowed_exit_reason": reason,
        "allowed_exit_reason_source": _text(
            review.get("allowed_exit_reason_source")
        ),
        "exit_policy_rule": rule,
        "exit_policy_rationale": _text(review.get("exit_policy_rationale")),
    }


def _requires_board_decision(advisory: Mapping[str, Any]) -> bool:
    if advisory.get("requires_board_decision") is True:
        return True
    candidate = advisory.get("loss_exit_candidate")
    return isinstance(candidate, Mapping) and candidate.get("requires_board_decision") is True


def resolve_exit_authority(
    *,
    supervisor_review: Mapping[str, Any] | Any,
    advisory_analysis: Mapping[str, Any] | Any | None,
    board_decision: Mapping[str, Any] | Any | None = None,
    decision_ledger_root: str | Path | None = None,
    decision_evidence_root: str | Path | None = None,
    current_supervisor_binding: CurrentSupervisorReviewBinding | None = None,
    current_position: Mapping[str, Any] | None = None,
    now: Any = None,
) -> ExitAuthorityVerdict:
    """Resolve loss-exit authority without granting research execution power."""
    review = _mapping(supervisor_review)
    advisory = _mapping(advisory_analysis)
    reason = _text(review.get("allowed_exit_reason"))
    policy_claimed = review.get("policy_rule_exit") is not False or reason in POLICY_EXIT_REASONS
    if policy_claimed:
        if review.get("allowed") is not True or review.get("policy_rule_exit") is not True:
            return _invalid_policy_verdict(
                "pre-registered policy exit requires allowed and policy_rule_exit to be literal True"
            )
        if reason not in POLICY_EXIT_RULE_IDS:
            return _invalid_policy_verdict("pre-registered policy exit has an unknown reason")
        missing = [
            field
            for field in (
                "symbol",
                "decision_id",
                "allowed_exit_reason_source",
                "exit_policy_rule",
                "exit_policy_rationale",
            )
            if not _text(review.get(field))
        ]
        if missing:
            return _invalid_policy_verdict(
                "pre-registered policy exit is missing required fields: "
                + ", ".join(missing)
            )
        blocker_issue = _policy_blockers(review)
        if blocker_issue is not None:
            return _invalid_policy_verdict(blocker_issue)
        source_packet_ids_issue = _source_packet_ids_issue(review)
        if source_packet_ids_issue is not None:
            return _invalid_policy_verdict(source_packet_ids_issue)
        rule = _text(review.get("exit_policy_rule"))
        if rule not in POLICY_EXIT_RULE_IDS[reason]:
            return _invalid_policy_verdict(
                f"pre-registered policy reason {reason} does not match rule {rule or 'missing'}"
            )
        if (
            not isinstance(current_position, Mapping)
            or not isinstance(now, datetime.datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            return _invalid_policy_verdict(
                "pre-registered policy exit requires a current broker position and current clock"
            )
        if verify_pre_registered_exit_policy_review(
            review,
            current_position=current_position,
            now=now,
        ) is None:
            return _invalid_policy_verdict(
                "pre-registered policy exit does not match fresh policy evaluation"
            )
        return ExitAuthorityVerdict(
            exit_allowed=True,
            trade_decision_resolved=True,
            execution_eligible=True,
            execution_blockers=(),
            authority_source="pre_registered_policy_rule",
            requires_additional_decision=False,
            decision_owner="execution_operator",
            reason=f"pre-registered exit rule remains authoritative: {reason}",
        )

    if _requires_board_decision(advisory):
        verified = _verified_board_decision(
            board_decision=board_decision,
            decision_ledger_root=decision_ledger_root,
            decision_evidence_root=decision_evidence_root,
            now=now,
        )
        if verified is not None and _board_decision_matches_supervisor(
            verified, review, current_supervisor_binding
        ):
            return ExitAuthorityVerdict(
                exit_allowed=verified.exit_allowed,
                trade_decision_resolved=True,
                execution_eligible=verified.execution_eligible,
                execution_blockers=verified.execution_blockers,
                authority_source="autonomous_portfolio_board",
                requires_additional_decision=False,
                decision_owner="portfolio_executive",
                reason=(
                    "autonomous portfolio BOARD recorded a SELL decision; "
                    "a separate execution intent is still required"
                    if verified.decision == "SELL"
                    else "autonomous portfolio BOARD recorded a HOLD decision"
                ),
            )
        return ExitAuthorityVerdict(
            exit_allowed=False,
            trade_decision_resolved=False,
            execution_eligible=False,
            execution_blockers=("discretionary loss exit requires an internal portfolio decision",),
            authority_source="advisory_research",
            requires_additional_decision=True,
            decision_owner="portfolio_executive",
            reason="discretionary loss exit requires an internal portfolio decision",
        )
    return ExitAuthorityVerdict(
        exit_allowed=review.get("allowed") is True and review.get("execution_eligible") is True,
        trade_decision_resolved=review.get("allowed") is True,
        execution_eligible=review.get("execution_eligible") is True,
        execution_blockers=tuple(
            item for item in _bounded_strings(review.get("execution_blockers"))
        ) or (() if review.get("execution_eligible") is True else ("execution eligibility is unverified",)),
        authority_source="supervisor_review",
        requires_additional_decision=False,
        decision_owner="portfolio_executive",
        reason=_text(review.get("allowed_exit_reason_source")) or "supervisor review",
    )


def _board_decision_matches_supervisor(
    board_decision: Any,
    review: Mapping[str, Any],
    current_supervisor_binding: CurrentSupervisorReviewBinding | None,
) -> bool:
    """Only accept a verified decision for this exact supervisor review."""
    supervisor_packet = getattr(board_decision, "supervisor_packet", None)
    return (
        isinstance(current_supervisor_binding, CurrentSupervisorReviewBinding)
        and current_supervisor_binding.review == review
        and supervisor_packet is not None
        and current_supervisor_binding.path == getattr(supervisor_packet, "path", None)
        and current_supervisor_binding.sha256 == getattr(supervisor_packet, "sha256", None)
        and current_supervisor_binding.size_bytes == getattr(supervisor_packet, "size_bytes", None)
        and getattr(board_decision, "symbol", None) == _text(review.get("symbol")).upper()
        and getattr(board_decision, "supervisor_decision_id", None)
        == _text(review.get("decision_id"))
        and getattr(board_decision, "trade_decision_resolved", None) is True
        and getattr(board_decision, "analysis_only", None) is True
        and getattr(board_decision, "execution_authority", None) == "none"
        and getattr(board_decision, "can_submit_orders", None) is False
    )


def _verified_board_decision(
    *,
    board_decision: Mapping[str, Any] | Any | None,
    decision_ledger_root: str | Path | None,
    decision_evidence_root: str | Path | None,
    now: Any,
) -> Any | None:
    """Authenticate only a caller-supplied ledger packet reference.

    The caller owns both roots; packet input may name a packet ID only.  This
    prevents advisory research or a copied evidence tree from selecting its
    own trust boundary.
    """
    candidate = _mapping(board_decision)
    if (
        set(candidate) != {"ledger_packet_id"}
        or not isinstance(candidate.get("ledger_packet_id"), str)
        or not candidate["ledger_packet_id"].strip()
        or decision_ledger_root is None
        or decision_evidence_root is None
    ):
        return None
    try:
        from tradingagents.policy.loss_board_decision import (
            verify_autonomous_loss_board_decision,
        )

        return verify_autonomous_loss_board_decision(
            ledger_root=decision_ledger_root,
            ledger_packet_id=candidate["ledger_packet_id"],
            evidence_root=decision_evidence_root,
            now=now,
        )
    except (OSError, ValueError, TypeError):
        return None
