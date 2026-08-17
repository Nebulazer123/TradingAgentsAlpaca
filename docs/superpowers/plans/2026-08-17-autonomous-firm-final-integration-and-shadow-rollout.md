# Autonomous Firm Final Integration and Safe Shadow Rollout

## Authority and boundaries

This plan authorizes a local, reviewed source integration only. It does not
authorize a broker order, a live-control refresh/rearm/unfreeze, a risk,
strategy, promotion, credential, capital, or account change, or any GitHub
remote, PR, push, or hosted workflow. Runtime ambiguity remains HOLD/NO-GO.

## Source integration

1. Start from clean canonical `master` at `01c5401930fc7224d197f4a43b9475d6ca417287`.
2. In this worktree, fast-forward to `codex/autonomous-loss-board-decision` at
   `287f89b8e964b7eb22b4896a216847912c3e1a9d`.
3. Do not integrate the standalone authority-coordinate baseline, manual-NFLX,
   or overnight-reliability branches; their content is either superseded or
   already in `master`.
4. Cherry-pick, in order:
   - `d029a04082152002e1933aaf778b420509a206d3`
   - `c2e5d0c1d13f825592154a707b4b407b96816811`
   - `13cfb5b9434512068a2445e48563f6ef3a62beca`
   - `83d24814736741a48fb10f22f5f9b6e0c98922fb`
   - `5fd104259cae79af28c700322b462dee1cc01225`
5. Re-run the exact authority inventory and all declared integration checks.

## Scheduler contract

Add a backward-compatible `deployment_phase` to the source-read-only schedule
contract evaluator. The default `predeployment_paused` phase requires all ten
TradingAgents automations to be paused. The `frozen_observer` phase allows only
overnight research, preopen validation, self-healer, safety sentinel, execution
BOARD, paper tournament, and daily report to be active. It requires all three
of market supervisor, wake controller, and sleep controller to remain paused.
Every active role must be contractually no-submit.

Replace only the self-healer phrase `24/7 doomsday-capable` with the approved
weekday market-session reliability wording, then update the exact prompt hash
in the source contract. No other prompt text changes.

## Review and verification

Use SDD: one implementer at a time, task review after every task, fresh Sol
review of the final paper-safety commit, and an xhigh Sol whole-branch review
before `master` advances. Start new behavior with RED tests, then minimally
implement and verify GREEN.

Before a fast-forward to `master`, require the declared integration test group,
the full pytest suite, Ruff, compileall, zsh syntax check, `git diff --check`,
and no P0/P1 review findings. Record runtime/control and automation hashes
before/after; test artifacts under ignored `results/` are reported but never
used as runtime evidence.

## Runtime rollout after source integration

Use the Codex automation API only, preserving all records as paused while
correcting the source-contract schedules and the self-healer phrase. Do not
activate anything without independent America/Chicago next-run proof. If the
automation API cannot provide reliable next-run evidence, keep every record
paused. A five-day observer evidence ladder, final readiness packet, and any
future rearm remain later gates; none permits order submission automatically.

## Task 1: Fresh paper-safety source review

Perform a source-only independent review of `8b136ed..5fd1042`. Verify current
time expiry, selection/report/ledger cross-binding, candidate-strategy equality,
downstream non-consumption, and scheduled dry-run behavior. This task edits no
tracked file. A P0/P1 finding blocks later tasks until repaired and re-reviewed.

## Task 2: Integrate the verified source branches

Fast-forward this branch to the loss-board branch, cherry-pick the one schedule
contract commit and four paper-safety commits in the stated order, and commit
this plan document. Preserve all runtime state. Add no broad authority-inventory
exemption. Run the focused source integration tests and record all commands and
results.

## Task 3: Add frozen-observer deployment contract support

Write RED tests first for the two deployment phases and invalid active-status
sets. Implement the backward-compatible evaluator and contract schema described
above, plus the one-sentence self-healer prompt semantic/hash update. Limit
tracked changes to the schedule contract, evaluator, its tests, and directly
related documentation. Commit after GREEN focused verification.

## Task 4: Combined verification and integration review

Run the declared integration suite, then the full suite, static checks, zsh
syntax check, runtime/hash comparison, and authority inventory. A fresh Sol
whole-branch review must report no P0/P1 issue. Fix review findings through the
SDD loop. Only then fast-forward canonical `master` locally and re-index the
canonical graph.

## Task 5: Paused scheduler reconciliation

Use the Codex automation API to update the ten existing records, one field class
at a time, while every status stays PAUSED. First correct schedule fields, then
the exact self-healer sentence. Read back each record and prove the source
contract is clean in `predeployment_paused`. Preserve model, reasoning effort,
notification policy, project target, cwd, and all non-targeted fields. Stop if
timezone/next-run proof is unavailable; do not activate any automation in this
task.

## Task 6: Frozen-observer evidence ladder

Begin only after Task 5 proves timezone/next-run behavior and the source contract
accepts `frozen_observer`. Activate only the exact seven observer automations.
Initialize a fresh paper-only tournament on the next confirmed regular market
day, retain dry-run behavior, and record five distinct complete no-submit days.
Any failed or incomplete day is not counted. Finish with a Sol-readiness review
and a GO/NO-GO packet; do not rearm or submit an order.
