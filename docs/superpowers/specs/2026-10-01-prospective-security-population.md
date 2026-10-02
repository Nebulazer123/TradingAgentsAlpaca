# Prospective security population contract

Policy version `prospective_security_population/v3`, specified October 2, 2026.
The immutable machine-readable receipt was frozen at 09:42:40 UTC before the
separate complete directory capture. Its cutoff is October 5, 13:00 UTC
(08:00 Central), and its hash is
`08c4590ca36cab0dccdeb9f4f5460ded6e76e2aff3bf6e13213fc319c5e78c88`.
V3 retains unsupported directory aliases as original records; the earlier v2
receipt and parser profile remain replayable under their own policy.
A missed cutoff requires a new campaign version, preserving the prior receipt.
The receipt does not backdate historical custody or admit a cohort.

## Declared population

The discovery population consists of every row in the explicit active and
inactive Alpaca Trading API `us_equity` snapshots. The eligible population is the
subset positively established as U.S.-listed, Alpaca-tradable common/ordinary
share classes at the cutoff, with complete source-supported identity and pricing.
Separate share classes are separate securities; a ticker is not the population
key. Common REIT and SPAC shares can qualify when their class is positively
proved. Foreign ordinary shares can qualify on the same basis; issuer domicile
alone does not decide eligibility.

Exclude positively identified preferred shares, ETFs/ETNs/funds, ADR/depositary
receipts, warrants, rights, units, test instruments and OTC listings. A class
that cannot be positively distinguished remains unresolved, with its exact source
gap. Never classify by company-name text or by absence of an ETF keyword.
Inactive/delisted listings are retained and accounted for but ineligible for new
selection. Their listing/identity and outcome-coverage gaps remain independent.

## Frozen source families and coverage units

| Dimension | Required declared scope |
| --- | --- |
| Discovery | Active and inactive `GET /v2/assets?asset_class=us_equity` on the paper host, captured as whole original responses. These are two explicit source partitions, not all historical U.S. securities. |
| Identity/type/aliases | Source-bound Alpaca identifiers plus original issuer/exchange/SEC assertions covering each potentially eligible listing/share class and the ranking interval. SEC CIK is an issuer identifier. Current SEC ticker metadata alone cannot establish dated class/alias intervals. Each record/interval gap stays unresolved. |
| Calendar | Alpaca calendar with `date_type=TRADING`, inclusive dates and actual session times. Bind exactly the prior 60 completed market sessions; no synthetic weekday calendar. |
| Prices | Consolidated SIP, USD, raw provider daily bars over the exact preceding 60 sessions, explicit `asof` and sort. No IEX fallback. Retain actual single- or multi-symbol upstream pages and every continuation. |
| Events/consideration | REST processing-date records plus separately scoped emission replay/issuer action originals as required. Coverage and absent-event proof are independent of price/discovery completion. Terminal cash/security legs require their own originals. |

Each campaign names exact requests, intervals, symbols/partitions, page limits,
parser/source profiles and original artifact IDs. Budgets cannot silently omit
partitions: an exhausted limit is incomplete. Every page must carry the upstream
continuation field or the source profile's independently qualified terminal
rule. Multi-symbol responses are sorted/paged globally by the provider; retain
the whole response rather than manufacturing per-symbol HTTP originals.
Representative access tests precede full capture and have no population claim.

## Cutoff and selection

Before full capture, freeze the campaign ID, UTC decision cutoff, the contract's
canonical hash, required source partitions, ranking interval and session basis.
All admitted facts must be in trusted local custody by that cutoff. Source
effective/publication dates cannot replace capture/archive clocks. The campaign
must be future-facing at issue time; forecasts and outcomes come after cohort
freeze. Later source corrections create new versions.

Preserve the established policy exactly:

1. Prior completed close must be at least USD 5.
2. Require all 60 prior complete sessions, retaining explicit zero volume and
   rejecting missing, duplicate or unexpected sessions. Do not impute missing
   volume or close.
3. Rank by the exact median of daily close times volume using the established
   integer-coefficient decimal arithmetic and existing deterministic tie break.
   The day basis is Alpaca provider daily; no unsupported regular-session-only
   assertion is added.
4. Produce one global ordered top 100 across all declared source partitions.
   Primary 75 and sensitivity 50 are its literal ordered prefixes. Keep the
   configured benchmark separate unless its security independently qualifies.
5. Partitioned input must reproduce the identical global ranking. A 512-row
   parser limit or the earlier 43-symbol detailed capture does not define this
   declared population.

## Complete accounting and unavailable evidence

Every discovered source record appears exactly once in the accounting receipt,
bound to its original page/path. Its disposition is eligible, ineligible or
unresolved with source-supported reasons. Record source conflicts, reused ticker
ambiguity, missing class/interval claims, stale/late custody, missing prices and
unsupported consideration separately. Common-share identity can qualify while
future outcome consideration is still pending; future proceeds are not required
to register a prospective protocol, but originals-verifier capability is.

Any unresolved candidate capable of changing the ranking prevents an unqualified
global top-100 claim. Known policy exclusions can be counted without prices when
their exclusion is source-backed. Completion counts must reconcile to discovery
originals and page/partition inventories. The coverage receipt distinguishes
discovery, identity/alias, price and event/proceeds states rather than reducing
them to one success boolean.

No provider request, credential access, paid/signup operation, model call,
holdout release or schedule/control change is authorized by this contract.
Actual source collection requires the then-current exact endpoint, interval,
volume, storage/use and owner authorization. Pending access leaves a precise
incomplete gate while independent source work continues.

## Captured discovery and current accounting

The October 2 capture reopened 14,387 active and 19,168 inactive original rows.
The exhaustive receipt retains all 33,555 rows, including 407 unsupported aliases:
20,356 have source-supported exclusions and 13,199 are unresolved. Eligible count
is zero until the required class, relationship, dated identity and price evidence
exist. Whole-array completion is distinct from identity, price and event coverage.
The separately captured 10,434-row SEC ticker/exchange file supports issuer
metadata only. [Current evidence and hashes](../checkpoints/2026-10-02-continuation-source-and-data.md)
record these captures; no ranking or prospective protocol is admitted.
