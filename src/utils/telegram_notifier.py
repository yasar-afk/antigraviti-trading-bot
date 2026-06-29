# ============================================================
# src/utils/telegram_notifier.py — Telegram Notification Utility
# ============================================================

import urllib.request
import urllib.parse
from typing import Optional
from src.config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def send_telegram_notification(message: str) -> None:
    """Sends a notification message to the configured Telegram chat."""
    import sys
    # Skip if running under pytest unit tests
    if "pytest" in sys.modules:
        return

    try:
        cfg = get_settings()
        token = cfg.telegram_bot_token
        chat_id = cfg.telegram_chat_id

        if not token or not chat_id:
            logger.debug("Telegram notification skipped: Token or Chat ID not configured.")
            return

        # Skip default placeholders
        if "your_telegram_bot" in token or "your_telegram_chat" in chat_id:
            logger.debug("Telegram notification skipped: Placeholder values in configuration.")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data, method="POST")
        # Set a 10s timeout to prevent blocking the bot execution
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                logger.error(f"Telegram notification failed with status {response.status}")
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
