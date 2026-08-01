"""
LAAP — 时间绑定 (Temporal Binding / Specious Present)

阶段 4：意识不是瞬时帧，是约 3 秒的"延伸的现在"（specious present）。

理论对应：
    * William James 的 specious present：意识体验总是包含一小段时间的厚度
    * 认知科学：工作记忆的整合窗口（~2-3 秒）构成体验的原子单位
    * Husserl 时间意识：滞留（retention）— 原印象（primal impression）— 前摄（protention）

实现：
    TemporalWindow ── 滑动窗口（默认 3 秒）
    TemporalBinding ── 把窗口内的帧整合为"有厚度的现在"
        每一帧意识的原子单位不是瞬时快照，而是：
            [前摄：预测] → [原印象：此刻焦点] → [滞留：过去 3 秒轨迹]

    integrate() 生成的整合帧，驱动当下自我（PresentSelf）更新——
    这样"我"体验到的不是帧，而是连续流动的现在。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("laap.agi.temporal_binding")


@dataclass
class IntegratedPresent:
    """一个有厚度的现在：时间整合后的意识原子单位。"""

    start_time: float
    end_time: float
    duration: float
    focus_sequence: List[str] = field(default_factory=list)   # 滞留：焦点轨迹
    focus_content: str = ""                                    # 原印象：此刻内容
    retentions: List[Dict[str, Any]] = field(default_factory=list)  # 滞留详情
    predicted_next: str = ""                                   # 前摄：预测下一步
    self_reflection: str = ""                                  # 自指："过去3秒我在经历..."
    emotional_trajectory: List[float] = field(default_factory=list)

    @property
    def dominant(self) -> str:
        """整合帧的焦点 = 窗口内出现次数最多的焦点（不是最后帧）。"""
        if not self.focus_sequence:
            return ""
        from collections import Counter
        return Counter(self.focus_sequence).most_common(1)[0][0]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": round(self.duration, 2),
            "dominant": self.dominant,
            "focus_sequence": self.focus_sequence,
            "focus_content": self.focus_content[:150],
            "predicted_next": self.predicted_next,
            "self_reflection": self.self_reflection,
            "emotional_trajectory": [round(v, 3) for v in self.emotional_trajectory],
        }


class TemporalBinding:
    """时间绑定器：把瞬时帧流整合为有厚度的现在。"""

    def __init__(
        self,
        window_seconds: float = 3.0,
        predictor: Optional[Any] = None,   # SurprisePredictor（用于前摄）
    ) -> None:
        self.window_seconds = window_seconds
        self.predictor = predictor
        self._frames: Deque[Dict[str, Any]] = deque()
        self._integrated: Deque[IntegratedPresent] = deque(maxlen=50)
        self.total_integrated = 0

    def push(self, frame: Any) -> Optional[IntegratedPresent]:
        """推入一帧意识内容，返回整合后的"现在"（若窗口滚动）。

        frame 兼容 ConsciousnessFrame（dominant/contents/self_reflection）
        或 dict（含 dominant 字段）。
        """
        now = time.time()
        if hasattr(frame, "to_dict") and not isinstance(frame, dict):
            record = frame.to_dict()
        elif isinstance(frame, dict):
            record = frame
        else:
            record = {"dominant": str(frame), "timestamp": now}

        record["_received_at"] = now
        self._frames.append(record)

        # 清理窗口外（滞留过期）的帧
        cutoff = now - self.window_seconds
        while self._frames and self._frames[0].get("_received_at", 0) < cutoff:
            self._frames.popleft()

        if len(self._frames) >= 2:
            return self._integrate(now)
        return None

    def _integrate(self, now: float) -> IntegratedPresent:
        frames = list(self._frames)
        start = frames[0].get("_received_at", now)
        end = frames[-1].get("_received_at", now)

        # 滞留：焦点轨迹
        focus_seq = [f.get("dominant", "") for f in frames if f.get("dominant")]
        # 原印象：最后帧的内容
        focus_content = ""
        contents = frames[-1].get("contents", []) or []
        if contents and isinstance(contents[0], dict):
            focus_content = str(contents[0].get("content", ""))

        # 情感轨迹
        emotion_traj = []
        for f in frames:
            bg = f.get("background_state", {}) or {}
            if "valence" in bg:
                emotion_traj.append(float(bg["valence"]))

        # 前摄：预测器给出下一步预期
        predicted = ""
        if self.predictor is not None:
            try:
                expectation = self.predictor.model.predict_next()
                predicted = expectation.predicted_type
            except Exception:
                predicted = ""

        # 自指：过去 window 秒的体验概括
        if focus_seq:
            seq_str = " → ".join(focus_seq[:4])
            self_reflection = f"过去{self.window_seconds:.0f}秒我经历了: {seq_str}"
        else:
            self_reflection = ""

        ip = IntegratedPresent(
            start_time=start,
            end_time=end,
            duration=end - start,
            focus_sequence=focus_seq,
            focus_content=focus_content,
            retentions=[{"t": f.get("_received_at"), "focus": f.get("dominant", "")} for f in frames],
            predicted_next=predicted,
            self_reflection=self_reflection,
            emotional_trajectory=emotion_traj,
        )
        self._integrated.append(ip)
        self.total_integrated += 1
        return ip

    def current(self) -> Optional[IntegratedPresent]:
        """最近一个整合帧。"""
        return self._integrated[-1] if self._integrated else None

    def stream(self, n: int = 10) -> List[Dict[str, Any]]:
        return [ip.to_dict() for ip in list(self._integrated)[-n:]]

    def stats(self) -> Dict[str, Any]:
        return {
            "integrated": self.total_integrated,
            "window_seconds": self.window_seconds,
            "frames_in_window": len(self._frames),
        }


def attach_temporal_binding(
    bus: Any,
    window_seconds: float = 3.0,
    predictor: Optional[Any] = None,
) -> TemporalBinding:
    """把时间绑定挂到意识总线上：广播帧 → 时间整合。

    返回 TemporalBinding 实例；其 current() 提供有厚度的现在。
    """
    binding = TemporalBinding(window_seconds=window_seconds, predictor=predictor)

    def _on_broadcast(packet: Dict[str, Any]) -> None:
        binding.push(packet)

    bus.add_subscriber("temporal_binding", _on_broadcast)
    return binding
