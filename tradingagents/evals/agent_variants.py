"""Agent variant registration convention and scoreboard.

The Agent Intelligence Ledger keys every forecast, score, and influence
weight by the ``agent`` string. That makes agent evolution cheap: a prompt
revision, model route, toolset, or context policy variant is just a new
agent name that earns (or loses) influence through the exact same audited
resolution pipeline as the base roles — no new authority, no new storage.

This module pins the naming convention so variants stay machine-readable::

    <role>::<prompt_version>+<model_route>+<toolset>+<context_policy>

e.g. ``market_analyst::pv2+sonnet45+default+lean_ctx``. Plain role names
(no ``::``) remain the baseline. Malformed variant strings are treated as
plain agent names rather than rejected, so foreign ledger rows never break
the scoreboard.

Everything here is analysis-only; the scoreboard ranks research influence
and can never touch live gates, sizing, or order paths.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from tradingagents.evals.agent_intelligence_ledger import (
    LEDGER_FORBIDDEN_EFFECTS,
    AgentForecast,
    agent_influence_weights,
)

VARIANT_SEPARATOR = "::"
FIELD_SEPARATOR = "+"
EARNED_WEIGHT_STATES = ("earned_weight", "contextual_earned_weight")

_ALLOWED_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.")


@dataclass(frozen=True)
class AgentVariantSpec:
    """One registered agent variant: a role plus what was varied."""

    role: str
    prompt_version: str
    model_route: str
    toolset: str = "default"
    context_policy: str = "default"

    @property
    def agent_name(self) -> str:
        fields = FIELD_SEPARATOR.join(
            (self.prompt_version, self.model_route, self.toolset, self.context_policy)
        )
        return f"{self.role}{VARIANT_SEPARATOR}{fields}"


def _part(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return "".join(char for char in normalized if char in _ALLOWED_CHARS)


def variant_agent_name(
    *,
    role: str,
    prompt_version: str,
    model_route: str,
    toolset: str = "default",
    context_policy: str = "default",
) -> str:
    """Build the canonical ledger agent name for a variant."""

    parts = {
        "role": _part(role),
        "prompt_version": _part(prompt_version),
        "model_route": _part(model_route),
        "toolset": _part(toolset),
        "context_policy": _part(context_policy),
    }
    for field_name, value in parts.items():
        if not value:
            raise ValueError(f"variant {field_name} must be non-empty after normalization")
    return AgentVariantSpec(**parts).agent_name


def parse_variant_agent_name(name: str) -> AgentVariantSpec | None:
    """Parse a ledger agent name; ``None`` means it is a plain (baseline) agent."""

    raw = str(name or "")
    if VARIANT_SEPARATOR not in raw:
        return None
    role_raw, _, tail = raw.partition(VARIANT_SEPARATOR)
    fields = tail.split(FIELD_SEPARATOR)
    if len(fields) != 4:
        return None
    role = _part(role_raw)
    normalized = [_part(field) for field in fields]
    if not role or any(not field for field in normalized):
        return None
    return AgentVariantSpec(role, *normalized)


def base_role(name: str) -> str:
    """The role a variant competes in; plain agent names map to themselves."""

    spec = parse_variant_agent_name(name)
    return spec.role if spec else str(name or "")


def _weight_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    try:
        weight = Decimal(str(entry.get("weight", "1.00")))
    except (InvalidOperation, ValueError):
        weight = Decimal("1.00")
    return (
        entry.get("state") not in EARNED_WEIGHT_STATES,
        -weight,
        -int(entry.get("resolved_count") or 0),
        str(entry.get("agent") or ""),
    )


def variant_scoreboard(
    forecasts: Sequence[AgentForecast],
    *,
    min_resolved: int = 3,
) -> dict[str, Any]:
    """Rank agent variants per role on resolved-forecast evidence.

    Earned entries (enough resolved history to move influence) rank ahead of
    unproven ones; within that, higher bounded weight wins. A role only gets
    a ``leader`` when its top entry actually earned its weight.
    """

    weights = agent_influence_weights(forecasts, min_resolved=min_resolved)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for agent_name in sorted(weights["agents"]):
        item = weights["agents"][agent_name]
        spec = parse_variant_agent_name(agent_name)
        entry = {
            "agent": agent_name,
            "is_baseline": spec is None,
            "variant": asdict(spec) if spec else None,
            "weight": str(item.get("weight", "1.00")),
            "state": str(item.get("state", "unknown")),
            "resolved_count": int(item.get("resolved_count") or 0),
            "accuracy": item.get("accuracy"),
            "average_brier_score": item.get("average_brier_score"),
        }
        grouped.setdefault(spec.role if spec else agent_name, []).append(entry)
    roles: dict[str, Any] = {}
    for role in sorted(grouped):
        entries = sorted(grouped[role], key=_weight_sort_key)
        leader = (
            entries[0]["agent"]
            if entries and entries[0]["state"] in EARNED_WEIGHT_STATES
            else None
        )
        roles[role] = {
            "variant_count": len(entries),
            "variants": entries,
            "leader": leader,
        }
    return {
        "kind": "agent_variant_scoreboard",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(LEDGER_FORBIDDEN_EFFECTS),
        "min_resolved": max(1, int(min_resolved)),
        "role_count": len(roles),
        "roles": roles,
    }
