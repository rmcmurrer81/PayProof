@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "Setup PayProof.cmd"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m unittest discover -s tests -v
pause

