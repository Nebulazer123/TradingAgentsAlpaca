# Read-only Alpaca and SEC source checkpoint — 2026-09-14

## Result and scope

The authorized collection is complete with explicit source gaps. Offline verification
passed for **298 retained GET responses, 297 standard raw archive objects, 81 SEC
filings and 43 exploratory adjusted-price windows**. The production source candidate
was unchanged at documentation follow-up `1c9ff9fb3045ad9c4acf0be6d1705e0b9ee017b8`
through collection and verification. This report is documentation, not a new source
qualification gate.

The user's “You can do whatever you want” answered the pending request for free SEC
filings and additional read-only Alpaca universe data. That collection permission
is now satisfied; the earlier unanswered-permission blocker is superseded. It did
not lift the existing trading, model, holdout, scheduling, privacy or preservation
boundaries. No new standing polling or external publication is configured.

## Collected inputs

- Active Alpaca `us_equity` asset discovery: **14,263 records**, including records
  that are not eligible common-stock cohort members. Listing presence is not
  security-type or historical effective-identity proof.
- Calendar discovery plus the exact **61-session** response needed to identify
  **60 preceding sessions, June 17–September 11**, for the September 14 candidate
  selection date. This date is discovery metadata, not a frozen experiment.
- SEC ticker mapping and submissions for the **42 existing ledger tickers**;
  **41 successful company-facts responses** and **81 annual/interim documents**.
  This is a real document seed set, not the accepted 500/300/400/200 benchmark.
- Exact single-symbol Alpaca asset reads plus raw and `adjustment=all` SIP bars
  for those 42 tickers and the existing SPY benchmark: **129 HTTP 200 responses**,
  **2,580 raw and 2,580 adjusted daily bars**, all **86 price responses** matching
  the exact 60-session calendar with complete, unpaginated REST bodies.
- **43 source-bound adjusted-price windows**, derived and reopened through the
  accepted production builder/validator with actual current cutoff
  `2026-09-14T05:53:10+00:00`. Requested dates are June 17–September 13; actual
  first/last sessions are June 17/September 11. Current single-asset IDs bind these
  exploratory derivatives; no historical identity continuity is asserted.

The SEC endpoints and contact/rate practices follow the
[official EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [developer access guidance](https://www.sec.gov/about/developer-resources).
Alpaca routes follow its [asset documentation](https://docs.alpaca.markets/us/docs/working-with-assets)
and [single-symbol historical bars contract](https://docs.alpaca.markets/us/reference/stockbarsingle-1).
Actual retained bytes, not documentation examples or normalized SDK output, are
the evidence used here.

## Exact evidence owners

All paths below are relative to the canonical repository
`/Users/corbinfloyd/Documents/TradingAgents`. Generated data remains private and
ignored; no raw filing/account data or credentials were added to Git.

| Owner | Result | SHA-256 of manifest/receipt |
| --- | --- | --- |
| `results/prospective_source_capture/20260914T053450368366Z/manifest.json` | 109 successful responses; safely capped partial run | `7c9b4ab8a34f22f82fb943cf050657834f2062c79096ca94078678d781f9f77c` |
| `results/prospective_source_capture/20260914T054621723040Z/manifest.json` | Missing-only continuation: 60 new responses, 109 originals reused, 81 total filings | `2de374d3aae527f0940d782a023db946c9a4e9a13824aacc70b0b49973c422e7` |
| `results/prospective_alpaca_symbols/20260914T054956898095Z/manifest.json` | 129 successful single-symbol responses, no gaps | `05ea383a73e5ca1b919d31bb72c03620be7b1efacd27d0091d1a163e5c9448fc` |
| `results/prospective_source_verification/20260914T055310824698Z/verification.json` | Offline integrity/custody/grid verification and derivative identities | `0c062ea4a03a6a07a1a29a236e32e4e3228d165fd4dc28bec7d7336a20899f03` |

The final directory also contains `exploratory_adjusted_windows/` and its 43
canonical receipts. Verification rechecked all response hashes/lengths, matching
sidecars, raw archive receipts/bytes, source URIs, non-backdated retrieval/archive
times, 1,194 private capture files, exact request uniqueness and all calendar
grids. Total retained response entity bytes: **445,682,498**. The 404 body is kept
as an access result but is not admitted as usable raw source evidence.

The initial run stopped while reading the next company-facts response at its
300 MiB aggregate cap, after retaining 311,668,748 bytes. Its exit 1 and partial
manifest remain unchanged. The continuation verified and reused all 109 retained
responses, fetched only missing URLs, and exited 0. Thus 298 is the count of
retained responses, not a claim that the cap-aborted HTTP attempt never happened.
The market capture and offline verifier also exited 0. All four processes are
terminal; do not replay them or poll their closed handles.

## Explicit gaps and non-claims

- QQQ company facts returned HTTP 404; its inspected submissions index contained
  no requested annual/interim forms. No alternate host/access bypass was tried.
- The current XOM map/submissions identify **ExxonMobil Holdings Corp**, CIK
  `0002115436`, with an August 3 10-Q but no annual form or older submissions file
  in this response. An annual report from a different entity was not silently
  substituted. This is also a concrete reason not to infer historical identity
  continuity from today's ticker.
- Current documents were captured on September 14. They do not establish custody
  before earlier forecast/feature cutoffs. Newly derived windows use a current
  cutoff and are not exact legacy forecast/outcome mappings.
- The accepted cohort contract still requires a real effective-dated
  `security_master/v1` source in addition to each Alpaca asset. The configured
  `security-master.tradingagents.local` profile is not an official Alpaca endpoint
  or a license to fabricate `effective_from`, `effective_to` or common-stock
  classification. No legitimate producer/history was established in this intake.
- A 43-symbol ledger/benchmark seed set is not a ranked eligible 100/75/50 cohort.
  No cohort/protocol/partition admission, historical qualification, corporate-action
  completeness, terminal-proceeds proof, forecast reconciliation, real benchmark
  verdict, economic outcome, operational qualifier or five-day trial is claimed.

Next dependent evidence work starts with legitimate effective-dated identity
provenance and a specified eligible candidate pool, followed by the original
ordered admission gates. The SEC seed documents can support later independently
checked benchmark labels; merely counting documents or generated questions cannot
satisfy that benchmark. Do not reopen the closed broad archive search or replace
the real learning ledger to bypass these requirements.

## Verification and preserved posture

Ignored bounded helpers are beside the existing SDD `progress.md`:
`prospective_source_capture_20260914.py`, `prospective_source_resume_20260914.py`,
`alpaca_single_symbol_capture_20260914.py`, and
`prospective_source_verify_20260914.py`. Scoped Ruff passed. Offline capture
self-checks passed for exact route allowlists, disabled redirects, credential
separation, missing-only reuse, drift/duplicate rejection and zero real network
requests. The final verifier ran with sockets disabled and used actual retained
inputs. This is solo implementation and self-review, not independent review.

Before/after checks confirmed **four protected owner hashes**, **ten byte-identical
PAUSED automation configurations**, **24 original Alpaca response hashes** and
the **original Phase 5 ZIP**. The original ledger, promotion state and frozen live
control were not changed. Both handoffs and existing worktrees remain preserved.
No model, trade, cancellation, holdout release, schedule, outbox, live rearm or
cleanup operation occurred.

The executing-plans workflow kept this slice within the approved plan and reused
the accepted **5,005-test/75-subtest source gate**; no broad gate was restarted for
data collection or this documentation-only checkpoint. Full readiness and the
original goal remain incomplete; profitability remains **NOT_ESTABLISHED**.
