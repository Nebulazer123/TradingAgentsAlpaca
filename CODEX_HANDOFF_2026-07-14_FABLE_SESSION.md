# Handoff to Codex — Fable 5 Mac Audit Session (2026-07-14/15)

> This is an operational handoff of one Claude Fable 5 session, not a governing
> spec. `CODEX_HANDOFF_PROMPT.md` is still the original build mandate;
> `CLAUDE.md` (repo root) is the living system map — read it first for
> architecture. This document is the session diary: what changed, what's
> armed right now, and the one thing that needs attention before market open.
>
> **Codex now owns scheduling.** Claude/Fable is not going to run anything on
> a timer on this machine going forward — see §5.

> **Codex pickup addendum — 2026-07-15 01:12 UTC:** the scheduler gap below is
> resolved. Five Codex app automations are active: overnight research (04:00 ET),
> pre-open validation (09:15), paper tournament (10:05), market supervisor
> (hourly at :35 from 09:35 through 15:35), and daily report/outbox (16:30).
> Claude's launchd jobs remain uninstalled, so there is still only one order
> trigger. A fresh submit-capable closed-market run identified NFLX at −11.51%,
> applied the mechanical hard stop and 73.55 limit, and stopped solely because
> the market was closed. Codex also fixed a notification bug where stale TSM
> BOARD evidence could overwrite the active NFLX alert, then fixed pytest CLI
> runs writing into the production SMTP outbox. Seventy-six stale/test-generated
> messages were quarantined without sending; the active outbox now has zero
> pending items. Full verification is 1091 passed, 1 skipped. n8n and its
> localhost runner are healthy with 24 allowlisted and zero submit-capable jobs.

---

## 0. Read this first — time-sensitive

**Historical state at handoff:** live trading was armed but nothing would trigger it. I built and then, per
owner instruction, tore down a set of macOS `launchd` jobs that would have
executed the NFLX stop-loss exit automatically tomorrow morning. The
underlying safety state (dead-man timer, promotion record) is still armed and
correct — there is simply no scheduler pointed at it anymore.

The Codex pickup addendum above supersedes that last sentence: the active market
automation now satisfies option 1 below while preserving the same guard chain.

**NFLX is at ~−11.5%, past its −8% hard-stop rule, in a real (tiny, ~$24)
live position. NFLX and TSM both report earnings 2026-07-16.** If a stop-loss
exit before earnings is still wanted, **Codex needs to either:**

1. Stand up its own scheduler that calls, at minimum once during regular
   market hours before Thu 2026-07-16 close:
   ```
   cd /Users/corbinfloyd/Documents/TradingAgents
   .venv/bin/python -m cli.main alpaca supervise-hourly --submit-actions \
     --json-output --log-dir results/hourly_supervisor \
     --overnight-log-dir results/overnight_plans \
     --paper-tournament-log-dir results/paper_strategy_tournament \
     --premarket-brief-log-dir results/premarket_briefs
   ```
   This is idempotent and safe to run repeatedly — it only submits when a
   decision is material and every gate (dead-man, promotion, risk envelope,
   buying power) passes. It's the exact command the removed launchd jobs ran.

2. Or run it manually once during market hours.

3. Or do nothing — the dead-man expires 2026-07-17T12:58Z and the system
   fails closed automatically; NFLX stays held through earnings by default.

**Current armed state** (`results/policy/live_control.json`):
```json
{
  "frozen": false,
  "reason": "Arm mechanical stop-loss exits (NFLX -11.6%, hard-stop rule) ahead of NFLX/TSM earnings 2026-07-16",
  "dead_man_expires_at": "2026-07-17T12:58:45+00:00"
}
```
To re-freeze/cancel instead: `.venv/bin/python -m cli.main policy freeze-live --reason "..."`.

---

## 1. What this session was

A full audit and repair pass on a Windows→Mac transfer of an autonomous
equities system that had been idle ~1 month. Two phases:

- **Phase A** (afternoon): architecture mapping, git init + `fable` worktree,
  fixed a 100%-failure bug in overnight research, fixed the disconnect
  between the paper-strategy tournament and live trading, rebuilt owner
  notifications in plain language, wrote `CLAUDE.md`.
- **Phase B** (evening, this handoff): wired the user's OpenRouter key into
  research, validated a real end-to-end graph run, built a mechanical
  stop-loss/time-stop exit policy (the system had none — losing positions
  could only exit via narrative evidence nobody ever supplied), armed live
  trading for the NFLX exit, found and fixed a real launchd/timezone bug
  while verifying, then tore the scheduler back down per owner instruction
  in favor of Codex-owned scheduling.

Full commit history (repo root, `master`, 19 commits this session):
```
5f03442 Update CLAUDE.md: live trading armed for NFLX exit ahead of 7/16 earnings
34fcf01 Merge branch 'fable'
1fc9a80 Fix launchd schedule: convert Central-time intent to this Mac's Eastern clock
1ed7c40 Merge branch 'fable'
b063ed1 Hermetic tests: ignore operator promotion_state.json by default
9d1aec8 Merge branch 'fable'
e261828 Drain notification outbox on every hourly tick, not just 15:40
a7bd68f Update CLAUDE.md: exit policy, OpenRouter live, TCC resolved, delivery verified
8a0de8a Add pre-registered mechanical exit policy for losing positions
13c1609 Merge branch 'fable'
0083475 Fix vendor-chain crash on missing optional key; local-date email subjects
9178434 Add CLAUDE.md: system map, audit decisions, operating model, exec matrix
d5a78b1 Merge fable: graph fix, promotion bridge, plain-language notifications, Mac automation
1b2e1c1 Redesign owner notifications to plain language + durable outbox
1c96956 Fix all 8 legacy test failures; full suite green (1074 passed)
3d53487 Wire paper-tournament winner into live promotion path
b7379eb Fix overnight graph 3/3 failure: REMOVE_ALL_MESSAGES in analyst cleanup
492782d Ignore fable worktree directory
9d2fc2a Import Windows TradingAgents transfer snapshot (2026-07-11)
```
Dev work happened in a git worktree at `../tradingagents-fable` (branch
`fable`), merged into `master` after each validated slice. That worktree
still exists and is safe to reuse or remove.

Test suite at Codex pickup: **1091 passed, 1 skipped** (was 8 failed / 1066
passed at session start). Run with `.venv/bin/python -m pytest tests/ -q`.

---

## 2. Fixes made (root cause → fix → evidence)

### 2.1 Overnight research: 100% graph failure → fixed
2026-07-11's overnight run failed 3/3 (IBM, NFLX, UNH) with
`"Attempting to delete a message with an ID that doesn't exist"`. Root cause:
parallel analyst fan-out (`analyst_concurrency_limit=2`) had each branch emit
per-message-id `RemoveMessage` ops into a shared LangGraph channel; a branch
could reference an id that only ever existed in a sibling branch's ephemeral
state, and the `add_messages` reducer raised on merge.
**Fix:** `tradingagents/agents/utils/agent_utils.py` — use the
`REMOVE_ALL_MESSAGES` sentinel instead of enumerating ids.
**Evidence:** `tests/test_graph_analyst_concurrency.py` includes a
regression test that compiles and invokes the real graph with the old
behavior first (reproduces the exact production error), then confirms the
fix. Also found + fixed a second graph-killer: a missing *optional* vendor
API key (`ALPHA_VANTAGE_API_KEY`) raised `ValueError` instead of the
fallback-chain-recognized `OfficialDataError`, crashing the whole graph
instead of skipping that one vendor
(`tradingagents/dataflows/alpha_vantage_common.py`).
**Validated live** this evening with the user's real OpenRouter key: first
clean 1/1 full-graph success since June.

### 2.2 Live strategy was hardcoded to the worst-performing sleeve
The paper tournament ranked `pullback-support` the clear winner (+3.11%
return, 85.7% win rate, −1.91% max drawdown over 11 tracked days) vs.
`current-aggressive` (−12.25%, 14% win rate) — but live trading was
hardcoded to `current-aggressive` regardless, and the tournament's selection
was explicitly stamped `advisory_only`. Two disconnected systems: nothing
ever wrote a real `results/policy/promotion_state.json` record for the
winner.
**Fix:** new `tradingagents/policy/promotion_sync.py` (deterministic,
evidence-gated promotion writer; new CLI `policy sync-promotion`),
`resolve_live_sleeve()` in `alpaca_supervisor.py` (selection becomes binding
only with a live-enabled promotion record; fails closed otherwise), and
wired the previously-dead `adapt_candidate_signals_for_live_strategy` into
the hourly decision path.
**Applied:** `promotion_state.json` now shows `pullback-support:
tiny_live_eligible/live_enabled=true`, `current-aggressive: paper_only`
(demoted on its own negative evidence).

### 2.3 No notification transport existed
Email bodies were composed but nothing in the repo ever sent one — that was
always the outer Windows Codex automation, which is permanently paused.
**Fix:** `tradingagents/notifications/outbox.py` (durable JSON queue,
`results/outbox/`) + `scripts/mac/deliver_outbox.py` (SMTP sender). Also
rewrote both email composers (`brokers/supervisor/daily_report.py`,
`alert.py`) into a plain-language 5-section contract (Plain English / Where
you stand / What happened / Why it matters / What to do next), enforced by
`evals/email_clarity.py`, with a machine-jargon ban list.
**Verified delivering** to `corbin.inboxhub@gmail.com` via the owner's SMTP
app password — real daily report delivered and scored 100/100 on the
clarity eval.

### 2.4 No mechanical loss-exit path existed
`loss_exit_review_packet` (`brokers/supervisor/loss_review.py`) required 13
pieces of narrative evidence (original thesis text, SPY/QQQ/sector context,
company-news check, confidence score, source packet ids, ...) that nothing
in the system ever populated. Result: any losing position that crossed the
review threshold sat in `HOLD/loss-review` indefinitely — this is why NFLX
had been stuck for weeks while its drawdown grew.
**Fix:** new `tradingagents/policy/exit_policy.py` — pre-registered
mechanical rules (standard swing-trading discipline, not invented ad hoc):
- hard stop at −8% (classic max-loss discipline: an 8% loss needs +8.7% to
  recover; a 25% loss needs +33%)
- catastrophic floor at −12% (unconditional)
- time stop: 15 trading days underwater past −5% (needs holding-period
  evidence to fire)
- sell limits priced 0.3% below market, rounded down, for realistic fills

A rule-triggered exit supplies its own reason code
(`policy_stop_floor`/`policy_time_stop`) and is exempted from the subjective
narrative blockers in `loss_review.py` (objective blockers — price data,
position actually below entry — still apply). Thresholds are overridable in
`config/risk_envelope.yaml`. Fully unit-tested
(`tests/test_exit_policy.py`), including an end-to-end hourly-decision test.
**Verified against the real live account** this evening (market closed at
verification time): NFLX correctly identified at hard-stop, only blocker was
"market closed," as expected.

### 2.5 launchd/timezone bug (found while arming, now moot but documented)
While verifying the automation, discovered the Mac's system clock is
`America/New_York` (`readlink /etc/localtime`) but
`market_session_label()` hardcodes `America/Chicago` for NYSE-hours
classification. The launchd jobs I'd installed used raw hour integers
intended as Chicago-equivalent but launchd interprets them in system-local
time — every tick was firing an hour early relative to real market
boundaries (an 8:00am tick landed at 7:00am Central, before the market
opens). Fixed in `scripts/mac/install_launchd.sh` (documented in its header;
re-derive with Eastern = Chicago + 1 if the system timezone ever changes) —
**this fix is preserved in the script even though the jobs themselves were
uninstalled per owner instruction (§5).** Whatever Codex builds for
scheduling needs to account for this same Chicago-vs-system-clock mismatch,
or convert `market_session_label()` to use system-local time instead of a
hardcoded zone.

### 2.6 8 pre-existing test failures (unrelated to trading logic, fixed for CI hygiene)
Windows-path assumptions in MiroFish artifact discovery (`Path("C:\\...")` 
doesn't parse basenames on POSIX), a stale required-report-id constant, two
assertions that expected the June 2026 PDT-transition window to still be
active (it ended 2026-07-03; the code was correctly reporting it expired,
the tests were stale), a missing `submit_capable_count` key in
`n8n-list-jobs` output, and Ollama route-health probing that needed the
probe result passed to the selector instead of checked separately. All were
root-caused individually — see commit `1c96956`.

---

## 3. Current system state (as of 2026-07-15T01:xx UTC)

| Item | State |
|---|---|
| Live account | equity ~$200, buying power ~$86, 4 positions (AMZN, MA, NFLX, TSM) |
| NFLX | qty 0.320946, −11.5%, past −8% hard-stop → armed to exit |
| TSM | qty 0.055684, −5.4%, below stop threshold, not yet triggered |
| Live sleeve | `pullback-support` (promoted on evidence); `current-aggressive` demoted |
| Dead-man control | armed, expires **2026-07-17T12:58:45Z** |
| Risk envelope | unchanged: $250 max at risk, $50/name, $25 tranche, $25 daily-loss halt, 5% drawdown halt |
| Exit policy thresholds | −8% hard stop / −12% catastrophic / 15-day time stop (config/risk_envelope.yaml overridable) |
| Scheduler | Five active Codex automations; market supervisor is the only submit-capable trigger; Claude launchd jobs remain removed |
| OpenRouter | configured, `.env`: quick lane `qwen/qwen3-30b-a3b-instruct-2507`, deep lane `deepseek/deepseek-v4-flash` |
| SMTP outbox | configured and verified delivering to `corbin.inboxhub@gmail.com` |
| n8n-runner | healthy 2026-07-15; 24 allowlisted jobs, zero submit-capable jobs, localhost-only `env -i` wrapper |
| Test suite | 1089 passed, 1 skipped |

---

## 4. File map (what's new or materially changed)

```
tradingagents/policy/promotion_sync.py       NEW — tournament evidence -> promotion_state.json
tradingagents/policy/exit_policy.py          NEW — mechanical stop-loss / time-stop rules
tradingagents/notifications/outbox.py        NEW — durable email queue
tradingagents/brokers/alpaca_supervisor.py   resolve_live_sleeve(), live_sleeve param threading
tradingagents/brokers/supervisor/hourly.py   exit-policy enrichment before loss review
tradingagents/brokers/supervisor/loss_review.py  policy-rule exemption from narrative blockers
tradingagents/brokers/supervisor/daily_report.py  plain-language 5-section rewrite
tradingagents/brokers/supervisor/alert.py    plain-language 5-section rewrite
tradingagents/brokers/supervisor/formatting.py  plain_language_reason(), strategy_display_name()
tradingagents/evals/email_clarity.py         new 5-section contract + jargon ban list
tradingagents/agents/utils/agent_utils.py    REMOVE_ALL_MESSAGES fix
tradingagents/dataflows/alpha_vantage_common.py  OfficialDataError instead of ValueError
tradingagents/research/mirofish_handoff.py   Mac sibling-checkout discovery path
cli/main.py                                  policy sync-promotion command, outbox wiring, live_sleeve_resolution evidence
config/risk_envelope.yaml                    exit-policy threshold docs (commented, overridable)
scripts/mac/ta_job.sh                        job runner (jobs no longer scheduled, but script intact)
scripts/mac/install_launchd.sh               installer (Eastern-tz-corrected; NOT currently applied)
scripts/mac/deliver_outbox.py                SMTP delivery script
CLAUDE.md                                    living system map — READ THIS for architecture
tests/test_exit_policy.py                    NEW
tests/test_promotion_sync.py                 NEW
tests/test_notifications_outbox.py           NEW
tests/test_graph_analyst_concurrency.py      + compiled-graph regression test
```

---

## 5. Scheduling — now Codex's

Per owner instruction: **Claude/Fable will not schedule anything to run
automatically on this machine.** The `scripts/mac/` directory (launchd job
script + installer + SMTP delivery script) is left in place as reference —
it is known-correct (timezone bug fixed, verified against the live account)
but is **not currently installed as a scheduler.**

If Codex wants to reuse it as-is: `scripts/mac/install_launchd.sh` installs
six jobs (hourly supervisor, pre-open, paper tournament, overnight research,
daily report, outbox delivery) with a `TA_LIVE_SUBMIT` env toggle
(`0`=dry-run default, `1`=allow submission after a clean dry-run — the
unified go-live guard is still the real gate either way). If Codex is
building its own scheduling infrastructure instead, the one thing to carry
forward is the Chicago-vs-system-clock issue in §2.5 — don't rediscover it.

**Whatever Codex sets up, avoid two schedulers hitting the same order path
concurrently** — the guardrails handle idempotency reasonably well (open-order
checks, dead-man, throttled alerts) but there's no distributed lock beyond
that.

---

## 6. Unresolved / recommended next (unchanged from CLAUDE.md, repeated for convenience)

1. **Urgent, time-sensitive:** see §0 — get something to fire (or
   deliberately not fire) the NFLX exit before 2026-07-16 earnings.
2. Tournament v2: current tournament sleeves are mark-to-market only (no
   sell rules, so "win rate" only reflects still-open positions). A
   realized-PnL tournament with exit rules would be stronger promotion
   evidence.
3. Re-verify the n8n observer stack on Mac (`research n8n-list-jobs`) — not
   touched or re-validated this session.
4. Consider a MiroFish refresh run (OpenRouter-funded, cheap) before the
   next macro catalyst window — the current advisory is from June and stale
   by design (has an explicit `advisory_expires_after`).
5. `TA_LIVE_SUBMIT` and the dead-man TTL are both time-boxed for a reason —
   don't set a long-lived unattended dead-man without deliberately deciding
   to do that. The safe resting state is the dead-man expired or live control
   frozen; the Codex schedule may still run, but the unified guard fails closed.

---

## 7. How to verify anything in this document

```
cd /Users/corbinfloyd/Documents/TradingAgents
.venv/bin/python -m pytest tests/ -q                     # 1089 passed, 1 skipped
.venv/bin/python -m cli.main alpaca check                 # live/paper connectivity + balances
cat results/policy/live_control.json                      # dead-man state
cat results/policy/promotion_state.json                   # which sleeve is live-enabled
launchctl list | grep tradingagents                       # confirm: only n8n-runner, no com.tradingagents.* jobs
git log --oneline -19                                      # this session's commits
```
