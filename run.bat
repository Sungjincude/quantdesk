@echo off
REM QuantDesk launcher - Windows.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call install.bat

REM open browser once the server has had a moment to boot
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8600"
echo QuantDesk running at http://127.0.0.1:8600  (close this window to stop)
.venv\Scripts\python -m uvicorn quantdesk.server:app --host 127.0.0.1 --port 8600
