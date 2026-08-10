"""Tests for the resolution-quality layer under the Agent Intelligence Ledger.

The Hypothesis Factory must learn only from labels with mechanically audited
resolution windows. These tests prove the audit primitives: maturity vs data
gaps, exit-bar availability, ticker/benchmark window matching, deterministic
non-trading-day handling, defer-instead-of-contaminate, retro-audit of
already-resolved labels, and machine-readable quality summaries.

2026-06-01 is a Monday; the synthetic week below uses real weekday math.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

from tradingagents.evals.agent_intelligence_ledger import (
    AgentForecast,
    audit_resolved_forecasts,
    load_ledger,
    resolve_forecasts,
    resolve_forecasts_with_quality,
    summarize_agent_scores,
    write_ledger,
)
from tradingagents.evals.resolution_quality import (
    DEFER_FINAL_BAR_MISSING,
    DEFER_MISSING_BENCHMARK_DATA,
    DEFER_MISSING_TICKER_DATA,
    DEFER_TICKER_FINAL_BAR_MISSING,
    DEFER_WINDOW_MISMATCH,
    LABEL_QUALITY_DEGRADED,
    LABEL_QUALITY_HIGH,
    LABEL_QUALITY_SUSPECT,
    STATUS_DEFERRED,
    STATUS_NOT_MATURE,
    STATUS_RESOLVABLE,
    PriceWindow,
    audit_resolution_window,
    expected_entry_session,
    expected_exit_session,
    price_window_from_bars,
    summarize_resolution_quality,
)

UTC = datetime.timezone.utc

MONDAY = "2026-06-01"
TUESDAY = "2026-06-02"
WEDNESDAY = "2026-06-03"
FRIDAY = "2026-06-05"
SATURDAY = "2026-06-06"
SUNDAY = "2026-06-07"
NEXT_MONDAY = "2026-06-08"
LONG_AFTER = datetime.datetime(2026, 6, 19, tzinfo=UTC)
RESOLUTION_EVENING = datetime.datetime(2026, 6, 8, 22, 0, tzinfo=UTC)

WEEK_SESSIONS = [MONDAY, TUESDAY, WEDNESDAY, "2026-06-04", FRIDAY, NEXT_MONDAY]


def _window(
    symbol: str,
    *,
    sessions: list[str] | None = None,
    start: str = MONDAY,
    end: str = NEXT_MONDAY,
    entry_close: str = "100",
    exit_close: str = "105",
) -> PriceWindow:
    dates = sessions if sessions is not None else WEEK_SESSIONS
    return PriceWindow(
        symbol=symbol,
        requested_start=start,
        requested_end=end,
        entry_date=dates[0],
        entry_close=entry_close,
        exit_date=dates[-1],
        exit_close=exit_close,
        session_count=len(dates),
    )


def _audit(ticker_window, benchmark_window, *, now=LONG_AFTER, start=MONDAY, end=NEXT_MONDAY):
    return audit_resolution_window(
        forecast_id="af-test",
        ticker="NVDA",
        benchmark="SPY",
        intended_start=start,
        intended_end=end,
        horizon="5 trading days",
        ticker_window=ticker_window,
        benchmark_window=benchmark_window,
        now=now,
    )


def test_expected_sessions_adjust_weekend_boundaries_deterministically():
    assert expected_entry_session(datetime.date(2026, 6, 6)) == datetime.date(2026, 6, 8)
    assert expected_entry_session(datetime.date(2026, 6, 1)) == datetime.date(2026, 6, 1)
    assert expected_exit_session(datetime.date(2026, 6, 7)) == datetime.date(2026, 6, 5)
    assert expected_exit_session(datetime.date(2026, 6, 8)) == datetime.date(2026, 6, 8)


def test_price_window_from_bars_filters_range_and_requires_two_bars():
    bars = [
        ("2026-05-29", "98"),  # before requested window
        (MONDAY, "100"),
        (TUESDAY, "101"),
        (NEXT_MONDAY, "105"),
        ("2026-06-09", "107"),  # after requested window
    ]
    window = price_window_from_bars(
        symbol="NVDA", requested_start=MONDAY, requested_end=NEXT_MONDAY, bars=bars
    )
    assert window is not None
    assert window.entry_date == MONDAY
    assert window.exit_date == NEXT_MONDAY
    assert window.entry_close == "100"
    assert window.exit_close == "105"
    assert window.session_count == 3
    assert (
        price_window_from_bars(
            symbol="NVDA",
            requested_start=MONDAY,
            requested_end=NEXT_MONDAY,
            bars=[(MONDAY, "100")],
        )
        is None
    )


def test_price_window_from_bars_skips_non_finite_closes():
    bars = [
        (MONDAY, "100"),
        (TUESDAY, "nan"),
        (WEDNESDAY, "101"),
        (NEXT_MONDAY, float("nan")),
    ]
    window = price_window_from_bars(
        symbol="NVDA", requested_start=MONDAY, requested_end=NEXT_MONDAY, bars=bars
    )
    assert window is not None
    assert window.entry_date == MONDAY
    assert window.exit_date == WEDNESDAY
    assert window.session_count == 2


def test_resolve_with_quality_defers_non_finite_price_windows():
    forecasts = [_pending_forecast("NVDA")]
    table = {
        "NVDA": _window("NVDA", entry_close="100", exit_close="nan"),
        "SPY": _window("SPY", entry_close="100", exit_close="102"),
    }
    resolved, reports = resolve_forecasts_with_quality(
        forecasts,
        window_lookup=_window_lookup_from(table),
        now=LONG_AFTER,
    )
    assert resolved[0].resolved is False
    assert reports[0].status == STATUS_DEFERRED
    assert reports[0].defer_reason == "invalid_window"


def test_clean_matching_windows_resolve_with_high_quality_label():
    report = _audit(_window("NVDA"), _window("SPY"))
    assert report.status == STATUS_RESOLVABLE
    assert report.label_quality == LABEL_QUALITY_HIGH
    assert report.quality_flags == ()
    assert report.defer_reason is None
    window = report.window
    assert window is not None
    assert window.ticker_entry_date == MONDAY
    assert window.ticker_exit_date == NEXT_MONDAY
    assert window.benchmark_entry_date == MONDAY
    assert window.benchmark_exit_date == NEXT_MONDAY
    assert window.final_bar_available is True
    assert window.expected_entry_session == MONDAY
    assert window.expected_exit_session == NEXT_MONDAY
    assert window.expected_session_count == 6
    assert window.horizon_kind == "trading_days_weekend_adjusted"


def test_weekend_intended_end_resolves_deterministically_without_flags():
    # Intended end on Sunday: the expected exit session is Friday.
    sessions = WEEK_SESSIONS[:-1]  # Monday..Friday
    report = _audit(
        _window("NVDA", sessions=sessions, end=SUNDAY),
        _window("SPY", sessions=sessions, end=SUNDAY),
        end=SUNDAY,
    )
    assert report.status == STATUS_RESOLVABLE
    assert report.label_quality == LABEL_QUALITY_HIGH
    assert report.window.expected_exit_session == FRIDAY
    assert report.window.final_bar_available is True


def test_missing_final_bar_defers_when_session_is_recent():
    # Both legs stop on Friday but the window intends Monday; at Monday-evening
    # resolution time the bar may simply not have printed yet -> defer.
    sessions = WEEK_SESSIONS[:-1]
    report = _audit(
        _window("NVDA", sessions=sessions),
        _window("SPY", sessions=sessions),
        now=RESOLUTION_EVENING,
    )
    assert report.status == STATUS_DEFERRED
    assert report.defer_reason == DEFER_FINAL_BAR_MISSING
    assert report.label_quality is None


def test_missing_final_bar_long_ago_is_assumed_market_holiday_and_degraded():
    sessions = WEEK_SESSIONS[:-1]
    report = _audit(
        _window("NVDA", sessions=sessions),
        _window("SPY", sessions=sessions),
        now=LONG_AFTER,
    )
    assert report.status == STATUS_RESOLVABLE
    assert report.label_quality == LABEL_QUALITY_DEGRADED
    assert "assumed_market_holiday_at_window_end" in report.quality_flags
    assert report.window.final_bar_available is True


def test_benchmark_missing_more_than_one_session_defers():
    sessions = WEEK_SESSIONS[:-2]  # Monday..Thursday; Friday and Monday missing
    report = _audit(
        _window("NVDA", sessions=sessions),
        _window("SPY", sessions=sessions),
        now=LONG_AFTER,
    )
    assert report.status == STATUS_DEFERRED
    assert report.defer_reason == DEFER_FINAL_BAR_MISSING


def test_ticker_missing_final_bar_defers_as_stale_ticker_data():
    report = _audit(
        _window("NVDA", sessions=WEEK_SESSIONS[:-1]),
        _window("SPY"),
    )
    assert report.status == STATUS_DEFERRED
    assert report.defer_reason == DEFER_TICKER_FINAL_BAR_MISSING


def test_entry_session_mismatch_defers_with_window_mismatch_reason():
    report = _audit(
        _window("NVDA", sessions=WEEK_SESSIONS[1:]),
        _window("SPY"),
    )
    assert report.status == STATUS_DEFERRED
    assert report.defer_reason == DEFER_WINDOW_MISMATCH
    assert "entry_session_mismatch" in report.quality_flags


def test_missing_windows_defer_with_distinct_reasons():
    missing_ticker = _audit(None, _window("SPY"))
    assert missing_ticker.status == STATUS_DEFERRED
    assert missing_ticker.defer_reason == DEFER_MISSING_TICKER_DATA
    missing_benchmark = _audit(_window("NVDA"), None)
    assert missing_benchmark.status == STATUS_DEFERRED
    assert missing_benchmark.defer_reason == DEFER_MISSING_BENCHMARK_DATA


def test_mid_window_holiday_is_flagged_and_degraded():
    sessions = [MONDAY, TUESDAY, "2026-06-04", FRIDAY, NEXT_MONDAY]  # no Wednesday
    report = _audit(
        _window("NVDA", sessions=sessions),
        _window("SPY", sessions=sessions),
    )
    assert report.status == STATUS_RESOLVABLE
    assert report.label_quality == LABEL_QUALITY_DEGRADED
    assert "missing_weekday_sessions_inside_window" in report.quality_flags


def test_summary_separates_not_mature_data_gaps_and_quality_tiers():
    reports = [
        _audit(_window("NVDA"), _window("SPY")),
        _audit(None, _window("SPY")),
        _audit(
            _window("NVDA", sessions=WEEK_SESSIONS[:-1]),
            _window("SPY", sessions=WEEK_SESSIONS[:-1]),
            now=LONG_AFTER,
        ),
    ]
    reports.append(
        audit_resolution_window(
            forecast_id="af-future",
            ticker="NVDA",
            benchmark="SPY",
            intended_start=MONDAY,
            intended_end=NEXT_MONDAY,
            horizon="5 trading days",
            ticker_window=None,
            benchmark_window=None,
            now=LONG_AFTER,
            mature=False,
        )
    )
    summary = summarize_resolution_quality(reports, unaudited_resolved_count=7)
    assert summary["kind"] == "resolution_quality_summary"
    assert summary["analysis_only"] is True
    assert summary["can_submit_orders"] is False
    assert summary["execution_authority"] == "none"
    assert summary["status_counts"][STATUS_RESOLVABLE] == 2
    assert summary["status_counts"][STATUS_DEFERRED] == 1
    assert summary["status_counts"][STATUS_NOT_MATURE] == 1
    assert summary["label_quality_counts"][LABEL_QUALITY_HIGH] == 1
    assert summary["label_quality_counts"][LABEL_QUALITY_DEGRADED] == 1
    assert summary["defer_reason_counts"][DEFER_MISSING_TICKER_DATA] == 1
    assert summary["quality_flag_counts"]["assumed_market_holiday_at_window_end"] == 1
    assert summary["trusted_label_count"] == 2
    assert summary["unaudited_resolved_count"] == 7


def _pending_forecast(
    ticker: str,
    *,
    created_at: str = f"{MONDAY}T12:00:00+00:00",
    resolve_after: str = f"{NEXT_MONDAY}T12:00:00+00:00",
    direction: str = "bullish",
    probability: str = "0.60",
) -> AgentForecast:
    return AgentForecast(
        forecast_id=f"af-quality-{ticker}-{created_at}",
        agent="market_analyst",
        ticker=ticker,
        claim=f"{ticker} test claim",
        forecast_type="test_direction",
        horizon="5 trading days",
        probability=probability,
        expected_outcome=f"{ticker} outperforms SPY by >1.5%",
        direction=direction,
        created_at=created_at,
        resolve_after=resolve_after,
    )


def _window_lookup_from(table):
    def lookup(symbol, start_date, end_date):
        return table.get(symbol)

    return lookup


def test_resolve_with_quality_scores_clean_windows_and_stamps_audit_metadata():
    forecasts = [_pending_forecast("NVDA")]
    table = {
        "NVDA": _window("NVDA", entry_close="100", exit_close="110"),
        "SPY": _window("SPY", entry_close="100", exit_close="102"),
    }
    resolved, reports = resolve_forecasts_with_quality(
        forecasts,
        window_lookup=_window_lookup_from(table),
        now=LONG_AFTER,
    )
    record = resolved[0]
    assert record.resolved is True
    assert record.outcome is True
    assert record.actual_return == "10.00"
    assert record.benchmark_return == "2.00"
    assert record.relative_return == "8.00"
    assert record.label_quality == LABEL_QUALITY_HIGH
    assert record.quality_flags == []
    assert record.defer_reason is None
    assert record.resolution_note == "resolved against audited relative return window"
    assert record.resolution_window["ticker_exit_date"] == NEXT_MONDAY
    assert record.resolution_window["benchmark_exit_date"] == NEXT_MONDAY
    assert record.resolution_window["final_bar_available"] is True
    assert len(reports) == 1
    assert reports[0].status == STATUS_RESOLVABLE


def test_resolve_with_quality_defers_instead_of_contaminating():
    forecasts = [_pending_forecast("MSFT")]
    table = {
        "MSFT": _window("MSFT", sessions=WEEK_SESSIONS[:-1]),
        "SPY": _window("SPY"),
    }
    resolved, reports = resolve_forecasts_with_quality(
        forecasts,
        window_lookup=_window_lookup_from(table),
        now=LONG_AFTER,
    )
    record = resolved[0]
    assert record.resolved is False
    assert record.outcome is None
    assert record.defer_reason == DEFER_TICKER_FINAL_BAR_MISSING
    assert record.resolution_note.startswith("deferred:")
    assert reports[0].status == STATUS_DEFERRED


def test_resolve_with_quality_reports_not_mature_forecasts():
    future = _pending_forecast(
        "NVDA",
        created_at="2026-06-15T12:00:00+00:00",
        resolve_after="2026-06-22T12:00:00+00:00",
    )
    resolved, reports = resolve_forecasts_with_quality(
        [future],
        window_lookup=_window_lookup_from({}),
        now=LONG_AFTER,
    )
    assert resolved[0].resolved is False
    assert reports[0].status == STATUS_NOT_MATURE


def test_legacy_price_lookup_path_is_unchanged_and_unaudited():
    forecasts = [_pending_forecast("NVDA")]

    def price_lookup(symbol, start_date, end_date):
        return (Decimal("100"), Decimal("110")) if symbol == "NVDA" else (
            Decimal("100"),
            Decimal("102"),
        )

    resolved = resolve_forecasts(forecasts, price_lookup=price_lookup, now=LONG_AFTER)
    record = resolved[0]
    assert record.resolved is True
    assert record.resolution_note == "resolved against relative return window"
    assert record.label_quality is None
    assert record.resolution_window is None


def test_quality_fields_round_trip_through_the_jsonl_ledger(tmp_path):
    table = {
        "NVDA": _window("NVDA", entry_close="100", exit_close="110"),
        "SPY": _window("SPY", entry_close="100", exit_close="102"),
    }
    resolved, _reports = resolve_forecasts_with_quality(
        [_pending_forecast("NVDA")],
        window_lookup=_window_lookup_from(table),
        now=LONG_AFTER,
    )
    ledger_path = tmp_path / "ledger.jsonl"
    write_ledger(resolved, path=ledger_path)
    loaded = load_ledger(ledger_path)[0]
    assert loaded.label_quality == LABEL_QUALITY_HIGH
    assert loaded.resolution_window["expected_exit_session"] == NEXT_MONDAY
    assert loaded.defer_reason is None
    # Old rows without the new keys must still load.
    row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])
    for key in ("label_quality", "quality_flags", "resolution_window", "defer_reason"):
        row.pop(key)
    legacy_path = tmp_path / "legacy.jsonl"
    legacy_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    legacy = load_ledger(legacy_path)[0]
    assert legacy.label_quality is None
    assert legacy.quality_flags == []


def _resolved_forecast(ticker: str, *, outcome: bool, relative_return: str) -> AgentForecast:
    base = _pending_forecast(ticker)
    return AgentForecast(
        **{
            **base.as_dict(),
            "resolved": True,
            "outcome": outcome,
            "actual_return": "10.00" if outcome else "0.00",
            "benchmark_return": "2.00",
            "relative_return": relative_return,
            "brier_score": "0.16",
            "agent_score_delta": "0.10",
            "resolved_at": f"{NEXT_MONDAY}T22:00:00+00:00",
            "resolution_note": "resolved against relative return window",
        }
    )


def test_retro_audit_confirms_stable_labels_and_marks_unstable_ones_suspect():
    stable = _resolved_forecast("NVDA", outcome=True, relative_return="8.00")
    unstable = _resolved_forecast("MSFT", outcome=True, relative_return="8.00")
    unverifiable = _resolved_forecast("TSLA", outcome=True, relative_return="8.00")
    table = {
        "NVDA": _window("NVDA", entry_close="100", exit_close="110"),
        # MSFT recomputes to a losing relative return -> stored label unstable.
        "MSFT": _window("MSFT", entry_close="100", exit_close="101"),
        "SPY": _window("SPY", entry_close="100", exit_close="102"),
    }
    audited, reports = audit_resolved_forecasts(
        [stable, unstable, unverifiable],
        window_lookup=_window_lookup_from(table),
        now=LONG_AFTER,
    )
    by_ticker = {forecast.ticker: forecast for forecast in audited}
    assert by_ticker["NVDA"].label_quality == LABEL_QUALITY_HIGH
    assert by_ticker["NVDA"].outcome is True
    assert by_ticker["MSFT"].label_quality == LABEL_QUALITY_SUSPECT
    assert "reaudit_outcome_mismatch" in by_ticker["MSFT"].quality_flags
    assert by_ticker["MSFT"].outcome is True  # history is annotated, never rewritten
    assert by_ticker["TSLA"].label_quality == LABEL_QUALITY_SUSPECT
    assert "window_unverifiable" in by_ticker["TSLA"].quality_flags
    assert len(reports) == 3
    summary = summarize_resolution_quality(reports)
    assert summary["label_quality_counts"][LABEL_QUALITY_SUSPECT] == 2
    assert summary["label_quality_counts"][LABEL_QUALITY_HIGH] == 1


def test_agent_score_summary_counts_label_quality_tiers():
    table = {
        "NVDA": _window("NVDA", entry_close="100", exit_close="110"),
        "SPY": _window("SPY", entry_close="100", exit_close="102"),
    }
    resolved, _ = resolve_forecasts_with_quality(
        [_pending_forecast("NVDA")],
        window_lookup=_window_lookup_from(table),
        now=LONG_AFTER,
    )
    legacy = _resolved_forecast("IBM", outcome=False, relative_return="-1.00")
    summary = summarize_agent_scores([*resolved, legacy, _pending_forecast("AMD")])
    assert summary["label_quality_counts"] == {"high": 1, "unaudited": 1}
