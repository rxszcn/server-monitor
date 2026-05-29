import threading
import time
import queue
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class AlertManager(threading.Thread):
    """告警管理器 - 消费告警队列，执行连续计数、冷却和恢复判定"""

    def __init__(self, alert_queue, config_manager, webhook_sender):
        super().__init__(daemon=True, name="AlertManager")
        self.alert_queue = alert_queue
        self.config_manager = config_manager
        self.webhook_sender = webhook_sender
        self._running = True
        # 状态追踪: key = "type:target" -> {"count": int, "last_alert_time": float, "is_alerting": bool}
        self._state = {}
        self._lock = threading.Lock()

    def run(self):
        """主循环：从队列获取事件并处理"""
        logger.info("AlertManager 已启动")
        while self._running:
            try:
                event = self.alert_queue.get(timeout=1)
                self._process(event)
            except queue.Empty:
                continue  # 正常超时，无事件
            except Exception as e:
                logger.error(f"AlertManager 处理异常: {e}", exc_info=True)
                continue

    def stop(self):
        """停止告警管理器"""
        logger.info("AlertManager 正在停止...")
        self._running = False

    def _process(self, event):
        """处理单个告警事件"""
        event_type = event.get('type', '')
        target = event.get('target', '')
        level = event.get('level', 'warning')  # warning, critical, recovery
        metric_name = event.get('metric_name', '')
        current_value = event.get('current_value', 0)
        threshold = event.get('threshold', 0)

        # 如果 event_type 为空，直接返回
        if not event_type:
            logger.warning("收到无效告警事件: type 为空")
            return

        # 构建状态key
        state_key = f"{event_type}:{target}" if target else event_type

        # 获取配置中的 consecutive_count 和 cooldown
        cfg_prefix = self._get_config_prefix(event_type)
        consecutive_count = self.config_manager.get(f'{cfg_prefix}.consecutive_count', 3)
        cooldown = self.config_manager.get(f'{cfg_prefix}.cooldown', 300)

        with self._lock:
            # 获取当前状态，如果不存在则初始化
            state = self._state.get(state_key, {
                'count': 0,
                'last_alert_time': 0,
                'is_alerting': False
            })

            if level == 'recovery':
                # 恢复事件：仅当之前处于告警状态且冷却已过时发送恢复通知
                if state['is_alerting']:
                    now = time.time()
                    if now - state['last_alert_time'] >= cooldown:
                        try:
                            self._send_alert(
                                event_type, 'info', metric_name,
                                self._format_value(current_value, event_type),
                                self._format_value(threshold, event_type),
                                f"{metric_name}已恢复正常"
                            )
                            logger.info(f"发送恢复通知: {metric_name}")
                        except Exception as e:
                            logger.error(f"发送恢复通知失败: {e}")
                        state['is_alerting'] = False
                        state['count'] = 0
                        state['last_alert_time'] = now
                    else:
                        # 冷却未过，标记为不再告警但暂不发送恢复通知
                        state['is_alerting'] = False
                        state['count'] = 0
                else:
                    # 已经不在告警状态，无需处理
                    state['count'] = 0
            else:
                # 告警事件（warning 或 critical）：累计连续计数
                state['count'] += 1

                logger.debug(
                    f"告警事件累积: key={state_key}, "
                    f"count={state['count']}/{consecutive_count}, "
                    f"level={level}"
                )

                if state['count'] >= consecutive_count:
                    now = time.time()
                    # 冷却检查：之前未告警，或已冷却足够长时间
                    if not state['is_alerting'] or now - state['last_alert_time'] >= cooldown:
                        try:
                            critical_label = "严重" if level == 'critical' else ""
                            self._send_alert(
                                event_type, level, metric_name,
                                self._format_value(current_value, event_type),
                                self._format_value(threshold, event_type),
                                f"{metric_name}超过{critical_label}阈值，"
                                f"当前值：{self._format_value(current_value, event_type)}，"
                                f"阈值：{self._format_value(threshold, event_type)}"
                            )
                            logger.info(
                                f"触发告警: {metric_name}, "
                                f"当前值={self._format_value(current_value, event_type)}, "
                                f"阈值={self._format_value(threshold, event_type)}"
                            )
                        except Exception as e:
                            logger.error(f"发送告警失败: {e}")
                        state['is_alerting'] = True
                        state['last_alert_time'] = now
                        state['count'] = 0  # 触发告警后重置计数

            # 更新状态
            self._state[state_key] = state

    def _get_config_prefix(self, event_type):
        """根据事件类型获取配置前缀"""
        mapping = {
            'cpu': 'system_monitor.cpu',
            'memory': 'system_monitor.memory',
            'disk': 'system_monitor.disk',
            'port': 'port_monitor',
            'process': 'process_monitor',
        }
        return mapping.get(event_type, 'system_monitor.cpu')

    def _get_alert_type(self, event_type, level):
        """生成 alert_type 字段值"""
        if event_type in ('cpu', 'memory', 'disk'):
            return f"{event_type}_high"
        elif event_type == 'port':
            return 'port_down'
        elif event_type == 'process':
            return 'process_down'
        return f"{event_type}_alert"

    def _format_value(self, value, event_type):
        """格式化值的显示"""
        if event_type in ('cpu', 'memory', 'disk'):
            try:
                return f"{float(value):.1f}%"
            except (ValueError, TypeError):
                return f"{value}%"
        elif event_type == 'port':
            return str(value)
        elif event_type == 'process':
            return str(value)
        return str(value)

    def _send_alert(self, event_type, level, metric_name, current_value, threshold, message):
        """通过 webhook 发送告警（静默时段内跳过低级别告警）"""
        # 检查告警静默时段
        if self._is_in_silence_period(level):
            logger.info(f"告警静默中，跳过推送: {metric_name} (级别: {level})")
            return

        alert_type = self._get_alert_type(event_type, level)
        # level 为 info 时视为恢复通知
        if level == 'info':
            alert_type = 'recovery'

        alert_data = {
            "alert_type": alert_type,
            "alert_level": level,
            "metric_name": metric_name,
            "current_value": current_value,
            "threshold": threshold,
            "message": message
        }

        try:
            success, total = self.webhook_sender.send(alert_data)
            if success < total:
                logger.warning(f"告警发送部分失败: 成功 {success}/{total}")
        except Exception as e:
            logger.error(f"webhook_sender.send 调用失败: {e}")

    def _is_in_silence_period(self, level):
        """判断当前是否在告警静默时段内"""
        enabled = self.config_manager.get('alert_silence.enabled', False)
        if not enabled:
            return False

        periods = self.config_manager.get('alert_silence.periods', [])
        if not periods:
            return False

        try:
            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute

            for period in periods:
                silence_level = period.get('level', 'warning')

                # 严重告警不受 warning 级别静默影响
                if level == 'critical' and silence_level == 'warning':
                    continue

                start_str = period.get('start', '00:00')
                end_str = period.get('end', '00:00')

                start_h, start_m = map(int, start_str.split(':'))
                end_h, end_m = map(int, end_str.split(':'))

                start_minutes = start_h * 60 + start_m
                end_minutes = end_h * 60 + end_m

                if start_minutes <= end_minutes:
                    # 同日时间段（如 06:00-22:00）
                    if start_minutes <= current_minutes <= end_minutes:
                        logger.debug(f"当前在静默时段内: {start_str}-{end_str}, 级别: {silence_level}")
                        return True
                else:
                    # 跨天时间段（如 22:00-06:00）
                    if current_minutes >= start_minutes or current_minutes <= end_minutes:
                        logger.debug(f"当前在静默时段内(跨天): {start_str}-{end_str}, 级别: {silence_level}")
                        return True

        except Exception as e:
            logger.warning(f"检查静默时段时出错: {e}")

        return False

    def get_status(self):
        """获取告警状态快照（供外部查询）"""
        with self._lock:
            return dict(self._state)
