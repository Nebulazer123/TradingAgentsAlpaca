"""Shared source-bound tournament receipt fixture builders."""

from __future__ import annotations

import datetime as dt
import json
from collections import OrderedDict
from pathlib import Path

from tradingagents.dataflows.pit import (
    PointInTimeObservation,
    RawPointInTimeArtifactArchive,
    SecurityIdentity,
    build_source_bound_adjusted_price_window,
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


def _security_fields(symbol: str) -> dict[str, object]:
    return {
        "schema_version": "security_identity/v1",
        "security_id": f"security-{symbol.lower()}",
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
    available_at: str,
) -> tuple[SecurityIdentity, PointInTimeObservation]:
    source_value = _security_fields(symbol)
    clock_value[0] = dt.datetime.fromisoformat(available_at)
    artifact = archive.admit(
        raw_bytes=_canonical_bytes({"value": source_value}),
        source_uri=f"https://example.invalid/security-master/{symbol}.json",
        content_type="application/json",
        retrieved_at=available_at,
    )
    security = SecurityIdentity(
        security_id=f"security-{symbol.lower()}",
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
) -> tuple[dict[str, object], SecurityIdentity]:
    security, security_observation = _security(
        archive,
        clock_value,
        symbol=event.symbol,
        available_at=event.available_at,
    )
    candidate = {
        "symbol": event.symbol,
        "available_at": event.available_at,
        "close_t_21": "110" if event.symbol == "T000" else None,
        "close_t_252": None,
        "trailing_operating_income": None,
        "average_total_assets": None,
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
    if event.symbol == "T000":
        field_sources.append(
            {
                "field": "close_t_21",
                "value": "110",
                "observation": _observation(
                    artifact=artifact,
                    security=security,
                    observed_value="110",
                    available_at=event.available_at,
                    source_kind="economic_candidate_json",
                    value_path=["value", "close_t_21"],
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


def _next_weekdays(market_date: str) -> tuple[str, str]:
    day = dt.date.fromisoformat(market_date)
    dates: list[str] = []
    while len(dates) < 2:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            dates.append(day.isoformat())
    return dates[0], dates[1]


def _outcome_window(
    archive: RawPointInTimeArtifactArchive,
    clock_value: list[dt.datetime],
    *,
    security: SecurityIdentity,
    market_date: str,
) -> dict[str, object]:
    start, end = _next_weekdays(market_date)
    retrieved_at = f"{end}T20:00:00+00:00"
    clock_value[0] = dt.datetime.fromisoformat(retrieved_at)
    raw_bytes = _canonical_bytes(
        {
            "bars": {
                security.symbol: [
                    {"t": f"{start}T05:00:00Z", "c": "10"},
                    {"t": f"{end}T05:00:00Z", "c": "11"},
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
    ).to_dict()


def build_tournament_receipt(
    root: Path,
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
) -> tuple[SourceBoundTournamentInput, RawPointInTimeArtifactArchive]:
    """Build a complete receipt while preserving the pre/post outcome boundary."""

    clock_value = [dt.datetime(2026, 1, 1, tzinfo=dt.UTC)]
    archive = RawPointInTimeArtifactArchive(root, clock=lambda: clock_value[0])
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
            )
            candidates.append(candidate)
            identities[security.symbol] = security
        first_event = date_events[0]
        spy, spy_security_observation = _security(
            archive,
            clock_value,
            symbol="SPY",
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
    outcome_inputs = []
    for market_date in grouped:
        identities = identities_by_date[market_date]
        outcome_inputs.append(
            {
                "market_date": market_date,
                "outcomes": [
                    {
                        "symbol": symbol,
                        "return": "0.1",
                        "price_window": _outcome_window(
                            archive,
                            clock_value,
                            security=identities[symbol],
                            market_date=market_date,
                        ),
                    }
                    for symbol in sorted((*protocol.primary_universe, "SPY"))
                ],
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
