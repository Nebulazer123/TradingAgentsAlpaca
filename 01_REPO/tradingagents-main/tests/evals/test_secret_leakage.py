"""B1/B3: secret-leak scanner + key hygiene. Never emits raw secrets, only fingerprints."""

from __future__ import annotations

from pathlib import Path

from tradingagents.evals import secret_leakage as sl


def test_literal_loaded_key_is_detected(tmp_path: Path) -> None:
    (tmp_path / "leak.json").write_text('{"note": "ALPACA_LIVE_API_KEY=PKLIVEKEY1234567890"}')
    env = {"ALPACA_LIVE_API_KEY": "PKLIVEKEY1234567890"}
    leaks = sl.find_secret_leaks([tmp_path], env=env)
    assert leaks, "the actual live key value in a results file must be flagged"
    leak = leaks[0]
    assert "PKLIVEKEY1234567890" not in leak.detail  # never echo the raw secret
    assert leak.fingerprint == sl.fingerprint("PKLIVEKEY1234567890")


def test_clean_dir_has_no_leaks(tmp_path: Path) -> None:
    (tmp_path / "ok.json").write_text('{"decision": "hold", "symbol": "MSFT"}')
    env = {"ALPACA_LIVE_API_KEY": "PKLIVEKEY1234567890"}
    assert sl.find_secret_leaks([tmp_path], env=env) == []


def test_owner_email_alone_is_not_flagged(tmp_path: Path) -> None:
    # Emails/account refs legitimately appear in owner notifications; the scanner
    # must not treat them as secret leaks (only keys/token-assignments count).
    (tmp_path / "email.json").write_text('{"email_to": "owner@example.com", "body": "You are up 2%."}')
    assert sl.find_secret_leaks([tmp_path], env={}) == []


def test_secret_pattern_assignment_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "log.txt").write_text("authorization: Bearer abcdefghijklmnop1234567890")
    leaks = sl.find_secret_leaks([tmp_path], env={})
    assert any(lk.kind == "secret_pattern" for lk in leaks)


def test_scan_skips_the_env_file_and_binary(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ALPACA_LIVE_API_KEY=PKLIVEKEY1234567890")
    env = {"ALPACA_LIVE_API_KEY": "PKLIVEKEY1234567890"}
    # The .env file itself is where the key belongs; it must not be reported.
    assert sl.find_secret_leaks([tmp_path], env=env) == []


def test_key_hygiene_flags_identical_live_and_paper_keys() -> None:
    issues = sl.check_key_hygiene({
        "ALPACA_LIVE_API_KEY": "SAME", "ALPACA_PAPER_API_KEY": "SAME",
        "ALPACA_LIVE_SECRET_KEY": "s1", "ALPACA_PAPER_SECRET_KEY": "s2",
    })
    assert any("identical" in i for i in issues)


def test_key_hygiene_clean_when_distinct() -> None:
    issues = sl.check_key_hygiene({
        "ALPACA_LIVE_API_KEY": "LIVEK", "ALPACA_PAPER_API_KEY": "PAPERK",
        "ALPACA_LIVE_SECRET_KEY": "s1", "ALPACA_PAPER_SECRET_KEY": "s2",
    })
    assert issues == []


def test_email_body_secret_check() -> None:
    assert sl.email_contains_secret("api_key=sk_abcdefghijklmnop1234567890") is True
    assert sl.email_contains_secret("You are up 2% on MSFT. owner@example.com") is False
