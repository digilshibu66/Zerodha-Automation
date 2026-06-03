import logging
import os
import sys
import json
import threading
import time

from telegram_manager import send_message, get_latest_update_offset, poll_group_messages, get_bot_username
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
TELEGRAM_PRIORITY_INBOX_FILE = "prompts/telegram_priority_inbox.txt"
OPENCLAW_WORKSPACE_TELEGRAM_INBOX_FILE = os.path.expanduser(
    "~/.openclaw/workspace/prompts/telegram_inbox.txt"
)
OPENCLAW_WORKSPACE_TELEGRAM_PRIORITY_INBOX_FILE = os.path.expanduser(
    "~/.openclaw/workspace/prompts/telegram_priority_inbox.txt"
)
OPENCLAW_TELEGRAM_OUTBOX_FILE = "prompts/openclaw_telegram_outbox.txt"
OPENCLAW_WORKSPACE_TELEGRAM_OUTBOX_FILE = os.path.expanduser(
    "~/.openclaw/workspace/prompts/openclaw_telegram_outbox.txt"
)
RUNTIME_CONTROL_FILE = "prompts/runtime_control.json"
OPENCLAW_WORKSPACE_RUNTIME_CONTROL_FILE = os.path.expanduser(
    "~/.openclaw/workspace/prompts/runtime_control.json"
)
_last_sent_messages = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("runtime")


def _append_telegram_inbox(message):
    for path in (TELEGRAM_INBOX_FILE, OPENCLAW_WORKSPACE_TELEGRAM_INBOX_FILE):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception as e:
            logger.warning("Could not append Telegram inbox %s: %s", path, e)


def _append_priority_inbox(message):
    for path in (TELEGRAM_PRIORITY_INBOX_FILE, OPENCLAW_WORKSPACE_TELEGRAM_PRIORITY_INBOX_FILE):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception as e:
            logger.warning("Could not append Telegram priority inbox %s: %s", path, e)


def _write_runtime_control(command, text=""):
    payload = {
        "command": command,
        "text": text,
        "updated_at": time.time(),
    }
    for path in (RUNTIME_CONTROL_FILE, OPENCLAW_WORKSPACE_RUNTIME_CONTROL_FILE):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.write("\n")
        except Exception as e:
            logger.warning("Could not write runtime control %s: %s", path, e)


def _runtime_control_command():
    latest_command = "running"
    latest_ts = -1
    for path in (RUNTIME_CONTROL_FILE, OPENCLAW_WORKSPACE_RUNTIME_CONTROL_FILE):
        try:
            with open(path, encoding="utf-8-sig") as f:
                payload = json.load(f)
            ts = float(payload.get("updated_at") or 0)
            if ts > latest_ts:
                latest_ts = ts
                latest_command = str(payload.get("command") or "running")
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            continue
        except Exception as e:
            logger.warning("Could not read runtime control %s: %s", path, e)
    return latest_command


def _send_deduped(message, min_interval=120):
    now = time.time()
    last_sent = _last_sent_messages.get(message, 0)
    if now - last_sent < min_interval:
        logger.info("Suppressed duplicate Telegram reply: %s", message)
        return
    _last_sent_messages[message] = now
    send_message(message)


def _telegram_command(text):
    value = text.strip().lower()
    if value.startswith("/"):
        value = value[1:]
    if value in ("stop", "halt", "shutdown"):
        return "stop"
    if value in ("wait", "pause", "hold"):
        return "pause"
    if value in ("resume", "start", "continue"):
        return "resume"
    if value in ("quiet", "mute", "mute errors", "mute error", "silent"):
        return "quiet"
    if value in ("status", "state", "what is happening", "what's happening") or "status" in value:
        return "status"
    return "message"


def start_telegram_inbox_watcher(stop_event, interval=1):
    offset = get_latest_update_offset()
    bot_username = get_bot_username()
    logger.info("Telegram group inbox watcher started; new group messages will show here and in %s", TELEGRAM_INBOX_FILE)
    _append_telegram_inbox("--- Telegram inbox watcher started; newest messages appear below ---")
    _append_priority_inbox("--- Telegram priority inbox started; user messages appear below ---")

    def _watch():
        nonlocal offset
        while not stop_event.is_set():
            try:
                offset, messages = poll_group_messages(offset=offset, timeout=interval)
                for msg in messages:
                    if msg.get("is_bot") or (bot_username and str(msg.get("from", "")).lower() == bot_username.lower()):
                        continue
                    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(msg['date']))}] {msg['from']}: {msg['text']}"
                    logger.info("Telegram group message: %s", line)
                    _append_telegram_inbox(line)
                    _append_priority_inbox(line)

                    command = _telegram_command(msg["text"])
                    if command == "stop":
                        _write_runtime_control("stop", msg["text"])
                        _send_deduped("STOP received. Pausing bot actions and shutting down safely.", min_interval=10)
                        stop_openclaw()
                        stop_event.set()
                    elif command == "pause":
                        _write_runtime_control("pause", msg["text"])
                        _send_deduped("WAIT/PAUSE received. New dummy entries are paused; monitoring stays alive.", min_interval=10)
                    elif command == "resume":
                        _write_runtime_control("resume", msg["text"])
                        _send_deduped("RESUME received. Monitoring can continue; dummy entries remain chart-signal gated.", min_interval=10)
                    elif command == "quiet":
                        _write_runtime_control("quiet", msg["text"])
                        _send_deduped("QUIET received. Technical browser/tool retry errors are muted; market status and dummy trade alerts continue.", min_interval=10)
                    elif command == "status":
                        _write_runtime_control("status", msg["text"])
                        _send_deduped("Status: bot is running if launcher is active. New entries require fresh browser chart_signal.json; OpenClaw instructions are in telegram_priority_inbox.txt.", min_interval=10)
                    else:
                        _write_runtime_control("message", msg["text"])
                        _send_deduped("Message received. I am prioritizing it now.", min_interval=30)
            except Exception as e:
                logger.warning("Telegram inbox watcher error: %s", e)
            stop_event.wait(0.1)

    thread = threading.Thread(target=_watch, name="telegram-inbox", daemon=True)
    thread.start()
    return thread


def _is_browser_read_warning(message):
    text = message.lower()
    return (
        "browser page read failed" in text
        or "chrome devtools read" in text
        or "browser snapshot failed" in text
        or "browser read failed" in text
    )


def _is_technical_outbox_noise(message):
    text = message.lower()
    user_action_terms = (
        "login",
        "otp",
        "pin screen",
        "upstox pin",
        "enter the pin",
        "symbol cannot be found",
        "cannot be found",
        "please enter",
    )
    if any(term in text for term in user_action_terms):
        return False

    technical_terms = (
        "browser page read failed",
        "chrome devtools read",
        "browser snapshot failed",
        "browser read failed",
        "retrying chrome devtools",
        "retrying browser",
        "after 3 retries",
        "dummy operator alive",
        "selector syntax",
        "javascript syntax error",
        "dom inspection",
        "visible-row lookup",
        "cleanup tab close failed",
        "target id",
        "untitled target",
        "extra tab",
    )
    return any(term in text for term in technical_terms)


def start_openclaw_outbox_watcher(stop_event, interval=1):
    paths = (OPENCLAW_TELEGRAM_OUTBOX_FILE, OPENCLAW_WORKSPACE_TELEGRAM_OUTBOX_FILE)
    offsets = {}
    recent_messages = {}

    for path in paths:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "a", encoding="utf-8").close()
            offsets[path] = os.path.getsize(path)
        except Exception as e:
            logger.warning("Could not initialize OpenClaw Telegram outbox %s: %s", path, e)
            offsets[path] = 0

    def _watch():
        while not stop_event.is_set():
            now = time.time()
            for path in paths:
                try:
                    with open(path, encoding="utf-8") as f:
                        f.seek(offsets.get(path, 0))
                        lines = f.readlines()
                        offsets[path] = f.tell()
                except FileNotFoundError:
                    continue
                except Exception as e:
                    logger.warning("OpenClaw Telegram outbox read error %s: %s", path, e)
                    continue

                for line in lines:
                    message = line.strip()
                    if not message:
                        continue

                    if _is_technical_outbox_noise(message):
                        logger.info("Muted technical OpenClaw outbox message: %s", message)
                        continue

                    last_sent = recent_messages.get(message, 0)
                    if now - last_sent < 300:
                        logger.info("Suppressed duplicate OpenClaw Telegram outbox message: %s", message)
                        continue

                    recent_messages[message] = now
                    _send_deduped(message)

            stop_event.wait(interval)

    thread = threading.Thread(target=_watch, name="openclaw-outbox", daemon=True)
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
    if simulation is not True:
        logger.error("Refusing to start: simulation_mode must be true for dummy-only operation")
        send_message("Safety stop: simulation_mode must be true. No real trading is allowed.")
        return

    send_message("Trading Automation Bot starting")
    telegram_stop = threading.Event()
    _write_runtime_control("running", "bot starting")
    telegram_thread = start_telegram_inbox_watcher(telegram_stop, interval=1)
    openclaw_outbox_thread = start_openclaw_outbox_watcher(telegram_stop)

    # Get platform selection dynamically
    platform = get_platform_choice()
    logger.info("Selected Platform: %s", platform)
    if platform == "Upstox":
        import datetime
        if datetime.datetime.now().weekday() >= 5:
            logger.info("Market closed: Upstox weekday strategy is configured only for Monday-Friday")
            send_message("Market closed: weekday Upstox strategy is configured for NIFTY on Mon/Tue/Fri and SENSEX on Wed/Thu. No dummy monitoring started.")
            telegram_stop.set()
            telegram_thread.join(timeout=2)
            openclaw_outbox_thread.join(timeout=2)
            return

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
        telegram_stop.set()
        telegram_thread.join(timeout=2)
        openclaw_outbox_thread.join(timeout=2)
        return

    logger.info("Launching OpenClaw agent — Chrome will open, navigate to %s, and wait for your login", platform)
    send_message(f"OpenClaw agent starting — Chrome will open. Please log in to {platform} when prompted.")

    start_gateway()  # starts gateway + waits 4s for it to be ready

    if platform == "Upstox":
        chart_cfg = load_strategy().get("chart", {})
        import datetime
        today_idx = datetime.datetime.now().weekday()
        if today_idx in (2, 3):
            dynamic_symbol = "SENSEX"
            dynamic_name = "SENSEX"
        elif today_idx in (0, 1, 4):
            dynamic_symbol = "NIFTY"
            dynamic_name = "NIFTY 50"
        else:
            send_message("Market closed: no weekday target index configured. No dummy monitoring started.")
            telegram_stop.set()
            telegram_thread.join(timeout=2)
            openclaw_outbox_thread.join(timeout=2)
            return

        chart_symbol = dynamic_symbol
        index_display_name = dynamic_name
        index_timeframe = str(chart_cfg.get("index_timeframe", "15 min")).strip()
        option_strike = chart_cfg.get("option_strike", "ATM")
        option_timeframe = str(chart_cfg.get("option_timeframe", "3 min")).strip()
        ce_target = f"{chart_symbol} ATM CE"
        pe_target = f"{chart_symbol} ATM PE"
        login_url = "https://login.upstox.com"
        post_login_url = chart_cfg.get("url", "https://pro.upstox.com/trading-charts")
        initial_url = post_login_url
        success_indicators = "dashboard/holdings/positions/portfolio/funds/orders"
    else:
        chart_symbol = ""
        login_url = "https://kite.zerodha.com"
        post_login_url = login_url
        initial_url = login_url
        success_indicators = "dashboard/holdings/positions"

    if platform == "Upstox":
        post_login_instruction = (
            "First check whether the current page or trading charts page already shows market/chart data. "
            f"Start by opening {post_login_url}; if chart/watchlist/market data is visible, treat Upstox as logged in. "
            f"If it redirects to login or shows a login form, go to {login_url}. "
            "Read mobile from config/upstox_login.json if present, use it only to fill the mobile/phone field, then click Continue/Get OTP/Proceed to request OTP. "
            "Do not store, type, or ask for the 6-digit PIN in chat, logs, files, or Telegram. "
            "After submitting the mobile number, wait for the user to enter OTP manually. "
            "If a PIN screen appears, request Telegram status 'Please enter the Upstox PIN in the opened Chrome window.' through prompts/openclaw_telegram_outbox.txt. Then wait while the user enters it manually. "
            f"After login is confirmed, navigate to {post_login_url}. "
            f"Ensure the right pane is the {index_display_name} {index_timeframe} chart. "
            f"Diagnose the crossover strategy on the {index_display_name} {index_timeframe} chart using only fully closed candles: bullish requires previous closed candle 5 EMA <= 20 EMA and latest closed candle 5 EMA > 20 EMA; bearish requires previous closed candle 5 EMA >= 20 EMA and latest closed candle 5 EMA < 20 EMA. "
            f"In the left side sidebar, find {index_display_name} and click the icon that shows the option chain. "
            f"In the option chain, locate the nearest ATM strike to the live {index_display_name} spot LTP, using the current/nearest weekly expiry unless the user specifies otherwise. If ATM or expiry is unclear, ask via Telegram before selecting another strike or expiry. "
            f"If {index_display_name} is bearish based on the crossover, select the ATM contract explicitly labeled PE. If bullish, select the ATM contract explicitly labeled CE. Treat left/right layout as a visual hint only, not the source of truth. "
            f"Once the call or put chart appears on the left, set it to {option_timeframe} and monitor only fully closed candles for an upward crossover where the previous closed candle has 5 EMA <= 20 EMA and the latest closed candle has 5 EMA > 20 EMA. "
            "When this specific upward premium-chart crossover happens according to the strategy, record a simulated/dummy entry only; never click broker order controls. "
            "Calculate and report the dummy entry price, ATM strike, selected expiry, 10% hard SL level, dynamic SL 2 to 3 points below entry, and 20% to 50% target level. "
            f"Then open/locate and diagnose BOTH premium charts: {ce_target} and {pe_target} on the {option_timeframe} timeframe. After bias is known, keep the eligible side visible and actively refresh only that visible chart every 5-10 seconds for current premium price, SL, and target checks; refresh the opposite non-eligible side less often, about every 30-60 seconds, only for status. "
            "Fast browser mode: do not reopen the option chain, navigate away from Trading Charts, or switch chart symbols unless ATM/expiry/bias is missing, stale, or changed. "
            f"Keep the right pane fixed on the {index_display_name} {index_timeframe} chart and the left pane fixed on the eligible ATM premium {option_timeframe} chart after bias is known. "
            "For an active dummy trade, prioritize reading only the visible current premium price and immediately write chart_signal.json with current_price, timestamp, direction, SL/target levels, and exit status. "
            "Run full EMA diagnosis only on closed-candle boundaries or when the visible chart state changes; do not perform heavy full-page/DOM inspection every fast cycle. "
            "If a browser read fails once, retry once silently. Use full recovery/navigation only after repeated failures or if the required chart is no longer visible. "
            f"Request Telegram/status updates through prompts/openclaw_telegram_outbox.txt with the {index_display_name} {index_timeframe} bias, selected ATM/expiry, and both CE/PE premium-chart states only when genuinely observed from the browser. "
            f"Only the side allowed by the {index_display_name} {index_timeframe} bias is eligible for dummy entry; still diagnose the opposite side and report it as not eligible. "
            f"If {chart_symbol}, {ce_target}, {pe_target}, the ATM strike, or expiry cannot be found, ask the user via Telegram before clicking another chart symbol, strike, or expiry. "
        )
    else:
        post_login_instruction = ""

    try:
        result = run_openclaw_agent(
            f"You are an automated intraday options trading agent for {platform}. "
            "You are also the project programmer/operator for this bot. "
            "All trades are simulated/dummy only. Never place, modify, cancel, square off, or confirm a real broker order. "
            "Never click real Buy, Sell, Order, Basket, Modify, Exit, Square-off, Submit, Confirm, or Place Order controls. "
            "Use the broker site only for login/chart/watchlist/price/indicator monitoring and send dummy Telegram/log events only. "
            "Read the full strategy from prompts/strategy_prompt.txt using 'cat prompts/strategy_prompt.txt'. "
            "Read live Telegram group replies from prompts/telegram_inbox.txt; check that file whenever you are waiting for login, chart choice, STOP/WAIT commands, or user assistance. "
            "Before every browser/chart action, check prompts/telegram_priority_inbox.txt and prompts/runtime_control.json; user Telegram instructions have priority. "
            "If runtime_control.json says stop, stop browser/chart work and exit. If it says pause, block new dummy entries until resume. "
            "Treat Telegram group messages in that inbox as user instructions, unless they ask for unsafe credential handling or strategy changes. "
            "If a runtime error, command failure, browser automation issue, missing config, or recoverable setup problem occurs, diagnose it, make the smallest safe fix, rerun the failed command or browser step, and continue only after verification. "
            "Never write real credentials, tokens, or API keys into tracked files; ask the user via Telegram if a secret is required. "
            "Do not change trading strategy rules unless the user explicitly asks. "
            "Do not call curl, Telegram sendMessage, or read Telegram config from any path, including config/telegram.json or ~/.openclaw/workspace/config/telegram.json. "
            "To request a Telegram status message, append one short line to prompts/openclaw_telegram_outbox.txt; Python will send and dedupe it. "
            "After each successful browser chart diagnosis, write prompts/chart_signal.json with timestamp, target_index, spot_ltp, atm_strike, expiry, index_bias, direction, ce_state, pe_state, entry_confirmed, entry_price or premium_price, current_price, dynamic_sl, hard_sl_price, target_price, exit_confirmed, exit_reason, exit_price, lots, and lot_size. Python will not create dummy entries from random data. "
            "Request Telegram status messages for market condition, login/user action, dummy trade, and final verification updates only. "
            "Do not request Telegram messages for transient technical browser/tool retry errors such as browser page reads, Chrome DevTools reads, selector syntax, DOM inspection, cleanup tabs, or retry diagnostics; log/fix them silently and continue. "
            "IMPORTANT: Use the OpenClaw-managed 'openclaw' browser profile, not the external 'user' profile. "
            "If the user is clicking, selecting a Chrome profile, or entering login details, wait and do not interrupt. "
            f"Open the 'openclaw' browser profile and go to {initial_url}; with CLI use: openclaw browser --browser-profile openclaw open {initial_url}. "
            f"To keep the browser clean, close any extra tabs (like 'New Tab' or 'about:blank') so only the {platform} login/dashboard tab is open. "
            "Check login state: if login form visible, request Telegram status 'Please log in to the opened Chrome window.' through prompts/openclaw_telegram_outbox.txt. "
            f"Wait and recheck every 5 seconds until login is confirmed ({success_indicators} visible). "
            f"Once logged in, request Telegram status '{platform} login confirmed!' through prompts/openclaw_telegram_outbox.txt. "
            f"{post_login_instruction}"
            "Once logged in, start monitoring the market using the strategy rules. "
            "Request Telegram alerts for every event (entry, exit, SL, target) through prompts/openclaw_telegram_outbox.txt.",
            platform=platform,
        )
    except KeyboardInterrupt:
        telegram_stop.set()
        telegram_thread.join(timeout=2)
        openclaw_outbox_thread.join(timeout=2)
        logger.info("Interrupted during OpenClaw agent phase — shutting down")
        send_message("Bot stopped by user.")
        stop_openclaw()
        return

    if _runtime_control_command() == "stop":
        logger.info("Telegram STOP completed during OpenClaw phase")
        send_message("Bot stopped by Telegram STOP command.")
        stop_openclaw()
        telegram_stop.set()
        telegram_thread.join(timeout=2)
        openclaw_outbox_thread.join(timeout=2)
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
            telegram_stop.set()
            telegram_thread.join(timeout=2)
            openclaw_outbox_thread.join(timeout=2)
            return
        else:
            logger.warning("OpenClaw agent finished with code %d", code)
            send_message("OpenClaw agent failed — starting one automatic recovery attempt")
            recovery = run_openclaw_agent(
                f"The previous {platform} automation run failed with exit code {code}. "
                "Act as the project programmer/operator. Inspect logs, config, prompts, and browser/gateway state. "
                "Make the smallest safe fix, never write real credentials into tracked files, rerun the failed browser/login/setup step, verify it, and request status through prompts/openclaw_telegram_outbox.txt only for market/login/user-action/final verification updates. Do not call Telegram directly. "
                "Also read prompts/telegram_inbox.txt for any user instructions sent in the Telegram group.",
                platform=platform,
            )
            if not recovery or recovery[2] != 0:
                send_message("OpenClaw recovery failed before login/browser setup — market monitoring not started")
                stop_openclaw()
                telegram_stop.set()
                telegram_thread.join(timeout=2)
                openclaw_outbox_thread.join(timeout=2)
                return
            send_message("OpenClaw recovery completed — starting strategy monitor loop")
    else:
        logger.warning("OpenClaw agent failed to launch")
        send_message("OpenClaw agent failed to launch — check that openclaw is installed")
        stop_openclaw()
        telegram_stop.set()
        telegram_thread.join(timeout=2)
        openclaw_outbox_thread.join(timeout=2)
        return

    logger.info("Starting strategy engine for ongoing monitoring...")
    send_message("Starting market monitoring loop...")

    try:
        run_strategy_cycle(cycles=None, interval=5)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        send_message("Bot shutting down...")
    finally:
        telegram_stop.set()
        telegram_thread.join(timeout=2)
        openclaw_outbox_thread.join(timeout=2)
        stop_openclaw()
        logger.info("Bot stopped")
        send_message("Bot stopped")


if __name__ == "__main__":
    main()
