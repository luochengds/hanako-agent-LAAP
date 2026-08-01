@echo off
title 阿瑞斯语音对话系统
echo ========================================
echo  阿瑞斯语音对话系统
echo  持续监听→语音识别→思考→TTS回复
echo  说 "晚安" 自动下线
echo ========================================
echo.

cd /d D:\LAAP\laap\voicetools

:: 激活 Hermes 的 venv
if exist D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat (
    call D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat
) else if exist D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\venv\Scripts\activate.bat (
    call D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\venv\Scripts\activate.bat
)

python aris_voice_loop.py

if errorlevel 1 (
    echo.
    echo 按任意键退出...
    pause > nul
)
