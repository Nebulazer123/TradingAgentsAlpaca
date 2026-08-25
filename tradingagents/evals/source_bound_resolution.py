"""Resolution-quality bridge for immutable point-in-time price receipts.

This module deliberately supplies no price downloader and has no fallback
route.  It converts an already archived, total-return-adjusted Alpaca receipt
into the existing resolution-quality ``PriceWindow`` only after rebuilding it
from the exact raw source bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
    SourceBoundAdjustedPriceWindow,
    verify_source_bound_adjusted_price_window,
)
from tradingagents.evals.resolution_quality import PriceWindow, WindowLookup

__all__ = [
    "build_source_bound_window_lookup",
    "source_bound_price_window",
]


def source_bound_price_window(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifact: RawPointInTimeArtifact,
    receipt: SourceBoundAdjustedPriceWindow,
) -> PriceWindow:
    """Return a legacy-shaped window only after source-byte verification."""

    if type(receipt) is not SourceBoundAdjustedPriceWindow:
        raise PointInTimeDataError(
            "receipt must be an exact SourceBoundAdjustedPriceWindow"
        )
    verified = verify_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=raw_artifact,
        value=receipt.to_dict(),
    )
    return PriceWindow(
        symbol=verified.symbol,
        requested_start=verified.requested_start,
        requested_end=verified.requested_end,
        entry_date=verified.entry_date,
        entry_close=verified.entry_close,
        exit_date=verified.exit_date,
        exit_close=verified.exit_close,
        session_count=verified.session_count,
    )


def build_source_bound_window_lookup(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifacts: Mapping[str, RawPointInTimeArtifact],
    receipts: Sequence[SourceBoundAdjustedPriceWindow],
) -> WindowLookup:
    """Build a no-fallback lookup backed solely by re-verified PIT receipts."""

    if type(archive) is not RawPointInTimeArtifactArchive:
        raise PointInTimeDataError("archive must be an exact raw PIT artifact archive")
    if not isinstance(raw_artifacts, Mapping):
        raise PointInTimeDataError("raw_artifacts must be an artifact-ID mapping")
    if not isinstance(receipts, Sequence) or isinstance(receipts, (bytes, str)):
        raise PointInTimeDataError("receipts must be a sequence of PIT price receipts")
    artifacts: dict[str, RawPointInTimeArtifact] = {}
    for artifact_id, artifact in raw_artifacts.items():
        if (
            type(artifact_id) is not str
            or type(artifact) is not RawPointInTimeArtifact
            or artifact.raw_artifact_id != artifact_id
        ):
            raise PointInTimeDataError("raw_artifacts must be keyed by exact artifact ID")
        artifacts[artifact_id] = artifact

    indexed: dict[tuple[str, str, str], SourceBoundAdjustedPriceWindow] = {}
    for receipt in receipts:
        if type(receipt) is not SourceBoundAdjustedPriceWindow:
            raise PointInTimeDataError(
                "receipts must contain exact SourceBoundAdjustedPriceWindow values"
            )
        raw_artifact = artifacts.get(receipt.raw_artifact_id)
        if raw_artifact is None:
            raise PointInTimeDataError("price receipt names an unavailable raw artifact")
        source_bound_price_window(
            archive=archive,
            raw_artifact=raw_artifact,
            receipt=receipt,
        )
        key = (receipt.symbol, receipt.requested_start, receipt.requested_end)
        if key in indexed:
            raise PointInTimeDataError("duplicate source-bound price receipt window")
        indexed[key] = receipt

    def lookup(symbol: str, requested_start: str, requested_end: str) -> PriceWindow | None:
        receipt = indexed.get((symbol, requested_start, requested_end))
        if receipt is None:
            return None
        raw_artifact = artifacts[receipt.raw_artifact_id]
        return source_bound_price_window(
            archive=archive,
            raw_artifact=raw_artifact,
            receipt=receipt,
        )

    return lookup
