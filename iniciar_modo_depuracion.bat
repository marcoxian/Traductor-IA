@echo off
setlocal
cd /d "%~dp0"
title Traductor IA - Modo Depuracion (CMD Activo)

echo =======================================================================
echo          TRADUCTOR IA - CENTRO DE CONTROL EN MODO DEPURACION
echo =======================================================================
echo [i] La consola CMD permanecera abierta para capturar cualquier error,
echo     traza de excepcion o mensaje interno del sistema.
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

echo [*] Utilizando interprete Python: %PY%
echo [*] Iniciando interfaz con flag --debug...
echo.

"%PY%" herramientas_extra\monitor_bandeja.py --debug %*
set "EXIT_CODE=%errorlevel%"

echo.
echo =======================================================================
if not "%EXIT_CODE%"=="0" (
    echo [!] ALERTA: La aplicacion ha finalizado con error (Codigo: %EXIT_CODE%).
    echo [i] Puedes seleccionar el texto de arriba para copiarmelo en el chat,
    echo     o ejecutar 'diagnostico.bat' para generar un informe completo.
) else (
    echo [v] Aplicacion cerrada con normalidad.
)
echo =======================================================================
echo Presiona cualquier tecla para cerrar esta ventana...
pause >nul
