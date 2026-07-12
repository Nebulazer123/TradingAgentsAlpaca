import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.automation_memory_rollup import (
    apply_automation_memory_rollup_plan,
    build_automation_memory_rollup_plan,
    write_automation_memory_rollup_plan,
)

runner = CliRunner()


def _write_memory(root, automation_id, text):
    path = root / automation_id
    path.mkdir(parents=True)
    (path / "memory.md").write_text(text, encoding="utf-8")


def test_automation_memory_rollup_is_analysis_only_and_flags_large_memories(tmp_path):
    automation_root = tmp_path / "automations"
    _write_memory(automation_root, "hourly", ("large memory line\n" * 200))
    _write_memory(automation_root, "small", "short\n")

    packet = build_automation_memory_rollup_plan(
        automation_root=automation_root,
        archive_root=tmp_path / "archives",
        max_tail_lines=5,
        candidate_kb=1,
    )

    assert packet["analysis_only"] is True
    assert packet["can_submit_orders"] is False
    assert packet["execution_authority"] == "none"
    assert packet["mutation_mode"] == "dry_run_only"
    assert packet["apply_required_for_mutation"] is True
    assert packet["summary"]["memory_count"] == 2
    assert packet["summary"]["rollup_candidate_count"] == 1
    candidate = packet["memories"][0]
    assert candidate["automation_id"] == "hourly"
    assert candidate["suggested_action"] == "rollup_candidate"
    assert candidate["tail_line_count"] == 5
    assert "mutate_automation_memory_without_operator_approval" in packet["forbidden_effects"]


def test_automation_memory_rollup_writes_latest_artifacts(tmp_path):
    automation_root = tmp_path / "automations"
    _write_memory(automation_root, "hourly", ("large memory line\n" * 200))
    packet = build_automation_memory_rollup_plan(
        automation_root=automation_root,
        archive_root=tmp_path / "out" / "archives",
        candidate_kb=1,
    )

    json_path, md_path = write_automation_memory_rollup_plan(packet, tmp_path / "out")

    assert json_path.exists()
    assert md_path.exists()
    assert (tmp_path / "out" / "latest-automation-memory-rollup.json").exists()
    assert (tmp_path / "out" / "latest-automation-memory-rollup.md").exists()


def test_automation_memory_rollup_cli_json(tmp_path):
    automation_root = tmp_path / "automations"
    _write_memory(automation_root, "hourly", ("large memory line\n" * 200))

    result = runner.invoke(
        app,
        [
            "research",
            "automation-memory-rollup",
            "--automation-root",
            str(automation_root),
            "--output-dir",
            str(tmp_path / "out"),
            "--candidate-kb",
            "1",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["summary"]["rollup_candidate_count"] == 1
    assert payload["json_path"]
    assert payload["markdown_path"]


def test_apply_requires_explicit_confirmation(tmp_path):
    automation_root = tmp_path / "automations"
    _write_memory(automation_root, "hourly", ("large memory line\n" * 200))
    packet = build_automation_memory_rollup_plan(
        automation_root=automation_root,
        archive_root=tmp_path / "archives",
        candidate_kb=1,
    )

    try:
        apply_automation_memory_rollup_plan(packet)
    except ValueError as exc:
        assert "confirm_apply" in str(exc)
    else:
        raise AssertionError("apply should require explicit confirmation")


def test_apply_archives_full_memory_and_replaces_live_file_with_digest_tail(tmp_path):
    automation_root = tmp_path / "automations"
    original = "".join(f"line {i}\n" for i in range(200))
    _write_memory(automation_root, "hourly", original)
    memory_path = automation_root / "hourly" / "memory.md"
    packet = build_automation_memory_rollup_plan(
        automation_root=automation_root,
        archive_root=tmp_path / "archives",
        max_tail_lines=3,
        candidate_kb=1,
    )

    result = apply_automation_memory_rollup_plan(packet, confirm_apply=True)

    assert result["can_submit_orders"] is False
    assert result["execution_authority"] == "none"
    assert result["compacted_count"] == 1
    item = result["results"][0]
    archive_path = item["archive_path"]
    assert item["status"] == "compacted"
    assert item["after_approx_tokens"] < item["before_approx_tokens"]
    assert (tmp_path / "archives" / "hourly" / "memory-archive-20260607.md").exists() or archive_path
    assert Path(archive_path).read_text(encoding="utf-8") == original
    compacted = memory_path.read_text(encoding="utf-8")
    assert "# Automation Memory Rollup Digest" in compacted
    assert "line 197" in compacted
    assert "line 199" in compacted
    assert "line 1\n" not in compacted


def test_cli_apply_is_gated_by_confirm_apply(tmp_path):
    automation_root = tmp_path / "automations"
    _write_memory(automation_root, "hourly", ("large memory line\n" * 200))

    result = runner.invoke(
        app,
        [
            "research",
            "automation-memory-rollup",
            "--automation-root",
            str(automation_root),
            "--output-dir",
            str(tmp_path / "out"),
            "--candidate-kb",
            "1",
            "--apply",
            "--json-output",
        ],
    )

    assert result.exit_code != 0


def test_cli_apply_with_confirm_writes_apply_result(tmp_path):
    automation_root = tmp_path / "automations"
    _write_memory(automation_root, "hourly", ("large memory line\n" * 200))

    result = runner.invoke(
        app,
        [
            "research",
            "automation-memory-rollup",
            "--automation-root",
            str(automation_root),
            "--output-dir",
            str(tmp_path / "out"),
            "--candidate-kb",
            "1",
            "--apply",
            "--confirm-apply",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["apply_result"]["compacted_count"] == 1
    assert payload["apply_json_path"]
    assert (tmp_path / "out" / "latest-automation-memory-rollup-apply.json").exists()
