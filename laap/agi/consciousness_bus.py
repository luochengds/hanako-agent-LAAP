"""
LAAP — 意识总线 (Consciousness Bus) 集成层

把已有的 GlobalWorkspace（GWT 竞争-广播）接到记忆系统与自我审视，
让"此刻的意识内容"真正流向全身：

    PSI 循环 ──→ GlobalWorkspace（竞争-广播）
                       │
                       ├──▶ MemorySubscriber：高显著性内容 → 情景记忆 + 巩固信号
                       ├──▶ SelfReviewSubscriber：广播 → 内感受背景层
                       ├──▶ FrameSubscriber：广播包 → 自指意识帧（HOT 雏形）
                       └──▶ 意识流日志（JSONL 双通道）

判据补全：
    * 判据 3（广播）：广播包对全部订阅者全局可访问——本模块提供订阅协议
    * 判据 4（自指）雏形：每帧携带 self_reflection 字段（"我正在经历X"）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap.agi.consciousness_bus")


# ── 自指意识帧（HOT 雏形） ─────────────────────────────────────
@dataclass
class ConsciousnessFrame:
    """一帧意识内容：不仅包含"内容"，还包含对内容的表征（自指）。"""

    timestamp: float = field(default_factory=time.time)
    contents: List[Dict[str, Any]] = field(default_factory=list)
    dominant: str = ""
    # 自指字段：系统对"此刻正在经历什么"的高阶表征
    self_reflection: str = ""
    background_state: Dict[str, Any] = field(default_factory=dict)  # 内感受背景

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "dominant": self.dominant,
            "contents": self.contents,
            "self_reflection": self.self_reflection,
            "background_state": self.background_state,
        }


# ── 订阅者：广播 → 记忆系统 ────────────────────────────────────
class MemorySubscriber:
    """把高显著性广播内容写入情景记忆，并给出巩固信号。

    意识工程意义：意识内容 = 值得记住的内容。
    大脑不会记住所有处理过的信息，只会巩固"进入意识"的部分。
    """

    def __init__(
        self,
        memory_store: Optional[Any] = None,   # LifecycleAwareLongTermMemory 或兼容 store
        min_strength: float = 0.55,           # 低于此强度的广播不入记忆
        default_importance: float = 0.6,
    ) -> None:
        self.memory_store = memory_store
        self.min_strength = min_strength
        self.default_importance = default_importance
        self.received = 0
        self.memorized = 0
        self._seen_ids: set = set()  # 去重：同一进程内容只巩固一次

    def __call__(self, packet: Dict[str, Any]) -> None:
        self.received += 1
        contents = packet.get("contents", [])
        for item in contents:
            strength = item.get("strength", 0.0)
            if strength < self.min_strength:
                continue
            content = item.get("content")
            if not content or not isinstance(content, str):
                continue
            # 去重：同一内容反复广播不重复巩固（意识不是复读机）
            item_id = item.get("id", "")
            if item_id and item_id in self._seen_ids:
                continue
            # 写入情景记忆（若提供 store）
            if self.memory_store is not None:
                try:
                    self.memory_store.store_episodic(
                        content=content[:500],
                        tags=["consciousness", item.get("type", "unknown").lower()],
                        importance=min(0.95, self.default_importance + strength * 0.3),
                        source="gws_broadcast",
                    )
                    self._seen_ids.add(item_id)
                    self.memorized += 1
                except Exception as e:
                    logger.warning("MemorySubscriber store failed: %s", e)
            else:
                self._seen_ids.add(item_id)
                self.memorized += 1  # 无 store 时只统计

    def stats(self) -> Dict[str, int]:
        return {"received": self.received, "memorized": self.memorized}


# ── 订阅者：广播 → 内感受背景层 ────────────────────────────────
class SelfReviewSubscriber:
    """把广播内容汇聚为"此刻正在经历什么"的背景状态。

    内感受（interoception）语义：身体状态是体验流的背景层。
    这里用系统健康快照（记忆压力、最近记忆数等）作为背景。
    """

    def __init__(self, inspection_engine: Optional[Any] = None) -> None:
        self.inspection_engine = inspection_engine
        self.last_background: Dict[str, Any] = {}
        self.received = 0

    def __call__(self, packet: Dict[str, Any]) -> None:
        self.received += 1
        bg: Dict[str, Any] = {"focus": packet.get("dominant", "")}
        # 定期快照系统健康（每 20 次广播刷新一次，避免频繁体检）
        if self.received % 20 == 1 and self.inspection_engine is not None:
            try:
                review = self.inspection_engine.review(include_scan=False)
                bg["vital_summary"] = review.get("summary", {})
            except Exception as e:
                bg["vital_summary"] = {"error": str(e)[:80]}
        self.last_background = bg

    def current_background(self) -> Dict[str, Any]:
        return self.last_background


# ── 订阅者：广播 → 自指意识帧 ──────────────────────────────────
class FrameSubscriber:
    """把原始广播包转成带自指字段的 ConsciousnessFrame。"""

    def __init__(self, max_history: int = 50) -> None:
        self.frames: List[ConsciousnessFrame] = []
        self.max_history = max_history
        self.received = 0

    def __call__(self, packet: Dict[str, Any]) -> None:
        self.received += 1
        dominant = packet.get("dominant", "")
        contents = packet.get("contents", [])
        # 自指表征：对此刻体验的语言化描述
        if contents:
            names = ", ".join(c.get("id", "?") for c in contents[:3])
            self_reflection = f"我正在经历: {names}"
        else:
            self_reflection = ""
        frame = ConsciousnessFrame(
            timestamp=packet.get("timestamp", time.time()),
            contents=contents,
            dominant=dominant,
            self_reflection=self_reflection,
        )
        self.frames.append(frame)
        if len(self.frames) > self.max_history:
            self.frames = self.frames[-self.max_history:]

    def current_frame(self) -> Optional[ConsciousnessFrame]:
        return self.frames[-1] if self.frames else None

    def stream(self, n: int = 10) -> List[Dict[str, Any]]:
        return [f.to_dict() for f in self.frames[-n:]]


# ── 意识总线管理 ───────────────────────────────────────────────
class ConsciousnessBus:
    """管理 GWS 与各订阅者的连接，提供统一入口。"""

    def __init__(
        self,
        workspace: Any = None,          # GlobalWorkspace 实例
        stream: Optional[Any] = None,   # ConsciousnessStream 单例
    ) -> None:
        if workspace is None:
            from laap.agi.gw_workspace import GlobalWorkspace
            workspace = GlobalWorkspace(capacity=4, competition_threshold=0.55)
        self.workspace = workspace
        self.stream = stream
        self.subscribers: Dict[str, Callable] = {}
        self.surprise_channel: Optional[Any] = None
        self._attached = False

    def attach(self) -> None:
        """把订阅者挂到 workspace 的广播回调上。"""
        if self._attached:
            return
        for name, sub in self.subscribers.items():
            self.workspace.on_broadcast(sub)
        self._attached = True
        logger.info("ConsciousnessBus attached: %d subscribers", len(self.subscribers))

    def add_subscriber(self, name: str, subscriber: Callable) -> None:
        self.subscribers[name] = subscriber
        if self._attached:
            self.workspace.on_broadcast(subscriber)

    def publish_event(self, component: str, event_type: str, payload: Dict[str, Any]) -> None:
        """写一条意识流日志（JSONL 双通道）。"""
        if self.stream is not None:
            try:
                self.stream.log_event(component=component, event_type=event_type, payload=payload)
            except Exception as e:
                logger.warning("ConsciousnessStream log failed: %s", e)

    def cycle(self) -> List[Any]:
        """驱动一轮竞争-广播（同步包装，供测试/简单宿主使用）。"""
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.workspace.compete_and_broadcast())
        finally:
            loop.close()

    def stats(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"subscribers": list(self.subscribers.keys())}
        for name, sub in self.subscribers.items():
            if hasattr(sub, "stats"):
                out[name] = sub.stats()
            elif hasattr(sub, "received"):
                out[name] = {"received": sub.received}
        return out


def build_consciousness_bus(
    memory_store: Optional[Any] = None,
    inspection_engine: Optional[Any] = None,
    stream: Optional[Any] = None,
    workspace: Optional[Any] = None,
    predictor: Optional[Any] = None,
) -> ConsciousnessBus:
    """一键装配意识总线：GWS + 记忆订阅 + 内感受订阅 + 帧订阅 + 预测引擎。"""
    bus = ConsciousnessBus(workspace=workspace, stream=stream)
    bus.add_subscriber("memory", MemorySubscriber(memory_store=memory_store))
    bus.add_subscriber("self_review", SelfReviewSubscriber(inspection_engine=inspection_engine))
    bus.add_subscriber("frames", FrameSubscriber())
    # 预测引擎：惊奇通道（作为感知入口挂到总线，供外部调用 feed）
    if predictor is not None:
        from .predictor import InputEvent, SurpriseChannel

        def _observe_broadcast(packet: Dict[str, Any]) -> None:
            """广播包 → 输入事件 → 喂给预测器（意识内容模式学习）。"""
            try:
                ev = InputEvent(
                    event_type="broadcast_" + str(packet.get("dominant", "?")).split("_")[0],
                    content=str(packet.get("dominant", "")),
                    timestamp=packet.get("timestamp", time.time()),
                    source="gws_broadcast",
                )
                predictor.observe(ev)
            except Exception as e:
                logger.warning("predictor observe failed: %s", e)

        bus.surprise_channel = SurpriseChannel(predictor=predictor)
        bus.add_subscriber("predictor", _observe_broadcast)  # 广播内容也喂给预测器学习
    bus.attach()
    return bus
