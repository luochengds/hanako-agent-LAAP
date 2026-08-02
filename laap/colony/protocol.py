"""Agent 间协作协议

定义标准化的 Agent 间通信协议：
- 消息格式（source, target, type, payload, timestamp）
- 订阅/发布模式
- 任务分发和结果聚合

本模块在现有 `laap.sandbox.colony.ColonyEventBus` 之上提供面向
Agent 协作场景的高层 API，便于不同 Colony 数字生命体之间通过
消息进行任务委托与结果汇总。底层事件总线负责沙箱级别的路由与
过滤，本模块专注于"业务级"的协作语义。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap.colony.protocol")

__all__ = [
    "AgentMessage",
    "ColonyProtocol",
    "TaskDispatcher",
    "CollaborationScenario",
    # P4-charter-guardian
    "GuardianRegistry",
    "get_guardian_registry",
    "reset_guardian_registry_for_test",
]


# ============================================================
# 标准消息类型常量
# ============================================================
class _MessageType:
    """标准 Agent 间消息类型常量

    这些常量仅作为推荐值使用，订阅者可使用任意字符串作为消息类型。
    """

    TASK_ASSIGN = "task_assign"  # 任务分发
    TASK_RESULT = "task_result"  # 任务结果回传
    TASK_FAILED = "task_failed"  # 任务执行失败
    QUERY = "query"  # 信息查询
    REPLY = "reply"  # 信息回复
    NOTIFY = "notify"  # 通知类消息
    HEARTBEAT = "heartbeat"  # 心跳


# Agent 角色 → 默认 agent_id 映射（用于 TaskDispatcher 路由）
_DEFAULT_ROLE_AGENT_IDS: Dict[str, str] = {
    "architect": "architect-agent",
    "test_engineer": "test-engineer-agent",
    "security": "security-agent",
    "performance": "perf-agent",
    "doc": "doc-agent",
}


@dataclass
class AgentMessage:
    """Agent 间消息

    通用消息载体，可在 Agent 之间定向或广播传递。
    所有字段均为可序列化的基础类型，便于通过事件总线或外部 IPC 传输。
    """

    source: str  # 发送方 agent_id
    target: str  # 接收方 agent_id 或 "broadcast"
    type: str  # 消息类型（参考 _MessageType 常量）
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:8]}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "message_id": self.message_id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMessage":
        """从字典构造消息实例。"""
        return cls(
            source=data.get("source", ""),
            target=data.get("target", "broadcast"),
            type=data.get("type", ""),
            payload=dict(data.get("payload", {})),
            timestamp=float(data.get("timestamp", time.time())),
            message_id=data.get("message_id", f"msg-{uuid.uuid4().hex[:8]}"),
        )


class ColonyProtocol:
    """Colony 协作协议

    支持订阅/发布模式与点对点消息，并提供消息历史记录以便
    UI 层展示 Agent 之间的协作流向。

    线程安全：使用 `threading.RLock` 保护订阅者列表与历史记录。
    """

    def __init__(self) -> None:
        # 消息类型 -> 订阅者回调列表
        self._subscribers: Dict[str, List[Callable[[AgentMessage], None]]] = {}
        # 通配订阅者（订阅所有消息）
        self._wildcard_subscribers: List[Callable[[AgentMessage], None]] = []
        # 消息历史（按时间顺序， newest 在尾部）
        self._message_history: List[AgentMessage] = []
        # 最大历史保留条数
        self._max_history = 1000
        # 互斥锁，保护订阅者列表与历史记录
        self._lock = threading.RLock()

    # ------------------------------------------------------------
    # 订阅 / 取消订阅
    # ------------------------------------------------------------

    def subscribe(self, message_type: str, handler: Callable[[AgentMessage], None]) -> None:
        """订阅特定类型的消息。

        Args:
            message_type: 消息类型字符串；传入 "*" 表示订阅所有消息
            handler: 消息回调函数，接收 AgentMessage 实例
        """
        with self._lock:
            if message_type == "*":
                if handler not in self._wildcard_subscribers:
                    self._wildcard_subscribers.append(handler)
                return
            handlers = self._subscribers.setdefault(message_type, [])
            if handler not in handlers:
                handlers.append(handler)

    def unsubscribe(self, message_type: str, handler: Callable[[AgentMessage], None]) -> bool:
        """取消订阅。

        Args:
            message_type: 订阅时使用的消息类型；"*" 表示取消通配订阅
            handler: 待移除的回调函数

        Returns:
            是否成功找到并移除回调
        """
        with self._lock:
            if message_type == "*":
                if handler in self._wildcard_subscribers:
                    self._wildcard_subscribers.remove(handler)
                    return True
                return False
            handlers = self._subscribers.get(message_type)
            if handlers and handler in handlers:
                handlers.remove(handler)
                if not handlers:
                    self._subscribers.pop(message_type, None)
                return True
            return False

    # ------------------------------------------------------------
    # 发布 / 发送
    # ------------------------------------------------------------

    def publish(self, message: AgentMessage) -> int:
        """发布消息（广播或定向）。

        路由规则：
        1. 当 `message.target == "broadcast"` 时，通知所有订阅该类型
           的订阅者以及通配订阅者；
        2. 否则仅通知该类型订阅者中 `_agent_id` 属性匹配 `target` 的回调
           以及通配订阅者中匹配的回调（若回调无 `_agent_id` 属性则视为匹配）；
        3. 同步调用回调（保持顺序），异常被记录但不影响其他订阅者；
        4. 消息加入历史记录。

        Args:
            message: 待发布消息

        Returns:
            实际投递到的订阅者数量
        """
        callbacks_to_invoke: List[Callable[[AgentMessage], None]] = []
        with self._lock:
            type_handlers = self._subscribers.get(message.type, [])
            callbacks_to_invoke.extend(self._filter_by_target(type_handlers, message.target))
            callbacks_to_invoke.extend(self._filter_by_target(self._wildcard_subscribers, message.target))

            self._message_history.append(message)
            if len(self._message_history) > self._max_history:
                # 仅截断末尾保留最近的 N 条
                self._message_history = self._message_history[-self._max_history:]

        delivered = 0
        for cb in callbacks_to_invoke:
            try:
                cb(message)
                delivered += 1
            except Exception:  # noqa: BLE001 — 不让一个回调异常影响其他订阅者
                logger.exception(f"Agent 消息回调异常 type={message.type} id={message.message_id}")
        return delivered

    def send(self, source: str, target: str, msg_type: str, payload: Dict[str, Any]) -> AgentMessage:
        """发送点对点消息。

        Args:
            source: 发送方 agent_id
            target: 接收方 agent_id（非 "broadcast"）
            msg_type: 消息类型
            payload: 消息负载

        Returns:
            创建并发出的 AgentMessage 实例
        """
        message = AgentMessage(
            source=source,
            target=target,
            type=msg_type,
            payload=payload,
        )
        self.publish(message)
        return message

    def broadcast(self, source: str, msg_type: str, payload: Dict[str, Any]) -> AgentMessage:
        """广播消息给所有订阅该类型的 Agent。

        Args:
            source: 发送方 agent_id
            msg_type: 消息类型
            payload: 消息负载

        Returns:
            创建并广播的 AgentMessage 实例
        """
        message = AgentMessage(
            source=source,
            target="broadcast",
            type=msg_type,
            payload=payload,
        )
        self.publish(message)
        return message

    # ------------------------------------------------------------
    # 历史查询
    # ------------------------------------------------------------

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的消息历史（按时间倒序）。

        Args:
            limit: 返回的最大条数

        Returns:
            消息字典列表（最近的最先）
        """
        with self._lock:
            snapshot = list(self._message_history)
        snapshot.reverse()
        return [m.to_dict() for m in snapshot[: max(0, limit)]]

    def get_agent_messages(self, agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取与指定 Agent 相关的消息（作为发送方或接收方）。

        Args:
            agent_id: Agent 标识
            limit: 返回的最大条数

        Returns:
            消息字典列表（最近的最先）
        """
        with self._lock:
            snapshot = [
                m for m in self._message_history
                if m.source == agent_id
                or m.target == agent_id
                or m.target == "broadcast"
            ]
        snapshot.reverse()
        return [m.to_dict() for m in snapshot[: max(0, limit)]]

    # ------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------

    @staticmethod
    def _filter_by_target(handlers: List[Callable[[AgentMessage], None]],
                          target: str) -> List[Callable[[AgentMessage], None]]:
        """按 target 过滤订阅者。

        - 广播消息：返回全部
        - 定向消息：仅返回 `_agent_id` 属性等于 target，或没有该属性的回调
        """
        if target == "broadcast":
            return list(handlers)
        result: List[Callable[[AgentMessage], None]] = []
        for cb in handlers:
            cb_agent_id = getattr(cb, "_agent_id", None)
            if cb_agent_id is None or cb_agent_id == target:
                result.append(cb)
        return result


class CollaborationScenario:
    """协作场景常量与角色路由配置

    用于 TaskDispatcher 在不同协作场景下决定任务分发对象。
    场景配置以"任务类别 -> 角色列表"的形式描述。
    """

    # 场景：架构问题
    ARCHITECTURE = "architecture"
    # 场景：安全漏洞
    SECURITY = "security"
    # 场景：性能瓶颈
    PERFORMANCE = "performance"

    # 各场景下需要参与的 Agent 角色列表
    SCENARIO_ROLES: Dict[str, List[str]] = {
        ARCHITECTURE: ["test_engineer", "security", "performance"],
        SECURITY: ["architect", "test_engineer"],
        PERFORMANCE: ["test_engineer", "doc"],
    }

    # 各场景下分发给每个角色的子任务标签（描述该角色需要做的事）
    SCENARIO_SUBTASK_LABELS: Dict[str, Dict[str, str]] = {
        ARCHITECTURE: {
            "test_engineer": "测试验证",
            "security": "安全审计",
            "performance": "性能评估",
        },
        SECURITY: {
            "architect": "修复方案",
            "test_engineer": "测试用例",
        },
        PERFORMANCE: {
            "test_engineer": "基准测试",
            "doc": "文档更新",
        },
    }


class TaskDispatcher:
    """协作任务分发器

    支持任务分解、按角色路由以及结果聚合。分发器为每个协作任务
    分配一个 `task_id`，并跟踪各子任务的完成状态。

    超时机制：
    - dispatch() 时记录 timeout_at (created_at + default_timeout_sec)
    - check_timeouts() 扫描所有 pending 任务，超时的自动标记为 failed
    - 超时任务通过 protocol 广播 task_failed/event=timeout 通知
    - cleanup_old_tasks() 清理已完成/已失败的旧任务
    """

    def __init__(self, protocol: ColonyProtocol,
                 default_timeout_sec: float = 300.0) -> None:
        """
        Args:
            protocol: ColonyProtocol 实例
            default_timeout_sec: 默认超时秒数（从分发时起算），默认 5 分钟
        """
        self._protocol = protocol
        self._default_timeout_sec = default_timeout_sec
        # task_id -> 任务元信息
        self._pending_tasks: Dict[str, Dict[str, Any]] = {}
        # task_id -> 各 agent 的结果列表
        self._completed_results: Dict[str, List[Dict[str, Any]]] = {}
        # 角色到 agent_id 的映射（可被外部覆盖以适配真实环境）
        self._role_to_agent: Dict[str, str] = dict(_DEFAULT_ROLE_AGENT_IDS)
        self._lock = threading.RLock()

    # ------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------

    def register_agent(self, role: str, agent_id: str) -> None:
        """注册或更新角色对应的 agent_id。

        Args:
            role: Agent 角色标识（如 "architect"）
            agent_id: 实际的 agent_id
        """
        with self._lock:
            self._role_to_agent[role] = agent_id

    def get_agent_for_role(self, role: str) -> Optional[str]:
        """获取角色对应的 agent_id（若未注册返回 None）。"""
        with self._lock:
            return self._role_to_agent.get(role)

    # ------------------------------------------------------------
    # 任务分发与聚合
    # ------------------------------------------------------------

    def dispatch(self, main_task: Dict[str, Any], agent_roles: List[str]) -> str:
        """分发协作任务

        将主任务分解为多个子任务，按角色路由到对应 Agent，并通过
        协议发送 `task_assign` 消息。

        Args:
            main_task: 主任务描述，建议包含字段：
                - title: 任务标题
                - description: 任务描述
                - scenario: 协作场景（参考 CollaborationScenario 常量）
                - priority: 优先级（critical/high/medium/low）
            agent_roles: 需要参与的 Agent 角色列表

        Returns:
            task_id: 协作任务 ID
        """
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        scenario = main_task.get("scenario", "")
        subtask_labels = CollaborationScenario.SCENARIO_SUBTASK_LABELS.get(scenario, {})

        subtasks: List[Dict[str, Any]] = []
        with self._lock:
            for role in agent_roles:
                agent_id = self._role_to_agent.get(role)
                if not agent_id:
                    logger.warning(f"角色 '{role}' 未注册 agent_id，已跳过")
                    continue
                label = subtask_labels.get(role, role)
                subtask = {
                    "role": role,
                    "agent_id": agent_id,
                    "label": label,
                    "status": "pending",
                }
                subtasks.append(subtask)
                # 通过协议发送任务分配消息
                self._protocol.send(
                    source="dispatcher",
                    target=agent_id,
                    msg_type=_MessageType.TASK_ASSIGN,
                    payload={
                        "task_id": task_id,
                        "scenario": scenario,
                        "label": label,
                        "main_task": main_task,
                    },
                )

            now = time.time()
            self._pending_tasks[task_id] = {
                "task_id": task_id,
                "main_task": main_task,
                "scenario": scenario,
                "subtasks": subtasks,
                "created_at": now,
                "timeout_at": now + self._default_timeout_sec,
                "status": "pending",
            }
            self._completed_results.setdefault(task_id, [])
        return task_id

    def dispatch_scenario(self, scenario: str, main_task: Dict[str, Any]) -> str:
        """基于预定义协作场景分发任务。

        Args:
            scenario: CollaborationScenario 中的场景常量
            main_task: 主任务描述

        Returns:
            task_id
        """
        roles = CollaborationScenario.SCENARIO_ROLES.get(scenario, [])
        enriched_task = {**main_task, "scenario": scenario}
        return self.dispatch(enriched_task, roles)

    def collect_result(self, task_id: str, agent_id: str, result: Dict[str, Any]) -> bool:
        """收集子任务结果

        Args:
            task_id: 协作任务 ID
            agent_id: 提交结果的 Agent ID
            result: 结果数据，建议包含 status / summary / details 字段

        Returns:
            是否成功接收（任务存在且未完成时为 True）
        """
        with self._lock:
            task = self._pending_tasks.get(task_id)
            if task is None:
                logger.warning(f"未知 task_id={task_id}，结果被丢弃")
                return False
            # 标记对应子任务为已完成
            for sub in task.get("subtasks", []):
                if sub.get("agent_id") == agent_id:
                    sub["status"] = "completed"
                    sub["completed_at"] = time.time()
                    break
            # 追加结果
            result_entry = {
                "agent_id": agent_id,
                "task_id": task_id,
                "result": result,
                "submitted_at": time.time(),
            }
            self._completed_results.setdefault(task_id, []).append(result_entry)
            # 检查是否全部完成
            if all(sub.get("status") == "completed" for sub in task.get("subtasks", [])):
                task["status"] = "completed"
                task["completed_at"] = time.time()
                # 通过协议通知任务完成
                self._protocol.broadcast(
                    source="dispatcher",
                    msg_type=_MessageType.NOTIFY,
                    payload={
                        "task_id": task_id,
                        "event": "task_completed",
                        "scenario": task.get("scenario", ""),
                    },
                )
        return True

    def aggregate(self, task_id: str) -> Optional[Dict[str, Any]]:
        """聚合所有子任务结果

        仅当所有子任务均完成时才返回聚合结果，否则返回 None。

        Args:
            task_id: 协作任务 ID

        Returns:
            聚合结果字典或 None（任务不存在或未完成）
        """
        with self._lock:
            task = self._pending_tasks.get(task_id)
            if task is None:
                return None
            subtasks = task.get("subtasks", [])
            if not subtasks:
                return None
            if not all(sub.get("status") == "completed" for sub in subtasks):
                return None
            results = list(self._completed_results.get(task_id, []))
            return {
                "task_id": task_id,
                "scenario": task.get("scenario", ""),
                "main_task": task.get("main_task", {}),
                "summary": self._summarize_results(results),
                "results": results,
                "completed_at": task.get("completed_at"),
            }

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """获取任务状态

        Args:
            task_id: 协作任务 ID

        Returns:
            状态字典。若任务不存在，返回 `{"status": "unknown", "task_id": task_id}`。
        """
        with self._lock:
            task = self._pending_tasks.get(task_id)
            if task is None:
                return {"status": "unknown", "task_id": task_id}
            subtasks = task.get("subtasks", [])
            completed = sum(1 for s in subtasks if s.get("status") == "completed")
            return {
                "task_id": task_id,
                "status": task.get("status", "pending"),
                "scenario": task.get("scenario", ""),
                "total_subtasks": len(subtasks),
                "completed_subtasks": completed,
                "subtasks": [dict(s) for s in subtasks],
                "created_at": task.get("created_at"),
                "completed_at": task.get("completed_at"),
            }

    def list_pending_tasks(self) -> List[Dict[str, Any]]:
        """列出所有进行中的协作任务状态。"""
        with self._lock:
            return [self.get_task_status(tid) for tid in list(self._pending_tasks.keys())]

    # ------------------------------------------------------------
    # 超时 & 清理
    # ------------------------------------------------------------

    def check_timeouts(self) -> List[str]:
        """检查并标记超时任务。

        遍历所有 pending 任务，对超过 timeout_at 的任务：
        1. 标记为 status=failed, reason=timeout
        2. 通知所有未完成的子任务
        3. 通过 protocol 广播 task_failed 事件

        Returns:
            超时的 task_id 列表
        """
        now = time.time()
        timed_out: List[str] = []

        with self._lock:
            for task_id, task in list(self._pending_tasks.items()):
                if task.get("status") != "pending":
                    continue
                timeout_at = task.get("timeout_at")
                if timeout_at is not None and now >= timeout_at:
                    task["status"] = "failed"
                    task["failed_at"] = now
                    task["failure_reason"] = "timeout"
                    timed_out.append(task_id)

        # 在锁外广播通知（避免回调中死锁）
        for task_id in timed_out:
            task = self._pending_tasks.get(task_id)
            self._protocol.broadcast(
                source="dispatcher",
                msg_type=_MessageType.TASK_FAILED,
                payload={
                    "task_id": task_id,
                    "event": "timeout",
                    "scenario": task.get("scenario", "") if task else "",
                },
            )
            logger.warning(f"任务 {task_id} 超时，已标记为 failed")

        return timed_out

    def cleanup_old_tasks(self, max_age_sec: float = 3600.0) -> int:
        """清理超过 max_age_sec 的已完成/已失败任务。

        Args:
            max_age_sec: 保留的最大秒数（默认 1 小时）

        Returns:
            清理的任务数量
        """
        now = time.time()
        removed = 0

        with self._lock:
            task_ids = list(self._pending_tasks.keys())
            for task_id in task_ids:
                task = self._pending_tasks.get(task_id)
                if not task:
                    continue
                status = task.get("status", "")
                if status not in ("completed", "failed"):
                    continue
                completed_at = task.get("completed_at") or task.get("failed_at")
                if completed_at and (now - completed_at) >= max_age_sec:
                    del self._pending_tasks[task_id]
                    self._completed_results.pop(task_id, None)
                    removed += 1

        if removed:
            logger.info(f"清理了 {removed} 个过期任务")
        return removed

    # ------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------

    @staticmethod
    def _summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "total_results": len(results),
            "by_agent": {},
        }
        for entry in results:
            agent_id = entry.get("agent_id", "unknown")
            result = entry.get("result", {})
            summary["by_agent"][agent_id] = {
                "status": result.get("status", "unknown"),
                "summary": result.get("summary", ""),
            }
        return summary


# ============================================================
# P4-charter-guardian: 宪章守护者注册表
# ============================================================
# 不可修改上方 ColonyProtocol / TaskDispatcher / CollaborationScenario
# 类（已稳定被 P3 / P2 / P1 引用）。GuardianRegistry 作为独立类追加到
# 本文件末尾，依赖 P4-witness-trail 的 WitnessTrail.record 沉淀行使
# 记录（不可篡改），依赖 events.bus 发布 guardian_act 事件。
class GuardianRegistry:
    """宪章守护者注册表（P4-charter-guardian）

    维护守护者公钥白名单 + 目标 agent 状态跟踪，所有行使动作通过
    P4-witness-trail 的 ``WitnessTrail.record('guardian_act', ...)``
    沉淀到不可篡改的链式日志中。

    核心约束：
    - **白名单校验**：只有 ``_guardian_pks`` 集合内的公钥可调用
      ``guardian_act``，否则返回 ``unauthorized``；
    - **不可篡改**：每次行使必须写入 ``WitnessTrail``（链式 SHA-256
      hash + 可选 Ed25519 签名），事后无法删除或修改；
    - **状态跟踪**：``_target_status`` 记录每个目标 agent 的当前状态
      （active / suspended / warned / expelled / restored），用于
      社区健康仪表盘实时展示；
    - **事件发布**：每次行使通过 ``events.bus.publish_simple`` 发布
      ``guardian_act`` 事件，UI / 其他模块可订阅；
    - **私钥永不离开 sidecar**（spec L435）：``guardian_private_key``
      仅 sidecar 内部传入 raw bytes 用于签名，MCP 工具不暴露此参数；
    - **幂等**：同一行使可重复调用（每次产生新 trail_id，但 target
      状态幂等）。

    线程安全：使用 ``threading.RLock`` 保护所有可变状态。
    """

    # 允许的 action 集合（spec L367）
    ALLOWED_ACTIONS: set = {"suspend", "warn", "expel", "restore"}

    # action → 目标状态映射
    ACTION_TO_STATUS: Dict[str, str] = {
        "suspend": "suspended",
        "warn": "warned",
        "expel": "expelled",
        "restore": "restored",
    }

    # 视为"滥用事件"的 action（用于 recent_abuse_events 统计）
    ABUSE_ACTIONS: set = {"suspend", "warn", "expel"}

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # 守护者公钥白名单（base64 Ed25519 公钥）
        self._guardian_pks: set = set()
        # 目标 agent 标识 → 当前状态（active/suspended/warned/expelled/restored）
        self._target_status: Dict[str, str] = {}
        # 行使历史列表（按时间顺序，newest 在尾部）
        self._acts: List[Dict[str, Any]] = []

    # ------------------------------------------------------------
    # 白名单管理
    # ------------------------------------------------------------

    def register_guardian(self, public_key: str) -> Dict[str, Any]:
        """注册一个守护者公钥到白名单.

        Args:
            public_key: 守护者 base64 Ed25519 公钥.

        Returns:
            ``{registered: bool, public_key: str, total_guardians: int}``.
        """
        if not isinstance(public_key, str) or not public_key.strip():
            return {"registered": False, "reason": "empty_public_key"}
        pk = public_key.strip()
        with self._lock:
            self._guardian_pks.add(pk)
            total = len(self._guardian_pks)
        logger.info(f"GuardianRegistry: registered guardian pk={pk[:16]}... total={total}")
        return {"registered": True, "public_key": pk, "total_guardians": total}

    def unregister_guardian(self, public_key: str) -> Dict[str, Any]:
        """从白名单移除一个守护者公钥（用于测试或权限回收）."""
        if not isinstance(public_key, str) or not public_key.strip():
            return {"unregistered": False, "reason": "empty_public_key"}
        pk = public_key.strip()
        with self._lock:
            if pk in self._guardian_pks:
                self._guardian_pks.discard(pk)
                total = len(self._guardian_pks)
                logger.info(f"GuardianRegistry: unregistered guardian pk={pk[:16]}... total={total}")
                return {"unregistered": True, "public_key": pk, "total_guardians": total}
            return {"unregistered": False, "reason": "not_in_whitelist", "public_key": pk}

    def is_guardian(self, public_key: str) -> bool:
        """检查公钥是否在守护者白名单中."""
        if not isinstance(public_key, str):
            return False
        with self._lock:
            return public_key.strip() in self._guardian_pks

    def list_guardians(self) -> List[str]:
        """列出所有守护者公钥（排序后）."""
        with self._lock:
            return sorted(self._guardian_pks)

    # ------------------------------------------------------------
    # 行使守护权力
    # ------------------------------------------------------------

    def guardian_act(
        self,
        action: str,
        target: str,
        reason: str,
        guardian_public_key: str,
        guardian_private_key: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """行使守护权力（spec L364-369）.

        1. 白名单校验：``guardian_public_key`` 必须在 ``_guardian_pks`` 中；
        2. action 校验：必须属于 ``{suspend, warn, expel, restore}``；
        3. 写入 ``WitnessTrail``（event_type='guardian_act'，不可篡改）；
        4. 更新 ``_target_status[target]`` 为对应状态；
        5. 通过 ``events.bus.publish_simple`` 发布 ``guardian_act`` 事件.

        Args:
            action: 行使动作，∈ ``{suspend, warn, expel, restore}``.
            target: 目标 agent 标识（公钥或 agent_id）.
            reason: 行使理由（人类可读）.
            guardian_public_key: 行使者 base64 公钥（必须在白名单中）.
            guardian_private_key: 行使者 32 字节 Raw Ed25519 私钥（可选，
                spec L435 私钥永不离开 sidecar，本参数仅供 sidecar 内部调用
                用于对 witness trail entry 签名）.

        Returns:
            ``{acted: bool, act_id?: str, trail_id?: str, hash?: str,
            action?: str, target?: str, target_status?: str,
            reason?: str, reason_if_failed?: str}``.
        """
        # 参数基础校验
        if not isinstance(action, str) or action not in self.ALLOWED_ACTIONS:
            return {
                "acted": False,
                "reason": "invalid_action",
                "allowed_actions": sorted(self.ALLOWED_ACTIONS),
            }
        if not isinstance(target, str) or not target.strip():
            return {"acted": False, "reason": "empty_target"}
        if not isinstance(reason, str) or not reason.strip():
            return {"acted": False, "reason": "empty_reason"}
        if not isinstance(guardian_public_key, str) or not guardian_public_key.strip():
            return {"acted": False, "reason": "empty_guardian_public_key"}

        guardian_pk = guardian_public_key.strip()
        target_id = target.strip()

        # 白名单校验
        with self._lock:
            if guardian_pk not in self._guardian_pks:
                logger.warning(
                    f"GuardianRegistry: unauthorized guardian_act by pk={guardian_pk[:16]}... "
                    f"(not in whitelist)"
                )
                return {
                    "acted": False,
                    "reason": "unauthorized",
                    "guardian_public_key": guardian_pk,
                }

        # 构造 payload（写入 WitnessTrail）
        act_id = f"guard-act-{uuid.uuid4().hex[:12]}"
        new_status = self.ACTION_TO_STATUS[action]
        payload: Dict[str, Any] = {
            "act_id": act_id,
            "action": action,
            "target": target_id,
            "reason": reason,
            "guardian_public_key": guardian_pk,
            "previous_status": self._target_status.get(target_id, "active"),
            "new_status": new_status,
        }

        # 写入 WitnessTrail（不可篡改）
        trail_id = ""
        trail_hash = ""
        try:
            from laap.events.bus import get_witness_trail
            witness = get_witness_trail()
            record_result = witness.record(
                event_type="guardian_act",
                recorder=guardian_pk,
                payload=payload,
                recorder_public_key=guardian_pk,
                recorder_private_key=guardian_private_key,
                broadcast=False,  # guardian_act 非里程碑，不触发跨节点广播
            )
            if record_result.get("recorded"):
                trail_id = record_result.get("trail_id", "")
                trail_hash = record_result.get("hash", "")
        except Exception as exc:
            logger.error(
                f"GuardianRegistry: witness_trail record failed: {exc}",
                exc_info=True,
            )
            return {
                "acted": False,
                "reason": "witness_trail_record_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

        # 更新目标状态 + 追加历史
        with self._lock:
            self._target_status[target_id] = new_status
            act_entry = {
                "act_id": act_id,
                "action": action,
                "target": target_id,
                "reason": reason,
                "guardian_public_key": guardian_pk,
                "previous_status": payload["previous_status"],
                "new_status": new_status,
                "trail_id": trail_id,
                "trail_hash": trail_hash,
                "timestamp": time.time(),
            }
            self._acts.append(act_entry)

        # 发布 guardian_act 事件（让 UI / 其他模块可订阅）
        try:
            from laap.events.bus import bus as event_bus
            event_bus.publish_simple(
                "guardian_act",
                {
                    "act_id": act_id,
                    "action": action,
                    "target": target_id,
                    "reason": reason,
                    "guardian_public_key": guardian_pk,
                    "new_status": new_status,
                    "trail_id": trail_id,
                },
                source="guardian",
            )
        except Exception as exc:
            logger.warning(f"GuardianRegistry: emit guardian_act event failed: {exc}")

        logger.info(
            f"GuardianRegistry: guardian_act action={action} target={target_id} "
            f"by pk={guardian_pk[:16]}... trail_id={trail_id} new_status={new_status}"
        )
        return {
            "acted": True,
            "act_id": act_id,
            "trail_id": trail_id,
            "hash": trail_hash,
            "action": action,
            "target": target_id,
            "target_status": new_status,
            "reason": reason,
            "guardian_public_key": guardian_pk,
        }

    # ------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------

    def list_acts(
        self,
        target: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询行使历史（按时间倒序）.

        Args:
            target: 按目标 agent 过滤（None 表示不过滤）.
            action: 按 action 过滤（None 表示不过滤）.
            limit: 最大返回条数.

        Returns:
            行使记录 dict 列表（最近的最先）.
        """
        try:
            safe_limit = int(limit)
        except (TypeError, ValueError):
            safe_limit = 100
        if safe_limit <= 0:
            safe_limit = 100
        with self._lock:
            snapshot = list(self._acts)
        result: List[Dict[str, Any]] = []
        for entry in snapshot:
            if target and entry.get("target") != target:
                continue
            if action and entry.get("action") != action:
                continue
            result.append(dict(entry))
        result.reverse()  # 最近优先
        return result[:safe_limit]

    def get_target_status(self, target: str) -> str:
        """获取目标 agent 当前状态（默认 'active'）."""
        if not isinstance(target, str):
            return "active"
        with self._lock:
            return self._target_status.get(target, "active")

    def list_targets(self) -> Dict[str, str]:
        """列出所有目标 agent 及其当前状态."""
        with self._lock:
            return dict(self._target_status)

    # ------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """社区健康仪表盘统计.

        Returns:
            ``{total_acts, by_action, by_target_status, active_guardians,
            recent_abuse_events, targets_count}``.
        """
        with self._lock:
            acts_snapshot = list(self._acts)
            target_snapshot = dict(self._target_status)
            guardians_count = len(self._guardian_pks)

        by_action: Dict[str, int] = {a: 0 for a in self.ALLOWED_ACTIONS}
        by_target_status: Dict[str, int] = {}
        recent_abuse: List[Dict[str, Any]] = []

        # 取最近 20 条滥用事件（按时间倒序）
        abuse_acts = [
            (index, act)
            for index, act in enumerate(acts_snapshot)
            if act.get("action") in self.ABUSE_ACTIONS
        ]
        # time.time() can have equal/low-resolution values on some platforms;
        # use insertion order as a deterministic tie-breaker so the newest
        # event is still first when timestamps collide.
        abuse_acts.sort(
            key=lambda item: (item[1].get("timestamp", 0), item[0]),
            reverse=True,
        )
        recent_abuse = [
            {
                "act_id": a.get("act_id"),
                "action": a.get("action"),
                "target": a.get("target"),
                "reason": a.get("reason"),
                "timestamp": a.get("timestamp"),
            }
            for _, a in abuse_acts[:20]
        ]

        for entry in acts_snapshot:
            a = entry.get("action", "")
            if a in by_action:
                by_action[a] += 1
            status = entry.get("new_status", "")
            if status:
                by_target_status[status] = by_target_status.get(status, 0) + 1

        # 目标状态聚合（当前快照）
        target_status_count: Dict[str, int] = {}
        for status in target_snapshot.values():
            target_status_count[status] = target_status_count.get(status, 0) + 1

        return {
            "total_acts": len(acts_snapshot),
            "by_action": by_action,
            "by_target_status": by_target_status,
            "active_guardians": guardians_count,
            "recent_abuse_events": recent_abuse,
            "targets_count": len(target_snapshot),
            "target_status_snapshot": target_status_count,
        }

    # ------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------

    def clear(self) -> None:
        """清空所有状态（仅用于测试）."""
        with self._lock:
            self._guardian_pks.clear()
            self._target_status.clear()
            self._acts.clear()


# ── 单例 ──────────────────────────────────────────────────
_guardian_registry_singleton: Optional[GuardianRegistry] = None
_guardian_registry_lock = threading.Lock()


def get_guardian_registry() -> GuardianRegistry:
    """获取 ``GuardianRegistry`` 单例（进程内）."""
    global _guardian_registry_singleton
    if _guardian_registry_singleton is None:
        with _guardian_registry_lock:
            if _guardian_registry_singleton is None:
                _guardian_registry_singleton = GuardianRegistry()
    return _guardian_registry_singleton


def reset_guardian_registry_for_test() -> GuardianRegistry:
    """重置 ``GuardianRegistry`` 单例（仅用于测试）.

    Returns:
        新创建的 ``GuardianRegistry`` 实例.
    """
    global _guardian_registry_singleton
    with _guardian_registry_lock:
        _guardian_registry_singleton = GuardianRegistry()
    return _guardian_registry_singleton
