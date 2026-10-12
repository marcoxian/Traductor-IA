@echo off
setlocal
cd /d "%~dp0"

if exist venv_traductor\Scripts\pythonw.exe (
    start "" venv_traductor\Scripts\pythonw.exe herramientas_extra\monitor_bandeja.py %*
) else (
    start "" pythonw herramientas_extra\monitor_bandeja.py %*
)
