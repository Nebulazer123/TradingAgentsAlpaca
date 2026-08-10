"""Benchmark TradingAgents compact-context storage/read path.

The benchmark compares the current JSON/text cache against the rollback mode
(`TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE=0`) without changing packet schemas.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "results" / "performance_storage"


CHILD_CODE = r"""
import json
import time
from scripts import automation_context_snapshot as snapshot

snapshot.JSON_FILE_CACHE.clear()
started = time.perf_counter()
written = snapshot.write_context_files()
elapsed = time.perf_counter() - started
print(json.dumps({
    "elapsed_seconds": round(elapsed, 6),
    "written_count": len(written),
    "cache_stats": snapshot.JSON_FILE_CACHE.stats_dict(),
}))
"""


def _artifact_inventory() -> list[dict[str, Any]]:
    patterns = ["*.json", "*.jsonl", "*.csv", "*.db", "*.sqlite", "*.duckdb", "*.parquet"]
    rows: list[dict[str, Any]] = []
    for pattern in patterns:
        paths = [
            path
            for path in ROOT.rglob(pattern)
            if ".venv" not in path.parts
            and ".git" not in path.parts
            and "__pycache__" not in path.parts
        ]
        total_bytes = sum(path.stat().st_size for path in paths if path.exists())
        rows.append(
            {
                "pattern": pattern,
                "file_count": len(paths),
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / 1024 / 1024, 3),
            }
        )
    return rows


def _top_json_dirs(limit: int = 20) -> list[dict[str, Any]]:
    by_dir: dict[str, int] = {}
    for path in ROOT.rglob("*.json"):
        if ".venv" in path.parts or ".git" in path.parts:
            continue
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue
        if not relative.parts or relative.parts[0] not in {"results", "reports", "config", "docs", "n8n"}:
            continue
        key = str(Path(*relative.parts[:2])) if len(relative.parts) > 1 else relative.parts[0]
        by_dir[key] = by_dir.get(key, 0) + path.stat().st_size
    return [
        {"directory": key, "total_bytes": value, "total_mb": round(value / 1024 / 1024, 3)}
        for key, value in sorted(by_dir.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _run_mode(mode: str, *, runs: int) -> dict[str, Any]:
    env = os.environ.copy()
    if mode == "cache_disabled":
        env["TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE"] = "0"
    elif mode == "cache_enabled":
        env["TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE"] = "1"
    else:
        raise ValueError(f"unsupported mode: {mode}")

    observations: list[dict[str, Any]] = []
    for run_index in range(1, runs + 1):
        completed = subprocess.run(
            [sys.executable, "-c", CHILD_CODE],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            observations.append(
                {
                    "run": run_index,
                    "returncode": completed.returncode,
                    "stderr_tail": "\n".join(completed.stderr.splitlines()[-8:]),
                    "stdout_tail": "\n".join(completed.stdout.splitlines()[-8:]),
                }
            )
            continue
        payload = json.loads(completed.stdout)
        payload["run"] = run_index
        payload["returncode"] = completed.returncode
        observations.append(payload)

    successful = [item["elapsed_seconds"] for item in observations if item.get("returncode") == 0]
    return {
        "mode": mode,
        "run_count": runs,
        "success_count": len(successful),
        "median_seconds": round(statistics.median(successful), 6) if successful else None,
        "mean_seconds": round(statistics.mean(successful), 6) if successful else None,
        "min_seconds": round(min(successful), 6) if successful else None,
        "max_seconds": round(max(successful), 6) if successful else None,
        "observations": observations,
    }


def build_benchmark_packet(*, runs: int) -> dict[str, Any]:
    disabled = _run_mode("cache_disabled", runs=runs)
    enabled = _run_mode("cache_enabled", runs=runs)
    speedup = None
    if disabled.get("median_seconds") and enabled.get("median_seconds"):
        speedup = round(disabled["median_seconds"] / enabled["median_seconds"], 4)
    return {
        "schema": "tradingagents.performance_storage_benchmark.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "benchmark_target": "scripts/automation_context_snapshot.py --write",
        "runs_per_mode": runs,
        "speedup_median_cache_enabled_vs_disabled": speedup,
        "modes": [disabled, enabled],
        "artifact_inventory": _artifact_inventory(),
        "top_json_directories": _top_json_dirs(),
        "rollback": "The JSON/text cache is off by default. Leave TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE unset or set it to 0 to keep the proven faster default; set it to 1 only for large-artifact experiments.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark TradingAgents storage/context hot path")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()

    packet = build_benchmark_packet(runs=max(1, args.runs))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"storage-context-benchmark-{dt.datetime.now(dt.timezone.utc):%Y%m%d-%H%M%S}"
    json_path = args.output_dir / f"{stem}.json"
    latest_path = args.output_dir / "latest.json"
    packet["json_path"] = str(json_path.relative_to(ROOT))
    json_text = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    latest_path.write_text(json_text, encoding="utf-8")

    if args.json_output:
        print(json.dumps(packet, indent=2, sort_keys=True))
    else:
        print(
            textwrap.dedent(
                f"""\
                Benchmark: {packet['benchmark_target']}
                Runs per mode: {packet['runs_per_mode']}
                Median speedup: {packet['speedup_median_cache_enabled_vs_disabled']}
                Packet: {packet['json_path']}
                """
            ).strip()
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
