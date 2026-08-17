from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_scheduled_tournament_wrapper_is_explicitly_dry_run():
    wrapper = (ROOT / "scripts" / "mac" / "ta_job.sh").read_text(encoding="utf-8")

    tournament_block = wrapper.split("  tournament)\n", maxsplit=1)[1].split("    ;;", maxsplit=1)[0]

    assert 'run "$PY" -m cli.main alpaca paper-tournament run --all --dry-run --json-output' in tournament_block
