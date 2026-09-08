"""Shared source-bound tournament receipt fixture builders."""

from __future__ import annotations

import datetime as dt
import json
from collections import OrderedDict
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from tradingagents.dataflows.pit import (
    ExecutionPriceTwin,
    PointInTimeObservation,
    RawPointInTimeArtifactArchive,
    SecurityIdentity,
    SourceBoundAdjustedPriceWindow,
    build_market_session_calendar,
    build_source_bound_adjusted_price_window,
    build_source_bound_execution_outcome,
    resolve_market_session_open,
)
from tradingagents.evals.economic_evaluation_partition_binding import (
    ValidationPhaseEligibility,
)
from tradingagents.evals.economic_evaluation_protocol import FrozenEvaluationProtocol
from tradingagents.evals.economic_tournament_evidence import (
    SourceBoundTournamentInput,
    build_source_bound_tournament_features,
    build_source_bound_tournament_input,
    build_source_bound_tournament_outcomes,
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _security_fields(symbol: str, security_id: str) -> dict[str, object]:
    return {
        "schema_version": "security_identity/v1",
        "security_id": security_id,
        "symbol": symbol,
        "cik": None,
        "figi": None,
        "exchange": "NYSE",
        "security_type": "common_stock",
        "effective_from": "2020-01-01",
        "effective_to": None,
        "status": "active",
        "successor_security_id": None,
        "terminal_proceeds_artifact_id": None,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


def _security(
    archive: RawPointInTimeArtifactArchive,
    clock_value: list[dt.datetime],
    *,
    symbol: str,
    security_id: str,
    available_at: str,
) -> tuple[SecurityIdentity, PointInTimeObservation]:
    source_value = _security_fields(symbol, security_id)
    clock_value[0] = dt.datetime.fromisoformat(available_at)
    artifact = archive.admit(
        raw_bytes=_canonical_bytes({"value": source_value}),
        source_uri=f"https://example.invalid/security-master/{symbol}.json",
        content_type="application/json",
        retrieved_at=available_at,
    )
    security = SecurityIdentity(
        security_id=security_id,
        symbol=symbol,
        cik=None,
        figi=None,
        exchange="NYSE",
        security_type="common_stock",
        effective_from="2020-01-01",
        effective_to=None,
        status="active",
        successor_security_id=None,
        terminal_proceeds_artifact_id=None,
        source_hashes={"security-master": artifact.raw_artifact_sha256},
    )
    return security, _observation(
        artifact=artifact,
        security=security,
        observed_value=source_value,
        available_at=available_at,
        source_kind="security_identity_json",
        value_path=["value"],
    )


def _observation(
    *,
    artifact,
    security: SecurityIdentity,
    observed_value: object,
    available_at: str,
    source_kind: str,
    value_path: list[str],
) -> PointInTimeObservation:
    availability = dt.datetime.fromisoformat(available_at)
    publication = availability - dt.timedelta(hours=1)
    event_time = publication - dt.timedelta(hours=1)
    return PointInTimeObservation(
        security_id=security.security_id,
        identity_effective_from=security.effective_from,
        identity_effective_to=security.effective_to,
        event_time=event_time.isoformat(timespec="seconds"),
        publication_time=publication.isoformat(timespec="seconds"),
        availability_time=available_at,
        retrieval_time=artifact.archive_recorded_at,
        raw_artifact_id=artifact.raw_artifact_id,
        raw_artifact_sha256=artifact.raw_artifact_sha256,
        observed_value=observed_value,
        market_data_feed=None,
        adjustment_mode=None,
        market_session=None,
        session_date=None,
        adjustment_status="unadjusted",
        source_span={
            "source_kind": source_kind,
            "span_type": "json_paths",
            "source_sha256": artifact.raw_artifact_sha256,
            "paths": {"observed_value": value_path},
        },
    )


def _candidate_row(
    archive: RawPointInTimeArtifactArchive,
    clock_value: list[dt.datetime],
    *,
    event,
    security_id: str,
    momentum_selected: frozenset[str] | None = None,
) -> tuple[dict[str, object], SecurityIdentity]:
    security, security_observation = _security(
        archive,
        clock_value,
        symbol=event.symbol,
        security_id=security_id,
        available_at=event.available_at,
    )
    selected = momentum_selected is not None and event.symbol in momentum_selected
    default_anchor = momentum_selected is None and event.symbol == "T000"
    candidate = {
        "symbol": event.symbol,
        "available_at": event.available_at,
        "close_t_21": "110" if selected or default_anchor else None,
        "close_t_252": "100" if selected else None,
        "trailing_operating_income": "10" if selected else None,
        "average_total_assets": "100" if selected else None,
        "pullback_features": None,
    }
    clock_value[0] = dt.datetime.fromisoformat(event.available_at)
    artifact = archive.admit(
        raw_bytes=_canonical_bytes({"value": candidate}),
        source_uri=f"https://example.invalid/economic-candidate/{event.symbol}.json",
        content_type="application/json",
        retrieved_at=event.available_at,
    )
    candidate_observation = _observation(
        artifact=artifact,
        security=security,
        observed_value=candidate,
        available_at=event.available_at,
        source_kind="economic_candidate_json",
        value_path=["value"],
    )
    field_sources = []
    source_values = (
        (
            ("close_t_21", "110"),
            ("close_t_252", "100"),
            ("trailing_operating_income", "10"),
            ("average_total_assets", "100"),
        )
        if selected
        else (("close_t_21", "110"),)
        if default_anchor
        else ()
    )
    if source_values:
        for field, value in sorted(
            source_values
        ):
            field_sources.append(
            {
                "field": field,
                "value": value,
                "observation": _observation(
                    artifact=artifact,
                    security=security,
                    observed_value=value,
                    available_at=event.available_at,
                    source_kind="economic_candidate_json",
                    value_path=["value", field],
                ).to_dict(),
            }
        )
    return (
        {
            "decision_event_id": event.decision_event_id,
            "candidate": candidate,
            "security": security.to_dict(),
            "security_observation": security_observation.to_dict(),
            "candidate_observation": candidate_observation.to_dict(),
            "field_sources": field_sources,
        },
        security,
    )


def _next_weekdays(market_date: str, count: int = 5) -> tuple[str, ...]:
    day = dt.date.fromisoformat(market_date)
    dates: list[str] = []
    while len(dates) < count:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            dates.append(day.isoformat())
    return tuple(dates)


def _outcome_window(
    archive: RawPointInTimeArtifactArchive,
    clock_value: list[dt.datetime],
    *,
    security: SecurityIdentity,
    market_date: str,
    gross_return: str | None = None,
) -> SourceBoundAdjustedPriceWindow:
    session_dates = _next_weekdays(market_date)
    start, end = session_dates[0], session_dates[-1]
    retrieved_at = f"{end}T20:00:00+00:00"
    clock_value[0] = dt.datetime.fromisoformat(retrieved_at)
    raw_bytes = _canonical_bytes(
        {
            "bars": {
                security.symbol: [
                    {
                        "t": f"{session_date}T05:00:00Z",
                        "c": (
                            str(Decimal("10") * (Decimal("1") + Decimal(gross_return)))
                            if gross_return is not None and index == len(session_dates) - 1
                            else str(11 + index)
                        ),
                    }
                    for index, session_date in enumerate(session_dates)
                ]
            }
        }
    )
    artifact = archive.admit(
        raw_bytes=raw_bytes,
        source_uri=(
            f"https://data.alpaca.markets/v2/stocks/{security.symbol}/bars?"
            f"timeframe=1Day&feed=iex&adjustment=all&start={start}T00:00:00Z"
            f"&end={(dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()}T00:00:00Z"
        ),
        content_type="application/json",
        retrieved_at=retrieved_at,
    )
    return build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=artifact,
        security_id=security.security_id,
        symbol=security.symbol,
        requested_start=start,
        requested_end=end,
        decision_cutoff=f"{end}T21:00:00+00:00",
    )


def build_tournament_receipt(
    root: Path,
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    security_id_overrides: Mapping[str, str] | None = None,
    unavailable_next_open: frozenset[tuple[str, str]] = frozenset(),
    gross_return_overrides: Mapping[tuple[str, str], str] | None = None,
    momentum_symbols_by_date: Mapping[str, frozenset[str]] | None = None,
) -> tuple[SourceBoundTournamentInput, RawPointInTimeArtifactArchive]:
    """Build a complete receipt while preserving the pre/post outcome boundary."""

    clock_value = [dt.datetime(2026, 1, 1, tzinfo=dt.UTC)]
    archive = RawPointInTimeArtifactArchive(root, clock=lambda: clock_value[0])
    primary_security_ids = {
        row.symbol: row.security_id
        for row in protocol.cohort.ranking[: len(protocol.primary_universe)]
    }
    overrides = dict(security_id_overrides or {})
    return_overrides = dict(gross_return_overrides or {})
    momentum_overrides = dict(momentum_symbols_by_date or {})
    events_by_id = {
        event.decision_event_id: event for event in protocol.input_manifest.events
    }
    grouped: OrderedDict[str, list[object]] = OrderedDict()
    for event_id in eligibility.event_ids:
        event = events_by_id[event_id]
        grouped.setdefault(event.market_date, []).append(event)
    feature_inputs: list[dict[str, object]] = []
    identities_by_date: dict[str, dict[str, SecurityIdentity]] = {}
    for market_date, date_events in grouped.items():
        events_for_date = {event.symbol: event for event in date_events}
        date_events = [events_for_date[symbol] for symbol in protocol.primary_universe]
        candidates: list[dict[str, object]] = []
        identities: dict[str, SecurityIdentity] = {}
        for event in date_events:
            candidate, security = _candidate_row(
                archive,
                clock_value,
                event=event,
                security_id=overrides.get(
                    event.symbol,
                    primary_security_ids[event.symbol],
                ),
                momentum_selected=momentum_overrides.get(market_date),
            )
            candidates.append(candidate)
            identities[security.symbol] = security
        first_event = date_events[0]
        spy, spy_security_observation = _security(
            archive,
            clock_value,
            symbol="SPY",
            security_id="security-spy",
            available_at=first_event.available_at,
        )
        benchmark_value = {
            "security_id": spy.security_id,
            "symbol": "SPY",
            "market_date": market_date,
        }
        clock_value[0] = dt.datetime.fromisoformat(first_event.available_at)
        benchmark_artifact = archive.admit(
            raw_bytes=_canonical_bytes({"value": benchmark_value}),
            source_uri=f"https://example.invalid/economic-benchmark/{market_date}.json",
            content_type="application/json",
            retrieved_at=first_event.available_at,
        )
        benchmark_observation = _observation(
            artifact=benchmark_artifact,
            security=spy,
            observed_value=benchmark_value,
            available_at=first_event.available_at,
            source_kind="economic_benchmark_json",
            value_path=["value"],
        )
        identities["SPY"] = spy
        identities_by_date[market_date] = identities
        feature_inputs.append(
            {
                "market_date": market_date,
                "candidates": candidates,
                "benchmark": {
                    "security": spy.to_dict(),
                    "security_observation": spy_security_observation.to_dict(),
                    "benchmark_observation": benchmark_observation.to_dict(),
                },
            }
        )
    features = build_source_bound_tournament_features(
        protocol=protocol,
        eligibility=eligibility,
        market_date_inputs=tuple(feature_inputs),
    )
    calendar_dates = tuple(
        sorted(
            {
                date
                for market_date in grouped
                for date in (market_date, *_next_weekdays(market_date))
            }
        )
    )
    clock_value[0] = dt.datetime.fromisoformat(
        f"{calendar_dates[-1]}T22:00:00+00:00"
    )
    calendar_artifact = archive.admit(
        raw_bytes=_canonical_bytes(
            [
                {"date": date, "open": "09:30", "close": "16:00"}
                for date in calendar_dates
            ]
        ),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at=clock_value[0].isoformat(timespec="seconds"),
    )
    market_calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=calendar_artifact,
    )
    outcome_inputs = []
    for market_date, date_events in grouped.items():
        identities = identities_by_date[market_date]
        events_for_date = {event.symbol: event for event in date_events}
        first_event = events_for_date[protocol.primary_universe[0]]
        date_outcomes = []
        for symbol in sorted((*protocol.primary_universe, "SPY")):
            security = identities[symbol]
            window = _outcome_window(
                archive,
                clock_value,
                security=security,
                market_date=market_date,
                gross_return=return_overrides.get((market_date, symbol)),
            )
            official_open = resolve_market_session_open(
                archive=archive,
                market_calendar=market_calendar,
                session_date=window.entry_date,
            )
            twins = (
                ExecutionPriceTwin(
                    price_basis="mid_price",
                    status="unavailable",
                    security_id=security.security_id,
                    session_date=window.entry_date,
                    observed_at=None,
                    price=None,
                    adjustment_status=None,
                    source_artifact_id=None,
                    source_artifact_sha256=None,
                    unavailable_reason="source_not_retained",
                ),
                ExecutionPriceTwin(
                    price_basis="next_open",
                    status=(
                        "unavailable"
                        if (market_date, symbol) in unavailable_next_open
                        else "available"
                    ),
                    security_id=security.security_id,
                    session_date=window.entry_date,
                    observed_at=(
                        None
                        if (market_date, symbol) in unavailable_next_open
                        else official_open
                    ),
                    price=(
                        None
                        if (market_date, symbol) in unavailable_next_open
                        else "10"
                    ),
                    adjustment_status=(
                        None
                        if (market_date, symbol) in unavailable_next_open
                        else "total_return_adjusted"
                    ),
                    source_artifact_id=(
                        None
                        if (market_date, symbol) in unavailable_next_open
                        else window.raw_artifact_id
                    ),
                    source_artifact_sha256=(
                        None
                        if (market_date, symbol) in unavailable_next_open
                        else window.raw_artifact_sha256
                    ),
                    unavailable_reason=(
                        "source_not_retained"
                        if (market_date, symbol) in unavailable_next_open
                        else None
                    ),
                ),
                ExecutionPriceTwin(
                    price_basis="executable_quote",
                    status="unavailable",
                    security_id=security.security_id,
                    session_date=window.entry_date,
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
                    security_id=security.security_id,
                    session_date=window.entry_date,
                    observed_at=None,
                    price=None,
                    adjustment_status=None,
                    source_artifact_id=None,
                    source_artifact_sha256=None,
                    unavailable_reason="source_not_retained",
                ),
            )
            event = first_event if symbol == "SPY" else events_for_date[symbol]
            execution = build_source_bound_execution_outcome(
                decision_event_id=event.decision_event_id,
                decision_market_date=market_date,
                decision_cutoff=event.decision_at,
                security=security,
                market_calendar=market_calendar,
                adjusted_price_window=window,
                entry_session_open_at=official_open,
                corporate_actions=(),
                terminal_proceeds=None,
                price_twins=twins,
            )
            date_outcomes.append(
                {
                    "execution_outcome": execution.to_dict(),
                    "price_window": window.to_dict(),
                }
            )
        outcome_inputs.append(
            {
                "market_date": market_date,
                "market_calendar": market_calendar.to_dict(),
                "outcomes": date_outcomes,
            }
        )
    outcomes = build_source_bound_tournament_outcomes(
        protocol=protocol,
        eligibility=eligibility,
        features=features,
        market_date_inputs=tuple(outcome_inputs),
    )
    return (
        build_source_bound_tournament_input(
            protocol=protocol,
            eligibility=eligibility,
            features=features,
            outcomes=outcomes,
        ),
        archive,
    )
