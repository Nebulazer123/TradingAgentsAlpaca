import json
from decimal import Decimal

from tradingagents.brokers.alpaca_supervisor import (
    LIVE_AGGRESSIVE_SLEEVE,
    resolve_live_sleeve,
)
from tradingagents.policy.promotion_sync import (
    sync_promotion_state_from_tournament,
    sync_promotion_state_file,
)


def _ranking(
    strategy_id,
    *,
    total_return="311.36",
    total_return_pct="3.11",
    max_drawdown_pct="-1.91",
    win_rate_pct="85.71",
    tracked_days=11,
    equity="10311.36",
):
    return {
        "strategy_id": strategy_id,
        "name": strategy_id,
        "equity": equity,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate_pct,
        "tracked_days": tracked_days,
    }


def _report(candidate="pullback-support"):
    return {
        "generated_at": "2026-06-20T21:12:35+00:00",
        "tournament_id": "paper-tournament-20260531-080741",
        "rankings": [
            _ranking("pullback-support"),
            _ranking(
                "current-aggressive",
                total_return="-1225.06",
                total_return_pct="-12.25",
                max_drawdown_pct="-15.30",
                win_rate_pct="14.28",
                equity="8774.94",
            ),
            _ranking(
                "catalyst-relative-strength",
                total_return="-1313.05",
                total_return_pct="-13.13",
                max_drawdown_pct="-14.42",
                win_rate_pct="20.00",
                equity="8686.95",
            ),
        ],
        "live_strategy_candidate": {
            "status": "candidate",
            "strategy_id": candidate,
            "reason": "best positive paper strategy after 11 tracked day(s)",
        },
    }


def _incumbent_state():
    return {
        "schema_version": "1.0.0",
        "sleeves": {
            "current-aggressive": {
                "stage": "tiny_live_eligible",
                "live_enabled": True,
                "preregistered": True,
                "ci_green": True,
                "shadow_confirmed": True,
                "benchmark_gate_passed": True,
                "cost_gate_passed": True,
                "recent_alpha_gate_passed": True,
                "capacity_gate_passed": True,
                "validation_report_ref": "results/paper_strategy_tournament/latest.json",
                "risk_envelope_ref": "config/risk_envelope.yaml",
            }
        },
    }


def test_sync_promotes_candidate_and_demotes_negative_incumbent():
    result = sync_promotion_state_from_tournament(
        _report(),
        _incumbent_state(),
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
    )
    assert result.promoted == ["pullback-support"]
    assert result.demoted == ["current-aggressive"]

    promoted = result.state["sleeves"]["pullback-support"]
    assert promoted["stage"] == "tiny_live_eligible"
    assert promoted["live_enabled"] is True
    assert promoted["preregistered"] is True
    assert promoted["shadow_confirmed"] is True
    assert promoted["benchmark_gate_passed"] is True
    assert promoted["recent_alpha_gate_passed"] is True
    assert promoted["evidence_metrics"]["tracked_days"] == 11

    demoted = result.state["sleeves"]["current-aggressive"]
    assert demoted["stage"] == "paper_only"
    assert demoted["live_enabled"] is False
    assert "turned negative" in demoted["demotion_reason"]


def test_sync_without_arm_live_stays_fail_closed():
    result = sync_promotion_state_from_tournament(
        _report(),
        _incumbent_state(),
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=False,
        ci_green=True,
    )
    promoted = result.state["sleeves"]["pullback-support"]
    assert promoted["stage"] == "tiny_live_eligible"
    assert promoted["live_enabled"] is False
    assert "none (fail-closed)" in result.summary


def test_sync_quality_gates_block_weak_candidate():
    report = _report()
    report["rankings"][0]["max_drawdown_pct"] = "-12.50"
    result = sync_promotion_state_from_tournament(
        report,
        None,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
    )
    assert result.promoted == []
    record = result.state["sleeves"]["pullback-support"]
    assert record["stage"] == "paper_only"
    assert record["live_enabled"] is False
    assert any("max_drawdown_pct" in issue for issue in record["issues"])


def test_sync_requires_ci_attestation():
    result = sync_promotion_state_from_tournament(
        _report(),
        None,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=False,
    )
    assert result.promoted == []
    record = result.state["sleeves"]["pullback-support"]
    assert record["stage"] == "paper_only"
    assert "ci_green" in record["issues"]


def test_sync_promotion_state_file_roundtrip(tmp_path):
    report_path = tmp_path / "latest.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    state_path = tmp_path / "promotion_state.json"
    state_path.write_text(json.dumps(_incumbent_state()), encoding="utf-8")

    result = sync_promotion_state_file(
        report_path,
        state_path,
        tiny_live_tranche_usd=Decimal("25"),
        arm_live=True,
        ci_green=True,
    )
    assert result.promoted == ["pullback-support"]
    written = json.loads(state_path.read_text(encoding="utf-8"))
    assert written["sleeves"]["pullback-support"]["live_enabled"] is True
    assert written["sleeves"]["current-aggressive"]["live_enabled"] is False
    assert written["source"]["kind"] == "paper_tournament_sync"


def test_resolve_live_sleeve_prefers_backed_selection():
    selection = {"status": "active", "strategy_id": "pullback-support"}
    promotion_state = {
        "sleeves": {
            "pullback-support": {
                "stage": "tiny_live_eligible",
                "live_enabled": True,
            }
        }
    }
    sleeve, reason = resolve_live_sleeve(selection, promotion_state)
    assert sleeve == "pullback-support"
    assert "live-enabled promotion record" in reason


def test_resolve_live_sleeve_falls_back_to_enabled_sleeve():
    selection = {"status": "active", "strategy_id": "pullback-support"}
    promotion_state = {
        "sleeves": {
            "current-aggressive": {
                "stage": "tiny_live_eligible",
                "live_enabled": True,
            },
            "pullback-support": {"stage": "paper_only", "live_enabled": False},
        }
    }
    sleeve, reason = resolve_live_sleeve(selection, promotion_state)
    assert sleeve == "current-aggressive"
    assert "not live-enabled" in reason


def test_resolve_live_sleeve_fail_closed_default():
    sleeve, reason = resolve_live_sleeve(None, None)
    assert sleeve == LIVE_AGGRESSIVE_SLEEVE
    assert "fail-closed" in reason
