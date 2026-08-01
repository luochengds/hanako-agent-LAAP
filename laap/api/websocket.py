"""LAAP WebSocket 推送管理器。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ClientConnection:
    """单个 WebSocket 客户端连接的元数据。"""

    client_id: str
    websocket: Any  # starlette.websockets.WebSocket
    subscriptions: Set[str] = field(default_factory=set)  # 订阅的事件类型
    connected_at: float = field(default_factory=time.time)

    async def send_json(self, data: Dict[str, Any]) -> bool:
        """发送 JSON 数据到客户端，返回是否成功。"""
        try:
            await self.websocket.send_text(
                json.dumps(data, ensure_ascii=False, default=str)
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to send to client {self.client_id}: {e}")
            return False


class WebSocketManager:
    """WebSocket 连接管理器，支持广播与按事件订阅。"""

    def __init__(self) -> None:
        self._connections: Dict[str, ClientConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: Any, client_id: Optional[str] = None) -> str:
        """接受 WebSocket 连接并注册到管理器。

        Args:
            websocket: starlette WebSocket 实例
            client_id: 可选客户端 ID，未提供则自动生成 uuid4

        Returns:
            分配的 client_id
        """
        cid = client_id or str(uuid.uuid4())
        await websocket.accept()
        async with self._lock:
            self._connections[cid] = ClientConnection(
                client_id=cid,
                websocket=websocket,
            )
        logger.info(f"WebSocket client connected: {cid}")
        return cid

    async def disconnect(self, client_id: str) -> None:
        """移除客户端连接。"""
        async with self._lock:
            self._connections.pop(client_id, None)
        logger.info(f"WebSocket client disconnected: {client_id}")

    async def subscribe(self, client_id: str, event_types: List[str]) -> bool:
        """为客户端订阅特定事件类型。

        Args:
            client_id: 客户端 ID
            event_types: 事件类型列表（如 ["psi_state", "memory_update"]）

        Returns:
            True 如果订阅成功，False 如果客户端不存在
        """
        async with self._lock:
            conn = self._connections.get(client_id)
            if conn is None:
                return False
            conn.subscriptions.update(event_types)
        return True

    async def broadcast(self, event_type: str, payload: Any) -> int:
        """广播消息到所有订阅该事件类型的客户端。

        Args:
            event_type: 事件类型（如 "psi_state" / "memory_update"）
            payload: 任意可序列化数据

        Returns:
            成功推送的客户端数量
        """
        message = {
            "type": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }
        sent_count = 0
        dead_clients: List[str] = []

        async with self._lock:
            # snapshot 避免持锁等待 IO
            conns = list(self._connections.values())

        for conn in conns:
            # 客户端未订阅任何事件 → 接收所有（向后兼容）
            # 客户端订阅了特定事件 → 仅推送订阅事件
            if conn.subscriptions and event_type not in conn.subscriptions:
                continue
            ok = await conn.send_json(message)
            if ok:
                sent_count += 1
            else:
                dead_clients.append(conn.client_id)

        # 清理失效连接
        if dead_clients:
            async with self._lock:
                for cid in dead_clients:
                    self._connections.pop(cid, None)
            logger.info(f"Cleaned up {len(dead_clients)} dead WebSocket clients")

        return sent_count

    async def handle_connection(
        self, websocket: Any, client_id: Optional[str] = None
    ) -> None:
        """处理 WebSocket 连接生命周期。

        接受连接后循环接收客户端消息：
        - {"subscribe": ["event1", "event2"]} 订阅事件
        - {"unsubscribe": ["event1"]} 取消订阅
        - {"ping": ...} 心跳，返回 {"pong": ...}

        直到客户端断开连接。
        """
        cid = await self.connect(websocket, client_id)
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"error": "invalid json"}))
                    continue

                if msg.get("subscribe"):
                    await self.subscribe(cid, msg["subscribe"])
                    await websocket.send_text(
                        json.dumps({"subscribed": msg["subscribe"]})
                    )
                elif msg.get("unsubscribe"):
                    async with self._lock:
                        conn = self._connections.get(cid)
                        if conn:
                            conn.subscriptions.difference_update(msg["unsubscribe"])
                    await websocket.send_text(
                        json.dumps({"unsubscribed": msg["unsubscribe"]})
                    )
                elif msg.get("ping"):
                    await websocket.send_text(json.dumps({"pong": msg["ping"]}))
        except Exception as e:
            # WebSocketDisconnect 或其他异常
            logger.debug(f"WebSocket {cid} disconnected: {e}")
        finally:
            await self.disconnect(cid)

    def stats(self) -> Dict[str, Any]:
        """返回管理器统计信息。"""
        return {
            "total_connections": len(self._connections),
            "client_ids": list(self._connections.keys()),
        }


# 模块级单例
_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """获取 WebSocketManager 单例。"""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager
