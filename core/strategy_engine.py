import json
import logging
import random
import time
from datetime import datetime
from telegram_manager import send_message

logger = logging.getLogger(__name__)

SETTINGS_FILE = "config/settings.json"
STRATEGY_FILE = "config/strategy_prompt.json"
LOG_DIR = "logs"


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _log_to_file(entry):
    import os
    os.makedirs(LOG_DIR, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(LOG_DIR, f"strategy_{date}.log")
    with open(log_path, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {entry}\n")


def _get_signal(strategy):
    logic = strategy.get("direction_logic", "")
    direction = random.choice(["CE", "PE"])
    if "CE" in logic.upper() and "PE" in logic.upper():
        pass
    elif "CE" in logic.upper():
        direction = "CE"
    elif "PE" in logic.upper():
        direction = "PE"
    premium_confirmed = random.choice([True, False])
    return direction, premium_confirmed


def run_strategy_cycle(cycles=None, interval=60):
    settings = _load_json(SETTINGS_FILE)
    strategy = _load_json(STRATEGY_FILE)
    simulation = settings.get("simulation_mode", True)
    alerts = settings.get("telegram_alerts", True)

    logger.info("Strategy cycle started (simulation=%s, interval=%ds)", simulation, interval)
    send_message("Strategy monitoring cycle started")

    count = 0
    while cycles is None or count < cycles:
        count += 1
        timestamp = datetime.now().strftime("%H:%M:%S")

        direction, confirmed = _get_signal(strategy)
        timeframe = strategy.get("timeframe", "N/A")

        msg = (
            f"[{timestamp}] Cycle {count} | Timeframe: {timeframe} | "
            f"Signal: {direction} | Premium Confirmed: {confirmed}"
        )
        logger.info(msg)
        _log_to_file(msg)

        if alerts:
            send_message(f"Cycle {count}: {direction} signal | Premium: {'confirmed' if confirmed else 'waiting'}")

        if confirmed:
            trade_msg = (
                f"[{timestamp}] Dummy trade opened: {direction} "
                f"ATM option | Simulated entry @ {random.randint(50, 200)}"
            )
            logger.info(trade_msg)
            _log_to_file(trade_msg)
            if alerts:
                send_message(f"Dummy trade: {direction} ATM option opened")

        time.sleep(interval)

    send_message("Strategy monitoring cycle completed")
