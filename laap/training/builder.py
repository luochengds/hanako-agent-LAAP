"""
Phase 3 — TrajectoryBuilder + RewardAdapter (训练数据层)

OpenForge RL 集成: 把 RolloutCollector 采集的 raw_trajectories 转换成
标准 RL 训练格式 (veRL/GRPO 兼容), 并把 LAAP 现有的评估系统评分
(FitnessEvaluator, StabilityMonitor) 接入作为奖励信号。

功能:
  - TrajectoryBuilder: 将 Trajectory 对象转换为 veRL 训练样本
  - RewardAdapter: 多源奖励信号计算 + GRPO 组优势值
  - 输出格式: JSONL, 每行一个训练样本, 兼容 veRL train.py

奖励信号来源 (复用现有组件):
  - FitnessEvaluator.composite_fitness() → 综合适应度评分 (0~1)
  - StabilityMonitor.check() → 稳定性惩罚 (critical 警报扣分)
  - task_completion: 任务完成状态 (成功=1.0, 失败=0.0)
  - user_feedback: 用户反馈 (可选, 外部注入)

GRPO 优势值:
  参考 OpenForge 论文: 基于组的算法根据同组轨迹的平均奖励计算优势值。
  advantage = (reward - group_mean) / (group_std + epsilon)

数据流:
    Phase 1 Trajectory + Phase 2 Trajectory
        → TrajectoryBuilder.build(trajectory)     [格式转换]
        → RewardAdapter.compute_reward(trajectory) [奖励评分]
        → RewardAdapter.compute_group_advantages() [组优势值]
        → JSONL 输出文件                           [训练就绪]
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from laap.training.rollout_collector import Trajectory, TurnSnapshot

logger = logging.getLogger("laap.training.builder")


# ══════════════════════════════════════════════════════════════════
# 奖励权重配置
# ══════════════════════════════════════════════════════════════════

DEFAULT_REWARD_WEIGHTS = {
    "fitness": 0.30,
    "stability": 0.15,
    "task_completion": 0.35,
    "user_feedback": 0.20,
}

# Stability 惩罚: 出现 critical 警告时扣分
STABILITY_CRITICAL_PENALTY = 0.3
STABILITY_WARNING_PENALTY = 0.1


# ══════════════════════════════════════════════════════════════════
# RewardAdapter
# ══════════════════════════════════════════════════════════════════

class RewardAdapter:
    """奖励适配器 — 将多种信号源映射为 RL 训练可用的奖励值。

    支持:
    - 从 Trajectory.rewards 中提取已记录信号
    - 外部注入 FitnessEvaluator / StabilityMonitor 评分
    - 计算 GRPO 组相对优势值
    - 可配置各信号源的权重

    用法:
        >>> adapter = RewardAdapter()
        >>> reward = adapter.compute_reward(trajectory)
        >>> advantages = adapter.compute_group_advantages(trajectories)
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None,
                 epsilon: float = 1e-8):
        """
        Args:
            weights: 各信号源权重. 默认 DEFAULT_REWARD_WEIGHTS.
            epsilon: 防止除零.
        """
        self.weights = weights or dict(DEFAULT_REWARD_WEIGHTS)
        self.epsilon = epsilon

    # ── 单轨迹奖励计算 ───────────────────────────────────────

    def compute_reward(self, trajectory: Trajectory,
                       external_scores: Optional[Dict[str, float]] = None) -> float:
        """计算单个 trajectory 的综合奖励值。

        奖励来源 (按优先级):
        1. Trajectory 中已记录的 reward 信号 (若 weight 匹配)
        2. 外部注入的评分 (external_scores)
        3. 任务完成状态 (从 trajectory.status 推断)

        Args:
            trajectory: Phase 1 采集的 Trajectory 对象.
            external_scores: 可选, 外部评分字典, 如 {"fitness": 0.8}.

        Returns:
            综合奖励值 (0.0 ~ 1.0).
        """
        signals: Dict[str, float] = {}

        # 1. 从 trajectory.rewards 中提取
        for reward in trajectory.rewards:
            src = reward.source
            if src in self.weights:
                # 同源奖励取最大值 (允许多次记录, 保留最佳)
                if src not in signals or reward.value > signals[src]:
                    signals[src] = reward.value

        # 2. 外部注入的评分
        if external_scores:
            for src, val in external_scores.items():
                if src in self.weights:
                    signals[src] = val

        # 3. 任务完成状态兜底
        if "task_completion" not in signals:
            if trajectory.status == "completed":
                # 根据是否有有效 turn 判断完成质量
                quality = min(1.0, len(trajectory.turns) / 10.0) if trajectory.turns else 0.5
                signals["task_completion"] = max(0.5, quality)
            elif trajectory.status == "truncated":
                signals["task_completion"] = 0.3
            else:
                signals["task_completion"] = 0.0

        # 4. 稳定性惩罚 (根据 trajectory metadata 中的警报)
        stability_penalty = self._compute_stability_penalty(trajectory)
        if stability_penalty > 0:
            # 从 fitness 或 task_completion 扣分
            for src in ("fitness", "task_completion"):
                if src in signals:
                    signals[src] = max(0.0, signals[src] - stability_penalty)
                    break

        # 加权求和
        total_weight = 0.0
        weighted_sum = 0.0
        for src, val in signals.items():
            w = self.weights.get(src, 0.0)
            weighted_sum += val * w
            total_weight += w

        if total_weight == 0.0:
            return 0.5  # 默认中性值

        return max(0.0, min(1.0, weighted_sum / total_weight))

    def _compute_stability_penalty(self, trajectory: Trajectory) -> float:
        """从 trajectory 元数据中提取稳定性惩罚。"""
        alerts = trajectory.metadata.get("stability_alerts", [])
        if not alerts:
            return 0.0

        max_level = "none"
        for alert in alerts:
            level = alert.get("level", "")
            if level == "critical":
                max_level = "critical"
                break
            elif level == "warning" and max_level != "critical":
                max_level = "warning"

        if max_level == "critical":
            return STABILITY_CRITICAL_PENALTY
        elif max_level == "warning":
            return STABILITY_WARNING_PENALTY
        return 0.0

    # ── GRPO 组优势值 ────────────────────────────────────────

    def compute_group_advantages(
        self,
        trajectories: List[Trajectory],
        external_scores: Optional[Dict[str, List[float]]] = None,
    ) -> List[float]:
        """计算一组 trajectory 的 GRPO 组相对优势值。

        参考 OpenForge 论文:
            GRPO 等基于组的算法根据同组轨迹的平均奖励计算优势值。

        Formula:
            group_mean = mean(rewards)
            group_std  = std(rewards)
            advantage_i = (reward_i - group_mean) / (group_std + epsilon)

        Args:
            trajectories: 同一训练批次的一组 Trajectory 列表.
            external_scores: 可选, 外部评分的字典, 每项是 float 列表.

        Returns:
            每个 trajectory 对应的优势值列表 (长度与 trajectories 一致).
        """
        if not trajectories:
            return []

        # 计算每个 trajectory 的奖励
        rewards = []
        for i, traj in enumerate(trajectories):
            ext = None
            if external_scores:
                ext = {k: v[i] for k, v in external_scores.items()
                       if i < len(v)}
            reward = self.compute_reward(traj, external_scores=ext)
            rewards.append(reward)

        # GRPO 组统计
        group_mean = sum(rewards) / len(rewards)
        if len(rewards) > 1:
            variance = sum((r - group_mean) ** 2 for r in rewards) / len(rewards)
            group_std = math.sqrt(variance + self.epsilon)
        else:
            group_std = 1.0

        # 计算优势值
        advantages = [
            (r - group_mean) / (group_std + self.epsilon)
            for r in rewards
        ]
        return advantages

    # ── 便捷方法 ─────────────────────────────────────────────

    def compute_from_signals(self, signals: Dict[str, float]) -> float:
        """直接根据信号值字典计算加权奖励。"""
        total_weight = 0.0
        weighted_sum = 0.0
        for src, val in signals.items():
            w = self.weights.get(src, 0.0)
            weighted_sum += val * w
            total_weight += w

        if total_weight == 0.0:
            return 0.5
        return max(0.0, min(1.0, weighted_sum / total_weight))

    def compute_composite_scores(
        self,
        trajectory: Trajectory,
        fitness_score: Optional[float] = None,
        stability_alerts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        """综合计算各项评分。

        Args:
            trajectory: Trajectory 对象.
            fitness_score: FitnessEvaluator 输出的综合评分.
            stability_alerts: StabilityMonitor 输出的警报列表.

        Returns:
            {source: value, ...} 评分字典.
        """
        signals: Dict[str, float] = {}

        if fitness_score is not None:
            signals["fitness"] = fitness_score

        if stability_alerts is not None:
            # 警报转换为稳定性分 (1.0 - 惩罚)
            penalty = 0.0
            for alert in stability_alerts:
                if alert.level == "critical":
                    penalty = max(penalty, STABILITY_CRITICAL_PENALTY)
                elif alert.level == "warning":
                    penalty = max(penalty, STABILITY_WARNING_PENALTY)
            signals["stability"] = max(0.0, 1.0 - penalty)
        else:
            signals["stability"] = 0.5

        # 任务完成
        if trajectory.status == "completed" and trajectory.turns:
            signals["task_completion"] = 1.0
        elif trajectory.status == "truncated":
            signals["task_completion"] = 0.3
        else:
            signals["task_completion"] = 0.0

        return signals

    def reward_summary(self, trajectory: Trajectory) -> Dict[str, Any]:
        """生成单条轨迹的奖励分析摘要。"""
        reward = self.compute_reward(trajectory)

        # 按来源分解
        sources = {}
        for r in trajectory.rewards:
            sources[r.source] = r.value

        return {
            "trajectory_id": trajectory.trajectory_id,
            "final_reward": round(reward, 4),
            "sources": sources,
            "num_turns": len(trajectory.turns),
            "status": trajectory.status,
        }


# ══════════════════════════════════════════════════════════════════
# TrajectoryBuilder
# ══════════════════════════════════════════════════════════════════

class TrajectoryBuilder:
    """轨迹构建器 — 将 Trajectory 对象转换为 veRL 兼容的训练样本。

    核心功能:
    - build(): 单条 Trajectory → 训练样本 (dict)
    - build_batch(): 批量转换
    - export_jsonl(): 导出为 JSONL 文件
    - build_grpo_batch(): 批量转换 + 计算 GRPO 优势值

    veRL 兼容格式:
    {
        "trajectory_id": "...",
        "conversations": [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "...",
             "tool_calls": [{"name": "...", "arguments": {...}}]},
            ...
        ],
        "reward": 0.85,
        "advantage": 0.62,        # GRPO 优势值 (可选)
        "reward_sources": {...},  # 各来源奖励分解
        "metadata": {...}         # 元数据
    }
    """

    def __init__(self, reward_adapter: Optional[RewardAdapter] = None):
        """
        Args:
            reward_adapter: 可选的 RewardAdapter 实例.
                            不传则创建一个默认配置的实例.
        """
        self.reward_adapter = reward_adapter or RewardAdapter()

    # ── 单条转换 ─────────────────────────────────────────────

    def build(self, trajectory: Trajectory,
              external_scores: Optional[Dict[str, float]] = None,
              advantage: Optional[float] = None) -> dict:
        """将单条 Trajectory 转换为 veRL 兼容的训练样本。

        Args:
            trajectory: Phase 1 采集的 Trajectory.
            external_scores: 可选, 外部评分.
            advantage: 可选, GRPO 优势值.

        Returns:
            训练样本字典, 可直接写入 JSONL.
        """
        # 基础记录 (复用 Trajectory.to_training_record 的格式)
        record = trajectory.to_training_record()

        # 计算奖励
        reward = self.reward_adapter.compute_reward(
            trajectory, external_scores=external_scores
        )
        record["reward"] = round(reward, 6)

        # 加入优势值
        if advantage is not None:
            record["advantage"] = round(advantage, 6)

        # 加入奖励来源分解
        reward_sources = {}
        for r in trajectory.rewards:
            reward_sources[r.source] = r.value
        if external_scores:
            reward_sources.update(external_scores)
        record["reward_sources"] = reward_sources

        # 加入额外元数据
        record["metadata"]["builder_version"] = "phase3.v1"
        record["metadata"]["converted_at"] = time.time()
        record["metadata"]["trajectory_status"] = trajectory.status

        # 加入训练状态标记
        if trajectory.status == "failed" or trajectory.status == "discarded":
            record["valid"] = False
        else:
            record["valid"] = True

        return record

    # ── 批量转换 ─────────────────────────────────────────────

    def build_batch(self, trajectories: List[Trajectory],
                    external_scores: Optional[Dict[str, List[float]]] = None,
                    compute_advantages: bool = False) -> List[dict]:
        """批量转换多条轨迹为训练样本。

        Args:
            trajectories: Trajectory 列表.
            external_scores: 可选, 外部评分 (每源一个列表).
            compute_advantages: 是否计算 GRPO 组优势值.

        Returns:
            训练样本字典列表.
        """
        if not trajectories:
            return []

        # 计算 GRPO 优势值 (如果需要)
        advantages = None
        if compute_advantages:
            advantages = self.reward_adapter.compute_group_advantages(
                trajectories, external_scores=external_scores
            )

        records = []
        for i, traj in enumerate(trajectories):
            ext = None
            if external_scores:
                ext = {k: v[i] for k, v in external_scores.items()
                       if i < len(v)}
            adv = advantages[i] if advantages else None
            record = self.build(traj, external_scores=ext, advantage=adv)
            records.append(record)

        return records

    def build_grpo_batch(self, trajectories: List[Trajectory],
                         external_scores: Optional[Dict[str, List[float]]] = None
                         ) -> Tuple[List[dict], List[float]]:
        """批量转换 + 计算 GRPO 优势值。

        Returns:
            (records, advantages) 元组.
        """
        if not trajectories:
            return [], []

        advantages = self.reward_adapter.compute_group_advantages(
            trajectories, external_scores=external_scores
        )

        records = []
        for i, traj in enumerate(trajectories):
            ext = None
            if external_scores:
                ext = {k: v[i] for k, v in external_scores.items()
                       if i < len(v)}
            record = self.build(traj, external_scores=ext, advantage=advantages[i])
            records.append(record)

        return records, advantages

    # ── 导出 ─────────────────────────────────────────────────

    def export_jsonl(self, trajectories: List[Trajectory], path: str,
                     external_scores: Optional[Dict[str, List[float]]] = None,
                     compute_advantages: bool = False,
                     filter_valid: bool = True) -> int:
        """导出训练样本到 JSONL 文件。

        Args:
            trajectories: Trajectory 列表.
            path: 输出文件路径.
            external_scores: 可选, 外部评分.
            compute_advantages: 是否计算 GRPO 优势值.
            filter_valid: 只导出有效轨迹 (status=completed/truncated).

        Returns:
            导出的样本数.
        """
        if filter_valid:
            trajectories = [
                t for t in trajectories
                if t.status in ("completed", "truncated") and t.turns
            ]

        records = self.build_batch(
            trajectories,
            external_scores=external_scores,
            compute_advantages=compute_advantages,
        )

        count = 0
        with open(path, 'w', encoding='utf-8') as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
                count += 1

        logger.info(
            f"Exported {count} training records to {path} "
            f"(advantages={'on' if compute_advantages else 'off'})"
        )
        return count

    def export_training_metadata(self, path: str,
                                 trajectories: List[Trajectory],
                                 records: List[dict]) -> None:
        """导出训练元数据文件 (JSON), 包含统计信息和样本索引。"""
        rewards = [r.get("reward", 0.0) for r in records]
        advantages = [r.get("advantage", 0.0) for r in records if "advantage" in r]
        tokens_total = sum(
            t.total_tokens() for t in trajectories if t.status in ("completed", "truncated")
        )

        metadata = {
            "exported_at": time.time(),
            "total_trajectories": len(trajectories),
            "exported_records": len(records),
            "valid_records": sum(1 for r in records if r.get("valid", True)),
            "reward_stats": {
                "mean": round(sum(rewards) / len(rewards), 4) if rewards else 0.0,
                "min": round(min(rewards), 4) if rewards else 0.0,
                "max": round(max(rewards), 4) if rewards else 0.0,
            },
            "advantage_stats": {
                "mean": round(sum(advantages) / len(advantages), 4) if advantages else 0.0,
                "min": round(min(advantages), 4) if advantages else 0.0,
                "max": round(max(advantages), 4) if advantages else 0.0,
            } if advantages else {},
            "tokens_collected": tokens_total,
            "reward_weights": self.reward_adapter.weights,
            "config": {
                "compute_advantages": len(advantages) > 0,
            },
        }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        logger.info(f"Training metadata exported to {path}")


# ══════════════════════════════════════════════════════════════════
# 便捷工厂
# ══════════════════════════════════════════════════════════════════

def create_builder(weights: Optional[Dict[str, float]] = None) -> TrajectoryBuilder:
    """创建配置好的 TrajectoryBuilder 实例。"""
    adapter = RewardAdapter(weights=weights)
    return TrajectoryBuilder(reward_adapter=adapter)


# ── 模块自检 ─────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from laap.training.rollout_collector import (
        TurnSnapshot, ToolCallSnapshot, RewardSignal,
    )

    # 创建测试轨迹
    trajs = []
    for ep in range(3):
        t = Trajectory(trajectory_id=f"test_{ep}")
        for i in range(2):
            t.add_turn(TurnSnapshot(
                turn_id=i + 1,
                user_message=f"测试消息 {ep}.{i}",
                assistant_response=f"测试回复 {ep}.{i}",
                tokens_in=50, tokens_out=100,
                duration_ms=500.0,
            ))
        t.add_reward(RewardSignal(value=0.8 + ep * 0.1, source="task_completion"))
        t.add_reward(RewardSignal(value=0.7, source="fitness"))
        trajs.append(t)

    # TrajectoryBuilder + GRPO 优势值
    builder = create_builder()
    records, advantages = builder.build_grpo_batch(trajs)

    print(f"Built {len(records)} records")
    for i, (rec, adv) in enumerate(zip(records, advantages)):
        print(f"  Record {i}: reward={rec['reward']:.4f}, advantage={adv:.4f}")

    # 导出示例
    builder.export_jsonl(trajs, "test_training_data.jsonl", compute_advantages=True)
    builder.export_training_metadata("test_training_metadata.json", trajs, records)

    print("\nSample record:")
    print(json.dumps(records[0], indent=2, ensure_ascii=False))
