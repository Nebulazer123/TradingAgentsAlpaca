"""Resolution-quality layer for the Agent Intelligence Ledger.

Forecast resolution is only as trustworthy as its price windows. This module
mechanically audits every resolution window before a label is written:

- Was the forecast actually mature?
- Was the final expected session bar available, or merely the latest bar?
- Did the ticker and the benchmark measure the exact same sessions?
- Were weekend boundaries adjusted deterministically, and were market
  holidays distinguished from missing data?

A forecast that cannot be scored cleanly is deferred with a machine-readable
reason instead of contaminating the ledger. Scored labels carry a quality
tier (``high`` / ``degraded`` / ``suspect``) plus fixed-vocabulary flags so
downstream consumers (Hypothesis Factory mining, influence weights) can prove
which labels they are allowed to learn from.

Everything here is analysis-only; nothing in this module can touch order
paths, live gates, or sizing.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

UTC = datetime.timezone.utc

LABEL_QUALITY_HIGH = "high"
LABEL_QUALITY_DEGRADED = "degraded"
LABEL_QUALITY_SUSPECT = "suspect"
# Labels the Hypothesis Factory may learn from. ``suspect`` and unaudited
# labels are never minable evidence.
MINABLE_LABEL_QUALITIES = (LABEL_QUALITY_HIGH, LABEL_QUALITY_DEGRADED)

STATUS_RESOLVABLE = "resolvable"
STATUS_DEFERRED = "deferred"
STATUS_NOT_MATURE = "not_mature"

DEFER_MISSING_TICKER_DATA = "missing_ticker_data"
DEFER_MISSING_BENCHMARK_DATA = "missing_benchmark_data"
DEFER_FINAL_BAR_MISSING = "final_bar_missing"
DEFER_TICKER_FINAL_BAR_MISSING = "ticker_final_bar_missing"
DEFER_ENTRY_BAR_MISSING = "entry_bar_missing"
DEFER_WINDOW_MISMATCH = "window_mismatch"
DEFER_INVALID_WINDOW = "invalid_window"

HORIZON_KIND_TRADING_DAYS = "trading_days_weekend_adjusted"
# A missing final-session bar within this many days of the expected session is
# treated as "not printed yet" (defer and retry tomorrow). Only after the
# grace period does a bar missing on BOTH legs become an assumed market
# holiday; a bar missing on one leg only is always stale data, never a
# holiday.
FINAL_BAR_GRACE_DAYS = 2

DEFAULT_RESOLUTION_QUALITY_PATH = Path("results/agent_intelligence/resolution_quality.json")


@dataclass(frozen=True)
class PriceWindow:
    """Dated close prices actually available for one symbol over a window."""

    symbol: str
    requested_start: str
    requested_end: str
    entry_date: str
    entry_close: str
    exit_date: str
    exit_close: str
    session_count: int
    # Optional immutable provenance carried by point-in-time adapters.  The
    # quality audit intentionally remains able to inspect legacy windows, but
    # only callers that receive this provenance may create source-bound
    # learning evidence.
    source_evidence: Mapping[str, str] | None = None


@dataclass(frozen=True)
class ResolutionWindow:
    """The audited, matched measurement window behind a resolved label."""

    intended_start: str
    intended_end: str
    expected_entry_session: str
    expected_exit_session: str
    expected_session_count: int
    ticker_entry_date: str
    ticker_exit_date: str
    benchmark_entry_date: str
    benchmark_exit_date: str
    ticker_session_count: int
    benchmark_session_count: int
    final_bar_available: bool
    horizon: str
    horizon_kind: str = HORIZON_KIND_TRADING_DAYS

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolutionQualityReport:
    """Machine-readable audit verdict for one forecast's resolution attempt."""

    forecast_id: str
    ticker: str
    benchmark: str
    status: str
    label_quality: str | None
    quality_flags: tuple[str, ...]
    defer_reason: str | None
    window: ResolutionWindow | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quality_flags"] = list(self.quality_flags)
        return payload


WindowLookup = Callable[[str, str, str], "PriceWindow | None"]


def _as_date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value).strip()[:10])


def _now_utc(value: datetime.datetime | str | None = None) -> datetime.datetime:
    if value is None:
        return datetime.datetime.now(tz=UTC)
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    clean = str(value).strip()
    if clean.endswith("Z"):
        clean = f"{clean[:-1]}+00:00"
    parsed = datetime.datetime.fromisoformat(clean)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def expected_entry_session(start: datetime.date) -> datetime.date:
    """First weekday on or after the intended window start."""

    current = start
    while current.weekday() >= 5:
        current += datetime.timedelta(days=1)
    return current


def expected_exit_session(end: datetime.date) -> datetime.date:
    """Last weekday on or before the intended window end."""

    current = end
    while current.weekday() >= 5:
        current -= datetime.timedelta(days=1)
    return current


def _weekday_count(start: datetime.date, end: datetime.date) -> int:
    if start > end:
        return 0
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += datetime.timedelta(days=1)
    return count


def _finite_close(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    if not parsed.is_finite():
        return None
    return parsed


def price_window_from_bars(
    *,
    symbol: str,
    requested_start: str | datetime.date,
    requested_end: str | datetime.date,
    bars: Sequence[tuple[Any, Any]],
) -> PriceWindow | None:
    """Build a :class:`PriceWindow` from dated closes, clipped to the window.

    Bars with non-finite closes (NaN/inf data glitches) are dropped. Returns
    ``None`` when fewer than two usable in-window bars exist, because a
    return cannot be measured from a single bar.
    """

    start = _as_date(requested_start)
    end = _as_date(requested_end)
    in_range = sorted(
        (bar_date, str(close))
        for bar_date, close in (
            (_as_date(raw_date), _finite_close(raw_close)) for raw_date, raw_close in bars
        )
        if close is not None and start <= bar_date <= end
    )
    if len(in_range) < 2:
        return None
    return PriceWindow(
        symbol=symbol,
        requested_start=start.isoformat(),
        requested_end=end.isoformat(),
        entry_date=in_range[0][0].isoformat(),
        entry_close=str(in_range[0][1]),
        exit_date=in_range[-1][0].isoformat(),
        exit_close=str(in_range[-1][1]),
        session_count=len(in_range),
    )


def audit_resolution_window(
    *,
    forecast_id: str,
    ticker: str,
    benchmark: str,
    intended_start: str | datetime.date,
    intended_end: str | datetime.date,
    horizon: str,
    ticker_window: PriceWindow | None,
    benchmark_window: PriceWindow | None,
    now: datetime.datetime | str | None = None,
    mature: bool = True,
) -> ResolutionQualityReport:
    """Mechanically audit one forecast's resolution window.

    The benchmark leg acts as the trading-calendar oracle: a session the
    benchmark traded is a session the ticker must also have, and a weekday
    missing from BOTH legs (after the grace period) is an assumed market
    holiday rather than missing data.
    """

    start = _as_date(intended_start)
    end = _as_date(intended_end)
    current = _now_utc(now)

    def _report(
        *,
        status: str,
        label_quality: str | None = None,
        quality_flags: tuple[str, ...] = (),
        defer_reason: str | None = None,
        window: ResolutionWindow | None = None,
        note: str,
    ) -> ResolutionQualityReport:
        return ResolutionQualityReport(
            forecast_id=forecast_id,
            ticker=ticker,
            benchmark=benchmark,
            status=status,
            label_quality=label_quality,
            quality_flags=quality_flags,
            defer_reason=defer_reason,
            window=window,
            note=note,
        )

    def _deferred(reason: str, note: str, flags: tuple[str, ...] = ()) -> ResolutionQualityReport:
        return _report(
            status=STATUS_DEFERRED,
            quality_flags=flags,
            defer_reason=reason,
            note=note,
        )

    if not mature:
        return _report(
            status=STATUS_NOT_MATURE,
            note="forecast has not reached its resolution window yet",
        )
    entry_expected = expected_entry_session(start)
    exit_expected = expected_exit_session(end)
    if exit_expected < entry_expected:
        return _deferred(DEFER_INVALID_WINDOW, "window contains no expected trading session")
    if benchmark_window is None:
        return _deferred(
            DEFER_MISSING_BENCHMARK_DATA,
            f"no usable {benchmark} price window for the resolution period",
        )
    if ticker_window is None:
        return _deferred(
            DEFER_MISSING_TICKER_DATA,
            f"no usable {ticker} price window for the resolution period",
        )
    benchmark_entry = _as_date(benchmark_window.entry_date)
    benchmark_exit = _as_date(benchmark_window.exit_date)
    ticker_entry = _as_date(ticker_window.entry_date)
    ticker_exit = _as_date(ticker_window.exit_date)
    if (
        benchmark_entry < entry_expected
        or benchmark_exit > exit_expected
        or ticker_entry < entry_expected
        or ticker_exit > exit_expected
    ):
        return _deferred(
            DEFER_INVALID_WINDOW,
            "price window extends beyond the expected trading sessions",
        )

    flags: list[str] = []
    final_bar_available = True
    final_gap = _weekday_count(benchmark_exit + datetime.timedelta(days=1), exit_expected)
    if final_gap == 1 and ticker_exit == benchmark_exit:
        if (current.date() - exit_expected).days <= FINAL_BAR_GRACE_DAYS:
            return _deferred(
                DEFER_FINAL_BAR_MISSING,
                "final expected session bar is not available yet",
            )
        flags.append("assumed_market_holiday_at_window_end")
    elif final_gap >= 1:
        return _deferred(
            DEFER_FINAL_BAR_MISSING,
            "benchmark window is missing the final expected session bar",
        )
    if ticker_exit < benchmark_exit:
        return _deferred(
            DEFER_TICKER_FINAL_BAR_MISSING,
            "ticker data stops before the benchmark's final session",
        )
    if ticker_exit > benchmark_exit:
        return _deferred(
            DEFER_WINDOW_MISMATCH,
            "ticker has a bar after the benchmark's final session",
            flags=("ticker_exit_after_benchmark_exit",),
        )
    if ticker_entry != benchmark_entry:
        return _deferred(
            DEFER_WINDOW_MISMATCH,
            "ticker and benchmark entry sessions differ",
            flags=("entry_session_mismatch",),
        )
    entry_gap = _weekday_count(entry_expected, benchmark_entry - datetime.timedelta(days=1))
    if entry_gap == 1:
        flags.append("assumed_market_holiday_at_window_start")
    elif entry_gap >= 2:
        return _deferred(
            DEFER_ENTRY_BAR_MISSING,
            "no bar near the expected entry session",
        )
    expected_session_count = _weekday_count(entry_expected, exit_expected)
    allowed_session_count = (
        expected_session_count
        - ("assumed_market_holiday_at_window_end" in flags)
        - ("assumed_market_holiday_at_window_start" in flags)
    )
    if benchmark_window.session_count < allowed_session_count:
        flags.append("missing_weekday_sessions_inside_window")
    if ticker_window.session_count != benchmark_window.session_count:
        flags.append("ticker_benchmark_session_count_mismatch")
    window = ResolutionWindow(
        intended_start=start.isoformat(),
        intended_end=end.isoformat(),
        expected_entry_session=entry_expected.isoformat(),
        expected_exit_session=exit_expected.isoformat(),
        expected_session_count=expected_session_count,
        ticker_entry_date=ticker_entry.isoformat(),
        ticker_exit_date=ticker_exit.isoformat(),
        benchmark_entry_date=benchmark_entry.isoformat(),
        benchmark_exit_date=benchmark_exit.isoformat(),
        ticker_session_count=ticker_window.session_count,
        benchmark_session_count=benchmark_window.session_count,
        final_bar_available=final_bar_available,
        horizon=horizon,
    )
    return _report(
        status=STATUS_RESOLVABLE,
        label_quality=LABEL_QUALITY_HIGH if not flags else LABEL_QUALITY_DEGRADED,
        quality_flags=tuple(flags),
        window=window,
        note=(
            "resolution window verified against matched ticker/benchmark sessions"
            if not flags
            else "resolution window verified with quality flags"
        ),
    )


def summarize_resolution_quality(
    reports: Sequence[ResolutionQualityReport],
    *,
    unaudited_resolved_count: int = 0,
) -> dict[str, Any]:
    """Aggregate audit reports into a machine-readable quality summary.

    The summary deliberately separates "not mature" from "mature but missing
    data" from "resolved with a quality tier" so resolution stalls and data
    gaps are visible instead of blended.
    """

    status_counts: dict[str, int] = {}
    label_quality_counts: dict[str, int] = {}
    defer_reason_counts: dict[str, int] = {}
    quality_flag_counts: dict[str, int] = {}
    for report in reports:
        status_counts[report.status] = status_counts.get(report.status, 0) + 1
        if report.label_quality:
            label_quality_counts[report.label_quality] = (
                label_quality_counts.get(report.label_quality, 0) + 1
            )
        if report.defer_reason:
            # Counted for deferred resolutions and for retro-audited labels
            # whose windows could not be verified (reason kept on the report).
            defer_reason_counts[report.defer_reason] = (
                defer_reason_counts.get(report.defer_reason, 0) + 1
            )
        for flag in report.quality_flags:
            quality_flag_counts[flag] = quality_flag_counts.get(flag, 0) + 1
    trusted_label_count = sum(
        label_quality_counts.get(quality, 0) for quality in MINABLE_LABEL_QUALITIES
    )
    return {
        "kind": "resolution_quality_summary",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "report_count": len(reports),
        "status_counts": status_counts,
        "label_quality_counts": label_quality_counts,
        "defer_reason_counts": defer_reason_counts,
        "quality_flag_counts": quality_flag_counts,
        "not_mature_count": status_counts.get(STATUS_NOT_MATURE, 0),
        "deferred_count": status_counts.get(STATUS_DEFERRED, 0),
        "resolvable_count": status_counts.get(STATUS_RESOLVABLE, 0),
        "trusted_label_count": trusted_label_count,
        "unaudited_resolved_count": unaudited_resolved_count,
    }
