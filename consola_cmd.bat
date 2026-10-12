@echo off
cd /d "%~dp0"
title Traductor IA - Consola de Comandos (Entorno de Trabajo)

if exist "venv_traductor\Scripts\activate.bat" (
    call venv_traductor\Scripts\activate.bat
)

echo =======================================================================
echo          CONSOLA CMD INTERACTIVA — TRADUCTOR IA VIDEOJUEGOS
echo =======================================================================
echo Entorno listo en: %CD%
echo.
echo Comandos utiles disponibles:
echo   - Ejecutar diagnostico completo  : python herramientas_extra\diagnostico.py
echo   - Abrir monitor con depuracion   : python herramientas_extra\monitor_bandeja.py --debug
echo   - Traducir juego por consola     : python 1_traducir_juego.py --ruta "Ruta\Al\Juego" --turbo
echo   - Ver modelos de Ollama activos  : ollama list
echo   - Ver estado de la tarjeta GPU   : nvidia-smi
echo =======================================================================
echo.

cmd /k prompt (Traductor-IA) $P$G
