@echo off
chcp 65001 >nul
title 安装 Windows Server Monitor 服务

echo ========================================
echo   安装 Windows Server Monitor 服务
echo ========================================
echo.

:: 必须以管理员权限运行
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请以管理员权限运行此脚本！
    echo 右键点击 install_service.bat，选择"以管理员身份运行"
    pause
    exit /b 1
)

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python
    pause
    exit /b 1
)

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 检查并安装依赖
echo [1/4] 检查依赖包...
pip show pywin32 >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 正在安装 pywin32...
    pip install pywin32
    if %errorlevel% neq 0 (
        echo [错误] pywin32 安装失败，请手动执行: pip install pywin32
        pause
        exit /b 1
    )
)

pip show psutil >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 正在安装依赖包...
    pip install -r requirements.txt
)

:: 创建日志目录
if not exist "logs" mkdir logs

echo [2/4] 正在安装 Windows 服务...
python main.py -s install
if %errorlevel% neq 0 (
    echo [错误] 服务安装失败
    pause
    exit /b 1
)

echo [3/4] 正在启动服务...
python main.py -s start
if %errorlevel% neq 0 (
    echo [错误] 服务启动失败
    pause
    exit /b 1
)

echo [4/4] 安装完成！
echo.
echo ========================================
echo   服务信息:
echo   服务名称: WindowsServerMonitor
echo   显示名称: Windows Server Monitor
echo   描述: Windows 服务器综合监控系统
echo ========================================
echo.
echo 常用命令:
echo   启动服务: net start WindowsServerMonitor
echo   停止服务: net stop WindowsServerMonitor
echo   查看状态: sc query WindowsServerMonitor
echo   卸载服务: uninstall_service.bat
echo.
pause
