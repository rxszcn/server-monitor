# -*- coding: utf-8 -*-
"""
邮件通知模块 - SMTP SSL/TLS 发送
与 Webhook 并行工作，发送失败不影响主流程
"""

import smtplib
import threading
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

logger = logging.getLogger(__name__)


class EmailSender:
    """邮件发送器，支持 SMTP SSL/TLS"""

    def __init__(self, config_manager):
        self.config_manager = config_manager

    def send_alert(self, alert_data):
        """异步发送告警邮件（在独立线程中执行，不阻塞主流程）"""
        enabled = self.config_manager.get('email.enabled', False)
        if not enabled:
            return

        thread = threading.Thread(
            target=self._send_sync,
            args=(alert_data,),
            daemon=True,
            name="EmailSender",
        )
        thread.start()

    def _send_sync(self, alert_data):
        """同步发送邮件"""
        try:
            smtp_server = self.config_manager.get('email.smtp_server', '')
            smtp_port = self.config_manager.get('email.smtp_port', 465)
            sender_email = self.config_manager.get('email.sender_email', '')
            sender_password = self.config_manager.get('email.sender_password', '')
            receiver_emails = self.config_manager.get('email.receiver_emails', [])
            use_ssl = self.config_manager.get('email.use_ssl', True)
            server_name = self.config_manager.get('server.name', 'Unknown')

            if not smtp_server or not sender_email or not receiver_emails:
                logger.warning("邮件配置不完整，跳过发送")
                return

            # 构建邮件内容
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

            alert_type_cn = alert_type_map.get(alert_data.get('alert_type', ''), alert_data.get('alert_type', ''))
            level_cn = level_map.get(alert_data.get('alert_level', ''), '')

            subject = f"[{server_name}] {alert_type_cn} - {level_cn}"
            body_lines = [
                f"服务器: {alert_data.get('server_name', server_name)}",
                f"时间: {alert_data.get('timestamp', '')}",
                f"类型: {alert_type_cn}",
                f"等级: {level_cn}",
                f"指标: {alert_data.get('metric_name', '')}",
                f"当前值: {alert_data.get('current_value', '')}",
                f"阈值: {alert_data.get('threshold', '')}",
                f"详情: {alert_data.get('message', '')}",
            ]

            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = ', '.join(receiver_emails)
            msg['Subject'] = Header(subject, 'utf-8')
            msg.attach(MIMEText('\n'.join(body_lines), 'plain', 'utf-8'))

            # 发送邮件
            if use_ssl:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
                server.starttls()

            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_emails, msg.as_string())
            server.quit()

            logger.info(f"邮件发送成功: {subject}")
        except smtplib.SMTPAuthenticationError:
            logger.error("邮件发送失败: SMTP 认证失败，请检查邮箱账号和授权码")
        except smtplib.SMTPConnectError:
            logger.error(f"邮件发送失败: 无法连接到 SMTP 服务器 {smtp_server}:{smtp_port}")
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")

    def send_test(self):
        """发送测试邮件，验证配置是否正确"""
        test_data = {
            "alert_type": "recovery",
            "alert_level": "info",
            "metric_name": "测试邮件",
            "current_value": "正常",
            "threshold": "无",
            "message": "这是一封测试邮件，用于验证邮件通知配置是否正确。",
            "server_name": self.config_manager.get('server.name', 'Unknown'),
            "timestamp": "",
        }
        self.send_alert(test_data)
