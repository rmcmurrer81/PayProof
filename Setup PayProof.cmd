@echo off
setlocal
cd /d "%~dp0"
echo [PayProof] Preparing the local environment...
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error
if not exist ".env" copy /y ".env.example" ".env" >nul
echo.
echo [PayProof] Setup complete. Run Start PayProof.cmd.
pause
exit /b 0
:error
echo.
echo [PayProof] Setup failed. Keep this window open and share the error shown above.
pause
exit /b 1

