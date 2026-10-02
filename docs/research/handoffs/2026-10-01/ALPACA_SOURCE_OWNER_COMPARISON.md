# Alpaca probe source-owner comparison

Reviewed October 2, 2026 against source `d1cd3ee40002660ca4cb116ca69240e7aa376ae5`
on `oai/tradingagents-harness-20261001`. The donor was based on
`b3484fe22270b9282adef2228a35477558730b4a`. All four proposed paths are absent in
the current source, so adoption is additive. The original packet and its copies
remain intact. Root owns this integration and a separate self-review.

## Disposition of the four added-file hunks

| Donor hunk | Disposition and current owner |
| --- | --- |
| `tradingagents/dataflows/alpaca_source_probe.py` | Adopt the fixed-route diagnostic, exclusive private capture, original entity bytes, continuation receipts, finite exact decimals, and offline replay. Repair incomplete 401/429 stopping, strict manifest/receipt accounting, canonical UUID comparison, and documented SSE envelopes before qualification. Keep it independent of `alpaca_reference.py`, whose redacted analysis packets are not original-byte custody receipts. |
| `scripts/alpaca_source_probe.py` | Adopt the direct standard-library loader. Existing `tradingagents/__init__.py` loads dotenv; the standalone entry preserves zero credential/configuration reads in plan and inspect. No CLI registration or scheduler route is added. |
| `tests/test_alpaca_source_probe.py` | Adopt the synthetic offline checks, update envelopes to the reviewed schema and add repair regressions. Current `tests/conftest.py` blocks external network and real Codex inference; the donor's DNS guard adds protection. Run against the canonical environment and existing PIT raw-artifact/reference checks. |
| `docs/data/ALPACA_SOURCE_PROBE.md` | Adopt with the current review date, actual integrated-check evidence, and corrected envelope/accounting behavior. Preserve diagnostic-only meaning and explicit capture authority. |

## Boundary with existing owners

- `pit/raw_artifacts.py` owns canonical original-byte admission, trusted local
  retrieval/import clocks, immutable digest receipts and readback. The probe's
  bundle is intake evidence; it does not mint those receipts or backdate custody.
- `pit/official_observations.py` owns original-derived SEC and market observations.
  Keep SEC intake there; current SEC company/ticker metadata is not a dated
  security/listing history.
- `pit/records.py` and `cohort_admission.py` retain v1 identity/master replay,
  strict source profiles and pre-decision cutoff checks. No probe asset UUID,
  `us_equity` class or company name becomes a permanent identity or common-stock
  classification. The probe's twelve-symbol bound does not redefine the universe.
- `cohort_admission.py` retains the exact 60-session median and 100/75/50 rule.
  The diagnostic checks its saved calendar and uses the same integer-coefficient
  arithmetic; it performs no cohort admission.
- `execution_outcomes.py` remains the economic outcome owner. REST/SSE completion
  and action IDs do not prove terms, absence of events, or terminal consideration.

## Current official contract review

Public documentation only was read. No authenticated provider endpoint, account,
credential or model was accessed. Documented contracts are distinct from live
entitlements and observed retention.

| Official reference | Verified meaning and adoption limit |
| --- | --- |
| [Assets](https://docs.alpaca.markets/us/reference/get-v2-assets-1) | Trading/data asset directory; explicit active/inactive `us_equity` filters. It does not document complete historical membership or effective type/alias intervals. Retain all returned rows without the existing small sample truncation. |
| [Asset lookup](https://docs.alpaca.markets/us/reference/get-v2-assets-symbol_or_asset_id) | Symbol, asset ID and US-equity CUSIP lookup are documented. This diagnostic uses validated symbols only. A 404 remains a failed lookup, with no inferred delisting or identity end. |
| [Calendar](https://docs.alpaca.markets/us/reference/legacycalendar) | Inclusive dates, actual market opening/closing times, and explicit `TRADING` versus `SETTLEMENT` date basis. Require the saved exact session grid, with no weekday substitution. |
| [Single-symbol bars](https://docs.alpaca.markets/us/reference/stockbarsingle-1) | Inclusive interval, `1Day`, explicit SIP/raw/asof/sort, and `next_page_token` continuation even on short pages. `asof` maps names for an underlying entity and can fall back to symbol-only behavior; it is not permanent identity evidence. Provider daily aggregation remains explicitly uncertified as regular-session-only. |
| [Corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1) | Date bounds refer to `process_date`; total response limits and page tokens apply. `data_quality=all` includes incomplete early records, and publication can be delayed. Retain unknown groups and reject repeated IDs during paging. Neither an empty response nor a provider completeness label proves event/consideration coverage. |
| [Corporate-action SSE](https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse) | Bounds are emission times; replay/reconnect is inclusive. The rendered response schema requires `action` (insert/update/delete), `at`, ULID `event_id`, `event_type`, `region` and `ca`. Documentation includes an array of envelopes. Inspect retained envelopes and reject malformed/unknown mutations; do not apply a revision state machine or infer historical completeness. |
| [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Public submissions use issuer CIK and include current/former names and current tickers/exchanges. Live JSON and nightly bulk files have distinct vintages. Keep the issuer/security/listing distinction and source capture/publication clocks; these APIs do not alone supply historical security identity or action proceeds. |

The SSE rendered schema/examples were inspected in the browser because the text
retrieval omitted the expanded schema. Examples remain documentation, not actual
captured events. REST and SSE payloads still need authorized representative
response qualification before any importer profile is accepted.

## Unresolved source gates

Historical directory completeness, type and alias intervals, source publication
vintages, earliest corporate-action replay, missing-event proof, original action
terms/proceeds, SIP entitlement, and data-use/publication rights remain
`NOT_ESTABLISHED`. No live or historical coverage is accepted by this review.

The protection readback is retained privately at
`results/readiness_continuation/20261002-continuation-implementation/before-protection.json`.
All four frozen owner digests match the accepted October 1 baseline. All ten
automations remain paused, but nine TOML byte digests differ from that older
baseline; the current bytes are recorded without changing them. Semantic contract
readback remains separate from byte equality. This review grants no
external-operation authority.
