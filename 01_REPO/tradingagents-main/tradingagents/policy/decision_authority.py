"""Deterministic authority resolution for loss-exit decisions.

Research can add context to a loss review, but it cannot override a valid
pre-registered mechanical exit rule. This module is deliberately local-only:
it performs no network, broker, or model calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tradingagents.policy.exit_policy import POLICY_REASON_CODES

POLICY_EXIT_REASONS = POLICY_REASON_CODES


@dataclass(frozen=True)
class ExitAuthorityVerdict:
    allowed: bool
    authority_source: str
    requires_additional_decision: bool
    decision_owner: str
    reason: str


def resolve_exit_authority(
    *,
    supervisor_review: Mapping[str, Any],
    advisory_analysis: Mapping[str, Any] | None,
) -> ExitAuthorityVerdict:
    """Resolve loss-exit authority without granting research execution power."""
    reason = str(supervisor_review.get("allowed_exit_reason") or "")
    policy_exit = (
        supervisor_review.get("allowed") is True
        and supervisor_review.get("policy_rule_exit") is True
        and reason in POLICY_EXIT_REASONS
    )
    if policy_exit:
        return ExitAuthorityVerdict(
            allowed=True,
            authority_source="pre_registered_policy_rule",
            requires_additional_decision=False,
            decision_owner="execution_operator",
            reason=f"pre-registered exit rule remains authoritative: {reason}",
        )

    advisory = advisory_analysis or {}
    if advisory.get("requires_board_decision") is True:
        return ExitAuthorityVerdict(
            allowed=False,
            authority_source="advisory_research",
            requires_additional_decision=True,
            decision_owner="portfolio_executive",
            reason="discretionary loss exit requires an internal portfolio decision",
        )
    return ExitAuthorityVerdict(
        allowed=bool(supervisor_review.get("allowed")),
        authority_source="supervisor_review",
        requires_additional_decision=False,
        decision_owner="portfolio_executive",
        reason=str(supervisor_review.get("allowed_exit_reason_source") or "supervisor review"),
    )
