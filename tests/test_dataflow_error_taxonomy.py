from __future__ import annotations

import json

import pandas as pd
import pytest
import requests

from tradingagents.dataflows import _official_common as official_common
from tradingagents.dataflows import (
    alpha_vantage_common,
    alpha_vantage_fundamentals,
    decision_vendor_adapters,
    interface,
    stockstats_utils,
)
from tradingagents.dataflows._official_common import (
    DataTransportError,
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
    VendorNotConfiguredError,
)


def test_recoverable_dataflow_error_hierarchy_is_action_based():
    recoverable = getattr(official_common, "RecoverableDataflowError", None)
    unavailable = getattr(official_common, "DataUnavailableError", None)
    not_configured = getattr(official_common, "VendorNotConfiguredError", None)
    transport = getattr(official_common, "DataTransportError", None)

    assert recoverable is not None
    assert unavailable is not None
    assert not_configured is not None
    assert transport is not None
    assert issubclass(recoverable, official_common.OfficialDataError)
    assert issubclass(unavailable, recoverable)
    assert issubclass(not_configured, unavailable)
    assert issubclass(not_configured, ValueError)
    assert issubclass(transport, recoverable)


def test_required_environment_value_is_typed_not_configured(monkeypatch):
    monkeypatch.delenv("TASK_7A_MISSING_KEY", raising=False)

    with pytest.raises(VendorNotConfiguredError, match="TASK_7A_MISSING_KEY is missing"):
        official_common.env_value("TASK_7A_MISSING_KEY", required=True)


def test_alpha_vantage_uses_shared_not_configured_and_transport_types(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    assert issubclass(alpha_vantage_common.AlphaVantageRateLimitError, DataTransportError)
    with pytest.raises(
        VendorNotConfiguredError,
        match="ALPHA_VANTAGE_API_KEY environment variable is not set",
    ):
        alpha_vantage_common.get_api_key()


class _TransportSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, _url, **_kwargs):
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    def post(self, _url, **_kwargs):
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class _NonJsonResponse:
    status_code = 200
    headers = {}
    text = "not-json api_key=secret-value"
    content = text.encode()

    def raise_for_status(self):
        return None

    def json(self):
        raise ValueError("not JSON")


def _use_temporary_health_file(monkeypatch, tmp_path):
    official_common.reset_connector_health()
    monkeypatch.setattr(
        official_common,
        "CONNECTOR_HEALTH_PATH",
        tmp_path / "connector-health.json",
    )


@pytest.mark.parametrize(
    "fetch",
    [
        lambda session: official_common.get_json(
            "https://api.example.test/data",
            session=session,
            connector_name="typed_json",
            max_attempts=1,
            sleep_func=lambda _delay: None,
        ),
        lambda session: official_common.get_text(
            "https://api.example.test/data",
            session=session,
            connector_name="typed_text",
            max_attempts=1,
            sleep_func=lambda _delay: None,
        ),
    ],
)
def test_exhausted_transport_failure_is_typed_sanitized_and_recorded(
    fetch,
    monkeypatch,
    tmp_path,
):
    _use_temporary_health_file(monkeypatch, tmp_path)
    session = _TransportSession(
        requests.Timeout("https://api.example.test/?api_key=secret-value")
    )

    with pytest.raises(DataTransportError) as exc_info:
        fetch(session)

    assert session.calls == 1
    assert "secret-value" not in str(exc_info.value)
    health = official_common.connector_health_snapshot()
    assert health[0]["errors"] == 1
    assert "secret-value" not in str(health[0]["last_error"])


def test_open_connector_circuit_is_a_transport_failure(monkeypatch, tmp_path):
    _use_temporary_health_file(monkeypatch, tmp_path)
    session = _TransportSession(requests.Timeout("timed out"))

    with pytest.raises(DataTransportError):
        official_common.get_json(
            "https://api.example.test/data",
            session=session,
            connector_name="typed_circuit",
            max_attempts=1,
            circuit_failure_threshold=1,
            circuit_cooldown_seconds=60,
            sleep_func=lambda _delay: None,
        )
    with pytest.raises(DataTransportError, match="circuit is open"):
        official_common.get_json(
            "https://api.example.test/data",
            session=session,
            connector_name="typed_circuit",
            max_attempts=1,
            circuit_failure_threshold=1,
            circuit_cooldown_seconds=60,
            sleep_func=lambda _delay: None,
        )

    assert session.calls == 1
    assert official_common.connector_health_snapshot()[0]["circuit_state"] == "open"


def test_received_non_json_content_is_a_transport_failure(monkeypatch, tmp_path):
    _use_temporary_health_file(monkeypatch, tmp_path)

    with pytest.raises(DataTransportError, match="non-JSON"):
        official_common.get_json(
            "https://api.example.test/data",
            session=_TransportSession(_NonJsonResponse()),
            connector_name="typed_non_json",
            max_attempts=1,
        )


def test_local_request_contract_errors_are_terminal():
    session = _TransportSession({"unexpected": "call"})
    with pytest.raises(OfficialDataError) as method_error:
        official_common._request_json(  # noqa: SLF001 - contract boundary under test.
            "DELETE",
            "https://api.example.test/data",
            session=session,
        )
    assert not isinstance(method_error.value, RecoverableDataflowError)
    assert "supports GET and POST only" in str(method_error.value)
    assert session.calls == 0

    with pytest.raises(OfficialDataError) as text_method_error:
        official_common._request_text_response(  # noqa: SLF001
            "POST",
            "https://text.example.test/data",
            session=session,
        )
    assert not isinstance(text_method_error.value, RecoverableDataflowError)
    assert session.calls == 0

    with pytest.raises(OfficialDataError) as path_error:
        official_common.validate_official_path(
            "../admin",
            allowed_prefixes=("v1/public",),
        )
    assert not isinstance(path_error.value, RecoverableDataflowError)

    with pytest.raises(OfficialDataError) as allowlist_error:
        official_common.validate_official_path(
            "v1/private",
            allowed_prefixes=("v1/public",),
        )
    assert not isinstance(allowlist_error.value, RecoverableDataflowError)


@pytest.mark.parametrize(
    "error",
    [
        DataUnavailableError("no dated evidence"),
        VendorNotConfiguredError("optional key missing"),
        DataTransportError("transport retries exhausted"),
    ],
)
def test_typed_recoverable_failure_uses_next_first_success_provider(
    error,
    monkeypatch,
):
    calls = []

    def primary(*_args, **_kwargs):
        calls.append("primary")
        raise error

    def fallback(*_args, **_kwargs):
        calls.append("fallback")
        return "fallback evidence"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"primary": primary, "fallback": fallback},
    )
    monkeypatch.setattr(interface, "get_vendor", lambda *_args: "primary,fallback")

    assert interface.route_to_vendor("get_stock_data", "NFLX") == "fallback evidence"
    assert calls == ["primary", "fallback"]


def test_merge_route_continues_after_typed_failure_without_changing_policy(
    monkeypatch,
):
    calls = []

    def unavailable(*_args, **_kwargs):
        calls.append("unavailable")
        raise DataUnavailableError("no relevant news")

    def first(*_args, **_kwargs):
        calls.append("first")
        return "Shared headline\nFirst-only headline"

    def transport(*_args, **_kwargs):
        calls.append("transport")
        raise DataTransportError("upstream retries exhausted")

    def second(*_args, **_kwargs):
        calls.append("second")
        return "Shared headline\nSecond-only headline"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {
            "unavailable": unavailable,
            "first": first,
            "transport": transport,
            "second": second,
        },
    )
    monkeypatch.setattr(
        interface,
        "get_vendor",
        lambda *_args: "unavailable,first,transport,second",
    )

    result = interface.route_to_vendor("get_news", "NFLX", "2026-07-01", "2026-07-19")

    assert interface.MERGEABLE_METHODS["get_news"] == {
        "max_sources": 4,
        "max_chars": 12_000,
    }
    assert "Execution authority: none (research evidence only)" in result
    assert result.count("Shared headline") == 1
    assert "First-only headline" in result
    assert "Second-only headline" in result
    assert calls == ["unavailable", "first", "transport", "second"]


@pytest.mark.parametrize(
    "error",
    [
        OfficialDataError("malformed evidence"),
        requests.Timeout("raw requests timeout"),
        TimeoutError("raw timeout"),
        ConnectionError("raw connection error"),
        ValueError("invalid request"),
        TypeError("programming contract failure"),
        AssertionError("invariant failure"),
    ],
)
def test_terminal_failures_propagate_unchanged_without_fallback(error, monkeypatch):
    calls = []

    def primary(*_args, **_kwargs):
        calls.append("primary")
        raise error

    def fallback(*_args, **_kwargs):
        calls.append("fallback")
        return "must not run"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"primary": primary, "fallback": fallback},
    )
    monkeypatch.setattr(interface, "get_vendor", lambda *_args: "primary,fallback")

    with pytest.raises(type(error)) as exc_info:
        interface.route_to_vendor("get_stock_data", "NFLX")

    assert exc_info.value is error
    assert calls == ["primary"]


def test_all_typed_recoverable_failures_keep_bounded_runtime_summary(monkeypatch):
    long_message = "no evidence " + ("x" * 500)

    def unavailable(*_args, **_kwargs):
        raise DataUnavailableError(long_message)

    def transport(*_args, **_kwargs):
        raise DataTransportError(long_message)

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"unavailable": unavailable, "transport": transport},
    )
    monkeypatch.setattr(interface, "get_vendor", lambda *_args: "unavailable,transport")

    with pytest.raises(RuntimeError, match="No available vendor") as exc_info:
        interface.route_to_vendor("get_stock_data", "NFLX")

    message = str(exc_info.value)
    assert "unavailable: DataUnavailableError" in message
    assert "transport: DataTransportError" in message
    assert message.count("...") == 2
    assert len(message) < 500


def test_stale_yfinance_ohlcv_reaches_next_stock_provider(monkeypatch):
    calls = []

    def stale_yfinance(*_args, **_kwargs):
        calls.append("yfinance")
        return stockstats_utils.validate_daily_ohlcv(
            pd.DataFrame({"Date": ["2026-06-01"], "Close": [100.0]}),
            "yfinance",
            "NFLX",
            "2026-07-19",
        )

    def fallback(*_args, **_kwargs):
        calls.append("tiingo")
        return "fresh Tiingo OHLCV"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"yfinance": stale_yfinance, "tiingo": fallback},
    )
    monkeypatch.setattr(interface, "get_vendor", lambda *_args: "yfinance,tiingo")

    assert interface.route_to_vendor("get_stock_data", "NFLX") == "fresh Tiingo OHLCV"
    assert calls == ["yfinance", "tiingo"]


def test_unavailable_historical_alpha_reports_reach_next_provider(monkeypatch):
    calls = []
    payload = json.dumps(
        {
            "annualReports": [
                {
                    "fiscalDateEnding": "2023-12-31",
                    "filingDate": "2024-02-16",
                }
            ],
            "quarterlyReports": [],
        }
    )

    def alpha_vantage(*_args, **_kwargs):
        calls.append("alpha_vantage")
        return alpha_vantage_fundamentals._filter_reports_by_date(  # noqa: SLF001
            payload,
            "2024-02-15",
        )

    def yfinance(*_args, **_kwargs):
        calls.append("yfinance")
        return "point-in-time yfinance evidence"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_balance_sheet",
        {"alpha_vantage": alpha_vantage, "yfinance": yfinance},
    )
    monkeypatch.setattr(
        interface,
        "get_vendor",
        lambda *_args: "alpha_vantage,yfinance",
    )

    assert (
        interface.route_to_vendor("get_balance_sheet", "NFLX")
        == "point-in-time yfinance evidence"
    )
    assert calls == ["alpha_vantage", "yfinance"]


def test_malformed_alpha_evidence_is_terminal_without_fallback(monkeypatch):
    calls = []

    def alpha_vantage(*_args, **_kwargs):
        calls.append("alpha_vantage")
        return alpha_vantage_fundamentals._filter_reports_by_date(  # noqa: SLF001
            "{malformed",
            "2024-02-15",
        )

    def yfinance(*_args, **_kwargs):
        calls.append("yfinance")
        return "must not run"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_balance_sheet",
        {"alpha_vantage": alpha_vantage, "yfinance": yfinance},
    )
    monkeypatch.setattr(
        interface,
        "get_vendor",
        lambda *_args: "alpha_vantage,yfinance",
    )

    with pytest.raises(OfficialDataError, match="malformed JSON") as exc_info:
        interface.route_to_vendor("get_balance_sheet", "NFLX")

    assert not isinstance(exc_info.value, RecoverableDataflowError)
    assert calls == ["alpha_vantage"]


def test_missing_sec_cik_reaches_next_fundamentals_provider(monkeypatch):
    calls = []

    class Packet:
        payload = {
            "0": {"ticker": "MSFT", "cik_str": 789019},
        }

    monkeypatch.setattr(
        decision_vendor_adapters,
        "fetch_sec_company_tickers",
        lambda: Packet(),
    )

    def sec(*args, **kwargs):
        calls.append("sec")
        return decision_vendor_adapters.get_sec_fundamentals(*args, **kwargs)

    def yfinance(*_args, **_kwargs):
        calls.append("yfinance")
        return "yfinance fundamentals"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_fundamentals",
        {"sec": sec, "yfinance": yfinance},
    )
    monkeypatch.setattr(interface, "get_vendor", lambda *_args: "sec,yfinance")

    assert (
        interface.route_to_vendor("get_fundamentals", "NFLX")
        == "yfinance fundamentals"
    )
    assert calls == ["sec", "yfinance"]


def test_invalid_sec_ticker_and_malformed_payload_are_terminal(monkeypatch):
    calls = []
    payload = []

    def fetch():
        calls.append("fetch")
        return type("Packet", (), {"payload": payload})()

    monkeypatch.setattr(
        decision_vendor_adapters,
        "fetch_sec_company_tickers",
        fetch,
    )

    with pytest.raises(ValueError, match="ticker"):
        decision_vendor_adapters._sec_cik_for_symbol("")  # noqa: SLF001
    assert calls == []

    with pytest.raises(OfficialDataError, match="payload") as exc_info:
        decision_vendor_adapters._sec_cik_for_symbol("NFLX")  # noqa: SLF001
    assert not isinstance(exc_info.value, RecoverableDataflowError)
    assert calls == ["fetch"]

    payload = {"0": "malformed entry"}
    with pytest.raises(OfficialDataError, match="payload") as entry_exc_info:
        decision_vendor_adapters._sec_cik_for_symbol("NFLX")  # noqa: SLF001
    assert not isinstance(entry_exc_info.value, RecoverableDataflowError)
    assert calls == ["fetch", "fetch"]
