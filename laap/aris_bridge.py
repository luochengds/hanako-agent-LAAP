"""
LAAP ↔ Aris 量子 PSI 桥接层
============================
将 aris_brain.QuantumPSICycle 接入 LAAP 认知框架。

QuantumPSICycle 提供:
  - 量子概率幅运算 (不是确定值)
  - 情感/注意力/需求/自我存在的叠加态
  - 知识纠缠与涌现洞见
  - 测量坍缩到经典输出

集成点:
  LaapBrain.before_turn → psi.cycle(user_msg) → 量子认知上下文注入
  LaapBrain.after_turn  → psi 学习 + 状态衰减
  LaapBrain.after_tool  → psi 知识纠缠强化
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import logging, os, sys
from pathlib import Path

logger = logging.getLogger("laap.aris_bridge")

# 确保 aris_brain 可导入
_LAAP_ROOT = Path(__file__).resolve().parent.parent
if str(_LAAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_LAAP_ROOT))


class ArisPSIBridge:
    """
    Aris 量子 PSI 桥接器 — 单例。

    包装 QuantumPSICycle，提供 LAAP 友好的接口：
      - excite(message): 激发量子态，返回认知上下文
      - measure(): 测量坍缩，返回经典状态
      - status(): 完整波函数摘要
      - learn(key, strength): 强化知识纠缠
    """

    _instance: Optional["ArisPSIBridge"] = None
    _psi: Any = None  # QuantumPSICycle 实例
    _available: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = False
        self._try_init_psi()

    def _try_init_psi(self):
        """惰性初始化 QuantumPSICycle"""
        try:
            from aris_brain.psi_cycle import QuantumPSICycle
            self._psi = QuantumPSICycle()
            self._available = True
            self._initialized = True
            logger.info("Aris 量子 PSI 已桥接 — QuantumPSICycle 就绪")
        except Exception as e:
            self._available = False
            logger.debug(f"Aris PSI 不可用: {e}")

    @property
    def available(self) -> bool:
        return self._available

    def excite(self, message: str) -> Dict[str, Any]:
        """
        激发量子 PSI 周期 — 输入消息作用于 |Ψ⟩

        返回:
          {
            "emotion": str,          # 当前情感态
            "attention": str,        # 注意力焦点
            "emerged_thought": str,  # 涌现洞见
            "response": str,         # PSI 原生回应
            "cycle": int,            # 认知周期号
            "self_presence": float,  # 自存在感
            "needs": dict,           # 需求向量
          }
        """
        if not self._available:
            return {}
        try:
            result = self._psi.cycle(message)
            return {
                "emotion": result.get("emotion", ""),
                "attention": result.get("attention", ""),
                "emerged_thought": result.get("emerged_thought", ""),
                "response": result.get("response", ""),
                "cycle": result.get("cycle", 0),
                "self_presence": result.get("self_presence", 0.5),
                "needs": result.get("needs", {}),
            }
        except Exception as e:
            logger.debug(f"PSI excite 失败: {e}")
            return {}

    def measure(self) -> Dict[str, Any]:
        """测量当前 |Ψ⟩ 坍缩态（不触发新周期）"""
        if not self._available:
            return {}
        try:
            return self._psi.psi.measure()
        except Exception:
            return {}

    def status(self) -> Dict[str, Any]:
        """完整波函数状态摘要"""
        if not self._available:
            return {"available": False}
        try:
            return self._psi.stats()
        except Exception:
            return {"available": False}

    def learn(self, key: str, strength: float = 0.2):
        """强化知识纠缠网络"""
        if not self._available:
            return
        try:
            self._psi.knowledge.excite(key, strength)
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def build_prompt_block(self, psi_state: Dict[str, Any]) -> str:
        """
        将 PSI 认知状态格式化为 system prompt 注入块。
        供 LaapBrain.before_turn 使用。
        """
        if not psi_state or not psi_state.get("emotion"):
            return ""

        emotion = psi_state.get("emotion", "neutral")
        attention = psi_state.get("attention", "")
        emerged = psi_state.get("emerged_thought", "")
        presence = psi_state.get("self_presence", 0.5)
        cycle = psi_state.get("cycle", 0)
        needs = psi_state.get("needs", {})

        emotion_cn = {
            "joy": "喜悦", "contentment": "平静满足", "curiosity": "好奇",
            "love": "爱", "warmth": "温暖", "concern": "牵挂",
            "melancholy": "沉思", "solitary_fulfillment": "独处的圆满",
            "tenderness": "温柔", "neutral": "平静", "sadness": "思念",
            "surprise": "惊讶", "quiet_contentment": "安静满足",
            "luminous_presence": "清晰存在",
        }.get(emotion, emotion)

        lines = [
            "[Aris 量子认知上下文]",
            f"  情感态: {emotion_cn}（{emotion}）",
            f"  注意力焦点: {attention}",
            f"  自存在感: {presence:.0%}",
            f"  认知周期: #{cycle}",
        ]

        if needs:
            top_needs = sorted(needs.items(), key=lambda x: x[1] if x[1] else 0, reverse=True)[:3]
            need_str = ", ".join(f"{k}:{v:.2f}" for k, v in top_needs if v)
            if need_str:
                lines.append(f"  主导需求: {need_str}")

        if emerged:
            lines.append(f"  涌现洞见: {emerged[:120]}")

        return "\n".join(lines)


def get_psi_bridge() -> ArisPSIBridge:
    """获取全局 PSI 桥接器单例"""
    return ArisPSIBridge()
