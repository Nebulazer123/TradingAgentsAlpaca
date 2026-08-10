# Token Efficiency Audit

Date: 2026-06-02

Scope: repo/workflow efficiency for recurring TradingAgents/Alpaca automation
work. This is not a trading-methodology audit.

## Ranked Token Sinks

1. Repeated mental-model rebuilds across the same automation paths.
   Evidence: recurring commands and result folders are documented across
   `README.md`, `REPO_OVERVIEW.md`, `TRADING_METHODS_AND_AUTOMATIONS.md`, long
   automation prompts under `C:\cm\automations\*\automation.toml`, and growing
   automation memories. Fix first with `AGENTS.md`, `CONTEXT_ROUTER.md`, and the
   snapshot helper.

2. Large timestamped result packets are easy to over-read.
   Evidence: `results/overnight_plans/latest.json` is about 228 KB, many
   timestamped overnight JSON packets are over 200 KB each, and premarket briefs
   are often 45-55 KB each. Fix by summarizing latest packets first and opening
   full packets only for blockers, submissions, schema changes, or failed tickers.

3. Automation memories are growing into hidden context dumps.
   Evidence: `C:\cm\automations\hourly-market-supervisor\memory.md` is about
   111 KB and `paper-strategy-tournament-runner\memory.md` is about 50 KB.
   Fix by reading tails or compact summaries rather than whole files.

4. Root docs are useful but too broad for routine runs.
   Evidence: `README.md`, `REPO_OVERVIEW.md`, `TRADING_METHODS_AND_AUTOMATIONS.md`,
   `CODEX_HANDOFF_PROMPT.md`, and `CODEX_IMPLEMENTATION_SPEC.md` are all
   substantial and overlap on commands, safety constraints, and future strategy
   ideas. Fix by routing from `CONTEXT_ROUTER.md`; read sections only as needed.

5. Broad validation is tempting but often unnecessary.
   Evidence: Alpaca automation tests are concentrated in
   `tests/test_alpaca_cli.py`, `tests/test_alpaca_supervisor.py`,
   `tests/test_paper_tournament.py`, and `tests/test_alpaca_execution.py`.
   Fix by running targeted slices unless changing shared graph/dataflow behavior.

6. Chat reports can repeat packet contents.
   Evidence: daily reports and automation prompts request detailed balances,
   positions, P/L, rankings, blockers, and paths. Preserve detail in files, but
   keep chat to status, paths, submissions, blockers, and next inspection point.

## Measured Current Load

Approximation: `ceil(chars_or_bytes / 4)`. This is for ranking context weight,
not exact billing.

- Starter guidance is small: `AGENTS.md` about 1.6 KB, `CONTEXT_ROUTER.md`
  about 7.0 KB, and this audit about 3.4 KB before this update.
- Active automation prompts are roughly 1.8-3.4 KB each, and they repeat the
  same repo executable, result folders, safety constraints, and reporting rules.
- Automation memories are now a larger repeated source: the hourly supervisor
  memory is over 115 KB and the paper-tournament memory is over 54 KB.
- Latest result packets are much larger than the route docs: overnight latest is
  about 234 KB, premarket latest about 58 KB, paper tournament latest about
  37 KB, and the latest flagged hourly packet about 27 KB.
- `results/_context/` artifacts are compact by comparison: latest summary about
  5-6 KB, flags about 2 KB, recent deltas about 1-2 KB, and the automation index
  about 13 KB.

## Implemented Now

- `AGENTS.md`: compact repo-local start instructions.
- `CONTEXT_ROUTER.md`: automation routing map, context loading policy, and
  reporting contract.
- `scripts/automation_context_snapshot.py`: compact current-state summarizer.
- `results/_context/`: generated compact indexes and approval plan.
- `results/_context/latest-summary.json` now includes the new capability audit,
  research batch, market-mirror directory, crawler run, model telemetry report,
  promotion state, and Agent Intelligence Ledger summary packet families.
- `results/_context/latest-flags.json` now flags failed research quality gates,
  blocked/harmful model telemetry, crawler failures, and audit redaction/config
  problems without requiring raw packet reads first.
- `results/_context/recent-deltas.md` now watches the new research fields:
  audit redaction/missing env count, research quality gates, crawler status/page
  counts, model usefulness/outcome counts, promotion-state counts, and
  agent-ledger forecast counts.
- `tests/test_automation_context_snapshot.py` covers the new compact-summary
  packet families.
- This audit file as a durable diagnosis record.

## Left Alone

- Existing automation prompts under `C:\cm\automations\...`; changing live
  schedules/prompts is higher blast radius and should be a separate pass.
- Result packet schemas; they preserve operational evidence and should stay
  detailed.
- Trading strategy logic and broker safety behavior.
- Existing broad docs; they still matter for full-context work.

## Next Efficiency Pass

1. Add a pruning/compaction policy for automation memory files.
2. Consider adding `--summary-output` or `--compact-json-output` to the CLI
   commands so automations emit compact machine-readable summaries directly.
3. Review whether `premarket_brief.source_packets` needs full source payloads or
   can store references plus compact deltas.
4. If safe, update `C:\cm\automations\*\automation.toml` prompts to point at
   `CONTEXT_ROUTER.md` and the snapshot helper instead of restating long context.
