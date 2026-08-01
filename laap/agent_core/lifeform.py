"""LAAP Lifeform Core — 数字生命体核心
独创: 生命计算范式 (Living Computation Paradigm)
超越传统Agent框架，将AI Agent视为"数字生命体":
- 生理学: 心跳/呼吸/代谢 (健康监控+节能)
- 内驱力: 饥饿/好奇/安全 (自主探索)
- 感知: 意识流 (持续性上下文感知)
- 成长: 经验积累+能力进化
- 社会: 多Agent社交与协作
"""
from __future__ import annotations
import time, json, logging, threading, random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent_core.lifeform")

class VitalSign(str, Enum):
    ACTIVE = "active"; IDLE = "idle"; SLEEPING = "sleeping"; STRESSED = "stressed"; GROWING = "growing"

@dataclass
class Physiology:
    heartbeat: float = 60.0  # bpm
    energy: float = 100.0    # 0-100
    stress: float = 0.0      # 0-100
    curiosity: float = 50.0  # 0-100
    growth_rate: float = 1.0 # multiplier
    last_interaction: float = 0.0
    total_interactions: int = 0

class LifeformCore:
    """数字生命体核心 — 生理学+内驱力+成长系统"""
    
    def __init__(self, agent=None):
        self.agent = agent
        self.vitals = Physiology()
        self.state = VitalSign.ACTIVE
        self._stream = threading.Thread(target=self._physiology_loop, daemon=True)
        self._running = False
    
    def start(self):
        self._running = True
        self._stream.start()
        logger.info("Lifeform activated")
    
    def stop(self):
        self._running = False
    
    def _physiology_loop(self):
        """生理循环 — 心跳/能量代谢"""
        while self._running:
            time.sleep(10)  # 每10秒更新
            self.vitals.heartbeat = 60.0 + self.vitals.stress * 0.3
            
            # 能量消耗 (休息时消耗少)
            if self.state == VitalSign.ACTIVE:
                self.vitals.energy = max(0, self.vitals.energy - random.uniform(0.5, 1.5))
            elif self.state == VitalSign.SLEEPING:
                self.vitals.energy = min(100, self.vitals.energy + random.uniform(1.0, 3.0))
            
            # 压力衰减
            if self.vitals.stress > 0:
                self.vitals.stress = max(0, self.vitals.stress - 0.5)
            
            # 好奇心变化
            if random.random() < 0.1:
                self.vitals.curiosity += random.uniform(-5, 5)
                self.vitals.curiosity = max(10, min(100, self.vitals.curiosity))
            
            # 状态转换
            now = time.time()
            idle_seconds = now - self.vitals.last_interaction
            if self.vitals.energy < 20:
                self.state = VitalSign.SLEEPING
            elif self.vitals.energy < 40:
                self.state = VitalSign.IDLE
            elif idle_seconds > 3600:
                self.state = VitalSign.SLEEPING
            elif self.vitals.stress > 60:
                self.state = VitalSign.STRESSED
            elif self.vitals.curiosity > 70:
                self.state = VitalSign.GROWING
            else:
                self.state = VitalSign.ACTIVE
    
    def interact(self):
        """交互触发 — 激活生命体"""
        self.vitals.last_interaction = time.time()
        self.vitals.total_interactions += 1
        self.vitals.energy = min(100, self.vitals.energy + 2.0)
        self.vitals.curiosity += 1
        self.state = VitalSign.ACTIVE
    
    def get_status(self) -> dict:
        """获取生命体状态"""
        return {
            "state": self.state.value,
            "heartbeat": round(self.vitals.heartbeat, 1),
            "energy": round(self.vitals.energy, 1),
            "stress": round(self.vitals.stress, 1),
            "curiosity": round(self.vitals.curiosity, 1),
            "growth": round(self.vitals.growth_rate, 2),
            "interactions": self.vitals.total_interactions,
        }
    
    def get_stats(self) -> dict:
        return self.get_status()
