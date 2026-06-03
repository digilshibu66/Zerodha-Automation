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

- **OpenClaw installed** → agent opens Chrome using the OpenClaw-managed `openclaw` browser profile, checks selected-platform login, and sends Telegram updates
- **Provider/API key unavailable** → logs the provider preflight failure and stops before launching the OpenClaw agent
- **Not installed** → logs a warning and stops before monitoring

On Windows and Linux launcher flow, OpenClaw components open in separate terminals/consoles when supported:
- `run_bot.bat` / `run_bot.sh` terminal stays as the Python controller/log window
- `OpenClaw Gateway` terminal runs `openclaw gateway run`
- `OpenClaw TUI` terminal runs the saved strategy prompt with `openclaw agent`

Windows uses separate PowerShell console windows. Supported Linux terminal emulators for separate windows are `gnome-terminal`, `konsole`, `xfce4-terminal`, and `xterm`. If none are found, the bot falls back to the previous same-terminal/background behavior on Linux.

To smoke-test the Windows launcher wiring without starting real Gateway/TUI sessions, run this in PowerShell from the project root:

```powershell
.\tests\windows_launch_smoke.ps1
```

The smoke test checks launcher files, Python syntax, OpenClaw PATH availability, generated Gateway/TUI PowerShell wrappers, and that no PIN is present in tracked files. Use `-SkipOpenClawCheck` only when testing on a machine before OpenClaw is installed.

The runtime writes OpenClaw credentials to the current user's profile, for example `C:\Users\<you>\.openclaw\agents\main\agent\auth-profiles.json` on Windows. The file uses OpenClaw's `version: 1` auth profile format, so switching PCs requires entering the provider API key once on that PC.

For local browser/tool access, the runtime also sets `OPENCLAW_GATEWAY_TOKEN` automatically when it is missing and starts the Gateway with that same token. This lets the OpenClaw agent authenticate to the local Gateway without manually editing `C:\Users\<you>\.openclaw\openclaw.json`.

The generated prompt asks OpenClaw to use the OpenClaw-managed `openclaw` browser profile. This avoids Linux `existing-session` attach timeouts from the external `user` Chrome profile.

The runtime polls the configured Telegram group every second and writes new user messages to both `prompts/telegram_inbox.txt` and `~/.openclaw/workspace/prompts/telegram_inbox.txt`. It also writes the same messages to `prompts/telegram_priority_inbox.txt` and `~/.openclaw/workspace/prompts/telegram_priority_inbox.txt`; OpenClaw is instructed to check the priority inbox and `prompts/runtime_control.json` before browser/chart actions. Bot messages are ignored so Python does not loop on its own replies. If group messages do not appear, disable BotFather privacy mode for the bot or send command-style messages such as `/status`, `/wait`, `/resume`, `/quiet`, `/stop`.

Priority Telegram commands are handled immediately by Python: `STOP` stops bot actions, `WAIT`/`PAUSE` blocks new dummy entries while monitoring stays alive, `RESUME` allows chart-signal-gated entries again, `QUIET`/`MUTE ERRORS` confirms technical error-noise muting while market updates continue, and `STATUS` replies with current high-level state. Unknown user messages are acknowledged once and forwarded to the priority inbox for OpenClaw. Replies are deduped to avoid repeated heartbeat-style Telegram spam.

OpenClaw does not receive Telegram credentials and must not call Telegram directly. When it needs a Telegram alert, it appends one line to `prompts/openclaw_telegram_outbox.txt` in the OpenClaw workspace. The Python runtime reads that outbox, sends market/status/trade/login messages, and mutes technical browser/tool retry diagnostics such as browser page read, Chrome DevTools read, selector syntax, DOM inspection, tab cleanup, or retry noise.

When the selected platform is Upstox, OpenClaw first checks `https://pro.upstox.com/trading-charts`. If chart/watchlist/market data is visible, it treats the session as already logged in. If login is required, it navigates to `https://login.upstox.com`, fills the mobile number from untracked `config/upstox_login.json` when available, clicks Continue/Get OTP/Proceed to request OTP, and waits while the user manually enters OTP and PIN in Chrome. The PIN is never stored or auto-entered. After login it navigates back to the `chart.url` in `config/strategy_prompt.json`, selects the weekday target index (`NIFTY 50`/`NIFTY` on Monday, Tuesday, Friday; `SENSEX` on Wednesday, Thursday), and asks through Telegram before substituting any missing chart symbol, strike, or expiry.

The generated OpenClaw task also assigns the agent a programmer/operator role. If a recoverable runtime error, command failure, browser automation issue, missing config, or setup problem occurs, the agent is instructed to make the smallest safe fix, rerun the failed step, verify the result, and request Telegram status only for market condition, login/user action, dummy trade, or final verification updates. Transient browser page read, Chrome DevTools read, selector syntax, DOM inspection, tab cleanup, and retry diagnostics are logged/fixed silently and muted by the Python runtime. The runtime does not send periodic heartbeat spam; status is sent for starts/stops, priority Telegram replies, meaningful market state changes, and occasional active-session monitoring updates. It must not write real credentials or API keys into tracked files and must not change strategy rules unless explicitly requested.

During active market sessions, the Python strategy monitor sends periodic Telegram status updates even when no entry signal has fired yet. These updates summarize the target-index 15-minute direction check, ATM premium chart entry check, current session, browser-derived bias, entry wait/confirmation state, and trade counts. Python does not generate random dummy entries; it waits for OpenClaw to write a fresh browser-derived `prompts/chart_signal.json` diagnosis before recording any dummy entry or exit.

For the current Upstox setup, OpenClaw is instructed to diagnose the weekday target index on the 15-minute timeframe first, using only fully closed candles. Bullish bias requires the previous closed 15-minute candle 5 EMA <= 20 EMA and the latest closed 15-minute candle 5 EMA > 20 EMA; bearish bias requires the previous closed candle 5 EMA >= 20 EMA and the latest closed candle 5 EMA < 20 EMA. It then locates the nearest ATM strike to live target-index spot LTP in the option chain, uses the current/nearest weekly expiry unless the user specifies otherwise, and diagnoses both selected ATM CE/PE premium charts on the 3-minute timeframe. Both option charts should be checked and reported, but only the side allowed by the target-index 15-minute bias is eligible for a dummy entry.

The chart signal file must include browser-observed fields such as `timestamp`, `target_index`, `spot_ltp`, `atm_strike`, `expiry`, `index_bias`, `direction`, `ce_state`, `pe_state`, `entry_confirmed`, `entry_price` or `premium_price`, `current_price`, `dynamic_sl`, `hard_sl_price`, `target_price`, `exit_confirmed`, `exit_reason`, `exit_price`, `lots`, and `lot_size`. Stale or missing chart signals are treated as no-entry/waiting. Python uses separate freshness windows: entry EMA signals can be up to 180 seconds old because they are closed-candle based, but live premium price for SL/target exits must be 15 seconds old or newer. To keep browser reads fast, OpenClaw is instructed to keep the target-index chart and eligible ATM premium chart visible, refresh the eligible side every 5-10 seconds for current price/SL/target checks, and refresh the opposite side only every 30-60 seconds for status.

If the first OpenClaw browser/setup run exits with an error, the runtime starts one automatic recovery attempt with instructions to inspect logs/config, fix safely, rerun the failed step, verify, and report through Telegram. If recovery also fails, market monitoring is not started.

Startup waits 10 seconds for the OpenClaw gateway/browser service by default. If a slower machine needs more warmup time, set `OPENCLAW_GATEWAY_WAIT_SECONDS` before launching the bot.

### 5. Strategy Engine Loop

`run_strategy_cycle()` runs continuously (every 5 seconds from the runtime) and follows this decision flow:

```
Every 5s cycle:
  │
  ├── Check: daily trade count < 4?
  │     If not → STOP, send Telegram "Daily limit reached"
  │
  ├── Read fresh browser 15m EMA direction → CE or PE bias
  │
  ├── Check: inside a session window?
  │     ├── Morning:   09:30 - 11:30  (max 2 trades)
  │     └── Afternoon: 13:30 - 15:00  (max 2 trades)
  │     └── Outside both → sleep, skip
  │
  ├── Check: session trade count < session max?
  │     └── If session limit hit → Telegram "Session limit reached", skip
  │
  ├── Read fresh browser 3m ATM premium EMA crossover → entry confirmed?
  │     └── If not confirmed → sleep, skip
  │
  ├── Check: no active trade already running
  │
  ├── ENTER TRADE
  │     ├── Direction: CE/PE (from 15m)
  │     ├── Strike: nearest ATM from browser signal
  │     ├── Capital: 100% dummy deployed up to available capital
  │     ├── Lots/quantity: calculated from entry price and lot size when available
  │     ├── Telegram: "Trade entry: CE ATM | 2 lot(s) @ 145.50 | SL 142.50/130.95 | Target 174.60"
  │     └── Log to file
  │
  ├── MONITOR POSITION (3-6 monitor cycles)
  │     └── Exit when fresh observed premium price hits target / dynamic SL / hard SL, or OpenClaw confirms an exit
  │
  ├── EXIT TRADE
  │     ├── P&L: target = +20-50%, SL = 0 to -10%, hard SL = -10%
  │     ├── Telegram: "Trade exit: CE | P&L: +4500 | Reason: target"
  │     ├── Log: entry/exit time, direction, strike, lots, prices, P&L, reason, duration
  │     └── trade_count++
  │
  └── Sleep 5s, repeat
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
| 11:30 - 13:30 | — | Bot waits |
| 13:30 - 15:00 | **Afternoon** | 2 trades max |
| After 15:00 | — | Bot idle |
| 15:15 | Dummy square-off | Any dummy active position is closed in logs/Telegram only |

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
          │           ├── 5s loop
         │           ├── session check
         │           ├── direction (CE/PE)
         │           ├── entry confirmation
         │           ├── dummy signal recording only, no real broker order
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
| `simulation_mode` | `true` | Required. The runtime refuses to start if this is not `true`; no live trading is allowed. |
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
    "type": "Dynamic ATM",
    "rule": "CE bias → diagnose selected ATM CE; PE bias → diagnose selected ATM PE"
  },
  "entry": {
    "timeframe": "3 min",
    "indicators": ["5 EMA", "20 EMA"],
    "conditions": {
      "CE": ["15m direction = Bullish fresh closed-candle crossover", "ATM CE premium previous closed 3m candle 5 EMA <= 20 EMA and latest closed 3m candle 5 EMA > 20 EMA",
             "Inside allowed session", "Trade count not exceeded", "No active position"],
      "PE": ["15m direction = Bearish fresh closed-candle crossover", "ATM PE premium previous closed 3m candle 5 EMA <= 20 EMA and latest closed 3m candle 5 EMA > 20 EMA",
             "Inside allowed session", "Trade count not exceeded", "No active position"]
    }
  },
  "capital": { "usage": "100% per trade", "quantity": "Max lots by margin" },
  "risk_management": { "max_loss_per_trade": "10% of deployed capital" },
  "reward_target": { "min": "20%", "max": "50%", "configurable": true },
  "stop_loss": { "type": "Multi-condition", "indicator": "10% hard SL plus dynamic SL 2-3 points below entry" },
  "sessions": [
    { "name": "Morning", "start": "09:30", "end": "11:30", "max_trades": 2 },
    { "name": "Afternoon", "start": "13:30", "end": "15:00", "max_trades": 2 }
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
    "Calculate dummy deployment using 100% available capital",
    "Record Dummy Buy Signal (No Real Order)",
    "Monitor target, 20 EMA SL, hard SL",
    "Record Dummy Exit Signal (No Real Order)",
    "Update Logs & Trade Count",
    "Wait For Fresh Signal"
  ]
}
```

This config is written to `prompts/strategy_prompt.txt` with OpenClaw browser/login instructions.

### `config/telegram.json`

Generated by the setup script and ignored by git. Use `config/telegram.example.json` as the safe tracked template:

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
  telegram.example.json   # Safe Telegram config template
  telegram.json           # Bot token + group chat ID (generated by setup, untracked)
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
- `config/telegram.example.json` is the tracked placeholder; keep real Telegram credentials only in untracked `config/telegram.json`
- `simulation_mode: true` is mandatory — the runtime stops if it is changed, and no real trades are allowed
- OpenClaw may inspect broker charts after login, but it must never click real Buy/Sell/Order/Modify/Exit/Square-off/Submit/Confirm controls

---

## License

MIT
