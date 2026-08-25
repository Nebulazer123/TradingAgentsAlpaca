"""Resolution-quality bridge for immutable point-in-time price receipts.

This module deliberately supplies no price downloader and has no fallback
route.  It converts an already archived, total-return-adjusted Alpaca receipt
into the existing resolution-quality ``PriceWindow`` only after rebuilding it
from the exact raw source bytes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifact,
    RawPointInTimeArtifactArchive,
    SourceBoundAdjustedPriceWindow,
    validate_raw_point_in_time_artifact,
    validate_source_bound_adjusted_price_window,
    verify_source_bound_adjusted_price_window,
)
from tradingagents.evals.resolution_quality import PriceWindow

__all__ = [
    "SourceBoundWindowLookup",
    "build_source_bound_window_lookup",
    "load_source_bound_window_lookup",
    "source_bound_price_window",
]


def _receipt_evidence(receipt: SourceBoundAdjustedPriceWindow) -> dict[str, str]:
    return {
        "schema_version": "source_bound_price_window_evidence/v1",
        "window_id": receipt.window_id,
        "window_sha256": receipt.window_sha256,
        "security_id": receipt.security_id,
        "raw_artifact_id": receipt.raw_artifact_id,
        "raw_artifact_sha256": receipt.raw_artifact_sha256,
        "decision_cutoff": receipt.decision_cutoff,
        "retrieved_at": receipt.retrieved_at,
        "feed": receipt.feed,
        "adjustment_mode": receipt.adjustment_mode,
        "adjustment_status": receipt.adjustment_status,
    }


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
        source_evidence=_receipt_evidence(verified),
    )


class SourceBoundWindowLookup:
    """Callable receipt index that re-verifies both legs at learning admission."""

    def __init__(
        self,
        *,
        archive: RawPointInTimeArtifactArchive,
        artifacts: Mapping[str, RawPointInTimeArtifact],
        receipts: Mapping[tuple[str, str, str], SourceBoundAdjustedPriceWindow],
    ) -> None:
        self._archive = archive
        self._artifacts = dict(artifacts)
        self._receipts = dict(receipts)

    def __call__(
        self,
        symbol: str,
        requested_start: str,
        requested_end: str,
    ) -> PriceWindow | None:
        receipt = self._receipts.get((symbol, requested_start, requested_end))
        if receipt is None:
            return None
        raw_artifact = self._artifacts[receipt.raw_artifact_id]
        return source_bound_price_window(
            archive=self._archive,
            raw_artifact=raw_artifact,
            receipt=receipt,
        )

    def verify_forecast(self, forecast: object) -> bool:
        """Rebuild the two retained receipt legs named by a resolved forecast."""

        ticker = getattr(forecast, "ticker", None)
        benchmark = getattr(forecast, "benchmark", None)
        window = getattr(forecast, "resolution_window", None)
        evidence = getattr(forecast, "resolution_evidence", None)
        if (
            not isinstance(ticker, str)
            or not isinstance(benchmark, str)
            or not isinstance(window, Mapping)
            or not isinstance(evidence, Mapping)
            or not isinstance(window.get("intended_start"), str)
            or not isinstance(window.get("intended_end"), str)
        ):
            return False
        try:
            ticker_window = self(ticker, window["intended_start"], window["intended_end"])
            benchmark_window = self(
                benchmark,
                window["intended_start"],
                window["intended_end"],
            )
        except PointInTimeDataError:
            return False
        if ticker_window is None or benchmark_window is None:
            return False
        ticker_evidence = ticker_window.source_evidence
        benchmark_evidence = benchmark_window.source_evidence
        return evidence == {
            "schema_version": "source_bound_resolution_evidence/v1",
            "ticker": ticker_evidence,
            "benchmark": benchmark_evidence,
        }


def build_source_bound_window_lookup(
    *,
    archive: RawPointInTimeArtifactArchive,
    raw_artifacts: Mapping[str, RawPointInTimeArtifact],
    receipts: Sequence[SourceBoundAdjustedPriceWindow],
) -> SourceBoundWindowLookup:
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

    return SourceBoundWindowLookup(
        archive=archive,
        artifacts=artifacts,
        receipts=indexed,
    )


def _receipt_payload(path_value: str | Path, *, label: str) -> Mapping[str, object]:
    path = Path(path_value)
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointInTimeDataError(f"{label} cannot be read as JSON") from exc
    if not isinstance(payload, Mapping):
        raise PointInTimeDataError(f"{label} must contain a JSON object")
    return payload


def load_source_bound_window_lookup(
    *,
    raw_artifact_archive: str | Path,
    raw_artifact_receipts: Sequence[str | Path],
    price_window_receipts: Sequence[str | Path],
) -> SourceBoundWindowLookup:
    """Load an explicit no-fallback lookup from canonical local receipts."""

    if not isinstance(raw_artifact_receipts, Sequence) or isinstance(
        raw_artifact_receipts, (bytes, str)
    ):
        raise PointInTimeDataError("raw_artifact_receipts must be a receipt-path sequence")
    if not isinstance(price_window_receipts, Sequence) or isinstance(
        price_window_receipts, (bytes, str)
    ):
        raise PointInTimeDataError("price_window_receipts must be a receipt-path sequence")
    archive = RawPointInTimeArtifactArchive(raw_artifact_archive)
    artifacts: dict[str, RawPointInTimeArtifact] = {}
    for receipt_path in raw_artifact_receipts:
        artifact = validate_raw_point_in_time_artifact(
            _receipt_payload(receipt_path, label="raw artifact receipt")
        )
        if artifact.raw_artifact_id in artifacts:
            raise PointInTimeDataError("raw artifact receipt is duplicated")
        artifacts[artifact.raw_artifact_id] = artifact
    receipts: list[SourceBoundAdjustedPriceWindow] = []
    for receipt_path in price_window_receipts:
        receipts.append(
            validate_source_bound_adjusted_price_window(
                _receipt_payload(receipt_path, label="price window receipt")
            )
        )
    return build_source_bound_window_lookup(
        archive=archive,
        raw_artifacts=artifacts,
        receipts=tuple(receipts),
    )
