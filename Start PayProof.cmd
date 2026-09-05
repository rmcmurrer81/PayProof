@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "Setup PayProof.cmd"
if errorlevel 1 exit /b 1
start "" http://127.0.0.1:8765
echo [PayProof] Control Room: http://127.0.0.1:8765
echo [PayProof] Keep this window open. Press Ctrl+C to stop.
".venv\Scripts\python.exe" app.py

