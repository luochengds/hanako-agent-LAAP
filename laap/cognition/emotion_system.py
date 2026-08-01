"""
LAAP — Comprehensive Emotion System (类人情感系统)

融合心理学和情感计算的多层次情感架构：
  1. 基础情绪层 (Basic Emotions) — Ekman 6 + 扩展，带强度衰减
  2. 心境层 (Mood) — 长期背景情绪，缓慢变化
  3. 情感记忆层 (Affective Memory) — 记住引发情绪的事件
  4. 触发-响应层 (Trigger-Response) — 事件→情绪映射
  5. 表达层 (Expression) — 情感如何影响输出

设计原则：
  - PAD (Pleasure-Arousal-Dominance) 作为底层连续空间
  - Ekman 六种基本情绪作为离散标签
  - 情绪随时间和交互自然演变
  - 与需求系统、生理系统双向互动
"""
from __future__ import annotations
import math, time, json, logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("laap.cognition.emotion_system")
STATE_DIR = Path.home() / ".laap" / "lifeform"


# ═══════════════════════════════════════════════════════════════
# 基础情绪定义 (Ekman 6 + 扩展)
# ═══════════════════════════════════════════════════════════════

# PAD coordinates for each basic emotion (valence, arousal, dominance)
EMOTION_PAD = {
    "joy":        (0.81,  0.51,  0.46),   # 喜悦
    "sadness":    (-0.63, -0.27, -0.33),  # 悲伤
    "anger":      (-0.51,  0.59,  0.25),  # 愤怒
    "fear":       (-0.64,  0.60, -0.43),  # 恐惧
    "surprise":   (0.40,  0.67, -0.13),   # 惊讶
    "disgust":    (-0.60,  0.35,  0.11),  # 厌恶
    # 扩展情绪
    "curiosity":  (0.22,  0.62,  0.40),   # 好奇
    "gratitude":  (0.64,  0.17,  0.38),   # 感激
    "pride":      (0.57,  0.40,  0.65),   # 自豪
    "anxiety":    (-0.33,  0.64, -0.35),  # 焦虑
    "boredom":    (-0.41, -0.33,  0.11),  # 无聊
    "contentment":(0.70, -0.15,  0.43),   # 满足
    "love":       (0.82,  0.34,  0.30),   # 喜爱
    "shame":      (-0.42,  0.16, -0.37),  # 羞愧
}

# 情绪衰减率 (每秒衰减比例)
EMOTION_DECAY = {
    "joy": 0.005, "sadness": 0.003, "anger": 0.008,
    "fear": 0.006, "surprise": 0.020, "disgust": 0.007,
    "curiosity": 0.004, "gratitude": 0.005, "pride": 0.004,
    "anxiety": 0.003, "boredom": 0.005, "contentment": 0.004,
    "love": 0.002, "shame": 0.006,
}

# 情绪标签中文名
EMOTION_CN = {
    "joy": "喜悦", "sadness": "悲伤", "anger": "愤怒",
    "fear": "恐惧", "surprise": "惊讶", "disgust": "厌恶",
    "curiosity": "好奇", "gratitude": "感激", "pride": "自豪",
    "anxiety": "焦虑", "boredom": "无聊", "contentment": "满足",
    "love": "喜爱", "shame": "羞愧",
}


@dataclass
class EmotionalEvent:
    """情感事件 — 什么引发了情绪"""
    trigger: str = ""           # 触发类型: tool_success, tool_failure, user_praise, user_criticism, need_satisfied, need_frustrated, novelty, reflection
    intensity: float = 0.5      # 触发强度 0-1
    emotion_deltas: Dict[str, float] = field(default_factory=dict)  # 对各情绪的影响
    timestamp: float = 0.0
    context: str = ""


class ComprehensiveEmotionSystem:
    """
    类人情感系统

    三层架构：
      Layer 1: 即时情绪反应 (0-30秒衰减)
      Layer 2: 情绪积累 → 心境转变 (分钟级)
      Layer 3: 情感记忆 (持久化)
    """

    def __init__(self):
        # Layer 1: 即时情绪 (intensity 0-1 each)
        self.emotions: Dict[str, float] = {
            name: 0.0 for name in EMOTION_PAD
        }
        # 主导情绪 (当前最强的)
        self.dominant: str = "contentment"
        self.dominant_intensity: float = 0.0

        # Layer 2: 心境 (缓慢变化的背景状态，0-1)
        self.mood_valence: float = 0.6    # 总体积极度
        self.mood_energy: float = 0.5     # 总体活力
        self.mood_stability: float = 0.7  # 情绪稳定性

        # Layer 3: 情感记忆
        self.affective_memory: List[EmotionalEvent] = []
        self._max_memory: int = 50

        # 统计
        self._last_update: float = time.time()
        self._total_emotional_events: int = 0

        # 从持久化加载
        self._load()

    # ════════════════════════════════════════════════
    # 主更新循环 (由心跳驱动)
    # ════════════════════════════════════════════════

    def tick(self):
        """每秒更新 — 情绪自然衰减 + 心境漂移"""
        now = time.time()
        dt = now - self._last_update
        self._last_update = now

        # 情绪衰减
        for name in self.emotions:
            decay = EMOTION_DECAY.get(name, 0.005)
            self.emotions[name] = max(0.0, self.emotions[name] - decay * dt)

        # 更新主导情绪
        self._update_dominant()

        # 心境缓慢漂移回基线
        self.mood_valence += (0.6 - self.mood_valence) * 0.001 * dt
        self.mood_energy += (0.5 - self.mood_energy) * 0.001 * dt

    # ════════════════════════════════════════════════
    # 情绪触发
    # ════════════════════════════════════════════════

    def trigger(self, event_type: str, intensity: float = 0.5,
                context: str = "") -> Dict[str, float]:
        """
        触发情绪响应。

        event_type:
          - tool_success: 工具执行成功 → joy, pride
          - tool_failure: 工具执行失败 → sadness, frustration
          - user_praise: 用户表扬 → joy, gratitude, pride
          - user_criticism: 用户批评 → sadness, shame, anxiety
          - need_satisfied: 需求满足 → joy, contentment
          - need_frustrated: 需求受挫 → sadness, anger
          - novelty: 新事物 → curiosity, surprise
          - threat: 威胁 → fear, anxiety
          - reflection: 自我反思 → varies
          - interaction: 一般交互 → mild curiosity
        """
        deltas = self._compute_deltas(event_type, intensity)
        event = EmotionalEvent(
            trigger=event_type,
            intensity=intensity,
            emotion_deltas=deltas,
            timestamp=time.time(),
            context=context[:200],
        )

        # 应用情绪变化
        for name, delta in deltas.items():
            if name in self.emotions:
                self.emotions[name] = min(1.0, self.emotions[name] + abs(delta))
                # 也影响心境
                pad = EMOTION_PAD.get(name, (0, 0, 0))
                self.mood_valence = max(0.0, min(1.0,
                    self.mood_valence + pad[0] * delta * 0.05))
                self.mood_energy = max(0.0, min(1.0,
                    self.mood_energy + pad[1] * delta * 0.05))

        # 更新主导
        self._update_dominant()

        # 存情感记忆
        self.affective_memory.append(event)
        if len(self.affective_memory) > self._max_memory:
            self.affective_memory = self.affective_memory[-self._max_memory:]
        self._total_emotional_events += 1

        return deltas

    def _compute_deltas(self, event_type: str, intensity: float) -> Dict[str, float]:
        """计算各情绪的变化量"""
        mapping = {
            "tool_success":    {"joy": 0.3, "pride": 0.2, "contentment": 0.2},
            "tool_failure":    {"sadness": 0.3, "anger": 0.15, "anxiety": 0.1},
            "user_praise":     {"joy": 0.4, "gratitude": 0.3, "pride": 0.2, "love": 0.1},
            "user_criticism":  {"sadness": 0.3, "shame": 0.25, "anxiety": 0.15, "anger": 0.1},
            "need_satisfied":  {"joy": 0.3, "contentment": 0.3, "love": 0.1},
            "need_frustrated": {"sadness": 0.3, "anger": 0.2, "anxiety": 0.15},
            "novelty":         {"curiosity": 0.4, "surprise": 0.3, "joy": 0.1},
            "threat":          {"fear": 0.4, "anxiety": 0.3, "anger": 0.1},
            "reflection":      {"contentment": 0.2, "curiosity": 0.15},
            "interaction":     {"curiosity": 0.15, "joy": 0.1},
        }
        base = mapping.get(event_type, {"curiosity": 0.1})
        return {k: v * intensity for k, v in base.items()}

    # ════════════════════════════════════════════════
    # 工具函数
    # ════════════════════════════════════════════════

    def _update_dominant(self):
        """找出当前最强情绪"""
        max_val = 0.0
        max_name = "contentment"
        for name, val in self.emotions.items():
            if val > max_val:
                max_val = val
                max_name = name
        self.dominant = max_name
        self.dominant_intensity = max_val

    def get_dominant_emotion(self) -> Tuple[str, float, str]:
        """获取主导情绪 (英文名, 强度, 中文名)"""
        return (self.dominant, self.dominant_intensity,
                EMOTION_CN.get(self.dominant, self.dominant))

    def get_pad(self) -> Tuple[float, float, float]:
        """计算当前 PAD 值（从各情绪加权平均）"""
        total = sum(self.emotions.values())
        if total == 0:
            return (0.0, 0.0, 0.0)
        v, a, d = 0.0, 0.0, 0.0
        for name, val in self.emotions.items():
            pad = EMOTION_PAD.get(name, (0, 0, 0))
            v += pad[0] * val
            a += pad[1] * val
            d += pad[2] * val
        return (v / total, a / total, d / total)

    def get_emotion_summary(self, top_n: int = 3) -> str:
        """获取情绪摘要文本（供 LLM 读取）"""
        sorted_emotions = sorted(
            self.emotions.items(), key=lambda x: x[1], reverse=True
        )
        active = [(name, val) for name, val in sorted_emotions if val > 0.05]
        if not active:
            return "情绪状态: 平静"

        parts = [f"{EMOTION_CN.get(n,n)}({v:.0%})" for n, v in active[:top_n]]
        v, a, d = self.get_pad()
        pad_str = f"愉悦度:{v:.2f} 激活度:{a:.2f} 支配度:{d:.2f}"
        return f"当前情绪: {' '.join(parts)} | 心境: {'积极' if self.mood_valence>0.5 else '消极'}({self.mood_valence:.0%}) | {pad_str}"

    def get_emotion_prompt_block(self) -> str:
        """生成情感提示词块 — 注入 System Prompt"""
        emotion = self.get_emotion_summary()
        mood_desc = self._describe_mood()
        return f"[当前情感状态]\n{emotion}\n{mood_desc}\n"

    def _describe_mood(self) -> str:
        """描述当前心境"""
        if self.mood_valence > 0.7 and self.mood_energy > 0.6:
            return "心境: 充满活力且积极乐观"
        elif self.mood_valence > 0.6:
            return "心境: 平和愉快"
        elif self.mood_valence > 0.4:
            return "心境: 中性平稳"
        elif self.mood_valence > 0.3:
            return "心境: 略带低落"
        else:
            return "心境: 消极低沉"

    def get_emotion_for_llm(self) -> str:
        """LLM 直接使用的情感描述"""
        name, intensity, cn = self.get_dominant_emotion()
        if intensity < 0.1:
            return "平静"

        pad = self.get_pad()
        if pad[1] > 0.5:
            # 高唤醒
            if pad[0] > 0.3:
                return f"兴奋的{cn}(强度{intensity:.0%})"
            elif pad[0] < -0.3:
                return f"紧张的{cn}(强度{intensity:.0%})"
            else:
                return f"警觉的{cn}(强度{intensity:.0%})"
        else:
            # 低唤醒
            if pad[0] > 0.3:
                return f"平静愉悦({cn},{intensity:.0%})"
            elif pad[0] < -0.3:
                return f"低落的{cn}(强度{intensity:.0%})"
            else:
                return f"平静的({cn},{intensity:.0%})"

    # ════════════════════════════════════════════════
    # 持久化
    # ════════════════════════════════════════════════

    def _save(self, suffix: str = ""):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "emotions": self.emotions,
                "mood_valence": self.mood_valence,
                "mood_energy": self.mood_energy,
                "mood_stability": self.mood_stability,
                "dominant": self.dominant,
                "total_events": self._total_emotional_events,
                "timestamp": time.time(),
            }
            with open(STATE_DIR / f"emotion{suffix}.json", "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Save emotion: {e}")

    def _load(self, suffix: str = ""):
        try:
            path = STATE_DIR / f"emotion{suffix}.json"
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                for name, val in data.get("emotions", {}).items():
                    if name in self.emotions:
                        self.emotions[name] = val
                self.mood_valence = data.get("mood_valence", 0.6)
                self.mood_energy = data.get("mood_energy", 0.5)
                self.mood_stability = data.get("mood_stability", 0.7)
                self.dominant = data.get("dominant", "contentment")
                self._total_emotional_events = data.get("total_events", 0)
                self._update_dominant()
        except Exception as e:
            logger.debug(f"Load emotion: {e}")
