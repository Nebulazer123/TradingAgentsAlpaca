import contextlib
import errno
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys
import typing

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.agent_intelligence_ledger import (
    AgentForecast,
    agent_influence_weights,
    summarize_agent_scores,
)
from tradingagents.evals.agent_intelligence_reconciliation import (
    EFFECTIVE_SAMPLE_STATUS_PROVISIONAL,
    INFLUENCE_WEIGHTING_STATUS_LEGACY,
    SCHEMA_VERSION,
    SUMMARY_FRESHNESS_CURRENT,
    SUMMARY_FRESHNESS_MALFORMED,
    SUMMARY_FRESHNESS_MISSING,
    SUMMARY_FRESHNESS_STALE,
    SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY,
    ReconciliationPathError,
    SummaryReadError,
    build_reconciliation_receipt,
    canonical_json_text,
    dependence_block,
    evaluate_summary_freshness,
    market_event_key,
    packet_event_key,
    reconcile_ledger_file,
    write_reconciliation_receipt,
)

runner = CliRunner()

WINDOW_A = {"entry_date": "2026-06-02", "exit_date": "2026-06-09"}
WINDOW_B = {"entry_date": "2026-06-02", "exit_date": "2026-06-10"}


def _source_bound_resolution_evidence() -> dict[str, object]:
    def leg(marker: str) -> dict[str, str]:
        return {
            "schema_version": "source_bound_price_window_evidence/v1",
            "window_id": f"spw-{marker}",
            "window_sha256": marker * 64,
            "security_id": f"security-{marker}",
            "raw_artifact_id": f"pit-{marker}",
            "raw_artifact_sha256": marker * 64,
            "decision_cutoff": "2026-06-12T00:00:00+00:00",
            "retrieved_at": "2026-06-11T00:00:00+00:00",
            "feed": "iex",
            "adjustment_mode": "all",
            "adjustment_status": "total_return_adjusted",
        }

    return {
        "schema_version": "source_bound_resolution_evidence/v1",
        "ticker": leg("a"),
        "benchmark": leg("b"),
    }


def _forecast(
    forecast_id="af-x",
    *,
    resolved=False,
    source_packet_id="pkt-a",
    ticker="NVDA",
    created_at="2026-06-01T12:00:00+00:00",
    horizon="5 trading days",
    benchmark="SPY",
    resolution_window=None,
    probability="0.66",
    **overrides,
):
    row = AgentForecast(
        forecast_id=forecast_id,
        agent="market_analyst",
        ticker=ticker,
        claim="c",
        forecast_type="market_report_direction",
        horizon=horizon,
        probability=probability,
        expected_outcome="x",
        direction="bullish",
        benchmark=benchmark,
        created_at=created_at,
        resolve_after="2026-06-08T12:00:00+00:00",
        source_packet_id=source_packet_id,
        resolved=resolved,
        resolution_window=resolution_window,
    )
    if overrides:
        row = row.__class__(**{**row.as_dict(), **overrides})
    return row


def _line(forecast):
    return json.dumps(forecast.as_dict(), sort_keys=True)


def _mixed_ledger_bytes():
    r1 = _forecast("af-r1", resolved=True, resolution_window=dict(WINDOW_A))
    r2 = _forecast("af-r2", resolved=True, resolution_window=dict(WINDOW_A))
    r3 = _forecast(
        "af-r3", resolved=True, source_packet_id="pkt-b", resolution_window=dict(WINDOW_B)
    )
    r4 = _forecast(
        "af-r4",
        resolved=True,
        source_packet_id="",
        created_at="2026-06-02T12:00:00+00:00",
        resolution_window=dict(WINDOW_A),
    )
    r5 = _forecast(
        "af-r5", resolved=True, source_packet_id="pkt-c", ticker="nvda", created_at="not-a-date"
    )
    pending = _forecast("af-p1", source_packet_id="pkt-d", ticker="AAPL")
    duplicate_of_r1 = _forecast("af-r1", resolved=True, resolution_window=dict(WINDOW_A))
    conflict_a = _forecast("af-x")
    conflict_b = _forecast("af-x", probability="0.67")
    corrupt_json = "{not json"
    schema_invalid = '{"forecast_id":"af-schema","unknown_field":true}'
    lines = [
        _line(r1),
        _line(r2),
        _line(r3),
        _line(r4),
        _line(r5),
        _line(pending),
        _line(duplicate_of_r1),
        _line(conflict_a),
        _line(conflict_b),
        corrupt_json,
        schema_invalid,
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_receipt_is_deterministic_and_binds_one_byte_snapshot():
    data = _mixed_ledger_bytes()

    first = build_reconciliation_receipt(data)
    second = build_reconciliation_receipt(data)

    assert first == second
    assert first["schema_version"] == SCHEMA_VERSION
    assert first["ledger_sha256"] == hashlib.sha256(data).hexdigest()
    assert first["ledger_byte_length"] == len(data)
    assert isinstance(first["receipt_sha256"], str) and len(first["receipt_sha256"]) == 64


def test_receipt_counts_synthetic_mixed_ledger_exactly():
    receipt = build_reconciliation_receipt(_mixed_ledger_bytes())

    assert receipt["raw_nonempty_line_count"] == 11
    assert receipt["valid_forecast_count"] == 9
    assert receipt["corrupt_line_count"] == 2
    assert receipt["resolved_row_count"] == 6
    assert receipt["duplicate_forecast_id_row_count"] == 1
    assert receipt["conflicting_forecast_id_count"] == 1
    assert receipt["packet_event_cluster_count"] == 3
    assert receipt["packet_event_unclusterable_count"] == 1
    assert receipt["packet_event_null_window_resolved_row_count"] == 1
    assert receipt["packet_event_null_window_cluster_count"] == 1
    assert receipt["packet_event_non_null_window_cluster_count"] == 2
    assert receipt["market_event_cluster_count"] == 2
    assert receipt["market_event_unclusterable_count"] == 1
    assert receipt["provisional_effective_sample"] == 2
    assert receipt["provisional_effective_sample_basis"] == "conservative_market_event_cluster_count"
    assert receipt["effective_sample_status"] == EFFECTIVE_SAMPLE_STATUS_PROVISIONAL


def test_receipt_sha256_covers_whole_receipt_without_the_hash_field():
    receipt = build_reconciliation_receipt(_mixed_ledger_bytes())
    assert {
        "schema_version",
        "ledger_sha256",
        "ledger_byte_length",
        "raw_nonempty_line_count",
        "valid_forecast_count",
        "corrupt_line_count",
        "duplicate_forecast_id_row_count",
        "conflicting_forecast_id_count",
        "resolved_row_count",
        "packet_event_cluster_count",
        "packet_event_unclusterable_count",
        "market_event_cluster_count",
        "market_event_unclusterable_count",
        "provisional_effective_sample",
        "summary_freshness",
        "receipt_sha256",
    } <= set(receipt)
    recorded = receipt.pop("receipt_sha256")

    recomputed = hashlib.sha256(canonical_json_text(receipt).encode("utf-8")).hexdigest()

    assert recorded == recomputed


def test_packet_and_market_keys_reject_missing_or_malformed_material_without_invention():
    ok = _forecast(resolved=True)

    assert packet_event_key(ok) == (
        "pkt-a",
        "NVDA",
        "SPY",
        json.dumps(None, sort_keys=True, separators=(",", ":")),
    )
    assert market_event_key(ok) == ("NVDA", "2026-06-01", "5_trading_days", "SPY")
    assert packet_event_key(_forecast(source_packet_id="")) is None
    assert packet_event_key(_forecast(ticker="")) is None
    assert packet_event_key(_forecast(benchmark="")) is None
    assert market_event_key(_forecast(created_at="not-a-date")) is None
    assert market_event_key(_forecast(created_at="")) is None
    assert market_event_key(_forecast(horizon="")) is None
    utc_shifted = _forecast(created_at="2026-06-01T20:00:00-04:00")
    assert market_event_key(utc_shifted)[1] == "2026-06-02"


def test_receipt_alias_protection_fails_closed_on_metadata_errors(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    before = ledger_path.read_bytes()
    target = tmp_path / "receipt.json"
    receipt = build_reconciliation_receipt(before)
    real_samefile = os.path.samefile

    def denied_samefile(first, second):
        names = {pathlib.Path(str(item)).name for item in (first, second)}
        if "receipt.json" in names:
            raise PermissionError(f"{first} metadata denied")
        return real_samefile(first, second)

    monkeypatch.setattr(os.path, "samefile", denied_samefile)

    with pytest.raises(ReconciliationPathError, match="could not be verified"):
        write_reconciliation_receipt(receipt, target, protected_paths=(ledger_path,))

    assert ledger_path.read_bytes() == before
    assert not target.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_reconcile_reads_ledger_bytes_exactly_once(tmp_path, monkeypatch):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())

    real_read_bytes = pathlib.Path.read_bytes
    calls = []

    def counted(self):
        calls.append(self)
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", counted)

    receipt = reconcile_ledger_file(ledger_path)

    assert len(calls) == 1
    assert calls[0] == ledger_path
    assert receipt == build_reconciliation_receipt(_mixed_ledger_bytes())


def test_reconcile_never_mutates_the_raw_ledger(tmp_path, monkeypatch):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    before = ledger_path.read_bytes()

    def _forbidden(*args, **kwargs):
        raise AssertionError("reconciliation must not invoke mutation paths")

    for name in (
        "append_forecasts",
        "write_ledger",
        "write_summary",
        "resolve_forecasts",
        "resolve_forecasts_with_quality",
        "audit_resolved_forecasts",
    ):
        monkeypatch.setattr(
            __import__(
                "tradingagents.evals.agent_intelligence_ledger", fromlist=[name]
            ),
            name,
            _forbidden,
        )

    receipt = reconcile_ledger_file(ledger_path)

    assert ledger_path.read_bytes() == before
    assert receipt["ledger_sha256"] == hashlib.sha256(before).hexdigest()
    assert not list(tmp_path.glob("summary.json"))


def test_summary_freshness_states_are_exact():
    snapshot = {
        "ledger_sha256": "a" * 64,
        "ledger_byte_length": 10,
        "valid_forecast_count": 3,
        "resolved_row_count": 2,
    }
    fingerprint = {
        "schema_version": SCHEMA_VERSION,
        **snapshot,
    }

    assert evaluate_summary_freshness(None, **snapshot) == SUMMARY_FRESHNESS_MISSING
    assert evaluate_summary_freshness(["nope"], **snapshot) == SUMMARY_FRESHNESS_MALFORMED
    assert (
        evaluate_summary_freshness({}, **snapshot) == SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY
    )
    assert (
        evaluate_summary_freshness({"agents": {}}, **snapshot)
        == SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY
    )
    assert (
        evaluate_summary_freshness({"ledger_fingerprint": {"note": "x"}}, **snapshot)
        == SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY
    )
    assert (
        evaluate_summary_freshness(
            {"ledger_fingerprint": {**fingerprint, "ledger_sha256": "b" * 64}}, **snapshot
        )
        == SUMMARY_FRESHNESS_STALE
    )
    assert (
        evaluate_summary_freshness(
            {"ledger_fingerprint": {**fingerprint, "valid_forecast_count": 4}}, **snapshot
        )
        == SUMMARY_FRESHNESS_STALE
    )
    assert (
        evaluate_summary_freshness(
            {"ledger_fingerprint": {**fingerprint, "resolved_row_count": 9}}, **snapshot
        )
        == SUMMARY_FRESHNESS_STALE
    )
    assert (
        evaluate_summary_freshness(
            {"ledger_fingerprint": {**fingerprint, "ledger_byte_length": 11}}, **snapshot
        )
        == SUMMARY_FRESHNESS_STALE
    )
    assert (
        evaluate_summary_freshness(
            {"ledger_fingerprint": {"ledger_sha256": "a" * 64}}, **snapshot
        )
        == SUMMARY_FRESHNESS_STALE
    )
    assert (
        evaluate_summary_freshness(
            {
                "ledger_fingerprint": fingerprint,
                "influence_weights": {"execution_authority": "none"},
            },
            **snapshot,
        )
        == SUMMARY_FRESHNESS_CURRENT
    )


def test_reconcile_reads_summary_freshness_from_disk_states(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    receipt = build_reconciliation_receipt(ledger_path.read_bytes())
    snapshot = {
        "ledger_sha256": receipt["ledger_sha256"],
        "ledger_byte_length": receipt["ledger_byte_length"],
        "valid_forecast_count": receipt["valid_forecast_count"],
        "resolved_row_count": receipt["resolved_row_count"],
    }

    missing = reconcile_ledger_file(ledger_path, summary_path=tmp_path / "nope.json")
    assert missing["summary_freshness"] == SUMMARY_FRESHNESS_MISSING

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{broken", encoding="utf-8")
    malformed = reconcile_ledger_file(ledger_path, summary_path=malformed_path)
    assert malformed["summary_freshness"] == SUMMARY_FRESHNESS_MALFORMED

    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps({"agents": {}}), encoding="utf-8")
    legacy = reconcile_ledger_file(ledger_path, summary_path=legacy_path)
    assert legacy["summary_freshness"] == SUMMARY_FRESHNESS_UNVERIFIABLE_LEGACY

    stale_payload = {
        "ledger_fingerprint": {
            "ledger_sha256": receipt["ledger_sha256"],
            "ledger_byte_length": receipt["ledger_byte_length"],
            "valid_forecast_count": receipt["valid_forecast_count"],
            "resolved_row_count": receipt["resolved_row_count"] + 1,
        }
    }
    stale_path = tmp_path / "stale.json"
    stale_path.write_text(json.dumps(stale_payload), encoding="utf-8")
    stale = reconcile_ledger_file(ledger_path, summary_path=stale_path)
    assert stale["summary_freshness"] == SUMMARY_FRESHNESS_STALE

    current_payload = {"ledger_fingerprint": dict(snapshot)}
    current_path = tmp_path / "current.json"
    current_path.write_text(json.dumps(current_payload), encoding="utf-8")
    current = reconcile_ledger_file(ledger_path, summary_path=current_path)
    assert current["summary_freshness"] == SUMMARY_FRESHNESS_CURRENT


def test_dependence_block_clusters_resolved_rows_and_labels_provisional_bound():
    rows = [
        _forecast("af-r1", resolved=True, resolution_window=dict(WINDOW_A)),
        _forecast("af-r2", resolved=True, resolution_window=dict(WINDOW_A)),
        _forecast("af-r3", resolved=True, source_packet_id="pkt-b"),
        _forecast("af-p1"),
    ]

    block = dependence_block(rows)

    assert block == {
        "scope": "resolved_rows",
        "resolved_row_count": 3,
        "packet_event_cluster_count": 2,
        "packet_event_unclusterable_count": 0,
        "packet_event_null_window_resolved_row_count": 1,
        "packet_event_null_window_cluster_count": 1,
        "packet_event_non_null_window_cluster_count": 1,
        "market_event_cluster_count": 1,
        "market_event_unclusterable_count": 0,
        "provisional_effective_sample": 1,
        "provisional_effective_sample_basis": "conservative_market_event_cluster_count",
        "effective_sample_status": EFFECTIVE_SAMPLE_STATUS_PROVISIONAL,
        "raw_resolved_rows_are_independent_observations": False,
        "influence_weighting_status": INFLUENCE_WEIGHTING_STATUS_LEGACY,
    }
    assert dependence_block(rows) == block


def test_summarize_agent_scores_exposes_deterministic_dependence_block():
    rows = [
        _forecast("af-r1", resolved=True, resolution_window=dict(WINDOW_A)),
        _forecast("af-r2", resolved=True, resolution_window=dict(WINDOW_A)),
    ]

    summary = summarize_agent_scores(rows)

    assert summary["dependence"] == dependence_block(rows)
    assert summary["dependence"]["provisional_effective_sample"] == 1
    assert (
        summary["dependence"]["effective_sample_status"]
        == "provisional_pending_preregistered_estimator"
    )
    assert summary["dependence"]["raw_resolved_rows_are_independent_observations"] is False


def test_unverified_source_metadata_cannot_earn_influence_despite_dependence_fields():
    def row(fid, agent, outcome):
        return _forecast(
            fid,
            agent=agent,
            resolved=True,
            outcome=outcome,
            brier_score="0.1156" if outcome else "0.4356",
            agent_score_delta="0.16" if outcome else "-0.16",
            relative_return="8.00" if outcome else "-2.00",
            label_quality="high",
            resolution_evidence=_source_bound_resolution_evidence(),
        )

    forecasts = []
    for index in range(3):
        forecasts.append(row(f"af-mkt-{index}", "market_analyst", True))
        forecasts.append(row(f"af-news-{index}", "news_analyst", False))

    weights = agent_influence_weights(forecasts)

    assert weights["kind"] == "agent_influence_weights"
    assert weights["execution_authority"] == "none"
    assert weights["forecast_count"] == 6
    assert weights["qualifying_resolved_count"] == 0
    assert weights["agents"]["market_analyst"]["weight"] == "1.00"
    assert weights["agents"]["market_analyst"]["state"] == "insufficient_history"
    assert weights["agents"]["news_analyst"]["weight"] == "1.00"


def test_cli_prints_canonical_json_and_hermetic_summary_state(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["valid_forecast_count"] == 9
    assert payload["resolved_row_count"] == 6
    assert payload["packet_event_cluster_count"] == 3
    assert payload["market_event_cluster_count"] == 2
    assert payload["provisional_effective_sample"] == 2
    assert payload["summary_freshness"] == SUMMARY_FRESHNESS_MISSING
    assert payload["influence_weighting_status"] == INFLUENCE_WEIGHTING_STATUS_LEGACY
    assert INFLUENCE_WEIGHTING_STATUS_LEGACY in result.output
    assert result.output.strip() == canonical_json_text(payload)


def test_cli_writes_only_the_receipt_atomically_when_asked(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    before = ledger_path.read_bytes()
    receipt_path = tmp_path / "receipt.json"

    first = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--receipt-path",
            str(receipt_path),
        ],
    )
    assert first.exit_code == 0, first.output
    assert receipt_path.read_text(encoding="utf-8").strip() == first.output.strip()
    assert ledger_path.read_bytes() == before
    assert not summary_path.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]

    second_payload = json.loads(first.output)
    second_payload["receipt_sha256"] = "0" * 64
    receipt_path.write_text(canonical_json_text(second_payload), encoding="utf-8")

    rewrite = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--receipt-path",
            str(receipt_path),
        ],
    )
    assert rewrite.exit_code == 0, rewrite.output
    assert receipt_path.read_text(encoding="utf-8").strip() == rewrite.output.strip()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def _expect_ledger_intact(root):
    assert (root / "ledger.jsonl").read_bytes() == _mixed_ledger_bytes()


def _expect_alias_still_symlink(root):
    alias = root / "ledger-alias.jsonl"
    ledger = (root / "ledger.jsonl").resolve()
    assert alias.is_symlink()
    assert alias.resolve() == ledger
    assert alias.read_bytes() == _mixed_ledger_bytes()


def _expect_summary_absent(root):
    assert not (root / "summary.json").exists()


def _expect_still_directory(root):
    directory = root / "receipt-dir"
    assert directory.is_dir()
    assert not [entry for entry in directory.iterdir() if entry.name.endswith(".tmp")]


def _expect_hardlink_intact(root):
    alias = root / "ledger-hardlink.jsonl"
    ledger = root / "ledger.jsonl"
    assert alias.exists() and not alias.is_symlink()
    assert os.path.samefile(alias, ledger)
    assert alias.read_bytes() == _mixed_ledger_bytes()


@pytest.mark.parametrize(
    "target_factory,verify",
    [
        pytest.param(
            lambda root: root / "ledger.jsonl",
            _expect_ledger_intact,
            id="ledger-itself",
        ),
        pytest.param(
            lambda root: root / "ledger-alias.jsonl",
            _expect_alias_still_symlink,
            id="symlink-alias-of-ledger",
        ),
        pytest.param(
            lambda root: root / "ledger-hardlink.jsonl",
            _expect_hardlink_intact,
            id="hardlink-alias-of-ledger",
        ),
        pytest.param(
            lambda root: root / "summary.json",
            _expect_summary_absent,
            id="summary-path",
        ),
        pytest.param(
            lambda root: root / "receipt-dir",
            _expect_still_directory,
            id="directory-target",
        ),
    ],
)
def test_cli_rejects_unsafe_receipt_paths(tmp_path, target_factory, verify):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    alias = tmp_path / "ledger-alias.jsonl"
    alias.symlink_to(ledger_path)
    hardlink = tmp_path / "ledger-hardlink.jsonl"
    os.link(ledger_path, hardlink)
    (tmp_path / "receipt-dir").mkdir()
    target = target_factory(tmp_path)

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--receipt-path",
            str(target),
        ],
    )

    assert result.exit_code != 0
    verify(tmp_path)


def test_write_reconciliation_receipt_rejects_protected_paths_directly(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    receipt = build_reconciliation_receipt(ledger_path.read_bytes())
    alias = tmp_path / "alias.jsonl"
    alias.symlink_to(ledger_path)

    with pytest.raises(ReconciliationPathError):
        write_reconciliation_receipt(
            receipt, ledger_path, protected_paths=(ledger_path,)
        )
    with pytest.raises(ReconciliationPathError):
        write_reconciliation_receipt(receipt, alias, protected_paths=(ledger_path,))
    assert not alias.exists() or alias.is_symlink()


def test_cli_fails_cleanly_when_the_ledger_is_missing(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(tmp_path / "absent.jsonl"),
            "--summary-path",
            str(tmp_path / "summary.json"),
        ],
    )

    assert result.exit_code != 0
    assert "could not read ledger" in result.output
    assert "could not read summary" not in result.output


def test_cli_reports_summary_read_errors_with_summary_wording(tmp_path, monkeypatch):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")

    real_read_bytes = pathlib.Path.read_bytes

    def denied_summary_read(self):
        if self.name == "summary.json":
            raise PermissionError(f"{self} denied")
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", denied_summary_read)

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
        ],
    )

    assert result.exit_code != 0
    assert "could not read summary" in result.output
    assert "could not read ledger" not in result.output


@pytest.mark.parametrize("alias_kind", ["direct", "symlink", "hardlink"])
def test_single_record_ledger_alias_is_malformed_not_unverifiable(
    tmp_path, monkeypatch, alias_kind
):
    single_record = (_line(_forecast("af-single")) + "\n").encode("utf-8")
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(single_record)
    if alias_kind == "direct":
        summary_path = ledger_path
    elif alias_kind == "symlink":
        summary_path = tmp_path / "ledger-symlink.jsonl"
        summary_path.symlink_to(ledger_path)
    else:
        summary_path = tmp_path / "ledger-hardlink.jsonl"
        os.link(ledger_path, summary_path)

    real_read_bytes = pathlib.Path.read_bytes
    ledger_reads = {"count": 0}

    def counting_read(self):
        try:
            is_ledger = self.exists() and os.path.samefile(self, ledger_path)
        except OSError:
            is_ledger = False
        if is_ledger:
            ledger_reads["count"] += 1
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", counting_read)

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert ledger_reads["count"] == 1
    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_MALFORMED


@pytest.mark.parametrize("alias_kind", ["direct", "symlink", "hardlink"])
def test_summary_aliasing_the_ledger_reuses_one_captured_byte_snapshot(
    tmp_path, monkeypatch, alias_kind
):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    if alias_kind == "direct":
        summary_path = ledger_path
    elif alias_kind == "symlink":
        summary_path = tmp_path / "ledger-symlink.jsonl"
        summary_path.symlink_to(ledger_path)
    else:
        summary_path = tmp_path / "ledger-hardlink.jsonl"
        os.link(ledger_path, summary_path)

    real_read_bytes = pathlib.Path.read_bytes
    ledger_reads = {"count": 0}

    def counting_read(self):
        try:
            is_ledger = self.exists() and os.path.samefile(self, ledger_path)
        except OSError:
            is_ledger = False
        if is_ledger:
            ledger_reads["count"] += 1
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", counting_read)

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert ledger_reads["count"] == 1
    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_MALFORMED
    assert receipt["valid_forecast_count"] == 9


def _raw_row(**overrides):
    row = _forecast(**overrides).as_dict()
    return {key: value for key, value in row.items()}


def _spliced_row_line(forecast_id, **overrides):
    return json.dumps(
        _forecast(forecast_id, **overrides).as_dict(), sort_keys=True, separators=(",", ":")
    )


def test_strict_json_rejects_nan_inside_resolution_window_rows():
    clean = _spliced_row_line(
        "af-nan-window",
        resolved=True,
        resolution_window={"entry_date": "2026-06-02", "exit_date": "2026-06-09"},
    )
    nan_row = clean.replace(
        '"exit_date":"2026-06-09"}',
        '"exit_date":"2026-06-09","session_count":NaN}',
        1,
    ).encode("utf-8")
    assert b"NaN" in nan_row
    data = _line(_forecast("af-ok")).encode("utf-8") + b"\n" + nan_row + b"\n"

    receipt = build_reconciliation_receipt(data)

    assert receipt["valid_forecast_count"] == 1
    assert receipt["corrupt_line_count"] == 1


def test_strict_json_rejects_duplicate_keys_including_nested_windows():
    nested_dup = _spliced_row_line(
        "af-dup-nested",
        resolved=True,
        resolution_window={"entry_date": "2026-06-02", "exit_date": "2026-06-09"},
    ).replace(
        '"entry_date":"2026-06-02"',
        '"entry_date":"2026-06-02","entry_date":"2026-06-03"',
        1,
    )
    top_dup = _spliced_row_line("af-dup-top").replace(
        '"ticker":"NVDA"', '"ticker":"NVDA","ticker":"MSFT"', 1
    )
    data = (
        _line(_forecast("af-ok")).encode("utf-8")
        + b"\n"
        + nested_dup.encode("utf-8")
        + b"\n"
        + top_dup.encode("utf-8")
        + b"\n"
    )

    receipt = build_reconciliation_receipt(data)

    assert receipt["valid_forecast_count"] == 1
    assert receipt["corrupt_line_count"] == 2


def test_canonical_json_text_rejects_non_finite_values():
    with pytest.raises(ValueError):
        canonical_json_text({"session_count": float("nan")})
    with pytest.raises(ValueError):
        canonical_json_text({"session_count": float("inf")})
    with pytest.raises(ValueError):
        canonical_json_text({"session_count": float("-inf")})


def test_strict_lf_splitting_tolerates_crlf_and_keeps_unicode_separators_intact():
    separator_row = _forecast("af-uni", claim="line\u2028break\u2029and\u0085end")
    crlf_row = _forecast("af-crlf")
    bad_utf8 = b'{"forecast_id":"af-bad","claim":"\xff"}'
    separator_line = json.dumps(
        separator_row.as_dict(), sort_keys=True, ensure_ascii=False
    )
    data = (
        _line(crlf_row).encode("utf-8")
        + b"\r\n"
        + separator_line.encode("utf-8")
        + b"\n"
        + bad_utf8
        + b"\n"
    )
    assert b"\xe2\x80\xa8" in data
    assert b"\xe2\x80\xa9" in data
    assert b"\xc2\x85" in data

    receipt = build_reconciliation_receipt(data)

    assert receipt["ledger_sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt["raw_nonempty_line_count"] == 3
    assert receipt["valid_forecast_count"] == 2
    assert receipt["corrupt_line_count"] == 1


def test_vertical_tab_and_form_feed_records_count_raw_nonempty_and_corrupt():
    data = (
        _line(_forecast("af-ok")).encode("utf-8")
        + b"\n"
        + b"\x0b"
        + b"\n"
        + b"\x0c"
        + b"\n"
    )

    receipt = build_reconciliation_receipt(data)

    assert receipt["raw_nonempty_line_count"] == 3
    assert receipt["valid_forecast_count"] == 1
    assert receipt["corrupt_line_count"] == 2


def test_space_and_tab_padding_records_stay_ignored_with_trailing_cr():
    data = (
        _line(_forecast("af-ok")).encode("utf-8")
        + b"\r\n"
        + b"   "
        + b"\n"
        + b"\t\t"
        + b"\n"
    )

    receipt = build_reconciliation_receipt(data)

    assert receipt["ledger_sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt["raw_nonempty_line_count"] == 1
    assert receipt["valid_forecast_count"] == 1
    assert receipt["corrupt_line_count"] == 0


def test_invalid_utf8_inside_an_otherwise_valid_row_counts_corrupt():
    clean_line = json.dumps(
        _forecast("af-badutf8").as_dict(), sort_keys=True, separators=(",", ":")
    )
    corrupted_line = clean_line.encode("utf-8").replace(
        b'"claim":"c"', b'"claim":"bad\xff"', 1
    )
    data = _line(_forecast("af-ok")).encode("utf-8") + b"\n" + corrupted_line + b"\n"
    twin = (
        _line(_forecast("af-ok")).encode("utf-8")
        + b"\n"
        + clean_line.encode("utf-8")
        + b"\n"
    )

    assert b"\xff" in corrupted_line
    receipt = build_reconciliation_receipt(data)
    twin_receipt = build_reconciliation_receipt(twin)

    assert receipt["raw_nonempty_line_count"] == 2
    assert receipt["valid_forecast_count"] == 1
    assert receipt["corrupt_line_count"] == 1
    assert twin_receipt["valid_forecast_count"] == 2
    assert twin_receipt["corrupt_line_count"] == 0


def test_non_object_json_records_are_corrupt_not_valid():
    data = (
        b"[1,2]\n"
        + b'"just a string"\n'
        + b"123\n"
        + b"null\n"
        + _line(_forecast("af-ok")).encode("utf-8")
        + b"\n"
    )

    receipt = build_reconciliation_receipt(data)

    assert receipt["raw_nonempty_line_count"] == 5
    assert receipt["valid_forecast_count"] == 1
    assert receipt["corrupt_line_count"] == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"probability": 123},
        {"resolved": "true"},
        {"outcome": 1},
        {"evidence_sources": "market_report"},
        {"quality_flags": [1]},
        {"resolution_window": []},
        {"source_packet_id": {}},
        {"ticker": ["NVDA"]},
        {"cost_usd": None},
    ],
)
def test_schema_type_drift_rows_are_corrupt(overrides):
    data = (_line(_forecast("af-drift", **overrides)) + "\n").encode("utf-8")

    receipt = build_reconciliation_receipt(data)

    assert receipt["valid_forecast_count"] == 0
    assert receipt["corrupt_line_count"] == 1


def test_undeclared_fields_are_schema_corrupt():
    raw = _raw_row()
    raw["undeclared_field"] = "x"
    data = (json.dumps(raw, sort_keys=True) + "\n").encode("utf-8")

    receipt = build_reconciliation_receipt(data)

    assert receipt["valid_forecast_count"] == 0
    assert receipt["corrupt_line_count"] == 1


def test_cluster_keys_never_stringify_non_strings_and_require_mapping_windows():
    numeric_pid = {
        **_raw_row(source_packet_id=123),
        "resolution_window": dict(WINDOW_A),
    }
    list_horizon = {**_raw_row(), "horizon": ["5 trading days"]}
    dict_created = {**_raw_row(), "created_at": {"when": "2026-06-01"}}
    non_mapping_window_str = {**_raw_row(), "resolution_window": "entry/exit"}
    non_mapping_window_int = {**_raw_row(), "resolution_window": 42}
    mapping_window = {**_raw_row(), "resolution_window": dict(WINDOW_A)}
    omitted_window = _raw_row()
    del omitted_window["resolution_window"]

    assert packet_event_key(numeric_pid) is None
    assert market_event_key(dict_created) is None
    assert market_event_key(list_horizon) is None
    assert packet_event_key(non_mapping_window_str) is None
    assert packet_event_key(non_mapping_window_int) is None
    assert packet_event_key(omitted_window) is None
    assert packet_event_key(mapping_window) is not None


def test_market_key_requires_offset_aware_timestamps():
    naive = {**_raw_row(), "created_at": "2026-06-01T12:00:00"}
    date_only = {**_raw_row(), "created_at": "2026-06-01"}
    aware = {**_raw_row()}

    assert market_event_key(naive) is None
    assert market_event_key(date_only) is None
    assert market_event_key(aware) == ("NVDA", "2026-06-01", "5_trading_days", "SPY")


def test_resolved_rows_require_exactly_true():
    truthy_int = _forecast("af-int", resolved=True).as_dict() | {"resolved": 1}
    exact_bool = _forecast("af-bool", resolved=True)

    assert dependence_block([truthy_int])["resolved_row_count"] == 0
    assert dependence_block([exact_bool])["resolved_row_count"] == 1


def test_null_window_counters_separate_explicit_null_from_missing_field(tmp_path):
    explicit_null = _forecast("af-null", resolved=True)
    missing_field = _forecast("af-missing", resolved=True, source_packet_id="pkt-a")
    raw_missing = missing_field.as_dict()
    del raw_missing["resolution_window"]
    both = (
        json.dumps(explicit_null.as_dict(), sort_keys=True)
        + "\n"
        + json.dumps(raw_missing, sort_keys=True)
        + "\n"
    )
    data = both.encode("utf-8")

    receipt = build_reconciliation_receipt(data)

    assert receipt["resolved_row_count"] == 2
    assert receipt["packet_event_cluster_count"] == 1
    assert receipt["packet_event_unclusterable_count"] == 1
    assert receipt["packet_event_null_window_resolved_row_count"] == 1
    assert receipt["packet_event_null_window_cluster_count"] == 1
    assert receipt["packet_event_non_null_window_cluster_count"] == 0
    block = dependence_block([explicit_null, missing_field])
    assert block["packet_event_null_window_resolved_row_count"] == 2


def test_mixed_duplicate_and_conflict_group_accounting():
    base = _forecast("af-mix", resolved=True)
    identical_copy = _forecast("af-mix", resolved=True)
    divergent = _forecast("af-mix", resolved=True, probability="0.67")
    data = (
        "\n".join([_line(base), _line(identical_copy), _line(divergent)]) + "\n"
    ).encode("utf-8")

    receipt = build_reconciliation_receipt(data)

    assert receipt["duplicate_forecast_id_row_count"] == 0
    assert receipt["conflicting_forecast_id_count"] == 1
    assert receipt["valid_forecast_count"] == 3


def test_summary_invalid_utf8_is_malformed(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_bytes(b'{"agents": "\xff"}')

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_MALFORMED


def test_summary_json_literal_null_is_malformed_not_missing(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("null", encoding="utf-8")

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_MALFORMED


def _raw_fingerprint_summary(ledger_receipt):
    return (
        '{"ledger_fingerprint": {"ledger_sha256": "'
        + ledger_receipt["ledger_sha256"]
        + '", "ledger_byte_length": '
        + str(ledger_receipt["ledger_byte_length"])
        + ', "valid_forecast_count": '
        + str(ledger_receipt["valid_forecast_count"])
        + ', "resolved_row_count": '
        + str(ledger_receipt["resolved_row_count"])
        + "}}"
    )


def test_summary_with_nan_is_malformed_even_when_fingerprint_matches(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    base = build_reconciliation_receipt(ledger_path.read_bytes())
    summary_text = _raw_fingerprint_summary(base).replace(
        '"resolved_row_count": ' + str(base["resolved_row_count"]),
        '"resolved_row_count": ' + str(base["resolved_row_count"]) + ', "note": NaN',
        1,
    )
    assert "NaN" in summary_text
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(summary_text, encoding="utf-8")

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_MALFORMED


def test_summary_with_duplicate_keys_is_malformed(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_text = (
        '{"ledger_fingerprint": {"ledger_sha256": "a"}, '
        + '"ledger_fingerprint": {"ledger_sha256": "b"}}'
    )
    assert summary_text.count("ledger_fingerprint") == 2
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(summary_text, encoding="utf-8")

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_MALFORMED


def test_summary_read_never_probes_path_existence(tmp_path, monkeypatch):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    base = build_reconciliation_receipt(ledger_path.read_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(_raw_fingerprint_summary(base), encoding="utf-8")

    probed = {"paths": []}
    real_exists = pathlib.Path.exists

    def forbidden_exists(self):
        if self in (ledger_path, summary_path):
            probed["paths"].append(str(self))
            raise AssertionError(f"unexpected existence probe on {self}")
        return real_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", forbidden_exists)

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert probed["paths"] == []
    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_CURRENT


def test_summary_alias_stat_permission_error_raises_summary_read_error(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    real_samefile = os.path.samefile

    def denied_samefile(first, second):
        if "summary.json" in str(first) or "summary.json" in str(second):
            raise PermissionError(f"{first} metadata denied")
        return real_samefile(first, second)

    monkeypatch.setattr(os.path, "samefile", denied_samefile)

    with pytest.raises(SummaryReadError, match="could not read summary"):
        reconcile_ledger_file(ledger_path, summary_path=summary_path)


def test_cli_reports_alias_stat_permission_error_with_summary_wording(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    real_samefile = os.path.samefile

    def denied_samefile(first, second):
        if "summary.json" in str(first) or "summary.json" in str(second):
            raise PermissionError(f"{first} metadata denied")
        return real_samefile(first, second)

    monkeypatch.setattr(os.path, "samefile", denied_samefile)

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
        ],
    )

    assert result.exit_code != 0
    assert "could not read summary" in result.output
    assert "could not read ledger" not in result.output


def test_duplicate_accounting_preserves_window_field_presence(tmp_path):
    explicit_null = _forecast("af-window-presence", resolved=True)
    omitted_window = _forecast("af-window-presence", resolved=True)
    raw_omitted = omitted_window.as_dict()
    del raw_omitted["resolution_window"]
    data = (
        json.dumps(explicit_null.as_dict(), sort_keys=True)
        + "\n"
        + json.dumps(raw_omitted, sort_keys=True)
        + "\n"
    ).encode("utf-8")

    receipt = build_reconciliation_receipt(data)

    assert receipt["valid_forecast_count"] == 2
    assert receipt["resolved_row_count"] == 2
    assert receipt["duplicate_forecast_id_row_count"] == 0
    assert receipt["conflicting_forecast_id_count"] == 1
    assert receipt["packet_event_cluster_count"] == 1
    assert receipt["packet_event_unclusterable_count"] == 1
    assert receipt["packet_event_null_window_resolved_row_count"] == 1
    assert receipt["packet_event_null_window_cluster_count"] == 1
    assert receipt["packet_event_non_null_window_cluster_count"] == 0


def test_summary_vanishing_between_exists_and_read_is_missing(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")

    real_read_bytes = pathlib.Path.read_bytes
    summary_reads = {"count": 0}

    def vanishing_read(self):
        if self.name == "summary.json":
            summary_reads["count"] += 1
            raise FileNotFoundError(f"{self} vanished")
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", vanishing_read)

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert summary_reads["count"] == 1
    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_MISSING


def test_summary_permission_error_surfaces_as_accurate_read_error(
    tmp_path, monkeypatch
):
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")

    real_read_bytes = pathlib.Path.read_bytes

    def denied_read(self):
        if self.name == "summary.json":
            raise PermissionError(f"{self} denied")
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", denied_read)

    with pytest.raises(SummaryReadError, match="could not read summary"):
        reconcile_ledger_file(ledger_path, summary_path=summary_path)


def test_receipt_carries_the_legacy_influence_label_in_sha_coverage():
    receipt = build_reconciliation_receipt(_mixed_ledger_bytes())

    assert receipt["influence_weighting_status"] == INFLUENCE_WEIGHTING_STATUS_LEGACY
    recorded = receipt.pop("receipt_sha256")
    recomputed = hashlib.sha256(canonical_json_text(receipt).encode("utf-8")).hexdigest()
    assert recorded == recomputed


def test_write_failure_after_replace_is_not_reported_as_success(tmp_path, monkeypatch):
    import tradingagents.evals.agent_intelligence_reconciliation as reconciliation

    receipt = build_reconciliation_receipt(_mixed_ledger_bytes())
    target = tmp_path / "receipt.json"
    calls = []
    real_fsync_directory = reconciliation._fsync_directory

    def recording(path):
        calls.append(path)
        return real_fsync_directory(path)

    monkeypatch.setattr(reconciliation, "_fsync_directory", recording)

    write_reconciliation_receipt(receipt, target)

    assert calls and pathlib.Path(calls[0]).resolve() == tmp_path.resolve()

    monkeypatch.setattr(
        reconciliation,
        "_fsync_directory",
        lambda path: (_ for _ in ()).throw(OSError("sync failed")),
    )

    with pytest.raises(OSError, match="sync failed"):
        write_reconciliation_receipt(receipt, target)


def test_cli_reports_write_failures_as_write_errors_not_read_errors(
    tmp_path, monkeypatch
):
    import tradingagents.evals.agent_intelligence_reconciliation as reconciliation

    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(_mixed_ledger_bytes())

    def failing_replace(src, dst):
        raise PermissionError("disk full")

    monkeypatch.setattr(reconciliation.os, "replace", failing_replace)

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-reconcile",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(tmp_path / "summary.json"),
            "--receipt-path",
            str(tmp_path / "receipt.json"),
        ],
    )

    assert result.exit_code != 0
    assert "could not write receipt" in result.output
    assert "could not read ledger" not in result.output
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_reconciliation_module_imports_without_the_ledger_module():
    probe = (
        "import sys, tradingagents.evals.agent_intelligence_reconciliation; "
        "raise SystemExit("
        "0 if 'tradingagents.evals.agent_intelligence_ledger' not in sys.modules else 1)"
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "field, literal",
    [
        ("valid_forecast_count", "true"),
        ("valid_forecast_count", "1.0"),
        ("resolved_row_count", "true"),
        ("resolved_row_count", "1.0"),
    ],
)
def test_fingerprint_numeric_fields_require_exact_int_types(tmp_path, field, literal):
    data = (_line(_forecast("af-fp", resolved=True)) + "\n").encode("utf-8")
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_bytes(data)
    base = build_reconciliation_receipt(data)
    base_text = _raw_fingerprint_summary(base)
    summary_text = base_text.replace(
        f'"{field}": {base[field]}', f'"{field}": {literal}', 1
    )
    assert summary_text != base_text
    summary_path = tmp_path / f"summary-{field}-{literal}.json"
    summary_path.write_text(summary_text, encoding="utf-8")

    receipt = reconcile_ledger_file(ledger_path, summary_path=summary_path)

    assert receipt["summary_freshness"] == SUMMARY_FRESHNESS_STALE


def test_type_checker_validates_dict_keys_and_values():
    from tradingagents.evals.agent_intelligence_reconciliation import _type_checker

    check = _type_checker(dict[str, int])

    assert check({"a": 1}) is True
    assert check({"a": "x"}) is False
    assert check({1: 1}) is False
    assert check({}) is True

    loose = _type_checker(dict[str, typing.Any])
    assert loose({"anything": [1, "x"]}) is True


@pytest.mark.parametrize(
    "hint",
    [
        dict,
        list,
        tuple,
        set,
        frozenset,
        tuple[int, str],
        typing.Dict,  # noqa: UP006 - deliberate legacy generic fixture
        typing.List,  # noqa: UP006 - deliberate legacy generic fixture
    ],
)
def test_type_checker_rejects_unsupported_hints_loudly(hint):
    from tradingagents.evals.agent_intelligence_reconciliation import _type_checker

    with pytest.raises(TypeError):
        _type_checker(hint)


def test_type_checker_accepts_declared_agent_forecast_hints():
    from tradingagents.evals.agent_intelligence_reconciliation import _type_checker

    assert _type_checker(object)({"anything": 1}) is True
    assert _type_checker(str)("NVDA") is True
    assert _type_checker(bool)(1) is False

    int_check = _type_checker(int)

    assert int_check(1) is True
    assert int_check(True) is False
    assert int_check(1.0) is False


def test_evaluate_summary_freshness_requires_exact_int_byte_length():
    fingerprint_sha = "c" * 64
    snapshot = {
        "ledger_sha256": fingerprint_sha,
        "ledger_byte_length": 1,
        "valid_forecast_count": 0,
        "resolved_row_count": 0,
    }

    def freshness_with(recorded_byte_length):
        payload = {
            "ledger_fingerprint": {
                "ledger_sha256": fingerprint_sha,
                "ledger_byte_length": recorded_byte_length,
                "valid_forecast_count": 0,
                "resolved_row_count": 0,
            }
        }
        return evaluate_summary_freshness(payload, **snapshot)

    assert freshness_with(1) == SUMMARY_FRESHNESS_CURRENT
    assert freshness_with(True) == SUMMARY_FRESHNESS_STALE
    assert freshness_with(1.0) == SUMMARY_FRESHNESS_STALE


def test_successful_receipt_file_mode_is_owner_only(tmp_path):
    target = tmp_path / "receipt.json"

    write_reconciliation_receipt(
        build_reconciliation_receipt(_mixed_ledger_bytes()), target
    )

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_fdopen_failure_closes_descriptor_and_removes_temp_residue(
    tmp_path, monkeypatch
):
    import tempfile as tempfile_module

    import tradingagents.evals.agent_intelligence_reconciliation as reconciliation

    receipt = build_reconciliation_receipt(_mixed_ledger_bytes())
    target = tmp_path / "receipt.json"
    captured = {}
    real_mkstemp = tempfile_module.mkstemp

    def capturing_mkstemp(*args, **kwargs):
        descriptor, name = real_mkstemp(*args, **kwargs)
        captured["fd"] = descriptor
        captured["name"] = name
        return descriptor, name

    def failing_fdopen(descriptor, *args, **kwargs):
        raise OSError(errno.EBADF, "bad file descriptor")

    monkeypatch.setattr(reconciliation.tempfile, "mkstemp", capturing_mkstemp)
    monkeypatch.setattr(reconciliation.os, "fdopen", failing_fdopen)

    try:
        with pytest.raises(OSError, match="bad file descriptor"):
            write_reconciliation_receipt(receipt, target)

        with pytest.raises(OSError):
            os.fstat(captured["fd"])
        assert not pathlib.Path(captured["name"]).exists()
        assert not target.exists()
    finally:
        with contextlib.suppress(OSError):
            os.close(captured["fd"])


def test_fdopen_close_failure_preserves_original_error(tmp_path, monkeypatch):
    import tempfile as tempfile_module

    import tradingagents.evals.agent_intelligence_reconciliation as reconciliation

    receipt = build_reconciliation_receipt(_mixed_ledger_bytes())
    target = tmp_path / "receipt.json"
    captured = {}
    real_mkstemp = tempfile_module.mkstemp

    def capturing_mkstemp(*args, **kwargs):
        descriptor, name = real_mkstemp(*args, **kwargs)
        captured["fd"] = descriptor
        captured["name"] = name
        return descriptor, name

    def closing_then_failing_fdopen(descriptor, *args, **kwargs):
        os.close(descriptor)
        raise OSError(errno.EIO, "storage media revoked")

    monkeypatch.setattr(reconciliation.tempfile, "mkstemp", capturing_mkstemp)
    monkeypatch.setattr(reconciliation.os, "fdopen", closing_then_failing_fdopen)

    try:
        with pytest.raises(OSError, match="storage media revoked"):
            write_reconciliation_receipt(receipt, target)

        with pytest.raises(OSError):
            os.fstat(captured["fd"])
        assert not pathlib.Path(captured["name"]).exists()
        assert not target.exists()
    finally:
        with contextlib.suppress(OSError):
            os.close(captured["fd"])
