@echo off
cd /d "%~dp0"
if "%CCF_ZIP_PASSWORD%"=="" (
  echo Configure a variavel de ambiente CCF_ZIP_PASSWORD antes de executar.
  exit /b 1
)
python -m streamlit run ccf_app.py
