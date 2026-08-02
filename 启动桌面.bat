@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo [Hanako] 未检测到 Python 虚拟环境，开始安装依赖...
  call "%ROOT%自动安装依赖.bat"
  if errorlevel 1 exit /b %errorlevel%
)

if not exist "%ROOT%hanako\node_modules" (
  echo [Hanako] 未检测到 Node 依赖，开始安装依赖...
  call "%ROOT%自动安装依赖.bat" --skip-python
  if errorlevel 1 exit /b %errorlevel%
)

rem 让桌面插件优先使用项目虚拟环境中的 Python，并启用严格 PSI。
set "PATH=%ROOT%.venv\Scripts;%PATH%"
set "LAAP_COGNITIVE_RUNTIME=agi"
set "LAAP_PSI_GATE_REQUIRED=1"
set "LAAP_PSI_RECEIPT_REQUIRED=1"

cd /d "%ROOT%hanako"
echo [Hanako] 正在启动 Desktop 开发模式...
npm run start:dev
exit /b %errorlevel%
