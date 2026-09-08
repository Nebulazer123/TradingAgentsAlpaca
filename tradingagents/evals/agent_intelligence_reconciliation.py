"""Read-only agent ledger reconciliation and dependence bounds.

This module derives a deterministic ``agent_intelligence_reconciliation/v2``
receipt from exactly one captured byte snapshot of the Agent Intelligence
Ledger JSONL. It never mutates the ledger, never rewrites raw forecast
history, and never replaces the derived agent score summary.

Dependence semantics (fixed for this increment):

- The packet-event key is ``(source_packet_id, normalized ticker,
  normalized benchmark, canonical JSON of resolution_window)``. Key inputs
  must be strings of non-zero length; an explicitly present JSON ``null``
  resolution window is the legitimate canonical legacy null sentinel, while
  any other window shape makes a row unclusterable. On a raw payload mapping
  an omitted ``resolution_window`` field is missing cluster material and is
  packet-event unclusterable; constructed AgentForecast objects lose field
  presence, so object-space dependence blocks count their ``None`` attribute
  as that same null sentinel. Any missing or malformed identity material
  also makes a row unclusterable; nothing is replaced with invented
  identity.
- The conservative market-event key is ``(normalized ticker, validated UTC
  created_at date, normalized horizon, normalized benchmark)``. Timestamps
  must be offset-aware strings and normalize to UTC; naive values, date-only
  strings, and any other missing or malformed key material are
  unclusterable and never replaced with an invented identity.
- Both clusterings cover rows whose ``resolved`` field is exactly ``True``:
  dependence bounds describe the resolved sample, not pending rows.
- Conservative market-event clusters are reported only as provisional
  dependence groups. They are not an effective sample size; that count stays
  unavailable until a preregistered estimator exists. Raw resolved rows are
  never independent observations.
- Canonical economic decision-event and decision-market-date counts stay
  unavailable unless a verified economic identity binding is present. The
  current ledger schema has no such binding, so neither ``created_at`` nor a
  provisional cluster key is promoted into economic identity.
- ``influence_weighting_status`` labels the row-weighted influence
  estimator legacy/unregistered in every receipt and dependence block.

Summary freshness states are exact: ``missing``, ``malformed`` (including
invalid UTF-8 and invalid JSON), ``unverifiable_legacy_summary`` (no ledger
fingerprint in the summary), ``stale`` (fingerprint or required counts
differ), and ``current`` only when the fingerprint and every required count
match. The summary path is never probed for existence; a file that vanishes
before or directly during its read is ``missing``, and other read failures
raise :class:`SummaryReadError` instead of being silently mislabeled.
"""

from __future__ import annotations

import contextlib
import datetime
import functools
import hashlib
import json
import os
import tempfile
import types
import typing
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "agent_intelligence_reconciliation/v2"
SUMMARY_FRESHNESS_MISSING = "missing"
SUMMARY_FRESHNESS_MALFORMED = "malformed"
SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY = "unverifiable_legacy_summary"
SUMMARY_FRESHNESS_STALE = "stale"
SUMMARY_FRESHNESS_CURRENT = "current"
LEDGER_FINGERPRINT_KEY = "ledger_fingerprint"
EFFECTIVE_SAMPLE_STATUS_UNAVAILABLE = "unavailable_pending_preregistered_estimator"
ECONOMIC_IDENTITY_STATUS_UNAVAILABLE = "unavailable_no_verified_economic_identity_binding"
ECONOMIC_IDENTITY_REASON = (
    "no_source_bound_verifier_with_frozen_economic_protocol"
)
INFLUENCE_WEIGHTING_STATUS_LEGACY = "legacy_unregistered_row_weighted_estimator"

UTC = datetime.timezone.utc


class ReconciliationPathError(ValueError):
    """Raised when a receipt output path would clobber a protected file."""


class SummaryReadError(OSError):
    """Raised when an existing summary cannot be read for freshness checks."""


class _MalformedSummary:
    """Sentinel payload for a summary path that is not a real summary.

    Used when a summary path physically aliases the ledger: the captured
    ledger bytes are never re-parsed as summary JSON, because even a valid
    single-record ledger would then masquerade as a fingerprint-less legacy
    summary instead of classifying deterministically as malformed.
    """

    __slots__ = ()


_MALFORMED_SUMMARY = _MalformedSummary()


class StrictJsonError(ValueError):
    """Raised when a document is not strict canonical JSON evidence."""


def _reject_duplicate_json_keys(pairs):
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise StrictJsonError(f"duplicate JSON key: {key}")
        seen[key] = value
    return seen


def _reject_non_finite_constant(value: str) -> Any:
    raise StrictJsonError(f"non-finite JSON constant: {value}")


_STRICT_JSON_DECODER = json.JSONDecoder(
    object_pairs_hook=_reject_duplicate_json_keys,
    parse_constant=_reject_non_finite_constant,
)


def canonical_json_text(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def normalized_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def parse_utc_timestamp(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if not clean:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _row_value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _required_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


@functools.lru_cache(maxsize=1)
def _agent_forecast_schema() -> tuple[tuple[str, ...], dict[str, Any]]:
    import dataclasses

    from tradingagents.evals.agent_intelligence_ledger import AgentForecast

    hints = typing.get_type_hints(AgentForecast)
    required: list[str] = []
    checks: dict[str, Any] = {}
    for declared in dataclasses.fields(AgentForecast):
        if (
            declared.default is dataclasses.MISSING
            and declared.default_factory is dataclasses.MISSING
        ):
            required.append(declared.name)
        checks[declared.name] = _type_checker(hints[declared.name])
    return tuple(required), checks


@functools.cache
def _type_checker(hint: Any) -> Any:
    """Build a deterministic predicate for one declared schema annotation.

    Supported: ``Any``/``object``, plain types (with exact ``bool``), PEP 604
    unions, ``list[T]``, and ``dict[K, V]`` with both key and value checks.
    Bare containers, tuples/sets, and any other unrecognized annotation raise
    TypeError during schema construction instead of silently accepting
    everything.
    """

    if hint is Any or hint is object:
        return lambda _value: True
    origin = typing.get_origin(hint)
    if origin is typing.Union or isinstance(hint, types.UnionType):
        args = typing.get_args(hint)
        allows_none = type(None) in args
        members = tuple(_type_checker(arg) for arg in args if arg is not type(None))

        def union_check(value: Any) -> bool:
            if value is None:
                return allows_none
            return any(check(value) for check in members)

        return union_check
    if hint in (list, dict, tuple, set, frozenset) or origin in (
        tuple,
        set,
        frozenset,
    ):
        raise TypeError(
            f"unsupported container annotation in AgentForecast schema: {hint!r}"
        )
    if origin is list:
        args = typing.get_args(hint)
        if len(args) != 1:
            raise TypeError(
                f"unsupported list annotation in AgentForecast schema: {hint!r}"
            )
        element_check = _type_checker(args[0])

        def list_check(value: Any) -> bool:
            return isinstance(value, list) and all(element_check(item) for item in value)

        return list_check
    if origin is dict:
        args = typing.get_args(hint)
        if len(args) != 2:
            raise TypeError(
                f"unsupported dict annotation in AgentForecast schema: {hint!r}"
            )
        key_check = _type_checker(args[0])
        value_check = _type_checker(args[1])

        def dict_check(value: Any) -> bool:
            return isinstance(value, dict) and all(
                key_check(key) and value_check(item) for key, item in value.items()
            )

        return dict_check
    if isinstance(hint, type):
        if hint is bool:

            def bool_check(value: Any) -> bool:
                return isinstance(value, bool)

            return bool_check
        if hint is int:

            def int_check(value: Any) -> bool:
                return isinstance(value, int) and not isinstance(value, bool)

            return int_check
        expected = hint

        def type_check(value: Any) -> bool:
            return isinstance(value, expected)

        return type_check
    raise TypeError(f"unsupported annotation in AgentForecast schema: {hint!r}")


def _row_matches_agent_forecast_schema(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    required, checks = _agent_forecast_schema()
    if any(name not in row for name in required):
        return False
    for name, value in row.items():
        check = checks.get(name)
        if check is None or not check(value):
            return False
    return True


def packet_event_key(row: Any) -> tuple[str, str, str, str] | None:
    """Packet-event key for a raw mapping or a constructed forecast row.

    For a Mapping payload an omitted ``resolution_window`` field is missing
    cluster material and yields ``None``; an explicitly present JSON ``null``
    remains the legitimate canonical legacy null sentinel. Object-space rows
    always expose the dataclass default, so their ``None`` attribute is
    treated as that same sentinel even though field presence is lost.
    """

    source_packet_id = _required_string(_row_value(row, "source_packet_id"))
    ticker = _required_string(_row_value(row, "ticker"))
    benchmark = _required_string(_row_value(row, "benchmark"))
    if not source_packet_id or not ticker or not benchmark:
        return None
    if isinstance(row, Mapping):
        if "resolution_window" not in row:
            return None
        window: Any = row["resolution_window"]
    else:
        window = getattr(row, "resolution_window", None)
    return _packet_key_from_parts(
        source_packet_id,
        ticker.upper(),
        benchmark.upper(),
        window,
    )


def _packet_key_from_parts(
    source_packet_id: str,
    ticker: str,
    benchmark: str,
    window: Any,
) -> tuple[str, str, str, str] | None:
    if window is None:
        window_key = "null"
    elif isinstance(window, Mapping):
        try:
            window_key = canonical_json_text(window)
        except (TypeError, ValueError):
            return None
    else:
        return None
    return (source_packet_id, ticker, benchmark, window_key)


def market_event_key(row: Any) -> tuple[str, str, str, str] | None:
    ticker = _required_string(_row_value(row, "ticker"))
    benchmark = _required_string(_row_value(row, "benchmark"))
    horizon = _required_string(_row_value(row, "horizon"))
    created_at = parse_utc_timestamp(_row_value(row, "created_at"))
    if not ticker or not benchmark or not horizon or created_at is None:
        return None
    return (
        ticker.upper(),
        created_at.date().isoformat(),
        normalized_token(horizon),
        benchmark.upper(),
    )


def _resolved_rows(rows: Iterable[Any]) -> list[Any]:
    return [row for row in rows if _row_value(row, "resolved") is True]


def _cluster_counts(
    rows: Sequence[Any],
    key_fn,
) -> tuple[int, int]:
    keys: set[tuple[str, ...]] = set()
    unclusterable = 0
    for row in rows:
        key = key_fn(row)
        if key is None:
            unclusterable += 1
        else:
            keys.add(key)
    return len(keys), unclusterable


def _verified_economic_identity_report(
    resolved_rows: Sequence[dict[str, Any]],
    *,
    source_bound_verifier: object | None,
) -> dict[str, Any]:
    """Count only v3 rows reverified against PIT bytes and a frozen protocol."""

    if source_bound_verifier is None:
        return {
            "unique_economic_decision_event_id_count": None,
            "unique_economic_decision_market_date_count": None,
            "economic_decision_verified_resolved_row_count": 0,
            "economic_decision_unbound_resolved_row_count": len(resolved_rows),
            "economic_decision_identity_status": ECONOMIC_IDENTITY_STATUS_UNAVAILABLE,
            "economic_decision_identity_reason": ECONOMIC_IDENTITY_REASON,
        }
    from tradingagents.evals.agent_intelligence_ledger import AgentForecast
    from tradingagents.evals.source_bound_resolution import SourceBoundWindowLookup

    if type(source_bound_verifier) is not SourceBoundWindowLookup:
        raise TypeError("source_bound_verifier must be an exact SourceBoundWindowLookup")
    event_ids: set[str] = set()
    market_dates: set[str] = set()
    verified_rows = 0
    for row in resolved_rows:
        forecast = AgentForecast(**row)
        evidence = row.get("resolution_evidence")
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("schema_version") != "source_bound_resolution_evidence/v3"
            or source_bound_verifier.verify_forecast(forecast) is not True
        ):
            continue
        economic = evidence.get("economic_decision")
        if not isinstance(economic, Mapping):
            continue
        event_id = economic.get("decision_event_id")
        market_date = economic.get("market_date")
        if type(event_id) is not str or type(market_date) is not str:
            continue
        event_ids.add(event_id)
        market_dates.add(market_date)
        verified_rows += 1
    unbound = len(resolved_rows) - verified_rows
    return {
        "unique_economic_decision_event_id_count": len(event_ids),
        "unique_economic_decision_market_date_count": len(market_dates),
        "economic_decision_verified_resolved_row_count": verified_rows,
        "economic_decision_unbound_resolved_row_count": unbound,
        "economic_decision_identity_status": (
            "verified" if unbound == 0 else "verified_with_unbound_rows"
        ),
        "economic_decision_identity_reason": (
            None if unbound == 0 else "resolved_rows_without_reverified_v3_binding"
        ),
    }


def dependence_block(rows: Iterable[Any]) -> dict[str, Any]:
    """Object-space dependence counters for constructed forecast rows.

    Because AgentForecast construction replaces an omitted
    ``resolution_window`` field with the ``None`` default, this block counts
    ``AgentForecast.resolution_window=None`` as the canonical legacy null
    sentinel. Raw receipts built by :func:`build_reconciliation_receipt` keep
    payload mappings and therefore distinguish an omitted field (missing
    cluster material, packet-event unclusterable) from an explicit JSON null.
    """

    resolved = _resolved_rows(rows)
    packet_clusters, packet_unclusterable = _cluster_counts(resolved, packet_event_key)
    market_clusters, market_unclusterable = _cluster_counts(resolved, market_event_key)
    null_window_rows = [
        row for row in resolved if _row_value(row, "resolution_window") is None
    ]
    mapping_window_rows = [
        row
        for row in resolved
        if isinstance(_row_value(row, "resolution_window"), Mapping)
    ]
    null_window_clusters, _ = _cluster_counts(null_window_rows, packet_event_key)
    non_null_window_clusters, _ = _cluster_counts(mapping_window_rows, packet_event_key)
    return {
        "scope": "resolved_rows",
        "resolved_row_count": len(resolved),
        "packet_event_cluster_count": packet_clusters,
        "packet_event_unclusterable_count": packet_unclusterable,
        "packet_event_null_window_resolved_row_count": len(null_window_rows),
        "packet_event_null_window_cluster_count": null_window_clusters,
        "packet_event_non_null_window_cluster_count": non_null_window_clusters,
        "market_event_cluster_count": market_clusters,
        "market_event_unclusterable_count": market_unclusterable,
        "provisional_market_event_cluster_count": market_clusters,
        "effective_sample_count": None,
        "effective_sample_status": EFFECTIVE_SAMPLE_STATUS_UNAVAILABLE,
        "raw_resolved_rows_are_independent_observations": False,
        "influence_weighting_status": INFLUENCE_WEIGHTING_STATUS_LEGACY,
    }


def evaluate_summary_freshness(
    summary_payload: Any,
    *,
    ledger_sha256: str,
    ledger_byte_length: int,
    valid_forecast_count: int,
    resolved_row_count: int,
) -> str:
    """Classify summary freshness against the captured ledger snapshot.

    The fingerprint's ``ledger_sha256`` must be a nonempty string; the three
    numeric fields require exactly ``int`` (JSON ``true`` and float literals
    such as ``1.0`` never equal an int here), and any mismatch is ``stale``.
    A fingerprint block without a usable sha stays
    ``unverifiable_legacy_summary``.
    """

    if summary_payload is None:
        return SUMMARY_FRESHNESS_MISSING
    if not isinstance(summary_payload, Mapping):
        return SUMMARY_FRESHNESS_MALFORMED
    fingerprint = summary_payload.get(LEDGER_FINGERPRINT_KEY)
    if not isinstance(fingerprint, Mapping):
        return SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY
    recorded_sha256 = fingerprint.get("ledger_sha256")
    if not isinstance(recorded_sha256, str) or not recorded_sha256.strip():
        return SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY
    if recorded_sha256 != ledger_sha256:
        return SUMMARY_FRESHNESS_STALE
    numeric_required = {
        "ledger_byte_length": ledger_byte_length,
        "valid_forecast_count": valid_forecast_count,
        "resolved_row_count": resolved_row_count,
    }
    for field, expected in numeric_required.items():
        value = fingerprint.get(field)
        if type(value) is not int or value != expected:
            return SUMMARY_FRESHNESS_STALE
    return SUMMARY_FRESHNESS_CURRENT


def build_reconciliation_receipt(
    ledger_bytes: bytes,
    *,
    summary_payload: Any = None,
    source_bound_verifier: object | None = None,
) -> dict[str, Any]:
    """Reconcile one captured ledger byte snapshot into a v2 receipt.

    Records are split on LF bytes with one trailing CR tolerated for CRLF and
    strictly UTF-8 decoded individually; decode failures are corrupt without
    lossy replacement. Legal U+2028/U+2029/U+0085 inside JSON strings never
    split a row because splitting is byte-level. Every nonempty record must
    be a JSON object validating against the declared AgentForecast schema;
    anything else counts corrupt. Duplicate/conflict accounting groups these
    validated payload mappings directly, so field presence survives: an
    omitted ``resolution_window`` and an explicit JSON ``null`` with
    otherwise identical content are conflicting rows, not exact duplicates.
    Packet and market clusters are likewise derived from the validated
    payload mappings, so an omitted ``resolution_window`` field stays missing
    cluster material (packet-event unclusterable) while an explicitly
    present JSON ``null`` remains the canonical legacy null sentinel; only
    explicit nulls are reported as null-window rows.
    """

    valid_raw: list[dict[str, Any]] = []
    corrupt_line_count = 0
    raw_nonempty_line_count = 0
    for record in ledger_bytes.split(b"\n"):
        if record.endswith(b"\r"):
            record = record[:-1]
        if not record.strip(b" \t"):
            continue
        raw_nonempty_line_count += 1
        try:
            text = record.decode("utf-8")
        except UnicodeDecodeError:
            corrupt_line_count += 1
            continue
        try:
            parsed = _STRICT_JSON_DECODER.decode(text)
        except (json.JSONDecodeError, StrictJsonError):
            corrupt_line_count += 1
            continue
        if not _row_matches_agent_forecast_schema(parsed):
            corrupt_line_count += 1
            continue
        valid_raw.append(parsed)

    by_forecast_id: dict[str, list[dict[str, Any]]] = {}
    for row in valid_raw:
        by_forecast_id.setdefault(row["forecast_id"], []).append(row)
    duplicate_forecast_id_row_count = 0
    conflicting_forecast_id_count = 0
    for group in by_forecast_id.values():
        if len(group) < 2:
            continue
        payloads = {canonical_json_text(row) for row in group}
        if len(payloads) == 1:
            duplicate_forecast_id_row_count += len(group) - 1
        else:
            conflicting_forecast_id_count += 1

    resolved_raw = [row for row in valid_raw if row.get("resolved") is True]
    pending_raw = [row for row in valid_raw if row.get("resolved") is False]
    packet_clusters, packet_unclusterable = _cluster_counts(
        resolved_raw, packet_event_key
    )
    market_clusters, market_unclusterable = _cluster_counts(resolved_raw, market_event_key)
    ledger_sha256 = hashlib.sha256(ledger_bytes).hexdigest()

    explicit_null_window_rows = [
        row
        for row in valid_raw
        if row.get("resolved") is True
        and "resolution_window" in row
        and row["resolution_window"] is None
    ]
    mapping_window_rows = [
        row
        for row in valid_raw
        if row.get("resolved") is True and isinstance(row.get("resolution_window"), Mapping)
    ]

    null_window_cluster_count, _ = _cluster_counts(
        explicit_null_window_rows, packet_event_key
    )
    non_null_window_cluster_count, _ = _cluster_counts(
        mapping_window_rows, packet_event_key
    )

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ledger_sha256": ledger_sha256,
        "ledger_byte_length": len(ledger_bytes),
        "raw_nonempty_line_count": raw_nonempty_line_count,
        "valid_forecast_count": len(valid_raw),
        "corrupt_line_count": corrupt_line_count,
        "duplicate_forecast_id_row_count": duplicate_forecast_id_row_count,
        "conflicting_forecast_id_count": conflicting_forecast_id_count,
        "resolved_row_count": len(resolved_raw),
        "pending_row_count": len(pending_raw),
        "resolved_high_quality_count": sum(
            row.get("label_quality") == "high" for row in resolved_raw
        ),
        "resolved_degraded_quality_count": sum(
            row.get("label_quality") == "degraded" for row in resolved_raw
        ),
        "resolved_suspect_quality_count": sum(
            row.get("label_quality") == "suspect" for row in resolved_raw
        ),
        "packet_event_cluster_count": packet_clusters,
        "packet_event_unclusterable_count": packet_unclusterable,
        "packet_event_null_window_resolved_row_count": len(explicit_null_window_rows),
        "packet_event_null_window_cluster_count": null_window_cluster_count,
        "packet_event_non_null_window_cluster_count": non_null_window_cluster_count,
        "market_event_cluster_count": market_clusters,
        "market_event_unclusterable_count": market_unclusterable,
        "provisional_market_event_cluster_count": market_clusters,
        "effective_sample_count": None,
        "effective_sample_status": EFFECTIVE_SAMPLE_STATUS_UNAVAILABLE,
        "raw_resolved_rows_are_independent_observations": False,
        "influence_weighting_status": INFLUENCE_WEIGHTING_STATUS_LEGACY,
        "summary_freshness": evaluate_summary_freshness(
            summary_payload,
            ledger_sha256=ledger_sha256,
            ledger_byte_length=len(ledger_bytes),
            valid_forecast_count=len(valid_raw),
            resolved_row_count=len(resolved_raw),
        ),
    }
    receipt.update(
        _verified_economic_identity_report(
            resolved_raw,
            source_bound_verifier=source_bound_verifier,
        )
    )
    receipt["receipt_sha256"] = hashlib.sha256(
        canonical_json_text(receipt).encode("utf-8")
    ).hexdigest()
    return receipt


def _decoded_summary_payload(raw: bytes) -> Any:
    """Decode summary bytes with the shared strict JSON decoder.

    Invalid UTF-8, invalid JSON, non-finite constants, duplicate keys at any
    nesting level, and JSON literal ``null`` all map to the malformed
    sentinel; only an absent or vanished file represents ``missing``.
    """

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    try:
        parsed = _STRICT_JSON_DECODER.decode(text)
    except (json.JSONDecodeError, StrictJsonError):
        return ""
    if parsed is None:
        return ""
    return parsed


def reconcile_ledger_file(
    ledger_path: str | Path,
    *,
    summary_path: str | Path | None = None,
    source_bound_verifier: object | None = None,
) -> dict[str, Any]:
    """Reconcile a ledger path read-only, capturing its bytes exactly once.

    A summary path that physically aliases the ledger (direct path, symlink,
    or hardlink) never triggers a second read of those bytes; the alias is
    classified with a private malformed-summary sentinel instead of parsing
    ledger bytes as summary JSON, so even a valid single-record ledger can
    never masquerade as a fingerprint-less legacy summary. The summary path
    is never probed for existence: the bytes are read directly,
    ``FileNotFoundError`` maps to ``missing`` (including vanish races), and
    every other metadata/alias/read ``OSError`` raises
    :class:`SummaryReadError` so failures are never mislabeled as ledger
    problems. A present summary holding JSON literal ``null`` is malformed.
    """

    ledger_file = Path(ledger_path)
    ledger_data = ledger_file.read_bytes()
    summary_payload: Any = None
    if summary_path is not None:
        summary_file = Path(summary_path)
        try:
            summary_aliases_ledger = _paths_equivalent(
                summary_file, ledger_file, strict=True
            )
        except OSError as exc:
            raise SummaryReadError(f"could not read summary {summary_file}: {exc}") from exc
        if summary_aliases_ledger:
            summary_payload = _MALFORMED_SUMMARY
        else:
            try:
                summary_bytes = summary_file.read_bytes()
            except FileNotFoundError:
                summary_bytes = None
            except OSError as exc:
                raise SummaryReadError(f"could not read summary {summary_file}: {exc}") from exc
            if summary_bytes is not None:
                summary_payload = _decoded_summary_payload(summary_bytes)
    return build_reconciliation_receipt(
        ledger_data,
        summary_payload=summary_payload,
        source_bound_verifier=source_bound_verifier,
    )


def _paths_equivalent(first: Path, second: Path, *, strict: bool = False) -> bool:
    """Report physical aliasing without any existence probe.

    ``os.path.samefile`` decides inode aliasing directly. FileNotFoundError
    means no inode alias and permits the realpath fallback; any other
    OSError from samefile or realpath re-raises in strict mode — used by
    summary reads and receipt protected-path validation — while non-strict
    mode stays non-raising for best-effort callers only.
    """

    try:
        try:
            return bool(os.path.samefile(first, second))
        except FileNotFoundError:
            pass
        except OSError:
            if strict:
                raise
        return os.path.realpath(first) == os.path.realpath(second)
    except OSError:
        if strict:
            raise
        return False


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_reconciliation_receipt(
    receipt: Mapping[str, Any],
    path: str | Path,
    *,
    protected_paths: Sequence[str | Path] = (),
) -> Path:
    """Atomically write only the receipt JSON, never a partial overwrite.

    Refuses targets equivalent (same file, symlink alias, hardlink alias, or
    realpath) to any protected path such as the ledger or the agent score
    summary. The payload is staged in a sibling temp file and moved into
    place with ``os.replace`` followed by a directory fsync, so readers see
    either the previous file or the complete new receipt; a failed stage,
    replace, or fsync raises instead of reporting success.
    """

    target = Path(path)
    for protected in protected_paths:
        try:
            aliased = _paths_equivalent(target, Path(protected), strict=True)
        except OSError as exc:
            raise ReconciliationPathError(
                f"receipt path protection could not be verified against "
                f"{protected}: {exc}"
            ) from exc
        if aliased:
            raise ReconciliationPathError(
                f"receipt path must not overwrite protected path: {protected}"
            )
    if target.is_dir():
        raise ReconciliationPathError(f"receipt path is a directory: {target}")
    payload = (canonical_json_text(dict(receipt)) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        descriptor_open = True
        try:
            handle = os.fdopen(handle_fd, "wb")
            descriptor_open = False
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor_open:
                with contextlib.suppress(OSError):
                    os.close(handle_fd)
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()
        raise
    return target
