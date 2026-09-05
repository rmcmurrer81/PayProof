@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "Setup PayProof.cmd"
if errorlevel 1 exit /b 1
echo [PayProof] Control Room: http://127.0.0.1:8765
echo [PayProof] Keep this window open. Press Ctrl+C to stop.
start "" /b powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0tools\open_when_ready.ps1" -Url "http://127.0.0.1:8765/api/health"
".venv\Scripts\python.exe" app.py
