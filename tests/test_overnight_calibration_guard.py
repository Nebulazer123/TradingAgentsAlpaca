import json

from tradingagents.evals.overnight_calibration import (
    build_overnight_calibration_guard,
    write_overnight_calibration_guard,
)


def _cohort_summary():
    return {
        "kind": "walk_forward_overnight_cohort_refresh",
        "generated_at": "2026-06-06T19:50:33+00:00",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "selected_packet_count": 12,
        "returns_row_count": 140,
        "fixture_row_count": 420,
        "sample_floor_met": True,
        "replay_packet_path": "results/research_batches/replay.json",
        "walk_forward_metrics": [
            {
                "arm_id": "deterministic_sleeve_only",
                "scored_count": 420,
                "sample_floor_met": True,
                "directional_accuracy": "0.3905",
                "false_positive_rate": "0.1690",
                "average_brier": "0.2577",
                "average_action_relative_return": "-0.3781",
            },
            {
                "arm_id": "tradingagents_advisory_overlay",
                "scored_count": 11,
                "sample_floor_met": True,
                "directional_accuracy": "0.4545",
                "false_positive_rate": "0.5455",
                "average_brier": "0.2901",
                "average_action_relative_return": "-0.2109",
            },
        ],
    }


def test_overnight_calibration_guard_tightens_after_underperforming_cohort():
    packet = build_overnight_calibration_guard(
        _cohort_summary(),
        cohort_summary_path="results/research_batches/cohort.json",
    )

    assert packet["analysis_only"] is True
    assert packet["can_submit_orders"] is False
    assert packet["execution_authority"] == "none"
    assert packet["guard_decision"] == "tighten"
    assert packet["can_increase_live_influence"] is False
    assert "deterministic_sleeve_negative_action_return" in packet["red_flags"]
    assert "tradingagents_overlay_false_positive_risk" in packet["red_flags"]
    assert packet["metric_summary"]["deterministic_sleeve_only"][
        "average_action_relative_return"
    ] == "-0.3781"
    assert packet["metric_summary"]["tradingagents_advisory_overlay"][
        "false_positive_rate"
    ] == "0.5455"
    assert any("controlled dip" in item for item in packet["recommended_guardrails"])
    assert any("green-spike" in item for item in packet["recommended_guardrails"])
    assert packet["live_influence_policy"] == {
        "mode": "tighten",
        "can_increase_live_influence": False,
        "live_influence_action": "tighten_or_hold_reduced_weight",
        "new_buy_permission": "controlled_dip_support_reclaim_only",
        "replacement_buy_permission": "disabled_unless_fresh_independent_setup",
        "sell_permission": "independent_profit_or_board_approved_exit_only",
    }
    assert "false_positive_rate_too_high" in packet["promotion_blockers"]
    assert "action_relative_return_negative" in packet["promotion_blockers"]
    required_entry_ids = {
        item["id"]
        for item in packet["entry_validation_requirements"]
        if item["required"] is True
    }
    assert {
        "controlled_dip_or_support_reclaim",
        "no_green_spike_chase",
        "buy_sell_independence",
        "source_freshness_and_quality",
        "anti_crowding_confirmation",
    } <= required_entry_ids
    assert packet["paper_exploration_policy"]["status"] == "continue"


def test_overnight_calibration_guard_allows_monitoring_when_metrics_are_clean():
    cohort = _cohort_summary()
    cohort["walk_forward_metrics"] = [
        {
            "arm_id": "deterministic_sleeve_only",
            "scored_count": 50,
            "sample_floor_met": True,
            "directional_accuracy": "0.6200",
            "false_positive_rate": "0.0800",
            "average_brier": "0.1800",
            "average_action_relative_return": "0.2100",
        },
        {
            "arm_id": "tradingagents_advisory_overlay",
            "scored_count": 25,
            "sample_floor_met": True,
            "directional_accuracy": "0.6400",
            "false_positive_rate": "0.1200",
            "average_brier": "0.1700",
            "average_action_relative_return": "0.2300",
            "net_edge_vs_baseline": "0.0200",
            "beats_baseline_after_costs": True,
        },
    ]

    packet = build_overnight_calibration_guard(cohort)

    assert packet["guard_decision"] == "monitor"
    assert packet["can_increase_live_influence"] is True
    assert packet["red_flags"] == []
    assert packet["live_influence_policy"]["mode"] == "monitor"
    assert packet["live_influence_policy"]["new_buy_permission"] == "controlled_dip_only"
    anti_crowding = next(
        item
        for item in packet["entry_validation_requirements"]
        if item["id"] == "anti_crowding_confirmation"
    )
    assert anti_crowding["required"] is False
    assert packet["promotion_blockers"] == []


def test_overnight_calibration_guard_tightens_when_overlay_loses_to_baseline_after_costs():
    cohort = _cohort_summary()
    cohort["walk_forward_metrics"] = [
        {
            "arm_id": "deterministic_sleeve_only",
            "scored_count": 50,
            "sample_floor_met": True,
            "directional_accuracy": "0.6200",
            "false_positive_rate": "0.0800",
            "average_brier": "0.1800",
            "average_action_relative_return": "0.2100",
            "net_edge_vs_baseline": "0.0000",
            "beats_baseline_after_costs": True,
        },
        {
            "arm_id": "tradingagents_advisory_overlay",
            "scored_count": 25,
            "sample_floor_met": True,
            "directional_accuracy": "0.6400",
            "false_positive_rate": "0.1200",
            "average_brier": "0.1700",
            "average_action_relative_return": "0.1900",
            "net_edge_vs_baseline": "-0.0200",
            "beats_baseline_after_costs": False,
        },
    ]

    packet = build_overnight_calibration_guard(cohort)

    assert packet["guard_decision"] == "tighten"
    assert "tradingagents_overlay_not_beating_baseline_after_costs" in packet["red_flags"]
    assert "overlay_not_beating_baseline_after_costs" in packet["promotion_blockers"]
    assert packet["can_increase_live_influence"] is False


def test_write_overnight_calibration_guard_writes_latest_and_markdown(tmp_path):
    packet = build_overnight_calibration_guard(_cohort_summary())

    packet_path = write_overnight_calibration_guard(packet, tmp_path)

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    latest_compact = json.loads(
        (tmp_path / "latest-compact.json").read_text(encoding="utf-8")
    )
    compact_path = packet_path.with_suffix(".compact.json")
    assert packet_path.exists()
    assert compact_path.exists()
    assert (tmp_path / "latest.md").exists()
    assert latest["guard_decision"] == "tighten"
    assert latest["can_submit_orders"] is False
    assert latest_compact["schema"] == "compact_overnight_calibration_guard_v1"
    assert latest_compact["raw_packet_path"] == str(packet_path)
    assert latest_compact["guard_decision"] == "tighten"
    assert latest_compact["can_submit_orders"] is False
    assert latest_compact["execution_authority"] == "none"
    assert latest_compact["baseline_action_relative_return"] == "-0.3781"
    assert latest_compact["tradingagents_false_positive_rate"] == "0.5455"
    assert "anti_crowding_confirmation" in latest_compact[
        "required_entry_validation_ids"
    ]
