"""Focused contracts for source-verifiable point-in-time economic cohorts."""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    SecurityIdentity,
    build_market_session_calendar,
    build_source_verifiable_point_in_time_cohort,
    validate_point_in_time_cohort,
    verify_source_verifiable_point_in_time_cohort,
)

MARKET_DATE = "2026-04-01"
AS_OF_CUTOFF = "2026-04-01T12:00:00+00:00"
SELECTION_TIME = "2026-04-01T12:05:00+00:00"
SOURCE_RETRIEVED_AT = "2026-03-31T20:30:00+00:00"
ARCHIVE_RECORDED_AT = dt.datetime(2026, 3, 31, 20, 31, tzinfo=dt.UTC)
MARKET_TIMEZONE = ZoneInfo("America/New_York")


def _registered_market_dates() -> tuple[str, ...]:
    dates: list[str] = []
    day = dt.date.fromisoformat(MARKET_DATE)
    while len(dates) < 61:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day -= dt.timedelta(days=1)
    return tuple(reversed(dates))


def _daily_bar_timestamp(market_date: str) -> str:
    local_midnight = dt.datetime.combine(
        dt.date.fromisoformat(market_date),
        dt.time(0, 0),
        tzinfo=MARKET_TIMEZONE,
    )
    return local_midnight.astimezone(dt.UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _source_cohort_fixture(
    root: Path,
    *,
    candidate_count: int = 100,
    asset_overrides: dict[int, dict[str, object]] | None = None,
) -> tuple[RawPointInTimeArtifactArchive, object, dict[str, object]]:
    """Build exact retained Alpaca calendar, asset, and daily-bar fixtures."""

    archive = RawPointInTimeArtifactArchive(
        root,
        clock=lambda: ARCHIVE_RECORDED_AT,
    )
    market_dates = _registered_market_dates()
    calendar_artifact = archive.admit(
        raw_bytes=json.dumps(
            [
                {"date": value, "open": "09:30", "close": "16:00"}
                for value in market_dates
            ],
            separators=(",", ":"),
        ).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at=SOURCE_RETRIEVED_AT,
    )
    calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=calendar_artifact,
    )
    session_dates = market_dates[:-1]
    candidates: list[dict[str, object]] = []
    for index in range(candidate_count):
        symbol = f"X{index:03d}"
        security_id = f"security-us-{symbol.lower()}-common"
        asset_payload: dict[str, object] = {
            "id": security_id,
            "symbol": symbol,
            "exchange": "NASDAQ",
            "security_type": "common_stock",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "status": "active",
            "class": "us_equity",
            "tradable": True,
        }
        asset_payload.update((asset_overrides or {}).get(index, {}))
        asset_artifact = archive.admit(
            raw_bytes=json.dumps(asset_payload, separators=(",", ":")).encode(),
            source_uri=f"https://paper-api.alpaca.markets/v2/assets/{symbol}",
            content_type="application/json",
            retrieved_at=SOURCE_RETRIEVED_AT,
        )
        security = SecurityIdentity(
            security_id=security_id,
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
            source_hashes={"alpaca_asset": asset_artifact.raw_artifact_sha256},
        )
        bars = [
            {
                "t": _daily_bar_timestamp(session_date),
                "c": 10,
                "v": index + 1,
            }
            for session_date in session_dates
        ]
        bars_payload = {"bars": {symbol: bars}, "next_page_token": None}
        bars_uri = (
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
            f"?timeframe=1Day&feed=sip&adjustment=raw"
            f"&start={session_dates[0]}T00:00:00Z&end={MARKET_DATE}T00:00:00Z"
        )
        bars_artifact = archive.admit(
            raw_bytes=json.dumps(bars_payload, separators=(",", ":")).encode(),
            source_uri=bars_uri,
            content_type="application/json",
            retrieved_at=SOURCE_RETRIEVED_AT,
        )
        candidates.append(
            {
                "security": security.to_dict(),
                "identity_sources": [
                    {
                        "source_hash_name": "alpaca_asset",
                        "raw_artifact_id": asset_artifact.raw_artifact_id,
                        "raw_artifact_sha256": asset_artifact.raw_artifact_sha256,
                        "qualification_field_selectors": {
                            "security_id": ["id"],
                            "symbol": ["symbol"],
                            "exchange": ["exchange"],
                            "security_type": ["security_type"],
                            "effective_from": ["effective_from"],
                            "effective_to": ["effective_to"],
                            "status": ["status"],
                            "asset_class": ["class"],
                            "tradable": ["tradable"],
                        },
                    }
                ],
                "market_data_source": {
                    "raw_artifact_id": bars_artifact.raw_artifact_id,
                    "raw_artifact_sha256": bars_artifact.raw_artifact_sha256,
                    "bar_selectors": {
                        "rows_path": ["bars", symbol],
                        "timestamp_field": "t",
                        "close_field": "c",
                        "volume_field": "v",
                    },
                },
            }
        )
    return archive, calendar, {
        "market_date": MARKET_DATE,
        "as_of_cutoff": AS_OF_CUTOFF,
        "selection_time": SELECTION_TIME,
        "candidates": candidates,
    }


def _build_from_fixture(
    archive: RawPointInTimeArtifactArchive,
    calendar: object,
    payload: dict[str, object],
):
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    return build_source_verifiable_point_in_time_cohort(
        archive=archive,
        market_calendar=calendar,
        market_date=payload["market_date"],
        as_of_cutoff=payload["as_of_cutoff"],
        selection_time=payload["selection_time"],
        candidates=tuple(candidates),
    )


def test_source_verifiable_cohort_rebuilds_ranked_prefixes_and_exact_rejections(
    tmp_path: Path,
):
    first_session = _registered_market_dates()[0]
    archive, calendar, payload = _source_cohort_fixture(
        tmp_path / "pit",
        candidate_count=109,
        asset_overrides={
            100: {"security_type": "etf"},
            101: {"security_type": "etn"},
            102: {"security_type": "preferred_stock"},
            103: {"security_type": "warrant"},
            104: {"exchange": "OTC"},
            105: {"status": "inactive"},
            106: {"tradable": False},
            107: {"class": "crypto"},
            108: {"effective_from": MARKET_DATE},
        },
    )

    cohort = _build_from_fixture(archive, calendar, payload)

    assert cohort.session_dates[0] == first_session
    assert cohort.session_dates[-1] == "2026-03-31"
    assert cohort.ranking[0].symbol == "X099"
    assert cohort.sensitivity_universe_100 == tuple(
        row.symbol for row in cohort.ranking[:100]
    )
    assert cohort.primary_universe_75 == cohort.sensitivity_universe_100[:75]
    assert cohort.sensitivity_universe_50 == cohort.sensitivity_universe_100[:50]
    assert cohort.primary_universe_75 != tuple(sorted(cohort.primary_universe_75))
    assert cohort.sensitivity_universe_100_id.startswith("economic-universe-")
    assert len(cohort.sensitivity_universe_100_sha256) == 64
    assert len(cohort.primary_universe_75_sha256) == 64
    assert len(cohort.sensitivity_universe_50_sha256) == 64
    assert [row.reasons for row in cohort.rejections] == [
        ("security_type_etf",),
        ("security_type_etn",),
        ("security_type_preferred",),
        ("security_type_warrant",),
        ("exchange_otc",),
        ("asset_status_not_active",),
        ("asset_not_tradable",),
        ("asset_class_not_us_equity",),
        ("identity_not_effective_for_full_window",),
    ]
    serialized = cohort.canonical_json_bytes()
    assert b"session_dollar_volumes" not in serialized
    assert b"next_page_token" not in serialized
    assert validate_point_in_time_cohort(json.loads(serialized)) == cohort
    assert (
        verify_source_verifiable_point_in_time_cohort(
            archive=archive,
            value=json.loads(serialized),
        )
        == cohort
    )


def test_source_verifiable_cohort_rejects_missing_duplicate_extra_and_out_of_order_bars(
    tmp_path: Path,
):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    original_ref = candidates[0]["market_data_source"]
    assert isinstance(original_ref, dict)
    original_artifact = archive.read_artifact(original_ref["raw_artifact_id"])
    original_payload = json.loads(archive.read_bytes(original_artifact))
    original_bars = original_payload["bars"]["X000"]
    mutations = {
        "missing": original_bars[:-1],
        "duplicate": [*original_bars[:-1], original_bars[0]],
        "extra": [*original_bars, original_bars[-1]],
        "out_of_order": list(reversed(original_bars)),
    }

    for bars in mutations.values():
        changed_source = {"bars": {"X000": bars}, "next_page_token": None}
        changed_artifact = archive.admit(
            raw_bytes=json.dumps(changed_source, separators=(",", ":")).encode(),
            source_uri=original_artifact.source_uri,
            content_type="application/json",
            retrieved_at=SOURCE_RETRIEVED_AT,
        )
        changed = copy.deepcopy(payload)
        changed_candidates = changed["candidates"]
        assert isinstance(changed_candidates, list)
        changed_ref = changed_candidates[0]["market_data_source"]
        assert isinstance(changed_ref, dict)
        changed_ref["raw_artifact_id"] = changed_artifact.raw_artifact_id
        changed_ref["raw_artifact_sha256"] = changed_artifact.raw_artifact_sha256

        with pytest.raises(PointInTimeDataError, match="60|session"):
            _build_from_fixture(archive, calendar, changed)


def test_source_verifiable_cohort_rejects_caller_truth_and_unbound_identity_fields(
    tmp_path: Path,
):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    caller_authored = copy.deepcopy(payload)
    caller_candidates = caller_authored["candidates"]
    assert isinstance(caller_candidates, list)
    caller_candidates[0]["prior_complete_close"] = "999"

    with pytest.raises(PointInTimeDataError, match="candidate input fields"):
        _build_from_fixture(archive, calendar, caller_authored)

    unbound = copy.deepcopy(payload)
    unbound_candidates = unbound["candidates"]
    assert isinstance(unbound_candidates, list)
    identity_sources = unbound_candidates[0]["identity_sources"]
    assert isinstance(identity_sources, list)
    selectors = identity_sources[0]["qualification_field_selectors"]
    assert isinstance(selectors, dict)
    del selectors["security_type"]

    with pytest.raises(PointInTimeDataError, match="unbound qualification fields"):
        _build_from_fixture(archive, calendar, unbound)


def test_source_verifiable_cohort_tie_breaks_by_symbol_then_security_id(tmp_path: Path):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    for candidate in candidates:
        market_data = candidate["market_data_source"]
        assert isinstance(market_data, dict)
        artifact = archive.read_artifact(market_data["raw_artifact_id"])
        source = json.loads(archive.read_bytes(artifact))
        symbol = candidate["security"]["symbol"]
        for row in source["bars"][symbol]:
            row["v"] = 1
        replacement = archive.admit(
            raw_bytes=json.dumps(source, separators=(",", ":")).encode(),
            source_uri=artifact.source_uri,
            content_type="application/json",
            retrieved_at=SOURCE_RETRIEVED_AT,
        )
        market_data["raw_artifact_id"] = replacement.raw_artifact_id
        market_data["raw_artifact_sha256"] = replacement.raw_artifact_sha256

    cohort = _build_from_fixture(archive, calendar, payload)

    assert tuple(row.symbol for row in cohort.ranking) == tuple(
        f"X{index:03d}" for index in range(100)
    )
