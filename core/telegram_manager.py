import requests
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_CONFIG_PATH = "config/telegram.json"
BOT_TOKEN = None
CHAT_ID = None

def _load_config():
    global BOT_TOKEN, CHAT_ID
    if BOT_TOKEN and CHAT_ID:
        return True
    try:
        with open(_CONFIG_PATH, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        BOT_TOKEN = str(cfg["bot_token"])
        CHAT_ID = str(cfg["chat_id"])
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


def _get_updates(offset=None, timeout=10):
    if not _load_config():
        return []
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": timeout, "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=timeout + 5)
        if r.status_code != 200:
            logger.warning("Telegram getUpdates failed (HTTP %d): %s", r.status_code, r.text[:200])
            return []
        data = r.json()
        if not data.get("ok"):
            logger.warning("Telegram getUpdates returned not ok: %s", data)
            return []
        return data.get("result", [])
    except requests.RequestException as e:
        logger.warning("Telegram getUpdates error: %s", e)
        return []
    except ValueError as e:
        logger.warning("Telegram getUpdates invalid JSON: %s", e)
        return []


def get_latest_update_offset():
    updates = _get_updates(timeout=0)
    if not updates:
        return None
    return max(update.get("update_id", 0) for update in updates) + 1


def poll_group_messages(offset=None, timeout=5):
    updates = _get_updates(offset=offset, timeout=timeout)
    messages = []
    next_offset = offset
    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            next_offset = max(next_offset or 0, update_id + 1)

        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        if str(chat.get("id")) != str(CHAT_ID):
            continue

        text = (msg.get("text") or msg.get("caption") or "").strip()
        if not text:
            continue

        sender = msg.get("from") or {}
        name = sender.get("username") or sender.get("first_name") or "unknown"
        messages.append({
            "text": text,
            "from": name,
            "date": msg.get("date", int(time.time())),
        })
    return next_offset, messages
