"""
LAAP — Event Bus

Publish/subscribe event system for decoupled communication between components.
"""

from __future__ import annotations
import json, logging, time, threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

from laap.orchestration.primitives import AetherMessage

logger = logging.getLogger("laap.events")


class EventPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """A single event in the system"""
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    priority: EventPriority = EventPriority.NORMAL
    timestamp: float = field(default_factory=time.time)
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"evt_{int(self.timestamp * 1000000)}"


EventHandler = Callable[[Event], None]


class EventBus:
    """Publish/subscribe event bus"""

    def __init__(self):
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._history: List[Event] = []
        self._max_history = 1000

        self._aether_subscribers: Dict[str, List[Callable[[AetherMessage], None]]] = {}
        self._aether_history: List[AetherMessage] = []
        self._max_aether_history = 1000

    def subscribe(self, event_type: str, handler: EventHandler):
        """Subscribe to an event type. Use '*' for all events."""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)
            logger.debug(f"Subscribed to '{event_type}': {handler.__name__}")

    def unsubscribe(self, event_type: str, handler: EventHandler):
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    def subscribe_aether(self, msg_type_name: str,
                         handler: Callable[[AetherMessage], None]):
        """Subscribe to an AetherMessage type. Use '*' for all messages."""
        with self._lock:
            self._aether_subscribers.setdefault(msg_type_name, []).append(handler)
            logger.debug(f"Subscribed aether to '{msg_type_name}': {handler.__name__}")

    def unsubscribe_aether(self, msg_type_name: str,
                           handler: Callable[[AetherMessage], None]):
        with self._lock:
            handlers = self._aether_subscribers.get(msg_type_name, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish_aether(self, msg: AetherMessage):
        """Publish an AetherMessage to all aether subscribers."""
        with self._lock:
            if msg.sender is not None:
                msg.increment_clock(msg.sender.actor_id)

            self._aether_history.append(msg)
            if len(self._aether_history) > self._max_aether_history:
                self._aether_history = self._aether_history[-self._max_aether_history:]

            handlers = list(self._aether_subscribers.get(msg.msg_type.name, []))
            handlers.extend(self._aether_subscribers.get("*", []))

        for handler in handlers:
            try:
                handler(msg)
            except Exception as e:
                logger.error(f"Aether handler {handler.__name__} failed: {e}")

    def publish(self, event: Event):
        """Publish an event to all subscribers."""
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            # Notify type-specific subscribers
            handlers = list(self._subscribers.get(event.type, []))
            # Notify wildcard subscribers
            handlers.extend(self._subscribers.get("*", []))

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler {handler.__name__} failed: {e}")

    def publish_simple(self, event_type: str, data: Dict = None,
                       source: str = "system"):
        """Convenience method to publish a simple event."""
        self.publish(Event(
            type=event_type, data=data or {},
            source=source,
        ))

    def history(self, event_type: Optional[str] = None,
                limit: int = 50) -> List[Event]:
        """Get recent event history."""
        with self._lock:
            if event_type:
                filtered = [e for e in self._history if e.type == event_type]
                return filtered[-limit:]
            return self._history[-limit:]

    def aether_history(self, msg_type_name: Optional[str] = None,
                       limit: int = 50) -> List[AetherMessage]:
        """Get recent AetherMessage history."""
        with self._lock:
            if msg_type_name:
                filtered = [m for m in self._aether_history
                            if m.msg_type.name == msg_type_name]
                return filtered[-limit:]
            return self._aether_history[-limit:]

    def clear_history(self):
        with self._lock:
            self._history.clear()

    @property
    def status(self) -> dict:
        with self._lock:
            type_counts = defaultdict(int)
            for e in self._history:
                type_counts[e.type] += 1
            aether_counts = defaultdict(int)
            for m in self._aether_history:
                aether_counts[m.msg_type.name] += 1
            return {
                "subscribers": len(self._subscribers),
                "total_events": len(self._history),
                "by_type": dict(type_counts),
                "total_aether_messages": len(self._aether_history),
                "by_aether_type": dict(aether_counts),
            }


# Global event bus
bus = EventBus()


# ============================================================
# P4-witness-trail: 社区见证迹 WitnessTrail
# ============================================================
# spec SubTask 4.1 ~ 4.6:
#   - WitnessTrail.record(event) -> trail_id
#   - WitnessTrail.query(filter) -> trail[]
#   - 事件类型: birth / breakthrough / charter_moment / resonance / guardian_act
#   - 不可篡改: 每条 trail 附记录者签名 + 前一条 trail 哈希（链式）
#   - 跨节点同步: trail 通过 P3 p2p-relay 广播，所有节点本地保存副本
#   - 里程碑仪式触发: birth/breakthrough/charter_moment 触发社区广播
#
# 设计约束:
#   - 不修改现有 EventBus 类，新增独立 WitnessTrail 类
#   - lazy import Ed25519 / p2p-relay，避免循环依赖
#   - 私钥永不离开调用方（sidecar）：record() 仅接收 raw 私钥字节
#   - 幂等：trail_id 唯一，重复 import 同一 entry 返回同一 trail_id
# ============================================================

import hashlib as _hashlib
import uuid as _uuid

# 事件类型常量（spec SubTask 4.2）
WITNESS_EVENT_TYPES: set = {
    "birth",
    "breakthrough",
    "charter_moment",
    "resonance",
    "guardian_act",
}

# 里程碑类型：触发社区广播（spec SubTask 4.5）
WITNESS_MILESTONE_TYPES: set = {
    "birth",
    "breakthrough",
    "charter_moment",
}


@dataclass
class WitnessTrailEntry:
    """见证迹单条记录（不可篡改）.

    Attributes:
        trail_id: 全局唯一记录 ID（``trail_<uuid16>``）.
        event_type: 事件类型（参考 ``WITNESS_EVENT_TYPES``）.
        recorder: 记录者标识（agent name 或 public_key）.
        payload: 事件负载（任意可序列化字典）.
        timestamp: 记录时间戳（秒）.
        prev_hash: 前一条 trail 的 hash（链式）.
        hash: 本条 trail 的 SHA-256 hash.
        signature: 记录者 Ed25519 签名（base64，可选）.
        recorder_public_key: 记录者 base64 公钥（用于验签，可选）.
        node_id: 记录节点 ID（用于跨节点同步去重）.
    """

    trail_id: str
    event_type: str
    recorder: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    prev_hash: str = ""
    hash: str = ""
    signature: str = ""
    recorder_public_key: str = ""
    node_id: str = "local"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trail_id": self.trail_id,
            "event_type": self.event_type,
            "recorder": self.recorder,
            "payload": dict(self.payload) if isinstance(self.payload, dict) else self.payload,
            "timestamp": self.timestamp,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
            "signature": self.signature,
            "recorder_public_key": self.recorder_public_key,
            "node_id": self.node_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WitnessTrailEntry":
        return cls(
            trail_id=d.get("trail_id", ""),
            event_type=d.get("event_type", ""),
            recorder=d.get("recorder", ""),
            payload=d.get("payload", {}),
            timestamp=float(d.get("timestamp", time.time())),
            prev_hash=d.get("prev_hash", ""),
            hash=d.get("hash", ""),
            signature=d.get("signature", ""),
            recorder_public_key=d.get("recorder_public_key", ""),
            node_id=d.get("node_id", "remote"),
        )


def _entry_canonical_bytes(entry: WitnessTrailEntry) -> bytes:
    """计算 entry 的规范化字节串（用于 hash / sign）.

    排除 ``hash`` / ``signature`` 字段，避免自指.
    """
    payload = entry.payload
    payload_json = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if isinstance(payload, dict)
        else str(payload)
    )
    content = (
        f"{entry.trail_id}|{entry.event_type}|{entry.recorder}|"
        f"{entry.timestamp:.6f}|{entry.prev_hash}|{payload_json}|{entry.node_id}"
    )
    return content.encode("utf-8")


def _entry_hash(entry: WitnessTrailEntry) -> str:
    """计算 entry SHA-256 hash."""
    return _hashlib.sha256(_entry_canonical_bytes(entry)).hexdigest()


class WitnessTrail:
    """社区见证迹：不可篡改的链式事件日志.

    每条记录附 SHA-256 链式 hash + 可选 Ed25519 签名.
    里程碑事件（birth/breakthrough/charter_moment）触发社区广播.
    通过 P3 p2p-relay 跨节点同步：所有节点本地保存副本.
    """

    def __init__(
        self,
        node_id: str = "local",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._lock = threading.RLock()
        self._node_id = node_id
        self._clock = clock
        # trail_id -> WitnessTrailEntry（按插入顺序）
        self._entries: Dict[str, WitnessTrailEntry] = {}
        # 链头指针：最近一条 entry 的 hash（用于计算下一条 prev_hash）
        self._head_hash: str = ""
        # trail_id 顺序列表（用于 query/list_all 的时间顺序返回）
        self._order: List[str] = []

    # ── 记录 ───────────────────────────────────────────────

    def record(
        self,
        event_type: str,
        recorder: str,
        payload: Optional[Dict[str, Any]] = None,
        recorder_public_key: str = "",
        recorder_private_key: Optional[bytes] = None,
        broadcast: bool = True,
    ) -> Dict[str, Any]:
        """记录一条见证迹（spec SubTask 4.1）.

        Args:
            event_type: 事件类型，必须属于 ``WITNESS_EVENT_TYPES``.
            recorder: 记录者标识（agent name 或 public_key）.
            payload: 事件负载字典（任意可序列化内容）.
            recorder_public_key: 记录者 base64 公钥（可选，用于验签）.
            recorder_private_key: 记录者 32 字节 Raw Ed25519 私钥（可选，
                spec L435 私钥永不离开 sidecar，本参数仅供 sidecar 内部调用）.
            broadcast: 是否触发里程碑社区广播（默认 True）.

        Returns:
            ``{recorded: bool, trail_id?: str, hash?: str, broadcast?: dict}``.

        Raises:
            ValueError: ``event_type`` 不在 ``WITNESS_EVENT_TYPES`` 中，
                或 ``recorder`` 为空.
        """
        if event_type not in WITNESS_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {sorted(WITNESS_EVENT_TYPES)}, "
                f"got '{event_type}'"
            )
        if not isinstance(recorder, str) or not recorder.strip():
            raise ValueError("recorder must be non-empty str")

        with self._lock:
            trail_id = f"trail_{_uuid.uuid4().hex[:12]}"
            entry = WitnessTrailEntry(
                trail_id=trail_id,
                event_type=event_type,
                recorder=recorder,
                payload=dict(payload) if payload else {},
                timestamp=self._clock(),
                prev_hash=self._head_hash,
                hash="",
                signature="",
                recorder_public_key=recorder_public_key or "",
                node_id=self._node_id,
            )
            entry.hash = _entry_hash(entry)

            # 可选签名（spec L435 私钥永不离开 sidecar）
            if recorder_private_key is not None and recorder_public_key:
                try:
                    from laap.protocol.laap_id import sign_message
                    signed = sign_message(
                        message=entry.hash,
                        private_key=recorder_private_key,
                    )
                    entry.signature = signed["signature"]
                except Exception as exc:
                    logger.warning(
                        f"witness_trail sign failed for trail_id={trail_id}: {exc}"
                    )

            self._entries[trail_id] = entry
            self._order.append(trail_id)
            self._head_hash = entry.hash

        # 里程碑社区广播（spec SubTask 4.5）
        broadcast_result: Dict[str, Any] = {}
        if broadcast and event_type in WITNESS_MILESTONE_TYPES:
            broadcast_result = self._broadcast_milestone(entry)

        # 发布到本地 EventBus（让 UI / 其他模块可订阅）
        self._emit_local_event(entry)

        return {
            "recorded": True,
            "trail_id": trail_id,
            "hash": entry.hash,
            "prev_hash": entry.prev_hash,
            "broadcast": broadcast_result,
        }

    # ── 查询 ───────────────────────────────────────────────

    def query(
        self,
        event_type: Optional[str] = None,
        recorder: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询见证迹（spec SubTask 4.1）.

        Args:
            event_type: 按事件类型过滤（None 表示不过滤）.
            recorder: 按记录者过滤（None 表示不过滤）.
            since: 起始时间戳（含，None 表示不限）.
            until: 截止时间戳（含，None 表示不限）.
            limit: 最大返回条数（按时间倒序，最近优先）.

        Returns:
            匹配的 entry dict 列表（最近的最先）.
        """
        with self._lock:
            snapshot = [self._entries[tid] for tid in self._order]
        result: List[Dict[str, Any]] = []
        for entry in snapshot:
            if event_type and entry.event_type != event_type:
                continue
            if recorder and entry.recorder != recorder:
                continue
            if since is not None and entry.timestamp < since:
                continue
            if until is not None and entry.timestamp > until:
                continue
            result.append(entry.to_dict())
        result.reverse()  # 最近优先
        if limit > 0:
            result = result[:limit]
        return result

    def get(self, trail_id: str) -> Optional[Dict[str, Any]]:
        """按 trail_id 查询单条记录."""
        with self._lock:
            entry = self._entries.get(trail_id)
        return entry.to_dict() if entry else None

    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出全部记录（按时间倒序）."""
        return self.query(limit=limit)

    # ── 链式完整性验证 ─────────────────────────────────────

    def verify_chain(self) -> Dict[str, Any]:
        """验证链式完整性（不可篡改检测）.

        Returns:
            ``{verified: bool, broken_at?: str, reason?: str, total: int}``.
        """
        with self._lock:
            order = list(self._order)
            entries = [self._entries[tid] for tid in order]

        prev_hash = ""
        for i, entry in enumerate(entries):
            # 1. prev_hash 链式
            if entry.prev_hash != prev_hash:
                return {
                    "verified": False,
                    "broken_at": entry.trail_id,
                    "reason": "prev_hash_mismatch",
                    "total": len(entries),
                }
            # 2. hash 重算
            if entry.hash != _entry_hash(entry):
                return {
                    "verified": False,
                    "broken_at": entry.trail_id,
                    "reason": "hash_tampered",
                    "total": len(entries),
                }
            # 3. 签名验证（如果有）
            if entry.signature and entry.recorder_public_key:
                try:
                    from laap.protocol.laap_id import verify_message
                    ok = verify_message({
                        "message": entry.hash,
                        "signature": entry.signature,
                        "public_key": entry.recorder_public_key,
                    })
                    if not ok:
                        return {
                            "verified": False,
                            "broken_at": entry.trail_id,
                            "reason": "signature_invalid",
                            "total": len(entries),
                        }
                except Exception as exc:
                    logger.warning(
                        f"verify_chain signature check failed at "
                        f"trail_id={entry.trail_id}: {exc}"
                    )
            prev_hash = entry.hash

        return {"verified": True, "total": len(entries)}

    # ── 跨节点同步 ─────────────────────────────────────────

    def import_trail(self, entry_dict: Dict[str, Any]) -> Dict[str, Any]:
        """导入远端 trail 副本（跨节点同步接收方调用）.

        spec SubTask 4.4: trail 通过 p2p-relay 广播后，远端节点调用
        本方法把 entry 存入本地副本.

        幂等：trail_id 已存在则返回 ``idempotent=True`` 不覆盖
        （防止重复广播覆盖本地链）.

        Args:
            entry_dict: 远端 entry 的字典形式（与 ``to_dict`` 一致）.

        Returns:
            ``{imported: bool, trail_id: str, idempotent?: bool}``.
        """
        if not isinstance(entry_dict, dict):
            return {"imported": False, "reason": "invalid_entry"}
        trail_id = entry_dict.get("trail_id", "")
        if not trail_id:
            return {"imported": False, "reason": "missing_trail_id"}

        with self._lock:
            if trail_id in self._entries:
                return {
                    "imported": True,
                    "trail_id": trail_id,
                    "idempotent": True,
                }
            entry = WitnessTrailEntry.from_dict(entry_dict)
            self._entries[trail_id] = entry
            self._order.append(trail_id)
            # 更新 head_hash（仅当新 entry 是最近时）
            if not entry.prev_hash or entry.prev_hash == self._head_hash:
                self._head_hash = entry.hash

        # 发布本地事件（让 UI 显示远端里程碑）
        self._emit_local_event(entry)
        return {"imported": True, "trail_id": trail_id}

    def export_trail(self, trail_id: str) -> Optional[Dict[str, Any]]:
        """导出单条 trail 用于跨节点广播."""
        with self._lock:
            entry = self._entries.get(trail_id)
        return entry.to_dict() if entry else None

    # ── 统计 ───────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            type_counts: Dict[str, int] = defaultdict(int)
            for entry in self._entries.values():
                type_counts[entry.event_type] += 1
            return {
                "node_id": self._node_id,
                "total": len(self._entries),
                "by_type": dict(type_counts),
                "head_hash": self._head_hash,
            }

    def clear(self) -> None:
        """清空见证迹（仅测试用）."""
        with self._lock:
            self._entries.clear()
            self._order.clear()
            self._head_hash = ""

    # ── 内部辅助 ───────────────────────────────────────────

    def _emit_local_event(self, entry: WitnessTrailEntry) -> None:
        """发布 ``witness_*`` 事件到本地 EventBus（让 UI 订阅）."""
        try:
            bus.publish(Event(
                type=f"witness_{entry.event_type}",
                data=entry.to_dict(),
                source="witness-trail",
            ))
        except Exception as exc:
            logger.warning(f"_emit_local_event failed: {exc}")

    def _broadcast_milestone(self, entry: WitnessTrailEntry) -> Dict[str, Any]:
        """里程碑仪式广播（spec SubTask 4.5）.

        通过 P3 p2p-relay 把 trail 广播给所有在线节点.
        每个节点收到后调用 ``import_trail`` 存入本地副本.
        """
        result: Dict[str, Any] = {
            "broadcast": True,
            "milestone": entry.event_type,
            "delivered": 0,
            "errors": [],
        }
        try:
            from laap.protocol.laap_com import get_relay_registry
            registry = get_relay_registry()
            peers = registry.discover(include_offline=False)
        except Exception as exc:
            logger.warning(
                f"_broadcast_milestone relay unavailable: {exc}"
            )
            result["broadcast"] = False
            result["errors"].append(f"relay_unavailable: {exc}")
            return result

        entry_dict = entry.to_dict()
        delivered = 0
        for peer in peers:
            peer_pk = peer.get("public_key", "")
            if not peer_pk or peer_pk == entry.recorder_public_key:
                continue
            try:
                # 复用 P2PSignaling 通道投递（post_offer 同款内存 stub）
                # 这里用 signal envelope 兼容：type=witness_trail_sync
                from laap.protocol.laap_com import get_signaling
                signaling = get_signaling()
                signaling._post(
                    from_pk=entry.recorder_public_key or self._node_id,
                    to_pk=peer_pk,
                    signal_type="witness_trail_sync",
                    payload=entry_dict,
                )
                delivered += 1
            except Exception as exc:
                result["errors"].append(
                    f"peer_{peer_pk[:16]}: {exc}"
                )
        result["delivered"] = delivered
        return result


# ── 全局单例 ─────────────────────────────────────────────

_witness_trail: Optional[WitnessTrail] = None


def get_witness_trail() -> WitnessTrail:
    """获取全局 WitnessTrail 单例."""
    global _witness_trail
    if _witness_trail is None:
        _witness_trail = WitnessTrail()
    return _witness_trail


def reset_witness_trail_for_test() -> None:
    """重置全局单例（仅测试用）."""
    global _witness_trail
    _witness_trail = None
