"""主动建议引擎

ProactiveAdvisor 是 LAAP 2.0 Living Workspace 的核心组件，负责：
1. 装配触发器列表
2. 接收事件并匹配触发器
3. 生成候选建议并调用 sandbox.think() 补充
4. 排序、去重、限流
5. 投递建议到队列
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from laap.sandbox._types import ProjectSnapshot, Suggestion, WorkspaceEvent
from laap.sandbox.container import CognitiveSandbox
from laap.workspace.perception import ProjectPerception
from laap.workspace.triggers import (
    BuildFailureTrigger,
    CommitTrigger,
    FileOpenTrigger,
    IdleTrigger,
    PeriodicTrigger,
    Trigger,
)


class ProactiveAdvisor:
    """主动建议引擎——管理触发器、生成和投递建议。

    核心流程：
    1. evaluate(event) → 匹配触发器 → 生成候选建议
    2. 调用每个 sandbox.think() → 补充建议
    3. _rank_and_dedupe(suggestions) → 排序去重
    4. 限流 → 最多投递 N 条建议
    5. 投递到 SuggestionQueue（如果配置了）

    用法：
        perception = ProjectPerception(root_path="/path/to/project")
        sandboxes = [CognitiveSandbox(...), ...]
        queue = SuggestionQueue(db_path="suggestions.db")
        advisor = ProactiveAdvisor(
            perception=perception,
            sandboxes=sandboxes,
            queue=queue,
            max_suggestions_per_event=3,
            max_suggestions_per_idle=1,
        )
        advisor.evaluate(WorkspaceEvent(event_type="file_open", payload={"file": "src/main.py"}))
    """

    _PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, perception: ProjectPerception,
                 sandboxes: List[CognitiveSandbox],
                 queue: Optional["SuggestionQueue"] = None,
                 max_suggestions_per_event: int = 3,
                 max_suggestions_per_idle: int = 1):
        """
        Args:
            perception: 项目感知器（提供 ProjectSnapshot）
            sandboxes: CognitiveSandbox 列表（用于调用 think() 生成建议）
            queue: 建议队列（用于持久化建议）
            max_suggestions_per_event: 每次事件最多投递建议数
            max_suggestions_per_idle: 空闲触发器最多投递建议数
        """
        self.perception = perception
        self.sandboxes = sandboxes
        self.queue = queue

        self.triggers = [
            FileOpenTrigger(),
            BuildFailureTrigger(),
            IdleTrigger(),
            CommitTrigger(),
            PeriodicTrigger(),
        ]

        self._max_per_event = max_suggestions_per_event
        self._max_per_idle = max_suggestions_per_idle

        self._total_events = 0
        self._total_suggestions = 0
        self._total_deduplicated = 0

    def evaluate(self, event: WorkspaceEvent) -> List[Suggestion]:
        """评估事件并生成建议。

        流程：
        1. 获取当前 ProjectSnapshot（通过 perception.perceive()）
        2. 遍历所有触发器，匹配的触发器生成候选建议
        3. 调用每个 sandbox.think() 补充建议
        4. 排序去重（调用 _rank_and_dedupe）
        5. 限流（根据事件类型）
        6. 投递到队列（如果配置了）
        7. 返回最终建议列表

        Returns:
            已排序去重后的建议列表（已投递）
        """
        self._total_events += 1

        if not event.event_type:
            return []

        snapshot = self.perception.perceive(full=False)

        all_suggestions: List[Suggestion] = []

        for trigger in self.triggers:
            if trigger.matches(event):
                suggestions = trigger.generate_suggestions(snapshot, event)
                all_suggestions.extend(suggestions)

        for sandbox in self.sandboxes:
            suggestion = sandbox.think()
            if suggestion:
                all_suggestions.append(suggestion)

        self._total_suggestions += len(all_suggestions)

        deduplicated = self._rank_and_dedupe(all_suggestions)
        self._total_deduplicated += len(all_suggestions) - len(deduplicated)

        limited = self._apply_rate_limit(deduplicated, event.event_type)

        self._deliver_to_queue(limited)

        return limited

    def _rank_and_dedupe(self, suggestions: List[Suggestion]) -> List[Suggestion]:
        """排序并去重建议。

        排序规则（优先级从高到低）：
        1. priority（critical > high > medium > low）
        2. relevance（高到低）
        3. recency（新到旧，基于 created_at）

        去重规则：
        - 按 task_id（category:target_file）去重
        - 保留优先级最高、relevance 最高的版本
        - 同一 task_id 的建议只保留一条

        Returns:
            排序去重后的建议列表
        """
        if not suggestions:
            return []

        task_map: Dict[str, Suggestion] = {}

        for suggestion in suggestions:
            task_id = suggestion.task_id

            if task_id not in task_map:
                task_map[task_id] = suggestion
            else:
                existing = task_map[task_id]

                if self._is_better(suggestion, existing):
                    task_map[task_id] = suggestion

        result = list(task_map.values())

        result.sort(
            key=lambda s: (
                self._PRIORITY_ORDER.get(s.priority, 4),
                -s.relevance,
                -s.created_at,
            )
        )

        return result

    def _is_better(self, new: Suggestion, existing: Suggestion) -> bool:
        """判断新建议是否比现有建议更好"""
        new_priority = self._PRIORITY_ORDER.get(new.priority, 4)
        existing_priority = self._PRIORITY_ORDER.get(existing.priority, 4)

        if new_priority < existing_priority:
            return True

        if new_priority == existing_priority and new.relevance > existing.relevance:
            return True

        return False

    def _apply_rate_limit(self, suggestions: List[Suggestion],
                          event_type: str) -> List[Suggestion]:
        """应用限流。

        规则：
        - idle 事件：最多保留 max_suggestions_per_idle 条
        - 其他事件：最多保留 max_suggestions_per_event 条
        - 保留优先级最高的前 N 条

        Returns:
            限流后的建议列表
        """
        if not suggestions:
            return []

        if event_type == "idle":
            limit = self._max_per_idle
        else:
            limit = self._max_per_event

        return suggestions[:limit]

    def _deliver_to_queue(self, suggestions: List[Suggestion]) -> None:
        """投递建议到队列（如果配置了）。"""
        if not self.queue or not suggestions:
            return

        for suggestion in suggestions:
            self.queue.push(suggestion)

    def register_trigger(self, trigger: Trigger) -> None:
        """注册自定义触发器。"""
        self.triggers.append(trigger)

    def unregister_trigger(self, trigger_name: str) -> bool:
        """取消注册触发器。返回是否成功。"""
        for i, trigger in enumerate(self.triggers):
            if trigger.name == trigger_name:
                del self.triggers[i]
                return True
        return False

    def stats(self) -> Dict[str, Any]:
        """返回统计信息。"""
        return {
            "total_events": self._total_events,
            "total_suggestions_generated": self._total_suggestions,
            "total_deduplicated": self._total_deduplicated,
            "trigger_count": len(self.triggers),
            "sandbox_count": len(self.sandboxes),
            "has_queue": self.queue is not None,
        }


__all__ = ["ProactiveAdvisor"]
