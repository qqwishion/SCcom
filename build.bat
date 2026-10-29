@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failure
)
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m PyInstaller --noconfirm VDchecker.spec
if errorlevel 1 goto failure
echo Ready: dist\VDchecker.exe
pause
exit /b 0
:failure
echo Build failed.
pause
exit /b 1
