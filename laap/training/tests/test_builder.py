"""Phase 3 — TrajectoryBuilder + RewardAdapter unit tests."""
import json
import os
import tempfile
import pytest
from laap.training.builder import (
    RewardAdapter,
    TrajectoryBuilder,
    create_builder,
    DEFAULT_REWARD_WEIGHTS,
)
from laap.training.rollout_collector import (
    Trajectory,
    TurnSnapshot,
    RewardSignal,
)


# ══════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════

def make_trajectory(tid: str = "test-1", turns: int = 2,
                    status: str = "completed",
                    rewards: dict = None) -> Trajectory:
    """创建测试用 Trajectory。"""
    t = Trajectory(trajectory_id=tid, status=status)
    for i in range(turns):
        t.add_turn(TurnSnapshot(
            turn_id=i + 1,
            user_message=f"msg_{i}",
            assistant_response=f"resp_{i}",
            tokens_in=50, tokens_out=100,
            duration_ms=500.0,
        ))
    if rewards:
        for src, val in rewards.items():
            t.add_reward(RewardSignal(value=val, source=src))
    return t


# ══════════════════════════════════════════════════════════════════
# Test: RewardAdapter
# ══════════════════════════════════════════════════════════════════

class TestRewardAdapter:
    def test_default_weights(self):
        adapter = RewardAdapter()
        assert adapter.weights == DEFAULT_REWARD_WEIGHTS

    def test_custom_weights(self):
        adapter = RewardAdapter(weights={"fitness": 1.0})
        reward = adapter.compute_from_signals({"fitness": 0.8})
        assert reward == 0.8

    def test_compute_reward_from_trajectory(self):
        adapter = RewardAdapter()
        traj = make_trajectory(rewards={"task_completion": 1.0, "fitness": 0.8})
        reward = adapter.compute_reward(traj)
        # Expected: (1.0 * 0.35 + 0.8 * 0.30) / (0.35 + 0.30) = 0.9077
        assert 0.85 < reward < 0.95

    def test_compute_reward_with_external(self):
        adapter = RewardAdapter()
        traj = make_trajectory()  # 没有奖励信号
        reward = adapter.compute_reward(traj, external_scores={"fitness": 0.9})
        assert reward > 0.5  # 至少是正面

    def test_compute_reward_empty(self):
        adapter = RewardAdapter()
        traj = Trajectory(trajectory_id="empty", status="failed")
        reward = adapter.compute_reward(traj)
        # failed 状态无 reward 信号 → task_completion 兜底为 0.0
        assert reward == 0.0

    def test_compute_reward_failed(self):
        adapter = RewardAdapter()
        traj = make_trajectory(status="failed", rewards={"task_completion": 0.0})
        reward = adapter.compute_reward(traj)
        assert reward < 0.5  # 负面

    def test_stability_penalty(self):
        adapter = RewardAdapter()
        traj = make_trajectory(
            rewards={"task_completion": 1.0},
            status="completed",
        )
        traj.metadata["stability_alerts"] = [
            {"level": "critical", "message": "test alert"}
        ]
        reward = adapter.compute_reward(traj)
        # task_completion=1.0 减去 critical 惩罚 0.3 → 0.7
        assert 0.60 < reward < 0.80

    def test_group_advantages_three(self):
        adapter = RewardAdapter()
        trajs = [
            make_trajectory(f"t{i}", rewards={"task_completion": 0.5 + i * 0.25})
            for i in range(3)
        ]
        advantages = adapter.compute_group_advantages(trajs)
        assert len(advantages) == 3
        # 中间的值应该接近 0
        assert abs(advantages[1]) < 0.1
        # 第一个应该是负的
        assert advantages[0] < 0
        # 第三个应该是正的
        assert advantages[2] > 0

    def test_group_advantages_single(self):
        """单条轨迹时优势值为 0。"""
        adapter = RewardAdapter()
        traj = make_trajectory(rewards={"task_completion": 0.8})
        advantages = adapter.compute_group_advantages([traj])
        assert len(advantages) == 1
        assert advantages[0] == 0.0

    def test_group_advantages_empty(self):
        adapter = RewardAdapter()
        advantages = adapter.compute_group_advantages([])
        assert advantages == []

    def test_compute_composite_scores(self):
        adapter = RewardAdapter()
        traj = make_trajectory(rewards={"task_completion": 1.0})
        scores = adapter.compute_composite_scores(
            traj, fitness_score=0.85,
            stability_alerts=[]
        )
        assert "fitness" in scores
        assert scores["fitness"] == 0.85
        assert "task_completion" in scores

    def test_reward_summary(self):
        adapter = RewardAdapter()
        traj = make_trajectory(rewards={"task_completion": 0.9, "fitness": 0.75})
        summary = adapter.reward_summary(traj)
        assert summary["trajectory_id"] == "test-1"
        assert "final_reward" in summary
        assert "sources" in summary
        assert summary["sources"]["task_completion"] == 0.9


# ══════════════════════════════════════════════════════════════════
# Test: TrajectoryBuilder
# ══════════════════════════════════════════════════════════════════

class TestTrajectoryBuilder:
    def test_create(self):
        builder = create_builder()
        assert isinstance(builder, TrajectoryBuilder)
        assert isinstance(builder.reward_adapter, RewardAdapter)

    def test_build_single(self):
        builder = create_builder()
        traj = make_trajectory(rewards={"task_completion": 1.0})
        record = builder.build(traj)
        assert record["trajectory_id"] == "test-1"
        assert "conversations" in record
        assert "reward" in record
        assert record["valid"] is True

    def test_build_with_advantage(self):
        builder = create_builder()
        traj = make_trajectory()
        record = builder.build(traj, advantage=0.5)
        assert record["advantage"] == 0.5

    def test_build_invalid(self):
        builder = create_builder()
        traj = make_trajectory(status="failed", rewards={"task_completion": 0.0})
        record = builder.build(traj)
        assert record["valid"] is False

    def test_build_batch(self):
        builder = create_builder()
        trajs = [
            make_trajectory(f"t{i}", rewards={"task_completion": 0.8})
            for i in range(3)
        ]
        records = builder.build_batch(trajs)
        assert len(records) == 3
        for i, rec in enumerate(records):
            assert rec["trajectory_id"] == f"t{i}"

    def test_build_batch_empty(self):
        builder = create_builder()
        records = builder.build_batch([])
        assert records == []

    def test_build_grpo_batch(self):
        builder = create_builder()
        trajs = [
            make_trajectory(f"t{i}", rewards={"task_completion": 0.5 + i * 0.25})
            for i in range(5)
        ]
        records, advantages = builder.build_grpo_batch(trajs)
        assert len(records) == 5
        assert len(advantages) == 5
        # 每个 record 应包含 advantage
        for rec in records:
            assert "advantage" in rec

    def test_export_jsonl(self):
        builder = create_builder()
        trajs = [
            make_trajectory(f"t{i}", rewards={"task_completion": 0.8})
            for i in range(3)
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                         delete=False) as f:
            path = f.name

        try:
            count = builder.export_jsonl(trajs, path, compute_advantages=True)
            assert count == 3  # 全部有效

            # 验证 JSONL 格式
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            assert len(lines) == 3
            for line in lines:
                record = json.loads(line)
                assert "trajectory_id" in record
                assert "reward" in record
        finally:
            os.unlink(path)

    def test_export_jsonl_filter_invalid(self):
        builder = create_builder()
        trajs = [
            make_trajectory("valid", rewards={"task_completion": 0.8}),
            make_trajectory("invalid", status="failed", rewards={"task_completion": 0.0}),
            make_trajectory("empty_turns", turns=0, status="completed"),
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                         delete=False) as f:
            path = f.name

        try:
            count = builder.export_jsonl(trajs, path, filter_valid=True)
            assert count == 1  # 只有第一个有效
        finally:
            os.unlink(path)

    def test_export_training_metadata(self):
        builder = create_builder()
        trajs = [
            make_trajectory(f"t{i}", rewards={"task_completion": 0.8})
            for i in range(3)
        ]
        records = builder.build_batch(trajs)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as f:
            path = f.name

        try:
            builder.export_training_metadata(path, trajs, records)
            with open(path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            assert metadata["total_trajectories"] == 3
            assert metadata["exported_records"] == 3
            assert "reward_stats" in metadata
        finally:
            os.unlink(path)
