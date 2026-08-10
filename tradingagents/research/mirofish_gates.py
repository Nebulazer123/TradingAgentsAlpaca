"""Advisory false-signal gates derived from the MiroFish behavioral-simulation report.

ADVISORY ONLY — NO EXECUTION AUTHORITY.

The MiroFish Stage-4 report ("## TradingAgents rule implications") prescribes four
gates/filters that TradingAgents should apply *before acting* on simulation-derived
or social-flow signals, plus a set of real-market validations that must pass first:

    1. Broker-Friction Gate   -> broker_confusion_index, buying_power_rejection_confusion
    2. Macro-Override Gate     -> macro_dominance_index overrides retail_flow_intensity
                                  during scheduled macro catalysts
    3. Bot-Convergence Filter  -> AI_bot_copycat_index; synchronized low-liquidity / off-peak
                                  spikes are mean-reversion / false-positive candidates
    4. Attribution-Error Filter-> false_signal_risk_index; cross-check social spikes against
                                  institutional confirmation and options_gamma_IV_pressure

This module translates those prescriptions into pure, deterministic, testable
evaluators. They DOWNGRADE or FLAG a candidate signal; they never size, submit,
promote, or authorize any order. They are intentionally NOT wired into the live
order path. A caller in the research/advisory layer may use
``evaluate_mirofish_gates`` to annotate a candidate with advisory verdicts before
deterministic policy (live_gate / risk_envelope) decides anything.

Index convention: every index is a normalized float in [0.0, 1.0] (0 = absent,
1 = maximal). The MiroFish report describes these indices qualitatively, so the
default thresholds below are conservative starting points and MUST be calibrated
against real telemetry (the report itself mandates real-market validation before
acting — see ``required_validations``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# --- Default thresholds (calibration-required; see module docstring) -----------
ELEVATED = 0.60  # index level at which a signal becomes advisory-suspect
DOMINANT = 0.50  # macro dominance floor before macro-override applies

EXECUTION_AUTHORITY = "none"

# Validations the report requires before any simulation-derived signal is acted on.
REQUIRED_VALIDATION_TASKS = {
    "broker_friction": "phantom_liquidity",  # social/blocked-trade volume vs executed flow
    "macro_override": "macro_attribution",  # isolate macro/yield move from retail-flow attribution
    "bot_convergence": "order_flow_toxicity",  # synchronized small/cancelled orders vs real depth
    "attribution_error": "macro_attribution",
}


def _f(value: Any) -> float:
    """Coerce an index to a clamped float in [0, 1]; missing/garbage -> 0.0."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if out != out:  # NaN
        return 0.0
    return max(0.0, min(1.0, out))


@dataclass(frozen=True)
class GateVerdict:
    gate: str
    action: str  # "allow" | "flag" | "suppress"
    triggered: bool
    reason: str
    inputs: dict[str, float] = field(default_factory=dict)


def broker_friction_gate(
    broker_confusion_index: float,
    buying_power_rejection_confusion: float,
    *,
    threshold: float = ELEVATED,
) -> GateVerdict:
    """Suppress retail-breakout signals when broker friction is the dominant explanation.

    The report's core lesson: high social volume around "blocked trades" / buying-power
    rejection is a *contrarian* indicator of available liquidity, not a breakout precursor.
    """
    bc = _f(broker_confusion_index)
    bp = _f(buying_power_rejection_confusion)
    inputs = {"broker_confusion_index": bc, "buying_power_rejection_confusion": bp}
    if bc >= threshold or bp >= threshold:
        return GateVerdict(
            "broker_friction",
            "suppress",
            True,
            (
                "Broker friction elevated (broker_confusion_index="
                f"{bc:.2f}, buying_power_rejection_confusion={bp:.2f}); retail breakout volume is "
                "likely phantom (blocked by margin haircuts / Reg T), not executable flow."
            ),
            inputs,
        )
    return GateVerdict("broker_friction", "allow", False, "Broker friction not elevated.", inputs)


def macro_override_gate(
    macro_dominance_index: float,
    retail_flow_intensity: float,
    *,
    scheduled_catalyst: bool = False,
    dominance_floor: float = DOMINANT,
) -> GateVerdict:
    """Suppress retail-flow attribution when macro dominates (esp. on a scheduled catalyst).

    When ``macro_dominance_index`` exceeds ``retail_flow_intensity`` during a scheduled
    macro window (jobs/CPI/PPI, Treasury auctions, FOMC), attributing a move to retail
    leverage is unreliable and should be downgraded.
    """
    md = _f(macro_dominance_index)
    rf = _f(retail_flow_intensity)
    inputs = {"macro_dominance_index": md, "retail_flow_intensity": rf}
    if md >= dominance_floor and md > rf:
        action = "suppress" if scheduled_catalyst else "flag"
        return GateVerdict(
            "macro_override",
            action,
            True,
            (
                f"Macro dominance ({md:.2f}) exceeds retail_flow_intensity ({rf:.2f})"
                + (" during a scheduled macro catalyst" if scheduled_catalyst else "")
                + "; retail-flow attribution is unreliable — downgrade PDT/retail-breakout confidence."
            ),
            inputs,
        )
    return GateVerdict("macro_override", "allow", False, "Macro does not override retail flow.", inputs)


def bot_convergence_gate(
    ai_bot_copycat_index: float,
    *,
    low_liquidity: bool = False,
    off_peak: bool = False,
    threshold: float = ELEVATED,
) -> GateVerdict:
    """Flag synchronized bot-copycat spikes as mean-reversion / false-positive candidates.

    Synchronized prompt-bot entry creates localized liquidity vacuums quickly faded by
    market makers; sudden spikes in low-liquidity names or off-peak hours should be treated
    as reversal candidates, not trend confirmation.
    """
    ai = _f(ai_bot_copycat_index)
    inputs = {"ai_bot_copycat_index": ai}
    if ai >= threshold and (low_liquidity or off_peak):
        ctx = ", ".join(
            label for label, on in (("low_liquidity", low_liquidity), ("off_peak", off_peak)) if on
        )
        return GateVerdict(
            "bot_convergence",
            "flag",
            True,
            (
                f"AI_bot_copycat_index elevated ({ai:.2f}) with {ctx}; treat the spike as a "
                "brittle synchronized-bot liquidity vacuum (mean-reversion candidate), not a breakout."
            ),
            inputs,
        )
    return GateVerdict("bot_convergence", "allow", False, "No brittle bot-convergence pattern.", inputs)


def attribution_error_gate(
    false_signal_risk_index: float,
    *,
    social_spike: bool = False,
    institutional_confirmation: bool = False,
    options_gamma_iv_pressure: float = 0.0,
    threshold: float = ELEVATED,
) -> GateVerdict:
    """Flag likely causal-attribution errors: social heat without institutional confirmation.

    When ``false_signal_risk_index`` is elevated and a social spike lacks institutional
    flow confirmation (or coincides with high dealer gamma/IV pressure that pins prices),
    the move is likely misattributed and should be flagged.
    """
    fs = _f(false_signal_risk_index)
    gamma = _f(options_gamma_iv_pressure)
    inputs = {"false_signal_risk_index": fs, "options_gamma_iv_pressure": gamma}
    if fs >= threshold and social_spike and not institutional_confirmation:
        return GateVerdict(
            "attribution_error",
            "flag",
            True,
            (
                f"false_signal_risk_index elevated ({fs:.2f}) on a social spike without institutional "
                f"confirmation (options_gamma_IV_pressure={gamma:.2f}); likely macro/gamma misattribution."
            ),
            inputs,
        )
    return GateVerdict("attribution_error", "allow", False, "No attribution-error pattern.", inputs)


def required_validations(triggered_gates: list[str]) -> list[str]:
    """Real-market validations that must pass before acting, given the triggered gates."""
    out: list[str] = []
    for gate in triggered_gates:
        task = REQUIRED_VALIDATION_TASKS.get(gate)
        if task and task not in out:
            out.append(task)
    return out


def evaluate_mirofish_gates(indices: Mapping[str, Any], *, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run all four advisory gates over a normalized index map and a small context map.

    Args:
        indices: any of the report's telemetry indices, normalized to [0,1]
            (broker_confusion_index, buying_power_rejection_confusion, macro_dominance_index,
            retail_flow_intensity, ai_bot_copycat_index, false_signal_risk_index,
            options_gamma_iv_pressure). Missing keys default to 0.0.
        context: optional booleans (scheduled_catalyst, low_liquidity, off_peak,
            social_spike, institutional_confirmation).

    Returns an advisory verdict dict. ``action`` is the most conservative gate outcome
    ("suppress" > "flag" > "allow"). It carries ``execution_authority="none"`` because
    these gates are advisory and never authorize execution.
    """
    ctx = dict(context or {})
    verdicts = [
        broker_friction_gate(
            indices.get("broker_confusion_index", 0.0),
            indices.get("buying_power_rejection_confusion", 0.0),
        ),
        macro_override_gate(
            indices.get("macro_dominance_index", 0.0),
            indices.get("retail_flow_intensity", 0.0),
            scheduled_catalyst=bool(ctx.get("scheduled_catalyst", False)),
        ),
        bot_convergence_gate(
            indices.get("ai_bot_copycat_index", 0.0),
            low_liquidity=bool(ctx.get("low_liquidity", False)),
            off_peak=bool(ctx.get("off_peak", False)),
        ),
        attribution_error_gate(
            indices.get("false_signal_risk_index", 0.0),
            social_spike=bool(ctx.get("social_spike", False)),
            institutional_confirmation=bool(ctx.get("institutional_confirmation", False)),
            options_gamma_iv_pressure=indices.get("options_gamma_iv_pressure", 0.0),
        ),
    ]
    triggered = [v.gate for v in verdicts if v.triggered]
    if any(v.action == "suppress" for v in verdicts):
        action = "suppress"
    elif any(v.action == "flag" for v in verdicts):
        action = "flag"
    else:
        action = "allow"
    return {
        "type": "mirofish_advisory_gates",
        "execution_authority": EXECUTION_AUTHORITY,
        "action": action,
        "triggered_gates": triggered,
        "required_validations": required_validations(triggered),
        "verdicts": [
            {
                "gate": v.gate,
                "action": v.action,
                "triggered": v.triggered,
                "reason": v.reason,
                "inputs": v.inputs,
            }
            for v in verdicts
        ],
        "advisory_note": (
            "Advisory false-signal filters only. They downgrade/flag candidate signals and "
            "have no execution authority; deterministic policy still decides any action, and the "
            "listed real-market validations must pass before acting."
        ),
    }
