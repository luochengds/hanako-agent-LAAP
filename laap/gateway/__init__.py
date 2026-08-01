"""LAAP Gateway — Multi-Platform Messaging Gateway

Start with: laap gateway [--platform telegram] [--token xxx]
"""

from __future__ import annotations

# Pluggable gateway abstraction (Task 10 backfill).
from laap.gateway.base import GatewayAdapter, GatewayMessage
from laap.gateway.feishu import FeishuGatewayAdapter
from laap.gateway.telegram import TelegramGatewayAdapter
from laap.gateway.server import GatewayServer

# Legacy gateway components (kept for backward compatibility).
from laap.gateway.engine import GatewayEngine, SessionStore, PlatformRegistry, SessionEntry
from laap.gateway.events import GatewayEvent, MessageChunk, MessageStop, ToolCallChunk

__all__ = [
    # Pluggable abstraction
    "GatewayAdapter",
    "GatewayMessage",
    "FeishuGatewayAdapter",
    "TelegramGatewayAdapter",
    "GatewayServer",
    # Legacy
    "GatewayEngine",
    "SessionStore",
    "PlatformRegistry",
    "SessionEntry",
    "GatewayEvent",
    "MessageChunk",
    "MessageStop",
    "ToolCallChunk",
]
