# -*- coding: utf-8 -*-
"""
心跳监控模块 - 定期记录程序和线程运行状态
"""

import threading
import time
import logging
import os
import psutil

logger = logging.getLogger(__name__)


class HeartbeatMonitor(threading.Thread):
    """心跳监控线程，定期输出心跳日志和程序健康状态"""

    def __init__(self, config_manager, metrics_store=None, monitor_threads=None):
        super().__init__(daemon=True, name="HeartbeatMonitor")
        self.config_manager = config_manager
        self.metrics_store = metrics_store
        # 外部传入的监控线程引用，用于状态检查
        self.monitor_threads = monitor_threads or {}
        self._running = True
        self.start_time = time.time()
        self._process = psutil.Process(os.getpid())

    def run(self):
        """主循环：按配置间隔输出心跳"""
        logger.info("HeartbeatMonitor 已启动")
        while self._running:
            try:
                interval = self.config_manager.get('heartbeat.interval', 60)
                self._beat()
                time.sleep(interval)
            except Exception as e:
                logger.error(f"HeartbeatMonitor 异常: {e}", exc_info=True)
                time.sleep(10)

    def stop(self):
        """停止心跳监控"""
        logger.info("HeartbeatMonitor 正在停止...")
        self._running = False

    def _beat(self):
        """执行一次心跳检测"""
        try:
            uptime_seconds = time.time() - self.start_time
            uptime_str = self._format_uptime(uptime_seconds)

            # 线程状态检查
            thread_status = {}
            for name, thread in self.monitor_threads.items():
                if thread:
                    thread_status[name] = "运行中" if thread.is_alive() else "已停止"

            # 程序自身资源占用
            try:
                mem_info = self._process.memory_info()
                mem_mb = mem_info.rss / (1024 * 1024)
                cpu_percent = self._process.cpu_percent(interval=0)
            except Exception:
                mem_mb = 0
                cpu_percent = 0

            logger.info(
                f"心跳 | 运行时长: {uptime_str} | "
                f"内存占用: {mem_mb:.1f}MB | "
                f"CPU占用: {cpu_percent:.1f}% | "
                f"线程状态: {thread_status}"
            )

            # 写入指标存储
            if self.metrics_store:
                self.metrics_store.add("heartbeat", {
                    "uptime_seconds": uptime_seconds,
                    "uptime_str": uptime_str,
                    "memory_mb": round(mem_mb, 1),
                    "cpu_percent": round(cpu_percent, 1),
                    "threads": thread_status,
                })

            # 心跳 Webhook 推送（可选功能）
            webhook_enabled = self.config_manager.get('heartbeat.webhook_enabled', False)
            if webhook_enabled:
                self._push_heartbeat(uptime_str, mem_mb, cpu_percent, thread_status)

        except Exception as e:
            logger.error(f"心跳检测出错: {e}")

    def _push_heartbeat(self, uptime_str, mem_mb, cpu_percent, thread_status):
        """通过 Webhook 发送心跳状态（可选）"""
        try:
            from src.webhook_sender import WebhookSender
            sender = WebhookSender(self.config_manager)
            sender.send({
                "alert_type": "heartbeat",
                "alert_level": "info",
                "metric_name": "心跳检测",
                "current_value": uptime_str,
                "threshold": "无",
                "message": (
                    f"程序运行正常 | 时长: {uptime_str} | "
                    f"内存: {mem_mb:.1f}MB | "
                    f"CPU: {cpu_percent:.1f}% | "
                    f"线程: {thread_status}"
                ),
            })
        except Exception as e:
            logger.debug(f"心跳Webhook推送失败: {e}")

    @staticmethod
    def _format_uptime(seconds):
        """格式化运行时长"""
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}天")
        if hours:
            parts.append(f"{hours}小时")
        if minutes:
            parts.append(f"{minutes}分钟")
        parts.append(f"{secs}秒")
        return "".join(parts)
