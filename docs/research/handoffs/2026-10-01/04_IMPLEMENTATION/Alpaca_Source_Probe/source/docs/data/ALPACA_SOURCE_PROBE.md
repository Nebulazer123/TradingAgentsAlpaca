# Alpaca source-qualification probe — first implementation

## What this adds

A standard-library-only diagnostic collector and offline replay verifier, next to
TradingAgents' existing dataflow code. It answers what the existing Alpaca routes
actually return; it **does not** create an authoritative security master, establish
complete historical membership, admit a cohort/protocol, or resolve a trading outcome.

This is an additive patch designed against the remotely inspected reference
`b3484fe22270b9282adef2228a35477558730b4a`. Compare with the current local checkout
before integration. In particular, preserve unpushed Codex subscription-runner and
research-benchmark changes. No existing module, gate, model route, dependency lock,
credential file, scheduler or runtime configuration is modified by this patch.

## Entry points

Use the direct script, rather than `python -m tradingagents...`. The package's
existing `__init__.py` loads dotenv files. This script deliberately loads only the
new standard-library module, so planning and inspection do not initialize the
application or inspect credentials.

From the actual repository root:

```sh
python3 scripts/alpaca_source_probe.py --help
python3 scripts/alpaca_source_probe.py plan \
  --start 2026-06-17 --end 2026-09-11 \
  --symbol-asof 2026-10-01 \
  --symbols AAPL,GOOG,GOOGL,META
```

`plan` prints JSON and performs no credential or network reads. Save that JSON to
a new private file to prepare a later collection. The dates above are an explicit
historical diagnostic window, not a retrospective study admission. The saved
calendar determines the actual trading sessions; weekday arithmetic is never used
to qualify real bars. A window with other than exactly 60 returned sessions remains
a valid diagnostic request but cannot produce the 60-session metric.

To include bounded replay, supply **both** `--replay-since` and `--replay-until`
with timezone-aware timestamps. Maximum span: seven days. Example: the one-hour
window `2026-09-20T00:00:00Z` through `2026-09-20T01:00:00Z`. Replay emission dates
are independent of the REST corporate-action `process_date` window. The replay
query is market-wide for the US, NOT filtered to the sampled symbols. It is off
unless both bounds are provided.

### Future authorized collection — not performed by the implementation tests

Collection requires appropriate explicit read authorization. Possession of keys,
a plan file, or an old permission receipt is not a substitute for that authorization.
The opt-in flag is a deliberate command-line check, not a new trading permission.

```sh
python3 scripts/alpaca_source_probe.py collect \
  --plan /absolute/path/to/private-probe-plan.json \
  --out /absolute/path/to/new-private-probe-bundle \
  --allow-network-read
```

Only at this entry point are `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_SECRET_KEY`
read from the process environment. No dotenv loading, keychain access, secret
printing, broker account/position/order reads, or live-host fallback is performed.
Do not paste credentials into chat or into this plan. Use the existing approved
local credential-loading arrangement. The output directory must not exist and its
parent must already exist. Never reuse an existing capture directory.

The collector accepts completed dates only: the inclusive market end date must
precede the current New York date and `symbol_asof` cannot be in the future. It
never claims that historical data newly retrieved now were in local custody at
an earlier decision cutoff.

### Offline inspection

```sh
python3 scripts/alpaca_source_probe.py inspect /absolute/path/to/private-probe-bundle
python3 -m pytest -q tests/test_alpaca_source_probe.py
```

`inspect` reopens and hashes the original response bodies, checks receipt/manifest
consistency and pagination, and recalculates the diagnostic. It ignores the saved
`report.json` instead of trusting a previous success label. Missing, altered,
symlinked or unexpected bundle files are rejected.

Exit 0 means the requested response diagnostics and sample 60-session grids
passed without snapshot identity conflicts. It never means the master or cohort
is qualified. Exit 2 means an invalid input, inaccessible source, incomplete
response/window, snapshot inconsistency, or other diagnostic gap. A market sample
with a known price below $5 is still useful for testing data access; its reported
price-floor flag is false, not permission to include it in a cohort.

## Exact supported request surface

| Kind | Fixed host and path | Important parameters |
| --- | --- | --- |
| Discovery | `paper-api.alpaca.markets/v2/assets` | Separate active/inactive requests, `asset_class=us_equity` |
| Sample identity | `paper-api.alpaca.markets/v2/assets/{symbol}` | Validated symbol, no account endpoint |
| Calendar | `paper-api.alpaca.markets/v2/calendar` | Explicit dates and `date_type=TRADING` |
| Prices | `data.alpaca.markets/v2/stocks/{symbol}/bars` | `1Day`, `sip`, `raw`, explicit `asof`, bounded dates, ascending pages |
| Actions | `data.alpaca.markets/v1/corporate-actions` | Sample symbols, explicit processing dates, `region=us`, `data_quality=all` |
| Optional replay | `stream.data.alpaca.markets/v1beta1/events/corporate-actions` | Explicit `since`/`until`, `region=us` |

No arbitrary URL, HTTP method, host override, redirect following, automatic
retry, proxy discovery, or separately billed provider is supported. A 401 or 429
stops subsequent requests. A 403 is recorded as an unverified entitlement failure,
not silently retried with another feed or host. A 404 is not delisting evidence.
Independent remaining queries can continue after source-specific failures.

Budgets are code-owned: 12 sampled symbols, 64 total requests, eight pages per
query, 32 MiB per response, 96 MiB total response bodies, and a 180-second overall
cooperative budget with at most 15-second request/read deadlines. These limits do
not define a stock universe. DNS and OS calls retain OS timing behavior; this is
not an operating-system-enforced hard wall-clock kill. A timed-out or byte-capped
body is retained as a **partial prefix**, marked incomplete and excluded from
interpretation. Incomplete HTTP Content-Length bodies are not accepted as complete.

## Bundle contents and evidence meaning

- `plan.json`: validated explicit input scope, with no credentials.
- `responses/NNNN.body`: exact response entity bytes, or an explicitly partial prefix.
- `responses/NNNN.json`: fixed request, timestamps, HTTP result, body digest/length.
- `manifest.json`: response inventory and collection outcomes.
- `report.json`: rederived diagnostic output; not an authority record.

The bundle directory is created mode 0700; files are created exclusively with
mode 0600 and flushed to disk. Per-response files survive later request failures.
A process interruption before `manifest.json` is complete leaves an incomplete
bundle, not a successful receipt. There is no resume/overwrite feature in v1.
Existing private parent directories are trusted; this is not a defense against a
malicious local administrator or a process with the same user's write authority.

Responses containing an exact credential value are withheld rather than edited
and then mislabeled as original. Compressed bodies are refused rather than
silently transformed. HTTP exception text and request authentication headers are
never included in reports. Keep actual captured data private; the repository's
code license does not grant market-data redistribution rights.

Injected transports are labelled `injected_fixture`; actual transport collection is
labelled `https`. This label is diagnostic metadata, not third-party attestation.
Hashes establish byte consistency, not the truth of source facts or authenticity
against an attacker able to rewrite the entire local bundle.

## What is checked

Discovery records are counted without a 512-record truncation. Asset IDs, returned
status/class filters, duplicate IDs, ambiguous active symbols, and disagreement
between bulk and individual snapshots are checked. `us_equity`, a name containing
"Common Stock", or an ETF-like name is never promoted to a security-type assertion.
Both share classes and inactive records remain visible. No ticker history or
permanent internal identity is inferred from the current Alpaca UUID.

Bars must match the returned calendar's **exact 60 sessions** with no duplicate,
missing or unexpected dates. Explicit zero volume is retained; missing rows are
never imputed as zero. Daily close-times-volume products and the even median use
exact integer-coefficient decimal arithmetic, independent of process precision.
The existing median definition and $5 previous-close flag are preserved. Session
basis is labelled Alpaca provider daily, not asserted to be regular-session-only.

REST actions retain all returned action groups, including unknown future types,
and reject repeated IDs during pagination rather than silently overwriting a
possible correction. `data_quality=all` is not coverage certification. An empty
response never proves that no actions occurred. SSE parsing accepts comments,
multiline data and CR/LF framing, rejects incomplete final frames, and detects
conflicting repeated event IDs. Byte-identical event payload redelivery is
deduplicated; differently serialized repeats are conservatively flagged. The
probe **does not apply insert/update/delete mutations** or infer a complete
revision history from the received sample.

## Boundary with the existing PIT archive

These are intake diagnostics, not a replacement canonical archive. V1 does not
write `security_master/v1`, modify source-profile allowlists, or invoke the existing
cohort/protocol admission functions. Once actual schema/entitlement behavior is
qualified, a separate reviewed importer can bind retained originals to the
existing `RawPointInTimeArtifactArchive` and source-derivation profiles. It must
preserve actual capture times and distinguish imports from original retrieval.
Never copy a historical date into a newly admitted artifact's trusted local time.

Every report explicitly retains:

```json
{
  "market_population_completeness": "NOT_ESTABLISHED",
  "security_master_qualified": false,
  "cohort_qualified": false,
  "historical_custody_qualified": false
}
```

## Verification scope

Tests use deliberately synthetic market calendars, asset responses, prices and
SSE envelopes. They check software behavior, not real market history, live
entitlements, API uptime, exact provider event-mutation schemas or completeness.
Real HTTP transport behavior is exercised with a mocked HTTPS connection; tests
block real DNS/socket creation. The standalone-entry test poisons package
initialization to verify that planning does not load the application's dotenv.

This additive slice was tested independently because a full clone was unavailable
in the implementation environment. It still needs the current checkout's focused
integration tests and ordinary final-candidate gates. No broad repository pass is
claimed. Python 3.10 grammar is checked separately; runtime tests used Python 3.13.

## Primary references checked October 1, 2026

- Assets: https://docs.alpaca.markets/us/reference/get-v2-assets-1
- Single-symbol asset: https://docs.alpaca.markets/us/reference/get-v2-assets-symbol_or_asset_id
- Calendar: https://docs.alpaca.markets/us/reference/legacycalendar
- Bars, adjustment, asof and pagination: https://docs.alpaca.markets/us/reference/stockbarsingle-1
- Corporate actions and processing-date semantics: https://docs.alpaca.markets/us/reference/corporateactions-1
- Replay host, bounds and inclusive redelivery: https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse
- Existing reference module: https://github.com/Nebulazer123/TradingAgentsAlpaca/blob/b3484fe22270b9282adef2228a35477558730b4a/tradingagents/dataflows/alpaca_reference.py
- Existing exact-median method: https://github.com/Nebulazer123/TradingAgentsAlpaca/blob/b3484fe22270b9282adef2228a35477558730b4a/tradingagents/dataflows/pit/cohort_admission.py

Next dependent work: verify actual bounded endpoint responses, then implement
upstream-backed identity assertions and complete-population manifests. Do not
change the 100/75/50 selection rule to make incomplete data appear sufficient.
