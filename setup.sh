#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; }

echo "========================================"
echo " OpenClaw Trading Automation Setup"
echo "========================================"
echo ""

# ------------------------------------------------------------------
# Pre-flight checks
# ------------------------------------------------------------------
info "Checking environment requirements..."

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    fail "Python not found. Install Python 3.8+ first."
    exit 1
fi
PY_VER=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
PY_MAJOR=${PY_VER%%.*}
PY_MINOR=${PY_VER#*.}
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]; }; then
    fail "Python 3.8+ required (found $PYTHON $PY_VER)"
    exit 1
fi
ok "Python $PY_VER ($PYTHON)"

if command -v node &>/dev/null; then
    NODE_MAJOR=$(node --version 2>&1 | sed 's/v//' | cut -d. -f1)
    if [ "$NODE_MAJOR" -lt 22 ]; then
        fail "Node.js 22+ required (found $(node --version))"
        exit 1
    fi
    ok "Node.js $(node --version)"
else
    fail "Node.js not found. Install Node.js 22+ first."
    exit 1
fi

if command -v npm &>/dev/null; then
    ok "npm $(npm --version)"
else
    fail "npm not found."
    exit 1
fi

CHROME_FOUND=false
for cmd in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$cmd" &>/dev/null; then
        CHROME_FOUND=true
        ok "Browser: $cmd"
        break
    fi
done
if [ "$CHROME_FOUND" = false ]; then
    warn "Chrome/Chromium not found in PATH."
    warn "Install Chrome or Chromium for browser monitoring."
fi
echo ""

# ------------------------------------------------------------------
# Python virtual environment
# ------------------------------------------------------------------
if [ ! -d "venv" ]; then
    info "Creating Python virtual environment..."
    $PYTHON -m venv venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

# shellcheck disable=SC1091
source venv/bin/activate
if venv/bin/python -c "import requests, psutil, pygetwindow, playwright" &>/dev/null; then
    ok "Python dependencies already installed"
else
    info "Installing Python dependencies..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    ok "Python dependencies installed"
fi

# Install Playwright Chromium for Chrome tab inspection (cross-platform CDP detection)
if venv/bin/python -c "import playwright" &>/dev/null && [ -d ~/.cache/ms-playwright/chromium* ] 2>/dev/null; then
    ok "Playwright Chromium already installed"
else
    info "Installing Playwright Chromium..."
    venv/bin/python -m playwright install chromium 2>/dev/null || warn "Playwright browser install skipped (not critical)"
fi
echo ""

# ------------------------------------------------------------------
# OpenClaw installation
# ------------------------------------------------------------------
# Try running openclaw first (works if in PATH via any mechanism)
if openclaw --version &>/dev/null; then
    ok "OpenClaw already installed ($(openclaw --version))"
else
    # Check common npm global paths and add to PATH if found
    NPM_PREFIX=$(npm config get prefix)
    for _dir in "$NPM_PREFIX/bin" "$HOME/.npm-global/bin" "$HOME/node_modules/.bin"; do
        if [ -f "$_dir/openclaw" ] || [ -f "$_dir/openclaw.cmd" ]; then
            export PATH="$_dir:$PATH"
            break
        fi
    done
    if openclaw --version &>/dev/null; then
        ok "OpenClaw already installed ($(openclaw --version))"
    else
        info "Installing OpenClaw..."
        if [ ! -w "$NPM_PREFIX" ]; then
            LOCAL_NPM_DIR="$HOME/.npm-global"
            warn "npm global prefix ($NPM_PREFIX) not writable without sudo"
            info "Configuring npm to use local prefix: $LOCAL_NPM_DIR"
            mkdir -p "$LOCAL_NPM_DIR"
            npm config set prefix "$LOCAL_NPM_DIR"
            if ! grep -q '\.npm-global/bin' "$HOME/.bashrc" 2>/dev/null; then
                echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$HOME/.bashrc"
            fi
        fi
        NPM_BIN_DIR="$(npm config get prefix)/bin"
        export PATH="$NPM_BIN_DIR:$PATH"
        npm install -g openclaw
        ok "OpenClaw installed ($(openclaw --version))"
    fi
fi

# Ensure OpenClaw global config is valid (set gateway.mode local)
if openclaw --version &>/dev/null; then
    mkdir -p "${HOME}/.openclaw"
    if ! openclaw config validate &>/dev/null; then
        openclaw config set gateway.mode local 2>/dev/null || true
    fi
fi
echo ""

# ------------------------------------------------------------------
# Create missing directories
# ------------------------------------------------------------------
info "Creating project directories..."
mkdir -p logs prompts
ok "Directories: logs/, prompts/"
echo ""

# ------------------------------------------------------------------
# Configure Telegram Bot
# ------------------------------------------------------------------
TELEGRAM_CONFIG="config/telegram.json"

NEED_TELEGRAM=false
if [ ! -s "$TELEGRAM_CONFIG" ] || grep -q "YOUR_BOT_TOKEN\|YOUR_CHAT_ID" "$TELEGRAM_CONFIG" 2>/dev/null; then
    NEED_TELEGRAM=true
else
    read -r -p "Update Telegram credentials? (y/N): " UPDATE_TELEGRAM
    if [[ "$UPDATE_TELEGRAM" =~ ^[Yy]$ ]]; then
        NEED_TELEGRAM=true
    fi
fi

if [ "$NEED_TELEGRAM" = true ]; then
    echo ""
    echo "--- Telegram Group Setup ---"
    echo "1. Create a bot: Open Telegram, search @BotFather, send /newbot, follow prompts."
    echo "   Save the bot_token (looks like: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)."
    echo ""
    echo "2. Create a group: Telegram -> New Group, add your bot as a member."
    echo "   (Important: Bot must be in the group to send messages there.)"
    echo ""
    echo "3. Send a test message in the group (any text)."
    echo ""
    echo "4. Get the group chat_id:"
    echo "   Option A -- Search @getidsbot, add it to the group, it will reply with the chat ID."
    echo "   Option B -- Visit in browser (after step 3):"
    echo "     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
    echo "     Look for 'chat':{'id':-100...} -- that negative number is the group chat_id."
    echo "--------------------------------------------------------------------"
    read -r -p "Enter bot_token: " BOT_TOKEN
    read -r -p "Enter group chat_id (negative number, e.g. -1001234567890): " CHAT_ID
    cat > "$TELEGRAM_CONFIG" << EOF
{
  "bot_token": "$BOT_TOKEN",
  "chat_id": "$CHAT_ID"
}
EOF
    ok "Telegram config saved"
fi
echo ""

# ------------------------------------------------------------------
# Save strategy prompt
# ------------------------------------------------------------------
if [ -s "config/strategy_prompt.json" ]; then
    ok "Strategy prompt already exists at config/strategy_prompt.json"
else
    info "Saving strategy prompt..."
    cat > "config/strategy_prompt.json" << 'EOF'
{
  "strategy_type": "Intraday ATM Options Buying",
  "direction": {
    "timeframe": "15 min",
    "indicators": ["5 EMA", "20 EMA"],
    "rules": {
      "CE": "5 EMA crosses ABOVE 20 EMA on 15m chart → Enable ONLY CE trades",
      "PE": "5 EMA crosses BELOW 20 EMA on 15m chart → Enable ONLY PE trades"
    }
  },
  "strike_selection": {
    "type": "ATM",
    "rule": "If CE bias → Buy ATM CE; If PE bias → Buy ATM PE",
    "note": "ATM strike dynamically updates based on current underlying spot price"
  },
  "entry": {
    "timeframe": "3 min",
    "indicators": ["5 EMA", "20 EMA"],
    "conditions": {
      "CE": ["15m direction = Bullish", "ATM CE premium 5 EMA crosses ABOVE 20 EMA", "Current time inside allowed session", "Trade count limit not exceeded", "No active position running"],
      "PE": ["15m direction = Bearish", "ATM PE premium 5 EMA crosses BELOW 20 EMA", "Current time inside allowed session", "Trade count limit not exceeded", "No active position running"]
    }
  },
  "capital": { "usage": "100% of available capital per trade", "quantity": "Maximum possible lots using available margin, multiple lots allowed" },
  "risk_management": { "max_loss_per_trade": "10% of deployed capital", "example": "If capital = ₹20,000, max loss = ₹2,000" },
  "reward_target": { "min": "20% of deployed capital", "max": "50% of deployed capital", "configurable": true },
  "stop_loss": { "type": "EMA based", "indicator": "20 EMA of 3-minute premium chart", "condition": "Exit if premium price touches/closes beyond 20 EMA against trade direction" },
  "sessions": [
    { "name": "Morning", "start": "09:30", "end": "11:30", "max_trades": 2 },
    { "name": "Afternoon", "start": "13:00", "end": "15:00", "max_trades": 2 }
  ],
  "daily_limit": { "max_trades": 4, "rule": "After 4 completed trades, block all new entries" },
  "exit_conditions": ["Profit target hit (20%-50% of deployed capital)", "EMA stop loss hit (price crosses 20 EMA on 3m premium chart)", "Hard risk stop hit (loss reaches 10% of deployed capital)"],
  "position_management": { "max_active": 1, "rules": ["Only ONE active trade at a time", "No averaging", "No hedging", "No reverse entry without fresh signal", "Wait for fresh EMA crossover after exit"] },
  "auto_square_off": { "time": "15:15", "rule": "Exit all open positions before market close" },
  "safety": ["Duplicate order prevention", "API failure handling", "Internet reconnect handling", "Manual emergency stop", "Trade execution confirmation check"],
  "alerts": ["Trade entry", "Trade exit", "SL hit", "Target hit", "Session limit reached", "Daily trade limit reached", "API/order failure"],
  "logging": ["Entry time", "Exit time", "Direction (CE/PE)", "Strike selected", "Lot quantity", "Entry price", "Exit price", "P&L", "Exit reason", "Trade duration"],
  "flow": ["15m EMA Direction Check", "Determine CE or PE Bias", "Select ATM Option Premium", "Monitor 3m EMA Crossover", "Validate: Session timing, Trade count, No active trade", "Deploy 100% available capital", "Execute Buy Order", "Monitor: Target, 20 EMA SL, Hard SL", "Exit Trade", "Update Logs & Trade Count", "Wait For Fresh Signal"]
}
EOF
    ok "Strategy prompt saved to config/strategy_prompt.json"
fi
echo ""

# ------------------------------------------------------------------
# Configure OpenClaw model
# ------------------------------------------------------------------
MODEL_CONFIG="config/openclaw_model.json"
OC_GLOBAL_CONFIG="${HOME}/.openclaw/openclaw.json"

if [ -s "$MODEL_CONFIG" ] && ! grep -q "YOUR_API_KEY" "$MODEL_CONFIG" 2>/dev/null; then
    ok "OpenClaw model config already exists at $MODEL_CONFIG"
else
    echo ""
    echo "--- OpenClaw Model Configuration ---"
    echo "Select the AI model provider for OpenClaw:"
    echo "  1) OpenAI"
    echo "  2) OpenRouter"
    echo "  3) Anthropic"
    echo "  4) Google Gemini"
    echo "  5) Other (OpenAI-compatible)"
    read -r -p "Choice [1]: " MODEL_CHOICE
    MODEL_CHOICE=${MODEL_CHOICE:-1}

    case $MODEL_CHOICE in
        1) PROVIDER="openai"; DEFAULT_MODEL="gpt-4o" ;;
        2) PROVIDER="openrouter"; DEFAULT_MODEL="openrouter/auto" ;;
        3) PROVIDER="anthropic"; DEFAULT_MODEL="claude-sonnet-4-20250514" ;;
        4) PROVIDER="google"; DEFAULT_MODEL="gemini-2.5-pro" ;;
        5) PROVIDER="custom"; DEFAULT_MODEL="" ;;
    esac

    if [ "$PROVIDER" != "custom" ]; then
        read -r -p "Model [$DEFAULT_MODEL]: " MODEL_NAME
        MODEL_NAME=${MODEL_NAME:-$DEFAULT_MODEL}
    else
        read -r -p "Provider identifier (e.g. openai, openrouter): " PROVIDER
        read -r -p "Model name: " MODEL_NAME
    fi

    read -r -p "API key (leave blank to set later): " API_KEY

    # Save project model config
    cat > "$MODEL_CONFIG" << EOF
{
  "provider": "$PROVIDER",
  "model": "$MODEL_NAME",
  "api_key": "${API_KEY:-YOUR_API_KEY}"
}
EOF
    ok "Model config saved to $MODEL_CONFIG"

    # Save API key as env var (model is passed via CLI in runtime, not stored in global config)
    if [ -n "$API_KEY" ]; then
        ENV_VAR="${PROVIDER^^}_API_KEY"
        grep -q "$ENV_VAR" "${HOME}/.bashrc" 2>/dev/null || echo "export $ENV_VAR='$API_KEY'" >> "${HOME}/.bashrc"
        export "$ENV_VAR=$API_KEY"
        ok "API key saved to ~/.bashrc as $ENV_VAR"
    fi
fi
echo ""

# ------------------------------------------------------------------
# Set permissions
# ------------------------------------------------------------------
info "Setting executable permissions..."
chmod +x setup.sh
[ -f "run_bot.sh" ] && chmod +x run_bot.sh
ok "Permissions set"
echo ""

# ------------------------------------------------------------------
# Validation summary
# ------------------------------------------------------------------
echo "========================================"
echo " Setup Complete - Validation Summary"
echo "========================================"
echo ""

PASS=0
FAIL=0

check() {
    local desc=$1
    local cmd=$2
    if eval "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $desc"
        PASS=$((PASS+1))
    else
        echo -e "  ${RED}✗${NC} $desc"
        FAIL=$((FAIL+1))
    fi
}

check "Python virtual environment"    "[ -f venv/bin/python ]"
check "Python venv dependencies"       "venv/bin/python -c 'import requests, psutil'"
check "OpenClaw installed"           "command -v openclaw"
check "logs/ directory"              "[ -d logs ]"
check "prompts/ directory"           "[ -d prompts ]"
check "Telegram config exists"       "[ -s config/telegram.json ]"
check "Strategy prompt exists"       "[ -s config/strategy_prompt.json ]"
check "Zerodha config exists"        "[ -s config/zerodha.json ]"
check "Settings config exists"       "[ -s config/settings.json ]"
check "OpenClaw model config exists" "[ -s config/openclaw_model.json ]"
check "Playwright Chromium installed"  "venv/bin/python -c 'import playwright' 2>/dev/null"

echo ""
echo "  $PASS passed, $FAIL failed"
echo ""

if [ "$FAIL" -gt 0 ]; then
    warn "Some checks failed. Review output above."
else
    ok "All checks passed!"
fi

echo ""
echo "Next steps:"
echo "  1. Ensure Chrome is installed and logged into Zerodha"
echo "  2. Activate venv: source venv/bin/activate"
echo "  3. Run bot:    ./run_bot.sh"
echo ""
