"""Read-only automation run-ledger audit for TradingAgents schedules."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

UTC = dt.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")

MANAGED_AUTOMATION_IDS = (
    "tradingagents-automation-wake-controller",
    "tradingagents-wake-verification",
    "hourly-market-supervisor",
    "paper-strategy-tournament-runner",
    "tradingagents-self-heal-monitor",
    "market-supervisor-15-min-before-open",
    "market-supervisor-30-min-after-open",
    "market-supervisor-30-min-before-close",
    "market-supervisor-15-min-after-close",
    "tradingagents-daily-market-report",
    "tradingagents-automation-sleep-controller",
    "tradingagents-night-shift-supervisor",
    "tradingagents-overnight-planning",
    "fetch-tradingagents-deep-research-report",
)

WAKE_CONTROLLER_DEPENDENT_AUTOMATIONS = (
    "hourly-market-supervisor",
    "paper-strategy-tournament-runner",
    "market-supervisor-15-min-before-open",
    "market-supervisor-30-min-after-open",
    "market-supervisor-30-min-before-close",
    "market-supervisor-15-min-after-close",
    "tradingagents-daily-market-report",
)

ARTIFACT_GLOBS = {
    "hourly-market-supervisor": ("results/hourly_supervisor/hourly-supervisor-*.json",),
    "paper-strategy-tournament-runner": (
        "results/paper_strategy_tournament/paper-tournament-run-*.json",
        "results/paper_strategy_tournament/alphainsider-paper-watch-*.json",
    ),
    "tradingagents-self-heal-monitor": (
        "results/self_heal/self-heal-handoff-*.json",
        "results/self_heal/plans/self-heal-plan-*.json",
    ),
    "market-supervisor-15-min-before-open": ("results/hourly_supervisor/hourly-supervisor-*.json",),
    "market-supervisor-30-min-after-open": ("results/hourly_supervisor/hourly-supervisor-*.json",),
    "market-supervisor-30-min-before-close": ("results/hourly_supervisor/hourly-supervisor-*.json",),
    "market-supervisor-15-min-after-close": ("results/hourly_supervisor/hourly-supervisor-*.json",),
    "tradingagents-daily-market-report": ("results/hourly_supervisor/hourly-supervisor-*.json",),
    "tradingagents-automation-sleep-controller": (
        "results/control_plane_patrol/sleep-controller-patrol-*.json",
    ),
    "tradingagents-automation-wake-controller": (
        "results/control_plane_patrol/wake-controller-patrol-*.json",
    ),
    "tradingagents-wake-verification": (
        "results/control_plane_patrol/wake-verification-patrol-*.json",
    ),
    "tradingagents-night-shift-supervisor": (
        "results/night_shift_patrol/night-shift-patrol-*.json",
    ),
    "tradingagents-overnight-planning": (
        "results/overnight_plans/overnight-plan-*.json",
    ),
    "fetch-tradingagents-deep-research-report": (
        "reports/research_merge/*.json",
        "reports/research_merge/*.md",
    ),
}

MEMORY_EVIDENCE_AUTOMATION_IDS = {
    "market-supervisor-15-min-before-open",
    "market-supervisor-30-min-after-open",
    "market-supervisor-30-min-before-close",
    "market-supervisor-15-min-after-close",
    "tradingagents-daily-market-report",
}

SHARED_HOURLY_SUPERVISOR_AUTOMATION_IDS = {
    "hourly-market-supervisor",
    "market-supervisor-15-min-before-open",
    "market-supervisor-30-min-after-open",
    "market-supervisor-30-min-before-close",
    "market-supervisor-15-min-after-close",
}

SELF_HEAL_HANDOFF_GLOB = "results/self_heal/self-heal-handoff-*.json"
SELF_HEAL_PLAN_GLOB = "results/self_heal/plans/self-heal-plan-*.json"
REAL_SIMULATION_AUDIT_GLOB = "results/real_simulation_audits/real-simulation-audit-*.json"
SCHEDULER_SETTLE_GRACE = dt.timedelta(minutes=15)
SETTLE_GRACE_BY_AUTOMATION = {
    "tradingagents-overnight-planning": dt.timedelta(minutes=120),
}
DUE_ALIGNED_ARTIFACT_AUTOMATION_IDS = {
    "tradingagents-overnight-planning",
}
NIGHT_SHIFT_EXPECTED_HOURS = {0, 4, 8, 12, 16, 20}
NIGHT_SHIFT_EXPECTED_MINUTES = {15}
NIGHT_SHIFT_EXPECTED_WEEKDAYS = set(range(7))
OVERNIGHT_PLANNER_ID = "tradingagents-overnight-planning"

HEALTH_BY_STATUS: dict[str, str] = {
    "ok": "healthy",
    "partial": "degraded",
    "late": "degraded",
    "duplicate": "degraded",
    "warning": "degraded",
    "stale": "critical",
    "missing": "critical",
}

PENDING_HEALTH_STATUSES = {"late", "partial", "warning", "duplicate", "missing", "stale"}

CATCH_UP_POLICY_BY_STATUS: dict[str, str] = {
    "ok": "no_manual_catch_up_required",
    "partial": "manual_catch_up_allowed_if_safe",
    "missing": "manual_catch_up_required",
    "late": "await_followup_before_catch_up",
    "duplicate": "investigate_before_catch_up",
    "warning": "review_before_catch_up",
    "stale": "review_before_catch_up",
}

TIMESTAMP_RUN_ID_RE = re.compile(r"(?<!\d)(\d{8}-\d{6}(?:-\d{1,6})?)(?!\d)")


def default_automation_root() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "automations"
    if os.name == "nt":
        return Path(r"C:\cm\automations")
    return Path.home() / ".codex" / "automations"


def _coerce_count(value: Any, *, fallback: Any | None = None) -> int:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if value is None:
        if isinstance(fallback, (list, tuple, set)):
            return len(fallback)
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(items: Sequence[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _first_nonempty(*values: Any) -> Any | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return None


def _now_iso(now: dt.datetime) -> str:
    return now.astimezone(UTC).isoformat(timespec="seconds")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _managed_automation_ids(automation_root: Path) -> tuple[str, ...]:
    current_configs = sorted(automation_root.glob("tradingagents-*/automation.toml"))
    current_ids = tuple(path.parent.name for path in current_configs)
    if any(
        automation_id in current_ids
        for automation_id in (
            "tradingagents-autonomous-safety-sentinel",
            "tradingagents-autonomous-self-healer",
        )
    ):
        return current_ids
    return MANAGED_AUTOMATION_IDS


def _session_index_latest_times(
    automation_root: Path,
    *,
    automation_ids: Sequence[str],
) -> dict[str, dt.datetime]:
    names_by_id: dict[str, str] = {}
    for automation_id in automation_ids:
        config = _read_toml(automation_root / automation_id / "automation.toml")
        name = str(config.get("name") or "").strip()
        if name:
            names_by_id[automation_id] = name
    if not names_by_id:
        return {}

    session_index = automation_root.parent / "session_index.jsonl"
    try:
        lines = session_index.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}

    ids_by_name = {name: automation_id for automation_id, name in names_by_id.items()}
    latest: dict[str, dt.datetime] = {}
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        automation_id = ids_by_name.get(str(payload.get("thread_name") or ""))
        updated_at = payload.get("updated_at")
        if automation_id is None or not updated_at:
            continue
        try:
            parsed = dt.datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        if automation_id not in latest or parsed > latest[automation_id]:
            latest[automation_id] = parsed
    return latest


def _is_paused_config(config: dict[str, Any]) -> bool:
    return str(config.get("status") or "").strip().upper() == "PAUSED"


def _parse_generated_at(path: Path) -> dt.datetime | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("generated_at", "completed_at", "created_at"):
        value = payload.get(key)
        if not value:
            continue
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _artifact_time(path: Path) -> dt.datetime:
    parsed = _parse_generated_at(path)
    if parsed is not None:
        return parsed
    return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _read_packet_metrics(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"unreadable": True}
    if not isinstance(payload, dict):
        return {"unreadable": True}
    submitted_list = payload.get("submitted") or payload.get("submitted_orders") or []
    actions = payload.get("actions") or []
    warnings = payload.get("warnings") or []
    errors = payload.get("errors") or payload.get("blockers") or []
    issues = payload.get("issues") or payload.get("blockers") or []
    mode = _first_nonempty(
        payload.get("execution_mode"),
        payload.get("mode"),
        payload.get("analysis_mode"),
        payload.get("mode_hint"),
    )
    run_id = _first_nonempty(payload.get("run_id"), payload.get("runId"), payload.get("run"))
    stale_count = payload.get("stale_count")
    submitted_count = _coerce_count(
        payload.get("submitted_count") or payload.get("submitted_order_count"),
        fallback=submitted_list,
    )
    issue_count = _coerce_count(payload.get("issue_count"), fallback=issues)
    if issue_count == 0:
        issue_count = _coerce_count(issues)
    if issue_count == 0 and isinstance(issues, list):
        issue_count = len(issues)
    action_count = _coerce_count(payload.get("action_count"), fallback=actions)
    warning_count = _coerce_count(payload.get("warning_count"), fallback=warnings)
    error_count = _coerce_count(payload.get("error_count"), fallback=errors)
    stale_count = _coerce_count(stale_count)
    metrics = {
        "unreadable": False,
        "run_id": str(run_id) if run_id is not None else None,
        "mode": str(mode) if mode is not None else None,
        "submitted_count": int(submitted_count),
        "issue_count": issue_count,
        "action_count": int(action_count),
        "warning_count": int(warning_count),
        "error_count": int(error_count),
        "stale_count": int(stale_count),
    }
    if "overnight_plans" in str(path).replace("\\", "/"):
        quality = payload.get("overnight_quality")
        if not isinstance(quality, Mapping):
            quality = {
                "completion_status": payload.get("completion_status"),
                "graph_failure_count": payload.get("graph_failure_count"),
                "full_graph_success_count": payload.get("full_graph_success_count"),
            }
        metrics.update(
            {
                "analysis_only": payload.get("analysis_only"),
                "trade_date": payload.get("trade_date"),
                "submitted": submitted_list if isinstance(submitted_list, list) else [],
                "overnight_quality": dict(quality),
            }
        )
    return metrics


def _read_packet(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path.absolute()).casefold()


def _repo_path_key(repo_root: Path, path_like: Any) -> str | None:
    if not path_like:
        return None
    path = Path(str(path_like))
    if not path.is_absolute():
        path = repo_root / path
    return _path_key(path)


def _artifact_role(path: Path) -> str:
    name = path.name
    if name.startswith("paper-tournament-run-"):
        return "paper_tournament_run"
    if name.startswith("alphainsider-paper-watch-"):
        return "alphainsider_paper_watch"
    if name.startswith("self-heal-handoff-"):
        return "self_heal_handoff"
    if name.startswith("self-heal-plan-"):
        return "self_heal_plan"
    return path.stem


def _real_simulation_observer_paths(
    repo_root: Path,
    *,
    window_start: dt.datetime,
    now: dt.datetime,
) -> set[str]:
    """Artifacts generated by the audit harness should not look like scheduler duplicates."""
    observer_paths: set[str] = set()
    for audit_path in sorted(repo_root.glob(REAL_SIMULATION_AUDIT_GLOB)):
        try:
            audit_time = _artifact_time(audit_path)
        except OSError:
            continue
        if audit_time < window_start or audit_time > now:
            continue
        payload = _read_packet(audit_path)
        commands = payload.get("commands")
        if not isinstance(commands, list):
            continue
        for command in commands:
            if not isinstance(command, dict):
                continue
            packet_paths = command.get("packet_paths")
            if not isinstance(packet_paths, list):
                continue
            for packet_path in packet_paths:
                key = _repo_path_key(repo_root, packet_path)
                if key:
                    observer_paths.add(key)
    return observer_paths


def _parse_rrule(rrule: str) -> dict[str, Any]:
    text = rrule.strip()
    if text.upper().startswith("RRULE:"):
        text = text.split(":", 1)[1]
    parsed: dict[str, Any] = {}
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.upper()] = value
    return parsed


def _int_list(value: str | None, default: tuple[int, ...]) -> list[int]:
    if not value:
        return list(default)
    result = []
    for piece in value.split(","):
        try:
            result.append(int(piece))
        except ValueError:
            continue
    return result or list(default)


def _weekday_list(value: str | None) -> set[int]:
    mapping = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    if not value:
        return set(range(7))
    return {mapping[piece] for piece in value.split(",") if piece in mapping}


def _due_times(
    rrule: str,
    *,
    now: dt.datetime,
    window_start: dt.datetime,
) -> list[dt.datetime]:
    rule = _parse_rrule(rrule)
    count = int(rule.get("COUNT") or "0")
    if count == 1:
        return []
    freq = str(rule.get("FREQ") or "").upper()
    minutes = _int_list(rule.get("BYMINUTE"), (0,))
    weekdays = _weekday_list(rule.get("BYDAY"))
    due: list[dt.datetime] = []
    local_start = window_start.astimezone(CENTRAL).replace(second=0, microsecond=0)
    local_end = now.astimezone(CENTRAL).replace(second=0, microsecond=0)
    current = local_start
    while current <= local_end:
        if current.weekday() in weekdays:
            if freq == "HOURLY" and current.minute in minutes:
                due.append(current.astimezone(UTC))
            elif freq in {"DAILY", "WEEKLY"}:
                hours = _int_list(rule.get("BYHOUR"), (current.hour,))
                if current.hour in hours and current.minute in minutes:
                    due.append(current.astimezone(UTC))
        current += dt.timedelta(minutes=1)
    return due


def _schedule_config_issues(automation_id: str, rrule: str) -> list[str]:
    if automation_id != "tradingagents-night-shift-supervisor":
        return []
    rule = _parse_rrule(rrule)
    freq = str(rule.get("FREQ") or "").upper()
    hours = set(_int_list(rule.get("BYHOUR"), ()))
    minutes = set(_int_list(rule.get("BYMINUTE"), ()))
    weekdays = _weekday_list(rule.get("BYDAY"))
    if (
        freq == "WEEKLY"
        and hours == NIGHT_SHIFT_EXPECTED_HOURS
        and minutes == NIGHT_SHIFT_EXPECTED_MINUTES
        and weekdays == NIGHT_SHIFT_EXPECTED_WEEKDAYS
    ):
        return []
    return ["night_shift_cadence_mismatch"]


def _filter_overnight_due_times_for_market_need(
    automation_id: str,
    due_times: Sequence[dt.datetime],
) -> list[dt.datetime]:
    if automation_id != OVERNIGHT_PLANNER_ID:
        return list(due_times)
    # The overnight planner can run on weekend nights when it prepares the next
    # useful market morning, but Saturday 02:30 local is not a useful U.S.
    # regular-session prep point. Sunday remains due for Monday preparation.
    return [
        due_time
        for due_time in due_times
        if due_time.astimezone(CENTRAL).weekday() != 5
    ]


def _config_effective_time(config: Mapping[str, Any]) -> dt.datetime | None:
    """Return when the current automation config became judgeable, if known."""

    candidates: list[dt.datetime] = []
    for key in ("updated_at", "created_at"):
        value = config.get(key)
        parsed: dt.datetime | None = None
        if isinstance(value, (int, float)):
            raw = float(value)
            if raw > 10_000_000_000:
                raw /= 1000
            try:
                parsed = dt.datetime.fromtimestamp(raw, tz=UTC)
            except (OSError, OverflowError, ValueError):
                parsed = None
        elif isinstance(value, str) and value.strip():
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is not None and parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
        if parsed is not None:
            candidates.append(parsed.astimezone(UTC))
    return max(candidates) if candidates else None


def _apply_config_effective_floor(
    due_times: Sequence[dt.datetime],
    *,
    config_effective_time: dt.datetime | None,
) -> list[dt.datetime]:
    if config_effective_time is None:
        return list(due_times)
    floor = config_effective_time.astimezone(UTC)
    return [due_time for due_time in due_times if due_time.astimezone(UTC) >= floor]


def _memory_latest_time(path: Path) -> dt.datetime | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    matches = re.findall(r"\b20\d\d-\d\d-\d\d(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?)?", text)
    parsed: list[dt.datetime] = []
    date_only_dates: set[dt.date] = set()
    for value in matches:
        try:
            item = dt.datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError:
            continue
        value_has_clock = ":" in value
        if item.tzinfo is None:
            item = item.replace(tzinfo=CENTRAL)
        if not value_has_clock:
            date_only_dates.add(item.astimezone(CENTRAL).date())
        parsed.append(item.astimezone(UTC))
    try:
        file_time = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        file_time = None
    if file_time is not None and (
        not parsed or file_time.astimezone(CENTRAL).date() in date_only_dates
    ):
        parsed.append(file_time)
    return max(parsed) if parsed else None


def _latest_controller_due(
    controller_id: str,
    *,
    schedule_due_times: dict[str, list[dt.datetime]],
    memory_time: dt.datetime | None,
) -> dt.datetime | None:
    due_times = schedule_due_times.get(controller_id, [])
    if not due_times:
        return memory_time
    latest_due = max(due_times)
    if memory_time is None:
        return None
    # Date-only controller memories parse to midnight. Treat same-day memory as
    # proof the scheduled controller pass happened at its configured due time.
    if memory_time.astimezone(CENTRAL).date() == latest_due.astimezone(CENTRAL).date():
        return latest_due
    return memory_time


def _apply_controller_active_window(
    automation_id: str,
    due_times: Sequence[dt.datetime],
    *,
    current_status_active: bool,
    wake_effective_time: dt.datetime | None,
    sleep_effective_time: dt.datetime | None,
) -> list[dt.datetime]:
    if automation_id not in WAKE_CONTROLLER_DEPENDENT_AUTOMATIONS:
        return list(due_times)
    if not current_status_active:
        return []
    if wake_effective_time is None:
        return list(due_times)
    if sleep_effective_time is not None and sleep_effective_time > wake_effective_time:
        return []
    return [due_time for due_time in due_times if due_time >= wake_effective_time]


def _controller_active_floor(
    automation_id: str,
    *,
    current_status_active: bool,
    wake_effective_time: dt.datetime | None,
    sleep_effective_time: dt.datetime | None,
) -> dt.datetime | None:
    if automation_id not in WAKE_CONTROLLER_DEPENDENT_AUTOMATIONS:
        return None
    if not current_status_active or wake_effective_time is None:
        return None
    if sleep_effective_time is not None and sleep_effective_time > wake_effective_time:
        return None
    return wake_effective_time


def _settled_due_times(
    due_times: Sequence[dt.datetime],
    *,
    now: dt.datetime,
    grace: dt.timedelta = SCHEDULER_SETTLE_GRACE,
) -> list[dt.datetime]:
    cutoff = now - grace
    return [due_time for due_time in due_times if due_time <= cutoff]


def _discover_artifacts(
    repo_root: Path,
    automation_id: str,
    *,
    window_start: dt.datetime,
    now: dt.datetime,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for pattern in ARTIFACT_GLOBS.get(automation_id, ()):
        for path in sorted(repo_root.glob(pattern)):
            if _is_compact_json_artifact(path):
                continue
            try:
                artifact_time = _artifact_time(path)
            except OSError:
                continue
            if artifact_time < window_start or artifact_time > now:
                continue
            metrics = _read_packet_metrics(path) if path.suffix.lower() == ".json" else {}
            artifacts.append(
                {
                    "path": str(path),
                    "artifact_role": _artifact_role(path),
                    "generated_at": artifact_time.isoformat(timespec="seconds"),
                    **metrics,
                }
            )
    return sorted(artifacts, key=lambda item: item["generated_at"])


def _filter_hourly_supervisor_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    automation_due_times: list[dt.datetime],
    other_due_times: dict[str, list[dt.datetime]],
    grace_minutes: int = 15,
) -> list[dict[str, Any]]:
    if not artifacts or not automation_due_times:
        return artifacts
    filtered: list[dict[str, Any]] = []
    grace = dt.timedelta(minutes=grace_minutes)
    for artifact in artifacts:
        try:
            artifact_time = dt.datetime.fromisoformat(str(artifact["generated_at"]))
        except (KeyError, ValueError):
            filtered.append(artifact)
            continue
        if artifact_time.tzinfo is None:
            artifact_time = artifact_time.replace(tzinfo=UTC)
        artifact_time = artifact_time.astimezone(UTC)

        best_owner = "hourly-market-supervisor"
        best_due_time: dt.datetime | None = None
        best_delta: float | None = None
        for owner, due_times in {
            "hourly-market-supervisor": automation_due_times,
            **other_due_times,
        }.items():
            for due_time in due_times:
                delta_seconds = abs((artifact_time - due_time).total_seconds())
                if best_delta is None or delta_seconds < best_delta:
                    best_owner = owner
                    best_due_time = due_time
                    best_delta = delta_seconds
        if best_owner != "hourly-market-supervisor" or best_due_time is None:
            continue
        if artifact_time < best_due_time or artifact_time - best_due_time > grace:
            continue
        filtered.append(artifact)
    return filtered


def _filter_artifacts_after_due_start(
    artifacts: list[dict[str, Any]],
    *,
    due_times: Sequence[dt.datetime],
) -> list[dict[str, Any]]:
    if not artifacts or not due_times:
        return artifacts
    earliest_due = min(due_times).astimezone(UTC)
    filtered: list[dict[str, Any]] = []
    for artifact in artifacts:
        try:
            artifact_time = dt.datetime.fromisoformat(str(artifact["generated_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if artifact_time.tzinfo is None:
            artifact_time = artifact_time.replace(tzinfo=UTC)
        if artifact_time.astimezone(UTC) >= earliest_due:
            filtered.append(artifact)
    return filtered


def _classification_memory_time(
    automation_id: str,
    *,
    memory_time: dt.datetime | None,
    due_times: Sequence[dt.datetime],
    artifact_count: int,
) -> dt.datetime | None:
    if automation_id not in DUE_ALIGNED_ARTIFACT_AUTOMATION_IDS:
        return memory_time
    if not due_times:
        return memory_time
    latest_due = max(due_times).astimezone(UTC)
    if memory_time is None or memory_time < latest_due or artifact_count == 0:
        return None
    return memory_time


def _classify(
    *,
    due_count: int,
    artifact_count: int,
    memory_time: dt.datetime | None,
    window_start: dt.datetime,
    submitted_count: int,
    issue_count: int,
    duplicate_count: int,
    overlap_count: int,
) -> tuple[str, list[str], str | None]:
    issues: list[str] = []
    if submitted_count:
        issues.append("submitted_order")
    if issue_count:
        issues.append("packet_issue")
    if duplicate_count:
        issues.append("duplicate_run")
        return "duplicate", issues, f"near_duplicate_artifacts:{duplicate_count}"
    if due_count and artifact_count == 0 and memory_time is None:
        issues.append("missed_run")
        return (
            "missing",
            issues,
            "no_artifacts_seen_and_no_recent_memory",
        )
    if due_count and artifact_count < due_count and artifact_count > 0:
        issues.append("missed_run")
        return (
            "partial",
            issues,
            f"observed_runs_less_than_expected:{artifact_count}/{due_count}",
        )
    if due_count and artifact_count > max(1, due_count * 2):
        issues.append("duplicate_run")
        return (
            "duplicate",
            issues,
            "observed_runs_exceed_expected_windows",
        )
    if due_count and artifact_count == 0 and memory_time is not None and memory_time < window_start:
        issues.append("stale_memory")
        return (
            "stale",
            issues,
            f"memory_stale_before_window:{memory_time.isoformat(timespec='seconds')}",
        )
    if submitted_count or issue_count:
        return "warning", issues, "packet_status_has_warning_flags"
    if overlap_count:
        issues.append("overlap_run")
    return "ok", issues, None


def _artifact_records(
    repo_root: Path,
    pattern: str,
    *,
    window_start: dt.datetime,
    now: dt.datetime,
) -> list[tuple[dt.datetime, Path, dict[str, Any]]]:
    records: list[tuple[dt.datetime, Path, dict[str, Any]]] = []
    for path in sorted(repo_root.glob(pattern)):
        if _is_compact_json_artifact(path):
            continue
        try:
            artifact_time = _artifact_time(path)
        except OSError:
            continue
        if artifact_time < window_start or artifact_time > now:
            continue
        records.append((artifact_time, path, _read_packet(path)))
    return sorted(records, key=lambda item: item[0])


def _is_compact_json_artifact(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() == ".json" and (
        name.endswith(".compact.json") or name == "latest-compact.json"
    )


def _run_id_for_path(path: Path) -> str | None:
    stem = path.stem
    if stem.lower() in {"latest", "current"}:
        return None
    match = TIMESTAMP_RUN_ID_RE.search(stem)
    if match:
        return match.group(1)
    return stem or None


def _collect_run_ids(artifacts: Sequence[dict[str, Any]]) -> list[str]:
    run_ids: list[str] = []
    for artifact in artifacts:
        run_id = artifact.get("run_id")
        if run_id:
            run_ids.append(str(run_id))
            continue
        path = Path(str(artifact.get("path") or ""))
        if path.name:
            inferred = _run_id_for_path(path)
            if inferred:
                run_ids.append(inferred)
    return [item for item in _dedupe(run_ids) if item]


def _count_overlapping_artifacts(
    artifacts: Sequence[dict[str, Any]],
    *,
    due_times: Sequence[dt.datetime],
    max_delta_seconds: int = 900,
    same_role_only: bool = False,
) -> int:
    if not artifacts or not due_times:
        return 0
    if len(due_times) == 0:
        return 0
    due_list = sorted(due_times)
    buckets: dict[str, int] = {}
    for artifact in artifacts:
        generated_at = artifact.get("generated_at")
        if not generated_at:
            continue
        try:
            artifact_time = dt.datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        if artifact_time.tzinfo is None:
            artifact_time = artifact_time.replace(tzinfo=UTC)
        artifact_time = artifact_time.astimezone(UTC)
        nearest = min(
            due_list,
            key=lambda due_time: abs((artifact_time - due_time).total_seconds()),
        )
        if abs((artifact_time - nearest).total_seconds()) > max_delta_seconds:
            continue
        role = str(artifact.get("artifact_role") or "artifact")
        key = nearest.isoformat(timespec="seconds")
        if same_role_only:
            key = f"{key}:{role}"
        buckets[key] = buckets.get(key, 0) + 1
    overlap_count = 0
    for count in buckets.values():
        if count > 1:
            overlap_count += count - 1
    return overlap_count


def _count_near_duplicate_artifacts(
    artifacts: Sequence[dict[str, Any]],
    *,
    seconds: int = 120,
    same_role_only: bool = False,
) -> int:
    previous: dt.datetime | None = None
    previous_by_role: dict[str, dt.datetime] = {}
    duplicate_count = 0
    for item in artifacts:
        try:
            current = dt.datetime.fromisoformat(str(item["generated_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        if same_role_only:
            role = str(item.get("artifact_role") or "artifact")
            previous_for_role = previous_by_role.get(role)
            if previous_for_role is not None and (current - previous_for_role).total_seconds() <= seconds:
                duplicate_count += 1
            previous_by_role[role] = current
        else:
            if previous is not None and (current - previous).total_seconds() <= seconds:
                duplicate_count += 1
            previous = current
    return duplicate_count


def _has_near_duplicate_artifacts(artifacts: list[dict[str, Any]], *, seconds: int = 120) -> bool:
    return _count_near_duplicate_artifacts(artifacts, seconds=seconds) > 0


def _health_status_for_job_status(status: str) -> str:
    return HEALTH_BY_STATUS.get(status, "unknown")


def _iso_or_none(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _self_heal_timeliness(
    repo_root: Path,
    *,
    window_start: dt.datetime,
    now: dt.datetime,
    sla_minutes: int,
) -> dict[str, Any]:
    handoffs = _artifact_records(repo_root, SELF_HEAL_HANDOFF_GLOB, window_start=window_start, now=now)
    actionable_handoffs = [
        (timestamp, path, payload)
        for timestamp, path, payload in handoffs
        if payload.get("should_start_new_chat") is True
        or int(payload.get("active_plan_count") or 0) > 0
        or int(payload.get("trigger_count") or 0) > 0
    ]
    latest_handoff = actionable_handoffs[-1] if actionable_handoffs else None
    latest_handoff_at = latest_handoff[0] if latest_handoff else None
    plans_after_handoff: list[tuple[dt.datetime, Path, dict[str, Any]]] = []
    if latest_handoff_at is not None:
        plans_after_handoff = [
            record
            for record in _artifact_records(repo_root, SELF_HEAL_PLAN_GLOB, window_start=latest_handoff_at, now=now)
            if record[0] >= latest_handoff_at
        ]
    first_plan = plans_after_handoff[0] if plans_after_handoff else None
    first_plan_at = first_plan[0] if first_plan else None
    latest_plan = plans_after_handoff[-1] if plans_after_handoff else None
    latest_observed_plan_at = latest_plan[0] if latest_plan else None
    lag_seconds: int | None = None
    timely: bool | None = None
    issue: str | None = None
    if latest_handoff_at is not None:
        if first_plan_at is None:
            timely = False
            if (now - latest_handoff_at).total_seconds() > sla_minutes * 60:
                issue = "self_heal_plan_late"
            else:
                issue = "self_heal_plan_pending"
        else:
            lag_seconds = int((first_plan_at - latest_handoff_at).total_seconds())
            timely = lag_seconds <= sla_minutes * 60
            if not timely:
                issue = "self_heal_plan_late"
    return {
        "sla_minutes": sla_minutes,
        "latest_actionable_handoff_at": _iso_or_none(latest_handoff_at),
        "latest_followup_plan_at": _iso_or_none(first_plan_at),
        "latest_observed_plan_at": _iso_or_none(latest_observed_plan_at),
        "followup_lag_seconds": lag_seconds,
        "timely": timely,
        "issue": issue,
    }


def _extract_artifact_timeline(
    artifacts: Sequence[dict[str, Any]],
) -> list[tuple[dt.datetime, str]]:
    timeline: list[tuple[dt.datetime, str]] = []
    for item in artifacts:
        generated_at = item.get("generated_at")
        if not generated_at:
            continue
        path = str(item.get("path") or "")
        try:
            parsed = dt.datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        timeline.append((parsed.astimezone(UTC), path))
    return sorted(timeline, key=lambda item: item[0])


def _overnight_duplicate_artifacts_are_benign(
    artifacts: Sequence[dict[str, Any]],
) -> bool:
    if not artifacts:
        return False
    trade_dates: set[str] = set()
    for artifact in artifacts:
        if artifact.get("analysis_only") is not True:
            return False
        if int(artifact.get("submitted_count") or 0) != 0:
            return False
        if int(artifact.get("issue_count") or 0) != 0:
            return False
        submitted = artifact.get("submitted")
        if isinstance(submitted, list) and submitted:
            return False
        quality = artifact.get("overnight_quality")
        if not isinstance(quality, Mapping):
            return False
        if str(quality.get("completion_status") or "").lower() != "complete":
            return False
        if int(quality.get("graph_failure_count") or 0) != 0:
            return False
        trade_date = str(artifact.get("trade_date") or "").strip()
        if trade_date:
            trade_dates.add(trade_date)
    return len(trade_dates) <= 1


def _overnight_duplicate_artifacts_are_superseded_repair_reruns(
    artifacts: Sequence[dict[str, Any]],
) -> bool:
    """Return true for no-order overnight repair reruns that superseded stale output.

    The first stale-latest repair can leave multiple analysis-only overnight
    packets in the audit window. Once a later complete rerun exists for a newer
    trade date, the old packet should remain as evidence but should not keep
    self-heal paging on scheduler-overlap noise.
    """

    if not artifacts or not _overnight_duplicate_artifacts_are_safe_no_order(artifacts):
        return False
    trade_dates = [
        str(artifact.get("trade_date") or "").strip()
        for artifact in artifacts
        if str(artifact.get("trade_date") or "").strip()
    ]
    if len(set(trade_dates)) <= 1:
        return False
    latest_artifact = max(
        artifacts,
        key=lambda item: str(item.get("generated_at") or ""),
    )
    latest_trade_date = str(latest_artifact.get("trade_date") or "").strip()
    return bool(latest_trade_date and latest_trade_date == max(trade_dates))


def _overnight_duplicate_artifacts_are_safe_no_order(
    artifacts: Sequence[dict[str, Any]],
) -> bool:
    for artifact in artifacts:
        if artifact.get("analysis_only") is not True:
            return False
        if int(artifact.get("submitted_count") or 0) != 0:
            return False
        if int(artifact.get("issue_count") or 0) != 0:
            return False
        submitted = artifact.get("submitted")
        if isinstance(submitted, list) and submitted:
            return False
        quality = artifact.get("overnight_quality")
        if not isinstance(quality, Mapping):
            return False
        if str(quality.get("completion_status") or "").lower() != "complete":
            return False
        if int(quality.get("graph_failure_count") or 0) != 0:
            return False
    return True


def _format_expected_times(
    due_times: Sequence[dt.datetime],
    *,
    max_items: int = 3,
) -> str:
    if not due_times:
        return "none"
    rendered = [item.isoformat(timespec="seconds") for item in due_times]
    if len(rendered) <= max_items:
        return ", ".join(rendered)
    return ", ".join(rendered[:max_items]) + f", +{len(rendered) - max_items} more"


def _impact_and_action_for_status(status: str) -> tuple[str, str]:
    if status == "missing":
        return (
            "Missing scheduled evidence can leave dead-man and lock freshness blind spots for live control.",
            "Check the automation schedule and rerun the job for the missed window.",
        )
    if status == "partial":
        return (
            "Partial packet capture reduces confidence in run continuity for this automation and guardrail signals.",
            "Verify scheduler timing, then rerun the job after the next interval to cover missed windows.",
        )
    if status == "duplicate":
        return (
            "Duplicate packets can indicate overlapping triggers and may confuse manual follow-up decisions.",
            "Audit scheduler overlap and reduce duplicated invocations before any live-action approval.",
        )
    if status == "late":
        return (
            "Self-heal follow-up is delayed, so live-control remediation visibility is stale.",
            "Execute or schedule the self-heal follow-up before assuming controls are restored.",
        )
    return ("No additional action needed for run integrity.", "Run once and verify the latest packet.")


def _build_problem_jobs(
    *,
    status: str,
    due_times: Sequence[dt.datetime],
    artifact_timeline: Sequence[tuple[dt.datetime, str]],
    self_heal_timeliness: dict[str, Any] | None = None,
    handoff_timeline: Sequence[tuple[dt.datetime, str]] = (),
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if status == "ok":
        return jobs

    expected = _format_expected_times(due_times)
    artifact_count = len(artifact_timeline)
    latest_path = artifact_timeline[-1][1] if artifact_timeline else None
    latest_time = (
        artifact_timeline[-1][0].isoformat(timespec="seconds")
        if artifact_timeline
        else None
    )
    live_impact, user_action = _impact_and_action_for_status(status)

    if status == "missing":
        jobs.append(
            {
                "job": "missed run",
                "expected_time": expected,
                "actual_status": f"expected_runs={len(due_times)}; none seen",
                "actual_time": None,
                "evidence_path": None,
                "live_impact": live_impact,
                "user_action": user_action,
            }
        )
        return jobs

    if status == "partial":
        jobs.append(
            {
                "job": "partial run",
                "expected_time": expected,
                "actual_status": f"{artifact_count}/{len(due_times)} runs observed",
                "actual_time": latest_time,
                "evidence_path": latest_path,
                "live_impact": live_impact,
                "user_action": user_action,
            }
        )
        return jobs

    if status == "duplicate":
        duplicate_count = max(0, artifact_count - len(due_times))
        if not duplicate_count and artifact_count:
            duplicate_count = 1
        jobs.append(
            {
                "job": "duplicate run",
                "expected_time": expected,
                "actual_status": f"unexpected extra packets: {duplicate_count}",
                "actual_time": latest_time,
                "evidence_path": latest_path,
                "live_impact": live_impact,
                "user_action": user_action,
            }
        )
        return jobs

    if status == "late" and self_heal_timeliness is not None:
        expected_time = self_heal_timeliness.get("latest_actionable_handoff_at") or expected
        actual_time = self_heal_timeliness.get("latest_followup_plan_at")
        handoff_paths = [path for _, path in handoff_timeline]
        jobs.append(
            {
                "job": "late run",
                "expected_time": str(expected_time),
                "actual_status": f"follow-up plan status: {actual_time or 'pending'}",
                "actual_time": actual_time,
                "evidence_path": handoff_paths[-1] if handoff_paths else latest_path,
                "live_impact": live_impact,
                "user_action": user_action,
            }
        )

    return jobs


def build_automation_health_audit(
    *,
    repo_root: str | Path = ".",
    automation_root: str | Path = r"C:\cm\automations",
    now: dt.datetime | None = None,
    window_hours: int = 24,
    self_heal_plan_sla_minutes: int = 30,
) -> dict[str, Any]:
    current = now or dt.datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    window_start = current - dt.timedelta(hours=window_hours)
    repo = Path(repo_root)
    auto_root = Path(automation_root)
    managed_automation_ids = _managed_automation_ids(auto_root)
    session_index_times = _session_index_latest_times(
        auto_root,
        automation_ids=managed_automation_ids,
    )
    observer_paths = _real_simulation_observer_paths(
        repo,
        window_start=window_start,
        now=current,
    )
    schedule_due_times: dict[str, list[dt.datetime]] = {}
    for automation_id in managed_automation_ids:
        config = _read_toml(auto_root / automation_id / "automation.toml")
        rrule = str(config.get("rrule") or "")
        schedule_due_times[automation_id] = (
            _due_times(rrule, now=current, window_start=window_start) if rrule else []
        )
    controller_memory_times = {
        controller_id: _memory_latest_time(auto_root / controller_id / "memory.md")
        for controller_id in (
            "tradingagents-automation-wake-controller",
            "tradingagents-automation-sleep-controller",
        )
    }
    wake_effective_time = _latest_controller_due(
        "tradingagents-automation-wake-controller",
        schedule_due_times=schedule_due_times,
        memory_time=controller_memory_times.get("tradingagents-automation-wake-controller"),
    )
    sleep_effective_time = _latest_controller_due(
        "tradingagents-automation-sleep-controller",
        schedule_due_times=schedule_due_times,
        memory_time=controller_memory_times.get("tradingagents-automation-sleep-controller"),
    )
    rows: list[dict[str, Any]] = []
    unique_submitted_by_path: dict[str, int] = {}
    unique_issues_by_path: dict[str, int] = {}
    for automation_id in managed_automation_ids:
        config_path = auto_root / automation_id / "automation.toml"
        memory_path = auto_root / automation_id / "memory.md"
        config = _read_toml(config_path)
        rrule = str(config.get("rrule") or "")
        config_effective_time = _config_effective_time(config)
        scheduled_due_times = _filter_overnight_due_times_for_market_need(
            automation_id,
            schedule_due_times.get(automation_id, []),
        )
        is_paused = _is_paused_config(config)
        active_floor = _controller_active_floor(
            automation_id,
            current_status_active=not is_paused,
            wake_effective_time=wake_effective_time,
            sleep_effective_time=sleep_effective_time,
        )
        due_times = _settled_due_times(
            _apply_config_effective_floor(
                _apply_controller_active_window(
                    automation_id,
                    scheduled_due_times,
                    current_status_active=not is_paused,
                    wake_effective_time=wake_effective_time,
                    sleep_effective_time=sleep_effective_time,
                ),
                config_effective_time=config_effective_time,
            ),
            now=current,
            grace=SETTLE_GRACE_BY_AUTOMATION.get(automation_id, SCHEDULER_SETTLE_GRACE),
        )
        artifacts = (
            []
            if automation_id in MEMORY_EVIDENCE_AUTOMATION_IDS
            else _discover_artifacts(repo, automation_id, window_start=window_start, now=current)
        )
        if active_floor is not None and artifacts:
            active_artifacts: list[dict[str, Any]] = []
            for artifact in artifacts:
                try:
                    artifact_time = dt.datetime.fromisoformat(
                        str(artifact["generated_at"]).replace("Z", "+00:00")
                    )
                except (KeyError, ValueError):
                    active_artifacts.append(artifact)
                    continue
                if artifact_time.tzinfo is None:
                    artifact_time = artifact_time.replace(tzinfo=UTC)
                if artifact_time.astimezone(UTC) >= active_floor:
                    active_artifacts.append(artifact)
            artifacts = active_artifacts
        if config_effective_time is not None and artifacts:
            effective_artifacts: list[dict[str, Any]] = []
            for artifact in artifacts:
                try:
                    artifact_time = dt.datetime.fromisoformat(
                        str(artifact["generated_at"]).replace("Z", "+00:00")
                    )
                except (KeyError, ValueError):
                    effective_artifacts.append(artifact)
                    continue
                if artifact_time.tzinfo is None:
                    artifact_time = artifact_time.replace(tzinfo=UTC)
                if artifact_time.astimezone(UTC) >= config_effective_time.astimezone(UTC):
                    effective_artifacts.append(artifact)
            artifacts = effective_artifacts
        observer_artifact_count = 0
        if observer_paths and artifacts:
            kept_artifacts: list[dict[str, Any]] = []
            for artifact in artifacts:
                artifact_key = _repo_path_key(repo, artifact.get("path"))
                if artifact_key and artifact_key in observer_paths:
                    observer_artifact_count += 1
                    continue
                kept_artifacts.append(artifact)
            artifacts = kept_artifacts
        if automation_id == "hourly-market-supervisor":
            other_due_times = {
                other_id: schedule_due_times.get(other_id, [])
                for other_id in SHARED_HOURLY_SUPERVISOR_AUTOMATION_IDS
                if other_id != automation_id
            }
            artifacts = _filter_hourly_supervisor_artifacts(
                artifacts,
                automation_due_times=scheduled_due_times,
                other_due_times=other_due_times,
            )
        if automation_id in DUE_ALIGNED_ARTIFACT_AUTOMATION_IDS:
            artifacts = _filter_artifacts_after_due_start(
                artifacts,
                due_times=due_times,
            )
        memory_time = _memory_latest_time(memory_path)
        session_index_time = session_index_times.get(automation_id)
        run_evidence_source = "memory_md" if memory_time is not None else None
        if session_index_time is not None:
            memory_time = session_index_time
            run_evidence_source = "codex_session_index"
        submitted_count = sum(int(item.get("submitted_count") or 0) for item in artifacts)
        issue_count = sum(int(item.get("issue_count") or 0) for item in artifacts)
        for artifact in artifacts:
            artifact_path = str(artifact.get("path") or "")
            if not artifact_path:
                continue
            unique_submitted_by_path[artifact_path] = max(
                unique_submitted_by_path.get(artifact_path, 0),
                int(artifact.get("submitted_count") or 0),
            )
            unique_issues_by_path[artifact_path] = max(
                unique_issues_by_path.get(artifact_path, 0),
                int(artifact.get("issue_count") or 0),
            )
        if automation_id == "tradingagents-self-heal-monitor" and not is_paused:
            handoff_artifacts = [
                {"generated_at": timestamp.isoformat(timespec="seconds")}
                for timestamp, _path, _payload in _artifact_records(
                    repo,
                    SELF_HEAL_HANDOFF_GLOB,
                    window_start=window_start,
                    now=current,
                )
            ]
            duplicate_count = _count_near_duplicate_artifacts(handoff_artifacts)
            overlap_count = _count_overlapping_artifacts(
                handoff_artifacts,
                due_times=due_times,
            )
            handoff_timeline = [
                (timestamp, str(path))
                for timestamp, path, _payload in _artifact_records(
                    repo,
                    SELF_HEAL_HANDOFF_GLOB,
                    window_start=window_start,
                    now=current,
                )
            ]
        elif is_paused:
            duplicate_count = 0
            overlap_count = 0
            handoff_timeline = []
        else:
            role_scoped_duplicates = automation_id == "paper-strategy-tournament-runner"
            duplicate_count = _count_near_duplicate_artifacts(
                artifacts,
                same_role_only=role_scoped_duplicates,
            )
            overlap_count = _count_overlapping_artifacts(
                artifacts,
                due_times=due_times,
                same_role_only=role_scoped_duplicates,
            )
            handoff_timeline = []
        status, issue_types, status_reason = _classify(
            due_count=len(due_times),
            artifact_count=len(artifacts),
            memory_time=_classification_memory_time(
                automation_id,
                memory_time=memory_time,
                due_times=due_times,
                artifact_count=len(artifacts),
            ),
            window_start=window_start,
            submitted_count=submitted_count,
            issue_count=issue_count,
            duplicate_count=duplicate_count,
            overlap_count=overlap_count,
        )
        artifact_timeline = _extract_artifact_timeline(artifacts)
        latest_artifact_time = artifact_timeline[-1][0] if artifact_timeline else None
        history_gap_count = max(len(due_times) - len(artifacts), 0)
        self_heal_timeliness: dict[str, Any] | None = None
        if automation_id == "tradingagents-self-heal-monitor":
            self_heal_timeliness = _self_heal_timeliness(
                repo,
                window_start=window_start,
                now=current,
                sla_minutes=self_heal_plan_sla_minutes,
            )
            timeliness_issue = self_heal_timeliness.get("issue")
            if timeliness_issue:
                issue_types = [*issue_types, str(timeliness_issue)]
                if timeliness_issue == "self_heal_plan_late":
                    status = "late"
            elif status == "ok" and self_heal_timeliness.get("timely") is True:
                issue_types = [issue for issue in issue_types if issue != "overlap_run"]
                if overlap_count:
                    status_reason = "self_heal_timely_overlap_artifacts_de_noised"
            elif status == "partial" and artifacts:
                status = "ok"
                issue_types = [
                    issue
                    for issue in issue_types
                    if issue not in {"missed_run", "overlap_run"}
                ]
                status_reason = "self_heal_timely_followup_artifacts_de_noised"
            elif status == "duplicate" and self_heal_timeliness.get("timely") is True:
                status = "ok"
                issue_types = [
                    issue
                    for issue in issue_types
                    if issue not in {"duplicate_run", "overlap_run"}
                ]
                status_reason = "self_heal_timely_duplicate_artifacts_de_noised"
        elif (
            automation_id == "paper-strategy-tournament-runner"
            and status == "duplicate"
            and submitted_count == 0
            and issue_count == 0
            and memory_time is not None
            and latest_artifact_time is not None
            and memory_time >= latest_artifact_time
        ):
            status = "ok"
            issue_types = [issue for issue in issue_types if issue != "duplicate_run"]
            status_reason = "paper_only_duplicate_artifacts_de_noised"
        elif (
            automation_id == "hourly-market-supervisor"
            and status == "duplicate"
            and submitted_count == 0
            and issue_count == 0
            and memory_time is not None
            and latest_artifact_time is not None
            and memory_time >= latest_artifact_time
        ):
            status = "ok"
            issue_types = [issue for issue in issue_types if issue != "duplicate_run"]
            status_reason = "hourly_no_action_duplicate_artifacts_de_noised"
        elif (
            automation_id == "tradingagents-overnight-planning"
            and status == "duplicate"
            and submitted_count == 0
            and issue_count == 0
            and _overnight_duplicate_artifacts_are_benign(artifacts)
        ):
            status = "ok"
            issue_types = [issue for issue in issue_types if issue != "duplicate_run"]
            status_reason = "overnight_analysis_only_duplicate_artifacts_de_noised"
        elif (
            automation_id == "tradingagents-overnight-planning"
            and status == "duplicate"
            and submitted_count == 0
            and issue_count == 0
            and _overnight_duplicate_artifacts_are_superseded_repair_reruns(artifacts)
        ):
            status = "ok"
            issue_types = [issue for issue in issue_types if issue != "duplicate_run"]
            status_reason = "overnight_superseded_stale_repair_reruns_de_noised"
        elif (
            automation_id == "tradingagents-night-shift-supervisor"
            and status == "partial"
            and submitted_count == 0
            and issue_count == 0
            and latest_artifact_time is not None
            and due_times
            and latest_artifact_time >= max(due_times)
        ):
            status = "ok"
            issue_types = [issue for issue in issue_types if issue != "missed_run"]
            status_reason = "night_shift_latest_due_covered_history_ramp_up"
        elif (
            automation_id == "tradingagents-night-shift-supervisor"
            and status == "duplicate"
            and submitted_count == 0
            and issue_count == 0
            and latest_artifact_time is not None
            and due_times
            and latest_artifact_time >= max(due_times)
        ):
            status = "ok"
            issue_types = [issue for issue in issue_types if issue != "duplicate_run"]
            status_reason = "night_shift_extra_patrol_artifacts_de_noised"
        if not config_path.exists():
            status = "missing"
            issue_types = [*issue_types, "missing_config"]
        elif is_paused and status == "ok":
            status_reason = "automation_paused"
        row = {
            "automation_id": automation_id,
            "status": status,
            "issue_types": sorted(set(issue_types)),
            "config_path": str(config_path),
            "memory_path": str(memory_path),
            "schedule_rrule": rrule or None,
            "config_status": config.get("status"),
            "config_effective_at": (
                config_effective_time.isoformat(timespec="seconds")
                if config_effective_time
                else None
            ),
            "expected_run_count": len(due_times),
            "actual_artifact_count": len(artifacts),
            "observer_artifact_count": observer_artifact_count,
            "duplicate_count": duplicate_count,
            "overlap_count": overlap_count,
            "status_reason": status_reason,
            "history_gap_count": history_gap_count,
            "latest_memory_at": memory_time.isoformat(timespec="seconds") if memory_time else None,
            "run_evidence_source": run_evidence_source,
            "submitted_order_count": submitted_count,
            "issue_count": issue_count,
            "packet_paths": [item["path"] for item in artifacts[-5:]],
        }
        if self_heal_timeliness is not None:
            row["self_heal_timeliness"] = self_heal_timeliness
        config_issue_types = _schedule_config_issues(automation_id, rrule)
        if config_issue_types:
            row["issue_types"] = sorted(set([*row["issue_types"], *config_issue_types]))
            if row["status"] == "ok":
                row["status"] = "warning"
                row["status_reason"] = "config_policy_warning:night_shift_cadence_mismatch"
        row["problem_jobs"] = _build_problem_jobs(
            status=status,
            due_times=due_times,
            artifact_timeline=artifact_timeline,
            self_heal_timeliness=self_heal_timeliness,
            handoff_timeline=handoff_timeline,
        )
        rows.append(row)
    summary = {
        "ok_count": sum(1 for row in rows if row["status"] == "ok"),
        "missing_count": sum(1 for row in rows if row["status"] == "missing"),
        "partial_count": sum(1 for row in rows if row["status"] == "partial"),
        "late_count": sum(1 for row in rows if row["status"] == "late"),
        "duplicate_count": sum(1 for row in rows if row["status"] == "duplicate"),
        "stale_count": sum(1 for row in rows if row["status"] == "stale"),
        "warning_count": sum(1 for row in rows if row["status"] == "warning"),
        "timeliness_issue_count": sum(
            1 for row in rows if "self_heal_plan_late" in row["issue_types"]
        ),
    }
    return {
        "schema_version": 1,
        "kind": "tradingagents_automation_health_audit",
        "generated_at": _now_iso(current),
        "window_start": _now_iso(window_start),
        "window_hours": window_hours,
        "analysis_only": True,
        "can_submit_orders": False,
        "automation_count": len(rows),
        "submitted_order_count": sum(unique_submitted_by_path.values()),
        "issue_count": sum(unique_issues_by_path.values()),
        "summary": summary,
        "automations": rows,
        "recommended_next_step": (
            "Keep live dead-man blocked if critical schedule evidence is missing; "
            "paper/dry-run catch-up is allowed, live catch-up is not automatic."
        ),
    }


def _render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# TradingAgents Automation Health Audit",
        "",
        f"- Generated: {audit['generated_at']}",
        f"- Window: {audit['window_hours']} hours",
        f"- Can submit orders: {str(audit['can_submit_orders']).lower()}",
        f"- Submitted order count: {audit['submitted_order_count']}",
        "",
        "| Automation | Status | Expected | Artifacts | Issues | Problem Job | Expected Time | Actual Status | Evidence Path | Live Impact | User Action |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in audit["automations"]:
        issues = ", ".join(row["issue_types"]) or "none"
        problem_jobs = row.get("problem_jobs") or []
        if not problem_jobs:
            lines.append(
                f"| {row['automation_id']} | {row['status']} | "
                f"{row['expected_run_count']} | {row['actual_artifact_count']} | {issues} | "
                "| - | - | - | - | - |"
            )
            continue
        for index, problem in enumerate(problem_jobs, start=1):
            lines.append(
                f"| {row['automation_id'] if index == 1 else ' '} | {row['status'] if index == 1 else ' '} | "
                f"{row['expected_run_count']} | {row['actual_artifact_count']} | {issues} | "
                f"{problem['job']} | {problem['expected_time']} | {problem['actual_status']} | "
                f"{problem['evidence_path'] or '-'} | {problem['live_impact']} | {problem['user_action']} |"
            )
    lines.extend(["", audit["recommended_next_step"], ""])
    return "\n".join(lines)


def _observed_less_than_expected_gap(reason: object) -> int | None:
    if not isinstance(reason, str):
        return None
    match = re.search(r"observed_runs_less_than_expected:(\d+)<(\d+)", reason)
    if not match:
        return None
    observed = int(match.group(1))
    expected = int(match.group(2))
    return max(expected - observed, 0)


def _is_benign_self_heal_overlap(row: Mapping[str, Any]) -> bool:
    """Treat timely self-heal observer overlap as attention, not a problem."""

    if row.get("automation_id") != "tradingagents-self-heal-monitor":
        return False
    if row.get("status") != "ok":
        return False
    issue_types = set(row.get("issue_types") or [])
    if not issue_types or issue_types.difference({"overlap_run"}):
        return False
    timeliness = row.get("self_heal_timeliness")
    return isinstance(timeliness, Mapping) and timeliness.get("timely") is True


def build_compact_automation_health_audit(audit: Mapping[str, Any]) -> dict[str, Any]:
    packet_summary = audit.get("summary") if isinstance(audit.get("summary"), Mapping) else {}
    automations = audit.get("automations") if isinstance(audit.get("automations"), list) else []
    submitted_count = int(audit.get("submitted_order_count") or 0)
    issue_count = int(audit.get("issue_count") or 0)
    partial_count = int(packet_summary.get("partial_count") or 0)
    benign_partial_ids = [
        str(item.get("automation_id"))
        for item in automations
        if isinstance(item, Mapping)
        and item.get("automation_id") == "tradingagents-night-shift-supervisor"
        and item.get("status") == "partial"
        and str(item.get("status_reason") or "").startswith("observed_runs_less_than_expected:")
        and (_observed_less_than_expected_gap(item.get("status_reason")) or 0) <= 1
        and int(item.get("actual_artifact_count") or 0) > 0
        and not {
            "stale_memory",
            "late_run",
            "duplicate_run",
            "night_shift_cadence_mismatch",
            "self_heal_plan_late",
        }.intersection(set(item.get("issue_types") or []))
    ]
    actionable_partial_count = max(partial_count - len(benign_partial_ids), 0)
    problem_ids: list[str] = []
    attention_ids: list[str] = []
    for row in automations:
        if not isinstance(row, Mapping):
            continue
        automation_id = str(row.get("automation_id") or "")
        if not automation_id:
            continue
        issue_types = row.get("issue_types") if isinstance(row.get("issue_types"), list) else []
        status = str(row.get("status") or "")
        if (
            automation_id not in benign_partial_ids
            and not _is_benign_self_heal_overlap(row)
            and (status not in {"", "ok"} or issue_types)
        ):
            problem_ids.append(automation_id)
        if status in {"partial", "late", "stale", "missing", "warning"} or issue_types:
            attention_ids.append(automation_id)

    self_heal_timeliness = None
    for row in automations:
        if isinstance(row, Mapping) and row.get("automation_id") == "tradingagents-self-heal-monitor":
            value = row.get("self_heal_timeliness")
            self_heal_timeliness = value if isinstance(value, Mapping) else None
            break

    return {
        "schema": "compact_automation_health_audit_v1",
        "analysis_only": audit.get("analysis_only"),
        "can_submit_orders": audit.get("can_submit_orders"),
        "raw_packet_path": audit.get("json_path"),
        "markdown_path": audit.get("markdown_path"),
        "generated_at": audit.get("generated_at"),
        "automation_count": audit.get("automation_count"),
        "submitted_order_count": submitted_count,
        "issue_count": issue_count,
        "ok_count": packet_summary.get("ok_count"),
        "missing_count": packet_summary.get("missing_count"),
        "partial_count": partial_count,
        "actionable_partial_count": actionable_partial_count,
        "benign_partial_automation_ids": benign_partial_ids[:8],
        "late_count": packet_summary.get("late_count"),
        "duplicate_count": packet_summary.get("duplicate_count"),
        "stale_count": packet_summary.get("stale_count"),
        "warning_count": packet_summary.get("warning_count"),
        "timeliness_issue_count": packet_summary.get("timeliness_issue_count"),
        "problem_automation_ids": problem_ids[:12],
        "attention_automation_ids": attention_ids[:12],
        "self_heal_timeliness": dict(self_heal_timeliness) if self_heal_timeliness else None,
        "raw_field_groups": [
            "automations",
            "summary",
            "recommended_next_step",
            "submitted_order_count",
            "issue_count",
        ],
    }


def write_automation_health_audit(
    audit: dict[str, Any],
    output_dir: str | Path = "results/automation_health",
) -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = path / f"automation-health-audit-{stamp}.json"
    md_path = path / f"automation-health-audit-{stamp}.md"
    audit["json_path"] = str(json_path)
    audit["markdown_path"] = str(md_path)
    json_text = json.dumps(audit, indent=2, sort_keys=True)
    md_text = _render_markdown(audit)
    compact = build_compact_automation_health_audit(audit)
    compact_text = json.dumps(compact, indent=2, sort_keys=True)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    json_path.with_suffix(".compact.json").write_text(compact_text, encoding="utf-8")
    (path / "latest.json").write_text(json_text, encoding="utf-8")
    (path / "latest.md").write_text(md_text, encoding="utf-8")
    (path / "latest-compact.json").write_text(compact_text, encoding="utf-8")
    return json_path, md_path
