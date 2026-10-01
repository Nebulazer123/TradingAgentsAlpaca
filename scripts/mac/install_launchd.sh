#!/bin/zsh
# Retired legacy schedule installer: deliberately has no mutation path.
# The ten Codex schedules, not the old six-job macOS timetable, are canonical.
# Keep this entry point so old instructions fail closed with a useful migration
# message. The original implementation remains recoverable in Git history.

set -euo pipefail

print -r -- 'TradingAgents legacy launchd schedule installation is retired.'
print -r -- 'Use config/automation_schedule_contract.json and docs/orchestration/automation-role-contracts.md.'
print -r -- 'The canonical schedule uses America/Chicago; do not install a second timetable.'
print -r -- 'All ten Codex schedules remain PAUSED until their separate deployment gates pass.'
print -r -- 'No schedules, services, files, or live controls were changed.'
print -r -- 'The existing localhost n8n runner is separate and is not removed by this command.'
print -r -- 'Legacy service removal requires a separately authorized, exact-target operation.'

if [[ "$#" == "1" && "$1" == "--help" ]]; then
  exit 0
fi

exit 2
