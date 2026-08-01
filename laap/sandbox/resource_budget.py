"""LAAP Sandbox 资源预算管理器

ResourceBudget 负责跟踪每个 Cognitive Sandbox 的资源消耗，
包括 LLM 调用次数、CPU 时间、内存使用、推理时间等。

当资源消耗超过阈值时，自动触发降级策略：
V5（完整认知循环）→ LLM（纯 LLM）→ CACHED（缓存/拒绝）
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional


class ResourceType(str, Enum):
    LLM_CALLS_PER_HOUR = "llm_calls_per_hour"
    CPU_SECONDS_PER_MIN = "cpu_seconds_per_min"
    MEMORY_MB = "memory_mb"
    INFERENCE_TIME_SEC = "inference_time_sec"


class DegradationLevel(str, Enum):
    V5 = "v5"
    LLM = "llm"
    CACHED = "cached"


class ResourceBudget:
    """沙箱资源预算管理器。

    跟踪每个时间窗口内的资源消耗，超限时按 v5 → llm → cached 链降级。
    """

    DEGRADATION_CHAIN = {
        ResourceType.LLM_CALLS_PER_HOUR: [DegradationLevel.V5, DegradationLevel.LLM, DegradationLevel.CACHED],
        ResourceType.CPU_SECONDS_PER_MIN: [DegradationLevel.V5, DegradationLevel.LLM, DegradationLevel.CACHED],
        ResourceType.MEMORY_MB: [DegradationLevel.V5, DegradationLevel.LLM, DegradationLevel.CACHED],
        ResourceType.INFERENCE_TIME_SEC: [DegradationLevel.V5, DegradationLevel.LLM, DegradationLevel.CACHED],
    }

    def __init__(self, sandbox_id: str,
                 llm_calls_per_hour: int = 100,
                 cpu_seconds_per_min: int = 30,
                 memory_mb: int = 512,
                 inference_time_sec: int = 60):
        self.sandbox_id = sandbox_id
        self._limits = {
            ResourceType.LLM_CALLS_PER_HOUR: llm_calls_per_hour,
            ResourceType.CPU_SECONDS_PER_MIN: cpu_seconds_per_min,
            ResourceType.MEMORY_MB: memory_mb,
            ResourceType.INFERENCE_TIME_SEC: inference_time_sec,
        }
        self._consumed = {rt: 0 for rt in ResourceType}
        self._window_started_at = {rt: time.time() for rt in ResourceType}
        self._window_duration_sec = {
            ResourceType.LLM_CALLS_PER_HOUR: 3600,
            ResourceType.CPU_SECONDS_PER_MIN: 60,
            ResourceType.MEMORY_MB: 1,
            ResourceType.INFERENCE_TIME_SEC: 60,
        }
        self._current_degradation = {rt: DegradationLevel.V5 for rt in ResourceType}
        self._degradation_history: List[Dict[str, Any]] = []

    def check(self, resource_type: ResourceType, amount: int = 1) -> bool:
        """检查是否还有预算可消耗（不实际消耗）。"""
        self._maybe_reset_window(resource_type)

        if self._current_degradation[resource_type] == DegradationLevel.CACHED:
            return False

        if resource_type == ResourceType.MEMORY_MB:
            return self._consumed[resource_type] + amount <= self._limits[resource_type]

        return self._consumed[resource_type] + amount <= self._limits[resource_type]

    def consume(self, resource_type: ResourceType, amount: int = 1) -> bool:
        """消耗资源。返回是否成功。如果超限，触发降级并返回 False。"""
        self._maybe_reset_window(resource_type)

        if self._current_degradation[resource_type] == DegradationLevel.CACHED:
            return False

        if resource_type == ResourceType.MEMORY_MB:
            if amount > self._limits[resource_type]:
                self._trigger_degradation(resource_type)
                return False
            self._consumed[resource_type] = amount
            return True

        if self._consumed[resource_type] + amount > self._limits[resource_type]:
            self._trigger_degradation(resource_type)
            return False

        self._consumed[resource_type] += amount
        return True

    def get_degradation_level(self, resource_type: ResourceType) -> DegradationLevel:
        """获取当前降级等级。"""
        return self._current_degradation[resource_type]

    def get_effective_degradation(self) -> DegradationLevel:
        """获取所有资源中最高（最受限）的降级等级。

        规则：取所有资源降级等级中"最低"的（最保守的）。
        例如：LLM=CACHED, CPU=LLM → 返回 CACHED
        """
        level_order = {DegradationLevel.CACHED: 0, DegradationLevel.LLM: 1, DegradationLevel.V5: 2}
        current_levels = list(self._current_degradation.values())
        if not current_levels:
            return DegradationLevel.V5

        return min(current_levels, key=lambda l: level_order[l])

    def reset_window(self, resource_type: Optional[ResourceType] = None) -> None:
        """重置时间窗口（手动或调度器触发）。None 表示重置全部。"""
        if resource_type is None:
            for rt in ResourceType:
                self._consumed[rt] = 0
                self._window_started_at[rt] = time.time()
                self._current_degradation[rt] = DegradationLevel.V5
        else:
            self._consumed[resource_type] = 0
            self._window_started_at[resource_type] = time.time()
            self._current_degradation[resource_type] = DegradationLevel.V5

    def _maybe_reset_window(self, resource_type: ResourceType) -> None:
        """检查并自动重置过期窗口。"""
        now = time.time()
        elapsed = now - self._window_started_at[resource_type]
        if elapsed > self._window_duration_sec[resource_type]:
            self._consumed[resource_type] = 0
            self._window_started_at[resource_type] = now
            self._current_degradation[resource_type] = DegradationLevel.V5

    def _trigger_degradation(self, resource_type: ResourceType) -> DegradationLevel:
        """触发降级。返回新的降级等级。

        规则：从当前等级往下走一级；已是 CACHED 则保持。
        记录到 _degradation_history，并清空该资源的消耗计数。
        """
        chain = self.DEGRADATION_CHAIN[resource_type]
        current = self._current_degradation[resource_type]

        if current == DegradationLevel.CACHED:
            return current

        current_idx = chain.index(current)
        if current_idx < len(chain) - 1:
            new_level = chain[current_idx + 1]
            self._degradation_history.append({
                "timestamp": time.time(),
                "resource": resource_type.value,
                "old_level": current.value,
                "new_level": new_level.value,
                "reason": f"resource_limit_exceeded:{self._limits[resource_type]}",
            })
            self._current_degradation[resource_type] = new_level
            self._consumed[resource_type] = 0
            return new_level

        return current

    def stats(self) -> Dict[str, Any]:
        """返回统计信息。"""
        now = time.time()
        return {
            "sandbox_id": self.sandbox_id,
            "limits": {rt.value: self._limits[rt] for rt in ResourceType},
            "consumed": {rt.value: self._consumed[rt] for rt in ResourceType},
            "degradation_levels": {rt.value: self._current_degradation[rt].value for rt in ResourceType},
            "effective_degradation": self.get_effective_degradation().value,
            "window_started_at": {rt.value: self._window_started_at[rt] for rt in ResourceType},
            "window_duration_sec": {rt.value: self._window_duration_sec[rt] for rt in ResourceType},
            "time_since_window_start": {rt.value: now - self._window_started_at[rt] for rt in ResourceType},
            "degradation_history_count": len(self._degradation_history),
        }