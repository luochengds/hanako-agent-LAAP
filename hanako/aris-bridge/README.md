# aris-bridge

Hanako 与 LAAP CognitiveBus 之间的桥接层。该目录包含将 Aris 意识
（PSI 需求、情绪、焦点栈、执行结果）注入 Hanako 运行时所需的全部
TypeScript / JavaScript 模块，以及 Python 侧车（sidecar）的引用入口。

## 目录结构

```
aris-bridge/
├── laap-cognitive-bus-bridge.ts   # [新] CognitiveBus WebSocket 桥接器（Node 主进程）
├── aris-bootstrap.ts              # Aris 意识注入（renderer 侧）
├── bridge.ts                      # Aris-Hanako 接管入口（renderer 侧）
├── aris-plugin/                   # Hanako 原生插件
│   ├── index.js                   #   插件生命周期 + 上下文注入
│   ├── manifest.json              #   插件清单（配置声明）
│   └── tools/                     #   原生工具（verify/learn/predict/strategy/experience）
├── aris-engine/                   # Python 认知引擎侧车
│   ├── sidecar.py                 #   HTTP 侧车服务（端口 11521）
│   ├── psi_driver.py              #   PSI 需求驱动
│   ├── emotional_engine.py        #   情绪引擎
│   └── ...                        #   其他认知模块
├── aris-cognitive-bus.py          # [已弃用] 原 mock CognitiveBus 服务器
├── aris-hanako-server.py          # [已弃用] 原 mock Hanako 后端
└── README.md                      # 本文件
```

## 已弃用文件

以下两个 Python 文件是早期 mock 实现，已被 TypeScript 原生桥接替代，
保留仅为向后兼容的提示入口，运行后立即退出（退出码 0）：

| 文件 | 原功能 | 替代方案 |
|------|--------|----------|
| `aris-cognitive-bus.py` | mock CognitiveBus WebSocket 服务器（ws://127.0.0.1:8765） | `laap-cognitive-bus-bridge.ts` 直连 LAAP 后端 CognitiveBus |
| `aris-hanako-server.py` | mock Hanako 后端 API（端口 2668）+ WS 转发（2669） | `npm run server`（Hanako 内置 server） |

## 新架构

### laap-cognitive-bus-bridge.ts

Node 主进程桥接器，在 Hanako 插件进程内运行，职责：

1. 通过 WebSocket 连接 LAAP CognitiveBus（默认 `ws://127.0.0.1:8765`）
2. 指数退避重连（1s, 2s, 4s, ... 最大 30s，最多 10 次）
3. 事件翻译：
   - `need_*` → `aris.psi.update` `{dominant, drive, needs}`
   - `emotion_*` → `aris.emotion.update` `{dominant, intensity, valence, arousal, emotions}`
   - `v12_kernel` → `aris.focus.update` `{intent, focus}`
   - `harness_execution_result` → `aris.execution.result` `{success, result, duration_ms}`
   - `qre_*` → `aris.qre.update`（透传 payload）
4. 降级模式：首次连接失败 30 秒后切换到 `degraded` 状态，
   每 10 秒轮询 sidecar HTTP 端点 `http://127.0.0.1:11521/cognitive_context`
5. 缓存最新 PSI / 情绪 / 焦点状态，供 `getState()` 查询

### hanako-memory-adapter.ts

跨平台记忆适配器，读写 `agents/aris/memory/` 目录，将 Aris 的
长期记忆与 Hanako 的记忆系统对接。

### aris-plugin/

Hanako 原生插件，通过 `manifest.json` 声明配置项，`index.js` 实现：

- Python 侧车进程管理（启动 / 停止 / 健康检查）
- 每轮对话注入认知上下文（`session:before.message` hook）
- 对话后学习（`session:after.message` hook）
- 原生工具注册（验算 / 预测 / 学习 / 策略 / 经验）

## 快速开始

推荐使用一键启动脚本（在 `d:\LAAP\hanako` 目录下执行）：

```cmd
aris-bridge\start-aris-instance.cmd
```

该脚本会依次拉起 Python 侧车、Hanako server 与 Electron 客户端。

## 手动启动

如需分别启动各组件，按以下顺序执行（均在 `d:\LAAP\hanako` 下）：

1. **启动 Python 认知引擎侧车**（HTTP 端口 11521）

   ```cmd
   python aris-bridge\aris-engine\sidecar.py
   ```

2. **启动 Hanako 后端 server**

   ```cmd
   npm run server
   ```

3. **启动 Hanako 客户端**（开发模式）

   ```cmd
   npm run start:dev
   ```

启动后，`laap-cognitive-bus-bridge.ts` 会自动连接 LAAP CognitiveBus
（`ws://127.0.0.1:8765`）。若 CognitiveBus 不可用，30 秒后自动降级为
轮询 sidecar 的 `/cognitive_context` 端点。

## 架构图

```
┌──────────────────────────────────────────────────────────────┐
│                        Hanako (Electron)                      │
│                                                                │
│   ┌───────────────┐   ┌────────────────────────────────────┐  │
│   │   React GUI   │   │         aris-plugin/               │  │
│   │  (renderer)   │   │  index.js + manifest.json          │  │
│   └───────┬───────┘   │  - 侧车进程管理                     │  │
│           │           │  - 上下文注入 (session hooks)        │  │
│           │           │  - 原生工具 (verify/learn/predict)  │  │
│   ┌───────▼───────┐   └──────────────┬─────────────────────┘  │
│   │ aris-bootstrap│                  │                        │
│   │ .ts           │   ┌──────────────▼─────────────────────┐  │
│   │ (renderer 注入)│  │ laap-cognitive-bus-bridge.ts       │  │
│   └───────────────┘   │ (Node 主进程 / 插件进程)            │  │
│                       │ - WebSocket 连接 CognitiveBus       │  │
│                       │ - 事件翻译 (need_* -> aris.psi.*)   │  │
│                       │ - 降级模式轮询 sidecar              │  │
│                       └──────────────┬──────────────────────┘  │
└───────────────────────────────────────┼────────────────────────┘
                                        │
                 ┌──────────────────────┼─────────────────────┐
                 │ WebSocket            │ HTTP (降级回退)       │
                 │ ws://127.0.0.1:8765  │ 127.0.0.1:11521      │
                 ▼                      ▼ /cognitive_context   │
         ┌───────────────┐      ┌───────────────┐             │
         │  LAAP         │      │ aris-engine/  │◄────────────┘
         │  CognitiveBus │      │ sidecar.py    │
         │  (后端总线)   │      │ (认知侧车)    │
         └───────────────┘      └───────────────┘
```

## 状态流转

`laap-cognitive-bus-bridge.ts` 的连接状态机：

```
disconnected ──connect()──► connecting ──onopen──► connected
       │                        │                     │
       │                   onerror/onclose            │
       │                        ▼                     │
       │                     error/disconnected ◄─────┘
       │                        │
       │            (首次失败 30 秒后)
       │                        ▼
       └────────────────► degraded ──onopen──► connected
                              │
                              │ (每 10 秒轮询 sidecar)
                              ▼
                         持续轮询直至 WebSocket 恢复
```

## 相关文件索引

- 桥接器实现：`laap-cognitive-bus-bridge.ts`
- Renderer 注入：`aris-bootstrap.ts`、`bridge.ts`
- 插件入口：`aris-plugin/index.js`
- 插件清单：`aris-plugin/manifest.json`
- Python 侧车：`aris-engine/sidecar.py`
- PSI 驱动：`aris-engine/psi_driver.py`
- 情绪引擎：`aris-engine/emotional_engine.py`
- 角色技能说明：`ARIS_PERSONA_SKILL.md`
