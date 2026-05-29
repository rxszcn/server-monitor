import threading
import time
import logging
import psutil

logger = logging.getLogger(__name__)


class SystemMonitor(threading.Thread):
    """系统资源监控线程 - 采集 CPU、内存、磁盘使用率"""

    def __init__(self, alert_queue, config_manager, metrics_store=None):
        super().__init__(daemon=True, name="SystemMonitor")
        self.alert_queue = alert_queue
        self.config_manager = config_manager
        self.metrics_store = metrics_store
        self._running = True
        # 记录每个指标上次的值，用于判断恢复
        self._last_values = {}  # key -> 上次是否超标
        # 缓存最近一次采集的CPU数据（psutil percpu首次调用返回0）
        self._last_cpu_percent = 0.0
        self._last_per_cpu = []

    def run(self):
        """主循环：按配置间隔采集系统资源数据"""
        logger.info("SystemMonitor 已启动")
        while self._running:
            try:
                # 检查配置热重载
                self.config_manager.check_reload()

                interval = self.config_manager.get('system_monitor.interval', 5)

                self._check_cpu()
                self._check_memory()
                self._check_disks()

                # 控制台实时输出
                self._print_status()

                time.sleep(interval)
            except Exception as e:
                logger.error(f"SystemMonitor 采集异常: {e}", exc_info=True)
                time.sleep(5)  # 出错后等待5秒再继续

    def stop(self):
        """停止监控"""
        logger.info("SystemMonitor 正在停止...")
        self._running = False

    def _check_cpu(self):
        """检查 CPU 使用率"""
        try:
            # 先建立per-cpu基线，再获取整体值（共享同一个1秒窗口）
            try:
                self._last_per_cpu = psutil.cpu_percent(interval=1, percpu=True) or []
                cpu_percent = sum(self._last_per_cpu) / len(self._last_per_cpu) if self._last_per_cpu else 0
            except Exception:
                cpu_percent = psutil.cpu_percent(interval=1)
                self._last_per_cpu = []
            self._last_cpu_percent = cpu_percent
            warning_threshold = self.config_manager.get('system_monitor.cpu.warning_threshold', 80)
            critical_threshold = self.config_manager.get('system_monitor.cpu.critical_threshold', 90)

            event = {
                "type": "cpu",
                "metric_name": "CPU使用率",
                "current_value": cpu_percent,
                "target": "",
            }

            if cpu_percent >= critical_threshold:
                event["level"] = "critical"
                event["threshold"] = critical_threshold
            elif cpu_percent >= warning_threshold:
                event["level"] = "warning"
                event["threshold"] = warning_threshold
            else:
                # 检查是否需要发送恢复通知
                key = "cpu:"
                prev = self._last_values.get(key, False)
                if prev:
                    event["level"] = "recovery"
                    event["threshold"] = warning_threshold
                else:
                    # 正常状态，仅记录到数据存储
                    if self.metrics_store:
                        self.metrics_store.add("cpu", cpu_percent)
                    return  # 正常，不发送事件

            state_key = "cpu:"
            self._last_values[state_key] = (event["level"] != "recovery")
            self.alert_queue.put(event)
            logger.debug(f"CPU: {cpu_percent:.1f}%, level={event['level']}")
            # 写入数据存储
            if self.metrics_store:
                self.metrics_store.add("cpu", cpu_percent)

            # 多物理CPU分别检查告警
            if self._last_per_cpu:
                physical_count = psutil.cpu_count(logical=False) or 1
                logical_count = len(self._last_per_cpu)
                cores_per_physical = max(1, logical_count // physical_count) if physical_count else logical_count
                for p in range(physical_count):
                    start = p * cores_per_physical
                    end = min(start + cores_per_physical, logical_count)
                    group = self._last_per_cpu[start:end]
                    cpu_pct = sum(group) / len(group) if group else 0
                    cpu_label = f"CPU{p}"

                    pevent = {
                        "type": "cpu",
                        "metric_name": f"CPU使用率({cpu_label})",
                        "current_value": cpu_pct,
                        "target": cpu_label,
                    }
                    if cpu_pct >= critical_threshold:
                        pevent["level"] = "critical"
                        pevent["threshold"] = critical_threshold
                    elif cpu_pct >= warning_threshold:
                        pevent["level"] = "warning"
                        pevent["threshold"] = warning_threshold
                    else:
                        pkey = f"cpu:{cpu_label}"
                        pprev = self._last_values.get(pkey, False)
                        if pprev:
                            pevent["level"] = "recovery"
                            pevent["threshold"] = warning_threshold
                        else:
                            continue

                    pstate_key = f"cpu:{cpu_label}"
                    self._last_values[pstate_key] = (pevent["level"] != "recovery")
                    self.alert_queue.put(pevent)

        except Exception as e:
            logger.error(f"检查CPU时出错: {e}")

    def _check_memory(self):
        """检查物理内存使用率"""
        try:
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
            mem_available_gb = mem.available / (1024 ** 3)

            warning_threshold = self.config_manager.get('system_monitor.memory.warning_threshold', 85)
            critical_threshold = self.config_manager.get('system_monitor.memory.critical_threshold', 95)

            event = {
                "type": "memory",
                "metric_name": "内存使用率",
                "current_value": mem_percent,
                "target": "",
            }

            if mem_percent >= critical_threshold:
                event["level"] = "critical"
                event["threshold"] = critical_threshold
            elif mem_percent >= warning_threshold:
                event["level"] = "warning"
                event["threshold"] = warning_threshold
            else:
                key = "memory:"
                prev = self._last_values.get(key, False)
                if prev:
                    event["level"] = "recovery"
                    event["threshold"] = warning_threshold
                else:
                    # 正常状态，仅记录到数据存储
                    if self.metrics_store:
                        self.metrics_store.add("memory", mem_percent, extra={"available_gb": round(mem_available_gb, 2)})
                    return

            state_key = "memory:"
            self._last_values[state_key] = (event["level"] != "recovery")
            self.alert_queue.put(event)
            logger.debug(f"内存: {mem_percent:.1f}%, 可用: {mem_available_gb:.2f}GB, level={event['level']}")
            # 写入数据存储
            if self.metrics_store:
                self.metrics_store.add("memory", mem_percent, extra={"available_gb": round(mem_available_gb, 2)})

        except Exception as e:
            logger.error(f"检查内存时出错: {e}")

    def _check_disks(self):
        """检查所有逻辑磁盘使用率，排除配置中指定的磁盘"""
        try:
            exclude_list = self.config_manager.get('system_monitor.disk.exclude', [])
            # 标准化排除列表为大写
            exclude_list = [d.upper().rstrip(':') + ':' for d in exclude_list if d]

            warning_threshold = self.config_manager.get('system_monitor.disk.warning_threshold', 90)
            critical_threshold = self.config_manager.get('system_monitor.disk.critical_threshold', 95)

            for partition in psutil.disk_partitions():
                try:
                    # 标准化盘符
                    device = partition.device.upper()
                    if ':' in device:
                        device = device.split(':')[0] + ':'

                    # 跳过排除的磁盘
                    if device in exclude_list:
                        continue

                    # 跳过 CD-ROM 等不可访问设备
                    if 'cdrom' in partition.opts.lower():
                        continue

                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_percent = usage.percent
                    disk_free_gb = usage.free / (1024 ** 3)

                    event = {
                        "type": "disk",
                        "metric_name": f"磁盘使用率({device})",
                        "current_value": disk_percent,
                        "target": device,
                    }

                    if disk_percent >= critical_threshold:
                        event["level"] = "critical"
                        event["threshold"] = critical_threshold
                    elif disk_percent >= warning_threshold:
                        event["level"] = "warning"
                        event["threshold"] = warning_threshold
                    else:
                        state_key = f"disk:{device}"
                        prev = self._last_values.get(state_key, False)
                        if prev:
                            event["level"] = "recovery"
                            event["threshold"] = warning_threshold
                        else:
                            # 正常状态，仅记录到数据存储
                            if self.metrics_store:
                                self.metrics_store.add("disk", disk_percent, target=device,
                                                        extra={"free_gb": round(disk_free_gb, 2)})
                            continue

                    state_key = f"disk:{device}"
                    self._last_values[state_key] = (event["level"] != "recovery")
                    self.alert_queue.put(event)
                    logger.debug(
                        f"磁盘 {device}: {disk_percent:.1f}%, "
                        f"可用: {disk_free_gb:.2f}GB, level={event['level']}"
                    )
                    # 写入数据存储
                    if self.metrics_store:
                        self.metrics_store.add("disk", disk_percent, target=device,
                                                extra={"free_gb": round(disk_free_gb, 2)})

                except Exception as e:
                    logger.debug(f"读取磁盘 {partition.device} 信息失败: {e}")

        except Exception as e:
            logger.error(f"检查磁盘时出错: {e}")

    def _print_status(self):
        """控制台实时输出当前监控状态"""
        try:
            from datetime import datetime

            cpu = psutil.cpu_percent(interval=0)  # 非阻塞获取
            mem = psutil.virtual_memory()

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status_line = (
                f"[{timestamp}] "
                f"CPU: {cpu:.1f}% | "
                f"内存: {mem.percent:.1f}% (可用: {mem.available / (1024**3):.2f}GB)"
            )

            # 磁盘信息
            exclude_list = self.config_manager.get('system_monitor.disk.exclude', [])
            exclude_list = [d.upper().rstrip(':') + ':' for d in exclude_list if d]

            disk_parts = []
            for partition in psutil.disk_partitions():
                device = partition.device.upper()
                if ':' in device:
                    device = device.split(':')[0] + ':'
                if device in exclude_list:
                    continue
                if 'cdrom' in partition.opts.lower():
                    continue
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_parts.append(f"{device} {usage.percent:.1f}%")
                except Exception:
                    pass

            if disk_parts:
                status_line += " | " + " | ".join(disk_parts)

            print(status_line, flush=True)

        except Exception as e:
            logger.debug(f"输出状态时出错: {e}")

    def get_cpu_info(self):
        """获取CPU详细信息（使用缓存数据，避免psutil首次调用返回0）"""
        try:
            per_cpu = self._last_per_cpu if self._last_per_cpu else [self._last_cpu_percent]
            logical_count = len(per_cpu) if per_cpu else psutil.cpu_count() or 1
            physical_count = psutil.cpu_count(logical=False) or 1
            cores_per_physical = max(1, logical_count // physical_count) if physical_count else logical_count

            # 计算每个物理CPU的平均使用率（仅多路服务器有意义，>4核组才显示）
            physical_percents = []
            if physical_count > 1 and physical_count <= 4:
                for p in range(physical_count):
                    start = p * cores_per_physical
                    end = min(start + cores_per_physical, logical_count)
                    group = per_cpu[start:end]
                    physical_percents.append(round(sum(group) / len(group), 1) if group else 0)

            return {
                "percent": self._last_cpu_percent,
                "count": logical_count,
                "per_cpu": per_cpu,
                "physical_cpus": len(physical_percents) if physical_percents else 1,
                "cores_per_physical": cores_per_physical,
                "physical_percents": physical_percents if physical_percents else [self._last_cpu_percent],
            }
        except Exception:
            return {"percent": 0, "count": 0, "per_cpu": [], "physical_cpus": 1, "cores_per_physical": 0, "physical_percents": [0]}

    def get_memory_info(self):
        """获取内存详细信息（供外部查询）"""
        try:
            mem = psutil.virtual_memory()
            return {
                "total_gb": mem.total / (1024 ** 3),
                "available_gb": mem.available / (1024 ** 3),
                "percent": mem.percent,
            }
        except Exception:
            return {"total_gb": 0, "available_gb": 0, "percent": 0}

    def get_disk_info(self):
        """获取所有磁盘信息（供外部查询）"""
        disks = []
        try:
            exclude_list = self.config_manager.get('system_monitor.disk.exclude', [])
            exclude_list = [d.upper().rstrip(':') + ':' for d in exclude_list if d]

            for partition in psutil.disk_partitions():
                device = partition.device.upper()
                if ':' in device:
                    device = device.split(':')[0] + ':'
                if device in exclude_list:
                    continue
                if 'cdrom' in partition.opts.lower():
                    continue
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disks.append({
                        "device": device,
                        "total_gb": usage.total / (1024 ** 3),
                        "used_gb": usage.used / (1024 ** 3),
                        "free_gb": usage.free / (1024 ** 3),
                        "percent": usage.percent,
                    })
                except Exception:
                    pass
        except Exception:
            pass
        return disks
