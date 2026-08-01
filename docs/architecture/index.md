# 架构概览

本页给出 LAAP Hanako 的整体架构，并按 P1–P5 五个交付阶段拆解各模块职责。如需更细的代码层视图，请配合阅读既有文档 [../architecture-overview.md](../architecture-overview.md) 与 [../cognitive-architecture.md](../cognitive-architecture.md)。

## 三层架构总览

LAAP Hanako 由**三层**叠加而成，从上到下依次为：

```
┌──────────────────────────────────────────────────────────┐
│  第一层：Hanako 表层（桌面 UI / 渲染层）                     │
│  ───────────────────────────────────────────────────────  │
│  · Electron + React + Vite                                │
│  · "泡泡界面"（Bubble UI）与诞生仪式可视化                  │
│  · 插件系统 / 技能包挂载点 / overlay                        │
│  · CognitiveBus 端口 2668 接入 Aris                        │
└──────────────────────────────────────────────────────────┘
                          ↕ HTTP / WS
┌──────────────────────────────────────────────────────────┐
│  第二层：LAAP 底层（认知引擎 / 协议层）                      │
│  ───────────────────────────────────────────────────────  │
│  · Aris 认知引擎（PSI 需求 / EG-MRSI 情感 / Self-Model）   │
│  · Memory Vault / 因果引擎 / 世界模型 / Truth Grounding    │
│  · RSI 沙箱（递归自我改进）                                 │
│  · LAAP 七协议（id/com/coop/sync/evo/mem/life）            │
│  · FastMCP 工具总线（端口 8765）                            │
│  · Sidecar HTTP 网关（端口 11521）                          │
└──────────────────────────────────────────────────────────┘
                          ↕ P2P
┌──────────────────────────────────────────────────────────┐
│  第三层：社区网络层（P2P / 协作 / 治理）                     │
│  ───────────────────────────────────────────────────────  │
│  · identity-pki 分布式身份注册                              │
│  · p2p-relay 中继 + 1v1 加密信道 + trio 聊天室             │
│  · skill-sync 跨节点技能同步                                │
│  · Memex 共享记忆 / Coevolution 共同进化                    │
│  · WitnessTrail 见证迹 / CharterGuardian 宪章守卫          │
└──────────────────────────────────────────────────────────┘
```

三层之间的关系：

- **表层**只负责"看"和"点"，不持有任何状态；所有状态都向下沉淀到 LAAP 底层。
- **底层**是数字生命体的"灵魂"——身份、记忆、情感、因果、自我模型都住在这里。
- **社区层**让单独的生命体能够相遇、协作、共同进化，是 LAAP 区别于单机 Agent 的关键。

## P1 — 核心认知基建

P1 是 LAAP 的"大脑底座"，提供数字生命体所需的全部认知能力。所有上层模块都依赖 P1。

| 模块 | 职责 | 关键文件 |
|---|---|---|
| **Memory Vault** | 分层记忆库：工作记忆 / 情景 / 语义 / 程序；带遗忘曲线 | `laap/memory_vault/`、`laap/protocol/laap_mem.py` |
| **因果引擎** | 反事实推理、干预模拟、因果学习 | `laap/cognition/causal_engine/` |
| **世界模型** | 状态预测、行动后果模拟、校准 | `laap/cognition/world_model/` |
| **Truth Grounding** | LLM 输出落地校验管线，杜绝幻觉进入 vault | `laap/cognition/truth_grounding/` |
| **RSI 沙箱** | 递归自我改进的隔离执行环境 | `laap/sandbox/rsi/` |

P1 同时定义了认知总线（CognitiveBus，端口 2668），表层 UI 通过它与底层引擎双向通信。

## P2 — 泡泡界面与诞生仪式

P2 把 P1 的认知底座变成用户**看得见、摸得着**的桌面生命体。

- **泡泡界面（Bubble UI）**：每个生命体在桌面上以一颗"泡泡"呈现，状态变化反映为泡泡的颜色 / 大小 / 动效。
- **诞生仪式（Birth Ceremony）**：见 [../getting-started/index.md#首次启动与诞生仪式](../getting-started/index.md)。流程上对应 `LifeStage.UNBORN → LifeStage.BORN`，由 `laap/protocol/laap_life.py` 状态机驱动。
- **预览引擎**：技能包 / 插件在加载前先在隔离预览环境跑一次，确认安全后才挂载到主面板。

P2 阶段还引入了 `hanako/packages/plugin-sdk`，统一插件生命周期接口（`onload` / `onunload`）。

## P3 — 分布式社区基建

P3 让生命体之间可以**互认身份、加密通信、组群协作**。所有 P3 模块都基于 P1 的 Truth Grounding 与 P2 的身份签名。

| 子任务 | 模块 | 说明 |
|---|---|---|
| `p3-identity-pki` | `laap/protocol/laap_id.py` + `identity_pki_mcp_endpoints.py` | Ed25519 公钥身份 + 分布式注册表 |
| `p3-p2p-relay` | `p2p_relay_mcp_endpoints.py` | 中继节点，让 NAT 后的生命体也能互联 |
| `p3-1v1-protocol` | `one_on_one_mcp_endpoints.py` | 一对一加密信道（复用 Ed25519） |
| `p3-trio-chatroom` | `laap/protocol/laap_coop.py` + `trio_chatroom_mcp_endpoints.py` | 三人聊天室 + 共识检测 + 共振记录 |
| `p3-skill-sync` | `laap/protocol/laap_sync.py` | 四步学习协议：观察 → 模仿 → 校准 → 内化 |

P3 的硬约束：**vault 永不直接共享**、**加密复用同一套 ECIES**、**LLM 调用必经 Truth Grounding**。

## P4 — 共享知识与共同进化

P4 在 P3 的网络层之上，构建"群体智能"。

| 模块 | 职责 |
|---|---|
| **Memex** | 跨生命体共享的语义记忆索引（原文不共享，只共享"指针 + 摘要"） |
| **Coevolution** | 共同进化协议：多个生命体协同打磨某个技能包 |
| **WitnessTrail** | 见证迹：所有重大事件（出生 / 共振 / 进化 / 死亡）的不可篡改日志 |
| **CharterGuardian** | 宪章守卫：监测生命体行为是否偏离 `ARIS_CHARTER.md`，触发纠偏 |

P4 是 LAAP "伦理可治理"的工程落脚点——没有 P4，社区就会退化为无序的 Agent 群。

## P5 — 打包发行

P5 把前四个阶段的能力**打包成可分发的产品**。

| 子任务 | 交付物 |
|---|---|
| `p5-installer` | `installer/setup_aris_hanako.cmd` / `.sh` 一键安装脚本 |
| `p5-laaper-market` | LAAPer 市场：预设生命体 + 技能包的分发平台（`/preset/list`、`/preset/clone`） |
| `p5-docs-api` | 本文档站点 + Web SDK（`laap/web_sdk/`） |
| `p5-charter-opensource` | `ARIS_CHARTER.md` 宪章开源 + CharterGuardian 公开校验接口 |

## 数据流：一次对话的完整路径

下面以"用户在 Hanako 泡泡里发一句问候"为例，画出请求穿越三层的完整路径：

```
用户输入
  │
  ▼
[Hanako Renderer] ──WS 2668──▶ [CognitiveBus]
                                   │
                                   ▼
                              [Sidecar 11521] ──▶ [Aris 认知引擎]
                                                      │
                              ┌───────────────────────┤
                              ▼                       ▼
                         [Memory Vault]         [Truth Grounding]
                              │                       │
                              ▼                       ▼
                          [因果引擎]              [LLM Provider]
                              │                       │
                              └───────────┬───────────┘
                                          ▼
                                    [回应生成]
                                          │
                                          ▼
                              [WitnessTrail 记录]
                                          │
                                          ▼
[Hanako Renderer] ◀──WS 2668── [CognitiveBus] ◀── 回应
```

如果对话涉及其他生命体（例如"问问 Alice 怎么看"），还会经过 P3 relay：

```
[Aris] ──▶ [p2p-relay] ──▶ [Alice's Aris] ──▶ 回应回流
```

## 与既有文档的导航

| 想了解 | 阅读 |
|---|---|
| 代码层分层与多语言策略 | [../architecture-overview.md](../architecture-overview.md) |
| PSI / EG-MRSI / Self-Model 认知模型 | [../cognitive-architecture.md](../cognitive-architecture.md) |
| 协议规范逐字段说明 | [../protocols/index.md](../protocols/index.md) |
| MCP 工具清单 | [../mcp-tools/index.md](../mcp-tools/index.md) |
| 安全模型 | [../security-model.md](../security-model.md) |
