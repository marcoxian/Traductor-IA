@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Iniciando Servidor Proxy de Traduccion para Unity
echo ============================================================
echo.

set "PY="
if exist "venv_traductor\Scripts\python.exe" (
    set "PY=venv_traductor\Scripts\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) else if exist "C:\Python313\python.exe" (
    set "PY=C:\Python313\python.exe"
) else (
    set "PY=python.exe"
)

"%PY%" ollama_proxy.py %*
pause
