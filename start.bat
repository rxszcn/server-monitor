@echo off
chcp 65001 >nul
title Windows 服务器综合监控系统

echo ========================================
echo   Windows 服务器综合监控系统
echo ========================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

:: 检查依赖是否安装
echo [1/3] 检查依赖包...
pip show psutil >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 正在安装依赖包...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖包安装失败
        pause
        exit /b 1
    )
    echo [信息] 依赖包安装完成
) else (
    echo [信息] 依赖包已就绪
)

:: 确保工作目录为脚本所在目录
cd /d "%~dp0"

:: 创建日志目录
if not exist "logs" mkdir logs

echo [2/3] 启动监控系统...
echo [3/3] 按 Ctrl+C 停止程序
echo.
echo ========================================

:: 前台运行
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出，错误码: %errorlevel%
    echo 请查看日志文件获取详细信息: logs\monitor.log
    pause
    exit /b %errorlevel%
)

pause
