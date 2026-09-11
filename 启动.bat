@echo off
cd /d %~dp0
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw power_monitor.py
) else (
    echo 未找到 Python，请先安装 Python 3.9+ 并勾选 Add to PATH
    pause
)
