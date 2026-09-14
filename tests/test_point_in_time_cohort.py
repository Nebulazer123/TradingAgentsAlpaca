"""Focused contracts for source-verifiable point-in-time economic cohorts."""

from __future__ import annotations

import copy
import datetime as dt
import json
from decimal import localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    SecurityIdentity,
    build_market_session_calendar,
    build_source_verifiable_point_in_time_cohort,
    validate_nonqualifying_point_in_time_cohort_record,
    verify_source_verifiable_point_in_time_cohort,
)

MARKET_DATE = "2026-04-01"
AS_OF_CUTOFF = "2026-04-01T11:55:00+00:00"
SELECTION_TIME = "2026-04-01T12:00:00+00:00"
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
    master_overrides: dict[int, dict[str, object]] | None = None,
    symbol_overrides: dict[int, str] | None = None,
    source_retrieved_at: str = SOURCE_RETRIEVED_AT,
    archive_recorded_at: dt.datetime = ARCHIVE_RECORDED_AT,
) -> tuple[RawPointInTimeArtifactArchive, object, dict[str, object]]:
    """Retain honest, distinct calendar, Alpaca asset, security-master, and bar shapes."""

    archive = RawPointInTimeArtifactArchive(
        root,
        clock=lambda: archive_recorded_at,
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
        source_uri=(
            "https://paper-api.alpaca.markets/v2/calendar"
            f"?start={market_dates[0]}&end={MARKET_DATE}"
        ),
        content_type="application/json",
        retrieved_at=source_retrieved_at,
    )
    calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=calendar_artifact,
    )
    session_dates = market_dates[:-1]
    candidates: list[dict[str, object]] = []
    for index in range(candidate_count):
        symbol = (symbol_overrides or {}).get(index, f"X{index:03d}")
        security_id = f"security-us-{symbol.lower()}-common"
        asset_payload: dict[str, object] = {
            "id": security_id,
            "symbol": symbol,
            "exchange": "NASDAQ",
            "class": "us_equity",
            "status": "active",
            "tradable": True,
        }
        asset_payload.update((asset_overrides or {}).get(index, {}))
        asset_artifact = archive.admit(
            raw_bytes=json.dumps(asset_payload, separators=(",", ":")).encode(),
            source_uri=f"https://paper-api.alpaca.markets/v2/assets/{symbol}",
            content_type="application/json",
            retrieved_at=source_retrieved_at,
        )
        master_payload: dict[str, object] = {
            "security_id": security_id,
            "symbol": symbol,
            "security_type": "common_stock",
            "effective_from": "2020-01-01",
            "effective_to": None,
        }
        master_payload.update((master_overrides or {}).get(index, {}))
        master_artifact = archive.admit(
            raw_bytes=json.dumps(master_payload, separators=(",", ":")).encode(),
            source_uri=(
                "https://security-master.tradingagents.local"
                f"/v1/securities/{security_id}"
            ),
            content_type="application/json",
            retrieved_at=source_retrieved_at,
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
            source_hashes={
                "alpaca_asset": asset_artifact.raw_artifact_sha256,
                "security_master": master_artifact.raw_artifact_sha256,
            },
        )
        bars = [
            {
                "t": _daily_bar_timestamp(session_date),
                "c": 10,
                "v": index + 1,
            }
            for session_date in session_dates
        ]
        bars_payload = {"bars": bars, "symbol": symbol, "next_page_token": None}
        bars_uri = (
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
            f"?timeframe=1Day&feed=sip&adjustment=raw"
            f"&start={session_dates[0]}T00:00:00Z&end={MARKET_DATE}T00:00:00Z"
        )
        bars_artifact = archive.admit(
            raw_bytes=json.dumps(bars_payload, separators=(",", ":")).encode(),
            source_uri=bars_uri,
            content_type="application/json",
            retrieved_at=source_retrieved_at,
        )
        candidates.append(
            {
                "security": security.to_dict(),
                "identity_sources": [
                    {
                        "source_profile": "alpaca_asset/v1",
                        "record_identity": symbol,
                        "raw_artifact_id": asset_artifact.raw_artifact_id,
                        "raw_artifact_sha256": asset_artifact.raw_artifact_sha256,
                    },
                    {
                        "source_profile": "security_master/v1",
                        "record_identity": security_id,
                        "raw_artifact_id": master_artifact.raw_artifact_id,
                        "raw_artifact_sha256": master_artifact.raw_artifact_sha256,
                    },
                ],
                "market_data_source": {
                    "source_profile": "alpaca_stock_daily_bars/v1",
                    "record_identity": symbol,
                    "raw_artifact_id": bars_artifact.raw_artifact_id,
                    "raw_artifact_sha256": bars_artifact.raw_artifact_sha256,
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


def _candidate_source(candidate: dict[str, object], profile: str) -> dict[str, object]:
    sources = candidate["identity_sources"]
    assert isinstance(sources, list)
    return next(source for source in sources if source["source_profile"] == profile)


def _replace_bars(
    archive: RawPointInTimeArtifactArchive,
    payload: dict[str, object],
    index: int,
    source: dict[str, object],
    *,
    source_uri: str | None = None,
) -> None:
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidate = candidates[index]
    reference = candidate["market_data_source"]
    assert isinstance(reference, dict)
    original = archive.read_artifact(reference["raw_artifact_id"])
    replacement = archive.admit(
        raw_bytes=json.dumps(source, separators=(",", ":")).encode(),
        source_uri=source_uri or original.source_uri,
        content_type="application/json",
        retrieved_at=SOURCE_RETRIEVED_AT,
    )
    reference["raw_artifact_id"] = replacement.raw_artifact_id
    reference["raw_artifact_sha256"] = replacement.raw_artifact_sha256


def test_source_verifiable_cohort_rebuilds_profiles_ranked_prefixes_and_rejections(
    tmp_path: Path,
):
    archive, calendar, payload = _source_cohort_fixture(
        tmp_path / "pit",
        candidate_count=109,
        asset_overrides={
            104: {"exchange": "OTC"},
            105: {"status": "inactive"},
            106: {"tradable": False},
            107: {"class": "crypto"},
        },
        master_overrides={
            100: {"security_type": "etf"},
            101: {"security_type": "etn"},
            102: {"security_type": "preferred_stock"},
            103: {"security_type": "warrant"},
            108: {"effective_from": MARKET_DATE},
        },
    )

    cohort = _build_from_fixture(archive, calendar, payload)

    assert cohort.as_of_cutoff <= cohort.selection_time <= cohort.selection_window_close_at
    assert cohort.market_session_open_at == cohort.selection_window_close_at
    assert cohort.session_dates[-1] == "2026-03-31"
    assert cohort.ranking[0].symbol == "X099"
    assert cohort.sensitivity_universe_100 == tuple(row.symbol for row in cohort.ranking[:100])
    assert cohort.primary_universe_75 == cohort.sensitivity_universe_100[:75]
    assert cohort.sensitivity_universe_50 == cohort.sensitivity_universe_100[:50]
    assert cohort.primary_universe_75 != tuple(sorted(cohort.primary_universe_75))
    reasons = {row.symbol: row.reasons for row in cohort.rejections}
    assert "security_type_etf" in reasons["X100"]
    assert "security_type_etn" in reasons["X101"]
    assert "security_type_preferred" in reasons["X102"]
    assert "security_type_warrant" in reasons["X103"]
    assert "exchange_otc" in reasons["X104"]
    assert "asset_status_not_active" in reasons["X105"]
    assert "asset_not_tradable" in reasons["X106"]
    assert "asset_class_not_us_equity" in reasons["X107"]
    assert "identity_not_effective_for_full_window" in reasons["X108"]
    assert tuple(
        source.source_profile for source in cohort.candidates[0].identity_sources
    ) == ("alpaca_asset/v1", "security_master/v1")
    serialized = cohort.canonical_json_bytes()
    assert b"session_dollar_volumes" not in serialized
    assert validate_nonqualifying_point_in_time_cohort_record(json.loads(serialized)) == cohort
    assert verify_source_verifiable_point_in_time_cohort(
        archive=archive,
        value=json.loads(serialized),
    ) == cohort


def test_code_owned_profiles_defeat_shadow_fields_wrong_paths_and_source_reordering(
    tmp_path: Path,
):
    archive, calendar, payload = _source_cohort_fixture(
        tmp_path / "pit",
        candidate_count=102,
        asset_overrides={
            100: {
                "exchange": "OTC",
                "class": "crypto",
                "status": "inactive",
                "tradable": False,
                "shadow": {
                    "id": "security-us-x100-common",
                    "symbol": "X100",
                    "exchange": "NASDAQ",
                    "class": "us_equity",
                    "status": "active",
                    "tradable": True,
                },
            }
        },
        master_overrides={
            101: {
                "security_type": "etf",
                "effective_from": MARKET_DATE,
                "shadow": {
                    "security_id": "security-us-x101-common",
                    "symbol": "X101",
                    "security_type": "common_stock",
                    "effective_from": "2020-01-01",
                    "effective_to": None,
                },
            }
        },
    )
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    canonical_order = _build_from_fixture(archive, calendar, copy.deepcopy(payload))
    candidates[0]["identity_sources"].reverse()

    cohort = _build_from_fixture(archive, calendar, payload)

    assert cohort.canonical_json_bytes() == canonical_order.canonical_json_bytes()
    reasons = {row.symbol: row.reasons for row in cohort.rejections}
    assert {
        "exchange_otc",
        "asset_status_not_active",
        "asset_class_not_us_equity",
        "asset_not_tradable",
    } <= set(reasons["X100"])
    assert {"security_type_etf", "identity_not_effective_for_full_window"} <= set(
        reasons["X101"]
    )
    assert tuple(
        source.source_profile for source in cohort.candidates[0].identity_sources
    ) == ("alpaca_asset/v1", "security_master/v1")

    bypass = copy.deepcopy(payload)
    bypass_candidates = bypass["candidates"]
    assert isinstance(bypass_candidates, list)
    bypass_source = _candidate_source(bypass_candidates[0], "alpaca_asset/v1")
    bypass_source["qualification_field_selectors"] = {
        role: ["shadow", role]
        for role in ("security_id", "symbol", "exchange", "asset_class", "status", "tradable")
    }
    with pytest.raises(PointInTimeDataError, match="fields are invalid"):
        _build_from_fixture(archive, calendar, bypass)


def test_one_and_two_character_alpaca_symbols_build_serialize_and_reverify(
    tmp_path: Path,
):
    archive, calendar, payload = _source_cohort_fixture(
        tmp_path / "pit",
        symbol_overrides={0: "A", 1: "BR"},
    )

    cohort = _build_from_fixture(archive, calendar, payload)
    serialized = cohort.canonical_json_bytes()
    rebuilt = validate_nonqualifying_point_in_time_cohort_record(json.loads(serialized))
    reverified = verify_source_verifiable_point_in_time_cohort(
        archive=archive,
        value=json.loads(serialized),
    )

    candidates = {candidate.security.symbol: candidate for candidate in cohort.candidates}
    assert {"A", "BR"} <= set(candidates)
    assert candidates["A"].identity_sources[0].record_identity == "A"
    assert candidates["BR"].identity_sources[0].record_identity == "BR"
    assert rebuilt.canonical_json_bytes() == serialized
    assert reverified.canonical_json_bytes() == serialized


def test_exact_liquidity_and_even_median_ignore_ambient_decimal_context(tmp_path: Path):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    huge = 10**60
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    for index, upper_delta in ((0, 2), (1, 4)):
        symbol = candidates[index]["security"]["symbol"]
        bars = [
            {
                "t": _daily_bar_timestamp(session_date),
                "c": huge if row_index < 30 else huge + upper_delta,
                "v": 1,
            }
            for row_index, session_date in enumerate(_registered_market_dates()[:-1])
        ]
        _replace_bars(
            archive,
            payload,
            index,
            {"bars": bars, "symbol": symbol, "next_page_token": None},
        )

    with localcontext() as context:
        context.prec = 9
        low_precision = _build_from_fixture(archive, calendar, payload)
    with localcontext() as context:
        context.prec = 80
        high_precision = _build_from_fixture(archive, calendar, payload)

    assert low_precision.canonical_json_bytes() == high_precision.canonical_json_bytes()
    assert low_precision.ranking[0].symbol == "X001"
    by_symbol = {candidate.security.symbol: candidate for candidate in low_precision.candidates}
    assert by_symbol["X000"].median_daily_dollar_volume == str(huge + 1)
    assert by_symbol["X001"].median_daily_dollar_volume == str(huge + 2)


def test_source_verifiable_cohort_rejects_bad_bar_sets_and_numeric_limits(tmp_path: Path):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    reference = candidates[0]["market_data_source"]
    artifact = archive.read_artifact(reference["raw_artifact_id"])
    original = json.loads(archive.read_bytes(artifact))
    bars = original["bars"]
    mutations = (
        bars[:-1],
        [*bars[:-1], bars[0]],
        [*bars, bars[-1]],
        list(reversed(bars)),
    )
    for changed_bars in mutations:
        changed = copy.deepcopy(payload)
        _replace_bars(
            archive,
            changed,
            0,
            {"bars": changed_bars, "symbol": "X000", "next_page_token": None},
        )
        with pytest.raises(PointInTimeDataError, match="60|session"):
            _build_from_fixture(archive, calendar, changed)

    for field in ("c", "v"):
        changed = copy.deepcopy(payload)
        oversized = copy.deepcopy(bars)
        oversized[0][field] = 10**128
        _replace_bars(
            archive,
            changed,
            0,
            {"bars": oversized, "symbol": "X000", "next_page_token": None},
        )
        with pytest.raises(PointInTimeDataError, match="numeric|bounded"):
            _build_from_fixture(archive, calendar, changed)


def test_selection_window_and_archive_time_are_prospective(tmp_path: Path):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    reversed_times = copy.deepcopy(payload)
    reversed_times["as_of_cutoff"] = "2026-04-01T12:05:00+00:00"
    with pytest.raises(PointInTimeDataError, match="pre-open window"):
        _build_from_fixture(archive, calendar, reversed_times)

    after_open = copy.deepcopy(payload)
    after_open["selection_time"] = "2026-04-01T14:00:00+00:00"
    with pytest.raises(PointInTimeDataError, match="pre-open window"):
        _build_from_fixture(archive, calendar, after_open)

    unregistered = copy.deepcopy(payload)
    unregistered["market_date"] = "2026-04-02"
    with pytest.raises(PointInTimeDataError, match="registered"):
        _build_from_fixture(archive, calendar, unregistered)

    late_archive, late_calendar, late_payload = _source_cohort_fixture(
        tmp_path / "late-pit",
        source_retrieved_at="2026-04-01T11:56:00+00:00",
        archive_recorded_at=dt.datetime(2026, 4, 1, 11, 57, tzinfo=dt.UTC),
    )
    with pytest.raises(PointInTimeDataError, match="after as_of_cutoff"):
        _build_from_fixture(late_archive, late_calendar, late_payload)


def test_exact_uri_provenance_rejects_ports_suffixes_encodings_and_query_aliases(
    tmp_path: Path,
):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    calendar_artifact = archive.read_artifact(calendar.raw_artifact_id)
    calendar_bytes = archive.read_bytes(calendar_artifact)
    calendar_start = _registered_market_dates()[0]
    calendar_base = (
        "https://paper-api.alpaca.markets/v2/calendar"
        f"?start={calendar_start}&end={MARKET_DATE}"
    )
    assert calendar_artifact.source_uri == calendar_base
    bad_calendar_uris = (
        "https://paper-api.alpaca.markets/v2/calendar",
        (
            "https://paper-api.alpaca.markets/v2/calendar"
            f"?end={MARKET_DATE}&start={calendar_start}"
        ),
        calendar_base + f"&start={calendar_start}",
        calendar_base + "&extra=1",
        calendar_base.replace(
            calendar_start,
            calendar_start.replace("-", "%2D"),
        ),
    )
    for uri in bad_calendar_uris:
        replacement = archive.admit(
            raw_bytes=calendar_bytes,
            source_uri=uri,
            content_type="application/json",
            retrieved_at=SOURCE_RETRIEVED_AT,
        )
        replacement_calendar = build_market_session_calendar(
            archive=archive,
            raw_artifact=replacement,
        )
        with pytest.raises(PointInTimeDataError, match="calendar URI"):
            _build_from_fixture(archive, replacement_calendar, payload)

    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidate = candidates[0]
    asset_ref = _candidate_source(candidate, "alpaca_asset/v1")
    asset_artifact = archive.read_artifact(asset_ref["raw_artifact_id"])
    asset_bytes = archive.read_bytes(asset_artifact)
    bad_asset_uris = (
        "https://paper-api.alpaca.markets:8443/v2/assets/X000",
        "https://paper-api.alpaca.markets/v2/assets/X000/extra",
        "https://paper-api.alpaca.markets/v2/assets/%58000",
    )
    for uri in bad_asset_uris:
        changed = copy.deepcopy(payload)
        changed_candidates = changed["candidates"]
        assert isinstance(changed_candidates, list)
        changed_ref = _candidate_source(changed_candidates[0], "alpaca_asset/v1")
        replacement = archive.admit(
            raw_bytes=asset_bytes,
            source_uri=uri,
            content_type="application/json",
            retrieved_at=SOURCE_RETRIEVED_AT,
        )
        changed_ref["raw_artifact_id"] = replacement.raw_artifact_id
        with pytest.raises(PointInTimeDataError, match="URI/content profile"):
            _build_from_fixture(archive, calendar, changed)

    market_ref = candidate["market_data_source"]
    market_artifact = archive.read_artifact(market_ref["raw_artifact_id"])
    market_source = json.loads(archive.read_bytes(market_artifact))
    base = market_artifact.source_uri
    bad_market_uris = (
        base.replace("data.alpaca.markets", "data.alpaca.markets:8443"),
        base.replace("timeframe=1Day&feed=sip", "feed=sip&timeframe=1Day"),
        base + "&feed=sip",
        base + "&extra=1",
        base.replace("1Day", "%31Day"),
    )
    for uri in bad_market_uris:
        changed = copy.deepcopy(payload)
        _replace_bars(archive, changed, 0, market_source, source_uri=uri)
        with pytest.raises(PointInTimeDataError, match="canonical Alpaca"):
            _build_from_fixture(archive, calendar, changed)


@pytest.mark.parametrize(
    ("extra_row", "position"),
    (
        ({"date": "2026-01-06", "open": "09:30", "close": "16:00"}, "before"),
        ({"date": "2026-04-02", "open": "09:30", "close": "16:00"}, "after"),
    ),
)
def test_calendar_source_rejects_rows_outside_exact_requested_61_sessions(
    tmp_path: Path,
    extra_row: dict[str, object],
    position: str,
):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / position)
    artifact = archive.read_artifact(calendar.raw_artifact_id)
    rows = json.loads(archive.read_bytes(artifact))
    assert isinstance(rows, list)
    changed_rows = [extra_row, *rows] if position == "before" else [*rows, extra_row]
    replacement = archive.admit(
        raw_bytes=json.dumps(changed_rows, separators=(",", ":")).encode(),
        source_uri=artifact.source_uri,
        content_type="application/json",
        retrieved_at=SOURCE_RETRIEVED_AT,
    )
    replacement_calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=replacement,
    )

    with pytest.raises(PointInTimeDataError, match="exactly the requested 61"):
        _build_from_fixture(archive, replacement_calendar, payload)


def test_resource_limits_reject_before_unbounded_candidate_or_artifact_work(tmp_path: Path):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    too_many = copy.deepcopy(payload)
    too_many["candidates"] = [candidates[0]] * 513
    with pytest.raises(PointInTimeDataError, match="candidate count"):
        _build_from_fixture(archive, calendar, too_many)

    extra_source = copy.deepcopy(payload)
    extra_candidates = extra_source["candidates"]
    assert isinstance(extra_candidates, list)
    extra_candidates[0]["identity_sources"].append(
        copy.deepcopy(extra_candidates[0]["identity_sources"][0])
    )
    with pytest.raises(PointInTimeDataError, match="exactly two"):
        _build_from_fixture(archive, calendar, extra_source)

    oversized = copy.deepcopy(payload)
    oversized_candidates = oversized["candidates"]
    assert isinstance(oversized_candidates, list)
    oversized_candidate = oversized_candidates[0]
    oversized_ref = _candidate_source(oversized_candidate, "alpaca_asset/v1")
    oversized_payload = {
        "id": "security-us-x000-common",
        "symbol": "X000",
        "exchange": "NASDAQ",
        "class": "us_equity",
        "status": "active",
        "tradable": True,
        "padding": "x" * 65_000,
    }
    oversized_artifact = archive.admit(
        raw_bytes=json.dumps(oversized_payload, separators=(",", ":")).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/assets/X000",
        content_type="application/json",
        retrieved_at=SOURCE_RETRIEVED_AT,
    )
    oversized_ref["raw_artifact_id"] = oversized_artifact.raw_artifact_id
    oversized_ref["raw_artifact_sha256"] = oversized_artifact.raw_artifact_sha256
    oversized_candidate["security"]["source_hashes"][
        "alpaca_asset"
    ] = oversized_artifact.raw_artifact_sha256
    with pytest.raises(PointInTimeDataError, match="byte limit"):
        _build_from_fixture(archive, calendar, oversized)

    deep = copy.deepcopy(payload)
    deep_candidates = deep["candidates"]
    assert isinstance(deep_candidates, list)
    deep_candidate = deep_candidates[0]
    deep_ref = _candidate_source(deep_candidate, "alpaca_asset/v1")
    nested: object = True
    for _ in range(14):
        nested = [nested]
    deep_payload = {
        "id": "security-us-x000-common",
        "symbol": "X000",
        "exchange": "NASDAQ",
        "class": "us_equity",
        "status": "active",
        "tradable": True,
        "shadow": nested,
    }
    deep_artifact = archive.admit(
        raw_bytes=json.dumps(deep_payload, separators=(",", ":")).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/assets/X000",
        content_type="application/json",
        retrieved_at=SOURCE_RETRIEVED_AT,
    )
    deep_ref["raw_artifact_id"] = deep_artifact.raw_artifact_id
    deep_ref["raw_artifact_sha256"] = deep_artifact.raw_artifact_sha256
    deep_candidate["security"]["source_hashes"][
        "alpaca_asset"
    ] = deep_artifact.raw_artifact_sha256
    with pytest.raises(PointInTimeDataError, match="depth/node"):
        _build_from_fixture(archive, calendar, deep)


def test_source_verifiable_cohort_rejects_caller_truth_and_duplicate_profiles(tmp_path: Path):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    caller_authored = copy.deepcopy(payload)
    caller_candidates = caller_authored["candidates"]
    assert isinstance(caller_candidates, list)
    caller_candidates[0]["prior_complete_close"] = "999"
    with pytest.raises(PointInTimeDataError, match="fields are invalid"):
        _build_from_fixture(archive, calendar, caller_authored)

    duplicate = copy.deepcopy(payload)
    duplicate_candidates = duplicate["candidates"]
    assert isinstance(duplicate_candidates, list)
    duplicate_candidates[0]["identity_sources"][1] = copy.deepcopy(
        duplicate_candidates[0]["identity_sources"][0]
    )
    with pytest.raises(PointInTimeDataError, match="profiles"):
        _build_from_fixture(archive, calendar, duplicate)


def test_source_verifiable_cohort_tie_breaks_by_symbol_then_security_id(tmp_path: Path):
    archive, calendar, payload = _source_cohort_fixture(tmp_path / "pit")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    for index, candidate in enumerate(candidates):
        symbol = candidate["security"]["symbol"]
        bars = [
            {"t": _daily_bar_timestamp(session_date), "c": 10, "v": 1}
            for session_date in _registered_market_dates()[:-1]
        ]
        _replace_bars(
            archive,
            payload,
            index,
            {"bars": bars, "symbol": symbol, "next_page_token": None},
        )

    cohort = _build_from_fixture(archive, calendar, payload)

    assert tuple(row.symbol for row in cohort.ranking) == tuple(
        f"X{index:03d}" for index in range(100)
    )
