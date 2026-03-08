import logging

import requests

from .config import MAX_MESSAGE_LENGTH, TELEGRAM_API_BASE

logger = logging.getLogger(__name__)


def send_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    if not bot_token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        return False
    chat_id = str(chat_id).strip()
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[: MAX_MESSAGE_LENGTH - 3] + "..."
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        if not r.ok:
            body = r.text
            try:
                data = r.json()
                body = data.get("description", body)
            except Exception:
                pass
            logger.error("Telegram error %s: %s", r.status_code, body)
            if r.status_code == 400 and "chat not found" in body.lower():
                logger.info("Fix: 1) Open your bot in Telegram 2) Send /start or any message 3) Get your Id from @userinfobot 4) Put that number in .env as TELEGRAM_CHAT_ID")
            return False
        return True
    except requests.RequestException as e:
        logger.error("Telegram send failed: %s", e)
        return False
