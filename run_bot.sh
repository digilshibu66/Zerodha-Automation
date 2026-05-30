#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

CONFIGURE=false
REAUTH=false
RUNTIME_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --configure|-Configure|-configure) CONFIGURE=true ;;
        --reauth|-Reauth|-reauth) REAUTH=true ;;
        *) RUNTIME_ARGS+=("$arg") ;;
    esac
done

# Ensure OpenClaw installer locations are in PATH
OPENCLAW_PATHS=("$HOME/.local/bin" "$HOME/.npm-global/bin" "$HOME/node_modules/.bin")
if command -v npm >/dev/null 2>&1; then
    NPM_PREFIX=$(npm config get prefix 2>/dev/null || true)
    if [ -n "$NPM_PREFIX" ]; then
        OPENCLAW_PATHS+=("$NPM_PREFIX" "$NPM_PREFIX/bin")
    fi
fi
for _dir in "${OPENCLAW_PATHS[@]}"; do
    if [ -d "$_dir" ]; then
        export PATH="$_dir:$PATH"
    fi
done

write_model_config() {
    local provider="$1"
    local model="$2"
    local api_key="$3"
    local auth_type="${4:-api_key}"
    local auth_choice="${5:-}"
    local direct_key_arg="${6:-}"
    local env_var="${7:-}"
    mkdir -p config
    python - "$provider" "$model" "$api_key" "$auth_type" "$auth_choice" "$direct_key_arg" "$env_var" <<'PY'
import json
import sys

provider, model, api_key, auth_type, auth_choice, direct_key_arg, env_var = sys.argv[1:8]
data = {
    "provider": provider,
    "model": model,
    "api_key": api_key,
    "auth_type": auth_type,
    "auth_choice": auth_choice,
}
if direct_key_arg:
    data["direct_key_arg"] = direct_key_arg
if env_var:
    data["env_var"] = env_var
with open("config/openclaw_model.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

provider_option() {
    case "$1" in
        1) printf '%s\n' 'opencode|OpenCode Zen|api_key|opencode-zen|--opencode-zen-api-key|OPENCODE_API_KEY|opencode/claude-opus-4-6|opencode' ;;
        2) printf '%s\n' 'opencode-go|OpenCode Go|api_key|opencode-go|--opencode-go-api-key|OPENCODE_API_KEY|opencode-go/kimi-k2.6|opencode-go' ;;
        3) printf '%s\n' 'openai|OpenAI API|api_key|openai-api-key||OPENAI_API_KEY|openai/gpt-5.5|openai' ;;
        4) printf '%s\n' 'openai|OpenAI Codex OAuth|oauth|openai-codex|||openai/gpt-5.5|openai' ;;
        5) printf '%s\n' 'anthropic|Anthropic|api_key|apiKey||ANTHROPIC_API_KEY|anthropic/claude-opus-4-6|anthropic' ;;
        6) printf '%s\n' 'google|Google Gemini|api_key|gemini-api-key||GEMINI_API_KEY|google/gemini-3.1-pro-preview|google' ;;
        7) printf '%s\n' 'openrouter|OpenRouter|api_key|||OPENROUTER_API_KEY|openrouter/auto|openrouter' ;;
        *) return 1 ;;
    esac
}

openclaw_auth_setup() {
    local provider="$1"
    local model="$2"
    local api_key="$3"
    local auth_type="$4"
    local auth_choice="$5"
    local direct_key_arg="$6"
    local env_var="$7"

    if ! command -v openclaw >/dev/null 2>&1; then
        echo "OpenClaw is not installed or not on PATH. Run setup.sh first." >&2
        return 1
    fi

    if [ "$auth_type" = "api_key" ] && [ -n "$env_var" ] && [ -n "$api_key" ] && [ "$api_key" != "YOUR_API_KEY" ]; then
        export "$env_var=$api_key"
        if [ "$provider" = "google" ]; then
            export GOOGLE_API_KEY="$api_key"
        fi
    fi

    if [ -n "$auth_choice" ]; then
        echo "[INFO] Running OpenClaw onboarding for $provider"
        if [ -n "$direct_key_arg" ] && [ -n "$api_key" ] && [ "$api_key" != "YOUR_API_KEY" ]; then
            openclaw onboard "$direct_key_arg" "$api_key"
        else
            openclaw onboard --auth-choice "$auth_choice"
        fi
    elif [ "$auth_type" = "api_key" ]; then
        echo "[INFO] No OpenClaw onboarding command configured for $provider; using saved API key at runtime"
    fi

    if [ -n "$model" ]; then
        openclaw models set "$model" 2>/dev/null || openclaw config set agents.defaults.model.primary "$model" >/dev/null 2>&1 || true
    fi
    openclaw models list --provider "$provider" >/dev/null 2>&1 || true
}

write_platform_config() {
    local platform="$1"
    mkdir -p config
    python - "$platform" <<'PY'
import json
import sys

with open("config/platform.json", "w", encoding="utf-8") as f:
    json.dump({"platform": sys.argv[1]}, f, indent=2)
    f.write("\n")
PY
}

fetch_provider_models() {
    local provider="$1"
    local api_key="$2"
    python - "$provider" "$api_key" <<'PY'
import json
import sys
import urllib.error
import urllib.request

provider, api_key = sys.argv[1:3]
endpoints = {
    "openai": ("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"}),
    "openrouter": ("https://openrouter.ai/api/v1/models", {"Authorization": f"Bearer {api_key}"}),
    "anthropic": ("https://api.anthropic.com/v1/models", {"x-api-key": api_key, "anthropic-version": "2023-06-01"}),
    "opencode": ("https://opencode.ai/zen/v1/models", {}),
    "opencode-go": ("", {}),
    "google": (f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}", {}),
}
if provider == "opencode-go":
    print("opencode-go/kimi-k2.6")
    print("opencode-go/glm-5")
    print("opencode-go/minimax-m2.5")
    sys.exit(0)
if provider not in endpoints:
    sys.exit(0)
url, headers = endpoints[provider]
try:
    headers = dict(headers)
    headers.setdefault("User-Agent", "trading-automation-setup")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
except Exception:
    sys.exit(0)
models = sorted(item.get("id", "") for item in data.get("data", []) if item.get("id"))
if provider == "opencode":
    models = [f"opencode/{model}" for model in models]
elif provider == "google":
    models = sorted(
        f"google/{item.get('name', '').removeprefix('models/')}"
        for item in data.get("models", [])
        if "generateContent" in item.get("supportedGenerationMethods", [])
    )
for model in models[:30]:
    print(model)
PY
}

select_model() {
    local provider="$1"
    local api_key="$2"
    local default_model="$3"
    local models=()
    local selected=""

    while IFS= read -r model; do
        [ -n "$model" ] && models+=("$model")
    done < <(fetch_provider_models "$provider" "$api_key")

    if [ "${#models[@]}" -gt 0 ]; then
        echo "" >&2
        echo "Available models from $provider (showing up to 30):" >&2
        for i in "${!models[@]}"; do
            echo "$((i + 1)). ${models[$i]}" >&2
        done
        read -r -p "Choose model number, or press Enter for [$default_model]: " selected
        if [ -n "$selected" ]; then
            if [[ "$selected" =~ ^[0-9]+$ ]] && [ "$selected" -ge 1 ] && [ "$selected" -le "${#models[@]}" ]; then
                printf '%s\n' "${models[$((selected - 1))]}"
                return
            fi
            printf '%s\n' "$selected"
            return
        fi
    fi

    read -r -p "Model [$default_model]: " selected
    printf '%s\n' "${selected:-$default_model}"
}

configure_model_for_run() {
    local provider=""
    local model=""
    local api_key=""
    local auth_type="api_key"
    local auth_choice=""
    local direct_key_arg=""
    local env_var=""
    local has_config="false"

    if [ -s "config/openclaw_model.json" ]; then
        local saved
        saved=$(python - <<'PY' 2>/dev/null || true
import json
try:
    data=json.load(open("config/openclaw_model.json", encoding="utf-8"))
    print("\n".join([
        data.get("provider", ""),
        data.get("model", ""),
        data.get("api_key", ""),
        data.get("auth_type", "api_key"),
        data.get("auth_choice", ""),
        data.get("direct_key_arg", ""),
        data.get("env_var", ""),
    ]))
except Exception:
    pass
PY
)
        mapfile -t saved_lines <<< "$saved"
        provider="${saved_lines[0]:-}"
        model="${saved_lines[1]:-}"
        api_key="${saved_lines[2]:-}"
        auth_type="${saved_lines[3]:-api_key}"
        auth_choice="${saved_lines[4]:-}"
        direct_key_arg="${saved_lines[5]:-}"
        env_var="${saved_lines[6]:-}"
        if { [ "$auth_type" = "oauth" ] && [ -n "$provider" ] && [ -n "$model" ] && [ -n "$auth_choice" ]; } || \
           { [ -n "$provider" ] && [ -n "$model" ] && [ -n "$api_key" ] && [ "$api_key" != "YOUR_API_KEY" ]; }; then
            has_config="true"
        fi
    fi

    if [ "$has_config" = "true" ]; then
        echo ""
        echo "Current AI auth: $provider / $model / $auth_type"
        if [ "$REAUTH" = true ] && [ "$CONFIGURE" = false ]; then
            openclaw_auth_setup "$provider" "$model" "$api_key" "$auth_type" "$auth_choice" "$direct_key_arg" "$env_var"
            echo "[INFO] OpenClaw auth refreshed"
            return
        fi
        if [ "$CONFIGURE" = true ]; then
            change="y"
        else
            read -r -p "Re-auth or change provider? (y/N): " change
        fi
        case "$change" in
            y|Y) ;;
            *) echo "[INFO] Using existing AI provider config"; return ;;
        esac
    else
        echo ""
        echo "AI provider config is missing or incomplete."
    fi

    echo ""
    echo "Select AI provider:"
    echo "1. OpenCode Zen (API key)"
    echo "2. OpenCode Go (API key)"
    echo "3. OpenAI API key"
    echo "4. OpenAI Codex OAuth"
    echo "5. Anthropic API key"
    echo "6. Gemini API key"
    echo "7. OpenRouter API key"
    read -r -p "Choice [1]: " choice
    choice=${choice:-1}
    option=$(provider_option "$choice" || provider_option 1)
    IFS='|' read -r provider display_name auth_type auth_choice direct_key_arg env_var default_model model_provider <<< "$option"

    api_key=""
    if [ "$auth_type" = "api_key" ]; then
        while true; do
            read -r -s -p "Paste API key for $display_name: " api_key
            echo ""
            if [ -n "$api_key" ]; then
                break
            fi
            echo "API key is required for API-key auth."
        done
    else
        echo "[INFO] OAuth selected; OpenClaw will open its login/onboarding flow"
    fi
    model=$(select_model "$provider" "$api_key" "$default_model")
    if [ "$provider" = "opencode" ] && [[ "$model" != opencode/* ]]; then
        model="opencode/$model"
    fi
    if [ "$provider" = "opencode-go" ] && [[ "$model" != opencode-go/* ]]; then
        model="opencode-go/$model"
    fi
    if [ "$provider" = "openai" ] && [[ "$model" != openai/* ]]; then
        model="openai/$model"
    fi
    if [ "$provider" = "anthropic" ] && [[ "$model" != anthropic/* ]]; then
        model="anthropic/$model"
    fi
    if [ "$provider" = "openrouter" ] && [[ "$model" != openrouter/* ]]; then
        model="openrouter/$model"
    fi
    if [ "$provider" = "google" ] && [[ "$model" != google/* ]]; then
        model="google/$model"
    fi
    openclaw_auth_setup "$provider" "$model" "$api_key" "$auth_type" "$auth_choice" "$direct_key_arg" "$env_var"
    write_model_config "$provider" "$model" "$api_key" "$auth_type" "$auth_choice" "$direct_key_arg" "$env_var"
    echo "[INFO] AI provider config updated"
}

configure_platform_for_run() {
    local current="Zerodha"
    if [ -s "config/platform.json" ]; then
        current=$(python - <<'PY' 2>/dev/null || echo "Zerodha"
import json
try:
    data=json.load(open("config/platform.json", encoding="utf-8"))
    print(data.get("platform") or "Zerodha")
except Exception:
    print("Zerodha")
PY
)
    fi

    echo ""
    echo "Current trading platform: $current"
    read -r -p "Change trading platform? (y/N): " change
    if [ -s "config/platform.json" ]; then
        case "$change" in
            y|Y) ;;
            *) echo "[INFO] Using existing trading platform"; return ;;
        esac
    fi

    echo ""
    echo "Select trading platform:"
    echo "1. Zerodha"
    echo "2. Upstox"
    read -r -p "Choice [1]: " choice
    if [ "$choice" = "2" ]; then
        platform="Upstox"
    else
        platform="Zerodha"
    fi
    write_platform_config "$platform"
    echo "[INFO] Trading platform set to $platform"
}

if [ ! -d "venv" ]; then
    echo "ERROR: Virtual environment not found. Run setup.sh first." >&2
    exit 1
fi

source venv/bin/activate
configure_model_for_run
configure_platform_for_run
python core/runtime.py "${RUNTIME_ARGS[@]}"
