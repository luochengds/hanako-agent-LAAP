"""
Bias Computers — 从 CognitiveBus 状态计算 logit_bias

导出 5 个偏置计算机供 LLMTamer 主模块使用，
其中 CognitiveBiasComputer 为第 5 维（认知偏差映射）。
"""

from .attention import AttentionBiasComputer
from .emotion import EmotionBiasComputer
from .needs import NeedsBiasComputer
from .meta import MetaBiasComputer
from .cognitive import CognitiveBiasComputer

__all__ = [
    "AttentionBiasComputer",
    "EmotionBiasComputer",
    "NeedsBiasComputer",
    "MetaBiasComputer",
    "CognitiveBiasComputer",
]
