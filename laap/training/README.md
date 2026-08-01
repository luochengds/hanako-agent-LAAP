# LAAP Training Module — OpenForge RL 集成

**采集 Agent 交互数据 → 编排并行 rollout → 转换为训练格式 → 反哺模型进化。**

该模块将 [OpenForge RL](https://arxiv.org/abs/2607.21557) 的训练管道无缝集成到 LAAP Agent 中。
你不需要修改 Agent 的代码，也不需要理解 RL 的细节——只需开启一个配置项，训练数据就会自动采集。

---

## 架构总览

```
Agent.chat()
    │
    ▼
┌──────────────────────┐
│ Phase 1              │  RolloutCollector
│ 采集层               │  无侵入记录每次交互
│  rollout_collector   │  → TurnSnapshot → Trajectory
└──────────┬───────────┘
           │ raw_trajectories
           ▼
┌──────────────────────┐
│ Phase 2              │  TrainingOrchestrator
│ 编排层               │  并行 rollout 调度
│  orchestrator        │  进程隔离 · 墙钟超时 · 异常丢弃
└──────────┬───────────┘
           │ completed trajectories
           ▼
┌──────────────────────┐
│ Phase 3              │  TrajectoryBuilder + RewardAdapter
│ 训练数据层           │  格式转换 · 多源奖励评分 · GRPO 优势值
│  builder             │  → veRL/GRPO 兼容 JSONL
└──────────┬───────────┘
           │ training_data.jsonl
           ▼
     veRL / GRPO 训练框架
```

三层独立可测，不阻塞。你可以只开启 Phase 1 采集数据，等数据量够了再接入 Phase 2 和 Phase 3。

---

## 快速开始

### 1. 开启训练采集

在 Hanako `config.yaml` 或 `AgentConfig` 中添加：

```yaml
training:
  enabled: true               # 总开关
  rollout_collector: true     # 采集层（最常用）
  auto_export: true           # 自动导出 JSONL
  max_concurrent: 4           # 最大并发 rollout 数
  trajectory_output: "./training_data"  # 导出目录
```

代码方式：

```python
from laap.agent_core.agent import Agent, AgentConfig
from laap.training.integration import enable_training_config

config = AgentConfig()
enable_training_config(config, enabled=True)

agent = Agent(config=config)
# agent.training 已自动挂载
```

### 2. 采集交互数据

Agent 的每次 `chat()` 调用会自动记录到 `RolloutCollector` 中。
你也可以手动控制采集周期：

```python
# 开始一个新的采集周期
agent.training.start_episode(metadata={"task": "代码审查"})

# 采集会自动进行...
response = agent.chat("帮我 review 这段代码")
agent.training.record_reward(0.85, source="task_completion")

# 结束采集周期
agent.training.end_episode()
```

### 3. 导出训练数据

```python
# 手动导出所有已采集轨迹
count = agent.training.export_trajectories("./training_data/batch_001.jsonl")
print(f"导出了 {count} 条训练记录")

# 查看采集状态
status = agent.training.status()
print(f"轨迹数: {status['rollout_collector']['total_trajectories']}")
print(f"Token 数: {status['rollout_collector']['total_tokens']}")
```

### 4. 使用编排器启动并行 rollout

```python
from laap.training.orchestrator import TrainingOrchestrator, RolloutTask

orch = TrainingOrchestrator(max_concurrent=4)

# 提交批量 rollout 任务
tasks = [
    RolloutTask(messages=["解释量子计算的基本原理"], timeout_s=60),
    RolloutTask(messages=["写一个 Python 装饰器示例"], timeout_s=60),
    RolloutTask(messages=["比较 REST 和 GraphQL"], timeout_s=60),
]
rids = orch.submit_batch(tasks)

# 等待全部完成
orch.wait_until_idle(timeout=120)

# 获取完成的轨迹
trajectories = orch.get_completed_trajectories()
```

---

## 三层详解

### Phase 1: RolloutCollector

**作用**：在 Agent 的对话流程上加一层"记录探头"，不修改 Agent 核心逻辑。

| 概念 | 说明 |
|------|------|
| `TurnSnapshot` | 单轮交互快照（用户消息、助手回复、工具调用、token 数、耗时） |
| `RewardSignal` | 一个奖励信号（来源：fitness / stability / task_completion 等） |
| `Trajectory` | 一次完整会话的轨迹（多轮 TurnSnapshot + 奖励） |
| `RolloutCollector` | 采集器，管理 episode 生命周期 |

**两种集成模式：**

- **回调模式**（推荐）：挂载到 `ConversationLoop.on()` 事件系统，零侵入
- **包装模式**：用 `collector.wrap(agent.chat)` 包装 chat 函数，自动记录

```python
# 包装模式示例
collector = RolloutCollector()
wrapped_chat = collector.wrap(agent.chat)
response = wrapped_chat("你好")  # 自动记录到 collector
```

### Phase 2: TrainingOrchestrator

**作用**：管理并行 rollout 的生命周期——创建、调度、超时、回收。

模拟 OpenForge 论文中的 Kubernetes 编排器的本地实现：

| 特性 | 实现 |
|------|------|
| 进程隔离 | 每个 rollout 在独立 subprocess 中运行 |
| 墙钟超时 | 超时后干净截断，不等待、不重试 |
| 异常丢弃 | 失败的 rollout 标记为 `discarded`，不进入训练池 |
| 优先级调度 | 复用 `TaskScheduler` 的评分系统 |
| 未来扩展 | 可映射到真实 K8s Pod（通过 `K8sManager`） |

### Phase 3: TrajectoryBuilder + RewardAdapter

**作用**：把采集的轨迹转换为 RL 训练框架可用的格式。

**TrajectoryBuilder：**
- `build(trajectory)` → 单条轨迹转训练样本
- `build_batch(trajectories)` → 批量转换
- `build_grpo_batch(trajectories)` → 批量转换 + GRPO 组优势值计算
- `export_jsonl(trajectories, path)` → 导出为 JSONL 文件

**RewardAdapter（多源奖励评分）：**

| 信号源 | 权重 | 来源 |
|--------|------|------|
| fitness | 0.30 | `FitnessEvaluator.composite_fitness()` |
| stability | 0.15 | `StabilityMonitor.check()` → 惩罚 |
| task_completion | 0.35 | 任务完成状态 |
| user_feedback | 0.20 | 外部注入（可选） |

权重可在 `config.yaml` 中自定义。

**GRPO 优势值计算：**

```
advantage_i = (reward_i - group_mean) / (group_std + epsilon)
```

同一训练批次的轨迹按相对表现归一化，奖励高的轨迹获得正优势值，低的获得负优势值。

---

## 数据流示例

从一个用户对话到 RL 训练数据的完整路径：

```
用户: "帮我把这段代码优化一下"
    │
    ▼ RolloutCollector.record_turn()
TurnSnapshot {
    turn_id: 1,
    user_message: "帮我把这段代码优化一下",
    assistant_response: "好的，我建议...",
    tool_calls: [{name: "read_file", ...}],
    tokens_in: 50, tokens_out: 350,
}
    │
    ▼ RolloutCollector.record_reward(value=0.9, source="task_completion")
RewardSignal { value: 0.9, source: "task_completion" }
    │
    ▼ end_episode() → Trajectory.to_training_record()
{
    "trajectory_id": "ep_a1b2c3d4",
    "conversations": [
        {"role": "user", "content": "帮我把这段代码优化一下"},
        {"role": "assistant", "content": "好的，我建议...",
         "tool_calls": [{"name": "read_file", ...}]}
    ],
    "reward": 0.85,
    "reward_sources": {"task_completion": 0.9, "fitness": 0.8},
    "metadata": {"total_tokens": 400, "num_turns": 1}
}
    │
    ▼ export_jsonl() → training_data.jsonl
一行 JSON → 一条训练样本 → 可输入 veRL / GRPO
```

---

## 配置参考

### 完整配置项

```yaml
training:
  # 总开关
  enabled: false

  # Phase 1: 采集层
  rollout_collector: true    # 启用交互数据采集

  # Phase 2: 编排层
  max_concurrent: 4          # 最大并发 rollout 数

  # Phase 3: 奖励权重
  reward_weights:
    fitness: 0.30
    stability: 0.15
    task_completion: 0.35
    user_feedback: 0.20

  # 导出设置
  trajectory_output: ""      # 输出目录（默认 ~/.laap/trajectories/）
  auto_export: false         # Episode 结束时自动导出
  auto_export_format: jsonl  # 导出格式
```

### 常用配置场景

| 场景 | 配置 |
|------|------|
| 仅采集数据，暂不训练 | `enabled: true, auto_export: false` |
| 全自动采集 + 导出 | `enabled: true, auto_export: true` |
| 高并发采集 | `enabled: true, max_concurrent: 8` |
| 自定义奖励权重 | `enabled: true, reward_weights: {fitness: 0.5, task_completion: 0.5}` |

---

## 运行时控制

训练管道在运行时可通过 `agent.training` 接口动态控制：

```python
# 临时停止采集（不丢失已采集的数据）
agent.training.set_enabled(False)

# 重新开启
agent.training.set_enabled(True)

# 查看实时状态
print(agent.training.status())

# 重置所有采集数据（谨慎！）
agent.training.reset()
```

---

## 与 OpenForge RL 论文的对应关系

| OpenForge 概念 | LAAP Training 对应 |
|----------------|--------------------|
| Agent (包装推理服务器，记录模型调用) | `RolloutCollector.wrap()` / `on_turn_complete()` |
| 训练轨迹（prompt-response 记录） | `Trajectory` + `TurnSnapshot` |
| Kubernetes 编排器 | `TrainingOrchestrator` (本地 subprocess 版) |
| 墙钟超时 | `TaskScheduler.deadline` + `_collect_results()` 后台线程 |
| 异常 rollout 丢弃 | `end_episode(status="discarded")` 不进入训练池 |
| 基于组的优势值 (GRPO) | `RewardAdapter.compute_group_advantages()` |
| veRL 兼容训练格式 | `Trajectory.to_training_record()` + `export_jsonl()` |

> **K8s 迁移说明**：本实现的本地 subprocess 隔离在语义上等价于 K8s Pod 隔离。
> 迁移到真实 K8s 集群时，只需将 `_execute_rollout()` 中的 `subprocess.Popen`
> 替换为 `K8sManager.deploy()`（已在 `infrastructure/deployment/k8s.py` 中占位），
> 架构无需重做。

---

## 模块文件

```
laap/training/
├── __init__.py                  # 模块入口，导出所有公开 API
├── rollout_collector.py         # Phase 1: 采集层
├── orchestrator.py              # Phase 2: 编排层
├── builder.py                   # Phase 3: 训练数据层
├── integration.py               # Hanako 集成层
├── README.md                    # 本文件
└── tests/
    ├── test_rollout_collector.py  # 24 个测试
    ├── test_orchestrator.py       # 14 个测试
    ├── test_builder.py            # 22 个测试
    └── test_integration.py        # 19 个测试
    └── 总计: 79 个测试，全部通过
```

---

## 设计原则

1. **零侵入**：不修改 Agent 核心逻辑（`agent.py` / `conversation_loop.py`）
2. **可插拔**：不启用 training 时，训练模块不参与任何执行路径
3. **向后兼容**：已有代码无需修改，新功能通过配置开关控制
4. **失败优雅**：ImportError 和运行时异常均不阻塞 Agent 主流程
5. **独立可测**：三层各自有完整单元测试，不依赖外部服务
