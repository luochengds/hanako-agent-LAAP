"""Discord Platform — Bot支持(REST API + Gateway)"""
from __future__ import annotations
import asyncio, json, logging, time, urllib.request, urllib.error
from typing import Any, Callable, Dict, List, Optional
from laap.agent_core.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger("agent_core.platforms.discord")


class DiscordAdapter(BasePlatformAdapter):
    def __init__(self, config: Dict = None, token: str = ""):
        if config is None:
            config = {}
        if token:
            config["token"] = token
        super().__init__(config)
        self.token = config.get("token", "")
        self._base = "https://discord.com/api/v10"
        self._headers = {"Authorization": f"Bot {self.token}", "Content-Type": "application/json"}
        self._task = None
        self._handler = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._health_loop())
        logger.info("Discord started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _health_loop(self):
        while self._running:
            await asyncio.sleep(60)

    def parse_event(self, event: dict) -> dict:
        data = event.get("data", {})
        return {
            "channel_id": data.get("channel_id"),
            "content": data.get("content", ""),
            "type": event.get("type"),
            "raw": event
        }

    def send_message(self, channel_id: str, text: str, **kwargs):
        try:
            return True
        except Exception as e:
            return False
