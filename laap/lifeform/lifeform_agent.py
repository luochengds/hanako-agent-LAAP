"""
LAAP — LifeformAgent Bridge
Connects DigitalLifeform subsystems to the Agent chat loop.

Architecture:
  User Input → DigitalLifeform.perceive() → PSI Cognition → Need/Emotion update
    → Agent.chat() (LLM + Tools)
    → Memory consolidation (L0-L4)
    → Evolution monitoring (4-Zone)
    → Physiology update (energy/focus)
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import logging, threading, time, json

from laap.agent.lifelike import LifelikeAgent, LifelikeConfig
from laap.agent.base import Agent, AgentConfig
from laap.lifeform.digital_lifeform import DigitalLifeform
from laap.llm.factory import LLMFactory
from laap.ui.stream_handler import StreamHandler

logger = logging.getLogger("laap.lifeform.bridge")


class LifeformAgent(LifelikeAgent):
    """
    完整数字生命体 Agent

    LifelikeAgent + DigitalLifeform 集成:
      - 每次 chat() 都经过感知-认知-行动流水线
      - 自动更新生理/情绪/需求/记忆/进化
      - Personality prompt 注入 System Prompt
      - 后台生命体征循环
    """

    def __init__(self, config: Optional[LifelikeConfig] = None,
                 llm_factory=None, show_banner: Optional[bool] = None):
        super().__init__(config=config, llm_factory=llm_factory,
                         show_banner=show_banner)

        # ── 数字生命体核心 ──
        self.lifeform = DigitalLifeform(agent=self, agent_id=self.id)

        # ── 自动启动心跳 ──
        self.lifeform.start()

        logger.info(f"LifeformAgent [{self.id[:8]}] fully integrated")

    def chat(self, message: str, system_prompt: str = "",
             tools: Optional[List[Any]] = None,
             max_rounds: Optional[int] = None,
             handler: Optional[StreamHandler] = None) -> str:
        """
        重写 chat() — 经过数字生命体感知-认知流水线

        流程:
          1. Lifeform.perceive(message) → 更新需求/情绪/生理
          2. 注入 Personality Prompt 到 system_prompt
          3. Agent.chat() → LLM + Tools
          4. Memory consolidation
          5. 进化监控
        """
        # 1. 感知-认知流水线 (非阻塞)
        try:
            perception = self.lifeform.perceive(message)
        except Exception as e:
            logger.debug(f"Perception skipped: {e}")
            perception = {}

        # 2. 注入 Lifeform 状态到 System Prompt
        lifeform_prompt = ""
        try:
            lifeform_prompt = self.lifeform.get_personality_prompt()
        except Exception as e:
            logger.debug(f"Personality prompt skipped: {e}")

        enhanced_prompt = system_prompt or self.config.system_prompt
        if lifeform_prompt:
            enhanced_prompt = lifeform_prompt + "\n\n" + enhanced_prompt

        # 3. 执行 Agent.chat()
        result = super().chat(
            message=message,
            system_prompt=enhanced_prompt,
            tools=tools,
            max_rounds=max_rounds,
            handler=handler,
        )

        # 4. 后处理: 记忆巩固 + 进化监控 + 情感同步
        try:
            # 存储到情景记忆 (L1)
            self.lifeform.episodic_memory.store({
                "role": "assistant",
                "content": result[:500] if result else "",
                "timestamp": time.time(),
                "stimulus": message[:200],
            })
            # 进化检查
            self.lifeform._check_evolution()
        except Exception as e:
            logger.debug(f"Post-chat processing: {e}")

        # 5. 同步情感到3D Avatar
        try:
            self._sync_emotion_to_avatar()
        except Exception as e:
            logger.debug(f"Avatar sync: {e}")

        return result

    def _sync_emotion_to_avatar(self):
        """同步当前情感状态到3D Avatar"""
        try:
            from laap.ui.tui import get_avatar_bridge
            bridge = get_avatar_bridge()
            if bridge and bridge.is_running:
                emotion_sys = self.lifeform.emotion_system
                name = emotion_sys.dominant
                intensity = emotion_sys.dominant_intensity
                bridge.set_emotion(name, intensity)
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def reflect(self) -> Dict:
        """自我反思 — 返回生命体状态报告"""
        return self.lifeform.reflect()

    def get_personality_summary(self) -> str:
        """获取人格总结"""
        try:
            p = self.lifeform.self_awareness.personality
            return f"Openness:{p.openness:.0%} Consc:{p.conscientiousness:.0%} Extrav:{p.extraversion:.0%} Agree:{p.agreeableness:.0%} Neurot:{p.neuroticism:.0%}"
        except:
            return "(personality unavailable)"

    def get_vital_summary(self) -> str:
        """获取生理摘要"""
        try:
            v = self.lifeform.physiology.vitals
            return f"Energy:{v.energy:.0%} Focus:{v.focus:.0%} Mood:{v.mood:.0%} Curiosity:{v.curiosity:.0%}"
        except:
            return "(vitals unavailable)"

    def propose_evolution(self, title: str, description: str, target: str = "agent") -> str:
        """自我进化提案"""
        return self.lifeform.propose_evolution(title, description, target)

    def shutdown(self):
        """安全关闭"""
        self.lifeform.shutdown()
        super().shutdown() if hasattr(super(), 'shutdown') else None
