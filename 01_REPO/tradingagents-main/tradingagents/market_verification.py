"""Evidence packet helpers for one-time Alpaca execution checks."""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvidenceItem:
    category: str
    summary: str
    source: str
    observed_at: datetime.datetime | None = None


@dataclass(frozen=True)
class MarketVerificationPacket:
    run_id: str
    baseline_collected_at: datetime.datetime
    generated_at: datetime.datetime
    baseline_items: tuple[EvidenceItem, ...]
    delta_items: tuple[EvidenceItem, ...]
    decision: str
    email_to: str


def build_market_verification_packet(
    *,
    run_id: str,
    baseline_collected_at: datetime.datetime,
    generated_at: datetime.datetime,
    baseline_items: Sequence[EvidenceItem],
    delta_items: Sequence[EvidenceItem],
    decision: str,
    email_to: str,
) -> MarketVerificationPacket:
    return MarketVerificationPacket(
        run_id=run_id,
        baseline_collected_at=baseline_collected_at,
        generated_at=generated_at,
        baseline_items=tuple(baseline_items),
        delta_items=tuple(delta_items),
        decision=decision,
        email_to=email_to,
    )


def render_market_verification_markdown(packet: MarketVerificationPacket) -> str:
    lines = [
        f"# Market Verification Evidence Packet: {packet.run_id}",
        "",
        f"- Baseline collected at: {_format_dt(packet.baseline_collected_at)}",
        f"- Packet generated at: {_format_dt(packet.generated_at)}",
        f"- Email target: {packet.email_to}",
        f"- Decision: {packet.decision}",
        "",
        "## NOW Baseline",
        *_render_items(packet.baseline_items),
        "",
        "## Delta Since Baseline",
        *_render_items(packet.delta_items),
        "",
    ]
    return "\n".join(lines)


def render_email_summary(packet: MarketVerificationPacket) -> str:
    baseline_sources = _source_list(packet.baseline_items)
    delta_sources = _source_list(packet.delta_items)
    return "\n".join(
        [
            f"To: {packet.email_to}",
            f"Subject: Tuesday Alpaca Check: {packet.run_id}",
            f"Decision: {packet.decision}",
            f"Baseline collected at: {_format_dt(packet.baseline_collected_at)}",
            f"Packet generated at: {_format_dt(packet.generated_at)}",
            f"Baseline sources: {baseline_sources}",
            f"Delta sources: {delta_sources}",
        ]
    )


def write_market_verification_packet(
    packet: MarketVerificationPacket,
    *,
    output_dir: str | Path = "results/market_verification",
) -> tuple[Path, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe_filename(packet.run_id)}-{packet.generated_at:%Y%m%d-%H%M%S}"
    markdown_path = output_path / f"{stem}.md"
    json_path = output_path / f"{stem}.json"
    markdown_path.write_text(render_market_verification_markdown(packet), encoding="utf-8")
    json_path.write_text(
        json.dumps(packet_to_dict(packet), indent=2),
        encoding="utf-8",
    )
    return markdown_path, json_path


def packet_to_dict(packet: MarketVerificationPacket) -> dict:
    return {
        "run_id": packet.run_id,
        "baseline_collected_at": _format_dt(packet.baseline_collected_at),
        "generated_at": _format_dt(packet.generated_at),
        "email_to": packet.email_to,
        "decision": packet.decision,
        "baseline_items": [_item_to_dict(item) for item in packet.baseline_items],
        "delta_items": [_item_to_dict(item) for item in packet.delta_items],
    }


def _render_items(items: Iterable[EvidenceItem]) -> list[str]:
    rendered = []
    for item in items:
        observed = f" ({_format_dt(item.observed_at)})" if item.observed_at else ""
        rendered.append(
            f"- **{item.category}**{observed}: {item.summary} Source: {item.source}"
        )
    return rendered or ["- None recorded."]


def _source_list(items: Iterable[EvidenceItem]) -> str:
    sources = [item.source for item in items if item.source]
    return ", ".join(sources) if sources else "none"


def _item_to_dict(item: EvidenceItem) -> dict:
    return {
        "category": item.category,
        "summary": item.summary,
        "source": item.source,
        "observed_at": _format_dt(item.observed_at) if item.observed_at else None,
    }


def _format_dt(value: datetime.datetime) -> str:
    return value.isoformat(timespec="seconds")


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value)
