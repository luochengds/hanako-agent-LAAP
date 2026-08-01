"""
Phase 2 — TrainingOrchestrator (编排层)

OpenForge RL 集成: 管理并行 rollout 的生命周期——创建、调度、超时、回收。

设计决策:
  1. 进程隔离: 每个 rollout 在独立 Python 子进程中运行 (subprocess),
     加载独立的 Agent(mode="kernel") 实例 + RolloutCollector。
     未来可映射到真实 K8s Pod。

  2. 墙钟超时: 复用已有的 TaskScheduler 的 deadline + priority 评分系统。
     超过 deadline 直接丢弃, 不等待、不重试、不给负奖励。

  3. 异常丢弃: 如果 rollout 因 harness 故障/网络超时/任务异常终止,
     reward 标记为 None, 不进入训练轨迹池。

  4. 混合调度: 本地用 TaskScheduler + subprocess,
     未来替换为 K8sManager.deploy() 生成真实 PodSpec。

数据流:
    submit_rollout() → TaskScheduler 排队 → subprocess 执行 →
    RolloutCollector 采集轨迹 → collect_rollout() 返回 Trajectory

依赖:
    - laap.orchestration.task_scheduler: TaskScheduler (优先级评分 + 超时)
    - laap.tasks.registry: TaskRegistry (后台异步执行)
    - laap.training.rollout_collector: RolloutCollector + Trajectory
    - laap.infrastructure.deployment.k8s: K8sManager (未来映射)
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

from laap.training.rollout_collector import (
    RolloutCollector,
    Trajectory,
    TurnSnapshot,
)

logger = logging.getLogger("laap.training.orchestrator")


# ══════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════

@dataclass
class RolloutTask:
    """一个 rollout 任务的定义。

    对应 OpenForge 论文中的一个 "rollout container"。
    每个 RolloutTask 在独立的进程中运行一个 Agent 实例,
    执行一段对话, 记录轨迹, 然后终止。
    """

    task_id: str = ""
    agent_mode: str = "kernel"          # kernel / hermes
    agent_config: Dict[str, Any] = field(default_factory=dict)
    messages: List[str] = field(default_factory=list)
    environment: str = "kernel"
    timeout_s: int = 300
    priority: int = 5                   # 1-10, 10 = highest
    psi_urgency: float = 0.0            # 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = f"rt_{uuid.uuid4().hex[:12]}"
        if not self.messages:
            self.messages = ["你好"]  # 默认消息


@dataclass
class RolloutResult:
    """一个 rollout 的执行结果。"""

    rollout_id: str = ""
    status: str = "pending"             # pending / running / completed / failed / timed_out / discarded
    trajectory: Optional[Trajectory] = None
    error: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    exit_code: Optional[int] = None


@dataclass
class RolloutStats:
    """编排器统计信息。"""
    total_submitted: int = 0
    completed: int = 0
    failed: int = 0
    timed_out: int = 0
    discarded: int = 0
    running: int = 0
    pending: int = 0
    total_tokens_collected: int = 0


# ══════════════════════════════════════════════════════════════════
# TrainingOrchestrator
# ══════════════════════════════════════════════════════════════════

class TrainingOrchestrator:
    """训练编排器 — 管理并行 rollout 生命周期。

    OpenForge 论文中的 "Kubernetes 编排器" 的本地实现。
    使用 subprocess 进程隔离替代真实 K8s Pod, 提供相同的语义:

    - 每个 rollout 独立进程, 独立 Agent 实例, 独立 RolloutCollector
    - 墙钟超时, 超时后干净截断
    - 异常 rollout 自动丢弃, 不污染训练数据
    - 未来可映射到真实 K8s (通过 K8sManager)

    用法:
        >>> from laap.training.orchestrator import TrainingOrchestrator, RolloutTask
        >>> orch = TrainingOrchestrator(max_concurrent=4)
        >>> task = RolloutTask(messages=["帮我查天气"], timeout_s=60)
        >>> rid = orch.submit_rollout(task)
        >>> result = orch.collect_rollout(rid, wait=True)
        >>> traj = result.trajectory  # Trajectory 对象, 传给 Phase 3
    """

    def __init__(self, max_concurrent: int = 4,
                 data_dir: Optional[str] = None):
        """
        Args:
            max_concurrent: 最大并发 rollout 数量.
            data_dir: 临时数据目录 (用于进程间传递轨迹 JSON).
                      默认使用系统临时目录.
        """
        self.max_concurrent = max_concurrent
        self.data_dir = data_dir or tempfile.mkdtemp(prefix="laap_rollout_")
        os.makedirs(self.data_dir, exist_ok=True)

        self._results: Dict[str, RolloutResult] = {}
        self._tasks: Dict[str, RolloutTask] = {}
        self._lock = threading.RLock()
        self._running_processes: Dict[str, subprocess.Popen] = {}
        self._result_queue: queue.Queue = queue.Queue()
        self._stats = RolloutStats()

        # 初始化调度器
        try:
            from laap.orchestration.task_scheduler import TaskScheduler
            self._scheduler = TaskScheduler()
            self._use_scheduler = True
        except ImportError:
            self._scheduler = None
            self._use_scheduler = False
            logger.warning("TaskScheduler not available, using FIFO dispatch")

        # 启动结果收集线程
        self._collector_thread = threading.Thread(
            target=self._collect_results, daemon=True
        )
        self._collector_thread.start()

        logger.info(
            f"TrainingOrchestrator initialized: "
            f"max_concurrent={max_concurrent}, data_dir={self.data_dir}"
        )

    # ── 提交 ─────────────────────────────────────────────────

    def submit_rollout(self, task: RolloutTask) -> str:
        """提交单个 rollout 任务到调度队列。

        Args:
            task: RolloutTask 定义.

        Returns:
            rollout_id.
        """
        with self._lock:
            if not task.task_id:
                task.task_id = f"rt_{uuid.uuid4().hex[:12]}"

            # 存储任务定义
            self._tasks[task.task_id] = task

            # 初始化结果记录
            self._results[task.task_id] = RolloutResult(
                rollout_id=task.task_id,
                status="pending" if self._stats.running < self.max_concurrent
                       else "queued",
            )
            self._stats.total_submitted += 1
            self._stats.pending += 1

            # 使用 TaskScheduler 调度 (如果有)
            if self._use_scheduler:
                try:
                    from laap.orchestration.task_scheduler import Task
                    scheduler_task = Task(
                        id=task.task_id,
                        name=f"rollout_{task.task_id[:8]}",
                        priority=task.priority,
                        deadline=time.time() + task.timeout_s,
                        psi_urgency=task.psi_urgency,
                        payload={"rollout_id": task.task_id},
                    )
                    self._scheduler.submit(scheduler_task)
                except Exception as e:
                    logger.warning(f"TaskScheduler submit failed: {e}, using FIFO")

            # 尝试立即派发
            self._dispatch_pending()

            logger.info(
                f"Rollout submitted: {task.task_id} "
                f"(priority={task.priority}, timeout={task.timeout_s}s)"
            )
            return task.task_id

    def submit_batch(self, tasks: List[RolloutTask]) -> List[str]:
        """批量提交多个 rollout 任务。

        Args:
            tasks: RolloutTask 列表.

        Returns:
            rollout_id 列表.
        """
        return [self.submit_rollout(t) for t in tasks]

    # ── 结果收集 ─────────────────────────────────────────────

    def collect_rollout(self, rollout_id: str,
                        wait: bool = False,
                        timeout: Optional[float] = None) -> Optional[RolloutResult]:
        """获取指定 rollout 的结果。

        Args:
            rollout_id: 要获取的 rollout id.
            wait: 是否等待 rollout 完成 (若仍在运行).
            timeout: 等待超时 (秒), None = 无限.

        Returns:
            RolloutResult, 若不存在返回 None.
        """
        with self._lock:
            result = self._results.get(rollout_id)

        if result is None:
            return None

        if wait and result.status in ("pending", "running", "queued"):
            deadline = time.time() + (timeout or 300)
            while time.time() < deadline:
                with self._lock:
                    result = self._results.get(rollout_id)
                    if result and result.status in ("completed", "failed",
                                                    "timed_out", "discarded"):
                        break
                time.sleep(0.1)

        return result

    def cancel_rollout(self, rollout_id: str) -> bool:
        """取消一个 rollout 任务。

        Args:
            rollout_id: 要取消的 rollout id.

        Returns:
            取消是否成功.
        """
        with self._lock:
            result = self._results.get(rollout_id)
            if result is None:
                return False
            if result.status == "running":
                proc = self._running_processes.get(rollout_id)
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    self._running_processes.pop(rollout_id, None)
                result.status = "discarded"
                self._stats.discarded += 1
                self._stats.running -= 1
                return True
            elif result.status in ("pending", "queued"):
                result.status = "discarded"
                self._stats.discarded += 1
                self._stats.pending -= 1
                return True
            return False

    # ── 调度与执行 ──────────────────────────────────────────

    def _dispatch_pending(self) -> None:
        """尝试将 pending/queued 任务派发执行。"""
        with self._lock:
            if self._stats.running >= self.max_concurrent:
                return

            # 找出所有未执行的任务
            pending = [
                rid for rid, r in self._results.items()
                if r.status in ("pending", "queued")
            ]

            if not pending:
                return

            # 如果有 TaskScheduler, 按调度顺序执行
            if self._use_scheduler and self._scheduler is not None:
                pending_sorted = []
                while (scheduled := self._scheduler.next()) is not None:
                    rid = scheduled.id
                    if rid in self._results and self._results[rid].status in ("pending", "queued"):
                        pending_sorted.append(rid)
                # 补上未进入 scheduler 的
                for rid in pending:
                    if rid not in pending_sorted:
                        pending_sorted.append(rid)
            else:
                pending_sorted = pending

            # 派发, 直到达到最大并发
            for rid in pending_sorted:
                if self._stats.running >= self.max_concurrent:
                    break
                task = None
                # 找回原始 RolloutTask (存储在 metadata 中)
                result = self._results[rid]
                result.status = "running"
                result.start_time = time.time()
                self._stats.running += 1
                self._stats.pending -= 1
                self._execute_rollout_async(rid)

    def _execute_rollout_async(self, rollout_id: str) -> None:
        """在后台线程执行 rollout。"""
        thread = threading.Thread(
            target=self._execute_rollout,
            args=(rollout_id,),
            daemon=True,
        )
        thread.start()

    def _execute_rollout(self, rollout_id: str) -> None:
        """执行单个 rollout (在后台线程中运行)。

        使用 subprocess 创建独立子进程运行 agent,
        确保进程级隔离。
        """
        result = self._results.get(rollout_id)
        if result is None:
            return

        # 获取任务定义
        task = self._tasks.get(rollout_id)
        if task is None:
            result.status = "failed"
            result.error = "Task definition not found"
            return

        # 创建临时轨迹文件路径
        trajectory_path = os.path.join(
            self.data_dir, f"trajectory_{rollout_id}.json"
        )
        rollout_script = self._generate_rollout_script(
            rollout_id, trajectory_path, task
        )

        # 写入临时脚本
        script_path = os.path.join(
            self.data_dir, f"rollout_{rollout_id}.py"
        )
        try:
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(rollout_script)

            # 在子进程中执行
            start_time = time.time()

            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.data_dir,
            )

            with self._lock:
                self._running_processes[rollout_id] = proc

            # 等待完成或超时
            try:
                stdout, stderr = proc.communicate(timeout=result.end_time - time.time()
                                                  if result.end_time > 0 else 5)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
                with self._lock:
                    result.status = "timed_out"
                    result.error = f"Wall clock timeout exceeded"
                    result.end_time = time.time()
                    result.duration_ms = (result.end_time - result.start_time) * 1000
                    self._stats.timed_out += 1
                    self._stats.running -= 1
                    self._stats.total_submitted -= 0  # already counted
                logger.warning(f"Rollout {rollout_id} timed out")
                self._cleanup_rollout(rollout_id, script_path, trajectory_path)
                return

            # 读取轨迹文件
            trajectory = None
            if os.path.exists(trajectory_path):
                try:
                    with open(trajectory_path, 'r', encoding='utf-8') as f:
                        traj_data = json.load(f)

                    # 重建 Trajectory 对象
                    trajectory = Trajectory(
                        trajectory_id=traj_data.get("trajectory_id", rollout_id),
                        status=traj_data.get("status", "completed"),
                        final_reward=traj_data.get("final_reward"),
                        metadata=traj_data.get("metadata", {}),
                    )
                    # 重建 turns
                    for turn_data in traj_data.get("turns", []):
                        from laap.training.rollout_collector import TurnSnapshot, ToolCallSnapshot
                        turn = TurnSnapshot(
                            turn_id=turn_data.get("turn_id", 0),
                            user_message=turn_data.get("user_message", ""),
                            assistant_response=turn_data.get("assistant_response", ""),
                            tokens_in=turn_data.get("tokens_in", 0),
                            tokens_out=turn_data.get("tokens_out", 0),
                            duration_ms=turn_data.get("duration_ms", 0.0),
                            error=turn_data.get("error", ""),
                        )
                        for tc_data in turn_data.get("tool_calls", []):
                            tc = ToolCallSnapshot(
                                tool_name=tc_data.get("tool_name", ""),
                                arguments=tc_data.get("arguments", {}),
                                result=tc_data.get("result"),
                                error=tc_data.get("error", ""),
                                duration_ms=tc_data.get("duration_ms", 0.0),
                            )
                            turn.tool_calls.append(tc)
                        trajectory.add_turn(turn)

                    # 重建奖励
                    for reward_data in traj_data.get("rewards", []):
                        from laap.training.rollout_collector import RewardSignal
                        rs = RewardSignal(
                            value=reward_data.get("value", 0.0),
                            source=reward_data.get("source", ""),
                        )
                        trajectory.add_reward(rs)

                except Exception as e:
                    logger.error(f"Failed to parse trajectory for {rollout_id}: {e}")

            with self._lock:
                end_time = time.time()
                result.trajectory = trajectory
                result.exit_code = exit_code
                result.end_time = end_time
                result.duration_ms = (end_time - result.start_time) * 1000

                if exit_code == 0:
                    result.status = "completed"
                    self._stats.completed += 1
                else:
                    result.status = "failed"
                    result.error = stderr[:500] if stderr else f"exit code {exit_code}"
                    self._stats.failed += 1

                self._stats.running -= 1

            if stderr:
                logger.debug(f"Rollout {rollout_id} stderr: {stderr[:200]}")

        except Exception as e:
            with self._lock:
                result.status = "failed"
                result.error = str(e)
                result.end_time = time.time()
                self._stats.failed += 1
                self._stats.running -= 1
                logger.error(f"Rollout {rollout_id} execution error: {e}")

        finally:
            self._cleanup_rollout(rollout_id, script_path, trajectory_path)
            # 尝试派发下一个任务
            self._dispatch_pending()

    def _generate_rollout_script(self, rollout_id: str,
                                  trajectory_path: str,
                                  task: RolloutTask) -> str:
        """生成 rollout 子进程脚本。

        OpenForge 论文中的:
        - Agent (包装推理服务器, 记录模型调用)
        - 任务结束后收集奖励
        - 重构为训练轨迹

        子进程独立运行, 隔离内存和状态。
        """
        return f'''"""
Auto-generated rollout script (Phase 2).
Rollout ID: {rollout_id}
"""
import json, sys, time
sys.path.insert(0, r"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")

from laap.training.rollout_collector import RolloutCollector, TurnSnapshot

# 初始化采集器
collector = RolloutCollector()
collector.start_episode(
    episode_id="{rollout_id}",
    metadata={{"orchestrator": "TrainingOrchestrator"}}
)

# 初始化 Agent
try:
    from laap.agent_core.agent import Agent, AgentConfig
    config = AgentConfig()
    agent = Agent(config=config, mode="{task.agent_mode}")
    agent.system_prompt = "你是一个有帮助的助手。"

    # 执行消息
    messages = {json.dumps(task.messages)}
    for i, msg in enumerate(messages):
        t0 = time.time()
        try:
            response = agent.chat(msg)
            error = ""
        except Exception as e:
            response = str(e)
            error = str(e)
        duration_ms = (time.time() - t0) * 1000

        snapshot = TurnSnapshot(
            turn_id=i + 1,
            user_message=msg,
            assistant_response=response,
            duration_ms=duration_ms,
            error=error,
        )
        collector.record_turn(snapshot)

    # 记录完成奖励
    collector.record_reward(1.0, source="task_completion")
    collector.end_episode(status="completed")

except Exception as e:
    collector.end_episode(status="failed")
    print(str(e), file=sys.stderr)
    sys.exit(1)

# 导出轨迹
trajs = collector.get_trajectories()
if trajs:
    traj = trajs[0]
    with open(r"{trajectory_path}", 'w', encoding='utf-8') as f:
        json.dump({{
            "trajectory_id": traj.trajectory_id,
            "turns": [t.to_dict() for t in traj.turns],
            "rewards": [{{"value": r.value, "source": r.source}} for r in traj.rewards],
            "final_reward": traj.final_reward,
            "status": traj.status,
            "metadata": traj.metadata,
        }}, f, ensure_ascii=False, default=str)
'''

    def _cleanup_rollout(self, rollout_id: str, script_path: str,
                         trajectory_path: str) -> None:
        """清理 rollout 产生的临时文件。"""
        with self._lock:
            self._running_processes.pop(rollout_id, None)
        try:
            if os.path.exists(script_path):
                os.unlink(script_path)
        except OSError:
            pass
        # 保留轨迹文件直到被收集
        # collect_rollout 后调用 cleanup_exported 可以显式清理

    def _collect_results(self) -> None:
        """后台线程: 持续检查超时 rollout。"""
        while True:
            try:
                time.sleep(5)
                now = time.time()
                with self._lock:
                    for rid, result in list(self._results.items()):
                        if result.status == "running" and result.start_time > 0:
                            elapsed = now - result.start_time
                            # 默认 300s 超时, 可通过任务配置
                            if elapsed > 300:
                                proc = self._running_processes.get(rid)
                                if proc:
                                    proc.kill()
                                result.status = "timed_out"
                                result.end_time = now
                                result.error = "Wall clock timeout (background check)"
                                self._stats.timed_out += 1
                                self._stats.running -= 1
                                logger.warning(
                                    f"Rollout {rid} timed out (background)"
                                )
            except Exception:
                pass

    # ── 查询 ─────────────────────────────────────────────────

    def status(self) -> dict:
        """编排器状态摘要。"""
        with self._lock:
            stats = {
                "total_submitted": self._stats.total_submitted,
                "completed": self._stats.completed,
                "failed": self._stats.failed,
                "timed_out": self._stats.timed_out,
                "discarded": self._stats.discarded,
                "running": self._stats.running,
                "pending": self._stats.pending,
                "max_concurrent": self.max_concurrent,
                "total_tokens_collected": self._stats.total_tokens_collected,
            }

            # 最近结果
            recent = sorted(
                [(rid, r) for rid, r in self._results.items()
                 if r.status in ("completed", "failed", "timed_out")],
                key=lambda x: x[1].end_time,
                reverse=True,
            )[:10]

            stats["recent_results"] = [
                {"rollout_id": rid, "status": r.status,
                 "duration_ms": r.duration_ms,
                 "error": r.error[:80] if r.error else ""}
                for rid, r in recent
            ]

            return stats

    def get_completed_trajectories(self) -> List[Trajectory]:
        """获取所有已完成的轨迹。"""
        with self._lock:
            return [
                r.trajectory for r in self._results.values()
                if r.status == "completed" and r.trajectory is not None
            ]

    def get_failed_rollouts(self) -> List[str]:
        """获取所有失败的 rollout id。"""
        with self._lock:
            return [
                rid for rid, r in self._results.items()
                if r.status in ("failed", "timed_out", "discarded")
            ]

    def cleanup_exported(self, rollout_id: str) -> bool:
        """清理已导出的轨迹临时文件。"""
        trajectory_path = os.path.join(
            self.data_dir, f"trajectory_{rollout_id}.json"
        )
        try:
            if os.path.exists(trajectory_path):
                os.unlink(trajectory_path)
                return True
        except OSError:
            pass
        return False

    def cleanup_all(self) -> int:
        """清理所有临时文件并重置状态。"""
        count = 0
        for fname in os.listdir(self.data_dir):
            if fname.startswith("trajectory_") or fname.startswith("rollout_"):
                try:
                    os.unlink(os.path.join(self.data_dir, fname))
                    count += 1
                except OSError:
                    pass
        return count

    @property
    def is_idle(self) -> bool:
        """编排器是否空闲 (没有正在运行的 rollout)。"""
        with self._lock:
            return self._stats.running == 0

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        """等待直到所有 rollout 完成。

        Args:
            timeout: 最大等待时间 (秒), None = 无限.

        Returns:
            True 如果成功等待到空闲, False 如果超时.
        """
        deadline = time.time() + (timeout or float('inf'))
        while time.time() < deadline:
            if self.is_idle:
                return True
            time.sleep(0.5)
        return False

    @property
    def scheduler_status(self) -> dict:
        """底层 TaskScheduler 的状态。"""
        if self._use_scheduler and self._scheduler is not None:
            return {
                "pending_tasks": self._scheduler.size(),
                "top_task": str(self._scheduler.peek()) if self._scheduler.peek() else None,
            }
        return {"pending_tasks": 0, "top_task": None}


# ══════════════════════════════════════════════════════════════════
# 便捷工厂
# ══════════════════════════════════════════════════════════════════

def create_orchestrator(max_concurrent: int = 4,
                        data_dir: Optional[str] = None) -> TrainingOrchestrator:
    """创建并返回一个配置好的 TrainingOrchestrator。

    Args:
        max_concurrent: 最大并发 rollout 数量.
        data_dir: 临时数据目录.

    Returns:
        TrainingOrchestrator 实例.
    """
    return TrainingOrchestrator(
        max_concurrent=max_concurrent,
        data_dir=data_dir,
    )


# ── 模块自检 ─────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    orch = create_orchestrator(max_concurrent=2)

    # 提交几个测试 rollout
    tasks = [
        RolloutTask(
            messages=[f"测试消息 {i}"],
            timeout_s=30,
            priority=i + 3,
        )
        for i in range(3)
    ]

    rids = orch.submit_batch(tasks)
    print(f"Submitted {len(rids)} rollouts: {rids}")

    # 等待完成
    orch.wait_until_idle(timeout=60)
    print(f"\nFinal status: {json.dumps(orch.status(), indent=2, ensure_ascii=False)}")

    completed = orch.get_completed_trajectories()
    print(f"\nCompleted trajectories: {len(completed)}")

    # 清理
    orch.cleanup_all()
    print("Cleanup done.")
