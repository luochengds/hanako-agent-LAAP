"""LAAP Body — Gateway Helpers

Convenience constructors for the pluggable gateway server.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from laap.gateway import FeishuGatewayAdapter, GatewayServer, TelegramGatewayAdapter


def create_default_gateway_server(
    cognitive_bus: Optional[Any] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
    telegram_bot_token: Optional[str] = None,
    extra_adapters: Optional[Dict[str, Any]] = None,
) -> GatewayServer:
    """Create a default ``GatewayServer`` with built-in adapters.

    Args:
        cognitive_bus: Optional ``ArisCognitiveBus`` instance. When None,
            incoming messages are buffered in-memory.
        host: Interface to bind.
        port: Port to bind.
        telegram_bot_token: Optional Telegram bot token. If provided,
            outbound replies via the Telegram Bot API are enabled.
        extra_adapters: Optional mapping of platform name -> adapter instance.

    Returns:
        A configured ``GatewayServer`` instance.
    """
    adapters: Dict[str, Any] = {
        "feishu": FeishuGatewayAdapter(),
        "telegram": TelegramGatewayAdapter(bot_token=telegram_bot_token),
    }
    if extra_adapters:
        adapters.update(extra_adapters)
    return GatewayServer(
        host=host,
        port=port,
        adapters=adapters,
        cognitive_bus=cognitive_bus,
    )
