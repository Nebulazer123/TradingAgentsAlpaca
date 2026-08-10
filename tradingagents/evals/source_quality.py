"""Source-quality review packets for research evidence."""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tradingagents.research.source_quality import FORBIDDEN_EFFECTS, assess_source_quality

UTC = datetime.timezone.utc
DEFAULT_SOURCE_ROOTS = (
    Path("results/research_evidence"),
    Path("results/crawler_runs"),
    Path("results/research_batches"),
)
SKIP_DISCOVERY_NAME_PARTS = ("fixture", "sample")


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def discover_source_packet_paths(
    roots: Iterable[str | Path] = DEFAULT_SOURCE_ROOTS,
    *,
    limit: int = 250,
) -> list[Path]:
    paths: list[Path] = []
    for root_value in roots:
        root = Path(root_value)
        if not root.exists():
            continue
        paths.extend(
            path
            for path in root.glob("*.json")
            if path.is_file() and not any(part in path.stem.lower() for part in SKIP_DISCOVERY_NAME_PARTS)
        )
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _source_name(payload: Mapping[str, Any]) -> str:
    source_name = str(payload.get("source_name") or "").strip()
    if source_name:
        return source_name
    kind = str(payload.get("kind") or payload.get("crawler") or "").strip()
    if kind:
        return kind
    return "unknown"


def _as_of(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("as_of") or payload.get("generated_at")
    return str(value).strip() if value else None


def _blocked(payload: Mapping[str, Any]) -> bool:
    freshness = payload.get("freshness")
    if isinstance(freshness, Mapping) and freshness.get("blocked"):
        return True
    inner_payload = payload.get("payload")
    return bool(isinstance(inner_payload, Mapping) and inner_payload.get("blocked"))


def build_source_quality_review(
    packet_paths: Iterable[str | Path],
    *,
    current_time: datetime.datetime | None = None,
) -> dict[str, Any]:
    now = current_time.astimezone(UTC) if current_time else datetime.datetime.now(tz=UTC)
    decisions: list[dict[str, Any]] = []
    unreadable_paths: list[str] = []
    quality_counts: dict[str, int] = {}
    freshness_counts: dict[str, int] = {}
    for path_value in packet_paths:
        path = Path(path_value)
        payload = _read_json(path)
        if payload is None:
            unreadable_paths.append(str(path))
            continue
        decision = assess_source_quality(
            _source_name(payload),
            as_of=_as_of(payload),
            current_time=now,
        )
        quality_counts[decision.quality] = quality_counts.get(decision.quality, 0) + 1
        freshness_counts[decision.freshness_status] = (
            freshness_counts.get(decision.freshness_status, 0) + 1
        )
        decisions.append(
            {
                "path": str(path),
                "source_name": decision.source_name,
                "quality": decision.quality,
                "freshness_status": decision.freshness_status,
                "blocked": _blocked(payload),
                "ttl_hours": decision.ttl_hours,
                "role": decision.role,
                "allowed_effects": list(decision.allowed_effects),
                "forbidden_effects": list(decision.forbidden_effects),
                "reason": decision.reason,
            }
        )

    stale_count = freshness_counts.get("stale", 0)
    missing_count = freshness_counts.get("missing_or_invalid", 0)
    blocked_count = sum(1 for decision in decisions if decision.get("blocked"))
    stale_downrank_count = sum(
        1
        for decision in decisions
        if decision.get("freshness_status") == "stale" and "downrank" in (decision.get("allowed_effects") or [])
    )
    stale_low_or_unknown_count = sum(
        1
        for decision in decisions
        if decision.get("freshness_status") == "stale"
        and str(decision.get("quality") or "").lower() in {"low", "unknown"}
    )
    stale_safe_count = sum(
        1
        for decision in decisions
        if decision.get("freshness_status") == "stale"
        and (
            "downrank" in (decision.get("allowed_effects") or [])
            or str(decision.get("quality") or "").lower() in {"low", "unknown"}
        )
    )
    stale_needs_refresh_count = max(stale_count - stale_safe_count, 0)
    return {
        "schema_version": "1.0.0",
        "packet_id": f"source-quality-review-{uuid.uuid4().hex}",
        "kind": "source_quality_review",
        "generated_at": _now_iso(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "source_count": len(decisions),
        "unreadable_count": len(unreadable_paths),
        "stale_count": stale_count,
        "stale_downrank_count": stale_downrank_count,
        "stale_low_or_unknown_count": stale_low_or_unknown_count,
        "stale_safe_count": stale_safe_count,
        "stale_needs_refresh_count": stale_needs_refresh_count,
        "blocked_count": blocked_count,
        "missing_or_invalid_count": missing_count,
        "quality_counts": quality_counts,
        "freshness_counts": freshness_counts,
        "decisions": decisions,
        "unreadable_paths": unreadable_paths,
    }


def _render_markdown(review: Mapping[str, Any]) -> str:
    lines = [
        "# Source Quality Review",
        "",
        f"Generated: {review.get('generated_at')}",
        "",
        f"- Analysis only: {review.get('analysis_only')}",
        f"- Can submit orders: {review.get('can_submit_orders')}",
        f"- Source count: {review.get('source_count')}",
        f"- Stale count: {review.get('stale_count')}",
        f"- Stale safe/downranked count: {review.get('stale_safe_count')}",
        f"- Stale needs refresh count: {review.get('stale_needs_refresh_count')}",
        f"- Blocked count: {review.get('blocked_count')}",
        f"- Missing/invalid count: {review.get('missing_or_invalid_count')}",
        "",
        "## Quality Counts",
        "",
    ]
    for quality, count in sorted((review.get("quality_counts") or {}).items()):
        lines.append(f"- {quality}: {count}")
    lines.extend(["", "## Decisions", ""])
    for decision in review.get("decisions") or []:
        lines.append(
            "- "
            f"{decision.get('source_name')} "
            f"quality={decision.get('quality')} "
            f"freshness={decision.get('freshness_status')} "
            f"blocked={decision.get('blocked')} "
            f"path={decision.get('path')}"
        )
    return "\n".join(lines) + "\n"


def write_source_quality_review(
    review: Mapping[str, Any],
    *,
    output_dir: str | Path = Path("results/source_quality"),
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = root / f"source-quality-review-{stamp}.json"
    markdown_path = root / f"source-quality-review-{stamp}.md"
    payload = dict(review)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(markdown_path)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    compact = build_compact_source_quality_review(payload)
    compact_text = json.dumps(compact, indent=2, sort_keys=True)
    compact_path = root / f"source-quality-review-{stamp}.compact.json"
    compact_path.write_text(compact_text, encoding="utf-8")
    latest_path = root / "latest.json"
    latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (root / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    return payload


def build_compact_source_quality_review(
    review: Mapping[str, Any],
    *,
    sample_limit: int = 12,
) -> dict[str, Any]:
    """Build a compact stdout-safe source-quality summary.

    Full per-source decisions stay in the raw packet referenced by json_path; this keeps
    automation and n8n context small while preserving drilldown paths.
    """

    count_keys = (
        "source_count",
        "unreadable_count",
        "stale_count",
        "stale_downrank_count",
        "stale_low_or_unknown_count",
        "stale_safe_count",
        "stale_needs_refresh_count",
        "blocked_count",
        "missing_or_invalid_count",
    )
    counts = {key: int(review.get(key) or 0) for key in count_keys}
    decisions = list(review.get("decisions") or [])

    def decision_priority(decision: Mapping[str, Any]) -> tuple[int, str, str]:
        freshness = str(decision.get("freshness_status") or "")
        quality = str(decision.get("quality") or "")
        blocked = bool(decision.get("blocked"))
        needs_attention = blocked or freshness in {"stale", "missing_or_invalid"}
        return (
            0 if needs_attention else 1,
            freshness,
            quality,
        )

    sample_decisions: list[dict[str, Any]] = []
    for decision in sorted(
        (decision for decision in decisions if isinstance(decision, Mapping)),
        key=decision_priority,
    )[:sample_limit]:
        sample_decisions.append(
            {
                "path": decision.get("path"),
                "source_name": decision.get("source_name"),
                "quality": decision.get("quality"),
                "freshness_status": decision.get("freshness_status"),
                "blocked": bool(decision.get("blocked")),
                "role": decision.get("role"),
            }
        )

    next_action = "use_review_for_downranking"
    if (
        counts["stale_needs_refresh_count"]
        or counts["missing_or_invalid_count"]
        or counts["unreadable_count"]
    ):
        next_action = "refresh_or_downrank_flagged_sources"

    return {
        "schema": "compact_source_quality_review_v1",
        "packet_id": review.get("packet_id"),
        "kind": review.get("kind"),
        "generated_at": review.get("generated_at"),
        "analysis_only": bool(review.get("analysis_only")),
        "can_submit_orders": bool(review.get("can_submit_orders")),
        "execution_authority": review.get("execution_authority"),
        "raw_packet_path": review.get("json_path"),
        "json_path": review.get("json_path"),
        "markdown_path": review.get("markdown_path"),
        **counts,
        "counts": counts,
        "quality_counts": dict(review.get("quality_counts") or {}),
        "freshness_counts": dict(review.get("freshness_counts") or {}),
        "sample_decisions": sample_decisions,
        "sample_decision_count": len(sample_decisions),
        "decision_count": len(decisions),
        "next_action": next_action,
        "raw_field_groups": {
            "full_decisions": "decisions",
            "unreadable_paths": "unreadable_paths",
        },
    }
