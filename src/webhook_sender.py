import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


class WebhookSender:
    """Webhook 推送器，支持多URL同时推送和失败重试"""

    def __init__(self, config_manager):
        self.config_manager = config_manager

    def send(self, alert_data):
        """
        发送告警到所有配置的webhook地址

        alert_data 格式:
        {
            "alert_type": "cpu_high|memory_high|disk_high|port_down|process_down|recovery",
            "alert_level": "warning|critical|info",
            "metric_name": "CPU使用率",
            "current_value": "85%",
            "threshold": "80%",
            "message": "CPU使用率超过阈值，当前值：85%，阈值：80%"
        }

        函数负责补充 timestamp 和 server_name 字段
        返回: (成功数, 总URL数)
        """
        urls = self.config_manager.get('webhook.urls', [])
        timeout = self.config_manager.get('webhook.timeout', 10)
        retry_count = self.config_manager.get('webhook.retry_count', 3)
        retry_interval = self.config_manager.get('webhook.retry_interval', 5)
        server_name = self.config_manager.get('server.name', 'Unknown')

        # 如果没有任何 webhook URL，直接返回
        if not urls:
            logger.warning("没有配置 webhook URL，跳过告警推送")
            return 0, 0

        # 构建完整payload，补充 timestamp（UTC+8）和 server_name
        tz = timezone(timedelta(hours=8))  # UTC+8
        payload = {
            "timestamp": datetime.now(tz).isoformat(),
            "server_name": server_name,
            "alert_type": alert_data.get('alert_type', ''),
            "alert_level": alert_data.get('alert_level', ''),
            "metric_name": alert_data.get('metric_name', ''),
            "current_value": alert_data.get('current_value', ''),
            "threshold": alert_data.get('threshold', ''),
            "message": alert_data.get('message', '')
        }

        success = 0
        session = requests.Session()

        for url in urls:
            # 根据平台生成对应格式的 payload
            formatted_payload = self._format_for_platform(url, payload)

            for attempt in range(retry_count):
                try:
                    resp = session.post(
                        url,
                        json=formatted_payload,
                        timeout=timeout,
                        headers={'Content-Type': 'application/json'}
                    )
                    if 200 <= resp.status_code < 300:
                        # 飞书/钉钉/企微即使返回200，body中可能包含错误码
                        body_ok = self._check_response(resp, url)
                        if body_ok:
                            success += 1
                            logger.info(f"告警推送成功: {url}")
                            break
                        # body有错误码，继续重试
                        if attempt < retry_count - 1:
                            time.sleep(retry_interval)
                    else:
                        # 非2xx重试
                        logger.warning(
                            f"告警推送返回非200状态码: {url}, "
                            f"状态码: {resp.status_code}, "
                            f"响应: {resp.text[:200]}, "
                            f"尝试次数: {attempt + 1}/{retry_count}"
                        )
                        if attempt < retry_count - 1:
                            time.sleep(retry_interval)
                except requests.exceptions.Timeout:
                    logger.warning(
                        f"告警推送超时: {url}, "
                        f"尝试次数: {attempt + 1}/{retry_count}"
                    )
                    if attempt < retry_count - 1:
                        time.sleep(retry_interval)
                except requests.exceptions.ConnectionError:
                    logger.warning(
                        f"告警推送连接失败: {url}, "
                        f"尝试次数: {attempt + 1}/{retry_count}"
                    )
                    if attempt < retry_count - 1:
                        time.sleep(retry_interval)
                except Exception as e:
                    logger.error(
                        f"告警推送未知错误: {url}, "
                        f"错误: {e}, "
                        f"尝试次数: {attempt + 1}/{retry_count}"
                    )
                    if attempt < retry_count - 1:
                        time.sleep(retry_interval)

        session.close()
        logger.info(f"告警推送完成: 成功 {success}/{len(urls)}")
        return success, len(urls)

    def _format_for_platform(self, url, payload):
        """根据 webhook URL 所属平台，生成对应格式的消息体"""
        url_lower = url.lower()

        if 'feishu' in url_lower:
            # 飞书自定义机器人格式
            text = self._build_text_message(payload)
            return {
                "msg_type": "text",
                "content": {
                    "text": text
                }
            }
        elif 'qyapi.weixin' in url_lower:
            # 企业微信机器人格式
            text = self._build_text_message(payload)
            return {
                "msgtype": "text",
                "text": {
                    "content": text
                }
            }
        elif 'dingtalk' in url_lower or 'oapi.dingtalk' in url_lower:
            # 钉钉机器人格式
            text = self._build_text_message(payload)
            return {
                "msgtype": "text",
                "text": {
                    "content": text
                }
            }
        else:
            # 通用格式：直接发送标准 JSON
            return payload

    @staticmethod
    def _check_response(resp, url):
        """检查响应体中的业务错误码（飞书/钉钉/企微可能返回200但code≠0）"""
        try:
            body = resp.json()
            code = body.get('code') or body.get('errcode') or body.get('Status') or body.get('StatusCode')
            if code is not None and code != 0:
                logger.warning(f"Webhook返回业务错误: {url}, code={code}, msg={body.get('msg', body.get('errmsg', ''))}")
                return False
        except Exception:
            pass  # 无法解析JSON就当成功
        return True

    @staticmethod
    def _build_text_message(payload):
        """将告警 payload 构建为可读的文本消息（用于飞书/企微/钉钉）"""
        alert_type_map = {
            'cpu_high': 'CPU使用率过高',
            'memory_high': '内存使用率过高',
            'disk_high': '磁盘使用率过高',
            'port_down': '端口不可达',
            'process_down': '进程未运行',
            'recovery': '恢复通知',
        }
        level_map = {
            'warning': '⚠️ 警告',
            'critical': '🚨 严重',
            'info': '✅ 恢复',
        }

        alert_type_cn = alert_type_map.get(payload.get('alert_type', ''), payload.get('alert_type', ''))
        level_cn = level_map.get(payload.get('alert_level', ''), payload.get('alert_level', ''))

        lines = [
            f"【{alert_type_cn}】{level_cn}",
            f"服务器: {payload.get('server_name', '')}",
            f"时间: {payload.get('timestamp', '')}",
            f"指标: {payload.get('metric_name', '')}",
            f"当前值: {payload.get('current_value', '')}",
            f"阈值: {payload.get('threshold', '')}",
            f"详情: {payload.get('message', '')}",
        ]
        return "\n".join(lines)
