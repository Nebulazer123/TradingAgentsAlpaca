#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Transfer root: $ROOT"
echo "This script only checks prerequisites; it does not start trading, email, schedulers, or simulations."

command -v python3 >/dev/null && python3 --version || echo "Missing: python3"
command -v uv >/dev/null && uv --version || echo "Optional: uv"
command -v node >/dev/null && node --version || echo "Optional: node"
command -v npm >/dev/null && npm --version || echo "Optional: npm"

echo "Read 04_SETUP/DEPENDENCIES_AND_SETUP.md before creating environments."
echo "Keep credentials outside this transfer and create local .env files from sanitized templates only."
