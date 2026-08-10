# Flat TradingAgents Repository Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/Users/corbinfloyd/Documents/TradingAgents` the single Git, Codex, Python project, runtime, documentation, and archive root while preserving current work, history, credentials, and unique artifacts.

**Architecture:** Flatten the live application from `01_REPO/tradingagents-main` into the existing Git root. Preserve transfer-era and inactive-checkout material under a clearly labeled `archive/`, retain clean development histories as branches, and migrate every active absolute path before restarting the local runner. Finish with repository-wide inventory, affirmative root agent guidance, graph reindexing, and requirement-by-requirement verification.

**Tech Stack:** Git worktrees and bundles, macOS launchd, zsh, Python 3.13 virtual environment, uv, pytest, Ruff, TOML, SHA-256 manifests, codebase-memory-mcp.

## Global Constraints

- Canonical root: `/Users/corbinfloyd/Documents/TradingAgents`.
- Former application root: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main`.
- Preserve current tracked modifications, project-authored untracked files, Git refs, credentials, result packets, modes, timestamps, and unique ignored artifacts.
- Preserve all ten automation statuses and non-path configuration fields.
- Preserve `results/policy/live_control.json`, broker state, strategy configuration, result packets, and trading behavior.
- Keep historical former-path references only inside the Windows-transfer archive; active configuration must have zero former-path references.
- Build root `AGENTS.md` after the canonical layout exists and use affirmative operating guidance without prohibition-oriented directives.
- Use exact, validated targets for archive, worktree removal, task-directory cleanup, and service reload operations.
- Save preservation and verification evidence under `archive/consolidation-manifests/` and `docs/consolidation/`.

---

### Task 1: Capture Preservation Evidence and Create the Pre-Consolidation Checkpoint

**Files:**
- Create: `archive/consolidation-manifests/2026-08-10/pre-move-git.txt`
- Create: `archive/consolidation-manifests/2026-08-10/pre-move-files.tsv`
- Create: `archive/consolidation-manifests/2026-08-10/pre-move-runtime.txt`
- Create: `archive/consolidation-manifests/2026-08-10/pre-move-path-references.txt`
- Create: `archive/consolidation-manifests/2026-08-10/pre-move-secrets-metadata.tsv`
- Create: `archive/consolidation-manifests/2026-08-10/pre-move-ignored.txt`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Current filesystem, Git, process, launchd, automation, and environment metadata.
- Produces: Immutable evidence used by Tasks 2-9 to prove preservation and detect drift.

- [ ] **Step 1: Validate all source and destination roots**

Run:

```zsh
test -d /Users/corbinfloyd/Documents/TradingAgents/.git
test -d /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main/tradingagents
test -d /Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm
test -d /Users/corbinfloyd/Documents/TradingAgentsAlpaca-public/.git
git -C /Users/corbinfloyd/Documents/TradingAgents rev-parse --show-toplevel
```

Expected: every `test` succeeds and Git prints `/Users/corbinfloyd/Documents/TradingAgents`.

- [ ] **Step 2: Create the evidence directories and extend ignore coverage**

Create `archive/consolidation-manifests/2026-08-10/`, `archive/inactive-checkouts/`, and `docs/consolidation/`. Merge the application `.gitignore` into the root `.gitignore`, retaining the temporary fable-worktree ignore and adding:

```gitignore
archive/inactive-checkouts/*.tar.gz
archive/inactive-checkouts/*.zip
archive/inactive-checkouts/*.bundle
archive/consolidation-manifests/**/private-*
```

Expected: the canonical ignore file covers Python, environments, results, credentials, generated state, and compressed local recovery archives.

- [ ] **Step 3: Record Git state**

Run exact read-only Git commands and redirect their combined output to `pre-move-git.txt`:

```zsh
git status --short --ignored
git log -1 --decorate --date=iso --format=fuller
git branch -vv
git worktree list --porcelain
git remote -v
git show-ref
git rev-list --left-right --count master...codex/autonomous-trading-firm
git rev-list --left-right --count master...fable
```

Expected: the file records `master`, `fable`, `codex/autonomous-trading-firm`, and all three worktree paths.

- [ ] **Step 4: Record every source file and preservation-critical hash**

Use `find ... -print0` plus `stat` and `shasum -a 256` to write a tab-separated record of path, type, mode, size, modification time, and SHA-256 for regular files across the canonical root, the autonomous worktree, and the public clone. Record symlink targets without traversing them.

Expected: `pre-move-files.tsv` contains records for all three source roots and no file contents or secret values.

- [ ] **Step 5: Record credentials metadata without contents**

Inventory files named `.env`, `*.env`, `*.pem`, `*.key`, `*.token`, and matching local credential patterns. Save only path, mode, size, modification time, and SHA-256 in `pre-move-secrets-metadata.tsv`.

Expected: the active and fable `.env` hashes match and the active `.env` mode is `0600`.

- [ ] **Step 6: Record runtime and path references**

Capture `ps`, `lsof -a -p <runner-pid> -d cwd,txt`, `launchctl print gui/$(id -u)/com.tradingagents.n8n-runner`, runner health, package import path, the runner wrapper metadata, and plist metadata in `pre-move-runtime.txt`. Run exact-string `rg` for the former application root across the repository, `.codex/automations`, `Library/LaunchAgents`, and `.local/bin`, saving results to `pre-move-path-references.txt`.

Expected: evidence identifies the live runner, ten automation definitions, current memory files, launchd plist, local wrapper, and repository-owned references.

- [ ] **Step 7: Create a recoverable Git checkpoint**

Stage current tracked changes and project-authored untracked files while ignored credentials, environments, results, and caches remain excluded. Review `git diff --cached --stat`, `git diff --cached --check`, and `git status --short`, then commit:

```zsh
git commit -m "chore: checkpoint TradingAgents before repository consolidation"
```

Expected: the checkpoint includes current non-secret project work and is explicitly described as preservation, not release verification.

---

### Task 2: Archive Inactive Checkouts and Preserve Their Git Histories

**Files:**
- Create: `archive/inactive-checkouts/tradingagents-autonomous-firm-2026-08-10.tar.gz`
- Create: `archive/inactive-checkouts/tradingagents-fable-2026-08-10.tar.gz`
- Create: `archive/inactive-checkouts/TradingAgentsAlpaca-public-2026-08-10.tar.gz`
- Create: `archive/inactive-checkouts/TradingAgentsAlpaca-public-2026-08-10.bundle`
- Create: `archive/inactive-checkouts/SHA256SUMS.txt`
- Create: `archive/inactive-checkouts/README.md`

**Interfaces:**
- Consumes: Task 1 source inventory and Git refs.
- Produces: Verified recovery artifacts that allow duplicate physical checkouts to be retired without losing tracked or ignored state.

- [ ] **Step 1: Revalidate each checkout immediately before archiving**

Confirm exact realpaths, directory types, Git top levels, branches, status, and absence of nested symlink escapes for:

```text
/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm
/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-fable
/Users/corbinfloyd/Documents/TradingAgentsAlpaca-public
```

Expected: autonomous and fable are clean registered worktrees; public is a clean standalone repository on `main`.

- [ ] **Step 2: Create full recovery archives**

Create each archive from its parent directory using the exact checkout basename. Include Git metadata, ignored local files, environments, caches, and results so the archive represents the full source directory.

Expected: all three archives are non-empty and `tar -tzf` lists their expected top-level directory.

- [ ] **Step 3: Create and verify the public Git bundle**

Run:

```zsh
git -C /Users/corbinfloyd/Documents/TradingAgentsAlpaca-public bundle create /Users/corbinfloyd/Documents/TradingAgents/archive/inactive-checkouts/TradingAgentsAlpaca-public-2026-08-10.bundle --all
git bundle verify /Users/corbinfloyd/Documents/TradingAgents/archive/inactive-checkouts/TradingAgentsAlpaca-public-2026-08-10.bundle
```

Expected: bundle verification reports every public-clone ref as complete.

- [ ] **Step 4: Hash and test every recovery artifact**

Write SHA-256 hashes to `SHA256SUMS.txt`, run `shasum -a 256 -c SHA256SUMS.txt`, list both worktree archives, list the public archive, and rerun `git bundle verify`.

Expected: all hashes pass and every archive opens.

- [ ] **Step 5: Document branch and restore mappings**

Write `README.md` with source path, branch, HEAD, archive filename, hash filename, and exact restore commands for each checkout. State that active development begins at the canonical root and the archives are recovery material.

Expected: future agents can restore any retired checkout without guessing its origin or branch.

- [ ] **Step 6: Retire duplicate physical checkouts**

After revalidating archives and exact target paths, use `git worktree remove` for each registered worktree with the necessary force level selected once based on its known ignored-file state. Move the standalone public clone to a uniquely named item in the macOS Trash after verifying the destination does not exist.

Expected: `git worktree list` retains only the canonical root, both development branches remain in `git branch -vv`, the public source path is absent, and the Trash item plus canonical archives provide recovery.

---

### Task 3: Flatten the Application and Rehome the Windows-Transfer Package

**Files:**
- Move: `01_REPO/tradingagents-main/*` and hidden application entries to the repository root.
- Move: `00_START_HERE_MAC.md` to `archive/windows-transfer-2026-07-11/README-original.md`
- Move: `02_CONTEXT_TODAY_2026-07-11/` to `archive/windows-transfer-2026-07-11/context/`
- Move: `03_AUTOMATIONS/` to `archive/windows-transfer-2026-07-11/automation-snapshots/`
- Move: `04_SETUP/` to `archive/windows-transfer-2026-07-11/setup/`
- Move: `05_VALIDATION/` to `archive/windows-transfer-2026-07-11/validation/`
- Move: `01_REPO/mirofish-main/` to `archive/windows-transfer-2026-07-11/mirofish/`
- Move: `TradingAgents_Autonomy_Catch_Up_2026-07-26.*` to `docs/history/`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Verified recovery evidence from Tasks 1-2.
- Produces: A single canonical Python and Git root for path migration and documentation.

- [ ] **Step 1: Stop only the affected local runner**

Reconfirm label, PID, working directory, and service health, then run:

```zsh
launchctl bootout "gui/$(id -u)/com.tradingagents.n8n-runner"
```

Expected: the label is absent from `launchctl print` and port 8765 no longer responds.

- [ ] **Step 2: Validate the application move set**

Enumerate every immediate child of `01_REPO/tradingagents-main`, including dotfiles. Require the source realpath to equal the former application root, require every destination basename except `.gitignore` to be absent from the canonical root, and save the exact move list under `archive/consolidation-manifests/2026-08-10/application-move-list.txt`.

Expected: `.gitignore` is the only collision.

- [ ] **Step 3: Move the application children**

Move each validated child except `.gitignore` into the canonical root. Preserve modes, timestamps, symlinks, `.env`, `.venv`, results, caches, and untracked content. Save the former application `.gitignore` as `archive/windows-transfer-2026-07-11/application-gitignore-original.txt`, then apply the merged root ignore file.

Expected: `pyproject.toml`, `tradingagents/`, `cli/`, `tests/`, `scripts/`, `config/`, `results/`, `.env`, and `.venv` exist directly under the canonical root.

- [ ] **Step 4: Move the Windows-transfer components**

Create each explicit archive destination, validate that it is absent, then move the transfer context, automation snapshots, setup records, validation records, original start document, and MiroFish tree to the paths listed above.

Expected: historical transfer material is browsable under one dated archive and no longer resembles the active application.

- [ ] **Step 5: Move historical autonomy documents**

Create `docs/history/`, move the July 26 PDF and DOCX there, and verify their pre-move SHA-256 hashes.

Expected: both documents remain byte-identical.

- [ ] **Step 6: Remove only verified empty former containers**

Inspect the former application directory and `01_REPO` using `find -mindepth 1`. Use `rmdir` only when the directory is empty, is a real directory, and its realpath is exactly the expected former container.

Expected: `01_REPO/tradingagents-main` and `01_REPO` are absent; failure leaves the non-empty container intact for inspection.

- [ ] **Step 7: Verify the flat root before path edits**

Run `git status --short`, import with `.venv/bin/python`, run `.venv/bin/python -m cli.main --help`, and confirm `Path(tradingagents.__file__).resolve()` is under the canonical root.

Expected: source imports from `/Users/corbinfloyd/Documents/TradingAgents/tradingagents` and the CLI help exits zero.

---

### Task 4: Migrate Active Paths and Restore the Local Runner

**Files:**
- Modify: `scripts/mac/install_launchd.sh`
- Modify: `scripts/mac/ta_job.sh`
- Modify: `CLAUDE.md`
- Modify: `CODEX_HANDOFF_2026-07-14_FABLE_SESSION.md`
- Modify: `docs/superpowers/plans/2026-07-18-autonomous-trading-firm-program.md`
- Modify: `/Users/corbinfloyd/.codex/automations/tradingagents-*/automation.toml`
- Modify: `/Users/corbinfloyd/.codex/automations/tradingagents-*/memory.md`
- Modify: `/Users/corbinfloyd/Library/LaunchAgents/com.tradingagents.n8n-runner.plist`
- Modify: `/Users/corbinfloyd/.local/bin/tradingagents-n8n-runner`

**Interfaces:**
- Consumes: Canonical flat root from Task 3 and pre-move path inventory from Task 1.
- Produces: Active configuration with canonical paths and a healthy launchd runner.

- [ ] **Step 1: Snapshot the external configuration files**

Copy the exact runner plist, runner wrapper, ten automation TOMLs, and current automation memory files to `archive/consolidation-manifests/2026-08-10/external-config-before/`, preserving modes and relative names. Record hashes.

Expected: every external file scheduled for a path replacement has a canonical recovery copy.

- [ ] **Step 2: Replace the former path in active repository files**

Replace exactly:

```text
/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
```

with:

```text
/Users/corbinfloyd/Documents/TradingAgents
```

in active repository files outside `archive/`. Review each diff and retain historical references only inside the dated archive.

Expected: `rg` finds no former path outside `archive/`.

- [ ] **Step 3: Replace the path in automation definitions and current memories**

Apply the same exact replacement to the ten automation TOMLs and their current memory files. Parse each TOML with Python `tomllib`, compare before and after structures, and require all fields other than string path occurrences to match.

Expected: all files parse; all ten statuses remain unchanged; prompts and `cwds` resolve to the canonical root.

- [ ] **Step 4: Update and validate the launchd plist and runner wrapper**

Apply the exact path replacement, run `plutil -lint` on the plist, run `zsh -n` on the wrapper, verify both file modes, and inspect the diff against their recovery copies.

Expected: plist and shell validation pass and both point to the root `.venv` and root working directory.

- [ ] **Step 5: Reload the runner**

Run:

```zsh
launchctl bootstrap "gui/$(id -u)" /Users/corbinfloyd/Library/LaunchAgents/com.tradingagents.n8n-runner.plist
```

Expected: `launchctl print` reports `state = running`; `lsof` reports cwd `/Users/corbinfloyd/Documents/TradingAgents`; port 8765 health reports `status=ok`; the live process imports the root package.

- [ ] **Step 6: Prove former active paths are gone**

Run exact-string scans across the canonical repository excluding `archive/`, `.codex/automations`, `Library/LaunchAgents`, and `.local/bin`.

Expected: zero active matches. Historical matches inside `archive/windows-transfer-2026-07-11/` are reported separately as provenance.

- [ ] **Step 7: Commit the flattening and path migration**

Review the full status and rename detection, run `git diff --check`, stage the canonical layout and repository-owned path updates, then commit:

```zsh
git commit -m "refactor: flatten TradingAgents into canonical repository root"
```

Expected: the commit records the structural move separately from the preservation checkpoint.

---

### Task 5: Inventory and Semantically Inspect the Consolidated Repository

**Files:**
- Create: `archive/consolidation-manifests/2026-08-10/post-move-files.tsv`
- Create: `archive/consolidation-manifests/2026-08-10/repository-file-classification.tsv`
- Create: `archive/consolidation-manifests/2026-08-10/repository-text-review.tsv`
- Create: `docs/consolidation/REPOSITORY_MAP.md`

**Interfaces:**
- Consumes: Flat canonical root and current codebase graph.
- Produces: Complete file accounting and evidence-backed project map used to author `AGENTS.md`.

- [ ] **Step 1: Inventory every canonical-root entry**

Walk the canonical root without traversing external symlinks. Record every path, type, mode, size, timestamp, symlink target, Git tracking status, and content class. Hash all regular files.

Expected: every filesystem entry belongs to exactly one classification: authored source, authored documentation/configuration, tests/fixtures, runtime results, dependency/environment, generated cache, binary/media, archive, Git metadata, or local credential/configuration.

- [ ] **Step 2: Inspect every repository-authored text file**

Enumerate tracked and project-authored untracked Markdown, Python, shell, PowerShell, TOML, YAML, JSON, JavaScript/TypeScript, HTML, and configuration files outside dependency, cache, environment, result, and archive-generated trees. Read each file, record line count and review status in `repository-text-review.tsv`, and capture its purpose and authoritative role in `REPOSITORY_MAP.md`.

Expected: every authored text path has a recorded review status; generated and binary paths have an explicit classification instead of a false semantic-read claim.

- [ ] **Step 3: Refresh and inspect the codebase graph**

Reindex `/Users/corbinfloyd/Documents/TradingAgents` in fast mode. Verify the project root and branch with `list_projects` and `index_status`. Use architecture, symbol search, and call-path tools to map CLI entrypoints, TradingAgents graph flow, Alpaca supervision, policy, orchestration, dataflows, evaluation, research, and test ownership.

Expected: the graph root is canonical and the repository map cites direct source reads for paths outside complete graph coverage.

- [ ] **Step 4: Inspect operational documentation and current state surfaces**

Read `README.md`, `CONTEXT_ROUTER.md`, `REPO_OVERVIEW.md`, `TRADING_METHODS_AND_AUTOMATIONS.md`, current plans, mac scripts, n8n configuration, risk configuration, automation TOMLs, compact context summaries, live-control metadata, and newest packet families relevant to current operation.

Expected: `REPOSITORY_MAP.md` distinguishes durable architecture from current runtime state and historical transfer material.

- [ ] **Step 5: Save the consolidated repository map**

Document the root purpose, major directories, entrypoints, configuration surfaces, runtime evidence locations, automation integrations, archive structure, development branches, generated/local state, and verification commands.

Expected: the map provides enough evidence to write a specific, current root `AGENTS.md`.

---

### Task 6: Write the Root AGENTS.md and Canonical Start Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `CONTEXT_ROUTER.md`
- Create: `START_HERE.md`

**Interfaces:**
- Consumes: Task 5 repository map, source review, graph architecture, and current runtime configuration.
- Produces: One clear start surface for all future Codex sessions.

- [ ] **Step 1: Draft the root AGENTS.md from current evidence**

Cover canonical identity, project map, task routing, context refresh, Mac command entrypoints, configuration, runtime evidence, testing, documentation, Git state, automation integrations, archive provenance, and completion evidence. Use affirmative instructions and plain language.

Expected: every named path exists in the flat root and every command is Mac-valid from the canonical root.

- [ ] **Step 2: Scan AGENTS.md language**

Search case-insensitively for prohibition-oriented directives including `do not`, `don't`, `never`, `must not`, `cannot`, `can't`, `forbid`, `prohibit`, and directive uses of `avoid`. Rewrite each occurrence as an affirmative workflow while preserving useful operational meaning.

Expected: the scan returns zero prohibition-oriented directives.

- [ ] **Step 3: Create START_HERE.md**

State the canonical path, first three orientation commands, common developer commands, runtime health command, where current evidence lives, where migration history lives, and which branches retain inactive development work.

Expected: a new Codex chat opened at the root can orient without entering a nested application directory.

- [ ] **Step 4: Refresh root README and context router paths**

Update layout tables, Windows command remnants, former nested paths, and transfer-era current-state language. Preserve historical facts in the archive and make current Mac instructions primary.

Expected: active documentation consistently treats the root as the Python application and Git repository.

- [ ] **Step 5: Validate documentation references**

Extract repository-relative code spans that look like paths, check their existence or documented generated-state status, run an exact former-path scan, and run `git diff --check`.

Expected: all active references resolve and the former path appears only in historical archive evidence.

- [ ] **Step 6: Commit the guidance and repository map**

Stage `AGENTS.md`, `START_HERE.md`, active documentation changes, repository map, and review manifests, then commit:

```zsh
git commit -m "docs: establish canonical TradingAgents agent workspace"
```

Expected: the root guidance is a separate reviewable commit.

---

### Task 7: Run Project, Runtime, and Preservation Verification

**Files:**
- Create: `docs/consolidation/VERIFICATION_RESULTS.md`
- Create: `archive/consolidation-manifests/2026-08-10/post-move-runtime.txt`
- Create: `archive/consolidation-manifests/2026-08-10/post-move-git.txt`
- Create: `archive/consolidation-manifests/2026-08-10/preservation-comparison.tsv`

**Interfaces:**
- Consumes: Tasks 1-6 and their manifests.
- Produces: Fresh proof for each completion criterion.

- [ ] **Step 1: Verify filesystem preservation**

Compare preservation-critical pre/post hashes, modes, symlinks, tracked files, credentials metadata, result packets, and unique archive artifacts. Record `match`, `intentional-path-change`, `generated-rebuilt`, or `investigate` for every comparison row.

Expected: zero unexplained missing or changed preservation-critical files.

- [ ] **Step 2: Verify Git integrity**

Run `git fsck --full`, `git status --short`, `git log --oneline --decorate -5`, `git branch -vv`, `git worktree list --porcelain`, `git bundle verify`, and archive checksum validation.

Expected: Git reports no integrity errors, the canonical root is the only registered worktree, both development branches remain, and archives verify.

- [ ] **Step 3: Run focused project checks**

Run from the canonical root:

```zsh
.venv/bin/python -c 'import tradingagents, pathlib; print(pathlib.Path(tradingagents.__file__).resolve())'
.venv/bin/python -m cli.main --help
.venv/bin/python -m pytest tests/test_automation_context_snapshot.py tests/test_automation_health_audit.py tests/test_n8n_runner_policy.py tests/test_n8n_evaluations.py tests/test_test_isolation.py -q
.venv/bin/ruff check cli tradingagents scripts tests
```

Expected: import and CLI pass; test and Ruff outcomes are recorded exactly, with path-migration regressions resolved.

- [ ] **Step 4: Run the broad test suite**

Run:

```zsh
.venv/bin/python -m pytest -q
```

Expected: record total passes, skips, warnings, failures, duration, and exact failing tests. Resolve failures caused by consolidation; identify unrelated pre-existing failures with evidence.

- [ ] **Step 5: Verify runtime and automation configuration**

Capture launchd state, PID, cwd, command, health endpoint, package import path, automation TOML parsing, automation status comparison, active absolute-path scan, and live-control file hash comparison.

Expected: the runner is healthy from the canonical root, every automation retains its prior status, no active old path remains, and live-control content is unchanged.

- [ ] **Step 6: Verify codebase-memory indexing**

Run `list_projects`, match the canonical root, inspect `index_status`, and check coverage for `AGENTS.md`, `cli/main.py`, `tradingagents/orchestration/n8n_runner.py`, `tradingagents/policy/live_gate.py`, and `scripts/mac/ta_job.sh`.

Expected: the canonical root is indexed at current HEAD and coverage gaps are documented with direct-source fallbacks.

- [ ] **Step 7: Write verification results**

For every completion criterion in the design spec, cite the authoritative command output or artifact path and mark it `proved`, `contradicted`, `missing`, or `needs follow-up`.

Expected: every requirement is proved before the goal is marked complete.

---

### Task 8: Clean Obsolete Empty Task Locations and Publish the Consolidation Report

**Files:**
- Create: `docs/consolidation/CONSOLIDATION_REPORT.md`
- Create: `archive/consolidation-manifests/2026-08-10/obsolete-task-directories.txt`
- Modify: `archive/inactive-checkouts/README.md`

**Interfaces:**
- Consumes: Final verification evidence from Task 7.
- Produces: One durable human-readable handoff and an unambiguous filesystem.

- [ ] **Step 1: Re-enumerate TradingAgents-looking locations**

Repeat the original `find` and Spotlight searches across Documents, Desktop, Downloads, `.codex/worktrees`, LaunchAgents, automations, and relevant application support. Classify each match as canonical, archived, portfolio/reference asset, historical evidence, empty Codex task directory, or unexpected checkout.

Expected: no unexpected runnable TradingAgents checkout remains outside the canonical root.

- [ ] **Step 2: Remove only exact empty Codex task directories**

For each previously identified `own-the-autonomous-tradingagents-resilience-and*` directory, resolve its realpath, confirm it is a real directory rather than a link, require `find -mindepth 1` to return zero entries, record it in `obsolete-task-directories.txt`, and remove it with `rmdir`.

Expected: all empty task containers are gone; any non-empty or linked target remains and is reported.

- [ ] **Step 3: Write the consolidation report**

Summarize the canonical path, final layout, moved content, retained branches, recovery archives, public bundle, external locations retired, runtime path updates, root guidance, tests, graph index, known pre-existing issues, and exact evidence links.

Expected: future agents can understand the consolidation without relying on chat history.

- [ ] **Step 4: Run the completion audit**

Re-read the design spec and this plan. For every explicit objective, artifact, invariant, path, command, and verification requirement, inspect current evidence and update `CONSOLIDATION_REPORT.md` with the result.

Expected: no requirement is supported only by intent or absence of an obvious error.

- [ ] **Step 5: Commit final evidence**

Stage the consolidation report, verification results, safe manifests, archive documentation, and final path updates. Review for secrets and large ignored recovery files, then commit:

```zsh
git commit -m "chore: verify TradingAgents repository consolidation"
```

Expected: final Git history separates design, preservation checkpoint, flattening, guidance, and verification.

- [ ] **Step 6: Confirm the user-facing start location**

Run:

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents
git rev-parse --show-toplevel
.venv/bin/python -m cli.main --help
```

Expected: the first command location is simultaneously the Git root and runnable application root.
