# LAAP Body Layer

`laap.body` 是 LAAP 的**躯体层（Body Layer）**统一入口，负责封装与外部世界交互所需的感知、执行、模型、协议、技能、插件和网关能力。

## 架构边界

| 层级 | 模块 | 职责 |
|------|------|------|
| **Aether 编排层** | `laap.agi`、`laap.agent`、`laap.orchestration` 等 | 基于 Petri net、Actor 模型和 PSI 的认知编排与自主决策 |
| **Body 躯体层** | `laap.body` | 感知输入、工具执行、LLM 调用、MCP 协议、技能加载、插件扩展、消息网关 |

- **Aether 层**决定“做什么”与“为什么做”。
- **Body 层**提供“怎么做”的执行能力，以及“如何与外界交互”的接口。

## 公共 API

`laap.body` 暴露以下公共子模块：

```python
from laap.body import tools, llm, mcp, skills, plugins, gateway
```

| 子模块 | 说明 |
|--------|------|
| `laap.body.tools` | 工具层：代码执行、终端、搜索、文件系统、浏览器自动化等 |
| `laap.body.llm` | LLM 抽象层：provider、路由、限流、凭证池、模型注册表 |
| `laap.body.mcp` | Model Context Protocol 生命周期管理 |
| `laap.body.skills` | 技能引擎、技能管理器、系统提示组装 |
| `laap.body.plugins` | 插件发现、加载与生命周期钩子 |
| `laap.body.gateway` | 多平台消息网关适配器基座 |

> **实现位置说明**：底层具体实现仍位于 `laap.tools.*`、`laap.llm.*`、`laap.mcp.*` 等模块。`laap.body.*` 是对这些实现层的**稳定公共入口**重新导出，便于 Aether 编排层统一引用，也便于未来替换具体实现。

## 快速开始

```python
from laap.body import create_default_body_system

body = create_default_body_system()
print(body.tools.list_tools())   # 列出已注册工具
```

## 能力清单与成熟度

下表按当前实现状态标注成熟度：

| 能力 | 状态 | 说明 |
|------|------|------|
| `create_default_body_system` | stable | 构造默认 Body 子系统，已在多个测试中验证 |
| 统一工具注册表 (`laap.tools.tool_registry`) | stable | 支持自动 JSON Schema 生成、按类别检索、全局注册 |
| 文件系统 / 搜索 / 终端 / 代码执行工具 | stable | 已覆盖核心用例并有单元测试 |
| Web / Shell / Vision / Memory / Kanban / Delegate 工具 | stable | 已实现基础功能并通过测试 |
| 浏览器自动化 | beta | 依赖 Playwright，CI 中可跳过；headless 与 visible 模式已支持 |
| LLM transports（Anthropic / OpenAI / Ollama / Fallback） | beta | 接口稳定，真实调用需要配置对应 API key |
| MCP client / server | beta | 支持 stdio/SSE 内存传输测试，完整运行需要 `mcp` 包 |
| 技能系统 | beta | 支持扫描、加载、热重载；需要 `skills/` 目录结构 |
| 插件系统 | beta | 支持加载、启用/禁用、失败隔离 |
| Session / 上下文管理 | stable | 多轮对话、话题切换、上下文压缩 |
| 飞书网关适配器 | beta | Webhook 适配器已实现，但生产级事件订阅仍需完善 |
| Telegram / Discord 等网关适配器 | placeholder | 仅提供 `GatewayAdapter` 基座，具体适配器待实现 |
| Hermes 适配器 | placeholder | `HermesBodyAdapter` 当前为透传/no-op，用于未来平滑迁移 |

## 已知限制

- **网关**: 目前仅实现了飞书 webhook 适配器示例；Telegram、Discord 等平台只有基座接口。
- **LLM 回退**: `FallbackTransport` 支持链式回退，但真实生产部署需要配置多个 provider 并处理配额/限流。
- **浏览器工具**: 需要安装 Playwright 依赖；在部分 CI 环境或无桌面环境中可能无法运行。
- **MCP 生态**: 内存传输测试通过，但与外部 MCP server 的集成需要用户自行配置 `mcpServers`。
- **Hermes 适配**: 当前为 no-op 占位，未实现真正的 Hermes agent 桥接逻辑。

## 可选：Hermes 适配器

`laap.body.adapters.hermes` 提供 `HermesBodyAdapter`，用于将 Body 层桥接到 Hermes Agent 框架。

```python
from laap.body.adapters.hermes import HermesBodyAdapter

adapter = HermesBodyAdapter()
body = adapter.adapt()  # Hermes 不可用时，原样返回 BodySystem
```

默认行为为**透传 / no-op**：即使 Hermes 未安装或不可用，LAAP 也能正常启动。
