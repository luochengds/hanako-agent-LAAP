@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo   LAAP Hanako 一键安装
echo ============================================
echo.

REM ── 安装脚本所在目录的上一级即 LAAP 根目录 ──
set "LAAP_ROOT=%~dp0.."
pushd "%LAAP_ROOT%" >nul
set "LAAP_ROOT=%CD%"
popd >nul

REM ── 1. 检测 Python ──────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] 未检测到 Python，请安装 Python 3.11+
    echo        下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ── 2. 检测 Node.js ─────────────────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo [FAIL] 未检测到 Node.js，请安装 Node.js 20+
    echo        下载地址：https://nodejs.org/
    pause
    exit /b 1
)

REM ── 3. 检测 Git（仅警告）────────────────────────────────────
where git >nul 2>&1
if errorlevel 1 (
    echo [WARN] 未检测到 Git，部分功能可能受限
) else (
    echo [OK]   Git 已安装
)

REM ── 4. 运行环境检测 ─────────────────────────────────────────
echo.
echo [INFO] 运行环境依赖检测...
python "%~dp0check_env.py"
if errorlevel 1 (
    echo.
    echo [FAIL] 环境检测未通过，请修复上述问题后重试
    pause
    exit /b 1
)

REM ── 5. 设置环境变量（用户级，幂等）──────────────────────────
if not defined HANA_HOME (
    echo [INFO] 设置 HANA_HOME = %USERPROFILE%\.hana
    setx HANA_HOME "%USERPROFILE%\.hana" >nul
    set "HANA_HOME=%USERPROFILE%\.hana"
) else (
    echo [OK]   HANA_HOME 已设置：!HANA_HOME!
)

if not defined LAAP_HOME (
    echo [INFO] 设置 LAAP_HOME = %USERPROFILE%\.laap
    setx LAAP_HOME "%USERPROFILE%\.laap" >nul
    set "LAAP_HOME=%USERPROFILE%\.laap"
) else (
    echo [OK]   LAAP_HOME 已设置：!LAAP_HOME!
)

REM ── 6. 创建数据目录（幂等）──────────────────────────────────
if not exist "%HANA_HOME%" mkdir "%HANA_HOME%"
if not exist "%LAAP_HOME%" mkdir "%LAAP_HOME%"
echo [OK]   数据目录就绪

REM ── 7. 安装 Python 依赖 ─────────────────────────────────────
echo.
echo [INFO] 安装 LAAP Python 依赖...
REM requirements.txt 位于 LAAP 根目录（内部引用 pyproject.toml）
if exist "%LAAP_ROOT%\requirements.txt" (
    python -m pip install -r "%LAAP_ROOT%\requirements.txt"
    if errorlevel 1 (
        echo [FAIL] Python 依赖安装失败
        pause
        exit /b 1
    )
) else (
    echo [WARN] 未找到 requirements.txt，跳过 Python 依赖安装
)

REM ── 8. 安装 Hanako npm 依赖 ─────────────────────────────────
echo.
echo [INFO] 安装 Hanako npm 依赖...
cd /d "%LAAP_ROOT%\hanako"
call npm install
if errorlevel 1 (
    echo [FAIL] npm 依赖安装失败
    pause
    exit /b 1
)

REM ── 9. 构建桌面端 ───────────────────────────────────────────
echo.
echo [INFO] 构建 Hanako 桌面端...
REM package.json 提供 build:client（main + preload + renderer + splash + theme）
call npm run build:client
if errorlevel 1 (
    echo [WARN] 桌面端构建失败，可稍后手动运行 npm run build:client
)

REM ── 10. 初始化数据库 ────────────────────────────────────────
echo.
echo [INFO] 初始化 LAAP 记忆库（agent: aris）...
cd /d "%LAAP_ROOT%"
REM init_for_agent 是 VaultManager 实例方法，通过模块级单例 vault_manager 调用
python -c "from laap.memory_vault.vault_manager import vault_manager; p = vault_manager.init_for_agent('aris'); print('vault:', p)"
if errorlevel 1 (
    echo [WARN] 记忆库初始化失败，可稍后手动运行
)

REM ── 完成 ────────────────────────────────────────────────────
echo.
echo ============================================
echo   安装完成！
echo.
echo   启动方式：
echo     python installer\launch.py
echo.
echo   仅检测端口：
echo     python installer\launch.py --check
echo ============================================
echo.
pause
endlocal
