"""
Phase 1 — RolloutCollector (采集层)

OpenForge RL 集成: 在 agent 的标准对话循环上加一层"记录探头"，
不修改 agent 的核心逻辑。

功能:
  - 逐轮记录交互快照 (用户消息、助手回复、工具调用、计时)
  - 接收奖励信号 (fitness、stability、task_completion、user_feedback)
  - 聚合成完整的 episode trajectory
  - 导出为 veRL/GRPO 兼容的 JSONL 训练格式
  - 支持回调模式 (挂载到 ConversationLoop.on()) 和包装模式 (包装 Agent.chat())

数据流:
    Agent.chat() → TurnSnapshot → RolloutCollector → Trajectory → JSONL

设计原则:
  - 零侵入: 不修改 agent.py / conversation_loop.py 的任何一行
  - 可插拔: 不启用 training 时 Collector 不参与任何执行路径
  - 原子记录: 每条 TurnSnapshot 不可变，写入后不修改
  - 向前兼容: 输出格式对接 veRL 标准轨迹格式
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap.training.rollout_collector")


# ══════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════

@dataclass
class ToolCallSnapshot:
    """一次工具调用的快照。"""

    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class TurnSnapshot:
    """单轮交互的完整快照。

    对应 OpenForge 论文中一次 prompt-response 记录。
    """

    turn_id: int = 0
    user_message: str = ""
    assistant_response: str = ""
    tool_calls: List[ToolCallSnapshot] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    error: str = ""
    phase: str = "completed"  # started / thinking / tool_call / observing / completed / failed

    def to_dict(self) -> dict:
        """转为可序列化字典。"""
        d = asdict(self)
        d["tool_calls"] = [asdict(tc) for tc in self.tool_calls]
        return d


@dataclass
class RewardSignal:
    """一个奖励信号的记录。"""

    value: float = 0.0
    source: str = ""  # fitness / stability / task_completion / user_feedback
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trajectory:
    """一次完整的 episode 轨迹。

    对应 OpenForge 论文中一个 rollout 的完整训练轨迹。
    包含多轮交互 + 终止奖励。
    """

    trajectory_id: str = ""
    turns: List[TurnSnapshot] = field(default_factory=list)
    rewards: List[RewardSignal] = field(default_factory=list)
    final_reward: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    status: str = "completed"  # completed / truncated / failed / discarded

    def add_turn(self, turn: TurnSnapshot) -> None:
        """追加一轮交互。"""
        self.turns.append(turn)

    def add_reward(self, reward: RewardSignal) -> None:
        """追加一个奖励信号。"""
        self.rewards.append(reward)

    def compute_final_reward(self) -> Optional[float]:
        """计算最终奖励 (加权和, 取最近一次各来源奖励)。"""
        if not self.rewards:
            return self.final_reward

        # 按来源分组，每组取最后一次
        latest_by_source: Dict[str, float] = {}
        for r in self.rewards:
            latest_by_source[r.source] = r.value

        if not latest_by_source:
            return self.final_reward

        # 默认等权平均
        self.final_reward = sum(latest_by_source.values()) / len(latest_by_source)
        return self.final_reward

    def total_tokens(self) -> int:
        """轨迹的总 token 消耗。"""
        return sum(t.tokens_in + t.tokens_out for t in self.turns)

    def total_duration_ms(self) -> float:
        """轨迹的总时长 (毫秒)。"""
        if not self.turns:
            return 0.0
        return sum(t.duration_ms for t in self.turns)

    def to_training_record(self) -> dict:
        """转为 veRL / GRPO 兼容的训练记录。

        输出格式 (JSONL 每行):
        {
            "trajectory_id": "...",
            "conversations": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "...", "tool_calls": [...]},
                ...
            ],
            "reward": 0.85,
            "reward_sources": {"fitness": 0.8, "task_completion": 1.0},
            "metadata": { "total_tokens": 1500, "total_duration_ms": 3200 }
        }
        """
        self.compute_final_reward()

        conversations = []
        for turn in self.turns:
            conversations.append({
                "role": "user",
                "content": turn.user_message,
            })
            entry = {
                "role": "assistant",
                "content": turn.assistant_response,
            }
            if turn.tool_calls:
                entry["tool_calls"] = [
                    {
                        "name": tc.tool_name,
                        "arguments": tc.arguments,
                        "result": str(tc.result)[:500] if tc.result is not None else None,
                        "error": tc.error or None,
                    }
                    for tc in turn.tool_calls
                ]
            conversations.append(entry)

            if turn.error:
                conversations.append({
                    "role": "system",
                    "content": f"[error] {turn.error}",
                })

        record = {
            "trajectory_id": self.trajectory_id,
            "conversations": conversations,
            "reward": self.final_reward or 0.0,
            "reward_sources": {
                r.source: r.value for r in self.rewards
            },
            "metadata": {
                "total_tokens": self.total_tokens(),
                "total_duration_ms": self.total_duration_ms(),
                "num_turns": len(self.turns),
                "status": self.status,
            },
        }
        return record

    def to_jsonl_line(self) -> str:
        """转为 JSONL 一行。"""
        return json.dumps(self.to_training_record(), ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════
# RolloutCollector
# ══════════════════════════════════════════════════════════════════

class RolloutCollector:
    """Agent 交互数据采集器。

    两种使用模式:

    1. 回调模式 (推荐, 零侵入):
        >>> from laap.training import RolloutCollector
        >>> collector = RolloutCollector()
        >>> collector.start_episode()
        >>> # 在每次对话后手动记录:
        >>> collector.record_turn(snapshot)
        >>> collector.record_reward(0.85, source="task_completion")
        >>> collector.end_episode()

    2. 包装模式 (自动包装 Agent.chat):
        >>> collector = RolloutCollector()
        >>> wrapped_chat = collector.wrap(agent.chat)
        >>> response = wrapped_chat("你好")  # 自动记录

    ConversationLoop 集成:
        >>> loop = ConversationLoop(agent)
        >>> collector = RolloutCollector()
        >>> loop.on("turn_complete", collector.on_turn_complete)
        >>> loop.on("tool_call", collector.on_tool_call)
        >>> result = loop.process("你好")
        >>> trajectory = loop.on("episode_end", collector.on_episode_end)

    设计细节:
        - 每个 episode 独立采集, 自动生成 trajectory_id
        - 单次 episode 内允许多个 reward 信号, 按来源取最后一次
        - 异常 episode 标记为 discarded 不进入训练池
        - 所有方法线程安全 (threading.RLock)
    """

    def __init__(self):
        self._current_trajectory: Optional[Trajectory] = None
        self._trajectories: List[Trajectory] = []
        self._lock = threading.RLock()
        self._enabled: bool = True
        self._episode_active: bool = False

    # ── 启用/禁用 ────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """采集器是否启用。"""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """启用或禁用采集器。

        禁用时 record_turn 和 record_reward 为 no-op。
        """
        self._enabled = enabled
        logger.info(f"RolloutCollector {'enabled' if enabled else 'disabled'}")

    # ── Episode 生命周期 ──────────────────────────────────────

    def start_episode(self, episode_id: Optional[str] = None,
                      metadata: Optional[Dict[str, Any]] = None) -> str:
        """开始一个新的 episode 采集。

        Args:
            episode_id: 可选, 不传时自动生成.
            metadata: 可选的元数据 (环境名, 任务描述等).

        Returns:
            episode_id.
        """
        if not self._enabled:
            return ""

        with self._lock:
            if self._episode_active:
                logger.warning(
                    "Episode already active. Call end_episode() first."
                )
                return self._current_trajectory.trajectory_id

            tid = episode_id or f"ep_{uuid.uuid4().hex[:12]}"
            self._current_trajectory = Trajectory(
                trajectory_id=tid,
                metadata=metadata or {},
            )
            self._episode_active = True
            logger.debug(f"Episode started: {tid}")
            return tid

    def record_turn(self, snapshot: TurnSnapshot) -> None:
        """记录一轮交互快照。

        Args:
            snapshot: 单轮交互的完整快照.
        """
        if not self._enabled:
            return

        with self._lock:
            if not self._episode_active or self._current_trajectory is None:
                logger.debug("No active episode, starting one automatically")
                self.start_episode()

            self._current_trajectory.add_turn(snapshot)
            logger.debug(
                f"Turn {snapshot.turn_id} recorded "
                f"({snapshot.tokens_in + snapshot.tokens_out} tokens)"
            )

    def record_reward(self, value: float, source: str = "",
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        """记录一个奖励信号。

        Args:
            value: 奖励值 (通常 0.0 ~ 1.0).
            source: 来源标识 (fitness / stability / task_completion / user_feedback).
            metadata: 可选的元数据.
        """
        if not self._enabled:
            return

        with self._lock:
            if not self._episode_active or self._current_trajectory is None:
                logger.debug("No active episode, dropping reward signal")
                return

            signal = RewardSignal(
                value=value,
                source=source,
                metadata=metadata or {},
            )
            self._current_trajectory.add_reward(signal)
            logger.debug(f"Reward recorded: {value} from {source}")

    def end_episode(self, status: str = "completed",
                    final_reward: Optional[float] = None) -> Optional[str]:
        """结束当前 episode.

        Args:
            status: completed / truncated / failed / discarded.
            final_reward: 可选, 覆盖自动计算的最终奖励.

        Returns:
            trajectory_id, 若没有活跃 episode 则返回 None.
        """
        if not self._enabled:
            return None

        with self._lock:
            if not self._episode_active or self._current_trajectory is None:
                logger.debug("No active episode to end")
                return None

            traj = self._current_trajectory
            traj.status = status
            if final_reward is not None:
                traj.final_reward = final_reward
            else:
                traj.compute_final_reward()

            # 只有 completed 的轨迹才进入训练池
            if status == "completed" or status == "truncated":
                self._trajectories.append(traj)
                logger.info(
                    f"Episode {traj.trajectory_id} ended: "
                    f"status={status}, reward={traj.final_reward}, "
                    f"turns={len(traj.turns)}, tokens={traj.total_tokens()}"
                )
            else:
                logger.info(
                    f"Episode {traj.trajectory_id} discarded: "
                    f"status={status}"
                )

            self._episode_active = False
            tid = traj.trajectory_id
            self._current_trajectory = None
            return tid

    # ── ConversationLoop 回调集成 ─────────────────────────────

    def on_turn_complete(self, turn_data: Any) -> None:
        """ConversationLoop 的 turn_complete 事件回调。

        将 ConversationLoop 的 TurnRecord 转换为 TurnSnapshot 并记录。
        """
        if not self._enabled:
            return

        # 确保有活跃 episode
        with self._lock:
            if not self._episode_active:
                self.start_episode()

        # 构造 TurnSnapshot
        snapshot = TurnSnapshot(
            turn_id=getattr(turn_data, 'turn_id', 0),
            user_message=getattr(turn_data, 'user_msg', ''),
            assistant_response=getattr(turn_data, 'assistant_msg', ''),
            duration_ms=getattr(turn_data, 'duration_ms', 0.0),
            error=getattr(turn_data, 'error', ''),
            tokens_in=getattr(turn_data, 'tokens_in', 0),
            tokens_out=getattr(turn_data, 'tokens_out', 0),
        )

        # 提取工具调用
        tool_calls = getattr(turn_data, 'tool_calls', [])
        for tc in (tool_calls or []):
            if isinstance(tc, dict):
                tc_snapshot = ToolCallSnapshot(
                    tool_name=tc.get("tool", tc.get("name", "")),
                    arguments=tc.get("arguments", {}),
                    result=tc.get("result"),
                    error=tc.get("error", ""),
                    duration_ms=tc.get("duration_ms", 0.0),
                )
                snapshot.tool_calls.append(tc_snapshot)

        self.record_turn(snapshot)

    def on_tool_call(self, tool_data: Any) -> None:
        """ConversationLoop 的 tool_call 事件回调。

        记录工具调用事件 (turn_complete 中已经有完整工具列表,
        此回调可选用于实时监控).
        """
        if not self._enabled:
            return
        # 工具调用的详细信息在 turn_complete 中已完整记录,
        # 此回调仅用于日志和实时追踪
        tool_name = ""
        if isinstance(tool_data, dict):
            tool_name = tool_data.get("tool", "")
        elif hasattr(tool_data, 'tool_name'):
            tool_name = tool_data.tool_name
        logger.debug(f"Tool call observed: {tool_name}")

    def on_episode_end(self, episode_data: Any) -> None:
        """ConversationLoop 的 episode_end 事件回调。

        根据 episode_data 中的 status 决定是否丢弃轨迹。
        """
        if not self._enabled:
            return

        status = "completed"
        final_reward = None
        if isinstance(episode_data, dict):
            status = episode_data.get("status", "completed")
            final_reward = episode_data.get("final_reward")
        elif hasattr(episode_data, 'status'):
            status = episode_data.status

        self.end_episode(status=status, final_reward=final_reward)

    # ── 包装模式 ─────────────────────────────────────────────

    def wrap(self, chat_fn: Callable[[str], str],
             episode_id: Optional[str] = None) -> Callable[[str], str]:
        """包装一个 chat 函数, 自动记录每次调用。

        Args:
            chat_fn: 符合 Callable[[str], str] 签名的 chat 函数.
            episode_id: 可选, episode id.

        Returns:
            包装后的 chat 函数, 签名与原函数一致.
        """

        def wrapped(message: str) -> str:
            if not self._enabled:
                return chat_fn(message)

            # 自动启动 episode (首次调用)
            with self._lock:
                if not self._episode_active:
                    self.start_episode(
                        episode_id=episode_id,
                        metadata={"wrapped_fn": getattr(chat_fn, '__name__', 'chat')},
                    )

            # 记录输入
            t0 = time.time()

            # 调用原函数
            try:
                response = chat_fn(message)
                error = ""
            except Exception as e:
                response = str(e)
                error = str(e)

            duration_ms = (time.time() - t0) * 1000

            # 构造快照并记录
            snapshot = TurnSnapshot(
                turn_id=len(self._current_trajectory.turns) + 1
                if self._current_trajectory else 1,
                user_message=message,
                assistant_response=response,
                duration_ms=duration_ms,
                error=error,
            )
            self.record_turn(snapshot)

            return response

        return wrapped

    # ── 查询与导出 ───────────────────────────────────────────

    def get_trajectories(self) -> List[Trajectory]:
        """获取所有已完成的轨迹。"""
        with self._lock:
            return list(self._trajectories)

    def get_current_trajectory(self) -> Optional[Trajectory]:
        """获取当前正在采集的轨迹 (若存在)。"""
        with self._lock:
            return self._current_trajectory

    def is_active(self) -> bool:
        """是否有活跃的 episode。"""
        with self._lock:
            return self._episode_active

    def export_jsonl(self, path: str,
                     filter_status: Optional[List[str]] = None) -> int:
        """导出所有轨迹为 JSONL 文件。

        Args:
            path: 输出文件路径.
            filter_status: 可选, 只导出指定状态的轨迹,
                          如 ["completed", "truncated"].

        Returns:
            导出的轨迹数量.
        """
        with self._lock:
            trajectories = list(self._trajectories)

        if filter_status:
            trajectories = [t for t in trajectories if t.status in filter_status]

        count = 0
        with open(path, 'w', encoding='utf-8') as f:
            for traj in trajectories:
                if traj.status in ("completed", "truncated"):
                    # 丢弃空轨迹 (没有有效 turn)
                    if not traj.turns:
                        continue
                    f.write(traj.to_jsonl_line() + '\n')
                    count += 1

        logger.info(f"Exported {count} trajectories to {path}")
        return count

    def summary(self) -> dict:
        """采集器状态摘要。"""
        with self._lock:
            trajectories = list(self._trajectories)

        by_status: Dict[str, int] = {}
        total_tokens = 0
        for t in trajectories:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            total_tokens += t.total_tokens()

        return {
            "enabled": self._enabled,
            "active": self._episode_active,
            "total_trajectories": len(trajectories),
            "by_status": by_status,
            "total_tokens_collected": total_tokens,
            "current_episode_id":
                self._current_trajectory.trajectory_id
                if self._current_trajectory else None,
        }

    def reset(self) -> None:
        """重置采集器, 清除所有已采集轨迹。"""
        with self._lock:
            self._current_trajectory = None
            self._trajectories.clear()
            self._episode_active = False
            logger.info("RolloutCollector reset: all trajectories cleared")


# ══════════════════════════════════════════════════════════════════
# 便捷工厂函数
# ══════════════════════════════════════════════════════════════════

def create_collector(
    enabled: bool = True,
    auto_start: bool = False,
    episode_metadata: Optional[Dict[str, Any]] = None,
) -> RolloutCollector:
    """创建并返回一个配置好的 RolloutCollector 实例。

    Args:
        enabled: 是否默认启用采集.
        auto_start: 是否在创建后自动开始一个 episode.
        episode_metadata: 自动开始时的元数据.

    Returns:
        配置好的 RolloutCollector 实例.
    """
    collector = RolloutCollector()
    collector.set_enabled(enabled)
    if auto_start:
        collector.start_episode(metadata=episode_metadata)
    return collector


# ── 模块自检 ─────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 快速演示
    collector = create_collector()
    collector.start_episode(metadata={"env": "test"})

    # 模拟 3 轮对话
    for i in range(3):
        snapshot = TurnSnapshot(
            turn_id=i + 1,
            user_message=f"测试消息 {i + 1}",
            assistant_response=f"测试回复 {i + 1}",
            tokens_in=50,
            tokens_out=100,
            duration_ms=1500.0,
        )
        collector.record_turn(snapshot)

    collector.record_reward(0.85, source="task_completion")
    collector.record_reward(0.75, source="fitness")
    collector.end_episode()

    # 导出演示
    collector.export_jsonl("test_trajectories.jsonl")

    print("摘要:", json.dumps(collector.summary(), ensure_ascii=False, indent=2))
    print("\n训练记录样例:")
    traj = collector.get_trajectories()[0]
    print(json.dumps(traj.to_training_record(), ensure_ascii=False, indent=2))
