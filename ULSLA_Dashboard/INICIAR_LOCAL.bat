@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Execute primeiro INSTALAR_LOCAL.bat nesta pasta.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" iniciar_local.py
if errorlevel 1 pause
