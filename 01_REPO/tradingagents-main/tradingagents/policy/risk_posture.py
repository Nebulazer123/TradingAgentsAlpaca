"""Risk-posture knobs for research and paper exploration.

This module deliberately avoids broker sizing and live-gate authority. Live
eligibility remains controlled by the risk envelope, promotion state, live
control state, dry-run evidence, and the unified live gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

VALID_RISK_POSTURES = frozenset(
    {"conservative", "balanced", "performance_seeking"}
)


@dataclass(frozen=True)
class RiskPosturePolicy:
    name: str
    environment: str
    paper_first_threshold: Decimal
    overnight_candidate_limit: int
    deep_research_top_n: int
    market_mirror_max_agents: int
    paid_model_route: str
    live_gate_relaxation_allowed: bool = False
    live_cap_multiplier: Decimal = Decimal("1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "environment": self.environment,
            "paper_first_threshold": str(self.paper_first_threshold),
            "overnight_candidate_limit": self.overnight_candidate_limit,
            "deep_research_top_n": self.deep_research_top_n,
            "market_mirror_max_agents": self.market_mirror_max_agents,
            "paid_model_route": self.paid_model_route,
            "live_gate_relaxation_allowed": self.live_gate_relaxation_allowed,
            "live_cap_multiplier": str(self.live_cap_multiplier),
        }


def normalize_risk_posture(value: object | None, *, default: str = "balanced") -> str:
    raw = str(value or default).strip().lower().replace("-", "_")
    if raw not in VALID_RISK_POSTURES:
        raise ValueError(
            "risk_posture must be one of: "
            + ", ".join(sorted(VALID_RISK_POSTURES))
        )
    return raw


def risk_posture_policy(
    value: object | None = None,
    *,
    environment: str = "paper",
) -> RiskPosturePolicy:
    env = environment.strip().lower()
    default = "conservative" if env == "live" else "balanced"
    name = normalize_risk_posture(value, default=default)
    policies = {
        "conservative": RiskPosturePolicy(
            name="conservative",
            environment=env,
            paper_first_threshold=Decimal("0.65"),
            overnight_candidate_limit=8,
            deep_research_top_n=3,
            market_mirror_max_agents=3,
            paid_model_route="disabled_by_default",
        ),
        "balanced": RiskPosturePolicy(
            name="balanced",
            environment=env,
            paper_first_threshold=Decimal("0.60"),
            overnight_candidate_limit=12,
            deep_research_top_n=5,
            market_mirror_max_agents=5,
            paid_model_route="cap_required",
        ),
        "performance_seeking": RiskPosturePolicy(
            name="performance_seeking",
            environment=env,
            paper_first_threshold=Decimal("0.55"),
            overnight_candidate_limit=20,
            deep_research_top_n=8,
            market_mirror_max_agents=9,
            paid_model_route="cap_required",
        ),
    }
    return policies[name]


def risk_posture_policy_from_config(
    config: Mapping[str, object],
    *,
    environment: str = "paper",
) -> RiskPosturePolicy:
    return risk_posture_policy(config.get("risk_posture"), environment=environment)
