"""LAAP Sandbox 认知容器

CognitiveSandbox 是 LAAP 2.0 的核心容器，为每个数字生命体提供
完整的认知隔离环境，装配 8 个独立的认知子系统。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._types import ColonyEvent, ProjectSnapshot, SandboxConfig, Suggestion
from .boundary import Boundary
from .colony import ColonyEventBus
from .resource_budget import DegradationLevel, ResourceBudget
from .skill_library import SkillLibrary

try:
    from laap.agi.architecture_dna import create_architecture_dna
    from laap.agi.self_model import create_self_model, EmergentSelfModel
    from laap.agi.world_model import create_world_model, AbstractWorldModel
    from laap.agi.conscious import create_conscious_stream, ConsciousStream
except ImportError:
    raise RuntimeError("AGI modules not available")


@dataclass
class _GoalKeeper:
    sandbox_id: str
    goals: List[Dict[str, Any]] = field(default_factory=list)

    def add_goal(self, title: str, priority: str = "medium") -> str:
        goal_id = f"goal-{uuid.uuid4().hex[:8]}"
        goal = {
            "id": goal_id,
            "title": title,
            "priority": priority,
            "progress": 0.0,
            "created_at": time.time(),
        }
        self.goals.append(goal)
        return goal_id

    def update_goal(self, goal_id: str, **kwargs) -> bool:
        for goal in self.goals:
            if goal["id"] == goal_id:
                for key, value in kwargs.items():
                    if key in ("title", "priority", "progress"):
                        goal[key] = value
                return True
        return False

    def remove_goal(self, goal_id: str) -> bool:
        for i, goal in enumerate(self.goals):
            if goal["id"] == goal_id:
                del self.goals[i]
                return True
        return False

    def list_goals(self) -> List[Dict[str, Any]]:
        return self.goals[:]


class CognitiveSandbox:
    """认知沙箱——数字生命体的完整隔离容器。

    每个沙箱拥有 8 个独立的认知子系统：
    1. identity (ArchitectureDNA) — 先天身份基因
    2. self_model (EmergentSelfModel) — 后天自我模型（完全私有）
    3. world_model (AbstractWorldModel) — 世界模型（完全私有）
    4. memory_stream (ConsciousStream) — 意识流/记忆（完全私有）
    5. goal_keeper — 目标守护（完全私有）
    6. resource_budget (ResourceBudget) — 资源预算（完全私有）
    7. skill_library (SkillLibrary) — 技能库（共享只读引用）
    8. boundary (Boundary) — 边界控制器（完全私有）

    隔离性保证：
    - 自我模型、世界模型、记忆流、目标守护、资源预算、边界均为 per-sandbox 实例
    - 技能库为全局共享只读，不允许沙箱修改
    - 跨沙箱通信必须通过 ColonyEventBus，受 Boundary 过滤
    """

    SNAPSHOT_VERSION = "1.0"
    SNAPSHOT_EXTENSION = ".laapsnap"

    def __init__(self, sandbox_id: str, name: str, role: str,
                 skill_library: SkillLibrary, event_bus: ColonyEventBus,
                 config: Optional[SandboxConfig] = None):
        self.sandbox_id = sandbox_id
        self.name = name
        self.role = role

        self.boundary = Boundary(sandbox_id)
        self.identity = create_architecture_dna(sandbox_id, role=role)
        self.self_model = create_self_model(sandbox_id, agent_name=name)
        self.world_model = create_world_model(sandbox_id, model_type="local")
        self.memory_stream = create_conscious_stream(sandbox_id)

        self.goal_keeper = _GoalKeeper(sandbox_id)

        cfg = config or SandboxConfig(name=name, role=role, sandbox_id=sandbox_id)
        self.resource_budget = ResourceBudget(
            sandbox_id=sandbox_id,
            llm_calls_per_hour=cfg.llm_calls_per_hour,
            cpu_seconds_per_min=cfg.cpu_seconds_per_min,
            memory_mb=cfg.memory_mb,
            inference_time_sec=cfg.inference_time_sec,
        )

        self.skill_library = skill_library
        self.event_bus = event_bus

        self.boundary.register_allowed_egress(["colony_event", "suggestion", "skill_lookup"])

        self.event_bus.subscribe("*", self._on_colony_event)

        # 意识中间件层 — 情感系统与元认知系统
        from laap.cognition.emotion import EmotionSystem
        from laap.cognition.metacognition import MetacognitionSystem
        self.emotion_system = EmotionSystem()
        self.metacognition_system = MetacognitionSystem()

        self._is_active = True
        self._last_perceive_at = 0.0

    def perceive(self, snapshot: ProjectSnapshot) -> None:
        """感知项目状态并注入到世界模型。

        流程：
        1. 更新 world_model（调用 update_from_snapshot）
        2. 写入 memory_stream（记录感知到的状态变化）
        3. 更新 self_model（学习项目特征）
        """
        self.world_model.update_from_snapshot(snapshot)

        summary = snapshot.summary()
        self.memory_stream.experience(
            content=f"Perceived project: {summary['root']} (files={summary['files']}, "
                    f"tech_debt={summary['tech_debt_markers']}, tests={summary['test_cases']})",
            modality="perception",
            intensity=0.6,
            context={"source_module": "perceive", "novelty": 0.3},
        )

        self._last_perceive_at = time.time()

    def think(self) -> Optional[Suggestion]:
        """执行一次思考循环。

        返回：
            Optional[Suggestion] — 生成的主动建议（可能为 None，如果无建议）
            None — 如果资源已降级到 CACHED 或无可执行建议

        流程：
        1. 检查资源预算（get_effective_degradation）
        2. 如果已降级到 CACHED，返回 None
        3. 基于 world_model 和 self_model 生成建议
        4. 通过 Boundary 检查建议是否允许 egress
        5. 如果允许，发布到事件总线并返回建议
        """
        effective_degradation = self.resource_budget.get_effective_degradation()
        if effective_degradation == DegradationLevel.CACHED:
            return None

        suggestion = self._generate_suggestion()
        if not suggestion:
            return None

        if self.boundary.check_egress("suggestion"):
            event = ColonyEvent(
                event_type="suggestion",
                source_sandbox=self.sandbox_id,
                target_sandbox=None,
                payload={"suggestion": json.loads(json.dumps(
                    suggestion.__dict__, default=str
                ))},
            )
            self.event_bus.publish(event)
            return suggestion

        return None

    def _generate_suggestion(self) -> Optional[Suggestion]:
        """基于世界模型状态生成建议（简化实现）。"""
        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return None

        tech_debt = snapshot.tech_debt
        test_state = snapshot.test_state

        if tech_debt.total_markers > 50:
            return Suggestion(
                title="清理技术债务",
                description=f"检测到 {tech_debt.total_markers} 个技术债务标记，建议优先清理热点文件",
                priority="high",
                relevance=0.8,
                category="tech_debt",
                source_sandbox=self.sandbox_id,
                actions=["识别高优先级债务", "制定清理计划", "逐步修复"],
            )

        if test_state.total_cases > 0 and test_state.passed < test_state.total_cases * 0.8:
            return Suggestion(
                title="提升测试覆盖率",
                description=f"测试通过率仅 {test_state.passed}/{test_state.total_cases}，建议补充测试用例",
                priority="medium",
                relevance=0.7,
                category="test_gap",
                source_sandbox=self.sandbox_id,
                actions=["分析失败测试", "补充缺失测试", "修复不稳定测试"],
            )

        if tech_debt.todo_count > 20:
            return Suggestion(
                title="处理 TODO 项",
                description=f"项目中有 {tech_debt.todo_count} 个 TODO 标记待处理",
                priority="medium",
                relevance=0.6,
                category="refactor",
                source_sandbox=self.sandbox_id,
                actions=["按优先级排序", "分批处理"],
            )

        if snapshot.dependencies.outdated:
            return Suggestion(
                title="更新依赖",
                description=f"发现 {len(snapshot.dependencies.outdated)} 个过期依赖",
                priority="low",
                relevance=0.5,
                category="dependency",
                source_sandbox=self.sandbox_id,
                actions=["审查依赖更新", "执行更新", "验证兼容性"],
            )

        return None

    def _on_colony_event(self, event: ColonyEvent) -> None:
        """处理来自 ColonyEventBus 的事件（通过边界过滤）。"""
        if not self._is_active:
            return

        if self.boundary.check_ingress(event.event_type, event.source_sandbox):
            self.memory_stream.experience(
                content=f"Received colony event: {event.event_type} from {event.source_sandbox}",
                modality="perception",
                intensity=0.4,
                context={"source_module": "colony_event"},
            )

    def export_to(self, path: str | Path) -> str:
        """导出当前 sandbox 状态到 .laapsnap 文件（JSON 格式，含 SHA256 校验）。

        序列化 8 个认知子系统状态，文件结构为
        ``{"hash": "<sha256>", "data": {inner_data}}``，
        SHA256 基于 ``json.dumps(inner_data, ensure_ascii=False, indent=2)`` 计算。

        Args:
            path: 目标文件路径（自动追加 .laapsnap 扩展名）

        Returns:
            实际写入的文件路径（含 .laapsnap 扩展名）
        """
        from laap.sandbox.migration import export_sandbox_json
        return export_sandbox_json(self, path)

    @classmethod
    def import_from(
        cls,
        path: str | Path,
        skill_library: Optional[SkillLibrary] = None,
        event_bus: Optional[ColonyEventBus] = None,
    ) -> "CognitiveSandbox":
        """从 .laapsnap 文件导入并重建 sandbox（自动检测 JSON / 二进制格式）。

        - JSON 格式（由 ``export_to`` 生成）：校验 SHA256 与版本号
        - 二进制格式（由 ``migration.export_sandbox`` 生成）：委托给 ``import_sandbox``

        Args:
            path: .laapsnap 文件路径
            skill_library: 可选的 SkillLibrary 实例（未提供则使用默认单例）
            event_bus: 可选的 ColonyEventBus 实例（未提供则新建）

        Returns:
            重建后的 CognitiveSandbox 实例

        Raises:
            ValueError: 文件格式不正确或 SHA256 校验失败或版本不匹配
        """
        from laap.sandbox.migration import import_sandbox, import_sandbox_json, is_json_laapsnap
        # 自动检测文件格式：JSON 格式首字节为 '{'，否则视为二进制格式
        if is_json_laapsnap(path):
            return import_sandbox_json(path, skill_library=skill_library, event_bus=event_bus)
        return import_sandbox(path, skill_library=skill_library, event_bus=event_bus)

    def stats(self) -> Dict[str, Any]:
        """返回沙箱统计信息。"""
        return {
            "sandbox_id": self.sandbox_id,
            "name": self.name,
            "role": self.role,
            "is_active": self._is_active,
            "last_perceive_at": self._last_perceive_at,
            "identity": {"role": self.identity.get("identity", {}).get("role", "unknown")},
            "self_model": self.self_model.stats(),
            "world_model": self.world_model.stats(),
            "memory_stream": self.memory_stream.stats(),
            "goal_keeper": {"goals_count": len(self.goal_keeper.goals)},
            "resource_budget": self.resource_budget.stats(),
            "boundary": self.boundary.stats(),
            "skill_library": {"skills_count": len(self.skill_library.list_skills())},
        }

    def shutdown(self) -> None:
        """安全关闭沙箱。"""
        self._is_active = False
        self.event_bus.unsubscribe("*", self._on_colony_event)


__all__ = ["CognitiveSandbox"]