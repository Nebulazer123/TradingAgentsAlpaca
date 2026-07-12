# Automation Catalog

All 14 Codex automations were set to `PAUSED` before transfer. Their original prompts, schedules, models, and memory files are preserved in `automation-snapshots`.

## Market and research jobs

- `hourly-market-supervisor`: hourly live/paper supervisor tick; depends on compact context, Alpaca checks, dry-run/live gate, premarket briefs, and risk controls.
- `paper-strategy-tournament-runner`: paper-only tournament tick; depends on the tournament ledger, AlphaInsider watch, and paper packets.
- `market-supervisor-15-min-before-open`: preopen validation and supervisor; depends on fresh quotes/news, premarket brief, preopen validation, and the live gate.
- `market-supervisor-30-min-after-open`: first post-open supervisor; depends on Alpaca check, supervisor dry-run, and current premarket context.
- `market-supervisor-30-min-before-close`: close-prep supervisor; depends on Alpaca check, dry-run/live gate, positions, orders, and risk envelope.
- `market-supervisor-15-min-after-close`: after-close fills, rejections, P/L, and daily-report inputs.
- `tradingagents-daily-market-report`: daily report/email; depends on agent-ledger summary, supervisor packets, and the configured email destination.
- `tradingagents-overnight-planning`: bounded analysis-only overnight research; depends on source quality, provider bundles, agent ledger, overnight planning, and premarket brief.
- `fetch-tradingagents-deep-research-report`: one-off Deep Research export heartbeat tied to the current thread.

## Control and health jobs

- `tradingagents-automation-sleep-controller`: postmarket status controller and overnight handoff.
- `tradingagents-automation-wake-controller`: morning status controller and market-day gate.
- `tradingagents-wake-verification`: verifies wake-controller results and market-day statuses.
- `tradingagents-night-shift-supervisor`: overnight patrol for stale context, gaps, and follow-up routing.
- `tradingagents-self-heal-monitor`: compact self-heal handoff, safe-plan, and automation-health loop.

## Pause boundary

The separate Windows `Job Profile OS Daily Check` task is disabled. Codex Remote Control, WSL SSH, Taskbar AutoHide, Office, Windows, and PowerToys infrastructure were left running because they are host services rather than token-consuming project automations.
