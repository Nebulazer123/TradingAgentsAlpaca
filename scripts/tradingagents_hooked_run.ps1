param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "results\_context\hook-events") | Out-Null

& $Python scripts\automation_context_snapshot.py --write | Out-Null

if ($CommandArgs.Count -eq 0) {
    Write-Error "No command was provided."
    exit 2
}

$StartedAt = (Get-Date).ToUniversalTime().ToString("o")
$Exe = $CommandArgs[0]
$Args = @()
if ($CommandArgs.Count -gt 1) {
    $Args = $CommandArgs[1..($CommandArgs.Count - 1)]
}

& $Exe @Args
$CommandExit = $LASTEXITCODE
if ($null -eq $CommandExit) {
    $CommandExit = 0
}

& $Python scripts\automation_context_snapshot.py --write | Out-Null

$Packet = [ordered]@{
    schema_version = 1
    event = "hooked_run"
    started_at = $StartedAt
    completed_at = (Get-Date).ToUniversalTime().ToString("o")
    exit_code = $CommandExit
    command_exe = $Exe
    arg_count = $Args.Count
    authority = "context_wrapper_no_trade_bypass"
}
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss-ffffff")
$OutPath = Join-Path $RepoRoot "results\_context\hook-events\hooked-run-$Stamp.json"
$Packet | ConvertTo-Json -Depth 5 | Set-Content -Path $OutPath -Encoding UTF8

exit $CommandExit

