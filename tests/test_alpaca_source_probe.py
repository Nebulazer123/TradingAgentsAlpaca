"""Offline diagnostic tests. Fixtures are synthetic, NOT historical market truth."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import socket
import subprocess
import sys
from decimal import Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tradingagents/dataflows/alpaca_source_probe.py"
SPEC = importlib.util.spec_from_file_location("_test_alpaca_source_probe", MODULE)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)

NOW = dt.datetime(2026, 10, 1, 18, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A fixture test attempted a real network connection")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def dates():
    # Deliberately synthetic weekday calendar. Never claim official holiday coverage.
    result = []
    date = dt.date(2026, 1, 2)
    while len(result) < 60:
        if date.weekday() < 5:
            result.append(date.isoformat())
        date += dt.timedelta(days=1)
    return result


def plan(symbols=("AAPL",), replay=False):
    sessions = dates()
    return probe.ProbePlan(sessions[0], sessions[-1], "2026-10-01", tuple(sorted(symbols)),
                           "2026-09-20T00:00:00Z" if replay else None,
                           "2026-09-20T01:00:00Z" if replay else None)


def body(value):
    return json.dumps(value, separators=(",", ":")).encode()


def asset(symbol="AAPL", index=1, status="active", **overrides):
    return {"id": str(UUID(int=index)), "symbol": symbol, "class": "us_equity", "exchange": "NASDAQ",
            "status": status, "tradable": status == "active", **overrides}


def bars(symbol="AAPL"):
    rows = []
    for i, date in enumerate(dates(), 1):
        instant = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(), probe.NY).astimezone(probe.UTC)
        rows.append({"t": instant.isoformat().replace("+00:00", "Z"), "c": 10, "v": i})
    return {"symbol": symbol, "bars": rows, "next_page_token": None}


def sse_payload(event_id="01J9RPMV5TKB8WX3M4F1KZ7QH2", event_type="name_change_corporateaction_event", **extras):
    return {"event_id": event_id, "event_type": event_type, "action": "insert", "at": "2026-09-20T00:00:00Z", "region": "us", "ca": {"id": "example-action"}, **extras}


def frame(payload):
    return b"data: " + body(payload) + b"\n\n"


class FakeTransport:
    def __init__(self, active_plan, overrides=None):
        self.plan = active_plan
        self.overrides = overrides or {}
        self.calls = []

    def get(self, request, **kwargs):
        self.calls.append(request)
        index = sum(item.query_id == request.query_id for item in self.calls) - 1
        custom = self.overrides.get(request.query_id)
        if custom is not None:
            return custom[min(index, len(custom) - 1)]
        if request.kind == "assets":
            state = dict(request.params)["status"]
            payload = [asset(sym, i + 1) for i, sym in enumerate(self.plan.symbols)] if state == "active" else [asset("OLD", 1000, "inactive")]
        elif request.kind == "asset":
            payload = asset(request.symbol, self.plan.symbols.index(request.symbol) + 1)
        elif request.kind == "calendar":
            payload = [{"date": date, "open": "09:30", "close": "16:00"} for date in dates()]
        elif request.kind == "bars":
            payload = bars(request.symbol)
        elif request.kind == "actions":
            payload = {"corporate_actions": {}, "next_page_token": None}
        else:
            return probe.FetchResult(200, "text/event-stream", frame(sse_payload()))
        return probe.FetchResult(200, "application/json", body(payload))


def collect(tmp_path, overrides=None, active_plan=None):
    active_plan = active_plan or plan()
    transport = FakeTransport(active_plan, overrides)
    destination = tmp_path / "capture"
    report = probe.collect_probe(active_plan, destination, transport, allow_network_read=True, clock=lambda: NOW)
    return report, destination, transport


def test_plan_is_canonical_and_round_trips():
    p = plan(("A", "AAPL", "BRK.B"))
    assert probe.ProbePlan.from_dict(p.to_dict()) == p
    requests = probe.build_requests(p)
    assert all(item.to_dict()["method"] == "GET" for item in requests)
    assert {item.host for item in requests} == {"paper-api.alpaca.markets", "data.alpaca.markets"}
    assert all("accounts" not in item.path and "orders" not in item.path and "positions" not in item.path for item in requests)
    bars_query = next(item for item in requests if item.kind == "bars")
    assert dict(bars_query.params)["asof"] == "2026-10-01"
    assert dict(bars_query.params)["feed"] == "sip"
    assert dict(bars_query.params)["adjustment"] == "raw"
    assert next(item for item in requests if item.kind == "asset").url.endswith("/A")


@pytest.mark.parametrize("changes", [
    {"symbols": ("aapl",)}, {"symbols": ("../orders",)}, {"symbols": ("AAPL?x",)},
    {"symbols": ("AAPL", "AAPL")}, {"symbols": ("B", "A")}, {"symbols": ()},
    {"symbols": tuple(f"X{i:02}" for i in range(13))},
    {"start": "2026-12-01"}, {"end": "2028-01-01"}, {"symbol_asof": "now"},
    {"replay_since": "2026-01-01T00:00:00Z"},
    {"replay_since": "2026-01-01T00:00:00Z", "replay_until": "2026-02-01T00:00:00Z"},
])
def test_invalid_plans_fail_before_requests(changes):
    fields = dict(start=plan().start, end=plan().end, symbol_asof=plan().symbol_asof,
                  symbols=plan().symbols, replay_since=None, replay_until=None)
    with pytest.raises(probe.ProbeError):
        probe.ProbePlan(**{**fields, **changes})


def test_no_arbitrary_url_from_serialized_plan():
    value = plan().to_dict()
    value["url"] = "https://evil.example/capture"
    with pytest.raises(probe.ProbeError):
        probe.ProbePlan.from_dict(value)


def test_opt_in_required_before_any_write_or_request(tmp_path):
    transport = FakeTransport(plan())
    with pytest.raises(probe.ProbeError, match="authorization"):
        probe.collect_probe(plan(), tmp_path / "nope", transport)
    assert transport.calls == []
    assert not (tmp_path / "nope").exists()


def test_complete_replay_and_median_are_not_historical_qualification(tmp_path):
    report, root, transport = collect(tmp_path)
    assert report["diagnostic_checks_passed"] is True
    assert report["sample_bars"]["AAPL"]["median_daily_dollar_volume"] == "305"
    assert report["sample_bars"]["AAPL"]["prior_complete_close"] == "10"
    assert report["calendar"]["exactly_60"]
    assert report["corporate_actions"]["returned_records"] == 0
    assert report["corporate_actions"]["event_absence_proven"] is False
    for key in ("security_master_qualified", "cohort_qualified", "historical_custody_qualified"):
        assert report[key] is False
    assert report["sample_assets"]["AAPL"]["historical_effective_from"] is None
    assert report["sample_assets"]["AAPL"]["security_type"] == "UNKNOWN"
    assert probe.inspect_probe(root) == report
    assert all(item.host in probe._HOSTS for item in transport.calls)
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "responses/0001.body").stat().st_mode & 0o777 == 0o600


def test_json_decimal_precision_ignores_ambient_context(tmp_path):
    payload = bars()
    raw = body(payload).replace(b'"c":10', b'"c":10.12345678901234567890123456789')
    with localcontext() as context:
        context.prec = 3
        report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", raw)]})
    with localcontext() as context:
        context.prec = 100
        expected = probe._decimal_text(Decimal("10.12345678901234567890123456789") * Decimal("30.5"))
    assert report["sample_bars"]["AAPL"]["median_daily_dollar_volume"] == expected


def test_more_than_512_inventory_records_do_not_truncate(tmp_path):
    payload = [asset(f"X{i:04}", i + 1) for i in range(1025)]
    report, _, _ = collect(tmp_path, {"assets_active": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["inventory"]["active"]["records"] == 1025
    assert report["market_population_completeness"] == "NOT_ESTABLISHED"


def test_dual_share_classes_are_not_merged(tmp_path):
    report, _, _ = collect(tmp_path, active_plan=plan(("GOOG", "GOOGL")))
    assert report["sample_assets"]["GOOG"]["id"] != report["sample_assets"]["GOOGL"]["id"]
    assert len(report["sample_assets"]) == 2


def test_same_active_ticker_with_distinct_ids_remains_ambiguous(tmp_path):
    payload = [asset("META", 1), asset("META", 2)]
    report, _, _ = collect(tmp_path, {"assets_active": [probe.FetchResult(200, "application/json", body(payload))]})
    assert len(report["inventory"]["ambiguous_active_symbols"]["META"]) == 2


def test_untradable_and_etf_names_never_become_common_stock(tmp_path):
    payload = [asset("ETF", 1, name="A Very Common Stock ETF"), asset("BLOCK", 2, tradable=False)]
    report, _, _ = collect(tmp_path, {"assets_active": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["inventory"]["active"]["potential_common_stock_candidates_not_type_verified"] == 1
    assert report["inventory"]["active"]["common_stock_classification"] == "UNKNOWN"


def test_follow_short_pages_using_token_not_row_count(tmp_path):
    payload = bars()
    first = {**payload, "bars": [], "next_page_token": "opaque+/token="}
    second = {**payload, "bars": payload["bars"][:11], "next_page_token": "two"}
    third = {**payload, "bars": payload["bars"][11:]}
    overrides = {"bars_AAPL": [probe.FetchResult(200, "application/json", body(item)) for item in (first, second, third)]}
    report, root, transport = collect(tmp_path, overrides)
    calls = [item for item in transport.calls if item.kind == "bars"]
    assert len(calls) == 3
    assert dict(calls[1].params)["page_token"] == "opaque+/token="
    assert "opaque%2B%2Ftoken%3D" in calls[1].url
    assert report["diagnostic_checks_passed"]
    assert probe.inspect_probe(root) == report


@pytest.mark.parametrize("payload,reason", [
    ({"bars": [], "symbol": "AAPL"}, "pagination_field_missing"),
    ({"bars": [], "symbol": "AAPL", "next_page_token": ""}, "invalid_page_token"),
    ({"bars": [], "symbol": "AAPL", "next_page_token": "x\r\n"}, "invalid_page_token"),
    ({"bars": [], "symbol": "AAPL", "next_page_token": "same"}, "pagination_cycle"),
])
def test_bad_pagination_is_not_complete(tmp_path, payload, reason):
    report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["queries"]["bars_AAPL"]["reason"] == reason
    assert report["diagnostic_checks_passed"] is False


def test_page_budget_is_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "MAX_PAGES", 1)
    payload = {**bars(), "next_page_token": "more"}
    report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["queries"]["bars_AAPL"]["status"] == "incomplete"
    assert not report["diagnostic_checks_passed"]


@pytest.mark.parametrize("status,reason,stop", [
    (401, "authentication_failed", True), (403, "forbidden_unverified_entitlement", False),
    (404, "not_found_not_delisting_proof", False), (429, "rate_limited", True),
    (302, "http_status_not_200", False), (500, "http_status_not_200", False),
])
def test_http_failures_do_not_become_empty_universe(tmp_path, status, reason, stop):
    report, _, transport = collect(tmp_path, {"assets_active": [probe.FetchResult(status, "application/json", b'{}')]})
    assert report["queries"]["assets_active"]["reason"] == reason
    assert (len(transport.calls) == 1) is stop
    assert not report["diagnostic_checks_passed"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["bars"].append(p["bars"][0]), "bar_duplicate_or_unsorted"),
    (lambda p: p.update(symbol="WRONG"), "bar_response_shape_or_symbol"),
    (lambda p: p["bars"][0].update(v=True), "bar_number_type"),
    (lambda p: p["bars"][0].update(v=-1), "bar_number_type"),
    (lambda p: p["bars"][0].update(c=0), "bar_number_range"),
    (lambda p: p["bars"][0].update(t="2026-01-02T09:30:00Z"), "not_daily_bar_timestamp"),
])
def test_bad_bars_fail_diagnostics(tmp_path, mutation, reason):
    payload = bars()
    mutation(payload)
    report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["queries"]["bars_AAPL"]["reason"] == reason
    assert not report["diagnostic_checks_passed"]


def test_missing_session_not_imputed_to_zero(tmp_path):
    payload = bars()
    payload["bars"].pop(12)
    report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["sample_bars"]["AAPL"]["missing_sessions"] == [dates()[12]]
    assert report["sample_bars"]["AAPL"]["median_daily_dollar_volume"] is None
    assert not report["diagnostic_checks_passed"]


def test_explicit_zero_volume_is_valid_not_missing(tmp_path):
    payload = bars()
    payload["bars"][12]["v"] = 0
    report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["sample_bars"]["AAPL"]["matches_60_session_grid"]


def test_incomplete_body_preserved_but_not_parsed(tmp_path):
    partial = b'{"bars":'
    report, root, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", partial, False, "byte_budget")]})
    entry = next(item for item in json.loads((root / "manifest.json").read_text())["entries"] if item["query_id"] == "bars_AAPL")
    assert (root / entry["body_path"]).read_bytes() == partial
    assert report["queries"]["bars_AAPL"]["reason"] == "byte_budget"
    assert "AAPL" not in report["sample_bars"]


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e100000}', b'[]garbage'])
def test_malformed_json_rejected(raw):
    with pytest.raises(probe.ProbeError):
        probe._load(raw)


def test_sse_replay_deduplicates_without_historical_completeness(tmp_path):
    a = sse_payload(action="insert")
    b = sse_payload("01J9RPMV5TKB8WX3M4F1KZ7QH3", action="update")
    c = sse_payload("01J9RPMV5TKB8WX3M4F1KZ7QH4", action="delete")
    raw = b': heartbeat\n\n' + frame(a) + frame(a) + frame(b) + frame(c)
    report, _, _ = collect(tmp_path, {"action_replay": [probe.FetchResult(200, "text/event-stream", raw)]}, plan(replay=True))
    assert report["action_replay"]["unique_events"] == 3
    assert report["action_replay"]["duplicate_deliveries"] == 1
    assert report["action_replay"]["mutations_applied"] is False
    assert report["action_replay"]["revision_history_completeness"] == "UNKNOWN"


@pytest.mark.parametrize("end", [b"", b"\n"])
def test_truncated_sse_frame_is_not_dispatched(end):
    raw = b'data: ' + body(sse_payload()) + end
    with pytest.raises(probe.ProbeError, match="unterminated"):
        probe.parse_sse(raw)


def test_sse_multiline_crlf_bom_and_unknown_action_type():
    text = json.dumps(sse_payload(event_type="future_action_type"), indent=2)
    raw = b'\xef\xbb\xbf' + b'\r\n'.join(b'data: ' + line.encode() for line in text.splitlines()) + b'\r\n\r\n'
    result = probe.parse_sse(raw)
    assert result["event_types"] == {"future_action_type": 1}


def test_sse_conflicting_id_is_rejected():
    with pytest.raises(probe.ProbeError, match="conflicting"):
        probe.parse_sse(frame(sse_payload(action="insert")) + frame(sse_payload(action="update")))


def test_sse_frame_count_is_bounded(monkeypatch):
    monkeypatch.setattr(probe, "MAX_EVENTS", 1)
    with pytest.raises(probe.ProbeError, match="event_limit"):
        probe.parse_sse(frame(sse_payload()) * 2)


def test_corporate_action_pages_preserve_unknown_types(tmp_path):
    payload = {"corporate_actions": {"future_action_type": [{"id": "a", "cash": 1.25}]}, "next_page_token": None}
    report, _, _ = collect(tmp_path, {"actions": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["corporate_actions"]["types"] == {"future_action_type": 1}
    assert report["corporate_actions"]["query_date_basis"] == "process_date"
    assert report["corporate_actions"]["event_absence_proven"] is False


def test_corporate_action_pagination_revision_is_not_silently_overwritten(tmp_path):
    first = {"corporate_actions": {"cash_dividends": [{"id": "same", "cash": 1}]}, "next_page_token": "two"}
    last = {"corporate_actions": {"cash_dividends": [{"id": "same", "cash": 2}]}, "next_page_token": None}
    report, _, _ = collect(tmp_path, {"actions": [probe.FetchResult(200, "application/json", body(value)) for value in (first, last)]})
    assert report["queries"]["actions"]["status"] == "invalid"


def test_raw_tampering_detected(tmp_path):
    _, root, _ = collect(tmp_path)
    (root / "responses/0001.body").write_bytes(b'[]')
    with pytest.raises(probe.ProbeError, match="raw_bytes_mismatch"):
        probe.inspect_probe(root)


def test_missing_response_detected(tmp_path):
    _, root, _ = collect(tmp_path)
    (root / "responses/0002.body").unlink()
    with pytest.raises(probe.ProbeError):
        probe.inspect_probe(root)


def test_unexpected_file_detected(tmp_path):
    _, root, _ = collect(tmp_path)
    (root / "extra.json").write_text('{}')
    with pytest.raises(probe.ProbeError, match="unexpected"):
        probe.inspect_probe(root)


def test_symlink_body_refused(tmp_path):
    _, root, _ = collect(tmp_path)
    original = root / "responses/0001.body"
    target = tmp_path / "outside"
    target.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(target)
    with pytest.raises(probe.ProbeError):
        probe.inspect_probe(root)


def test_cached_report_is_not_trusted(tmp_path):
    report, root, _ = collect(tmp_path)
    (root / "report.json").write_text('{"cohort_qualified":true}')
    assert probe.inspect_probe(root) == report


def test_does_not_overwrite_existing_destination(tmp_path):
    _, root, _ = collect(tmp_path)
    with pytest.raises(probe.ProbeError, match="must_be_new"):
        probe.collect_probe(plan(), root, FakeTransport(plan()), allow_network_read=True, clock=lambda: NOW)


def test_global_request_budget_keeps_partial_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "MAX_REQUESTS", 1)
    report, root, transport = collect(tmp_path)
    assert len(transport.calls) == 1
    assert (root / "manifest.json").exists()
    assert report["queries"]["calendar"]["status"] == "not_attempted"
    assert not report["diagnostic_checks_passed"]


def test_future_windows_rejected_before_capture(tmp_path):
    p = probe.ProbePlan("2026-09-01", "2026-10-01", "2026-10-01", ("AAPL",))
    transport = FakeTransport(p)
    with pytest.raises(probe.ProbeError, match="completed_dates"):
        probe.collect_probe(p, tmp_path / "capture", transport, allow_network_read=True, clock=lambda: NOW)
    assert transport.calls == []


def test_clock_regression_does_not_mint_success(tmp_path):
    times = iter([NOW, NOW, NOW - dt.timedelta(seconds=1)])
    with pytest.raises(probe.ProbeError, match="clock_regressed"):
        probe.collect_probe(plan(), tmp_path / "capture", FakeTransport(plan()), allow_network_read=True, clock=lambda: next(times))
    assert not (tmp_path / "capture/manifest.json").exists()


def test_real_transport_refuses_unplanned_or_mutating_endpoint():
    t = probe.AlpacaReadTransport(plan(), "fixture-key", "fixture-secret")
    base = probe.build_requests(plan())[0]
    bad = probe.replace(base, host="evil.example", path="/v2/orders")
    with pytest.raises(probe.ProbeError, match="unplanned"):
        t.get(bad, timeout=1, max_bytes=1000, deadline=probe.time.monotonic()+1)


def test_cli_plan_does_not_read_environment(monkeypatch, capsys):
    class ForbiddenEnvironment:
        def get(self, *args):
            raise AssertionError("offline command read environment")
    monkeypatch.setattr(probe, "os", SimpleNamespace(environ=ForbiddenEnvironment()))
    assert probe.main(["plan", "--start", plan().start, "--end", plan().end,
                       "--symbol-asof", plan().symbol_asof, "--symbols", "AAPL"]) == 0
    assert json.loads(capsys.readouterr().out)["symbols"] == ["AAPL"]


def test_cli_collection_without_optin_does_not_read_plan_or_credentials(monkeypatch, capsys):
    class ForbiddenEnvironment:
        def get(self, *args):
            raise AssertionError("read credentials")
    monkeypatch.setattr(probe, "os", SimpleNamespace(environ=ForbiddenEnvironment()))
    assert probe.main(["collect", "--plan", "absent.json", "--out", "absent"]) == 2
    assert "authorization" in capsys.readouterr().out


def test_standalone_script_bypasses_package_init(tmp_path):
    (tmp_path / "tradingagents/dataflows").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tradingagents/__init__.py").write_text('raise RuntimeError("package import would load credentials")')
    shutil.copy2(MODULE, tmp_path / "tradingagents/dataflows/alpaca_source_probe.py")
    script = tmp_path / "scripts/alpaca_source_probe.py"
    shutil.copy2(ROOT / "scripts/alpaca_source_probe.py", script)
    result = subprocess.run([sys.executable, str(script), "plan", "--start", plan().start,
                             "--end", plan().end, "--symbol-asof", plan().symbol_asof, "--symbols", "AAPL"],
                            capture_output=True, text=True, timeout=10, check=False, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["schema_version"] == probe.SCHEMA


@pytest.mark.parametrize("complete,status", [(1, 200), (True, True), (True, 999)])
def test_response_types_strict(complete, status):
    with pytest.raises(probe.ProbeError):
        probe.FetchResult(status, "application/json", b'{}', complete)


class FakeHTTPResponse:
    def __init__(self, payload=b'[]', status=200, mime="application/json", encoding="identity", failure=None):
        self.status, self.payload, self.mime, self.encoding = status, payload, mime, encoding
        self.offset = 0
        self.failure = failure

    def getheader(self, key, default=None):
        return {"Content-Type": self.mime, "Content-Encoding": self.encoding}.get(key, default)

    def read1(self, limit):
        if self.failure and self.offset:
            raise self.failure
        data = self.payload[self.offset:self.offset+limit]
        self.offset += len(data)
        return data


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.sock = None
        self.calls = []
        self.closed = False

    def request(self, method, target, headers):
        self.calls.append((method, target, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def http_call(monkeypatch, response, maximum=4096):
    connection = FakeConnection(response)
    made = []
    def factory(host, **kwargs):
        made.append(host)
        return connection
    monkeypatch.setattr(probe.http.client, "HTTPSConnection", factory)
    t = probe.AlpacaReadTransport(plan(), "fixture-key", "fixture-secret")
    result = t.get(probe.build_requests(plan())[0], timeout=1, max_bytes=maximum, deadline=probe.time.monotonic()+1)
    return result, connection, made


def test_http_transport_is_get_only_and_closes(monkeypatch):
    result, connection, hosts = http_call(monkeypatch, FakeHTTPResponse())
    assert result.status == 200 and result.complete
    assert hosts == ["paper-api.alpaca.markets"]
    assert connection.calls[0][0] == "GET"
    assert connection.calls[0][2]["APCA-API-KEY-ID"] == "fixture-key"
    assert connection.closed


def test_http_redirect_is_not_followed(monkeypatch):
    result, connection, hosts = http_call(monkeypatch, FakeHTTPResponse(status=302))
    assert result.status == 302
    assert len(connection.calls) == len(hosts) == 1


def test_http_byte_cap_retains_only_prefix(monkeypatch):
    result, connection, _ = http_call(monkeypatch, FakeHTTPResponse(b'123456'), maximum=3)
    assert result.body == b'123'
    assert result.complete is False and result.stop_reason == "byte_budget"
    assert connection.closed


def test_http_transport_error_keeps_existing_prefix_without_exception_text(monkeypatch):
    result, _, _ = http_call(monkeypatch, FakeHTTPResponse(b'partial', failure=OSError("contains fixture-secret")))
    assert result.body == b'partial'
    assert result.stop_reason == "transport_error"
    assert "fixture-secret" not in repr(result)


def test_http_response_echoing_credentials_is_withheld(monkeypatch):
    result, _, _ = http_call(monkeypatch, FakeHTTPResponse(b'{"error":"fixture-secret"}'))
    assert result.body == b'' and result.stop_reason == "credential_echo_withheld"


def test_http_compression_not_silently_relabelled_raw(monkeypatch):
    result, _, _ = http_call(monkeypatch, FakeHTTPResponse(b'compressed', encoding="gzip"))
    assert not result.complete
    assert result.stop_reason == "unexpected_content_encoding"
    assert result.body == b''


def test_empty_sse_stream_does_not_prove_no_actions():
    result = probe.parse_sse(b': heartbeat\n\n')
    assert result["unique_events"] == 0
    assert result["revision_history_completeness"] == "UNKNOWN"


def test_injected_transport_is_clearly_labelled(tmp_path):
    report, _, _ = collect(tmp_path)
    assert report["transport_mode"] == "injected_fixture"


def test_wrong_content_type_is_diagnostic_failure(tmp_path):
    report, _, _ = collect(tmp_path, {"assets_active": [probe.FetchResult(200, "text/html", b'<h1>blocked</h1>')]})
    assert report["queries"]["assets_active"]["reason"] == "unexpected_content_type"


def test_continuation_request_tampering_detected_even_when_sidecars_match(tmp_path):
    first = {**bars(), "bars": [], "next_page_token": "real-token"}
    overrides = {"bars_AAPL": [probe.FetchResult(200, "application/json", body(first)),
                                probe.FetchResult(200, "application/json", body(bars()))]}
    _, root, _ = collect(tmp_path, overrides)
    manifest = json.loads((root / "manifest.json").read_text())
    entry = next(item for item in manifest["entries"] if item["query_id"] == "bars_AAPL" and item["page"] == 2)
    entry["url"] = entry["url"].replace("real-token", "fake-token")
    (root / f'responses/{entry["sequence"]:04d}.json').write_bytes(probe._json_bytes(entry))
    (root / "manifest.json").write_bytes(probe._json_bytes(manifest))
    with pytest.raises(probe.ProbeError, match="pagination_chain"):
        probe.inspect_probe(root)


def test_cross_request_clock_regression_detected(tmp_path):
    values = iter([NOW, NOW, NOW, NOW - dt.timedelta(seconds=1)])
    with pytest.raises(probe.ProbeError, match="clock_regressed"):
        probe.collect_probe(plan(), tmp_path / "capture", FakeTransport(plan()), allow_network_read=True, clock=lambda: next(values))


def test_ambiguous_identity_is_diagnostic_gap(tmp_path):
    payload = [asset("META", 1), asset("META", 2)]
    report, _, _ = collect(tmp_path, {"assets_active": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["snapshot_identity_conflicts"]
    assert not report["diagnostic_checks_passed"]


def test_http_early_eof_with_content_length_is_partial(monkeypatch):
    response = FakeHTTPResponse(b'[]')
    original = response.getheader
    response.getheader = lambda key, default=None: "99" if key == "Content-Length" else original(key, default)
    result, _, _ = http_call(monkeypatch, response)
    assert result.body == b'[]'
    assert not result.complete
    assert result.stop_reason == "incomplete_http_body"


def test_extreme_even_median_is_exact_without_decimal_context(tmp_path):
    payload = bars()
    for index, row in enumerate(payload["bars"]):
        row["c"] = "SMALL" if index < 30 else "LARGE"
        row["v"] = 1
    raw = body(payload).replace(b'"SMALL"', b'1e-100').replace(b'"LARGE"', b'1e100')
    with localcontext() as context:
        context.prec = 2
        report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", raw)]})
    with localcontext() as context:
        context.prec = 250
        expected = probe._decimal_text((Decimal('1e100') + Decimal('1e-100')) / 2)
    assert report["sample_bars"]["AAPL"]["median_daily_dollar_volume"] == expected


def test_offline_inspection_does_not_read_credentials(tmp_path, monkeypatch):
    report, root, _ = collect(tmp_path)
    class ForbiddenCredentials(dict):
        def get(self, name, default=None):
            if "ALPACA" in name or "SECRET" in name or "KEY" in name:
                raise AssertionError("offline replay read credential configuration")
            return super().get(name, default)
    monkeypatch.setattr(probe.os, "environ", ForbiddenCredentials(probe.os.environ))
    assert probe.inspect_probe(root) == report


def test_inactive_source_identifiers_remain_counted_without_becoming_aliases(tmp_path):
    payload = [asset("78500B403", 100, "inactive"), asset("IMFC_DELISTED", 101, "inactive")]
    report, root, _ = collect(tmp_path, {"assets_inactive": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["inventory"]["inactive"]["records"] == 2
    assert report["inventory"]["inactive"]["unsupported_request_alias_records"] == 2
    assert report["queries"]["assets_inactive"]["status"] == "response_complete"
    assert probe.inspect_probe(root) == report
    with pytest.raises(probe.ProbeError, match="invalid_asset_symbol"):
        probe._asset(payload[0])


def test_null_bars_are_an_observed_empty_response_not_an_imputed_grid(tmp_path):
    report, _, _ = collect(tmp_path, {"bars_AAPL": [probe.FetchResult(200, "application/json", body({"symbol": "AAPL", "bars": None, "next_page_token": None}))]})
    assert report["queries"]["bars_AAPL"]["status"] == "response_complete"
    assert report["sample_bars"]["AAPL"]["row_count"] == 0
    assert report["sample_bars"]["AAPL"]["median_daily_dollar_volume"] is None
    assert report["sample_bars"]["AAPL"]["matches_60_session_grid"] is False
    assert report["cohort_qualified"] is False


def test_v2_capture_receipt_replays_with_explicit_v3_reader_lineage(tmp_path):
    _report, root, _ = collect(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["parser_version"] = "alpaca_source_probe_parser/v2"
    (root / "manifest.json").write_bytes(probe._json_bytes(manifest))
    result = probe.inspect_probe(root)
    assert result["capture_parser_version"] == "alpaca_source_probe_parser/v2"
    assert result["parser_version"] == "alpaca_source_probe_parser/v3"


def test_bounded_replay_allows_more_than_two_thousand_realistic_events():
    frames = []
    for index in range(2501):
        payload = {"event_id": "0" + str(index).zfill(25), "action": "update", "at": "2026-10-01T12:00:00Z",
                   "event_type": "cash_dividend_corporateaction_event", "region": "us", "ca": {"id": f"action-{index}"}}
        frames.append(b"data: " + body(payload) + b"\n\n")
    result = probe.parse_sse(b"".join(frames), since="2026-10-01T00:00:00Z", until="2026-10-02T00:00:00Z")
    assert result["unique_events"] == 2501
    assert result["mutations_applied"] is False


def test_v3_reopens_old_v2_sse_limit_failure_without_erasing_producer_lineage(tmp_path):
    active = plan(replay=True)
    query_id = next(item.query_id for item in probe.build_requests(active) if item.kind == "sse")
    raw = b"".join(frame(sse_payload(event_id="0" + str(index).zfill(25))) for index in range(2501))
    _, root, _ = collect(tmp_path, {query_id: [probe.FetchResult(200, "text/event-stream", raw)]}, active)
    manifest = json.loads((root / "manifest.json").read_bytes())
    manifest["parser_version"] = "alpaca_source_probe_parser/v2"
    manifest["completed_queries"].remove(query_id)
    manifest["failures"][query_id] = "sse_event_limit"
    (root / "manifest.json").write_bytes(probe._json_bytes(manifest))
    result = probe.inspect_probe(root)
    assert result["queries"][query_id]["status"] == "response_complete"
    assert result["capture_failures"][query_id] == "sse_event_limit"
    assert query_id not in result["capture_completed_queries"]
    assert result["capture_parser_version"] == "alpaca_source_probe_parser/v2"
    assert result["action_replay"]["unique_events"] == 2501
    assert result["action_replay"]["mutations_applied"] is False


@pytest.mark.parametrize("status", [401, 429])
def test_terminal_status_stops_even_when_error_body_is_partial(tmp_path, status):
    failure = probe.FetchResult(status, "application/json", b'{', False, "incomplete_http_body")
    report, _, transport = collect(tmp_path, {"assets_active": [failure]})
    assert len(transport.calls) == 1
    assert report["queries"]["assets_active"]["reason"] in {"authentication_failed", "rate_limited"}


def test_asset_uuid_forms_are_compared_as_the_same_identifier(tmp_path):
    identifier = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    payload = [asset(index=1, id=identifier), asset(index=2, id=identifier.upper())]
    report, _, _ = collect(tmp_path, {"assets_active": [probe.FetchResult(200, "application/json", body(payload))]})
    assert report["queries"]["assets_active"]["reason"] == "duplicate_asset_id"


@pytest.mark.parametrize("mutation", ["missing_query", "duplicate_completed", "wrong_failure", "boolean_bytes", "boolean_page"])
def test_manifest_accounting_is_reopened_and_strict(tmp_path, mutation):
    _, root, _ = collect(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    if mutation == "missing_query":
        manifest["completed_queries"].pop()
    elif mutation == "duplicate_completed":
        manifest["completed_queries"].append(manifest["completed_queries"][0])
    elif mutation == "wrong_failure":
        query = manifest["completed_queries"].pop()
        manifest["failures"][query] = "transport_error"
    else:
        entry = manifest["entries"][0]
        entry["page" if mutation == "boolean_page" else "body_bytes"] = True
        (root / "responses/0001.json").write_bytes(probe._json_bytes(entry))
    (root / "manifest.json").write_bytes(probe._json_bytes(manifest))
    with pytest.raises(probe.ProbeError):
        probe.inspect_probe(root)


@pytest.mark.parametrize("changes", [{"action": "replace"}, {"action": None}, {"at": "2026-09-20"}, {"region": "unknown"}, {"ca": []}, {"event_id": "bad-id"}])
def test_unknown_or_malformed_mutation_envelope_is_rejected(changes):
    payload = sse_payload(action="insert", at="2026-09-20T00:00:00Z", region="us")
    payload.update(changes)
    with pytest.raises(probe.ProbeError):
        probe.parse_sse(frame(payload))


def test_documented_array_of_sse_envelopes_is_retained():
    payload = sse_payload(action="insert", at="2026-09-20T00:00:00Z", region="us")
    result = probe.parse_sse(frame([payload]))
    assert result["unique_events"] == 1
    assert result["mutations_applied"] is False


def test_replay_envelope_outside_requested_emission_window_is_unavailable(tmp_path):
    payload = sse_payload(action="insert", at="2026-09-21T00:00:00Z", region="us")
    report, _, _ = collect(tmp_path, {"action_replay": [probe.FetchResult(200, "text/event-stream", frame(payload))]}, plan(replay=True))
    assert report["queries"]["action_replay"]["status"] == "invalid"
    assert not report["diagnostic_checks_passed"]
