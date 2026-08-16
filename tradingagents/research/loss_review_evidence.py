"""Analysis-only evidence refresh for hourly loss-review holds."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tradingagents.dataflows._official_common import evidence_packet, request_hash
from tradingagents.policy.decision_authority import (
    bounded_exit_authority_record,
    parse_pre_registered_exit_policy_candidate,
    resolve_exit_authority,
)
from tradingagents.research.provider_orchestrator import (
    TickerProviderResearchResult,
    build_ticker_provider_research_packets,
    canonical_provider_timestamp,
    configured_quote_components,
    strict_loss_review_news_event,
)
from tradingagents.schemas.research import SourceEvidencePacket

DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS: tuple[str, ...] = (
    "quote_price_context",
    "market_news",
    "fundamentals_profile",
    "earnings_transcripts",
)

LOSS_REVIEW_FORBIDDEN_EFFECTS: tuple[str, ...] = (
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
    "mark_loss_exit_allowed",
)

# The supervisory quote route is deliberately requested per symbol.  The
# configured providers commonly return a one-symbol quote/previous-day packet;
# treating an imaginary four-symbol Alpaca response as the only valid shape
# made a real evidence refresh unable to clear its market-context blocker.
DEFAULT_LOSS_REVIEW_SECTOR_PROXY = "XLK"
# This is the configured loss-news route order.  It is intentionally explicit
# here because only one issuer event may enter the current BOARD decision:
# Alpaca first, then Finnhub, then FMP.  If the same source returns several
# qualified events, the newest canonical event time wins; packet id is the
# final stable tie-break.  Other raw packets remain diagnostics only.
_LOSS_REVIEW_NEWS_PROVIDER_PRIORITY = {
    "alpaca_news": 0,
    "finnhub": 1,
    "fmp": 2,
}


def loss_review_sector_proxy(symbol: str) -> str:
    """Return the configured default comparison proxy for a loss review.

    This is intentionally a small, explicit policy hook rather than an
    inference from an issuer name.  A future sector-classification source may
    replace it without changing the immutable evidence contract.
    """
    del symbol
    return DEFAULT_LOSS_REVIEW_SECTOR_PROXY


def _current_post_fetch_authority_now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def build_loss_review_provider_research(
    symbol: str,
    *,
    sector_proxy: str | None = None,
    provider_builder=build_ticker_provider_research_packets,
    **kwargs: Any,
) -> TickerProviderResearchResult:
    """Collect the target and three benchmark quotes through configured routes.

    The target receives the normal loss-review research needs.  SPY, QQQ, and
    the configured sector proxy receive quote-only requests.  All returned
    packets are preserved so the normalizer can bind their exact raw bytes.
    This remains research-only; it has no broker mutation path.
    """
    target = str(symbol).strip().upper()
    proxy = str(sector_proxy or loss_review_sector_proxy(target)).strip().upper()
    target_needs = tuple(kwargs.pop("evidence_needs", DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS))
    post_fetch_authority_now = kwargs.pop("authority_now", None)
    if post_fetch_authority_now is None:
        post_fetch_authority_now = _current_post_fetch_authority_now
    requested = (target, "SPY", "QQQ", proxy)
    packets: list[SourceEvidencePacket] = []
    attempts: list[dict[str, Any]] = []
    for requested_symbol in dict.fromkeys(requested):
        needs = (
            target_needs
            if requested_symbol == target
            else ("quote_price_context",)
        )
        result = provider_builder(
            requested_symbol,
            evidence_needs=needs,
            # Loss BOARD alone needs an admissible current/previous pair for
            # every component.  General ticker research preserves its normal
            # packet-cap behaviour.
            require_admissible_quote=True,
            # Loss BOARD research needs a strict, current company event, not
            # merely the first cache/RSS/blocked news packet returned.
            require_admissible_loss_news=True,
            # Only a production-shaped transcript route with an issuer event
            # time and fresh capture can clear the loss-board substance slot.
            require_admissible_loss_substance=True,
            # Resolve this callable only after each source read.  Tests may
            # supply a fixed aware instant for deterministic admission.
            authority_now=post_fetch_authority_now,
            **kwargs,
        )
        packets.extend(result.packets)
        attempts.extend(
            [
                {**dict(item), "requested_symbol": requested_symbol}
                for item in result.route_attempts
                if isinstance(item, Mapping)
            ]
        )
    return TickerProviderResearchResult(
        symbol=target,
        packets=packets,
        summary_packet=None,
        route_attempts=attempts,
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_hourly_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if _is_raw_hourly_packet_path(path) else []
    return sorted(
        (
            packet_path
            for packet_path in path.glob("hourly-supervisor-*.json")
            if _is_raw_hourly_packet_path(packet_path)
        ),
        reverse=True,
    )


def _is_raw_hourly_packet_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    return not path.name.lower().endswith(".compact.json")


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _trading_days_between(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    start_date = start.astimezone(UTC).date()
    end_date = end.astimezone(UTC).date()
    if end_date < start_date:
        return None
    current = start_date
    days = 0
    while current < end_date:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def _loss_review_from_packet(packet: Mapping[str, Any]) -> Mapping[str, Any] | None:
    evidence = packet.get("evidence")
    if not isinstance(evidence, Mapping):
        return None
    review = evidence.get("loss_exit_review")
    return review if isinstance(review, Mapping) else None


def _entry_context_from_packet(
    *,
    path: Path,
    packet: Mapping[str, Any],
    symbol: str,
    review_at: datetime | None,
) -> dict[str, Any] | None:
    actions = packet.get("actions")
    submitted = packet.get("submitted")
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes, bytearray)):
        actions = []
    if not isinstance(submitted, Sequence) or isinstance(submitted, (str, bytes, bytearray)):
        submitted = []

    matching_actions = [
        action
        for action in actions
        if isinstance(action, Mapping)
        and str(action.get("symbol") or "").strip().upper() == symbol
        and str(action.get("side") or "").strip().lower() == "buy"
        and str(action.get("account") or "").strip().lower() == "live"
    ]
    matching_orders = [
        order
        for order in submitted
        if isinstance(order, Mapping)
        and str(order.get("symbol") or "").strip().upper() == symbol
        and str(order.get("side") or "").strip().lower() == "buy"
    ]
    if not matching_actions and not matching_orders:
        return None

    action = matching_actions[-1] if matching_actions else {}
    order = matching_orders[-1] if matching_orders else {}
    packet_generated_at = _parse_timestamp(packet.get("generated_at"))
    submitted_at = _parse_timestamp(order.get("submitted_at"))
    created_at = _parse_timestamp(order.get("created_at"))
    opened_at = submitted_at or created_at or packet_generated_at
    entry_reason = str(action.get("reason") or "").strip()
    return {
        "source": "local_hourly_supervisor_history",
        "packet_path": str(path),
        "packet_generated_at": packet.get("generated_at"),
        "symbol": symbol,
        "account": str(action.get("account") or "live"),
        "entry_reason": entry_reason or None,
        "notional": action.get("notional") or order.get("notional"),
        "limit_price": action.get("limit_price") or order.get("limit_price"),
        "client_order_id": order.get("client_order_id"),
        "submitted_at": order.get("submitted_at"),
        "order_status": order.get("status"),
        "holding_period_trading_days": _trading_days_between(opened_at, review_at),
        "is_submitted_order_context": bool(order),
        "is_action_context": bool(action),
    }


def find_prior_live_entry_context(
    hourly_packet_path: str | Path,
    *,
    symbol: str,
    review_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Find the newest prior same-symbol live buy context from local hourly history."""
    path = Path(hourly_packet_path)
    root = path.parent if path.is_file() else path
    if not root.exists():
        return None
    current_path = path.resolve() if path.exists() else None
    for candidate in _candidate_hourly_paths(root):
        if current_path is not None and candidate.resolve() == current_path:
            continue
        try:
            packet = _load_json(candidate)
        except (OSError, json.JSONDecodeError):
            continue
        packet_at = _parse_timestamp(packet.get("generated_at"))
        if review_at is not None and packet_at is not None and packet_at >= review_at:
            continue
        context = _entry_context_from_packet(
            path=candidate,
            packet=packet,
            symbol=symbol,
            review_at=review_at,
        )
        if context is not None:
            return context
    return None


def find_latest_loss_review_packet(hourly_dir: str | Path) -> tuple[Path, dict[str, Any], Mapping[str, Any]]:
    """Return the newest hourly packet with structured loss-review evidence."""
    root = Path(hourly_dir)
    for path in _candidate_hourly_paths(root):
        try:
            packet = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        review = _loss_review_from_packet(packet)
        if review is not None:
            return path, packet, review
    raise FileNotFoundError(f"no hourly loss-review packet found under {root}")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _float_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except ValueError:
        return None


def _source_packet_ids(provider_result: TickerProviderResearchResult) -> list[str]:
    # The BOARD authenticates direct provider packets through their local raw
    # descriptors.  The orchestrator summary is separately named in the loss
    # payload but has no raw-provider descriptor, so it is not part of this
    # exact source manifest contract.
    return [packet.packet_id for packet in provider_result.packets]


def _coverage_by_need(provider_result: TickerProviderResearchResult) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for packet in provider_result.packets:
        coverage[packet.evidence_type] = coverage.get(packet.evidence_type, 0) + 1
    return coverage


def _has_coverage(coverage_by_need: Mapping[str, int], *needs: str) -> bool:
    return any(int(coverage_by_need.get(need) or 0) > 0 for need in needs)


def _find_symbol_entry(items: Any, symbol: str) -> Mapping[str, Any] | None:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        return None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("symbol") or "").strip().upper() == symbol:
            return item
    return None


def _provider_packet_refs(provider_result: TickerProviderResearchResult) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for packet in provider_result.packets:
        refs.append(
            {
                "packet_id": packet.packet_id,
                "source_name": packet.source_name,
                "evidence_type": packet.evidence_type,
                "quality": packet.quality,
                "as_of": str(packet.as_of or packet.generated_at),
            }
        )
    if provider_result.summary_packet is not None:
        packet = provider_result.summary_packet
        refs.append(
            {
                "packet_id": packet.packet_id,
                "source_name": packet.source_name,
                "evidence_type": packet.evidence_type,
                "quality": packet.quality,
                "as_of": str(packet.as_of or packet.generated_at),
            }
        )
    return refs


def _raw_provider_packet_provenance(
    packet: SourceEvidencePacket,
    relative: Path,
    raw: bytes,
) -> dict[str, Any]:
    """Preserve one exact raw identity for authoritative later replay."""
    return {
        "raw_packet_path": relative.as_posix(),
        "raw_packet_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_packet_id": packet.packet_id,
        "raw_evidence_type": packet.evidence_type,
        "raw_source_name": packet.source_name,
        "raw_symbol": packet.symbol,
        "raw_subject": packet.subject,
        "raw_as_of": packet.as_of,
        "raw_quality": packet.quality,
        "raw_generated_at": str(packet.generated_at),
    }


def _accepted_source_descriptors(
    provider_result: TickerProviderResearchResult,
    *,
    source_packet_paths: Mapping[str, str | Path] | None,
    evidence_root: str | Path | None,
    now: datetime | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind written provider packets exactly for the downstream BOARD recorder.

    Missing, outside-root, unreadable, or malformed source files are omitted.
    That is intentionally conservative: an incomplete descriptor set leads to
    HOLD rather than allowing a source's self-description to clear a blocker.
    """
    if not source_packet_paths or evidence_root is None:
        return [], [], []
    run_now = now or datetime.now(tz=UTC)
    if run_now.tzinfo is None or run_now.utcoffset() is None:
        return [], [], []
    root = _safe_root(evidence_root)
    result: list[dict[str, Any]] = []
    raw_source_manifest: list[dict[str, Any]] = []
    quote_components: dict[str, dict[str, Any]] = {}
    news_candidates: list[dict[str, Any]] = []

    for packet in provider_result.packets:
        supplied = source_packet_paths.get(packet.packet_id)
        if supplied is None:
            continue
        try:
            relative, raw, stored = _read_contained_json(root, supplied)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(stored, Mapping):
            continue
        as_of = canonical_provider_timestamp(packet.as_of or packet.generated_at)
        if as_of is None:
            continue
        if (
            stored.get("packet_id") != packet.packet_id
            or stored.get("source_name") != packet.source_name
            or stored.get("evidence_type") != packet.evidence_type
            or stored.get("symbol") != packet.symbol
            or stored.get("as_of") != packet.as_of
            or stored.get("quality") != packet.quality
        ):
            continue
        raw_provenance = _raw_provider_packet_provenance(packet, relative, raw)
        raw_source_manifest.append(raw_provenance)
        components = _configured_quote_components(
            source_name=packet.source_name,
            evidence_type=packet.evidence_type,
            raw_payload=stored.get("payload"),
            expected_symbol=packet.symbol,
        ) if packet.evidence_type in {"quote_price_context", "quote"} else ()
        if components:
            for component in components:
                quote_components[component["symbol"]] = {
                    "symbol": component["symbol"],
                    "value": component["value"],
                    "current": component["current"],
                    "previous": component["previous"],
                    "current_sha256": component["current_sha256"],
                    "previous_sha256": component["previous_sha256"],
                    "quality": packet.quality,
                    "as_of": as_of,
                    "raw_evidence_type": packet.evidence_type,
                    "raw_packet_path": relative.as_posix(),
                    "raw_packet_sha256": hashlib.sha256(raw).hexdigest(),
                    "raw_packet_id": packet.packet_id,
                }
            # Quote components are collected first and normalized once below;
            # each component is useless on its own for autonomous authority.
            continue
        normalized = _normalize_provider_packet(
            packet=packet, stored=stored, symbol=packet.symbol, now=run_now
        )
        if normalized is None:
            continue
        normalized_type, normalized_payload, normalized_as_of = normalized
        if normalized_type == "company_news":
            # Do not publish every duplicate native news event as a BOARD
            # source.  Raw packets are still present in `source_packet_ids`
            # for diagnostics; exactly one deterministic candidate is allowed
            # into authority material below.
            news_candidates.append(
                {
                    "packet": packet,
                    "relative": relative,
                    "raw": raw,
                    "raw_provenance": raw_provenance,
                    "normalized_payload": normalized_payload,
                    "normalized_as_of": normalized_as_of,
                }
            )
            continue
        normalized_relative = Path("normalized_loss_review_evidence") / f"{packet.packet_id}-{normalized_type}.json"
        normalized_packet = {
            "packet_id": f"normalized-{packet.packet_id}-{normalized_type}",
            "source_name": packet.source_name,
            "evidence_type": normalized_type,
            "subject": packet.symbol,
            "symbol": packet.symbol,
            "as_of": normalized_as_of,
            "quality": packet.quality,
            "provenance": {
                **raw_provenance,
            },
            "payload": normalized_payload,
        }
        normalized_raw = json.dumps(normalized_packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            _publish_immutable(root, normalized_relative, normalized_raw)
        except (OSError, ValueError):
            continue
        result.append(
            {
                "path": normalized_relative.as_posix(),
                "sha256": hashlib.sha256(normalized_raw).hexdigest(),
                "size_bytes": len(normalized_raw),
                "packet_id": normalized_packet["packet_id"],
                "source_name": packet.source_name,
                "evidence_type": normalized_type,
                "as_of": normalized_as_of,
                "quality": packet.quality,
            }
        )
    if news_candidates:
        def news_sort_key(candidate: Mapping[str, Any]) -> tuple[int, float, str]:
            packet = candidate["packet"]
            observed = _parse_timestamp(candidate["normalized_as_of"])
            return (
                _LOSS_REVIEW_NEWS_PROVIDER_PRIORITY.get(packet.source_name.lower(), 999),
                -(observed.timestamp() if observed is not None else float("-inf")),
                packet.packet_id,
            )

        selected = min(news_candidates, key=news_sort_key)
        packet = selected["packet"]
        relative = selected["relative"]
        raw = selected["raw"]
        normalized_payload = selected["normalized_payload"]
        normalized_as_of = selected["normalized_as_of"]
        normalized_relative = Path("normalized_loss_review_evidence") / f"{packet.packet_id}-company_news.json"
        normalized_packet = {
            "packet_id": f"normalized-{packet.packet_id}-company_news",
            "source_name": packet.source_name,
            "evidence_type": "company_news",
            "subject": packet.symbol,
            "symbol": packet.symbol,
            "as_of": normalized_as_of,
            "quality": packet.quality,
            "provenance": {
                **selected["raw_provenance"],
                "selection_policy": "configured_provider_priority_then_newest_event_then_packet_id",
            },
            "payload": normalized_payload,
        }
        normalized_raw = json.dumps(normalized_packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            _publish_immutable(root, normalized_relative, normalized_raw)
        except (OSError, ValueError):
            pass
        else:
            result.append(
                {
                    "path": normalized_relative.as_posix(),
                    "sha256": hashlib.sha256(normalized_raw).hexdigest(),
                    "size_bytes": len(normalized_raw),
                    "packet_id": normalized_packet["packet_id"],
                    "source_name": packet.source_name,
                    "evidence_type": "company_news",
                    "as_of": normalized_as_of,
                    "quality": packet.quality,
                }
            )
    # A market context must contain four exact, current components.  This
    # supports both the legacy combined packet and the configured individual
    # target/SPY/QQQ/sector requests without granting either partial shape
    # authority.  The normalized packet retains raw paths and hashes for all
    # component evidence in its provenance.
    required = {provider_result.symbol.upper(), "SPY", "QQQ", loss_review_sector_proxy(provider_result.symbol)}
    if required <= set(quote_components):
        target = provider_result.symbol.upper()
        target_component = quote_components[target]
        spy_component = quote_components["SPY"]
        qqq_component = quote_components["QQQ"]
        sector_component = quote_components[loss_review_sector_proxy(provider_result.symbol)]
        component_times = {
            item["symbol"]: _parse_timestamp(item["as_of"])
            for item in (target_component, spy_component, qqq_component, sector_component)
        }
        if any(value is None for value in component_times.values()):
            return result
        aggregate_as_of = max(component_times.values()).replace(microsecond=0).isoformat(timespec="seconds")
        sector_as_of = max(
            component_times[target], component_times[loss_review_sector_proxy(provider_result.symbol)]
        ).replace(microsecond=0).isoformat(timespec="seconds")
        normalized_payload = {
            "symbol": target,
            "as_of": aggregate_as_of,
            "target": {"symbol": target, "value": target_component["value"], "as_of": target_component["as_of"]},
            "spy": {"symbol": "SPY", "value": spy_component["value"], "as_of": spy_component["as_of"]},
            "qqq": {"symbol": "QQQ", "value": qqq_component["value"], "as_of": qqq_component["as_of"]},
            "sector_relative": {
                "symbol": target,
                "value": _normalized_decimal(
                    (_float_value(target_component["value"]) or 0)
                    - (_float_value(sector_component["value"]) or 0)
                ),
                "as_of": sector_as_of,
            },
            "target_relative_to_spy": _normalized_decimal(
                (_float_value(target_component["value"]) or 0)
                - (_float_value(spy_component["value"]) or 0)
            ),
            "target_relative_to_qqq": _normalized_decimal(
                (_float_value(target_component["value"]) or 0)
                - (_float_value(qqq_component["value"]) or 0)
            ),
        }
        if (
            normalized_payload["sector_relative"]["value"] is not None
            and normalized_payload["target_relative_to_spy"] is not None
            and normalized_payload["target_relative_to_qqq"] is not None
        ):
            components = [target_component, spy_component, qqq_component, sector_component]
            component_refs = [
                {
                    "packet_id": item["raw_packet_id"],
                    "path": item["raw_packet_path"],
                    "sha256": item["raw_packet_sha256"],
                    "symbol": item["symbol"],
                    "quality": item["quality"],
                    "as_of": item["as_of"],
                    "evidence_type": item["raw_evidence_type"],
                    "current": item["current"],
                    "previous": item["previous"],
                    "current_sha256": item["current_sha256"],
                    "previous_sha256": item["previous_sha256"],
                }
                for item in components
            ]
            identity = hashlib.sha256(
                json.dumps(component_refs, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            normalized_relative = Path("normalized_loss_review_evidence") / f"market-context-{identity}.json"
            normalized_packet = {
                "packet_id": f"normalized-market-context-{identity}",
                "source_name": "configured_quote_bundle",
                "evidence_type": "market_context",
                "subject": target,
                "symbol": target,
                "as_of": aggregate_as_of,
                # An aggregate cannot acquire quality its weakest raw input
                # does not have.  In particular a low yfinance component
                # must never be laundered into a SELL-eligible bundle.
                "quality": _component_quality([item["quality"] for item in components]),
                "provenance": {"components": component_refs},
                "payload": normalized_payload,
            }
            normalized_raw = json.dumps(normalized_packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
            try:
                _publish_immutable(root, normalized_relative, normalized_raw)
            except (OSError, ValueError):
                pass
            else:
                result.append(
                    {
                        "path": normalized_relative.as_posix(),
                        "sha256": hashlib.sha256(normalized_raw).hexdigest(),
                        "size_bytes": len(normalized_raw),
                        "packet_id": normalized_packet["packet_id"],
                        "source_name": normalized_packet["source_name"],
                        "evidence_type": "market_context",
                    "as_of": normalized_packet["as_of"],
                        "quality": normalized_packet["quality"],
                    }
                )
    return (
        result,
        sorted(raw_source_manifest, key=lambda item: str(item["raw_packet_id"])),
        [
            candidate["raw_provenance"]
            for candidate in sorted(
                news_candidates,
                key=lambda candidate: str(candidate["packet"].packet_id),
            )
        ],
    )


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_POSITIVE_WORDS = frozenset({"raise", "raises", "raised", "beat", "beats", "growth", "wins", "won", "approval", "approved", "partnership", "expands", "expansion"})
_GUIDANCE_CUT = re.compile(r"\b(cut|cuts|lower(?:ed|s)?|reduces?|revised?\s+down|withdraws?)\b.{0,80}\b(guidance|outlook|forecast|revenue)\b|\b(guidance|outlook|forecast|revenue)\b.{0,80}\b(cut|lower(?:ed|s)?|reduc(?:ed|es)|down)\b", re.I)
_CONTRACT_LOSS = re.compile(r"\b(lost|loss|terminated|termination|cancel(?:led|ed)?|canceled)\b.{0,80}\b(contract|customer|client|agreement)\b", re.I)
_THESIS_INVALIDATOR = re.compile(r"\b(bankruptcy|fraud|restatement|going concern|delist(?:ing)?|material weakness)\b", re.I)


def _safe_root(value: str | Path) -> Path:
    root = Path(value)
    state = root.lstat()
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise ValueError("evidence root must be a real directory")
    return root.resolve()


def _relative_under(root: Path, supplied: str | Path) -> Path:
    value = Path(supplied)
    if value.is_absolute():
        try:
            value = value.relative_to(root)
        except ValueError as exc:
            raise ValueError("source packet escapes evidence root") from exc
    if not value.parts or ".." in value.parts:
        raise ValueError("source packet escapes evidence root")
    return value


def _read_contained_json(root: Path, supplied: str | Path) -> tuple[Path, bytes, Mapping[str, Any]]:
    relative = _relative_under(root, supplied)
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW)
    current_fd = root_fd
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        descriptor = os.open(relative.parts[-1], os.O_RDONLY | _NOFOLLOW, dir_fd=current_fd)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("source packet must be a regular file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                raw = stream.read()
        finally:
            if descriptor != -1:
                os.close(descriptor)
        stored = json.loads(raw)
        if not isinstance(stored, Mapping):
            raise ValueError("source packet must be an object")
        return relative, raw, stored
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _mkdir_relative(root: Path, parts: tuple[str, ...]) -> int:
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW)
    current_fd = root_fd
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current_fd)
                os.fsync(current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        if current_fd != root_fd:
            os.close(current_fd)
        raise
    finally:
        os.close(root_fd)


def _publish_immutable(root: Path, relative: Path, content: bytes) -> None:
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2:
        raise ValueError("normalized evidence path is unsafe")
    parent_fd = _mkdir_relative(root, tuple(relative.parts[:-1]))
    try:
        try:
            descriptor = os.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            descriptor = os.open(relative.name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode) or os.read(descriptor, max(len(content) + 1, 1)) != content:
                    raise ValueError("immutable normalized evidence collision")
            finally:
                os.close(descriptor)
            return
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent_fd)
        finally:
            if descriptor != -1:
                os.close(descriptor)
    finally:
        os.close(parent_fd)


def _normalized_decimal(value: Any) -> str | None:
    numeric = _float_value(value)
    if numeric is None:
        return None
    # A canonical string is required by the decision validator; avoid a
    # provider's locale/percentage formatting leaking into authority material.
    return f"{numeric:.8f}".rstrip("0").rstrip(".") or "0"


_QUALITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def _component_quality(values: Sequence[str]) -> str:
    """Return the weakest component quality; an unrecognised label is unknown."""
    if not values:
        return "unknown"
    return min(values, key=lambda value: _QUALITY_RANK.get(str(value), 0))


def _canonical_value_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _normalize_provider_packet(
    *,
    packet: SourceEvidencePacket,
    stored: Mapping[str, Any],
    symbol: str,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any], str] | None:
    """Admit only semantically complete provider material into strict BOARD types.

    Raw provider packet names are never authority.  This intentionally accepts
    only structured facts from their payload; generic quotes, news headlines,
    SEC submission indexes, connector gaps, and cached placeholders yield None.
    """
    raw_payload = stored.get("payload")
    if not isinstance(raw_payload, Mapping) or packet.quality not in {"high", "medium"}:
        return None
    as_of = canonical_provider_timestamp(packet.as_of or packet.generated_at)
    if as_of is None:
        return None
    if (
        (packet.source_name.lower(), packet.evidence_type)
        in {
            ("alpaca_news", "market_news"),
            ("finnhub", "company_news"),
            ("fmp", "stock_news"),
        }
    ):
        event = strict_loss_review_news_event(
            source_name=packet.source_name,
            evidence_type=packet.evidence_type,
            payload=raw_payload,
            as_of=packet.as_of or packet.generated_at,
            quality=packet.quality,
            freshness=packet.freshness,
            now=now,
        )
        if event is None:
            return None
        event_as_of = event.pop("as_of")
        return "company_news", {"symbol": symbol, "as_of": event_as_of, **event}, event_as_of
    if packet.evidence_type in {"earnings_transcripts", "fundamentals_profile"}:
        event = _adverse_transcript_event(raw_payload, symbol=symbol)
        if not isinstance(event, Mapping) or event.get("direction") != "adverse":
            return None
        category = event.get("event_category")
        fraction = _normalized_decimal(event.get("change_fraction", event.get("impact_fraction")))
        if category not in {"guidance_cut", "adverse_filing_disclosure"} or fraction is None or _float_value(fraction) is None or _float_value(fraction) > -0.01:
            return None
        normalized_payload = {
            "symbol": symbol,
            "as_of": as_of,
            "event_category": category,
            "direction": "adverse",
            "change_fraction": fraction,
        }
        # FMP's configured transcript adapter preserves a provider-published
        # event time separately from its fresh collection timestamp.  The
        # latter controls BOARD freshness; the former proves the event was not
        # fabricated from local wall-clock time.
        if packet.source_name == "fmp":
            provider_event_at = raw_payload.get("published_at")
            if provider_event_at in (None, ""):
                provider_event_at = raw_payload.get("event_at")
            # A wrapper's ``generated_at`` is capture evidence only.  It may
            # never fill in for a missing provider publication/event time.
            event_at = canonical_provider_timestamp(provider_event_at)
            captured_at = canonical_provider_timestamp(packet.generated_at)
            if event_at is None or captured_at is None:
                return None
            if now is not None:
                current = now.astimezone(UTC).replace(microsecond=0)
                event_time = datetime.fromisoformat(event_at)
                capture_time = datetime.fromisoformat(captured_at)
                if (
                    event_time > current
                    or current - event_time > timedelta(days=7)
                    or capture_time > current
                    or current - capture_time > timedelta(minutes=15)
                ):
                    return None
            as_of = captured_at
            normalized_payload["as_of"] = captured_at
            normalized_payload["event_at"] = event_at
        return "earnings_guidance_filing", normalized_payload, as_of
    return None


def replay_normalized_loss_review_source(
    *,
    raw_packet: Mapping[str, Any],
    symbol: str,
    now: datetime,
) -> tuple[str, dict[str, Any], str] | None:
    """Re-run the source normalizer from exact raw packet bytes.

    This is deliberately separate from descriptor creation so the BOARD
    verifier can prove that a normalized news or filing packet still follows
    from the authenticated provider packet it names.  Invalid/malformed raw
    evidence remains non-authorizing.
    """
    try:
        packet = SourceEvidencePacket.model_validate(dict(raw_packet))
    except Exception:
        return None
    if packet.symbol != symbol or packet.subject in (None, ""):
        return None
    return _normalize_provider_packet(
        packet=packet,
        stored=raw_packet,
        symbol=symbol,
        now=now,
    )


def _quote_values(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, Mapping):
        return None
    current = next(
        (
            value.get(key)
            for key in ("p", "c", "price", "last", "last_price", "close", "Close")
            if value.get(key) not in (None, "")
        ),
        None,
    )
    previous_raw = next(
        (
            value.get(key)
            for key in (
                "pc", "previous_close", "previousClose", "prev_close",
                "prior_close", "previous_day_close",
            )
            if value.get(key) not in (None, "")
        ),
        None,
    )
    price = _float_value(current)
    previous = _float_value(previous_raw)
    if price is None or previous is None or previous <= 0:
        return None
    return price, previous


def _quote_price(value: Any) -> float | None:
    values = _quote_values(value)
    if values is None:
        return None
    price, previous = values
    return (price - previous) / previous


def _configured_quote_components(
    *, source_name: str, evidence_type: str, raw_payload: Any, expected_symbol: str
) -> tuple[dict[str, str], ...]:
    """Extract individual configured quote/previous-day facts, never aliases.

    Alpaca can supply ``data.trades`` keyed by symbol; yfinance and several
    configured fallback routes provide one target quote in ``data`` or
    ``latest_bar``.  The caller combines only exact requested component
    symbols, so a target quote is never re-labelled as SPY/QQQ/sector data.
    """
    found: list[dict[str, str]] = []
    for raw_component in configured_quote_components(
        source_name=source_name,
        evidence_type=evidence_type,
        raw_payload=raw_payload,
        expected_symbol=expected_symbol,
    ):
        symbol = str(raw_component["symbol"]).upper()
        current, previous = raw_component["current"], raw_component["previous"]
        normalized = _normalized_decimal((current - previous) / previous)
        if normalized is None:
            continue
        # Preserve both source values and their canonical scalar hashes.  The
        # BOARD verifier recomputes the change from these exact raw values.
        found.append({
            "symbol": symbol,
            "value": normalized,
            "current": _normalized_decimal(current),
            "previous": _normalized_decimal(previous),
            "current_sha256": _canonical_value_hash(_normalized_decimal(current)),
            "previous_sha256": _canonical_value_hash(_normalized_decimal(previous)),
        })
    return tuple(found)


def _news_items(payload: Mapping[str, Any]) -> Sequence[Any]:
    for key in ("data", "articles", "news"):
        candidate = payload.get(key)
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
            return candidate
    return ()


# A target such as "guidance cut to 5%" does not reveal the magnitude of the
# change.  Decision evidence needs an explicit adverse delta, not an endpoint.
_ADVERSE_CHANGE_PERCENT = re.compile(
    r"\b(?:cut|cuts|lowered|lowers|lower|reduced|reduces|reduce)\b.{0,80}?\b(?:by|of)\s+(\d{1,3}(?:\.\d+)?)\s*%"
    r"|\b(?:down|fell|fall)\b\s+(\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)


def _adverse_news_event(
    payload: Mapping[str, Any], *, source_name: str, symbol: str, as_of: str
) -> dict[str, str] | None:
    """Normalize only real Finnhub/Alpaca adverse news facts with a magnitude.

    Keywords alone are not decision evidence.  This avoids the old unsafe
    behaviour where a generic headline was silently assigned ``-1%``.
    """
    event = strict_loss_review_news_event(
        source_name=source_name,
        evidence_type="market_news" if source_name.lower() == "alpaca_news" else "company_news",
        payload=payload,
        as_of=as_of,
        quality="medium",
        now=_parse_timestamp(as_of),
    )
    if event is None:
        return None
    return {
        "event_category": event["event_category"],
        "direction": event["direction"],
        "impact_fraction": event["impact_fraction"],
    }


def _adverse_transcript_event(payload: Mapping[str, Any], *, symbol: str) -> dict[str, str] | None:
    if str(payload.get("symbol") or "").upper() != symbol:
        return None
    items = payload.get("transcript_items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        return None
    text = " ".join(str(item.get("content") or item.get("text") or "") for item in items if isinstance(item, Mapping)).lower()
    if not text or any(token in text for token in _POSITIVE_WORDS) or not _GUIDANCE_CUT.search(text):
        return None
    match = re.search(r"(?:guidance|outlook|revenue).{0,80}?(?:by|of)\s+(\d+(?:\.\d+)?)\s*%|(?:by|of)\s+(\d+(?:\.\d+)?)\s*%.{0,80}?(?:guidance|outlook|revenue)", text)
    value = next((entry for entry in (match.groups() if match else ()) if entry), None)
    if value is None or float(value) < 1:
        return None
    return {"event_category": "guidance_cut", "direction": "adverse", "change_fraction": _normalized_decimal(-float(value) / 100.0) or "-0.01"}


def _qualified_loss_review_evidence(
    provider_result: TickerProviderResearchResult,
    *,
    symbol: str,
    accepted_sources: Sequence[Mapping[str, Any]] = (),
) -> dict[str, bool]:
    """Return strict source-category facts for a possible autonomous decision.

    Generic quotes, cache/watchlist material, SEC submissions indexes, and
    connector-gap packets can still inform research.  They cannot falsely
    clear the three evidence blockers that an autonomous loss decision needs.
    """
    result = {"market": False, "company_news": False, "filing": False}
    # Only descriptors produced by _accepted_source_descriptors represent
    # canonical, semantically-admitted normalized packets.
    for source in accepted_sources:
        evidence_type = source.get("evidence_type") if isinstance(source, Mapping) else None
        if evidence_type == "market_context":
            result["market"] = True
        elif evidence_type == "company_news":
            result["company_news"] = True
        elif evidence_type == "earnings_guidance_filing":
            result["filing"] = True
    return result


def _descriptor_by_type(
    descriptors: Sequence[Mapping[str, Any]], evidence_type: str
) -> Mapping[str, Any] | None:
    matches = [item for item in descriptors if item.get("evidence_type") == evidence_type]
    return matches[0] if len(matches) == 1 else None


def _exact_reason_reference(descriptor: Mapping[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(descriptor, Mapping):
        return None
    values = {key: descriptor.get(key) for key in ("packet_id", "path", "sha256")}
    if all(isinstance(value, str) and value for value in values.values()):
        return values  # type: ignore[return-value]
    return None


def _read_current_supervisor_binding(
    *,
    hourly_packet_path: str | Path,
    evidence_root: str | Path | None,
) -> dict[str, Any] | None:
    if evidence_root is None:
        return None
    try:
        root = _safe_root(evidence_root)
        relative, raw, _packet = _read_contained_json(root, hourly_packet_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _normalized_source_payload(
    descriptor: Mapping[str, Any] | None,
    *,
    evidence_root: str | Path | None,
) -> Mapping[str, Any] | None:
    if not isinstance(descriptor, Mapping) or evidence_root is None:
        return None
    try:
        root = _safe_root(evidence_root)
        _relative, raw, stored = _read_contained_json(root, descriptor.get("path"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if hashlib.sha256(raw).hexdigest() != descriptor.get("sha256"):
        return None
    payload = stored.get("payload")
    return payload if isinstance(payload, Mapping) else None


def _current_market_clock(clock: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """Normalize one fresh broker-clock read for immutable decision evidence."""
    if not isinstance(clock, Mapping):
        return None, "market clock is unavailable"
    raw = clock.get("raw_clock")
    raw_as_of = _parse_timestamp(raw.get("timestamp")) if isinstance(raw, Mapping) else None
    as_of = _parse_timestamp(clock.get("as_of"))
    captured_at = _parse_timestamp(clock.get("captured_at"))
    is_open = clock.get("is_open")
    if (
        not isinstance(raw, Mapping)
        or raw_as_of is None
        or as_of is None
        or captured_at is None
        or type(is_open) is not bool
        or raw.get("is_open") is not is_open
        or as_of.replace(microsecond=0) != raw_as_of.replace(microsecond=0)
    ):
        return None, "market clock is unavailable"
    # Clock response time and local capture time must agree.  A clock can be
    # closed and still support a decision-only SELL, but stale/malformed data
    # cannot.
    if abs((captured_at - as_of).total_seconds()) > 15 * 60:
        return None, "market clock is stale"
    raw_bytes = json.dumps(dict(raw), sort_keys=True, separators=(",", ":")).encode("utf-8")
    session = "regular" if is_open else "closed"
    return {
        "source_name": str(clock.get("source_name") or "alpaca_clock"),
        "source_ref": str(clock.get("source_ref") or "alpaca:/v2/clock"),
        "as_of": as_of.replace(microsecond=0).isoformat(timespec="seconds"),
        "captured_at": captured_at.replace(microsecond=0).isoformat(timespec="seconds"),
        "market_session": session,
        "is_open": is_open,
        "raw_clock": dict(raw),
        "raw_clock_sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }, ""


def _derive_current_loss_review(
    *,
    historical_review: Mapping[str, Any],
    hourly_packet_path: str | Path,
    accepted_sources: Sequence[Mapping[str, Any]],
    evidence_root: str | Path | None,
    market_clock: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the current authority candidate without changing historical review.

    The result is materialized inside the immutable refreshed evidence packet.
    It is the only review a BOARD recorder may evaluate.  If a precise binding
    is unavailable, this returns a structurally valid HOLD candidate instead
    of copying any historical scalar authority forward.
    """
    symbol = str(historical_review.get("symbol") or "").strip().upper()
    supervisor = _read_current_supervisor_binding(
        hourly_packet_path=hourly_packet_path,
        evidence_root=evidence_root,
    )
    market = _descriptor_by_type(accepted_sources, "market_context")
    news = _descriptor_by_type(accepted_sources, "company_news")
    filing = _descriptor_by_type(accepted_sources, "earnings_guidance_filing")
    market_payload = _normalized_source_payload(market, evidence_root=evidence_root)
    news_payload = _normalized_source_payload(news, evidence_root=evidence_root)
    filing_payload = _normalized_source_payload(filing, evidence_root=evidence_root)
    current_at = (
        str((market or {}).get("as_of") or (news or {}).get("as_of") or (filing or {}).get("as_of") or "")
    )
    clock_binding, _clock_blocker = _current_market_clock(market_clock)
    canonical_session = str((clock_binding or {}).get("market_session") or "unknown")
    complete = (
        supervisor is not None
        and isinstance(market_payload, Mapping)
        and isinstance(news_payload, Mapping)
        and isinstance(filing_payload, Mapping)
        and bool(symbol)
        and bool(current_at)
        and clock_binding is not None
    )
    spy = market_payload.get("spy") if isinstance(market_payload, Mapping) else None
    qqq = market_payload.get("qqq") if isinstance(market_payload, Mapping) else None
    sector = market_payload.get("sector_relative") if isinstance(market_payload, Mapping) else None
    current_price = _normalized_decimal(historical_review.get("current_price"))
    average_entry = _normalized_decimal(historical_review.get("average_entry_price"))
    spy_value = spy.get("value") if isinstance(spy, Mapping) else None
    qqq_value = qqq.get("value") if isinstance(qqq, Mapping) else None
    sector_relative = sector.get("value") if isinstance(sector, Mapping) else None
    reason_source = _exact_reason_reference(filing)
    target_vs_spy = market_payload.get("target_relative_to_spy") if isinstance(market_payload, Mapping) else None
    target_vs_qqq = market_payload.get("target_relative_to_qqq") if isinstance(market_payload, Mapping) else None
    if not all(
        _normalized_decimal(value) is not None
        for value in (current_price, average_entry, spy_value, qqq_value, sector_relative, target_vs_spy, target_vs_qqq)
    ):
        complete = False
    # A provider-reported guidance cut is a dedicated, structured production
    # fact.  Generic adverse filings and generic news never become
    # ``thesis_invalidated``.  Use the narrower, directly proven taxonomy.
    filing_category = filing_payload.get("event_category") if isinstance(filing_payload, Mapping) else None
    filing_direction = filing_payload.get("direction") if isinstance(filing_payload, Mapping) else None
    filing_change = filing_payload.get("change_fraction") if isinstance(filing_payload, Mapping) else None
    news_category = news_payload.get("event_category") if isinstance(news_payload, Mapping) else None
    news_direction = news_payload.get("direction") if isinstance(news_payload, Mapping) else None
    news_impact = news_payload.get("impact_fraction") if isinstance(news_payload, Mapping) else None
    if filing_category not in {"guidance_cut", "earnings_miss", "material_impairment", "adverse_filing_disclosure"} or filing_direction != "adverse" or _normalized_decimal(filing_change) is None:
        complete = False
    if news_category not in {"guidance_cut", "material_contract_loss", "regulatory_adverse_action", "thesis_invalidator"} or news_direction != "adverse" or _normalized_decimal(news_impact) is None:
        complete = False
    blockers = [] if complete else ["refreshed evidence is incomplete"]
    execution_eligible = bool(complete and (clock_binding or {}).get("is_open") is True)
    execution_blockers = [] if execution_eligible else [
        "market session is not tradeable for a live loss exit"
    ] if complete else ["decision evidence is incomplete"]
    return {
        "schema": "tradingagents.refreshed_loss_review.v1",
        "symbol": symbol,
        "original_supervisor": {
            "decision_id": historical_review.get("decision_id"),
            **(supervisor or {}),
        },
        "market_session": canonical_session,
        "market_clock": clock_binding,
        "current_evidence_at": current_at,
        "evidence_generated_at": current_at,
        "current_price": current_price,
        "average_entry_price": average_entry,
        # `allowed` remains the historical compatibility alias for a trade
        # decision.  It never means permission to submit an order.
        "allowed": bool(complete),
        "trade_decision_allowed": bool(complete),
        "execution_eligible": execution_eligible,
        "execution_blockers": execution_blockers,
        "allowed_exit_reason": "earnings_or_guidance_break" if complete else None,
        "allowed_exit_reason_source": reason_source if complete else None,
        "current_thesis_status": (
            "Structured guidance evidence broke the original entry thesis."
            if complete else "Refreshed evidence is incomplete; HOLD remains safer."
        ),
        "why_hold_is_worse_than_sell": (
            "A current, adverse guidance event is bound to the issuer and outweighs recovery hope."
            if complete else "Current evidence does not prove SELL is better than HOLD."
        ),
        "confidence": "0.82" if complete else "0.00",
        # Keep the public compact reason stable.  The detailed immutable
        # clock binding below is independently revalidated by the BOARD; a
        # missing or stale clock still produces HOLD, never a silent sell.
        "blockers": blockers,
        "blocked_reasons": list(blockers),
        "broad_market_context": {"SPY": _normalized_decimal(spy_value), "QQQ": _normalized_decimal(qqq_value)},
        "relative_performance_vs_SPY": _normalized_decimal(target_vs_spy),
        "relative_performance_vs_QQQ": _normalized_decimal(target_vs_qqq),
        "sector_or_peer_context": {
            "sector": loss_review_sector_proxy(symbol),
            "relative_performance": _normalized_decimal(sector_relative),
        },
        "company_news_event_category": news_category,
        "company_news_direction": news_direction,
        "company_news_impact_fraction": _normalized_decimal(news_impact),
        "filing_event_category": filing_category,
        "filing_direction": filing_direction,
        "filing_change_fraction": _normalized_decimal(filing_change),
        "why_this_is_not_broad_market_red_day_noise": (
            "The bound issuer guidance event supplies company-specific adverse evidence."
            if complete else "Company-specific versus broad-market damage is unresolved."
        ),
        "source_packet_ids": [str(item.get("packet_id")) for item in accepted_sources],
    }


def _infer_current_thesis_status(
    *,
    review: Mapping[str, Any],
    ranked_reason: str,
    position: Mapping[str, Any] | None,
    entry_context: Mapping[str, Any] | None,
    has_refreshed_evidence: bool,
) -> tuple[str, dict[str, Any]]:
    current_thesis_status = str(review.get("current_thesis_status") or "").strip()
    if current_thesis_status:
        return current_thesis_status, {
            "status": current_thesis_status,
            "drivers": ["supervisor provided current_thesis_status"],
            "approval_effect": "advisory_only_not_loss_exit_approval",
            "requires_board_decision": True,
        }

    drivers: list[str] = []
    ranked_reason_lower = ranked_reason.lower()
    if "falling-knife" in ranked_reason_lower or "sharp drop" in ranked_reason_lower:
        drivers.append("current candidate is flagged as falling-knife/sharp-drop watch")

    entry_reason_lower = str((entry_context or {}).get("entry_reason") or "").lower()
    if any(
        marker in entry_reason_lower
        for marker in ("momentum", "time-sensitive", "high-conviction")
    ):
        drivers.append("prior entry thesis was momentum or time-sensitive")

    current_price = _float_value(
        review.get("current_price") or (position or {}).get("current_price")
    )
    average_entry = _float_value(
        review.get("average_entry_price") or (position or {}).get("avg_entry_price")
    )
    if (
        current_price is not None
        and average_entry is not None
        and current_price < average_entry
    ):
        drivers.append("position is below average entry price")

    if "current candidate is flagged as falling-knife/sharp-drop watch" in drivers:
        return "thesis_under_pressure_falling_knife_watch", {
            "status": "thesis_under_pressure_falling_knife_watch",
            "drivers": drivers,
            "approval_effect": "advisory_only_not_loss_exit_approval",
            "requires_board_decision": True,
        }

    unresolved_status = (
        "unresolved_from_refreshed_evidence; BOARD must decide whether the original thesis is broken"
        if has_refreshed_evidence
        else "unresolved_no_refreshed_evidence"
    )
    return unresolved_status, {
        "status": unresolved_status,
        "drivers": drivers,
        "approval_effect": "advisory_only_not_loss_exit_approval",
        "requires_board_decision": True,
    }


def _loss_exit_confidence_tier(confidence: float) -> str:
    if confidence >= 0.75:
        return "medium"
    if confidence >= 0.55:
        return "low"
    return "none"


def _infer_loss_exit_candidate(
    *,
    thesis_status_evidence: Mapping[str, Any],
    ranked_reason: str,
    entry_context: Mapping[str, Any] | None,
    position: Mapping[str, Any] | None,
    review: Mapping[str, Any],
    has_market_context: bool,
    has_company_context: bool,
    source_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Infer a BOARD-only loss-exit candidate without granting approval."""
    drivers: list[str] = []
    status = str(thesis_status_evidence.get("status") or "")
    status_drivers = _strings(thesis_status_evidence.get("drivers"))
    ranked_reason_lower = ranked_reason.lower()
    entry_reason_lower = str((entry_context or {}).get("entry_reason") or "").lower()

    if (
        status == "thesis_under_pressure_falling_knife_watch"
        or "falling-knife" in ranked_reason_lower
        or "sharp drop" in ranked_reason_lower
    ):
        drivers.append("current candidate is flagged as falling-knife/sharp-drop watch")
    if (
        "prior entry thesis was momentum or time-sensitive" in status_drivers
        or any(marker in entry_reason_lower for marker in ("momentum", "time-sensitive"))
    ):
        drivers.append("prior entry thesis was momentum or time-sensitive")

    current_price = _float_value(
        review.get("current_price") or (position or {}).get("current_price")
    )
    average_entry = _float_value(
        review.get("average_entry_price") or (position or {}).get("avg_entry_price")
    )
    if (
        "position is below average entry price" in status_drivers
        or (
            current_price is not None
            and average_entry is not None
            and current_price < average_entry
        )
    ):
        drivers.append("position is below average entry price")
    if has_market_context and has_company_context and source_refs:
        drivers.append("refreshed market and company evidence attached")
    if (entry_context or {}).get("holding_period_trading_days") is not None:
        drivers.append("holding period is available")

    has_required_driver_set = all(
        item in drivers
        for item in (
            "current candidate is flagged as falling-knife/sharp-drop watch",
            "prior entry thesis was momentum or time-sensitive",
            "position is below average entry price",
            "refreshed market and company evidence attached",
        )
    )
    if not has_required_driver_set:
        return {
            "allowed_exit_reason_candidate": None,
            "allowed_exit_reason_source": None,
            "confidence": "0.00",
            "confidence_tier": "none",
            "reason_summary": (
                "No BOARD loss-exit candidate: refreshed evidence does not yet "
                "prove a thesis break or superior capital reuse."
            ),
            "drivers": drivers,
            "approval_effect": "board_review_input_not_loss_exit_approval",
            "requires_board_decision": True,
            "requires_tradeable_session": True,
            "can_submit_orders": False,
        }

    confidence = 0.42
    confidence += 0.08  # thesis status under pressure
    confidence += 0.07  # falling-knife/sharp-drop evidence
    confidence += 0.05  # entry thesis was momentum/time-sensitive
    confidence += 0.05  # below average entry
    confidence += 0.05  # refreshed market evidence
    confidence += 0.05  # refreshed company/filing evidence
    confidence += (
        0.03
        if (entry_context or {}).get("holding_period_trading_days") is not None
        else 0
    )
    confidence = min(confidence, 0.78)
    return {
        "allowed_exit_reason_candidate": "thesis_invalidated",
        "allowed_exit_reason_source": "refreshed_loss_review_evidence",
        "confidence": f"{confidence:.2f}",
        "confidence_tier": _loss_exit_confidence_tier(confidence),
        "reason_summary": (
            "Prior momentum/time-sensitive thesis is under pressure while the "
            "current candidate is a falling-knife watch below average entry."
        ),
        "drivers": drivers,
        "approval_effect": "board_review_input_not_loss_exit_approval",
        "requires_board_decision": True,
        "requires_tradeable_session": True,
        "can_submit_orders": False,
    }


def _pre_registered_policy_candidate(
    review: Mapping[str, Any],
) -> dict[str, Any] | None:
    parsed = parse_pre_registered_exit_policy_candidate(review)
    if parsed is None:
        return None
    return {
        "allowed_exit_reason_candidate": parsed["allowed_exit_reason"],
        "allowed_exit_reason_source": parsed["allowed_exit_reason_source"],
        "confidence": None,
        "confidence_tier": "pre_registered_policy",
        "reason_summary": parsed["exit_policy_rationale"],
        "drivers": [
            "pre-registered exit rule is a review-only candidate until the "
            "live gate binds a current broker position and clock"
        ],
        "approval_effect": "preserves_pre_registered_policy_candidate",
        "requires_board_decision": False,
        "requires_tradeable_session": True,
        "can_submit_orders": False,
    }


def _build_advisory_analysis(
    *,
    symbol: str,
    review: Mapping[str, Any],
    hourly_packet: Mapping[str, Any],
    provider_result: TickerProviderResearchResult,
    coverage_by_need: Mapping[str, int],
    accepted_sources: Sequence[Mapping[str, Any]] = (),
    entry_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    portfolio = hourly_packet.get("portfolio")
    live = portfolio.get("live") if isinstance(portfolio, Mapping) else {}
    position = (
        _find_symbol_entry(live.get("positions"), symbol)
        if isinstance(live, Mapping)
        else None
    )
    ranked = hourly_packet.get("ranked_candidates")
    if not ranked and isinstance(portfolio, Mapping):
        ranked = portfolio.get("ranked_candidates")
    ranked_entry = _find_symbol_entry(ranked, symbol)
    source_refs = _provider_packet_refs(provider_result)
    route_summary = [
        {
            "evidence_need": str(attempt.get("evidence_need") or ""),
            "source_name": str(attempt.get("source_name") or ""),
            "status": str(attempt.get("status") or ""),
            "packet_id": str(attempt.get("packet_id") or ""),
            "blocked": bool(attempt.get("blocked")),
        }
        for attempt in provider_result.route_attempts
        if isinstance(attempt, Mapping)
    ]

    qualified_evidence = _qualified_loss_review_evidence(
        provider_result, symbol=symbol, accepted_sources=accepted_sources
    )
    has_market_context = qualified_evidence["market"]
    has_fundamental_context = qualified_evidence["filing"]
    has_news_context = qualified_evidence["company_news"]
    ranked_reason = str((ranked_entry or {}).get("reason") or "").strip()
    current_thesis_status, thesis_status_evidence = _infer_current_thesis_status(
        review=review,
        ranked_reason=ranked_reason,
        position=position,
        entry_context=entry_context,
        has_refreshed_evidence=bool(source_refs),
    )
    loss_exit_candidate = _infer_loss_exit_candidate(
        thesis_status_evidence=thesis_status_evidence,
        ranked_reason=ranked_reason,
        entry_context=entry_context,
        position=position,
        review=review,
        has_market_context=has_market_context,
        has_company_context=has_news_context or has_fundamental_context,
        source_refs=source_refs,
    )

    advisory_analysis = {
        "purpose": (
            "advisory context for the autonomous portfolio BOARD; not a loss-exit approval"
        ),
        "symbol": symbol,
        "position_snapshot": {
            "qty": (position or {}).get("qty"),
            "market_value": (position or {}).get("market_value"),
            "current_price": review.get("current_price") or (position or {}).get("current_price"),
            "average_entry_price": review.get("average_entry_price")
            or (position or {}).get("avg_entry_price"),
            "unrealized_pl": review.get("unrealized_pl") or (position or {}).get("unrealized_pl"),
            "unrealized_pnl_percent": review.get("unrealized_pnl_percent")
            or (position or {}).get("unrealized_plpc"),
        },
        "entry_context": dict(entry_context or {}),
        "current_candidate_context": {
            "ranked_score": (ranked_entry or {}).get("score"),
            "day_change_pct": (ranked_entry or {}).get("day_change_pct"),
            "volume_ratio": (ranked_entry or {}).get("volume_ratio"),
            "reason": ranked_reason or None,
            "falling_knife_watch": "falling-knife" in ranked_reason.lower()
            or "sharp drop" in ranked_reason.lower(),
        },
        "market_context_attached": has_market_context,
        "company_context_attached": has_news_context or has_fundamental_context,
        "qualified_evidence": qualified_evidence,
        "hold_vs_sell_frame": (
            "SELL is better only if BOARD can prove thesis break, invalidator, or superior capital reuse; otherwise HOLD remains the default because this packet cannot approve a loss exit."
            if source_refs
            else "No refreshed source packet is attached, so HOLD remains the default."
        ),
        "broad_market_noise_frame": (
            "Refreshed market/news context is attached for BOARD to decide whether the drawdown is broad/sector noise or company-specific damage; broad weakness alone remains insufficient."
            if has_market_context
            else "No refreshed market/sector context is attached, so broad-market noise has not been ruled out."
        ),
        "current_thesis_status_candidate": current_thesis_status,
        "thesis_status_evidence": thesis_status_evidence,
        "loss_exit_candidate": loss_exit_candidate,
        "source_refs": source_refs,
        "route_summary": route_summary,
        "review_allowed_after_refresh": False,
        "forbidden_effects": list(LOSS_REVIEW_FORBIDDEN_EFFECTS),
    }
    policy_candidate = _pre_registered_policy_candidate(review)
    if policy_candidate is not None:
        advisory_analysis["loss_exit_candidate"] = policy_candidate
        advisory_analysis["review_allowed_after_refresh"] = False
        advisory_analysis["authority_source"] = (
            "pre_registered_policy_rule_candidate"
        )
        advisory_analysis["requires_board_decision"] = False
        advisory_analysis["decision_owner"] = "execution_operator"
        advisory_analysis["policy_rule_conflict"] = False
        return advisory_analysis

    policy_claimed = (
        review.get("policy_rule_exit") is True
        or str(review.get("allowed_exit_reason") or "")
        in {"policy_stop_floor", "policy_time_stop"}
    )
    if policy_claimed:
        # A structurally invalid policy claim is not rescued by advisory
        # evidence.  It stays a BOARD-owned HOLD/review input.
        advisory_analysis["authority_source"] = (
            "invalid_pre_registered_policy_rule_candidate"
        )
        advisory_analysis["requires_board_decision"] = True
        advisory_analysis["decision_owner"] = "portfolio_executive"
        advisory_analysis["policy_rule_conflict"] = True
        return advisory_analysis

    authority = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=advisory_analysis,
    )
    advisory_analysis["review_allowed_after_refresh"] = authority.allowed
    advisory_analysis["authority_source"] = authority.authority_source
    advisory_analysis["requires_board_decision"] = authority.requires_additional_decision
    advisory_analysis["decision_owner"] = authority.decision_owner
    advisory_analysis["policy_rule_conflict"] = (
        authority.authority_source == "invalid_pre_registered_policy_rule"
    )
    return advisory_analysis


def _refresh_resolved_blockers(
    blockers: Sequence[str],
    *,
    source_packet_ids: Sequence[str],
    coverage_by_need: Mapping[str, int],
    qualified_evidence: Mapping[str, bool] | None = None,
    entry_context: Mapping[str, Any] | None = None,
    thesis_status_candidate: str | None = None,
    loss_exit_candidate: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return loss-review blockers addressed by this read-only evidence refresh."""
    resolved: list[str] = []
    has_sources = bool(source_packet_ids)
    qualified = dict(qualified_evidence or {})
    has_news = qualified.get("company_news") is True
    has_earnings_or_filings = qualified.get("filing") is True
    has_market_context = qualified.get("market") is True
    has_hold_sell_context = has_sources and has_news and has_earnings_or_filings
    has_entry_reason = bool(str((entry_context or {}).get("entry_reason") or "").strip())
    has_holding_period = (entry_context or {}).get("holding_period_trading_days") is not None
    has_current_thesis_status = bool(
        thesis_status_candidate
        and not str(thesis_status_candidate).startswith("unresolved_")
    )
    has_loss_exit_reason = bool(
        str((loss_exit_candidate or {}).get("allowed_exit_reason_candidate") or "").strip()
    )
    has_loss_exit_reason_source = bool(
        str((loss_exit_candidate or {}).get("allowed_exit_reason_source") or "").strip()
    )
    has_loss_exit_confidence = (
        _float_value((loss_exit_candidate or {}).get("confidence")) or 0
    ) > 0
    for blocker in blockers:
        normalized = blocker.lower()
        if (
            ("allowed loss-exit reason source" in normalized and has_loss_exit_reason_source)
            or ("allowed loss-exit reason" in normalized and has_loss_exit_reason)
            or ("loss-exit confidence" in normalized and has_loss_exit_confidence)
            or ("source packet ids" in normalized and has_sources)
            or ("original buy thesis" in normalized and has_entry_reason)
            or ("holding period evidence" in normalized and has_holding_period)
            or ("current thesis status" in normalized and has_current_thesis_status)
            or ("company-specific news check" in normalized and has_news)
            or (
                "earnings/guidance/filing check" in normalized
                and has_earnings_or_filings
            )
            or ("spy/qqq/sector context" in normalized and has_market_context)
            or ("why hold is worse than sell" in normalized and has_hold_sell_context)
            or (
                "why this is not broad-market red-day noise" in normalized
                and has_market_context
            )
        ):
            resolved.append(blocker)
    return resolved


def build_loss_review_evidence_packet(
    *,
    hourly_packet_path: str | Path,
    hourly_packet: Mapping[str, Any],
    provider_result: TickerProviderResearchResult,
    evidence_needs: Sequence[str] = DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS,
    entry_context: Mapping[str, Any] | None = None,
    source_packet_paths: Mapping[str, str | Path] | None = None,
    decision_evidence_root: str | Path | None = None,
    market_clock: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> SourceEvidencePacket:
    """Build an advisory packet for autonomous portfolio BOARD loss-review analysis.

    The packet attaches fresh research references to the current hold, but it
    deliberately does not mutate the supervisor's loss_exit_review or approve a
    loss exit.
    """
    review = _loss_review_from_packet(hourly_packet)
    if review is None:
        raise ValueError("hourly packet does not contain evidence.loss_exit_review")
    symbol = str(review.get("symbol") or provider_result.symbol).strip().upper()
    source_ids = _source_packet_ids(provider_result)
    accepted_sources, raw_source_manifest, news_candidate_manifest = _accepted_source_descriptors(
        provider_result,
        source_packet_paths=source_packet_paths,
        evidence_root=decision_evidence_root,
        now=now,
    )
    blockers = _strings(review.get("blockers")) or _strings(review.get("blocked_reasons"))
    coverage_by_need = _coverage_by_need(provider_result)
    review_at = _parse_timestamp(
        review.get("evidence_generated_at") or hourly_packet.get("generated_at")
    )
    if entry_context is None:
        entry_context = find_prior_live_entry_context(
            hourly_packet_path,
            symbol=symbol,
            review_at=review_at,
        )
    advisory_analysis = _build_advisory_analysis(
        symbol=symbol,
        review=review,
        hourly_packet=hourly_packet,
        provider_result=provider_result,
        coverage_by_need=coverage_by_need,
        accepted_sources=accepted_sources,
        entry_context=entry_context,
    )
    current_loss_review = _derive_current_loss_review(
        historical_review=review,
        hourly_packet_path=hourly_packet_path,
        accepted_sources=accepted_sources,
        evidence_root=decision_evidence_root,
        market_clock=market_clock,
    )
    # Advisory output consumes the same derived Mapping that the recorder
    # authenticates.  It cannot introduce a second scalar reason source.
    advisory_analysis["current_loss_review"] = dict(current_loss_review)
    # A valid pre-registered mechanical exit remains its own authority path;
    # a failed discretionary BOARD refresh must not erase that existing policy
    # candidate.  Conversely, an advisory candidate can never create or
    # upgrade a policy exit.
    if advisory_analysis.get("authority_source") not in {
        "pre_registered_policy_rule",
        "pre_registered_policy_rule_candidate",
    }:
        advisory_analysis["current_thesis_status_candidate"] = current_loss_review[
            "current_thesis_status"
        ]
        advisory_analysis["loss_exit_candidate"] = {
            "allowed_exit_reason_candidate": current_loss_review["allowed_exit_reason"],
            "allowed_exit_reason_source": current_loss_review[
                "allowed_exit_reason_source"
            ],
            "confidence": current_loss_review["confidence"],
            "reason_summary": current_loss_review["why_hold_is_worse_than_sell"],
            "approval_effect": "board_review_input_not_loss_exit_approval",
            "requires_board_decision": True,
            "requires_tradeable_session": True,
            "can_submit_orders": False,
        }
    qualified_evidence = advisory_analysis.get("qualified_evidence")
    if not isinstance(qualified_evidence, Mapping):
        qualified_evidence = {}
    resolved_blockers = _refresh_resolved_blockers(
        blockers,
        source_packet_ids=source_ids,
        coverage_by_need=coverage_by_need,
        qualified_evidence=qualified_evidence,
        entry_context=entry_context,
        thesis_status_candidate=advisory_analysis.get("current_thesis_status_candidate"),
        loss_exit_candidate=advisory_analysis.get("loss_exit_candidate"),
    )
    resolved_set = set(resolved_blockers)
    remaining_blockers = [blocker for blocker in blockers if blocker not in resolved_set]
    # The immutable current review, not the frozen historic review, carries
    # the actual decision-window blockers.  Retain the historical list for
    # lineage/audit, but do not let it silently overrule a fully bound refresh.
    current_remaining = current_loss_review.get("blockers")
    if isinstance(current_remaining, list) and all(isinstance(item, str) for item in current_remaining):
        remaining_blockers = list(current_remaining)
    hourly_path = Path(hourly_packet_path)
    source_ref = f"local://{hourly_path.as_posix()}"
    payload = {
        "symbol": symbol,
        "hourly_packet_path": str(hourly_path),
        "supervisor_packet_path": (
            str(hourly_path.resolve().relative_to(Path(decision_evidence_root).resolve()).as_posix())
            if decision_evidence_root is not None
            and hourly_path.exists()
            and hourly_path.resolve().is_relative_to(Path(decision_evidence_root).resolve())
            else None
        ),
        "supervisor_decision_id": review.get("decision_id"),
        "hourly_generated_at": hourly_packet.get("generated_at"),
        "hourly_decision": hourly_packet.get("decision"),
        "submitted_order_count": len(hourly_packet.get("submitted") or []),
        "review_allowed": review.get("allowed") is True,
        "supervisor_review_authority": bounded_exit_authority_record(review),
        "supervisor_review_source_packet_ids": _strings(review.get("source_packet_ids")),
        "source_packet_ids": source_ids,
        # The complete direct-provider manifest is independent of the
        # normalized winner.  BOARD replays every native-news source from it,
        # then requires this eligible-candidate list to be exact before it
        # accepts the normalized company-news packet.
        "raw_source_packet_manifest": raw_source_manifest,
        "news_candidate_manifest": news_candidate_manifest,
        "accepted_sources": accepted_sources,
        "provider_summary_packet_id": (
            provider_result.summary_packet.packet_id
            if provider_result.summary_packet is not None
            else None
        ),
        "evidence_needs": [need for need in evidence_needs if need],
        "evidence_coverage_by_need": coverage_by_need,
        "route_attempt_count": len(provider_result.route_attempts),
        "entry_context": dict(entry_context or {}),
        "entry_context_found": bool(entry_context),
        "advisory_analysis": advisory_analysis,
        "current_loss_review": current_loss_review,
        "market_clock_snapshot": current_loss_review.get("market_clock"),
        "remaining_blockers_before_refresh": blockers,
        "resolved_blockers_by_refresh": resolved_blockers,
        "remaining_blockers": remaining_blockers,
        "review_snapshot": {
            "current_price": review.get("current_price"),
            "average_entry_price": review.get("average_entry_price"),
            "unrealized_pl": review.get("unrealized_pl"),
            "unrealized_pnl_percent": review.get("unrealized_pnl_percent"),
            "market_session": review.get("market_session"),
        },
        "next_action": "autonomous_hold",
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "forbidden_effects": list(LOSS_REVIEW_FORBIDDEN_EFFECTS),
    }
    return evidence_packet(
        source_name="loss_review_evidence",
        evidence_type="loss_review_evidence",
        subject=symbol,
        symbol=symbol,
        source_ref=source_ref,
        payload=payload,
        quality="medium" if source_ids else "unknown",
        request_fingerprint=request_hash(
            "LOCAL",
            source_ref,
            None,
            {
                "symbol": symbol,
                "hourly_generated_at": hourly_packet.get("generated_at"),
                "evidence_needs": [need for need in evidence_needs if need],
                "source_packet_ids": source_ids,
            },
        ),
        tool_route="local_loss_review_evidence",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "can_submit_orders": False,
            "source_packet_count": len(source_ids),
            "current_evidence_at": current_loss_review.get("current_evidence_at"),
        },
    )
