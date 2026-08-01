"""
self_model_nn — Adapter (SelfStateOutput ↔ CognitiveStateSnapshot 转换层)
=========================================================================

本模块是三路径闭环的关键接缝代码，负责在两个状态表示间转换：

  SelfStateOutput (self_model_nn 输出)
      ↓ self_state_output_to_snapshot()
  CognitiveStateSnapshot (CognitiveBus / llm_tamer / guided_generator 消费)
      ↓ snapshot_to_self_state_output()
  SelfStateOutput (反馈给 self_model_nn 训练)

字段映射:
  ┌─────────────────────┐         ┌──────────────────────────┐
  │ SelfStateOutput     │         │ CognitiveStateSnapshot   │
  ├─────────────────────┤         ├──────────────────────────┤
  │ attention_focus:str │ ──────→ │ attention.focus: Enum    │
  │ emotional_valence   │ ──────→ │ emotion.valence: Enum    │
  │ arousal: float      │ ──────→ │ emotion.arousal: float   │
  │ needs: Dict         │ ──────→ │ needs: NeedState         │
  │ self_presence       │ ──────→ │ self_presence: float     │
  │ certainty           │ ──────→ │ needs.certainty          │
  │ narrative_token     │ ──────→ │ narrative: str           │
  │ new_hidden_state    │ (不转换) │ (由 state_manager 管理)  │
  └─────────────────────┘         └──────────────────────────┘

枚举映射说明:
  - AttentionFocus: SelfStateOutput 用小写字符串，CognitiveStateSnapshot 用 Enum
  - EmotionalValence: 同上，需建立 str ↔ Enum 映射表
  - bridge 的 AttentionFocus/EmotionalState 与 AGI 版枚举值不同，也需映射

依赖:
  - laap.agi.cognitive_bus (CognitiveStateSnapshot 及相关枚举)
  - laap.laap_tools.self_model.model (SelfStateOutput)

设计原则:
  - 单向无副作用：转换函数不修改输入对象
  - 容错：未知字符串映射到默认枚举值，不抛异常
  - 可追溯：所有映射决策有注释
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("laap.self_model.adapter")


# ═══════════════════════════════════════════════════════════════
# 尝试导入 CognitiveStateSnapshot 及相关枚举
# ═══════════════════════════════════════════════════════════════
try:
    from laap.agi.cognitive_bus import (
        CognitiveStateSnapshot,
        NeedState,
        EmotionState,
        AttentionState,
        AttentionFocus,
        EmotionalValence,
        PredictionError,
    )
    _AGI_AVAILABLE = True
except ImportError:
    _AGI_AVAILABLE = False
    CognitiveStateSnapshot = None  # type: ignore
    NeedState = None  # type: ignore
    EmotionState = None  # type: ignore
    AttentionState = None  # type: ignore
    AttentionFocus = None  # type: ignore
    EmotionalValence = None  # type: ignore
    PredictionError = None  # type: ignore
    logger.debug("laap.agi.cognitive_bus 不可用，adapter 将以降级模式运行")

from .model import SelfStateOutput


# ═══════════════════════════════════════════════════════════════
# 字符串 → 枚举 映射表
# ═══════════════════════════════════════════════════════════════

# AttentionFocus: SelfStateOutput 字符串 → AGI AttentionFocus 枚举
# SelfStateOutput 的 attention_focus 值来自 model.py:308-310，与 AGI 枚举值一致
_ATTENTION_FOCUS_MAP: Dict[str, str] = {
    "user": "USER",
    "task": "TASK",
    "self": "SELF",
    "environment": "ENVIRONMENT",
    "memory": "MEMORY",
    "planning": "PLANNING",
    "learning": "LEARNING",
    "idle": "IDLE",
}

# EmotionalValence: SelfStateOutput 字符串 → AGI EmotionalValence 枚举
# SelfStateOutput 的 emotional_valence 值来自 model.py:318-320，与 AGI 枚举值一致
_EMOTIONAL_VALENCE_MAP: Dict[str, str] = {
    "positive_high": "POSITIVE_HIGH",
    "positive_mild": "POSITIVE_MILD",
    "neutral": "NEUTRAL",
    "negative_mild": "NEGATIVE_MILD",
    "negative_high": "NEGATIVE_HIGH",
    "curious": "CURIOUS",
    "confused": "CONFUSED",
}

# ArisCognitiveBridge 的 AttentionFocus → AGI AttentionFocus 映射
# bridge 枚举（aris_cognitive_bridge.py:82-88）与 AGI 枚举值不同，需显式映射
_BRIDGE_TO_AGI_ATTENTION: Dict[str, str] = {
    "respond": "USER",      # 回应用户 → 关注用户
    "learn": "LEARNING",    # 学习中 → 学习
    "explore": "ENVIRONMENT",  # 探索 → 关注环境
    "reflect": "SELF",      # 反思 → 关注自我
    "plan": "PLANNING",     # 规划 → 规划
    "idle": "IDLE",         # 空闲 → 空闲
}

# ArisCognitiveBridge 的 EmotionalState → AGI EmotionalValence 映射
# bridge 枚举（aris_cognitive_bridge.py:90-96）与 AGI 枚举值不同，需显式映射
_BRIDGE_TO_AGI_EMOTION: Dict[str, str] = {
    "neutral": "NEUTRAL",
    "curious": "CURIOUS",
    "concerned": "NEGATIVE_MILD",
    "joyful": "POSITIVE_HIGH",
    "contemplative": "POSITIVE_MILD",
    "anxious": "NEGATIVE_HIGH",
}


# ═══════════════════════════════════════════════════════════════
# 核心转换函数
# ═══════════════════════════════════════════════════════════════

def _resolve_attention_focus(focus_str: str) -> str:
    """
    将字符串解析为 AGI AttentionFocus 枚举成员名。
    未知字符串降级为 IDLE。
    """
    return _ATTENTION_FOCUS_MAP.get(focus_str.lower(), "IDLE")


def _resolve_emotional_valence(valence_str: str) -> str:
    """
    将字符串解析为 AGI EmotionalValence 枚举成员名。
    未知字符串降级为 NEUTRAL。
    """
    return _EMOTIONAL_VALENCE_MAP.get(valence_str.lower(), "NEUTRAL")


def self_state_output_to_snapshot(
    output: SelfStateOutput,
    base_snapshot: Optional[Any] = None,
) -> Any:
    """
    将 SelfModelNN 的输出转换为 CognitiveStateSnapshot。

    这是三路径闭环的关键转换：self_model.forward() → 本函数 → tamer/generator 消费。

    Args:
        output: SelfModelNN 前向传播的输出
        base_snapshot: 基础快照（可选）。如果提供，保留其 timestamp、
                       prediction_error、active_modules 字段，
                       仅更新 needs/emotion/attention/self_presence/curiosity/narrative。
                       如果不提供，创建全新快照。

    Returns:
        CognitiveStateSnapshot 实例。如果 AGI 模块不可用，返回 dict 降级表示。

    降级策略:
        如果 laap.agi.cognitive_bus 不可用（_AGI_AVAILABLE=False），
        返回与 CognitiveStateSnapshot.to_dict() 结构一致的 dict，
        这样 tamer/generator 的降级路径仍可消费。
    """
    needs_dict = {
        "competence": float(output.needs.get("competence", 0.5)),
        "autonomy": float(output.needs.get("autonomy", 0.5)),
        "relatedness": float(output.needs.get("relatedness", 0.5)),
        "certainty": float(output.needs.get("certainty", output.certainty)),
        "growth": float(output.needs.get("growth", 0.5)),
    }

    attention_focus_name = _resolve_attention_focus(output.attention_focus)
    emotional_valence_name = _resolve_emotional_valence(output.emotional_valence)

    # 降级模式：AGI 模块不可用时返回 dict
    if not _AGI_AVAILABLE:
        return {
            "timestamp": time.time(),
            "needs": needs_dict,
            "emotion": {
                "valence": output.emotional_valence,
                "arousal": output.arousal,
                "dominance": 0.5,
            },
            "attention": {
                "focus": output.attention_focus,
                "intensity": 0.5,
                "salience_map": {},
            },
            "self_presence": output.self_presence,
            "curiosity": 0.3,
            "prediction_error": None,
            "active_modules": [],
            "narrative": output.narrative_token or "",
        }

    # 正常模式：构造 CognitiveStateSnapshot
    needs = NeedState(
        competence=needs_dict["competence"],
        autonomy=needs_dict["autonomy"],
        relatedness=needs_dict["relatedness"],
        certainty=needs_dict["certainty"],
        growth=needs_dict["growth"],
    )

    emotion = EmotionState(
        valence=EmotionalValence[emotional_valence_name],
        arousal=float(output.arousal),
        dominance=0.5,
    )

    attention = AttentionState(
        focus=AttentionFocus[attention_focus_name],
        intensity=0.5,
        salience_map={},
    )

    # 从 base_snapshot 继承不变字段（如果有）
    if base_snapshot is not None:
        timestamp = base_snapshot.timestamp
        prediction_error = base_snapshot.prediction_error
        active_modules = base_snapshot.active_modules
    else:
        timestamp = time.time()
        prediction_error = None
        active_modules = ["self_model_nn"]

    # curiosity: SelfStateOutput 没有直接对应字段，
    # 用 emotional_valence == "curious" 作为好奇心信号
    curiosity = 0.7 if output.emotional_valence.lower() == "curious" else 0.3

    snapshot = CognitiveStateSnapshot(
        timestamp=timestamp,
        needs=needs,
        emotion=emotion,
        attention=attention,
        self_presence=float(output.self_presence),
        curiosity=curiosity,
        prediction_error=prediction_error,
        active_modules=active_modules,
        narrative=output.narrative_token or "",
    )

    logger.debug(
        f"Converted SelfStateOutput → CognitiveStateSnapshot "
        f"(focus={attention_focus_name}, valence={emotional_valence_name}, "
        f"self_presence={output.self_presence:.3f})"
    )

    return snapshot


def snapshot_to_self_state_output(
    snapshot: Any,
    hidden_state: Optional[Any] = None,
) -> SelfStateOutput:
    """
    将 CognitiveStateSnapshot 转换回 SelfStateOutput（反向转换）。

    用途：
      - 在 self_model.forward() 之前，把 CognitiveBus 当前状态转为 SelfStateOutput
        作为训练标签或对比基线
      - 在 after_turn 中构造训练样本（before_state + after_state）

    Args:
        snapshot: CognitiveStateSnapshot 实例或 dict（降级模式）
        hidden_state: 可选的隐藏状态向量（不来自 snapshot，来自 state_manager）

    Returns:
        SelfStateOutput 实例
    """
    import numpy as np

    # 处理 dict 降级模式
    if isinstance(snapshot, dict):
        needs = snapshot.get("needs", {})
        emotion = snapshot.get("emotion", {})
        attention = snapshot.get("attention", {})
        return SelfStateOutput(
            attention_focus=attention.get("focus", "idle"),
            emotional_valence=emotion.get("valence", "neutral"),
            arousal=float(emotion.get("arousal", 0.5)),
            needs={
                "competence": float(needs.get("competence", 0.5)),
                "autonomy": float(needs.get("autonomy", 0.5)),
                "relatedness": float(needs.get("relatedness", 0.5)),
                "certainty": float(needs.get("certainty", 0.5)),
                "growth": float(needs.get("growth", 0.5)),
            },
            self_presence=float(snapshot.get("self_presence", 0.5)),
            certainty=float(needs.get("certainty", 0.5)),
            new_hidden_state=np.asarray(hidden_state, dtype=np.float32)
                if hidden_state is not None else None,
            narrative_token=snapshot.get("narrative", ""),
        )

    # 处理 CognitiveStateSnapshot 实例
    needs = snapshot.needs
    emotion = snapshot.emotion
    attention = snapshot.attention

    return SelfStateOutput(
        attention_focus=attention.focus.value,
        emotional_valence=emotion.valence.value,
        arousal=float(emotion.arousal),
        needs={
            "competence": float(needs.competence),
            "autonomy": float(needs.autonomy),
            "relatedness": float(needs.relatedness),
            "certainty": float(needs.certainty),
            "growth": float(needs.growth),
        },
        self_presence=float(snapshot.self_presence),
        certainty=float(needs.certainty),
        new_hidden_state=np.asarray(hidden_state, dtype=np.float32)
            if hidden_state is not None else None,
        narrative_token=snapshot.narrative,
    )


def bridge_state_to_snapshot(
    bridge_state: Any,
    bridge_focus_enum: Any = None,
    bridge_emotion_enum: Any = None,
) -> Any:
    """
    将 ArisCognitiveBridge 的 CognitiveState 转换为 AGI CognitiveStateSnapshot。

    ArisCognitiveBridge 使用自己的 CognitiveState dataclass（aris_cognitive_bridge.py:99-110），
    与 AGI 版的 CognitiveStateSnapshot 字段不同：
      - bridge.focus 是 AttentionFocus 枚举（RESPOND/LEARN/EXPLORE/REFLECT/PLAN/IDLE）
      - bridge.emotion 是 EmotionalState 枚举（NEUTRAL/CURIOUS/CONCERNED/JOYFUL/CONTEMPLATIVE/ANXIOUS）
      - bridge 没有 certainty/growth 字段

    本函数建立两者间的映射，使 bridge 状态可被 tamer/generator 消费。

    Args:
        bridge_state: ArisCognitiveBridge 的 CognitiveState 实例
        bridge_focus_enum: bridge 的 AttentionFocus 枚举类（用于 .value 访问）
        bridge_emotion_enum: bridge 的 EmotionalState 枚举类

    Returns:
        CognitiveStateSnapshot 实例或 dict（降级模式）
    """
    # 提取 bridge 状态值
    focus_value = bridge_state.focus.value if hasattr(bridge_state.focus, 'value') else str(bridge_state.focus)
    emotion_value = bridge_state.emotion.value if hasattr(bridge_state.emotion, 'value') else str(bridge_state.emotion)

    # bridge → AGI 枚举映射
    agi_focus_name = _BRIDGE_TO_AGI_ATTENTION.get(focus_value, "IDLE")
    agi_valence_name = _BRIDGE_TO_AGI_EMOTION.get(emotion_value, "NEUTRAL")

    needs_dict = {
        "competence": float(getattr(bridge_state, 'needs_competence', 0.5)),
        "autonomy": float(getattr(bridge_state, 'needs_autonomy', 0.5)),
        "relatedness": float(getattr(bridge_state, 'needs_relatedness', 0.5)),
        "certainty": float(getattr(bridge_state, 'confidence', 0.5)),
        "growth": 0.5,  # bridge 没有 growth 字段，使用默认值
    }

    # 降级模式
    if not _AGI_AVAILABLE:
        return {
            "timestamp": time.time(),
            "needs": needs_dict,
            "emotion": {
                "valence": agi_valence_name.lower(),
                "arousal": float(getattr(bridge_state, 'cognitive_load', 0.3)),
                "dominance": float(getattr(bridge_state, 'self_presence', 0.7)),
            },
            "attention": {
                "focus": agi_focus_name.lower(),
                "intensity": 0.5,
                "salience_map": {},
            },
            "self_presence": float(getattr(bridge_state, 'self_presence', 0.7)),
            "curiosity": 0.7 if emotion_value == "curious" else 0.3,
            "prediction_error": None,
            "active_modules": ["aris_bridge"],
            "narrative": "",
        }

    # 正常模式
    needs = NeedState(
        competence=needs_dict["competence"],
        autonomy=needs_dict["autonomy"],
        relatedness=needs_dict["relatedness"],
        certainty=needs_dict["certainty"],
        growth=needs_dict["growth"],
    )

    emotion = EmotionState(
        valence=EmotionalValence[agi_valence_name],
        arousal=float(getattr(bridge_state, 'cognitive_load', 0.3)),
        dominance=float(getattr(bridge_state, 'self_presence', 0.7)),
    )

    attention = AttentionState(
        focus=AttentionFocus[agi_focus_name],
        intensity=0.5,
        salience_map={},
    )

    snapshot = CognitiveStateSnapshot(
        timestamp=time.time(),
        needs=needs,
        emotion=emotion,
        attention=attention,
        self_presence=float(getattr(bridge_state, 'self_presence', 0.7)),
        curiosity=0.7 if emotion_value == "curious" else 0.3,
        prediction_error=None,
        active_modules=["aris_bridge"],
        narrative="",
    )

    logger.debug(
        f"Converted bridge CognitiveState → AGI CognitiveStateSnapshot "
        f"(bridge_focus={focus_value} → agi_focus={agi_focus_name}, "
        f"bridge_emotion={emotion_value} → agi_valence={agi_valence_name})"
    )

    return snapshot
