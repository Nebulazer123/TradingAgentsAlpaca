"""Registered dependence-aware weekly TA-Control statistics."""

from __future__ import annotations

import json

import pytest

from tradingagents.evals.economic_evaluation_protocol import CONTROL_ARM_IDS
from tradingagents.evals.economic_tournament_statistics import (
    EconomicTournamentStatisticsError,
    WeeklyArmObservation,
    build_economic_tournament_statistics,
    validate_economic_tournament_statistics,
)


MARKET_DATES = (
    "2026-01-09",
    "2026-01-16",
    "2026-01-23",
    "2026-01-30",
    "2026-02-06",
    "2026-02-13",
    "2026-02-20",
    "2026-02-27",
)


def _observations():
    result = {}
    for arm_index, arm in enumerate(CONTROL_ARM_IDS):
        rows = []
        for date_index, market_date in enumerate(MARKET_DATES):
            returned = "0" if arm == "cash" else (
                "0.01" if (date_index + arm_index) % 3 else "-0.02"
            )
            rows.append(
                WeeklyArmObservation(
                    market_date=market_date,
                    gross_return=returned,
                    net_return=returned,
                    benchmark_net_return="0.005",
                    turnover="0" if arm == "cash" else "0.25",
                    cost_drag="0" if arm == "cash" else "0.00025",
                    false_positive=returned.startswith("-"),
                    positions=(
                        (("CASH", "1"),)
                        if arm == "cash"
                        else (("CASH", "0"), (f"T{arm_index:03d}", "1"))
                    ),
                    factor_exposures=(
                        () if arm == "cash" else (("market_beta", "1"),)
                    ),
                    sector_exposures=(
                        () if arm == "cash" else (("technology", "1"),)
                    ),
                )
            )
        result[arm] = tuple(rows)
    return result


def test_registered_statistics_are_deterministic_and_weekly_date_primary():
    first = build_economic_tournament_statistics(
        raw_source_row_count=1208,
        decision_event_count=600,
        packet_event_cluster_count=32,
        market_event_cluster_count=8,
        observations_by_arm=_observations(),
    )
    second = build_economic_tournament_statistics(
        raw_source_row_count=1208,
        decision_event_count=600,
        packet_event_cluster_count=32,
        market_event_cluster_count=8,
        observations_by_arm=_observations(),
    )

    assert first.canonical_json_bytes() == second.canonical_json_bytes()
    payload = first.to_dict()
    assert payload["primary_unit"] == "weekly_market_date"
    assert payload["unique_decision_date_count"] == 8
    assert payload["market_event_cluster_count"] == 8
    assert payload["bootstrap"]["method"] == "deterministic_market_date_block_bootstrap"
    assert payload["walk_forward"]["purge_sessions"] == 5
    assert payload["walk_forward"]["embargo_sessions"] == 5
    assert payload["multiple_testing"]["method"] == "holm_bonferroni_registered_contrasts"
    assert payload["status"] == "completed"
    assert payload["analysis_only"] is True
    assert "effective_sample_size" not in json.dumps(payload)
    rebuilt = validate_economic_tournament_statistics(payload)
    assert rebuilt.canonical_json_bytes() == first.canonical_json_bytes()


def test_statistics_reject_arm_or_date_pseudoreplication():
    rows = _observations()
    with pytest.raises(EconomicTournamentStatisticsError):
        build_economic_tournament_statistics(
            raw_source_row_count=1208,
            decision_event_count=600,
            packet_event_cluster_count=32,
            market_event_cluster_count=8,
            observations_by_arm={key: value for key, value in rows.items() if key != "cash"},
        )

    rows["spy"] = rows["spy"][:-1]
    with pytest.raises(EconomicTournamentStatisticsError):
        build_economic_tournament_statistics(
            raw_source_row_count=1208,
            decision_event_count=600,
            packet_event_cluster_count=32,
            market_event_cluster_count=8,
            observations_by_arm=rows,
        )
