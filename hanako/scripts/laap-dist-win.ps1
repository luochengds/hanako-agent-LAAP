# ═══════════════════════════════════════════════════════════
# 一键打包 LAAP 深度定制版 Hanako（Windows）
# 
# 必须设置 HANA_SIGN_KEY / HANA_SIGN_KEYSET：
#   - HANA_SIGN_KEY:  local-2025 私钥（签名 seed manifest）
#   - HANA_SIGN_KEYSET: local-2025 公钥 keyset（打进构建，运行时校验）
# 不设置这两项 → seed 签名与运行时 keyset 不匹配 → 用户首启报
# "keyId local-2025 not present in keyset"
# ═══════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
Set-Location D:\LAAP\hanako

$env:HANA_SIGN_KEY = "D:\LAAP\hanako\.local\sign-key.pem"
$env:HANA_SIGN_KEYSET = "D:\LAAP\hanako\.local\sign-keyset.json"
$env:NODE_OPTIONS = "--max-old-space-size=8192"
$env:HANA_SKIP_NFT_TRACE = "1"

Write-Host "HANA_SIGN_KEY: $env:HANA_SIGN_KEY"
Write-Host "HANA_SIGN_KEYSET: $env:HANA_SIGN_KEYSET"
Write-Host "NODE_OPTIONS: $env:NODE_OPTIONS"
Write-Host "HANA_SKIP_NFT_TRACE: $env:HANA_SKIP_NFT_TRACE"

# 清理残留，避免 EACCES
Remove-Item .\dist-server -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\dist-server-artifact -Recurse -Force -ErrorAction SilentlyContinue

# 防止 PowerShell profile 加载错误遗留非零 $LASTEXITCODE
$LASTEXITCODE = 0

function Invoke-BuildStep {
    param([string]$Name, [string]$Command)
    Write-Host "`n[laap-dist-win] >>> $Name"
    Invoke-Expression $Command
    if ($LASTEXITCODE -ne 0) { Write-Host "$Name FAILED"; exit 1 }
}

# 使用 --publish never 避免 GitHub 发布，同时用相同的一次性签名密钥
Invoke-BuildStep "BUILD COMPUTER-USE HELPER" "npm run build:computer-use-helper"
Invoke-BuildStep "BUILD SANDBOX HELPER" "npm run build:windows-sandbox-helper"
Invoke-BuildStep "GENERATE WINDOWS ICON" "npm run generate:windows-icon"
Invoke-BuildStep "BUILD CLIENT" "npm run build:client"
Invoke-BuildStep "BUILD SERVER" "npm run build:server"
Invoke-BuildStep "VERIFY SEED KIT" "npm run verify:seed-kit"
Invoke-BuildStep "BUILD INSTALLER" "npx electron-builder --win nsis --publish never"
Write-Host "BUILD OK"
