# Task 4.5 — Source-Frozen Shadow-Trial Protocol Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. Each increment is committed separately after its own RED→GREEN cycle and focused verification.

**Goal:** Close five verified runtime-protocol gaps before the first real qualification day so that Task 5 becomes a precise, recoverable, source-frozen qualification protocol: terminal-report safety, crash-safe day closure, market-day (not calendar-day) leases, one immutable runtime identity across all six countable days, full paper/reconciliation cross-binding, and enforced daily temporal sequence.

**Provenance:** The approved specification is the "Upgraded Plan: Source-Frozen Qualification and Five-Market-Day Paper Trial" review (2026-08-22). This plan decomposes its Task 4.5 into six independently verifiable source increments. It supersedes the conflicting post-qualification `research shadow-streak-report` step recorded in `.superpowers/sdd/2026-08-17-clean-day-qualification-and-five-day-paper-trial/task-4-report.md`.

**Baseline:** Canonical `master` clean at `1743545`; this isolated worktree branch `codex/source-frozen-shadow-protocol-20260822`. Tasks 1–4 of the clean-day plan are complete. All ten automations are `PAUSED`; frozen live-control SHA-256 `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`; no qualification day or trial has run. The next calendar candidate remains Monday, 2026-08-24, but it must not be used until all six increments below are implemented, reviewed, merged to canonical, and freshly verified.

## Global boundaries (every increment)

- Source-only work in this isolated worktree; no canonical-master or other-worktree edits.
- All ten TradingAgents automations remain `PAUSED`; no automation update call.
- `TA_LIVE_SUBMIT=0` for every command; no live order/cancellation; no broker read or write from these tasks (tests use fakes only).
- No live-control refresh/rearm/unfreeze/rewrite; no promotion, risk, capital, account, credential, endpoint, schedule, or outbox change.
- No scheduled/unattended execution; no runtime qualification/trial activity.
- Every behavior change begins RED, then minimal GREEN, then focused + dependent verification.

## Verification vocabulary (per increment)

Focused: the increment's named test functions. Dependent: the owning modules' full test files plus listed neighbor suites. Static: `ruff check` on changed paths, `compileall -q` on changed packages, `git diff --check`. Program-wide final gate (Increment 6): full pytest, Ruff on `cli tradingagents scripts tests`, `compileall -q cli tradingagents scripts`, `git diff --check`, `zsh -n scripts/mac/ta_job.sh`, broker/network mutation inventory, independent specification review, independent authority/security review, zero unresolved P0/P1, fast-forward only from clean canonical `master`, then re-index the canonical graph.

---

## Increment 1: Correct terminal-report semantics and add read-only status

**Problem:** `build_shadow_streak_report()` (`tradingagents/evals/shadow_trial.py:2932`) admits a terminal `readiness_candidate`/`readiness_no_go` record; afterwards `_LedgerState` rejects any further start (`tradingagents/evals/shadow_trial.py:2530`, `2422`). The runbook calls it right after qualifier adjudication, terminally closing the program before Day 1.

**Files:**
- Modify: `tradingagents/evals/shadow_trial.py`
- Modify: `cli/main.py`
- Modify: `tests/test_shadow_trial.py`
- Modify: `tests/test_alpaca_cli.py` (runbook parser test)
- Modify: `.superpowers/sdd/2026-08-17-clean-day-qualification-and-five-day-paper-trial/task-4-report.md`

**Interfaces:**
- New `shadow_streak_status() -> dict`: pure replay via `_store_envelopes()` + `_LedgerState`; appends nothing. Returns always `{analysis_only: true, execution_authority: "none", can_submit_orders: false}` plus `phase`, `last_result` (object/run/market date/role/status/phase/reasons or null), `clean_trial_streak` (consecutive trailing clean trial-role days), `required_clean_trial_days: 5`, `pending_start` view or null, `predecessor_object_id` expected by the next start, `can_start_next_day`, and `ledger_head_object_id`.
- `build_shadow_streak_report(*, final_no_go: bool = False)`: refuses (ValueError) unless the ledger already ends in a candidate chain (clean `trial_complete`) or an existing report is being re-read, unless the caller explicitly passes `final_no_go=True` (deliberate program termination as NO-GO).
- CLI: new read-only `research shadow-streak-status [--json-output]`; `research shadow-streak-report` gains `--final-no-go/--no-final-no-go` and fails closed pre-terminal without it.
- Runbook: post-qualifier invocation replaced with `shadow-streak-status`; terminal `shadow-streak-report` documented exactly once, only after clean Day 5 adjudication + trial finalization.

**Tests (RED first):**
- `tests/test_shadow_trial.py::test_red_shadow_streak_status_is_read_only_non_authorizing_and_admissibility_true` — empty ledger, pending start, and post-qualification states report correct phase/streak/predecessor/admissibility; ledger byte state identical before/after status.
- `tests/test_shadow_trial.py::test_red_status_after_clean_qualification_does_not_block_trial_day_1` — status between qualifier and Day 1 leaves zero final-report objects and Day 1 start+adjudication succeed; streak counts trial days only.
- `tests/test_shadow_trial.py::test_red_terminal_report_refuses_before_clean_trial_complete_unless_final_no_go` — refusal after failed qualifier and mid-trial; `final_no_go=True` admits `readiness_no_go`; full clean chain still admits `readiness_candidate` without the flag.
- Update `test_red_production_cli_exposes_only_pinned_non_authorizing_inputs` signature assertion to require exactly one keyword-only parameter `final_no_go` defaulting False; add CLI-level status JSON assertions and pre-terminal CLI refusal.
- Update `tests/test_alpaca_cli.py::test_clean_day_runbook_exact_commands_exist_without_executing_runtime`: documented order becomes adjudicate < finalize < `shadow-streak-status` < exactly-one `shadow-streak-report`.

- [x] Write RED tests; record failures.
- [x] Implement `shadow_streak_status`, `final_no_go` gate, CLI command/flag, runbook revision.
- [x] Run focused shadow + runbook-parser tests, dependent `tests/test_alpaca_cli.py` shadow/sentinel cases, Ruff, compileall, `git diff --check`.
- [x] Commit Increment 1.

## Increment 2: Crash-safe day closure (abort + expire-pending)

**Problem:** A pending start blocks all future starts, but normal adjudication refuses after the Central date changes (`tradingagents/evals/shadow_trial.py:2731`). A crash can permanently strand the ledger.

**Files:**
- Modify: `tradingagents/evals/shadow_trial.py` (new semantic facades beside `create_shadow_day_start_manifest`)
- Modify: `cli/main.py`
- Test: `tests/test_shadow_trial.py` (new RED classes)

**Interfaces:**
- `abort_shadow_day(*, start_object_id: str, stopped_at_stage: str, notes...) -> EvidenceAdmission`: today's authenticated pending start only; admits terminal `failed`/`incomplete` result with `phase="repair_required"`, captured stop stage and existing-artifact inventory; never `clean`; no broker/schedule/control authority; reuses the anchored admission transaction.
- `expire_pending_shadow_day() -> EvidenceAdmission | None`: pending start whose Central market date is in the past converts to immutable `incomplete` with reason `pending_day_expired_without_adjudication`, phase `repair_required`; cannot manufacture evidence; idempotent-safe (returns None when nothing expired).
- CLI: `research shadow-day-abort --start-object-id ID --stopped-at-stage KEY ...` and `research shadow-day-expire-pending`.

**Tests:** interruption after every daily stage including immediately post-start, post-paper persistence, post-manifest, pre-adjudication; abort refuses wrong object id, non-today dates, existing successor; expire refuses same-date pending; both fail closed on anchor/journal damage; aborted/expired days reset streak and force repair→requalification transitions through `_start_spec`.

- [x] RED interruption-matrix and guard tests; record failures.
- [x] Implement both facades + CLI; prove every pending start has exactly one recoverable path to an immutable non-clean result.
- [x] Focused shadow tests + recovery suites + static checks; commit.

**Implementation record (2026-08-22):** Day payloads gained `closure_kind`, `stopped_at_stage`, and `notes` (exact-field schema). `SHADOW_DAY_STOP_STAGES` is `("day_start", *DAILY_CHAIN_STAGES, "manifest_written")`; `manifest_written` is abort-only and names the interruption window after the chain manifest is sealed but before its single adjudication. Abort forces reason `shadow_day_aborted_by_operator`; expiry forces `pending_day_expired_without_adjudication`; both derive `phase="repair_required"` through the unchanged `_day_phase`. Replay validation now admits a late day result only for `closure_kind="pending_expired"` recorded on a strictly later Central date. The three prior inline anchored-write blocks were extracted verbatim into the shared `_admit_shadow_envelope` transaction used by start, adjudicate, report, abort, and expire alike. CLI gained read-surface-only `research shadow-day-abort` (start id, stop stage, required notes, optional present-artifact paths) and argument-free `research shadow-day-expire-pending` (`expired: false` JSON when nothing qualifies). No runtime identity capture was added in this increment.

**Review fix round (P2, 2026-08-22):** removed an unreachable duplicated return at the end of `build_shadow_streak_report`; made the idle expiry probe observationally pure by replaying through `_store_envelopes_readonly()` before any admission, so a fresh or non-expired ledger creates no trusted-head lock and mutates no byte (RED: fresh-empty-ledger snapshot test failed against `a6054c8` because `.manual-shadow-trusted-head.lock` was created); added the abort-only `manifest_written` stop stage with interruption-matrix coverage via parametrization over `SHADOW_DAY_STOP_STAGES` (15 cases).

## Increment 3: Bind runtime identity

**Problem:** Start payloads pin control/schedule/calendar but not Git commit, dependency locks, interpreter, package inventory, model routes, or contract hashes; Days could silently drift across source versions.

**Files:**
- Create: `tradingagents/evals/runtime_identity.py`
- Modify: `tradingagents/evals/shadow_trial.py` (`_START_FIELDS`/`_DAY_FIELDS` gain `runtime_identity`)
- Modify: `cli/main.py`
- Tests: `tests/test_runtime_identity.py` (new), `tests/test_shadow_trial.py`

**Interfaces:**
- `capture_runtime_identity(...) -> dict`: canonical repo path; exact commit; `tracked_tree_clean=true`; SHA-256 of `pyproject.toml`, `uv.lock`, `requirements.txt`, `requirements-crawler.txt`; Python executable path/version; normalized installed-package inventory SHA-256; schedule/role-contract hashes; nonsecret overnight model/provider route names; packet-schema versions.
- Start and day payloads embed identical `runtime_identity`; cross-day mismatch is a hard failure (`runtime_identity_mismatch`); dirty tree or unparseable capture refuses start admission.

**Tests:** dirty tree; changed commit; changed lockfile/package inventory/model route/schedule TOML/live-control bytes; cross-day mismatch — each fails closed and counts as non-clean; documentation-only change also resets strict identity.

- [x] RED identity-capture and mismatch tests; implement capture + binding; verify; commit.

**Implementation record (2026-08-22):** Runtime identity is the canonical flat `runtime_identity/v1` payload; the obsolete nested `runtime_identity_v1` shape is rejected by strict validation. `validate_runtime_identity` enforces the exact field set with strict types, verifies every component digest (required-source map, contract/control hashes, automation-TOML map, provider-route/schema-version maps, overnight route, package inventory) plus the whole-payload `identity_sha256`, and structurally rejects empty required-source/automation-TOML/schema-version mappings even when all digests are freshly recomputed (`provider_routes` may remain empty because the production seam supplies no provider-route map). Git capture scrubs inherited `GIT_*` routing environment, pins `GIT_CONFIG_NOSYSTEM`, `GIT_TERMINAL_PROMPT`, and `GIT_OPTIONAL_LOCKS`, disables optional locks via `core.optionalLocks=false`, bounds each subprocess at 30 seconds, translates Git/path/read failures into `RuntimeIdentityError`, and pins `--untracked-files=all` on the command line so hostile user-global config such as `status.showUntrackedFiles=no` cannot hide dirt from the clean-worktree truth. External automation TOMLs are hashed under an explicit optional `automation_root` containment boundary requiring regular non-symlink files inside it; repository files, contracts, and live control stay constrained to `repo_root`. The no-argument private production seam `_runtime_identity_capture` binds exactly the task worktree with its four required source files (`pyproject.toml`, `uv.lock`, `requirements.txt`, `requirements-crawler.txt`), the canonical schedule/role contracts plus frozen live control, exactly ten canonical automation TOMLs, the current Python interpreter plus a deterministic normalized installed name==version inventory, the configured allowlisted provider/quick-model/deep-model names resolved with existing `TRADINGAGENTS_OVERNIGHT_*` environment/default precedence (backend URLs, CLI-only argument layers, health-probed auto-Ollama model overrides, and disabled-graph fallbacks are deliberately excluded as unobservable execution inputs), and the pinned `START_SCHEMA`/`DAY_SCHEMA`/`REPORT_SCHEMA` constants. Start captures and strictly validates identity before any ledger surface is initialized and admits nothing when the runtime is dirty, unavailable, malformed, internally inconsistent, or does not bind the captured control/schedule source digests; normal adjudication stores one fresh strict identity in the day payload and fails the result with phase `repair_required` and the single hard reason `runtime_identity_mismatch` on drift versus the admitted start, the immediate predecessor-day identity, or this day's bound control/schedule sources; replay compares only stored start/day/predecessor identities and never recaptures a changed worktree; abort and expiry copy the admitted start identity verbatim without calling the seam, expiry records exactly `["pending_day_expired_without_adjudication"]`, and closure reasons otherwise remain unchanged except for stored-predecessor drift. P2 review fixes: hostile global Git status configuration pinned (RED-to-GREEN via isolated fake HOME/gitconfig) and the overnight route locked to explicitly bounded configured-route semantics with focused precedence coverage. Verification under `TA_LIVE_SUBMIT=0`: 54 runtime-identity tests, 7 focused `-k runtime_identity` shadow cases, 95 full shadow-trial tests, 1 focused clean-day runbook CLI test, Ruff on all four changed source/test paths, compileall, and `git diff --check` all green. Final independent specification plus quality/security review: no P0/P1/P2 findings; P3 items are deferred advisory only. `cli/main.py` was intentionally left unchanged in this increment. Commit subject: `feat(evals): bind runtime identity to shadow days`.

## Increment 4: Market-day leases replace calendar-day leases

**Problem:** `paper_tournament.py:942` computes `ends_at = now + timedelta(days=duration_days)`; a midweek start expires before five market days elapse; holidays worsen it.

**Files:**
- Modify: `tradingagents/brokers/paper_tournament.py`
- Modify: `cli/main.py`
- Test: `tests/test_paper_tournament.py`

**Interfaces:**
- `authorized_market_day_limit` derived lease: `authorized_market_dates` computed at initialization from authenticated exchange calendar entries with real open/close/early-close times; `ends_at` = close of fifth authorized market date bounded by a conservative wall-clock ceiling; early closes come from calendar data, never fixed inference; admission uses the admitted dates list rather than elapsed wall clock.

**Tests:** Monday–Friday starts, weekend crossing, holiday crossing, early close, same-day duplicate, sixth market day, date outside admitted calendar, changed/unavailable calendar evidence — each fails closed.

- [x] RED lease-calendar tests written and recorded failing (25/25 new cases failed pre-implementation).
- [x] GREEN implemented: admitted-dates derivation, market-day admission, ceiling-bound `ends_at`, strict live-evidence cross-check, evidence-hash binding.
- [x] Focused + dependent paper/supervisor suites green; Ruff/compileall clean; `git diff --check` clean.
- [x] Commit Increment 4 — authorized following completed acceptance: independent verification PASS, specification re-review PASS, and quality/security review with no P0/P1 findings (legacy-ledger submission-ineligibility P2 documented and resolved in the implementation record); the scoped Increment 4 commit is cleared for execution on this worktree.

**Implementation record (2026-08-22):** Canonical market-day lease decision — `initialize_tournament(..., market_calendar=...)` admits exactly `max_submission_market_days` authenticated exchange sessions as `authorized_market_dates` (strict `{date, open, close}`, exchange-time session bounds converted to UTC instants), selected ascending from the init-date Central window returned over horizon `authenticated_market_date_window(now, duration_days, market_day_limit)` spanning `max(duration_days − 1, 2 × limit)` days so any configured capacity is admittable from plausible calendars while `duration_days` never gates admission. `ends_at = min(final admitted close UTC, started_at + lease_window_days)` with `lease_window_days = duration_days`; `authorized_market_dates`, `authorized_market_day_limit`, and `lease_window_days` are all bound into `_submission_lease_evidence`. `_validate_submission_lease` fails closed on missing/malformed/duplicated/out-of-limit admitted lists; rejects any Central date outside the admitted list (weekend, holiday, sixth market day, pre-window) before any broker call; requires the live `list_calendar(start=end=today)` response to contain a normalized matching admitted entry — every observation must be well-formed and uniquely dated, and the matched entry must equal the stored admitted evidence verbatim; malformed or duplicate observations and missing/changed/unavailable evidence each fail closed; enforces the regular-session window from the admitted entry's real open/close (early closes honored from data, never fixed inference). The fixed 8:30–15:00 CT window, weekday check, and elapsed-wall-clock expiry were removed — expiry is purely market-day based, with the conservative wall-clock ceiling enforced as `ends_at`. CLI `alpaca paper-tournament init` fetches the wide authenticated range and passes it through. Accepted quality-review P2 rationale: ledgers lacking `authorized_market_dates`/`lease_window_days` (pre-Increment-4 roots) are permanently submission-ineligible by design — such a root is normally rejected first because its legacy lease-evidence digest no longer matches, and any re-signed or otherwise malformed attempt then fails closed on its missing admitted market-day calendar evidence — and such roots must be replaced by a newly initialized trial root via `alpaca paper-tournament init`; no migration path is provided. Focused verification: `pytest tests/test_paper_tournament.py -q` → 87 passed (TA_LIVE_SUBMIT=0, fakes only, zero network). Dependent suites: `test_alpaca_cli.py` + `test_alpaca_supervisor.py` → 211 passed; Increments 1–3 integrity (`test_shadow_trial.py` + `test_runtime_identity.py`) → 149 passed; combined five-suite gate → 447 passed. Static: Ruff clean on the three changed files; `compileall -q tradingagents/brokers cli` clean; `git diff --check` clean. Final acceptance: independent verifier PASS; specification re-review PASS; quality/security review found no P0/P1 findings, and its legacy-ledger P2 is documented/resolved above. The worktree remains intentionally uncommitted until the Increment 4 commit is executed.

## Increment 5: Cross-bind paper and reconciliation evidence; retire abandoned ledgers

**Problem:** Manifest records paper IDs and embeds reconciliation separately (`shadow_trial.py:2070` area); nothing proves one-to-one order identity, post-paper ordering, or terminality; an abandoned paper root has no fail-closed retirement.

**Files:**
- Modify: `tradingagents/evals/shadow_trial.py` (`_manifest_reasons`/paper-stage reasons)
- Modify: `tradingagents/brokers/paper_tournament.py` (finalize/recovery-required retirement)
- Modify: `cli/main.py` (`alpaca paper-tournament abort-submission-lease` fail-closed op)
- Tests: `tests/test_shadow_trial.py`, `tests/test_paper_tournament.py`

**Interfaces:**
- Strict comparison inside manifest validation: every `ta-paperbot-*` paper-packet order appears exactly once in the post-paper snapshot with matching broker id, client order id, symbol, side, type, timestamp; duplicates/missing/extra/reverse timestamps/nonterminal/ambiguous ⇒ `incomplete`; reconciliation `captured_at` must follow the last paper submission record; naturally empty signal set stays clean.
- Recovery-required roots permanently reject further submissions; replacement trials get fresh roots/tournament IDs.

- [ ] RED cross-binding + retirement tests; implement; verify; commit.

## Increment 6: Enforce the daily temporal sequence

**Problem:** Verifier proves containment within start→adjudication but not causal monotonic order across the sixteen-step day.

**Files:**
- Modify: `tradingagents/evals/shadow_trial.py` (stage-order validation over manifest stages)
- Test: `tests/test_shadow_trial.py`

**Interfaces:**
- Calendar-derived stage windows plus monotonic nondecreasing `generated_at` ordering over `DAILY_CHAIN_STAGES` in the approved sequence (sentinel bound, hourly dry-run, loss review, BOARD, handoff, plan, paper tick during regular session, reconciliation after paper tick, daily report after session, manifest, adjudication); backward/causal-reversed timestamps fail; equality allowed only where producer precision legitimately ties.

**Tests:** pairwise swaps, equal-timestamp acceptance, backward timestamps, paper-after-reconciliation reversal, out-of-session paper tick — each non-clean.

- [ ] RED ordering tests; implement; verify; commit.

---

## Final Task 4.5 acceptance (before any Task 5 runtime)

- [ ] Increments 1–6 committed; full pytest green; Ruff/compileall/diff/wrapper checks green; mutation inventory reviewed.
- [ ] Independent specification review and independent authority/security review with zero unresolved P0/P1 findings.
- [ ] Fast-forwarded to clean canonical `master`; canonical graph re-indexed with coverage for every changed path.
- [ ] Only then select the first real market day for Task 5A campaign admission.
