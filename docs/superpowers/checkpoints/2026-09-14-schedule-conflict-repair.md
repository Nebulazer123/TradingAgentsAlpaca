# Schedule and dry-run conflict repair — 2026-09-14

## User-priority scope

The user asked to resolve repo conflicts before the day/night/weekend
visualization. Canonical `master` had no unmerged paths or conflict markers in
the inspected active source/config/plan scope. The actual schedule contract
evaluation passes for all ten PAUSED records with no issues; status remains
`not_deployed`, not proof of activation or runtime health.

## Confirmed issues repaired in source

1. Retire the legacy six-job macOS installer as a non-mutating compatibility
   entry point. Its hardcoded Eastern timetable conflicts with the canonical
   ten-job Central-time contract. Help explains the replacement; installation,
   uninstallation, unknown options and implicit installation all refuse without
   changing files/services. The old implementation remains in Git history.
2. Make preopen unconditionally dry-run, even with an inherited action flag.
3. Prevent preopen and dry-run hourly jobs from draining previously queued real
   mail. Explicit hourly action and separately requested outbox jobs retain
   their existing guarded behavior. Scheduled tournament stays dry-run.
4. Correct wrapper and agent-guide descriptions: Codex owns the schedule; the
   localhost n8n launchd runner is separate. The current hourly CLI hard-disables
   direct live submission; an environment flag does not issue a live intent.
5. Replace obsolete current-tense documentation about already-corrected
   one-hour/prompt/tournament defects with the current read-only contract check
   and explicit remaining deployment requirements.

Only `AGENTS.md`, the orchestration guide, two Mac scripts, and the wrapper test
module change behavior/documentation. There are no broker, risk, strategy,
promotion, credential, model-route, automation-TOML or live-control edits.

## Verification

- RED: **8 failed / 3 passed** on the old scripts. Two failures prove dry-runs
  drained the outbox; one proves preopen inherited `--submit-actions`; five
  reject the historical mutating installer before executing it.
- GREEN: **11 passed**. Tests execute the real wrapper with a recording-only
  fake Python executable in a temporary task directory; no real application,
  broker, model, mail, service or installer mutation is invoked.
- Affected gate: **125 passed, 2 existing AST escape warnings, 10.40 seconds**.
  Coverage includes wrappers, schedule/role contracts, authority inventories,
  n8n policy, automation health, and three CLI dry-run/live-intent regressions.
- Scoped Ruff, both individual zsh syntax checks, executable-mode preservation,
  `git diff --check`, and distinct solo self-review pass.

Affected JUnit receipt is beside SDD `progress.md` as
`schedule-conflict-affected-20260914.xml`. The old 81b7463 full gate remains valid
for its unchanged inputs; these new wrapper changes require a new exact-candidate
full source gate before integration. Do not restart or relabel the old gate.

## Preserved historical merge is not an active-code defect

A read-only scan of all **25 registered worktrees** found one unmerged index:
`/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-integration`,
with **67 paths / 83 index-stage entries**. Its HEAD/ORIG_HEAD is
`ce2dd4352b7366a6ec2c2b9370b456ab56bed218`, pending historical merge parent
`6f8fa28025843fb87423c56716e8f77f741f0c67`; there are no untracked files.

The completed August 13 root-migration plan explicitly preserves this failed
merge unchanged as recovery evidence. Its actual root-correct resolution
`02ea6b8878fcf076fcdbab3c93847ccd51eba9fa` and reviewed follow-up
`e14a78a11960e07f5a720a158c26ca4fe02aa02a` are both verified ancestors of current
canonical master. Re-merging the July candidate would revive a superseded layout.
No reset, abort, resolution, deletion, rebase, staging or commit was performed
in that protected worktree. Archiving/retiring it needs a clear release of the
specific preserve-unchanged boundary, not a blanket “choose ours/theirs.”

## Runtime posture

The read-only launchd listing showed only `com.tradingagents.n8n-runner`, PID
2369, and no six-job legacy schedule. The Mac timezone is America/Chicago.
This is service-listing evidence, not a broker or dashboard health claim.
No real wrapper/installer/service/outbox operation was performed. The four
protected owner hashes, ten PAUSED automation hashes, 24 original Alpaca response
hashes and original Phase 5 ZIP all reverified unchanged. Both handoffs and all
historical worktrees remain preserved. Whole-program readiness is not claimed.
