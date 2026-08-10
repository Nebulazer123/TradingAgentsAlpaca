# TradingAgents Performance Storage Audit

Generated: 2026-06-08

## Executive Summary

The highest-confidence bottleneck found in this pass is the compact-context generator, `scripts/automation_context_snapshot.py`. It is on the hot path for hooks, n8n, self-heal, controller checks, and supervisor context refreshes. The repo does have many JSON/JSONL artifacts, but the right first move was not a broad SQLite/DuckDB migration. The measured improvement was simpler: avoid duplicate generated-context refreshes inside one `--write` run.

Implemented:

- `write_context_files()` now refreshes generated source/context files once instead of refreshing again inside both `collect_snapshot()` and `collect_metrics()`.
- A reversible `JsonFileCache` storage helper exists for opt-in large-artifact experiments, but it is disabled by default because current benchmarks do not prove it should be on.
- A repeatable benchmark script now records timing, artifact inventory, cache stats, and rollback guidance.

No trading analysis quality was reduced. Raw JSON/JSONL packets remain the audit trail. No agents, debate steps, validation checks, provider bundles, citations, BOARD review, self-heal, or n8n evaluation coverage were removed.

## Current Storage And Artifact Architecture

The repo currently uses:

- JSON packets under `results/` for most supervisor, overnight, n8n, source-quality, self-heal, BOARD, process-review, and evaluation artifacts.
- JSONL for append-only ledgers such as Agent Intelligence Ledger and replay/eval rows.
- CSV for evaluation tables, market-derived fixtures, and exported datasets.
- Existing DB files, mostly external/local tool state, not currently used as the main TradingAgents packet query path.
- Compact JSON sidecars such as `latest-compact.json` as the token-efficient first read.
- `results/_context/latest-summary.json` and `latest-flags.json` as the primary automation context router.

Measured artifact inventory from the latest benchmark:

| Pattern | Count | Size |
| --- | ---: | ---: |
| `*.json` | 7,520 | 249.876 MB |
| `*.jsonl` | 7 | 5.776 MB |
| `*.csv` | 62 | 9.917 MB |
| `*.db` | 16 | 74.715 MB |
| `*.sqlite` | 0 | 0 MB |
| `*.duckdb` | 0 | 0 MB |
| `*.parquet` | 0 | 0 MB |

Largest JSON directories:

| Directory | Size |
| --- | ---: |
| `results\overnight_plans` | 110.503 MB |
| `results\research_evidence` | 52.183 MB |
| `results\n8n_evaluations` | 16.931 MB |
| `results\source_quality` | 10.229 MB |
| `results\premarket_briefs` | 9.709 MB |
| `results\research_provider_cache` | 9.394 MB |
| `results\overnight_probes` | 7.548 MB |
| `results\hourly_supervisor` | 6.246 MB |
| `results\mirofish_handoff` | 5.225 MB |
| `results\research_batches` | 4.086 MB |

## Bottlenecks Found

### 1. Compact-context generation repeated work

`scripts/automation_context_snapshot.py --write` is frequently invoked by automation/control-plane paths. Before this slice it refreshed generated context inside `collect_snapshot()` and again inside `collect_metrics()` during a single write.

Original subprocess baseline before the fix:

- 5 runs of `.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write`
- Median: `7.9154s`
- Mean: `7.9278s`
- Min: `6.0945s`
- Max: `9.5440s`

Direct instrumentation before the fix showed:

- `read_json` calls: about 300
- unique JSON paths: about 100
- file metric calls: about 102
- unique metric paths: about 52
- generated context refresh calls: 2

### 2. JSON artifacts are large, but not every path needs a database

The largest directories are overnight plans and research evidence. These should remain raw audit packets. A persistent SQLite index could help later for cross-run historical search, but the immediate hot path only needs latest compact packets and a small number of recent records.

### 3. Naive JSON cache was not a clear default win

The new `JsonFileCache` hit about 58.7% on JSON reads and 48.0% on text metrics, but path/stat/key overhead made it slower or only tied in real runs. It remains opt-in for large-artifact experiments.

## Implementation Chosen

Chosen first improvement: faster JSON path plus duplicate-refresh removal.

Files changed:

- `scripts/automation_context_snapshot.py`
  - Added `refresh` parameters to `collect_snapshot()` and `collect_metrics()`.
  - `write_context_files()` now calls `refresh_generated_context_files()` once and then calls collectors with `refresh=False`.
  - Uses `JsonFileCache` helper for JSON/text reads, but cache is off unless explicitly enabled.
  - Copies mutable dicts before writing compact sidecars so cached values are not mutated.
- `tradingagents/storage/json_cache.py`
  - New focused storage helper with opt-in parsed JSON/text metric cache.
  - Cache key includes resolved path, `mtime_ns`, and file size.
  - Env controls:
    - `TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE=1` enables cache.
    - unset or `0` keeps cache off.
    - `TRADINGAGENTS_STORAGE_CACHE` is a broader fallback switch.
- `scripts/benchmark_storage_context.py`
  - Runs real compact-context builds in `cache_disabled` and `cache_enabled` modes.
  - Writes benchmark packets to `results/performance_storage/`.
  - Includes artifact inventory and top JSON directories.
- `tests/test_storage_json_cache.py`
  - Tests cache reuse, rewrite invalidation, text metrics, and env switches.
- `tests/test_automation_context_snapshot.py`
  - Tests generated context refresh happens once during `write_context_files()`.

## Benchmark Results

Repeatable benchmark packets:

- `results\performance_storage\storage-context-benchmark-20260608-111507.json`
- `results\performance_storage\storage-context-benchmark-20260608-111656.json`

The best comparison is the 3-run packet after the cache was made opt-in:

| Mode | Median | Mean | Notes |
| --- | ---: | ---: | --- |
| cache disabled | 5.207237s | 5.406522s | default path; duplicate-refresh fix active |
| cache enabled | 5.193592s | 5.151829s | opt-in; 58.7% JSON hit rate |

The benchmark shows the cache is not harmful in that 3-run sample, but the previous 5-run sample showed it could be slower:

| Mode | Median | Mean | Notes |
| --- | ---: | ---: | --- |
| cache disabled | 4.415212s | 4.419949s | default path |
| cache enabled | 5.068119s | 5.105772s | slower despite hits |

Decision: keep cache off by default. The durable win is the duplicate-refresh fix, which reduces the original baseline from about `7.9s` median to roughly `4.4s-5.2s` median depending on run variance.

## Alternatives Rejected For Now

### SQLite working store

Rejected for this slice because the benchmarked hot path did not require persistent indexed queries yet. A SQLite index is still a strong candidate for historical packet search, Agent Intelligence Ledger queries, and large source-quality history, but it should be introduced behind an equivalence test and a benchmark proving it beats the JSON path.

### DuckDB analytical store

Rejected for this slice because current hot path is latest-packet/control-plane context, not large analytical scans. DuckDB may become useful for walk-forward, paper tournament, and source-quality trend analysis if those datasets grow into table-heavy workloads.

### Rust helper

Rejected for this slice because Python duplicate-work removal already produced a meaningful win and Rust packaging/integration complexity is not justified yet.

### Default-on JSON object cache

Rejected by benchmark. It can be enabled for experiments, but not as the default.

## Rollback Instructions

To disable the optional JSON/text cache:

```powershell
$env:TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE = "0"
```

or leave it unset, which is now the default.

To roll back the duplicate-refresh optimization, revert only the `collect_snapshot(refresh=...)`, `collect_metrics(refresh=...)`, and `write_context_files()` changes in `scripts/automation_context_snapshot.py`. That is not recommended unless a regression appears, because tests now cover the intended behavior.

## Quality Checks

Commands run:

```powershell
uv run --no-sync --with pytest python -m pytest tests\test_storage_json_cache.py tests\test_automation_context_snapshot.py::test_write_context_files_refreshes_generated_context_once tests\test_automation_context_snapshot.py::test_write_context_files_emits_field_provenance_for_every_compact_field tests\test_automation_context_snapshot.py::test_write_context_files_exposes_automation_memory_rollup_summary -q
uv run --no-sync --group static-analysis ruff check tradingagents\storage\json_cache.py tradingagents\storage\__init__.py scripts\automation_context_snapshot.py scripts\benchmark_storage_context.py tests\test_storage_json_cache.py tests\test_automation_context_snapshot.py
.\.venv\Scripts\python.exe -m compileall -q tradingagents\storage scripts\automation_context_snapshot.py scripts\benchmark_storage_context.py
.\.venv\Scripts\python.exe scripts\benchmark_storage_context.py --runs 5 --json-output
.\.venv\Scripts\python.exe scripts\benchmark_storage_context.py --runs 3 --json-output
.\.venv\Scripts\python.exe scripts\benchmark_storage_context.py --runs 1 --json-output
```

Passing checks:

- Focused pytest: `6 passed`.
- Ruff: `All checks passed`.
- Compileall: passed.
- Benchmark modes completed successfully.

## Remaining Bottlenecks

1. `results\overnight_plans` is the largest JSON directory at about 110 MB. Do not migrate it blindly; first benchmark repeated historical search or top-candidate lookup.
2. `results\research_evidence` is about 52 MB and is a better candidate for a metadata index because source-quality and provider-bundle overlays search recent records.
3. Agent Intelligence Ledger is JSONL and should get a SQLite index only when forecast resolution or influence queries become measurably slow.
4. n8n evaluation datasets are growing and may benefit from Data Table/API sync diffing instead of full replacement, but evaluation coverage must not be reduced.
5. Large `CONTEXT_ROUTER.md` and automation memories remain token-cost hotspots. Existing compact summaries help, but a content-hash summary cache could reduce repeated model context if prompts keep rereading unchanged docs.

## Recommended Next Optimization

Build a metadata-only SQLite packet index behind a feature flag, starting with `results\research_evidence` and `results\overnight_plans`.

Required first test:

- Generate summaries using the current JSON scan.
- Generate the same summaries using SQLite metadata.
- Assert semantic equivalence for path, generated_at, schema, symbol/top candidate, status, source name, gap counts, and drilldown reasons.
- Benchmark both paths with at least 5 runs.
- Keep raw JSON as source of truth and rebuild the index from raw packets.

Do not move trading decisions, prompts, reports, or raw audit trails into SQLite until equivalence and rollback are proven.

