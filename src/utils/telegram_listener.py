# ============================================================
# src/utils/telegram_listener.py — Telegram Message Listener
# ============================================================

import json
import urllib.request
import urllib.parse
import threading
import time
import sys
from typing import Any
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramListener(threading.Thread):
    def __init__(self, token: str, chat_id: str, execution_engine: Any) -> None:
        super().__init__(daemon=True)
        self.token = token
        self.chat_id = str(chat_id)
        self.engine = execution_engine
        self.last_update_id = 0
        self.running = True

    def run(self) -> None:
        if "pytest" in sys.modules:
            return  # Skip during unit tests

        logger.info("Telegram command listener thread starting...")
        
        # Get the initial offset so we don't read past messages
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset=-1&limit=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get("ok") and res.get("result"):
                    self.last_update_id = res["result"][0]["update_id"]
        except Exception as e:
            logger.debug(f"Telegram listener offset check failed (normal if bot has no messages yet): {e}")

        while self.running:
            try:
                # Long polling getUpdates
                url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={self.last_update_id + 1}&timeout=10"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res = json.loads(resp.read().decode('utf-8'))
                    if res.get("ok") and res.get("result"):
                        for update in res["result"]:
                            self.last_update_id = update["update_id"]
                            
                            msg = update.get("message") or update.get("edited_message")
                            if not msg:
                                continue
                            
                            text = msg.get("text", "").strip()
                            chat = msg.get("chat", {})
                            chat_id_from_msg = str(chat.get("id"))
                            
                            # Check commands in lowercase
                            text_lower = text.lower()
                            target_commands = [
                                "guncel", "güncel", "status", "durum", "portfolio", "portföy",
                                "acik", "açık", "islem", "işlem", "pozisyon", "pozisyonlar",
                                "position", "positions", "open"
                            ]
                            
                            # Support messages like: "güncel", "/guncel", "@guncel", "/status", etc.
                            is_match = False
                            for cmd in target_commands:
                                if cmd in text_lower:
                                    is_match = True
                                    break
                            
                            if is_match and chat_id_from_msg == self.chat_id:
                                logger.info(f"Telegram listener received status command: '{text}' from chat {chat_id_from_msg}")
                                # Trigger portfolio summary send
                                self.engine._send_portfolio_summary("Güncel Portföy Durumu (Sorgu Üzerine)")
            except Exception as e:
                logger.error(f"Telegram command listener error: {e}")
                time.sleep(10)
            
            # Prevent 100% CPU usage
            time.sleep(2)


def start_telegram_listener(execution_engine: Any) -> None:
    """Starts the Telegram command listener in a background thread."""
    cfg = execution_engine.settings
    token = cfg.telegram_bot_token
    chat_id = cfg.telegram_chat_id

    if not token or not chat_id:
        return

    # Only start listener for version v5 to prevent conflicts between multiple running bot versions (V2.1, V3, V4, V5)
    if getattr(cfg.strategy, "version", "") != "v5":
        return

    # Skip placeholder values
    if "your_telegram_bot" in token or "your_telegram_chat" in chat_id:
        return

    listener = TelegramListener(token, chat_id, execution_engine)
    listener.start()
