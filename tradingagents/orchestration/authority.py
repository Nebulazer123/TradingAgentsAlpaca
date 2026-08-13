from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionClass(str, Enum):
    TRADE_DECISION = "trade_decision"
    STRATEGY_CHANGE = "strategy_change"
    RISK_CHANGE = "risk_change"
    PROMOTION_CHANGE = "promotion_change"
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
    ActionClass.TRADE_DECISION: "portfolio_executive",
    ActionClass.STRATEGY_CHANGE: "strategy_learning",
    ActionClass.RISK_CHANGE: "portfolio_executive",
    ActionClass.PROMOTION_CHANGE: "strategy_learning",
    ActionClass.FREEZE: "integrity_verifier",
    ActionClass.REPAIR: "reliability_controller",
    ActionClass.VERIFY: "integrity_verifier",
    ActionClass.REARM_REQUEST: "reliability_controller",
    ActionClass.REARM_ISSUE: "integrity_verifier",
    ActionClass.ORDER_SUBMIT: "execution_operator",
}
_HUMAN_ACTIONS = {
    ActionClass.CAPITAL_CHANGE,
    ActionClass.ACCOUNT_IDENTITY_CHANGE,
    ActionClass.CREDENTIAL_CHANGE,
    ActionClass.CHARTER_CHANGE,
}


def authority_for(action: ActionClass | str) -> AuthorityVerdict:
    normalized = action if isinstance(action, ActionClass) else ActionClass(action)
    owner = _MACHINE_OWNERS.get(normalized)
    if owner is not None:
        return AuthorityVerdict(
            action=normalized,
            allowed=True,
            human_required=False,
            owner_role=owner,
            reason="owned by the autonomous experiment charter",
        )
    if normalized in _HUMAN_ACTIONS:
        return AuthorityVerdict(
            action=normalized,
            allowed=False,
            human_required=True,
            owner_role="account_owner",
            reason="requires external account or charter authority",
        )
    raise ValueError(f"unclassified action: {normalized.value}")
