"""Eval/contract tests for the MiroFish advisory false-signal gates.

These encode the four gate contracts the MiroFish Stage-4 report prescribes under
"## TradingAgents rule implications" as concrete scenario tables.
"""

from tradingagents.research.mirofish_gates import (
    EXECUTION_AUTHORITY,
    attribution_error_gate,
    bot_convergence_gate,
    broker_friction_gate,
    evaluate_mirofish_gates,
    macro_override_gate,
    required_validations,
)


def test_broker_friction_suppresses_phantom_retail_breakout():
    v = broker_friction_gate(0.82, 0.10)
    assert v.triggered is True
    assert v.action == "suppress"
    v2 = broker_friction_gate(0.10, 0.71)
    assert v2.action == "suppress"
    calm = broker_friction_gate(0.20, 0.15)
    assert calm.triggered is False
    assert calm.action == "allow"


def test_macro_override_downgrades_retail_attribution_on_scheduled_catalyst():
    # Jobs report shock gate: macro dominates retail flow -> suppress during catalyst.
    v = macro_override_gate(0.80, 0.30, scheduled_catalyst=True)
    assert v.triggered is True
    assert v.action == "suppress"
    # Macro dominates but no scheduled catalyst -> flag (not hard suppress).
    v2 = macro_override_gate(0.70, 0.30, scheduled_catalyst=False)
    assert v2.action == "flag"
    # Retail flow actually exceeds macro -> allow.
    v3 = macro_override_gate(0.40, 0.65)
    assert v3.triggered is False


def test_bot_convergence_flags_synchronized_low_liquidity_spike():
    v = bot_convergence_gate(0.78, low_liquidity=True)
    assert v.triggered is True
    assert v.action == "flag"
    v_offpeak = bot_convergence_gate(0.66, off_peak=True)
    assert v_offpeak.triggered is True
    # Elevated copycat index but in a liquid, on-peak name -> not a brittle vacuum.
    liquid = bot_convergence_gate(0.90, low_liquidity=False, off_peak=False)
    assert liquid.triggered is False


def test_attribution_error_flags_social_spike_without_institutional_confirmation():
    v = attribution_error_gate(0.72, social_spike=True, institutional_confirmation=False)
    assert v.triggered is True
    assert v.action == "flag"
    # Institutional confirmation present -> not an attribution error.
    confirmed = attribution_error_gate(0.72, social_spike=True, institutional_confirmation=True)
    assert confirmed.triggered is False
    # No social spike -> nothing to misattribute.
    quiet = attribution_error_gate(0.80, social_spike=False)
    assert quiet.triggered is False


def test_evaluate_picks_most_conservative_action_and_lists_validations():
    indices = {
        "broker_confusion_index": 0.85,
        "buying_power_rejection_confusion": 0.70,
        "macro_dominance_index": 0.80,
        "retail_flow_intensity": 0.30,
        "ai_bot_copycat_index": 0.75,
        "false_signal_risk_index": 0.75,
        "options_gamma_iv_pressure": 0.6,
    }
    context = {
        "scheduled_catalyst": True,
        "low_liquidity": True,
        "social_spike": True,
        "institutional_confirmation": False,
    }
    result = evaluate_mirofish_gates(indices, context=context)
    assert result["action"] == "suppress"  # most conservative across gates
    assert set(result["triggered_gates"]) == {
        "broker_friction",
        "macro_override",
        "bot_convergence",
        "attribution_error",
    }
    # The report mandates real-market validation before acting on the triggered gates.
    assert "phantom_liquidity" in result["required_validations"]
    assert "macro_attribution" in result["required_validations"]
    assert "order_flow_toxicity" in result["required_validations"]
    assert result["execution_authority"] == "none"


def test_evaluate_allows_when_all_indices_benign():
    result = evaluate_mirofish_gates(
        {
            "broker_confusion_index": 0.10,
            "macro_dominance_index": 0.20,
            "retail_flow_intensity": 0.55,
            "ai_bot_copycat_index": 0.15,
            "false_signal_risk_index": 0.10,
        }
    )
    assert result["action"] == "allow"
    assert result["triggered_gates"] == []
    assert result["required_validations"] == []
    assert result["execution_authority"] == "none"


def test_gates_never_carry_execution_authority_and_tolerate_garbage_indices():
    # Missing / garbage indices must not crash and must default to safe (no trigger).
    result = evaluate_mirofish_gates({"broker_confusion_index": "not-a-number"})
    assert result["execution_authority"] == EXECUTION_AUTHORITY == "none"
    assert result["action"] == "allow"
    assert required_validations([]) == []
