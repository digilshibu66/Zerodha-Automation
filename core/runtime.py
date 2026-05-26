import logging
import signal
import json

from telegram_manager import send_message
from openclaw_manager import (
    prepare_prompt,
    configure_openclaw,
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


def load_config():
    with open(SETTINGS_FILE) as f:
        return json.load(f)


def main():
    settings = load_config()
    simulation = settings.get("simulation_mode", True)

    logger.info("Trading Automation Bot")
    logger.info("Simulation mode: %s", simulation)
    send_message("Trading Automation Bot starting")

    prepare_prompt()
    logger.info("Strategy prompt prepared")

    openclaw_ok = configure_openclaw()
    if not openclaw_ok:
        logger.warning("OpenClaw not configured")
        send_message("OpenClaw not configured — cannot continue")
        return

    logger.info("Launching OpenClaw agent — it will handle Chrome, login, and Telegram")
    send_message("OpenClaw agent starting — it will handle Chrome, login check, and monitoring")

    result = run_openclaw_agent(
        "You are an automated intraday options trading agent for Zerodha. "
        "All trades are simulated. "
        "Read the full strategy from prompts/strategy_prompt.txt using 'cat prompts/strategy_prompt.txt'. "
        "Execute the strategy step by step using bash commands. "
        "Launch Chrome with CDP, navigate to Kite, check login, send Telegram messages. "
        "Once logged in, start monitoring the market using the strategy rules. "
        "Send Telegram alerts for every event.",
        timeout_seconds=180,
    )

    if result:
        stdout, stderr, code = result
        if code == 0:
            logger.info("OpenClaw agent completed")
            send_message("OpenClaw agent completed successfully")
        else:
            logger.warning("OpenClaw agent finished with code %d", code)
            send_message("OpenClaw agent finished (check logs)")
    else:
        logger.warning("OpenClaw agent failed to launch")
        send_message("OpenClaw agent failed to launch")

    logger.info("Starting strategy engine for ongoing monitoring...")
    send_message("Starting market monitoring...")

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
