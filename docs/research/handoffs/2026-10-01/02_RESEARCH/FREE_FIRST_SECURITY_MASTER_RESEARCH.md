# Original assistant response — deep free-first security-master research

# TradingAgents: a defensible, free-first security master

**Research date: October 1, 2026**

## 1. Executive answer

**My recommendation is to build a source-backed, prospective security master using your existing Alpaca integration, SEC filings, and public exchange records—not purchase an enterprise dataset.**

There is now substantially better evidence for that route. Alpaca documents free historical stock data, provides corporate-action endpoints, and has added a replayable corporate-action event stream. However, these capabilities **do not establish that Alpaca alone provides a complete historical security master or an uninterrupted archive of everything known at each historical date**. ([docs.alpaca.markets](https://docs.alpaca.markets/us/docs/about-market-data-api))

The distinction determines what TradingAgents can honestly qualify:

| Question | Answer |
|---|---|
| Can the project obtain historical ranking prices without another paid provider? | **Verified in documentation:** Alpaca permits historical SIP requests without a paid subscription when the requested end is at least 15 minutes old. Your existing account’s present access still needs a bounded check. |
| Can it start building a trustworthy record for future decisions? | **Strongly supported:** capture actual inputs before selection, preserve revisions, and resolve identities against source records. |
| Can the free stack immediately recreate a complete, historical, “as-known” U.S. security master? | **Not established.** Historical asset completeness, original corporate-action vintages, and dated classification coverage remain insufficiently documented. |
| Must you sign up for anything now? | **No new signup is my recommended next step.** Qualify the existing access first. |
| Is the blocker entirely missing data? | **No.** The inspected code also has identity-model, population-completeness, and corporate-action-verification gaps. |

The historical SIP entitlement is explicit in Alpaca’s [Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq); it should replace my earlier suggestion that another historical-price provider was necessarily missing.

The target remains **60-session median daily dollar volume, 75 primary securities, and nested 100/50 sensitivity cohorts**. No change to average volume, market capitalization, or present-day index constituents is warranted merely to simplify acquisition.

This was documentary research and static source inspection. It does **not** constitute successful endpoint testing, verification of the ignored local archive, or qualification of a production cohort.

---

## 2. What TradingAgents already has—and what the code actually lacks

### Inspected source boundary

The principal implementation reference was [`b3484fe…`](https://github.com/Nebulazer123/TradingAgentsAlpaca/tree/b3484fe22270b9282adef2228a35477558730b4a), with readiness material from `36e8727…`. Remote `main`, `master`, readiness, and agent-guidance branches remain distinct. Your newer local Codex work must be preserved and compared before applying these findings.

The existing system already provides the right architectural foundation:

| Existing component | What it already does | What remains necessary |
|---|---|---|
| `raw_artifacts.py` | Preserves source bytes, hashes, retrieval time, and archive-recording time. | Add narrowly scoped support for original CSV/text/event-stream formats and derived-record lineage. |
| `records.py` | Represents security identities, observations, and corporate actions. | Separate security identity from ticker/listing history and from outcome availability. |
| `cohort.py` | Computes deterministic rankings and nested cohorts. | Bind the result to a complete declared candidate population. |
| `cohort_admission.py` | Reopens sources and recalculates qualification facts. | Replace the unestablished local master profile with a real upstream-derived producer. |
| Economic evidence/admission modules | Bind protocols, features, prices, outcomes, and source receipts. | Verify corporate-action coverage and original action/proceeds evidence as rigorously as price evidence. |

These are existing modules to extend—not reasons to install another database, trading platform, or agent framework.

### Finding A: discovery was broad; detailed collection was narrow

The [September 14 collection checkpoint](https://github.com/Nebulazer123/TradingAgentsAlpaca/blob/36e8727ba927ed717dd6108a01dfbce174e2879f/docs/superpowers/checkpoints/2026-09-14-prospective-source-collection.md) reports **14,263 active Alpaca `us_equity` records**, but detailed price collection for only **42 ledger symbols plus SPY**. It also reports complete 60-session raw and adjusted SIP responses for those 43 symbols. These are reported results, not raw files independently reopened during this investigation.

The actual problem is therefore not “find another 57 ticker names.” It is **convert broad discovery into a source-supported, completely accounted-for candidate population**.

### Finding B: the master is a required input, not an established source

The admission path expects an Alpaca asset record plus a `security_master/v1` record associated with `security-master.tradingagents.local`. It validates their fields and hashes, but the checkpoint explicitly says no legitimate producer/history was established behind that profile.

Generating matching JSON would satisfy a shape, not establish the underlying facts.

### Finding C: the 512-record bound is not a completeness mechanism

The builder accepts at most **512 candidates**, verifies the supplied records, and requires at least 100 eligible securities. It does not independently establish that potentially higher-ranked securities were included.

That is a valid bounded parser design, but it cannot support an unqualified market-wide top-100 claim without an upstream population manifest.

### Finding D: identity and terminal outcomes are too tightly coupled

The inspected `SecurityIdentity` supports one symbol, one exchange, and one effective interval. An active identity cannot have an end date; a delisted identity requires a successor or terminal-proceeds reference. `CorporateAction` supports six action categories but not a distinct spinoff representation.

A listing can end without the security becoming economically worthless. A ticker can change without the security terminating. The schema needs to represent those distinctions directly.

### Finding E: “complete corporate-action set” is not currently demonstrated

The inspected outcome builder hashes a supplied action set with `completeness_status="complete"` without receiving an independent coverage receipt. The traced tournament verifier replays price-window and calendar evidence, but does not show equivalent reopening of each corporate-action and terminal-proceeds original.

This is a **static-review finding requiring focused tests**, not a claim that I executed a failing case. Nevertheless, it is directly relevant: reliable prices alone cannot qualify outcomes through mergers or delistings.

---

## 3. Source matrix

### Sources relevant to the free-first implementation

| Source | Identity, listings, and events | Prices/rankings | Access and recommended role |
|---|---|---|---|
| **[Alpaca](https://docs.alpaca.markets/us/docs/about-market-data-api)** | Current active/inactive asset records; corporate-action queries and revision events. Complete historical asset membership and original-version retention are not established. | Historical OHLCV since 2016 is documented. Calculate your ranking locally. | Existing credentials; Basic is free. **Primary acquisition route**, not sole identity authority. |
| **[SEC EDGAR](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)** | Issuer identity, filings, merger terms, share-class descriptions, and dated disclosures. Not a complete exchange security master. | Financial inputs, not a consolidated trading-volume feed. | No API key. **Issuer/event corroboration and fundamentals.** |
| **[OpenFIGI](https://www.openfigi.com/api/documentation)** | Permanent instrument identifiers and crosswalk metadata; supports unlisted-equity searches. No documented historical-as-of alias archive in this interface. | None. | Usable without an account. **Supporting crosswalk**, not proof of historical eligibility. |
| **[Nasdaq directories](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)** | Current listings and useful flags. Separate Daily List contains dated events; do not conflate the products. | Not your historical consolidated ranking series. | Public snapshot files. **Independent population reconciliation.** |
| **[NYSE public material](https://www.nyse.com/trade/corporate-actions)** | Notices and a public MEF directory exist; complete freely retained historical contents were not verified. | Separate pricing products. | **Corroboration and a qualification lead**, not a proven free historical master. |
| **[FINRA OTC Daily List](https://otce.finra.org/otce/dailyList)** | OTC additions, deletions, symbol/name changes, and actions. Relevant to listed-to-OTC transitions, not a substitute for national-exchange history. | Not a consolidated listed-equity price source. | Public website; documented API uses credentials. **Transition/outcome corroboration.** |
| **[Cboe listed symbols](https://www.cboe.com/us/equities/market_statistics/listed_symbols/)** | Timestamped current listings, downloadable as CSV/XML. | Current trading statistics are not the required 60-session history. | Public. **Current-inventory cross-check.** |
| **[Alpha Vantage listing status](https://www.alphavantage.co/documentation/#listing-status)** | Dated active/delisted lists after January 1, 2010; CSV output. Does not establish permanent identity or original publication vintages. | Separate price endpoints. | Free key; optional **historical membership cross-check**. |

### Paid providers as benchmarks—not recommended dependencies

| Provider | Verified useful capabilities and historical limitations | Published cost/access |
|---|---|---|
| **[Databento](https://databento.com/docs/venues-and-datasets/security-master)** | Listing-level master from **2005-01-01**; corporate actions separately from **2018-05-01**. Its corporate-action API explicitly supports retained point-in-time versions. | Full-universe package/entitlement needs qualification and pricing confirmation. Internal use permitted; external file/API redistribution prohibited under the documented product terms. |
| **[CRSP](https://www.crsp.org/research__trashed/crsp-us-stock-databases/)** | Daily/monthly data, corporate actions, active/inactive U.S. securities, PERMNO/PERMCO. Coverage must be selected by exchange and product; latest corrected history is not automatically an original vendor vintage. | Subscription/qualified institutional access; no verified individual price. **Not a signup prerequisite.** |
| **[Sharadar](https://sharadar.com/docs/actions)** | Actions documented from 1998, including lifecycle events. Permanent ticker IDs are useful, but its ticker table is explicitly a **snapshot**, not an as-of metadata table. | Prices plan **$9/month or $99/year for five years**; full history **$39/month or $299/year**. Personal-use and retention restrictions matter. |
| **[Norgate](https://norgatedata.com/data-package-faq.php)** | Delisted securities and historical index membership in relevant packages. Does not expose historical name/ticker records or a historical correction-version log sufficient for this contract. | U.S. Platinum **$630/year**, with advertised history back to 1990. Good backtesting data; **not the complete master requested here**. |
| **[QuantConnect](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quantconnect/us-equity-security-master)** | Master history from 1998, mapping and adjustment files designed for LEAN. A separate platform’s historical constituent machinery does not automatically fit your retained-source contract. | Documented master download/subscription line is **$600**, with **$600/year updates**; additional datasets and platform terms are separate. |
| **[Massive](https://massive.com/pricing)** | Dated ticker queries and historical price/reference components. Complete merger-successor and original-revision coverage still needs qualification. | Free plan has five calls/minute and advertised two-year history; paid plans begin at **$29/month**. Endpoint-specific history must not be inferred from plan headlines. |
| **[Intrinio](https://docs.intrinio.com/documentation/download/securities)** | Security metadata includes previous tickers, FIGIs, delisting and primary-listing fields. Its help page says merger histories can be joined onto a successor—important to inspect rather than assume untouched security-specific history. | Individual plan **$150/month**, no redistribution/display. No reason to add it before qualifying existing access. |
| **[LSEG](https://www.lseg.com/en/data-analytics/market-data/data-analytics-pricing/reference-data/corporate-actions)** | Global corporate actions, extensive event coverage, and advertised 25-plus years of equity history. | Quote/contract required; historical version semantics and delivery rights need product-specific confirmation. |
| **[Bloomberg](https://professional.bloomberg.com/products/data/enterprise-catalog/cofi/)** | Connected point-in-time financials, prices, and security-master datasets via Data License. | Enterprise entitlement/quote; not equivalent to free OpenFIGI access. |
| **[ICE](https://developer.ice.com/fixed-income-data-services/catalog/ice-reference-data)** | Instrument-to-listing reference data; inactive-security files; corporate-action audit trails and identifier cross-references. History explicitly depends on asset and attribute. | Quote/contract required. Useful completeness benchmark, not a zero-cost route. |

FactSet’s [Data Management Solutions](https://www.factset.com/marketplace/catalog/product/factset-data-management-solutions) and [Global Prices API](https://developer.factset.com/api-catalog/factset-global-prices-api) also provide relevant symbology, entity relationships, prices, and corporate-action interfaces. Their exact package, historical-version coverage, and rights would require entitlement-specific qualification; I found no reason to make that process a project dependency.

### Other inexpensive sources do not remove the central gap

**Tiingo** offers a free tier with 500 unique symbols/month, 50 requests/hour, and 1,000 requests/day. That is useful for bounded checks, but a 500-symbol allowance must not become an arbitrary definition of your full population.

**FMP** advertises 250 free calls/day; that does not establish access to every historical/reference endpoint. Its pricing page also requires a separate agreement for display or redistribution.

**EODHD** advertises 20 free calls/day and one year of history, with free dividends/splits activated through support. It does not offer a clear advantage over your existing Alpaca price route for this task.

The Stooq download page could not be inspected beyond browser verification. I did not establish its required identity, event-history, or redistribution guarantees and would not select it as the authoritative replacement.

---

## 4. Alpaca deep dive

### 4.1 Asset UUIDs are useful—but not a universal permanent identity

Alpaca’s [mandatory corporate-action documentation](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions) makes a consequential distinction: a symbol change with an unchanged CUSIP updates the existing asset, whereas a CUSIP change produces a new asset object and makes the old one inactive.

Therefore:

> **An Alpaca asset ID should be an external identifier attached to TradingAgents’ identity model—not the sole definition of economic continuity.**

The right outcome may be the same security with a changed external identifier, a new security replacing an old one, or a merger involving multiple securities. The corporate terms determine that relationship.

### 4.2 `us_equity` is not a common-stock classification

The asset API exposes class, exchange, status, and tradability. Alpaca’s Broker API FAQ explicitly notes that the asset response does not provide a stock-versus-ETF category.

Do not classify by a name containing “Inc.” or by the absence of “ETF.” Obtain a positive security-type assertion from corroborating reference metadata or issuer/exchange evidence.

Broker API documentation also must not be treated as proof of every retail Trading API entitlement.

### 4.3 Historical SIP solves much of the price problem

The Basic plan documents 200 historical requests/minute. Its 30-symbol WebSocket limit is not a limit on the total historical candidate population. Historical SIP access and real-time SIP access have different entitlement rules.

For this project, explicitly select the consolidated historical feed and retain the selected feed in every receipt. Do not silently switch some candidates to IEX when a SIP request fails.

An illustrative workload of 5,000 securities × 60 sessions is **300,000 daily rows**. It is not 300,000 separate API calls. Alpaca’s [multi-symbol endpoint](https://docs.alpaca.markets/us/reference/stockbars) supports batched requests, but results are ordered by symbol/time and pagination limits apply across the response. Follow every continuation token.

The existing strict single-symbol profile can remain supported. A multi-symbol profile must retain its actual original response, not fabricate separate “original HTTP responses” from normalized slices.

### 4.4 `asof` controls symbol mapping—not historical knowledge

The [single-symbol bar documentation](https://docs.alpaca.markets/us/reference/stockbarsingle-1) says `asof` identifies the entity associated with a ticker on a date. It defaults to the current day. Mapping can be disabled with `-`, and an unknown ticker on the specified date can result in mapping being skipped.

Three implementation consequences follow:

**Pin the mapping date.** A moving default is not reproducible.

**Retain an independent identity relationship.** A successful bar response does not prove the intended security was selected.

**Do not interpret `asof` as a vintage filter.** It does not mean “return the database exactly as published on that date.”

### 4.5 Corporate-action queries are valuable but have important semantics

The [corporate-action endpoint](https://docs.alpaca.markets/us/reference/corporateactions-1) covers splits, distributions, spinoffs, several merger types, reorganizations, name changes, and other events. Its date filters use **`process_date`**, and Alpaca provides no guarantee that events appear immediately after announcement.

Furthermore, `data_quality=complete` is a field-completeness filter—not a certificate that every relevant corporate action exists. Already-processed records can be included despite otherwise incomplete fields. A blank currency can have multiple meanings and must not automatically become USD.

Query broader processing windows and reconcile revisions. Do not query only the economic holding dates and assume all late-arriving events were captured.

### 4.6 Replayable revisions are a meaningful new capability

Alpaca’s **July 20, 2026 changelog** announces the corporate-action SSE endpoint. It supports time-based and event-ID-based replay. This is evidence of an implemented capability, not just a feature request.

The [stream specification](https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse) distinguishes insert, update, and delete events. Replay is based on emitted-event time or IDs; reconnect behavior can redeliver the boundary event, requiring deduplication. A bounded `since`/`until` request can close after replay rather than remain permanently connected.

**Still unresolved:** earliest retained event, retention guarantee, completeness of pre-launch revisions, and your account’s access to this particular endpoint.

The endpoint’s launch date does not establish that its history starts then—or that it extends back to the price archive’s 2016 start.

### 4.7 Daily bars need a session-basis audit

An Alpaca staff explanation states that daily volume includes premarket and postmarket activity. That matters because the inspected observation schema labels market data `regular` and derives daily completion from regular-session close.

Preserve the 60-session median formula, but identify what its daily bars actually measure. Do not label extended-hours-inclusive volume “regular-session volume.”

If the intended protocol truly requires regular-session-only volume, that requires a documented acquisition change or protocol amendment—not a misleading label.

### 4.8 Missing historical prices are not proof of nonexistence

Alpaca staff have documented fixes involving missing historical prices caused by corporate-action/IPO metadata, and corrections to corporate-action ratios. These dated reports establish that corrections and mapping defects can occur; they do not establish that those specific defects persist today.

Consequently, an empty response should produce **`data_unavailable` or `identity_unresolved`**, not an invented IPO date, automatic delisting, or zero return.

---

## 5. The strongest free-source architecture

I recommend this pipeline:

**Complete current discovery → source-backed identity assertions → dated crosswalks and event history → accounted-for eligibility population → verified historical SIP ranking inputs → deterministic global ranking → frozen 100/75/50 cohorts → prospective economic evaluation.**

### Public-source responsibilities

**SEC:** use accession-specific filings for issuer identity, share classes, merger consideration, reorganizations, and financial inputs. Preserve filing/acceptance availability separately from the fiscal period being reported. Company-facts history is not an excuse to treat subsequently restated values as previously known.

**OpenFIGI:** use a matching instrument-level identifier as corroboration. Its specification says FIGIs are permanent and retired identifiers are not reused, while associated metadata is mutable. Permanence of the identifier does not turn today’s metadata into historical metadata.

**Exchange files:** use captured directories for population reconciliation and notices for dated changes.

Nasdaq’s August 2026 filing describes freely distributed event information preceding the commercial Daily List. But the actual implementation notice and a complete free historical archive were not established. The historical Daily List’s documented start, May 24, 1999, does not mean that archive became free.

NYSE’s public MEF directory is a useful lead, but I could not inspect the referenced JSON contents reliably. It remains a qualification candidate, not a declared replacement for paid reference history.

### Bootstrap honestly

For a **future** selection cutoff, historical facts reconstructed and captured beforehand can be legitimate inputs, provided the study accurately describes them. They cannot retroactively establish custody for an old prediction.

Where the preceding 60-session identity continuity cannot be supported, there are two honest choices: resolve it from source documents/events, or accumulate the necessary forward observation history. Accumulating 60 sessions does not automatically repair missing events; capture gaps still require reconciliation.

**Do not set `effective_from` to the first returned price merely to satisfy the validator.**

---

## 6. Remaining unavoidable gaps

The research did not establish a free source that resolves all of these simultaneously:

| Gap | Why it matters |
|---|---|
| Complete historical Alpaca asset membership | Today’s active/inactive responses are not a documented historical roster for every past date. |
| Earliest retained corporate-action revisions | Replay capability does not establish original-version coverage for the required interval. |
| Historical security-type continuity | Current common-stock metadata does not prove that classification throughout an earlier window. |
| Complete alias/exchange-transition history | Prices and current identifiers can conceal transfers, reuse, or stitched histories. |
| Corporate-action absence | “No rows returned” cannot prove no action occurred when coverage or ingestion is uncertain. |
| Terminal consideration for every selected security | Some outcomes need cash/share terms and later settlement evidence, not another price bar. |
| External processing/redistribution rights | API access is not a license to publish raw data or pass it to arbitrary third parties. |

These gaps need explicit states and targeted resolution. They do **not** justify declaring the entire project impossible, repeatedly searching the same archive, or immediately adding an expensive subscription.

---

## 7. Proposed security-master representation

Use a narrowly versioned **`security_master/v2`** rather than silently changing the meaning of existing receipts.

The design follows the distinction between effective history and the history of what was known. An append-only knowledge history can preserve later corrections without overwriting earlier decisions; this is the relevant part of [bitemporal history](https://martinfowler.com/articles/bitemporal-history.html), not a requirement to install a temporal database.

### Record families

| Record | Essential fields |
|---|---|
| **Issuer** | Internal `issuer_id`, legal-name assertions, CIK/LEI crosswalks, predecessor/successor relationships. |
| **Security/share class** | Internal `security_id`, issuer relationship, class/type, economic creation/termination assertions. |
| **Listing** | `listing_id`, security ID, venue/MIC, currency, primary-listing status, listing/suspension/delisting assertions. |
| **Ticker alias** | Namespace, ticker, listing/security relationship, effective interval, supporting evidence. |
| **External identifier** | Namespace, value, identifier level, valid interval, mapping evidence; Alpaca ID and different FIGI levels remain distinct. |
| **Corporate-action event** | Provider event ID/version, event type, affected IDs, dates, status, source references, and one or more cash/security legs. |
| **Eligibility assertion** | Policy version, decision cutoff, eligible/ineligible/unresolved, reason, evidence references. |
| **Coverage record** | Declared population, requested intervals/types, completed partitions, missing records, reconciliation result. |

Use an internal identifier whose continuity is established by evidence. Do not derive identity solely from ticker, issuer CIK, or a vendor ID that can be replaced.

### Keep the clocks separate

Each factual assertion should carry:

**Effective interval:** when the fact applied.

**Source publication/record time:** when the provider or issuer published that particular version, where supplied.

**Retrieval time:** when the response was received.

**Archive-recording time:** the trusted local capture time already used by TradingAgents.

A corporate action can be announced **before** its effective date. Do not force action announcements through a generic observation rule requiring event time to precede publication time.

For new versioned records, half-open intervals are practical. Existing v1 code uses different end-date comparisons, so migration must be explicit and tested rather than silently reinterpreting old dates.

### Source receipt requirements

Retain the provider/product, exact source reference, sanitized request parameters, response status, original bytes/hash, pagination chain, capture times, schema version, parser version, and derivation-parent hashes.

A normalized assertion must identify **which original field, filing passage, or event produced it**. `security-master.tradingagents.local` may identify an internal derivative, but cannot replace that upstream chain.

Represent uncertainty as `unknown`, `conflicting`, `observed`, `reconstructed`, or `corroborated`, with a reason and supporting assertions. A null end date means “no established ending in this record,” not “proved to exist forever.”

Finally, separate **known delisting** from **known terminal proceeds**. It must be possible to record the former while the latter remains unavailable.

---

## 8. Candidate completeness protocol

### Declare the population before ranking

The closest match to the existing code is:

> **U.S.-listed, Alpaca-tradable common securities satisfying the frozen eligibility policy at the selection cutoff.**

That is not identical to every security ever traded in the United States. If the existing acceptance requirement demands that broader scope, changing it requires an explicit protocol decision.

For a prospective study, using the actual eligible population at selection is not survivorship bias relative to future outcomes. Using that same population to reconstruct years of past cohorts would be.

### Account for every discovery record

Create one population manifest containing all records from the selected discovery sources. Every record must become:

| State | Meaning |
|---|---|
| **Eligible** | All required facts and ranking inputs are established. |
| **Ineligible** | A source-backed policy reason excludes it. |
| **Unresolved** | Identity, type, coverage, or ranking data is insufficient. |

Preserve source-only records that do not match Alpaca; they are reconciliation exceptions, not records to delete silently.

Separate “the API request finished” from “the response covers the intended population.” Reconcile source counts, identifiers, venue/type distributions, pagination, and independent directory differences.

### Resolve the ranking boundary without wasting effort

There is no need to research every low-liquidity security’s entire corporate history equally deeply before selecting the top 100.

A safe staged approach is to establish trustworthy ranking values or conservative bounds, then resolve identities and classifications that could change membership.

An unresolved record can be demonstrated irrelevant **only when its defensible maximum possible ranking score is below the established cutoff**. Missing prices or ambiguous ticker mapping generally prevent such a bound. They cannot simply be assigned zero.

This allows efficient qualification without pretending that every field of a universal historical master is complete.

### Preserve the 512 limit as a processing bound, not a market definition

Partition the full population. Validate every partition and retain its complete eligibility/ranking ledger.

For a fixed total ordering, a record below rank 100 in its own partition cannot enter the global top 100. Therefore, merging partition-level top-100 results can recover the exact global top 100. This is a mathematical property of the ranking, not a provider claim.

However, the final receipt must bind **all partitions and all exclusions**. Otherwise, a missing partition or manipulated partition winner list defeats the proof.

The existing bounded cohort representation can remain compact while a versioned reference points to the complete population manifest. Merely increasing `_MAX_CANDIDATES` does not solve provenance or omission.

---

## 9. Cohort algorithm: preserve the implemented rule

For each admitted selection:

1. Obtain the exact preceding 60 completed sessions from the retained official calendar.
2. Resolve each potentially eligible security and its ticker mappings across that window.
3. Use one explicit feed and consistent raw daily-bar basis.
4. Require prior completed close ≥ $5 and the existing common-stock/venue/status/tradability conditions.
5. Compute the exact median of the 60 daily close-times-volume products.
6. Rank descending, preserving the implementation’s symbol-then-security-ID tie-break; take prefixes 100, 75, and 50.

For sorted daily products \(x_{(1)},\ldots,x_{(60)}\):

\[
L_i=\frac{x_{(30)}+x_{(31)}}{2},
\qquad x_{i,d}=C^{raw}_{i,d}V^{raw}_{i,d}.
\]

This is a daily dollar-volume **proxy**, not exact transaction-by-transaction traded value. The inspected implementation already calculates the even median using exact decimal arithmetic.

Do not forward-fill missing bars or convert a missing response into a zero-volume observation. A confirmed zero-volume record is different from absent data.

The economic protocol’s **weekly decision cadence** remains separate from the initial universe-selection rule. The momentum/quality control subsequently needs longer price history and dated financial inputs; the 60-session cohort intake alone does not supply those features.

Freeze membership before outcomes. Later failure, acquisition, or delisting must not erase a selected security.

---

## 10. Repository implementation map

These are proposed changes, not changes performed.

| Repository area | Action | Smallest coherent change |
|---|---|---|
| `dataflows/pit/raw_artifacts.py` | **Modify** | Preserve bounded original CSV/text/SSE bodies with truthful MIME types and derivation links. |
| `dataflows/alpaca_reference.py` and API catalog | **Extend adapter** | Explicit asset, bar, and corporate-action routes with pagination and bounded replay semantics. |
| `dataflows/pit/records.py` | **Version schema** | Separate security/listing/alias assertions; permit incomplete lifecycle knowledge without inventing proceeds. |
| New narrow `dataflows/pit/security_master.py` | **Add producer** | Derive normalized assertions from retained upstream records and verified crosswalks. |
| `dataflows/pit/cohort.py` | **Modify** | Bind population-manifest identity while preserving the ranking rule and nested prefixes. |
| `dataflows/pit/cohort_admission.py` | **Modify** | Verify upstream lineage, complete partitions, explicit symbol mapping, and ranking-boundary exceptions. |
| `official_observations.py` | **Audit/modify** | Correct session-basis and availability derivations where source semantics differ. |
| `execution_outcomes.py` | **Modify** | Separate alias changes from termination; support required spinoff/merger legs and coverage evidence. |
| `economic_tournament_evidence_admission.py` | **Modify** | Reopen original action/proceeds evidence, not only prices and calendar. |
| Relevant point-in-time/economic tests | **Add tests** | Real-event documentary fixtures plus missing-partition, revision, and future-contamination regressions. |
| `cli/main.py` | **Minimal interface work** | Expose acquisition/validation/manifests through the existing CLI structure. |
| Ranking policy, control arms, immutable strategy store, model graph | **No redesign** | Reuse unless a focused test exposes a necessary change. |

The existing source receipt and qualification boundaries are already strong enough to support these extensions. The objective is to finish the missing producer and verification chain, not add another layer of self-certifying packets.

---

## 11. Qualification tests, including real historical cases

### Documentary ground-truth cases

These examples establish what the implementation must represent. They do **not** establish that an untested provider currently returns every event correctly.

| Real case | Primary evidence | Required result |
|---|---|---|
| **FB → META, June 9, 2022** | Meta’s [announcement](https://investor.atmeta.com/investor-news/press-release-details/2022/Meta-Platforms-Inc.-to-Change-Ticker-Symbol-to-META-on-June-9/default.aspx) says the CUSIP remained unchanged. | Same supported security continuity, dated alias change, no fabricated terminal event. |
| **META ticker reuse** | Roundhill’s [SEC filing](https://www.sec.gov/Archives/edgar/data/1683471/000089418922000256/meta497etickerchange.htm) changed its ETF ticker from META to METV effective January 31, 2022. | January’s META ETF must not become June’s Meta common shares. Also tests positive type classification. |
| **Pioneer → ExxonMobil, May 3, 2024** | Pioneer’s [closing 8-K](https://www.sec.gov/Archives/edgar/data/1038357/000119312524130052/d803313d8k.htm) records 2.3234 XOM shares per eligible PXD share. | Preserve predecessor identity and explicit stock consideration; do not simply concatenate prices. |
| **Twitter cash acquisition, October 27, 2022** | Twitter’s [closing filing](https://www.sec.gov/Archives/edgar/data/1418091/000119312522272772/d411753d8k.htm) documents cash consideration. | Resolve supported cash entitlement rather than using the last quoted price or requiring nonexistent later TWTR bars. |
| **Palantir exchange transfer, November 26, 2024** | [MIAX’s exchange notice](https://www.miaxglobal.com/alert/2024/11/25/miax-exchange-group-options-markets-change-market-underlying-security-used) identifies the NYSE-to-Nasdaq change. | Change the listing/venue assertion without assuming a new security or ticker. |
| **Bed Bath & Beyond: Nasdaq suspension and OTC continuation** | Its [SEC annual filing](https://www.sec.gov/Archives/edgar/data/886158/000088615823000059/bbby-20230225.htm) records suspension on May 3, 2023 and subsequent BBBYQ quotation. | National-exchange eligibility ends, but delisting alone does not imply a zero-value terminal outcome. |
| **Xperi/Adeia separation, October 2022** | Adeia’s [SEC filing](https://www.sec.gov/Archives/edgar/data/1803696/000095017024019362/adea-20231231.htm) describes the separation and distribution. | Represent parent continuation plus distributed child security. Old XPER history must not be blindly assigned to both successor tickers. |
| **GOOG/GOOGL share classes** | Alphabet’s [annual filing](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm) describes the Class A/Class C trading-symbol histories. | One issuer does not collapse distinct traded share classes into one security. |
| **Reddit IPO, March 21, 2024** | Reddit’s [SEC financial statement note](https://www.sec.gov/Archives/edgar/data/1713445/000171344525000018/R10.htm) confirms the first trading date. | It cannot have 60 preceding public-market sessions immediately after listing; exclude for the actual history requirement, not future performance. |

A present-day filing used to build a fixture establishes documentary ground truth for that fixture. It must not be mislabeled as a document available before the historical event.

### Pipeline tests that matter most

**Completeness:** omit an entire discovery page or source partition. Qualification must fail even if the remaining input still contains 100 eligible stocks.

**Boundary uncertainty:** insert an unresolved candidate whose plausible liquidity exceeds rank 100. The system must not certify an unchanged top 100.

**Pagination:** return fewer rows than requested with a non-null continuation token. Collection must continue.

**Revision replay:** deliver insert, update, delete, and a duplicate reconnect event. Original views remain reproducible; the updated view changes appropriately.

**Future contamination:** append future prices, revised mappings, and later outcomes. A frozen prior cohort’s bytes must not change.

**Partition invariance:** shuffled input order, different batch sizes, and different partition boundaries must yield the same ranked population and nested cohorts.

**Session semantics:** distinguish incomplete current-day bars, regular-session data, and provider-defined daily bars.

**Source replay:** alter an action ratio or terminal cash term while keeping the price window unchanged. Verification must fail when the value no longer matches retained originals.

**Identity continuity:** a simple ticker rename must not require a terminating identity. A merger or spinoff must not be reduced to that same rename case.

### Outcome handling needs particular care

The current builder’s requirement for a complete five-session price window before terminal-action handling deserves a regression test. A security acquired during that window may have provable consideration but no subsequent standalone price bars. Also, the current treatment of `symbol_change` as requiring a terminating identity is too restrictive for the FB/META case.

Outcome-time continuation records should reference the frozen feature identity, not overwrite it. Unknown terminal proceeds remain `outcome_unavailable`; documented cash/share consideration must be handled without double-counting adjustments and distributions.

---

## 12. Cost, access, licensing, and retention

### What the recommended route requires

| Component | Incremental cost | Access |
|---|---:|---|
| Existing Alpaca Basic historical data | **$0 documented** | Existing credentials; verify endpoint access rather than assume current entitlement. |
| SEC EDGAR | **$0** | No account/key; follow published access practices. |
| Public exchange directories/notices | **$0 where publicly provided** | No signup for the cited public pages/files; historical products are separate. |
| OpenFIGI mapping | **$0** | No key required; optional free key for higher limits. |
| Alpha Vantage membership checks | **$0 optional** | Free key; not my recommended immediate dependency. |
| FINRA public API credential | **$0 credential tier** | Individual account/credential; dataset access still needs confirmation. |
| Sharadar | **Optional paid alternative** | Personal subscription and material retention restrictions. Not required to start. |
| Enterprise providers | **Not recommended now** | Product agreement/quote/entitlement. |

**Two small documentation details matter.** OpenFIGI’s page lists ten unauthenticated mapping jobs in its general limit table but five in the endpoint-specific table. Use a conservative five-job batch until actual behavior is verified. Alpha Vantage advertises unlimited calls for verified educational/open-source projects, but that requires verification and should not be part of the base implementation assumption.

### Private research is not public redistribution

Alpaca’s [support answer](https://alpaca.markets/support/redistribute-alpaca-api) explicitly prohibits redistributing its API data under the ordinary arrangement. Its [disclosure library](https://alpaca.markets/disclosures) also links the applicable subscriber agreements.

Therefore, keep the populated archive and reconstructible master outside public Git. Publishing the code and synthetic fixtures does not require publishing the licensed data.

OpenFIGI’s open-data policy is different, but it does not erase restrictions attached to another provider’s fields merely because FIGIs were added.

Sharadar’s personal terms require deletion of its data and reconstructible datasets within 30 days of termination; they permit retention of non-reconstructible research outputs. They also restrict publication of evaluations of the service without approval. Those terms make “buy one month and retain a permanent reproducible public archive” unsuitable.

**External model processing remains a separate unresolved right.** I did not establish blanket permission to send raw SIP/reference data to external LLM services. Keep identity resolution, ranking, and source verification deterministic/local; assess the applicable rights before transmitting provider data. This does not require replacing your subscription-based coding workflow with a paid model API.

---

## 13. Unresolved questions and the exact evidence needed

| Unresolved question | Evidence that would resolve it |
|---|---|
| Does your existing Alpaca account permit the new corporate-action replay endpoint? | A bounded authenticated read with its actual response/status and entitlement information. |
| How far back are action events and revisions retained? | An explicit provider coverage statement plus boundary-date samples. Samples alone establish a lower bound, not completeness. |
| Are inactive assets complete for the desired historical interval? | A documented historical-universe contract or reconciliation against an independently complete historical roster. |
| Can the selected securities’ full 60-session identity/type continuity be established? | Dated source assertions and event chains covering each required interval. |
| Is the current daily-bar session labeling consistent with actual vendor aggregation? | Source specification plus representative raw responses and a focused interpretation test. |
| Have Nasdaq’s 2026 free-event changes actually been deployed, and what is retained? | The implementation notice, actual file schema, and documented retention policy. |
| Can public NYSE MEF material fill a specific historical gap? | Successful inspection of actual contents, coverage, retention, and reuse terms. |
| What rights cover external processing of the stored provider data? | The agreement applicable to the user/product and the exact proposed processing arrangement. |

Further generic provider searches are unlikely to answer account-specific access questions. Conversely, a successful account request will not by itself settle a population-completeness or licensing question.

---

## 14. The implementation I recommend

**Implement a prospective, source-backed master and a complete declared-population manifest. Keep broad historical reconstruction as a separately labeled capability.**

The first production target should be a future pre-open selection with all required inputs already captured, not a retroactively “repaired” old cohort.

Its qualification should establish four things independently:

**Identity:** each selected security and its relevant history are supported.

**Population:** the declared discovery universe is completely accounted for, with no unresolved record capable of changing the selected boundary.

**Reproducibility:** retained originals regenerate the same median ranking and 100/75/50 prefixes.

**Outcomes:** later action/proceeds evidence is independently verified without altering the frozen inputs.

Where the current acceptance contract demands broader historical coverage than this prospective design supplies, record a versioned scope decision. Do not make it appear satisfied by relabeling a current snapshot `security_master/v1`.

The inexpensive alternative is not “trust worse data.” It is **use a narrower, explicit claim; capture evidence before future decisions; preserve uncertainty; and spend engineering effort on the records that can affect the experiment**.

---

## 15. Immediate next actions

| Priority | Action | Expected evidence | Repository area | Access/cost |
|---|---|---|---|---|
| **1** | Build a bounded Alpaca source-qualification probe around the documented transition cases. | Endpoint results, actual schemas, mapping behavior, revision replay, and a precise gap report. | Alpaca adapters/catalog and focused fixtures. | Local implementation needs no new service. Credentialed execution requires appropriate read authorization; no purchase. |
| **2** | Implement source-backed security/listing/alias assertions on the current local checkout. | Reproducible crosswalks and explicit unresolved histories. | `records.py`, raw archive, narrow master producer. | Local work; no new account. |
| **3** | Add complete-population manifests and partitioned ranking. | Every record accounted for; missing-partition and boundary-uncertainty tests. | Cohort builder/admission. | Local work; full data intake uses existing permitted access. |
| **4** | Repair corporate-action completeness and raw outcome verification. | Real-event fixtures for aliases, spinoffs, mergers, OTC transitions, and proceeds. | Outcome builder and tournament evidence admission. | Local work; source acquisition only where needed. |
| **5** | Admit a future cohort from the qualified inputs. | Frozen 100/75/50 cohort and prospective experiment identity. | Existing economic protocol/admission path. | No new paid model/data dependency; subsequent outcomes require real elapsed sessions. |

### SINGLE BEST NEXT ACTION

**Have Codex build the bounded, fixture-tested Alpaca qualification probe—preserving your newer local work—so the next authorized read establishes exactly which identity, corporate-action, and historical-price facts your existing access can supply before adding any provider.**
