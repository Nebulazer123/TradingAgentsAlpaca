# Performance Storage Ingestion Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the TradingAgents storage, ingestion, and compact-context read path faster and cheaper without reducing trading-agent reasoning quality, report detail, auditability, or evaluation coverage.

**Architecture:** Keep raw JSON/JSONL packets as the authoritative audit trail. Optimize only measured hot paths first: compact-context generation, latest-packet lookup, and repeated JSON/text metric reads. Add heavier SQLite/DuckDB indexes only after benchmarks show a real query workload that benefits from persistent indexes.

**Tech Stack:** Python stdlib `json`, `sqlite3` only if later justified, repo venv Python, Typer CLI through `.\.venv\Scripts\tradingagents.exe`, pytest, Ruff, compact artifacts under `results/_context/`, benchmark packets under `results/performance_storage/`.

---

## Current Checkpoint

- Original baseline before this slice: `scripts/automation_context_snapshot.py --write` subprocess median about `7.9154s` across 5 runs.
- Implemented first proven improvement: `write_context_files()` now refreshes generated source-routing/context once, then calls `collect_snapshot(refresh=False)` and `collect_metrics(refresh=False)`.
- Added opt-in `JsonFileCache` for JSON/text metric experiments, but left it off by default because the 5-run benchmark showed it could be slower or roughly tied on this workload.
- Latest repeatable benchmark packet: `results\performance_storage\storage-context-benchmark-20260608-111507.json`.
- Latest report-shape sanity benchmark: `results\performance_storage\storage-context-benchmark-20260608-111656.json`.
- Current artifact scale: about `7,520` JSON files, `249.876 MB` JSON, `7` JSONL files, `5.776 MB` JSONL, `62` CSV files, `9.917 MB` CSV, and `16` DB files, `74.715 MB`.
- Largest JSON directories: `results\overnight_plans` at about `110.503 MB`, `results\research_evidence` at about `52.183 MB`, and `results\n8n_evaluations` at about `16.931 MB`.

## Implemented Files

- Created: `tradingagents/storage/__init__.py`
- Created: `tradingagents/storage/json_cache.py`
- Created: `scripts/benchmark_storage_context.py`
- Created: `tests/test_storage_json_cache.py`
- Modified: `scripts/automation_context_snapshot.py`
- Modified: `tests/test_automation_context_snapshot.py`
- To write/update after each slice: `PERFORMANCE_STORAGE_AUDIT.md`

## Task 1: Keep The Proven Compact-Context Speedup

- [x] Add `collect_snapshot(refresh: bool = True)` and `collect_metrics(refresh: bool = True)`.
- [x] Change `write_context_files()` to call `refresh_generated_context_files()` once, then call both collectors with `refresh=False`.
- [x] Add `test_write_context_files_refreshes_generated_context_once`.
- [x] Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests\test_automation_context_snapshot.py::test_write_context_files_refreshes_generated_context_once -q
```

Expected: `1 passed`.

## Task 2: Keep JSON/Text Cache Opt-In, Not Default

- [x] Add `JsonFileCache` keyed by absolute path, mtime, and size.
- [x] Add env controls:
  - `TRADINGAGENTS_CONTEXT_SNAPSHOT_CACHE=1` enables the cache.
  - unset or `0` keeps the faster default for current workload.
  - `TRADINGAGENTS_STORAGE_CACHE` is a broader fallback switch.
- [x] Add tests for cache reuse, rewrite invalidation, text metrics, and env control.
- [x] Run:

```powershell
uv run --no-sync --with pytest python -m pytest tests\test_storage_json_cache.py -q
```

Expected: all tests pass.

## Task 3: Keep Benchmarking Repeatable

- [x] Add `scripts/benchmark_storage_context.py`.
- [x] Benchmark both modes:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_storage_context.py --runs 5 --json-output
.\.venv\Scripts\python.exe scripts\benchmark_storage_context.py --runs 3 --json-output
```

Expected:

- Packet written under `results\performance_storage\`.
- Both modes have `success_count == runs`.
- Packet includes artifact inventory, top JSON directories, per-run cache stats, and rollback text.

## Task 4: Document The Honest Result

- [x] Create `PERFORMANCE_STORAGE_AUDIT.md`.
- [x] Include current storage architecture, bottlenecks, benchmark results, chosen implementation, alternatives rejected, risks, and rollback.
- [ ] Update this plan after any later persistent index work.

## Task 5: Next High-Leverage Storage Work, Only If Benchmarked

- [ ] Build a persistent SQLite packet index only if a benchmark proves repeated cross-run latest-packet discovery or search is the bottleneck.
- [ ] First index only metadata, not full packets:
  - `path`
  - `label`
  - `directory`
  - `mtime_ns`
  - `size_bytes`
  - `generated_at`
  - `schema`
  - `raw_packet_path`
  - `top_symbol`
  - `status`
  - `submitted_count`
  - `issue_count`
  - `drilldown_reasons`
- [ ] Keep raw JSON/JSONL as source of truth.
- [ ] Add equivalence tests comparing JSON scan and SQLite query summaries.
- [ ] Only switch a hot caller to SQLite after the equivalence test and benchmark pass.

## Task 6: Do Not Optimize By Making The System Dumber

- [ ] Do not remove TradingAgents graph roles.
- [ ] Do not remove provider bundles, source-quality review, BOARD checks, live gates, self-heal checks, or n8n evaluation cases.
- [ ] Do not reduce report fields unless a compact output already points to the raw packet.
- [ ] Do not hide stale data; downrank or flag it.
- [ ] Do not replace raw audit logs with opaque databases.

## Verification Commands

Run after this slice:

```powershell
uv run --no-sync --with pytest python -m pytest tests\test_storage_json_cache.py tests\test_automation_context_snapshot.py::test_write_context_files_refreshes_generated_context_once tests\test_automation_context_snapshot.py::test_write_context_files_emits_field_provenance_for_every_compact_field tests\test_automation_context_snapshot.py::test_write_context_files_exposes_automation_memory_rollup_summary -q
uv run --no-sync --group static-analysis ruff check tradingagents\storage\json_cache.py tradingagents\storage\__init__.py scripts\automation_context_snapshot.py scripts\benchmark_storage_context.py tests\test_storage_json_cache.py tests\test_automation_context_snapshot.py
.\.venv\Scripts\python.exe scripts\benchmark_storage_context.py --runs 3 --json-output
.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write
```

## Acceptance Criteria

- The compact-context hot path is faster than the original baseline.
- Cache is not default-on unless it benchmarks faster.
- Raw packet schemas and report fields remain compatible.
- Focused tests and Ruff pass.
- Benchmark packet and audit doc explain rollback.
- Any persistent DB migration remains a future measured step, not an assumption.

