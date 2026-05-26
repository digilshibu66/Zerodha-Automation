import logging
import os
import sys
import signal
import json

from telegram_manager import send_message
from openclaw_manager import (
    prepare_prompt,
    configure_openclaw,
    start_gateway,
    run_openclaw_agent,
    stop_openclaw,
)
from strategy_engine import run_strategy_cycle

SETTINGS_FILE = "config/settings.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("runtime")


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
            with open(config_file) as f:
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
            with open(config_file, "w") as f:
                json.dump({"platform": platform}, f, indent=2)
            logger.info("Platform selection '%s' saved to %s", platform, config_file)
        except Exception as e:
            logger.warning("Could not save platform config: %s", e)

    return platform


def load_config():
    with open(SETTINGS_FILE) as f:
        return json.load(f)


def main():
    settings = load_config()
    simulation = settings.get("simulation_mode", True)

    logger.info("Trading Automation Bot")
    logger.info("Simulation mode: %s", simulation)
    send_message("Trading Automation Bot starting")

    # Get platform selection dynamically
    platform = get_platform_choice()
    logger.info("Selected Platform: %s", platform)

    doc_path = settings.get("architecture_doc_path", "")
    arch_doc = None
    if doc_path and os.path.isfile(doc_path):
        try:
            with open(doc_path) as f:
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
        login_url = "https://login.upstox.com"
        success_indicators = "dashboard/holdings/positions/portfolio/funds/orders"
    else:
        login_url = "https://kite.zerodha.com"
        success_indicators = "dashboard/holdings/positions"

    try:
        result = run_openclaw_agent(
            f"You are an automated intraday options trading agent for {platform}. "
            "All trades are simulated. "
            "Read the full strategy from prompts/strategy_prompt.txt using 'cat prompts/strategy_prompt.txt'. "
            "IMPORTANT: Always use the 'openclaw' managed browser profile (NOT the 'user' profile). "
            "Do NOT try to attach to an existing Chrome session. Use OpenClaw's own managed browser. "
            f"Open the 'openclaw' managed Chrome profile, reuse the active tab (or navigate it directly) to go to {login_url}. "
            f"To keep the browser clean, close any extra tabs (like 'New Tab' or 'about:blank') so only the {platform} login/dashboard tab is open. "
            "Check login state: if login form visible, send Telegram: 'Please log in to the opened Chrome window.' "
            f"Wait and retry until login is confirmed ({success_indicators} visible). "
            f"Once logged in, send Telegram: '{platform} login confirmed!' "
            "Once logged in, start monitoring the market using the strategy rules. "
            "Send Telegram alerts for every event (entry, exit, SL, target)."
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
            send_message("OpenClaw agent finished (check terminal for details)")
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
        stop_openclaw()
        logger.info("Bot stopped")
        send_message("Bot stopped")


if __name__ == "__main__":
    main()
