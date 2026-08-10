#!/bin/zsh
# Install (or reinstall) the TradingAgents launchd agents on this Mac.
#
# Recreates the paused Windows Codex automation cadence with local launchd
# jobs that call the deterministic repo CLI via ta_job.sh.
#
# IMPORTANT: launchd's StartCalendarInterval Hour/Minute fields are the
# system's local time zone (verify with `readlink /etc/localtime`), but
# tradingagents.brokers.supervisor.session.market_session_label() classifies
# market sessions in hardcoded America/Chicago time (NYSE 9:30-16:00 ET is
# defined there as 8:30-15:00 CT). On a Mac set to America/New_York (the
# common case), every schedule below must be entered in Eastern = Chicago+1
# so the two clocks agree; entering raw Central hours here silently shifts
# every tick an hour early relative to actual market session boundaries
# (e.g. a tick meant for market open lands in the pre-open/closed window
# instead). Times below are ALREADY converted to Eastern for an
# America/New_York system. If this Mac's system time zone is ever changed,
# recompute these hours (Eastern = Chicago + 1; re-derive from Chicago-time
# intent if the system zone changes to something else).
#
#   com.tradingagents.hourly      hourly 09:00-16:00 ET + 15:30 + 16:15 ticks
#                                 (= CT 08:00-15:00 + 14:30 + 15:15)
#   com.tradingagents.preopen     09:15 ET (= CT 08:15) daily; market-closed
#                                 days produce quiet packets
#   com.tradingagents.tournament  hourly at :05, 09:05-16:05 ET (= CT 08:05-15:05)
#   com.tradingagents.overnight   daily 04:00 ET (= CT 03:00)
#   com.tradingagents.daily-report weekdays 16:30 ET pattern (= CT 15:30);
#                                 daily, quiet on closed days
#   com.tradingagents.deliver-outbox daily 16:40 ET (= CT 15:40)
#
# Usage: install_launchd.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
TA_REPO="${TA_REPO:-/Users/corbinfloyd/Documents/TradingAgents}"
JOB_RUNNER="$TA_REPO/scripts/mac/ta_job.sh"
AGENT_DIR="$HOME/Library/LaunchAgents"
UID_TARGET="gui/$(id -u)"

LABELS=(
  com.tradingagents.hourly
  com.tradingagents.preopen
  com.tradingagents.tournament
  com.tradingagents.overnight
  com.tradingagents.daily-report
  com.tradingagents.deliver-outbox
)

if [[ "${1:-}" == "--uninstall" ]]; then
  for label in "${LABELS[@]}"; do
    launchctl bootout "$UID_TARGET/$label" 2>/dev/null || true
    rm -f "$AGENT_DIR/$label.plist"
    echo "removed $label"
  done
  exit 0
fi

mkdir -p "$AGENT_DIR"

calendar_entries() {
  # $1 = minute, $2.. = hours
  local minute="$1"; shift
  for hour in "$@"; do
    cat <<EOF
    <dict><key>Hour</key><integer>$hour</integer><key>Minute</key><integer>$minute</integer></dict>
EOF
  done
}

write_plist() {
  # $1 label, $2 job name, $3 calendar entries (already-rendered XML)
  local label="$1" job="$2" calendar="$3"
  cat > "$AGENT_DIR/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$JOB_RUNNER</string>
    <string>$job</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TA_REPO</key><string>$TA_REPO</string>
    <key>TA_LIVE_SUBMIT</key><string>${TA_LIVE_SUBMIT:-0}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
$calendar
  </array>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$TA_REPO/results/mac_automation/logs/$label.out</string>
  <key>StandardErrorPath</key><string>$TA_REPO/results/mac_automation/logs/$label.err</string>
</dict>
</plist>
EOF
}

mkdir -p "$TA_REPO/results/mac_automation/logs"

write_plist com.tradingagents.hourly hourly "$(calendar_entries 0 9 10 11 12 13 14 15 16)
$(calendar_entries 30 15)
$(calendar_entries 15 16)"
write_plist com.tradingagents.preopen preopen "$(calendar_entries 15 9)"
write_plist com.tradingagents.tournament tournament "$(calendar_entries 5 9 10 11 12 13 14 15 16)"
write_plist com.tradingagents.overnight overnight "$(calendar_entries 0 4)"
write_plist com.tradingagents.daily-report daily-report "$(calendar_entries 30 16)"
write_plist com.tradingagents.deliver-outbox deliver-outbox "$(calendar_entries 40 16)"

for label in "${LABELS[@]}"; do
  launchctl bootout "$UID_TARGET/$label" 2>/dev/null || true
  launchctl bootstrap "$UID_TARGET" "$AGENT_DIR/$label.plist"
  echo "installed $label"
done

echo "Done. Verify with: launchctl list | grep tradingagents"
