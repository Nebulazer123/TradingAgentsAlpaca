import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.process_review import build_process_review, write_process_review

runner = CliRunner()


def test_process_review_is_analysis_only_and_writes_artifacts(tmp_path):
    (tmp_path / "docs/superpowers/plans").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("start here", encoding="utf-8")
    (tmp_path / "CONTEXT_ROUTER.md").write_text("router", encoding="utf-8")
    (tmp_path / "TOKEN_EFFICIENCY_AUDIT.md").write_text("audit", encoding="utf-8")
    (tmp_path / "docs/superpowers/plans/2026-06-02-tradingagents-autonomous-revision.md").write_text(
        "- [ ] **Step example**\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/superpowers/plans/2026-06-03-plugin-methodology-integration.md").write_text(
        "- [ ] **Second plan step**\n",
        encoding="utf-8",
    )
    review = build_process_review(tmp_path)
    json_path, md_path = write_process_review(review, tmp_path / "out")

    assert review["analysis_only"] is True
    assert review["can_submit_orders"] is False
    assert review["plan_doc_count"] == 2
    assert review["unchecked_step_count"] == 2
    assert any("2026-06-02-tradingagents-autonomous-revision.md: Step example" in item for item in review["unchecked_steps"])
    assert any("2026-06-03-plugin-methodology-integration.md: Second plan step" in item for item in review["unchecked_steps"])
    assert json_path.exists()
    assert md_path.exists()
    assert (tmp_path / "out" / "latest.json").exists()


def test_process_review_ignores_superseded_plan_checklists(tmp_path):
    (tmp_path / "docs/superpowers/plans").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("start here", encoding="utf-8")
    (tmp_path / "CONTEXT_ROUTER.md").write_text("router", encoding="utf-8")
    (tmp_path / "TOKEN_EFFICIENCY_AUDIT.md").write_text("audit", encoding="utf-8")
    (tmp_path / "docs/superpowers/plans/2026-06-08-old-plan.md").write_text(
        "# Old Plan\n\n"
        "> Superseded execution entrypoint: use "
        "`docs/superpowers/plans/2026-06-08-master-plan.md` first.\n\n"
        "- [ ] **Historical step that should not count**\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/superpowers/plans/2026-06-08-master-plan.md").write_text(
        "# Master Plan\n\n"
        "- [ ] **Current step that should count**\n",
        encoding="utf-8",
    )

    review = build_process_review(tmp_path)

    assert review["plan_doc_count"] == 2
    assert review["unchecked_step_count"] == 1
    assert review["unchecked_steps"] == [
        "docs/superpowers/plans/2026-06-08-master-plan.md: Current step that should count"
    ]


def test_process_review_cli_writes_json(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "process-review",
            "--output-dir",
            str(tmp_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["json_path"]
    assert payload["markdown_path"]
