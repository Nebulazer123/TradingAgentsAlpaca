# TradingAgents launch preparation

The first intended deployment is the existing frozen observer phase: collect
research, make clearly labeled forecasts, check the system, and report results.
Trading remains frozen and paper orders stay off. This card is prepared for
review; no schedule or model setting has been changed.

The owner has no additional files to supply. Root owns finding public source
documents, tracing saved predictions, and preparing the run. Estimates may guide
planning and new forecasts. They do not establish historical results, document
accuracy, or trading readiness.

## Jobs and proposed model refresh

| Job | Intended observer phase | Current Codex model | Proposed Codex model |
| --- | --- | --- | --- |
| Overnight research | Eligible after gates; one capped ticker initially | GPT-5.6 Terra | GPT-6.1 Sol, high |
| Preopen checks | Eligible after gates; dry-run | GPT-5.6 Luna | GPT-6 Luna, medium |
| Safety sentinel | Eligible after gates; verification | GPT-5.6 Luna | GPT-6 Luna, medium |
| Self-healer | Eligible after gates; handoff and plan only | GPT-5.6 Terra | GPT-6.1 Sol, high |
| Execution BOARD | Eligible after gates; analysis only | GPT-5.6 Terra | GPT-6.1 Sol, high |
| Paper tournament | Eligible after gates; dry-run | GPT-5.6 Terra | GPT-6 Luna, medium |
| Daily report | Eligible after gates; local report | GPT-5.6 Luna | GPT-6 Luna, medium |
| Market supervisor | Remain paused | GPT-5.6 Terra | GPT-6.1 Sol, high |
| Wake controller | Remain paused | GPT-5.6 Luna | GPT-6 Luna, medium |
| Sleep controller | Remain paused | GPT-5.6 Luna | GPT-6 Luna, medium |

These are proposed assignments, pending the required checks. Current OpenAI
guidance recommends Sol for complex work with cost constraints and Luna for
frequent, focused tasks. Astra is a possible bounded reviewer for an unresolved
research question; it is not an always-on extra job. See the
[current model guidance](https://developers.openai.com/api/docs/guides/model-selection).

Codex runs these scheduled jobs. TradingAgents has separate provider/model
settings for its internal research graph; its versioned defaults remain
`gpt-5.4` and `gpt-5.4-mini`. Changing a Codex job's model does not change those
graph models. A graph-model refresh must check its actual provider, API/tool
compatibility, fixed identity, telemetry, privacy and qualification before use.

The current schedule has 23 invocations per ordinary market weekday for the
seven observer jobs. This is a timetable count, not a promise of runtime or cost.
Market holidays still require the existing calendar check.

## Planning estimates

For illustration, assume one internal research API call uses 20,000 input tokens
and 4,000 output tokens, with no cache discount or paid tools. At the
[published standard API prices](https://developers.openai.com/api/docs/models/compare),
that is approximately $0.004 with Luna, $0.08 with Sol, or $0.40 with Astra.
Twelve such calls would be approximately $0.048, $0.96, or $4.80. These are
planning estimates. Real source size, reasoning output, retries and tool calls
can change them. Codex subscription usage is separate. No paid run or spending
authorization follows from these figures.

The operational campaign needs six distinct clean market sessions after the
source freeze and its prerequisites: one qualifier and five additional sessions.
Even with no failure, that takes more than one calendar week. Economic results
need the actual prospectively registered outcome windows; their completion date
cannot be promised before that protocol exists.

## Checks before activation

The existing acceptance requirements remain in force. Finish the real document
corpus and qualification, legitimate stock selection and prospective study,
prediction reconciliation, current readiness supersession, final source gate,
and the six-session campaign. Then use the existing no-submit shadow-equivalence
and artifact-health checks. Missing model comparison evidence remains missing;
it does not prove the best stack uses no models.

Readback on September 30, 2026 found all ten actual automation files paused and
matching all recorded contract fields, including their prompt hashes. Protected
evidence is saved under
`results/readiness_continuation/20260930-launch-preparation/`:

- `activation-card-evidence.json`: current hashes, exact contract comparisons,
  seven future eligible roles and three roles that remain paused.
- `proposed-automation-updates.json`: exact prepared prompt/model updates, each
  still marked PAUSED and not applied.

The read-only automation API rendered a card but returned no next-run metadata.
API-returned next runs in Central time and UTC therefore remain unavailable.
Calculated times must not be substituted for this deployment proof.

The [day/night/weekend walkthrough](../orchestration/day-night-weekend-walkthrough.md)
describes the cadence. Current economic and trading readiness remain
unestablished. Actual activation requires the separate owner decision against
the checked card; this file grants none.
