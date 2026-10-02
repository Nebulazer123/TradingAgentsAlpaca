# October 2 continuation: source and data evidence

Implementation began from `d1cd3ee40002660ca4cb116ca69240e7aa376ae5` on
`oai/tradingagents-harness-20261001`. Root owns implementation, verification and
a separate self-review. This record distinguishes completed local capabilities
from source, economic and operational gates that remain open.

## Actual source captures

The owner authorized the prepared Alpaca diagnostic and subsequent in-scope
continuation work on October 2. Existing credentials were used privately, with
no account mutation, order, model or message operation. Two later read-only
paper-account/position GETs supply current portfolio originals for Task 12.
All captures remain in
the ignored private directory
`results/readiness_continuation/20261002-continuation-implementation/`.

The representative diagnostic made 17 GETs and retained every original HTTP
response. All returned HTTP 200 with complete bodies. Five active samples had
the requested 60-session SIP/raw grid; TWTR returned no bars. The bounded SSE
response contained 38,806 emission envelopes. Its original v2 capture-parser
failure at 2,000 events remains preserved. The v3 offline reopener accepts the
bounded original while retaining the original producer failure and version.
No event mutation is applied and this does not certify effective-event coverage.

The v3 population contract was frozen at **09:42:40 UTC** before the separate
discovery collection, with a prospective cutoff of **October 5, 13:00 UTC**
(08:00 Central). Contract SHA-256:
`08c4590ca36cab0dccdeb9f4f5460ded6e76e2aff3bf6e13213fc319c5e78c88`.
The earlier v2 policy receipt and scope lineage remain retained.

The second capture completed at **09:43:47 UTC**. Reopened whole active/inactive
arrays contain **14,387 active + 19,168 inactive = 33,555 records**, with no
snapshot identity conflict. The earlier diagnostic had one more active record;
the two capture times are distinct provider snapshots. Complete discovery means
the two declared current arrays were accounted for, not an atomic historical
market inventory.

Every row is retained with its original array index, artifact/hash, provider UUID
and original symbol. The original-backed accounting receipt records:

| Disposition | Records |
| --- | ---: |
| Source-supported ineligible | 20,356 |
| Unresolved | 13,199 |
| Eligible with all required evidence | 0 |
| Total | 33,555 |

All 407 unsupported directory aliases remain counted, without converting them
to requestable tickers. Names and `us_equity` do not establish common-share class.
The potentially eligible records still need positive class evidence, independent
share-class identities, dated listing/alias coverage and their exact preceding
60-session prices. No top-100/75/50 cohort or economic protocol is admitted.

Accounting SHA-256:
`ed5d8b313dd475ad187280a25129e67d5b955bd0c34bc4e5446ce34c93203294`.
Companion full-row JSONL SHA-256:
`bede136614683db3bd21f8847b7fb4e88a0fe2cb6ced9c2eb8aab3a1f26491b2`.

A separate bounded SEC GET captured `company_tickers_exchange.json`: 10,434
issuer/ticker metadata rows, original SHA-256
`2df6dbed748a66dfbb6ed403e1e88b4d7b5590e61188ea74d5548d0f8aec09c1`.
It supplies issuer metadata only; it does not close any class or dated identity
gap. No source originals or keys are published.

## Current free crosswalk profiles

Three later free requests captured five OpenFIGI mappings and two whole Nasdaq
listing files at **10:57:35–36 UTC**. The current type/profile reopener retains
all **5,633 Nasdaq-listed + 7,661 other-listed = 13,294 rows**. Ten other-listed
rows use exchange codes F/M outside the current published definition table.
The first whole-original replay rejected those codes; its failure remains
retained. The repaired reader preserves the rows and explicit unmapped venue
gaps. The publisher's footer wall clock remains without an assigned time zone.

The observed OpenFIGI label pairs normalize AAPL/GOOG/GOOGL to common stock and
TSM to ADR. SPY's broad ETP/Mutual Fund pair remains unknown. GOOG and GOOGL have
distinct returned share-class FIGIs. The five normalized type assertions reopen
both the original outgoing request and complete response. Their dates remain
null and their internal subjects have no reviewed crosswalk. No source facts
were silently copied into the frozen Alpaca v3 population accounting.

[Source-profile rules](../../data/SECURITY_SOURCE_PROFILES.md) describe the new
explicit normalization parser and unchanged direct-parser replay. Originals,
profiles and assertions are private under `free-crosswalk-original-replay-v2/`.
Population-wide classifications/prices, dated listing/alias/class relationships
and effective-event coverage remain open. A future cohort using these extra
families requires a prospectively frozen policy; the existing v3 policy is not
backdated or expanded.

## Additive source capabilities

- `security_master/v2` reopens original JSON fields, keeps issuer, security,
  listing, alias, external identifier and event subjects distinct, verifies
  assertion clocks and append-only corrections, and leaves unknown/conflicting
  facts visible. Existing v1 parsing and replay are unchanged.
- The frozen population contract, discovery reopener and exhaustive accounting
  rederive complete arrays, every row and all counts. Altered flags, missing rows,
  tampered originals and late custody fail. Discovery, identity, price and event
  coverage remain independent.
- Original action pages and consideration prices are reopened by hash and exact
  request/page scope. Covered cash, successor shares, mixed mergers, splits and
  distributions use exact rational quantities and raw prices. Entry ex-date
  entitlement is not added again. Unknown currency, missing legs and ambiguous
  same-session ordering remain unavailable. A name change's processing date is
  never invented as its effective date or economic termination.
- `source_bound_execution_outcome/v2` permits an all-cash event without fabricated
  post-termination bars. Its current provider profiles still lack complete
  effective-event, dated identity, certified official-open price and required
  payment/delivery coverage, so
  `gross_return` stays null. Tournament admission reopens the originals; the
  result path retains unavailable references and null metrics. V1 canonical
  replay remains supported and does not supply the missing coverage proof.
  A provider daily `o` is labelled as a conditional daily-open price, not proof
  of an execution at the official session-open clock.
- The actual sampled AAPL action response reopened successfully but omitted
  currency for its cash-dividend record. Its normalized terms remain unavailable;
  USD is not guessed. A terminal REST page proves only the returned processing
  scope, never absence of effective events.
- Strict normal-trade intent reload now compares exact types and values. A real
  JSON round trip passes while altered, partial and numeric boolean lookalikes
  reject. No execution or submission authority changes.

## Subscription qualification registration

New `research_qualification_registration/v7` records dispatch explicitly to the
Codex subscription route. Historical v4/v5/v6 and OpenRouter replay remain
available. The frozen v7 migration retains all 1,400 v6 case/gold bytes exactly,
with case SHA-256
`fa50e7f64f0c3b2157d59fba7bf4a50194fd8e78aa601cd1287bd117b6388498`.
Registration SHA-256:
`ef2e9adfc06f7502d41c805aaef0c1e9a3878d9652a5c1e87c27ceb664dbf790`.

It records installed CLI 0.159.3, explicit requested models/effort and runner
limits. The CLI does not return serving-model/revision identity or subscription
allocation cost; those values stay unknown. Missing or repeated execution IDs,
invalid telemetry, changed runners and sensitive inputs reject qualification.
Source bundles remain equal across lanes and gold remains outside model input.
The original zero budgets are retained. No model or 1,400-case rerun occurred.
The full-graph supplemental registration is written after source freeze under
`results/readiness_continuation/20261002-continuation-implementation/codex-full-graph-registration-v2-final/`,
binding the final clean revision and unchanged dependency lock. It grants no
model execution authority.

## Learning and current readiness

All 6,244 original ledger rows and the byte-exact backup retain SHA-256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`.
The exhaustive audit finds 4,944 stored resolved labels and 1,300 pending labels,
but **zero verified economic bindings**; all 6,244 remain economically unresolved.
Original resolved quality labels are retained: 132 suspect, 80 degraded and
4,732 high. Missing prediction/packet/window/security/price/action bindings are
recorded for every row. Read-only reconciliation reproduces the same state;
it is not an accepted economic fixed point. No ledger rewrite, fabricated
resolution, availability event or accepted summary refresh was produced.

The fresh readiness packet at **10:02:30 UTC** says `NOT_ESTABLISHED`, profitability
unestablished, ten paused jobs and no submission authority. It reopens current
contracts/TOMLs and the retained promotion supersession. An initial attempt using
the older schedule digest failed and is preserved; the successor binds current
bytes. Two additional paper GETs completed at **10:40:58 UTC**, retaining
whole account/position originals. They show 14 paper positions including TSM.
The source-bound fact review records provider values and their capture clock;
it lacks the original decision/loss reason and a returned quote clock. It is
not a qualifying TSM or BOARD review. No runtime transition occurred.

## Check scope and remaining gates

Focused evidence includes 178 population/master/probe/raw-archive checks before
the later parser migration; 235 integrated benchmark/source/media/client checks;
35 strict intent checks; 144 latest probe/population checks; 81 action/outcome/
population checks; and the additional original-leg tournament admission checks.
These groups overlap and must not be added into a unique suite count. Mocked
model responses and synthetic calendars establish source behavior only.
The first continuation candidate `ced5545` passed six static checks, then its
full suite was deliberately interrupted at the source-profile integration
boundary. Its durable exit 130 and withdrawal reason remain retained; it is not
an accepted candidate. The additional 124 profile/master/archive/population
checks passed after the original-backed normalization repair.
Failed attempts remain retained. At this pre-freeze checkpoint the final complete
integrated source gate has not yet run. The subsequent candidate-bound receipt
under `results/readiness_continuation/20261002-continuation-implementation/source-gate-final-v2/`
owns final source acceptance; only its recorded completed successful exits
establish a passing gate.

Remaining acceptance includes qualified identity/source profiles and every
potentially rank-changing candidate, complete pricing and pre-decision event
coverage, the exact prospective cohort/partitions/protocol, genuine phase
outcomes, legitimate historical learning bindings, fresh portfolio/BOARD inputs,
the separate holdout release, candidate-bound source acceptance and six distinct real
market sessions in the existing twelve-stage order/reset rules. Scheduler-returned
next runs in Central/UTC and no-submit shadow equivalence remain deployment
prerequisites. All ten jobs stay paused, concurrency stays one, paper submission
stays off and live control stays frozen.
