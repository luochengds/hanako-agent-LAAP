@echo off
setlocal enableextensions enabledelayedexpansion

title Aris Hanako LAAP Instance Launcher
chcp 65001 > nul

REM ============================================================
REM Step 0: Header + setup
REM Working directory = parent of script dir (hanako root)
REM ============================================================
cd /d "%~dp0\.."

echo ╔══════════════════════════════════════════════════════════╗
echo ║   Aris Hanako LAAP Instance Launcher                     ║
echo ║   - Aris Sidecar      port 11521                         ║
echo ║   - Hanako Server     port 2668                          ║
echo ║   - Hanako Desktop    Electron                           ║
echo ║   - LAAP CognitiveBus ws://127.0.0.1:8765                ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM ============================================================
REM Step 1: Port conflict detection
REM ============================================================
echo [INFO] Checking port conflicts...
call :check_port 11521 "Aris Sidecar"
call :check_port 2668  "Hanako Server"
call :check_port 8765  "CognitiveBus"
echo.

REM ============================================================
REM Step 2: Verify Aris agent directory
REM ============================================================
echo [INFO] Verifying Aris agent directory...
if not exist "agents\aris\config.yaml" (
    echo [ERROR] agents\aris\config.yaml not found.
    set /p INIT_ANSWER="Initialize stub files? [y/n]: "
    if /I "!INIT_ANSWER!"=="y" (
        if not exist "agents\aris" mkdir "agents\aris"
        echo # Aris agent config stub> "agents\aris\config.yaml"
        echo # Aris yuan stub> "agents\aris\yuan.md"
        echo # Aris ishiki stub> "agents\aris\ishiki.md"
        echo # Aris pinned stub> "agents\aris\pinned.md"
        echo   [OK] Stub files created.
    ) else (
        echo [ERROR] Aborting: config.yaml missing.
        goto :end_script
    )
)
echo   [OK] Aris agent directory verified
echo.

REM ============================================================
REM Step 3: Start Aris sidecar (Python)
REM ============================================================
echo [INFO] Starting Aris sidecar...
set "PYTHON_CMD="
python --version >nul 2>&1
if !ERRORLEVEL! EQU 0 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 --version >nul 2>&1
    if !ERRORLEVEL! EQU 0 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    python3 --version >nul 2>&1
    if !ERRORLEVEL! EQU 0 set "PYTHON_CMD=python3"
)

if not defined PYTHON_CMD (
    echo [ERROR] No Python found in PATH. Skipping sidecar.
) else (
    set "ARIS_AGENT_DIR=d:\LAAP\hanako\agents\aris"
    echo [INFO] Using Python: !PYTHON_CMD!
    start "Aris Sidecar" cmd /k "!PYTHON_CMD! aris-bridge\aris-engine\sidecar.py"
    echo [INFO] Waiting for sidecar /health - up to 30s...
    set "SIDECAR_READY=0"
    for /L %%i in (1,1,30) do (
        if "!SIDECAR_READY!"=="0" (
            set "HTTP_CODE="
            for /f "delims=" %%H in ('curl -s -o nul -w "%%{http_code}" http://127.0.0.1:11521/health 2^>nul') do set "HTTP_CODE=%%H"
            if "!HTTP_CODE!"=="200" (
                set "SIDECAR_READY=1"
            ) else (
                timeout /t 1 /nobreak >nul
            )
        )
    )
    if "!SIDECAR_READY!"=="1" (
        echo   [OK] Aris sidecar ready ^(port 11521^)
    ) else (
        echo [WARN] Sidecar not ready after 30s; continuing anyway.
    )
)
echo.

REM ============================================================
REM Step 4: Start Hanako server
REM ============================================================
echo [INFO] Starting Hanako server...
if not exist "node_modules" (
    echo [INFO] node_modules missing, running npm install...
    call npm install
)
start "Hanako Server" cmd /k "npm run server"
echo [INFO] Waiting for Hanako server /api/health - up to 30s...
set "SERVER_READY=0"
for /L %%i in (1,1,30) do (
    if "!SERVER_READY!"=="0" (
        set "HTTP_CODE="
        for /f "delims=" %%H in ('curl -s -o nul -w "%%{http_code}" http://127.0.0.1:2668/api/health 2^>nul') do set "HTTP_CODE=%%H"
        if "!HTTP_CODE!"=="200" (
            set "SERVER_READY=1"
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
if "!SERVER_READY!"=="1" (
    echo   [OK] Hanako server ready ^(port 2668^)
) else (
    echo [WARN] Hanako server not ready after 30s; continuing anyway.
)
echo.

REM ============================================================
REM Step 5: Start Hanako desktop (Electron)
REM ============================================================
echo [INFO] Starting Hanako desktop - Electron...
start "Hanako Desktop" cmd /k "npm run start:dev"
echo   [OK] Hanako desktop launching...
echo.

REM ============================================================
REM Step 6: Print access summary
REM ============================================================
set "BUS_STATUS=offline"
netstat -ano | findstr ":8765 " | findstr LISTENING >nul 2>&1
if !ERRORLEVEL! EQU 0 set "BUS_STATUS=online"

echo ╔══════════════════════════════════════════════════════════╗
echo ║   Access Summary                                          ║
echo ╠══════════════════════════════════════════════════════════╣
echo ║   agentId         : aris                                  ║
echo ║   Memory dir      : d:\LAAP\hanako\agents\aris\memory    ║
echo ║   Sidecar         : http://127.0.0.1:11521               ║
echo ║   Hanako server   : http://127.0.0.1:2668                ║
echo ║   CognitiveBus    : ws://127.0.0.1:8765 [!BUS_STATUS!]   ║
echo ║   Default channel : #aris-lounge                          ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM ============================================================
REM Step 7: End
REM ============================================================
echo Press Ctrl+C in this window to exit (sidecar/server/desktop windows will keep running)
echo.
pause >nul
:end_script
endlocal
goto :eof

REM ============================================================
REM Subroutine: check_port
REM   %1 = port number, %2 = service name
REM ============================================================
:check_port
set "CP_PORT=%~1"
set "CP_NAME=%~2"
set "CP_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%CP_PORT% " ^| findstr LISTENING') do set "CP_PID=%%P"
if defined CP_PID (
    echo   [WARN] Port !CP_PORT! ^(!CP_NAME!^) occupied by PID !CP_PID!
    set /p CP_ANSWER="  Kill PID !CP_PID!? [y/n]: "
    if /I "!CP_ANSWER!"=="y" (
        taskkill /F /PID !CP_PID! >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo   [OK] Killed PID !CP_PID!
        ) else (
            echo   [ERROR] Failed to kill PID !CP_PID!
        )
    ) else (
        echo   [INFO] Skipping kill for port !CP_PORT!
    )
) else (
    echo   [OK] Port !CP_PORT! ^(!CP_NAME!^) free
)
goto :eof
