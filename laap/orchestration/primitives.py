import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


logger = logging.getLogger("laap.orchestration")


class MessageType(Enum):
    # Aether actor runtime semantics
    INVOKE = "INVOKE"
    CLAIM = "CLAIM"
    DELEGATE = "DELEGATE"
    EMIT = "EMIT"
    STATE_DELTA = "STATE_DELTA"
    CHECKPOINT = "CHECKPOINT"
    META_EVOLVE = "META_EVOLVE"

    # Legacy AgentMessage semantics (kept for backward compatibility)
    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    FORK = "fork_request"
    FUSION = "fusion_proposal"
    STATUS = "status_report"
    NULL_INJECT = "null_injection"


@dataclass(frozen=True)
class AetherAddress:
    host: str
    actor_id: str
    capability: str = "*"

    def __str__(self) -> str:
        return f"aether://{self.host}/{self.actor_id}#{self.capability}"

    def to_dict(self) -> dict[str, str]:
        return {
            "host": self.host,
            "actor_id": self.actor_id,
            "capability": self.capability,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "AetherAddress":
        return cls(
            host=data["host"],
            actor_id=data["actor_id"],
            capability=data.get("capability", "*"),
        )


@dataclass
class AetherMessage:
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    msg_type: MessageType = MessageType.INVOKE
    sender: Optional[AetherAddress] = None
    recipient: Optional[AetherAddress] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    vector_clock: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: int = 0
    ttl: int = 3
    # P0/Direction: 方向偏置信号，来自 Kakeya 覆盖度监控器
    direction_bias: Optional[Dict[str, float]] = None

    def increment_clock(self, actor_id: str) -> "AetherMessage":
        self.vector_clock[actor_id] = self.vector_clock.get(actor_id, 0) + 1
        return self

    @property
    def sender_id(self) -> str:
        """Legacy alias for sender actor id."""
        return self.sender.actor_id if self.sender is not None else ""

    @property
    def target_id(self) -> str:
        """Legacy alias for recipient actor id."""
        return self.recipient.actor_id if self.recipient is not None else ""

    @property
    def content(self) -> str:
        """Legacy alias for textual payload content."""
        return str(self.payload.get("content", ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type.value,
            "sender": self.sender.to_dict() if self.sender else None,
            "recipient": self.recipient.to_dict() if self.recipient else None,
            "payload": self.payload,
            "vector_clock": self.vector_clock,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "ttl": self.ttl,
            "direction_bias": self.direction_bias,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AetherMessage":
        msg_type = data.get("msg_type")
        if isinstance(msg_type, str):
            msg_type = MessageType(msg_type)
        return cls(
            msg_id=data.get("msg_id", str(uuid.uuid4())),
            msg_type=msg_type or MessageType.INVOKE,
            sender=AetherAddress.from_dict(data["sender"]) if data.get("sender") else None,
            recipient=AetherAddress.from_dict(data["recipient"]) if data.get("recipient") else None,
            payload=data.get("payload", {}),
            vector_clock=data.get("vector_clock", {}),
            timestamp=data.get("timestamp", time.time()),
            priority=data.get("priority", 0),
            ttl=data.get("ttl", 3),
            direction_bias=data.get("direction_bias"),
        )


class MessageRouter:
    """消息路由器 — 使用统一的 AetherMessage 寻址模型。

    原位于 ``laap.orchestration.protocol``；随着协议层合并，
    路由器作为基础原语迁至 ``primitives.py``。
    """

    def __init__(self):
        self.queues: Dict[str, List[AetherMessage]] = {}
        self._sent: List[AetherMessage] = []

    def send(self, msg: AetherMessage) -> None:
        recipient_id = msg.target_id
        if not recipient_id and msg.recipient is not None:
            recipient_id = msg.recipient.actor_id
        if recipient_id:
            self.queues.setdefault(recipient_id, []).append(msg)
        self._sent.append(msg)

    def broadcast(self, msg: AetherMessage, targets: List[str]) -> None:
        for t in targets:
            copy = AetherMessage(
                msg_type=msg.msg_type,
                sender=msg.sender,
                recipient=AetherAddress(host="local", actor_id=t),
                payload=msg.payload.copy(),
                vector_clock=msg.vector_clock.copy(),
                timestamp=msg.timestamp,
                priority=msg.priority,
                ttl=msg.ttl,
            )
            self.send(copy)

    def receive(self, agent_id: str) -> List[AetherMessage]:
        msgs = self.queues.get(agent_id, [])
        self.queues[agent_id] = []
        return msgs

    def status(self) -> dict:
        return {k: len(v) for k, v in self.queues.items() if v}
