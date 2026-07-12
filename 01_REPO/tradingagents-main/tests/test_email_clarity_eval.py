import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.email_clarity import evaluate_email_clarity, write_email_clarity_eval

runner = CliRunner()


def _good_daily_body() -> str:
    return "\n".join(
        [
            "To: operator@example.com",
            "Subject: TradingAgents Daily Market Supervisor Report",
            "",
            "Plain English",
            "- Orders were sent today. The dollars and accounts are listed below.",
            "",
            "What happened",
            "- Latest decision: buy - controlled dip; support checks stayed clean.",
            "- Supervisor checks today: 4",
            "- Material checks today: 2",
            "- Submitted orders today: 1",
            "",
            "Problem: none",
            "",
            "Money today",
            "- Live spent today: $25.00",
            "- Paper spent today: $0.00",
            "",
            "Live account",
            "- Live equity: $200.00",
            "- Live unrealized P/L: $2.00 (1.00%)",
            "- Holdings: MA qty 0.052 value $25.00 P/L $0.40 (1.60%)",
            "",
            "Paper account",
            "- Paper unrealized P/L: $0.00",
            "- Holdings: none",
            "",
            "Open orders",
            "- Live: none",
            "- Paper: none",
            "",
            "Submitted orders",
            "- live buy MA $25.00 limit status=filled",
            "",
            "Need from you",
            "- No approval needed. Routine trades and promotions stay autonomous inside the configured envelope.",
        ]
    )


def test_email_clarity_eval_passes_clear_daily_report():
    result = evaluate_email_clarity(
        _good_daily_body(),
        subject="TradingAgents Daily Market Supervisor Report",
        report_type="daily",
    )

    assert result["status"] == "pass"
    assert result["score"] == 100
    assert result["can_submit_orders"] is False
    assert result["problem_line"] == "Problem: none"
    assert result["need_from_you_line"].startswith("- No approval needed")


def test_email_clarity_eval_flags_programmer_words_and_trade_approval():
    body = "\n".join(
        [
            "Plain English",
            "- Go fix this file and debug this.",
            "Problem: projected $125 cap $100",
            "Need from you",
            "- Please approve this trade.",
        ]
    )

    result = evaluate_email_clarity(body, report_type="daily")

    assert result["status"] == "fail"
    joined = " | ".join(result["issues"])
    assert "missing required section" in joined
    assert "contains confusing/programmer wording" in joined
    assert "trade-level approval" in joined


def test_email_clarity_eval_requires_self_heal_language_for_current_blocker():
    body = "\n".join(
        [
            "Plain English",
            "- The bot stopped before live money moved.",
            "",
            "What happened",
            "- Risk checks failed.",
            "",
            "Problem: risk envelope missing",
            "",
            "Need from you",
            "- No action needed from you.",
        ]
    )

    result = evaluate_email_clarity(body, report_type="urgent")

    assert result["status"] == "fail"
    assert any("self-heal" in issue for issue in result["issues"])


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
            "TradingAgents Daily Market Supervisor Report",
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
