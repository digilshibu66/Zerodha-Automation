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
| `config/telegram.json` | Telegram bot token + chat ID (prompt-filled by setup) |
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
                     6. OpenClaw opens Chrome and navigates to kite.zerodha.com
                     7. OpenClaw checks login state and sends Telegram reminders
                     8. Once logged in → start strategy monitoring loop (simulated trades)
                     9. Send Telegram alerts for all events
                     10. Stop gateway + cleanup on exit
```

## How OpenClaw AI Agent Works
- Uses `openclaw agent --local --agent main --model <configured-model> -m "..."`
- Requires the OpenClaw gateway (`openclaw gateway run`) for browser/tool services
- AI auth/model are stored in `config/openclaw_model.json`; launchers reuse saved config and only reauth/change when requested
- Supports API-key providers and OpenClaw-managed OAuth such as OpenAI Codex OAuth
- OpenClaw handles browser automation (Chrome launch, navigation, login detection)
- Strategy engine runs independently for ongoing monitoring (Python loop)
- Runtime polls the configured Telegram group every 5 seconds and mirrors messages into `prompts/telegram_inbox.txt` for OpenClaw to read

## Browser Automation
- Chrome is opened by OpenClaw itself, not by Playwright or the Python runtime
- Kite login detection: checks page content for "dashboard"/"holdings"/"positions" (logged in) vs "userid"/"password" (login form)
- Login retry: OpenClaw sends Telegram reminders until login is confirmed

## Commands
| Platform | Setup | Activate venv | Run bot |
|---|---|---|---|
| Windows | `setup.bat` | `.\venv\Scripts\Activate.ps1` | `.\run.bat` |
| Linux/Mac | `./setup.sh` | `source venv/bin/activate` | `./run.sh` |

## Settings (`config/settings.json`)
- `simulation_mode`: true = all trades simulated
- `telegram_alerts`: toggle Telegram notifications
- `logging_enabled`: write timestamped strategy logs to `logs/`
- `architecture_doc_path`: optional path to architecture reference doc

## Security
- `config/telegram.json` and `config/openclaw_model.json` are in `.gitignore`
- No live tokens in git-tracked files
- API key is read from config and set as env var at runtime
- Never commit real credentials
