# Combined TradingAgents source acceptance — October 1, 2026

The final combined source candidate is
`85fe50d251e3d64fe25768b54c0ff3ecf3c3c01f`. It includes the preserved schedule
and dry-run repairs, decimal/shared-page fixes, v6 original-file and semantic
readers, durable verifier, and completed harness modernization. Root integrated
and verified it, with a separate self-review recorded under
`results/readiness_continuation/20261001-combined-source-integration/self-review.md`.
That review is not independent agent review.

The single detached source gate started at
`2026-10-01T10:11:17.295503+00:00` and finished **passed**, exit 0, at
`2026-10-01T11:55:39.937144+00:00`. The source stayed unchanged. Both the
canonical checkout and isolated continuation were clean at the tested candidate
when the terminal result was collected. The exact worker and Pytest processes
had exited; no replacement run was started.

- Pytest: **5,183 tests and 78 subtests passed**, one skipped live DeepSeek API
  test, 11 warnings, 6,260.52 seconds. JUnit records 5,262 test entries,
  including subtests, with zero failures/errors and one skip.
- Ruff, compileall, offline lock check, wrapper syntax, retired-installer syntax,
  and diff checks all exited 0.
- Durable terminal receipt, logs and JUnit:
  `results/readiness_continuation/20261001-combined-final-source-gate/`.
  File-backed results survived client output disconnection.
- Unchanged 81-test assertion repair, 159-test v6 group and 612-test harness
  results were reused. Earlier `-9`/broken-pipe, failed gates and intermediate
  receipts remain preserved at their original owners.

The post-test protection check matched the accepted post-migration baseline:
all ten automation records were unchanged and paused; the four frozen
handoff/ledger/live-control/promotion files and four benchmark readers matched.
The schedule contract remained unchanged. The original baseline and authorized
harness-migration successor remain retained. Verification is recorded in
`results/readiness_continuation/20261001-combined-final-source-gate/post-source-gate-protection.json`.
This check changed no external automation, protected control or evidence owner.

The checked 1,400-case v6 local qualification remains accepted within its typed
scope: deterministic critical/high/source accuracy is 100%; retrieval is
293/1,400 (20.9%) and does not qualify. Its original sources, labels, model
limitations and failed/intermediate attempts remain retained. Selecting this
bounded deterministic lane does not establish a no-model verdict.

**Readiness remains NOT_ESTABLISHED.** Dated stock identities and the ranked
100/75/50 universe, legitimate legacy prediction/outcome links, prospective
development/validation and separately released holdout, fresh TSM/BOARD
evidence, eligible model/concurrency comparisons and one qualifier plus five
additional real clean sessions remain incomplete. Both handoffs remain
available. The walkthrough and seven-future-eligible/three-paused launch card
grant no activation authority. Live control stays frozen, concurrency stays 1,
and paper submission stays off.

The status-document updates that record this result are prose changes after the
tested candidate. They receive readback, link and diff review; they change no
application, test, dependency, policy or schedule source and require no repeat
of this unchanged source gate.
