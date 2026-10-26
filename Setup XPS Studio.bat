@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Open Launch XPS Studio.bat.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11 or newer and check the message above.
pause
exit /b 1
