# Hanako-LAAP 架构收敛审计

更新时间：2026-08-02

## 审计目的

确认当前 Hanako-Agent-LAAP 源码中 `agent`、`agent_core`、`agi`、`cognition` 四层的实际关系，为后续收敛到 LAAP Runtime 结构提供依据。

本轮先做盘点和方案设计，并已完成第一步低风险实现：新增 `laap.runtime` 稳定入口 façade；不删除旧模块、不改变既有入口行为。

## 当前实际结构

```text
laap/agent/
  旧/兼容 Agent 层：base.py、lifelike.py、codex.py、meta_cognition.py、parliament.py

laap/agent_core/
  当前统一 Agent 编排层：agent.py、planner.py、executor.py、memory_bridge.py、tool_manager.py、platforms/、plugins/

laap/agi/
  大型认知与自进化能力层：PSI、意识流、情感、记忆、世界模型、因果、RSI、Guardian、Swarm 等

laap/cognition/
  较早的认知基础模块：needs.py、emotion.py、goals.py、awareness.py、integrated_engine.py 等
```

## 已确认的依赖关系

### `agent_core` 不是完全独立的主入口

`laap/agent_core/agent.py` 虽然是当前推荐入口，但仍然存在运行时兼容导入：

```python
from laap.agent.base import AGIBrain, AgentConfig
```

说明新 Agent 编排层仍依赖旧 Agent 层的一部分类型和兼容行为。

### `agent` 仍被外部入口直接使用

当前至少以下入口仍直接导入旧层：

```text
laap/api/server.py
laap/api/cli.py
laap/agent/test_agent_actor.py
```

其中 API server 和 CLI 仍使用：

```python
from laap.agent.base import Agent, AgentConfig
from laap.agent.lifelike import LifelikeAgent, LifelikeConfig
from laap.agent.codex import CodexAgent, CodexConfig
```

因此不能直接删除 `laap/agent/`。

### `agent` 与 `cognition` 强耦合

`laap/agent/base.py` 和 `laap/agent/lifelike.py` 直接使用：

```text
laap.cognition.awareness
laap.cognition.needs
laap.cognition.emotion
laap.cognition.emotion_system
laap.cognition.goals
```

这说明 `cognition` 并不是完全废弃目录，仍有实际调用者。

### `agi` 是当前最大的认知能力集合

`laap/agi/core.py` 组合了：

```text
world_model
self_model
causal
analogical
continuous_learning
autonomy
conscious
memory_system
evolution_system
security_system
code_evolution
self_healing
quality_assurance
multi_agent
PSIDriver
cognitive_bus
affective_engine
meta_cognitive
unified_memory
```

但 `laap/agi` 内部仍有许多实验、训练、桥接和历史模块，尚未形成清晰的稳定/实验边界。

## 当前真实架构判断

```text
Hanako server / CLI
        │
        ├── 直接使用 laap.agent（旧 Agent 生命周期）
        ├── 部分使用 laap.agent_core（新 Agent 编排）
        ├── 使用 laap.cognition（基础需求/情绪/目标）
        └── 使用 laap.agi（完整认知、自进化和安全能力）
```

因此当前并不是“agent_core 已完全替代 agent”，而是：

```text
新旧 Agent 并存
基础 cognition 与完整 agi 并存
多个入口通过兼容层连接
```

## 推荐目标结构

```text
laap/
├── runtime/
│   └── agent.py              # 最终稳定 Agent Runtime 入口
├── agent_core/               # 编排实现，可逐步保留为内部实现
├── agi/                      # PSI/意识/情感/记忆/RSI 能力
├── cognition/                # 只保留稳定基础认知服务
├── adapters/                 # MCP、Hanako、Sidecar、平台适配
└── compatibility/            # 旧 agent API 兼容壳
```

在不立即重命名目录的情况下，第一阶段可以先建立逻辑边界：

```text
agent_core.Agent       = 唯一推荐 Agent 主入口
agi                    = 认知能力实现
cognition              = 稳定基础认知 API
agent                  = 旧接口兼容层
api/cli/server         = 迁移到 agent_core 入口
```

## 安全迁移方案

### 阶段一：入口冻结

- 禁止新增代码直接依赖 `laap.agent.base.Agent`；
- API/CLI 新代码统一使用 `laap.agent_core.Agent`；
- 旧 `laap.agent` 保持兼容；
- 给旧入口添加迁移说明，不立即抛异常。

### 阶段二：类型解耦

- 从 `agent_core.agent` 中移除对 `AGIBrain` 的运行时依赖；
- 将共享配置、生命周期协议提取到稳定接口模块；
- 旧 `agent.base` 通过适配器实现该接口。

### 阶段三：认知边界

- 明确 `cognition` 保留的稳定 API；
- 将重复实现迁移到 `agi` 或标记为 legacy；
- 禁止 `agi` 直接反向依赖完整 Agent 生命周期。

### 阶段四：入口迁移

迁移：

```text
laap/api/server.py
laap/api/cli.py
```

使其优先使用 `agent_core`，只在显式 legacy 模式下使用 `laap.agent`。

### 阶段五：回归与清理

必须通过：

```text
Python 核心回归
Agent 集成测试
MCP 启动
Sidecar 启动
Hanako server 启动
API/CLI smoke test
```

确认无内部导入后，才考虑删除重复实现。

## 当前不应做的事情

```text
不要直接删除 laap/agent/
不要把 laap/cognition/ 整体移动到 laap/agi/
不要一次性重命名所有目录
不要在没有 import 图的情况下修改公共入口
不要把实验模块直接标记为稳定协议
```

## 第一阶段已实现

新增：

```text
laap/runtime/__init__.py
laap/runtime/agent.py
```

当前实现只是稳定入口 façade：

```python
from laap.runtime import Agent
```

内部仍委托给：

```python
laap.agent_core.agent
```

因此本阶段不搬迁代码、不删除旧入口、不改变既有行为，可直接回退。

同时新增 `laap/runtime/legacy.py`，并将 `laap/api/cli.py`、`laap/api/server.py` 的旧 Agent 导入改为从该兼容边界导入。旧实现未改变，迁移入口已集中。

新增 `laap/runtime/contracts.py`，定义 API/CLI 所需的最小 `AgentRuntime` 和可选增强的 `AgentLifecycle` Protocol。当前新旧 Agent 都保持原实现，只通过结构化契约进行下一阶段迁移准备。

新增 `laap/runtime/adapter.py` 的 `AgentLifecycleAdapter`，在不改变后端实现的前提下兼容 `id/config/run/status/alive/step_count`，为下一步将 API/CLI 切换到新 Agent 提供安全转换层。

已新增 `laap/runtime/factory.py` 的 `create_runtime_agent()`，并将 API/CLI 的默认 Agent 分支切换到 canonical `agent_core.Agent(mode="agi")`，外层通过生命周期适配器保持旧字段契约；Codex/Lifelike 分支暂时继续走兼容层。

新增 `laap/runtime/psi_gateway.py`。canonical API/CLI Agent 的 `run()`、`chat()`、`chat_stream()` 现在经过强制 PSI before/after 边界；PSI 初始化或边界失败时不静默绕过。Codex/Lifelike 兼容分支也通过 `wrap_runtime_agent()` 接入同一边界。Hanako Desktop 的 `prompt()` / `promptSession()` 已增加 Sidecar PSI gate，使用 `LAAP_PSI_GATE_REQUIRED=1` 开启严格模式。当前默认使用仓库内 `LaapBridge`，若完整 `laap_brain` 不可用会使用其 fallback cognitive kernel。真实 Sidecar 联动探针已通过：`/before_turn` 和 `/after_turn` 均返回 HTTP 200，因此第一阶段硬门控链路可用；这仍不等同于完整 `laap.agi.PSIDriver` 六阶段接管。

新增 `laap/runtime/subject_policy.py`，明确区分 PSI 必须覆盖的主体路径（输入、决定、工具行动、记忆变更、RSI、输出）与基础设施路径；适配器已将 `call_tool/execute_tool` 纳入 PSI 门控。API 的 RSI 触发/采纳和 Triphase memory store 也已通过 PSI gateway 包装。

真实 kernel Agent 适配探针已通过；新 Agent 的标识字段实际为 `_agent_id`，适配器已兼容该字段。启动时会记录可选 `model_tools` 未安装，但 kernel Agent 仍可创建并返回状态；这属于可选 Hermes 工具后端缺失，不是 runtime 入口阻断。

真实 `run()` 探针发现并修复了一个实际接口问题：`Context.get_messages()` 返回 dict，而旧 Provider 要求消息对象提供 `to_dict()`。新增 `get_llm_messages()` 作为 typed provider view，并将 kernel Agent / conversation loop 的 Provider 调用切换到该视图；原 dict 兼容接口保持不变。

## 最终迁移回归记录

2026-08-02 16:27 验证结果：

```text
Runtime/API probe：通过
API /agents/create：HTTP 200
Hanako server：监听 127.0.0.1:28903
MCP 入口：通过
Sidecar：完成初始化并监听 127.0.0.1:11521
TypeScript typecheck：通过
Python 核心：108 passed
Hanako 核心：76 passed
安全测试：43 passed
```

## 当前结论

架构叠层是真实存在的，但不是当前源码运行阻断。

最安全的下一步不是大规模搬目录，而是：

1. 冻结推荐入口；（已完成）
2. 提取共享接口；
3. 迁移 API/CLI；（默认 Agent 分支已切换到 `create_runtime_agent()`，Codex/Lifelike 保留兼容层）
4. 保留兼容壳；（已完成）
5. 用测试确认后再清理旧实现。
