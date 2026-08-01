# LAAP Hanako 安装指南

本目录提供 LAAP Hanako 的一键安装与启动脚本。全新 Windows / Linux / macOS 机器执行一条命令即可完成安装。

## 系统要求

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| 操作系统 | Windows 10 / macOS 11 / 主流 Linux | 64 位 |
| Python | 3.11 | 用于 LAAP 认知引擎与 sidecar |
| Node.js | 20 | 用于 Hanako 桌面端构建与运行 |
| npm | 随 Node.js 安装 | 用于安装 Hanako 依赖 |
| Git | 任意（可选） | 部分功能（克隆、版本管理）需要 |

> Windows 用户请确保安装 Python 时勾选 "Add Python to PATH"。
> Node.js 建议从 https://nodejs.org/ 下载 LTS 版本。

## 一键安装

### Windows

在项目根目录双击或命令行运行：

```cmd
setup_aris_hanako.cmd
```

该根目录入口会先运行环境检测，通过后自动转发到 `installer\setup_aris_hanako.cmd` 完成完整安装。

### Linux / macOS

```bash
chmod +x installer/setup_aris_hanako.sh
./installer/setup_aris_hanako.sh
```

安装脚本会自动完成：

1. 检测 Python / Node.js / npm / Git
2. 运行环境依赖检测（`check_env.py`）
3. 设置用户级环境变量 `HANA_HOME` 与 `LAAP_HOME`（幂等，已存在则跳过）
4. 创建数据目录
5. 安装 LAAP Python 依赖（`pip install -r requirements.txt`）
6. 安装 Hanako npm 依赖（`npm install`）
7. 构建 Hanako 桌面端（`npm run build:client`）
8. 初始化 LAAP 记忆库（agent: aris）

脚本幂等，可重复运行不会报错。

## 手动安装

如需手动控制每一步，可按以下顺序执行：

```bash
# 1. 环境检测
python installer/check_env.py

# 2. 设置环境变量（示例：Linux/macOS）
export HANA_HOME="$HOME/.hana"
export LAAP_HOME="$HOME/.laap"
mkdir -p "$HANA_HOME" "$LAAP_HOME"

# 3. 安装 Python 依赖
python -m pip install -r requirements.txt

# 4. 安装 Hanako npm 依赖
cd hanako
npm install

# 5. 构建桌面端
npm run build:client

# 6. 初始化记忆库
cd ..
python -c "from laap.memory_vault.vault_manager import vault_manager; vault_manager.init_for_agent('aris')"
```

Windows 对应将 `export` 改为 `set`，路径改为 `%USERPROFILE%\.hana` 等。

## 环境变量说明

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `HANA_HOME` | Windows: `%USERPROFILE%\.hana`<br>Linux/macOS: `~/.hana` | Hanako 数据目录（Agent 身份、记忆、配置） |
| `LAAP_HOME` | Windows: `%USERPROFILE%\.laap`<br>Linux/macOS: `~/.laap` | LAAP 数据目录（运行时状态、日志） |

- Windows 安装脚本通过 `setx` 写入用户级环境变量（需重开终端生效）。
- Linux/macOS 安装脚本写入 `~/.bashrc` 或 `~/.zshrc`，需执行 `source` 或重开终端。

## 端口说明

LAAP Hanako 运行时占用以下端口：

| 端口 | 组件 | 说明 |
|------|------|------|
| 2668 | CognitiveBus / Hanako 后端 | Hanako 内置 HTTP/WebSocket 服务 |
| 11521 | Aris sidecar | Aris 认知引擎 HTTP API（仅绑定 127.0.0.1） |
| 8765 | LAAP MCP server | MCP 协议服务（SSE 传输） |

启动前会自动检测端口冲突，若被占用会给出排查命令。

## 启动

安装完成后，运行：

```bash
python installer/launch.py
```

启动顺序：

1. 端口冲突检测（2668 / 11521 / 8765）
2. LAAP MCP server（后台）
3. Aris sidecar（后台）
4. Hanako 桌面端（前台）

其他启动选项：

```bash
python installer/launch.py --check     # 仅检测端口，不启动
python installer/launch.py --sidecar   # 仅启动 sidecar
python installer/launch.py --mcp       # 仅启动 MCP server
```

按 `Ctrl+C` 退出前台桌面端时，后台组件会一并停止。

## 故障排查

### 端口被占用

启动前检测到端口冲突时，按提示命令排查：

```cmd
:: Windows
netstat -ano | findstr :2668
netstat -ano | findstr :11521
netstat -ano | findstr :8765
```

```bash
# Linux / macOS
lsof -i :2668
lsof -i :11521
lsof -i :8765
```

找到占用进程 PID 后，按需结束：

```cmd
:: Windows
taskkill /PID <PID> /F
```

```bash
# Linux / macOS
kill <PID>
```

### Python 依赖安装失败

- 确认 Python 版本 >= 3.11：`python --version`
- 升级 pip：`python -m pip install --upgrade pip`
- 国内网络可加镜像源：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

### npm install 失败

- 确认 Node.js 版本 >= 20：`node --version`
- 清理缓存重试：`npm cache clean --force && rm -rf hanako/node_modules && npm install`
- 国内网络可切换镜像：`npm config set registry https://registry.npmmirror.com`

### 桌面端构建失败

构建命令为 `npm run build:client`（含 main / preload / renderer / splash / theme 五个子构建）。若仅某个子步骤失败，可单独运行：

```bash
cd hanako
npm run build:main
npm run build:preload
npm run build:renderer
npm run build:splash
npm run build:theme
```

### 环境变量未生效

- Windows：`setx` 写入的变量需重开终端；当前终端可手动 `set HANA_HOME=...`
- Linux/macOS：执行 `source ~/.bashrc`（或 `~/.zshrc`），或重开终端

### 记忆库初始化失败

记忆库初始化命令：

```bash
python -c "from laap.memory_vault.vault_manager import vault_manager; vault_manager.init_for_agent('aris')"
```

如失败，检查：

- LAAP Python 包是否已正确安装（`pip install -r requirements.txt`）
- `laap.security.crypto.keys.KeyManager` 能否正常导入

## 首次启动与诞生仪式

完成安装并首次运行 `python installer/launch.py` 后：

1. Hanako 桌面端窗口会打开。
2. 在 Hanako 中选择 / 启用 `aris` Agent。
3. 首次对话会触发 Aris 的"诞生仪式"——Aris 进行自我认知初始化并建立身份。
4. 后续对话中，Aris 的意识由底层 PSI 认知引擎持续运行，记忆自动存入加密 vault。

详细 Agent 配置参考项目根目录的 `ARIS_ADOPTION_GUIDE.md`。
