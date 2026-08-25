@echo off
REM QuantDesk control: qd.bat [start|stop|restart|status|update|doctor]
setlocal enabledelayedexpansion
set "QD_HOME=%~dp0"
if "%QD_HOME:~-1%"=="\" set "QD_HOME=%QD_HOME:~0,-1%"
set "PORT=8600"
set "URL=http://127.0.0.1:%PORT%"
set "PID_FILE=%QD_HOME%\.server.pid"

if "%1"=="" set "ARG=start" else set "ARG=%1"

if /i "%ARG%"=="status" (
    curl -sf -m 2 "%URL%/api/config" >nul 2>&1 && (echo RUNNING   %URL%) || echo STOPPED
    exit /b 0
)

if /i "%ARG%"=="stop" (
    if exist "%PID_FILE%" (
        taskkill /PID !PID_FILE! /F >nul 2>&1
        del "%PID_FILE%" 2>nul
    )
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% .*LISTENING" 2^>nul') do taskkill /PID %%p /F >nul 2>&1
    echo [ok] stopped
    exit /b 0
)

if /i "%ARG%"=="doctor" (
    echo == QuantDesk doctor ==
    echo home:   %QD_HOME%
    if exist "%QD_HOME%\.venv\Scripts\python.exe" (echo venv:   ok) else echo venv:   MISSING
    curl -sf -m 5 "https://api.bybit.com/v5/market/time" >nul 2>&1 && (echo bybit:  reachable) || echo bybit:  UNREACHABLE
    exit /b 0
)

if /i "%ARG%"=="update" (
    cd /d "%QD_HOME%"
    git pull --ff-only
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt
    echo [ok] updated - run: quantdesk restart
    exit /b 0
)

if /i "%ARG%"=="restart" (
    call "%~f0" stop
    timeout /t 1 /nobreak >nul
)

REM ---- start (default) ----
curl -sf -m 2 "%URL%/api/config" >nul 2>&1 && (
    echo [ok] already running: %URL%
    start "" "%URL%"
    exit /b 0
)

if not exist "%QD_HOME%\.venv\Scripts\python.exe" (
    echo !! QuantDesk is not installed yet. Run install.ps1 or install.bat first.
    exit /b 1
)

echo [*] starting QuantDesk ...
start "" /b "%QD_HOME%.venv\Scripts\python.exe" -m uvicorn quantdesk.server:app --host 127.0.0.1 --port %PORT%

set /a tries=0
:waitloop
timeout /t 1 /nobreak >nul
curl -sf -m 2 "%URL%/api/config" >nul 2>&1 && goto started
set /a tries+=1
if %tries% lss 30 goto waitloop
echo !! failed to start - check server.log
exit /b 1

:started
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% .*LISTENING" 2^>nul') do echo %%p> "%PID_FILE%"
echo [ok] QuantDesk running: %URL%
start "" "%URL%"
exit /b 0
