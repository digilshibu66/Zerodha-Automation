param(
    [switch]$SkipOpenClawCheck
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

function Pass($message) { Write-Host "[PASS] $message" -ForegroundColor Green }
function Warn($message) { Write-Host "[WARN] $message" -ForegroundColor Yellow }
function Fail($message) { throw "[FAIL] $message" }

if (-not (Test-Path "run_bot.bat")) { Fail "run_bot.bat not found" }
Pass "run_bot.bat exists"

if (-not (Test-Path "run_bot.ps1")) { Fail "run_bot.ps1 not found" }
Pass "run_bot.ps1 exists"

if (-not (Test-Path "core\openclaw_manager.py")) { Fail "core\openclaw_manager.py not found" }
Pass "core\openclaw_manager.py exists"

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Warn "venv\Scripts\python.exe not found; run setup.bat before full runtime testing"
    $python = "python"
} else {
    $python = "venv\Scripts\python.exe"
    Pass "Windows venv Python exists"
}

if (-not $SkipOpenClawCheck) {
    $openclaw = Get-Command openclaw -ErrorAction SilentlyContinue
    if (-not $openclaw) { Fail "openclaw is not on PATH; run setup.bat or reinstall OpenClaw" }
    Pass "openclaw found at $($openclaw.Source)"
}

& $python -m py_compile core\openclaw_manager.py core\runtime.py
if ($LASTEXITCODE -ne 0) { Fail "Python syntax check failed" }
Pass "Python syntax check passed"

$env:TRADING_BOT_DRY_RUN_WINDOWS_LAUNCH = "1"
$env:OPENCLAW_GATEWAY_TOKEN = "dry-run-token"

$pythonSnippet = @'
import json
import os
import tempfile

from core.openclaw_manager import _write_windows_console_script

tmp = tempfile.gettempdir()
gateway_script = _write_windows_console_script(
    ["openclaw", "gateway", "run", "--port", "18789", "--token", "dry-run-token"],
)
agent_script = _write_windows_console_script(
    ["openclaw", "agent", "--local", "--agent", "main", "--model", "openai/gpt-5.5", "--session-key", "agent:main:dry-run", "-m", "dry run message"],
    exit_code_path=os.path.join(tmp, "openclaw_agent_exit_dry_run.txt"),
    log_path=os.path.join(tmp, "openclaw_agent_dry_run.log"),
    hold_on_exit=True,
)
print(json.dumps({"gateway_script": gateway_script, "agent_script": agent_script}))
'@

$json = $pythonSnippet | & $python -

if ($LASTEXITCODE -ne 0) { Fail "Could not generate Windows console wrapper scripts" }
$scripts = $json | ConvertFrom-Json
Pass "Generated Gateway wrapper: $($scripts.gateway_script)"
Pass "Generated TUI wrapper: $($scripts.agent_script)"

foreach ($script in @($scripts.gateway_script, $scripts.agent_script)) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors -and $errors.Count -gt 0) {
        $joined = ($errors | ForEach-Object { $_.Message }) -join "; "
        Fail "PowerShell parse failed for ${script}: $joined"
    }
    Pass "PowerShell parse OK: $script"
}

$trackedFiles = git ls-files 2>$null
if ($LASTEXITCODE -eq 0 -and $trackedFiles) {
    $pinHit = $false
    $pinPattern = "800" + "085"
    foreach ($file in $trackedFiles) {
        if (Test-Path $file) {
            $matches = Select-String -Path $file -Pattern $pinPattern -SimpleMatch -ErrorAction SilentlyContinue
            if ($matches) {
                $pinHit = $true
                Write-Host $matches
            }
        }
    }
    if ($pinHit) { Fail "PIN-like secret found in tracked files" }
    Pass "No configured PIN found in tracked files"
} else {
    Warn "git ls-files unavailable; skipped tracked-file PIN scan"
}

Write-Host ""
Write-Host "Windows launch smoke test completed." -ForegroundColor Cyan
Write-Host "Next full test: run .\run_bot.bat and confirm controller, Gateway, TUI, and Chrome windows open." -ForegroundColor Cyan
