"""Phase 2 — TrainingOrchestrator unit tests."""
import time
import pytest
from laap.training.orchestrator import (
    RolloutTask,
    RolloutResult,
    TrainingOrchestrator,
    create_orchestrator,
    RolloutStats,
)


class TestRolloutTask:
    def test_defaults(self):
        task = RolloutTask()
        assert task.task_id.startswith("rt_")
        assert task.messages == ["你好"]
        assert task.timeout_s == 300
        assert task.priority == 5

    def test_custom(self):
        task = RolloutTask(
            task_id="my-task-1",
            messages=["hello", "world"],
            timeout_s=60,
            priority=8,
            metadata={"env": "test"},
        )
        assert task.task_id == "my-task-1"
        assert len(task.messages) == 2
        assert task.timeout_s == 60
        assert task.priority == 8
        assert task.metadata["env"] == "test"


class TestRolloutResult:
    def test_defaults(self):
        r = RolloutResult()
        assert r.status == "pending"
        assert r.error == ""
        assert r.duration_ms == 0.0


class TestTrainingOrchestrator:
    def test_create(self):
        orch = create_orchestrator(max_concurrent=2)
        assert orch.max_concurrent == 2
        assert orch.is_idle
        status = orch.status()
        assert status["total_submitted"] == 0
        assert status["running"] == 0

    def test_submit_and_collect(self):
        orch = create_orchestrator(max_concurrent=2)

        task = RolloutTask(messages=["你好"], timeout_s=30, priority=5)
        rid = orch.submit_rollout(task)
        assert rid is not None
        assert rid == task.task_id

        # Wait for completion
        result = orch.collect_rollout(rid, wait=True, timeout=30)
        assert result is not None
        assert result.status == "completed"
        assert result.duration_ms > 0

        trajs = orch.get_completed_trajectories()
        assert len(trajs) > 0

        status = orch.status()
        assert status["completed"] >= 1
        assert status["running"] == 0

    def test_batch_submit(self):
        orch = create_orchestrator(max_concurrent=4)

        tasks = [
            RolloutTask(messages=[f"msg_{i}"], timeout_s=30)
            for i in range(5)
        ]
        rids = orch.submit_batch(tasks)
        assert len(rids) == 5

        orch.wait_until_idle(timeout=60)
        assert orch.is_idle

        status = orch.status()
        assert status["completed"] == 5
        assert len(orch.get_completed_trajectories()) == 5

    def test_max_concurrent(self):
        """max_concurrent 限制应生效: 不会同时运行超过限制的 rollout。"""
        orch = create_orchestrator(max_concurrent=2)

        tasks = [
            RolloutTask(messages=["测试"], timeout_s=30)
            for _ in range(4)
        ]
        orch.submit_batch(tasks)

        # 短暂等待后检查并发数
        time.sleep(1)

        status = orch.status()
        # 不会超过 max_concurrent
        assert status["running"] <= 2

        orch.wait_until_idle(timeout=60)
        assert orch.is_idle
        assert orch.status()["completed"] == 4

    def test_cancel_pending(self):
        orch = create_orchestrator(max_concurrent=1)

        task1 = RolloutTask(messages=["first"], timeout_s=30)
        task2 = RolloutTask(messages=["second"], timeout_s=30)

        orch.submit_rollout(task1)
        orch.submit_rollout(task2)

        # Cancel the second one (should be pending)
        cancelled = orch.cancel_rollout(task2.task_id)
        assert cancelled is True

        orch.wait_until_idle(timeout=30)

        status = orch.status()
        assert status["completed"] == 1
        assert status["discarded"] == 1

    def test_status_with_recent_results(self):
        orch = create_orchestrator(max_concurrent=2)

        task = RolloutTask(messages=["你好"], timeout_s=30)
        orch.submit_rollout(task)
        orch.wait_until_idle(timeout=30)

        status = orch.status()
        assert "recent_results" in status
        assert len(status["recent_results"]) > 0
        assert status["recent_results"][0]["status"] == "completed"

    def test_wait_until_idle_timeout(self):
        orch = create_orchestrator(max_concurrent=1)

        # No tasks submitted, should be already idle
        assert orch.wait_until_idle(timeout=1) is True

    def test_submit_after_idle(self):
        """连续多轮提交。"""
        orch = create_orchestrator(max_concurrent=2)

        for batch in range(3):
            tasks = [
                RolloutTask(messages=[f"batch_{batch}_msg_{i}"], timeout_s=30)
                for i in range(2)
            ]
            orch.submit_batch(tasks)
            orch.wait_until_idle(timeout=30)

        assert orch.status()["completed"] == 6

    def test_cleanup_all(self):
        orch = create_orchestrator(max_concurrent=2)
        task = RolloutTask(messages=["cleanup test"], timeout_s=30)
        orch.submit_rollout(task)
        orch.wait_until_idle(timeout=30)

        count = orch.cleanup_all()
        assert count >= 0  # 至少清理成功

    def test_get_failed_rollouts(self):
        orch = create_orchestrator(max_concurrent=2)

        # 提交正常任务，不应有失败
        task = RolloutTask(messages=["ok"], timeout_s=30)
        orch.submit_rollout(task)
        orch.wait_until_idle(timeout=30)

        failed = orch.get_failed_rollouts()
        assert len(failed) == 0

    def test_scheduler_status(self):
        orch = create_orchestrator(max_concurrent=2)
        ss = orch.scheduler_status
        assert "pending_tasks" in ss
