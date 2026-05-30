#Requires -Version 5.1
param(
    [switch]$Configure,
    [switch]$Reauth
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Info  { Write-Host "[INFO]" -ForegroundColor Blue   -NoNewline; Write-Host " $args" }

function Read-JsonConfig($path) {
    if (Test-Path $path) {
        try { return Get-Content $path -Raw | ConvertFrom-Json } catch { return $null }
    }
    return $null
}

function Save-JsonConfig($path, $obj) {
    $dir = Split-Path -Parent $path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $json = $obj | ConvertTo-Json -Depth 5
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $json + [Environment]::NewLine, $utf8NoBom)
}

function Get-ProviderModels($provider, $apiKey) {
    try {
        switch ($provider) {
            "openai" {
                $response = Invoke-RestMethod -Uri "https://api.openai.com/v1/models" -Headers @{ Authorization = "Bearer $apiKey" } -TimeoutSec 20
                return @($response.data | ForEach-Object { $_.id } | Sort-Object)
            }
            "openrouter" {
                $response = Invoke-RestMethod -Uri "https://openrouter.ai/api/v1/models" -Headers @{ Authorization = "Bearer $apiKey" } -TimeoutSec 20
                return @($response.data | ForEach-Object { $_.id } | Sort-Object)
            }
            "anthropic" {
                $headers = @{ "x-api-key" = $apiKey; "anthropic-version" = "2023-06-01" }
                $response = Invoke-RestMethod -Uri "https://api.anthropic.com/v1/models" -Headers $headers -TimeoutSec 20
                return @($response.data | ForEach-Object { $_.id } | Sort-Object)
            }
            "opencode" {
                $response = Invoke-RestMethod -Uri "https://opencode.ai/zen/v1/models" -Headers @{ "User-Agent" = "trading-automation-setup" } -TimeoutSec 20
                return @($response.data | ForEach-Object { "opencode/$($_.id)" } | Sort-Object)
            }
            "opencode-go" {
                $models = @(Invoke-OpenClawModelsList "opencode-go")
                if ($models.Count -gt 0) { return $models }
                return @("opencode-go/kimi-k2.6", "opencode-go/glm-5", "opencode-go/minimax-m2.5")
            }
            "google" {
                $response = Invoke-RestMethod -Uri "https://generativelanguage.googleapis.com/v1beta/models?key=$apiKey" -TimeoutSec 20
                return @($response.models | Where-Object { $_.supportedGenerationMethods -contains "generateContent" } | ForEach-Object { "google/$($_.name -replace '^models/', '')" } | Sort-Object)
            }
        }
    } catch {
        Write-Host "Could not fetch model list for $provider. You can type the model manually." -ForegroundColor Yellow
    }
    return @()
}

function Get-ProviderOption($choice) {
    switch ($choice) {
        "1" { return @{ provider = "opencode"; display = "OpenCode Zen"; auth_type = "api_key"; auth_choice = "opencode-zen"; direct_key_arg = "--opencode-zen-api-key"; env_var = "OPENCODE_API_KEY"; default_model = "opencode/claude-opus-4-6"; model_provider = "opencode" } }
        "2" { return @{ provider = "opencode-go"; display = "OpenCode Go"; auth_type = "api_key"; auth_choice = "opencode-go"; direct_key_arg = "--opencode-go-api-key"; env_var = "OPENCODE_API_KEY"; default_model = "opencode-go/kimi-k2.6"; model_provider = "opencode-go" } }
        "3" { return @{ provider = "openai"; display = "OpenAI API"; auth_type = "api_key"; auth_choice = "openai-api-key"; direct_key_arg = ""; env_var = "OPENAI_API_KEY"; default_model = "openai/gpt-5.5"; model_provider = "openai" } }
        "4" { return @{ provider = "openai"; display = "OpenAI Codex OAuth"; auth_type = "oauth"; auth_choice = "openai-codex"; direct_key_arg = ""; env_var = ""; default_model = "openai/gpt-5.5"; model_provider = "openai" } }
        "5" { return @{ provider = "anthropic"; display = "Anthropic"; auth_type = "api_key"; auth_choice = "apiKey"; direct_key_arg = ""; env_var = "ANTHROPIC_API_KEY"; default_model = "anthropic/claude-opus-4-6"; model_provider = "anthropic" } }
        "6" { return @{ provider = "google"; display = "Google Gemini"; auth_type = "api_key"; auth_choice = "gemini-api-key"; direct_key_arg = ""; env_var = "GEMINI_API_KEY"; default_model = "google/gemini-3.1-pro-preview"; model_provider = "google" } }
        "7" { return @{ provider = "openrouter"; display = "OpenRouter"; auth_type = "api_key"; auth_choice = ""; direct_key_arg = ""; env_var = "OPENROUTER_API_KEY"; default_model = "openrouter/auto"; model_provider = "openrouter" } }
        default { return $null }
    }
}

function Invoke-OpenClawModelsList($provider) {
    try {
        $raw = & openclaw models list --provider $provider 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) { return @() }
        return @($raw | Where-Object { $_ -match "^\s*$provider/" } | ForEach-Object { ($_ -split "\s+")[0].Trim() } | Where-Object { $_ })
    } catch {
        return @()
    }
}

function Invoke-OpenClawAuthSetup($config) {
    $provider = $config.provider
    $model = $config.model
    $authType = if ($config.auth_type) { $config.auth_type } else { "api_key" }
    $authChoice = if ($config.auth_choice) { $config.auth_choice } else { "" }
    $apiKey = if ($config.api_key) { $config.api_key } else { "" }
    $directKeyArg = if ($config.direct_key_arg) { $config.direct_key_arg } else { "" }
    $envVar = if ($config.env_var) { $config.env_var } else { "" }

    if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) {
        Write-Host "OpenClaw is not installed or not on PATH. Run setup.bat first." -ForegroundColor Yellow
        return $false
    }

    if ($authType -eq "api_key" -and $envVar -and $apiKey -and $apiKey -ne "YOUR_API_KEY") {
        Set-Item -Path "Env:$envVar" -Value $apiKey
        if ($provider -eq "google") {
            $env:GOOGLE_API_KEY = $apiKey
        }
    }

    if ($authChoice) {
        try {
            if ($directKeyArg -and $apiKey -and $apiKey -ne "YOUR_API_KEY") {
                Info "Running OpenClaw onboarding for $provider"
                & openclaw onboard $directKeyArg $apiKey
            } else {
                Info "Running OpenClaw onboarding for $provider"
                & openclaw onboard --auth-choice $authChoice
            }
            if ($LASTEXITCODE -ne 0) {
                Write-Host "OpenClaw onboarding did not complete successfully." -ForegroundColor Yellow
                return $false
            }
        } catch {
            Write-Host "OpenClaw onboarding failed: $_" -ForegroundColor Yellow
            return $false
        }
    } elseif ($authType -eq "api_key") {
        Info "No OpenClaw onboarding command configured for $provider; using saved API key at runtime"
    }

    if ($model) {
        try {
            & openclaw models set $model 2>$null
            if ($LASTEXITCODE -ne 0) {
                & openclaw config set agents.defaults.model.primary $model 2>$null | Out-Null
            }
        } catch {
            try { & openclaw config set agents.defaults.model.primary $model 2>$null | Out-Null } catch {}
        }
    }
    try { & openclaw models list --provider $provider 2>$null | Out-Null } catch {}
    return $true
}

function Select-Model($provider, $apiKey, $defaultModel) {
    $models = @(Get-ProviderModels $provider $apiKey)
    if ($models.Count -gt 0) {
        Write-Host ""
        Write-Host "Available models from $provider (showing up to 30):" -ForegroundColor Cyan
        $shown = @($models | Select-Object -First 30)
        for ($i = 0; $i -lt $shown.Count; $i++) {
            Write-Host "$($i + 1). $($shown[$i])"
        }
        $choice = Read-Host "Choose model number, or press Enter for [$defaultModel]"
        if (-not [string]::IsNullOrWhiteSpace($choice)) {
            $idx = 0
            if ([int]::TryParse($choice, [ref]$idx) -and $idx -ge 1 -and $idx -le $shown.Count) {
                return $shown[$idx - 1]
            }
            return $choice
        }
    }

    $modelName = Read-Host "Model [$defaultModel]"
    if ([string]::IsNullOrWhiteSpace($modelName)) { return $defaultModel }
    return $modelName
}

function Read-ApiKey($provider) {
    return Read-Host "Paste API key for $provider"
}

function Configure-ModelForRun {
    $modelConfig = Join-Path $scriptDir "config\openclaw_model.json"
    $existing = Read-JsonConfig $modelConfig
    $existingAuthType = if ($existing -and $existing.auth_type) { $existing.auth_type } else { "api_key" }
    $hasApiKeyConfig = $existing -and $existing.provider -and $existing.model -and $existing.api_key -and $existing.api_key -ne "YOUR_API_KEY"
    $hasOauthConfig = $existing -and $existing.provider -and $existing.model -and $existingAuthType -eq "oauth" -and $existing.auth_choice
    $hasUsableConfig = $hasApiKeyConfig -or $hasOauthConfig

    if ($hasUsableConfig) {
        Write-Host ""
        Write-Host "Current AI auth: $($existing.provider) / $($existing.model) / $existingAuthType" -ForegroundColor Cyan
        if ($Reauth -and -not $Configure) {
            if (Invoke-OpenClawAuthSetup $existing) { Info "OpenClaw auth refreshed" }
            return
        }
        if (-not $Configure) {
            Info "Using existing AI provider config"
            return
        }
        $change = "y"
        if ($change -ne "y" -and $change -ne "Y") {
            Info "Using existing AI provider config"
            return
        }
    } else {
        Write-Host ""
        Write-Host "AI provider config is missing or incomplete." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Select AI provider:" -ForegroundColor White
    Write-Host "1. OpenCode Zen (API key)" -ForegroundColor White
    Write-Host "2. OpenCode Go (API key)" -ForegroundColor White
    Write-Host "3. OpenAI API key" -ForegroundColor White
    Write-Host "4. OpenAI Codex OAuth" -ForegroundColor White
    Write-Host "5. Anthropic API key" -ForegroundColor White
    Write-Host "6. Gemini API key" -ForegroundColor White
    Write-Host "7. OpenRouter API key" -ForegroundColor White
    $choice = Read-Host "Choice [1]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }
    $providerInfo = Get-ProviderOption $choice
    if (-not $providerInfo) {
        Write-Host "Unsupported choice. Defaulting to OpenCode Zen." -ForegroundColor Yellow
        $providerInfo = Get-ProviderOption "1"
    }

    $provider = $providerInfo.provider
    $authType = $providerInfo.auth_type
    $defaultModel = $providerInfo.default_model
    $apiKey = ""

    if ($authType -eq "api_key") {
        do {
            $apiKey = Read-ApiKey $providerInfo.display
            if ([string]::IsNullOrWhiteSpace($apiKey)) {
                Write-Host "API key is required for API-key auth." -ForegroundColor Yellow
            }
        } while ([string]::IsNullOrWhiteSpace($apiKey))
    } else {
        Info "OAuth selected; OpenClaw will open its login/onboarding flow"
    }

    $modelName = Select-Model $provider $apiKey $defaultModel
    if ($provider -eq "opencode" -and $modelName -notmatch "^opencode/") { $modelName = "opencode/$modelName" }
    if ($provider -eq "opencode-go" -and $modelName -notmatch "^opencode-go/") { $modelName = "opencode-go/$modelName" }
    if ($provider -eq "openai" -and $modelName -notmatch "^openai/") { $modelName = "openai/$modelName" }
    if ($provider -eq "anthropic" -and $modelName -notmatch "^anthropic/") { $modelName = "anthropic/$modelName" }
    if ($provider -eq "openrouter" -and $modelName -notmatch "^openrouter/") { $modelName = "openrouter/$modelName" }
    if ($provider -eq "google" -and $modelName -notmatch "^google/") { $modelName = "google/$modelName" }

    $newConfig = @{
        provider = $provider
        model = $modelName
        auth_type = $authType
        auth_choice = $providerInfo.auth_choice
        api_key = $apiKey
    }
    if ($providerInfo.direct_key_arg) { $newConfig.direct_key_arg = $providerInfo.direct_key_arg }
    if ($providerInfo.env_var) { $newConfig.env_var = $providerInfo.env_var }

    if (Invoke-OpenClawAuthSetup $newConfig) {
        Save-JsonConfig $modelConfig $newConfig
        Info "AI provider config updated"
    } else {
        Write-Host "AI provider config was not saved because OpenClaw auth setup failed." -ForegroundColor Yellow
        exit 1
    }
}

function Configure-PlatformForRun {
    $platformConfig = Join-Path $scriptDir "config\platform.json"
    $existing = Read-JsonConfig $platformConfig
    $current = if ($existing -and $existing.platform) { $existing.platform } else { "Zerodha" }

    Write-Host ""
    Write-Host "Current trading platform: $current" -ForegroundColor Cyan
    if (-not $Configure -and $existing -and $existing.platform) {
        Info "Using existing trading platform"
        return
    }
    $change = Read-Host "Change trading platform? (y/N)"
    if ($change -ne "y" -and $change -ne "Y" -and $existing -and $existing.platform) {
        Info "Using existing trading platform"
        return
    }

    Write-Host ""
    Write-Host "Select trading platform:" -ForegroundColor White
    Write-Host "1. Zerodha" -ForegroundColor White
    Write-Host "2. Upstox" -ForegroundColor White
    $choice = Read-Host "Choice [1]"
    if ($choice -eq "2") { $platform = "Upstox" } else { $platform = "Zerodha" }

    Save-JsonConfig $platformConfig @{ platform = $platform }
    Info "Trading platform set to $platform"
}

# Ensure OpenClaw installer locations are in PATH
$pathCandidates = @(
    (Join-Path $env:USERPROFILE ".local\bin"),
    (Join-Path $env:APPDATA "npm"),
    (Join-Path $env:LOCALAPPDATA "npm"),
    (Join-Path $env:LOCALAPPDATA "OpenClaw\deps\portable-node")
)

$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if ($npmCmd) {
    $npmPrefix = & $npmCmd.Source config get prefix 2>$null
    if ($npmPrefix) {
        $pathCandidates += $npmPrefix
        $pathCandidates += (Join-Path $npmPrefix "bin")
    }
}

foreach ($candidate in $pathCandidates) {
    if ($candidate -and (Test-Path $candidate)) {
        $env:Path = "$candidate;$env:Path"
    }
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

Configure-ModelForRun
Configure-PlatformForRun

# Run the bot
try {
    & python core\runtime.py $args
} catch {
    Write-Host "[ERROR] Bot crashed: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Read-Host "Press Enter to exit"
