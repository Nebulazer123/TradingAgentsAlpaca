"""Offline original terms, raw-price legs, and explicitly unavailable coverage."""

from __future__ import annotations

import copy
import datetime as dt
import json
from fractions import Fraction

import pytest

from tradingagents.dataflows.pit.action_originals import (
    replay_alpaca_action_pages,
    value_covered_action_legs,
    verify_covered_action_valuation,
    verify_execution_action_originals,
    verify_original_action_set,
)
from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError

STAMP = "2026-01-21T00:00:00+00:00"
DATES = ("2026-01-12", "2026-01-16")
ACTION_URI = "https://data.alpaca.markets/v1/corporate-actions?region=US&data_quality=all&start=2026-01-01&end=2026-01-20"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket
    import subprocess
    import urllib.request

    def blocked(*args, **kwargs):
        raise AssertionError("original terms tests cannot perform network or model calls")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)


@pytest.fixture
def archive(tmp_path):
    return RawPointInTimeArtifactArchive(tmp_path / "pit", clock=lambda: dt.datetime.fromisoformat(STAMP))


def original(archive, payload, uri):
    return archive.admit(raw_bytes=json.dumps(payload).encode(), source_uri=uri, content_type="application/json", retrieved_at=STAMP).raw_artifact_id


def record(**fields):
    return {"id": "00000000-0000-0000-0000-000000000001", "process_date": "2026-01-15", **fields}


def action_set(archive, group="cash_mergers", rows=None, *, token=None, uri=ACTION_URI):
    rows = rows if rows is not None else [record(acquiree_symbol="OLD", effective_date="2026-01-15", rate="13", currency="USD")]
    identifier = original(archive, {"corporate_actions": {group: rows}, "next_page_token": token}, uri)
    return replay_alpaca_action_pages(archive=archive, raw_artifact_ids=(identifier,))


def prices(archive, symbol="OLD", *, close="15", adjustment="raw", dates=DATES):
    return original(archive, {"symbol": symbol, "next_page_token": None, "bars": [{"t": f"{date}T05:00:00Z", "o": "10", "c": close} for date in dates]},
                    f"https://data.alpaca.markets/v2/stocks/{symbol}/bars?feed=sip&timeframe=1Day&adjustment={adjustment}&sort=asc&asof=2026-01-20&start=2026-01-12&end=2026-01-16")


def valuation(archive, actions, price_map):
    return value_covered_action_legs(archive=archive, action_set=actions, symbol="OLD", entry_session_date=DATES[0], exit_session_date=DATES[1], price_originals=price_map)


def number(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def test_whole_original_pages_replay_and_no_absence_claim(archive):
    value = action_set(archive)
    assert verify_original_action_set(archive=archive, value=json.loads(json.dumps(value))) == value
    assert value["returned_processing_scope_status"] == "complete"
    assert value["effective_event_coverage_status"] == "NOT_ESTABLISHED"
    assert value["absence_of_events_proven"] is False
    empty = action_set(archive, rows=[])
    assert empty["actions"] == [] and empty["absence_of_events_proven"] is False


@pytest.mark.parametrize("field,value", [("effective_event_coverage_status", "complete"), ("absence_of_events_proven", True), ("analysis_only", 1)])
def test_altered_derived_labels_cannot_prove_original_coverage(archive, field, value):
    receipt = action_set(archive)
    receipt[field] = value
    with pytest.raises(PointInTimeDataError, match="replay"):
        verify_original_action_set(archive=archive, value=receipt)


def test_all_cash_termination_needs_no_later_source_bars_and_keeps_gap(archive):
    value = valuation(archive, action_set(archive), {"OLD": prices(archive, dates=(DATES[0],))})
    assert number(value["covered_exit_value"]) == 13
    assert number(value["covered_return"]) == Fraction(3, 10)
    assert value["remaining_security_legs"] == {}
    assert value["gross_return"] is None
    assert value["status"] == "unavailable_for_economic_admission"
    assert value["entry_price_basis"] == "provider_daily_open_not_certified_session_open"
    assert "official_session_open_price" in value["required_gaps"]
    assert verify_covered_action_valuation(archive=archive, value=value) == value


def test_changed_original_cash_terms_change_value_with_identical_prices(archive):
    price = prices(archive, dates=(DATES[0],))
    first = valuation(archive, action_set(archive), {"OLD": price})
    second = valuation(archive, action_set(archive, rows=[record(acquiree_symbol="OLD", effective_date="2026-01-15", rate="14", currency="USD")]), {"OLD": price})
    assert number(first["covered_exit_value"]) == 13
    assert number(second["covered_exit_value"]) == 14
    assert first["valuation_id"] != second["valuation_id"]


def test_original_byte_tampering_fails_reopen(archive):
    value = action_set(archive)
    identifier = value["original_pages"][0]["raw_artifact_id"]
    (archive.root / "objects" / f"{identifier}.raw").write_bytes(b'{"corporate_actions":{},"next_page_token":null}')
    with pytest.raises(PointInTimeDataError, match="digest|hash|bytes"):
        verify_original_action_set(archive=archive, value=value)


@pytest.mark.parametrize("currency", [None, "", "EUR", True])
def test_cash_currency_cannot_default_to_usd(archive, currency):
    value = action_set(archive, rows=[record(acquiree_symbol="OLD", effective_date="2026-01-15", rate="13", currency=currency)])
    assert value["actions"][0]["normalized_terms"]["terms_status"] == "missing_or_unsupported_terms"
    with pytest.raises(PointInTimeDataError, match="terms are unavailable"):
        valuation(archive, value, {"OLD": prices(archive)})


def test_stock_and_cash_ratio_replays_both_legs(archive):
    def bundle(rate):
        return action_set(archive, "stock_and_cash_mergers", [record(acquiree_symbol="OLD", acquirer_symbol="NEW", effective_date="2026-01-15", acquiree_rate="3", acquirer_rate=rate, cash_rate="2", currency="USD")])
    originals = {"OLD": prices(archive, dates=(DATES[0],)), "NEW": prices(archive, "NEW", close="18", dates=(DATES[1],))}
    first, second = valuation(archive, bundle("1"), originals), valuation(archive, bundle("2"), originals)
    assert number(first["covered_exit_value"]) == 8
    assert number(second["covered_exit_value"]) == 14
    assert number(first["remaining_security_legs"]["NEW"]) == Fraction(1, 3)


def test_missing_successor_original_is_unavailable(archive):
    actions = action_set(archive, "stock_mergers", [record(acquiree_symbol="OLD", acquirer_symbol="NEW", effective_date="2026-01-15", acquiree_rate="2", acquirer_rate="1")])
    with pytest.raises(PointInTimeDataError, match="successor"):
        valuation(archive, actions, {"OLD": prices(archive)})


def test_spinoff_preserves_parent_and_successor(archive):
    actions = action_set(archive, "spin_offs", [record(source_symbol="OLD", new_symbol="NEW", source_rate="2", new_rate="1", ex_date="2026-01-15")])
    value = valuation(archive, actions, {"OLD": prices(archive, close="12"), "NEW": prices(archive, "NEW", close="6", dates=(DATES[1],))})
    assert number(value["covered_exit_value"]) == 15
    assert set(value["remaining_security_legs"]) == {"OLD", "NEW"}


def test_cash_distribution_counted_once_and_adjusted_prices_rejected(archive):
    actions = action_set(archive, "cash_dividends", [record(symbol="OLD", ex_date="2026-01-15", rate="1", currency="USD")])
    value = valuation(archive, actions, {"OLD": prices(archive, close="12")})
    assert number(value["covered_exit_value"]) == 13
    assert number(value["cash_receivable_usd"]) == 1
    with pytest.raises(PointInTimeDataError, match="raw"):
        valuation(archive, actions, {"OLD": prices(archive, adjustment="all")})


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", True, "1e999"])
def test_malformed_exchange_ratios_do_not_produce_legs(archive, rate):
    value = action_set(archive, "stock_mergers", [record(acquiree_symbol="OLD", acquirer_symbol="NEW", effective_date="2026-01-15", acquiree_rate=rate, acquirer_rate="1")])
    with pytest.raises(PointInTimeDataError, match="terms are unavailable"):
        valuation(archive, value, {"OLD": prices(archive)})


def test_continuation_chain_is_exact_and_incomplete_status_retained(archive):
    first = original(archive, {"corporate_actions": {}, "next_page_token": "next"}, ACTION_URI)
    second = original(archive, {"corporate_actions": {}, "next_page_token": None}, ACTION_URI + "&page_token=next")
    partial = replay_alpaca_action_pages(archive=archive, raw_artifact_ids=(first,))
    assert partial["returned_processing_scope_status"] == "incomplete"
    full = replay_alpaca_action_pages(archive=archive, raw_artifact_ids=(first, second))
    assert full["returned_processing_scope_status"] == "complete"
    with pytest.raises(PointInTimeDataError, match="continuation"):
        replay_alpaca_action_pages(archive=archive, raw_artifact_ids=(second, first))


def test_name_change_does_not_terminate_identity_or_invent_effective_date(archive):
    value = action_set(archive, "name_changes", [record(old_symbol="OLD", new_symbol="NEW")])
    terms = value["actions"][0]["normalized_terms"]
    assert terms["kind"] == "alias_change" and terms["effective_date"] is None
    with pytest.raises(PointInTimeDataError, match="effective"):
        valuation(archive, value, {"OLD": prices(archive)})


def test_duplicate_distribution_identity_is_rejected(archive):
    row = record(symbol="OLD", ex_date="2026-01-15", rate="1", currency="USD")
    with pytest.raises(PointInTimeDataError, match="duplicate"):
        action_set(archive, "cash_dividends", [row, row])


def test_entry_ex_date_is_not_applied_again(archive):
    value = valuation(archive, action_set(archive, "cash_dividends", [record(symbol="OLD", ex_date=DATES[0], rate="1", currency="USD")]), {"OLD": prices(archive, close="12")})
    assert number(value["covered_exit_value"]) == 12
    assert value["applied_source_action_ids"] == []


@pytest.mark.parametrize("reverse_ids", [False, True])
def test_terminal_event_cannot_hide_same_session_distribution_order(archive, reverse_ids):
    first, second = ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")
    if reverse_ids:
        first, second = second, first
    payload = {"corporate_actions": {
        "cash_mergers": [record(id=first, acquiree_symbol="OLD", effective_date="2026-01-15", rate="13", currency="USD")],
        "cash_dividends": [record(id=second, symbol="OLD", ex_date="2026-01-15", rate="1", currency="USD")],
    }, "next_page_token": None}
    identifier = original(archive, payload, ACTION_URI)
    actions = replay_alpaca_action_pages(archive=archive, raw_artifact_ids=(identifier,))
    with pytest.raises(PointInTimeDataError, match="same-session"):
        valuation(archive, actions, {"OLD": prices(archive, dates=(DATES[0],))})


def test_new_successor_distribution_on_transition_session_has_no_invented_order(archive):
    payload = {"corporate_actions": {
        "stock_mergers": [record(id="00000000-0000-0000-0000-000000000002", acquiree_symbol="OLD", acquirer_symbol="NEW", effective_date="2026-01-15", acquiree_rate="1", acquirer_rate="1")],
        "cash_dividends": [record(id="00000000-0000-0000-0000-000000000001", symbol="NEW", ex_date="2026-01-15", rate="1", currency="USD")],
    }, "next_page_token": None}
    identifier = original(archive, payload, ACTION_URI)
    actions = replay_alpaca_action_pages(archive=archive, raw_artifact_ids=(identifier,))
    with pytest.raises(PointInTimeDataError, match="same-session"):
        valuation(archive, actions, {"OLD": prices(archive), "NEW": prices(archive, "NEW")})


def test_serialized_valuation_cannot_substitute_amount_or_privileges(archive):
    value = valuation(archive, action_set(archive), {"OLD": prices(archive, dates=(DATES[0],))})
    for field, replacement in [("covered_exit_value", {"numerator": "999", "denominator": "1"}), ("gross_return", "99"), ("can_submit_orders", True)]:
        changed = copy.deepcopy(value)
        changed[field] = replacement
        with pytest.raises(PointInTimeDataError, match="replay"):
            verify_covered_action_valuation(archive=archive, value=changed)


def test_new_custody_check_rejects_unbound_legacy_actions(archive, tmp_path):
    from tests.test_economic_execution_outcomes import _build
    from tradingagents.dataflows.pit.records import CorporateAction

    action = CorporateAction(security_id="security-t000", action_type="dividend", effective_date="2026-01-15", terms={"amount_per_share": "1"}, source_artifact_id="raw-fake-action", source_artifact_sha256="a" * 64)
    execution, _security, _calendar, _window = _build(tmp_path, actions=(action,))
    with pytest.raises(PointInTimeDataError, match="original term bindings"):
        verify_execution_action_originals(archive=archive, execution=execution)


def test_new_custody_check_reopens_bound_legacy_dividend(archive, tmp_path):
    from tests.test_economic_execution_outcomes import _build
    from tradingagents.dataflows.pit.records import CorporateAction

    receipt = action_set(archive, "cash_dividends", [record(symbol="T000", ex_date="2026-01-15", rate="1", currency="USD")])
    source = receipt["actions"][0]
    action = CorporateAction(security_id="security-t000", action_type="dividend", effective_date="2026-01-15",
                             terms={"original_action_set": receipt, "source_action_id": source["source_action_id"]},
                             source_artifact_id=source["raw_artifact_id"], source_artifact_sha256=source["raw_artifact_sha256"])
    execution, _security, _calendar, _window = _build(tmp_path, actions=(action,))
    proof = verify_execution_action_originals(archive=archive, execution=execution)
    assert proof["verified_source_action_ids"] == [source["source_action_id"]]
    assert proof["absence_of_events_proven"] is False
    (archive.root / "objects" / f"{source['raw_artifact_id']}.raw").write_bytes(b'{}')
    with pytest.raises(PointInTimeDataError):
        verify_execution_action_originals(archive=archive, execution=execution)
