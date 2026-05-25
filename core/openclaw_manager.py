import json
import logging
import os
import subprocess
import signal
import psutil

logger = logging.getLogger(__name__)

PROMPTS_DIR = "prompts"
STRATEGY_CONFIG = "config/strategy_prompt.json"
PROMPT_FILE = os.path.join(PROMPTS_DIR, "strategy_prompt.txt")

_openclaw_process = None


def load_strategy():
    with open(STRATEGY_CONFIG) as f:
        return json.load(f)


def prepare_prompt(chrome_ok=False, zerodha_ok=False):
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    strategy = load_strategy()
    lines = [
        "Strategy Prompt for OpenClaw",
        "=" * 40,
        f"Timeframe: {strategy.get('timeframe', 'N/A')}",
        f"Direction Logic: {strategy.get('direction_logic', 'N/A')}",
        f"Confirmation: {strategy.get('confirmation', 'N/A')}",
        f"Instrument: {strategy.get('instrument', 'N/A')}",
        "",
        "Environment Status",
        "-" * 20,
        f"Chrome running: {'Yes' if chrome_ok else 'No'}",
        f"Zerodha/Kite window: {'Detected' if zerodha_ok else 'Not found'}",
        "",
        "Instructions: Monitor the market using the above strategy.",
        "Generate CE (Call Entry) or PE (Put Entry) signals based on EMA crossover.",
        "Wait for 3-minute premium chart confirmation before signaling.",
        "Select ATM options dynamically. All trades are simulated.",
    ]
    content = "\n".join(lines)
    with open(PROMPT_FILE, "w") as f:
        f.write(content)
    logger.info("Prompt saved to %s", PROMPT_FILE)
    return PROMPT_FILE


def launch_openclaw():
    global _openclaw_process
    try:
        cmd = ["openclaw", "--prompt", PROMPT_FILE]
        logger.info("Launching OpenClaw: %s", " ".join(cmd))
        _openclaw_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        logger.info("OpenClaw started (PID: %d)", _openclaw_process.pid)
        return True
    except FileNotFoundError:
        logger.warning("OpenClaw executable not found. Running in simulation-only mode.")
        return False
    except Exception as e:
        logger.warning("Failed to launch OpenClaw: %s. Running in simulation-only mode.", e)
        return False


def is_openclaw_running():
    if _openclaw_process and _openclaw_process.poll() is None:
        return True
    for proc in psutil.process_iter(["name"]):
        try:
            if "openclaw" in proc.info["name"].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def stop_openclaw():
    global _openclaw_process
    if _openclaw_process and _openclaw_process.poll() is None:
        logger.info("Stopping OpenClaw (PID: %d)...", _openclaw_process.pid)
        _openclaw_process.send_signal(signal.SIGTERM)
        try:
            _openclaw_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _openclaw_process.kill()
            _openclaw_process.wait()
        logger.info("OpenClaw stopped")
    _openclaw_process = None
