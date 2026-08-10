# Flat TradingAgents Repository Consolidation Design

Date: 2026-08-10

## Objective

Make `/Users/corbinfloyd/Documents/TradingAgents` the single canonical location
for opening Codex, using Git, running the TradingAgents Python project, reading
operational context, and maintaining the local runtime. Consolidate the
Windows-transfer envelope, registered worktrees, standalone public clone, and
historical supporting material without losing recoverable history, current
working-tree changes, local credentials, or unique artifacts.

## Current State

The outer directory is the Git root and Windows-to-Mac transfer envelope. The
runnable Python application is nested at `01_REPO/tradingagents-main`. A healthy
launchd-managed n8n bridge imports the package from that nested application.
Ten Codex automation definitions refer to the TradingAgents workspace and are
currently paused. The active `master` checkout contains tracked modifications
and untracked project files. Two clean registered worktrees preserve the
`fable` and `codex/autonomous-trading-firm` branches. A separate clean public
clone exists at `/Users/corbinfloyd/Documents/TradingAgentsAlpaca-public`.

## Selected Structure

The runnable project moves directly into the Git root:

```text
/Users/corbinfloyd/Documents/TradingAgents/
├── AGENTS.md
├── README.md
├── CONTEXT_ROUTER.md
├── pyproject.toml
├── uv.lock
├── .env
├── .venv/
├── cli/
├── tradingagents/
├── tests/
├── scripts/
├── config/
├── docs/
├── results/
├── reports/
├── research/
├── n8n/
├── assets/
└── archive/
    ├── windows-transfer-2026-07-11/
    ├── public-release-2026-07-17/
    ├── inactive-checkouts/
    └── consolidation-manifests/
```

Only `.gitignore` collides between the outer and inner roots. The application
ignore rules become the canonical base, augmented with archive and local
consolidation entries. The original outer ignore rule for the fable worktree is
retained until that registered checkout has been archived and unregistered.

## Preservation Model

Before relocation, create a timestamped consolidation manifest containing:

- Git root, HEAD, branch, worktree registrations, refs, remotes, and status.
- Tracked, untracked, ignored, environment, dependency, generated-result,
  binary, symlink, and archive inventories.
- File sizes, modes, timestamps, and SHA-256 hashes for preservation-critical
  files.
- The active `.env` hash and mode without recording its contents.
- Live process command, PID, working directory, package import path, launchd
  label, and health response.
- Every active absolute path reference found in repository files, automation
  definitions, launchd plists, and local runner wrappers.

Create a local pre-consolidation Git checkpoint that records the current
non-secret tracked and project-authored untracked work before the layout commit.
Record the checkpoint explicitly as a preservation snapshot rather than a test
or release claim.

The clean `fable` and `codex/autonomous-trading-firm` histories remain as Git
branches. Each physical checkout receives a compressed recovery archive for
ignored or machine-local material, plus a manifest and restore note. After the
archive hash is verified, unregister the duplicate worktree path while keeping
its branch.

The clean standalone public clone receives a Git bundle containing its refs,
a source snapshot, a manifest, and remote metadata under
`archive/public-release-2026-07-17/`. Verify the bundle before retiring the
external checkout.

The MiroFish tree and transfer-era context, automation snapshots, setup files,
validation records, and original start document move into
`archive/windows-transfer-2026-07-11/`. Generated dependency trees remain
recoverable as local archives or manifests rather than presenting as current
TradingAgents source.

## Relocation Sequence

1. Capture pre-move manifests and recovery artifacts.
2. Create the pre-consolidation Git checkpoint.
3. Quiesce the launchd n8n bridge immediately before its executable path moves.
4. Move the application tree into the canonical root, preserving modes and
   local state.
5. Merge `.gitignore` intentionally and relocate the Windows-transfer material.
6. Update repository-owned absolute paths from the nested application path to
   the canonical root.
7. Update the ten automation definitions and their current memory files while
   preserving each automation status, schedule, model, prompt meaning, and
   execution configuration.
8. Update the n8n runner wrapper and launchd plist, reload the service, and
   confirm its new working directory and import source.
9. Archive and unregister the inactive worktrees, then archive the public clone.
10. Remove empty obsolete task directories after exact enumeration and
    verification that they contain no files, links, mounts, or repository
    metadata.
11. Generate final manifests and the consolidation report.

## Repository Inspection for AGENTS.md

Build the root `AGENTS.md` only after the canonical layout exists. Inventory
every file under the canonical root. Semantically inspect every
repository-authored Markdown, source, test, configuration, shell, PowerShell,
TOML, YAML, and operational JSON file relevant to project behavior. Use the
codebase graph for symbols, call paths, entrypoints, and architecture, paired
with direct reads for documentation, scripts, manifests, packets, and exact
strings. Classify generated environments, dependencies, caches, binary
documents, media, and historical result packets by type, size, provenance, and
hash.

The resulting `AGENTS.md` uses positive operating guidance. It covers the
canonical root, project map, task routing, current Mac entrypoints, context
refresh, configuration, runtime evidence, testing, documentation, Git hygiene,
automation surfaces, MiroFish archive, and completion evidence. A language scan
checks the finished file for prohibition-oriented directives and rewrites them
as affirmative workflows.

## Runtime and Configuration Migration

The following active path surfaces move to the canonical root:

- Repository scripts and current documentation containing the nested path.
- Ten TradingAgents automation definitions.
- Current automation memory files that direct future runs.
- `/Users/corbinfloyd/Library/LaunchAgents/com.tradingagents.n8n-runner.plist`.
- `/Users/corbinfloyd/.local/bin/tradingagents-n8n-runner`.

Historical files placed inside the transfer archive retain their original paths
as provenance. A final path scan distinguishes archived historical references
from active configuration and requires zero active references to
`01_REPO/tradingagents-main`.

The consolidation changes filesystem organization and runtime paths. It
preserves automation statuses, live-control contents, strategy configuration,
broker state, result packets, and trading behavior.

## Verification

Filesystem and preservation checks:

- Compare pre-move and post-move manifests for every preserved class.
- Verify recovery archive and Git bundle hashes.
- Verify the `.env` hash and `0600` mode.
- Verify symlink targets and virtual-environment executables.
- Verify Git refs, worktree registrations, `git fsck`, status, and branch
  divergence records.

Project checks from `/Users/corbinfloyd/Documents/TradingAgents`:

- Import `tradingagents` and confirm its resolved source path is under the root.
- Run CLI help and current read-only health/context commands.
- Run focused tests covering CLI, automation context, n8n runner, launchd/mac
  wrappers, and path-sensitive behavior.
- Run Ruff and the broad pytest suite, recording exact outcomes and pre-existing
  failures separately.

Runtime checks:

- Parse every automation TOML and compare all fields except path replacements.
- Confirm every automation remains at its pre-move status.
- Confirm launchd reports the runner as active with the canonical working
  directory.
- Confirm the runner health endpoint returns `status=ok`.
- Confirm the live process imports package code from the canonical root.
- Scan active configuration for the former nested path and report zero matches.

Repository knowledge checks:

- Reindex the canonical root in codebase-memory-mcp.
- Verify the indexed root, branch, counts, exclusions, and changed-path coverage.
- Produce a final `CONSOLIDATION_REPORT.md` linking manifests, archives, runtime
  evidence, verification commands, and the canonical start instructions.

## Recovery

The pre-consolidation checkpoint, branch refs, compressed checkout archives,
public Git bundle, file manifests, and original path inventory provide the
recovery surfaces. The service stays stopped only during the short path switch.
If verification fails, restore the former runner path from the recorded launchd
and wrapper snapshots, then use the manifests to identify the incomplete move.

## Completion Criteria

The work is complete when:

1. `/Users/corbinfloyd/Documents/TradingAgents` is simultaneously the Git,
   Codex, Python project, test, script, result, and runtime root.
2. All identified TradingAgents checkouts are represented under the canonical
   root as active content, branches, verified archives, or provenance records.
3. Active configurations contain no former nested application path.
4. The local runner is healthy from the canonical root.
5. Git history, current work, credentials, and unique artifacts are accounted
   for by verified preservation evidence.
6. Root `AGENTS.md` accurately describes the consolidated project using
   affirmative operating guidance.
7. Final manifests, test results, index state, and consolidation report are
   saved inside the canonical repository.
