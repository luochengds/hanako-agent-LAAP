@echo off
title 阿瑞斯语音守护 [后台]
cd /d D:\LAAP\laap\voicetools

:: 激活 venv
if exist D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat (
    call D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat
) else if exist D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\venv\Scripts\activate.bat (
    call D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\venv\Scripts\activate.bat
)

:restart
python aris_voice_v3.py
timeout /t 3 /nobreak >nul
goto restart
