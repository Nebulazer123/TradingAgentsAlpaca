import json

import pytest

from tradingagents.dataflows import (
    _official_common as official_common,
)
from tradingagents.dataflows import (
    alpaca_news,
    alpha_vantage_common,
    bea,
    bls,
    eia,
    eodhd,
    finnhub,
    fmp,
    fred,
    google_news,
    marketaux,
    massive,
    newsapi,
    scrapingbee,
    sec,
    tiingo,
    treasury_fiscal,
)
from tradingagents.dataflows._official_common import (
    DataTransportError,
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
    cached_safe_fetch_evidence,
    connector_health_snapshot,
    env_value,
    evidence_packet,
    get_json,
    official_cache_key,
    reset_connector_health,
    safe_fetch_evidence,
    safe_source_ref,
)
from tradingagents.schemas.research import SourceEvidencePacket


class FakeResponse:
    def __init__(self, payload=None, *, text=None, headers=None, status_code=200):
        self.payload = payload
        self.text = text
        self.content = text.encode("utf-8") if isinstance(text, str) else b""
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload=None, *, text=None, headers=None, status_code=200):
        self.payload = payload or {"ok": True}
        self.text = text
        self.headers = headers or {}
        self.status_code = status_code
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(
            self.payload,
            text=self.text,
            headers=self.headers,
            status_code=self.status_code,
        )

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse(
            self.payload,
            text=self.text,
            headers=self.headers,
            status_code=self.status_code,
        )


class SequentialFakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if not self.payloads:
            raise AssertionError("no fake payload left")
        return FakeResponse(self.payloads.pop(0))


class FailingResponse:
    def raise_for_status(self):
        import requests

        raise requests.HTTPError("500 for url https://api.example.test/?api_key=secret-value")

    def json(self):
        return {"api_key": "secret-value"}


class FailingSession:
    def get(self, url, **kwargs):
        return FailingResponse()

    def post(self, url, **kwargs):
        return FailingResponse()


class SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class HttpResponse(FakeResponse):
    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} for url https://api.example.test/")


def _packet_json(packet):
    return json.dumps(packet.model_dump(), sort_keys=True)


def test_env_value_treats_whitespace_secret_as_missing(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "   ")

    with pytest.raises(OfficialDataError):
        env_value("FRED_API_KEY", required=True)


def test_safe_source_ref_strips_secret_query_from_url_and_params():
    ref = safe_source_ref(
        "https://api.example.test/data?api_key=url-secret&series_id=GDP",
        {"apikey": "param-secret", "observation_start": "2026-01-01"},
    )

    assert ref == "https://api.example.test/data?series_id=GDP&observation_start=2026-01-01"
    assert "secret" not in ref


def test_sec_companyfacts_builds_user_agent_and_analysis_only_packet():
    session = FakeSession({"cik": "789019", "facts": {"us-gaap": {}}})

    packet = sec.fetch_sec_companyfacts(
        "789019",
        symbol="msft",
        user_agent="Tester tester@example.com",
        session=session,
    )

    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url.endswith("/CIK0000789019.json")
    assert kwargs["headers"]["User-Agent"] == "Tester tester@example.com"
    assert packet.analysis_only is True
    assert packet.symbol == "MSFT"
    assert packet.source_refs == [
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"
    ]


def test_sec_company_tickers_builds_user_agent_and_analysis_only_packet():
    session = FakeSession({"0": {"ticker": "MSFT", "cik_str": 789019}})

    packet = sec.fetch_sec_company_tickers(
        user_agent="Tester tester@example.com",
        session=session,
    )

    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://www.sec.gov/files/company_tickers.json"
    assert kwargs["headers"]["User-Agent"] == "Tester tester@example.com"
    assert packet.analysis_only is True
    assert packet.evidence_type == "company_tickers"
    assert packet.source_refs == ["https://www.sec.gov/files/company_tickers.json"]
    assert packet.payload["0"]["ticker"] == "MSFT"


def test_sec_requires_user_agent_when_not_provided(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    with pytest.raises(OfficialDataError):
        sec.fetch_sec_submissions("1", session=FakeSession())


def test_fred_uses_key_for_request_but_never_stores_it():
    session = FakeSession({"observations": [{"date": "2026-01-01", "value": "1.0"}]})

    packet = fred.fetch_fred_series_observations(
        "GDP",
        api_key="fred-secret",
        observation_start="2026-01-01",
        session=session,
    )

    _method, _url, kwargs = session.calls[0]
    assert kwargs["params"]["api_key"] == "fred-secret"
    assert "fred-secret" not in _packet_json(packet)
    assert "api_key" not in packet.source_refs[0].lower()
    assert "series_id=GDP" in packet.source_refs[0]
    assert packet.analysis_only is True


def test_bls_v2_posts_registration_key_without_packet_leakage():
    session = FakeSession({"Results": {"series": []}, "registrationkey": "echo-secret"})

    packet = bls.fetch_bls_timeseries(
        ["LNS14000000"],
        2025,
        2026,
        api_key="bls-secret",
        session=session,
    )

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == bls.BLS_TIMESERIES_URL
    assert kwargs["json"]["registrationkey"] == "bls-secret"
    saved = _packet_json(packet)
    assert "bls-secret" not in saved
    assert "echo-secret" not in saved
    assert packet.payload["registrationkey"] == "[redacted]"


def test_bls_v2_can_run_without_optional_key():
    session = FakeSession({"Results": {"series": []}})

    packet = bls.fetch_bls_timeseries(
        ["LNS14000000"],
        2025,
        2026,
        api_key="",
        session=session,
    )

    _method, _url, kwargs = session.calls[0]
    assert "registrationkey" not in kwargs["json"]
    assert packet.analysis_only is True


def test_bea_uses_userid_without_storing_key():
    session = FakeSession({"BEAAPI": {"Request": {"UserID": "echo-key"}}})

    packet = bea.fetch_bea_data(
        "NIPA",
        TableName="T10101",
        Frequency="Q",
        Year="2026",
        api_key="bea-secret",
        session=session,
    )

    _method, _url, kwargs = session.calls[0]
    assert kwargs["params"]["UserID"] == "bea-secret"
    saved = _packet_json(packet)
    assert "bea-secret" not in saved
    assert "echo-key" not in saved
    assert "UserID" not in packet.source_refs[0]


def test_eia_uses_api_key_without_storing_key():
    session = FakeSession({"response": {"data": []}, "api_key": "echo-key"})

    packet = eia.fetch_eia_route(
        "electricity/retail-sales/data",
        api_key="eia-secret",
        frequency="monthly",
        session=session,
    )

    _method, url, kwargs = session.calls[0]
    assert url == "https://api.eia.gov/v2/electricity/retail-sales/data"
    assert kwargs["params"]["api_key"] == "eia-secret"
    saved = _packet_json(packet)
    assert "eia-secret" not in saved
    assert "echo-key" not in saved
    assert "api_key" not in packet.source_refs[0].lower()


def test_eia_rejects_unallowlisted_or_unsafe_routes():
    with pytest.raises(OfficialDataError):
        eia.fetch_eia_route("../admin", api_key="eia-secret", session=FakeSession())
    with pytest.raises(OfficialDataError):
        eia.fetch_eia_route("unknown-family/data", api_key="eia-secret", session=FakeSession())


def test_treasury_fiscal_needs_no_key_and_writes_source_ref():
    session = FakeSession({"data": [{"record_date": "2026-01-01"}]})

    packet = treasury_fiscal.fetch_treasury_fiscal(
        "v1/accounting/dts/dts_table_1",
        fields="record_date,account_type,open_today_bal",
        session=session,
    )

    _method, url, kwargs = session.calls[0]
    assert url.endswith("/v1/accounting/dts/dts_table_1")
    assert kwargs["params"]["fields"] == "record_date,account_type,open_today_bal"
    assert packet.source_name == "treasury_fiscal"
    assert packet.analysis_only is True
    assert "fields=record_date" in packet.source_refs[0]


def test_treasury_fiscal_rejects_unallowlisted_or_unsafe_paths():
    with pytest.raises(OfficialDataError):
        treasury_fiscal.fetch_treasury_fiscal("../admin", session=FakeSession())
    with pytest.raises(OfficialDataError):
        treasury_fiscal.fetch_treasury_fiscal("v9/unknown/path", session=FakeSession())


@pytest.mark.parametrize("error_type", [DataTransportError, DataUnavailableError])
def test_safe_fetch_turns_recoverable_failure_into_blocked_packet_without_secret_leak(
    error_type,
):
    def broken_fetch():
        raise error_type("failed url https://api.example.test/?api_key=secret-value")

    packet = safe_fetch_evidence(
        broken_fetch,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
    )

    saved = _packet_json(packet)
    assert packet.analysis_only is True
    assert packet.redaction_status == "blocked"
    assert packet.freshness["blocked"] is True
    assert packet.payload["status"] == "blocked"
    assert "secret-value" not in saved


def _source_packet_validation_error():
    try:
        SourceEvidencePacket.model_validate({})
    except Exception as exc:  # noqa: BLE001 - return the concrete Pydantic error.
        return exc
    raise AssertionError("invalid packet unexpectedly validated")


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: OfficialDataError("malformed official evidence"),
        lambda: RuntimeError("unexpected runtime failure"),
        lambda: TypeError("programming contract failure"),
        lambda: AssertionError("invariant failure"),
        _source_packet_validation_error,
    ],
)
def test_safe_fetch_propagates_nonrecoverable_failure_unchanged(error_factory):
    error = error_factory()

    def broken_fetch():
        raise error

    with pytest.raises(type(error)) as exc_info:
        safe_fetch_evidence(
            broken_fetch,
            source_name="fred",
            evidence_type="series_observations",
            subject="GDP",
        )

    assert exc_info.value is error


def test_request_failures_are_sanitized_before_leaving_adapter():
    with pytest.raises(OfficialDataError) as exc_info:
        fred.fetch_fred_series_observations(
            "GDP",
            api_key="fred-secret",
            session=FailingSession(),
        )

    message = str(exc_info.value)
    assert "official source request failed" in message
    assert "fred-secret" not in message
    assert "secret-value" not in message


def test_alpha_vantage_common_uses_shared_text_client(monkeypatch):
    calls = []

    def fake_get_text(url, **kwargs):
        calls.append((url, kwargs))
        return "timestamp,close\n2026-01-01,1\n"

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha-secret")
    monkeypatch.setattr(alpha_vantage_common, "get_text", fake_get_text)

    payload = alpha_vantage_common._make_api_request("TIME_SERIES_DAILY", {"symbol": "MSFT"})

    assert payload.startswith("timestamp,close")
    assert calls[0][0] == alpha_vantage_common.API_BASE_URL
    assert calls[0][1]["params"]["apikey"] == "alpha-secret"
    assert calls[0][1]["connector_name"] == "alpha_vantage"


def test_alpha_vantage_common_filters_csv_by_date_range():
    csv_data = "timestamp,close\n2026-06-01,10\n2026-06-02,11\n2026-06-03,12\n"

    filtered = alpha_vantage_common._filter_csv_by_date_range(
        csv_data,
        "2026-06-02",
        "2026-06-03",
    )

    assert "2026-06-01" not in filtered
    assert "2026-06-02" in filtered
    assert "2026-06-03" in filtered


def test_alpha_vantage_common_date_filter_failure_does_not_return_unfiltered_csv():
    csv_data = "timestamp,close\nnot-a-date,10\n2026-06-01,11\n"

    filtered = alpha_vantage_common._filter_csv_by_date_range(
        csv_data,
        "2026-06-02",
        "2026-06-03",
    )

    assert filtered.startswith("Error filtering Alpha Vantage CSV data by date range:")
    assert "2026-06-01,11" not in filtered
    assert "not-a-date,10" not in filtered


def test_get_json_retries_transient_errors_and_records_connector_health(tmp_path, monkeypatch):
    reset_connector_health()
    monkeypatch.setattr(official_common, "CONNECTOR_HEALTH_PATH", tmp_path / "connector-health.json")
    sleeps = []
    session = SequenceSession(
        [
            HttpResponse({"rate": "limited"}, headers={"Retry-After": "2"}, status_code=429),
            HttpResponse({"temporary": "down"}, status_code=503),
            HttpResponse({"ok": True}, status_code=200),
        ]
    )

    payload = get_json(
        "https://api.example.test/data",
        session=session,
        connector_name="example_connector",
        max_attempts=3,
        backoff_base_seconds=0.1,
        backoff_jitter_seconds=0.0,
        sleep_func=sleeps.append,
    )
    rows = connector_health_snapshot()
    row = next(item for item in rows if item["connector"] == "example_connector")

    assert payload == {"ok": True}
    assert len(session.calls) == 3
    assert sleeps == [2.0, 0.2]
    assert row["successes"] == 1
    assert row["errors"] == 2
    assert row["rate_limit_count"] == 1
    assert row["circuit_state"] == "closed"


def test_get_json_opens_circuit_after_repeated_connector_failure(tmp_path, monkeypatch):
    import requests

    reset_connector_health()
    monkeypatch.setattr(official_common, "CONNECTOR_HEALTH_PATH", tmp_path / "connector-health.json")
    session = SequenceSession([requests.Timeout("timed out")])

    with pytest.raises(OfficialDataError):
        get_json(
            "https://api.example.test/data",
            session=session,
            connector_name="circuit_connector",
            max_attempts=1,
            circuit_failure_threshold=1,
            circuit_cooldown_seconds=60,
            sleep_func=lambda _delay: None,
        )
    with pytest.raises(OfficialDataError) as exc_info:
        get_json(
            "https://api.example.test/data",
            session=session,
            connector_name="circuit_connector",
            max_attempts=1,
            circuit_failure_threshold=1,
            circuit_cooldown_seconds=60,
            sleep_func=lambda _delay: None,
        )

    row = next(item for item in connector_health_snapshot() if item["connector"] == "circuit_connector")
    assert len(session.calls) == 1
    assert "circuit is open" in str(exc_info.value)
    assert row["circuit_state"] == "open"


def test_cached_safe_fetch_uses_fresh_official_cache(tmp_path):
    cache_key = official_cache_key("fred", "GDP")
    called = {"count": 0}
    should_fail = {"value": False}

    def fetcher():
        called["count"] += 1
        if should_fail["value"]:
            raise AssertionError("fresh cache must bypass the fetcher")
        return evidence_packet(
            source_name="fred",
            evidence_type="series_observations",
            subject="GDP",
            source_ref="https://api.stlouisfed.org/fred/series/observations?series_id=GDP",
            payload={"observations": []},
            request_fingerprint=cache_key,
        )

    first = cached_safe_fetch_evidence(
        fetcher,
        cache_key=cache_key,
        ttl_seconds=3600,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
    )
    should_fail["value"] = True
    second = cached_safe_fetch_evidence(
        fetcher,
        cache_key=cache_key,
        ttl_seconds=3600,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
    )

    assert called["count"] == 1
    assert first.freshness["cache"]["state"] == "refreshed"
    assert second.freshness["cache"]["state"] == "hit"
    assert second.payload == {"observations": []}


@pytest.mark.parametrize("error_type", [DataTransportError, DataUnavailableError])
def test_cached_safe_fetch_returns_stale_cache_on_recoverable_refresh_failure(
    tmp_path,
    error_type,
):
    cache_key = official_cache_key("fred", "GDP")

    def good_fetch():
        return evidence_packet(
            source_name="fred",
            evidence_type="series_observations",
            subject="GDP",
            source_ref="https://api.stlouisfed.org/fred/series/observations?series_id=GDP",
            payload={"observations": [{"date": "2026-01-01"}]},
            request_fingerprint=cache_key,
        )

    cached_safe_fetch_evidence(
        good_fetch,
        cache_key=cache_key,
        ttl_seconds=0,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
    )

    def broken_fetch():
        raise error_type("api_key=secret-value failed")

    stale = cached_safe_fetch_evidence(
        broken_fetch,
        cache_key=cache_key,
        ttl_seconds=0,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
    )

    saved = _packet_json(stale)
    assert stale.freshness["cache"]["state"] == "stale_fallback"
    assert stale.freshness["stale"] is True
    assert "secret-value" not in saved
    assert stale.payload["observations"][0]["date"] == "2026-01-01"


@pytest.mark.parametrize("error_type", [DataTransportError, DataUnavailableError])
def test_cached_safe_fetch_without_cache_returns_blocked_packet(tmp_path, error_type):
    def broken_fetch():
        raise error_type("api_key=secret-value failed")

    packet = cached_safe_fetch_evidence(
        broken_fetch,
        cache_key=official_cache_key("fred", "missing"),
        ttl_seconds=3600,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
    )

    saved = _packet_json(packet)
    assert packet.redaction_status == "blocked"
    assert packet.payload["status"] == "blocked"
    assert "secret-value" not in saved


def test_cached_safe_fetch_does_not_use_stale_cache_when_policy_forbids_it(tmp_path):
    cache_key = official_cache_key("fred", "policy-forbids-stale")

    def good_fetch():
        return evidence_packet(
            source_name="fred",
            evidence_type="series_observations",
            subject="GDP",
            source_ref="https://api.stlouisfed.org/fred/series/observations?series_id=GDP",
            payload={"observations": [{"date": "2026-01-01"}]},
            request_fingerprint=cache_key,
        )

    cached_safe_fetch_evidence(
        good_fetch,
        cache_key=cache_key,
        ttl_seconds=0,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
    )

    def unavailable_fetch():
        raise DataUnavailableError("source has no current evidence")

    packet = cached_safe_fetch_evidence(
        unavailable_fetch,
        cache_key=cache_key,
        ttl_seconds=0,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
        allow_stale_on_error=False,
    )

    assert packet.payload["status"] == "blocked"
    assert packet.freshness.get("cache", {}).get("state") != "stale_fallback"


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: OfficialDataError("malformed official evidence"),
        lambda: RuntimeError("unexpected runtime failure"),
        lambda: TypeError("programming contract failure"),
        lambda: AssertionError("invariant failure"),
        _source_packet_validation_error,
    ],
)
def test_cached_safe_fetch_propagates_nonrecoverable_refresh_without_stale_fallback(
    tmp_path,
    error_factory,
):
    cache_key = official_cache_key("fred", type(error_factory).__name__)

    def good_fetch():
        return evidence_packet(
            source_name="fred",
            evidence_type="series_observations",
            subject="GDP",
            source_ref="https://api.stlouisfed.org/fred/series/observations?series_id=GDP",
            payload={"observations": [{"date": "2026-01-01"}]},
            request_fingerprint=cache_key,
        )

    cached_safe_fetch_evidence(
        good_fetch,
        cache_key=cache_key,
        ttl_seconds=0,
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        cache_dir=tmp_path,
    )
    error = error_factory()

    def broken_fetch():
        raise error

    with pytest.raises(type(error)) as exc_info:
        cached_safe_fetch_evidence(
            broken_fetch,
            cache_key=cache_key,
            ttl_seconds=0,
            source_name="fred",
            evidence_type="series_observations",
            subject="GDP",
            cache_dir=tmp_path,
            allow_stale_on_error=True,
        )

    assert exc_info.value is error


def test_eodhd_uses_api_token_without_packet_leakage():
    session = FakeSession({"General": {"Code": "AAPL"}, "api_token": "echo-secret"})

    packet = eodhd.fetch_eodhd_fundamentals(
        "AAPL.US",
        api_token="eodhd-secret",
        session=session,
    )

    _method, url, kwargs = session.calls[0]
    assert url == "https://eodhd.com/api/fundamentals/AAPL.US"
    assert kwargs["params"]["api_token"] == "eodhd-secret"
    saved = _packet_json(packet)
    assert "eodhd-secret" not in saved
    assert "echo-secret" not in saved
    assert "api_token" not in packet.source_refs[0]
    assert packet.analysis_only is True


def test_finnhub_uses_header_token_without_packet_leakage():
    session = FakeSession({"c": 123.45, "token": "echo-secret"})

    packet = finnhub.fetch_finnhub_quote("msft", api_key="finnhub-secret", session=session)

    _method, url, kwargs = session.calls[0]
    assert url == "https://finnhub.io/api/v1/quote"
    assert kwargs["headers"]["X-Finnhub-Token"] == "finnhub-secret"
    saved = _packet_json(packet)
    assert "finnhub-secret" not in saved
    assert "echo-secret" not in saved
    assert "token" not in packet.source_refs[0].lower()
    assert packet.symbol == "MSFT"


def test_fmp_massive_and_marketaux_strip_query_tokens():
    fmp_session = FakeSession({"data": [{"symbol": "AAPL"}], "apikey": "echo-secret"})
    massive_session = FakeSession({"results": {"ticker": "AAPL"}, "apiKey": "echo-secret"})
    marketaux_session = FakeSession(
        {"data": [{"title": "AAPL news", "published_at": "2026-06-01T10:00:00Z"}]}
    )

    fmp_packet = fmp.fetch_fmp_quote("AAPL", api_key="fmp-secret", session=fmp_session)
    massive_packet = massive.fetch_massive_ticker_overview(
        "AAPL",
        api_key="massive-secret",
        session=massive_session,
    )
    marketaux_packet = marketaux.fetch_marketaux_news(
        symbols=["AAPL"],
        api_token="marketaux-secret",
        session=marketaux_session,
    )

    assert fmp_session.calls[0][2]["params"]["apikey"] == "fmp-secret"
    assert massive_session.calls[0][2]["params"]["apiKey"] == "massive-secret"
    assert marketaux_session.calls[0][2]["params"]["api_token"] == "marketaux-secret"
    saved = "\n".join(
        _packet_json(packet)
        for packet in (fmp_packet, massive_packet, marketaux_packet)
    )
    assert "fmp-secret" not in saved
    assert "massive-secret" not in saved
    assert "marketaux-secret" not in saved
    assert "apikey" not in fmp_packet.source_refs[0].lower()
    assert "apikey" not in massive_packet.source_refs[0].lower()
    assert "api_token" not in marketaux_packet.source_refs[0].lower()


def test_fmp_earning_call_transcript_uses_key_without_packet_leakage():
    transcript = "Operator: welcome. Management: demand improved and margins expanded."
    session = FakeSession(
        [
            {
                "symbol": "AAPL",
                "year": 2026,
                "quarter": 1,
                "date": "2026-02-01",
                "content": transcript,
            }
        ]
    )

    packet = fmp.fetch_fmp_earning_call_transcript(
        "aapl",
        year=2026,
        quarter=1,
        api_key="fmp-secret",
        session=session,
    )

    _method, url, kwargs = session.calls[0]
    assert url == "https://financialmodelingprep.com/stable/earning-call-transcript"
    assert kwargs["params"]["apikey"] == "fmp-secret"
    assert kwargs["params"]["symbol"] == "AAPL"
    assert kwargs["params"]["year"] == 2026
    assert kwargs["params"]["quarter"] == 1
    saved = _packet_json(packet)
    assert "fmp-secret" not in saved
    assert "apikey" not in packet.source_refs[0].lower()
    assert packet.source_name == "fmp"
    assert packet.evidence_type == "earnings_transcripts"
    assert packet.symbol == "AAPL"
    assert packet.payload["transcript_item_count"] == 1
    assert packet.payload["transcript_char_count"] == len(transcript)
    assert packet.payload["execution_authority"] == "none"


def test_fmp_latest_earning_call_transcript_discovers_latest_quarter():
    transcript = "Prepared remarks. Analyst Q&A. Guidance tone improved."
    session = SequentialFakeSession(
        [
            [
                {"date": "2025-10-31", "year": 2025, "quarter": 3},
                {"date": "2026-02-02", "year": 2026, "quarter": 4},
            ],
            [
                {
                    "symbol": "MSFT",
                    "year": 2026,
                    "quarter": 4,
                    "date": "2026-02-02",
                    "content": transcript,
                }
            ],
        ]
    )

    packet = fmp.fetch_fmp_latest_earning_call_transcript(
        "msft",
        api_key="fmp-secret",
        session=session,
    )

    assert len(session.calls) == 2
    assert session.calls[0][1].endswith("/earning-call-transcript-dates")
    assert session.calls[1][1].endswith("/earning-call-transcript")
    assert session.calls[1][2]["params"]["year"] == 2026
    assert session.calls[1][2]["params"]["quarter"] == 4
    assert packet.payload["year"] == 2026
    assert packet.payload["quarter"] == 4
    assert packet.payload["transcript_char_count"] == len(transcript)


def test_fmp_missing_transcript_text_and_dates_are_unavailable():
    with pytest.raises(DataUnavailableError, match="no transcript text"):
        fmp.fetch_fmp_earning_call_transcript(
            "AAPL",
            year=2026,
            quarter=1,
            api_key="fmp-secret",
            session=FakeSession([{"symbol": "AAPL", "content": ""}]),
        )

    with pytest.raises(DataUnavailableError, match="no earnings transcript dates"):
        fmp.fetch_fmp_latest_earning_call_transcript(
            "AAPL",
            api_key="fmp-secret",
            session=FakeSession({"data": []}),
        )


@pytest.mark.parametrize(
    ("symbol", "quarter", "message"),
    [
        ("", 1, "symbol is missing"),
        ("AAPL", 5, "quarter must be 1-4"),
    ],
)
def test_fmp_transcript_invalid_caller_input_remains_terminal(
    symbol,
    quarter,
    message,
):
    with pytest.raises(OfficialDataError, match=message) as exc_info:
        fmp.fetch_fmp_earning_call_transcript(
            symbol,
            year=2026,
            quarter=quarter,
            api_key="fmp-secret",
            session=FakeSession(),
        )

    assert not isinstance(exc_info.value, RecoverableDataflowError)


def test_optional_vendor_route_helpers_reject_unsafe_paths():
    with pytest.raises(OfficialDataError):
        fmp.fetch_fmp_route("../admin", api_key="fmp-secret", session=FakeSession())
    with pytest.raises(OfficialDataError):
        massive.fetch_massive_route("v99/private", api_key="massive-secret", session=FakeSession())
    with pytest.raises(OfficialDataError):
        finnhub.fetch_finnhub_basic_financials(
            "",
            api_key="finnhub-secret",
            session=FakeSession(),
        )


def test_newsapi_everything_uses_key_without_packet_leakage():
    session = FakeSession(
        {
            "status": "ok",
            "apiKey": "echo-secret",
            "articles": [{"title": "NVDA headline", "publishedAt": "2026-06-01T12:00:00Z"}],
        }
    )

    packet = newsapi.fetch_newsapi_everything(
        "NVDA stock",
        api_key="newsapi-secret",
        session=session,
        symbol="nvda",
    )

    _method, url, kwargs = session.calls[0]
    assert url == "https://newsapi.org/v2/everything"
    assert kwargs["params"]["apiKey"] == "newsapi-secret"
    saved = _packet_json(packet)
    assert "newsapi-secret" not in saved
    assert "echo-secret" not in saved
    assert "apikey" not in packet.source_refs[0].lower()
    assert packet.symbol == "NVDA"
    assert packet.analysis_only is True


def test_tiingo_uses_header_token_without_packet_leakage():
    session = FakeSession(
        {
            "data": [{"ticker": "MSFT", "date": "2026-06-01T00:00:00Z"}],
            "Authorization": "Token echo-secret",
        }
    )

    packet = tiingo.fetch_tiingo_daily_prices(
        "msft",
        api_key="tiingo-secret",
        start_date="2026-06-01",
        session=session,
    )

    _method, url, kwargs = session.calls[0]
    assert url == "https://api.tiingo.com/tiingo/daily/MSFT/prices"
    assert kwargs["headers"]["Authorization"] == "Token tiingo-secret"
    saved = _packet_json(packet)
    assert "tiingo-secret" not in saved
    assert "echo-secret" not in saved
    assert "token" not in packet.source_refs[0].lower()
    assert packet.symbol == "MSFT"
    assert packet.analysis_only is True


def test_alpaca_news_uses_paper_keys_read_only_without_packet_leakage():
    session = FakeSession(
        {
            "news": [{"headline": "AAPL headline", "created_at": "2026-06-01T12:00:00Z"}],
            "APCA-API-KEY-ID": "echo-key",
            "APCA-API-SECRET-KEY": "echo-secret",
        }
    )

    packet = alpaca_news.fetch_alpaca_news(
        symbols=["aapl"],
        api_key="paper-key",
        secret_key="paper-secret",
        session=session,
    )

    _method, url, kwargs = session.calls[0]
    assert url == "https://data.alpaca.markets/v1beta1/news"
    assert kwargs["headers"]["APCA-API-KEY-ID"] == "paper-key"
    assert kwargs["headers"]["APCA-API-SECRET-KEY"] == "paper-secret"
    saved = _packet_json(packet)
    assert "paper-key" not in saved
    assert "paper-secret" not in saved
    assert "echo-key" not in saved
    assert "echo-secret" not in saved
    assert packet.freshness["execution_authority"] == "none"
    assert packet.freshness["read_only"] is True
    assert packet.symbol == "AAPL"


def test_new_optional_routes_reject_unsafe_paths():
    with pytest.raises(OfficialDataError):
        newsapi.fetch_newsapi_route("../admin", api_key="newsapi-secret", session=FakeSession())
    with pytest.raises(OfficialDataError):
        tiingo.fetch_tiingo_route("private/accounts", api_key="tiingo-secret", session=FakeSession())


def test_google_news_rss_parses_items_as_low_authority_news():
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><title>Google News</title><link>https://news.google.com/</link>
      <item><title>AAPL headline</title><link>https://example.test/a</link>
      <pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate><source>Example</source></item>
    </channel></rss>"""
    session = FakeSession(text=rss)

    packet = google_news.fetch_google_news_rss(query="AAPL stock", session=session)

    _method, url, kwargs = session.calls[0]
    assert url == "https://news.google.com/rss/search"
    assert kwargs["params"]["q"] == "AAPL stock"
    assert packet.source_name == "google_news_rss"
    assert packet.quality == "low"
    assert packet.payload["items"][0]["title"] == "AAPL headline"
    assert packet.analysis_only is True


def test_google_news_rss_filters_items_to_requested_date_window():
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><title>Google News</title><link>https://news.google.com/</link>
      <item><title>Old headline</title><link>https://example.test/old</link>
      <pubDate>Sun, 31 May 2026 10:00:00 GMT</pubDate><source>Example</source></item>
      <item><title>In-window headline</title><link>https://example.test/in</link>
      <pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate><source>Example</source></item>
      <item><title>Future headline</title><link>https://example.test/future</link>
      <pubDate>Thu, 04 Jun 2026 10:00:00 GMT</pubDate><source>Example</source></item>
    </channel></rss>"""
    session = FakeSession(text=rss)

    packet = google_news.fetch_google_news_rss(
        query="AAPL stock",
        start_date="2026-06-01",
        end_date="2026-06-03",
        session=session,
    )

    assert [item["title"] for item in packet.payload["items"]] == ["In-window headline"]
    assert packet.freshness["item_count"] == 1
    assert packet.freshness["unfiltered_item_count"] == 3
    assert packet.freshness["filtered_out_count"] == 2
    assert packet.freshness["date_filter"] == {
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
    }


@pytest.mark.parametrize("rss", ["not XML", "<rss></rss>"])
def test_google_news_unusable_external_rss_is_transport_failure(rss):
    with pytest.raises(DataTransportError):
        google_news.fetch_google_news_rss(
            query="AAPL stock",
            session=FakeSession(text=rss),
        )


def test_google_news_invalid_caller_date_remains_terminal():
    with pytest.raises(OfficialDataError, match="date filter") as exc_info:
        google_news.fetch_google_news_rss(
            query="AAPL stock",
            start_date="not-a-date",
            session=FakeSession(text="<rss><channel /></rss>"),
        )

    assert not isinstance(exc_info.value, RecoverableDataflowError)


def test_scrapingbee_uses_key_but_writes_only_redacted_preview():
    session = FakeSession(
        text="<html><title>Market page</title><p>AAPL news context</p></html>",
        headers={"Content-Type": "text/html"},
        status_code=200,
    )

    packet = scrapingbee.fetch_scrapingbee_html(
        "https://news.google.com/rss/search?q=AAPL&api_key=target-secret",
        api_key="scrapingbee-secret",
        session=session,
    )

    _method, url, kwargs = session.calls[0]
    assert url == "https://app.scrapingbee.com/api/v1"
    assert kwargs["params"]["api_key"] == "scrapingbee-secret"
    saved = _packet_json(packet)
    assert "scrapingbee-secret" not in saved
    assert "target-secret" not in saved
    assert "api_key" not in packet.source_refs[0].lower()
    assert packet.payload["content_type"] == "text/html"
    assert packet.freshness["read_only"] is True


def test_scrapingbee_rejects_non_allowlisted_targets():
    with pytest.raises(OfficialDataError):
        scrapingbee.fetch_scrapingbee_html(
            "https://evil.example.test/page",
            api_key="scrapingbee-secret",
            session=FakeSession(text="blocked"),
        )
