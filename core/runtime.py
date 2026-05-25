import json
import logging
import signal
import sys
from datetime import datetime

from browser_monitor import chrome_running
from telegram_manager import send_message
from zerodha_monitor import check_zerodha_open
from openclaw_manager import prepare_prompt, launch_openclaw, stop_openclaw, is_openclaw_running
from strategy_engine import run_strategy_cycle

SETTINGS_FILE = "config/settings.json"
STRATEGY_FILE = "config/strategy_prompt.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("runtime")


def load_config():
    with open(SETTINGS_FILE) as f:
        return json.load(f)


def read_architecture_doc(path):
    try:
        with open(path) as f:
            content = f.read()
        logger.info("Architecture document loaded (%d bytes)", len(content))
        return content
    except Exception as e:
        logger.warning("Could not read architecture doc '%s': %s", path, e)
        return None


def main():
    settings = load_config()
    simulation = settings.get("simulation_mode", True)
    arch_doc_path = settings.get("architecture_doc_path", None)

    logger.info("Trading Automation Bot - Phase 2")
    logger.info("Simulation mode: %s", simulation)
    send_message("Trading Automation Bot starting (Phase 2)")

    chrome_ok = chrome_running()
    if chrome_ok:
        logger.info("Chrome is running")
        send_message("Chrome detected")
    else:
        logger.warning("Chrome is NOT running. Continuing anyway (some features may not work).")
        send_message("Warning: Chrome not detected")

    zerodha_ok = check_zerodha_open()
    if zerodha_ok:
        logger.info("Zerodha login confirmed")
        send_message("Zerodha login is done. Proceeding with setup...")
    else:
        logger.warning("No Zerodha/Kite window found. Verify you are logged in.")
        send_message("Warning: Zerodha login not detected. Please login and restart.")
        return

    prompt_path = prepare_prompt(chrome_ok=chrome_ok, zerodha_ok=zerodha_ok)
    logger.info("Strategy prompt prepared at: %s", prompt_path)

    if arch_doc_path:
        doc = read_architecture_doc(arch_doc_path)
        if doc:
            logger.info("Architecture reference loaded for strategy context")

    openclaw_ok = launch_openclaw()
    if openclaw_ok:
        logger.info("OpenClaw launched successfully")
        send_message("OpenClaw engine started")
    else:
        logger.warning("Running in simulation-only mode (OpenClaw not available)")
        send_message("Running in simulation-only mode")

    send_message("Bot fully operational. Monitoring markets...")

    try:
        run_strategy_cycle(cycles=None, interval=60)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        send_message("Bot shutting down...")
    finally:
        if is_openclaw_running():
            stop_openclaw()
        logger.info("Bot stopped")
        send_message("Bot stopped")


if __name__ == "__main__":
    main()
