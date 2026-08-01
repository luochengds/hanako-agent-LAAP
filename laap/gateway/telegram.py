"""LAAP Gateway — Telegram Webhook Adapter

Parses incoming Telegram bot webhook updates and converts them to the
canonical GatewayMessage format. Supports outbound replies via the Telegram
Bot API when a bot token is configured.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from laap.gateway.base import GatewayAdapter, GatewayMessage

logger = logging.getLogger("laap.gateway.telegram")


class TelegramGatewayAdapter(GatewayAdapter):
    """Adapter for Telegram bot message webhooks.

    Expects the standard Telegram Bot API update object:
    https://core.telegram.org/bots/api#update

    Outbound sending requires a bot token. If no token is provided, ``send``
    returns ``True`` as a no-op placeholder.
    """

    platform_name = "telegram"

    def __init__(self, bot_token: Optional[str] = None) -> None:
        self.bot_token = bot_token

    async def receive(self, payload: Dict[str, Any]) -> GatewayMessage:
        """Extract sender/chat/text from a Telegram update payload."""
        message = payload.get("message") or payload.get("edited_message") or {}
        if not isinstance(message, dict):
            message = {}

        text = message.get("text", "")
        if not isinstance(text, str):
            text = ""

        sender = message.get("from", {}) or {}
        user_id = sender.get("id", "")

        chat = message.get("chat", {}) or {}
        chat_id = chat.get("id", "")

        date = message.get("date")
        try:
            timestamp = float(date) if date is not None else None
        except (ValueError, TypeError):
            timestamp = None

        return GatewayMessage(
            platform=self.platform_name,
            user_id=str(user_id),
            chat_id=str(chat_id),
            text=text,
            raw_payload=payload,
            timestamp=timestamp or time.time(),
        )

    async def send(self, message: GatewayMessage) -> bool:
        """Send a reply back to Telegram via the Bot API.

        Returns True if no token is configured (no-op) or if the API call
        succeeds. Logs and returns False on API errors.
        """
        if not self.bot_token:
            logger.debug("TelegramGatewayAdapter.send() skipped: no bot_token configured")
            return True

        try:
            import httpx
        except ImportError as exc:
            raise ImportError("Telegram outbound send requires httpx") from exc

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": message.chat_id,
            "text": message.text,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if data.get("ok"):
                    return True
                logger.warning("Telegram API error: %s", data.get("description"))
                return False
        except Exception as exc:
            logger.exception("Telegram send failed")
            return False
