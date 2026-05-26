import requests
import json
import logging
import os

logger = logging.getLogger(__name__)

_CONFIG_PATH = "config/telegram.json"
BOT_TOKEN = None
CHAT_ID = None

def _load_config():
    global BOT_TOKEN, CHAT_ID
    if BOT_TOKEN and CHAT_ID:
        return True
    try:
        with open(_CONFIG_PATH) as f:
            cfg = json.load(f)
        BOT_TOKEN = cfg["bot_token"]
        CHAT_ID = cfg["chat_id"]
        return True
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logger.warning("Telegram config not available: %s", e)
        return False


def send_message(message):
    if not _load_config():
        logger.warning("Cannot send Telegram message — no config")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code != 200:
            logger.warning("Telegram send failed (HTTP %d): %s", r.status_code, r.text[:200])
    except requests.RequestException as e:
        logger.warning("Telegram send error: %s", e)