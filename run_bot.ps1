#Requires -Version 5.1
param()

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Info  { Write-Host "[INFO]" -ForegroundColor Blue   -NoNewline; Write-Host " $args" }

# Ensure npm global binaries (openclaw) are in PATH
$npmPrefix = & npm config get prefix 2>$null
if (-not $npmPrefix) { $npmPrefix = "$env:USERPROFILE\.npm-global" }
$npmBin = Join-Path $npmPrefix "bin"
if (Test-Path $npmBin) {
    $env:Path = "$npmBin;$env:Path"
}
$npmBin2 = Join-Path $env:LOCALAPPDATA "npm"
if (Test-Path $npmBin2) {
    $env:Path = "$npmBin2;$env:Path"
}

# Check venv exists
$venvPython = Join-Path $scriptDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Virtual environment not found. Run setup.bat first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Activate venv
. (Join-Path $scriptDir "venv\Scripts\Activate.ps1")
Info "Virtual environment activated"

# Run the bot
try {
    & python core\runtime.py
} catch {
    Write-Host "[ERROR] Bot crashed: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Read-Host "Press Enter to exit"
