"""
LAAP-COM v1.0 — 数字生命体通信协议

定义生命体之间的消息格式、路由、加密：
- 意图驱动 (非类型驱动)
- 优先级 + TTL 时效
- 端到端签名
- 支持请求/响应/事件/广播
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

logger = logging.getLogger("laap.protocol.com")


def sign(private_key: Ed25519PrivateKey, message: bytes) -> bytes:
    """使用 Ed25519 私钥对消息签名，返回 64 字节签名。"""
    return private_key.sign(message)


def verify(public_key: Ed25519PublicKey, message: bytes, signature: bytes) -> bool:
    """使用 Ed25519 公钥验证消息签名；旧格式签名会被干净地拒绝。"""
    if len(signature) != 64:
        return False
    try:
        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        return False


class MessageType(str, Enum):
    REQUEST = "request"       # 请求-响应模式
    RESPONSE = "response"     # 响应
    EVENT = "event"           # 事件通知 (单向)
    BROADCAST = "broadcast"   # 广播 (一对多)

class MessageIntent(str, Enum):
    COLLABORATE = "collaborate"   # 协作
    INFORM = "inform"             # 通知
    REQUEST = "request"           # 请求
    EVOLVE = "evolve"             # 进化
    REPRODUCE = "reproduce"       # 繁殖
    SYNC = "sync"                 # 同步
    HEARTBEAT = "heartbeat"       # 心跳


@dataclass
class Message:
    """LAAP-COM 标准消息"""
    protocol: str = "LAAP-COM"
    version: str = "1.0"
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:16]}")
    sender: str = ""                # 发送者 LAAP-ID
    recipient: str = ""             # 接收者 LAAP-ID 或 "*" (广播)
    type: MessageType = MessageType.REQUEST
    intent: MessageIntent = MessageIntent.INFORM
    payload: Any = None
    priority: float = 0.5          # 0-1
    ttl: int = 60                   # 生存时间(秒)
    correlation_id: str = ""        # 关联消息ID (用于请求-响应配对)
    timestamp: float = field(default_factory=time.time)
    signature: str = ""             # 发送者签名 (base64 编码的 64 字节 Ed25519 签名)

    def _canonical_bytes(self) -> bytes:
        """构造用于签名的确定性消息字节。"""
        content = (
            f"{self.message_id}:{self.sender}:{self.recipient}:"
            f"{json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        )
        return content.encode("utf-8")

    def sign(
        self,
        private_key: Optional[Ed25519PrivateKey] = None,
        secret: str = "",
    ) -> str:
        """使用 Ed25519 私钥签名消息。

        兼容旧 API：若仅传入 ``secret``，则从中确定性派生 Ed25519 私钥。
        若未提供任何密钥材料，则签名置空，不再生成伪签名。
        """
        if private_key is not None:
            sig_bytes = sign(private_key, self._canonical_bytes())
            self.signature = base64.b64encode(sig_bytes).decode("ascii")
        elif secret:
            seed = hashlib.sha256(secret.encode("utf-8")).digest()
            derived_key = Ed25519PrivateKey.from_private_bytes(seed)
            sig_bytes = sign(derived_key, self._canonical_bytes())
            self.signature = base64.b64encode(sig_bytes).decode("ascii")
        else:
            self.signature = ""
        return self.signature

    def verify(self, public_key: Ed25519PublicKey) -> bool:
        """使用 Ed25519 公钥验证消息签名；旧格式签名会被拒绝。"""
        if not self.signature:
            return False
        try:
            sig_bytes = base64.b64decode(self.signature.encode("ascii"), validate=True)
        except Exception:
            return False
        return verify(public_key, self._canonical_bytes(), sig_bytes)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    def to_dict(self) -> dict:
        return asdict(self)


class MessageBus:
    """消息总线——生命体之间通信的核心"""

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._pending_responses: Dict[str, Message] = {}
        self._stats = {"sent": 0, "received": 0, "routed": 0}

    def subscribe(self, intent: str, handler: Callable[[Message], Optional[Message]]):
        """订阅特定意图的消息"""
        self._handlers.setdefault(intent, []).append(handler)

    def send(self, msg: Message) -> Optional[Message]:
        """发送消息 (同步请求-响应)"""
        msg.sign()
        self._stats["sent"] += 1
        logger.debug(f"Send: {msg.intent.value} → {msg.recipient[:16]}")

        # 查找处理器
        handlers = self._handlers.get(msg.intent.value, [])
        if not handlers:
            logger.warning(f"No handler for intent: {msg.intent.value}")
            return None

        # 调用处理器
        for handler in handlers:
            response = handler(msg)
            if response:
                self._stats["routed"] += 1
                if msg.type == MessageType.REQUEST:
                    self._pending_responses[msg.message_id] = response
                return response
        return None

    def publish(self, msg: Message):
        """发布事件 (异步广播)"""
        msg.type = MessageType.EVENT
        msg.sign()
        self._stats["sent"] += 1
        handlers = self._handlers.get(msg.intent.value, [])
        for handler in handlers:
            try:
                handler(msg)
                self._stats["routed"] += 1
            except Exception as e:
                logger.warning(f"Handler error: {e}")

    def get_stats(self) -> dict:
        return dict(self._stats)


# ── 全局消息总线 ────────────────────────────────────────────

_bus: Optional[MessageBus] = None

def get_bus() -> MessageBus:
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus

def send_message(sender: str, recipient: str, intent: MessageIntent,
                 payload: Any = None) -> Optional[Message]:
    """便捷：发送消息"""
    msg = Message(sender=sender, recipient=recipient, intent=intent, payload=payload)
    return get_bus().send(msg)


# ── P3-p2p-relay: 中继节点注册表 + 心跳调度 ─────────────────────────────
# spec tasks.md L95-101 (SubTask 3.2/3.3/3.4/3.5):
#   - /relay/discover 返回在线列表
#   - /relay/heartbeat 接收心跳（30s 间隔，90s 超时）
#   - /relay/offline 标记离线，触发 bubble-field 泡泡变暗事件
#   - P2P WebRTC 信令交换 stub（真实 WebRTC 由前端 hanako 处理）
#   - 加密信道：sign_message + verify_message 简化版（复用 p3-identity-pki）
#
# 硬约束（spec L427/L435）：
#   - clock 注入便于测试 mock；禁用 asyncio（用 threading.Timer / 同步调用）
#   - 私钥永不离开 sidecar；encrypt_channel 接收 raw bytes 私钥但不返回
#   - 不破坏现有 Message / MessageBus
#   - TODO P3-1v1-protocol: 升级为 ECIES（X25519 + AES-GCM）


@dataclass
class RelayNodeInfo:
    """中继节点信息（P3-p2p-relay）"""
    public_key: str
    name: str
    address: str = ""
    capabilities: List[str] = field(default_factory=list)
    color: str = ""
    online: bool = True
    last_heartbeat: float = 0.0
    registered_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "public_key": self.public_key,
            "name": self.name,
            "address": self.address,
            "capabilities": list(self.capabilities),
            "color": self.color,
            "online": self.online,
            "last_heartbeat": self.last_heartbeat,
            "registered_at": self.registered_at,
        }


class RelayRegistry:
    """P3-p2p-relay: 中继节点注册表 + 心跳调度.

    spec SubTask 3.2/3.5:
        - ``register_node`` 首次注册或更新信息
        - ``heartbeat`` 刷新心跳；未注册节点拒绝
        - ``mark_offline`` 标记离线，触发 ``agent_offline`` 事件
        - ``discover`` 先 ``_sweep_stale`` 标记超时节点离线，再返回在线列表
        - ``_sweep_stale`` 用 ``(now - last_heartbeat) > offline_timeout`` 判定

    Args:
        clock: 时间源 callable，注入便于测试 mock（默认 ``time.time``）。
        heartbeat_interval: 心跳间隔秒数（spec: 30）。
        offline_timeout: 离线超时秒数（spec: 90）。

    说明:
        - ``_emit`` lazy import ``laap.events.bus``，避免循环导入。
        - 不持久化到磁盘（中继状态瞬时，重启即清空）。
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        heartbeat_interval: int = 30,
        offline_timeout: int = 90,
    ):
        self._clock = clock
        self._heartbeat_interval = heartbeat_interval
        self._offline_timeout = offline_timeout
        self._nodes: Dict[str, RelayNodeInfo] = {}

    def register_node(
        self,
        public_key: str,
        name: str,
        address: str = "",
        capabilities: Optional[List[str]] = None,
        color: str = "",
    ) -> dict:
        """注册或更新节点信息.

        首次注册触发 ``agent_online`` 事件；后续调用视为信息更新
        （name/address/capabilities/color 任一非空即覆盖），并刷新心跳.

        Returns:
            节点信息字典（与 ``RelayNodeInfo.to_dict`` 一致）.
        Raises:
            ValueError: ``public_key`` / ``name`` 为空.
        """
        if not isinstance(public_key, str) or not public_key.strip():
            raise ValueError("public_key must be non-empty str")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be non-empty str")
        now = self._clock()
        existing = self._nodes.get(public_key)
        if existing is None:
            node = RelayNodeInfo(
                public_key=public_key,
                name=name,
                address=address or "",
                capabilities=list(capabilities) if capabilities else [],
                color=color or "",
                online=True,
                last_heartbeat=now,
                registered_at=now,
            )
            self._nodes[public_key] = node
            self._emit("agent_online", public_key, name)
        else:
            existing.name = name or existing.name
            if address:
                existing.address = address
            if capabilities:
                existing.capabilities = list(capabilities)
            if color:
                existing.color = color
            existing.online = True
            existing.last_heartbeat = now
        return self._nodes[public_key].to_dict()

    def heartbeat(self, public_key: str) -> dict:
        """刷新节点心跳.

        未注册节点拒绝（spec SubTask 3.2: 仅已注册节点可发心跳）.

        Returns:
            ``{ok, online, last_heartbeat, next_heartbeat_due}`` 成功；
            ``{ok: False, error: ...}`` 失败.
        """
        if not isinstance(public_key, str) or not public_key.strip():
            return {"ok": False, "error": "public_key must be non-empty str"}
        node = self._nodes.get(public_key)
        if node is None:
            return {"ok": False, "error": "node not registered"}
        now = self._clock()
        was_offline = not node.online
        node.last_heartbeat = now
        node.online = True
        # 节点恢复：从离线状态回到在线
        if was_offline:
            self._emit("agent_online", public_key, node.name, reason="heartbeat_revive")
        return {
            "ok": True,
            "online": True,
            "last_heartbeat": now,
            "next_heartbeat_due": now + self._heartbeat_interval,
        }

    def mark_offline(self, public_key: str, reason: str = "manual") -> dict:
        """标记节点离线，触发 ``agent_offline`` 事件（泡泡变暗）.

        Returns:
            ``{ok, online: False, public_key, name, reason}``；
            未注册返回 ``{ok: False, error: ...}``.
        """
        if not isinstance(public_key, str) or not public_key.strip():
            return {"ok": False, "error": "public_key must be non-empty str"}
        node = self._nodes.get(public_key)
        if node is None:
            return {"ok": False, "error": "node not registered"}
        node.online = False
        self._emit("agent_offline", public_key, node.name, reason=reason)
        return {
            "ok": True,
            "online": False,
            "public_key": public_key,
            "name": node.name,
            "reason": reason,
        }

    def discover(self, include_offline: bool = False) -> List[dict]:
        """列出在线节点（先 ``_sweep_stale`` 标记超时离线）.

        Args:
            include_offline: True 时返回包含离线节点在内的全部节点.
        """
        self._sweep_stale()
        result = []
        for node in self._nodes.values():
            if not node.online and not include_offline:
                continue
            result.append(node.to_dict())
        return result

    def get_node(self, public_key: str) -> Optional[RelayNodeInfo]:
        """直接查询节点信息（不触发 sweep）."""
        return self._nodes.get(public_key)

    def count(self) -> int:
        return len(self._nodes)

    def _sweep_stale(self) -> None:
        """标记超时节点离线（spec SubTask 3.5: 90s 超时）."""
        now = self._clock()
        for node in self._nodes.values():
            if not node.online:
                continue
            if (now - node.last_heartbeat) > self._offline_timeout:
                node.online = False
                self._emit(
                    "agent_offline",
                    node.public_key,
                    node.name,
                    reason="heartbeat_timeout",
                )

    def _emit(
        self,
        event_type: str,
        public_key: str,
        name: str,
        **kwargs: Any,
    ) -> None:
        """发布事件到全局 EventBus（lazy import 避免循环依赖）."""
        try:
            from laap.events.bus import bus, Event
            data = {"public_key": public_key, "name": name}
            data.update(kwargs)
            bus.publish(Event(type=event_type, data=data, source="p2p-relay"))
        except Exception as exc:
            logger.warning(f"RelayRegistry._emit({event_type}) failed: {exc}")


class P2PSignaling:
    """P3-p2p-relay SubTask 3.3: P2P WebRTC 信令交换 stub.

    真实 WebRTC 由前端 hanako 处理，本类仅做信令中转（内存 stub）.
    提供 ``post_offer`` / ``post_answer`` / ``post_ice`` 三方法 + ``poll``
    轮询接收方待取信令.
    """

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        # to_public_key -> List[signal envelope]
        self._signals: Dict[str, List[dict]] = {}

    def post_offer(self, from_pk: str, to_pk: str, sdp: Any) -> str:
        """投递 WebRTC offer SDP."""
        return self._post(from_pk, to_pk, "offer", sdp)

    def post_answer(self, from_pk: str, to_pk: str, sdp: Any) -> str:
        """投递 WebRTC answer SDP."""
        return self._post(from_pk, to_pk, "answer", sdp)

    def post_ice(self, from_pk: str, to_pk: str, ice: Any) -> str:
        """投递 ICE candidate."""
        return self._post(from_pk, to_pk, "ice", ice)

    def _post(
        self,
        from_pk: str,
        to_pk: str,
        signal_type: str,
        payload: Any,
    ) -> str:
        signal_id = f"sig_{uuid.uuid4().hex[:16]}"
        signal = {
            "signal_id": signal_id,
            "from": from_pk,
            "to": to_pk,
            "type": signal_type,
            "payload": payload,
            "timestamp": self._clock(),
        }
        self._signals.setdefault(to_pk, []).append(signal)
        return signal_id

    def poll(self, to_pk: str) -> List[dict]:
        """轮询并清空接收方待取信令."""
        if not isinstance(to_pk, str) or not to_pk:
            return []
        return self._signals.pop(to_pk, [])


# ── 加密信道（简化版：sign + verify） ─────────────────────────────────
# spec SubTask 3.4: 用对端公钥加密 + 自身私钥签名.
# P3-p2p-relay 阶段简化为 sign_message（无真加密，仅签名+对端公钥封装）.
# TODO P3-1v1-protocol: 升级为 ECIES（X25519+AES-GCM）.

def encrypt_channel(
    message: str,
    private_key: bytes,
    peer_public_key: str,
) -> dict:
    """加密信道（简化版）.

    spec SubTask 3.4: 用对端公钥加密 + 自身私钥签名.
    P3-identity-pki 阶段简化为 ``sign_message``（无真加密，仅签名 + 对端
    公钥封装）.

    Args:
        message: 原始消息字符串.
        private_key: 32 字节 Raw Ed25519 私钥（永不通过 HTTP 返回）.
        peer_public_key: 对端 base64 公钥（封装在 envelope 中供对端校验）.

    Returns:
        ``{message, signature, public_key, peer_public_key}``：
        - ``message``: 原始消息（透传）
        - ``signature``: 发送者 Ed25519 签名（base64）
        - ``public_key``: 发送者公钥（base64，从私钥派生）
        - ``peer_public_key``: 对端公钥（base64，封装供对端校验目标）

    Raises:
        TypeError/ValueError: 私钥格式错误（透传 ``sign_message`` 异常）.

    Note:
        TODO P3-1v1-protocol: 升级为 ECIES（X25519 + AES-GCM）.
    """
    from laap.protocol.laap_id import sign_message
    signed = sign_message(message, private_key)
    return {
        "message": signed["message"],
        "signature": signed["signature"],
        "public_key": signed["public_key"],
        "peer_public_key": peer_public_key,
    }


def decrypt_channel(envelope: dict) -> dict:
    """解密信道（简化版）.

    验证签名后返回 ``message`` + ``sender_public_key``；任何异常返回
    ``{verified: False, error: ...}``（不抛出）.

    Args:
        envelope: ``encrypt_channel`` 返回的字典（或兼容结构）.

    Returns:
        成功::  ``{verified: True, message, sender_public_key}``
        失败::  ``{verified: False, message?, sender_public_key?, error}``

    Note:
        TODO P3-1v1-protocol: 升级为 ECIES（用对端公钥 + 自身私钥解密）.
    """
    if not isinstance(envelope, dict):
        return {"verified": False, "error": "envelope must be dict"}
    signed = {
        "message": envelope.get("message", ""),
        "signature": envelope.get("signature", ""),
        "public_key": envelope.get("public_key", ""),
    }
    try:
        from laap.protocol.laap_id import verify_message
        ok = verify_message(signed)
    except Exception as exc:
        return {
            "verified": False,
            "message": signed["message"],
            "sender_public_key": signed["public_key"],
            "error": f"verify_message raised: {type(exc).__name__}: {exc}",
        }
    if ok:
        return {
            "verified": True,
            "message": signed["message"],
            "sender_public_key": signed["public_key"],
        }
    return {
        "verified": False,
        "message": signed["message"],
        "sender_public_key": signed["public_key"],
        "error": "signature verification failed",
    }


# ── 全局单例（仿 laap_id.get_registry 模式） ────────────────────────────

_relay_registry: Optional[RelayRegistry] = None
_signaling: Optional[P2PSignaling] = None


def get_relay_registry() -> RelayRegistry:
    """返回全局 RelayRegistry 单例."""
    global _relay_registry
    if _relay_registry is None:
        _relay_registry = RelayRegistry()
    return _relay_registry


def get_signaling() -> P2PSignaling:
    """返回全局 P2PSignaling 单例."""
    global _signaling
    if _signaling is None:
        _signaling = P2PSignaling()
    return _signaling


def reset_relay_registry_for_test(
    clock: Optional[Callable[[], float]] = None,
    heartbeat_interval: int = 30,
    offline_timeout: int = 90,
) -> RelayRegistry:
    """测试专用：重置全局 RelayRegistry 并注入 clock.

    供 ``test_p2p_relay.py`` 使用以避免全局状态污染.
    """
    global _relay_registry
    _relay_registry = RelayRegistry(
        clock=clock or time.time,
        heartbeat_interval=heartbeat_interval,
        offline_timeout=offline_timeout,
    )
    return _relay_registry


def reset_signaling_for_test(
    clock: Optional[Callable[[], float]] = None,
) -> P2PSignaling:
    """测试专用：重置全局 P2PSignaling."""
    global _signaling
    _signaling = P2PSignaling(clock=clock or time.time)
    return _signaling


# ── P3-1v1-protocol: LAAPer 间 1v1 安全消息通道 ─────────────────────────
# spec tasks.md L104-109 (SubTask 3.1/3.2):
#   - send_1v1(peer_public_key, message) -> message_id，复用 p2p-relay 信道
#     与 identity-pki 签名
#   - receive_1v1(signed_message) -> {verified, content}，验证签名后展示
#
# 加密复用说明（spec 硬约束）：
#   - send_1v1 直接调 encrypt_channel（sign + peer_public_key 封装），
#     不另起一套加密；与 p2p-relay 保持一致
#   - receive_1v1 直接调 decrypt_channel（verify_message）
#   - TODO 后续升级 ECIES 时，只需改 encrypt_channel/decrypt_channel 两处


@dataclass
class OneOnOneMessage:
    """1v1 对话消息记录（P3-1v1-protocol）"""
    message_id: str
    sender_public_key: str
    peer_public_key: str
    content: str
    timestamp: float
    envelope: Dict[str, Any]
    verified: bool = True

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "sender_public_key": self.sender_public_key,
            "peer_public_key": self.peer_public_key,
            "content": self.content,
            "timestamp": self.timestamp,
            "verified": self.verified,
        }


class OneOnOneManager:
    """P3-1v1-protocol: LAAPer 间 1v1 安全消息通道管理器.

    spec SubTask 3.1/3.2:
        - ``send_1v1`` 复用 ``encrypt_channel``（p2p-relay 签名信道）+
          ``sign_message``（identity-pki Ed25519 签名）产出已签名信封，
          存入本地内存历史并返回 ``message_id``.
        - ``receive_1v1`` 复用 ``decrypt_channel``（verify_message）验证
          签名，返回 ``{verified, content, sender_public_key}``.
        - ``get_history`` 按 peer 公钥查询对话历史（双向，本地内存）.

    Args:
        clock: 时间源 callable，注入便于测试 mock（默认 ``time.time``）.

    说明:
        - 历史仅存内存（进程内），不持久化；跨实例消息通过 P2P 信令/
          中继投递，本类只负责签名/验签/历史索引.
        - 历史键为排序后的 ``(pk_a, pk_b)`` 元组，双向可见.
        - 不引入 LLM 依赖（纯密码学 + 路由）.
    """

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        # (sorted_pk_a, sorted_pk_b) -> List[OneOnOneMessage]
        self._history: Dict[tuple, List[OneOnOneMessage]] = {}

    @staticmethod
    def _pair_key(pk_a: str, pk_b: str) -> tuple:
        """排序后的 peer 对键，确保双向历史一致."""
        return tuple(sorted((pk_a, pk_b)))

    def send_1v1(
        self,
        sender_public_key: str,
        peer_public_key: str,
        message: str,
        private_key: bytes,
    ) -> Dict[str, Any]:
        """发送 1v1 消息（签名信封 + 历史记录）.

        spec SubTask 3.1: 复用 p2p-relay ``encrypt_channel`` 信道与
        identity-pki ``sign_message`` 签名.

        Args:
            sender_public_key: 发送方 base64 公钥（从私钥派生，校验用）.
            peer_public_key: 接收方 base64 公钥（封装在信封供对端校验）.
            message: 原始消息字符串.
            private_key: 32 字节 Raw Ed25519 私钥（永不通过 HTTP 返回）.

        Returns:
            ``{message_id, envelope, stored}``：
            - ``message_id``: 消息 ID（``msg_1v1_<hex>``）
            - ``envelope``: ``encrypt_channel`` 产出的签名信封
              ``{message, signature, public_key, peer_public_key}``
            - ``stored``: 是否写入本地历史

        Raises:
            TypeError/ValueError: 私钥格式错误（透传 ``encrypt_channel``）.
        """
        envelope = encrypt_channel(message, private_key, peer_public_key)
        message_id = f"msg_1v1_{uuid.uuid4().hex[:16]}"
        record = OneOnOneMessage(
            message_id=message_id,
            sender_public_key=sender_public_key,
            peer_public_key=peer_public_key,
            content=message,
            timestamp=self._clock(),
            envelope=envelope,
            verified=True,
        )
        key = self._pair_key(sender_public_key, peer_public_key)
        self._history.setdefault(key, []).append(record)
        return {
            "message_id": message_id,
            "envelope": envelope,
            "stored": True,
        }

    def receive_1v1(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        """接收并验证 1v1 消息（验签后返回 content）.

        spec SubTask 3.2: 复用 p2p-relay ``decrypt_channel``（内部调
        identity-pki ``verify_message``）验证 Ed25519 签名.

        Args:
            envelope: ``encrypt_channel`` 返回的签名信封字典.

        Returns:
            成功::  ``{verified: True, content, sender_public_key,
                    message_id?}``
            失败::  ``{verified: False, content?, sender_public_key?,
                    error}``
        """
        result = decrypt_channel(envelope)
        if not result.get("verified"):
            return result
        return {
            "verified": True,
            "content": result.get("message", ""),
            "sender_public_key": result.get("sender_public_key", ""),
        }

    def record_inbound(
        self,
        sender_public_key: str,
        peer_public_key: str,
        content: str,
        envelope: Dict[str, Any],
    ) -> str:
        """把已验证的入站消息写入本地历史（供 ``get_history`` 双向查询）.

        供 sidecar 在 ``receive_1v1`` 验签通过后调用，把消息归档到本地
        历史以便 UI 拉取. ``message_id`` 由本方法生成.

        Returns:
            生成的 ``message_id``.
        """
        message_id = f"msg_1v1_{uuid.uuid4().hex[:16]}"
        record = OneOnOneMessage(
            message_id=message_id,
            sender_public_key=sender_public_key,
            peer_public_key=peer_public_key,
            content=content,
            timestamp=self._clock(),
            envelope=envelope,
            verified=True,
        )
        key = self._pair_key(sender_public_key, peer_public_key)
        self._history.setdefault(key, []).append(record)
        return message_id

    def get_history(
        self,
        peer_a: str,
        peer_b: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询两个 LAAPer 之间的 1v1 对话历史（双向，按时间升序）.

        Args:
            peer_a: 一方公钥.
            peer_b: 另一方公钥.
            limit: 最大返回条数（默认 100）.

        Returns:
            消息记录列表（``OneOnOneMessage.to_dict()``），按时间升序.
        """
        key = self._pair_key(peer_a, peer_b)
        records = self._history.get(key, [])
        return [r.to_dict() for r in records[-limit:]]

    def count(self) -> int:
        """总消息数（所有 peer 对）."""
        return sum(len(v) for v in self._history.values())


# ── 全局单例 ────────────────────────────────────────────

_one_on_one: Optional[OneOnOneManager] = None


def get_one_on_one_manager() -> OneOnOneManager:
    """返回全局 OneOnOneManager 单例."""
    global _one_on_one
    if _one_on_one is None:
        _one_on_one = OneOnOneManager()
    return _one_on_one


def reset_one_on_one_manager_for_test(
    clock: Optional[Callable[[], float]] = None,
) -> OneOnOneManager:
    """测试专用：重置全局 OneOnOneManager 并注入 clock."""
    global _one_on_one
    _one_on_one = OneOnOneManager(clock=clock or time.time)
    return _one_on_one
