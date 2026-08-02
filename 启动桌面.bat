@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo [Hanako] Python virtual environment not found. Installing dependencies...
  call "%ROOT%scripts\bootstrap.bat"
  if errorlevel 1 goto :fail
)

if not exist "%ROOT%hanako\node_modules" (
  echo [Hanako] Node dependencies not found. Installing dependencies...
  call "%ROOT%scripts\bootstrap.bat" --skip-python
  if errorlevel 1 goto :fail
)

set "PATH=%ROOT%.venv\Scripts;%PATH%"
set "LAAP_COGNITIVE_RUNTIME=agi"
set "LAAP_PSI_GATE_REQUIRED=1"
set "LAAP_PSI_RECEIPT_REQUIRED=1"

if not exist "%ROOT%hanako\package.json" (
  echo [Hanako] Missing hanako\package.json
  goto :fail
)

cd /d "%ROOT%hanako"
echo [Hanako] Starting Desktop development mode...
call npm.cmd run start:dev
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo [Hanako] Startup failed. Read the error above.
pause
exit /b 1
