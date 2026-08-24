from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionClass(str, Enum):
    TRADE_DECISION = "trade_decision"
    STRATEGY_CHANGE = "strategy_change"
    RISK_CHANGE = "risk_change"
    PROMOTION_CHANGE = "promotion_change"
    LIVE_PROMOTION = "live_promotion"
    RISK_ENVELOPE_EXPANSION = "risk_envelope_expansion"
    FREEZE = "freeze"
    REPAIR = "repair"
    VERIFY = "verify"
    REARM_REQUEST = "rearm_request"
    REARM_ISSUE = "rearm_issue"
    ORDER_SUBMIT = "order_submit"
    CAPITAL_CHANGE = "capital_change"
    ACCOUNT_IDENTITY_CHANGE = "account_identity_change"
    CREDENTIAL_CHANGE = "credential_change"
    CHARTER_CHANGE = "charter_change"


@dataclass(frozen=True)
class AuthorityVerdict:
    action: ActionClass
    allowed: bool
    human_required: bool
    owner_role: str
    reason: str


_MACHINE_OWNERS = {
    ActionClass.TRADE_DECISION: (
        "portfolio_executive",
        "owned by the autonomous experiment charter for research and paper decisions",
    ),
    ActionClass.STRATEGY_CHANGE: (
        "strategy_learning",
        "owned by the autonomous experiment charter",
    ),
    # Scoped: tightening/reducing risk and paper-only promotion records only.
    # Envelope expansion is RISK_ENVELOPE_EXPANSION; live eligibility or
    # promotion into live is LIVE_PROMOTION; both require account_owner
    # approval and are never authorized by these machine-owned classes.
    ActionClass.RISK_CHANGE: (
        "portfolio_executive",
        "machine-operable only for genuine risk reduction or tightening; any "
        "expansion requires account_owner approval",
    ),
    ActionClass.PROMOTION_CHANGE: (
        "strategy_learning",
        "machine-operable only for autonomous paper-only promotion records; "
        "live eligibility/promotion requires account_owner approval",
    ),
    ActionClass.FREEZE: (
        "integrity_verifier",
        "owned by the autonomous experiment charter",
    ),
    ActionClass.REPAIR: (
        "reliability_controller",
        "owned by the autonomous experiment charter",
    ),
    ActionClass.VERIFY: (
        "integrity_verifier",
        "owned by the autonomous experiment charter",
    ),
    ActionClass.REARM_REQUEST: (
        "reliability_controller",
        "owned by the autonomous recovery charter",
    ),
    ActionClass.REARM_ISSUE: (
        "integrity_verifier",
        "owned by the autonomous recovery charter",
    ),
    ActionClass.ORDER_SUBMIT: (
        "execution_operator",
        "paper submission is machine-operable; each live submission still "
        "requires a current account_owner approval at the unified go-live guard",
    ),
}
# Privileged transitions that a machine can request but never self-approve:
# they execute only with a separately owner-issued, current approval artifact.
_OWNER_APPROVAL_ACTIONS = {
    ActionClass.LIVE_PROMOTION: (
        "entering live eligibility, promotion into live, and normal-live "
        "activation require a current account_owner approval artifact"
    ),
    ActionClass.RISK_ENVELOPE_EXPANSION: (
        "capital-at-risk or risk-envelope expansion requires a current "
        "account_owner approval artifact"
    ),
}
_EXTERNAL_HUMAN_ACTIONS = {
    action: (
        "requires external account authority held only by the account_owner"
        if action is ActionClass.CAPITAL_CHANGE
        else "requires external account or charter authority"
    )
    for action in (
        ActionClass.CAPITAL_CHANGE,
        ActionClass.ACCOUNT_IDENTITY_CHANGE,
        ActionClass.CREDENTIAL_CHANGE,
        ActionClass.CHARTER_CHANGE,
    )
}


def authority_for(action: ActionClass | str) -> AuthorityVerdict:
    normalized = action if isinstance(action, ActionClass) else ActionClass(action)
    entry = _MACHINE_OWNERS.get(normalized)
    if entry is not None:
        owner_role, reason = entry
        return AuthorityVerdict(
            action=normalized,
            allowed=True,
            human_required=False,
            owner_role=owner_role,
            reason=reason,
        )
    privileged_reason = _OWNER_APPROVAL_ACTIONS.get(normalized)
    if privileged_reason is not None:
        return AuthorityVerdict(
            action=normalized,
            allowed=False,
            human_required=True,
            owner_role="account_owner",
            reason=f"owner approval required: {privileged_reason}",
        )
    external_reason = _EXTERNAL_HUMAN_ACTIONS.get(normalized)
    if external_reason is not None:
        return AuthorityVerdict(
            action=normalized,
            allowed=False,
            human_required=True,
            owner_role="account_owner",
            reason=external_reason,
        )
    raise ValueError(f"unclassified action: {normalized.value}")
