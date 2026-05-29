import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(config, is_service=False):
    """
    配置并返回 root logger。

    Args:
        config: 配置字典或 ConfigManager 对象，需包含 logging 相关配置。
        is_service: 当为 True 时仅输出到文件，为 False 时同时输出到控制台。

    Returns:
        配置好的 root logger。
    """
    # 从 config 中获取 logging 配置节
    if hasattr(config, 'get') and callable(getattr(config, 'get')):
        # ConfigManager 对象
        log_config = config.get('logging', {})
        if not isinstance(log_config, dict):
            log_config = {}
    elif isinstance(config, dict):
        log_config = config.get('logging', {})
    else:
        log_config = {}

    # 读取日志级别，默认为 INFO
    level_str = log_config.get('level', 'INFO').upper()
    level = getattr(logging, level_str, logging.INFO)

    # 读取日志文件路径
    log_file = log_config.get('file', 'logs/monitor.log')
    # 统一使用正斜杠，确保路径处理一致
    log_file = log_file.replace('\\', '/')

    # 读取 max_size（单位 MB），转换为 bytes
    max_size_mb = log_config.get('max_size', 10)
    max_bytes = max_size_mb * 1024 * 1024

    # 读取 backup_count
    backup_count = log_config.get('backup_count', 5)

    # 确保日志文件所在的目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            # 如果目录创建失败，将日志文件回退到当前目录
            log_file = os.path.basename(log_file)
            print(f"警告：无法创建日志目录 {log_dir}，回退到 {log_file}。错误: {e}")

    # 获取 root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # 清除已有的 handler，避免重复添加
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 创建 RotatingFileHandler（文件输出）
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"警告：无法创建文件日志处理器 {log_file}。错误: {e}")

    # 非服务模式时同时输出到控制台
    if not is_service:
        try:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        except Exception as e:
            print(f"警告：无法创建控制台日志处理器。错误: {e}")

    return logger
