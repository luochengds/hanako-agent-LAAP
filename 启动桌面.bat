@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo [Hanako] Python virtual environment not found. Installing dependencies...
  call "%ROOT%scripts\bootstrap.bat"
  if errorlevel 1 exit /b %errorlevel%
)

if not exist "%ROOT%hanako\node_modules" (
  echo [Hanako] Node dependencies not found. Installing dependencies...
  call "%ROOT%scripts\bootstrap.bat" --skip-python
  if errorlevel 1 exit /b %errorlevel%
)

rem Use the project virtual environment and enable strict PSI for Desktop.
set "PATH=%ROOT%.venv\Scripts;%PATH%"
set "LAAP_COGNITIVE_RUNTIME=agi"
set "LAAP_PSI_GATE_REQUIRED=1"
set "LAAP_PSI_RECEIPT_REQUIRED=1"

cd /d "%ROOT%hanako"
echo [Hanako] Starting Desktop development mode...
npm run start:dev
exit /b %errorlevel%
