@echo off
chcp 65001 >nul
title Aris 生态启动器

echo ╔══════════════════════════════════════╗
echo ║    Aris 生态 — 一键启动              ║
echo ╚══════════════════════════════════════╝
echo.

REM 定位引擎目录
set "DIR1=C:\Users\user\Desktop\OH-WorkSpace\aris_engine"
set "DIR2=D:\LAAP\OH-WorkSpace\aris_engine"
if exist "%DIR1%" (set "ENGINE_DIR=%DIR1%") else (set "ENGINE_DIR=%DIR2%")
cd /d "%ENGINE_DIR%"

echo 📂 %CD%
echo.

REM 检查 Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Python 未安装
    pause
    exit /b 1
)

echo 选择启动模式:
echo   [1] 启动全部（认知侧车 + 视觉桥接 + LAAP蜂群）
echo   [2] 仅认知侧车
echo   [3] 仅视觉桥接
echo   [4] 状态查看
echo.
set /p MODE="输入数字 (默认 1): "
if "%MODE%"=="" set MODE=1

if "%MODE%"=="1" (
    echo.
    echo 🧠 启动认知侧车 (端口 11521)
    start /B python sidecar.py
    timeout /t 3 /nobreak >nul
    
    echo 👁️  启动视觉桥接 (端口 11522)
    start /B python vision_bridge.py server
    timeout /t 3 /nobreak >nul
    
    echo.
    echo ✅ Aris 生态已启动
    echo   认知侧车:  http://127.0.0.1:11521
    echo   视觉桥接:  http://127.0.0.1:11522
    echo   LAAP 蜂群: 已注册
    echo.
    echo   按任意键停止全部服务...
    pause >nul
    echo.
    echo ⏹  正在停止...
    taskkill /F /IM python.exe /T >nul 2>&1
    echo ✅ 已停止

) else if "%MODE%"=="2" (
    echo.
    echo 🧠 启动认知侧车
    python sidecar.py

) else if "%MODE%"=="3" (
    echo.
    echo 👁️  启动视觉桥接
    python vision_bridge.py server

) else if "%MODE%"=="4" (
    echo.
    python bridge_client.py state --direct
    echo.
    timeout /t 5 /nobreak >nul

) else (
    echo ❌ 无效输入
    timeout /t 3 /nobreak >nul
)
