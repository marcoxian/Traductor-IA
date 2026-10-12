@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist "venv_traductor\Scripts\pythonw.exe" (
    set "PY=venv_traductor\Scripts\pythonw.exe"
) else if exist "C:\Users\marco\AppData\Local\Programs\Python\Python310\pythonw.exe" (
    set "PY=C:\Users\marco\AppData\Local\Programs\Python\Python310\pythonw.exe"
) else if exist "C:\Python313\pythonw.exe" (
    set "PY=C:\Python313\pythonw.exe"
) else (
    set "PY=pythonw.exe"
)

start "" "%PY%" herramientas_extra\monitor_bandeja.py %*
