"""
LAAP — 输入流预测引擎 (SurprisePredictor)

自由能原理的工程化：认知系统不是被动响应输入，而是持续预测
"下一个会发生什么"，并用预测误差（惊奇）驱动注意力。

    输入事件 ──▶ ExpectationModel（马尔可夫类型转移 + 内容期望）
                    │
                    ▼
              surprise = w₁·type_error + w₂·content_error
                    │
                    ▼
        SurpriseChannel → GWS 注册高显著性进程（意外抢占注意力）
                    │
                    ▼
        夜间校准：surprise 序列统计 → 夜间周期复盘

设计原则：
    * 零重依赖：内容相似度用 Jaccard（token 集合），不依赖 embedder API
    * 纯本地可测：马尔可夫链 + 集合运算，确定性输出
    * 可观测：全部 surprise 记录可回放
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("laap.agi.predictor")


# ── 事件与期望 ───────────────────────────────────────────────
@dataclass
class InputEvent:
    """一个输入事件（感知通道的原子单位）。"""

    event_type: str
    content: str
    timestamp: float = field(default_factory=time.time)
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"event_type": self.event_type, "content": self.content,
                "timestamp": self.timestamp, "source": self.source}


@dataclass
class Expectation:
    """对下一个事件的预测。"""

    predicted_type: str = ""
    type_probability: float = 0.0
    expected_keywords: set = field(default_factory=set)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_type": self.predicted_type,
            "type_probability": round(self.type_probability, 3),
            "confidence": round(self.confidence, 3),
        }


def _tokenize(content: str) -> set:
    """轻量分词：字母数字 token + 中文单字。"""
    import re
    toks = set(re.findall(r"[a-zA-Z0-9_]+", content.lower()))
    cjk = set(re.findall(r"[\u4e00-\u9fff]", content))
    return toks | cjk


def jaccard(a: set, b: set) -> float:
    """Jaccard 相似度（0~1）。"""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


class ExpectationModel:
    """轻量期望模型：类型马尔可夫链 + 内容关键词期望。"""

    def __init__(self, max_history: int = 50) -> None:
        self.max_history = max_history
        self.history: Deque[InputEvent] = deque(maxlen=max_history)
        # 类型转移计数：current_type -> Counter(next_type)
        self.transitions: Dict[str, Counter] = defaultdict(Counter)
        self.type_counts: Counter = Counter()

    def predict_next(self) -> Expectation:
        """预测下一个事件。"""
        if not self.history:
            return Expectation(confidence=0.0)

        current_type = self.history[-1].event_type
        trans = self.transitions.get(current_type, Counter())
        if trans:
            predicted_type, prob = trans.most_common(1)[0]
            total = sum(trans.values())
            type_prob = prob / total
        else:
            # 无转移数据：回退到类型频率
            predicted_type, freq = self.type_counts.most_common(1)[0]
            type_prob = freq / sum(self.type_counts.values())

        # 内容期望：最近 10 条的关键词并集（带衰减权重——简单起见取最近）
        recent = list(self.history)[-10:]
        expected_keywords: set = set()
        for ev in recent:
            expected_keywords |= _tokenize(ev.content)

        confidence = min(1.0, 0.3 + 0.5 * len(self.history) / 10.0)
        return Expectation(
            predicted_type=predicted_type,
            type_probability=type_prob,
            expected_keywords=expected_keywords,
            confidence=confidence,
        )

    def update(self, event: InputEvent) -> None:
        """吸收一个事件，更新转移矩阵与历史。"""
        if self.history:
            prev_type = self.history[-1].event_type
            self.transitions[prev_type][event.event_type] += 1
        self.type_counts[event.event_type] += 1
        self.history.append(event)

    def stats(self) -> Dict[str, Any]:
        return {
            "history": len(self.history),
            "types": dict(self.type_counts),
        }


class SurprisePredictor:
    """惊奇预测器：预测 → 误差 → surprise。"""

    def __init__(
        self,
        model: Optional[ExpectationModel] = None,
        type_weight: float = 0.4,
        content_weight: float = 0.6,
    ) -> None:
        self.model = model or ExpectationModel()
        self.type_weight = type_weight
        self.content_weight = content_weight
        self.surprise_history: Deque[Dict[str, Any]] = deque(maxlen=200)
        self.total_surprise = 0.0
        self.event_count = 0

    def observe(self, event: InputEvent) -> float:
        """观察一个事件，返回 surprise（0~1）。

        surprise = w₁·(1 - P(实际类型)) + w₂·(1 - Jaccard(内容, 期望))
        """
        expectation = self.model.predict_next()
        if not self.model.history:
            # 无历史：世界完全未知，类型无法预测 = 最大意外
            type_error = 1.0
            content_error = 0.5
        else:
            type_error = 0.0
            content_error = 0.5  # 占位，下面覆盖

            # 类型误差：1 - 转移概率（回退到类型频率）
            trans = self.model.transitions.get(self.model.history[-1].event_type, Counter())
            if trans:
                total = sum(trans.values())
                p = trans.get(event.event_type, 0) / total
            else:
                total = sum(self.model.type_counts.values())
                p = self.model.type_counts.get(event.event_type, 0) / total
            type_error = 1.0 - p

            # 内容误差：1 - Jaccard(实际内容, 期望关键词)
            actual_toks = _tokenize(event.content)
            content_error = 1.0 - jaccard(actual_toks, expectation.expected_keywords)

        surprise = self.type_weight * type_error + self.content_weight * content_error
        surprise = max(0.0, min(1.0, surprise))

        # 记录 + 更新模型
        self.surprise_history.append({
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "surprise": round(surprise, 3),
            "type_error": round(type_error, 3),
            "content_error": round(content_error, 3),
            "predicted": expectation.predicted_type,
        })
        self.total_surprise += surprise
        self.event_count += 1
        self.model.update(event)
        return surprise

    def recent_surprise(self, n: int = 10) -> float:
        """最近 n 条的平均惊奇（供显著性调制）。"""
        recent = list(self.surprise_history)[-n:]
        if not recent:
            return 0.0
        return sum(r["surprise"] for r in recent) / len(recent)

    def stats(self) -> Dict[str, Any]:
        avg = self.total_surprise / self.event_count if self.event_count else 0.0
        return {
            "events": self.event_count,
            "avg_surprise": round(avg, 3),
            "recent_surprise": round(self.recent_surprise(), 3),
            "model": self.model.stats(),
        }


# ── 惊奇通道：接入全局工作空间 ───────────────────────────────
class SurpriseChannel:
    """把高惊奇事件注册为 GWS 高显著性进程（意外抢占注意力）。"""

    def __init__(
        self,
        predictor: SurprisePredictor,
        surprise_boost: float = 0.8,   # 惊奇对显著性的放大系数
        boost_threshold: float = 0.5,  # 超过此值的惊奇才触发抢占
    ) -> None:
        self.predictor = predictor
        self.surprise_boost = surprise_boost
        self.boost_threshold = boost_threshold
        self.boosted_count = 0

    def feed(
        self,
        event: InputEvent,
        workspace: Any,
        base_activation: float = 0.5,
        base_salience: float = 0.5,
    ) -> float:
        """喂入事件：计算惊奇，若超过阈值则注册抢占进程。

        返回 surprise 值。
        """
        surprise = self.predictor.observe(event)
        if surprise >= self.boost_threshold:
            try:
                from laap.agi.gw_workspace import CoalitionalProcess, ProcessType
                boosted_salience = min(1.0, base_salience + surprise * self.surprise_boost)
                workspace.register_process(CoalitionalProcess(
                    process_id=f"surprise_{event.timestamp:.0f}_{event.event_type}",
                    process_type=ProcessType.PERCEPTUAL,
                    content=event.content,
                    activation=base_activation + surprise * 0.4,
                    salience=boosted_salience,
                ))
                self.boosted_count += 1
            except ImportError:
                pass
        return surprise

    def stats(self) -> Dict[str, Any]:
        return {"boosted_count": self.boosted_count,
                "predictor": self.predictor.stats()}


# ── 夜间校准：预测误差复盘 ───────────────────────────────────
def calibration_report(predictor: SurprisePredictor) -> Dict[str, Any]:
    """生成预测校准报告（供夜间周期复盘）。

    统计：平均惊奇、高惊奇事件占比、最意外的事件类型。
    """
    hist = list(predictor.surprise_history)
    if not hist:
        return {"events": 0, "avg_surprise": 0.0, "high_surprise_ratio": 0.0,
                "most_surprising_types": {}}
    avg = sum(h["surprise"] for h in hist) / len(hist)
    high = [h for h in hist if h["surprise"] >= 0.6]
    by_type = Counter(h["event_type"] for h in high)
    return {
        "events": len(hist),
        "avg_surprise": round(avg, 3),
        "high_surprise_ratio": round(len(high) / len(hist), 3),
        "most_surprising_types": dict(by_type.most_common(5)),
    }
