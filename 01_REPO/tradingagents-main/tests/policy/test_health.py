"""C4: plain-language health/heartbeat report. Pure core is fully deterministic."""

from __future__ import annotations

import datetime

from tradingagents.policy import health

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _base_inputs(**overrides):
    inputs = {
        "now": NOW,
        "control_present": True,
        "dead_man_expires_at": NOW + datetime.timedelta(hours=30),
        "frozen": False,
        "frozen_reason": "",
        "promotion_present": True,
        "live_enabled_sleeves": ["pullback-support"],
        "integrity_mode": "warn",
        "integrity_issues": [],
        "audit_issues": [],
        "last_tick_at": NOW - datetime.timedelta(hours=1),
        "outbox_backlog": 0,
        "disk_free_bytes": 50 * 1024**3,
        "env_present": True,
        "env_mode_octal": "600",
        "env_git_tracked": False,
        "broker_reachable": None,
    }
    inputs.update(overrides)
    return inputs


def test_healthy_system_is_ok() -> None:
    report = health.collect_health(_base_inputs())
    assert report.overall == health.OK
    assert report.to_dict()["overall"] == "ok"
    assert "trading system" in report.render_plain().lower()


def test_expired_dead_man_is_critical() -> None:
    report = health.collect_health(
        _base_inputs(dead_man_expires_at=NOW - datetime.timedelta(hours=1))
    )
    assert report.overall == health.CRITICAL
    dm = next(c for c in report.checks if c.name == "dead_man_timer")
    assert dm.status == health.CRITICAL


def test_missing_dead_man_is_critical() -> None:
    report = health.collect_health(_base_inputs(dead_man_expires_at=None))
    assert report.overall == health.CRITICAL


def test_dead_man_expiring_soon_warns() -> None:
    report = health.collect_health(
        _base_inputs(dead_man_expires_at=NOW + datetime.timedelta(hours=3))
    )
    assert report.overall == health.WARN


def test_frozen_is_reported_but_not_critical() -> None:
    report = health.collect_health(_base_inputs(frozen=True, frozen_reason="pause and review"))
    frozen = next(c for c in report.checks if c.name == "live_freeze")
    assert frozen.status == health.WARN
    assert "pause and review" in frozen.detail


def test_enforce_integrity_issue_is_critical() -> None:
    report = health.collect_health(
        _base_inputs(integrity_mode="enforce", integrity_issues=["integrity mismatch for live_control.json"])
    )
    assert report.overall == health.CRITICAL


def test_warn_integrity_issue_is_warn_not_critical() -> None:
    report = health.collect_health(
        _base_inputs(integrity_mode="warn", integrity_issues=["integrity mismatch for live_control.json"])
    )
    integ = next(c for c in report.checks if c.name == "state_integrity")
    assert integ.status == health.WARN
    assert report.overall != health.CRITICAL


def test_low_disk_is_critical() -> None:
    report = health.collect_health(_base_inputs(disk_free_bytes=100 * 1024**2))
    assert report.overall == health.CRITICAL


def test_stale_tick_warns() -> None:
    report = health.collect_health(
        _base_inputs(last_tick_at=NOW - datetime.timedelta(hours=40))
    )
    assert report.overall == health.WARN


def test_outbox_backlog_warns() -> None:
    report = health.collect_health(_base_inputs(outbox_backlog=25))
    assert report.overall == health.WARN


def test_env_group_readable_warns() -> None:
    report = health.collect_health(_base_inputs(env_mode_octal="644"))
    env = next(c for c in report.checks if c.name == "env_permissions")
    assert env.status == health.WARN


def test_env_git_tracked_is_critical() -> None:
    report = health.collect_health(_base_inputs(env_git_tracked=True))
    env = next(c for c in report.checks if c.name == "env_permissions")
    assert env.status == health.CRITICAL


def test_broker_unreachable_warns_when_checked() -> None:
    report = health.collect_health(_base_inputs(broker_reachable=False))
    assert report.overall == health.WARN
    # When not checked (None) there is no broker check at all.
    report_unchecked = health.collect_health(_base_inputs(broker_reachable=None))
    assert not any(c.name == "broker_reachability" for c in report_unchecked.checks)


def test_gather_reads_real_files(tmp_path, monkeypatch) -> None:
    import datetime as _dt

    from tradingagents.policy.integrity import write_state_with_integrity
    from tradingagents.policy.live_control import write_live_control_state

    control = tmp_path / "policy" / "live_control.json"
    promo = tmp_path / "policy" / "promotion_state.json"
    ticks = tmp_path / "hourly_supervisor"
    ticks.mkdir(parents=True)
    (ticks / "tick.json").write_text("{}")

    write_live_control_state(
        control, frozen=False, reason="armed",
        dead_man_expires_at=_dt.datetime.now(tz=UTC) + _dt.timedelta(hours=30),
    )
    write_state_with_integrity(
        promo, '{"sleeves": {"pullback-support": {"live_enabled": true}}}', actor="test"
    )

    inputs = health.gather_health_inputs(
        control_path=control, promotion_path=promo, tick_dir=ticks,
        outbox_dir=tmp_path / "outbox", env_path=tmp_path / "nope.env",
    )
    assert inputs["control_present"] is True
    assert inputs["dead_man_expires_at"] is not None
    assert inputs["live_enabled_sleeves"] == ["pullback-support"]
    assert inputs["last_tick_at"] is not None
    assert inputs["integrity_issues"] == []  # clean sidecars just written
    assert health.collect_health(inputs).overall == health.OK
