import os
import yaml
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置文件管理器，支持热重载"""

    def __init__(self, config_path="config/config.yaml"):
        self.config_path = config_path
        self.config = {}
        self._last_mtime = 0
        self.load()

    def load(self):
        """加载YAML配置文件，文件不存在时抛出FileNotFoundError"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        self._last_mtime = os.path.getmtime(self.config_path)
        logger.info(f"配置文件已加载: {self.config_path}")

    def check_reload(self):
        """检查配置文件是否被修改，是则自动重载。返回True表示已重载"""
        try:
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime > self._last_mtime:
                self.load()
                logger.info(f"配置文件已热重载: {self.config_path}")
                return True
        except Exception as e:
            logger.warning(f"检查配置文件热重载时出错: {e}")
        return False

    def get(self, key_path, default=None):
        """
        通过点号分隔路径获取配置值
        示例: get('system_monitor.cpu.warning_threshold') -> 80
        """
        keys = key_path.split('.')
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
