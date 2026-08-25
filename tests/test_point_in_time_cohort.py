"""Focused contracts for deterministic point-in-time economic cohorts."""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeCohortCandidate,
    PointInTimeDataError,
    SecurityIdentity,
    build_point_in_time_cohort,
    validate_point_in_time_cohort,
)


def _candidate(index: int, **overrides: object) -> PointInTimeCohortCandidate:
    symbol = f"X{index:03d}"
    digest = hashlib.sha256(f"raw-{symbol}".encode()).hexdigest()
    values: dict[str, object] = {
        "security": SecurityIdentity(
            security_id=f"security-us-{symbol.lower()}-common",
            symbol=symbol,
            cik=f"{index:010d}",
            figi=f"BBG{index:09d}",
            exchange="NASDAQ",
            security_type="common_stock",
            effective_from="2020-01-01",
            effective_to=None,
            status="active",
            successor_security_id=None,
            terminal_proceeds_artifact_id=None,
            source_hashes={"security_master": digest},
        ),
        "prior_complete_close": "10",
        "session_dollar_volumes": tuple(str(index + 1) for _ in range(60)),
        "selection_artifact_id": f"raw-universe-{symbol.lower()}",
        "selection_artifact_sha256": digest,
    }
    values.update(overrides)
    return PointInTimeCohortCandidate(**values)


def test_cohort_freezes_ranked_100_75_50_universes_and_rejections():
    candidates = tuple(_candidate(index) for index in range(102)) + (
        _candidate(998, prior_complete_close="4.99"),
        _candidate(999, session_dollar_volumes=tuple("0" for _ in range(60))),
    )
    cohort = build_point_in_time_cohort(
        market_date="2026-01-09",
        as_of_cutoff="2026-01-09T20:59:00+00:00",
        candidates=candidates,
    )

    assert len(cohort.sensitivity_universe_100) == 100
    assert len(cohort.primary_universe_75) == 75
    assert len(cohort.sensitivity_universe_50) == 50
    assert cohort.ranking[0].symbol == "X101"
    assert cohort.primary_universe_75 == tuple(
        sorted(row.symbol for row in cohort.ranking[:75])
    )
    assert cohort.sensitivity_universe_50 == tuple(
        sorted(row.symbol for row in cohort.ranking[:50])
    )
    assert [row.reason for row in cohort.rejections] == [
        "prior_complete_close_below_5",
        "median_dollar_volume_not_positive",
    ]
    assert validate_point_in_time_cohort(
        json.loads(cohort.canonical_json_bytes())
    ) == cohort


def test_cohort_rejects_underfilled_or_noncanonical_selection_inputs():
    with pytest.raises(PointInTimeDataError):
        build_point_in_time_cohort(
            market_date="2026-01-09",
            as_of_cutoff="2026-01-09T20:59:00+00:00",
            candidates=tuple(_candidate(index) for index in range(99)),
        )
    with pytest.raises(PointInTimeDataError):
        _candidate(1, session_dollar_volumes=tuple("1" for _ in range(59)))
    with pytest.raises(PointInTimeDataError):
        _candidate(1, prior_complete_close="05")


def test_cohort_excludes_non_us_exchange_securities_from_ranked_membership():
    foreign = _candidate(999)
    foreign = dataclasses.replace(
        foreign,
        security=dataclasses.replace(foreign.security, exchange="LSE"),
    )
    cohort = build_point_in_time_cohort(
        market_date="2026-01-09",
        as_of_cutoff="2026-01-09T20:59:00+00:00",
        candidates=tuple(_candidate(index) for index in range(100)) + (foreign,),
    )

    assert foreign.security.symbol not in cohort.sensitivity_universe_100
    assert cohort.rejections[-1].reason == "exchange_not_us_listed"
