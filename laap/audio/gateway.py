"""AetherMessage WebSocket 网关（端口 8765）。

将 laap-client 的 CognitiveBusClient AetherMessage 协议桥接到 LAAP 后端：
  - 接收客户端消息 -> 发布到 EventBus
  - 订阅 EventBus / CognitiveBus -> 以 AetherMessage 格式广播给客户端
  - 处理 ping/pong 心跳
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, Set

from laap.agi.cognitive_bus import (
    CognitiveBus,
    CognitiveEvent,
    CognitiveEventType,
    get_bus as get_cognitive_bus,
)
from laap.events.bus import EventBus, bus as global_event_bus

logger = logging.getLogger("laap.audio.gateway")

try:
    import websockets
    import websockets.server
    HAS_WEBSOCKETS = True
except Exception:
    HAS_WEBSOCKETS = False


class AetherGateway:
    """兼容 laap-client CognitiveBusClient 的 WebSocket 网关。"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        event_bus: Optional[EventBus] = None,
        cognitive_bus: Optional[CognitiveBus] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.event_bus = event_bus or global_event_bus
        self.cognitive_bus = cognitive_bus or get_cognitive_bus("aris")
        self._clients: Set[websockets.WebSocketServerProtocol] = set()
        self._server: Optional[websockets.WebSocketServer] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._consumer_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._event_bus_subscribed = False
        self._cognitive_subscribed = False

    async def start(self) -> None:
        if not HAS_WEBSOCKETS:
            logger.error("websockets 未安装，无法启动 AetherGateway")
            return
        self._loop = asyncio.get_running_loop()
        self._subscribe_buses()
        self._server = await websockets.server.serve(
            self._handle_client,
            self.host,
            self.port,
        )
        self._consumer_task = asyncio.create_task(self._consume_queue())
        logger.info(f"AetherGateway 已启动 ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        self._unsubscribe_buses()
        if self._consumer_task:
            self._consumer_task.cancel()
            self._consumer_task = None
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("AetherGateway 已停止")

    # ── 总线订阅 ──

    def _subscribe_buses(self) -> None:
        if not self._event_bus_subscribed:
            self.event_bus.subscribe("*", self._on_event_bus)
            self._event_bus_subscribed = True

        if not self._cognitive_subscribed:
            for event_type in CognitiveEventType:
                try:
                    self.cognitive_bus.subscribe("aether_gateway", event_type, self._on_cognitive_event)
                except Exception as e:
                    logger.debug(f"订阅认知事件 {event_type.value} 失败: {e}")
            self._cognitive_subscribed = True

    def _unsubscribe_buses(self) -> None:
        if self._event_bus_subscribed:
            self.event_bus.unsubscribe("*", self._on_event_bus)
            self._event_bus_subscribed = False
        if self._cognitive_subscribed:
            for event_type in CognitiveEventType:
                self.cognitive_bus.unsubscribe("aether_gateway", event_type)
            self._cognitive_subscribed = False

    def _on_event_bus(self, event) -> None:
        """EventBus 回调（可能来自任意线程） -> 放入 asyncio 队列。"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, ("event", event))

    def _on_cognitive_event(self, event: CognitiveEvent) -> None:
        """CognitiveBus 回调 -> 放入 asyncio 队列。"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, ("cognitive", event))

    async def _consume_queue(self) -> None:
        while True:
            kind, event = await self._queue.get()
            try:
                if kind == "raw":
                    await self._broadcast(event)
                    continue
                if kind == "event":
                    msg = self._event_to_aether(event)
                else:
                    msg = self._cognitive_event_to_aether(event)
                if msg:
                    await self._broadcast(msg)
            except Exception as e:
                logger.warning(f"广播消息失败: {e}")

    # ── 消息转换 ──

    def _event_to_aether(self, event) -> Optional[Dict[str, Any]]:
        data = event.data if isinstance(event.data, dict) else {"data": event.data}
        return {
            "id": uuid.uuid4().hex[:16],
            "type": event.type,
            "topic": event.type,
            "payload": data,
            "timestamp": int(event.timestamp * 1000),
            "sender": event.source or "laap",
        }

    def _cognitive_event_to_aether(self, event: CognitiveEvent) -> Optional[Dict[str, Any]]:
        topic = event.type.value
        payload = event.data if isinstance(event.data, dict) else {}

        if event.type == CognitiveEventType.NEED_CHANGED:
            # 拆分为 need_* 事件，便于前端 laapStore 订阅
            messages = []
            for key, change in payload.items():
                messages.append({
                    "id": uuid.uuid4().hex[:16],
                    "type": "need_changed",
                    "topic": f"need_{key}",
                    "payload": {"value": change.get("new") if isinstance(change, dict) else change},
                    "timestamp": int(event.timestamp * 1000),
                    "sender": event.source or "cognitive_bus",
                })
            # 这里只返回第一条；其余额外广播
            if len(messages) > 1:
                for extra in messages[1:]:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, ("raw", extra))
            return messages[0] if messages else None

        if event.type == CognitiveEventType.EMOTION_CHANGED:
            messages = []
            for key, change in payload.items():
                messages.append({
                    "id": uuid.uuid4().hex[:16],
                    "type": "emotion_changed",
                    "topic": f"emotion_{key}",
                    "payload": {"value": change.get("new") if isinstance(change, dict) else change},
                    "timestamp": int(event.timestamp * 1000),
                    "sender": event.source or "cognitive_bus",
                })
            if len(messages) > 1:
                for extra in messages[1:]:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, ("raw", extra))
            return messages[0] if messages else None

        if event.type == CognitiveEventType.ATTENTION_SHIFTED:
            topic = "v12_kernel"
            payload = {
                "phase": payload.get("focus", "idle"),
                "progress": payload.get("intensity", 0.5),
            }

        return {
            "id": uuid.uuid4().hex[:16],
            "type": topic,
            "topic": topic,
            "payload": payload,
            "timestamp": int(event.timestamp * 1000),
            "sender": event.source or "cognitive_bus",
        }

    async def _broadcast(self, message: Dict[str, Any]) -> None:
        if not self._clients:
            return
        data = json.dumps(message, ensure_ascii=False, default=str)
        dead: Set[Any] = set()
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except Exception:
                dead.add(ws)
        if dead:
            self._clients -= dead

    # ── WebSocket 连接处理 ──

    async def _handle_client(self, websocket: websockets.WebSocketServerProtocol, path: str = "") -> None:
        self._clients.add(websocket)
        logger.info(f"CognitiveBus 客户端已连接: {websocket.remote_address}")
        try:
            async for raw in websocket:
                await self._handle_message(websocket, raw)
        except Exception as e:
            logger.debug(f"客户端连接异常: {e}")
        finally:
            self._clients.discard(websocket)
            logger.info(f"CognitiveBus 客户端已断开: {websocket.remote_address}")

    async def _handle_message(self, websocket: websockets.WebSocketServerProtocol, raw: Any) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("收到非 JSON 消息")
            return

        topic = msg.get("topic") or msg.get("type")
        if topic == "ping":
            await websocket.send(json.dumps({
                "topic": "pong",
                "timestamp": msg.get("timestamp"),
            }, ensure_ascii=False))
            return

        payload = msg.get("payload", {})
        sender = msg.get("sender", "user")
        self.event_bus.publish_simple(topic, payload, source=sender)


# 模块级单例
_gateway_instance: Optional[AetherGateway] = None


async def start_gateway(
    host: str = "0.0.0.0",
    port: int = 8765,
    event_bus: Optional[EventBus] = None,
    cognitive_bus: Optional[CognitiveBus] = None,
) -> AetherGateway:
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = AetherGateway(
            host=host,
            port=port,
            event_bus=event_bus,
            cognitive_bus=cognitive_bus,
        )
        await _gateway_instance.start()
    return _gateway_instance
