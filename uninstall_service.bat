@echo off
chcp 65001 >nul
title 卸载 Windows Server Monitor 服务

echo ========================================
echo   卸载 Windows Server Monitor 服务
echo ========================================
echo.

:: 必须以管理员权限运行
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请以管理员权限运行此脚本！
    echo 右键点击 uninstall_service.bat，选择"以管理员身份运行"
    pause
    exit /b 1
)

cd /d "%~dp0"

echo [1/2] 正在停止服务...
net stop WindowsServerMonitor >nul 2>&1
sc stop WindowsServerMonitor >nul 2>&1
echo [信息] 服务已停止（如果正在运行）

echo [2/2] 正在卸载服务...
python main.py -s remove
if %errorlevel% neq 0 (
    echo [警告] 通过 Python 卸载失败，尝试直接删除...
    sc delete WindowsServerMonitor
)

echo.
echo ========================================
echo   服务已成功卸载
echo ========================================
echo.
pause
