"""
LAAP — Training Module

OpenForge RL 集成方案的三层架构实现。

层结构:
    Phase 1 — RolloutCollector (采集层)
    Phase 2 — TrainingOrchestrator (编排层)
    Phase 3 — TrajectoryBuilder + RewardAdapter (训练数据层)

各层独立可测，逐步构建。
"""
from laap.training.rollout_collector import (
    TurnSnapshot,
    ToolCallSnapshot,
    Trajectory,
    RolloutCollector,
)
from laap.training.orchestrator import (
    RolloutTask,
    RolloutResult,
    TrainingOrchestrator,
    create_orchestrator,
)
from laap.training.builder import (
    RewardAdapter,
    TrajectoryBuilder,
    create_builder,
    DEFAULT_REWARD_WEIGHTS,
)
from laap.training.integration import (
    TrainingConfig,
    TrainingIntegration,
    integrate_training,
    enable_training_config,
)

__all__ = [
    "TurnSnapshot",
    "ToolCallSnapshot",
    "Trajectory",
    "RolloutCollector",
    "RolloutTask",
    "RolloutResult",
    "TrainingOrchestrator",
    "create_orchestrator",
    "RewardAdapter",
    "TrajectoryBuilder",
    "create_builder",
    "DEFAULT_REWARD_WEIGHTS",
    "TrainingConfig",
    "TrainingIntegration",
    "integrate_training",
    "enable_training_config",
]
