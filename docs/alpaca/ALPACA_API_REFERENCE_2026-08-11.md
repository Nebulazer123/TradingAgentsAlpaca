# Alpaca API Reference Expansion - 2026-08-11

## Verified change

Alpaca MCP Server 2.2.1 adds five always-available, read-only documentation tools:

1. `search_alpaca_docs`
2. `fetch_alpaca_doc`
3. `search_alpaca_api_specs`
4. `list_alpaca_api_endpoints`
5. `get_alpaca_endpoint_docs`

They search and inspect Alpaca's Trading API, Market Data API, and Authentication
API documentation. Broker API is excluded. The documentation tools themselves
cannot change accounts or orders; that does not make the rest of Alpaca's MCP
server read-only.

Upstream evidence:

- Server: <https://github.com/alpacahq/alpaca-mcp-server>
- Documentation-tool commit: <https://github.com/alpacahq/alpaca-mcp-server/commit/d86619172814441ac0ec2dccc2962b873c0193dc>

## Current inventory

The captured 2.2.1 inventory contains 83 paths and 99 operations:

| API | Operations |
| --- | ---: |
| Trading | 54 |
| Market Data | 44 |
| Authentication | 1 |

| Method | Operations | TradingAgents treatment |
| --- | ---: | --- |
| GET | 77 | Allowlisted read-only reference surface |
| POST | 10 | Documented only; not callable here |
| DELETE | 8 | Documented only; not callable here |
| PATCH | 2 | Documented only; not callable here |
| PUT | 2 | Documented only; not callable here |

The complete per-operation matrix is the versioned
`config/alpaca_api_reference_catalog.json`. The catalog records host, path,
method, runtime class, report visibility, redaction class, and access scope.

## Runtime boundary

`tradingagents.dataflows.alpaca_reference` accepts stable catalog route IDs,
never an arbitrary URL or method. It sends GET requests only and returns
`SourceEvidencePacket` objects with `analysis_only=true`,
`execution_authority=none`, request hashes, source references, redaction, and
explicit forbidden effects. Account-administration reads require an explicit
opt-in. The two server-sent-event routes are disabled by default and have hard
event/time limits when enabled.

The new surface does not create trade intents, size positions, submit, replace,
or cancel orders, promote sleeves, waive live gates, or issue OAuth tokens.

## Newly useful details

- Stock market-data feeds include SIP, IEX, delayed SIP, BOATS, overnight, and
  OTC choices subject to subscription. Every collected result must retain its
  explicit feed and as-of time.
- Latest-trade results omit conditions that do not update bar price, so they are
  filtered price context rather than a complete tape.
- Calendar responses can expose regular and extended session fields,
  `settlement_date`, and `date_type=TRADING|SETTLEMENT` context.
- Corporate actions, event streams, quote/trade metadata, option/crypto market
  data, screeners, auctions, forex, fixed income, wallets, locates, and other
  families can be inspected through one catalog. Niche or sensitive families
  remain on-demand and out of routine email.
- Order-replacement documentation describes race conditions and buying-power
  constraints. It is operator reference only and grants no new write authority.

## Reporting behavior

`alpaca reference-snapshot` writes the full local catalog audit. The daily email
receives only a material summary, such as a stale session/feed warning; full
route status and provenance remain in local JSON. Documentation drift by itself
does not mark trading unhealthy or authorize an action.
