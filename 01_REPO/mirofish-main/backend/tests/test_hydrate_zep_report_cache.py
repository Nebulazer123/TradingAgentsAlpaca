from scripts.hydrate_zep_report_cache import main


def test_hydration_dry_run_writes_summary(tmp_path, capsys):
    code = main([
        "--simulation-id",
        "sim_974459649906",
        "--graph-id",
        "mirofish_4a9df9ae8b184878",
        "--cache-root",
        str(tmp_path),
        "--interval-seconds",
        "0",
        "--limit",
        "3",
        "--max-queries",
        "0",
    ])

    captured = capsys.readouterr()
    assert code == 0
    assert "Dry hydration check only" in captured.out
    assert (tmp_path / "hydration_summary.json").exists()
    assert (tmp_path / "hydration_summary.md").exists()

