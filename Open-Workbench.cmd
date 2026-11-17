@echo off
setlocal
if not exist "%~dp0.runtime\venv\Scripts\pythonw.exe" (
  echo Run Install.ps1 first.
  pause
  exit /b 1
)
start "" "%~dp0.runtime\venv\Scripts\pythonw.exe" -B -X utf8 "%~dp0app\workbench\open-workbench.py"
