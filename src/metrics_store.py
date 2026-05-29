# -*- coding: utf-8 -*-
"""
指标数据存储模块 - 内存环形缓冲区 + CSV 导出
线程安全，支持历史查询和数据导出
"""

import csv
import threading
import time
from collections import deque
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MetricsStore:
    """线程安全的指标数据存储，环形缓冲 + CSV 导出"""

    def __init__(self, max_records=1000):
        self.max_records = max_records
        self._records = deque(maxlen=max_records)
        self._lock = threading.Lock()
        # 最新快照数据，供 Web 界面快速读取
        self._latest = {}
        self.start_time = time.time()

    def add(self, metric_type, value, target="", extra=None):
        """添加一条指标记录"""
        record = {
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": metric_type,
            "value": value,
            "target": target,
            "extra": extra or {},
        }
        with self._lock:
            self._records.append(record)
            # 更新最新快照
            key = f"{metric_type}:{target}" if target else metric_type
            self._latest[key] = record

    def get_latest(self):
        """获取所有指标的最新快照（供 Web 界面使用）"""
        with self._lock:
            return dict(self._latest)

    def get_history(self, metric_type=None, minutes=60):
        """获取最近N分钟的历史记录"""
        cutoff = time.time() - minutes * 60
        result = []
        with self._lock:
            for record in self._records:
                if record["timestamp"] >= cutoff:
                    if metric_type is None or record["type"] == metric_type:
                        result.append({
                            "datetime": record["datetime"],
                            "type": record["type"],
                            "value": record["value"],
                            "target": record["target"],
                        })
        return result

    def get_recent(self, count=20):
        """获取最近N条记录"""
        with self._lock:
            records = list(self._records)[-count:]
            return [
                {
                    "datetime": r["datetime"],
                    "type": r["type"],
                    "value": r["value"],
                    "target": r["target"],
                }
                for r in records
            ]

    def export_csv(self, filepath, minutes=60):
        """导出指定时间范围的记录为 CSV 文件"""
        records = self.get_history(minutes=minutes)
        if not records:
            logger.warning("无数据可导出")
            return False

        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["时间", "类型", "指标", "值", "目标"])
                for r in records:
                    type_map = {
                        "cpu": "CPU使用率", "memory": "内存使用率",
                        "disk": "磁盘使用率", "port": "端口状态",
                        "process": "进程状态", "heartbeat": "心跳",
                    }
                    writer.writerow([
                        r["datetime"],
                        type_map.get(r["type"], r["type"]),
                        type_map.get(r["type"], r["type"]),
                        r["value"],
                        r["target"],
                    ])
            logger.info(f"CSV导出成功: {filepath}, 共 {len(records)} 条记录")
            return True
        except Exception as e:
            logger.error(f"CSV导出失败: {e}")
            return False

    def get_stats(self):
        """获取统计信息"""
        with self._lock:
            total = len(self._records)
        return {
            "total_records": total,
            "max_records": self.max_records,
            "uptime_seconds": time.time() - self.start_time,
        }
