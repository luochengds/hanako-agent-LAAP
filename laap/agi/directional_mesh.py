"""
LAAP AGI — Directional Agent Mesh (Aether 适配层)

包装方向概念，作为 PSI Driver 与 Aether 编排层之间的轻量桥接。

废弃（移至 Aether 编排层）：
  - DirectionalAgent → AgentCell (actor.py) + register_direction()
  - MeshTopology → ActorSystem 自动路由
  - TaskDirectionEncoder → laap/orchestration/direction.py

保留（本文件）：
  - DirectionalMeshOrchestrator → 轻量包装，隐藏 Aether 细节
  - build_default_mesh() → 构建 LAAP 模块 → 方向映射
  - resolve_task() → 方向匹配 + Kakeya 偏置注入
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

import numpy as np
from laap.orchestration.direction import (
    TaskDirectionEncoder,
    DirectionalCapability,
    DIRECTION_TEMPLATES,
    cosine_similarity,
    resolve_kakeya_bias,
)

logger = logging.getLogger("laap.agi.directional_mesh")


# LAAP 模块 → 方向模板映射
LAAP_DIRECTION_MAP = {
    "causal":    ("reason",    "因果推理核心",        ["因果分析", "反事实推理", "干预模拟"]),
    "memory":    ("remember",  "记忆系统",            ["情景检索", "语义查询", "程序技能"]),
    "world":     ("perceive",  "世界模型",            ["实体模拟", "关系推理", "空间推理"]),
    "self_model":("integrate", "自我模型",            ["经验记录", "技能跟踪", "身份叙事"]),
    "conscious": ("integrate", "意识流",              ["注意力焦点", "情感价值", "体验流"]),
    "planning":  ("plan",      "规划引擎",            ["任务规划", "步骤分解", "资源估计"]),
    "creative":  ("create",    "创意生成",            ["类比迁移", "概念合成", "发散思考"]),
    "meta":      ("meta",      "元认知",              ["自我监控", "策略评估", "认知校准"]),
    "empathy":   ("empathize", "共情推理",            ["情感识别", "需求推断", "关系维护"]),
}


class DirectionalMeshOrchestrator:
    """
    方向性网格编排器（轻量包装层）。

    作为 PSI Driver 与 Aether 编排层的桥接。PSI Driver 调用此接口，
    底层通过 laap.orchestration.direction 工具完成方向编码和匹配。
    """

    def __init__(self):
        self.encoder = TaskDirectionEncoder()
        self._agents: Dict[str, Dict[str, Any]] = {}      # name -> agent info
        self._direction_map: Dict[str, np.ndarray] = {}    # name -> direction vec
        self._initialized = False
        self._task_history: List[Dict[str, Any]] = []

    def build_default_mesh(self, agent_refs: Dict[str, Any]) -> None:
        """
        从 LAAP 认知模块引用构建默认方向映射。

        Args:
            agent_refs: 模块引用字典
        """
        for key, ref in agent_refs.items():
            if key in LAAP_DIRECTION_MAP:
                template_key, label, caps = LAAP_DIRECTION_MAP[key]
                vec = DIRECTION_TEMPLATES.get(template_key, DIRECTION_TEMPLATES["default"]).copy()
                self._agents[key] = {
                    "label": label,
                    "template": template_key,
                    "capabilities": caps,
                    "module_ref": ref,
                    "direction": vec,
                }
                self._direction_map[key] = vec

        self._initialized = True
        logger.info(f"[DirectionalMesh] 注册 {len(self._agents)} 个方向代理")

    def resolve_task(self, task_description: str, top_k: int = 3,
                     min_activation: float = 0.3,
                     external_bias: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """
        解析任务 → 编码方向 → 匹配方向代理。

        Args:
            task_description: 自然语言任务描述
            top_k: 最多返回的代理数
            min_activation: 最小激活分数 0~1
            external_bias: P0 Kakeya 覆盖度偏置

        Returns:
            {task_vector, task_inspect, activated}
        """
        task_vector = self.encoder.encode(task_description)

        # Kakeya 偏置注入
        bias = resolve_kakeya_bias(external_bias)
        if np.any(bias != 0.0):
            task_vector = task_vector + bias * 0.4
            task_vector = np.clip(task_vector, -1.0, 1.0)

        # 方向匹配评分
        scored = []
        for name, vec in self._direction_map.items():
            sim = cosine_similarity(vec, task_vector)
            if sim >= min_activation:
                scored.append((sim, name))

        scored.sort(key=lambda x: -x[0])
        selected = scored[:top_k]

        activated = []
        for score, name in selected:
            info = self._agents.get(name, {})
            activated.append({
                "agent_id": name,
                "label": info.get("label", name),
                "score": round(float(score), 3),
                "direction": [round(float(v), 3) for v in info.get("direction", [0, 0, 0]).tolist()],
                "capabilities": info.get("capabilities", []),
            })

        result = {
            "task_vector": task_vector.tolist(),
            "task_inspect": self.encoder.inspect(task_description),
            "activated": activated,
            "total_evaluated": len(self._direction_map),
        }

        self._task_history.append({
            "task": task_description[:80],
            "activated_count": len(activated),
            "t": import_time(),
        })

        return result

    def stats(self) -> Dict[str, Any]:
        """返回统计信息。"""
        return {
            "registered_agents": len(self._agents),
            "initialized": self._initialized,
            "task_history_count": len(self._task_history),
        }


def import_time():
    """获取当前时间戳（用于 stats 记录，避免顶级 import 问题）。"""
    import time
    return time.time()
