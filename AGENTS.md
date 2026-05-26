# TRADING-AUTOMATION — Agent Instructions

## Project Overview
OpenClaw-based automated intraday options monitoring and dummy trade simulation for Zerodha + Telegram.

## Key Files
| File | Purpose |
|---|---|
| `setup.ps1` / `setup.sh` | Full environment setup (venv, OpenClaw, deps, Playwright, config) |
| `setup.bat` | Launches `setup.ps1` on Windows |
| `run_bot.bat` | Launches `run_bot.ps1` on Windows |
| `run_bot.ps1` | Windows launcher — activates venv, sets PATH, runs runtime.py |
| `run_bot.sh` | Linux/Mac launcher — adds npm global bin to PATH, activates venv, runs runtime.py |
| `config/telegram.json` | Telegram bot token + chat ID (prompt-filled by setup) |
| `config/strategy_prompt.json` | EMA crossover strategy for OpenClaw |
| `config/zerodha.json` | Zerodha platform config |
| `config/settings.json` | Simulation mode toggle + architecture_doc_path |
| `config/openclaw_model.json` | AI provider, model ID, API key for OpenClaw |
| `core/browser_monitor.py` | Chrome process check via psutil |
| `core/chrome_launcher.py` | Auto-launch Chrome with CDP debug port, manage browser lifecycle |
| `core/zerodha_monitor.py` | Playwright CDP tab inspection, Kite login detection, page navigation |
| `core/openclaw_manager.py` | OpenClaw config, prompt prep, `infer model run` agent invocation |
| `core/strategy_engine.py` | Configurable EMA crossover strategy monitoring loop |
| `core/telegram_manager.py` | Telegram notification dispatcher |
| `core/runtime.py` | Pipeline orchestrator |

## Pipeline Flow
```
run_bot.sh → runtime.py → 1. Load settings
                             2. Prepare strategy prompt → prompts/
                             3. Launch Chrome with CDP (--remote-debugging-port=9222)
                             4. Navigate to kite.zerodha.com via Playwright
                             5. Check login state (dashboard vs login form)
                             6. If not logged in → wait 5 min with retries + Telegram
                             7. Once logged in → configure OpenClaw (API key + env)
                             8. Run OpenClaw AI for strategic assessment (infer model run)
                             9. Start strategy monitoring loop (simulated trades)
                             10. Send Telegram alerts for all events
                             11. Cleanup on exit (close Chrome, stop engine)
```

## How OpenClaw AI Agent Works
- Uses `openclaw infer model run --model openrouter/auto --prompt "..."` 
- Runs locally (no gateway needed), calls OpenRouter API via env var `OPENROUTER_API_KEY`
- Python runtime handles all browser automation (Chrome launch, CDP, navigation, login detection)
- OpenClaw provides AI strategic decisions for the trading strategy
- Strategy engine runs independently for ongoing monitoring (Python loop)

## Browser Automation
- Chrome is auto-launched with `--remote-debugging-port=9222` and a dedicated profile at `~/.openclaw-chrome-profile`
- Playwright connects via CDP to inspect tabs and page content
- Kite login detection: checks page content for "dashboard"/"holdings"/"positions" (logged in) vs "userid"/"password" (login form)
- Login retry: polls every 10 seconds for up to 5 minutes, sends Telegram reminders

## Commands
| Platform | Setup | Activate venv | Run bot |
|---|---|---|---|
| Windows | `setup.bat` | `.\venv\Scripts\Activate.ps1` | `.\run_bot.bat` |
| Linux/Mac | `./setup.sh` | `source venv/bin/activate` | `./run_bot.sh` |

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
