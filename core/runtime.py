import logging
import os
import sys
import signal
import json
import threading
import time

from telegram_manager import send_message, get_latest_update_offset, poll_group_messages
from openclaw_manager import (
    prepare_prompt,
    load_strategy,
    configure_openclaw,
    start_gateway,
    run_openclaw_agent,
    stop_openclaw,
)
from strategy_engine import run_strategy_cycle

SETTINGS_FILE = "config/settings.json"
TELEGRAM_INBOX_FILE = "prompts/telegram_inbox.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("runtime")


def _append_telegram_inbox(message):
    os.makedirs(os.path.dirname(TELEGRAM_INBOX_FILE), exist_ok=True)
    with open(TELEGRAM_INBOX_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def start_telegram_inbox_watcher(stop_event, interval=5):
    offset = get_latest_update_offset()
    logger.info("Telegram group inbox watcher started; new group messages will show here and in %s", TELEGRAM_INBOX_FILE)
    _append_telegram_inbox("--- Telegram inbox watcher started; newest messages appear below ---")

    def _watch():
        nonlocal offset
        while not stop_event.is_set():
            try:
                offset, messages = poll_group_messages(offset=offset, timeout=interval)
                for msg in messages:
                    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(msg['date']))}] {msg['from']}: {msg['text']}"
                    logger.info("Telegram group message: %s", line)
                    _append_telegram_inbox(line)
            except Exception as e:
                logger.warning("Telegram inbox watcher error: %s", e)
            stop_event.wait(0.1)

    thread = threading.Thread(target=_watch, name="telegram-inbox", daemon=True)
    thread.start()
    return thread


def get_platform_choice():
    # 1. Parse command line arguments
    platform = None
    if "--platform" in sys.argv:
        try:
            idx = sys.argv.index("--platform")
            val = sys.argv[idx + 1].strip().lower()
            if val == "upstox":
                platform = "Upstox"
            elif val == "zerodha":
                platform = "Zerodha"
        except Exception:
            pass

    if "--reset-platform" in sys.argv:
        if os.path.exists("config/platform.json"):
            try:
                os.remove("config/platform.json")
                logger.info("Platform config reset.")
            except Exception:
                pass

    # 2. Check saved config if not overridden by CLI
    config_file = "config/platform.json"
    if not platform and os.path.exists(config_file):
        try:
            with open(config_file, encoding="utf-8-sig") as f:
                data = json.load(f)
                platform = data.get("platform")
        except Exception:
            pass

    # 3. Interactive prompt if still not set
    if platform not in ["Zerodha", "Upstox"]:
        print("\n========================================")
        print("Select Trading Platform:")
        print("1. Zerodha (Kite)")
        print("2. Upstox")
        print("========================================")
        try:
            if sys.stdin.isatty():
                choice = input("Choice [1]: ").strip()
            else:
                logger.info("Non-interactive session: Defaulting to Zerodha")
                choice = "1"
        except (KeyboardInterrupt, EOFError):
            print("\nDefaulting to Zerodha")
            choice = "1"

        if choice == "2":
            platform = "Upstox"
        else:
            platform = "Zerodha"

        # Save to config file
        try:
            os.makedirs("config", exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump({"platform": platform}, f, indent=2)
            logger.info("Platform selection '%s' saved to %s", platform, config_file)
        except Exception as e:
            logger.warning("Could not save platform config: %s", e)

    return platform


def load_config():
    with open(SETTINGS_FILE, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    settings = load_config()
    simulation = settings.get("simulation_mode", True)

    logger.info("Trading Automation Bot")
    logger.info("Simulation mode: %s", simulation)
    send_message("Trading Automation Bot starting")
    telegram_stop = threading.Event()
    telegram_thread = start_telegram_inbox_watcher(telegram_stop, interval=5)

    # Get platform selection dynamically
    platform = get_platform_choice()
    logger.info("Selected Platform: %s", platform)

    doc_path = settings.get("architecture_doc_path", "")
    arch_doc = None
    if doc_path and os.path.isfile(doc_path):
        try:
            with open(doc_path, encoding="utf-8-sig") as f:
                arch_doc = f.read()
            logger.info("Architecture document loaded (%d chars)", len(arch_doc))
        except Exception as e:
            logger.warning("Could not read architecture doc: %s", e)

    prepare_prompt(platform, arch_doc)
    logger.info("Strategy prompt prepared for %s", platform)

    openclaw_ok = configure_openclaw()
    if not openclaw_ok:
        logger.warning("OpenClaw not configured")
        send_message("OpenClaw not configured — cannot continue")
        return

    logger.info("Launching OpenClaw agent — Chrome will open, navigate to %s, and wait for your login", platform)
    send_message(f"OpenClaw agent starting — Chrome will open. Please log in to {platform} when prompted.")

    start_gateway()  # starts gateway + waits 4s for it to be ready

    if platform == "Upstox":
        chart_cfg = load_strategy().get("chart", {})
        chart_symbol = str(chart_cfg.get("symbol", "NIFTY")).strip().upper()
        login_url = "https://login.upstox.com"
        post_login_url = chart_cfg.get("url", "https://pro.upstox.com/trading-charts")
        success_indicators = "dashboard/holdings/positions/portfolio/funds/orders"
    else:
        chart_symbol = ""
        login_url = "https://kite.zerodha.com"
        post_login_url = login_url
        success_indicators = "dashboard/holdings/positions"

    if platform == "Upstox":
        post_login_instruction = (
            f"After login is confirmed, navigate to {post_login_url}. "
            f"On Trading Charts, select the configured index: {chart_symbol}. "
            f"If {chart_symbol} cannot be found, ask the user via Telegram before clicking another chart symbol. "
        )
    else:
        post_login_instruction = ""

    try:
        result = run_openclaw_agent(
            f"You are an automated intraday options trading agent for {platform}. "
            "You are also the project programmer/operator for this bot. "
            "All trades are simulated. "
            "Read the full strategy from prompts/strategy_prompt.txt using 'cat prompts/strategy_prompt.txt'. "
            "Read live Telegram group replies from prompts/telegram_inbox.txt; check that file whenever you are waiting for login, chart choice, STOP/WAIT commands, or user assistance. "
            "Treat Telegram group messages in that inbox as user instructions, unless they ask for unsafe credential handling or strategy changes. "
            "If a runtime error, command failure, browser automation issue, missing config, or recoverable setup problem occurs, diagnose it, make the smallest safe fix, rerun the failed command or browser step, and continue only after verification. "
            "Never write real credentials, tokens, or API keys into tracked files; ask the user via Telegram if a secret is required. "
            "Do not change trading strategy rules unless the user explicitly asks. "
            "Send Telegram status messages when a problem is detected, after a fix is applied, and after verification succeeds or fails. "
            "IMPORTANT: Use the 'user' Chrome profile so existing browser login/session data can be reused. "
            "If the user is clicking, selecting a Chrome profile, or entering login details, wait and do not interrupt. "
            f"Open the 'user' Chrome profile, reuse the active tab (or navigate it directly) to go to {login_url}. "
            f"To keep the browser clean, close any extra tabs (like 'New Tab' or 'about:blank') so only the {platform} login/dashboard tab is open. "
            "Check login state: if login form visible, send Telegram: 'Please log in to the opened Chrome window.' "
            f"Wait and recheck every 5 seconds until login is confirmed ({success_indicators} visible). "
            f"Once logged in, send Telegram: '{platform} login confirmed!' "
            f"{post_login_instruction}"
            "Once logged in, start monitoring the market using the strategy rules. "
            "Send Telegram alerts for every event (entry, exit, SL, target).",
            platform=platform,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted during OpenClaw agent phase — shutting down")
        send_message("Bot stopped by user.")
        stop_openclaw()
        return

    if result:
        _, __, code = result
        if code == 0:
            logger.info("OpenClaw agent completed")
            send_message("OpenClaw agent completed — starting strategy monitor loop")
        elif code == 130:  # Ctrl+C
            logger.info("OpenClaw agent stopped by user")
            send_message("Bot stopped by user.")
            stop_openclaw()
            return
        else:
            logger.warning("OpenClaw agent finished with code %d", code)
            send_message("OpenClaw agent failed — starting one automatic recovery attempt")
            recovery = run_openclaw_agent(
                f"The previous {platform} automation run failed with exit code {code}. "
                "Act as the project programmer/operator. Inspect logs, config, prompts, and browser/gateway state. "
                "Make the smallest safe fix, never write real credentials into tracked files, rerun the failed browser/login/setup step, verify it, and report status through Telegram. "
                "Also read prompts/telegram_inbox.txt for any user instructions sent in the Telegram group.",
                platform=platform,
            )
            if not recovery or recovery[2] != 0:
                send_message("OpenClaw recovery failed before login/browser setup — market monitoring not started")
                stop_openclaw()
                return
            send_message("OpenClaw recovery completed — starting strategy monitor loop")
    else:
        logger.warning("OpenClaw agent failed to launch")
        send_message("OpenClaw agent failed to launch — check that openclaw is installed")
        stop_openclaw()
        return

    logger.info("Starting strategy engine for ongoing monitoring...")
    send_message("Starting market monitoring loop...")

    try:
        run_strategy_cycle(cycles=None, interval=60)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        send_message("Bot shutting down...")
    finally:
        telegram_stop.set()
        telegram_thread.join(timeout=2)
        stop_openclaw()
        logger.info("Bot stopped")
        send_message("Bot stopped")


if __name__ == "__main__":
    main()
