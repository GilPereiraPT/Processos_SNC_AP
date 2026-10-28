@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python instalar_local.py
) else (
  py -3 instalar_local.py
)
if errorlevel 1 (
  echo Nao foi possivel instalar. Confirme que Python 3.10 ou superior esta instalado.
  pause
  exit /b 1
)
pause
