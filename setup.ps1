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
function Invoke-WithProgress($filePath, [string[]]$argumentList, $label) {
    $frames = @("|", "/", "-", "\")
    $started = Get-Date
    $i = 0
    $proc = Start-Process -FilePath $filePath -ArgumentList $argumentList -NoNewWindow -PassThru
    while (-not $proc.HasExited) {
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        $frame = $frames[$i % $frames.Count]
        Write-Host -NoNewline "`r[INFO] $label still running $frame elapsed ${elapsed}s"
        Start-Sleep -Seconds 1
        $i++
        $proc.Refresh()
    }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Host "`r[INFO] $label finished in ${elapsed}s                          "
    return $proc.ExitCode
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
# Step 1 - Check / Install Python
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
            Info "Download/install progress will be shown below."
            & winget install --id Python.Python.3.12 --exact --source winget --accept-package-agreements --accept-source-agreements
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
            Warn "Automatic install failed: $($_.Exception.Message)"
            Warn "Download Python manually:"
            Write-Host "  https://www.python.org/downloads/" -ForegroundColor Cyan
            Read-Host "After the installer finishes, press Enter here (do not paste the URL)"
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
# Step 2 - Check / Install Node.js
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
            Info "Download/install progress will be shown below."
            & winget install --id OpenJS.NodeJS.LTS --exact --source winget --accept-package-agreements --accept-source-agreements
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
            Warn "Automatic install failed: $($_.Exception.Message)"
            Warn "Download Node.js 22+ manually:"
            Write-Host "  https://nodejs.org/" -ForegroundColor Cyan
            Read-Host "After the installer finishes, press Enter here (do not paste the URL)"
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
# Step 3 - Check Chrome
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
# Step 4 - Python virtual environment
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

$venvPython = Join-Path $scriptDir "venv\Scripts\python.exe"
$pip = Join-Path $scriptDir "venv\Scripts\pip.exe"

$missingDeps = & $venvPython -c "import importlib.metadata as m, pathlib, re, sys; req=pathlib.Path('requirements.txt'); missing=[]; lines=req.read_text().splitlines() if req.exists() else []; [missing.append(re.split(r'[<>=!~;\[]', line.strip(), maxsplit=1)[0].strip()) for line in lines if line.strip() and not line.lstrip().startswith('#') and not line.lstrip().startswith('-') and not m.distribution(re.split(r'[<>=!~;\[]', line.strip(), maxsplit=1)[0].strip())]" 2>&1
if ($LASTEXITCODE -eq 0) {
    Ok "All Python requirements are already installed"
} else {
    Info "Installing missing Python requirements..."
    Info "Download/install progress will be shown below."
    & $pip install --upgrade pip
    & $pip install -r requirements.txt
    if ($LASTEXITCODE -eq 0) { Ok "Python dependencies installed" } else { Fail "pip install failed"; exit 1 }
}

Write-Host ""

# ------------------------------------------------------------------
# Step 5 - Git for OpenClaw installer
# ------------------------------------------------------------------
Section "Git"

$gitFound = $false
function Find-GitOnWindows {
    $gitDirs = @(
        "$env:ProgramFiles\Git\cmd",
        "$env:ProgramFiles\Git\bin",
        "${env:ProgramFiles(x86)}\Git\cmd",
        "${env:ProgramFiles(x86)}\Git\bin",
        "$env:LOCALAPPDATA\Programs\Git\cmd",
        "$env:LOCALAPPDATA\Programs\Git\bin"
    )
    foreach ($dir in $gitDirs) {
        if (-not $dir -or -not (Test-Path $dir)) { continue }
        $gitExe = Join-Path $dir "git.exe"
        if (Test-Path $gitExe) {
            $env:Path = "$dir;$env:Path"
            return $true
        }
    }
    return $false
}

function Test-GitAvailable {
    try {
        $gitVer = & git --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Ok "Found $gitVer"
            return $true
        }
    } catch {}
    if (Find-GitOnWindows) {
        try {
            $gitVer = & git --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                Ok "Found $gitVer"
                return $true
            }
        } catch {}
    }
    return $false
}

$gitFound = Test-GitAvailable

if (-not $gitFound) {
    Warn "Git not found. OpenClaw installer needs Git and may otherwise download portable Git."
    $choice = Read-Host "Install Git automatically using winget? (Y/n)"
    if ($choice -ne "n") {
        try {
            $null = Get-Command winget -ErrorAction Stop
            Info "Installing Git via winget..."
            Info "Download/install progress will be shown below."
            & winget install --id Git.Git --exact --source winget --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) {
                Ok "Git installed via winget"
                $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
                $gitFound = Test-GitAvailable
                if (-not $gitFound) { Warn "Git installed but not available in this terminal yet" }
            } else {
                Warn "winget returned exit code: $LASTEXITCODE"
                Warn "Checking common Git install paths..."
                $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
                $gitFound = Test-GitAvailable
                if (-not $gitFound) { throw "Git is installed or winget found it, but git.exe is not on PATH" }
            }
        } catch {
            Warn "Automatic Git install failed: $($_.Exception.Message)"
            if (Test-GitAvailable) {
                $gitFound = $true
            } else {
                Warn "OpenClaw installer will try to bootstrap portable Git instead."
            }
            Warn "Manual Git installer: https://git-scm.com/download/win"
        }
    } else {
        Warn "Skipping Git install; OpenClaw installer may bootstrap portable Git."
    }
}
Write-Host ""

# ------------------------------------------------------------------
# Step 6 - OpenClaw installation
# ------------------------------------------------------------------
Section "OpenClaw"

# Try running openclaw first (works if already in PATH)
$ocReady = $false
try {
    $null = & openclaw --version 2>&1
    if ($LASTEXITCODE -eq 0) { $ocReady = $true }
} catch {}

if (-not $ocReady) {
    $searchPaths = @(
        "$env:LOCALAPPDATA\npm\openclaw.cmd", "$env:LOCALAPPDATA\npm\openclaw"
        "$env:APPDATA\npm\openclaw.cmd", "$env:APPDATA\npm\openclaw"
        "$env:USERPROFILE\.local\bin\openclaw.cmd", "$env:USERPROFILE\.local\bin\openclaw"
        "$env:LOCALAPPDATA\OpenClaw\deps\portable-node\openclaw.cmd", "$env:LOCALAPPDATA\OpenClaw\deps\portable-node\openclaw"
        "$env:ProgramFiles\nodejs\openclaw.cmd", "$env:ProgramFiles\nodejs\openclaw"
    )
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCmd) {
        $npmPrefix = & $npmCmd.Source config get prefix 2>$null
        if ($npmPrefix) {
            $searchPaths += "$npmPrefix\openclaw.cmd", "$npmPrefix\openclaw", "$npmPrefix\bin\openclaw.cmd", "$npmPrefix\bin\openclaw"
        }
    }
    foreach ($p in $searchPaths) {
        if (Test-Path $p) {
            $dir = Split-Path $p -Parent
            $env:Path = "$dir;$env:Path"
            try {
                $null = & openclaw --version 2>&1
                if ($LASTEXITCODE -eq 0) { $ocReady = $true; break }
            } catch {}
        }
    }
}

if ($ocReady) {
    $ocVer = & openclaw --version 2>&1
    Ok "OpenClaw already installed ($ocVer)"
} else {
    Info "Installing OpenClaw using the official installer..."
    Info "Download/install progress will be shown below."
    try {
        $installCode = Invoke-WithProgress "powershell" @("-c", "irm https://openclaw.ai/install.ps1 | iex") "OpenClaw installer"
        if ($installCode -eq 0) {
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
            $ocVer = & openclaw --version 2>&1
            if ($LASTEXITCODE -eq 0) { Ok "OpenClaw installed ($ocVer)" } else { Ok "OpenClaw installed" }
        } else { throw "OpenClaw installer failed with exit code $installCode" }
    } catch {
        Warn "OpenClaw installation failed: $($_.Exception.Message)"
        Warn 'Try running this manually in PowerShell: powershell -c "irm https://openclaw.ai/install.ps1 | iex"'
    }
}

# Ensure OpenClaw global config is valid (gateway + sandbox)
try {
    $null = & openclaw --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $ocValidate = & openclaw config validate 2>&1
        if ($LASTEXITCODE -ne 0) {
            & openclaw config set gateway.mode local 2>&1 | Out-Null
        }
        & openclaw config set agents.defaults.sandbox.mode off 2>&1 | Out-Null
    }
} catch {}
Write-Host ""

# ------------------------------------------------------------------
# Step 7 - Ensure the 'main' OpenClaw agent exists
# ------------------------------------------------------------------
Section "OpenClaw agent"

try {
    $null = & openclaw --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $agentExists = $false
        try {
            $agentsRaw = & openclaw agents list --json 2>$null
            if ($LASTEXITCODE -eq 0 -and $agentsRaw) {
                $agentsData = $agentsRaw | ConvertFrom-Json
                $agents = if ($agentsData -is [System.Array]) { $agentsData } else { $agentsData.agents }
                $agentExists = @($agents | Where-Object { $_.id -eq "main" }).Count -gt 0
            }
        } catch {}

        if ($agentExists) {
            Ok "OpenClaw 'main' agent exists"
        } else {
            Info "Creating 'main' agent for OpenClaw..."
            $workspace = Join-Path $env:USERPROFILE ".openclaw\workspace"
            New-Item -ItemType Directory -Force -Path $workspace | Out-Null
            & openclaw agents add main --non-interactive --workspace $workspace 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { Ok "OpenClaw 'main' agent created" } else { Warn "Could not create 'main' agent (will be created at runtime)" }
        }
    } else {
        Warn "OpenClaw not available; agent will be created at runtime if possible"
    }
} catch {
    Warn "OpenClaw agent check skipped"
}
Write-Host ""

# ------------------------------------------------------------------
# Step 8 - Create missing directories
# ------------------------------------------------------------------
Section "Project directories"

New-Item -ItemType Directory -Force -Path "logs"   | Out-Null
New-Item -ItemType Directory -Force -Path "prompts" | Out-Null
Ok "Directories: logs/, prompts/"
Write-Host ""

# ------------------------------------------------------------------
# Step 9 - Configure Telegram Bot
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
    Write-Host "   Option A - Search @getidsbot, add it to the group, it will reply with the chat ID." -ForegroundColor White
    Write-Host "   Option B - Visit in browser (after step 3):" -ForegroundColor White
    Write-Host "     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" -ForegroundColor Cyan
    Write-Host "     Look for 'chat':{'id':-100...} - that negative number is the group chat_id." -ForegroundColor White
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
# Step 10 - Save strategy prompt
# ------------------------------------------------------------------
Section "Strategy prompt"

$strategyConfig = "config\strategy_prompt.json"
if ((Test-Path $strategyConfig) -and ((Get-Item $strategyConfig).Length -gt 0)) {
    Ok "Strategy prompt already exists at $strategyConfig"
} else {
    @{
        strategy_type = "Intraday ATM Options Buying"
        direction = @{
            timeframe = "15 min"
            indicators = @("5 EMA", "20 EMA")
            rules = @{
                CE = "5 EMA crosses ABOVE 20 EMA on 15m chart -> Enable ONLY CE trades"
                PE = "5 EMA crosses BELOW 20 EMA on 15m chart -> Enable ONLY PE trades"
            }
        }
        strike_selection = @{
            type = "ATM"
            rule = "If CE bias -> Buy ATM CE; If PE bias -> Buy ATM PE"
            note = "ATM strike dynamically updates based on current underlying spot price"
        }
        entry = @{
            timeframe = "3 min"
            indicators = @("5 EMA", "20 EMA")
            conditions = @{
                CE = @("15m direction = Bullish", "ATM CE premium 5 EMA crosses ABOVE 20 EMA", "Current time inside allowed session", "Trade count limit not exceeded", "No active position running")
                PE = @("15m direction = Bearish", "ATM PE premium 5 EMA crosses BELOW 20 EMA", "Current time inside allowed session", "Trade count limit not exceeded", "No active position running")
            }
        }
        capital = @{ usage = "100% of available capital per trade"; quantity = "Maximum possible lots using available margin, multiple lots allowed" }
        risk_management = @{ max_loss_per_trade = "10% of deployed capital"; example = "If capital = Rs.20,000, max loss = Rs.2,000" }
        reward_target = @{ min = "20% of deployed capital"; max = "50% of deployed capital"; configurable = $true }
        stop_loss = @{ type = "EMA based"; indicator = "20 EMA of 3-minute premium chart"; condition = "Exit if premium price touches/closes beyond 20 EMA against trade direction" }
        sessions = @(
            @{ name = "Morning"; start = "09:30"; end = "11:30"; max_trades = 2 }
            @{ name = "Afternoon"; start = "13:30"; end = "15:00"; max_trades = 2 }
        )
        daily_limit = @{ max_trades = 4; rule = "After 4 completed trades, block all new entries" }
        exit_conditions = @("Profit target hit (20%-50% of deployed capital)", "EMA stop loss hit (price crosses 20 EMA on 3m premium chart)", "Hard risk stop hit (loss reaches 10% of deployed capital)")
        position_management = @{ max_active = 1; rules = @("Only ONE active trade at a time", "No averaging", "No hedging", "No reverse entry without fresh signal", "Wait for fresh EMA crossover after exit") }
        auto_square_off = @{ time = "15:15"; rule = "Exit all open positions before market close" }
        safety = @("Duplicate dummy signal prevention", "API/browser failure handling", "Internet reconnect handling", "Manual emergency stop", "Dummy signal confirmation check", "Never place/modify/cancel real broker orders")
        alerts = @("Trade entry", "Trade exit", "SL hit", "Target hit", "Session limit reached", "Daily trade limit reached", "API/order failure")
        logging = @("Entry time", "Exit time", "Direction (CE/PE)", "Strike selected", "Lot quantity", "Entry price", "Exit price", "P&L", "Exit reason", "Trade duration")
        flow = @("15m EMA Direction Check", "Determine CE or PE Bias", "Select ATM Option Premium", "Monitor 3m EMA Crossover", "Validate: Session timing, Trade count, No active trade", "Calculate dummy deployment using 100% available capital", "Record Dummy Buy Signal (No Real Order)", "Monitor: Target, 20 EMA SL, Hard SL", "Record Dummy Exit Signal (No Real Order)", "Update Logs & Trade Count", "Wait For Fresh Signal")
    } | ConvertTo-Json -Depth 5 | Set-Content $strategyConfig -Encoding UTF8
    Ok "Strategy prompt saved to $strategyConfig"
}
Write-Host ""

# ------------------------------------------------------------------
# Step 11 - Configure OpenClaw model
# ------------------------------------------------------------------
Section "OpenClaw Model Configuration"

$modelConfig = "config\openclaw_model.json"
$openclawDir = "$env:USERPROFILE\.openclaw"
$ocGlobalConfig = "$openclawDir\openclaw.json"

$hasModelConfig = (Test-Path $modelConfig) -and ((Get-Item $modelConfig).Length -gt 0)
$hasRealApiKey = $false
if ($hasModelConfig) {
    $content = Get-Content $modelConfig -Raw
    $hasRealApiKey = ($content -notmatch "YOUR_API_KEY")
}
if ($hasModelConfig -and $hasRealApiKey) {
    Ok "OpenClaw model config already exists"
} else {
    Write-Host ""
    Write-Host "--- AI Model Selection ---" -ForegroundColor Cyan
    Write-Host "Select provider for OpenClaw:" -ForegroundColor White
    Write-Host "  1) OpenAI"
    Write-Host "  2) OpenRouter"
    Write-Host "  3) OpenCode"
    Write-Host "  4) Anthropic"
    Write-Host "  5) Gemini"
    $modelChoice = Read-Host "Choice [3]"
    if ([string]::IsNullOrWhiteSpace($modelChoice)) { $modelChoice = "3" }

    switch ($modelChoice) {
        "1" { $provider = "openai"; $defaultModel = "gpt-4o" }
        "2" { $provider = "openrouter"; $defaultModel = "openrouter/auto" }
        "3" { $provider = "opencode"; $defaultModel = "opencode/deepseek-v4-flash-free" }
        "4" { $provider = "anthropic"; $defaultModel = "claude-sonnet-4-20250514" }
        "5" { $provider = "google"; $defaultModel = "google/gemini-3.1-pro-preview" }
        default { $provider = "opencode"; $defaultModel = "opencode/deepseek-v4-flash-free" }
    }

    $modelName = Read-Host "Model [$defaultModel]"
    if ([string]::IsNullOrWhiteSpace($modelName)) { $modelName = $defaultModel }

    $apiKey = Read-Host "API key (leave blank to set later)"

    @{ provider = $provider; model = $modelName; api_key = $(if ($apiKey) { $apiKey } else { "YOUR_API_KEY" }) } |
        ConvertTo-Json | Set-Content $modelConfig -Encoding UTF8
    Ok "Model config saved to $modelConfig"

    if ($apiKey) {
        $envVarName = switch ($provider) {
            "openai"    { "OPENAI_API_KEY" }
            "openrouter" { "OPENROUTER_API_KEY" }
            "opencode"  { "OPENCODE_API_KEY" }
            "anthropic" { "ANTHROPIC_API_KEY" }
            "google"    { "GEMINI_API_KEY" }
            default     { "${provider}_API_KEY".ToUpper() }
        }
        [Environment]::SetEnvironmentVariable($envVarName, $apiKey, "User")
        Ok "API key saved as environment variable: $envVarName"
    }
}
Write-Host ""

# ------------------------------------------------------------------
# Step 12 - Validation summary
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
Check "Python venv requirements"     { & "venv\Scripts\python.exe" -c "import importlib.metadata as m, pathlib, re; req=pathlib.Path('requirements.txt'); lines=req.read_text().splitlines() if req.exists() else []; [m.distribution(re.split(r'[<>=!~;\[]', line.strip(), maxsplit=1)[0].strip()) for line in lines if line.strip() and not line.lstrip().startswith('#') and not line.lstrip().startswith('-') and re.split(r'[<>=!~;\[]', line.strip(), maxsplit=1)[0].strip()]" 2>$null; $LASTEXITCODE -eq 0 }
Check "OpenClaw installed"           { Get-Command openclaw -ErrorAction SilentlyContinue }
Check "logs/ directory"              { Test-Path "logs" }
Check "prompts/ directory"           { Test-Path "prompts" }
Check "Telegram config exists"       { (Test-Path "config\telegram.json") -and ((Get-Item "config\telegram.json").Length -gt 0) }
Check "Strategy prompt exists"       { (Test-Path "config\strategy_prompt.json") -and ((Get-Item "config\strategy_prompt.json").Length -gt 0) }
Check "Zerodha config exists"        { Test-Path "config\zerodha.json" }
Check "Settings config exists"       { Test-Path "config\settings.json" }
Check "OpenClaw model config exists"  { Test-Path "config\openclaw_model.json" }
Check "OpenClaw 'main' agent exists"  {
    $agentsRaw = & openclaw agents list --json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $agentsRaw) {
        $false
    } else {
        $agentsData = $agentsRaw | ConvertFrom-Json
        $agents = if ($agentsData -is [System.Array]) { $agentsData } else { $agentsData.agents }
        @($agents | Where-Object { $_.id -eq "main" }).Count -gt 0
    }
}

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
Write-Host "  1. Make sure Chrome is installed; OpenClaw will open Kite and request login if needed"
Write-Host "  2. Activate venv: .\venv\Scripts\Activate.ps1"
Write-Host "  3. Run bot:    run.bat"
Write-Host ""

Read-Host "Press Enter to exit"
