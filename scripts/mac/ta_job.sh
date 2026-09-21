#!/bin/zsh
# TradingAgents Mac automation wrapper.
#
# Deterministic CLI sequences called by the canonical Codex schedules or an
# explicitly authorized manual run. This wrapper never installs schedules.
# The current hourly CLI hard-disables direct live submission; an action flag
# is not an independently issued live intent or an activation receipt.
#
# Usage: ta_job.sh <hourly|preopen|tournament|overnight|daily-report|deliver-outbox>
#
# Config via environment (set by the authorized caller):
#   TA_REPO          repo root (default: the production tree this script infers)
#   TA_LIVE_SUBMIT   1 requests the hourly CLI's gated action path and outbox
#                    delivery; it does not enable direct live orders. 0 is
#                    dry-run only, with no outbox delivery. Preopen is always
#                    dry-run regardless of an inherited action flag.

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
    if [[ "$JOB" == "hourly" && "$TA_LIVE_SUBMIT" == "1" ]]; then
      # Only explicitly requested hourly action runs use this route. The CLI
      # still rejects direct live orders; permitted paper actions retain their
      # own guards. Preopen validation can never inherit this action mode.
      run "$PY" -m cli.main "${SUPERVISE_ARGS[@]}" --submit-actions
    else
      run "$PY" -m cli.main "${SUPERVISE_ARGS[@]}" --dry-run
    fi
    run "$PY" -m cli.main alpaca premarket-brief --json-output
    if [[ "$JOB" == "preopen" ]]; then
      run "$PY" -m cli.main alpaca preopen-validation --json-output
    fi
    run "$PY" scripts/automation_context_snapshot.py --write
    # Analysis-only runs must not send previously queued real messages.
    # Explicit hourly action runs and the separate deliver-outbox job retain
    # delivery behavior; a dry-run does not authorize an outbox drain.
    if [[ "$JOB" == "hourly" && "$TA_LIVE_SUBMIT" == "1" ]]; then
      run "$PY" scripts/mac/deliver_outbox.py
    fi
    ;;
  tournament)
    run "$PY" -m cli.main alpaca paper-tournament run --all --dry-run --json-output
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
