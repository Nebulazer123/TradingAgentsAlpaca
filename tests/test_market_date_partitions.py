"""Contracts for exhaustive, purged market-date economic partitions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

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


def _market_dates() -> tuple[str, ...]:
    start = dt.date(2026, 1, 5)
    dates: list[str] = []
    day = start
    while len(dates) < 60:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return tuple(dates)


def _calendar(tmp_path, market_dates: tuple[str, ...]):
    raw_bytes = json.dumps([{"date": day} for day in market_dates]).encode("utf-8")
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifact = archive.admit(
        raw_bytes=raw_bytes,
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    return build_market_session_calendar(archive=archive, raw_artifact=artifact)


def _event(market_date: str, symbol: str):
    return build_decision_event(
        universe_id=canonical_universe_id(tuple(f"T{index:03d}" for index in range(75))),
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


def test_partitions_are_chronological_exhaustive_and_mask_both_purge_boundaries(tmp_path):
    market_dates = _market_dates()
    calendar = _calendar(tmp_path, market_dates)
    events = tuple(
        _event(market_date, f"T{index:03d}")
        for index, market_date in enumerate(market_dates)
    )
    partitions = build_market_date_partitions(
        market_calendar=calendar,
        events=events,
    )

    assert len(partitions.development_market_dates) == 36
    assert len(partitions.validation_market_dates) == 12
    assert len(partitions.holdout_market_dates) == 12
    assert partitions.development_validation_purge_dates == market_dates[31:36]
    assert partitions.development_validation_embargo_dates == market_dates[36:41]
    assert partitions.validation_holdout_purge_dates == market_dates[43:48]
    assert partitions.validation_holdout_embargo_dates == market_dates[48:53]
    assigned = (
        partitions.development_event_ids
        + partitions.validation_event_ids
        + partitions.holdout_event_ids
    )
    assert set(assigned) == {event.decision_event_id for event in events}
    assert len(assigned) == len(set(assigned))
    assert len(partitions.development_eligible_event_ids) == 31
    assert len(partitions.validation_eligible_event_ids) == 2
    assert len(partitions.holdout_eligible_event_ids) == 7
    assert not set(partitions.development_eligible_event_ids).intersection(
        partitions.development_validation_purge_event_ids
    )
    assert not set(partitions.validation_eligible_event_ids).intersection(
        partitions.development_validation_embargo_event_ids
        + partitions.validation_holdout_purge_event_ids
    )
    assert not set(partitions.holdout_eligible_event_ids).intersection(
        partitions.validation_holdout_embargo_event_ids
    )
    assert validate_market_date_partitions(
        json.loads(partitions.canonical_json_bytes())
    ) == partitions


def test_partitions_reject_too_short_calendar_or_events_outside_calendar(tmp_path):
    market_dates = _market_dates()
    calendar = _calendar(tmp_path, market_dates)
    with pytest.raises(PointInTimeDataError):
        build_market_date_partitions(
            market_calendar=_calendar(tmp_path / "short", market_dates[:24]),
            events=tuple(_event(day, "T000") for day in market_dates[:24]),
        )
    with pytest.raises(PointInTimeDataError):
        build_market_date_partitions(
            market_calendar=calendar,
            events=(_event("2026-02-01", "T000"),),
        )
