@echo off
setlocal EnableExtensions

rem LAAP + Hanako automatic dependency bootstrapper.
rem Usage: scripts\bootstrap.bat [-with-dev] [-dry-run]

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "SCRIPT=%ROOT%\scripts\bootstrap.py"

where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 "%SCRIPT%" %*
  exit /b %errorlevel%
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%SCRIPT%" %*
  exit /b %errorlevel%
)

echo [bootstrap] Python 3.11 or newer is required.
echo Install Python, then run this file again.
exit /b 1
