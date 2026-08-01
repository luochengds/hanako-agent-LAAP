"""Triphase Bridge Service — 生命周期管理与 LAAP 事件总线集成。"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from laap.events.bus import EventBus, bus as global_event_bus
from laap.agi.cognitive_bus import CognitiveBus, get_bus as get_cognitive_bus

from .encoder import TextEncoder
from .memory_service import TriphaseMemoryService
from .grounding_service import TriphaseGroundingService
from .topics import TriphaseTopic

logger = logging.getLogger(__name__)


class TriphaseBridgeService:
    """Triphase 与 LAAP 之间的总线桥接服务。

    功能：
    - 持有 encoder / memory_service / grounding_service 单例
    - 订阅 CognitiveBus / EventBus 的相关事件
    - 将 triphase 结果广播到 EventBus，供 WebSocketManager 推送给前端
    - 提供手动触发接口，便于 CLI / API 调用
    """

    def __init__(
        self,
        encoder: TextEncoder | None = None,
        event_bus: EventBus | None = None,
        cognitive_bus: CognitiveBus | None = None,
        data_dir: str | None = None,
    ) -> None:
        self.encoder = encoder or TextEncoder(dim=64)
        self.event_bus = event_bus or global_event_bus
        self.cognitive_bus = cognitive_bus or get_cognitive_bus("aris")
        self.data_dir = data_dir or os.path.join(
            os.path.expanduser("~"), ".laap", "triphase"
        )
        os.makedirs(self.data_dir, exist_ok=True)

        # 子服务
        self.memory = TriphaseMemoryService(
            encoder=self.encoder,
            on_event=self._emit_event,
        )
        self.grounding = TriphaseGroundingService(
            memory_service=self.memory,
            default_domain="biomedical",
        )

        self._subscribed = False
        self._lock = threading.RLock()
        self._start_time = time.time()

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """启动 bridge，订阅总线事件。"""
        with self._lock:
            if self._subscribed:
                return
            self._subscribed = True

        self.cognitive_bus.register_module(
            "triphase_bridge",
            version="0.1.0",
            capabilities=["memory", "grounding", "pipeline"],
        )
        self.event_bus.subscribe("user.input", self._on_user_input)
        self.event_bus.subscribe("agent.output", self._on_agent_output)
        self.event_bus.subscribe("triphase.memory.store", self._on_memory_store)
        self.event_bus.subscribe("triphase.memory.retrieve", self._on_memory_retrieve)
        self.event_bus.subscribe("triphase.grounding.verify", self._on_grounding_verify)

        self._emit_event(
            TriphaseTopic.BRIDGE_STATUS,
            {"status": "started", "data_dir": self.data_dir},
        )
        logger.info("TriphaseBridgeService started")

    def stop(self) -> None:
        """停止 bridge。"""
        with self._lock:
            self._subscribed = False
        self._emit_event(
            TriphaseTopic.BRIDGE_STATUS,
            {"status": "stopped"},
        )
        logger.info("TriphaseBridgeService stopped")

    # ------------------------------------------------------------------ 事件发射

    def _emit_event(self, topic: str, payload: dict[str, Any]) -> None:
        """统一向 EventBus 发布事件。"""
        try:
            self.event_bus.publish_simple(topic, payload, source="triphase_bridge")
        except Exception as e:
            logger.warning("Triphase 事件发布失败 %s: %s", topic, e)

    # ------------------------------------------------------------------ 事件处理器

    def _on_user_input(self, event: Any) -> None:
        """用户输入时：检索相关记忆并发布抗体警告。"""
        text = event.data.get("text", "")
        if not text:
            return
        try:
            warnings = self.memory.warnings(text)
            if warnings:
                self._emit_event(
                    TriphaseTopic.GROUNDING_ANTIBODY_HIT,
                    {"query": text, "warnings": warnings},
                )
            results = self.memory.retrieve(text, top_k=3)
            self._emit_event(
                TriphaseTopic.MEMORY_RETRIEVED,
                {"query": text, "entries": results, "trigger": "user.input"},
            )
        except Exception as e:
            logger.warning("处理 user.input 失败: %s", e)

    def _on_agent_output(self, event: Any) -> None:
        """Agent 输出时：存入记忆，并在可解析为声明时执行接地验证。"""
        text = event.data.get("text", "")
        if not text:
            return
        try:
            # 简单启发：将输出作为经验记忆存储
            self.memory.store(text, payload={"source": "agent.output"})
        except Exception as e:
            logger.warning("存储 agent.output 失败: %s", e)

    def _on_memory_store(self, event: Any) -> None:
        """手动存储记忆请求。"""
        d = event.data
        text = d.get("text", "")
        if not text:
            return
        self.memory.store(
            text=text,
            payload=d.get("payload"),
            key=d.get("key"),
            initial_evidence=d.get("initial_evidence", 0.0),
            tags=d.get("tags"),
        )

    def _on_memory_retrieve(self, event: Any) -> None:
        """手动检索记忆请求。"""
        d = event.data
        query = d.get("query", "")
        if not query:
            return
        results = self.memory.retrieve(
            query,
            top_k=d.get("top_k", 5),
        )
        self._emit_event(
            TriphaseTopic.MEMORY_RETRIEVED,
            {"query": query, "entries": results, "trigger": "triphase.memory.retrieve"},
        )

    def _on_grounding_verify(self, event: Any) -> None:
        """手动接地验证请求。"""
        d = event.data
        report = self.grounding.verify(
            text=d.get("text", ""),
            domain=d.get("domain"),
            kind=d.get("kind", "fact"),
            slots=d.get("slots", {}),
        )
        self._emit_event(TriphaseTopic.GROUNDING_REPORT, report)

    # ------------------------------------------------------------------ 公共 API

    def store_memory(
        self,
        text: str,
        payload: Any = None,
        key: str | None = None,
        initial_evidence: float = 0.0,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """手动存储记忆。"""
        item = self.memory.store(
            text=text,
            payload=payload,
            key=key,
            initial_evidence=initial_evidence,
            tags=tags,
        )
        from .codec import triphase_to_dict
        return triphase_to_dict(item)

    def retrieve_memory(
        self,
        query: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """手动检索记忆。"""
        return {
            "query": query,
            "entries": self.memory.retrieve(query, top_k=top_k),
        }

    def verify(
        self,
        text: str,
        domain: str | None = None,
        kind: str = "fact",
        slots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """手动执行接地验证。"""
        return self.grounding.verify(text, domain=domain, kind=kind, slots=slots)

    def record_hallucination(
        self,
        text: str,
        kind: str = "fact",
        slots: dict[str, Any] | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]:
        """手动记录幻觉抗体。"""
        return self.grounding.record_hallucination(text, kind=kind, slots=slots, reason=reason)

    def status(self) -> dict[str, Any]:
        """返回 bridge 运行状态。"""
        return {
            "started": self._subscribed,
            "uptime": round(time.time() - self._start_time, 1),
            "memory": self.memory.stats(),
            "grounding": self.grounding.stats(),
            "data_dir": self.data_dir,
        }


# 模块级单例，便于 LAAP API / Launcher 共享同一 bridge 实例
_bridge_instance: TriphaseBridgeService | None = None


def get_bridge(
    encoder: TextEncoder | None = None,
    event_bus: EventBus | None = None,
    cognitive_bus: CognitiveBus | None = None,
) -> TriphaseBridgeService:
    """获取或创建 TriphaseBridgeService 单例。"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = TriphaseBridgeService(
            encoder=encoder,
            event_bus=event_bus,
            cognitive_bus=cognitive_bus,
        )
        _bridge_instance.start()
    return _bridge_instance


def set_bridge(bridge: TriphaseBridgeService | None) -> None:
    """手动设置 bridge 单例（测试或 launcher 注入使用）。"""
    global _bridge_instance
    _bridge_instance = bridge
