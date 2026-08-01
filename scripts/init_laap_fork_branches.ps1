#Requires -Version 7.0
# LAAP fork 与 patch 分支自动化初始化脚本.
#
# 用法:
#   1. 先在 GitHub 上 fork 官方 openhanako 仓库，得到你的 fork URL.
#   2. 在 PowerShell 7+ 中运行:
#      .\scripts\init_laap_fork_branches.ps1 -ForkUrl "https://github.com/<your-username>/hanako-laap.git" -UpstreamUrl "https://github.com/openhanako/hanako.git"
#
# 脚本会:
#   - 检查本地仓库状态
#   - 配置 origin (你的 fork) 和 upstream (官方)
#   - 从当前分支创建 laap-main 并推送
#   - 创建 6 个 laap-patch/* 分支并推送
#   - 提示下一步整理 patch 内容

param(
    [Parameter(Mandatory = $true)]
    [string]$ForkUrl,

    [string]$UpstreamUrl = "https://github.com/openhanako/hanako.git",

    [string]$LaapMainBranch = "laap-main",

    [string[]]$PatchBranches = @(
        "laap-patch/core-protocol",
        "laap-patch/sidecar-bridge",
        "laap-patch/ui-plugins",
        "laap-patch/installer",
        "laap-patch/persona",
        "laap-patch/docs-charter"
    )
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "`n[STEP] $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "  [WARN] $msg" -ForegroundColor Yellow
}

function Invoke-Git($argsArray) {
    $cmd = "git " + ($argsArray -join " ")
    Write-Host "  `$ $cmd" -ForegroundColor DarkGray
    & git @argsArray
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed: $cmd"
    }
}

# ── 1. 检查当前目录是 git 仓库 ──
Write-Step "检查 git 仓库状态..."
if (-not (Test-Path ".git")) {
    throw "当前目录不是 git 仓库，请在 LAAP 仓库根目录运行本脚本。"
}

$currentBranch = git branch --show-current
Write-Ok "当前分支: $currentBranch"

# ── 2. 检查远程配置 ──
Write-Step "配置远程仓库..."
$remotes = git remote

if ($remotes -contains "origin") {
    $currentOrigin = git remote get-url origin
    if ($currentOrigin -ne $ForkUrl) {
        Write-Warn "origin 已存在但 URL 不匹配: $currentOrigin"
        Invoke-Git @("remote", "set-url", "origin", $ForkUrl)
        Write-Ok "已更新 origin 为 $ForkUrl"
    } else {
        Write-Ok "origin 已正确配置"
    }
} else {
    Invoke-Git @("remote", "add", "origin", $ForkUrl)
    Write-Ok "已添加 origin"
}

if ($remotes -contains "upstream") {
    $currentUpstream = git remote get-url upstream
    if ($currentUpstream -ne $UpstreamUrl) {
        Write-Warn "upstream 已存在但 URL 不匹配: $currentUpstream"
        Invoke-Git @("remote", "set-url", "upstream", $UpstreamUrl)
        Write-Ok "已更新 upstream 为 $UpstreamUrl"
    } else {
        Write-Ok "upstream 已正确配置"
    }
} else {
    Invoke-Git @("remote", "add", "upstream", $UpstreamUrl)
    Write-Ok "已添加 upstream"
}

Write-Ok "远程配置完成:"
& git remote -v

# ── 3. 拉取上游信息 ──
Write-Step "拉取上游分支信息..."
Invoke-Git @("fetch", "upstream")
Write-Ok "已拉取 upstream"

# ── 4. 创建 laap-main 分支 ──
Write-Step "创建并推送 LAAP 主线分支..."
$existingBranches = git branch --format="%(refname:short)"
if ($existingBranches -contains $LaapMainBranch) {
    Write-Warn "$LaapMainBranch 已存在，切换到该分支"
    Invoke-Git @("checkout", $LaapMainBranch)
} else {
    Invoke-Git @("checkout", "-b", $LaapMainBranch)
    Write-Ok "已创建 $LaapMainBranch"
}

# 推送前提醒：如果工作区有未提交改动，先提交或 stash
$status = git status --short
if ($status) {
    Write-Warn "工作区有未提交改动，建议先提交到 $LaapMainBranch 再推送"
    Write-Host $status -ForegroundColor Yellow
}

Invoke-Git @("push", "-u", "origin", $LaapMainBranch)
Write-Ok "$LaapMainBranch 已推送到 origin"

# ── 5. 创建 patch 分支 ──
Write-Step "创建 patch 分支..."
foreach ($patch in $PatchBranches) {
    $exists = git branch --format="%(refname:short)" | Where-Object { $_ -eq $patch }
    if ($exists) {
        Write-Warn "$patch 已存在，跳过"
        continue
    }

    Invoke-Git @("checkout", "-b", $patch)
    # 创建一个空的初始提交，标注分支用途
    $msg = "init($patch): LAAP customization patch branch`n`nThis branch will carry LAAP-specific changes for: $patch"
    Invoke-Git @("commit", "--allow-empty", "-m", $msg)
    Invoke-Git @("push", "-u", "origin", $patch)
    Write-Ok "$patch 已创建并推送"

    # 回到 laap-main 再创建下一个
    Invoke-Git @("checkout", $LaapMainBranch)
}

# ── 6. 回到 laap-main 并总结 ──
Invoke-Git @("checkout", $LaapMainBranch)

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  LAAP fork 与 patch 分支初始化完成" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  当前分支: $(git branch --show-current)" -ForegroundColor White
Write-Host "  远程仓库:"
& git remote -v
Write-Host "`n  已创建分支:"
foreach ($patch in $PatchBranches) {
    Write-Host "    - $patch"
}
Write-Host "`n  下一步:"
Write-Host "    1. 在 GitHub 上确认 fork 仓库已收到这些分支。"
Write-Host "    2. 按 LAAP_FORK_GUIDE.md 步骤 4，逐个 patch 分支整理实际改动。"
Write-Host "    3. 使用 git add -p / git checkout 等命令挑选每个分支应包含的文件。"
Write-Host "    4. 整理完成后跑: python scripts/laap_env_fix_and_smoke.py"
