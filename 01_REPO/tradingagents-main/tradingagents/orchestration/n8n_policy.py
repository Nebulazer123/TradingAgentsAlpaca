"""Allowlisted n8n job policy for the local TradingAgents runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "config" / "n8n_tradingagents_allowlist.json"

SAFE_ALPACA_SUBCOMMANDS = {
    "check",
    "compact-output-audit",
    "supervisor-daily-report",
}

SAFE_RESEARCH_SUBCOMMANDS = {
    "agent-ledger-summary",
    "agent-ledger-update",
    "automation-health-audit",
    "automation-orchestration-plan",
    "creator-workflow-status",
    "execution-board-review",
    "loss-review-evidence",
    "mirofish-handoff-status",
    "n8n-evaluation-dataset",
    "overnight-calibration-guard",
    "outcome-labeling",
    "process-review",
    "self-heal-handoff",
    "self-heal-plan",
    "source-quality-review",
}

BROKER_CAPABLE_HINTS = {
    "buy",
    "cancel",
    "close",
    "liquidate",
    "order",
    "rebalance",
    "sell",
    "submit",
    "supervise-hourly",
}


@dataclass(frozen=True)
class N8NJob:
    name: str
    description: str
    commands: list[list[str]]
    timeout_seconds: int = 60
    submit_capable: bool = False
    compact_output_only: bool = True


def _next_token(parts: list[str], token: str) -> str | None:
    try:
        index = parts.index(token)
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def _flag_value(parts: list[str], token: str) -> str | None:
    return _next_token(parts, token)


def _is_safe_alpaca_command(parts: list[str], subcommand: str) -> bool:
    if subcommand in SAFE_ALPACA_SUBCOMMANDS:
        return True
    if subcommand == "supervise-hourly":
        return (
            "--dry-run" in parts
            and "--submit-actions" not in parts
            and "--json-output" in parts
            and "--compact-json-output" in parts
        )
    if subcommand == "premarket-brief":
        return (
            "--no-write-latest" in parts
            and "--json-output" in parts
            and "--compact-json-output" in parts
        )
    if subcommand == "preopen-validation":
        return (
            "--no-write-latest" in parts
            and "--json-output" in parts
            and "--compact-json-output" in parts
            and "--submit-actions" not in parts
        )
    if subcommand == "plan-overnight":
        return (
            "--no-write-latest" in parts
            and "--no-agent-ledger" in parts
            and "--json-output" in parts
            and "--compact-json-output" in parts
            and "--submit-actions" not in parts
            and _flag_value(parts, "--full-graph-tickers") == "0"
            and _flag_value(parts, "--time-budget-minutes") == "0"
            and (
                "--no-research-context" in parts
                or (
                    "--source-quality-review-path" in parts
                    and "--source-quality-ordering" in parts
                    and _flag_value(parts, "--top-provider-bundle-count") == "0"
                )
            )
        )
    return False


def _looks_broker_capable(parts: list[str]) -> bool:
    alpaca_subcommand = _next_token(parts, "alpaca")
    if alpaca_subcommand:
        return not _is_safe_alpaca_command(parts, alpaca_subcommand)

    research_subcommand = _next_token(parts, "research")
    if research_subcommand:
        return research_subcommand not in SAFE_RESEARCH_SUBCOMMANDS

    return any(part in BROKER_CAPABLE_HINTS for part in parts)


def _validate_job(job: N8NJob) -> None:
    if job.timeout_seconds <= 0:
        raise ValueError(f"n8n job {job.name} timeout_seconds must be positive")
    if not job.commands:
        raise ValueError(f"n8n job {job.name} must define at least one command")
    for command in job.commands:
        if not command:
            raise ValueError(f"n8n job {job.name} has an empty command")
        lowered = [part.lower() for part in command]
        if "--submit-actions" in lowered and not job.submit_capable:
            raise ValueError(
                f"n8n job {job.name} contains --submit-actions but is not submit-capable"
            )
        if any(part in {"submit_live_now", "live_now"} for part in lowered):
            raise ValueError(f"n8n job {job.name} contains forbidden live-now wording")
        if not job.submit_capable and _looks_broker_capable(lowered):
            raise ValueError(
                f"n8n job {job.name} contains broker-capable command wording"
            )
        if job.submit_capable and job.compact_output_only:
            raise ValueError(
                f"n8n job {job.name} cannot be submit-capable and compact-output-only"
            )


def load_n8n_allowlist(path: str | Path | None = None) -> dict[str, N8NJob]:
    allowlist_path = Path(path) if path else DEFAULT_ALLOWLIST_PATH
    data = json.loads(allowlist_path.read_text(encoding="utf-8"))
    raw_jobs = data.get("jobs", {})
    if not isinstance(raw_jobs, dict):
        raise ValueError("n8n allowlist must contain a jobs object")

    jobs: dict[str, N8NJob] = {}
    for name, raw in raw_jobs.items():
        if not isinstance(raw, dict):
            raise ValueError(f"n8n job {name} must be an object")
        commands = raw.get("commands", [])
        if not isinstance(commands, list) or any(
            not isinstance(command, list) for command in commands
        ):
            raise ValueError(f"n8n job {name} commands must be a list of lists")
        job = N8NJob(
            name=str(name),
            description=str(raw.get("description") or ""),
            commands=[[str(part) for part in command] for command in commands],
            timeout_seconds=int(raw.get("timeout_seconds") or 60),
            submit_capable=bool(raw.get("submit_capable", False)),
            compact_output_only=bool(raw.get("compact_output_only", True)),
        )
        _validate_job(job)
        jobs[job.name] = job
    return jobs


def get_n8n_job(name: str, path: str | Path | None = None) -> N8NJob:
    jobs = load_n8n_allowlist(path)
    if name not in jobs:
        raise KeyError(f"n8n job is not allowlisted: {name}")
    return jobs[name]

