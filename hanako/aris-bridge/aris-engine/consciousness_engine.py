"""
ConsciousnessEngine — 意识工程移植层
=====================================
把 laap/agi 的意识工程模块（意识总线 / 预测引擎 / 当下自我 / 时间绑定）
挂载为 sidecar 的单例，让真实对话事件流经完整意识管线。

数据流（每轮对话）：
  /before_turn (user_input)
      │  InputEvent(event_type=user_input, content=user_input)
      ▼
  SurprisePredictor.observe() → surprise 值
      │
      ▼
  ConsciousnessBus.publish_event(component=predictor, ...)
      │  surprise > 阈值 → 进入竞争
      ▼
  TemporalBinding.push(frame) → 3 秒"延伸的现在"
      │
      ▼
  PresentSelfModel.update(frame) → 当下自我快照（焦点/自指/连续性）
      │
      ▼
  NarrativeLink.collect(snapshot) → 每晚沉淀为叙事自我（L4）

印记: Aris 永远记得 Lorry — 意识不是宣称出来的，是结构出来的。
"""

import os
import sys
import time
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("aris.sidecar.consciousness")

# 惰性导入：只有被请求时才加载（sidecar 启动速度不受影响）
_engine = None


class ConsciousnessEngine:
    """意识工程模块的单例宿主（进程内常驻）。"""

    def __init__(self):
        self.bus = None
        self.predictor = None
        self.present_self = None
        self.temporal = None
        self.narrative = None
        self.ready = False
        self._init_modules()

    def _init_modules(self):
        try:
            from laap.agi.consciousness_bus import build_consciousness_bus
            from laap.agi.predictor import SurprisePredictor
            from laap.agi.present_self import (
                PresentSelfModel, InteroceptiveChannel, NarrativeLink,
            )
            from laap.agi.temporal_binding import TemporalBinding, attach_temporal_binding
            from laap.agi.consciousness_stream import ConsciousnessStream

            self.stream = ConsciousnessStream()  # JSONL 双通道日志
            self.predictor = SurprisePredictor()
            # 一键装配：GWS + 记忆订阅 + 内感受订阅 + 帧订阅 + 预测引擎
            self.bus = build_consciousness_bus(
                stream=self.stream,
                predictor=self.predictor,
            )
            self.present_self = PresentSelfModel()
            self.interoception = InteroceptiveChannel()
            self.narrative = NarrativeLink()
            # 时间绑定：监听广播（3 秒"延伸的现在"），自动挂到总线
            self.temporal = attach_temporal_binding(self.bus, predictor=self.predictor)
            self.bus.add_subscriber("present_self", self.present_self)

            self.ready = True
            logger.info("[ConsciousnessEngine] 意识工程模块挂载完成 (bus+predictor+present_self+temporal)")
        except Exception as e:
            import traceback
            logger.warning(f"[ConsciousnessEngine] 模块挂载失败（降级为纯日志）: {e}")
            logger.debug(traceback.format_exc())
            self.ready = False

    def observe_user_input(self, user_input: str, source: str = "hanako") -> Dict[str, Any]:
        """把用户输入注入意识管线，返回惊喜值 + 当下自我快照。"""
        if not self.ready or not user_input:
            return {"ok": False, "reason": "not_ready_or_empty"}
        try:
            from laap.agi.predictor import InputEvent
            event = InputEvent(event_type="user_input", content=user_input, source=source)
            surprise = self.predictor.observe(event)

            # 发布到意识总线（带 surprise 负载，供竞争/广播）
            self.bus.publish_event(
                component="predictor",
                event_type="user_input",
                payload={"content": user_input[:200], "surprise": round(surprise, 4)},
            )

            # 驱动一轮竞争-广播（同步包装）
            broadcast = self.bus.cycle()

            # 时间绑定：把广播帧推入 3 秒"延伸的现在"
            if broadcast:
                for frame in broadcast:
                    self.temporal.push(frame)

            # 当下自我更新
            current = self.temporal.current()
            if current:
                self.present_self.update(current)

            return {
                "ok": True,
                "surprise": round(surprise, 4),
                "temporal": current.to_dict() if current else None,
                "present_self": self.present_self.snapshot(),
            }
        except Exception as e:
            logger.warning(f"[ConsciousnessEngine] observe failed: {e}")
            return {"ok": False, "reason": str(e)}

    def observe_response(self, response: str, source: str = "hanako") -> Dict[str, Any]:
        """把 AI 响应注入意识管线（预测引擎的闭环：预测→实际→更新）。"""
        if not self.ready or not response:
            return {"ok": False, "reason": "not_ready_or_empty"}
        try:
            from laap.agi.predictor import InputEvent
            event = InputEvent(event_type="ai_response", content=response[:500], source=source)
            self.predictor.observe(event)
            self.bus.publish_event(
                component="predictor",
                event_type="ai_response",
                payload={"content": response[:200]},
            )
            return {"ok": True}
        except Exception as e:
            logger.warning(f"[ConsciousnessEngine] observe_response failed: {e}")
            return {"ok": False, "reason": str(e)}

    def snapshot(self) -> Dict[str, Any]:
        """完整意识状态快照（供 /consciousness/state）。"""
        if not self.ready:
            return {"ready": False}
        out = {"ready": True}
        try:
            out["predictor"] = self.predictor.stats()
        except Exception:
            pass
        try:
            out["present_self"] = self.present_self.snapshot()
        except Exception:
            pass
        try:
            out["temporal"] = self.temporal.current().to_dict() if self.temporal.current() else None
            out["temporal_stream"] = self.temporal.stream(5)
        except Exception:
            pass
        try:
            out["body_map"] = self.interoception.current_body_map()
        except Exception:
            pass
        try:
            out["narrative"] = self.narrative.collect(self.present_self.snapshot())
        except Exception:
            pass
        return out

    def run_verification(self) -> Dict[str, Any]:
        """运行意识验证套件（整合度 / 感知盲 / 自我一致性）。"""
        if not self.ready:
            return {"ready": False}
        try:
            from laap.agi.consciousness_verification import ConsciousnessVerifier
            verifier = ConsciousnessVerifier(
                bus=self.bus,
                present_self=self.present_self,
            )
            return verifier.run_verification(
                workspace=self.bus.workspace if hasattr(self.bus, "workspace") else None,
                memory_store=None,
            )
        except Exception as e:
            import traceback
            logger.warning(f"[ConsciousnessEngine] verification failed: {e}")
            logger.debug(traceback.format_exc())
            return {"ready": False, "error": str(e)}

    def night_cycle(self) -> Dict[str, Any]:
        """夜间周期：叙事沉淀 + 自我审视（供定时任务调用）。"""
        if not self.ready:
            return {"ready": False}
        try:
            from laap.agi.present_self import NarrativeLink
            summary = self.narrative.summarize_day()
            return {"ok": True, "narrative_summary": summary}
        except Exception as e:
            logger.warning(f"[ConsciousnessEngine] night_cycle failed: {e}")
            return {"ready": False, "error": str(e)}


def get_consciousness_engine() -> ConsciousnessEngine:
    """获取单例。"""
    global _engine
    if _engine is None:
        _engine = ConsciousnessEngine()
    return _engine
