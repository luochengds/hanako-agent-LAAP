"""
Hanako 集成模块 — OpenForge RL 训练管道接入点

将 Phase 1 (RolloutCollector), Phase 2 (TrainingOrchestrator),
Phase 3 (TrajectoryBuilder + RewardAdapter) 整合为一个可配置的训练管道,
通过 Hanako Agent 配置自动加载。

集成方式:
  1. AgentConfig 新增 training 配置段 (通过 config.yaml)
  2. 在 Agent 初始化阶段调用 integrate_training(agent)
  3. integrate_training 根据配置自动:
     - 创建并挂载 RolloutCollector (采集层)
     - 创建 TrainingOrchestrator (编排层, 可选)
     - 创建 TrajectoryBuilder (训练数据层, 可选)
  4. 提供便捷 API: 导出轨迹、查看状态、启停控制

Hanako config.yaml 新增配置段:
```yaml
training:
  enabled: false                          # 总开关
  rollout_collector: true                 # 采集层开关
  trajectory_output: "./training_data"    # 轨迹输出目录
  auto_export: false                      # 是否自动导出
  max_concurrent: 4                       # 最大并发 rollout 数 (Phase 2)
  reward_weights:                         # 奖励权重 (Phase 3)
    fitness: 0.30
    stability: 0.15
    task_completion: 0.35
    user_feedback: 0.20
```
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.training.integration")


# ══════════════════════════════════════════════════════════════════
# TrainingConfig — AgentConfig 中 training 段的类型定义
# ══════════════════════════════════════════════════════════════════

@dataclass
class TrainingConfig:
    """训练管道配置。

    嵌入在 AgentConfig 或 Hanako config.yaml 的 training 段中。
    """

    enabled: bool = False
    """总开关。关闭时所有训练组件不初始化。"""

    rollout_collector: bool = True
    """采集层开关。启用后在 Agent.chat() 时自动采集交互数据。"""

    trajectory_output: str = ""
    """轨迹输出目录。空字符串表示使用默认路径 (data_dir/trajectories/)。"""

    auto_export: bool = False
    """自动导出。启用后每次 episode 结束自动写入 JSONL。"""

    auto_export_format: str = "jsonl"
    """导出格式: jsonl / metadata + jsonl。"""

    max_concurrent: int = 4
    """最大并发 rollout 数 (Phase 2 TrainingOrchestrator)。"""

    reward_weights: Optional[Dict[str, float]] = None
    """奖励权重 (Phase 3 RewardAdapter)。None = 使用默认权重。"""

    def __post_init__(self) -> None:
        if self.reward_weights is None:
            self.reward_weights = {
                "fitness": 0.30,
                "stability": 0.15,
                "task_completion": 0.35,
                "user_feedback": 0.20,
            }


# ══════════════════════════════════════════════════════════════════
# TrainingIntegration — 运行时集成状态
# ══════════════════════════════════════════════════════════════════

class TrainingIntegration:
    """训练管道运行时集成管理器。

    在 Agent 初始化时由 integrate_training() 创建并挂载到 agent 上。
    可通过 agent.training 访问。

    提供的方法:
      - training.start_episode()       — 开始采集
      - training.export_trajectories() — 导出轨迹
      - training.status()              — 状态摘要
      - training.set_enabled(on/off)   — 运行时启停
    """

    def __init__(self, config: TrainingConfig,
                 agent: Any = None,
                 data_dir: str = ""):
        """
        Args:
            config: TrainingConfig 配置对象.
            agent: 可选的 Agent 实例引用.
            data_dir: 数据目录 (用于轨迹存储).
        """
        self.config = config
        self.agent = agent
        self.data_dir = data_dir

        # Phase 1: RolloutCollector
        self.collector = None
        if config.rollout_collector and config.enabled:
            from laap.training.rollout_collector import RolloutCollector, create_collector
            self.collector = create_collector(
                enabled=True,
                episode_metadata={"agent_id": getattr(agent, '_agent_id', '')}
                if agent else None,
            )
            logger.info("RolloutCollector initialized and attached")

        # Phase 2: TrainingOrchestrator (惰性初始化)
        self.orchestrator = None
        self._orchestrator_initialized = False

        # Phase 3: TrajectoryBuilder + RewardAdapter
        self.builder = None
        if config.enabled:
            from laap.training.builder import create_builder
            self.builder = create_builder(weights=config.reward_weights)
            logger.info(f"TrajectoryBuilder initialized with weights: {config.reward_weights}")

        # 导出目录
        self.export_dir = config.trajectory_output or os.path.join(
            data_dir or os.path.expanduser("~/.laap"), "trajectories"
        )
        if config.enabled:
            os.makedirs(self.export_dir, exist_ok=True)

        self._episode_count = 0
        self._export_count = 0

    # ── 采集生命周期 ─────────────────────────────────────────

    def start_episode(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """开始一个新的采集 episode。

        委托给 RolloutCollector.start_episode()。
        """
        if not self.collector or not self.collector.enabled:
            return ""

        ep_metadata = dict(metadata or {})
        ep_metadata.setdefault("episode_number", self._episode_count + 1)
        eid = self.collector.start_episode(metadata=ep_metadata)
        if eid:
            self._episode_count += 1
            logger.debug(f"Episode started: {eid} (#{self._episode_count})")
        return eid

    def end_episode(self, status: str = "completed",
                    final_reward: Optional[float] = None) -> Optional[str]:
        """结束当前 episode 并可选自动导出。"""
        if not self.collector:
            return None

        tid = self.collector.end_episode(status=status, final_reward=final_reward)

        if tid and self.config.auto_export and self.builder:
            self._auto_export()

        return tid

    def record_reward(self, value: float, source: str = "",
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        """记录奖励信号 (委托给 RolloutCollector)。"""
        if self.collector:
            self.collector.record_reward(value, source=source, metadata=metadata)

    # ── 导出 ─────────────────────────────────────────────────

    def export_trajectories(self, path: Optional[str] = None,
                            compute_advantages: bool = True) -> int:
        """导出当前所有轨迹为 JSONL 训练数据。

        Args:
            path: 输出文件路径. 默认 auto-generate.
            compute_advantages: 是否计算 GRPO 优势值.

        Returns:
            导出的样本数.
        """
        if not self.collector or not self.builder:
            logger.warning("RolloutCollector or TrajectoryBuilder not available")
            return 0

        trajectories = self.collector.get_trajectories()
        if not trajectories:
            logger.info("No trajectories to export")
            return 0

        # 生成输出路径
        if not path:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.export_dir, f"training_{timestamp}.jsonl")

        count = self.builder.export_jsonl(
            trajectories, path,
            compute_advantages=compute_advantages,
            filter_valid=True,
        )

        # 导出元数据
        if count > 0:
            records = self.builder.build_batch(
                trajectories, compute_advantages=compute_advantages
            )
            meta_path = path.replace(".jsonl", "_metadata.json")
            self.builder.export_training_metadata(meta_path, trajectories, records)

        self._export_count += count
        logger.info(f"Exported {count} training records to {path}")
        return count

    def _auto_export(self) -> None:
        """自动导出 (config.auto_export 启用时调用)。"""
        try:
            self.export_trajectories()
        except Exception as e:
            logger.error(f"Auto-export failed: {e}")

    # ── 运行时启停 ───────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        """运行时启停采集。"""
        self.config.enabled = enabled
        if self.collector:
            self.collector.set_enabled(enabled)
        logger.info(f"Training integration {'enabled' if enabled else 'disabled'}")

    @property
    def enabled(self) -> bool:
        """采集是否启用。"""
        return self.config.enabled and (self.collector is not None)

    # ── 编排器 (惰性初始化) ─────────────────────────────────

    def get_orchestrator(self):
        """获取或惰性创建 TrainingOrchestrator。"""
        if not self._orchestrator_initialized and self.config.enabled:
            try:
                from laap.training.orchestrator import create_orchestrator
                self.orchestrator = create_orchestrator(
                    max_concurrent=self.config.max_concurrent,
                    data_dir=os.path.join(self.data_dir, "rollout_tmp")
                    if self.data_dir else None,
                )
                logger.info(
                    f"TrainingOrchestrator initialized "
                    f"(max_concurrent={self.config.max_concurrent})"
                )
            except Exception as e:
                logger.warning(f"TrainingOrchestrator init failed: {e}")
            self._orchestrator_initialized = True
        return self.orchestrator

    # ── 状态查询 ─────────────────────────────────────────────

    def status(self) -> dict:
        """训练管道完整状态摘要。"""
        collector_status = {}
        if self.collector:
            collector_status = self.collector.summary()

        orchestrator_status = {}
        if self._orchestrator_initialized and self.orchestrator:
            orchestrator_status = self.orchestrator.status()

        builder_stats = {}
        if self.builder:
            adapter = self.builder.reward_adapter
            builder_stats = {
                "weights": adapter.weights,
            }

        return {
            "enabled": self.config.enabled,
            "rollout_collector": {
                "active": collector_status.get("active", False),
                "total_trajectories": collector_status.get("total_trajectories", 0),
                "total_tokens": collector_status.get("total_tokens_collected", 0),
            },
            "training_orchestrator": {
                "initialized": self._orchestrator_initialized,
                "running": orchestrator_status.get("running", 0),
                "completed": orchestrator_status.get("completed", 0),
            },
            "trajectory_builder": {
                "weights": builder_stats.get("weights", {}),
            },
            "export": {
                "directory": self.export_dir,
                "auto_export": self.config.auto_export,
                "total_exported": self._export_count,
            },
            "episodes": {
                "total": self._episode_count,
            },
        }

    def reset(self) -> None:
        """重置所有采集数据。"""
        if self.collector:
            self.collector.reset()
        self._episode_count = 0
        self._export_count = 0
        logger.info("Training integration reset")


# ══════════════════════════════════════════════════════════════════
# 集成函数 — 从 AgentConfig 或 dict 初始化
# ══════════════════════════════════════════════════════════════════

def integrate_training(agent: Any,
                       config_dict: Optional[Dict[str, Any]] = None,
                       data_dir: str = "") -> Optional[TrainingIntegration]:
    """将训练管道集成到 Agent 实例中。

    在 Agent 初始化阶段调用 (通常在 memory/tools 初始化之后)。
    将 TrainingIntegration 实例作为 agent.training 挂载。

    Args:
        agent: 要集成的 Agent 实例.
        config_dict: 训练配置字典 (对应 Hanako config.yaml 的 training 段).
                     若为 None, 尝试从 agent.config 中读取.
        data_dir: 数据目录.

    Returns:
        TrainingIntegration 实例, 若未启用则返回 None.
    """
    if config_dict is None:
        config_dict = getattr(agent, 'training_config', None) or {}

    training_config = _dict_to_training_config(config_dict)

    if not training_config.enabled:
        logger.debug("Training integration skipped (disabled)")
        return None

    integration = TrainingIntegration(
        config=training_config,
        agent=agent,
        data_dir=data_dir,
    )

    # 挂载到 agent
    agent.training = integration

    # 如果开启了采集, 自动开始第一个 episode
    if training_config.rollout_collector and integration.collector:
        integration.start_episode(metadata={
            "agent_name": getattr(agent, 'config', None) and agent.config.name,
            "agent_mode": getattr(agent, 'mode', None) and agent.mode.value,
        })

    logger.info(
        f"Training integration complete: "
        f"collector={training_config.rollout_collector}, "
        f"max_concurrent={training_config.max_concurrent}"
    )
    return integration


def enable_training_config(config: Any,
                           enabled: bool = True,
                           rollout_collector: bool = True,
                           max_concurrent: int = 4,
                           auto_export: bool = False,
                           **kwargs) -> None:
    """在 AgentConfig 上启用训练配置。

    用法:
        >>> config = AgentConfig()
        >>> enable_training_config(config, enabled=True, max_concurrent=8)
        >>> agent = Agent(config=config)
        >>> integrate_training(agent)  # 自动读取 config.training
    """
    if not hasattr(config, 'training'):
        config.training = TrainingConfig()

    config.training.enabled = enabled
    config.training.rollout_collector = rollout_collector
    config.training.max_concurrent = max_concurrent
    config.training.auto_export = auto_export

    for k, v in kwargs.items():
        if hasattr(config.training, k):
            setattr(config.training, k, v)

    logger.info(
        f"Training config enabled on {config.__class__.__name__}: "
        f"enabled={enabled}, max_concurrent={max_concurrent}"
    )


def _dict_to_training_config(d: Dict[str, Any]) -> TrainingConfig:
    """将字典转换为 TrainingConfig 对象。"""
    return TrainingConfig(
        enabled=d.get("enabled", False),
        rollout_collector=d.get("rollout_collector", True),
        trajectory_output=d.get("trajectory_output", ""),
        auto_export=d.get("auto_export", False),
        auto_export_format=d.get("auto_export_format", "jsonl"),
        max_concurrent=d.get("max_concurrent", 4),
        reward_weights=d.get("reward_weights"),
    )


# ── 模块自检 ─────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 模拟 Agent 对象
    class MockAgent:
        def __init__(self):
            self._agent_id = "mock-agent-1"
            self.config = type("Config", (), {"name": "MockAgent", "mode": type("Mode", (), {"value": "kernel"})})()

    agent = MockAgent()

    # 通过 dict 配置集成
    integration = integrate_training(agent, config_dict={
        "enabled": True,
        "rollout_collector": True,
        "max_concurrent": 4,
        "auto_export": True,
        "reward_weights": {"fitness": 0.5, "task_completion": 0.5},
    }, data_dir=os.path.expanduser("~/.laap"))

    if integration:
        print("Status:", json.dumps(integration.status(), indent=2, ensure_ascii=False))
        integration.set_enabled(False)
        print("Disabled.")
        integration.set_enabled(True)
        print("Re-enabled.")
