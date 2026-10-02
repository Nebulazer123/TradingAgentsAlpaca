"""Replay Alpaca action terms and raw-price consideration from whole originals.

Returned processing-date pages prove their request scope only. They cannot prove
that every effective event existed in the response. Valuation here is therefore
conditional on the explicitly covered actions and never an admitted outcome.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from fractions import Fraction
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from tradingagents.dataflows.pit.raw_artifacts import RawPointInTimeArtifactArchive
from tradingagents.dataflows.pit.records import PointInTimeDataError
from tradingagents.dataflows.pit.security_master import _json, _plain

PARSER_VERSION = "alpaca_action_originals/v1"
_AUTHORITY = {"analysis_only": True, "execution_authority": "none", "can_submit_orders": False}
_GROUPS = {
    "cash_mergers", "stock_mergers", "stock_and_cash_mergers", "spin_offs",
    "forward_splits", "reverse_splits", "cash_dividends", "stock_dividends",
    "name_changes", "reorganizations", "redemptions",
}
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,19}")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _seal(material: dict, name: str) -> dict:
    digest = hashlib.sha256(_canonical(material)).hexdigest()
    return {**material, f"{name}_id": f"{name.replace('_', '-')}-{digest}", f"{name}_sha256": digest}


def _date(value: object) -> str:
    if type(value) is not str:
        raise PointInTimeDataError("action date must be an ISO string")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PointInTimeDataError("invalid action date") from exc
    if parsed.isoformat() != value:
        raise PointInTimeDataError("action date must be canonical")
    return value


def _symbol(value: object) -> str:
    if type(value) is not str or _SYMBOL.fullmatch(value) is None:
        raise PointInTimeDataError("original action symbol is missing or invalid")
    return value


def _amount(value: object, *, positive: bool = False) -> Fraction:
    # Exact JSON numbers are decoded as integers/Decimals, then copied to strings.
    if type(value) not in {str, int} or isinstance(value, bool):
        raise PointInTimeDataError("action amount must be an exact source decimal")
    text = str(value)
    if len(text) > 128 or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text) is None:
        raise PointInTimeDataError("action amount must be a bounded nonnegative decimal")
    result = Fraction(text)
    if positive and result <= 0:
        raise PointInTimeDataError("action exchange ratio must be positive")
    return result


def _fraction(value: Fraction) -> dict:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _terms(group: str, row: dict) -> dict:
    """Normalize only documented fields; missing currency/effectiveness stays open."""
    effective_field = "ex_date" if group in {"spin_offs", "forward_splits", "reverse_splits", "cash_dividends", "stock_dividends"} else "effective_date"
    effective = row.get(effective_field)
    if effective is not None:
        effective = _date(effective)
    result = {"effective_date": effective, "process_date": _date(row.get("process_date")),
              "source_status": row.get("data_quality", "not_returned"), "source_symbols": [],
              "kind": "unsupported", "cash_per_source_share": None, "security_legs": [], "terms_status": "unsupported"}
    try:
        if group in {"cash_mergers", "stock_mergers", "stock_and_cash_mergers"}:
            source = _symbol(row.get("acquiree_symbol"))
            result.update(kind="termination", source_symbols=[source])
            if group in {"cash_mergers", "stock_and_cash_mergers"}:
                if row.get("currency") != "USD":
                    raise PointInTimeDataError("cash consideration currency is unknown or unsupported")
                amount = _amount(row.get("rate" if group == "cash_mergers" else "cash_rate"))
                result["cash_per_source_share"] = _fraction(amount)
            if group != "cash_mergers":
                ratio = _amount(row.get("acquirer_rate"), positive=True) / _amount(row.get("acquiree_rate"), positive=True)
                result["security_legs"] = [{"symbol": _symbol(row.get("acquirer_symbol")), "ratio": _fraction(ratio)}]
        elif group == "spin_offs":
            source = _symbol(row.get("source_symbol"))
            ratio = _amount(row.get("new_rate"), positive=True) / _amount(row.get("source_rate"), positive=True)
            result.update(kind="distribution", source_symbols=[source], security_legs=[{"symbol": _symbol(row.get("new_symbol")), "ratio": _fraction(ratio)}])
        elif group in {"forward_splits", "reverse_splits"}:
            source = _symbol(row.get("symbol"))
            ratio = _amount(row.get("new_rate"), positive=True) / _amount(row.get("old_rate"), positive=True)
            result.update(kind="split", source_symbols=[source], security_legs=[{"symbol": _symbol(row.get("new_symbol", source)), "ratio": _fraction(ratio)}])
        elif group == "cash_dividends":
            source = _symbol(row.get("symbol"))
            if row.get("currency") != "USD":
                raise PointInTimeDataError("distribution currency is unknown or unsupported")
            result.update(kind="cash_distribution", source_symbols=[source], cash_per_source_share=_fraction(_amount(row.get("rate"))))
        elif group == "stock_dividends":
            source = _symbol(row.get("symbol"))
            ratio = _amount(row.get("rate"))
            result.update(kind="distribution", source_symbols=[source], security_legs=[{"symbol": source, "ratio": _fraction(ratio)}])
        elif group == "name_changes":
            # REST only gives process_date. It is not an effective alias clock.
            result.update(kind="alias_change", source_symbols=[_symbol(row.get("old_symbol"))],
                          security_legs=[{"symbol": _symbol(row.get("new_symbol")), "ratio": _fraction(Fraction(1))}], effective_date=None)
        if effective is None or result["kind"] == "unsupported":
            result["terms_status"] = "effective_time_or_record_family_unavailable"
        else:
            result["terms_status"] = "observed_terms"
    except PointInTimeDataError as exc:
        result["terms_status"] = "missing_or_unsupported_terms"
        result["unavailable_reason"] = str(exc)
    return result


def replay_alpaca_action_pages(*, archive: RawPointInTimeArtifactArchive, raw_artifact_ids: tuple[str, ...]) -> dict:
    """Reopen all upstream pages; a terminal token proves only response scope."""
    if type(archive) is not RawPointInTimeArtifactArchive or type(raw_artifact_ids) is not tuple or not 1 <= len(raw_artifact_ids) <= 100:
        raise PointInTimeDataError("action replay requires a PIT archive and bounded original pages")
    pages, actions, seen, expected_token, scope = [], [], set(), None, None
    for index, identifier in enumerate(raw_artifact_ids):
        artifact = archive.read_artifact(identifier)
        raw = archive.read_bytes(artifact)
        url = urlsplit(artifact.source_uri)
        params = parse_qsl(url.query, keep_blank_values=True)
        query = dict(params)
        if (url.scheme != "https" or url.netloc != "data.alpaca.markets" or url.path != "/v1/corporate-actions" or artifact.content_type != "application/json"
                or len(query) != len(params) or set(query) - {"region", "data_quality", "start", "end", "page_size", "limit", "sort", "symbols", "types", "page_token"}
                or query.get("region") not in {"us", "US"} or query.get("data_quality") not in {"all", "complete"}
                or query.get("page_token") != expected_token):
            raise PointInTimeDataError("action original request or continuation differs")
        if "sort" in query and query["sort"] != "asc":
            raise PointInTimeDataError("action original sort is unsupported")
        for field in ("page_size", "limit"):
            if field in query and (re.fullmatch(r"[1-9][0-9]{0,3}", query[field]) is None or int(query[field]) > 1000):
                raise PointInTimeDataError("action original page bound is invalid")
        if "symbols" in query:
            symbols = query["symbols"].split(",")
            if len(symbols) != len(set(symbols)) or not 1 <= len(symbols) <= 1000:
                raise PointInTimeDataError("action original symbol scope is invalid")
            for symbol in symbols:
                _symbol(symbol)
        dates = (_date(query.get("start")), _date(query.get("end")))
        if dates[0] > dates[1]:
            raise PointInTimeDataError("action processing interval is reversed")
        current_scope = {key: value for key, value in query.items() if key != "page_token"}
        if scope is not None and current_scope != scope:
            raise PointInTimeDataError("action pages have different request scopes")
        scope = current_scope
        payload = _json(raw)
        if type(payload) is not dict or set(payload) != {"corporate_actions", "next_page_token"} or type(payload["corporate_actions"]) is not dict:
            raise PointInTimeDataError("action original lacks its complete response envelope")
        token = payload["next_page_token"]
        if token is not None and (type(token) is not str or not token or len(token) > 4096):
            raise PointInTimeDataError("invalid action continuation token")
        if index + 1 < len(raw_artifact_ids) and token is None:
            raise PointInTimeDataError("action pages continue after a terminal response")
        for group, rows in payload["corporate_actions"].items():
            if type(rows) is not list:
                raise PointInTimeDataError("action response group must be an array")
            for row_index, source in enumerate(rows):
                row = _plain(source)
                if type(row) is not dict or type(row.get("id")) is not str:
                    raise PointInTimeDataError("action original lacks a record identity")
                try:
                    action_id = str(UUID(row["id"]))
                except ValueError as exc:
                    raise PointInTimeDataError("invalid original action UUID") from exc
                if row["id"] != action_id or action_id in seen:
                    raise PointInTimeDataError("duplicate or noncanonical original action UUID")
                seen.add(action_id)
                if not dates[0] <= _date(row.get("process_date")) <= dates[1]:
                    raise PointInTimeDataError("action processing date is outside its request")
                terms = _terms(group, row) if group in _GROUPS else {"kind": "unsupported", "terms_status": "unsupported", "source_symbols": []}
                actions.append({"source_action_id": action_id, "record_family": group, "original_record": row,
                                "source_path": ["corporate_actions", group, row_index], "raw_artifact_id": identifier, "raw_artifact_sha256": artifact.raw_artifact_sha256, "normalized_terms": terms})
        pages.append(artifact.to_dict())
        expected_token = token
    actions.sort(key=lambda row: row["source_action_id"])
    return _seal({"schema_version": "original_corporate_action_set/v2", "parser_version": PARSER_VERSION, "processing_scope": scope,
                  "original_pages": pages, "actions": actions, "returned_processing_scope_status": "complete" if expected_token is None else "incomplete",
                  "effective_event_coverage_status": "NOT_ESTABLISHED", "absence_of_events_proven": False, **_AUTHORITY}, "action_set")


def verify_original_action_set(*, archive: RawPointInTimeArtifactArchive, value: object) -> dict:
    if type(value) is not dict or type(value.get("original_pages")) is not list:
        raise PointInTimeDataError("original action set is invalid")
    try:
        rebuilt = replay_alpaca_action_pages(archive=archive, raw_artifact_ids=tuple(page["raw_artifact_id"] for page in value["original_pages"]))
    except (KeyError, TypeError) as exc:
        raise PointInTimeDataError("original action set pages are invalid") from exc
    if _canonical(rebuilt) != _canonical(value):
        raise PointInTimeDataError("action terms or original coverage do not replay")
    return rebuilt


def _raw_daily_prices(archive, identifier: str, symbol: str, session_date: str) -> tuple[Fraction, Fraction]:
    artifact = archive.read_artifact(identifier)
    raw = archive.read_bytes(artifact)
    url = urlsplit(artifact.source_uri)
    params = parse_qsl(url.query, keep_blank_values=True)
    query = dict(params)
    if (url.scheme != "https" or url.netloc != "data.alpaca.markets" or url.path != f"/v2/stocks/{symbol}/bars" or artifact.content_type != "application/json"
            or len(query) != len(params) or set(query) - {"adjustment", "timeframe", "feed", "start", "end", "asof", "sort", "limit"}
            or query.get("adjustment") != "raw" or query.get("timeframe") != "1Day" or query.get("feed") != "sip" or query.get("sort") != "asc"):
        raise PointInTimeDataError("consideration prices must be original SIP raw daily bars")
    start, end = _date(query.get("start")), _date(query.get("end"))
    _date(query.get("asof"))
    if not start <= session_date <= end:
        raise PointInTimeDataError("consideration session is outside its request")
    captured = dt.datetime.fromisoformat(artifact.retrieved_at).astimezone(ZoneInfo("America/New_York"))
    if captured.date().isoformat() <= session_date:
        raise PointInTimeDataError("consideration daily session was not complete at capture")
    payload = _json(raw)
    if type(payload) is not dict or payload.get("symbol") != symbol or payload.get("next_page_token", "missing") is not None or type(payload.get("bars")) is not list:
        raise PointInTimeDataError("consideration price original is incomplete")
    matching, seen = [], set()
    for row in payload["bars"]:
        if type(row) is not dict or type(row.get("t")) is not str:
            raise PointInTimeDataError("invalid consideration price row")
        try:
            instant = dt.datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise PointInTimeDataError("invalid consideration bar clock") from exc
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise PointInTimeDataError("consideration bar clock lacks timezone")
        local = instant.astimezone(ZoneInfo("America/New_York"))
        date = local.date().isoformat()
        if local.time() != dt.time(0) or date in seen:
            raise PointInTimeDataError("consideration bars must be unique provider daily sessions")
        seen.add(date)
        if date == session_date:
            matching.append((_amount(_plain(row.get("o")), positive=True), _amount(_plain(row.get("c")), positive=True)))
    if len(matching) != 1:
        raise PointInTimeDataError("required consideration price session is unavailable")
    return matching[0]


def value_covered_action_legs(*, archive: RawPointInTimeArtifactArchive, action_set: object, symbol: str,
                             entry_session_date: str, exit_session_date: str, price_originals: dict[str, str]) -> dict:
    """Exact one-share holding book; unknown global coverage blocks admission."""
    replay = verify_original_action_set(archive=archive, value=action_set)
    source = _symbol(symbol)
    entry, exit_date = _date(entry_session_date), _date(exit_session_date)
    if entry > exit_date or type(price_originals) is not dict or source not in price_originals:
        raise PointInTimeDataError("holding window and original entry prices are required")
    entry_price, _ = _raw_daily_prices(archive, price_originals[source], source, entry)
    holdings, cash, applied, clocks = {source: Fraction(1)}, Fraction(0), [], set()
    records = sorted(replay["actions"], key=lambda row: (row["normalized_terms"].get("effective_date") or "", row["source_action_id"]))
    for record in records:
        terms = record["normalized_terms"]
        affected = set(terms.get("source_symbols", [])) & set(holdings)
        if not affected:
            if terms["kind"] == "unsupported":
                raise PointInTimeDataError("unsupported original record can affect holding coverage")
            continue
        effective = terms.get("effective_date")
        if effective is None:
            raise PointInTimeDataError("held symbol has no original effective event/alias clock")
        if not entry <= effective <= exit_date:
            continue
        if effective == entry:
            if terms["kind"] == "termination":
                raise PointInTimeDataError("entry-session termination order is unavailable")
            # Ex-date distributions/splits already precede a purchase at that
            # session's open. Applying them again would double count entitlement.
            continue
        if terms["terms_status"] != "observed_terms" or len(affected) != 1:
            raise PointInTimeDataError("holding consideration terms are unavailable")
        token = affected.pop()
        touched = {token, *(leg["symbol"] for leg in terms["security_legs"])}
        if any(other["source_action_id"] != record["source_action_id"]
               and other["normalized_terms"].get("effective_date") == effective
               and touched & set(other["normalized_terms"].get("source_symbols", []))
               for other in records):
            # A terminal event can remove the holding before a second event is
            # visited. Check originals first so UUID ordering cannot hide it.
            raise PointInTimeDataError("same-session action order is unavailable")
        if (effective, token) in clocks:
            raise PointInTimeDataError("same-session action order is unavailable")
        clocks.add((effective, token))
        quantity = holdings[token]
        if terms["cash_per_source_share"] is not None:
            fraction = terms["cash_per_source_share"]
            cash += quantity * Fraction(int(fraction["numerator"]), int(fraction["denominator"]))
        if terms["kind"] in {"termination", "split"}:
            del holdings[token]
        for leg in terms["security_legs"]:
            ratio = leg["ratio"]
            amount = quantity * Fraction(int(ratio["numerator"]), int(ratio["denominator"]))
            holdings[leg["symbol"]] = holdings.get(leg["symbol"], Fraction(0)) + amount
        applied.append(record["source_action_id"])
    value = cash
    for token, quantity in holdings.items():
        if token not in price_originals:
            raise PointInTimeDataError("required successor/distribution price original is unavailable")
        _, close = _raw_daily_prices(archive, price_originals[token], token, exit_date)
        value += quantity * close
    originals = {token: archive.read_artifact(identifier).to_dict() for token, identifier in sorted(price_originals.items())}
    # Terms describe receivables/obligations; they do not assert a payment or fill.
    return _seal({"schema_version": "covered_action_valuation/v2", "parser_version": PARSER_VERSION,
                  "symbol": source, "entry_session_date": entry, "exit_session_date": exit_date, "action_set": replay,
                  "price_originals": originals, "price_basis": "raw_plus_explicit_legs",
                  "entry_price_basis": "provider_daily_open_not_certified_session_open",
                  "entry_price": _fraction(entry_price), "covered_exit_value": _fraction(value),
                  "covered_return": _fraction((value - entry_price) / entry_price),
                  "cash_receivable_usd": _fraction(cash), "remaining_security_legs": {key: _fraction(item) for key, item in sorted(holdings.items())},
                  "applied_source_action_ids": applied, "alias_effective_time_gaps": [],
                  "status": "unavailable_for_economic_admission", "gross_return": None,
                  "required_gaps": ["complete_effective_event_coverage", "dated_security_alias_crosswalk", "official_session_open_price", "payment_or_delivery_outcomes_if_required"],
                  **_AUTHORITY}, "valuation")


def verify_covered_action_valuation(*, archive: RawPointInTimeArtifactArchive, value: object) -> dict:
    if type(value) is not dict:
        raise PointInTimeDataError("covered action valuation must be an object")
    try:
        rebuilt = value_covered_action_legs(archive=archive, action_set=value["action_set"], symbol=value["symbol"],
                                          entry_session_date=value["entry_session_date"], exit_session_date=value["exit_session_date"],
                                          price_originals={key: item["raw_artifact_id"] for key, item in value["price_originals"].items()})
    except (KeyError, TypeError) as exc:
        raise PointInTimeDataError("covered action valuation source bindings are invalid") from exc
    if _canonical(rebuilt) != _canonical(value):
        raise PointInTimeDataError("consideration valuation does not replay from originals")
    return rebuilt


def verify_execution_action_originals(*, archive: RawPointInTimeArtifactArchive, execution) -> dict:
    """New custody check for v1 actions, while pure historical replay stays intact.

    A v1 cash amount cannot stand in for mixed/security consideration. Empty
    action lists retain an explicit coverage gap; they never become absence proof.
    """
    from tradingagents.dataflows.pit.execution_outcomes import SourceBoundExecutionOutcome

    if type(execution) is not SourceBoundExecutionOutcome:
        raise PointInTimeDataError("action custody requires an exact execution outcome")
    verified, cash_terminal = [], None
    mapping = {"forward_splits": {"split"}, "reverse_splits": {"split"}, "cash_dividends": {"dividend"},
               "stock_dividends": {"dividend"}, "cash_mergers": {"merger", "acquisition"},
               "stock_mergers": {"merger", "acquisition"}, "stock_and_cash_mergers": {"merger", "acquisition"}}
    for action in execution.corporate_actions:
        binding = action.to_dict()["terms"]
        if type(binding) is not dict or set(binding) != {"original_action_set", "source_action_id"}:
            raise PointInTimeDataError("execution action lacks original term bindings")
        replay = verify_original_action_set(archive=archive, value=binding["original_action_set"])
        records = [row for row in replay["actions"] if row["source_action_id"] == binding["source_action_id"]]
        if len(records) != 1:
            raise PointInTimeDataError("execution original action identity is unavailable")
        record, terms = records[0], records[0]["normalized_terms"]
        if (action.source_artifact_id != record["raw_artifact_id"] or action.source_artifact_sha256 != record["raw_artifact_sha256"]
                or action.action_type not in mapping.get(record["record_family"], set()) or terms["effective_date"] != action.effective_date
                or execution.symbol not in terms["source_symbols"] or terms["terms_status"] != "observed_terms"):
            raise PointInTimeDataError("execution action terms differ from original")
        if record["record_family"] in {"stock_mergers", "stock_and_cash_mergers"}:
            raise PointInTimeDataError("v1 terminal cash cannot replace successor security legs")
        if record["record_family"] == "cash_mergers":
            if cash_terminal is not None:
                raise PointInTimeDataError("multiple terminal consideration records conflict")
            cash_terminal = record
        verified.append(record["source_action_id"])
    if execution.terminal_proceeds is not None:
        proceeds = execution.terminal_proceeds
        if cash_terminal is None or proceeds.source_artifact_id != cash_terminal["raw_artifact_id"] or proceeds.source_artifact_sha256 != cash_terminal["raw_artifact_sha256"]:
            raise PointInTimeDataError("terminal proceeds original is unavailable")
        cash = cash_terminal["normalized_terms"]["cash_per_source_share"]
        if _amount(proceeds.amount_per_share) != Fraction(int(cash["numerator"]), int(cash["denominator"])) or proceeds.currency != "USD":
            raise PointInTimeDataError("terminal proceeds differ from original cash terms")
    return {"verified_source_action_ids": verified, "effective_event_coverage_status": "NOT_ESTABLISHED", "absence_of_events_proven": False, **_AUTHORITY}
