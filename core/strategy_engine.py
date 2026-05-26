import json
import logging
import os
import random
import time
from datetime import datetime, time as dtime

from telegram_manager import send_message

logger = logging.getLogger(__name__)

SETTINGS_FILE = "config/settings.json"
STRATEGY_FILE = "config/strategy_prompt.json"
LOG_DIR = "logs"


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _log_to_file(entry):
    os.makedirs(LOG_DIR, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(LOG_DIR, f"strategy_{date}.log")
    with open(log_path, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {entry}\n")


def _time_in_range(start_str, end_str):
    now = datetime.now().time()
    start = dtime(*map(int, start_str.split(":")))
    end = dtime(*map(int, end_str.split(":")))
    return start <= now <= end


def _simulate_direction(strategy):
    logic = strategy.get("direction", {})
    rules = logic.get("rules", {})
    direction = random.choice(["CE", "PE"])
    if "CE" in rules.get("CE", "").upper() and "PE" in rules.get("PE", "").upper():
        pass
    elif "CE" in rules.get("CE", "").upper():
        direction = "CE"
    elif "PE" in rules.get("PE", "").upper():
        direction = "PE"
    return direction


def _simulate_entry_confirmed():
    return random.choice([True, False])


def _simulate_trade_outcome(deployed_capital):
    outcome = random.choice(["target", "sl", "hard_sl"])
    pnl_pct = 0
    if outcome == "target":
        pnl_pct = random.uniform(0.20, 0.50)
    elif outcome == "sl":
        pnl_pct = random.uniform(-0.10, 0)
    elif outcome == "hard_sl":
        pnl_pct = -0.10
    pnl = round(deployed_capital * pnl_pct, 2)
    exit_price = round(random.uniform(50, 200), 2)
    return outcome, pnl, exit_price


def run_strategy_cycle(cycles=None, interval=30):
    settings = _load_json(SETTINGS_FILE)
    strategy = _load_json(STRATEGY_FILE)
    simulation = settings.get("simulation_mode", True)
    alerts = settings.get("telegram_alerts", True)

    sessions = strategy.get("sessions", [])
    daily_limit = strategy.get("daily_limit", {}).get("max_trades", 4)
    capital = strategy.get("capital", {})

    logger.info("Strategy engine started (simulation=%s)", simulation)
    send_message("Strategy engine started — monitoring market sessions")

    trade_count = 0
    total_pnl = 0.0
    deployed_capital = 20000.0
    active_trade = None
    count = 0

    while cycles is None or count < cycles:
        count += 1
        now = datetime.now()
        timestamp = now.strftime("%H:%M:%S")

        if trade_count >= daily_limit:
            msg = f"[{timestamp}] Daily trade limit ({daily_limit}) reached. Stopping."
            logger.info(msg)
            _log_to_file(msg)
            send_message("Daily trade limit reached. Bot idle.")
            break

        direction = _simulate_direction(strategy)
        entry_confirmed = _simulate_entry_confirmed()

        active_session = None
        for s in sessions:
            if _time_in_range(s["start"], s["end"]):
                active_session = s
                break

        if not active_session:
            if count % 20 == 0:
                logger.debug("[%s] Outside trading sessions. Waiting...", timestamp)
            time.sleep(interval)
            continue

        session_trades = sum(
            1 for _ in range(0)
        )
        trade_msg = (
            f"[{timestamp}] Session: {active_session['name']} | "
            f"Direction: {direction} | Entry: {'confirmed' if entry_confirmed else 'waiting'} | "
            f"Trades so far: {trade_count}/{active_session['max_trades']} (session) | {trade_count}/{daily_limit} (daily)"
        )
        logger.info(trade_msg)
        _log_to_file(trade_msg)

        if not entry_confirmed:
            time.sleep(interval)
            continue

        if active_trade:
            time.sleep(interval)
            continue

        if active_session and trade_count >= active_session["max_trades"]:
            msg = f"[{timestamp}] Session {active_session['name']} trade limit reached ({active_session['max_trades']})."
            logger.info(msg)
            _log_to_file(msg)
            if alerts:
                send_message(f"Session limit reached: {active_session['name']}")
            time.sleep(interval)
            continue

        deploy = deployed_capital
        entry_price = round(random.uniform(50, 200), 2)
        lots = random.randint(1, 3)
        active_trade = {
            "direction": direction,
            "entry_time": now,
            "entry_price": entry_price,
            "capital": deploy,
            "lots": lots,
            "strike": "ATM"
        }

        entry_log = (
            f"[{timestamp}] TRADE ENTRY | {direction} | ATM | {lots} lot(s) | "
            f"Entry: {entry_price} | Capital: {deploy}"
        )
        logger.info(entry_log)
        _log_to_file(entry_log)
        if alerts:
            send_message(f"Trade entry: {direction} ATM | {lots} lot(s) @ {entry_price}")

        monitor_cycles = random.randint(3, 6)
        for mc in range(monitor_cycles):
            exit_reason, pnl, exit_price = _simulate_trade_outcome(deploy)
            if exit_reason:
                break
            time.sleep(interval)

        exit_reason, pnl, exit_price = _simulate_trade_outcome(deploy)

        trade_duration = (datetime.now() - active_trade["entry_time"]).total_seconds() / 60
        total_pnl += pnl
        trade_count += 1

        exit_log = (
            f"[{timestamp}] TRADE EXIT | {direction} | ATM | {lots} lot(s) | "
            f"Entry: {entry_price} | Exit: {exit_price} | P&L: {pnl} | "
            f"Reason: {exit_reason} | Duration: {trade_duration:.1f}min"
        )
        logger.info(exit_log)
        _log_to_file(exit_log)
        if alerts:
            send_message(
                f"Trade exit: {direction} | P&L: {pnl} | Reason: {exit_reason}"
            )

        active_trade = None

        if trade_count >= daily_limit:
            msg = f"[{timestamp}] Daily trade limit ({daily_limit}) reached."
            logger.info(msg)
            _log_to_file(msg)
            if alerts:
                send_message("Daily trade limit reached. Bot stopping.")

        time.sleep(interval)

    summary = (
        f"Strategy cycle completed | Trades: {trade_count} | "
        f"Total P&L: {total_pnl} | Capital: {deployed_capital}"
    )
    logger.info(summary)
    _log_to_file(summary)
    send_message(f"Bot idle | Trades: {trade_count} | P&L: {total_pnl}")
