"""Slow Zep graph.search cache hydration for Mirror Fish Step 4 reports.

This intentionally uses graph.search only. It does not fetch all nodes/edges and
does not start Stage 3 or full Step 4 report generation.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")

from app.config import Config  # noqa: E402
from app.services.zep_report_cache import (  # noqa: E402
    MirrorFishQueryPack,
    ReportLock,
    ZepCacheConfig,
    ZepReportCache,
)
from app.services.zep_tools import ZepToolsService  # noqa: E402


DEFAULT_SIMULATION_ID = "sim_974459649906"
DEFAULT_GRAPH_ID = "mirofish_4a9df9ae8b184878"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hydrate Step 4 Zep graph.search cache slowly and resumably.")
    parser.add_argument("--simulation-id", default=DEFAULT_SIMULATION_ID)
    parser.add_argument("--graph-id", default=DEFAULT_GRAPH_ID)
    parser.add_argument("--max-queries", type=int, default=10, help="0 performs a dry planning/check run with no Zep calls.")
    parser.add_argument("--interval-seconds", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--cache-root", default=None)
    parser.add_argument("--force-live", action="store_true")
    parser.add_argument("--section", default=None, help="Optional exact required section title to hydrate first.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cache = ZepReportCache(
        ZepCacheConfig(
            graph_id=args.graph_id,
            cache_root=args.cache_root,
            default_interval_seconds=args.interval_seconds,
            max_live_calls=max(0, args.max_queries),
            max_live_calls_per_section=1,
            max_query_limit=args.limit,
        )
    )
    lock = ReportLock.acquire(cache.cache_root / "hydration.lock", owner=f"hydrate:{os.getpid()}")
    if not lock.acquired:
        print(f"Hydration already locked: {lock.current_owner}")
        return 2

    completed = 0
    try:
        pack = MirrorFishQueryPack.default()
        specs = pack.specs()
        if args.section:
            matching = [spec for spec in specs if spec.section == args.section]
            specs = [*matching, *[spec for spec in specs if spec.section != args.section]]

        if args.max_queries <= 0:
            paths = cache.write_hydration_summary(args.simulation_id, args.max_queries, completed)
            print(f"Dry hydration check only. Planned queries: {len(specs)}")
            print(f"Summary JSON: {paths['json']}")
            print(f"Summary MD: {paths['md']}")
            return 0

        tools = ZepToolsService(report_cache=cache, report_mode="zep_throttle_cached")
        for spec in specs[: args.max_queries]:
            outcome = cache.search(
                tool_name=f"hydration_{spec.category}",
                query=spec.query,
                limit=args.limit,
                scope="edges",
                live_search=lambda query, limit, scope: tools._zep_live_graph_search_payload(
                    args.graph_id, query, limit, scope
                ),
                force_live=args.force_live,
            )
            completed += 1
            print(f"{completed}/{args.max_queries} {spec.key}: {outcome.source} facts={len(outcome.facts)}")
            if outcome.pending:
                print(f"Pending: {outcome.skipped_reason}")

        paths = cache.write_hydration_summary(args.simulation_id, args.max_queries, completed)
        print(f"Summary JSON: {paths['json']}")
        print(f"Summary MD: {paths['md']}")
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
