"""
LAAP — 第一性原理元认知系统 (First-Principles Metacognition)

===========================================================
  第一性原理 + 元认知 = 数字生命体对自身思考的根基性审视
===========================================================

核心架构：
  Layer 1: 元认知监控 (Meta-Monitor)
    - 实时追踪思维过程、置信度、偏差
    - 所有监控指标都还原到第一性原理根基

  Layer 2: 第一性原理还原 (FP Grounding)
    - 当认知遇到瓶颈时，回退到基本真理重新推理
    - "我为什么这么想？这个想法的前提是什么？"

  Layer 3: 递归自审视 (Recursive Self-Examination)
    - "我知道我知道..." 的多层递归
    - 每个认知层都被上层监控

  Layer 4: 认知可信度评估 (Epistemic Trust)
    - 基于第一性原理评估信息的可信度
    - 区分"事实"、"推论"、"假设"、"信念"

与 Brain 的集成：
  Brain → 调用 FPMetaEngine 进行元认知评估
  FPMetaEngine → 回退到 FirstPrinciplesEngine 进行根基分析
  FPMetaEngine → 反馈给 MetaCognitionEngine 调整策略
"""

from laap.cognition.metacognition.fp_metacognition import (
    FirstPrinciplesMetaCognition,
    MetaCognitionLevel,
    EpistemicStatus,
    GroundedJudgment,
    ThinkingTrace,
    FPMetaState,
    FPCognitiveBias,
)
from laap.cognition.metacognition.reflection import (
    MetacognitionSystem,
    ReflectionReport,
    Anomaly,
    AnomalyType,
    Improvement,
    ImprovementType,
)

__all__ = [
    "FirstPrinciplesMetaCognition",
    "MetaCognitionLevel",
    "EpistemicStatus",
    "GroundedJudgment",
    "ThinkingTrace",
    "FPMetaState",
    "FPCognitiveBias",
    # 意识中间件层 — 反思/监控/改进
    "MetacognitionSystem",
    "ReflectionReport",
    "Anomaly",
    "AnomalyType",
    "Improvement",
    "ImprovementType",
]
