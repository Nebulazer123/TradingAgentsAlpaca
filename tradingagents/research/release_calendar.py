"""Official release-calendar context for research packets."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows._official_common import evidence_packet, request_hash

DEFAULT_RELEASE_CALENDAR_PATH = Path("config/release_calendar_watchlist.json")
UTC = datetime.timezone.utc
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
FORBIDDEN_CALENDAR_EFFECTS = (
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
)


def _as_utc(value: datetime.datetime | None) -> datetime.datetime:
    current = value or datetime.datetime.now(tz=UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _parse_event_time(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime.datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def load_release_calendar_config(path: str | Path = DEFAULT_RELEASE_CALENDAR_PATH) -> dict[str, Any]:
    config: object = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Release calendar config must contain a JSON object")
    return config


def _window_for_event(
    event: dict[str, Any],
    *,
    now: datetime.datetime,
    default_pre_hours: float,
    default_post_hours: float,
) -> dict[str, Any]:
    starts_at = _parse_event_time(str(event["starts_at"]))
    pre_hours = float(event.get("pre_window_hours", default_pre_hours))
    post_hours = float(event.get("post_window_hours", default_post_hours))
    window_starts_at = starts_at - datetime.timedelta(hours=pre_hours)
    window_ends_at = starts_at + datetime.timedelta(hours=post_hours)
    hours_until_release = (starts_at - now).total_seconds() / 3600
    return {
        "starts_at": _iso(window_starts_at),
        "ends_at": _iso(window_ends_at),
        "active": window_starts_at <= now <= window_ends_at,
        "pre_window_hours": pre_hours,
        "post_window_hours": post_hours,
        "hours_until_release": round(hours_until_release, 2),
    }


def _normalize_event(
    item: dict[str, Any],
    *,
    now: datetime.datetime,
    default_pre_hours: float,
    default_post_hours: float,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_id": str(item["event_id"]),
        "source_name": str(item["source_name"]),
        "title": str(item["title"]),
        "event_type": str(item.get("event_type", "macro")),
        "starts_at": _iso(_parse_event_time(str(item["starts_at"]))),
        "impact": str(item.get("impact", "medium")),
        "source_url": str(item.get("source_url", "")),
        "affected_themes": [str(theme) for theme in item.get("affected_themes", [])],
        "why_it_matters": str(item.get("why_it_matters", "")),
    }
    event["risk_window"] = _window_for_event(
        event,
        now=now,
        default_pre_hours=default_pre_hours,
        default_post_hours=default_post_hours,
    )
    return event


def _recurring_event_instances(
    item: dict[str, Any],
    *,
    now: datetime.datetime,
    horizon_end: datetime.datetime,
    default_pre_hours: float,
    default_post_hours: float,
) -> list[dict[str, Any]]:
    weekday = WEEKDAYS[str(item["day_of_week"]).strip().lower()]
    hour, minute = [int(part) for part in str(item["time"]).split(":", 1)]
    timezone = ZoneInfo(str(item.get("timezone", "America/New_York")))
    local_now = now.astimezone(timezone)
    first_date = local_now.date()
    days_until = (weekday - first_date.weekday()) % 7
    event_date = first_date + datetime.timedelta(days=days_until)
    events: list[dict[str, Any]] = []
    while True:
        local_start = datetime.datetime.combine(
            event_date,
            datetime.time(hour, minute),
            tzinfo=timezone,
        )
        starts_at = local_start.astimezone(UTC)
        if starts_at < now - datetime.timedelta(hours=default_post_hours):
            event_date += datetime.timedelta(days=7)
            continue
        if starts_at > horizon_end:
            break
        event_payload = {
            **item,
            "event_id": f"{item['event_id']}-{event_date.isoformat()}",
            "starts_at": starts_at.isoformat(timespec="seconds"),
        }
        events.append(
            _normalize_event(
                event_payload,
                now=now,
                default_pre_hours=default_pre_hours,
                default_post_hours=default_post_hours,
            )
        )
        event_date += datetime.timedelta(days=7)
    return events


def build_release_calendar_packet(
    *,
    path: str | Path = DEFAULT_RELEASE_CALENDAR_PATH,
    now: datetime.datetime | None = None,
    lookahead_days: int | None = None,
) -> Any:
    config_path = Path(path)
    config = load_release_calendar_config(config_path)
    policy = config.get("policy", {})
    reference_time = _as_utc(now)
    horizon_days = int(lookahead_days or policy.get("default_lookahead_days", 14))
    horizon_end = reference_time + datetime.timedelta(days=horizon_days)
    default_pre_hours = float(policy.get("default_pre_window_hours", 36))
    default_post_hours = float(policy.get("default_post_window_hours", 6))

    events = [
        _normalize_event(
            item,
            now=reference_time,
            default_pre_hours=default_pre_hours,
            default_post_hours=default_post_hours,
        )
        for item in config.get("static_events", [])
    ]
    for item in config.get("recurring_events", []):
        events.extend(
            _recurring_event_instances(
                item,
                now=reference_time,
                horizon_end=horizon_end,
                default_pre_hours=default_pre_hours,
                default_post_hours=default_post_hours,
            )
        )

    upcoming = [
        event
        for event in events
        if reference_time <= _parse_event_time(event["starts_at"]) <= horizon_end
    ]
    active = [event for event in events if event["risk_window"]["active"]]
    upcoming.sort(key=lambda event: event["starts_at"])
    active.sort(key=lambda event: event["starts_at"])
    high_impact = [event for event in upcoming if event["impact"] == "high"]
    if active:
        risk_state = "active_release_window"
    elif high_impact:
        risk_state = "upcoming_high_impact"
    elif upcoming:
        risk_state = "upcoming_low_or_medium"
    else:
        risk_state = "clear"

    source_urls = [
        str(calendar.get("source_url", ""))
        for calendar in config.get("calendars", [])
        if calendar.get("source_url")
    ]
    payload = {
        "policy": {
            **policy,
            "forbidden_effects": list(FORBIDDEN_CALENDAR_EFFECTS),
            "execution_authority": "none",
        },
        "lookahead_days": horizon_days,
        "calendars": config.get("calendars", []),
        "upcoming_events": upcoming,
        "active_event_windows": active,
        "event_risk_state": risk_state,
        "high_impact_count": len(high_impact),
        "planner_flags": {
            "macro_event_risk": bool(active or high_impact),
            "requires_fresh_post_release_validation": bool(active),
            "source_role": "official release calendar context only",
        },
        "source_urls": source_urls,
    }
    source_ref = f"local://{config_path.as_posix()}"
    return evidence_packet(
        source_name="official_release_calendar",
        evidence_type="macro_release_calendar",
        subject="official_macro_event_risk",
        source_ref=source_ref,
        payload=payload,
        quality="high",
        request_fingerprint=request_hash("READ", source_ref, None, payload),
        tool_route="local_release_calendar_policy",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "lookahead_days": horizon_days,
            "calendar_count": len(config.get("calendars", [])),
            "upcoming_event_count": len(upcoming),
            "active_event_window_count": len(active),
        },
    )
