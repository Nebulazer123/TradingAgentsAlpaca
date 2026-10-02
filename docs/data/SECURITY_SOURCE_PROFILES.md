# Current security source profiles

`tradingagents/dataflows/pit/security_source_profiles.py` reopens current metadata
from whole originals in the PIT archive. Profiles remain independent of reviewed
entity relationships, dated coverage, population eligibility and cohort admission.

## OpenFIGI mapping

The [official mapping documentation](https://www.openfigi.com/api/documentation)
describes returned instrument and share-class identifiers. The profile supports
the actual unauthenticated five-job response shape, with explicit US equity
`TICKER` jobs. It reopens outgoing request bytes and every response slot, rejects
wrong scope, duplicate FIGIs or ambiguous assertion selection, and retains error
and warning replies as unavailable.

Only these observed label pairs have a normalized classification:

| `securityType` / `securityType2` | Normalized observation |
| --- | --- |
| Common Stock / Common Stock | `common_stock` |
| ADR / Depositary Receipt | `adr` |
| Other, inconsistent or missing pairs | `unknown` |

ETP / Mutual Fund remains unknown. Multiple hits remain ambiguous. A profile
does not join a provider asset UUID to a FIGI or supply an effective interval.

`security_master/v2` assertions can explicitly use
`source_profile_normalization` and parser `security_master_openfigi_label_pair/v1`.
Their original response path and exact request/profile binding are required.
Both originals and the normalized pair are reopened at verification. Missing
dates stay null, so these assertions cannot satisfy dated cohort coverage.
The existing direct JSON parser and canonical records retain their original bytes.

## Nasdaq directories

The [publisher definitions](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)
describe current listing files, explicit ETF/test flags and their generation
footer. The profile accepts the actual `nasdaqlisted.txt` and `otherlisted.txt`
layouts, retaining every row, its original symbol namespace and field values.
It keeps generation time as a wall clock with unknown zone. Names do not supply
common-share classification. Undocumented exchange codes remain visible with
an explicit field gap.

The raw archive now accepts `text/plain` originals for these profiles. A plain
text original grants no eligibility or execution authority.

## October 2 diagnostic scope

Three authorized free requests retained five OpenFIGI jobs and two Nasdaq files.
Whole-original replay produced five current type observations and retained
5,633 Nasdaq-listed plus 7,661 other-listed rows. GOOG and GOOGL have distinct
returned share-class FIGIs. Ten rows use exchange codes outside the current
published table; their codes remain unchanged and unassigned to a venue.

Originals, profiles, assertions and the first failed replay are private under
`results/readiness_continuation/20261002-continuation-implementation/`.
No reviewed crosswalk or cohort was created. The frozen Alpaca v3 campaign and
its 33,555 dispositions are unchanged. Using these additional families for a
future cohort requires a prospectively frozen policy and qualified relationships,
dated listing/alias/class intervals, population pricing and event coverage.
