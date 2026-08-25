@echo off
REM QuantDesk installer - Windows. Double-click or run from cmd.
cd /d "%~dp0"
echo == QuantDesk installer ==

where py >nul 2>nul
if %errorlevel%==0 (
    echo [*] creating venv with py launcher
    py -3 -m venv .venv
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        echo [*] creating venv with python
        python -m venv .venv
    )
)

if not exist .venv\Scripts\python.exe (
    echo !! Could not create a Python environment.
    echo    Install Python from https://www.python.org/downloads/
    echo    IMPORTANT: tick "Add python.exe to PATH" in the installer.
    pause
    exit /b 1
)

echo [*] installing dependencies (1-3 minutes)
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt

echo [ok] installed. Start the app with run.bat
pause
