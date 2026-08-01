"""LAAP Sandbox Colony 事件总线

ColonyEventBus 是跨沙箱通信的核心组件，支持订阅/发布、
事件路由、资源请求/批准流程。所有 CognitiveSandbox 共享一个实例，
通过事件机制实现松耦合协作。

线程安全：使用 threading.RLock 保护订阅者列表与历史记录。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from ._types import ColonyEvent, SandboxID

logger = logging.getLogger("laap.sandbox.colony")

__all__ = ["ColonyEventType", "ColonyEventBus"]


class ColonyEventType:
    """标准事件类型常量"""

    SHARED_FACT = "shared_fact"
    RESOURCE_REQUEST = "resource_request"
    RESOURCE_APPROVED = "resource_approved"
    RESOURCE_REJECTED = "resource_rejected"
    COLONY_TASK = "colony_task"
    EXPERIENCE_PROPAGATION = "experience_propagation"
    HEARTBEAT = "heartbeat"


class ColonyEventBus:
    """跨沙箱事件总线——支持订阅/发布、事件路由、资源请求/批准流程。

    所有 CognitiveSandbox 共享一个 ColonyEventBus 实例，
    通过事件机制实现松耦合协作。

    线程安全：使用 threading.Lock 保护订阅者列表与历史记录。
    """

    MAX_HISTORY = 500

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[ColonyEvent], None]]] = {}
        self._wildcard_subscribers: List[Callable[[ColonyEvent], None]] = []
        self._sandbox_filters: Dict[SandboxID, Set[str]] = {}
        self._event_history: List[ColonyEvent] = []
        self._resource_requests: Dict[str, ColonyEvent] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, callback: Callable[[ColonyEvent], None]) -> None:
        """订阅特定类型事件。event_type='*' 订阅所有事件。"""
        with self._lock:
            if event_type == "*":
                if callback not in self._wildcard_subscribers:
                    self._wildcard_subscribers.append(callback)
            else:
                if event_type not in self._subscribers:
                    self._subscribers[event_type] = []
                if callback not in self._subscribers[event_type]:
                    self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable[[ColonyEvent], None]) -> bool:
        """取消订阅。返回是否成功找到并移除。"""
        with self._lock:
            if event_type == "*":
                if callback in self._wildcard_subscribers:
                    self._wildcard_subscribers.remove(callback)
                    return True
                return False
            else:
                if event_type in self._subscribers and callback in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(callback)
                    return True
                return False

    def register_sandbox_filter(self, sandbox_id: str, allowed_types: List[str]) -> None:
        """为沙箱注册事件过滤白名单。"""
        with self._lock:
            self._sandbox_filters[sandbox_id] = set(allowed_types)

    def _check_filter(self, sandbox_id: Optional[str], event_type: str) -> bool:
        """检查沙箱是否允许接收该事件类型。"""
        if sandbox_id is None:
            return True
        if sandbox_id not in self._sandbox_filters:
            return True
        return event_type in self._sandbox_filters[sandbox_id]

    def publish(self, event: ColonyEvent) -> int:
        """发布事件。返回送达的订阅者数量。

        路由规则：
        1. 如果 event.target_sandbox 指定 → 只投递给该沙箱（且需在白名单内）
        2. 如果 target_sandbox 为 None → 广播给所有订阅者（但被白名单过滤）
        3. 调用所有匹配的回调
        4. 记录到 _event_history
        """
        delivered = 0
        callbacks_to_invoke: List[Callable[[ColonyEvent], None]] = []

        with self._lock:
            if event.target_sandbox is not None:
                if event.event_type in self._subscribers:
                    for cb in self._subscribers[event.event_type]:
                        sandbox_id = getattr(cb, "_sandbox_id", None)
                        if sandbox_id == event.target_sandbox:
                            if self._check_filter(sandbox_id, event.event_type):
                                callbacks_to_invoke.append(cb)
                for cb in self._wildcard_subscribers:
                    sandbox_id = getattr(cb, "_sandbox_id", None)
                    if sandbox_id == event.target_sandbox:
                        if self._check_filter(sandbox_id, event.event_type):
                            callbacks_to_invoke.append(cb)
            else:
                if event.event_type in self._subscribers:
                    for cb in self._subscribers[event.event_type]:
                        sandbox_id = getattr(cb, "_sandbox_id", None)
                        if self._check_filter(sandbox_id, event.event_type):
                            callbacks_to_invoke.append(cb)
                for cb in self._wildcard_subscribers:
                    sandbox_id = getattr(cb, "_sandbox_id", None)
                    if self._check_filter(sandbox_id, event.event_type):
                        callbacks_to_invoke.append(cb)

            self._event_history.append(event)
            if len(self._event_history) > self.MAX_HISTORY:
                self._event_history.pop(0)

        for cb in callbacks_to_invoke:
            try:
                delivered += 1
                cb(event)
            except Exception:
                logger.exception(f"Exception in event callback for {event.event_type}")

        return delivered

    def request_resource(self, source_sandbox: str, resource_type: str, amount: int, reason: str = "") -> str:
        """发起资源请求。返回 event_id（用于查询结果）。

        生成 RESOURCE_REQUEST 事件并广播，
        保存到 _resource_requests 等待批准。
        """
        event = ColonyEvent(
            event_type=ColonyEventType.RESOURCE_REQUEST,
            source_sandbox=source_sandbox,
            payload={
                "resource_type": resource_type,
                "amount": amount,
                "reason": reason,
            },
        )
        with self._lock:
            self._resource_requests[event.event_id] = event
        self.publish(event)
        return event.event_id

    def approve_resource(self, request_event_id: str, approver_sandbox: str = "coordinator") -> bool:
        """批准资源请求。返回是否成功（事件存在且未处理）。"""
        with self._lock:
            if request_event_id not in self._resource_requests:
                return False
            request_event = self._resource_requests.pop(request_event_id)

        approved_event = ColonyEvent(
            event_type=ColonyEventType.RESOURCE_APPROVED,
            source_sandbox=approver_sandbox,
            target_sandbox=request_event.source_sandbox,
            payload=request_event.payload,
        )
        self.publish(approved_event)
        return True

    def reject_resource(self, request_event_id: str, approver_sandbox: str = "coordinator", reason: str = "") -> bool:
        """拒绝资源请求。"""
        with self._lock:
            if request_event_id not in self._resource_requests:
                return False
            request_event = self._resource_requests.pop(request_event_id)

        rejected_event = ColonyEvent(
            event_type=ColonyEventType.RESOURCE_REJECTED,
            source_sandbox=approver_sandbox,
            target_sandbox=request_event.source_sandbox,
            payload={**request_event.payload, "reject_reason": reason},
        )
        self.publish(rejected_event)
        return True

    def get_pending_requests(self) -> List[ColonyEvent]:
        """获取所有待批准的资源请求。"""
        with self._lock:
            return list(self._resource_requests.values())

    def get_history(self, event_type: Optional[str] = None, source_sandbox: Optional[str] = None, limit: int = 50) -> List[ColonyEvent]:
        """查询事件历史。"""
        with self._lock:
            result = self._event_history[:]
            if event_type is not None:
                result = [e for e in result if e.event_type == event_type]
            if source_sandbox is not None:
                result = [e for e in result if e.source_sandbox == source_sandbox]
            return result[-limit:]

    def stats(self) -> Dict[str, Any]:
        """返回统计信息。"""
        with self._lock:
            return {
                "total_subscribers": sum(len(callbacks) for callbacks in self._subscribers.values()),
                "wildcard_subscribers": len(self._wildcard_subscribers),
                "event_types": len(self._subscribers),
                "total_events": len(self._event_history),
                "pending_requests": len(self._resource_requests),
                "sandboxes_with_filters": len(self._sandbox_filters),
            }