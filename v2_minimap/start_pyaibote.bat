@echo off
chcp 65001 >nul
title 95沉默 PyAibote 挂机脚本

REM ===== 检查Python =====
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 请先安装 Python 3.9+
    pause
    exit /b
)

REM ===== 启动PyAibote挂机脚本 =====
cd /d "%~dp0"
echo 正在启动 95沉默 PyAibote 挂机脚本...
echo 确保 WindowsDriver.exe 在脚本同目录下
echo.
python mir2_bot_pyaibote.py
pause