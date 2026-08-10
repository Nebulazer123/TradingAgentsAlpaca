from app.api.report import (
    _active_report_task_for_simulation,
    _normalize_report_chat_options,
    _normalize_report_generate_options,
)
from app.models.task import TaskManager, TaskStatus


def test_generate_options_apply_mirror_fish_safe_defaults():
    options = _normalize_report_generate_options(
        "sim_974459649906",
        {"force_regenerate": True},
    )

    assert options["report_mode"] == "zep_throttle_cached"
    assert options["outline_mode"] == "mirror_fish_full"
    assert options["language"] == "english"
    assert options["zep_safe_mode"] is True
    assert options["zep_interval_seconds"] == 20.0
    assert options["max_live_zep_calls"] == 50
    assert options["max_live_zep_calls_per_section"] == 3


def test_generate_options_accept_legacy_aliases():
    options = _normalize_report_generate_options(
        "sim_974459649906",
        {
            "force_regenerate": True,
            "outline": "mirror_fish_required_sections",
            "language": "en",
            "zep_safe_mode": "true",
        },
    )

    assert options["outline_mode"] == "mirror_fish_full"
    assert options["language"] == "english"
    assert options["zep_safe_mode"] is True


def test_chat_options_apply_mirror_fish_safe_defaults():
    options = _normalize_report_chat_options("sim_974459649906", {})

    assert options["report_mode"] == "zep_throttle_cached"
    assert options["outline_mode"] == "mirror_fish_full"
    assert options["language"] == "english"
    assert options["zep_safe_mode"] is True
    assert options["zep_interval_seconds"] == 20.0
    assert options["max_live_zep_calls"] == 12
    assert options["max_live_zep_calls_per_section"] == 2


def test_chat_options_accept_legacy_aliases():
    options = _normalize_report_chat_options(
        "sim_974459649906",
        {
            "outline": "mirror_fish_required_sections",
            "language": "en",
            "zep_safe_mode": "true",
        },
    )

    assert options["outline_mode"] == "mirror_fish_full"
    assert options["language"] == "english"
    assert options["zep_safe_mode"] is True


def test_active_report_task_for_simulation_detects_running_task():
    manager = TaskManager()
    task_id = manager.create_task(
        "report_generate",
        metadata={"simulation_id": "sim_974459649906", "report_id": "report_running"},
    )
    manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=12)

    task = _active_report_task_for_simulation(manager, "sim_974459649906")

    assert task["task_id"] == task_id
    assert task["metadata"]["report_id"] == "report_running"
    manager.fail_task(task_id, "test cleanup")


def test_report_status_prefers_completed_report_from_stale_task_metadata(monkeypatch):
    from app.api.report import _report_status_from_completed_report_reference
    from app.services.report_agent import Report, ReportStatus

    report = Report(
        report_id="report_done",
        simulation_id="sim_done",
        graph_id="graph_done",
        simulation_requirement="requirement",
        status=ReportStatus.COMPLETED,
        markdown_content="complete",
    )

    monkeypatch.setattr(
        "app.api.report.ReportManager.get_report",
        lambda report_id: report if report_id == "report_done" else None,
    )
    monkeypatch.setattr(
        "app.api.report.ReportManager.get_report_by_simulation",
        lambda simulation_id: report if simulation_id == "sim_done" else None,
    )

    task_payload = {
        "task_id": "task_stale",
        "status": "processing",
        "progress": 0,
        "metadata": {"simulation_id": "sim_done", "report_id": "report_done"},
    }

    resolved = _report_status_from_completed_report_reference(task_payload)

    assert resolved["status"] == "completed"
    assert resolved["progress"] == 100
    assert resolved["report_id"] == "report_done"
    assert resolved["task_id"] == "task_stale"
    assert resolved["already_completed"] is True
