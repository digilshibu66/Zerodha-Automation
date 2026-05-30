# TRADING-AUTOMATION

OpenClaw-based automated intraday options monitoring and dummy trade simulation for Zerodha + Telegram.

**Phase 2** — Full pipeline with OpenClaw-managed Chrome/Zerodha checks, configurable strategy loop, and cross-platform launcher scripts.

---

## Pipeline

```
Launcher → Prompt prep → OpenClaw opens Chrome/Zerodha → Login check → Strategy engine loop → Telegram alerts → Cleanup
```

Every step sends a Telegram notification so you know the bot's status in real time.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.8+ |
| Node.js | 22+ |
| Chrome | Any recent version |
| Telegram account | For bot + group setup |

---

## Quick Start

### Windows

```batch
setup.bat
run.bat
```

### Linux / macOS

```bash
./setup.sh
./run.sh
```

`setup.bat` / `setup.sh` installs everything: Python venv, dependencies, OpenClaw, and prompts for Telegram credentials.

---

## Setup Details

### Step 1 — Clone & Run Setup

```bash
git clone <repo-url>
cd TRADING-AUTOMATION
```

Run the setup script for your platform. It will:
- Check for Python 3.8+, Node.js/npm, and Chrome; the OpenClaw installer can bootstrap Node/npm when needed
- Create a Python virtual environment (`venv/`)
- Reuse an existing Python virtual environment and install missing requirements only
- Check/install Git on Windows before OpenClaw setup so the installer does not need to bootstrap portable Git
- Install OpenClaw with the official OpenClaw installer
- Show installer download/progress output for troubleshooting
- Show an elapsed-time spinner while the OpenClaw installer is running
- Create `logs/` and `prompts/` directories
- Prompt for Telegram bot configuration
- Generate the default strategy config
- Run a validation summary

OpenClaw is installed with the official installer command for each platform:

```powershell
powershell -c "irm https://openclaw.ai/install.ps1 | iex"
```

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

### Step 2 — Telegram Group Setup

The bot sends alerts to a Telegram group. During setup you'll need:

1. **Create a bot** — Open Telegram, search `@BotFather`, send `/newbot`, save the `bot_token`
2. **Create a group** — New Group in Telegram, add your bot as a member
3. **Send a test message** in the group
4. **Get the group chat_id** — either:
   - Add `@getidsbot` to the group (it replies with the ID)
   - Or visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` after sending a message and look for `"chat":{"id":-100...}` (the negative number is your group chat_id)

### Step 3 — Run the Bot

```bash
# Windows
run.bat

# Linux / macOS
./run.sh
```

---

## Full Workflow

### 1. Launch

`run.bat` / `run.sh` launches the platform-specific runner, activates the Python virtual environment, and runs `core/runtime.py`.

On each run, the launcher checks saved config first:
- AI auth/model in `config/openclaw_model.json`. If complete, the Windows launcher reuses it automatically; pass `-Configure` or `-Reauth` only when you want to change or refresh auth.
- First-time setup or reauth can configure OpenCode Zen, OpenCode Go, OpenAI API, OpenAI Codex OAuth, Anthropic, Gemini, or OpenRouter. API-key flows save the key in project config; OAuth flows use OpenClaw-managed auth.
- OpenClaw onboarding/model setup is run by the launcher during first setup or reauth, then `openclaw models set <provider/model>` sets the selected default model.
- Trading platform in `config/platform.json` (`Zerodha` or `Upstox`). If complete, the Windows launcher reuses it automatically; pass `-Configure` to change it.

To force provider setup, run `run_bot.ps1 -Configure` on Windows or `./run_bot.sh --configure` on Linux/macOS. To re-run OpenClaw auth for the saved provider, run `run_bot.ps1 -Reauth` or `./run_bot.sh --reauth`.

### 2. Startup Checks

| Step | What happens | Telegram alert |
|---|---|---|
| Load settings | Reads `config/settings.json` for simulation mode, alerts, arch doc path | "Bot starting" |
| Provider preflight | Checks the configured AI provider/API key before launching OpenClaw | Failure alert if OpenClaw cannot continue |
| OpenClaw browser task | OpenClaw opens Chrome and navigates to the selected platform | Login request or confirmation |
| Platform login check | OpenClaw inspects Zerodha/Upstox for dashboard/login state | Login reminder or confirmation |

If the selected platform is not logged in, OpenClaw asks for login through Telegram and retries before monitoring.

### 3. Prompt Preparation

Reads `config/strategy_prompt.json` (the full 16-section strategy) and writes a generated prompt to `prompts/strategy_prompt.txt`. The prompt includes:
- Instructions for OpenClaw to open Chrome and verify Zerodha login itself
- All strategy rules (direction logic, entry conditions, sessions, risk, targets, SL, exits)
- Operating instructions for the two session windows

If `architecture_doc_path` is set in `settings.json`, that document is also loaded into context.

### 4. OpenClaw Launch

Runs the configured OpenClaw agent with the generated prompt:

- **OpenClaw installed** → agent opens Chrome using the `user` Chrome profile, checks selected-platform login, and sends Telegram updates
- **Provider/API key unavailable** → logs the provider preflight failure and stops before launching the OpenClaw agent
- **Not installed** → logs a warning and stops before monitoring

The runtime writes OpenClaw credentials to the current user's profile, for example `C:\Users\<you>\.openclaw\agents\main\agent\auth-profiles.json` on Windows. The file uses OpenClaw's `version: 1` auth profile format, so switching PCs requires entering the provider API key once on that PC.

For local browser/tool access, the runtime also sets `OPENCLAW_GATEWAY_TOKEN` automatically when it is missing and starts the Gateway with that same token. This lets the OpenClaw agent authenticate to the local Gateway without manually editing `C:\Users\<you>\.openclaw\openclaw.json`.

The generated prompt asks OpenClaw to use the `user` Chrome profile so an existing browser login/session can be reused. If OpenClaw cannot attach to that profile, close normal Chrome windows and relaunch Chrome with remote debugging enabled before running the bot again.

The runtime polls the configured Telegram group every 5 seconds and writes new messages to `prompts/telegram_inbox.txt`. These messages are also logged in the launcher console, so messages sent in the group appear in `run_bot.ps1` while the bot is running. OpenClaw is instructed to read this inbox while waiting for login, chart selection, STOP/WAIT commands, or user assistance. If group messages do not appear, disable BotFather privacy mode for the bot or send command-style messages such as `/nifty`, `/sensex`, `/stop`.

When the selected platform is Upstox, OpenClaw waits while the user selects a Chrome profile or completes login, rechecking login state every 5 seconds. After login it navigates to the `chart.url` in `config/strategy_prompt.json` and selects the configured `chart.symbol` such as `NIFTY`; if the symbol cannot be found, it asks through Telegram before clicking another chart.

The generated OpenClaw task also assigns the agent a programmer/operator role. If a recoverable runtime error, command failure, browser automation issue, missing config, or setup problem occurs, the agent is instructed to make the smallest safe fix, rerun the failed step, verify the result, and report status through Telegram. It must not write real credentials or API keys into tracked files and must not change strategy rules unless explicitly requested.

If the first OpenClaw browser/setup run exits with an error, the runtime starts one automatic recovery attempt with instructions to inspect logs/config, fix safely, rerun the failed step, verify, and report through Telegram. If recovery also fails, market monitoring is not started.

Startup waits 30 seconds for the OpenClaw gateway/browser service by default. If a slower machine needs more warmup time, set `OPENCLAW_GATEWAY_WAIT_SECONDS` before launching the bot.

### 5. Strategy Engine Loop

`run_strategy_cycle()` runs continuously (every 30 seconds by default) and follows this decision flow:

```
Every 30s cycle:
  │
  ├── Check: daily trade count < 4?
  │     If not → STOP, send Telegram "Daily limit reached"
  │
  ├── Simulate 15m EMA direction → CE or PE bias
  │
  ├── Check: inside a session window?
  │     ├── Morning:   09:30 - 11:30  (max 2 trades)
  │     └── Afternoon: 13:00 - 15:00  (max 2 trades)
  │     └── Outside both → sleep, skip
  │
  ├── Check: session trade count < session max?
  │     └── If session limit hit → Telegram "Session limit reached", skip
  │
  ├── Simulate 3m EMA crossover → entry confirmed?
  │     └── If not confirmed → sleep, skip
  │
  ├── Check: no active trade already running
  │
  ├── ENTER TRADE
  │     ├── Direction: CE/PE (from 15m)
  │     ├── Strike: ATM
  │     ├── Capital: 100% deployed
  │     ├── Lots: 1-3 (simulated)
  │     ├── Telegram: "Trade entry: CE ATM | 2 lot(s) @ 145.50"
  │     └── Log to file
  │
  ├── MONITOR POSITION (3-6 monitor cycles)
  │     └── Simulate exit reason: target / SL / hard SL
  │
  ├── EXIT TRADE
  │     ├── P&L: target = +20-50%, SL = 0 to -10%, hard SL = -10%
  │     ├── Telegram: "Trade exit: CE | P&L: +4500 | Reason: target"
  │     ├── Log: entry/exit time, direction, strike, lots, prices, P&L, reason, duration
  │     └── trade_count++
  │
  └── Sleep 30s, repeat
```

### 6. Shutdown

Press Ctrl+C or the bot catches `KeyboardInterrupt`:

- Stops OpenClaw gracefully (SIGTERM → kill if unresponsive)
- Telegram: "Bot stopped"
- Final summary logged with trade count and total P&L

---

## Trading Sessions

| Time | Session | Max Trades |
|---|---|---|
| Before 09:30 | — | Bot waits |
| 09:30 - 11:30 | **Morning** | 2 trades max |
| 11:30 - 13:00 | — | Bot waits |
| 13:00 - 15:00 | **Afternoon** | 2 trades max |
| After 15:00 | — | Bot idle |
| 15:15 | Auto square-off | All positions closed |

Daily cap: **4 trades max**. After 4, no new entries allowed.

---

## Data Flow Diagram

```
User runs:
  run.bat / run.sh
         │
         ▼
  runtime.py ─────────────────────────────► Telegram: "Bot starting"
         │
         ├── openclaw_manager
         │     ├── prepare_prompt() ──────► writes prompts/strategy_prompt.txt
         │     │                            (strategy + OpenClaw browser/login instructions)
         │     └── run_openclaw_agent() ──► OpenClaw opens Chrome and checks Zerodha login
         │
         ├── strategy_engine
         │     └── run_strategy_cycle() ──► Telegram: entry, exit, SL, limit alerts
         │           │
         │           ├── 30s loop
         │           ├── session check
         │           ├── direction (CE/PE)
         │           ├── entry confirmation
         │           ├── trade execution (simulated)
         │           ├── position monitoring
         │           ├── exit (target/SL/hard SL)
         │           └── logs to logs/strategy_YYYY-MM-DD.log
         │
         └── cleanup
               └── stop_openclaw() ───────► Telegram: "Bot stopped"
```

---

## Configuration

### `config/settings.json`

```json
{
  "simulation_mode": true,
  "telegram_alerts": true,
  "logging_enabled": true,
  "architecture_doc_path": "/path/to/architecture-doc.txt"
}
```

| Key | Default | Description |
|---|---|---|
| `simulation_mode` | `true` | All trades simulated. Set to `false` for live (use at your own risk). |
| `telegram_alerts` | `true` | Send Telegram notifications per event. |
| `logging_enabled` | `true` | Write timestamped logs to `logs/strategy_YYYY-MM-DD.log`. |
| `architecture_doc_path` | `null` | Optional path to an architecture reference document. |

### `config/strategy_prompt.json`

The full 16-section Intraday ATM Options Buying Strategy:

```json
{
  "strategy_type": "Intraday ATM Options Buying",
  "direction": {
    "timeframe": "15 min",
    "indicators": ["5 EMA", "20 EMA"],
    "rules": {
      "CE": "5 EMA crosses ABOVE 20 EMA on 15m → Enable ONLY CE",
      "PE": "5 EMA crosses BELOW 20 EMA on 15m → Enable ONLY PE"
    }
  },
  "strike_selection": {
    "type": "ATM",
    "rule": "CE bias → Buy ATM CE; PE bias → Buy ATM PE"
  },
  "entry": {
    "timeframe": "3 min",
    "indicators": ["5 EMA", "20 EMA"],
    "conditions": {
      "CE": ["15m direction = Bullish", "ATM CE premium 5 EMA crosses ABOVE 20 EMA",
             "Inside allowed session", "Trade count not exceeded", "No active position"],
      "PE": ["15m direction = Bearish", "ATM PE premium 5 EMA crosses BELOW 20 EMA",
             "Inside allowed session", "Trade count not exceeded", "No active position"]
    }
  },
  "capital": { "usage": "100% per trade", "quantity": "Max lots by margin" },
  "risk_management": { "max_loss_per_trade": "10% of deployed capital" },
  "reward_target": { "min": "20%", "max": "50%", "configurable": true },
  "stop_loss": { "type": "EMA based", "indicator": "20 EMA of 3m premium chart" },
  "sessions": [
    { "name": "Morning", "start": "09:30", "end": "11:30", "max_trades": 2 },
    { "name": "Afternoon", "start": "13:00", "end": "15:00", "max_trades": 2 }
  ],
  "daily_limit": { "max_trades": 4 },
  "exit_conditions": [
    "Profit target hit (20-50%)",
    "EMA stop loss hit (20 EMA crossover)",
    "Hard risk stop hit (10% loss)"
  ],
  "position_management": {
    "max_active": 1,
    "rules": ["No averaging", "No hedging", "Wait for fresh EMA crossover after exit"]
  },
  "auto_square_off": { "time": "15:15" },
  "safety": ["Duplicate prevention", "API failure handling", "Emergency stop"],
  "alerts": ["Entry", "Exit", "SL", "Target", "Session limit", "Daily limit"],
  "logging": ["Entry/Exit time", "Direction", "Strike", "Lots", "Prices", "P&L", "Reason"],
  "flow": [
    "15m EMA Direction Check",
    "Determine CE or PE Bias",
    "Select ATM Option Premium",
    "Monitor 3m EMA Crossover",
    "Validate session, trade count, no active trade",
    "Deploy 100% capital",
    "Execute Buy Order",
    "Monitor target, 20 EMA SL, hard SL",
    "Exit Trade",
    "Update Logs & Trade Count",
    "Wait For Fresh Signal"
  ]
}
```

This config is written to `prompts/strategy_prompt.txt` with OpenClaw browser/login instructions.

### `config/telegram.json`

Generated by the setup script:

```json
{
  "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
  "chat_id": "-1001234567890"
}
```

---

## Log Output Example

Every trade event is logged to `logs/strategy_YYYY-MM-DD.log`:

```
[2026-05-25T09:35:12.123] Session: Morning | Direction: CE | Entry: confirmed | Trades: 1/2 (session) | 1/4 (daily)
[2026-05-25T09:35:12.456] TRADE ENTRY | CE | ATM | 2 lot(s) | Entry: 145.50 | Capital: 20000
[2026-05-25T09:37:45.789] TRADE EXIT | CE | ATM | 2 lot(s) | Entry: 145.50 | Exit: 172.30 | P&L: +5360.0 | Reason: target | Duration: 2.6min
[2026-05-25T10:05:30.001] Session: Morning | Direction: PE | Entry: confirmed | Trades: 2/2 (session) | 2/4 (daily)
[2026-05-25T10:05:30.234] TRADE ENTRY | PE | ATM | 3 lot(s) | Entry: 78.20 | Capital: 20000
[2026-05-25T10:08:12.567] TRADE EXIT | PE | ATM | 3 lot(s) | Entry: 78.20 | Exit: 70.38 | P&L: -2000.0 | Reason: hard_sl | Duration: 2.7min
[2026-05-25T10:08:12.890] Session limit reached: Morning
```

---

## Project Structure

```
config/
  settings.json           # Simulation mode, alerts, arch doc path
  strategy_prompt.json    # Full 16-section strategy definition
  telegram.json           # Bot token + group chat ID (generated by setup)
  zerodha.json            # Platform config
core/
  openclaw_manager.py     # OpenClaw lifecycle + prompt preparation
  strategy_engine.py      # Session-aware strategy monitoring loop
  telegram_manager.py     # Telegram notification dispatcher
  runtime.py              # Pipeline orchestrator
logs/                     # Timestamped strategy logs
prompts/                  # Generated OpenClaw prompt files
setup.bat                 # Windows: launches setup.ps1
setup.ps1                 # Windows: full environment setup
setup.sh                  # Linux/macOS: full environment setup
run_bot.bat               # Windows: launches run_bot.ps1
run_bot.ps1               # Windows: venv activation + bot runner
run_bot.sh                # Linux/macOS: venv activation + bot runner
run.bat                   # Windows: short wrapper for run_bot.bat
run.sh                    # Linux/macOS: short wrapper for run_bot.sh
requirements.txt          # Python dependencies
AGENTS.md                 # Agent instructions for opencode.ai
```

---

## Security

- No live API tokens or credentials in git-tracked files
- `config/telegram.json` is populated interactively by the setup script
- Add `config/telegram.json` to `.gitignore` to prevent accidental commits
- `simulation_mode: true` is the default — no real trades are placed

---

## License

MIT
