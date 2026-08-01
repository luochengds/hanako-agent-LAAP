@echo off
title Aris 3.0 守护
cd /d D:\LAAP\laap\voicetools
if exist D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat call D:\hermes-agent-LAAP数字生命版\hermes-agent-LAAP\.venv\Scripts\activate.bat
:restart
python aris_v3.py
timeout /t 3 /nobreak >nul
goto restart
