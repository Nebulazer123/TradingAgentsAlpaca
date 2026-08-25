"""Source-bound builders for SEC fundamentals and Alpaca market observations.

These adapters perform no fetching.  Callers first archive the exact HTTPS
response bytes, then bind a bounded source span and observed availability to a
pure :class:`PointInTimeObservation` value.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from tradingagents.dataflows.pit.raw_artifacts import (
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
)
from tradingagents.dataflows.pit.records import (
    PointInTimeDataError,
    PointInTimeObservation,
)

__all__ = [
    "build_alpaca_market_observation",
    "build_sec_fundamental_observation",
]


_SEC_HOSTS = frozenset({"data.sec.gov", "www.sec.gov"})
_ALPACA_HOSTS = frozenset({"data.alpaca.markets"})
_SEC_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/xhtml+xml",
        "application/xml",
        "text/html",
        "text/xml",
    }
)
_ALPACA_CONTENT_TYPES = frozenset({"application/json", "application/x-ndjson"})
_ALPACA_ADJUSTMENT_STATUS = {
    "raw": "unadjusted",
    "split": "split_adjusted",
    "all": "total_return_adjusted",
}
_SOURCE_SPAN_FIELDS = frozenset(
    {"span_type", "start_byte", "end_byte", "source_sha256"}
)
_SEC_METADATA_FIELDS = frozenset(
    {
        "source_kind",
        "event_time",
        "publication_time",
        "availability_time",
        "source_span",
    }
)
_ALPACA_METADATA_FIELDS = _SEC_METADATA_FIELDS | {"feed", "adjustment_mode"}


def _raw_bytes(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
) -> bytes:
    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    if type(raw_artifact) is not RawPointInTimeArtifact:
        raise PointInTimeDataError("raw_artifact must be an exact raw PIT artifact")
    return archive.read_bytes(raw_artifact)


def _host(raw_artifact: RawPointInTimeArtifact, *, allowed: frozenset[str], label: str) -> None:
    hostname = urlsplit(raw_artifact.source_uri).hostname
    if hostname is None or hostname.lower() not in allowed:
        raise PointInTimeDataError(f"raw artifact is not a {label} source")


def _source_span(
    value: object,
    *,
    sealed_value: object,
    raw_artifact: RawPointInTimeArtifact,
    raw_bytes: bytes,
    source_kind: str,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_SPAN_FIELDS:
        raise PointInTimeDataError("source_span must be an exact byte-range mapping")
    if not isinstance(sealed_value, Mapping) or dict(value) != dict(sealed_value):
        raise PointInTimeDataError("source_span is not the immutable source claim")
    span_type = value["span_type"]
    start = value["start_byte"]
    end = value["end_byte"]
    digest = value["source_sha256"]
    if span_type != "byte_range":
        raise PointInTimeDataError("source_span.span_type must be byte_range")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(raw_bytes):
        raise PointInTimeDataError("source_span byte range is outside raw source bytes")
    if digest != raw_artifact.raw_artifact_sha256:
        raise PointInTimeDataError("source_span digest does not match raw source bytes")
    result: dict[str, object] = {
        "source_kind": source_kind,
        "span_type": span_type,
        "start_byte": start,
        "end_byte": end,
        "source_sha256": digest,
    }
    if extra is not None:
        result.update(extra)
    return result


def _metadata(
    raw_artifact: RawPointInTimeArtifact,
    *,
    expected_fields: frozenset[str],
    source_kind: str,
) -> Mapping[str, object]:
    metadata = raw_artifact.source_metadata
    if set(metadata) != expected_fields or metadata.get("source_kind") != source_kind:
        raise PointInTimeDataError("raw artifact source metadata is not the expected receipt")
    if not isinstance(metadata["source_span"], Mapping):
        raise PointInTimeDataError("raw artifact source span is invalid")
    return metadata


def build_sec_fundamental_observation(
    *,
    security_id: str,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
    source_span: Mapping[str, object],
) -> PointInTimeObservation:
    """Bind one SEC HTML/XBRL fact to exact archived source bytes."""

    raw_bytes = _raw_bytes(archive=archive, raw_artifact=raw_artifact)
    _host(raw_artifact, allowed=_SEC_HOSTS, label="SEC")
    if raw_artifact.content_type not in _SEC_CONTENT_TYPES:
        raise PointInTimeDataError("SEC raw artifact content type is not supported")
    metadata = _metadata(
        raw_artifact,
        expected_fields=_SEC_METADATA_FIELDS,
        source_kind="sec_html_xbrl",
    )
    return PointInTimeObservation(
        security_id=security_id,
        event_time=metadata["event_time"],  # type: ignore[arg-type]
        publication_time=metadata["publication_time"],  # type: ignore[arg-type]
        availability_time=metadata["availability_time"],  # type: ignore[arg-type]
        retrieval_time=raw_artifact.retrieved_at,
        raw_artifact_id=raw_artifact.raw_artifact_id,
        raw_artifact_sha256=raw_artifact.raw_artifact_sha256,
        adjustment_status="unadjusted",
        source_span=_source_span(
            source_span,
            sealed_value=metadata["source_span"],
            raw_artifact=raw_artifact,
            raw_bytes=raw_bytes,
            source_kind="sec_html_xbrl",
        ),
    )


def build_alpaca_market_observation(
    *,
    security_id: str,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
    source_span: Mapping[str, object],
) -> PointInTimeObservation:
    """Bind market bars to the exact recorded Alpaca feed and adjustment mode."""

    raw_bytes = _raw_bytes(archive=archive, raw_artifact=raw_artifact)
    _host(raw_artifact, allowed=_ALPACA_HOSTS, label="Alpaca market-data")
    if raw_artifact.content_type not in _ALPACA_CONTENT_TYPES:
        raise PointInTimeDataError("Alpaca raw artifact content type is not supported")
    metadata = _metadata(
        raw_artifact,
        expected_fields=_ALPACA_METADATA_FIELDS,
        source_kind="alpaca_market_data",
    )
    feed = metadata["feed"]
    adjustment_mode = metadata["adjustment_mode"]
    if feed not in {"iex", "sip"}:
        raise PointInTimeDataError("Alpaca market-data feed must be iex or sip")
    if adjustment_mode not in _ALPACA_ADJUSTMENT_STATUS:
        raise PointInTimeDataError("Alpaca adjustment mode is not supported")
    return PointInTimeObservation(
        security_id=security_id,
        event_time=metadata["event_time"],  # type: ignore[arg-type]
        publication_time=metadata["publication_time"],  # type: ignore[arg-type]
        availability_time=metadata["availability_time"],  # type: ignore[arg-type]
        retrieval_time=raw_artifact.retrieved_at,
        raw_artifact_id=raw_artifact.raw_artifact_id,
        raw_artifact_sha256=raw_artifact.raw_artifact_sha256,
        adjustment_status=_ALPACA_ADJUSTMENT_STATUS[adjustment_mode],
        source_span=_source_span(
            source_span,
            sealed_value=metadata["source_span"],
            raw_artifact=raw_artifact,
            raw_bytes=raw_bytes,
            source_kind="alpaca_market_data",
            extra={"feed": feed, "adjustment_mode": adjustment_mode},
        ),
    )
