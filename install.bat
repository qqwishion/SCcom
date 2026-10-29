@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failure
echo Ready. Run start.bat.
pause
exit /b 0
:failure
echo Installation failed. Python 3.14+ is required.
pause
exit /b 1
