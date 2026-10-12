@echo off
setlocal
cd /d "%~dp0"
title Traductor IA - Diagnostico y Registro de Fallos

echo =======================================================================
echo          RECOLECTANDO DIAGNOSTICO DEL SISTEMA Y TRADUCTOR IA
echo =======================================================================
echo Por favor, espera unos segundos mientras se comprueban GPU, Ollama y logs...
echo.

set "PY="
if exist "venv_traductor\Scripts\python.exe" (
    set "PY=venv_traductor\Scripts\python.exe"
) else if exist "C:\Python313\python.exe" (
    set "PY=C:\Python313\python.exe"
) else if exist "C:\Users\marco\AppData\Local\Programs\Python\Python310\python.exe" (
    set "PY=C:\Users\marco\AppData\Local\Programs\Python\Python310\python.exe"
) else (
    set "PY=python.exe"
)

"%PY%" herramientas_extra\diagnostico.py %*

echo.
pause
