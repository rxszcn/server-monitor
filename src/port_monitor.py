import threading
import time
import socket
import logging

logger = logging.getLogger(__name__)


class PortMonitor(threading.Thread):
    """端口监控线程 - 检测 TCP 端口连通性"""

    def __init__(self, alert_queue, config_manager):
        super().__init__(daemon=True, name="PortMonitor")
        self.alert_queue = alert_queue
        self.config_manager = config_manager
        self._running = True
        # 记录每个端口的状态，用于判断恢复: key = "ip:port" -> bool (True=可连通, False=不可达)
        self._port_status = {}

    def run(self):
        """主循环：按配置间隔检测端口连通性"""
        logger.info("PortMonitor 已启动")
        while self._running:
            try:
                # 检查配置热重载
                self.config_manager.check_reload()

                interval = self.config_manager.get('port_monitor.interval', 30)
                ports = self.config_manager.get('port_monitor.ports', [])

                for port_entry in ports:
                    self._check_port(port_entry)

                time.sleep(interval)
            except Exception as e:
                logger.error(f"PortMonitor 采集异常: {e}", exc_info=True)
                time.sleep(5)

    def stop(self):
        """停止监控"""
        logger.info("PortMonitor 正在停止...")
        self._running = False

    def _check_port(self, port_entry):
        """检测单个端口的连通性"""
        try:
            # 解析 IP:端口 格式
            if ':' not in port_entry:
                logger.warning(f"端口配置格式错误: {port_entry}")
                return

            # 支持 IPv6 地址（格式如 [::1]:80）
            if port_entry.startswith('['):
                # IPv6 格式
                addr_end = port_entry.rindex(']')
                ip = port_entry[1:addr_end]
                port = int(port_entry[addr_end + 2:])
            else:
                parts = port_entry.rsplit(':', 1)
                ip = parts[0]
                port = int(parts[1])

            timeout = self.config_manager.get('port_monitor.timeout', 5)

            event = {
                "type": "port",
                "metric_name": f"端口连通性({port_entry})",
                "target": port_entry,
            }

            # 尝试 TCP 连接
            is_reachable = False
            try:
                sock = socket.create_connection((ip, port), timeout=timeout)
                sock.close()
                is_reachable = True
            except (socket.timeout, ConnectionRefusedError, OSError):
                is_reachable = False

            prev_status = self._port_status.get(port_entry, True)  # 默认为正常

            if not is_reachable:
                # 端口不可达
                event["level"] = "warning"
                event["current_value"] = "不可达"
                event["threshold"] = "可连通"
                self.alert_queue.put(event)
                logger.warning(f"端口不可达: {port_entry}")
            elif prev_status is False:
                # 之前不可达，现在恢复
                event["level"] = "recovery"
                event["current_value"] = "已恢复"
                event["threshold"] = "可连通"
                self.alert_queue.put(event)
                logger.info(f"端口已恢复: {port_entry}")

            self._port_status[port_entry] = is_reachable

        except ValueError as e:
            logger.error(f"端口格式解析错误: {port_entry}, {e}")
        except Exception as e:
            logger.error(f"检测端口 {port_entry} 时出错: {e}")

    def get_status(self):
        """获取所有端口状态（供外部查询）"""
        return dict(self._port_status)
