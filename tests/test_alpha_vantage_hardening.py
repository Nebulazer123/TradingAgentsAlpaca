from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.dataflows import alpha_vantage_fundamentals as fundamentals
from tradingagents.dataflows._official_common import (
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
)


def _statement_payload(*rows: dict[str, str]) -> str:
    return json.dumps(
        {
            "symbol": "NFLX",
            "annualReports": list(rows),
            "metadata": {"source": "alpha-vantage"},
            "quarterlyReports": [
                {
                    "fiscalDateEnding": "2023-09-30",
                    "filingDate": "2023-10-20",
                    "marker": "quarterly-first",
                }
            ],
        }
    )


def test_json_string_reports_are_filtered_by_fiscal_and_availability_cutoff():
    payload = _statement_payload(
        {
            "fiscalDateEnding": "2023-12-31",
            "filingDate": "2024-02-15",
            "marker": "available-on-cutoff",
        },
        {
            "fiscalDateEnding": "2024-03-31",
            "filingDate": "2024-04-20",
            "marker": "future-fiscal-period",
        },
        {
            "fiscalDateEnding": "2023-12-31",
            "filingDate": "2024-02-16",
            "marker": "filed-after-cutoff",
        },
    )

    filtered = fundamentals._filter_reports_by_date(payload, "2024-02-15")

    assert isinstance(filtered, str)
    decoded = json.loads(filtered)
    assert list(decoded) == [
        "symbol",
        "annualReports",
        "metadata",
        "quarterlyReports",
    ]
    assert [row["marker"] for row in decoded["annualReports"]] == [
        "available-on-cutoff"
    ]
    assert decoded["quarterlyReports"][0]["marker"] == "quarterly-first"
    assert decoded["metadata"] == {"source": "alpha-vantage"}


@pytest.mark.parametrize(
    "availability_field",
    [
        "filingDate",
        "reportedDate",
        "publishedDate",
        "accepted",
        "acceptanceDateTime",
    ],
)
def test_each_recognized_availability_field_is_inclusive_on_cutoff(
    availability_field,
):
    payload = _statement_payload(
        {
            "fiscalDateEnding": "2023-12-31",
            availability_field: "2024-02-15",
            "marker": "on-cutoff",
        },
        {
            "fiscalDateEnding": "2023-12-31",
            availability_field: "2024-02-16",
            "marker": "after-cutoff",
        },
    )

    decoded = json.loads(
        fundamentals._filter_reports_by_date(payload, "2024-02-15")
    )

    assert [row["marker"] for row in decoded["annualReports"]] == ["on-cutoff"]


@pytest.mark.parametrize(
    "bad_row",
    [
        {"filingDate": "2024-02-01"},
        {"fiscalDateEnding": "2023/12/31", "filingDate": "2024-02-01"},
        {"fiscalDateEnding": "2023-12-31", "filingDate": "2024-02-01T00:00:00Z"},
        {"fiscalDateEnding": "2023-12-31", "filingDate": 20240201},
        {
            "fiscalDateEnding": "2023-12-31",
            "filingDate": "2024-02-01",
            "reportedDate": "not-a-date",
        },
        {
            "fiscalDateEnding": "2023-12-31",
            "filingDate": "2024-02-01",
            "reportedDate": "2024-02-16",
        },
        {"fiscalDateEnding": "2023-12-31"},
    ],
)
def test_historical_rows_fail_closed_without_valid_fiscal_and_availability_evidence(
    bad_row,
):
    payload = _statement_payload(
        {
            **bad_row,
            "marker": "invalid",
        }
    )

    decoded = json.loads(
        fundamentals._filter_reports_by_date(payload, "2024-02-15")
    )

    assert decoded["annualReports"] == []
    assert decoded["quarterlyReports"]


@pytest.mark.parametrize(
    "bad_cutoff",
    [
        "2024-02-01T00:00:00",
        "2024-02-01Z",
        "2024-2-01",
        "2024-02-30",
        " 2024-02-01",
        "",
        20240201,
    ],
)
def test_invalid_explicit_cutoff_fails_before_vendor_request(monkeypatch, bad_cutoff):
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return "{}"

    monkeypatch.setattr(fundamentals, "_make_api_request", request)

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        fundamentals.get_balance_sheet("NFLX", curr_date=bad_cutoff)

    assert calls == []


def test_current_cutoff_allows_missing_availability_because_fetch_proves_it(monkeypatch):
    future_date = (
        datetime.now(timezone.utc).date() + timedelta(days=1)
    ).isoformat()
    payload = _statement_payload(
        {
            "fiscalDateEnding": "2020-12-31",
            "marker": "fetched-now",
        }
    )
    monkeypatch.setattr(
        fundamentals,
        "_make_api_request",
        lambda *_args, **_kwargs: payload,
    )

    decoded = json.loads(
        fundamentals.get_balance_sheet("NFLX", curr_date=future_date)
    )

    assert decoded["annualReports"][0]["marker"] == "fetched-now"


def test_none_cutoff_preserves_unparsed_live_response(monkeypatch):
    original = "[not a dictionary, but valid live passthrough]"
    monkeypatch.setattr(
        fundamentals,
        "_make_api_request",
        lambda *_args, **_kwargs: original,
    )

    assert fundamentals.get_cashflow("NFLX", curr_date=None) is original
    assert fundamentals._filter_reports_by_date(original, None) is original


@pytest.mark.parametrize("body", ["{not-json", "[]", '"scalar"', "null"])
def test_filtered_evidence_rejects_malformed_or_non_dictionary_json(body):
    with pytest.raises(OfficialDataError, match="Alpha Vantage") as exc_info:
        fundamentals._filter_reports_by_date(body, "2024-02-15")

    assert not isinstance(exc_info.value, RecoverableDataflowError)


def test_historical_statement_with_no_usable_reports_is_unavailable(
    monkeypatch,
):
    payload = json.dumps(
        {
            "symbol": "NFLX",
            "annualReports": [
                {
                    "fiscalDateEnding": "2023-12-31",
                    "filingDate": "2024-02-16",
                }
            ],
            "quarterlyReports": [],
        }
    )
    monkeypatch.setattr(
        fundamentals,
        "_make_api_request",
        lambda *_args, **_kwargs: payload,
    )

    with pytest.raises(DataUnavailableError, match="no usable historical"):
        fundamentals.get_income_statement("NFLX", curr_date="2024-02-15")


def test_historical_overview_rejects_current_snapshot_without_request(monkeypatch):
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return '{"Symbol":"NFLX"}'

    monkeypatch.setattr(fundamentals, "_make_api_request", request)

    with pytest.raises(DataUnavailableError, match="historical OVERVIEW"):
        fundamentals.get_fundamentals("NFLX", curr_date="2024-02-15")

    assert calls == []


@pytest.mark.parametrize(
    ("endpoint_name", "vendor_function"),
    [
        ("BALANCE_SHEET", fundamentals.get_balance_sheet),
        ("CASH_FLOW", fundamentals.get_cashflow),
        ("INCOME_STATEMENT", fundamentals.get_income_statement),
    ],
)
def test_all_statement_endpoints_filter_json_and_return_strings(
    monkeypatch,
    endpoint_name,
    vendor_function,
):
    calls = []
    payload = _statement_payload(
        {
            "fiscalDateEnding": "2023-12-31",
            "reportedDate": "2024-02-01",
            "marker": endpoint_name,
        }
    )

    def request(function_name, params):
        calls.append((function_name, params))
        return payload

    monkeypatch.setattr(fundamentals, "_make_api_request", request)

    result = vendor_function("NFLX", curr_date="2024-02-15")

    assert isinstance(result, str)
    assert json.loads(result)["annualReports"][0]["marker"] == endpoint_name
    assert calls == [(endpoint_name, {"symbol": "NFLX"})]


def test_current_or_future_overview_and_none_cutoff_remain_string_passthrough(
    monkeypatch,
):
    responses = iter(['{"Symbol":"NFLX","mode":"current"}', "live text"])
    monkeypatch.setattr(
        fundamentals,
        "_make_api_request",
        lambda *_args, **_kwargs: next(responses),
    )
    future_date = (
        datetime.now(timezone.utc).date() + timedelta(days=1)
    ).isoformat()

    assert fundamentals.get_fundamentals("NFLX", curr_date=future_date) == (
        '{"Symbol":"NFLX","mode":"current"}'
    )
    assert fundamentals.get_fundamentals("NFLX", curr_date=None) == "live text"
