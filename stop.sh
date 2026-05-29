#!/bin/bash
# 服务器监控系统 - Linux 停止脚本

PID=$(pgrep -f "python3 main.py")
if [ -n "$PID" ]; then
    echo "正在停止监控系统 (PID: $PID)..."
    kill $PID
    sleep 2
    if ps -p $PID > /dev/null 2>&1; then
        echo "强制停止..."
        kill -9 $PID
    fi
    echo "监控系统已停止"
else
    echo "监控系统未运行"
fi
