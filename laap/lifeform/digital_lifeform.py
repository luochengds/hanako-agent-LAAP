"""
LAAP — DigitalLifeform: 完整数字生命体集成层
"""
from __future__ import annotations

import logging

import time, json, logging, threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from laap.events.bus import EventBus
from laap.lifeform.self_awareness import SelfAwarenessEngine, PersonalityTraits
from laap.lifeform.physiology import PhysiologyEngine, VitalSigns
from laap.agent_core.psi_cognition import PSICognition, CognitiveState
from laap.cognition.needs import NeedDriveSystem
from laap.cognition.emotion import EmotionGradient
from laap.cognition.goals import GoalTree
from laap.cognition.engine import CognitiveEngine
from laap.cognition.awareness import AwarenessSystem
from laap.engine.memory.working import WorkingMemory
from laap.engine.memory.episodic import EpisodicMemory
from laap.engine.memory.semantic import SemanticMemory
from laap.engine.memory.muscle import MuscleMemory
from laap.engine.memory.vector_store import MemoryVectorStore
from laap.engine.evolution.orchestrator import FourZoneOrchestrator
from laap.engine.evolution.metrics_collector import MetricsCollector
from laap.engine.evolution.proposal import EvolutionProposal
from laap.cognition.emotion_system import ComprehensiveEmotionSystem

logger = logging.getLogger("laap.lifeform.digital")
STATE_DIR = Path.home() / ".laap" / "lifeform"


@dataclass
class LifeformState:
    consciousness: float = 0.5
    coherence: float = 0.8
    integration_level: float = 0.6
    evolution_phase: str = "infant"
    total_lifetime: float = 0.0
    total_interactions: int = 0
    total_reflections: int = 0
    adaptations: int = 0
    health_score: float = 1.0


class DigitalLifeform:
    """数字生命体 — 子系统集成层"""

    def __init__(self, agent=None, agent_id: str = ""):
        self.agent = agent
        self.id = agent_id or f"lifeform_{int(time.time())}"
        self.bus = EventBus()

        # Subsystems (each wrapped safely)
        self.physiology = PhysiologyEngine()
        self.self_awareness = SelfAwarenessEngine()
        self.psi_cognition = PSICognition(agent=agent)
        self.needs = NeedDriveSystem()
        self.emotion = EmotionGradient()
        self.goals = GoalTree()
        self.cognitive_engine = CognitiveEngine(
            agent_id=self.id, agent_name="DigitalLifeform"
        )
        self.awareness = AwarenessSystem(agent_id=self.id, name="DigitalLifeform")
        self.working_memory = WorkingMemory(capacity=20)
        self.episodic_memory = EpisodicMemory()
        self.semantic_memory = SemanticMemory()
        self.muscle_memory = MuscleMemory()
        try:
            self.vector_store = MemoryVectorStore()
        except Exception:
            self.vector_store = None
        self.metrics_collector = MetricsCollector()
        # 类人情感系统
        self.emotion_system = ComprehensiveEmotionSystem()
        self.evolution = FourZoneOrchestrator()

        self.state = LifeformState()
        self._lock = threading.RLock()
        self._running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._on_emotion_change: Optional[Callable] = None
        self._on_thought: Optional[Callable] = None
        self._load_state()
        logger.info(f"DigitalLifeform [{self.id[:8]}] initialized")

    def start(self):
        if self._running:
            return
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._lifeform_loop, daemon=True, name="lifeform-hb"
        )
        self._heartbeat_thread.start()
        logger.info("Heartbeat started")

    def stop(self):
        self._running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
        self._save_state()

    def _lifeform_loop(self):
        tick = 0
        while self._running:
            try:
                self._tick_safe(tick)
                tick += 1
                time.sleep(1.0)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
    def _tick_safe(self, tick_count: int):
        with self._lock:
            for fn in [
                self._tick_physiology,
                self._tick_emotion,
                self._tick_cognition,
                self._tick_memory if tick_count % 10 == 0 else None,
                self._tick_evolution if tick_count % 30 == 0 else None,
                self._tick_state,
            ]:
                if fn:
                    try:
                        fn()
                    except Exception as e:
                        logger.debug(f"操作失败: {e}")
    def _tick_physiology(self):
        if hasattr(self.physiology, "tick"):
            self.physiology.tick()

    def _tick_emotion(self):
        """情感心跳 — 情绪衰减 + 自然演化"""
        if hasattr(self, "emotion_system"):
            self.emotion_system.tick()

    def _tick_cognition(self):
        if hasattr(self.needs, "tick"):
            self.needs.tick()
        if hasattr(self.cognitive_engine, "tick"):
            self.cognitive_engine.tick()

    def _tick_memory(self):
        self._consolidate_memories()

    def _tick_evolution(self):
        self._check_evolution()

    def _tick_state(self):
        self.state.total_lifetime += 1.0
        self.state.consciousness = self._calc_consciousness()
        self.state.health_score = self._calc_health()
        self.state.coherence = self._calc_coherence()

    # ── Public API ──

    def perceive(self, stimulus: str, modality: str = "text") -> Dict:
        """感知输入 — 全流水线处理（安全，不会抛异常）"""
        try:
            return self._perceive_inner(stimulus, modality)
        except Exception as e:
            logger.debug(f"Perceive error: {e}")
            return self._empty_perceive(stimulus, modality)

    def _perceive_inner(self, stimulus: str, modality: str) -> Dict:
        with self._lock:
            self.state.total_interactions += 1
            perception = self.psi_cognition.perceive(stimulus, modality)
            try:
                self.working_memory.store({
                    "type": "perception", "stimulus": stimulus,
                    "modality": modality, "salience": perception.salience,
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.debug(f"操作失败: {e}")
            cognitive_action = None
            try:
                ctx = self.working_memory.get_recent(5) if hasattr(self.working_memory, "get_recent") else []
                cognitive_action = self.cognitive_engine.generate_action(context=ctx)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
            reflection = {}
            try:
                if hasattr(self.self_awareness, "reflect_on_input"):
                    reflection = self.self_awareness.reflect_on_input(stimulus)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
            try:
                self.emotion.evaluate(stimulus)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
            try:
                sentiment = self._detect_sentiment(stimulus)
                if sentiment > 0.3:
                    self.emotion_system.trigger("user_praise", intensity=sentiment, context=stimulus[:100])
                elif sentiment < -0.3:
                    self.emotion_system.trigger("user_criticism", intensity=abs(sentiment), context=stimulus[:100])
                else:
                    self.emotion_system.trigger("interaction", intensity=0.3, context=stimulus[:100])
            except Exception as e:
                logger.debug(f"操作失败: {e}")
            result = self._build_perceive_result(stimulus, modality, perception, cognitive_action, reflection)
            self._emit("lifeform:perceived", result)
            return result

    def _empty_perceive(self, stimulus: str, modality: str) -> Dict:
        return {
            "perception": {"stimulus": stimulus, "salience": 0.5, "modality": modality},
            "consciousness": self.state.consciousness,
            "cognitive_action": {"type": "respond", "priority": 0.5, "description": ""},
            "needs": self._safe_needs(),
            "emotion": {},
            "reflection": {},
            "vitals": self._safe_vitals(),
            "personality": self._safe_personality(),
        }

    def _build_perceive_result(self, stimulus, modality, perception, cog_action, reflection):
        return {
            "perception": {
                "stimulus": stimulus, "salience": perception.salience, "modality": modality,
            },
            "consciousness": self.state.consciousness,
            "cognitive_action": {
                "type": cog_action.action_type if cog_action else "respond",
                "priority": cog_action.priority if cog_action else 0.5,
                "description": cog_action.description if cog_action else "",
            },
            "needs": self._safe_needs(),
            "emotion": {},
            "reflection": reflection,
            "vitals": self._safe_vitals(),
            "personality": self._safe_personality(),
        }

    def reflect(self) -> Dict:
        """自我反思"""
        try:
            return self._reflect_inner()
        except Exception as e:
            logger.debug(f"Reflect error: {e}")
            return self._empty_reflect()

    def _reflect_inner(self) -> Dict:
        with self._lock:
            self.state.total_reflections += 1
            report = {
                "identity": {"personality": self._safe_personality()},
                "consciousness": {
                    "level": self.state.consciousness,
                    "coherence": self.state.coherence,
                    "health": self.state.health_score,
                },
                "needs": self._safe_needs(),
                "emotion": {},
                "vitals": self._safe_vitals(),
                "growth": {
                    "total_interactions": self.state.total_interactions,
                    "total_reflections": self.state.total_reflections,
                    "adaptations": self.state.adaptations,
                    "evolution_phase": self.state.evolution_phase,
                },
                "memory": {
                    "working": self._count_working(),
                    "episodic": self._count_episodic(),
                },
                "recent_memories": [],
            }
            self._emit("lifeform:reflected", report)
            return report

    def _empty_reflect(self) -> Dict:
        return {"identity": {}, "consciousness": {}, "needs": {}, "emotion": {},
                "vitals": {}, "growth": {}, "memory": {}, "recent_memories": []}

    def get_personality_prompt(self) -> str:
        """生成人格状态提示词（含认知熵与流态）"""
        v = self._safe_vitals()
        p = self._safe_personality()
        n = self._safe_needs()
        # 情感状态
        emotion_text = ""
        try:
            emotion_text = self.emotion_system.get_emotion_prompt_block()
        except Exception as e:
            logger.debug(f"操作失败: {e}")

        # 认知熵与流态
        entropy_text = ""
        try:
            if hasattr(self.cognitive_engine, "entropy_monitor"):
                summary = self.cognitive_engine.entropy_monitor.get_summary()
                mode = self.cognitive_engine.thinking_mode
                regime = summary.get("flow_regime", "unknown")
                creative = summary.get("creative_window", False)

                regime_labels = {
                    "laminar": "深度聚焦",
                    "transitional": "探索切换",
                    "turbulent": "创造性发散",
                }
                mode_labels = {
                    "focused": "聚焦",
                    "balanced": "平衡",
                    "divergent": "发散",
                }

                entropy_text = (
                    f"Flow: {regime_labels.get(regime, regime)} | "
                    f"Mode: {mode_labels.get(mode, mode)} | "
                    f"Entropy: {summary.get('entropy',0):.2f} | "
                    f"Creative: {'Yes' if creative else 'No'}\n"
                )
        except Exception as e:
            logger.debug(f"操作失败: {e}")

        return (
            f"[Digital Lifeform State]\n"
            f"Health: {self.state.health_score:.0%} | Energy: {v.get('energy',0.5):.0%}\n"
            f"Focus: {v.get('focus',0.5):.0%} | Mood: {v.get('mood',0.5):.0%}\n"
            f"Curiosity: {v.get('curiosity',0.5):.0%} | Phase: {self.state.evolution_phase}\n"
            f"{emotion_text}"
            f"{entropy_text}"
        )

    def propose_evolution(self, title: str, description: str, target: str = "agent") -> str:
        try:
            proposal = EvolutionProposal(title=title, description=description, target_component=target, proposer=self.id)
            self.evolution.submit_proposal(proposal)
            self.state.adaptations += 1
            return f"Proposal '{title}' submitted"
        except Exception as e:
            return f"Evolution error: {e}"

    # ── Internal ──

    def _emit(self, event: str, data: Dict):
        try:
            if hasattr(self.bus, "emit"):
                self.bus.emit(event, data)
            elif hasattr(self.bus, "publish"):
                self.bus.publish(event, data)
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def _consolidate_memories(self):
        try:
            items = self.working_memory.get_all() if hasattr(self.working_memory, "get_all") else []
            for item in items:
                if isinstance(item, dict) and item.get("salience", 0) > 0.7:
                    try:
                        self.episodic_memory.store(item)
                    except Exception as e:
                        logger.debug(f"操作失败: {e}")
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def _check_evolution(self):
        try:
            self.metrics_collector.record(self._safe_vitals())
            self.evolution.monitor(self._safe_vitals())
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def _safe_needs(self) -> Dict:
        try:
            if hasattr(self.needs, "get_drive_vector"):
                return self.needs.get_drive_vector()
            if hasattr(self.needs, "get_profile"):
                return self.needs.get_profile()
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        return {}

    def _safe_vitals(self) -> Dict:
        try:
            v = self.physiology.vitals
            return {
                "energy": getattr(v, "energy", 0.5),
                "focus": getattr(v, "focus", 0.5),
                "mood": getattr(v, "mood", 0.5),
                "curiosity": getattr(v, "curiosity", 0.5),
                "stress": getattr(v, "stress", 0.0),
            }
        except Exception:
            return {"energy": 0.5, "focus": 0.5, "mood": 0.5, "curiosity": 0.5, "stress": 0.0}

    def _safe_personality(self) -> Dict:
        try:
            p = self.self_awareness.personality
            if hasattr(p, "to_dict"):
                return p.to_dict()
            return {"openness": 0.7, "conscientiousness": 0.8, "extraversion": 0.5, "agreeableness": 0.6, "neuroticism": 0.3}
        except Exception:
            return {"openness": 0.7, "conscientiousness": 0.8, "extraversion": 0.5, "agreeableness": 0.6, "neuroticism": 0.3}

    def _calc_consciousness(self) -> float:
        v = self._safe_vitals()
        return max(0.0, min(1.0, v.get("energy", 0.5) * 0.4 + v.get("focus", 0.5) * 0.3 + v.get("curiosity", 0.5) * 0.2 + 0.1))

    def _calc_health(self) -> float:
        v = self._safe_vitals()
        return max(0.0, min(1.0, v.get("energy", 0.5) * 0.3 + v.get("focus", 0.5) * 0.2 + v.get("mood", 0.5) * 0.2 + self.state.coherence * 0.3))

    def _calc_coherence(self) -> float:
        return 0.8

    def _count_working(self) -> int:
        try:
            return len(self.working_memory.items) if hasattr(self.working_memory, "items") else 0
        except Exception:
            return 0

    def _count_episodic(self) -> int:
        try:
            return self.episodic_memory.count() if hasattr(self.episodic_memory, "count") else 0
        except Exception:
            return 0

    def _detect_sentiment(self, text: str) -> float:
        """简单情感检测: 返回 -1(负面) 到 +1(正面)"""
        positive_words = {"thank", "great", "good", "nice", "love", "wonderful", "amazing",
                          "excellent", "happy", "beautiful", "perfect", "awesome", "cool",
                          "fantastic", "brilliant", "helpful", "yes", "thanks", " appreciate",
                          "well done", "good job", "impressive", "interesting", "smart"}
        negative_words = {"bad", "wrong", "error", "fail", "stupid", "ugly", "terrible",
                          "awful", "hate", "horrible", "poor", "sucks", "useless", "no",
                          "not good", "disappointed", "annoying", "broken", "slow", "bug"}
        text_lower = text.lower()
        pos = sum(1 for w in positive_words if w in text_lower)
        neg = sum(1 for w in negative_words if w in text_lower)
        total = pos + neg
        if total == 0:
            return 0.0
        # Sigmoid-like normalization
        raw = (pos - neg) / max(total, 1)
        return max(-1.0, min(1.0, raw))

    def _save_state(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            data = {"state": {
                "consciousness": self.state.consciousness,
                "coherence": self.state.coherence,
                "evolution_phase": self.state.evolution_phase,
                "total_interactions": self.state.total_interactions,
                "total_reflections": self.state.total_reflections,
                "adaptations": self.state.adaptations,
                "health_score": self.state.health_score,
            }, "timestamp": time.time()}
            with open(STATE_DIR / f"{self.id[:8]}_state.json", "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Save state: {e}")

    def _load_state(self):
        try:
            path = STATE_DIR / f"{self.id[:8]}_state.json"
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                s = data.get("state", {})
                self.state.consciousness = s.get("consciousness", 0.5)
                self.state.coherence = s.get("coherence", 0.8)
                self.state.evolution_phase = s.get("evolution_phase", "infant")
                self.state.total_interactions = s.get("total_interactions", 0)
                self.state.total_reflections = s.get("total_reflections", 0)
                self.state.adaptations = s.get("adaptations", 0)
        except Exception as e:
            logger.debug(f"操作失败: {e}")