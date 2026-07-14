# CLAUDE.md — TradingAgents System Map & Operating Model

Last full audit: **2026-07-14** (Claude Fable 5 session; market open during final validation).
Read this before `AGENTS.md`/`CONTEXT_ROUTER.md` — those predate the Mac migration.

## 1. What this system is

An autonomous equities workspace: a **paper account (~$97k)** does the real strategy
work, a **tiny live account (~$200)** mirrors the winner under hard caps, and a mesh
of scheduled jobs (supervisor ticks, overnight research, paper tournament, daily
report) produces JSON "packets" under `results/` as the single source of truth.
Everything order-affecting passes one chokepoint: the **unified go-live guard**
(`tradingagents/policy/live_gate.py`) — promotion record + risk envelope + dead-man
timer + buying power + stocks-only/limit-only. Analysis lanes are stamped
`execution_authority=none` and cannot trade.

**Decision flow:** market data → candidate signals → (overnight graph research +
paper tournament evidence + premarket brief) → hourly supervisor decision →
guardrail validation → go-live guard → (only then) limit orders.
**Money flow:** live buys are capped by `config/risk_envelope.yaml`
($250 max at risk, $50/name, $25 tranches, $25 daily-loss halt, 5% drawdown halt).

### Key components
| Piece | Where | Role |
|---|---|---|
| Hourly supervisor | `tradingagents/brokers/alpaca_supervisor.py`, `brokers/supervisor/` | live/paper tick, loss-review, profit-take |
| Paper tournament | `tradingagents/brokers/paper_tournament.py` | races 3 sleeves, writes live-selection |
| Promotion bridge | `tradingagents/policy/promotion_sync.py` + `policy sync-promotion` | tournament evidence → `results/policy/promotion_state.json` (NEW 2026-07) |
| Overnight research | `cli plan-overnight`, `tradingagents/graph/` | analysis-only LangGraph multi-agent research |
| Notifications | `brokers/supervisor/daily_report.py`, `alert.py`, `notifications/outbox.py` | plain-language emails → `results/outbox/` queue |
| Mac automation | `scripts/mac/` + `~/Library/LaunchAgents/com.tradingagents.*` | replaces the 14 paused Windows Codex automations |
| MiroFish | `../mirofish-main` | external society-simulation; advisory-only handoffs, no execution authority |
| n8n | `config/n8n_tradingagents_allowlist.json`, `orchestration/n8n_*` | observer workflows only; allowlisted read-only jobs |
| Zep | `research/memory.py` | **not configured, intentionally**; memory defaults to local redacted packets (Zep rate-limited badly in the past — keep local) |

## 2. Decisions made in the 2026-07-14 audit (with evidence)

1. **Fixed the overnight graph total failure.** 2026-07-11 run failed 3/3 (IBM,
   NFLX, UNH): parallel analyst fan-out emitted per-id `RemoveMessage`s that crash
   LangGraph's reducer at the merge. Fix: `REMOVE_ALL_MESSAGES` sentinel in
   `agents/utils/agent_utils.py`. Evidence: compiled-graph regression test in
   `tests/test_graph_analyst_concurrency.py`; old behavior reproduces the exact
   production error string.
2. **Corrected the live strategy.** The tournament and live trading were two
   disconnected systems: live was hardcoded to `current-aggressive` (worst sleeve,
   −12.25%, 14% win rate) while the winner `pullback-support` (+3.11%, 85.7% win
   rate, −1.91% max DD over 11 tracked days) was advisory-only. Built
   `promotion_sync` (evidence-gated writer), `resolve_live_sleeve()` (selection is
   binding only with a live-enabled promotion record), and wired the previously
   dead `adapt_candidate_signals_for_live_strategy` into the hourly path.
   Current state: **pullback-support = tiny_live_eligible + live_enabled;
   current-aggressive demoted on its own negative evidence.** Regime support:
   July 2026 is an AI-capex-stress, possible-rate-hike tape (software ETF −16% YTD,
   Oracle −29% YTD on OpenAI exposure) — a dip-buyer with anti-crowding filters fits;
   momentum-chasing does not. The June calibration guard ("downrank crowded AI
   beta") was validated by events.
3. **Rebuilt notifications for a non-technical owner.** Five fixed sections:
   Plain English / Where you stand / What happened / Why it matters / What to do
   next. Machine reasons translate via `formatting.plain_language_reason`;
   strategy ids get display names; paths/jargon are banned and enforced by
   `evals/email_clarity.py`. Every rendered email queues in `results/outbox/`
   (`scripts/mac/deliver_outbox.py` sends via SMTP_* env when configured).
   Evidence: real-data render passed clarity eval 100/100.
4. **Restored autonomous routines on the Mac** via launchd (see §3). Windows
   Codex automations stay paused permanently.
5. **Fixed all 8 pre-existing test failures** (Windows-path portability in
   MiroFish discovery, stale required-report-id, expired June transition-window
   assertions, missing `submit_capable_count` in n8n list-jobs, Ollama route
   health probing). Full suite: **1078 passed** (was 8 failed).

## 3. Operating model on this Mac

- Repo: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main`
  (branch `master`; dev worktree `../tradingagents-fable`, branch `fable`).
- Python: `.venv` (3.13, uv-managed). Tests: `.venv/bin/python -m pytest tests/ -q`.
- Credentials: `.env` (owner-only, gitignored) — Alpaca paper+live. The package
  auto-loads it from CWD. No GOOGLE/OPENAI keys on this machine yet.
- launchd agents (local time = America/Chicago; market 08:30–15:00):
  `hourly` (:00, 8–15 + 14:30 + 15:15) · `preopen` (08:15) · `tournament` (:05)
  · `overnight` (03:00) · `daily-report` (15:30) · `deliver-outbox` (15:40).
  Manage via `scripts/mac/install_launchd.sh [--uninstall]`.
  **Fail-closed default: `TA_LIVE_SUBMIT=0`** (dry-run only). To re-arm live:
  set `TA_LIVE_SUBMIT=1` in the plists AND refresh the dead-man
  (`policy refresh-live-control --reason ... --ttl-hours N`).
- **BLOCKER (owner action):** macOS TCC denies launchd access to `~/Documents`.
  Grant Full Disk Access to `/bin/zsh` (System Settings → Privacy & Security →
  Full Disk Access → “+” → ⌘⇧G → `/bin/zsh`), then
  `launchctl kickstart gui/$UID/com.tradingagents.daily-report` and check
  `results/mac_automation/logs/heartbeat.log`. Alternative: move the workspace
  out of `~/Documents`.
- Alpaca MCP (paper) is configured for Claude sessions; live keys exist but the
  MCP is paper-only by design.

## 4. Model strategy (2026-07 reality)

- **No LLM is currently wired on the Mac** — overnight runs use the deterministic
  fallback scorer (validated: ranks 40, submits 0). The graph bug fix is ready for
  when a provider returns.
- **OpenRouter** (user has a management key): cheap lanes as of July 2026 —
  DeepSeek V3.2 ≈ $0.14/$0.28 per 1M tokens; Gemini 2.5 Flash-class similar; free
  tier (DeepSeek R1, Llama 3.3 70B) at 20 req/min for non-urgent lanes. Route
  MiroFish + overnight deep lanes through these; keep judgment lanes on a stronger
  model. Set `OPENROUTER_API_KEY` in `.env`; the `llm_clients/` factory already
  supports an OpenAI-compatible backend URL.
- **Local Ollama option:** 32GB MacBook Pro runs `qwen3-30b-a3b` (MoE, ~18GB q4) or
  14B dense; the 48GB PC ran `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k`
  historically (route `windows_local_ollama` still exists in `model_routing.py`).
  Local quality < paid APIs for judgment; use local for bulk
  summarization/extraction lanes only, and only if a box stays plugged in and
  awake. Not required — cheap OpenRouter lanes likely beat the operational cost.
- **Zep replacement:** keep local packet memory (already default). If graph memory
  is wanted later, the locally-installed `codebase-memory` MCP covers code
  structure; a self-hosted mem0/Letta could cover research memory. Do not
  re-enable Zep.

## 5. MiroFish operating notes

- Runs have never completed 100% without skips; treat outputs as advisory priors
  with expiry (`staleness.valid_window`), never triggers. The required report id
  is `report_1e3059f732b1` (env override `TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID`).
- Best time to run: **overnight before a catalyst-dense day** (e.g., before CPI or
  a mega-cap earnings cluster), funded via cheap OpenRouter lanes. Don't run daily;
  the advisory decays in days and the June window showed most value pre-event.
- Discovery now checks the Mac sibling checkout first (`../mirofish-main`).

## 6. Unresolved risks

1. **TCC grant missing** → launchd jobs can't run yet (owner one-click; §3).
2. **Dead-man expired 2026-06-04** → live submits blocked (intentional until owner
   re-arms). Live account also has only $86 buying power — sizing warnings expected.
3. **NFLX loss-review is open with earnings 2026-07-16** — binary event in 2 days;
   the loss-review evidence refresh resolved 12/13 blockers. Decide hold-vs-exit
   before earnings or accept event risk. TSM also under review; TSM reports 2026-07-16.
4. **Tournament metrics are mark-to-market** (no sell rules in tournament sleeves;
   win rate = open positions only). Direction of evidence is right; magnitude is
   soft. Next iteration: realized-PnL tournament with exits.
5. **Paper portfolio is heavy AI-beta** (NVDA/AMD/AVGO/TSM/MSFT/ORCL/CRM…) in an
   AI-financing-stress regime; ORCL −41% and CRM −21% are the drag. The demoted
   aggressive sleeve imported these; pullback-support inherits watch-only.
6. **No LLM key on Mac** → overnight research is deterministic-only until
   OPENROUTER/GOOGLE key lands.
7. **n8n-runner launchd service exists but last exited via SIGTERM** — user
   installed n8n+Docker recently; the observer workflows haven't been re-verified
   on Mac.
8. **Session-limit fragility:** heavy multi-agent Claude work can hit plan limits
   mid-task; prefer inline work + durable commits.

## 7. Future priorities (ranked)

1. Owner: TCC grant + verify heartbeat (unblocks everything autonomous).
2. Owner: add `OPENROUTER_API_KEY`; then set overnight profile to a cheap
   DeepSeek/Flash lane and re-run `plan-overnight` with `--full-graph-tickers 3`.
3. Decide NFLX/TSM loss-reviews before 2026-07-16 earnings.
4. Re-arm live (dead-man + `TA_LIVE_SUBMIT=1`) once 1–2 clean dry-run days pass.
5. Tournament v2: realized-PnL scoring + exit rules + restart window (current one
   ended 2026-07-01; it keeps running but start a fresh 31-day window).
6. SMTP app password → outbox actually emails (or wire a Claude scheduled task to
   drain the queue).
7. Re-verify n8n observer stack on Mac (`research n8n-list-jobs`, runner service).
8. Consider MiroFish refresh run before the next macro window, OpenRouter-funded.

## 8. Validation evidence (this audit)

- Full test suite: `1078 passed, 1 skipped` (from 8 failed / 1066 passed).
- Live-market dry-run (open session, real data): loss-review decision, 0 orders,
  binding sleeve resolution `pullback-support`, alert queued + clarity pass.
- Pre-open validation on month-stale context: **fails closed** (2 fail, 1 warn).
- Overnight deterministic fallback: 40 ranked, 0 submitted, 0 failures.
- Daily report from real accounts: clarity 100/100, no jargon, correct money.
- Promotion state file: written by `policy sync-promotion --arm-live --ci-green`
  from tournament report `paper-tournament-20260531-080741`.

## 9. Executive matrix — completed & recommended (impact × risk)

| # | Work item | Status | Arch. impact | Impl. risk |
|---|---|---|---|---|
| 1 | Promotion bridge: evidence → live sleeve (was disconnected) | DONE | **Very high** — closes the core feedback loop | Low (fail-closed, gated, tested) |
| 2 | Overnight graph concurrency fix | DONE | **High** — restores the system's research engine | Very low (sentinel + regression tests) |
| 3 | Plain-language notifications + outbox transport | DONE | High — makes autonomy owner-legible; adds missing delivery layer | Low |
| 4 | Mac launchd automation layer (dry-run default) | DONE (needs TCC grant) | High — restores autonomy post-migration | Low-med (TCC, laptop sleep) |
| 5 | 8 legacy test failures + Windows-path portability | DONE | Medium — trustworthy CI signal on Mac | Very low |
| 6 | Strategy demotion of current-aggressive | DONE | High — stops worst sleeve from being live default | Low (live was blocked anyway) |
| 7 | Re-arm live trading (dead-man + TA_LIVE_SUBMIT) | RECOMMENDED (owner) | Medium — turns paper edge into (tiny) real P&L | Medium (real money; caps are small) |
| 8 | OpenRouter key + cheap overnight graph lanes | RECOMMENDED | High — real multi-agent research resumes at ~$0.1–0.3/M | Low (spend-capped) |
| 9 | Tournament v2 (realized PnL, exits, fresh window) | RECOMMENDED | High — evidence quality for promotions | Medium (touches core scoring) |
| 10 | NFLX/TSM loss-review decision pre-earnings | RECOMMENDED (urgent) | Low arch / high P&L relevance | Low |
| 11 | MiroFish refresh run (cheap-lane funded, pre-catalyst) | OPTIONAL | Medium — fresh advisory priors | Medium (never runs 100% clean) |
| 12 | Zep → stay local (+codebase-memory MCP) | DECIDED (no action) | Low | None |
