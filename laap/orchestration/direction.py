"""
LAAP Aether — Direction space toolkit

从 directional_mesh.py 提取的方向空间工具，作为 Aether 编排层的策略插件。
消除与 AgentCell/Capability/AetherMessage 的重复。

核心：
  - TaskDirectionEncoder: 任务 → 3 维方向向量 (认知功能, 响应模式, 抽象层级)
  - DirectionalCapability: 扩展 Capability，增加方向向量余弦匹配
  - Kakeya 偏置解析: P0 覆盖度缺口 → Aether 可理解的方向偏置
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

import numpy as np

logger = logging.getLogger("laap.orchestration.direction")


# ═══════════════════════════════════════════════════════════════
# 方向空间坐标系
# ═══════════════════════════════════════════════════════════════

class DirectionAxis(str, Enum):
    COGNITION = "cognition"       # -1=感知/记忆(过去), 0=推理/整合(现在), 1=预测/规划(未来)
    RESPONSE = "response"         # -1=分析/解构, 0=平衡/回应, 1=创造/综合
    ABSTRACTION = "abstraction"   # -1=具体/事实, 0=模式/结构, 1=抽象/元


DIRECTION_TEMPLATES = {
    "perceive":       np.array([-0.8, -0.3, -0.7]),
    "remember":       np.array([-0.9, -0.5, -0.3]),
    "analyze":        np.array([-0.3, -0.8,  0.0]),
    "reason":         np.array([ 0.0, -0.6,  0.5]),
    "integrate":      np.array([ 0.2,  0.0,  0.2]),
    "create":         np.array([ 0.3,  0.8,  0.5]),
    "empathize":      np.array([ 0.0,  0.5, -0.3]),
    "plan":           np.array([ 0.8,  0.2,  0.6]),
    "predict":        np.array([ 0.9, -0.1,  0.4]),
    "meta":           np.array([ 0.5, -0.2,  0.9]),
    "default":        np.array([ 0.0,  0.0,  0.0]),
}


# ═══════════════════════════════════════════════════════════════
# TaskDirectionEncoder — 任务方向编码器
# ═══════════════════════════════════════════════════════════════

class TaskDirectionEncoder:
    """
    将自然语言任务描述编码为方向空间中的 3 维向量。

    使用关键词分析将任务映射到 (认知功能, 响应模式, 抽象层级)。
    """

    KEYWORD_BIAS = {
        # 英文关键词
        "remember":    np.array([-0.6,  0.0, -0.2]),
        "recall":      np.array([-0.7, -0.1, -0.3]),
        "history":     np.array([-0.8, -0.2, -0.1]),
        "analyze":     np.array([-0.2, -0.7,  0.3]),
        "compare":     np.array([-0.3, -0.5,  0.2]),
        "logical":     np.array([ 0.0, -0.6,  0.5]),
        "cause":       np.array([-0.1, -0.5,  0.4]),
        "effect":      np.array([ 0.2, -0.4,  0.3]),
        "predict":     np.array([ 0.7,  0.0,  0.4]),
        "future":      np.array([ 0.8,  0.1,  0.3]),
        "plan":        np.array([ 0.6,  0.3,  0.5]),
        "create":      np.array([ 0.3,  0.7,  0.5]),
        "write":       np.array([ 0.2,  0.6,  0.4]),
        "design":      np.array([ 0.4,  0.6,  0.6]),
        "imagine":     np.array([ 0.2,  0.8,  0.7]),
        "feel":        np.array([ 0.0,  0.4, -0.2]),
        "empathy":     np.array([-0.1,  0.5, -0.3]),
        "think":       np.array([ 0.1, -0.3,  0.8]),
        "meta":        np.array([ 0.3, -0.2,  0.9]),
        "reflect":     np.array([-0.2,  0.1,  0.6]),
        "decide":      np.array([ 0.4, -0.3,  0.3]),
        # 中文关键词
        "分析":        np.array([-0.2, -0.7,  0.3]),
        "因果":        np.array([-0.1, -0.5,  0.4]),
        "原因":        np.array([-0.1, -0.4,  0.2]),
        "结果":        np.array([ 0.2, -0.3,  0.1]),
        "预测":        np.array([ 0.7,  0.0,  0.4]),
        "未来":        np.array([ 0.8,  0.1,  0.3]),
        "规划":        np.array([ 0.6,  0.3,  0.5]),
        "计划":        np.array([ 0.5,  0.2,  0.4]),
        "创造":        np.array([ 0.3,  0.7,  0.5]),
        "创作":        np.array([ 0.2,  0.8,  0.5]),
        "设计":        np.array([ 0.4,  0.6,  0.6]),
        "想象":        np.array([ 0.2,  0.8,  0.7]),
        "感受":        np.array([ 0.0,  0.4, -0.2]),
        "共情":        np.array([-0.1,  0.5, -0.3]),
        "情绪":        np.array([ 0.0,  0.5, -0.3]),
        "感觉":        np.array([ 0.0,  0.4, -0.2]),
        "心情":        np.array([ 0.0,  0.5, -0.2]),
        "思考":        np.array([ 0.1, -0.3,  0.8]),
        "反思":        np.array([-0.2,  0.1,  0.6]),
        "元认知":      np.array([ 0.3, -0.2,  0.9]),
        "决定":        np.array([ 0.4, -0.3,  0.3]),
        "记忆":        np.array([-0.9, -0.4, -0.2]),
        "回忆":        np.array([-0.8, -0.5, -0.3]),
        "回想":        np.array([-0.8, -0.5, -0.2]),
        "之前":        np.array([-0.7, -0.2, -0.1]),
        "系统":        np.array([ 0.3, -0.3,  0.6]),
        "结构":        np.array([-0.1, -0.6,  0.4]),
        "报告":        np.array([-0.2, -0.5,  0.0]),
        "默认":        np.array([ 0.0,  0.0,  0.0]),
    }

    def __init__(self, default_vector: Optional[np.ndarray] = None):
        self.default_vector = default_vector or DIRECTION_TEMPLATES["default"].copy()

    def inspect(self, task_description: str) -> Dict[str, Any]:
        """查看编码分解。"""
        vec = self.encode(task_description)
        # 匹配的关键词列表
        return vec

    def encode(self, task_description: str) -> np.ndarray:
        """将任务描述编码为方向向量（中英文均支持）。"""
        vec = self.default_vector.copy()
        text = task_description.lower()
        matched = 0
        # 按关键词长度降序遍历（长词优先匹配，避免短词误伤）
        for kw in sorted(self.KEYWORD_BIAS.keys(), key=lambda x: -len(x)):
            if kw == "default":
                continue
            if kw in text:
                vec = vec + self.KEYWORD_BIAS[kw] * 0.3
                matched += 1
        if matched > 0:
            vec = vec / max(matched, 1) * 1.5  # 放大系数使向量远离原点
            vec = np.clip(vec, -1.0, 1.0)
        return vec

    def inspect(self, task_description: str) -> Dict[str, Any]:
        """查看编码分解。"""
        vec = self.encode(task_description)
        text = task_description.lower()
        matched_kws = []
        for kw in sorted(self.KEYWORD_BIAS.keys(), key=lambda x: -len(x)):
            if kw == "default":
                continue
            if kw in text:
                matched_kws.append(kw)
        return {
            "cognition": round(float(vec[0]), 3),
            "response": round(float(vec[1]), 3),
            "abstraction": round(float(vec[2]), 3),
            "matched_keywords": matched_kws[:10],
        }


# ═══════════════════════════════════════════════════════════════
# 方向工具函数
# ═══════════════════════════════════════════════════════════════

# 全局编码器
_default_encoder = TaskDirectionEncoder()


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """计算两个方向向量的余弦相似度。"""
    a = v1.flatten()
    b = v2.flatten()
    n1 = np.linalg.norm(a)
    n2 = np.linalg.norm(b)
    if n1 < 1e-8 or n2 < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (n1 * n2))


def encode_task(text: str) -> np.ndarray:
    """快捷编码（使用全局编码器）。"""
    return _default_encoder.encode(text)


def resolve_kakeya_bias(external_bias: Optional[Dict[str, float]]) -> np.ndarray:
    """
    将 Kakeya 覆盖度缺口偏置解析为方向向量偏置。

    P0 集成: Kakeya 监控器产生的 {domain:xxx: gap} 信号 → 方向偏移。
    """
    bias_vector = np.array([0.0, 0.0, 0.0])
    if not external_bias:
        return bias_vector

    for key, gap in external_bias.items():
        if key.startswith("domain:"):
            dom = key.split(":", 1)[1]
            if dom in ("technical", "logical", "analysis"):
                bias_vector += np.array([0.0, -0.4, 0.3]) * gap
            elif dom in ("emotional", "social", "personal"):
                bias_vector += np.array([0.0, 0.3, -0.2]) * gap
            elif dom in ("creative", "design", "art"):
                bias_vector += np.array([0.2, 0.5, 0.3]) * gap
            elif dom in ("planning", "strategy", "future"):
                bias_vector += np.array([0.5, 0.0, 0.3]) * gap
            else:
                bias_vector += np.array([0.2, 0.0, 0.0]) * gap
        elif key.startswith("focus:"):
            focus = key.split(":", 1)[1]
            if focus in ("reflect", "think", "analyze"):
                bias_vector += np.array([-0.2, -0.3, 0.5]) * gap * 0.7
            elif focus in ("create", "imagine", "explore"):
                bias_vector += np.array([0.0, 0.5, 0.3]) * gap * 0.7

    return bias_vector


# ═══════════════════════════════════════════════════════════════
# DirectionalCapability — 方向感知的能力声明
# ═══════════════════════════════════════════════════════════════

@dataclass
class DirectionalCapability:
    """
    方向感知的能力声明。

    与 Aether 的 Capability 兼容，额外带方向向量用于语义匹配。
    可直接转换为 Capability(name, confidence, ...)。
    """
    name: str
    direction_vector: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
    confidence: float = 1.0
    description: str = ""
    domain: str = "general"
    activation_threshold: float = 0.3

    def match_task(self, task_vector: np.ndarray) -> float:
        """计算与任务方向向量的匹配度。"""
        sim = cosine_similarity(self.direction_vector, task_vector)
        return sim if sim >= self.activation_threshold else 0.0

    def to_capability_kwargs(self) -> Dict[str, Any]:
        """转换为 Aether Capability 构造函数参数。"""
        return {
            "name": self.name,
            "confidence": self.confidence,
            "schema": {
                "direction_vector": self.direction_vector.tolist(),
                "domain": self.domain,
                "description": self.description,
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "direction": [round(float(v), 3) for v in self.direction_vector],
            "confidence": self.confidence,
            "domain": self.domain,
            "activation_threshold": self.activation_threshold,
        }
