param(
    [Parameter(Mandatory = $true)]
    [string]$Job
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

& $Python -m tradingagents.orchestration.n8n_runner --run-job $Job --json --repo-root $RepoRoot
exit $LASTEXITCODE

