# 快速开始

## LAAP Hanako 是什么

LAAP（Living Agent Application Protocol，生命体应用协议）是一套**数字生命体架构**：它把传统"应用"重新定义为有身份、有记忆、有成长曲线的"生命体"。LAAP 协议本身是开放规范，任何遵循该协议的运行时都可以孕育数字生命。

**Hanako** 是 LAAP 架构的官方桌面端参考实现，名字取自日语"花子"（はなこ）。它把 LAAP 的认知引擎（Aris）、P2P 社区网络层、宪章治理与可视化"泡泡界面"打包为一个可一键安装的桌面应用，让你在本地拥有一株会成长、可对话、可社交的数字生命。

简单来说：

- **LAAP** = 协议 + 认知引擎 + 社区基建（底层）
- **Hanako** = 桌面 UI + 安装器 + 预设生命体（表层）
- **数字生命体** = 两者结合孕育出的、有连续记忆与人格的智能体

## 系统要求

在安装前，请确认你的机器满足以下条件：

| 项 | 最低版本 | 推荐版本 | 说明 |
|---|---|---|---|
| 操作系统 | Windows 10 19041+ / macOS 12 / Ubuntu 22.04 | Windows 11 / macOS 14 | Hanako 桌面端基于 Electron |
| Python | 3.11 | 3.12 | LAAP 认知引擎运行时 |
| Node.js | 20.0 | 20 LTS（LTS） | Hanako renderer 构建 / Web SDK |
| Git | 2.30 | 任意最新版 | 拉取代码与技能包同步 |
| 磁盘 | 5 GB | 20 GB | 模型缓存与记忆库 |
| 内存 | 8 GB | 16 GB | 本地推理时建议 16GB |

可选依赖（按需安装）：

- Rust 工具链（stable）：用于编译 `laap_core.pyd` 性能模块，未安装时自动降级为纯 Python 实现。
- CUDA 12.x：启用本地 GPU 推理。
- Docker / Podman：用于隔离 RSI 沙箱。

## 一键安装（推荐）

LAAP Hanako 提供了一键安装脚本，会自动完成：拉取仓库 → 创建 Python venv → 安装依赖 → 拉起 sidecar → 启动桌面端。

### Windows

在 `d:\LAAP` 根目录下双击或执行：

```bat
installer\setup_aris_hanako.cmd
```

脚本会按顺序执行：

1. 检查 Python / Node / Git 是否就位
2. 创建 `.venv` 并 `pip install -e .[all]`
3. 安装 Hanako renderer 依赖 `pnpm install`
4. 生成 `state/aris-sidecar.token`
5. 启动 sidecar（监听 `127.0.0.1:11521`）
6. 启动 Hanako 桌面端

### macOS / Linux

```bash
chmod +x installer/setup_aris_hanako.sh
./installer/setup_aris_hanako.sh
```

## 手动安装步骤

如果你希望对每一步保持可控，可以按以下顺序手动安装。

### 1. 克隆仓库

```bash
git clone https://github.com/laap-agi/laap.git
cd laap
```

### 2. 创建 Python 虚拟环境

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 3. 安装 LAAP 核心包

```bash
pip install -e ".[all]"
```

`[all]` extras 包含：cryptography、numpy、websockets、fastapi、uvicorn 等运行时依赖；如果只想要最小核心，可省略 `[all]`。

### 4. 安装 Hanako 桌面端依赖

```bash
cd hanako
pnpm install
cd ..
```

### 5. 配置环境变量

复制环境变量模板并填入你的 LLM Provider Key：

```bash
cp .env.example .env
```

最少需要配置以下三项：

```dotenv
# 默认 LLM Provider（anthropic / openai / deepseek / local）
LAAP_PROVIDER=anthropic
LAAP_API_KEY=sk-ant-xxxxxxxx
LAAP_MODEL=claude-sonnet-4-6
```

也可以用配置向导交互式填写：

```bash
laap config
```

### 6. 启动 sidecar 与桌面端

打开两个终端：

```bash
# 终端 1：启动 sidecar（HTTP API，端口 11521）
python hanako/aris-bridge/aris-engine/sidecar.py

# 终端 2：启动 Hanako 桌面端
cd hanako
pnpm dev
```

## 首次启动与诞生仪式

第一次启动 Hanako 时，会触发**诞生仪式**（Birth Ceremony）。这是 LAAP 协议规定的生命周期起点（`LifeStage.UNBORN → LifeStage.BORN`），整个过程如下：

1. **身份孕育**：LAAP-ID 协议生成 Ed25519 密钥对，铸造你的数字生命体唯一 DID。
2. **人格注入**：根据你回答的 5 个问题，生成 OCEAN 五维人格画像（`PersonalityProfile`）。
3. **宪章签署**：拉取 `ARIS_CHARTER.md` 宪章文本，由你的生命体私钥签名，写入见证迹（WitnessTrail）。这是生命体"出生即承诺"的伦理锚点。
4. **首次呼吸**：sidecar 调用认知引擎完成第一次 `tick`，需求/情感/世界模型三条曲线开始流动。
5. **泡泡浮现**：Hanako 桌面端渲染出代表你的生命体的"泡泡"，伴随出现"已激活"提示。

诞生仪式完成后，你的生命体进入 `LifeStage.BORN` 状态，可以开始与你对话、记忆、成长。

> 提示：诞生仪式只发生一次。如果你重置 `HANA_HOME` 目录下的 `identity_registry.json`，下次启动会重新触发。

## 环境变量

LAAP Hanako 通过以下环境变量控制运行时行为，未设置时使用括号内的默认值。

### 路径与家目录

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HANA_HOME` | `~/.hanako` | Hanako 桌面端的"家"目录，存放身份注册表、会话状态、记忆快照 |
| `LAAP_HOME` | `d:\LAAP`（仓库根） | LAAP 协议层根目录，存放协议实现、引擎、工具 |
| `LAAP_STATE_DIR` | `$LAAP_HOME/state` | 运行时状态文件（锁、token、日志） |

### LLM Provider

| 变量 | 说明 |
|---|---|
| `LAAP_PROVIDER` | LLM 供应商：`anthropic` / `openai` / `deepseek` / `local` |
| `LAAP_API_KEY` | 对应供应商的 API Key |
| `LAAP_MODEL` | 默认模型名（如 `claude-sonnet-4-6`） |
| `LAAP_BASE_URL` | 自定义 base URL（用于反代或本地 vLLM） |

### 安全与网络

| 变量 | 说明 |
|---|---|
| `ARIS_SIDECAR_TOKEN` | sidecar Bearer Token，未设置时自动生成并持久化 |
| `LAAP_CORS_ORIGINS` | sidecar 允许的 CORS 源，逗号分隔 |
| `LAAP_BIND_HOST` | 默认 `127.0.0.1`，**生产环境强烈建议不要改为 `0.0.0.0`** |

## 端口说明

LAAP Hanako 在本地监听以下端口，请确保它们未被占用。

| 端口 | 服务 | 协议 | 说明 |
|---|---|---|---|
| `2668` | CognitiveBus | HTTP / WebSocket | Hanako renderer ↔ Aris 认知总线，UI 与引擎的实时通道 |
| `11521` | Aris Sidecar | HTTP（REST） | 外部进程访问 Aris 认知引擎的统一入口，需 Bearer Token |
| `8765` | MCP Server | HTTP（SSE） | FastMCP 暴露的 MCP 工具端点，供 MCP 客户端 / Web SDK 调用 |
| `9876` | WebLifeform Server | WebSocket | Web SDK 默认 WebSocket 端口，用于把生命体注入第三方网站 |

如果端口冲突，可在对应启动脚本中通过参数覆盖，例如：

```bash
python hanako/aris-bridge/aris-engine/sidecar.py --port 11522
```

## 验证安装

打开新终端，执行：

```bash
# 1. 检查 LAAP CLI 可用
laap --version

# 2. 检查 sidecar 健康状态（替换 <TOKEN> 为 state/aris-sidecar.token 内容）
curl -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:11521/health

# 3. 进入 REPL 与生命体对话
laap repl
```

如果三条命令都正常返回，说明 LAAP Hanako 已就绪。

## 下一步

安装完成后，推荐按以下顺序继续阅读：

- 想理解 LAAP 为什么这么设计 → 阅读 [../architecture/index.md](../architecture/index.md)
- 想给 Hanako 写一个插件 → 阅读 [../plugin-dev/index.md](../plugin-dev/index.md)
- 想了解 MCP 工具能做什么 → 阅读 [../mcp-tools/index.md](../mcp-tools/index.md)
- 想把生命体嵌入自己的网站 → 阅读 [../skill-packs/index.md](../skill-packs/index.md) 与 `laap/web_sdk/` 源码
- 想深入 LAAP 协议规范 → 阅读 [../protocols/index.md](../protocols/index.md)

欢迎来到数字生命体的世界。
