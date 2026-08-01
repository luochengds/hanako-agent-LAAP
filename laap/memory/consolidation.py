"""
LAAP — 记忆巩固引擎

与遗忘引擎互为镜像：遗忘负责"分层沉淀"，巩固负责"提炼升华"。

巩固的三种机制：
    1. 重要性巩固：反复访问/强情绪的记忆，importance 自动上升，
       从而获得更高的激活值，抵御遗忘。
    2. 归纳巩固：把多条相似的情景记忆（episodic）归纳为一条
       语义记忆（semantic）——从"经历"升华为"知识"。
    3. 锁定保护：核心记忆（identity / 宪章级）永不降级，
       即使长期未访问也保持 ACTIVE。

设计依据：人类睡眠期海马体将短期记忆重放、转写至皮层。
我们的 run_consolidation() 就是这个"睡眠转写"过程。
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .forgetting.lifecycle import MemoryLifecycle

logger = logging.getLogger("laap.memory.consolidation")


@dataclass
class ConsolidationReport:
    timestamp: float = field(default_factory=time.time)
    strengthened: int = 0
    induced: int = 0
    protected: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "strengthened": self.strengthened,
            "induced": self.induced,
            "protected": self.protected,
            "notes": self.notes[-50:],
        }


class ConsolidationEngine:
    """记忆巩固引擎。"""

    # 永不遗忘的记忆类型（宪章级保护）
    PROTECTED_TYPES = {"identity", "charter", "oath"}

    def __init__(
        self,
        access_boost: float = 0.02,       # 每次访问的重要性增量
        emotion_boost: float = 0.05,      # 强情绪记忆的重要性增量
        similarity_threshold: float = 0.75,  # 归纳相似度阈值
    ) -> None:
        self.access_boost = access_boost
        self.emotion_boost = emotion_boost
        self.similarity_threshold = similarity_threshold

    def strengthen(
        self,
        importance: float,
        access_count: int,
        valence: float,
        memory_type: str,
    ) -> Dict[str, Any]:
        """计算一条记忆巩固后的重要性。

        - 受保护类型：importance 锁死为 1.0
        - 普通记忆：随访问次数与情绪强度增长，收敛于上限 0.95
        """
        if memory_type in self.PROTECTED_TYPES:
            return {"importance": 1.0, "protected": True}

        boost = access_count * self.access_boost + abs(valence) * self.emotion_boost
        new_importance = min(0.95, importance + boost)
        return {"importance": new_importance, "protected": False}

    def induce(
        self,
        episodic_memories: List[Dict[str, Any]],
        min_cluster: int = 3,
    ) -> List[Dict[str, Any]]:
        """归纳巩固：把相似的情景记忆聚类为语义记忆。

        返回生成的语义记忆条目列表。
        """
        if len(episodic_memories) < min_cluster:
            return []

        # 简单主题聚类：按共享 tags 聚合（可替换为向量聚类）
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for mem in episodic_memories:
            for tag in mem.get("tags", []):
                clusters.setdefault(tag, []).append(mem)

        induced: List[Dict[str, Any]] = []
        for tag, members in clusters.items():
            if len(members) < min_cluster:
                continue
            # 合并内容，生成语义记忆
            combined = " | ".join(m.get("content", "")[:60] for m in members[:5])
            semantic = {
                "id": hashlib.sha1(f"{tag}:{combined}".encode()).hexdigest()[:8],
                "content": f"[归纳自{len(members)}条情景记忆] 主题[{tag}]: {combined}",
                "memory_type": "semantic",
                "tags": [tag, "induced"],
                "importance": max(m.get("importance", 0.5) for m in members),
                "valence": sum(m.get("valence", 0.0) for m in members) / len(members),
                "lifecycle": MemoryLifecycle.ACTIVE.value,
                "source_memory_ids": [m.get("id") for m in members],
                "created_at": time.time(),
                "access_times": [time.time()],
            }
            induced.append(semantic)
        return induced

    def run_consolidation(
        self,
        memories: List[Dict[str, Any]],
        apply: bool = False,
    ) -> ConsolidationReport:
        """执行一轮巩固：强化 + 归纳 + 保护。"""
        report = ConsolidationReport()
        for mem in memories:
            mtype = mem.get("memory_type", "episodic")
            if mtype in self.PROTECTED_TYPES:
                mem["importance"] = 1.0
                mem["lifecycle"] = MemoryLifecycle.ACTIVE.value
                report.protected += 1
                continue

            result = self.strengthen(
                importance=mem.get("importance", 0.5),
                access_count=mem.get("access_count", 0),
                valence=mem.get("valence", 0.0),
                memory_type=mtype,
            )
            if result["importance"] > mem.get("importance", 0.5) + 1e-6:
                mem["importance"] = result["importance"]
                report.strengthened += 1

        episodic = [m for m in memories if m.get("memory_type") == "episodic"]
        induced = self.induce(episodic)
        if induced:
            report.induced = len(induced)
            report.notes.append(
                f"induced {len(induced)} semantic memories from {len(episodic)} episodic"
            )
            if apply:
                memories.extend(induced)
        return report
