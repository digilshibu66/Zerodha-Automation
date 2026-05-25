# TRADING-AUTOMATION — Agent Instructions

## Project Overview
OpenClaw-based automated intraday options monitoring and dummy trade simulation for Zerodha + Telegram. Phase 2: full pipeline with Chrome/Zerodha checks, OpenClaw lifecycle, configurable strategy loop, and launcher scripts.

## Key Files
| File | Purpose |
|---|---|
| `setup.ps1` / `setup.sh` | Full environment setup (venv, OpenClaw, deps, config) |
| `setup.bat` | Launches `setup.ps1` on Windows |
| `run_bot.bat` | Launches `run_bot.ps1` on Windows |
| `run_bot.ps1` | Windows launcher — activates venv, runs runtime.py |
| `run_bot.sh` | Linux/Mac launcher — activates venv, runs runtime.py |
| `config/telegram.json` | Telegram bot token + chat ID (prompt-filled by setup) |
| `config/strategy_prompt.json` | EMA crossover strategy for OpenClaw |
| `config/zerodha.json` | Zerodha platform config |
| `config/settings.json` | Simulation mode toggle + architecture_doc_path |
| `core/browser_monitor.py` | Chrome process check via psutil |
| `core/zerodha_monitor.py` | Zerodha-specific window detection via pygetwindow |
| `core/openclaw_manager.py` | OpenClaw process/lifecycle + prompt preparation |
| `core/strategy_engine.py` | Configurable EMA crossover strategy monitoring loop |
| `core/telegram_manager.py` | Telegram notification dispatcher |
| `core/runtime.py` | Pipeline orchestrator (all Phase 2 steps) |

## Pipeline Flow (Phase 2)
```
run_bot.bat → runtime.py → 1. Load settings
                             2. Check Chrome running
                             3. Check Zerodha/Kite window
                             4. Prepare strategy prompt → prompts/
                             5. Launch OpenClaw (or fall back to simulation)
                             6. Read architecture doc (optional, from settings)
                             7. Run strategy monitoring loop
                             8. Send Telegram alerts
                             9. Cleanup on exit
```

## Commands
| Platform | Setup | Activate venv | Run bot |
|---|---|---|---|
| Windows | `setup.bat` | `.\venv\Scripts\Activate.ps1` | `.\run_bot.bat` |
| Linux/Mac | `./setup.sh` | `source venv/bin/activate` | `./run_bot.sh` |

## Settings (`config/settings.json`)
- `simulation_mode`: true = all trades simulated (Phase 2 default)
- `telegram_alerts`: toggle Telegram notifications
- `logging_enabled`: write timestamped strategy logs to `logs/`
- `architecture_doc_path`: optional path to architecture reference doc

## Security
- No live tokens in git-tracked files
- `config/telegram.json` is populated by setup prompt; kept in `.gitignore` if needed
- Never commit real credentials
