#Requires -Version 5.1
param()

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# ------------------------------------------------------------------
# Color helpers
# ------------------------------------------------------------------
function Info  { Write-Host "[INFO]" -ForegroundColor Blue   -NoNewline; Write-Host " $args" }
function Ok    { Write-Host "[OK]"   -ForegroundColor Green  -NoNewline; Write-Host " $args" }
function Warn  { Write-Host "[WARN]" -ForegroundColor Yellow -NoNewline; Write-Host " $args" }
function Fail  { Write-Host "[FAIL]" -ForegroundColor Red    -NoNewline; Write-Host " $args" }
function Section($title) {
    Write-Host ""
    Write-Host "--- $title" -ForegroundColor Cyan
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " OpenClaw Trading Automation Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------
# Admin check
# ------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Warn "Some steps (global npm install) may need admin rights."
    Warn "If errors occur, re-run as Administrator."
}
Write-Host ""

# ------------------------------------------------------------------
# Step 1 — Check / Install Python
# ------------------------------------------------------------------
Section "Python 3.8+"

$pythonExe = $null
$pythonVer = $null

# Try py launcher first (most reliable on Windows)
try {
    $ver = & py -3 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pythonExe = "py -3"
        $pythonVer = $ver
    }
} catch {}

# Fallback: python command in PATH
if (-not $pythonExe) {
    try {
        $ver = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = "python"
            $pythonVer = $ver
        }
    } catch {}
}

if ($pythonExe) {
    Ok "Found $pythonVer"
    # Validate version >= 3.8
    if ($pythonVer -match '(\d+)\.(\d+)') {
        $maj = [int]$Matches[1]
        $min = [int]$Matches[2]
        if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 8)) {
            Fail "Python 3.8+ required (found $pythonVer)"
            exit 1
        }
    }
} else {
    Warn "Python not found."
    $choice = Read-Host "Install Python 3.8+ automatically using winget? (Y/n)"
    if ($choice -ne "n") {
        try {
            $null = Get-Command winget -ErrorAction Stop
            Info "Installing Python via winget..."
            winget install --id Python.Python --silent --accept-package-agreements 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Ok "Python installed via winget"
                # Refresh PATH
                $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
                # Re-check
                try {
                    $ver = & py -3 --version 2>&1
                    if ($LASTEXITCODE -eq 0) {
                        $pythonExe = "py -3"
                        $pythonVer = $ver
                        Ok "Python now available: $ver"
                    } else {
                        throw "Python not in PATH after install"
                    }
                } catch {
                    $ver = & python --version 2>&1
                    if ($LASTEXITCODE -eq 0) {
                        $pythonExe = "python"
                        $pythonVer = $ver
                        Ok "Python now available: $ver"
                    }
                }
                if (-not $pythonExe) {
                    Warn "Python installed but not in PATH. Restart terminal and re-run setup."
                    Warn "Or add to PATH manually: $env:LOCALAPPDATA\Programs\Python\*\"
                }
            } else {
                throw "winget exit code: $LASTEXITCODE"
            }
        } catch {
            Warn "Automatic install failed. Download Python manually:"
            Write-Host "  https://www.python.org/downloads/" -ForegroundColor Cyan
            Read-Host "Press Enter after installing Python"
            # Re-check after user installs
            try {
                $ver = & py -3 --version 2>&1
                if ($LASTEXITCODE -eq 0) { $pythonExe = "py -3"; $pythonVer = $ver }
            } catch {
                try { $ver = & python --version 2>&1; if ($LASTEXITCODE -eq 0) { $pythonExe = "python"; $pythonVer = $ver } } catch {}
            }
            if (-not $pythonExe) {
                Fail "Python still not found. Please install and re-run setup."
                exit 1
            }
        }
    } else {
        Fail "Python is required. Install it and re-run setup."
        exit 1
    }
}
Write-Host ""

# ------------------------------------------------------------------
# Step 2 — Check / Install Node.js
# ------------------------------------------------------------------
Section "Node.js 22+"

$nodeExe = $null
$nodeVer = $null

try {
    $ver = & node --version 2>&1
    if ($LASTEXITCODE -eq 0) { $nodeExe = "node"; $nodeVer = $ver }
} catch {}

if ($nodeExe) {
    Ok "Found $nodeVer"
    $major = [int]($nodeVer -replace '[vV]','' -replace '\..*','')
    if ($major -lt 22) {
        Fail "Node.js 22+ required (found $nodeVer)"
        exit 1
    }
} else {
    Warn "Node.js not found."
    $choice = Read-Host "Install Node.js LTS (22+) automatically using winget? (Y/n)"
    if ($choice -ne "n") {
        try {
            $null = Get-Command winget -ErrorAction Stop
            Info "Installing Node.js via winget..."
            winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Ok "Node.js installed via winget"
                $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
                try {
                    $ver = & node --version 2>&1
                    if ($LASTEXITCODE -eq 0) { $nodeExe = "node"; $nodeVer = $ver; Ok "Node.js now available: $ver" }
                } catch {}
                if (-not $nodeExe) {
                    Warn "Node.js installed but not in PATH. Restart terminal and re-run setup."
                }
            } else {
                throw "winget exit code: $LASTEXITCODE"
            }
        } catch {
            Warn "Automatic install failed. Download Node.js 22+ manually:"
            Write-Host "  https://nodejs.org/" -ForegroundColor Cyan
            Read-Host "Press Enter after installing Node.js"
            try {
                $ver = & node --version 2>&1
                if ($LASTEXITCODE -eq 0) { $nodeExe = "node"; $nodeVer = $ver }
            } catch {}
            if (-not $nodeExe) {
                Fail "Node.js still not found. Please install and re-run setup."
                exit 1
            }
        }
    } else {
        Fail "Node.js is required. Install it and re-run setup."
        exit 1
    }
}
Write-Host ""

# ------------------------------------------------------------------
# Step 3 — Check Chrome
# ------------------------------------------------------------------
Section "Google Chrome"

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chromeFound = $false
foreach ($p in $chromePaths) {
    if (Test-Path $p) {
        $chromeFound = $true
        break
    }
}

if ($chromeFound) {
    Ok "Google Chrome is installed"
} else {
    Warn "Google Chrome not found at standard paths."
    Warn "Chrome is needed for Zerodha browser monitoring."
    Warn "Download from: https://www.google.com/chrome/"
}
Write-Host ""

# ------------------------------------------------------------------
# Step 4 — Python virtual environment
# ------------------------------------------------------------------
Section "Python virtual environment"

if (-not (Test-Path "venv")) {
    Info "Creating Python virtual environment..."
    if ($pythonExe -eq "py -3") {
        & py -3 -m venv venv
    } else {
        & python -m venv venv
    }
    if ($LASTEXITCODE -eq 0) { Ok "Virtual environment created" } else { Fail "Failed to create venv"; exit 1 }
} else {
    Ok "Virtual environment already exists"
}

# Activate and install deps
$venvActivate = Join-Path $scriptDir "venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
} else {
    # Fallback for older PowerShell
    $venvPython = Join-Path $scriptDir "venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Fail "Virtual environment python.exe not found"
        exit 1
    }
}

Info "Installing Python dependencies..."
$pip = Join-Path $scriptDir "venv\Scripts\pip.exe"
& $pip install --upgrade pip -q 2>$null
& $pip install -r requirements.txt -q
if ($LASTEXITCODE -eq 0) { Ok "Python dependencies installed" } else { Fail "pip install failed"; exit 1 }
Write-Host ""

# ------------------------------------------------------------------
# Step 5 — OpenClaw installation
# ------------------------------------------------------------------
Section "OpenClaw"

try {
    $ocVer = & openclaw --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Ok "OpenClaw already installed ($ocVer)"
    } else { throw }
} catch {
    Info "Installing OpenClaw via npm..."
    # On Windows, npm global prefix defaults to $env:APPDATA\npm which is user-writable
    $npmPrefix = & npm config get prefix
    $npmBin = Join-Path $npmPrefix "openclaw.cmd"
    $npmBin2 = Join-Path $npmPrefix "openclaw"

    try {
        & npm install -g openclaw 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $ocVer = & openclaw --version 2>&1
            if ($LASTEXITCODE -eq 0) { Ok "OpenClaw installed ($ocVer)" } else { Ok "OpenClaw installed" }
        } else { throw "npm install failed with exit code $LASTEXITCODE" }
    } catch {
        Warn "Global npm install failed. Trying with --prefix..."
        $localNpmDir = Join-Path $scriptDir "node_modules\.global"
        New-Item -ItemType Directory -Force -Path $localNpmDir | Out-Null
        & npm install openclaw --prefix $localNpmDir 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $env:Path = (Join-Path $localNpmDir "node_modules\.bin") + ";" + $env:Path
            Ok "OpenClaw installed locally"
        } else {
            Warn "OpenClaw installation failed. Try running as Administrator."
        }
    }
}
Write-Host ""

# ------------------------------------------------------------------
# Step 6 — Create missing directories
# ------------------------------------------------------------------
Section "Project directories"

New-Item -ItemType Directory -Force -Path "logs"   | Out-Null
New-Item -ItemType Directory -Force -Path "prompts" | Out-Null
Ok "Directories: logs/, prompts/"
Write-Host ""

# ------------------------------------------------------------------
# Step 7 — Configure Telegram Bot
# ------------------------------------------------------------------
Section "Telegram Bot configuration"

$tgConfig = "config\telegram.json"

$needTelegram = $false
if (-not (Test-Path $tgConfig) -or (Get-Item $tgConfig).Length -eq 0) {
    $needTelegram = $true
} else {
    $content = Get-Content $tgConfig -Raw
    if ($content -match "YOUR_BOT_TOKEN|YOUR_CHAT_ID") {
        $needTelegram = $true
    } else {
        $choice = Read-Host "Update Telegram credentials? (y/N)"
        if ($choice -eq "y" -or $choice -eq "Y") { $needTelegram = $true }
    }
}

if ($needTelegram) {
    Write-Host ""
    Write-Host "--- Telegram Group Setup ---" -ForegroundColor Cyan
    Write-Host "1. Create a bot: Open Telegram, search @BotFather, send /newbot, follow prompts." -ForegroundColor White
    Write-Host "   Save the bot_token (looks like: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)." -ForegroundColor White
    Write-Host ""
    Write-Host "2. Create a group: Telegram -> New Group, add your bot as a member." -ForegroundColor White
    Write-Host "   (Important: Bot must be in the group to send messages there.)" -ForegroundColor White
    Write-Host ""
    Write-Host "3. Send a test message in the group (any text)." -ForegroundColor White
    Write-Host ""
    Write-Host "4. Get the group chat_id:" -ForegroundColor White
    Write-Host "   Option A — Search @getidsbot, add it to the group, it will reply with the chat ID." -ForegroundColor White
    Write-Host "   Option B — Visit in browser (after step 3):" -ForegroundColor White
    Write-Host "     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" -ForegroundColor Cyan
    Write-Host "     Look for 'chat':{'id':-100...} — that negative number is the group chat_id." -ForegroundColor White
    Write-Host "--------------------------------------------------------------------" -ForegroundColor Cyan
    $botToken = Read-Host "Enter bot_token"
    $chatId   = Read-Host "Enter group chat_id (negative number, e.g. -1001234567890)"
    $tgObj = @{ bot_token = $botToken; chat_id = $chatId }
    $tgObj | ConvertTo-Json | Set-Content $tgConfig -Encoding UTF8
    Ok "Telegram config saved to $tgConfig"
} else {
    Ok "Using existing Telegram config"
}
Write-Host ""

# ------------------------------------------------------------------
# Step 8 — Save strategy prompt
# ------------------------------------------------------------------
Section "Strategy prompt"

$strategyConfig = "config\strategy_prompt.json"
$strategy = @{
    timeframe    = "15 min"
    direction_logic = "5 EMA crossing above 20 EMA → CE only; 5 EMA crossing below 20 EMA → PE only"
    confirmation = "3 min premium chart confirmation before signal"
    instrument   = "ATM option (dynamic)"
}
$strategy | ConvertTo-Json | Set-Content $strategyConfig -Encoding UTF8
Ok "Strategy prompt saved to $strategyConfig"
Write-Host ""

# ------------------------------------------------------------------
# Step 9 — Validation summary
# ------------------------------------------------------------------
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Setup Complete - Validation Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$passed = 0
$failed = 0

function Check($desc, $scriptBlock) {
    try {
        $result = & $scriptBlock
        if ($result) {
            Write-Host "  [PASS]" -ForegroundColor Green -NoNewline; Write-Host " $desc"
            $script:passed++
        } else {
            Write-Host "  [FAIL]" -ForegroundColor Red -NoNewline; Write-Host " $desc"
            $script:failed++
        }
    } catch {
        Write-Host "  [FAIL]" -ForegroundColor Red -NoNewline; Write-Host " $desc"
        $script:failed++
    }
}

Check "Python virtual environment"   { Test-Path "venv\Scripts\python.exe" }
Check "Python venv dependencies"     { & "venv\Scripts\python.exe" -c "import requests, psutil; print('OK')" 2>$null; $LASTEXITCODE -eq 0 }
Check "OpenClaw installed"           { Get-Command openclaw -ErrorAction SilentlyContinue }
Check "logs/ directory"              { Test-Path "logs" }
Check "prompts/ directory"           { Test-Path "prompts" }
Check "Telegram config exists"       { (Test-Path "config\telegram.json") -and ((Get-Item "config\telegram.json").Length -gt 0) }
Check "Strategy prompt exists"       { (Test-Path "config\strategy_prompt.json") -and ((Get-Item "config\strategy_prompt.json").Length -gt 0) }
Check "Zerodha config exists"        { Test-Path "config\zerodha.json" }
Check "Settings config exists"       { Test-Path "config\settings.json" }

Write-Host ""
Write-Host "  $passed passed, $failed failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

if ($failed -gt 0) {
    Warn "Some checks failed. Review output above."
} else {
    Ok "All checks passed!"
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Make sure Chrome is installed and logged into Zerodha"
Write-Host "  2. Activate venv: .\venv\Scripts\Activate.ps1"
Write-Host "  3. Run bot:    python core\runtime.py"
Write-Host ""

Read-Host "Press Enter to exit"
