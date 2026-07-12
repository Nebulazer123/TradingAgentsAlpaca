import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.policy.preregistration import (
    append_preregistration,
    build_sleeve_preregistration,
    load_preregistrations,
)

runner = CliRunner()


def test_preregistration_id_changes_when_rules_change(tmp_path):
    first = build_sleeve_preregistration(
        sleeve="pullback-support",
        hypothesis="good dips outperform bad dips",
        rules_summary="support proximity plus ATR depth",
        created_at="2026-06-02T00:00:00+00:00",
    )
    same = build_sleeve_preregistration(
        sleeve="pullback-support",
        hypothesis="good dips outperform bad dips",
        rules_summary="support proximity plus ATR depth",
        created_at="2026-06-03T00:00:00+00:00",
    )
    changed = build_sleeve_preregistration(
        sleeve="pullback-support",
        hypothesis="good dips outperform bad dips",
        rules_summary="support proximity plus ATR depth plus volume confirmation",
        created_at="2026-06-02T00:00:00+00:00",
    )
    path = append_preregistration(first, tmp_path / "prereg.jsonl")
    append_preregistration(changed, path)
    loaded = load_preregistrations(path)

    assert first.registration_id == same.registration_id
    assert first.registration_id != changed.registration_id
    assert len(loaded) == 2
    assert first.analysis_only is True
    assert first.live_authority == "none"
    assert list(tmp_path.glob(".prereg.jsonl.*.tmp")) == []
    assert list(tmp_path.glob(".latest-preregistration.json.*.tmp")) == []


def test_policy_preregister_sleeve_cli_writes_record(tmp_path):
    result = runner.invoke(
        app,
        [
            "policy",
            "preregister-sleeve",
            "--sleeve",
            "pullback-support",
            "--hypothesis",
            "good dips can recover",
            "--rules-summary",
            "trend support, ATR depth, volume behavior",
            "--output-path",
            str(tmp_path / "prereg.jsonl"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["registration_id"].startswith("prereg-")
    assert (tmp_path / "latest-preregistration.json").exists()
