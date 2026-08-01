# LAAP-Hanako Fork 与独立更新源指南

## 目标

- 在 GitHub 上 fork 官方 openhanako 仓库。
- 建立 LAAP 定制分支体系：`upstream`（官方）、`laap-main`（LAAP 稳定主线）、`laap-patch/*`（具体功能补丁分支）。
- 把当前 `D:\LAAP` 的定制改动整理成可维护的 patch 分支。
- 建立 LAAP 独立发布/更新源，便于后续 OTA 或安装包分发。

## 前置条件

- GitHub 账号。
- 本地已安装 Git。
- 当前仓库分支：`feat/v4.0-full-stack`（根据 `git branch --show-current`）。

## 步骤 1：在 GitHub 上 Fork 官方仓库

1. 打开 https://github.com/openhanako/hanako （假设官方仓库地址，请替换为实际地址）。
2. 点击右上角 **Fork** → 选择你的个人/组织账号。
3.  fork 完成后，得到你的仓库地址，例如：
   ```
   https://github.com/<your-username>/hanako-laap.git
   ```

## 步骤 2：本地仓库配置远程

在当前 `D:\LAAP` 目录下执行：

```powershell
# 查看当前远程（通常为空或仅有 origin）
git remote -v

# 添加你的 fork 为 origin（如果还没有）
git remote add origin https://github.com/<your-username>/hanako-laap.git

# 添加官方仓库为 upstream
git remote add upstream https://github.com/openhanako/hanako.git

# 验证
git remote -v
```

## 步骤 3：建立 LAAP 主线分支

```powershell
# 从当前分支创建 laap-main（包含所有现有定制）
git checkout -b laap-main

# 推送到你的 fork
git push -u origin laap-main

# 后续 feat/v4.0-full-stack 作为历史保留，不再直接工作
```

## 步骤 4：把定制改动整理为 patch 分支

当前 LAAP 定制大致可分为以下几类 patch。建议每个类别一个分支：

| patch 分支 | 包含内容 | 本次涉及文件/目录 |
|---|---|---|
| `laap-patch/core-protocol` | LAAP 认知协议、MCP 工具、身份 PKI、共同进化 | `laap/colony/`, `laap/protocol/`, `laap/mcp/server.py`, `laap/evolution/`, `laap/skills/preset_*` |
| `laap-patch/sidecar-bridge` | sidecar 与 Hanako 的 HTTP 桥接端点 | `hanako/aris-bridge/aris-engine/sidecar.py` |
| `laap-patch/ui-plugins` | 泡泡界面、诞生仪式、聊天室、守护者、市场 | `hanako/plugins/bubble-field/`, `birth-ceremony/`, `laaper-chat/`, `trio-chatroom/`, `charter-guardian/`, `laaper-market/`, `hanako/desktop/src/react/App.tsx`, `types.ts`, `tsconfig.json` |
| `laap-patch/installer` | 一键安装包与启动脚本 | `installer/`, `setup_aris_hanako.cmd`, `setup_aris_hanako.sh`, `scripts/laap_env_fix_and_smoke.py` |
| `laap-patch/persona` | LAAP 人格模板、置顶记忆、skill | `hanako/lib/laap-persona/`, `scripts/implant_laap_persona.py`, `skills/laap/SKILL.md` |
| `laap-patch/docs-charter` | 宪章、fork 指南、文档 | `ARIS_CHARTER.md`, `LAAP_FORK_GUIDE.md` |

### 推荐操作（从 laap-main 切出并精简）

```powershell
# 确保在 laap-main
git checkout laap-main

# 逐个创建 patch 分支（示例：core-protocol）
git checkout -b laap-patch/core-protocol
# 用 git reset / git add -p / git checkout 只保留该分支应包含的改动
# 然后：
git commit -m "laap(core-protocol): colony protocol, mcp tools, coevolution, preset market"
git push -u origin laap-patch/core-protocol

# 回到 laap-main 切下一个
git checkout laap-main
git checkout -b laap-patch/sidecar-bridge
# ... 重复
```

> 由于当前工作区有大量未跟踪文件和混合改动，第一次整理建议用 `git add -p` 或按目录手工挑选，避免把实验文件（如 `aris_brain/`、`debug_*.py`）误入 patch。

## 步骤 5：建立 LAAP 独立更新源

### 方案 A：GitHub Release + 安装脚本

1. 在 fork 仓库发布 Release，上传构建产物：
   - `hanako-desktop-win-x64.zip`
   - `hanako-desktop-darwin-arm64.zip`
   - `installer.zip`
2. 修改 `installer/setup_aris_hanako.cmd` 和 `.sh`，从 GitHub Release 下载最新版：
   ```powershell
   # 示例：在 setup_aris_hanako.cmd 中替换下载逻辑
   set "LAAP_UPDATE_URL=https://github.com/<your-username>/hanako-laap/releases/latest/download"
   powershell -Command "Invoke-WebRequest -Uri '%LAAP_UPDATE_URL%/hanako-desktop-win-x64.zip' -OutFile 'hanako.zip'"
   ```

### 方案 B：自建 OTA 服务器

1. 准备一台服务器或对象存储（如 AWS S3、Cloudflare R2、阿里云 OSS）。
2. 每次构建后上传：
   - `/<version>/hanako-desktop-<platform>.zip`
   - `/<version>/manifest.json`（含版本号、sha256、最低兼容版本）
3. 在 `installer/check_env.py` 或 `hanako` 更新模块中加入 manifest 检查：
   ```python
   # 伪代码
   import urllib.request, json
   manifest = json.load(urllib.request.urlopen("https://ota.laap.io/manifest.json"))
   if manifest["latest"] > CURRENT_VERSION:
       print(f"[UPDATE] 新版本可用: {manifest['latest']}")
   ```

### 方案 C：Git 裸仓库 + 私有更新源

适合内网或不想依赖 GitHub 的场景：

```bash
# 在服务器上创建裸仓库
ssh user@server "mkdir -p /var/git/hanako-laap.git && cd /var/git/hanako-laap.git && git init --bare"

# 本地添加 laap-ota 远程并推送
git remote add laap-ota ssh://user@server/var/git/hanako-laap.git
git push laap-ota laap-main

# 安装脚本中改为从此仓库 clone/pull
```

## 步骤 6：维护流程（建议每两周一次）

```powershell
# 1. 拉取官方更新
git fetch upstream

# 2. 在本地创建官方最新分支的追踪分支
git checkout -b upstream-main upstream/main

# 3. 把 LAAP patch 变基到官方最新代码上
git checkout laap-patch/core-protocol
git rebase upstream-main
# 若有冲突，解决后：
git rebase --continue

# 4. 合并到 laap-main
git checkout laap-main
git merge upstream-main
git merge laap-patch/core-protocol
git merge laap-patch/sidecar-bridge
# ... 逐个合并

# 5. 跑验证
git push origin laap-main
python scripts/laap_env_fix_and_smoke.py

# 6. 发布新版本
# 构建、打 tag、上传 Release/OTA
```

## 当前仓库状态提示

- 当前分支：`feat/v4.0-full-stack`
- 工作区有大量未跟踪文件（`aris_brain/`、`debug_*.py`、`laap-client/` 等），建议先 `git clean -nd` 预览可清理文件，再决定是否加入 `.gitignore` 或删除。
- 在执行任何 `git push` 前，请确认 remote URL 指向你自己的 fork，避免误推到官方仓库。

## 快速开始命令

```powershell
# 一次性配置（替换 <your-username>）
git remote add origin https://github.com/<your-username>/hanako-laap.git
git remote add upstream https://github.com/openhanako/hanako.git
git fetch upstream

git checkout -b laap-main
git push -u origin laap-main

git checkout -b laap-patch/core-protocol
git push -u origin laap-patch/core-protocol
```
