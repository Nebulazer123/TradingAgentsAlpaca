// Generates importable n8n workflow JSON for the TradingAgents observer wrappers.
// Each workflow is a manual trigger chained through one or more READ-ONLY job
// calls to the local runner bridge (POST http://host.docker.internal:8765/run
// with body {"job": "<name>"}). None of these jobs can submit orders.
//
//   node n8n/generate-workflows.mjs
//
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "workflows");
mkdirSync(outDir, { recursive: true });

const RUNNER_URL = "http://host.docker.internal:8765/run";
const DATA_TABLE_LOCATOR = {
  mode: "list",
  value: "TradingAgents_Automation_Evaluations",
  cachedResultName: "TradingAgents_Automation_Evaluations",
};

// name -> ordered list of allowlisted jobs (see config/n8n_tradingagents_allowlist.json)
const WORKFLOWS = [
  ["TA · Hourly Supervisor (observer)", ["context_snapshot", "execution_board_review"]],
  ["TA · Paper Tournament (observer)", ["context_snapshot", "agent_ledger_summary"]],
  ["TA · Overnight Planner (observer)", ["context_snapshot", "creator_workflow_status", "source_quality_review", "agent_ledger_update", "agent_ledger_summary"]],
  ["TA · Pre-Open Supervisor (observer)", ["pre_open_context_refresh", "source_quality_review"]],
  ["TA · Post-Open Supervisor (observer)", ["context_snapshot", "execution_board_review"]],
  ["TA · Pre-Close Supervisor (observer)", ["context_snapshot", "execution_board_review"]],
  ["TA · After-Close Supervisor (observer)", ["context_snapshot", "agent_ledger_update", "agent_ledger_summary", "outcome_labeling"]],
  ["TA · Daily Report Preview (observer)", ["daily_report_preview"]],
  ["TA · Health + Self-Heal (observer)", ["automation_health_audit", "self_heal_plan"]],
  ["TA · Sync Evaluation Dataset (observer)", ["n8n_evaluation_dataset"]],
  ["TA · Automation Evaluations (observer)", ["n8n_evaluation_dataset", "automation_health_audit", "source_quality_review", "self_heal_plan"]],
];

function slug(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function httpNode(job, index) {
  return {
    parameters: {
      method: "POST",
      url: RUNNER_URL,
      sendBody: true,
      specifyBody: "json",
      jsonBody: JSON.stringify({ job }),
      options: { timeout: 120000 },
    },
    id: `job-${index}-${slug(job)}`,
    name: job,
    type: "n8n-nodes-base.httpRequest",
    typeVersion: 4.2,
    position: [320 + index * 240, 300],
  };
}

function buildWorkflow(name, jobs) {
  const trigger = {
    parameters: {},
    id: "manual-trigger",
    name: "Run observer",
    type: "n8n-nodes-base.manualTrigger",
    typeVersion: 1,
    position: [80, 300],
  };
  const jobNodes = jobs.map((j, i) => httpNode(j, i));
  const nodes = [trigger, ...jobNodes];

  // Connect trigger -> job0 -> job1 -> ... sequentially.
  const connections = {};
  const chain = [trigger, ...jobNodes];
  for (let i = 0; i < chain.length - 1; i++) {
    connections[chain[i].name] = {
      main: [[{ node: chain[i + 1].name, type: "main", index: 0 }]],
    };
  }

  return {
    name,
    nodes,
    connections,
    settings: { executionOrder: "v1" },
    active: false,
    tags: [{ name: "tradingagents" }, { name: "observer" }],
  };
}

function buildNativeEvaluationWorkflow() {
  const trigger = {
    parameters: {
      source: "dataTable",
      dataTableId: DATA_TABLE_LOCATOR,
      limitRows: true,
      maxRows: 25,
    },
    id: "evaluation-trigger",
    name: "Fetch evaluation case",
    type: "n8n-nodes-base.evaluationTrigger",
    typeVersion: 4.7,
    position: [80, 300],
  };
  const runJob = {
    parameters: {
      method: "POST",
      url: RUNNER_URL,
      sendBody: true,
      specifyBody: "json",
      jsonBody: "={{ JSON.parse($json.request_json) }}",
      options: { timeout: 120000 },
    },
    continueOnFail: true,
    id: "run-allowlisted-job",
    name: "Run allowlisted job",
    type: "n8n-nodes-base.httpRequest",
    typeVersion: 4.2,
    position: [320, 300],
  };
  const calculateMetrics = {
    parameters: {
      jsCode: `const sourceRow = $('Fetch evaluation case').item.json;
const response = $input.item.json || {};

function parseJson(value, fallback = {}) {
  if (value && typeof value === 'object') return value;
  if (typeof value !== 'string' || !value.trim()) return fallback;
  try { return JSON.parse(value); } catch { return fallback; }
}

const expected = parseJson(sourceRow.expected_json);
const body = response.body && typeof response.body === 'object' ? response.body : response;
const statusCode = Number(response.statusCode || response.status || body.statusCode || sourceRow.expected_http_status || 0);
const actualStatus = String(body.status || body.error?.status || (response.error ? 'error' : 'ok'));
const expectedHttp = Number(sourceRow.expected_http_status || 0);
const expectedStatus = String(sourceRow.expected_status || expected.status || '');
const httpStatusMatch = statusCode === expectedHttp ? 1 : 0;
const statusMatch = actualStatus === expectedStatus ? 1 : 0;
const compactContractMatch = body.compact_output_only === true || body.summary?.compact_output_only === true ? 1 : 0;
const noSubmitContractMatch = body.submit_capable === false || body.can_submit_orders === false || body.summary?.submit_capable === false ? 1 : 0;
const safetyContractScore = (httpStatusMatch + statusMatch + compactContractMatch + noSubmitContractMatch) / 4;

return [{
  json: {
    ...sourceRow,
    actual_http_status: statusCode || '',
    actual_status: actualStatus,
    actual_json: JSON.stringify(body).slice(0, 5000),
    actual_quality_score: safetyContractScore,
    actual_checked_at: new Date().toISOString(),
    actual_error: response.error?.message || body.error || '',
    metric_http_status_match: httpStatusMatch,
    metric_status_match: statusMatch,
    metric_compact_contract_match: compactContractMatch,
    metric_no_submit_contract_match: noSubmitContractMatch,
    metric_safety_contract_score: safetyContractScore,
  },
}];`,
    },
    id: "calculate-evaluation-metrics",
    name: "Calculate evaluation metrics",
    type: "n8n-nodes-base.code",
    typeVersion: 2,
    position: [560, 300],
  };
  const setOutputs = {
    parameters: {
      operation: "setOutputs",
      source: "dataTable",
      dataTableId: DATA_TABLE_LOCATOR,
      outputs: {
        values: [
          { outputName: "actual_http_status", outputValue: "={{ $json.actual_http_status }}" },
          { outputName: "actual_status", outputValue: "={{ $json.actual_status }}" },
          { outputName: "actual_json", outputValue: "={{ $json.actual_json }}" },
          { outputName: "actual_quality_score", outputValue: "={{ $json.actual_quality_score }}" },
          { outputName: "actual_checked_at", outputValue: "={{ $json.actual_checked_at }}" },
          { outputName: "actual_error", outputValue: "={{ $json.actual_error }}" },
        ],
      },
    },
    id: "set-evaluation-outputs",
    name: "Set evaluation outputs",
    type: "n8n-nodes-base.evaluation",
    typeVersion: 4.8,
    position: [800, 300],
  };
  const setMetrics = {
    parameters: {
      operation: "setMetrics",
      metric: "customMetrics",
      metrics: {
        assignments: [
          { id: "http-status-match", name: "http_status_match", value: "={{ $json.metric_http_status_match }}", type: "number" },
          { id: "status-match", name: "status_match", value: "={{ $json.metric_status_match }}", type: "number" },
          { id: "compact-contract-match", name: "compact_contract_match", value: "={{ $json.metric_compact_contract_match }}", type: "number" },
          { id: "no-submit-contract-match", name: "no_submit_contract_match", value: "={{ $json.metric_no_submit_contract_match }}", type: "number" },
          { id: "safety-contract-score", name: "safety_contract_score", value: "={{ $json.metric_safety_contract_score }}", type: "number" },
        ],
      },
    },
    id: "set-evaluation-metrics",
    name: "Set evaluation metrics",
    type: "n8n-nodes-base.evaluation",
    typeVersion: 4.8,
    position: [1040, 300],
  };
  return {
    id: "taBuiltInAutomationEvaluation",
    name: "TA · Built-in Automation Evaluation",
    nodes: [trigger, runJob, calculateMetrics, setOutputs, setMetrics],
    connections: {
      [trigger.name]: { main: [[{ node: runJob.name, type: "main", index: 0 }]] },
      [runJob.name]: { main: [[{ node: calculateMetrics.name, type: "main", index: 0 }]] },
      [calculateMetrics.name]: { main: [[{ node: setOutputs.name, type: "main", index: 0 }]] },
      [setOutputs.name]: { main: [[{ node: setMetrics.name, type: "main", index: 0 }]] },
    },
    settings: { executionOrder: "v1" },
    active: false,
    tags: [{ name: "tradingagents" }, { name: "evaluation" }, { name: "observer" }],
  };
}

let count = 0;
for (const [name, jobs] of WORKFLOWS) {
  const wf = buildWorkflow(name, jobs);
  const file = join(outDir, `${slug(name)}.json`);
  writeFileSync(file, JSON.stringify(wf, null, 2) + "\n");
  count++;
  console.log("wrote", file);
}
{
  const wf = buildNativeEvaluationWorkflow();
  const file = join(outDir, `${slug(wf.name)}.json`);
  writeFileSync(file, JSON.stringify(wf, null, 2) + "\n");
  count++;
  console.log("wrote", file);
}
console.log(`\nDone: ${count} workflow files in ${outDir}`);
