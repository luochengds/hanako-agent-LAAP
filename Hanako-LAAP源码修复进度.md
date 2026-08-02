# Hanako-Agent-LAAP 源码可用性整理

更新时间：2026-08-02

## 目标

当前目标是保证：

> 直接使用 `E:\worke\hanako-agent-LAAP` 源码，安装依赖后可以运行。

当前不处理：

- Windows exe；
- seed 归档；
- Electron 安装器；
- 公开发行版改造；
- 落星璃专属化；
- 许可证处理。

## 当前结论

源码核心运行链路已经基本打通，但还不能称为“全量测试零失败的最终稳定版”。

### 已验证可用

- LAAP Python 核心模块导入；
- LAAP 核心回归测试；
- Hanako TypeScript 类型检查；
- Hanako 前端构建；
- Hanako 源码 server 启动；
- MCP server 启动；
- Sidecar 启动；
- Sidecar Bearer Token 认证；
- better-sqlite3 native binding；
- node-pty native binding；
- birth-ceremony 插件源码加载；
- Hanako 核心插件加载；
- 持久化扫描与确定性 receipts；
- Windows 符号链接路径逃逸防护（28/28 安全测试通过）；
- 能力策略、归档路径、访问路由和 Windows sandbox 安全回归（93/98 通过，剩余 5 项为 Windows 路径大小写/断言契约）。

## 测试结果

### Python

```text
laap/config/test_paths.py
laap/evolution/test_rsi_sandbox.py
laap/colony/test_guardian.py

108 passed
```

### Hanako 定向源码测试

```text
server-startup-diagnostics-contract：35 passed
agent-executor-teardown：17 passed
birth-ceremony smoke：6 passed
channel-actions：24 passed
```

合计定向测试：

```text
82 passed
```

### Hanako 全量测试最近结果

```text
9099 passed
55 failed
13 skipped
```

之前为：

```text
8979 passed
175 failed
13 skipped
```

失败数量已经明显下降，但仍未达到全量零失败。

## 已完成的源码修复

### LAAP

- 新增 `laap/memory_vault/` 兼容层；
- 恢复 `vault_manager.store/retrieve/consolidate` 接口；
- 修复 Guardian 最近滥用事件排序；
- 统一核心模块的 `LAAP_ROOT` 和状态目录；
- 修复 world model、causal engine、RSI 的旧路径；
- 移除 LLM Provider 导入阶段的默认初始化警告；
- 补齐默认运行依赖：
  - `msgpack`；
  - `PyYAML`；
  - `mcp>=1.0,<2.0`；
  - FastAPI、HTTPX、NumPy、OpenAI、psutil 等。

### Hanako / Sidecar

- 新增真实 MCP 启动入口：`scripts/laap_cognitive_mcp.py`；
- 修复 FastMCP 新旧 API 差异；
- 修复 Sidecar Bearer Token 请求头；
- 清理 Sidecar 主要运行模块中的 `D:/LAAP`；
- 修复 Sidecar 本地 `psi_driver` 与 `laap/agi/psi_driver` 模块名冲突；
- 修复 `channels.ts` 的 `id` 作用域；
- 修复 Hanako JSX 类型配置；
- 修复 birth-ceremony 插件源码模式下的 TypeScript 类型 re-export 导入错误；
- native binding 通过 `npm rebuild better-sqlite3 node-pty` 恢复。

### 桌面端安全/生命周期

- 移除 Windows 桌面端对裸 PID `taskkill` 的强制终止逻辑；
- Windows server 无法由 native Job Guardian 确认收敛时，保留 `server-info.json`，避免误杀无关进程；
- 补充 conversation export 临时文件的持久化登记。

### 构建脚本

虽然 exe/seed 暂不作为目标，但已为后续源码环境提供 Node 复用能力：

```text
HANA_TARGET_NODE
HANA_TARGET_NPM_CLI
```

可避免 `build-server` 强制重复下载 Node.js。

## 源码使用方式

### Python 环境

```powershell
cd E:\worke\hanako-agent-LAAP
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m pip check
```

### Hanako 依赖

```powershell
cd E:\worke\hanako-agent-LAAP\hanako
npm ci
```

不要使用：

```powershell
npm ci --ignore-scripts
```

因为这会跳过 `better-sqlite3`、`node-pty` 等 native binding 的构建。

### 启动 LAAP MCP

```powershell
cd E:\worke\hanako-agent-LAAP
python scripts/laap_cognitive_mcp.py --sse --port 8765
```

### 启动 Sidecar

```powershell
cd E:\worke\hanako-agent-LAAP\hanako\aris-bridge\aris-engine
python sidecar.py
```

### 启动 Hanako 源码 server

```powershell
cd E:\worke\hanako-agent-LAAP\hanako
npm run server
```

源码 server 已验证可以完成初始化并进入：

```text
ready: port=28903
```

## 安全测试结果

### 已通过

```text
fs-route / resource-io / upload-route：28 passed
build-windows-sandbox-helper：通过大部分契约检查
```

已验证的安全行为包括：

- 普通路径越界拒绝；
- 未授权 workspace 写入拒绝；
- 上传路径约束；
- 本地资源访问权限约束；
- sandbox 参数和超时边界；
- Windows 原生命令隔离路径。

### 当前环境限制

当前 Windows 账户仍无法创建普通 SymbolicLink：

```text
New-Item -ItemType SymbolicLink：需要管理员权限
```

Developer Mode 已开启，但当前系统策略仍未允许本次终端创建普通符号链接；目录 Junction 可以创建。

因此涉及真实 symlink 的测试在测试框架中被环境条件跳过/阻断，不能把它们解释成安全逻辑失败。完整 symlink 验收仍需要管理员 PowerShell 或允许创建符号链接的策略环境。

Windows shell 测试当前：

```text
70 passed / 5 failed
```

剩余失败主要是 `C:\WINDOWS` 与 `C:\Windows` 的路径大小写，以及测试期望参数对象与当前实现附加诊断字段的差异。

## 当前剩余问题

### 1. 全量测试仍有 55 个失败

剩余失败主要集中在：

- CI / installer / build contract；
- 缺少 `hanako/build/installer.nsh` 等发行测试夹具；
- seed/打包相关测试；
- Windows shell/sandbox 仍有少量路径大小写和测试断言差异；
- Windows 路径大小写断言；
- 少量跨平台 shell 和生命周期契约测试。

这些不等价于 LAAP/MCP/Sidecar/Hanako server 无法启动；文件路径与符号链接安全测试已经通过。

### 2. 自动记忆摘要需要可用模型账户

源码 server 启动后，后台记忆任务可能出现：

```text
Insufficient Balance
```

这表示当前 Provider/API 账户余额不足，影响：

- 自动摘要；
- deep-memory 编译；
- 每日记忆整理。

不影响：

- server 启动；
- MCP；
- Sidecar；
- 本地存储；
- 基础交互。

### 3. 历史架构尚未完全收敛

仓库仍同时存在：

```text
laap/agent/
laap/agent_core/
laap/agi/
laap/cognition/
```

当前统一入口可以运行，但架构清理仍未完成。

## 下一步计划

1. 继续分类剩余 55 个测试失败；
2. 只修复真正影响源码运行的失败；
3. 将 CI/installer/seed/权限限制类测试单独标记；
4. 验证新机器或干净目录中的完整源码启动；
5. 清理测试状态和临时运行目录；
6. 形成干净源码快照；
7. 再决定是否上传源码快照。

## 上传状态

当前工作区仍是修复中的源码工作区，尚未作为最终稳定版本上传。

exe、seed 和安装器不纳入当前源码验收标准。
