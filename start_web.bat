@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

set "PYTHONPATH=%~dp0src"

echo.
echo  Legal Monitor Web UI
echo  --------------------
echo.

"%PY%" scripts\start_web.py
if errorlevel 1 (
    echo.
    echo  Ошибка запуска. Прочитайте сообщения выше.
    pause
)
