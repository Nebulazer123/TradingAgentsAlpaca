# Fable Pass 2 — Agent Intelligence Brainstem (2026-06-10)

Mission: make the first learning loop trustworthy and closed —
forecasts → mechanically audited labels → calibrated scores → preregistered
hypotheses → supported/refuted priors → advisory context in future research.

## Headline finding: every first-light label was premature

The retro-audit proved the suspected `iloc[-1]` early-bar bias was not an edge
case — it affected **132 of 132** resolved labels:

- All resolved windows intended exit sessions of 2026-06-09 (129) or
  2026-06-10 (3), but at audit time (2026-06-10T05:29Z) the price feed had
  bars **only through 2026-06-08**. The first resolution (2026-06-10T00:08Z)
  silently measured every forecast one-to-two sessions short.
- Verdict: all 132 labels downgraded to `suspect` with
  `window_unverifiable` / `final_bar_missing`. **trusted_label_count = 0.**
- The annotation is self-healing: once the 06-09/06-10 bars land in the feed,
  re-running `research ledger-quality-audit` re-measures each label and either
  confirms it (`high`/`degraded`) or proves the outcome flipped
  (`reaudit_outcome_mismatch` → permanently `suspect`). Outcomes and scores
  are never rewritten; only quality tiers move.
- Evidence: `results/agent_intelligence/quality-audit-20260610.json`;
  pre-audit backup `results/agent_intelligence/ledger.backup-quality-audit-20260610-052944.jsonl`.

The same night, the audited resolve path **deferred all 12 newly-due
forecasts** (`final_bar_missing`) that the old code would have scored against
stale 06-08 bars: `results/agent_intelligence/second-resolution-20260610.json`
(newly_resolved 0, deferred 12, not_mature 4,640). Zero contamination.

## Lane 1 — Resolution Integrity (built)

New truth-quality layer `tradingagents/evals/resolution_quality.py`:

- `PriceWindow` — dated closes actually available per symbol (NaN/inf bars
  dropped at construction; a NaN close from yfinance crashed the first audit
  run and is now structurally impossible).
- `audit_resolution_window` — pure, deterministic audit of one resolution
  window. The benchmark (SPY) acts as the trading-calendar oracle:
  - weekend boundaries adjusted deterministically
    (`expected_entry_session`/`expected_exit_session`);
  - a final-session bar missing on both legs within `FINAL_BAR_GRACE_DAYS=2`
    of the expected session ⇒ defer `final_bar_missing` ("not printed yet");
    older ⇒ `assumed_market_holiday_at_window_end` (degraded);
  - a bar missing on one leg only is never a holiday ⇒ defer
    (`ticker_final_bar_missing` / `window_mismatch` / `entry_bar_missing`);
  - mid-window holidays and ticker/benchmark session-count mismatches are
    flagged (`missing_weekday_sessions_inside_window`, …) ⇒ `degraded`;
  - horizon recorded as `trading_days_weekend_adjusted` with expected vs
    actual session counts (the calendar/trading-day question is answered per
    label, machine-readably).
- `ResolutionWindow` / `ResolutionQualityReport` /
  `summarize_resolution_quality` — label quality is machine-readable;
  the summary separates `not_mature` / `deferred` (by reason) /
  `resolvable` (by quality tier) and reports `trusted_label_count`.

Ledger (`agent_intelligence_ledger.py`):

- `AgentForecast` extended (defaults keep legacy rows loading):
  `defer_reason`, `label_quality`, `quality_flags`, `resolution_window`
  (intended/expected/actual entry+exit dates for both legs,
  `final_bar_available`, session counts, horizon kind).
- `resolve_forecasts_with_quality(window_lookup=…)` — audited resolve path;
  defers instead of contaminating; stamps full window+quality metadata on
  every new label. Legacy `resolve_forecasts(price_lookup=…)` unchanged
  byte-for-byte (unaudited labels stay `label_quality=None`).
- `audit_resolved_forecasts` — the retro-audit used above.
- `load_ledger_with_stats` — corrupt JSONL lines counted, not silently eaten.
- `summarize_agent_scores` now emits `label_quality_counts`.

CLI (`cli/main.py`):

- `_ledger_window_lookup` (lru_cached) returns dated `PriceWindow`s.
- `research agent-ledger-resolve` / `agent-ledger-update` now resolve through
  the audited path, write `results/agent_intelligence/resolution_quality.json`
  and carry `resolution_quality` in their payloads.
- New `research ledger-quality-audit` — timestamped backup, retro-audit,
  suspect-id listing, corrupt-line count. Idempotent; re-run after the feed
  catches up to heal `window_unverifiable` labels.

## Lane 2 — Intelligence Motor Bridge (closed)

`tradingagents/research/overnight_context.py`:

- `build_agent_intelligence_packet` reads
  `results/agent_intelligence/summary.json` +
  `results/hypothesis_factory/priors.json` and emits an
  `agent_intelligence_advisory` SourceEvidencePacket: forecast/resolved/
  pending counts, outcome + label-quality counts, machine-readable influence
  weights/states, supported priors (machine list + rendered text via the
  canonical renderers, so the literal advisory-only language flows through),
  explicit `summary_status`/`priors_status` (`ok|missing|malformed|
  no_supported_priors`), `can_submit_orders=false`,
  `execution_authority=none`. Never raises.
- Wired into `build_overnight_research_context_packets` /
  `write_overnight_research_context` (`include_agent_intelligence=True`),
  the research-context summary (`summary["agent_intelligence"]`), and the
  compact `overnight_prior_feed_v1` (weights + top-8 priors +
  `carry_forward_scope`).
- Overnight CLI flag: `--include-agent-intelligence/--no-agent-intelligence`.

Verified against the real files: the next overnight run will see
132 resolved / 4,652 pending, `label_quality_counts {suspect: 132}`, earned
weights (market_analyst 0.62, …), and "no out-of-sample supported research
priors yet; use neutral weighting." When a hypothesis becomes supported, the
prior and its multiplier appear in this packet automatically.

## Hypothesis Factory hardening

- `minable_forecasts` gate: `suspect` labels are **never** evidence; with
  `require_audited_labels` (CLI/run default **on**) unaudited legacy labels
  are excluded too — the factory learns only from mechanically audited
  windows. Mining and out-of-sample evaluation share the gate.
- Real run (`results/hypothesis_factory/second-run-20260610.json`):
  resolved 132 → minable 0, excluded_suspect 132, mined 0. The two
  preregistered hypotheses (`hyp-434cc01a6433d705`, `hyp-319a01e819d1a54f`)
  keep their status and out-of-sample clocks — no audited evidence has
  arrived yet, and the factory says so instead of pretending.
- `priors.json` / `summary.json` now carry `can_submit_orders=false`;
  corrupt store lines are counted in the run payload
  (`corrupt_store_line_count`).

## Validation (2026-06-10)

- 54 focused tests pass: `tests/test_resolution_quality.py` (21, new),
  `tests/test_agent_intelligence_ledger.py` (17, +3 CLI),
  `tests/test_hypothesis_factory.py` (11, +4),
  `tests/test_overnight_context.py` (5, new).
- `uv run --no-sync python -m compileall -q cli tradingagents tests` — pass.
- `ruff check --select E9,F63,F7,F82 cli tradingagents tests` — pass.
- Full `ruff check` clean on all nine touched files.
- 95 unrelated CLI-importing tests (`test_alpaca_supervisor`,
  `test_signal_processing`) unaffected.

Safety boundary held: no orders, no emails, no dead-man refresh, no staging
or commits, no live-authority changes. Every new payload carries
`analysis_only=true`, `can_submit_orders=false`, `execution_authority=none`.

## Operating cadence (analysis-only, idempotent)

```powershell
uv run --no-sync python -m cli.main research ledger-quality-audit --json-output
uv run --no-sync python -m cli.main research agent-ledger-resolve --json-output
uv run --no-sync python -m cli.main research hypothesis-factory --json-output
```

Quality-audit first: it heals `window_unverifiable` labels as the feed
catches up, which is what unlocks minable evidence for the factory.

## What remains (delegated)

See `2026-06-10-codex-packet-agent-intelligence-wiring.md`. Packet A from
2026-06-09 (overnight-context injection) is superseded — done by this pass.
