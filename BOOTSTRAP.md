# 自动依赖安装

仓库提供统一依赖引导脚本：

```bat
REM Windows CMD / 双击入口（仓库根目录）
自动安装依赖.bat
自动安装依赖.bat --with-dev
自动安装依赖.bat --dry-run
```

底层入口仍位于 `scripts\\bootstrap.bat`，根目录中文 BAT 只是统一启动入口。

安装完成后，想要像 Desktop 一样启动：

```bat
启动桌面.bat
```

也可以使用 PowerShell：

```powershell
# Windows：检测并安装运行依赖
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1

# 同时安装 Python 测试/静态检查依赖
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -WithDev

# 只检测并打印命令，不安装
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -DryRun
```

跨平台也可以直接运行：

```text
python scripts/bootstrap.py
python scripts/bootstrap.py --with-dev
python scripts/bootstrap.py --dry-run
```

## 自动检测内容

- Python：要求 3.11 或更高版本；默认创建/复用根目录 `.venv`。
- Python 依赖：安装根目录 `requirements.txt`，其中包含本地 editable LAAP 包。
- `--with-dev`：额外安装 `pytest`、`mypy`、`ruff` 等开发依赖。
- Node.js：要求 `>=24.12.0 <25`。
- Hanako 依赖：在 `hanako/` 中执行 `npm ci`。
- npm lifecycle scripts 保持启用，用于构建 `better-sqlite3`、`node-pty` 等 native binding。

## 不会自动安装或配置

脚本不会：

- 写入 API Key、Token 或 `.env`；
- 安装 Hermes、model_tools、Agent-Reach；
- 启用 Swarm；
- 修改 PSI/AGIAgent 运行策略；
- 删除 Git、聊天记录或本地运行状态。

这些能力需要明确的额外选择，避免安装脚本产生隐式外部副作用。

## 环境覆盖

```powershell
$env:LAAP_VENV=".venv-custom"
$env:LAAP_NODE="C:\Program Files\nodejs\node.exe"
$env:LAAP_NPM="C:\Program Files\nodejs\npm.cmd"
```

脚本是幂等的：已有虚拟环境和 `node_modules` 时会重新校验/同步依赖，不会覆盖源码配置。
