# MiroFish Finalization Goal And Checklist

Generated: 2026-06-04

## Outcome Goal

Finalize MiroFish Step 4/5 into the best practical research artifact for tomorrow's TradingAgents advisory workflow, without rerunning Stage 1, Stage 2, or Stage 3 and without touching broker execution.

The accepted final state must:

- preserve the known-good baseline report unless a newer report materially beats it
- improve weak Step 4 sections wherever there is a real quality gain
- keep Zep as canonical graph/memory evidence while using cached/local evidence as labeled support
- run the best supported Step 5/deep-interaction or replay workflow and save the result
- refresh the final review packet
- create a TradingAgents advisory-only handoff that tomorrow's automation/context readers can find
- verify that no broker execution, paper/live order submission, email, or Google Drive update occurred

## Quality Rubric

Step 4 is acceptable only if:

- 20 of 20 required report sections are present
- final prose is English
- `full_report.md` contains no raw tool errors
- `full_report.md` contains no evidence markdown leakage
- `meta.json` and canonical `full_report.md` are not materially stale against each other
- graph-wide safe-mode limits are not misrepresented as an empty graph
- no `0 / 1000 interviewed` result is treated as a successful interview
- replay/deferred interviews are labeled honestly
- section evidence files are present for every section
- diagnostics files are present
- machine-readable summary is present
- Zep graph evidence is used where available
- local fallback evidence is labeled as fallback/supporting evidence
- company/tech-executive coverage is improved if practical
- real-market validation packet is improved if practical
- TradingAgents implications remain advisory research, not trade orders
- console/log output is clean enough that a later reviewer can trust what happened

Step 5 is acceptable only if:

- the repo's real supported Step 5/deep-interaction path is inspected first
- true live interactions are used only if the completed run supports them safely
- otherwise the workflow is clearly labeled replay/deferred/evidence-based
- the seven post-report questions are answered and saved
- limitations are documented without hiding tool failures

TradingAgents handoff is acceptable only if:

- it is advisory-only
- it explicitly prohibits direct trade triggering
- it includes validation tasks, false-signal filters, risk gates, broker/API warnings, macro/options watch items, and provenance
- it is placed where the repo's context/automation readers can find it
- it does not change broker execution code or submit orders

## Execution Checklist

- [ ] Inspect accepted report artifacts and prior quality/audit packets.
- [ ] Rank weak sections and weak tools by evidence, not vibes.
- [ ] Inspect Step 4 and Step 5 code paths before launching anything.
- [ ] Inspect Zep cache/hydration state and avoid graph-wide all-node/all-edge calls in interactive Step 4.
- [ ] Patch only targeted tooling or source artifacts that materially improve quality.
- [ ] Run targeted tests around touched areas.
- [ ] Rerun Step 4 as many safe times as needed to get a materially improved report, preserving `report_44fb26ddc574`.
- [ ] Compare any new report against `report_44fb26ddc574` and accept the stronger report.
- [ ] Run or synthesize the best supported Step 5/deep-interaction workflow and save transcript/output.
- [ ] Refresh final review packet and run packet audit.
- [ ] Create TradingAgents advisory handoff and automation-readable pointer.
- [ ] Run final focused verification and record changed files.

## Hard Boundaries

- Do not rerun Stage 1, Stage 2, or Stage 3.
- Do not start a duplicate Step 4 while another Step 4 job is active.
- Do not overwrite `backend/uploads/reports/report_e22efc97ca64`.
- Do not send email.
- Do not update Google Drive.
- Do not modify broker execution or submit paper/live orders.
