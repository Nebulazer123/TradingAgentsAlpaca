#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  HeadingLevel,
  LevelFormat,
  PageNumber,
  PageOrientation,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} = require("docx");

const root = path.resolve(__dirname, "..");
const catalog = JSON.parse(
  fs.readFileSync(path.join(root, "config/alpaca_api_reference_catalog.json"), "utf8"),
);
const compact = JSON.parse(
  fs.readFileSync(path.join(root, "results/_context/latest-summary.json"), "utf8"),
);
const liveControl = JSON.parse(
  fs.readFileSync(path.join(root, "results/policy/live_control.json"), "utf8"),
);

const args = Object.fromEntries(
  process.argv.slice(2).map((item) => {
    const [key, ...rest] = item.replace(/^--/, "").split("=");
    return [key, rest.join("=")];
  }),
);
const output = path.resolve(
  args.output || path.join(root, "docs/history/TradingAgents_Autonomy_Catch_Up_2026-08-11.docx"),
);
const accountAsOf = args["account-as-of"] || "2026-08-11T09:42:00+00:00";
const accountFacts = {
  paper: {
    status: args["paper-status"] || "ACTIVE",
    buyingPower: args["paper-buying-power"] || "360263.06",
    equity: args["paper-equity"] || "98810.78",
  },
  live: {
    status: args["live-status"] || "ACTIVE",
    buyingPower: args["live-buying-power"] || "109.22",
    equity: args["live-equity"] || "204.16",
  },
};

const navy = "17324D";
const blue = "2D6A8A";
const paleBlue = "DDEBF3";
const paleYellow = "FFF2CC";
const paleRed = "FCE4D6";
const gray = "666666";
const white = "FFFFFF";
const border = { style: BorderStyle.SINGLE, size: 1, color: "B7C6D1" };
const borders = { top: border, bottom: border, left: border, right: border };

function run(text, options = {}) {
  return new TextRun({ text: String(text), font: "Arial", size: 20, ...options });
}

function paragraph(text, options = {}) {
  return new Paragraph({
    spacing: { after: 120, line: 276 },
    ...options,
    children: Array.isArray(text) ? text : [run(text)],
  });
}

function heading(text, level = HeadingLevel.HEADING_1) {
  return new Paragraph({
    heading: level,
    children: [run(text, { bold: true, color: navy })],
  });
}

function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "report-bullets", level },
    spacing: { after: 80, line: 260 },
    children: [run(text)],
  });
}

function cell(text, width, options = {}) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: options.fill
      ? { fill: options.fill, type: ShadingType.CLEAR }
      : undefined,
    margins: { top: 70, bottom: 70, left: 90, right: 90 },
    children: [
      new Paragraph({
        spacing: { after: 0 },
        children: [
          new TextRun({
            text: String(text ?? ""),
            font: "Arial",
            size: options.size || 17,
            bold: Boolean(options.bold),
            color: options.color,
          }),
        ],
      }),
    ],
  });
}

function table(headers, rows, widths, options = {}) {
  const total = widths.reduce((sum, value) => sum + value, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((header, index) =>
          cell(header, widths[index], { fill: navy, bold: true, color: white, size: options.headerSize || 17 }),
        ),
      }),
      ...rows.map(
        (row, rowIndex) =>
          new TableRow({
            cantSplit: true,
            children: row.map((value, index) =>
              cell(value, widths[index], {
                fill: rowIndex % 2 === 0 ? "F7FAFC" : white,
                size: options.bodySize || 16,
              }),
            ),
          }),
      ),
    ],
  });
}

function link(label, url) {
  return new ExternalHyperlink({
    link: url,
    children: [run(label, { color: blue, underline: {} })],
  });
}

const methodCounts = catalog.counts.methods;
const apiCounts = catalog.endpoints.reduce((acc, endpoint) => {
  acc[endpoint.api] = (acc[endpoint.api] || 0) + 1;
  return acc;
}, {});
const runtimeCounts = catalog.endpoints.reduce((acc, endpoint) => {
  acc[endpoint.runtime_class] = (acc[endpoint.runtime_class] || 0) + 1;
  return acc;
}, {});
const currentFlags = compact.flags || [];
const generatedAt = compact.generated_at || "unknown";

const portraitChildren = [
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 900, after: 260 },
    children: [run("TradingAgents Autonomy Catch-Up", { bold: true, size: 40, color: navy })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 180 },
    children: [run("Alpaca documentation expansion and regulatory correction", { size: 25, color: blue })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 560 },
    children: [run("Revision dated August 11, 2026", { bold: true, size: 22 })],
  }),
  paragraph("This is a new revision. The July 26 DOCX and PDF remain preserved as historical artifacts."),
  table(
    ["Evidence surface", "As of", "Current result"],
    [
      ["Alpaca MCP documentation", "2026-08-11", "Server 2.2.1; five read-only documentation tools"],
      ["Endpoint catalog", catalog.generated_at, `${catalog.counts.paths} paths; ${catalog.counts.operations} operations`],
      ["Compact runtime context", generatedAt, `${currentFlags.length} drill-down flag(s); observer/fail-closed posture`],
      ["Alpaca account connectivity", accountAsOf, "Paper and live endpoints answered read-only checks"],
    ],
    [2500, 2200, 4660],
  ),

  heading("Executive summary"),
  paragraph(
    "Alpaca's Trading MCP Server now exposes read-only documentation context to connected assistants. TradingAgents can use a complete, versioned endpoint catalog and a structurally GET-only client without expanding order or account-mutation authority.",
  ),
  bullet("The new tools inspect documentation; the broader Alpaca MCP server still includes mutation-capable trading tools."),
  bullet("The verified inventory is 83 paths and 99 operations: 77 GET and 22 non-GET."),
  bullet("All non-GET operations are cataloged for operator reference and rejected before network access by the new client."),
  bullet("The daily email receives only material feed/session/coverage warnings; complete route details remain in local JSON."),
  bullet("A prior June 4 PDT effective-date claim was unsupported and is corrected throughout current runtime guidance."),

  heading("What Alpaca added"),
  paragraph("The following five documentation tools are read-only and remain available independently of normal MCP toolset filtering:"),
  ...catalog.documentation_tools.map((tool) => bullet(tool)),
  paragraph([
    run("Primary upstream evidence: "),
    link("Alpaca MCP repository", "https://github.com/alpacahq/alpaca-mcp-server"),
    run(" and "),
    link("documentation-tool commit", "https://github.com/alpacahq/alpaca-mcp-server/commit/d86619172814441ac0ec2dccc2962b873c0193dc"),
    run("."),
  ]),

  heading("Coverage and implementation classification"),
  table(
    ["API", "Operations", "Current use"],
    [
      ["Trading", apiCounts.trading, "Read-only observer/reference routes; mutations documented only"],
      ["Market Data", apiCounts.market_data, "Quotes, trades, bars, events, metadata, and on-demand families"],
      ["Authentication", apiCounts.authentication, "Token POST documented only; never callable by reference client"],
    ],
    [2200, 1600, 5560],
  ),
  paragraph(" "),
  table(
    ["Method", "Count", "Runtime treatment"],
    [
      ["GET", methodCounts.GET, "Allowlisted read-only route ID required"],
      ["POST", methodCounts.POST, "Documented; not callable"],
      ["DELETE", methodCounts.DELETE, "Documented; not callable"],
      ["PATCH", methodCounts.PATCH, "Documented; not callable"],
      ["PUT", methodCounts.PUT, "Documented; not callable"],
    ],
    [2200, 1600, 5560],
  ),
  paragraph("The complete 99-row operation matrix appears in the landscape appendix and in config/alpaca_api_reference_catalog.json."),

  heading("Newly usable information"),
  bullet("Explicit stock feeds: SIP, IEX, delayed SIP, BOATS, overnight, and OTC, subject to subscription. TradingAgents now records feed provenance."),
  bullet("Latest trades are filtered price context, not a complete tape, because some trade conditions do not update bar price."),
  bullet("Calendar data can preserve session_open, session_close, settlement_date, and TRADING versus SETTLEMENT date type."),
  bullet("Corporate actions and two event streams are available; streams remain disabled by default and are capped by time and event count."),
  bullet("Options, crypto, screeners, auctions, forex, fixed income, logos, wallets, locates, tokenization, and related families are available on demand rather than broadly polled."),
  bullet("Replace-order constraints and race behavior are retained as operator documentation only; no new replace/cancel/submit route was added."),

  heading("Authority and safety boundary"),
  table(
    ["Capability", "Status", "Boundary"],
    [
      ["Documentation search/inspection", "Enabled", "Read-only external text; treat as untrusted source material"],
      ["Cataloged GET reference reads", "Enabled", "Stable route IDs only; analysis_only=true; execution_authority=none"],
      ["SSE event reads", "Opt-in", "Only two allowlisted GET streams; hard timeout and event cap"],
      ["Order/account mutations", "Unchanged", "No new authority; existing deterministic broker gates remain"],
      ["OAuth token POST", "Disabled", "Inventory/documentation only"],
    ],
    [2800, 1400, 5160],
  ),

  heading("Material regulatory correction"),
  paragraph(
    "The earlier report/runtime treated June 4, 2026 as a universal effective date for FINRA's replacement of the pattern day trader framework and cited FINRA Notice 25-14. That notice concerns a different subject. Current code no longer treats the calendar date alone as proof of adoption.",
  ),
  paragraph(
    "SEC Release 34-105226 approved SR-FINRA-2025-017 on April 14, 2026, but requires FINRA to announce the effective date in a separate Regulatory Notice and permits phased implementation. Current runtime status is approved_pending_finra_notice_or_broker_adoption. Account-specific activation defaults to unknown and requires fresh broker evidence or an explicit operator-attested adoption record.",
  ),
  paragraph([
    link("SEC rulemaking page", "https://www.sec.gov/rules-regulations/self-regulatory-organization-rulemaking/sr-finra-2025-017"),
    run(" · "),
    link("SEC approval order", "https://www.sec.gov/files/rules/sro/finra/2026/34-105226.pdf"),
    run(" · "),
    link("FINRA filing", "https://www.finra.org/rules-guidance/rule-filings/sr-finra-2025-017"),
    run(" · "),
    link("Alpaca transition guide", "https://docs.alpaca.markets/us/docs/understanding-finras-new-intraday-margin-rule-and-the-end-of-pdt"),
  ]),

  heading("Current read-only operational snapshot"),
  paragraph(`Account values below came from a read-only connectivity check at ${accountAsOf}. They establish connectivity, not trading authority.`),
  table(
    ["Mode", "Status", "Buying power", "Equity"],
    [
      ["Paper", accountFacts.paper.status, accountFacts.paper.buyingPower, accountFacts.paper.equity],
      ["Live", accountFacts.live.status, accountFacts.live.buyingPower, accountFacts.live.equity],
    ],
    [1900, 1900, 2780, 2780],
  ),
  paragraph("Live trading remains frozen. The current live-control reason is retained below because healthy account connectivity does not override authority evidence:"),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [
      new TableRow({
        children: [cell(liveControl.reason, 9360, { fill: paleRed, size: 17 })],
      }),
    ],
  }),
  paragraph(`The compact context refreshed at ${generatedAt} still identifies stale/drill-down work. No order was submitted, replaced, canceled, or otherwise managed during this update.`),

  heading("Files and reporting changes"),
  bullet("config/alpaca_api_reference_catalog.json - complete versioned inventory and runtime classification."),
  bullet("tradingagents/dataflows/alpaca_reference.py - fail-closed GET-only route client, bundle collector, bounded streams, and audit summary."),
  bullet("tradingagents/dataflows/alpaca_market_data.py - explicit feed provenance and filtered-tape caveat."),
  bullet("tradingagents/brokers/supervisor/daily_report.py and cli/main.py - material-only email summary plus full local reference snapshot."),
  bullet("tradingagents/research/market_structure.py and dependent overnight/hourly paths - pending/adoption-evidence regulatory model."),
  bullet("docs/alpaca and docs/regulatory - durable documentation and supersession notice."),
  paragraph("Historical July DOCX/PDF files remain untouched. This August 11 revision is the current report for these changes."),
];

const appendixRows = catalog.endpoints.map((endpoint) => [
  endpoint.id,
  endpoint.method,
  endpoint.path,
  endpoint.runtime_class,
  endpoint.report_visibility,
]);

const footer = new Footer({
  children: [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [run("TradingAgents · August 11, 2026 · Page ", { color: gray, size: 16 }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: gray })],
    }),
  ],
});

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      {
        id: "Heading1",
        name: "Heading 1",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: "Arial", size: 29, bold: true, color: navy },
        paragraph: { spacing: { before: 300, after: 140 }, outlineLevel: 0 },
      },
      {
        id: "Heading2",
        name: "Heading 2",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: "Arial", size: 24, bold: true, color: blue },
        paragraph: { spacing: { before: 220, after: 100 }, outlineLevel: 1 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "report-bullets",
        levels: [
          {
            level: 0,
            format: LevelFormat.BULLET,
            text: "•",
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 520, hanging: 260 } } },
          },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 900, right: 900, bottom: 900, left: 900 },
        },
      },
      footers: { default: footer },
      children: portraitChildren,
    },
    {
      properties: {
        type: "nextPage",
        page: {
          size: { width: 12240, height: 15840, orientation: PageOrientation.LANDSCAPE },
          margin: { top: 650, right: 650, bottom: 700, left: 650 },
        },
      },
      footers: { default: footer },
      children: [
        heading("Appendix: complete 99-operation Alpaca catalog"),
        paragraph("Every row is documentation/reference inventory. Only GET rows are callable through the new allowlisted client; bounded streams require explicit opt-in."),
        table(
          ["Stable route ID", "Method", "Path", "Runtime class", "Report"],
          appendixRows,
          [4300, 1100, 4300, 2700, 1900],
          { bodySize: 13, headerSize: 14 },
        ),
      ],
    },
  ],
});

fs.mkdirSync(path.dirname(output), { recursive: true });
Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(output, buffer);
  process.stdout.write(`${output}\n`);
});
