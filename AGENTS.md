# TRADING-AUTOMATION — Agent Instructions

## Project Overview
OpenClaw-based automated intraday options monitoring and dummy trade simulation for Zerodha + Telegram.

## Key Files
| File | Purpose |
|---|---|
| `setup.ps1` / `setup.sh` | Full environment setup (venv, OpenClaw, deps, config) |
| `setup.bat` | Launches `setup.ps1` on Windows |
| `run.bat` | Short Windows launcher for `run_bot.bat` |
| `run.sh` | Short Linux/Mac launcher for `run_bot.sh` |
| `run_bot.bat` | Launches `run_bot.ps1` on Windows |
| `run_bot.ps1` | Windows launcher — activates venv, sets PATH, runs runtime.py |
| `run_bot.sh` | Linux/Mac launcher — adds npm global bin to PATH, activates venv, runs runtime.py |
| `tests/windows_launch_smoke.ps1` | Windows dry-run smoke test for launcher, Gateway/TUI wrappers, and secret scan |
| `config/telegram.json` | Telegram bot token + chat ID (prompt-filled by setup) |
| `config/upstox_login.json` | Optional untracked Upstox mobile number for login form fill; never store PIN |
| `config/strategy_prompt.json` | EMA crossover strategy for OpenClaw |
| `config/zerodha.json` | Zerodha platform config |
| `config/settings.json` | Simulation mode toggle + architecture_doc_path |
| `config/openclaw_model.json` | AI provider, model ID, API key for OpenClaw |
| `core/openclaw_manager.py` | OpenClaw config, prompt prep, gateway start/stop, agent invocation |
| `core/strategy_engine.py` | Configurable EMA crossover strategy monitoring loop |
| `core/telegram_manager.py` | Telegram notification dispatcher + group inbox polling |
| `core/runtime.py` | Pipeline orchestrator |

## Pipeline Flow
```
run.sh → runtime.py → 1. Load settings
                     2. Prepare strategy prompt → prompts/
                     3. Configure OpenClaw (API key + env)
                     4. Start OpenClaw gateway (for browser/tool services)
                     5. Run OpenClaw agent (inherits terminal TTY)
                     6. OpenClaw opens the `openclaw` browser profile and navigates to the selected platform
                     7. OpenClaw checks login state and sends Telegram reminders
                     8. Once logged in → start strategy monitoring loop (simulated trades)
                     9. Send Telegram alerts for all events
                     10. Stop gateway + cleanup on exit
```

## How OpenClaw AI Agent Works
- Uses `openclaw agent --local --agent main --model <configured-model> -m "..."`
- Requires the OpenClaw gateway (`openclaw gateway run`) for browser/tool services
- On Windows, gateway and TUI are opened in separate PowerShell console windows from the main controller; on Linux, they are opened in separate terminal windows when `gnome-terminal`, `konsole`, `xfce4-terminal`, or `xterm` is available
- AI auth/model are stored in `config/openclaw_model.json`; launchers reuse saved config and only reauth/change when requested
- Supports API-key providers and OpenClaw-managed OAuth such as OpenAI Codex OAuth
- OpenClaw handles browser automation (Chrome launch, navigation, login detection)
- Strategy engine runs independently for ongoing monitoring (Python loop)
- Runtime polls the configured Telegram group every second, ignores bot-authored messages, mirrors user messages into `prompts/telegram_inbox.txt`, `prompts/telegram_priority_inbox.txt`, and the matching `~/.openclaw/workspace/prompts/` files for OpenClaw to read
- Telegram user commands are priority: `STOP` stops bot actions, `WAIT`/`PAUSE` blocks new dummy entries, `RESUME` allows fresh chart-signal-gated entries again, `QUIET`/`MUTE ERRORS` confirms technical error-noise muting while market updates continue, and `STATUS` replies immediately; avoid repeated heartbeat-style Telegram spam
- Current Upstox chart workflow: choose target index by weekday (`NIFTY 50`/`NIFTY` on Monday, Tuesday, Friday; `SENSEX` on Wednesday, Thursday), diagnose the target index 15-minute 5 EMA vs 20 EMA closed-candle crossover first, then select the nearest ATM strike from the live option chain and diagnose both selected ATM CE/PE premium charts on 3-minute closed candles; only the 15-minute direction-approved side is eligible for dummy entry
- Python strategy monitoring must not create random dummy entries/exits; it checks every 5 seconds, waits for a browser-derived `prompts/chart_signal.json` written by OpenClaw before recording any dummy signal, accepts closed-candle entry signals up to 180 seconds old, and enforces dummy target/dynamic SL/hard SL exits only from fresh observed premium prices 15 seconds old or newer
- Fast browser mode: after bias is known, keep the right pane fixed on the target index 15-minute chart and the left pane fixed on the eligible ATM premium 3-minute chart; refresh the eligible side every 5-10 seconds for current price/SL/target checks, refresh the opposite side every 30-60 seconds for status only, and avoid reopening option chain or doing full DOM/page inspection unless chart state is missing, stale, or changed

## Browser Automation
- Chrome is opened by OpenClaw itself, not by Playwright or the Python runtime
- Use the OpenClaw-managed `openclaw` browser profile; do not use the external `user` existing-session profile on Linux because attach can time out
- Upstox login starts by checking `https://pro.upstox.com/trading-charts`; if login is required, fill only the mobile number from untracked `config/upstox_login.json` and wait for the user to enter OTP and PIN manually
- Kite login detection: checks page content for "dashboard"/"holdings"/"positions" (logged in) vs "userid"/"password" (login form)
- Login retry: OpenClaw sends Telegram reminders until login is confirmed
- OpenClaw must not send Telegram directly or read `config/telegram.json`; it should append one status line to `prompts/openclaw_telegram_outbox.txt`, and the Python runtime sends/dedupes Telegram messages
- Transient browser page read, Chrome DevTools read, selector syntax, DOM inspection, tab cleanup, and retry diagnostics are technical noise: log/fix them silently and do not send them to Telegram. Telegram should still receive market condition, login/user-action, dummy trade, and final verification updates

## Commands
| Platform | Setup | Activate venv | Run bot |
|---|---|---|---|
| Windows | `setup.bat` | `.\venv\Scripts\Activate.ps1` | `.\run.bat` |
| Linux/Mac | `./setup.sh` | `source venv/bin/activate` | `./run.sh` |

## Settings (`config/settings.json`)
- `simulation_mode`: true = all trades simulated/dummy only; runtime must stop if this is not true
- `telegram_alerts`: toggle Telegram notifications
- `logging_enabled`: write timestamped strategy logs to `logs/`
- `architecture_doc_path`: optional path to architecture reference doc

## Security
- `config/telegram.json` and `config/openclaw_model.json` are in `.gitignore`
- `config/upstox_login.json` is in `.gitignore`; it may contain the mobile number only, never the PIN
- No live tokens in git-tracked files
- Runtime removes `~/.openclaw/workspace/config/telegram.json` so OpenClaw cannot send Telegram directly; keep Telegram credentials only in the project `config/telegram.json` and let Python send alerts
- API key is read from config and set as env var at runtime
- Never commit real credentials
- Never place, modify, cancel, exit, square off, or confirm real broker orders; broker browser access is for chart/login monitoring only
