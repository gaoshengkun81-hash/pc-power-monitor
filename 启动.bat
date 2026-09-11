@echo off
cd /d %~dp0
if exist PCPowerMonitor.exe (
    start "" PCPowerMonitor.exe
    exit /b
)
if exist dist\PCPowerMonitor.exe (
    start "" dist\PCPowerMonitor.exe
    exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw power_monitor.py
) else (
    echo 未找到可执行文件，也未找到 Python，请先安装 Python 3.9+ 并勾选 Add to PATH
    pause
)
