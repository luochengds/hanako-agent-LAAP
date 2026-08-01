"""PSI Cognition — LAAP独有认知架构
基于 PSI (Perception-Selection-Integration) 理论，三层认知架构：
1. Perception Layer — 感知输入/特征提取
2. Selection Layer — 意图选择/注意力机制  
3. Integration Layer — 认知整合/行为决策

这比传统ReAct更接近人类认知，是LAAP作为"数字生命体"的独特优势
"""
from __future__ import annotations
import time, json, logging, threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.psi_cognition")

class CognitiveState(Enum):
    PERCEIVE = "perceive"; SELECT = "select"; INTEGRATE = "integrate"
    ACT = "act"; LEARN = "learn"; REST = "rest"

@dataclass
class Perception:
    stimulus: str = ""; salience: float = 0.0; modality: str = "text"
    timestamp: float = 0.0; context: Dict = field(default_factory=dict)

@dataclass
class Intention:
    id: str = ""; goal: str = ""; priority: float = 0.5
    urgency: float = 0.0; selected: bool = False; plan: List[str] = field(default_factory=list)

@dataclass
class CognitiveIntegration:
    state: CognitiveState = CognitiveState.PERCEIVE
    confidence: float = 0.0; coherence: float = 0.0
    emotional_valence: float = 0.0; arousal: float = 0.5

class PSICognition:
    """PSI认知引擎 — 三层认知架构"""
    
    def __init__(self, agent=None):
        self.agent = agent
        self.state = CognitiveState.PERCEIVE
        self._perceptions: List[Perception] = []
        self._intentions: List[Intention] = []
        self._integration = CognitiveIntegration()
        self._attention_focus: str = ""
        self._short_term: Dict = {}
        self._stats = {"perceptions": 0, "intentions": 0, "acts": 0, "learns": 0}
        self._lock = threading.RLock()
    
    def perceive(self, stimulus: str, modality: str = "text") -> Perception:
        """感知层 — 处理输入"""
        p = Perception(stimulus=stimulus, modality=modality,
                       salience=self._calc_salience(stimulus), timestamp=time.time())
        with self._lock:
            self._perceptions.append(p)
            self._stats["perceptions"] += 1
            if len(self._perceptions) > 50:
                self._perceptions = self._perceptions[-50:]
        self.state = CognitiveState.PERCEIVE
        return p
    
    def _calc_salience(self, stimulus: str) -> float:
        """计算刺激显著性 (0-1)"""
        urgency_words = ["urgent", "紧急", "help", "danger", "error", "crash",
                         "现在", "马上", "立刻", "important", "重要"]
        salience = 0.3
        for w in urgency_words:
            if w in stimulus.lower():
                salience += 0.1
        return min(salience, 1.0)
    
    def select_intention(self, goal: str, priority: float = 0.5, urgency: float = 0.0) -> Intention:
        """选择层 — 意图选择与优先级排序"""
        intention = Intention(id=f"int_{int(time.time()*1000)}", goal=goal,
                              priority=priority, urgency=urgency)
        with self._lock:
            self._intentions.append(intention)
            self._stats["intentions"] += 1
            # 按优先级+紧迫度排序
            self._intentions.sort(key=lambda x: -(x.priority * 0.6 + x.urgency * 0.4))
            if len(self._intentions) > 20:
                self._intentions = self._intentions[:20]
        self.state = CognitiveState.SELECT
        return intention
    
    def integrate(self) -> CognitiveIntegration:
        """整合层 — 认知整合与决策"""
        self._integration.state = CognitiveState.INTEGRATE
        
        # 计算认知一致性 (coherence)
        if self._perceptions and self._intentions:
            self._integration.coherence = min(1.0, len(self._intentions) / max(len(self._perceptions), 1))
        
        # 计算置信度
        self._integration.confidence = min(1.0, self._integration.coherence * 0.7 + self._calc_salience(self._perceptions[-1].stimulus if self._perceptions else "") * 0.3)
        
        # 情感状态 (应急响应调节)
        if self._intentions:
            top_urgency = self._intentions[0].urgency
            self._integration.arousal = 0.3 + top_urgency * 0.7
            self._integration.emotional_valence = 0.5 - (top_urgency * 0.3)
        
        self.state = CognitiveState.INTEGRATE
        return self._integration
    
    def decide(self, stimulus: str) -> Tuple[str, CognitiveState]:
        """完整认知决策循环: 感知→选择→整合→行动"""
        self.perceive(stimulus)
        
        # 自动选择意图
        if not self._intentions:
            self.select_intention(stimulus[:50], urgency=0.5)
        
        self.integrate()
        self.state = CognitiveState.ACT
        self._stats["acts"] += 1
        
        # 选择最高优先级的意图
        if self._intentions:
            top = self._intentions[0]
            top.selected = True
            return top.goal, CognitiveState.ACT
        
        return "unknown", CognitiveState.ACT
    
    def learn(self, outcome: str, success: bool):
        """学习层 — 从结果学习"""
        self.state = CognitiveState.LEARN
        self._stats["learns"] += 1
        if self._intentions:
            last = self._intentions[-1]
            # 简单的Q值更新
            if success:
                last.priority = min(1.0, last.priority * 1.1)
            else:
                last.priority = max(0.1, last.priority * 0.9)
    
    def rest(self):
        """休息 — 认知重置"""
        self.state = CognitiveState.REST
        if len(self._perceptions) > 10:
            self._perceptions = self._perceptions[-5:]
    
    def get_attention(self) -> str:
        """获取当前注意焦点"""
        return self._attention_focus or (self._intentions[0].goal if self._intentions else "")
    
    def get_stats(self) -> dict:
        return dict(self._stats, state=self.state.value, perceptions=len(self._perceptions),
                    intentions=len(self._intentions), coherence=round(self._integration.coherence, 2),
                    confidence=round(self._integration.confidence, 2))
