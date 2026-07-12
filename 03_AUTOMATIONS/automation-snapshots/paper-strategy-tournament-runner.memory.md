# Automation Memory Rollup Digest

This live memory was compacted by the TradingAgents automation memory
rollup tool. Full history was archived before this file was replaced.

- Automation: paper-strategy-tournament-runner
- Original path: C:\cm\automations\paper-strategy-tournament-runner\memory.md
- Archive path: results\token_efficiency\automation_memory_archives\paper-strategy-tournament-runner\memory-archive-20260607.md
- Original bytes: 97356
- Original approx tokens: 24339
- Original line count: 708
- Original sha256: e5c5f515c503e0a1de48db779b2a934b6dbb67b516d8a8f1532dd8373bef2085
- Retained tail lines: 80

## Reader Policy

- Start with `results/_context/latest-summary.json` and `latest-flags.json`.
- Open the archive only when debugging this exact automation history.
- Do not infer trading authority from this memory file.

## Retained Tail

- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament` through `.\.venv\Scripts\python.exe -m cli.main`; AlphaInsider remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=308300.37`, and `packet_path=results\paper_strategy_tournament\alphainsider-paper-watch-20260604-171713-294804.json`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260604-171743-366665.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10141.02` return `1.41%` tracked_days `5`; `catalyst-relative-strength` equity `9666.39` return `-3.33%` tracked_days `5`; `current-aggressive` equity `9643.10` return `-3.56%` tracked_days `5`.
- Live strategy candidate stayed `pullback-support` in the report, and `results\paper_strategy_tournament\live-strategy-selection.json` is now `status=active` for `pullback-support`.
- No paper orders were submitted; both packet files exist on disk; runtime/current run time: `2026-06-04T12:18:44.3976824-05:00`.

## 2026-06-11T09:09:01+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- The ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=326168.56`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260611-090847-556122.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260611-090904-270544.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `catalyst-relative-strength`, then `current-aggressive`; `live_strategy_candidate` remained `candidate` for `pullback-support` with reason `best positive paper strategy after 9 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only with no live authority.
- Runtime/current run time: generated at `2026-06-11T09:09:01+00:00`, completed successfully.

## 2026-06-04T18:11:51+00:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; `results/_context/latest-flags.json` still flagged `paper_tournament` for `candidate_change`, and `results/_context/recent-deltas.md` showed no watched-field changes for the tournament.
- The expected repo console script `.\.venv\Scripts\tradingagents.exe` was not present in this checkout, so I used `.\.venv\Scripts\python.exe -m cli.main` to run the required commands from the repo root.
- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; it stayed paper-only and analysis-only with `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, and `packet_path=results\paper_strategy_tournament\alphainsider-paper-watch-20260604-181117-960369.json`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260604-181155-894500.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10147.55` return `1.47%` tracked_days `5`; `catalyst-relative-strength` equity `9724.23` return `-2.75%` tracked_days `5`; `current-aggressive` equity `9718.63` return `-2.81%` tracked_days `5`.
- Live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 5 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` remained `status=candidate`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`.
- Runtime/current run time: generated at `2026-06-04T18:11:51+00:00`, completed successfully.

## 2026-06-04T19:09:30+00:00

- Refreshed compact context first; `results/_context/latest-flags.json` still flagged `paper_tournament` for `candidate_change`, but `results/_context/recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; it stayed paper-only and analysis-only with `execution_authority=none`, `paper_only=true`, `analysis_only=true`, `fetch_status=blocked`, `strategy_count=0`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=308590.48`, and `packet_path=results\paper_strategy_tournament\alphainsider-paper-watch-20260604-190924-555836.json`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260604-190934-011616.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10142.47` return `1.42%` tracked_days `5`; `catalyst-relative-strength` equity `9744.47` return `-2.55%` tracked_days `5`; `current-aggressive` equity `9703.95` return `-2.96%` tracked_days `5`.
- Live strategy candidate in the run report stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 5 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` exists and still shows `status=active` for `pullback-support`.
- Verified the watch packet, run packet, `latest.json`, and live-selection file all exist locally. No paper orders were submitted.
- Runtime/current run time: generated at `2026-06-04T19:09:30+00:00`, completed successfully.

## 2026-06-04T20:08:57+00:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; `results/_context/recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed before running.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; it stayed paper-only and analysis-only with `execution_authority=none`, `paper_only=true`, `analysis_only=true`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, and `available_shadow_budget_usd=308269.30`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260604-200857-360029.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10142.11` tracked_days `5`; `catalyst-relative-strength` equity `9689.81` tracked_days `5`; `current-aggressive` equity `9668.31` tracked_days `5`.
- The run report kept the live candidate at `candidate` for `pullback-support`, but `results\paper_strategy_tournament\live-strategy-selection.json` shows `status=active`, so the live selection is active for `pullback-support`.
- All expected packet files exist locally; no paper orders were submitted and the AlphaInsider watch remained paper-only.
- Runtime/current run time: generated at `2026-06-04T20:08:57+00:00`, completed successfully.

## 2026-06-04T21:09:29+00:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; `results/_context/latest-flags.json` only flagged `mirofish_handoff_status` for drilldown, and `results/_context/recent-deltas.md` showed no watched-field changes for `paper_tournament`.
- Ledger already existed at `results\paper_strategy_tournament\paper-tournament-ledger.json`, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; it stayed `paper_only=true`, `analysis_only=true`, and `execution_authority=none` with `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=308257.01`, and `packet_path=results\paper_strategy_tournament\alphainsider-paper-watch-20260604-210923-142017.json`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260604-210932-243904.json`, and 3 rankings under `report.rankings`.
- Rankings: `pullback-support` equity `10140.76` return `1.40%` tracked_days `5`; `catalyst-relative-strength` equity `9689.61` return `-3.10%` tracked_days `5`; `current-aggressive` equity `9668.07` return `-3.31%` tracked_days `5`.
- The live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 5 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` exists and remains the active selection file for `pullback-support`.
- Verified the watch packet, run packet, and live-selection file exist locally; no paper orders were submitted.
- Runtime/current run time: generated at `2026-06-04T21:09:29+00:00`, completed successfully.

## 2026-06-06T19:08:40+00:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; `results/_context/recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; it stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, and `packet_path=results\paper_strategy_tournament\alphainsider-paper-watch-20260606-190834-775180.json`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260606-190844-124787.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10011.02` return `0.11%` tracked_days `7`; `catalyst-relative-strength` equity `9162.88` return `-8.37%` tracked_days `7`; `current-aggressive` equity `9099.41` return `-9.00%` tracked_days `7`.
- Live strategy candidate remained `pullback-support` with reason `best positive paper strategy after 7 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` stayed `status=active`.
- Verified `ledger.json`, both packet files, and `live-strategy-selection.json` exist locally; no paper orders were submitted and the AlphaInsider watch remained paper-only.
- Runtime/current run time: generated at `2026-06-06T19:08:40+00:00`, completed successfully.

## 2026-06-06T20:10:03+00:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; `results/_context/recent-deltas.md` again showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Confirmed the paper tournament ledger already existed, so init was skipped.
- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; it stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=328827.89`, and `packet_path=results\paper_strategy_tournament\alphainsider-paper-watch-20260606-200931-845047.json`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260606-201006-887002.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed unchanged in order: `pullback-support` equity `10011.02` return `0.11%` tracked_days `7`; `catalyst-relative-strength` equity `9162.88` return `-8.37%` tracked_days `7`; `current-aggressive` equity `9099.41` return `-9.00%` tracked_days `7`.
- Live strategy candidate stayed `pullback-support` with reason `best positive paper strategy after 7 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` remained present.
- Verified the watch packet, run packet, and live-selection file exist locally; no paper orders were submitted and the AlphaInsider watch remained paper-only.
- Runtime/current run time: generated at `2026-06-06T20:10:03+00:00`, completed successfully.

## 2026-06-06T21:09:25+00:00

- Refreshed compact context again and then ran the paper-only tournament tick from the repo executable directly: `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament` followed by `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`.
- Ledger already existed, so init was skipped.
- AlphaInsider watch stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=328827.89`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260606-210837-303262.json`.
- Tournament run returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260606-210845-029078.json`, and 3 rankings.
- Rankings stayed `pullback-support` first, then `catalyst-relative-strength`, then `current-aggressive`; `live_strategy_candidate` remained `candidate` for `pullback-support`.
- No paper orders submitted, no live candidate change, and no watch status/watchlist change beyond the same blocked AlphaInsider fetch.
- Runtime/current run time: generated at `2026-06-06T21:09:25+00:00`, completed successfully.

## 2026-06-11T01:08:19-05:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results/_context/recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; it stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=325591.81`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260611-060814-295340.json`.
- Ran `alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260611-060822-541368.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10097.41` return `0.97%` tracked_days `9`; `catalyst-relative-strength` equity `9024.08` return `-9.75%` tracked_days `9`; `current-aggressive` equity `8993.04` return `-10.06%` tracked_days `9`.
- Live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 9 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` remained active for `pullback-support`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only.
- Runtime/current run time: generated at `2026-06-11T01:08:19-05:00`, completed successfully.

## 2026-06-11T07:08:38+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, and no raw packet drilldown was needed.
- The repo executable was present, and the tournament ledger already existed, so init was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=325681.36`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260611-070820-618698.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260611-070840-597305.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10097.41` return `0.97%` tracked_days `9`; `catalyst-relative-strength` equity `9024.08` return `-9.75%` tracked_days `9`; `current-aggressive` equity `8993.04` return `-10.06%` tracked_days `9`.
- Live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 9 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` remained active for `pullback-support`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only.
- Runtime/current run time: generated at `2026-06-11T07:08:38+00:00`, completed successfully.

## 2026-06-11T08:09:43+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`.
- The ledger already existed, so init was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=325953.12`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260611-080939-675524.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260611-080946-172788.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `catalyst-relative-strength`, then `current-aggressive`; `live_strategy_candidate` remained `candidate` for `pullback-support` with reason `best positive paper strategy after 9 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only.
- Runtime/current run time: generated at `2026-06-11T08:09:43+00:00`, completed successfully.

## 2026-06-11T10:08:41+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `fetch_status=blocked`, `strategy_count=0`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=326224.69`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260611-100837-292270.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260611-100843-806776.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `9953.29` return `-0.46%` tracked_days `9`; `catalyst-relative-strength` equity `8759.32` return `-12.40%` tracked_days `9`; `current-aggressive` equity `8692.48` return `-13.07%` tracked_days `9`.
- Live strategy candidate stayed `pending` for `pullback-support` with reason `need at least 5 tracked days and a positive winner`; `results\paper_strategy_tournament\live-strategy-selection.json` was not written by this tick.
- No paper orders were submitted, and the AlphaInsider watch remained paper-only with no live authority.
- Runtime/current run time: generated at `2026-06-11T10:08:41+00:00`, completed successfully.

## 2026-06-11T06:10:34-05:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so raw packet drilldown was not needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `fetch_status=blocked`, `strategy_count=0`, `paper_shadow_spend_usd=0.00`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260611-110959-831387.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260611-111006-912436.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed in the same order: `pullback-support`, `catalyst-relative-strength`, `current-aggressive`.
- Live candidate remained `pending` for `pullback-support` with reason `need at least 5 tracked days and a positive winner`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only with no live authority.
- Runtime/current run time: generated at `2026-06-11T06:10:34.0782781-05:00`, completed successfully.

## 2026-06-11T12:07:51+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` still showed no watched-field changes for `paper_tournament`.
- Ledger already existed, so init was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=325935.87`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260611-120744-830442.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260611-120751-555819.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed in the same order: `pullback-support`, `catalyst-relative-strength`, `current-aggressive`.
- Live candidate remained `pending` for `pullback-support` with reason `need at least 5 tracked days and a positive winner`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only with no live authority.
- Runtime/current run time: generated at `2026-06-11T12:07:51+00:00`, completed successfully.

## 2026-06-18T20:10:22-05:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ledger already existed, so init was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327290.56`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-011003-952947.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-011029-002305.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10311.36` return `3.11%` tracked_days `10`; `current-aggressive` equity `8774.94` return `-12.25%` tracked_days `10`; `catalyst-relative-strength` equity `8686.95` return `-13.13%` tracked_days `10`.
- Live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`; `results\paper_strategy_tournament\live-strategy-selection.json` remained active for `pullback-support`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only, analysis-only, and execution-authority none.
- Runtime/current run time: generated at `2026-06-19T01:10:22+00:00`, completed successfully.

## 2026-06-18T21:08:03-05:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- The tournament ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-020729-809263.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-020740-060618.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; no live candidate or watch-status change was observed.
- No paper orders were submitted and the AlphaInsider watch remained paper-only with no live authority.
- Runtime/current run time: generated at `2026-06-18T21:08:03.6120346-05:00`, completed successfully.

## 2026-06-19T03:06:48+00:00

- Refreshed compact context first; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ledger already existed, so init was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-030639-936579.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-030651-122729.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained paper-only, analysis-only, and execution-authority none.
- Runtime/current run time: generated at `2026-06-19T03:06:48+00:00`, completed successfully.

## 2026-06-19T04:07:11+00:00

- Refreshed compact context first; `results/_context/recent-deltas.md` again showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, and `available_shadow_budget_usd=327330.96`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-040711-547176.json`, and 3 ranking rows.
- Live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`; no paper orders were submitted and the AlphaInsider watch remained paper-only.
- Runtime/current run time: generated at `2026-06-19T04:07:11+00:00`, completed successfully.

## 2026-06-19T05:08:43+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so raw packet drilldown was not needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-050834-124815.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-050846-852300.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`.
- Runtime/current run time: generated at `2026-06-19T05:08:43+00:00`, completed successfully.

## 2026-06-19T06:07:41+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so raw packet drilldown was not needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-060735-129207.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-060744-651545.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`.
- Runtime/current run time: generated at `2026-06-19T06:07:41+00:00`, completed successfully.

## 2026-06-19T07:07:48+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-070737-897741.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-070751-037208.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`.
- Runtime/current run time: generated at `2026-06-19T07:07:48+00:00`, completed successfully.

## 2026-06-19T08:07:24Z

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`, which errored because the ambient Python path could not import `tradingagents`; the existing compact context still showed `paper_tournament` with no watched-field changes, so no raw packet drilldown was needed.
- Ran the paper-only tournament tick with `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament` and `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`.
- AlphaInsider watch stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-080705-929862.json`.
- Tournament run returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-080716-728907.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and there was no watch status or watchlist change.
- Runtime/current run time: generated at `2026-06-19T08:07:24.3047865Z`, completed successfully.

## 2026-06-19T09:10:09+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Verified the tournament ledger already existed, so init was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-091000-412237.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-091012-384665.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`.
- Runtime/current run time: generated at `2026-06-19T09:10:09+00:00`, completed successfully.

## 2026-06-19T11:14:12+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-111407-559114.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-111418-276296.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and there was no watch status or watchlist change.
- Runtime/current run time: generated at `2026-06-19T11:14:12+00:00`, completed successfully.

## 2026-06-19T18:12:28+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` still showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- The tournament ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260619-181222-680833.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260619-181237-988316.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 10 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`; there was no watch status or watchlist change.
- Runtime/current run time: generated at `2026-06-19T18:12:28+00:00`, completed successfully.

## 2026-06-20T17:16:36+00:00

- Refreshed compact context with `.\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` again showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- Ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260620-171613-954080.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260620-171642-282762.json`, and 3 ranking rows under `report.rankings`.
- Rankings stayed `pullback-support` first, then `current-aggressive`, then `catalyst-relative-strength`; the live strategy candidate remained `candidate` for `pullback-support` with reason `best positive paper strategy after 11 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`; there was no watch status or watchlist change.
- Runtime/current run time: generated at `2026-06-20T17:16:36+00:00`, completed successfully.

## 2026-06-20T21:12:35+00:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; `results\_context\recent-deltas.md` showed no watched-field changes for `paper_tournament`, so no raw packet drilldown was needed.
- The tournament ledger already existed, so `alpaca paper-tournament init --capital-per-strategy 10000 --json-output --log-dir results/paper_strategy_tournament` was skipped.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament alphainsider-watch --json-output --log-dir results/paper_strategy_tournament`; AlphaInsider stayed `paper_only=true`, `analysis_only=true`, `execution_authority=none`, `strategy_count=0`, `fetch_status=blocked`, `paper_shadow_spend_usd=0.00`, `available_shadow_budget_usd=327330.96`, and wrote `results\paper_strategy_tournament\alphainsider-paper-watch-20260620-211225-786704.json`.
- Ran `.\.venv\Scripts\tradingagents.exe alpaca paper-tournament run --all --json-output --log-dir results/paper_strategy_tournament`; returned `submitted_count=0`, `ledger_path=results\paper_strategy_tournament\paper-tournament-ledger.json`, `live_selection_path=results\paper_strategy_tournament\live-strategy-selection.json`, `packet_path=results\paper_strategy_tournament\paper-tournament-run-20260620-211238-303486.json`, and 3 ranking rows under `report.rankings`.
- Rankings: `pullback-support` equity `10311.36` return `3.11%` tracked_days `11`; `current-aggressive` equity `8774.94` return `-12.25%` tracked_days `11`; `catalyst-relative-strength` equity `8686.95` return `-13.13%` tracked_days `11`.
- Live strategy candidate stayed `candidate` for `pullback-support` with reason `best positive paper strategy after 11 tracked day(s)`.
- No paper orders were submitted and the AlphaInsider watch remained `paper_only=true`, `analysis_only=true`, `execution_authority=none`; there was no watch status or watchlist change.
- Runtime/current run time: generated at `2026-06-20T21:12:35+00:00`, completed successfully.
