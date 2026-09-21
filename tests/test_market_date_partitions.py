"""Contracts for exhaustive, purged weekly economic partitions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

from tests.test_point_in_time_cohort import (
    _build_from_fixture,
    _source_cohort_fixture,
)
from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    build_market_date_partitions,
    build_market_session_calendar,
    validate_market_date_partitions,
)
from tradingagents.evals.economic_evaluation_protocol import (
    build_decision_event,
    canonical_universe_id,
)

REGISTERED_AT = "2026-04-01T12:01:00+00:00"


def _weekly_calendar_dates() -> tuple[str, ...]:
    dates: list[str] = []
    monday = dt.date(2026, 4, 6)
    for week in range(55):
        for weekday in range(5):
            if week in {7, 23, 41} and weekday == 4:
                continue
            dates.append((monday + dt.timedelta(weeks=week, days=weekday)).isoformat())
    return tuple(dates)


def _decision_dates(market_dates: tuple[str, ...]) -> tuple[str, ...]:
    by_week: dict[tuple[int, int], list[str]] = {}
    for market_date in market_dates:
        parsed = dt.date.fromisoformat(market_date)
        iso = parsed.isocalendar()
        by_week.setdefault((iso.year, iso.week), []).append(market_date)
    return tuple(rows[-1] for rows in by_week.values())


def _calendar(tmp_path, market_dates: tuple[str, ...]):
    raw_bytes = json.dumps(
        [{"date": day, "open": "09:30", "close": "16:00"} for day in market_dates],
        separators=(",", ":"),
    ).encode()
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "partition-calendar",
        clock=lambda: dt.datetime(2026, 4, 1, 12, 0, tzinfo=dt.timezone.utc),
    )
    artifact = archive.admit(
        raw_bytes=raw_bytes,
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-04-01T12:00:00+00:00",
    )
    return build_market_session_calendar(archive=archive, raw_artifact=artifact)


def _event(market_date: str, symbol: str, primary: tuple[str, ...]):
    return build_decision_event(
        universe_id=canonical_universe_id(primary),
        symbol=symbol,
        decision_at=f"{market_date}T20:55:00+00:00",
        market_date=market_date,
        horizon_sessions=5,
        horizon="5_sessions",
        benchmark="SPY",
        created_at=f"{market_date}T20:45:00+00:00",
        resolution_window={"start_at": f"{market_date}T20:55:00+00:00"},
        observation_start=f"{market_date}T19:00:00+00:00",
        observation_end=f"{market_date}T20:50:00+00:00",
        available_at=f"{market_date}T20:50:00+00:00",
        recorded_at=f"{market_date}T20:52:00+00:00",
        source_packet_id=f"packet-{market_date}-{symbol}",
        source_artifact_id=f"artifact-{market_date}-{symbol}",
        source_artifact_sha256=hashlib.sha256(
            f"{market_date}-{symbol}".encode()
        ).hexdigest(),
    )


@pytest.fixture(scope="module")
def weekly_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("weekly-partitions")
    cohort_archive, cohort_calendar, payload = _source_cohort_fixture(root / "cohort")
    cohort = _build_from_fixture(cohort_archive, cohort_calendar, payload)
    primary = cohort.primary_universe_75
    market_dates = _weekly_calendar_dates()
    decision_dates = _decision_dates(market_dates)
    calendar = _calendar(root, market_dates)
    events = tuple(
        _event(market_date, symbol, primary)
        for market_date in decision_dates
        for symbol in primary
    )
    return cohort, calendar, decision_dates, events


def _build(weekly_source, **overrides):
    cohort, calendar, decision_dates, events = weekly_source
    values = {
        "market_calendar": calendar,
        "cadence": "weekly",
        "registered_at": REGISTERED_AT,
        "primary_universe": cohort.primary_universe_75,
        "decision_market_dates": decision_dates,
        "events": events,
    }
    values.update(overrides)
    return build_market_date_partitions(**values)


def test_weekly_partitions_are_source_derived_complete_and_guarded(weekly_source):
    _cohort, _calendar_receipt, decision_dates, events = weekly_source
    partitions = _build(weekly_source)

    assert partitions.cadence == "weekly"
    assert partitions.decision_market_dates == decision_dates
    assert len(partitions.development_market_dates) == 33
    assert len(partitions.validation_market_dates) == 11
    assert len(partitions.holdout_market_dates) == 11
    assert partitions.development_validation_purge_dates == decision_dates[28:33]
    assert partitions.development_validation_embargo_dates == decision_dates[33:38]
    assert partitions.validation_holdout_purge_dates == decision_dates[39:44]
    assert partitions.validation_holdout_embargo_dates == decision_dates[44:49]
    assert len(partitions.development_event_ids) == 33 * 75
    assert len(partitions.validation_event_ids) == 11 * 75
    assert len(partitions.holdout_event_ids) == 11 * 75
    assert len(partitions.development_eligible_event_ids) == 28 * 75
    assert len(partitions.validation_eligible_event_ids) == 75
    assert len(partitions.holdout_eligible_event_ids) == 6 * 75
    assert any(dt.date.fromisoformat(day).weekday() == 3 for day in decision_dates)

    event_partition: dict[str, str] = {}
    for name, event_ids in (
        ("development", partitions.development_event_ids),
        ("validation", partitions.validation_event_ids),
        ("holdout", partitions.holdout_event_ids),
    ):
        for event_id in event_ids:
            event_partition[event_id] = name
    for market_date in decision_dates:
        date_partitions = {
            event_partition[event.decision_event_id]
            for event in events
            if event.market_date == market_date
        }
        assert len(date_partitions) == 1

    assert validate_market_date_partitions(
        json.loads(partitions.canonical_json_bytes())
    ) == partitions


@pytest.mark.parametrize(
    "change",
    (
        lambda source: {"cadence": "daily"},
        lambda source: {
            "decision_market_dates": (
                source[2][0],
                source[2][0],
                *source[2][2:],
            )
        },
        lambda source: {"decision_market_dates": source[2][:10] + source[2][11:]},
        lambda source: {"decision_market_dates": ("2026-04-06", *source[2][1:])},
        lambda source: {"events": source[3][:-1]},
        lambda source: {"events": (*source[3][:-1], source[3][0])},
        lambda source: {"registered_at": source[3][0].decision_at},
    ),
)
def test_partitions_reject_nonweekly_unregistered_or_incomplete_inputs(
    weekly_source,
    change,
):
    with pytest.raises(PointInTimeDataError):
        _build(weekly_source, **change(weekly_source))


def test_partition_validator_rejects_nonexhaustive_or_overlapping_receipts(weekly_source):
    payload = _build(weekly_source).to_dict()
    payload["development_event_ids"].pop()
    payload["validation_event_ids"].append(payload["holdout_event_ids"][0])

    with pytest.raises(PointInTimeDataError):
        validate_market_date_partitions(payload)
