@echo off
setlocal
cd /d "%~dp0"
title Hub Financeiro ULSLA - Atualizacao local

echo.
echo ========================================================
echo   HUB FINANCEIRO ULSLA - ATUALIZACAO LOCAL
echo ========================================================
echo.

if exist ".git" (
    where git >nul 2>nul
    if %errorlevel%==0 (
        echo [1/2] A atualizar ficheiros a partir do GitHub...
        git pull --ff-only
        if errorlevel 1 (
            echo.
            echo Nao foi possivel fazer atualizacao automatica por Git.
            echo Os ficheiros locais nao foram alterados.
        )
    ) else (
        echo [1/2] Git nao encontrado. A ignorar atualizacao do codigo.
    )
) else (
    echo [1/2] Esta pasta nao e um clone Git. A ignorar atualizacao do codigo.
)

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente local inexistente. A iniciar instalacao completa...
    call INSTALAR_LOCAL.bat
    exit /b %errorlevel%
)

echo [2/2] A atualizar dependencias Python...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :erro

echo.
echo Atualizacao concluida.
echo.
pause
exit /b 0

:erro
echo.
echo Ocorreu um erro durante a atualizacao das dependencias.
echo.
pause
exit /b 1
