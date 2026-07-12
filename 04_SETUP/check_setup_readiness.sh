#!/usr/bin/env bash
set -u

# Presence-only readiness check. It never prints secret values and never starts
# a server, scheduler, broker command, email sender, or simulation.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TA="$ROOT/01_REPO/tradingagents-main"
MF="$ROOT/01_REPO/mirofish-main"

pass=0
warn=0

ok() { printf 'OK   %s\n' "$1"; pass=$((pass + 1)); }
note() { printf 'NOTE %s\n' "$1"; warn=$((warn + 1)); }

printf 'Read-only setup readiness for %s\n' "$ROOT"

for command_name in uv node npm git; do
  if command -v "$command_name" >/dev/null 2>&1; then
    ok "$command_name is installed"
  else
    note "$command_name is missing"
  fi
done

if [[ -x "$TA/.venv/bin/python" ]]; then
  ok "TradingAgents Python environment exists"
else
  note "TradingAgents Python environment is missing"
fi

if [[ -x "$MF/backend/.venv/bin/python" ]]; then
  ok "MiroFish backend Python environment exists"
else
  note "MiroFish backend Python environment is missing"
fi

for directory in "$MF/node_modules" "$MF/frontend/node_modules"; do
  if [[ -d "$directory" ]]; then
    ok "Node dependencies exist: ${directory#$ROOT/}"
  else
    note "Node dependencies are missing: ${directory#$ROOT/}"
  fi
done

if [[ -f "$TA/.env" ]]; then
  note "TradingAgents .env exists; values were not inspected or printed"
else
  note "TradingAgents .env is not configured yet"
fi

if [[ -f "$MF/.env" ]]; then
  note "MiroFish .env exists; values were not inspected or printed"
else
  note "MiroFish .env is not configured yet"
fi

presence_in_file() {
  local file="$1"
  local key="$2"
  if [[ -f "$file" ]] && rg -q "^${key}=[^[:space:]].*$" "$file"; then
    ok "${key} is populated in ${file#$ROOT/}"
  else
    note "${key} is not populated in ${file#$ROOT/}"
  fi
}

if [[ -f "$MF/.env" ]]; then
  presence_in_file "$MF/.env" LLM_API_KEY
  presence_in_file "$MF/.env" LLM_BASE_URL
  presence_in_file "$MF/.env" LLM_MODEL_NAME
  presence_in_file "$MF/.env" ZEP_API_KEY
fi

printf '\nSummary: %d OK, %d notes\n' "$pass" "$warn"
printf 'This check is presence-only and has no external side effects.\n'
