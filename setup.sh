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

info "Installing Python dependencies..."
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "Python dependencies installed"
echo ""

# ------------------------------------------------------------------
# OpenClaw installation
# ------------------------------------------------------------------
info "Installing OpenClaw..."
if command -v openclaw &>/dev/null; then
    ok "OpenClaw already installed ($(openclaw --version))"
else
    NPM_PREFIX=$(npm config get prefix)
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
    # Ensure npm bin directory is in PATH
    LOCAL_NPM_DIR="$(npm config get prefix)"
    export PATH="$LOCAL_NPM_DIR/bin:$PATH"
    npm install -g openclaw
    ok "OpenClaw installed ($(openclaw --version))"
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
info "Saving strategy prompt..."
cat > "config/strategy_prompt.json" << 'EOF'
{
  "timeframe": "15 min",
  "direction_logic": "5 EMA crossing above 20 EMA → CE only; 5 EMA crossing below 20 EMA → PE only",
  "confirmation": "3 min premium chart confirmation before signal",
  "instrument": "ATM option (dynamic)"
}
EOF
ok "Strategy prompt saved to config/strategy_prompt.json"
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
