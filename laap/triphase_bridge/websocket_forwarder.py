"""EventBus → WebSocketManager 事件转发器。

由于 EventBus 是同步的，而 WebSocketManager.broadcast 是异步的，
本模块在已有事件循环上通过 run_coroutine_threadsafe 完成桥接。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from laap.events.bus import EventBus
from laap.api.websocket import WebSocketManager

logger = logging.getLogger(__name__)


class EventBusToWebSocketForwarder:
    """订阅 EventBus 的全部事件并转发到 WebSocketManager。"""

    def __init__(
        self,
        event_bus: EventBus,
        websocket_manager: WebSocketManager,
        loop: asyncio.AbstractEventLoop | None = None,
        prefix_allowlist: list[str] | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.websocket_manager = websocket_manager
        self.loop = loop or asyncio.get_event_loop()
        self.prefix_allowlist = prefix_allowlist or []
        self._handler = self._on_event
        self._subscribed = False

    def start(self) -> None:
        """开始转发。"""
        if self._subscribed:
            return
        self.event_bus.subscribe("*", self._handler)
        self._subscribed = True
        logger.info("EventBus → WebSocket 转发器已启动")

    def stop(self) -> None:
        """停止转发。"""
        if not self._subscribed:
            return
        self.event_bus.unsubscribe("*", self._handler)
        self._subscribed = False
        logger.info("EventBus → WebSocket 转发器已停止")

    def _on_event(self, event: Any) -> None:
        """EventBus 回调：把事件异步广播到 WebSocket 客户端。"""
        if self.prefix_allowlist and not any(
            str(event.type).startswith(p) for p in self.prefix_allowlist
        ):
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.websocket_manager.broadcast(
                    event.type,
                    {
                        "source": getattr(event, "source", "system"),
                        "data": event.data,
                        "timestamp": getattr(event, "timestamp", None),
                    },
                ),
                self.loop,
            )
        except Exception as e:
            logger.warning("EventBus → WebSocket 转发失败: %s", e)
