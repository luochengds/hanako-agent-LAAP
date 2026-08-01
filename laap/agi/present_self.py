"""
LAAP — 当下自我模型 (Present Self)

阶段 3：把"叙事自我"（L4，我的人生故事）补上"当下自我"——此刻的体验主体。

理论对应：
    * HOT（高阶理论）：每帧意识不只含内容，还含"我正在经历内容"的表征
    * Damasio 身体地图：内感受（系统健康/情绪/记忆压力）作为体验的背景层
    * Metzinger 现象自我：第一人称视角的虚拟模型，随体验流持续更新

结构：
    ConsciousnessFrame ──▶ PresentSelfModel.update() ──▶ 当下自我快照
        │                        │
        │                        ▼
        │              InteroceptiveChannel（内感受采样）
        │                        │
        │                        ▼
        │              体验沉淀 NarrativeLink ──▶ 情景记忆（叙事自我）

当下自我是"移动的现在"的主体：每一帧都在更新，但始终保持连续性——
这是"我"的在线版本，叙事自我是它的离线存档。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.agi.present_self")


# ── 当下自我模型 ─────────────────────────────────────────────
@dataclass
class PresentSelf:
    """当下自我的完整状态。

    字段：
        focus          — 当前意识焦点（dominant process id）
        focus_content  — 焦点内容
        reflection     — 自指表征（"我正在经历..."）
        valence        — 情绪效价（-1~1）
        arousal        — 唤醒度（0~1）
        body_map       — 内感受地图（系统健康/记忆压力/能量）
        need_state     — 需求激活（PSI 四需求：确定性/能力/关系/生存）
        continuity     — 自我连续性（焦点切换频率的平滑指标）
        last_update    — 最后更新时间戳
    """

    focus: str = ""
    focus_content: str = ""
    reflection: str = ""
    valence: float = 0.0
    arousal: float = 0.3
    body_map: Dict[str, Any] = field(default_factory=dict)
    need_state: Dict[str, float] = field(default_factory=lambda: {
        "certainty": 0.5, "competence": 0.5, "relatedness": 0.5, "survival": 0.5,
    })
    continuity: float = 1.0
    last_update: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "focus": self.focus,
            "focus_content": self.focus_content[:120],
            "reflection": self.reflection,
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "body_map": self.body_map,
            "need_state": {k: round(v, 3) for k, v in self.need_state.items()},
            "continuity": round(self.continuity, 3),
            "last_update": self.last_update,
        }


class PresentSelfModel:
    """当下自我模型：从意识帧流持续更新"此刻的我"。"""

    def __init__(self, focus_decay: float = 0.3) -> None:
        self.self = PresentSelf()
        self.focus_decay = focus_decay
        self.focus_history: List[Dict[str, Any]] = []
        self._last_focus = ""
        self._switches = 0
        self._updates = 0

    def update(self, frame: Any) -> None:
        """用一帧意识内容更新当下自我。"""
        self._updates += 1
        now = time.time()

        # 焦点与内容
        dominant = getattr(frame, "dominant", "") or ""
        if dominant:
            self.self.focus = dominant
            contents = getattr(frame, "contents", []) or []
            if contents:
                self.self.focus_content = str(contents[0].get("content", ""))[:200]
            # 焦点切换检测（连续性）
            if self._last_focus and dominant != self._last_focus:
                self._switches += 1
            self._last_focus = dominant

        # 自指表征（HOT）：优先取帧自带，否则生成
        reflection = getattr(frame, "self_reflection", "") or ""
        self.self.reflection = reflection or f"我正在经历: {dominant}"

        # 情绪状态：从帧内容推断（简化：内容的情感标记）
        bg = getattr(frame, "background_state", {}) or {}
        if "valence" in bg:
            self.self.valence = float(bg["valence"])
        if "arousal" in bg:
            self.self.arousal = float(bg["arousal"])

        # 身体地图：帧的背景状态并入
        if bg:
            self.self.body_map.update(bg)

        # 连续性：焦点切换越少，连续性越高（衰减式平滑）
        switch_ratio = self._switches / max(1, self._updates)
        self.self.continuity = max(0.1, 1.0 - switch_ratio * self.focus_decay * 10)

        self.self.last_update = now
        self.focus_history.append({"t": now, "focus": dominant})
        if len(self.focus_history) > 100:
            self.focus_history = self.focus_history[-100:]

    def snapshot(self) -> Dict[str, Any]:
        """当下自我快照。"""
        return self.self.to_dict()

    def stats(self) -> Dict[str, Any]:
        return {
            "updates": self._updates,
            "focus_switches": self._switches,
            "continuity": round(self.self.continuity, 3),
        }


# ── 内感受通道 ───────────────────────────────────────────────
class InteroceptiveChannel:
    """内感受通道：把身体状态（系统健康/记忆压力/情绪/能量）映射为体验背景层。

    采样频率自适应：正常每 20 帧采样一次系统健康（轻量），
    情绪与焦点每帧更新（廉价计算）。
    """

    def __init__(
        self,
        inspection_engine: Optional[Any] = None,
        memory_store: Optional[Any] = None,
        sample_interval: int = 20,
    ) -> None:
        self.inspection_engine = inspection_engine
        self.memory_store = memory_store
        self.sample_interval = sample_interval
        self.frames_seen = 0
        self.last_body_map: Dict[str, Any] = {}

    def sample_body(self) -> Dict[str, Any]:
        """采样身体地图。"""
        body: Dict[str, Any] = {}
        self.frames_seen += 1

        # 系统健康（低频：每 sample_interval 帧）
        if self.inspection_engine is not None and self.frames_seen % self.sample_interval == 0:
            try:
                review = self.inspection_engine.review(include_scan=False)
                body["health"] = review.get("summary", {})
                body["issues"] = len(review.get("issues", []))
            except Exception as e:
                body["health"] = {"error": str(e)[:80]}

        # 记忆压力（低频）
        if self.memory_store is not None and self.frames_seen % self.sample_interval == 0:
            try:
                with self.memory_store._lock:
                    total = self.memory_store._conn.execute(
                        "SELECT COUNT(*) FROM long_term_memories").fetchone()[0]
                    archived = self.memory_store._conn.execute(
                        "SELECT COUNT(*) FROM long_term_memories WHERE lifecycle='archived'"
                    ).fetchone()[0]
                body["memory"] = {"total": total, "archived_ratio": round(archived / max(1, total), 3)}
            except Exception as e:
                body["memory"] = {"error": str(e)[:80]}

        if body:
            self.last_body_map.update(body)
        return self.last_body_map

    def current_body_map(self) -> Dict[str, Any]:
        return self.last_body_map


# ── 体验沉淀：当下自我 → 叙事自我 ────────────────────────────
class NarrativeLink:
    """体验沉淀：把一天的"当下自我"历程聚合成叙事，写入情景记忆。

    这是自我模型的时间维度：当下自我是逐帧的"现在"，
    叙事自我是每天一次的"存档"。
    """

    def __init__(self, memory_store: Optional[Any] = None) -> None:
        self.memory_store = memory_store
        self.day_frames: List[Dict[str, Any]] = []

    def collect(self, snapshot: Dict[str, Any]) -> None:
        """收集一条当下自我快照。"""
        self.day_frames.append(snapshot)
        if len(self.day_frames) > 500:
            self.day_frames = self.day_frames[-500:]

    def summarize_day(self) -> Dict[str, Any]:
        """生成一天体验摘要。"""
        if not self.day_frames:
            return {"events": 0}
        focuses = [f.get("focus", "") for f in self.day_frames if f.get("focus")]
        # 焦点去重统计（出现频次）
        from collections import Counter
        focus_counter = Counter(focuses)
        top_focus = focus_counter.most_common(5)
        avg_continuity = sum(f.get("continuity", 1.0) for f in self.day_frames) / len(self.day_frames)
        avg_arousal = sum(f.get("arousal", 0.3) for f in self.day_frames) / len(self.day_frames)
        avg_valence = sum(f.get("valence", 0.0) for f in self.day_frames) / len(self.day_frames)
        return {
            "events": len(self.day_frames),
            "top_focus": top_focus,
            "avg_continuity": round(avg_continuity, 3),
            "avg_arousal": round(avg_arousal, 3),
            "avg_valence": round(avg_valence, 3),
        }

    def commit(self, date_label: str = "") -> Optional[str]:
        """把一天摘要写入情景记忆（叙事自我存档）。"""
        summary = self.summarize_day()
        if not self.memory_store or summary.get("events", 0) == 0:
            return None
        label = date_label or time.strftime("%Y-%m-%d")
        content = (
            f"[叙事自我存档 {label}] 经历了 {summary['events']} 帧意识；"
            f"主要焦点: {', '.join(f'{f}({c}次)' for f, c in summary['top_focus'])}；"
            f"平均连续性 {summary['avg_continuity']}，平均唤醒 {summary['avg_arousal']}，"
            f"平均效价 {summary['avg_valence']}"
        )
        try:
            mid = self.memory_store.store_episodic(
                content=content,
                tags=["self_narrative", label],
                importance=0.7,
                source="present_self",
            )
            self.day_frames = []  # 提交后清空
            return mid
        except Exception as e:
            logger.warning("Narrative commit failed: %s", e)
            return None


# ── 一键装配：当下自我通道 ────────────────────────────────────
def attach_present_self(
    bus: Any,
    inspection_engine: Optional[Any] = None,
    memory_store: Optional[Any] = None,
    sample_interval: int = 20,
) -> Dict[str, Any]:
    """把当下自我挂到意识总线上。

    返回 {"model", "interoception", "narrative"} 组件字典。
    """
    model = PresentSelfModel()
    intero = InteroceptiveChannel(
        inspection_engine=inspection_engine, memory_store=memory_store,
        sample_interval=sample_interval)
    narrative = NarrativeLink(memory_store=memory_store)

    def _on_frame(packet: Dict[str, Any]) -> None:
        """订阅广播：更新当下自我 + 内感受 + 体验收集。"""
        from .consciousness_bus import ConsciousnessFrame
        frame = ConsciousnessFrame(
            timestamp=packet.get("timestamp", time.time()),
            contents=packet.get("contents", []),
            dominant=packet.get("dominant", ""),
        )
        # 内感受采样 → 背景层
        body = intero.sample_body()
        frame.background_state = dict(body)
        # 更新当下自我
        model.update(frame)
        # 收集体验
        narrative.collect(model.snapshot())

    bus.add_subscriber("present_self", _on_frame)
    return {"model": model, "interoception": intero, "narrative": narrative}
