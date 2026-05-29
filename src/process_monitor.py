import threading
import time
import logging
import psutil

logger = logging.getLogger(__name__)


class ProcessMonitor(threading.Thread):
    """进程监控线程 - 检测 Windows 进程运行状态"""

    def __init__(self, alert_queue, config_manager):
        super().__init__(daemon=True, name="ProcessMonitor")
        self.alert_queue = alert_queue
        self.config_manager = config_manager
        self._running = True
        # 记录每个进程的状态: key = 进程名(小写) -> bool (True=运行中, False=不存在)
        self._process_status = {}

    def run(self):
        """主循环：按配置间隔检测进程状态"""
        logger.info("ProcessMonitor 已启动")
        while self._running:
            try:
                # 检查配置热重载
                self.config_manager.check_reload()

                interval = self.config_manager.get('process_monitor.interval', 30)
                processes = self.config_manager.get('process_monitor.processes', [])

                # 获取当前所有运行进程的名称集合（小写，用于大小写不敏感比较）
                running_processes = set()
                try:
                    for proc in psutil.process_iter(['name']):
                        try:
                            running_processes.add(proc.info['name'].lower())
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except Exception as e:
                    logger.error(f"获取运行进程列表失败: {e}")

                for proc_name in processes:
                    self._check_process(proc_name, running_processes)

                time.sleep(interval)
            except Exception as e:
                logger.error(f"ProcessMonitor 采集异常: {e}", exc_info=True)
                time.sleep(5)

    def stop(self):
        """停止监控"""
        logger.info("ProcessMonitor 正在停止...")
        self._running = False

    def _check_process(self, proc_name, running_processes):
        """检测单个进程是否运行"""
        try:
            # 大小写不敏感比较（Windows 进程名不区分大小写）
            is_running = proc_name.lower() in running_processes

            # 获取上一次状态，默认认为进程在运行
            prev_status = self._process_status.get(proc_name.lower(), True)

            event = {
                "type": "process",
                "metric_name": f"进程状态({proc_name})",
                "target": proc_name,
            }

            if not is_running:
                # 进程不存在
                event["level"] = "warning"
                event["current_value"] = "未运行"
                event["threshold"] = "运行中"
                self.alert_queue.put(event)
                logger.warning(f"进程未运行: {proc_name}")
            elif prev_status is False:
                # 进程之前不存在，现在恢复了
                event["level"] = "recovery"
                event["current_value"] = "运行中"
                event["threshold"] = "运行中"
                self.alert_queue.put(event)
                logger.info(f"进程已恢复: {proc_name}")

            self._process_status[proc_name.lower()] = is_running

        except Exception as e:
            logger.error(f"检测进程 {proc_name} 时出错: {e}")

    def get_status(self):
        """获取所有进程状态（供外部查询）"""
        return dict(self._process_status)
