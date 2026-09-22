@echo off
setlocal
cd /d "%~dp0"
title Hub Financeiro ULSLA - Instalacao local

echo.
echo ========================================================
echo   HUB FINANCEIRO ULSLA - INSTALACAO LOCAL
echo ========================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] A criar ambiente Python local...
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto :erro
) else (
    echo [1/3] Ambiente local ja existente.
)

echo [2/3] A atualizar o instalador de pacotes...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :erro

echo [3/3] A instalar/atualizar dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :erro

echo.
echo ========================================================
echo   INSTALACAO CONCLUIDA
echo ========================================================
echo Agora pode usar INICIAR_LOCAL.bat.
echo.
pause
exit /b 0

:erro
echo.
echo ========================================================
echo   ERRO NA INSTALACAO
echo ========================================================
echo Verifique se o Python 3 esta instalado e tente novamente.
echo.
pause
exit /b 1
