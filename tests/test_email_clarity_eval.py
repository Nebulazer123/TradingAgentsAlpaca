import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.email_clarity import evaluate_email_clarity, write_email_clarity_eval

runner = CliRunner()


def _good_daily_body() -> str:
    return "\n".join(
        [
            "Plain English",
            "- One order was placed today. The dollars and accounts are listed below.",
            "",
            "Where you stand",
            "- Real-money account: $200.00 total; overall position P/L $2.00 (1.00%); Holdings: 1",
            "- Largest holding: MA $0.40",
            "- Spent today: $25.00 real money, $0.00 practice",
            "- Practice account P/L: $0.00 (practice trades test ideas with no real money)",
            "",
            "What happened",
            "- A controlled dip was bought; support checks stayed clean.",
            "- Checks today: 4 routine, 2 needed attention, 1 order(s) sent",
            "- Problem: none",
            "- Order: live MA buy $25.00 limit 410.00 status=filled",
            "- Waiting orders: none",
            "",
            "Why it matters",
            "- Money moved today. The amounts above are what was spent, and every order stayed inside the safety limits.",
            "",
            "What to do next",
            "- Nothing needed from you today. Skim the order list above and reply if anything looks unfamiliar.",
        ]
    )


def test_email_clarity_eval_passes_clear_daily_report():
    result = evaluate_email_clarity(
        _good_daily_body(),
        subject="Your trading update for Monday, July 13: quiet day, no trades [TradingAgents]",
        report_type="daily",
    )

    assert result["status"] == "pass", result["issues"]
    assert result["score"] == 100
    assert result["can_submit_orders"] is False
    assert result["problem_line"] == "- Problem: none"
    assert result["need_from_you_line"].startswith("- Nothing needed from you")
    assert result["why_it_matters_line"].startswith("- Money moved today.")


def test_email_clarity_eval_flags_programmer_words_and_trade_approval():
    body = "\n".join(
        [
            "Plain English",
            "- Go fix this file and debug this.",
            "Problem: projected $125 cap $100",
            "What to do next",
            "- Please approve this trade.",
        ]
    )

    result = evaluate_email_clarity(body, report_type="daily")

    assert result["status"] == "fail"
    joined = " | ".join(result["issues"])
    assert "missing required section" in joined
    assert "contains confusing/programmer wording" in joined
    assert "trade-level approval" in joined


def test_email_clarity_eval_flags_engineering_vocabulary():
    body = _good_daily_body().replace(
        "- A controlled dip was bought; support checks stayed clean.",
        "- The pullback-support sleeve packet passed the live gate after a dry-run.",
    )

    result = evaluate_email_clarity(body, report_type="daily")

    assert result["status"] == "fail"
    joined = " | ".join(result["issues"])
    assert "contains confusing/programmer wording" in joined


def test_email_clarity_eval_requires_safe_pause_language_for_current_blocker():
    body = "\n".join(
        [
            "Plain English",
            "- The bot stopped before real money moved.",
            "",
            "Where you stand",
            "- Real-money account: $200.00 total; Holdings: 1",
            "- Spent today: $0.00 real money, $0.00 practice",
            "",
            "What happened",
            "- Risk checks failed.",
            "- Problem: a safety file is missing",
            "",
            "Why it matters",
            "- Money cannot move.",
            "",
            "What to do next",
            "- No action needed from you.",
        ]
    )

    result = evaluate_email_clarity(body, report_type="urgent")

    assert result["status"] == "fail"
    assert any("safe pause" in issue for issue in result["issues"])


def test_email_clarity_writer_and_cli_write_compact_artifacts(tmp_path):
    body_file = tmp_path / "body.txt"
    body_file.write_text(_good_daily_body(), encoding="utf-8")

    evaluation = evaluate_email_clarity(body_file.read_text(encoding="utf-8"))
    json_path, md_path = write_email_clarity_eval(evaluation, tmp_path / "evals")

    assert json_path.exists()
    assert md_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "pass"
    assert (tmp_path / "evals" / "latest.json").exists()

    result = runner.invoke(
        app,
        [
            "research",
            "email-clarity-eval",
            "--body-file",
            str(body_file),
            "--subject",
            "Your trading update for Monday, July 13: 1 trade(s) made [TradingAgents]",
            "--output-dir",
            str(tmp_path / "cli-evals"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "pass"
    assert payload["json_path"].endswith(".json")
    assert payload["can_submit_orders"] is False
