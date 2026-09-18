@echo off
setlocal
cd /d "%~dp0"
title Hub Financeiro ULSLA - Modo Local

if not exist ".venv\Scripts\python.exe" (
    echo A instalacao local ainda nao existe.
    echo Vou iniciar o instalador.
    echo.
    call INSTALAR_LOCAL.bat
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" launcher.py
