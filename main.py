# -*- coding: utf-8 -*-
"""
服务器综合监控系统 - 主程序入口
支持控制台前台运行和 Windows 服务后台运行
"""

import sys
import os
import time
import signal
import threading
import queue
import logging

# 将 src 目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.logger_setup import setup_logging
from src.config_manager import ConfigManager
from src.webhook_sender import WebhookSender
from src.alert_manager import AlertManager
from src.system_monitor import SystemMonitor
from src.port_monitor import PortMonitor
from src.process_monitor import ProcessMonitor
from src.metrics_store import MetricsStore
from src.email_sender import EmailSender
from src.heartbeat_monitor import HeartbeatMonitor
from src.web_dashboard import init_web_app, run_web_server

logger = logging.getLogger(__name__)

# 全局变量，用于信号处理和服务控制
_monitor_instance = None


class MonitorApplication:
    """监控系统主应用程序，管理所有监控线程"""

    def __init__(self, config_path="config/config.yaml", is_service=False):
        self.config_path = config_path
        self.is_service = is_service
        self.config_manager = None
        self.webhook_sender = None
        self.alert_manager = None
        self.system_monitor = None
        self.port_monitor = None
        self.process_monitor = None
        self.metrics_store = None       # 指标数据存储
        self.email_sender = None        # 邮件发送器
        self.heartbeat_monitor = None   # 心跳监控
        self.web_thread = None          # Web 界面线程
        self.alert_queue = queue.Queue(maxsize=1000)
        self._running = True
        # 线程配置映射，用于健康检查和自动重启
        self._thread_configs = {}

    def initialize(self):
        """初始化所有组件"""
        # 1. 加载配置
        self.config_manager = ConfigManager(self.config_path)

        # 2. 初始化日志系统
        log_config = self.config_manager.config.get('logging', {})
        setup_logging(log_config, is_service=self.is_service)
        logger.info("=" * 50)
        logger.info("服务器综合监控系统 正在启动...")
        logger.info("服务器名称: %s", self.config_manager.get('server.name', 'Unknown'))
        logger.info("运行模式: %s", "Windows 服务" if self.is_service else "控制台前台")

        # 3. 初始化 Webhook 发送器
        self.webhook_sender = WebhookSender(self.config_manager)

        # 4. 初始化指标数据存储（内存环形缓冲）
        max_records = self.config_manager.get('metrics_store.max_records', 1000)
        self.metrics_store = MetricsStore(max_records=max_records)
        logger.info("指标数据存储已初始化 (最大记录数: %d)", max_records)

        # 5. 初始化邮件发送器
        self.email_sender = EmailSender(self.config_manager)
        if self.config_manager.get('email.enabled', False):
            logger.info("邮件通知已启用")

        # 6. 初始化告警管理器（守护线程）
        self.alert_manager = AlertManager(
            self.alert_queue, self.config_manager, self.webhook_sender
        )

        # 7. 初始化三个监控线程（传入 metrics_store）
        self.system_monitor = SystemMonitor(
            self.alert_queue, self.config_manager, metrics_store=self.metrics_store
        )
        self.port_monitor = PortMonitor(self.alert_queue, self.config_manager)
        self.process_monitor = ProcessMonitor(self.alert_queue, self.config_manager)

        # 8. 初始化心跳监控
        self.heartbeat_monitor = HeartbeatMonitor(
            self.config_manager,
            metrics_store=self.metrics_store,
            monitor_threads={
                'system_monitor': self.system_monitor,
                'port_monitor': self.port_monitor,
                'process_monitor': self.process_monitor,
                'alert_manager': self.alert_manager,
            }
        )

        # 9. 初始化 Web 管理界面
        init_web_app(
            self.metrics_store, self.config_manager,
            system_monitor=self.system_monitor,
            port_monitor=self.port_monitor,
            process_monitor=self.process_monitor,
            alert_manager=self.alert_manager,
        )

        # 记录线程配置用于健康检查
        self._thread_configs = {
            'system_monitor': {
                'thread': self.system_monitor,
                'factory': lambda: SystemMonitor(
                    self.alert_queue, self.config_manager,
                    metrics_store=self.metrics_store
                ),
            },
            'port_monitor': {
                'thread': self.port_monitor,
                'factory': lambda: PortMonitor(self.alert_queue, self.config_manager),
            },
            'process_monitor': {
                'thread': self.process_monitor,
                'factory': lambda: ProcessMonitor(self.alert_queue, self.config_manager),
            },
            'heartbeat_monitor': {
                'thread': self.heartbeat_monitor,
                'factory': lambda: HeartbeatMonitor(
                    self.config_manager,
                    metrics_store=self.metrics_store,
                    monitor_threads={
                        'system_monitor': self.system_monitor,
                        'port_monitor': self.port_monitor,
                        'process_monitor': self.process_monitor,
                        'alert_manager': self.alert_manager,
                    }
                ),
            },
        }

        logger.info("所有组件初始化完成")

    def start(self):
        """启动所有监控线程"""
        logger.info("正在启动监控线程...")

        self.alert_manager.start()
        self.system_monitor.start()
        self.port_monitor.start()
        self.process_monitor.start()
        self.heartbeat_monitor.start()

        logger.info("AlertManager 已启动")
        logger.info("SystemMonitor 已启动")
        logger.info("PortMonitor 已启动")
        logger.info("ProcessMonitor 已启动")
        logger.info("HeartbeatMonitor 已启动")

        # 启动 Web 管理界面（可选）
        if self.config_manager.get('web_dashboard.enabled', True):
            web_host = self.config_manager.get('web_dashboard.host', '0.0.0.0')
            web_port = self.config_manager.get('web_dashboard.port', 5000)
            self.web_thread = threading.Thread(
                target=run_web_server,
                kwargs={'host': web_host, 'port': web_port},
                daemon=True,
                name="WebDashboard",
            )
            self.web_thread.start()
            logger.info("Web 管理界面已启动: http://%s:%d", web_host, web_port)

        logger.info("所有监控线程已启动，系统运行中...")

    def stop(self):
        """优雅停止所有线程"""
        logger.info("正在停止所有监控线程...")
        self._running = False

        # 按启动的逆序停止线程
        for name, config in self._thread_configs.items():
            thread = config['thread']
            if thread and thread.is_alive():
                try:
                    thread.stop()
                    logger.info("已发送停止信号: %s", name)
                except Exception as e:
                    logger.error("停止 %s 时出错: %s", name, e)

        # 停止告警管理器
        if self.alert_manager and self.alert_manager.is_alive():
            try:
                self.alert_manager.stop()
                logger.info("已发送停止信号: alert_manager")
            except Exception as e:
                logger.error("停止 alert_manager 时出错: %s", e)

        # 等待所有线程结束（最多等待10秒）
        all_threads = [self.alert_manager, self.system_monitor,
                       self.port_monitor, self.process_monitor,
                       self.heartbeat_monitor]
        for thread in all_threads:
            if thread and thread.is_alive():
                thread.join(timeout=10)
                if thread.is_alive():
                    logger.warning("线程 %s 未能在10秒内停止", thread.name)

        logger.info("所有监控线程已停止")
        logger.info("服务器综合监控系统 已退出")

    def health_check(self):
        """健康检查：检测异常退出的线程并自动重启"""
        for name, config in self._thread_configs.items():
            thread = config['thread']
            if thread and not thread.is_alive():
                logger.warning("检测到线程 %s 异常退出，正在重启...", name)
                try:
                    new_thread = config['factory']()
                    new_thread.start()
                    config['thread'] = new_thread
                    logger.info("线程 %s 已重启", name)
                except Exception as e:
                    logger.error("重启线程 %s 失败: %s", name, e)

        # 检查告警管理器
        if self.alert_manager and not self.alert_manager.is_alive():
            logger.warning("检测到 AlertManager 异常退出，正在重启...")
            try:
                new_alert_mgr = AlertManager(
                    self.alert_queue, self.config_manager, self.webhook_sender
                )
                new_alert_mgr.start()
                self.alert_manager = new_alert_mgr
                logger.info("AlertManager 已重启")
            except Exception as e:
                logger.error("重启 AlertManager 失败: %s", e)

    def run(self):
        """主运行循环"""
        try:
            self.initialize()
            self.start()

            # 主循环：健康检查 + 配置热重载
            while self._running:
                try:
                    time.sleep(10)  # 每10秒检查一次

                    # 配置热重载
                    if self.config_manager.check_reload():
                        logger.info("配置文件已热重载，新配置将在下个采集周期生效")

                    # 线程健康检查
                    self.health_check()

                except Exception as e:
                    logger.error("主循环异常: %s", e)
                    time.sleep(5)

        except KeyboardInterrupt:
            logger.info("收到中断信号 (Ctrl+C)")
        except Exception as e:
            logger.error("程序运行异常: %s", e, exc_info=True)
        finally:
            self.stop()


def run_as_service():
    """Windows 服务模式运行"""
    try:
        import win32serviceutil
        import win32service
        import win32event
        import servicemanager
    except ImportError:
        logger.error("pywin32 未安装，无法以 Windows 服务模式运行")
        logger.error("请执行: pip install pywin32")
        sys.exit(1)

    class MonitorService(win32serviceutil.ServiceFramework):
        _svc_name_ = "WindowsServerMonitor"
        _svc_display_name_ = "Windows Server Monitor"
        _svc_description_ = "Windows 服务器综合监控系统 - CPU/内存/磁盘/端口/进程监控与告警"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            self.app = None

        def SvcDoRun(self):
            """服务启动入口"""
            global _monitor_instance
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )

            self.app = MonitorApplication(is_service=True)
            _monitor_instance = self.app

            try:
                self.app.initialize()
                self.app.start()

                # 等待停止信号
                while self.app._running:
                    rc = win32event.WaitForSingleObject(self.hWaitStop, 10000)  # 10秒超时
                    if rc == win32event.WAIT_OBJECT_0:
                        # 收到停止信号
                        break
                    # 执行健康检查
                    self.app.health_check()
                    self.app.config_manager.check_reload()

            except Exception as e:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_ERROR_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, "错误: %s" % e)
                )
            finally:
                if self.app:
                    self.app.stop()

        def SvcStop(self):
            """服务停止入口"""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self.app:
                self.app._running = False
            win32event.SetEvent(self.hWaitStop)

    # 启动服务
    win32serviceutil.HandleCommandLine(MonitorService)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Windows 服务器综合监控系统")
    parser.add_argument(
        '-c', '--config',
        default='config/config.yaml',
        help='配置文件路径 (默认: config/config.yaml)'
    )
    parser.add_argument(
        '-s', '--service',
        choices=['install', 'start', 'stop', 'remove'],
        help='Windows 服务操作: install/start/stop/remove'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='调试模式（DEBUG 日志级别）'
    )

    args = parser.parse_args()

    # 确保工作目录正确
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # 服务模式操作
    if args.service:
        # Windows 服务模式
        run_as_service()
        return

    # 前台运行模式
    global _monitor_instance

    # 临时加载配置以初始化日志
    temp_config = ConfigManager(args.config)

    # 调试模式覆盖日志级别
    if args.debug:
        temp_config.config.setdefault('logging', {})['level'] = 'DEBUG'

    # 初始化日志
    log_config = temp_config.config.get('logging', {})
    setup_logging(log_config, is_service=False)

    # 创建并运行应用程序
    app = MonitorApplication(config_path=args.config, is_service=False)
    _monitor_instance = app

    # 注册信号处理函数（仅在非 Windows 或 Python 支持时）
    def signal_handler(signum, frame):
        """处理终止信号"""
        logger.info("收到信号 %s，正在退出...", signum)
        app._running = False

    # Windows 上 signal 支持有限，使用 try-except
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except (AttributeError, ValueError):
        # Windows 不支持这些信号或在非主线程中
        pass

    app.run()


if __name__ == '__main__':
    main()
