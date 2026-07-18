"""Deterministic authority resolution for loss-exit decisions.

Research can add context to a loss review, but it cannot override a valid
pre-registered mechanical exit rule. This module is deliberately local-only:
it performs no network, broker, or model calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tradingagents.policy.exit_policy import POLICY_REASON_CODES, POLICY_REASON_RULE_IDS

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
    "blockers",
    "blocked_reasons",
    "source_packet_ids",
    "source_identity",
)


@dataclass(frozen=True)
class ExitAuthorityVerdict:
    allowed: bool
    authority_source: str
    requires_additional_decision: bool
    decision_owner: str
    reason: str


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
        "blockers": _bounded_strings(source.get("blockers")),
        "blocked_reasons": _bounded_strings(source.get("blocked_reasons")),
        "source_packet_ids": _bounded_strings(source.get("source_packet_ids")),
        "source_identity": "hourly_supervisor.loss_exit_review",
    }


def _policy_blockers(review: Mapping[str, Any]) -> str | None:
    for key in ("blockers", "blocked_reasons"):
        value = review.get(key)
        if value is None:
            continue
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return f"pre-registered policy exit has malformed {key}"
        if any(str(item).strip() for item in value):
            return f"pre-registered policy exit has {key}"
    return None


def _invalid_policy_verdict(reason: str) -> ExitAuthorityVerdict:
    return ExitAuthorityVerdict(
        allowed=False,
        authority_source="invalid_pre_registered_policy_rule",
        requires_additional_decision=False,
        decision_owner="portfolio_executive",
        reason=reason,
    )


def _requires_board_decision(advisory: Mapping[str, Any]) -> bool:
    if advisory.get("requires_board_decision") is True:
        return True
    candidate = advisory.get("loss_exit_candidate")
    return isinstance(candidate, Mapping) and candidate.get("requires_board_decision") is True


def resolve_exit_authority(
    *,
    supervisor_review: Mapping[str, Any] | Any,
    advisory_analysis: Mapping[str, Any] | Any | None,
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
        rule = _text(review.get("exit_policy_rule"))
        if rule not in POLICY_EXIT_RULE_IDS[reason]:
            return _invalid_policy_verdict(
                f"pre-registered policy reason {reason} does not match rule {rule or 'missing'}"
            )
        return ExitAuthorityVerdict(
            allowed=True,
            authority_source="pre_registered_policy_rule",
            requires_additional_decision=False,
            decision_owner="execution_operator",
            reason=f"pre-registered exit rule remains authoritative: {reason}",
        )

    if _requires_board_decision(advisory):
        return ExitAuthorityVerdict(
            allowed=False,
            authority_source="advisory_research",
            requires_additional_decision=True,
            decision_owner="portfolio_executive",
            reason="discretionary loss exit requires an internal portfolio decision",
        )
    return ExitAuthorityVerdict(
        allowed=review.get("allowed") is True,
        authority_source="supervisor_review",
        requires_additional_decision=False,
        decision_owner="portfolio_executive",
        reason=_text(review.get("allowed_exit_reason_source")) or "supervisor review",
    )
