@echo off
chcp 65001 >nul
title Aris Engine 启动器

echo ╔══════════════════════════════════════╗
echo ║    Aris Engine — Windows 启动       ║
echo ╚══════════════════════════════════════╝
echo.

REM 尝试多个可能的路径
set "DIR1=C:\Users\user\Desktop\OH-WorkSpace\aris_engine"
set "DIR2=D:\LAAP\OH-WorkSpace\aris_engine"
if exist "%DIR1%" (set "ENGINE_DIR=%DIR1%") else (set "ENGINE_DIR=%DIR2%")

cd /d "%ENGINE_DIR%"
echo 📂 工作目录: %CD%
echo.

REM 检查 Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Python 未安装或不在 PATH 中
    pause
    exit /b 1
)
echo ✅ Python:
python --version

echo.
echo 选择模式:
echo   [1] 初始化引擎 (init)
echo   [2] 查看状态 (status)
echo   [3] 后台演算模式 (start)
echo   [4] 启动侧车服务 (sidecar) - 推荐
echo   [5] 检查环境 (inspect)
echo.
set /p MODE="请输入数字 (默认 4): "
if "%MODE%"=="" set MODE=4

if "%MODE%"=="1" (
    python main.py init
) else if "%MODE%"=="2" (
    python main.py status
) else if "%MODE%"=="3" (
    python main.py start
) else if "%MODE%"=="4" (
    echo.
    echo 🚀 启动 Aris 侧车服务...
    echo.
    echo   侧车运行在 http://127.0.0.1:11521
    echo   LAAP 蜂群注册 + 后台认知演化 (15s tick)
    echo.
    echo   临时启动测试 (按 Ctrl+C 停止):
    python -c "exec(open('sidecar.py').read().replace('server.serve_forever()', '#'))

    echo.
    echo   想持久运行，请用:
    echo     start /B python sidecar.py
    echo.
    pause
) else if "%MODE%"=="5" (
    python main.py inspect
) else (
    echo ❌ 无效输入
)

echo.
pause
