import json
import logging
import os
import time
from datetime import datetime, timezone, time as dtime

from telegram_manager import send_message

logger = logging.getLogger(__name__)

SETTINGS_FILE = "config/settings.json"
STRATEGY_FILE = "config/strategy_prompt.json"
LOG_DIR = "logs"
ENTRY_SIGNAL_MAX_AGE_SECONDS = 180
PRICE_SIGNAL_MAX_AGE_SECONDS = 15
STRATEGY_INTERVAL_SECONDS = 5
STATUS_INTERVAL_SECONDS = 300
CHART_SIGNAL_FILES = (
    "prompts/chart_signal.json",
    os.path.expanduser("~/.openclaw/workspace/prompts/chart_signal.json"),
)
RUNTIME_CONTROL_FILES = (
    "prompts/runtime_control.json",
    os.path.expanduser("~/.openclaw/workspace/prompts/runtime_control.json"),
)


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _load_runtime_control():
    latest = None
    latest_ts = None
    for path in RUNTIME_CONTROL_FILES:
        try:
            with open(path, encoding="utf-8-sig") as f:
                payload = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        ts = float(payload.get("updated_at") or 0)
        if latest_ts is None or ts > latest_ts:
            latest = payload
            latest_ts = ts
    return latest or {"command": "running", "updated_at": 0}


def _interruptible_sleep(seconds):
    end = time.time() + seconds
    while time.time() < end:
        control = _load_runtime_control()
        if control.get("command") == "stop":
            return "stop"
        time.sleep(min(1, max(0, end - time.time())))
    return None


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


def _parse_signal_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return None
    return None


def _load_chart_signal(max_age_seconds=ENTRY_SIGNAL_MAX_AGE_SECONDS):
    latest = None
    latest_ts = None
    for path in CHART_SIGNAL_FILES:
        try:
            with open(path, encoding="utf-8-sig") as f:
                signal = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue

        ts = _parse_signal_timestamp(signal.get("timestamp") or signal.get("updated_at"))
        if ts is None:
            continue
        if latest_ts is None or ts > latest_ts:
            latest = signal
            latest_ts = ts

    if latest is None:
        return None, "missing", None

    age = time.time() - latest_ts
    if age > max_age_seconds:
        return latest, f"stale {int(age)}s", latest_ts
    return latest, "fresh", latest_ts


def _normalize_direction(value):
    value = str(value or "").strip().upper()
    if value in ("CE", "CALL", "BULLISH"):
        return "CE"
    if value in ("PE", "PUT", "BEARISH"):
        return "PE"
    return "WAIT"


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _signal_price(signal):
    if not signal:
        return None
    for key in ("current_price", "premium_price", "exit_price", "entry_price"):
        price = _as_float(signal.get(key))
        if price is not None:
            return round(price, 2)
    return None


def _signal_matches_trade(signal, active_trade):
    if not signal or not active_trade:
        return False
    signal_direction = _normalize_direction(signal.get("direction") or signal.get("selected_side"))
    return signal_direction in (active_trade["direction"], "WAIT")


def _calculate_position(signal, entry_price, fallback_capital):
    available_capital = (
        _as_float(signal.get("available_capital"))
        or _as_float(signal.get("capital"))
        or _as_float(signal.get("deployed_capital"))
        or fallback_capital
    )
    lot_size = _as_int(signal.get("lot_size")) or 1
    requested_lots = _as_int(signal.get("lots"))
    max_lots = int(available_capital // (entry_price * lot_size)) if entry_price > 0 and lot_size > 0 else 0
    if max_lots < 1:
        return {
            "available_capital": round(available_capital, 2),
            "deployed_capital": 0.0,
            "lots": 0,
            "lot_size": lot_size,
            "quantity": 0,
            "hard_sl_price": 0.0,
            "dynamic_sl": 0.0,
            "target_price": 0.0,
        }
    lots = requested_lots if requested_lots and requested_lots > 0 else max_lots
    lots = min(lots, max_lots)
    quantity = lots * lot_size
    deployed_capital = round(entry_price * quantity, 2)
    hard_loss_amount = deployed_capital * 0.10
    hard_sl_price = _as_float(signal.get("hard_sl_price"))
    if hard_sl_price is None or hard_sl_price >= entry_price:
        hard_sl_price = max(0.0, entry_price - (hard_loss_amount / quantity))
    dynamic_sl = _as_float(signal.get("dynamic_sl"))
    if dynamic_sl is None or dynamic_sl >= entry_price:
        dynamic_sl = max(0.0, entry_price - 3.0)
    target_price = _as_float(signal.get("target_price"))
    if target_price is None or target_price <= entry_price:
        target_price = entry_price + ((deployed_capital * 0.20) / quantity)
    return {
        "available_capital": round(available_capital, 2),
        "deployed_capital": deployed_capital,
        "lots": lots,
        "lot_size": lot_size,
        "quantity": quantity,
        "hard_sl_price": round(hard_sl_price, 2),
        "dynamic_sl": round(dynamic_sl, 2),
        "target_price": round(target_price, 2),
    }


def _direction_allowed(signal, direction):
    bias = str(signal.get("index_bias") or signal.get("nifty_15m_bias") or "").strip().lower()
    if direction == "CE":
        return bias in ("bullish", "ce", "call")
    if direction == "PE":
        return bias in ("bearish", "pe", "put")
    return False


def run_strategy_cycle(cycles=None, interval=STRATEGY_INTERVAL_SECONDS):
    settings = _load_json(SETTINGS_FILE)
    strategy = _load_json(STRATEGY_FILE)
    simulation = settings.get("simulation_mode", True)
    if simulation is not True:
        msg = "Safety stop: simulation_mode must be true. Strategy engine is dummy-only and will not run live."
        logger.error(msg)
        send_message(msg)
        return

    alerts = settings.get("telegram_alerts", True)

    sessions = strategy.get("sessions", [])
    daily_limit = strategy.get("daily_limit", {}).get("max_trades", 4)
    capital = strategy.get("capital", {})
    chart = strategy.get("chart", {})
    option_strike = chart.get("option_strike", "ATM")
    import datetime
    today_idx = datetime.datetime.now().weekday()
    if today_idx in (2, 3):
        chart_symbol = "SENSEX"
        index_display_name = "SENSEX"
    elif today_idx in (0, 1, 4):
        chart_symbol = "NIFTY"
        index_display_name = "NIFTY 50"
    else:
        logger.info("Market closed: weekday strategy is configured only for Monday-Friday")
        send_message("Market closed: no dummy monitoring started.")
        return
    
    ce_target = f"{chart_symbol} ATM CE"
    pe_target = f"{chart_symbol} ATM PE"

    logger.info("Strategy engine started (simulation=%s, dummy_only=True)", simulation)
    send_message("Strategy engine started — dummy-only monitoring market sessions")

    trade_count = 0
    session_trade_counts = {s.get("name", str(i)): 0 for i, s in enumerate(sessions)}
    total_pnl = 0.0
    fallback_capital = 20000.0
    active_trade = None
    count = 0
    last_status_sent = 0
    last_entry_signal_ts = None
    last_exit_signal_ts = None
    pause_notice_sent = False

    while cycles is None or count < cycles:
        control = _load_runtime_control()
        if control.get("command") == "stop":
            logger.info("STOP received from Telegram runtime control. Strategy loop exiting.")
            send_message("Bot stopped by Telegram STOP command.")
            break
        paused = control.get("command") == "pause"
        if paused and not pause_notice_sent:
            logger.info("WAIT/PAUSE received from Telegram runtime control. New dummy entries paused.")
            send_message("Bot paused: new dummy entries are blocked until RESUME.")
            pause_notice_sent = True
        if not paused:
            pause_notice_sent = False

        count += 1
        now = datetime.now()
        timestamp = now.strftime("%H:%M:%S")

        if trade_count >= daily_limit:
            msg = f"[{timestamp}] Daily trade limit ({daily_limit}) reached. Stopping."
            logger.info(msg)
            _log_to_file(msg)
            send_message("Daily trade limit reached. Bot idle.")
            break

        signal, signal_status, signal_ts = _load_chart_signal(ENTRY_SIGNAL_MAX_AGE_SECONDS)
        price_signal, price_signal_status, price_signal_ts = _load_chart_signal(PRICE_SIGNAL_MAX_AGE_SECONDS)
        direction = _normalize_direction(signal.get("direction") if signal else None)
        entry_confirmed = bool(
            signal
            and signal_status == "fresh"
            and signal_ts != last_entry_signal_ts
            and signal.get("entry_confirmed")
        )
        entry_confirmed = entry_confirmed and _direction_allowed(signal, direction)

        active_session = None
        for s in sessions:
            if _time_in_range(s["start"], s["end"]):
                active_session = s
                break

        if not active_session:
            if count % 20 == 0:
                logger.debug("[%s] Outside trading sessions. Waiting...", timestamp)
                if alerts:
                    send_message("Bot idle: outside configured market monitoring sessions")
            if _interruptible_sleep(interval) == "stop":
                break
            continue

        session_name = active_session["name"]
        session_trades = session_trade_counts.get(session_name, 0)
        trade_msg = (
            f"[{timestamp}] Session: {active_session['name']} | "
            f"Direction: {direction} | Entry: {'confirmed' if entry_confirmed else 'waiting'} | "
            f"Chart signal: {signal_status} | "
            f"Trades so far: {session_trades}/{active_session['max_trades']} (session) | {trade_count}/{daily_limit} (daily)"
        )
        logger.info(trade_msg)
        _log_to_file(trade_msg)

        if alerts and time.time() - last_status_sent >= STATUS_INTERVAL_SECONDS:
            send_message(
                f"Monitoring active: {index_display_name} 15m direction check + {ce_target}/{pe_target} premium chart checks | "
                f"Session: {session_name} | Bias: {direction} | Entry: {'confirmed' if entry_confirmed else 'waiting'} | "
                f"Entry signal: {signal_status} | Price signal: {price_signal_status} | "
                f"Trades: {session_trades}/{active_session['max_trades']} session, {trade_count}/{daily_limit} daily"
            )
            last_status_sent = time.time()

        if active_trade:
            exit_reason = price_signal.get("exit_reason") if price_signal and price_signal_status == "fresh" and _signal_matches_trade(price_signal, active_trade) else None
            observed_price = _signal_price(price_signal) if price_signal_status == "fresh" and _signal_matches_trade(price_signal, active_trade) else None
            exit_confirmed = bool(
                price_signal
                and price_signal_status == "fresh"
                and price_signal_ts != last_exit_signal_ts
                and price_signal.get("exit_confirmed")
                and exit_reason
            )
            if not exit_confirmed and observed_price is not None:
                first_stop_name = "hard_sl_hit" if active_trade["hard_sl_price"] >= active_trade["dynamic_sl"] else "dynamic_sl_hit"
                second_stop_name = "dynamic_sl_hit" if first_stop_name == "hard_sl_hit" else "hard_sl_hit"
                first_stop_price = max(active_trade["hard_sl_price"], active_trade["dynamic_sl"])
                second_stop_price = min(active_trade["hard_sl_price"], active_trade["dynamic_sl"])
                if observed_price <= first_stop_price:
                    exit_confirmed = True
                    exit_reason = first_stop_name
                elif observed_price <= second_stop_price:
                    exit_confirmed = True
                    exit_reason = second_stop_name
                elif observed_price >= active_trade["target_price"]:
                    exit_confirmed = True
                    exit_reason = "target_hit"
            if not exit_confirmed:
                if _interruptible_sleep(interval) == "stop":
                    break
                continue

            exit_price = observed_price or _as_float(price_signal.get("exit_price") or price_signal.get("premium_price"))
            if exit_price is not None:
                exit_price = round(exit_price, 2)
            else:
                exit_price = active_trade["entry_price"]
            pnl = round((exit_price - active_trade["entry_price"]) * active_trade["quantity"], 2)

            trade_duration = (datetime.now() - active_trade["entry_time"]).total_seconds() / 60
            total_pnl += pnl
            trade_count += 1
            session_trade_counts[session_name] = session_trades + 1
            exit_log = (
                f"[{timestamp}] TRADE EXIT | {active_trade['direction']} | {active_trade['strike']} | {active_trade['lots']} lot(s) | "
                f"Entry: {active_trade['entry_price']} | Exit: {exit_price} | P&L: {pnl} | "
                f"Reason: {exit_reason} | Duration: {trade_duration:.1f}min"
            )
            logger.info(exit_log)
            _log_to_file(exit_log)
            if alerts:
                send_message(f"Trade exit: {active_trade['direction']} | P&L: {pnl} | Reason: {exit_reason}")
            last_exit_signal_ts = price_signal_ts
            active_trade = None
            if _interruptible_sleep(interval) == "stop":
                break
            continue

        if paused or not entry_confirmed:
            if _interruptible_sleep(interval) == "stop":
                break
            continue

        if active_session and session_trades >= active_session["max_trades"]:
            msg = f"[{timestamp}] Session {active_session['name']} trade limit reached ({active_session['max_trades']})."
            logger.info(msg)
            _log_to_file(msg)
            if alerts:
                send_message(f"Session limit reached: {active_session['name']}")
            if _interruptible_sleep(interval) == "stop":
                break
            continue

        try:
            entry_price = round(float(signal.get("entry_price") or signal.get("premium_price")), 2)
        except (TypeError, ValueError):
            logger.warning("Fresh chart signal confirmed entry but has no valid entry_price/premium_price; waiting")
            if _interruptible_sleep(interval) == "stop":
                break
            continue
        position = _calculate_position(signal, entry_price, fallback_capital)
        if position["lots"] < 1:
            logger.warning("Fresh chart signal confirmed entry but available capital cannot cover one lot; waiting")
            if alerts:
                send_message("Entry skipped: available dummy capital cannot cover one lot at observed premium")
            if _interruptible_sleep(interval) == "stop":
                break
            continue
        lots = position["lots"]
        strike = signal.get("atm_strike") or signal.get("option_strike") or option_strike
        active_trade = {
            "direction": direction,
            "entry_time": now,
            "entry_price": entry_price,
            "capital": position["deployed_capital"],
            "lots": lots,
            "lot_size": position["lot_size"],
            "quantity": position["quantity"],
            "strike": strike,
            "dynamic_sl": position["dynamic_sl"],
            "hard_sl_price": position["hard_sl_price"],
            "target_price": position["target_price"],
        }

        entry_log = (
            f"[{timestamp}] TRADE ENTRY | {direction} | {strike} | {lots} lot(s) x {position['lot_size']} | "
            f"Entry: {entry_price} | Capital: {position['deployed_capital']} | "
            f"Dynamic SL: {position['dynamic_sl']} | Hard SL: {position['hard_sl_price']} | Target: {position['target_price']}"
        )
        logger.info(entry_log)
        _log_to_file(entry_log)
        if alerts:
            send_message(
                f"Trade entry: {direction} {strike} | {lots} lot(s) @ {entry_price} | "
                f"SL {position['dynamic_sl']}/{position['hard_sl_price']} | Target {position['target_price']}"
            )
        last_entry_signal_ts = signal_ts

        if _interruptible_sleep(interval) == "stop":
            break

    summary = (
        f"Strategy cycle completed | Trades: {trade_count} | "
        f"Total P&L: {total_pnl} | Capital: {fallback_capital}"
    )
    logger.info(summary)
    _log_to_file(summary)
    send_message(f"Bot idle | Trades: {trade_count} | P&L: {total_pnl}")
