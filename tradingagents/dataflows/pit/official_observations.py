"""Source-derived point-in-time SEC and Alpaca observations."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

from tradingagents.dataflows.pit.raw_artifacts import (
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
)
from tradingagents.dataflows.pit.records import (
    PointInTimeDataError,
    PointInTimeObservation,
)

__all__ = ["build_alpaca_market_observation", "build_sec_fundamental_observation"]

_SEC_HOSTS = frozenset({"data.sec.gov", "www.sec.gov"})
_ALPACA_HOSTS = frozenset({"data.alpaca.markets"})
_ALPACA_ADJUSTMENT_STATUS = {
    "raw": "unadjusted",
    "split": "split_adjusted",
    "all": "total_return_adjusted",
}


def _bytes(archive: RawPointInTimeArtifactArchive, artifact: RawPointInTimeArtifact) -> bytes:
    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    if type(artifact) is not RawPointInTimeArtifact:
        raise PointInTimeDataError("raw_artifact must be an exact raw PIT artifact")
    return archive.read_bytes(artifact)


def _json_mapping(raw_bytes: bytes, *, label: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointInTimeDataError(f"{label} source bytes are not JSON") from exc
    if not isinstance(parsed, Mapping):
        raise PointInTimeDataError(f"{label} source JSON must be an object")
    return parsed


def _timestamp(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise PointInTimeDataError(f"{label} is absent from the raw source")
    normalized = value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PointInTimeDataError(f"{label} is not a source UTC timestamp") from exc
    if parsed.tzinfo != dt.UTC or parsed.microsecond:
        raise PointInTimeDataError(f"{label} is not a source UTC timestamp")
    return parsed.isoformat(timespec="seconds")


def _whole_source_span(
    artifact: RawPointInTimeArtifact,
    raw_bytes: bytes,
    *,
    kind: str,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "source_kind": kind,
        "span_type": "byte_range",
        "start_byte": 0,
        "end_byte": len(raw_bytes),
        "source_sha256": artifact.raw_artifact_sha256,
    }
    if extra:
        result.update(extra)
    return result


def build_sec_fundamental_observation(
    *,
    security_id: str,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
) -> PointInTimeObservation:
    """Derive SEC fact times from exact archived response bytes."""

    raw_bytes = _bytes(archive, raw_artifact)
    if (
        urlsplit(raw_artifact.source_uri).hostname not in _SEC_HOSTS
        or raw_artifact.content_type != "application/json"
    ):
        raise PointInTimeDataError("raw artifact is not an SEC JSON source")
    payload = _json_mapping(raw_bytes, label="SEC")
    event_time = _timestamp(payload.get("event_time"), label="SEC event_time")
    publication_time = _timestamp(
        payload.get("publication_time"), label="SEC publication_time"
    )
    return PointInTimeObservation(
        security_id=security_id,
        event_time=event_time,
        publication_time=publication_time,
        availability_time=raw_artifact.retrieved_at,
        retrieval_time=raw_artifact.retrieved_at,
        raw_artifact_id=raw_artifact.raw_artifact_id,
        raw_artifact_sha256=raw_artifact.raw_artifact_sha256,
        adjustment_status="unadjusted",
        source_span=_whole_source_span(raw_artifact, raw_bytes, kind="sec_html_xbrl"),
    )


def build_alpaca_market_observation(
    *,
    security_id: str,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
) -> PointInTimeObservation:
    """Derive bar time and feed/adjustment facts from archived response evidence."""

    raw_bytes = _bytes(archive, raw_artifact)
    parsed_url = urlsplit(raw_artifact.source_uri)
    if (
        parsed_url.hostname not in _ALPACA_HOSTS
        or raw_artifact.content_type != "application/json"
    ):
        raise PointInTimeDataError("raw artifact is not Alpaca market-data JSON")
    query = parse_qs(parsed_url.query, keep_blank_values=True)
    feed = query.get("feed")
    adjustment = query.get("adjustment")
    if feed is None or adjustment is None or len(feed) != 1 or len(adjustment) != 1:
        raise PointInTimeDataError("Alpaca URL must bind one feed and adjustment")
    if feed[0] not in {"iex", "sip"} or adjustment[0] not in _ALPACA_ADJUSTMENT_STATUS:
        raise PointInTimeDataError("Alpaca URL has unsupported feed or adjustment")
    payload = _json_mapping(raw_bytes, label="Alpaca")
    bars = payload.get("bars")
    if type(bars) is not list or not bars or not isinstance(bars[0], Mapping):
        raise PointInTimeDataError("Alpaca source has no first bar")
    event_time = _timestamp(bars[0].get("t"), label="Alpaca bar timestamp")
    return PointInTimeObservation(
        security_id=security_id,
        event_time=event_time,
        publication_time=event_time,
        availability_time=raw_artifact.retrieved_at,
        retrieval_time=raw_artifact.retrieved_at,
        raw_artifact_id=raw_artifact.raw_artifact_id,
        raw_artifact_sha256=raw_artifact.raw_artifact_sha256,
        adjustment_status=_ALPACA_ADJUSTMENT_STATUS[adjustment[0]],
        source_span=_whole_source_span(
            raw_artifact,
            raw_bytes,
            kind="alpaca_market_data",
            extra={"feed": feed[0], "adjustment_mode": adjustment[0]},
        ),
    )
