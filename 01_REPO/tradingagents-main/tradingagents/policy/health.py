"""C4: read-only health/heartbeat for the tiny-live control plane.

``collect_health`` is a pure function over already-gathered facts so it is fully
deterministic and testable. ``gather_health_inputs`` does the real (read-only) I/O.
Nothing here can trade; the worst it does is queue one plain-language owner email.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingagents.evals.secret_leakage import check_key_hygiene
from tradingagents.notifications.outbox import list_undelivered, write_outbox_message
from tradingagents.policy import integrity
from tradingagents.policy.live_control import load_live_control_state, parse_control_time
from tradingagents.policy.live_gate import _read_promotion_state

UTC = datetime.timezone.utc

OK = "ok"
WARN = "warn"
CRITICAL = "critical"
_SEVERITY_ORDER = {OK: 0, WARN: 1, CRITICAL: 2}

# Thresholds (chosen for a hourly-cadence tiny-live system on a personal Mac).
_DEAD_MAN_WARN_HOURS = 6.0
_TICK_STALE_WARN_HOURS = 26.0
_OUTBOX_BACKLOG_WARN = 10
_DISK_WARN_BYTES = 1 * 1024**3
_DISK_CRITICAL_BYTES = 200 * 1024**2


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class HealthReport:
    checks: list[HealthCheck] = field(default_factory=list)

    @property
    def overall(self) -> str:
        worst = OK
        for check in self.checks:
            if _SEVERITY_ORDER[check.status] > _SEVERITY_ORDER[worst]:
                worst = check.status
        return worst

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail}
                for c in self.checks
            ],
        }

    def render_plain(self) -> str:
        headline = {
            OK: "Your trading system looks healthy.",
            WARN: "Your trading system needs a look — some things are off.",
            CRITICAL: "Your trading system has a serious problem that needs attention.",
        }[self.overall]
        symbol = {OK: "OK", WARN: "CHECK", CRITICAL: "URGENT"}
        lines = [headline, ""]
        for check in self.checks:
            lines.append(f"[{symbol[check.status]}] {check.detail}")
        return "\n".join(lines)


def _hours_between(later: datetime.datetime, earlier: datetime.datetime) -> float:
    return (later - earlier).total_seconds() / 3600.0


def collect_health(inputs: dict[str, Any]) -> HealthReport:
    """Turn gathered facts into a health report. Pure and deterministic."""

    now: datetime.datetime = inputs["now"]
    checks: list[HealthCheck] = []

    # Dead-man timer — the freshness gate that keeps live trading fail-closed.
    expires = inputs.get("dead_man_expires_at")
    if not inputs.get("control_present", False) or expires is None:
        checks.append(HealthCheck("dead_man_timer", CRITICAL,
                                  "Live safety timer is missing — live trading is (correctly) blocked."))
    else:
        remaining = _hours_between(expires, now)
        if remaining <= 0:
            checks.append(HealthCheck("dead_man_timer", CRITICAL,
                                      "Live safety timer has expired — live trading is (correctly) blocked until refreshed."))
        elif remaining <= _DEAD_MAN_WARN_HOURS:
            checks.append(HealthCheck("dead_man_timer", WARN,
                                      f"Live safety timer expires in about {remaining:.0f} hour(s) — refresh soon to keep live trading armed."))
        else:
            checks.append(HealthCheck("dead_man_timer", OK,
                                      f"Live safety timer is fresh (about {remaining:.0f} hour(s) left)."))

    # Freeze state (intentional pause is not a fault, but the owner should know).
    if inputs.get("frozen", False):
        reason = inputs.get("frozen_reason") or "no reason recorded"
        checks.append(HealthCheck("live_freeze", WARN,
                                  f"Live trading is paused (frozen): {reason}."))

    # Promotion / which sleeve is live-enabled.
    live_sleeves = inputs.get("live_enabled_sleeves") or []
    if not inputs.get("promotion_present", False):
        checks.append(HealthCheck("promotion_state", WARN,
                                  "No promotion record found — no strategy is enabled for live trading."))
    elif live_sleeves:
        checks.append(HealthCheck("promotion_state", OK,
                                  f"Live strategy enabled: {', '.join(live_sleeves)}."))
    else:
        checks.append(HealthCheck("promotion_state", OK,
                                  "No strategy is enabled for live trading (paper only)."))

    # State integrity (tamper-evidence). Severity depends on the active mode.
    integrity_issues = inputs.get("integrity_issues") or []
    audit_issues = inputs.get("audit_issues") or []
    mode = inputs.get("integrity_mode", "warn")
    if integrity_issues or audit_issues:
        status = CRITICAL if mode == "enforce" else WARN
        detail_bits = list(integrity_issues) + list(audit_issues)
        checks.append(HealthCheck("state_integrity", status,
                                  "Safety-file integrity check flagged: " + "; ".join(detail_bits)))
    else:
        checks.append(HealthCheck("state_integrity", OK,
                                  f"Safety-file integrity checks pass (mode: {mode})."))

    # Last supervisor tick (is the automation actually running?).
    last_tick = inputs.get("last_tick_at")
    if last_tick is None:
        checks.append(HealthCheck("last_tick", WARN,
                                  "No recent activity record found — the automation may not have run yet."))
    else:
        age = _hours_between(now, last_tick)
        if age > _TICK_STALE_WARN_HOURS:
            checks.append(HealthCheck("last_tick", WARN,
                                      f"Last activity was about {age:.0f} hour(s) ago — the automation may be stopped."))
        else:
            checks.append(HealthCheck("last_tick", OK,
                                      f"Last activity was about {age:.0f} hour(s) ago."))

    # Outbox delivery backlog.
    backlog = int(inputs.get("outbox_backlog", 0) or 0)
    if backlog >= _OUTBOX_BACKLOG_WARN:
        checks.append(HealthCheck("outbox_backlog", WARN,
                                  f"{backlog} owner emails are queued but not delivered — email delivery may be broken."))
    else:
        checks.append(HealthCheck("outbox_backlog", OK,
                                  f"Email queue is clear ({backlog} waiting)."))

    # Disk space (packets are the source of truth; running out corrupts nothing but stops writes).
    free = inputs.get("disk_free_bytes")
    if free is not None:
        if free < _DISK_CRITICAL_BYTES:
            checks.append(HealthCheck("disk_space", CRITICAL,
                                      f"Very low disk space ({free / 1024**3:.1f} GB free)."))
        elif free < _DISK_WARN_BYTES:
            checks.append(HealthCheck("disk_space", WARN,
                                      f"Low disk space ({free / 1024**3:.1f} GB free)."))
        else:
            checks.append(HealthCheck("disk_space", OK,
                                      f"Disk space is fine ({free / 1024**3:.0f} GB free)."))

    # Credentials file hygiene (opsec).
    if inputs.get("env_present", False):
        mode_octal = str(inputs.get("env_mode_octal") or "")
        group_other_open = bool(mode_octal) and mode_octal[-2:] != "00"
        if inputs.get("env_git_tracked") is True:
            checks.append(HealthCheck("env_permissions", CRITICAL,
                                      "Your secrets file (.env) is tracked by git — keys could leak. Remove it from version control."))
        elif group_other_open:
            checks.append(HealthCheck("env_permissions", WARN,
                                      f"Your secrets file (.env) is readable by other users (mode {mode_octal}); tighten it to owner-only (chmod 600 .env)."))
        else:
            checks.append(HealthCheck("env_permissions", OK,
                                      "Your secrets file (.env) is owner-only."))

    # Credential hygiene (distinct live vs paper keys).
    hygiene_issues = inputs.get("key_hygiene_issues") or []
    if hygiene_issues:
        checks.append(HealthCheck("key_hygiene", WARN, "; ".join(hygiene_issues)))

    # Broker reachability — only present when explicitly checked.
    reachable = inputs.get("broker_reachable")
    if reachable is not None:
        if reachable:
            checks.append(HealthCheck("broker_reachability", OK, "Broker is reachable."))
        else:
            checks.append(HealthCheck("broker_reachability", WARN,
                                      "Broker did not respond — orders and price checks may be failing."))

    return HealthReport(checks=checks)


# --------------------------------------------------------------------------- I/O


def _env_mode_octal(env_path: Path) -> str | None:
    try:
        return oct(env_path.stat().st_mode & 0o777)[-3:]
    except OSError:
        return None


def _env_git_tracked(env_path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(env_path.name)],
            cwd=str(env_path.parent),
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def _newest_mtime(directory: Path) -> datetime.datetime | None:
    if not directory.exists():
        return None
    newest: float | None = None
    for path in directory.glob("*.json"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    if newest is None:
        return None
    return datetime.datetime.fromtimestamp(newest, tz=UTC)


def gather_health_inputs(
    *,
    control_path: Path = Path("results/policy/live_control.json"),
    promotion_path: Path = Path("results/policy/promotion_state.json"),
    tick_dir: Path = Path("results/hourly_supervisor"),
    outbox_dir: Path = Path("results/outbox"),
    env_path: Path = Path(".env"),
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Read-only gather of every health fact. No network, no orders."""

    current = now or datetime.datetime.now(tz=UTC)

    control_state, _control_issues = load_live_control_state(control_path, now=current)
    dead_man_expires_at = None
    frozen = False
    frozen_reason = ""
    if isinstance(control_state, dict):
        dead_man_expires_at = parse_control_time(str(control_state.get("dead_man_expires_at", "")))
        frozen = control_state.get("frozen") is True
        frozen_reason = str(control_state.get("reason") or "")

    promotion_state, _promo_issues = _read_promotion_state(promotion_path)
    live_sleeves: list[str] = []
    sleeves = promotion_state.get("sleeves") if isinstance(promotion_state, dict) else None
    if isinstance(sleeves, dict):
        live_sleeves = [
            name for name, rec in sleeves.items()
            if isinstance(rec, dict) and rec.get("live_enabled") is True
        ]

    mode = integrity.resolve_mode()
    integrity_issues: list[str] = []
    for state_path in (control_path, promotion_path):
        if state_path.exists():
            integrity_issues.extend(
                integrity.verify_state_integrity(state_path, state_path.read_text(encoding="utf-8"))
            )
    audit_issues = integrity.verify_audit_chain(integrity.audit_path(control_path))

    try:
        disk_free = shutil.disk_usage(str(control_path.parent if control_path.parent.exists() else Path.cwd())).free
    except OSError:
        disk_free = None

    return {
        "now": current,
        "control_present": isinstance(control_state, dict),
        "dead_man_expires_at": dead_man_expires_at,
        "frozen": frozen,
        "frozen_reason": frozen_reason,
        "promotion_present": bool(promotion_state),
        "live_enabled_sleeves": live_sleeves,
        "integrity_mode": mode,
        "integrity_issues": integrity_issues,
        "audit_issues": audit_issues,
        "last_tick_at": _newest_mtime(tick_dir),
        "outbox_backlog": len(list_undelivered(outbox_dir)),
        "disk_free_bytes": disk_free,
        "env_present": env_path.exists(),
        "env_mode_octal": _env_mode_octal(env_path) if env_path.exists() else None,
        "env_git_tracked": _env_git_tracked(env_path) if env_path.exists() else None,
        "key_hygiene_issues": check_key_hygiene(),
        "broker_reachable": None,
    }


def run_health_check(
    *,
    email_on_critical: bool = False,
    email_to: str = "",
    outbox_dir: Path = Path("results/outbox"),
    now: datetime.datetime | None = None,
    **gather_kwargs: Any,
) -> HealthReport:
    """Gather + evaluate; optionally queue a plain-language email if CRITICAL."""

    inputs = gather_health_inputs(outbox_dir=outbox_dir, now=now, **gather_kwargs)
    report = collect_health(inputs)
    if email_on_critical and report.overall == CRITICAL:
        write_outbox_message(
            {
                "email_to": email_to or os.environ.get("TRADINGAGENTS_OWNER_EMAIL", ""),
                "subject": "Trading system health: URGENT",
                "body": report.render_plain(),
            },
            outbox_dir=outbox_dir,
            report_type="health",
            severity="CRITICAL",
        )
    return report


def health_json(report: HealthReport) -> str:
    return json.dumps(report.to_dict(), indent=2)
