"""Source-bound next-open and five-session economic outcomes."""

from __future__ import annotations

import hashlib
import json

import pytest

from tradingagents.dataflows.pit import (
    CorporateAction,
    ExecutionPriceTwin,
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    SecurityIdentity,
    TerminalProceeds,
    build_market_session_calendar,
    build_source_bound_adjusted_price_window,
    build_source_bound_execution_outcome,
    resolve_market_session_open,
    validate_source_bound_execution_outcome,
)

MARKET_DATES = (
    "2026-01-09",
    "2026-01-12",
    "2026-01-13",
    "2026-01-14",
    "2026-01-15",
    "2026-01-16",
    "2026-01-20",
)


def _receipts(tmp_path):
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit")
    calendar_artifact = archive.admit(
        raw_bytes=json.dumps(
            [
                {"date": item, "open": "09:30", "close": "16:00"}
                for item in MARKET_DATES
            ]
        ).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-01-20T21:00:00+00:00",
    )
    calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=calendar_artifact,
    )
    price_artifact = archive.admit(
        raw_bytes=json.dumps(
            {
                "bars": {
                    "T000": [
                        {"t": f"{market_date}T05:00:00Z", "c": str(11 + index)}
                        for index, market_date in enumerate(MARKET_DATES[1:6])
                    ]
                }
            }
        ).encode(),
        source_uri=(
            "https://data.alpaca.markets/v2/stocks/T000/bars?"
            "timeframe=1Day&feed=iex&adjustment=all&"
            "start=2026-01-12T00:00:00Z&end=2026-01-17T00:00:00Z"
        ),
        content_type="application/json",
        retrieved_at="2026-01-20T21:00:00+00:00",
    )
    window = build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=price_artifact,
        security_id="security-t000",
        symbol="T000",
        requested_start="2026-01-12",
        requested_end="2026-01-16",
        decision_cutoff="2026-01-20T21:00:00+00:00",
    )
    return calendar, window


def _security(
    *, effective_to: str | None = None, terminal_artifact_id: str | None = None
) -> SecurityIdentity:
    return SecurityIdentity(
        security_id="security-t000",
        symbol="T000",
        cik="0000000001",
        figi=None,
        exchange="XNYS",
        security_type="common_stock",
        effective_from="2020-01-01",
        effective_to=effective_to,
        status="active" if effective_to is None else "delisted",
        successor_security_id=None,
        terminal_proceeds_artifact_id=terminal_artifact_id,
        source_hashes={"security_master": hashlib.sha256(b"security").hexdigest()},
    )


def _twins(*, security_id: str = "security-t000", next_open: bool = True):
    digest = hashlib.sha256(b"next-open").hexdigest()
    return (
        ExecutionPriceTwin(
            price_basis="mid_price",
            status="unavailable",
            security_id=security_id,
            session_date="2026-01-12",
            observed_at=None,
            price=None,
            adjustment_status=None,
            source_artifact_id=None,
            source_artifact_sha256=None,
            unavailable_reason="source_not_retained",
        ),
        ExecutionPriceTwin(
            price_basis="next_open",
            status="available" if next_open else "unavailable",
            security_id=security_id,
            session_date="2026-01-12",
            observed_at="2026-01-12T14:30:00+00:00" if next_open else None,
            price="10" if next_open else None,
            adjustment_status="total_return_adjusted" if next_open else None,
            source_artifact_id="raw-next-open" if next_open else None,
            source_artifact_sha256=digest if next_open else None,
            unavailable_reason=None if next_open else "source_not_retained",
        ),
        ExecutionPriceTwin(
            price_basis="executable_quote",
            status="unavailable",
            security_id=security_id,
            session_date="2026-01-12",
            observed_at=None,
            price=None,
            adjustment_status=None,
            source_artifact_id=None,
            source_artifact_sha256=None,
            unavailable_reason="source_not_retained",
        ),
        ExecutionPriceTwin(
            price_basis="observed_paper_fill",
            status="unavailable",
            security_id=security_id,
            session_date="2026-01-12",
            observed_at=None,
            price=None,
            adjustment_status=None,
            source_artifact_id=None,
            source_artifact_sha256=None,
            unavailable_reason="source_not_retained",
        ),
    )


def _build(tmp_path, *, actions=(), proceeds=None, next_open=True):
    calendar, window = _receipts(tmp_path)
    terminal = next(
        (
            action
            for action in actions
            if action.action_type in {"merger", "acquisition", "delisting"}
        ),
        None,
    )
    security = _security(
        effective_to=None if terminal is None else terminal.effective_date,
        terminal_artifact_id=(
            None if terminal is None else "raw-terminal-proceeds"
        ),
    )
    official_open = resolve_market_session_open(
        archive=RawPointInTimeArtifactArchive(tmp_path / "pit"),
        market_calendar=calendar,
        session_date=window.entry_date,
    )
    outcome = build_source_bound_execution_outcome(
        decision_event_id="decision-event-" + "a" * 64,
        decision_market_date="2026-01-09",
        decision_cutoff="2026-01-09T20:55:00+00:00",
        security=security,
        market_calendar=calendar,
        adjusted_price_window=window,
        entry_session_open_at=official_open,
        corporate_actions=actions,
        terminal_proceeds=proceeds,
        price_twins=_twins(next_open=next_open),
    )
    return outcome, security, calendar, window


def test_execution_outcome_binds_next_open_five_sessions_and_explicit_twins(tmp_path):
    dividend = CorporateAction(
        security_id="security-t000",
        action_type="dividend",
        effective_date="2026-01-14",
        terms={"amount_per_share": "0.25", "currency": "USD"},
        source_artifact_id="raw-dividend",
        source_artifact_sha256=hashlib.sha256(b"dividend").hexdigest(),
    )
    outcome, security, calendar, window = _build(
        tmp_path,
        actions=(dividend,),
    )

    assert outcome.entry_session_date == "2026-01-12"
    assert outcome.exit_session_date == "2026-01-16"
    assert outcome.holding_session_dates == MARKET_DATES[1:6]
    assert outcome.security_id == security.security_id
    assert outcome.status == "completed"
    assert outcome.gross_return == "0.5"
    assert outcome.price_for("mid_price") is None
    assert outcome.price_for("next_open") == "10"
    rebuilt = validate_source_bound_execution_outcome(
        outcome.to_dict(),
        security=security,
        market_calendar=calendar,
        adjusted_price_window=window,
    )
    assert rebuilt.canonical_json_bytes() == outcome.canonical_json_bytes()


def test_terminal_action_without_verified_proceeds_is_unavailable_not_guessed(tmp_path):
    acquisition = CorporateAction(
        security_id="security-t000",
        action_type="acquisition",
        effective_date="2026-01-15",
        terms={"consideration": "cash"},
        source_artifact_id="raw-acquisition",
        source_artifact_sha256=hashlib.sha256(b"acquisition").hexdigest(),
    )
    outcome, *_ = _build(tmp_path / "missing", actions=(acquisition,))
    assert outcome.status == "unavailable"
    assert outcome.unavailable_reason == "required_terminal_proceeds_unproven"
    assert outcome.exit_value is None
    assert outcome.gross_return is None

    proceeds = TerminalProceeds(
        security_id="security-t000",
        effective_date="2026-01-15",
        amount_per_share="14",
        currency="USD",
        source_artifact_id="raw-terminal-proceeds",
        source_artifact_sha256=hashlib.sha256(b"terminal").hexdigest(),
    )
    proven, *_ = _build(
        tmp_path / "proven",
        actions=(acquisition,),
        proceeds=proceeds,
    )
    assert proven.status == "completed"
    assert proven.exit_value == "14"
    assert proven.gross_return == "0.4"

    with pytest.raises(PointInTimeDataError):
        _build(
            tmp_path / "alias",
            actions=(acquisition,),
            proceeds=proceeds,
        )[0].price_for("unknown")


def test_missing_next_open_completes_as_unavailable_and_open_must_match(tmp_path):
    outcome, *_ = _build(tmp_path / "missing-open", next_open=False)
    assert outcome.status == "unavailable"
    assert outcome.unavailable_reason == "required_next_open_unproven"
    assert outcome.exit_value is None
    assert outcome.gross_return is None

    calendar, window = _receipts(tmp_path / "wrong-open")
    with pytest.raises(PointInTimeDataError, match="official session open"):
        build_source_bound_execution_outcome(
            decision_event_id="decision-event-" + "a" * 64,
            decision_market_date="2026-01-09",
            decision_cutoff="2026-01-09T20:55:00+00:00",
            security=_security(),
            market_calendar=calendar,
            adjusted_price_window=window,
            entry_session_open_at="2026-01-12T14:31:00+00:00",
            corporate_actions=(),
            terminal_proceeds=None,
            price_twins=_twins(),
        )
