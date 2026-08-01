"""LAAP Gateway — Feishu Webhook Adapter

Parses incoming Feishu bot webhook payloads and converts them to the
canonical GatewayMessage format.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from laap.gateway.base import GatewayAdapter, GatewayMessage

logger = logging.getLogger("laap.gateway.feishu")


class FeishuGatewayAdapter(GatewayAdapter):
    """Adapter for Feishu (Lark) bot message webhooks."""

    platform_name = "feishu"

    async def receive(self, payload: Dict[str, Any]) -> GatewayMessage:
        """Extract sender/chat/text from a standard Feishu bot event payload.

        Expected shape (v1 event callback):
            {
                "event": {
                    "message": {
                        "message_type": "text",
                        "content": {"text": "hello"},
                        "sender": {"sender_id": {"open_id": "ou_xxx"}},
                        "chat_id": "oc_xxx",
                        "create_time": "1234567890"
                    }
                }
            }
        """
        event = payload.get("event", {}) or {}
        message = event.get("message", {}) or {}
        content = message.get("content", {}) or {}

        text = ""
        if isinstance(content, dict):
            text = content.get("text", "")
        if isinstance(text, dict):
            text = text.get("text", "")

        sender = message.get("sender", {}) or {}
        sender_id = sender.get("sender_id", {}) or {}
        user_id = sender_id.get("open_id", "")
        chat_id = message.get("chat_id", "")

        create_time = message.get("create_time")
        try:
            ts_ms = float(create_time) if create_time is not None else None
            timestamp = ts_ms / 1000.0 if ts_ms is not None else None
        except (ValueError, TypeError):
            timestamp = None

        return GatewayMessage(
            platform=self.platform_name,
            user_id=str(user_id),
            chat_id=str(chat_id),
            text=str(text),
            raw_payload=payload,
            timestamp=timestamp or time.time(),
        )

    async def send(self, message: GatewayMessage) -> bool:
        """Outbound send is currently a no-op placeholder."""
        logger.debug("FeishuGatewayAdapter.send() is not implemented; returning True")
        return True
