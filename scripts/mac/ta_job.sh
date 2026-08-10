#!/bin/zsh
# TradingAgents Mac automation wrapper.
#
# Replaces the paused Windows Codex automations with deterministic CLI
# sequences driven by launchd. Every job is fail-closed: live submission
# still requires the unified go-live guard (promotion record, risk
# envelope, unexpired dead-man control, buying power) at submit time.
#
# Usage: ta_job.sh <hourly|preopen|tournament|overnight|daily-report|deliver-outbox>
#
# Config via environment (set in the launchd plist or shell):
#   TA_REPO          repo root (default: the production tree this script infers)
#   TA_LIVE_SUBMIT   1 to allow the supervisor to submit clean, gated actions
#                    after a clean dry-run (historical behavior); 0 = dry-run
#                    only (default until a human re-arms live trading).

set -euo pipefail

JOB="${1:?job name required}"
TA_REPO="${TA_REPO:-/Users/corbinfloyd/Documents/TradingAgents}"
TA_LIVE_SUBMIT="${TA_LIVE_SUBMIT:-0}"
PY="$TA_REPO/.venv/bin/python"
LOG_DIR="$TA_REPO/results/mac_automation/logs"
LOCK_DIR="$TA_REPO/results/mac_automation/locks/$JOB.lock"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/$JOB-$STAMP.log"

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_DIR")"
cd "$TA_REPO"

# mkdir is atomic: refuse to overlap a still-running instance of the same job.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$(date -u +%FT%TZ) $JOB already running; skipping" >> "$LOG_DIR/skipped.log"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

run() {
  echo ">>> $*" >> "$LOG_FILE"
  "$@" >> "$LOG_FILE" 2>&1
}

case "$JOB" in
  hourly|preopen)
    run "$PY" -m cli.main alpaca check
    SUPERVISE_ARGS=(
      alpaca supervise-hourly --json-output
      --notification-policy urgent-exceptions
      --log-dir results/hourly_supervisor
      --overnight-log-dir results/overnight_plans
      --paper-tournament-log-dir results/paper_strategy_tournament
      --premarket-brief-log-dir results/premarket_briefs
    )
    if [[ "$TA_LIVE_SUBMIT" == "1" ]]; then
      # The CLI itself only submits when the dry-run is clean and every
      # live gate passes; --submit-actions is permission to try, not to bypass.
      run "$PY" -m cli.main "${SUPERVISE_ARGS[@]}" --submit-actions
    else
      run "$PY" -m cli.main "${SUPERVISE_ARGS[@]}" --dry-run
    fi
    run "$PY" -m cli.main alpaca premarket-brief --json-output
    if [[ "$JOB" == "preopen" ]]; then
      run "$PY" -m cli.main alpaca preopen-validation --json-output
    fi
    run "$PY" scripts/automation_context_snapshot.py --write
    # Urgent alerts queue in the outbox as they happen; drain it every tick
    # so a CRITICAL/NOTABLE email is not stuck until the 15:40 daily drain.
    run "$PY" scripts/mac/deliver_outbox.py
    ;;
  tournament)
    run "$PY" -m cli.main alpaca paper-tournament run --all --json-output
    ;;
  overnight)
    run "$PY" -m cli.main alpaca check
    run "$PY" -m cli.main alpaca plan-overnight --json-output
    run "$PY" -m cli.main alpaca premarket-brief --json-output
    run "$PY" scripts/automation_context_snapshot.py --write
    ;;
  daily-report)
    run "$PY" -m cli.main alpaca supervisor-daily-report --json-output \
      --log-dir results/hourly_supervisor \
      --paper-tournament-log-dir results/paper_strategy_tournament \
      --premarket-brief-log-dir results/premarket_briefs \
      --email-to "${TA_EMAIL_TO:-nebulazer2003@gmail.com}"
    ;;
  deliver-outbox)
    run "$PY" scripts/mac/deliver_outbox.py
    ;;
  *)
    echo "unknown job: $JOB" >&2
    exit 2
    ;;
esac

echo "$(date -u +%FT%TZ) $JOB ok" >> "$LOG_DIR/heartbeat.log"
