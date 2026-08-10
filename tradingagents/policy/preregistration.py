"""Sleeve pre-registration records for promotion evidence."""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_append_line, atomic_write_text

UTC = datetime.timezone.utc


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SleevePreregistration:
    registration_id: str
    sleeve: str
    hypothesis: str
    rules_summary: str
    benchmark: str
    min_sample_size: int
    power_target: str
    cost_assumptions: dict[str, Any]
    capacity_assumption_usd: str
    created_at: str
    live_authority: str = "none"
    analysis_only: bool = True


def build_registration_id(payload: dict[str, Any]) -> str:
    relevant = {
        key: payload[key]
        for key in sorted(payload)
        if key not in {"registration_id", "created_at"}
    }
    digest = hashlib.sha256(json.dumps(relevant, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"prereg-{digest}"


def build_sleeve_preregistration(
    *,
    sleeve: str,
    hypothesis: str,
    rules_summary: str,
    benchmark: str = "SPY",
    min_sample_size: int = 30,
    power_target: str = "detect positive benchmark-relative edge after costs",
    cost_assumptions: dict[str, Any] | None = None,
    capacity_assumption_usd: str = "0",
    created_at: str | None = None,
) -> SleevePreregistration:
    payload = {
        "sleeve": sleeve,
        "hypothesis": hypothesis,
        "rules_summary": rules_summary,
        "benchmark": benchmark.upper(),
        "min_sample_size": int(min_sample_size),
        "power_target": power_target,
        "cost_assumptions": cost_assumptions or {},
        "capacity_assumption_usd": str(capacity_assumption_usd),
        "created_at": created_at or _now_iso(),
        "live_authority": "none",
        "analysis_only": True,
    }
    payload["registration_id"] = build_registration_id(payload)
    return SleevePreregistration(**payload)


def append_preregistration(record: SleevePreregistration, path: str | Path) -> Path:
    output = Path(path)
    serialized = json.dumps(asdict(record), sort_keys=True)
    atomic_append_line(output, serialized)
    latest_path = output.parent / "latest-preregistration.json"
    atomic_write_text(latest_path, json.dumps(asdict(record), indent=2, sort_keys=True))
    return output


def load_preregistrations(path: str | Path) -> list[SleevePreregistration]:
    source = Path(path)
    if not source.exists():
        return []
    records = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(SleevePreregistration(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return records
