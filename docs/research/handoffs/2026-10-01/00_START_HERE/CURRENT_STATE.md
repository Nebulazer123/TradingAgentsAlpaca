# TradingAgents current state distilled from this chat

## Project identity

- Repository: `Nebulazer123/TradingAgentsAlpaca`
- Canonical local root: `/Users/corbinfloyd/Documents/TradingAgents`
- The public repo has multiple branches and can lag newer local Codex work.
- Do not reset local work to the inspected remote revision.

## Current strategic decision

Use a **free-first, prospective, source-backed** security-master route. Do not purchase an expensive data service by default.

Primary stack under investigation:

- Alpaca for current asset inventory, historical SIP bars, and corporate-action data/replay where actually entitled;
- SEC EDGAR for issuer/filing/event facts and merger/acquisition terms;
- public exchange data for listing/event corroboration;
- OpenFIGI for identifier crosswalk support;
- Alpha Vantage historical listing status only as optional corroboration.

## Existing protocol that should not be casually changed

- 60 preceding completed trading sessions
- raw daily bars
- prior close >= $5
- median daily dollar volume
- U.S.-listed eligible common stocks
- explicit source-bound identity and market-data feed
- nested 100 / 75 / 50 cohorts, with 75 primary

## Existing repo evidence

Repository readiness/source-collection documentation says:

- roughly 14,263 active Alpaca `us_equity` records were discovered;
- detailed bar/identity collection was limited to the prior ~42 ledger symbols plus SPY;
- current local `security_master/v1` hostname/profile has no established authoritative upstream producer;
- a 43-symbol seed cannot qualify a 100/75/50 cohort;
- current snapshots do not prove historical identity continuity.

## Code-level issues found during inspection

### 1. Population completeness

`cohort.py` / admission logic can rank a supplied candidate set but the inspected version had a bounded candidate count (~512). That is not evidence the supplied set is the complete intended population.

### 2. Identity model

The inspected `SecurityIdentity` model has one symbol/exchange/effective interval and couples delisted state to successor/terminal-proceeds knowledge. Real lifecycle cases need more explicit issuer/security/listing/alias separation.

### 3. Security-master provenance

`security-master.tradingagents.local` validates a local record shape but does not establish the truth of the upstream facts. A real producer must bind normalized assertions to retained source bytes.

### 4. Corporate-action completeness

The outcome path can hash a provided action set as complete. The inspected tournament-evidence verifier showed stronger original-byte replay for prices/calendars than for every action/proceeds fact. This needs a focused reproduction in the current local source.

### 5. Daily-bar semantics

Research indicates provider daily bars may include extended-hours activity. Evidence labels must match vendor semantics rather than asserting regular-session-only volume without proof.

### 6. Additional static issues

- possible fixed-string `is not` bug in `AuthorizedNormalTradeIntent.from_dict` after JSON reload;
- remote benchmark code appeared hardwired to OpenRouter, while the project is now supposed to use the user’s existing ChatGPT/Codex subscription route where possible.

These are findings to reproduce against the current local checkout, not instructions to blindly patch old code.

## Research conclusions

### Alpaca

Strongest existing/free route for ranking data and a substantial part of event intake.

Important nuances:

- historical SIP and real-time SIP have different entitlement semantics;
- asset UUIDs can change around identifier/corporate-action changes;
- `us_equity` is not enough to establish common-stock type;
- `asof` is symbol/entity mapping context, not “data as known on that date”;
- corporate-action REST is process-date based and may be delayed;
- the 2026 event stream supports insert/update/delete replay, but retention depth and current entitlement are unverified until a bounded real read is performed;
- an empty corporate-action result cannot automatically prove absence.

### SEC

Good for issuer identity, filings, name history, merger terms, share-class and event corroboration. Not a complete share-class/listing/trading-status master by itself.

### OpenFIGI

Useful supporting crosswalk. Do not treat current associated metadata as historical membership evidence.

### Public exchanges

Useful current inventory and dated-event corroboration. Current symbol directories are snapshots, not historical rosters. Historical commercial products and newer free event feeds must be distinguished carefully.

## Implementation status from this chat

A first probe was written in an isolated workspace.

Authoritative receipt: `04_IMPLEMENTATION/Alpaca_Source_Probe/BUILD_RECEIPT.json`

- 85 focused tests passed.
- No provider or account requests were executed.
- No repository was modified.
- Full integration/Ruff remain outstanding.

The patch is additive and intentionally non-authoritative: it can plan, collect approved read-only source diagnostics, and inspect captured bundles offline. It explicitly leaves security-master and cohort qualification false.

## Immediate development sequence

1. Reconcile/integrate the additive probe into the current local checkout.
2. Run its focused tests plus local static checks.
3. Build a versioned source-backed security/listing/alias assertion layer.
4. Build a complete population manifest with explicit eligible/ineligible/unresolved states.
5. Extend cohort admission to bind the complete manifest and deterministic global ranking.
6. Strengthen corporate-action/proceeds raw-source verification.
7. Admit a new **future** cohort after its inputs are captured prospectively.

## External-action boundary

The code package does not itself authorize using credentials or external accounts. If the next agent reaches a point where an actual Alpaca/other provider read is required, it should identify the exact route, data requested, side effects (read-only), cost (expected $0 for the proposed route), and ask/confirm only if current authorization is not already explicit in its task context.
