# Source-backed security master v2

Implementation specification adopted October 2, 2026 from the reviewed October 1
packet. This is an additive evidence contract. It grants no source access, model,
cohort, economic, or trading authority.

## Owners and coexistence

`tradingagents/dataflows/pit/security_master.py` owns the new assertion and
reconciliation path. `RawPointInTimeArtifactArchive` remains the sole original
byte/custody owner. The existing `SecurityIdentity`, `security_master/v1`, cohort
admission, and retained v1 receipts keep their parsing and interval semantics.
V2 records are never passed off as v1 records or silently converted to them.
An actual v2 cohort requires a separately verified relationship/population receipt
and source profiles qualified against genuine response shapes.

## Identity layers

Use independent local UUID identities with kind prefixes. Identity allocation
and reviewed entity links are local resolution decisions, whose evidence is
retained separately from source assertions. Neither a ticker, CIK, FIGI, CUSIP nor
an Alpaca UUID alone establishes economic continuity.

| Layer | Meaning |
| --- | --- |
| issuer | Legal/reporting entity; CIK and names attach here. |
| security | A specific economic share class. Two issuer share classes remain distinct. |
| listing | A security's listing on a venue; its end need not terminate the security. |
| alias | A dated ticker/name alias on a listing. Ticker reuse produces separate aliases. |
| external_identifier | A source-scoped external ID/value; changes do not silently replace a security. |
| event | A corporate action or correction with independent effective/processing dates and consideration. |

Entity relationships require reviewed, source-bound crosswalks. Similar names,
the first returned price, and a bars `asof` label cannot create those links.

## Source assertions

Schema `security_master/v2` contains immutable, content-addressed assertions.
Each assertion has a local subject kind/ID, an allowed factual field, parser
version, selected source fields, original artifact receipt, and optional earlier
assertion IDs that it corrects. The builder reopens the original through the PIT
archive; validation and replay repeat that derivation. Caller-supplied normalized
facts, completeness flags and clock values are not accepted as substitutes.

The selected source paths describe a JSON value and any supplied
`effective_from`, `effective_to`, `source_published_at`, `source_recorded_at`, and
`coverage_through`. JSON paths are exact string/integer arrays. A absent source
field is represented by a null path, with no invented value. Duplicate JSON keys,
nonfinite numbers, numeric/path lookalikes and unbounded structures are rejected.
The parser copies bounded finite JSON facts; any later profile-specific
normalization needs its own version and independent fixtures.

All assertions bind the source URI, original-byte and receipt hashes, trusted
retrieval time, archive-recording time, source-path map and parser version.
Correction parents retain their exact assertion hashes and original lineage.
The assertion hash covers every field and the fixed analysis-only authority.

### Clocks and interval queries

- Effective dates concern the source's claim about validity. They do not describe
  when this application learned the fact.
- Source publication/recording clocks remain null when not supplied; neither is
  inferred from an effective date or local retrieval.
- Retrieval and archive clocks come exclusively from the verified PIT receipt.
  A newly imported old document remains newly archived.
- V2 effective intervals use `[effective_from, effective_to)`; this explicitly
  differs from unchanged v1 semantics. Unknown start/end states stay visible.
- A null end is open in the source, not proof of perpetual coverage. To use an
  open assertion on a date, require an explicit source-backed `coverage_through`
  boundary including that date. A point snapshot without such coverage cannot
  qualify a historical interval.
- As-known reconciliation uses a real UTC cutoff and requires all supplied
  knowledge clocks, including archive time, to be no later than that cutoff.
  Corrections captured later cannot rewrite an earlier query or frozen cohort.

### States

Reconciliation distinguishes `observed`, `reconstructed`, `corroborated`,
`conflicting`, `unknown`, `unsupported`, `data_unavailable`, and `not_requested`.
An original-backed single direct assertion is observed. Independent agreeing
source origins can corroborate it; repeated rows from one source do not count as
independent corroboration. Historical reconstruction is labelled explicitly and
does not imply historical custody. Missing interval coverage yields unknown.
Conflicts retain each assertion ID and value; no latest-wins rule resolves them
unless a valid, later append-only correction explicitly names its parents.
Unrequested/unavailable scope belongs in the independent coverage record, with
no synthetic empty source response or invented absence fact.

## Events and consideration

Event assertions retain source action type/status, announcement/publication and
processing/effective dates, and source cash/security consideration fields. Known
delisting is separate from known proceeds. A symbol change is an alias change
unless independently proved economic terms say otherwise. A missing cash/share
leg means unavailable consideration; no last-price or zero-value inference is
permitted. The economic outcome owner must reopen event/terms/proceeds originals
and evaluate legs without double counting. These assertions alone do not admit
an outcome.

## Coverage and complete populations

Coverage schema `security_master_coverage/v2` separately records discovery,
identity/alias, prices, and corporate-action/consideration dimensions. It binds a
frozen population contract, requested family/partition/interval, exact page and
source artifact inventory, capture clocks, parser version and accounted records.
Partition states are complete, incomplete, unavailable or not requested.
Complete means every declared partition's upstream page chain was independently
reopened and accounted for; a caller's `complete` label or row count cannot prove
that condition. A complete declared Alpaca snapshot is not complete U.S. history.

Discovery can be complete while cohort admission remains closed until the
required source-scoped coverage and issuer/security/listing/alias links are
verified. Every discovered record
is assigned exactly one eligible, ineligible or unresolved disposition. A narrow
diagnostic sample, an array limit and omitted candidate rows cannot qualify a
global top 100. Preserve the exact existing 60-session median and nested 100/75/50
ranking described in the [population contract](2026-10-01-prospective-security-population.md).

The October 2 original-backed discovery/accounting implementation reopens all
33,555 captured rows. No current directory or SEC ticker metadata was converted
to a dated share-class relationship. Original-leg v2 execution envelopes retain
covered cash/security quantities separately from unavailable economic returns;
their admission path reopens action, raw-price and calendar originals. Complete
effective-event and payment/delivery coverage remain independent open gates.

## Required offline evidence

Replay unchanged v1 fixtures. V2 fixtures use synthetic upstream originals and
trusted test archive clocks to cover independent share classes, ticker reuse,
name/external-ID changes, interval boundaries, unknown open coverage, conflicting
sources, missing/late events, delisting without proceeds, altered originals and
append-only corrections. Serialize and reopen each assertion; any changed fact,
path, clock, parent or hash must fail verification. These checks prove software
behavior and no historical/population coverage.

## Genuine current metadata profiles — October 2

`security_source_profiles.py` now reopens actual OpenFIGI request/response slots
and Nasdaq whole-file layouts. The explicit OpenFIGI label-pair parser can
produce original-backed normalized type assertions while the earlier direct
JSON parser remains byte-compatible. Unknown or broad types, ambiguous matches,
undocumented exchange codes and missing date/zone fields remain visible.

The diagnostic captured five mappings and 13,294 independent directory rows.
It does not establish a provider-to-share-class relationship or dated interval.
The frozen Alpaca v3 campaign and all of its dispositions are unchanged. A
future campaign using these additional families needs prospective policy freeze
and qualified coverage; source agreement alone does not admit a cohort.
