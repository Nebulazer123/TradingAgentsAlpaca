# TradingAgents launch preparation

This card describes the intended observer deployment and the saved model/prompt
configuration. Activation has its separate acceptance and owner scope.
Operational state comes from the scheduler and current runtime evidence.

## Saved role models — October 1, 2026

The harness modernization applied these Codex assignments and source prompts.
The versioned schedule contract binds the actual records; its timetable,
deployment phases, dependencies and no-submit fields retain their existing scope.

| Job | Intended observer phase | Saved Codex model / effort |
| --- | --- | --- |
| Overnight research | Eligible after gates; one capped ticker initially | GPT-6.1 Sol / high |
| Preopen checks | Eligible after gates; dry-run | GPT-6 Luna / medium |
| Safety sentinel | Eligible after gates; verification | GPT-6 Luna / medium |
| Self-healer | Eligible after gates; bounded recovery | GPT-6.1 Sol / high |
| Execution BOARD | Eligible after gates; analysis only | GPT-6.1 Sol / high |
| Paper tournament | Eligible after gates; dry-run | GPT-6 Luna / medium |
| Daily report | Eligible after gates; local queue | GPT-6 Luna / medium |
| Market supervisor | Ineligible in observer phase | GPT-6.1 Sol / high |
| Wake controller | Ineligible in observer phase | GPT-6 Luna / medium |
| Sleep controller | Ineligible in observer phase | GPT-6 Luna / medium |

Sol handles complex synthesis and recovery; Luna handles bounded repetitive
inspection and reporting. Astra is available as a bounded escalation/reviewer
choice, with no extra always-running job. See
[current model guidance](https://developers.openai.com/api/docs/guides/model-selection).
These are workload choices supported by published capabilities, not a measured
claim that a paid model improves forecasts.

The internal application graph has separate versioned OpenAI defaults:
`gpt-6.1-sol` for deep reasoning and `gpt-6-luna` for quick roles. Explicit provider
and model environment overrides still win. Native OpenAI uses Responses API
for tool calling; local tests verify configuration and dispatch without a remote
model call. Published API IDs/context and the local Codex availability cache
are distinct evidence; API account access and remote execution remain unverified.

## Planning and activation

The seven observer jobs have 23 invocations on an ordinary market weekday in the
existing timetable. That count does not predict runtime or cost. Use the current
[published API prices](https://developers.openai.com/api/docs/pricing) and the
specific experiment's verified rate card before budgeting execution. Model-token
costs, caching, retries and hosted tools need their actual accounting; Codex
subscription usage is separate.

The operational campaign requires one qualifier and five additional real clean
market sessions, in the existing twelve-stage order with reset rules. Even with
no failure, that spans more than one calendar week. Economic acceptance uses the
actual prospectively registered outcome windows.

Finish the remaining research qualification, legitimate cohort and prospective
study, prediction reconciliation, current readiness evidence, final source gate
and six-session campaign. Then use the existing no-submit shadow-equivalence
and artifact-health checks. API-returned next runs in Central and UTC remain a
separate deployment requirement; calculated times do not replace that proof.

Historical launch preparation remains under
`results/readiness_continuation/20260930-launch-preparation/`. Its old proposed
model/prompt values were superseded by the harness refresh; its earlier readback
and limitations remain historical evidence. See [current progress](CURRENT_STATUS.md),
[the completion contract](COMPLETION_CONTRACT.md), and
[the modernization report](../harness/2026-10-01-modernization.md).
