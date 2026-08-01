"""LAAP Gateway — HTTP Webhook Server

Exposes ``POST /gateway/<platform>`` endpoints. Each route delegates to a
registered ``GatewayAdapter``, converts the resulting ``GatewayMessage`` to an
``AetherMessage``, and forwards it to ``ArisCognitiveBus`` when available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from laap.gateway.base import GatewayAdapter, GatewayMessage
from laap.orchestration.primitives import AetherMessage, AetherAddress, MessageType

logger = logging.getLogger("laap.gateway.server")

try:
    from aiohttp import web

    HAS_AIOHTTP = True
except ImportError:  # pragma: no cover
    HAS_AIOHTTP = False
    web = None  # type: ignore[assignment]


class GatewayServer:
    """Pluggable HTTP gateway server for external messaging platforms."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        adapters: Optional[Dict[str, GatewayAdapter]] = None,
        cognitive_bus: Optional[Any] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.adapters = adapters or {}
        self.cognitive_bus = cognitive_bus
        self._queue: List[AetherMessage] = []
        self._app: Optional[Any] = None
        self._runner: Optional[Any] = None
        self._site: Optional[Any] = None

    def register_adapter(self, platform: str, adapter: GatewayAdapter) -> None:
        """Register a gateway adapter for a platform."""
        self.adapters[platform] = adapter

    @staticmethod
    def _gateway_message_to_aether(message: GatewayMessage) -> AetherMessage:
        """Convert a canonical gateway message to an AetherMessage."""
        return AetherMessage(
            msg_type=MessageType.INVOKE,
            sender=AetherAddress(
                host=message.platform,
                actor_id=message.user_id,
                capability="chat",
            ),
            recipient=AetherAddress(
                host="aris",
                actor_id="cognitive_bus",
                capability="process",
            ),
            payload={
                "text": message.text,
                "platform": message.platform,
                "chat_id": message.chat_id,
                "user_id": message.user_id,
                "raw_payload": message.raw_payload,
            },
            timestamp=message.timestamp or time.time(),
        )

    async def _handle_platform_post(self, request: Any) -> Any:
        """Handle POST /gateway/<platform>."""
        if not HAS_AIOHTTP:
            return None  # pragma: no cover
        platform = request.match_info.get("platform", "")
        adapter = self.adapters.get(platform)
        if adapter is None:
            return web.json_response(
                {"error": f"Unknown platform: {platform}"},
                status=404,
            )

        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            return web.json_response(
                {"error": f"Invalid JSON: {exc}"},
                status=400,
            )

        try:
            gateway_message = await adapter.receive(body)
        except Exception as exc:
            logger.exception("Adapter receive failed for platform=%s", platform)
            return web.json_response(
                {"error": f"Adapter error: {exc}"},
                status=500,
            )

        aether_message = self._gateway_message_to_aether(gateway_message)

        if self.cognitive_bus is not None:
            try:
                await self.cognitive_bus.process(
                    user_input=gateway_message.text,
                    context={
                        "platform": gateway_message.platform,
                        "chat_id": gateway_message.chat_id,
                        "user_id": gateway_message.user_id,
                    },
                )
            except Exception as exc:
                logger.exception("Cognitive bus processing failed")
                return web.json_response(
                    {"error": f"Cognitive bus error: {exc}"},
                    status=500,
                )
        else:
            self._queue.append(aether_message)

        return web.json_response(
            {
                "status": "accepted",
                "platform": platform,
                "message_id": aether_message.msg_id,
            },
            status=200,
        )

    def _build_app(self) -> Any:
        """Build the aiohttp application."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required to run GatewayServer")  # pragma: no cover
        self._app = web.Application()
        self._app.router.add_post("/gateway/{platform}", self._handle_platform_post)
        self._app.router.add_get("/health", self._handle_health)
        return self._app

    async def _handle_health(self, request: Any) -> Any:
        """Health check endpoint."""
        if not HAS_AIOHTTP:
            return None  # pragma: no cover
        return web.json_response({"status": "ok", "service": "laap-gateway"})

    async def start(self) -> None:
        """Start the HTTP server."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required to run GatewayServer")  # pragma: no cover
        self._build_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("GatewayServer started on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._site is not None:
            await self._site.stop()
        if self._runner is not None:
            await self._runner.cleanup()
        logger.info("GatewayServer stopped")

    async def run_forever(self) -> None:
        """Blocking helper that keeps the server alive."""
        await self.start()
        while True:
            await asyncio.sleep(3600)
