import json
import re
from datetime import date, datetime, timezone

from tradingagents.dataflows._official_common import (
    DataUnavailableError,
    OfficialDataError,
)

from .alpha_vantage_common import _make_api_request

_EXACT_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_AVAILABILITY_FIELDS = (
    "filingDate",
    "reportedDate",
    "publishedDate",
    "accepted",
    "acceptanceDateTime",
)


def _parse_exact_date(value: object, *, field_name: str) -> date:
    if not isinstance(value, str) or _EXACT_DATE_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be an exact YYYY-MM-DD calendar date"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an exact YYYY-MM-DD calendar date"
        ) from exc


def _utc_date() -> date:
    return datetime.now(timezone.utc).date()


def _row_is_available(
    row: object,
    *,
    cutoff: date,
    historical_cutoff: bool,
) -> bool:
    if not isinstance(row, dict):
        return False

    try:
        fiscal_date = _parse_exact_date(
            row.get("fiscalDateEnding"),
            field_name="fiscalDateEnding",
        )
    except ValueError:
        return False
    if fiscal_date > cutoff:
        return False

    supplied_availability = [
        row[field] for field in _AVAILABILITY_FIELDS if field in row
    ]
    if historical_cutoff and not supplied_availability:
        return False

    try:
        availability_dates = [
            _parse_exact_date(value, field_name="availability date")
            for value in supplied_availability
        ]
    except ValueError:
        return False
    return all(
        availability_date <= cutoff for availability_date in availability_dates
    )


def _filter_reports_by_date(
    result: str,
    curr_date: str | None,
    *,
    fetch_date: date | None = None,
) -> str:
    """Return only statement rows knowable by the exact point-in-time cutoff."""
    if curr_date is None:
        return result

    cutoff = _parse_exact_date(curr_date, field_name="curr_date")
    try:
        payload = json.loads(result) if isinstance(result, str) else None
    except json.JSONDecodeError as exc:
        raise OfficialDataError(
            "Alpha Vantage returned malformed JSON statement evidence"
        ) from exc
    if not isinstance(payload, dict):
        raise OfficialDataError(
            "Alpha Vantage statement evidence must be a JSON dictionary"
        )

    historical_cutoff = cutoff < (fetch_date or _utc_date())
    usable_report_count = 0
    for key in ("annualReports", "quarterlyReports"):
        if key not in payload:
            continue
        reports = payload[key]
        if not isinstance(reports, list):
            raise OfficialDataError(
                f"Alpha Vantage {key} evidence must be a JSON list"
            )
        filtered_reports = [
            row
            for row in reports
            if _row_is_available(
                row,
                cutoff=cutoff,
                historical_cutoff=historical_cutoff,
            )
        ]
        payload[key] = filtered_reports
        usable_report_count += len(filtered_reports)

    if historical_cutoff and usable_report_count == 0:
        raise DataUnavailableError(
            "Alpha Vantage returned no usable historical statement reports"
        )
    return json.dumps(payload)


def _get_statement(function_name: str, ticker: str, curr_date: str | None) -> str:
    if curr_date is None:
        return _make_api_request(function_name, {"symbol": ticker})

    _parse_exact_date(curr_date, field_name="curr_date")
    fetch_date_before = _utc_date()
    result = _make_api_request(function_name, {"symbol": ticker})
    fetch_date_after = _utc_date()
    return _filter_reports_by_date(
        result,
        curr_date,
        fetch_date=max(fetch_date_before, fetch_date_after),
    )


def get_fundamentals(ticker: str, curr_date: str = None) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol using Alpha Vantage.

    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd

    Returns:
        str: Company overview data including financial ratios and key metrics
    """
    params = {"symbol": ticker}
    if curr_date is None:
        return _make_api_request("OVERVIEW", params)

    cutoff = _parse_exact_date(curr_date, field_name="curr_date")
    if cutoff < _utc_date():
        raise DataUnavailableError(
            "Alpha Vantage historical OVERVIEW is unavailable because the "
            "endpoint only returns a current snapshot"
        )
    result = _make_api_request("OVERVIEW", params)
    if cutoff < _utc_date():
        raise DataUnavailableError(
            "Alpha Vantage historical OVERVIEW became stale during the request"
        )
    return result


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve balance sheet data for a given ticker symbol using Alpha Vantage."""
    return _get_statement("BALANCE_SHEET", ticker, curr_date)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve cash flow statement data for a given ticker symbol using Alpha Vantage."""
    return _get_statement("CASH_FLOW", ticker, curr_date)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve income statement data for a given ticker symbol using Alpha Vantage."""
    return _get_statement("INCOME_STATEMENT", ticker, curr_date)
