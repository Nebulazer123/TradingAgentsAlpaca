import inspect

from cli import main as cli_main


def test_submit_capable_cli_paths_keep_packet_writers():
    manual_submit = inspect.getsource(cli_main.alpaca_submit)
    pullback_paper = inspect.getsource(cli_main.alpaca_pullback_support_paper)
    tournament_run = inspect.getsource(cli_main.alpaca_paper_tournament_run)
    hourly_supervisor = inspect.getsource(cli_main.alpaca_supervise_hourly)
    overnight_plan = inspect.getsource(cli_main.alpaca_plan_overnight)
    premarket_brief = inspect.getsource(cli_main.alpaca_premarket_brief)

    assert "_write_manual_alpaca_submit_packet" in manual_submit
    assert "write_shadow_run_packet" in pullback_paper
    assert "write_tournament_packet" in tournament_run
    assert "write_hourly_decision_packet" in hourly_supervisor
    assert "write_overnight_plan_packet" in overnight_plan
    assert "write_premarket_brief_packet" in premarket_brief


def test_manual_submit_records_blocked_paths_before_exit():
    source = inspect.getsource(cli_main.alpaca_submit)

    assert source.count("_write_manual_alpaca_submit_packet") >= 6
    assert source.index("validate_supervisor_live_submit_allowed") < source.index("execute_order_pairs(")
    assert "status=\"blocked\"" in source
    assert "status=\"refused\"" in source
    assert "status=status" in source
