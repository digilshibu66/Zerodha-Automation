import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_oc_bin = None
_configured_model = None
_oc_config_needs_init = True

PROMPTS_DIR = "prompts"
STRATEGY_CONFIG = "config/strategy_prompt.json"
MODEL_CONFIG = "config/openclaw_model.json"
PROMPT_FILE = os.path.join(PROMPTS_DIR, "strategy_prompt.txt")


def _find_openclaw():
    global _oc_bin
    if _oc_bin:
        return _oc_bin
    import shutil
    candidates = [
        "openclaw",
        os.path.expanduser("~/.npm-global/bin/openclaw"),
    ]
    npm_prefix = os.popen("npm config get prefix 2>/dev/null").read().strip()
    if npm_prefix:
        candidates.append(os.path.join(npm_prefix, "bin", "openclaw"))
    for c in candidates:
        resolved = shutil.which(c) or (c if os.path.isfile(c) else None)
        if resolved:
            _oc_bin = resolved
            return resolved
    return None


def load_strategy():
    with open(STRATEGY_CONFIG) as f:
        return json.load(f)


def load_model_config():
    try:
        with open(MODEL_CONFIG) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def configure_openclaw():
    global _configured_model
    model_cfg = load_model_config()
    if not model_cfg:
        logger.warning("No model config found at %s", MODEL_CONFIG)
        return False

    provider = model_cfg.get("provider", "openai")
    model = model_cfg.get("model", "gpt-4o")
    api_key = model_cfg.get("api_key", "")

    if api_key and api_key != "YOUR_API_KEY":
        env_var = f"{provider.upper()}_API_KEY"
        os.environ[env_var] = api_key
    else:
        logger.warning("No valid API key in config")
        return False

    _configured_model = model
    logger.info("OpenClaw configured with model: %s", model)
    return True


def prepare_prompt():
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    s = load_strategy()

    lines = []
    lines.append("OpenClaw Automated Options Strategy — Final Developer Version")
    lines.append("=" * 70)
    lines.append("")

    lines.append("YOUR ROLE")
    lines.append("-" * 40)
    lines.append("You are an automated intraday options trading agent for Zerodha.")
    lines.append("You run in two sessions per day. All trades are simulated.")
    lines.append("You communicate with the user via Telegram for login and status.")
    lines.append("You have access to bash. Use it to check Chrome, launch browser, etc.")
    lines.append("")

    lines.append("STEP 1 — LAUNCH CHROME & CHECK ZERODHA LOGIN")
    lines.append("-" * 40)
    lines.append("1. Check if Chrome is running (ps aux | grep chrome).")
    lines.append("2. Launch Chrome with --remote-debugging-port=9222 if not already running.")
    lines.append("3. Navigate to https://kite.zerodha.com using bash/curl or a headless browser.")
    lines.append("4. Check if already logged in by looking for 'dashboard' or 'holdings' content.")
    lines.append("5. If login page detected, send Telegram: 'Please log in to the opened Chrome window.'")
    lines.append("6. Wait and retry until login is confirmed (dashboards detected).")
    lines.append("7. Once logged in, send Telegram: 'Zerodha login confirmed!'")
    lines.append("")

    lines.append("STEP 2 — SEND TELEGRAM MESSAGES")
    lines.append("-" * 40)
    lines.append("Use curl to send Telegram messages:")
    lines.append("  curl -s -X POST https://api.telegram.org/bot<TOKEN>/sendMessage")
    lines.append('    -d "chat_id=<CHAT_ID>" -d "text=<MESSAGE>"')
    lines.append("Read the token and chat_id from config/telegram.json")
    lines.append("")

    lines.append("STRATEGY TYPE")
    lines.append("-" * 40)
    lines.append(s.get("strategy_type", "N/A"))
    lines.append("")

    lines.append("DIRECTION LOGIC (Higher Timeframe Filter)")
    lines.append("-" * 40)
    lines.append(f"Timeframe: {s['direction']['timeframe']}")
    lines.append(f"Indicators: {', '.join(s['direction']['indicators'])}")
    lines.append(f"CE Rule: {s['direction']['rules']['CE']}")
    lines.append(f"PE Rule: {s['direction']['rules']['PE']}")
    lines.append("")

    lines.append("STRIKE SELECTION")
    lines.append("-" * 40)
    lines.append(f"Type: {s['strike_selection']['type']}")
    lines.append(f"Rule: {s['strike_selection']['rule']}")
    lines.append(f"Note: {s['strike_selection']['note']}")
    lines.append("")

    lines.append("ENTRY LOGIC (3m Premium Chart)")
    lines.append("-" * 40)
    lines.append(f"Entry Timeframe: {s['entry']['timeframe']}")
    lines.append(f"Indicators: {', '.join(s['entry']['indicators'])}")
    lines.append("")
    lines.append("CE Entry Conditions (ALL must be true):")
    for c in s['entry']['conditions']['CE']:
        lines.append(f"  - {c}")
    lines.append("")
    lines.append("PE Entry Conditions (ALL must be true):")
    for c in s['entry']['conditions']['PE']:
        lines.append(f"  - {c}")
    lines.append("")

    lines.append("CAPITAL DEPLOYMENT")
    lines.append("-" * 40)
    lines.append(f"Usage: {s['capital']['usage']}")
    lines.append(f"Quantity: {s['capital']['quantity']}")
    lines.append("")

    lines.append("RISK MANAGEMENT")
    lines.append("-" * 40)
    lines.append(f"Max Loss Per Trade: {s['risk_management']['max_loss_per_trade']}")
    lines.append(f"Example: {s['risk_management']['example']}")
    lines.append("")

    lines.append("REWARD TARGET")
    lines.append("-" * 40)
    lines.append(f"Min Target: {s['reward_target']['min']}")
    lines.append(f"Max Target: {s['reward_target']['max']}")
    lines.append(f"Configurable: {s['reward_target']['configurable']}")
    lines.append("")

    lines.append("STOP LOSS")
    lines.append("-" * 40)
    lines.append(f"Type: {s['stop_loss']['type']}")
    lines.append(f"Indicator: {s['stop_loss']['indicator']}")
    lines.append(f"Condition: {s['stop_loss']['condition']}")
    lines.append("")

    lines.append("TRADING SESSIONS")
    lines.append("-" * 40)
    for session in s['sessions']:
        lines.append(f"{session['name']}: {session['start']} - {session['end']} (Max {session['max_trades']} trades)")
    lines.append(f"Daily Limit: {s['daily_limit']['max_trades']} trades max")
    lines.append(f"Rule: {s['daily_limit']['rule']}")
    lines.append("")

    lines.append("EXIT CONDITIONS (Exit immediately if ANY is true)")
    lines.append("-" * 40)
    for i, cond in enumerate(s['exit_conditions'], 1):
        lines.append(f"{i}. {cond}")
    lines.append("")

    lines.append("POSITION MANAGEMENT")
    lines.append("-" * 40)
    lines.append(f"Max Active Trades: {s['position_management']['max_active']}")
    for r in s['position_management']['rules']:
        lines.append(f"  - {r}")
    lines.append("")

    lines.append("AUTO SQUARE-OFF")
    lines.append("-" * 40)
    lines.append(f"Time: {s['auto_square_off']['time']}")
    lines.append(f"Rule: {s['auto_square_off']['rule']}")
    lines.append("")

    lines.append("FAIL-SAFE & SAFETY FEATURES")
    lines.append("-" * 40)
    for item in s['safety']:
        lines.append(f"  - {item}")
    lines.append("")

    lines.append("ALERT SYSTEM (Telegram)")
    lines.append("-" * 40)
    for alert in s['alerts']:
        lines.append(f"  - {alert}")
    lines.append("")

    lines.append("INSTRUCTIONS")
    lines.append("-" * 40)
    lines.append("1. Launch Chrome with CDP if not running.")
    lines.append("2. Navigate to kite.zerodha.com, check login state.")
    lines.append("3. If not logged in, send Telegram asking user to login.")
    lines.append("4. Wait and retry until dashboard is detected.")
    lines.append("5. Once logged in, send Telegram confirmation.")
    lines.append("6. All trades are simulated. Monitor EMA crossover strategy.")
    lines.append("7. Sessions: 09:30-11:30 (max 2), 13:00-15:00 (max 2).")
    lines.append("8. Stop by 15:15 auto square-off.")
    lines.append("9. Send Telegram alerts for every event (entry, exit, SL, target).")
    lines.append("10. Use bash commands for all browser/Telegram operations.")

    content = "\n".join(lines)
    with open(PROMPT_FILE, "w") as f:
        f.write(content)
    logger.info("Prompt saved to %s (%d lines)", PROMPT_FILE, len(lines))
    return PROMPT_FILE


def run_openclaw_agent(task_message, timeout_seconds=120):
    global _configured_model
    oc_bin = _find_openclaw()
    if not oc_bin:
        logger.warning("OpenClaw executable not found")
        return None

    model = _configured_model or "openrouter/auto"

    try:
        logger.info("Launching OpenClaw agent...")
        result = subprocess.run(
            [
                oc_bin, "agent", "--local",
                "--agent", "main",
                "--model", model,
                "--session-key", "agent:main:trading-bot",
                "-m", task_message,
                "--timeout", str(timeout_seconds),
            ],
            capture_output=True, text=True, timeout=timeout_seconds + 15,
        )

        if result.returncode == 0:
            logger.info("OpenClaw agent completed successfully")
        else:
            logger.warning("OpenClaw agent exit code %d: %s",
                           result.returncode, result.stderr[:300])

        return result.stdout, result.stderr, result.returncode

    except FileNotFoundError:
        logger.warning("OpenClaw executable not found")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("OpenClaw agent timed out")
        return None
    except Exception as e:
        logger.warning("OpenClaw agent error: %s", e)
        return None


def stop_openclaw():
    pass
