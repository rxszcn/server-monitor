#!/bin/bash
# 服务器监控系统 - Linux 启动脚本

cd "$(dirname "$0")"

echo "========================================"
echo "  服务器综合监控系统"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装 Python 3.8+"
    exit 1
fi

# 检查依赖
echo "[1/3] 检查依赖包..."
if ! python3 -c "import psutil" 2>/dev/null; then
    echo "[信息] 正在安装依赖包..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[错误] 依赖包安装失败"
        exit 1
    fi
fi

# 创建日志目录
mkdir -p logs

echo "[2/3] 启动监控系统..."
echo "[3/3] 按 Ctrl+C 停止程序"
echo ""
echo "========================================"

# 前台运行
python3 main.py "$@"
