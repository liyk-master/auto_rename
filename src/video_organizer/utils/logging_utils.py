import logging
import logging.handlers
import os
import sys
from typing import Dict, Any, Optional

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 日志级别映射
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """
    设置日志记录
    
    Args:
        config: 日志配置，包含log_level、log_file、console_log、file_log等
    """
    # 默认配置
    default_config = {
        'log_level': 'INFO',
        'log_file': '',
        'console_log': True,
        'file_log': False
    }
    
    if config:
        default_config.update(config)
    
    # 获取根日志记录器
    root_logger = logging.getLogger()
    
    # 清除所有现有的处理器
    root_logger.handlers.clear()
    
    # 设置日志级别
    log_level = LOG_LEVELS.get(default_config['log_level'], logging.INFO)
    root_logger.setLevel(log_level)
    
    # 创建格式化器
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    
    # 添加控制台处理器
    if default_config['console_log']:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # 添加文件处理器
    if default_config['file_log'] and default_config['log_file']:
        log_file = default_config['log_file']
        
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            root_logger.info(f"日志文件已设置: {log_file}")
        except Exception as e:
            print(f"设置日志文件失败: {e}")
    
    # 记录初始化信息
    root_logger.info("日志系统初始化完成")


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志记录器
    
    Args:
        name: 日志记录器名称
    
    Returns:
        日志记录器实例
    """
    return logging.getLogger(name)


def log_exception(logger: logging.Logger, message: str, exc_info: bool = True) -> None:
    """
    记录异常信息
    
    Args:
        logger: 日志记录器
        message: 错误消息
        exc_info: 是否包含异常堆栈
    """
    logger.error(message, exc_info=exc_info)


def log_warning_with_details(logger: logging.Logger, message: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    记录带有详细信息的警告
    
    Args:
        logger: 日志记录器
        message: 警告消息
        details: 详细信息字典
    """
    if details:
        details_str = ', '.join([f"{k}={v}" for k, v in details.items()])
        logger.warning(f"{message} - 详情: {details_str}")
    else:
        logger.warning(message)


def log_success(logger: logging.Logger, message: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    记录成功信息
    
    Args:
        logger: 日志记录器
        message: 成功消息
        details: 详细信息字典
    """
    if details:
        details_str = ', '.join([f"{k}={v}" for k, v in details.items()])
        logger.info(f"✅ {message} - 详情: {details_str}")
    else:
        logger.info(f"✅ {message}")


def log_failure(logger: logging.Logger, message: str, error: Optional[Exception] = None) -> None:
    """
    记录失败信息
    
    Args:
        logger: 日志记录器
        message: 失败消息
        error: 异常对象
    """
    if error:
        logger.error(f"❌ {message} - 错误: {str(error)}", exc_info=True)
    else:
        logger.error(f"❌ {message}")


def configure_log_rotation(file_path: str, max_bytes: int = 10485760, backup_count: int = 5) -> logging.handlers.RotatingFileHandler:
    """
    配置日志轮转
    
    Args:
        file_path: 日志文件路径
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的备份文件数
    
    Returns:
        轮转文件处理器
    """
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    handler = logging.handlers.RotatingFileHandler(
        file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    handler.setFormatter(formatter)
    return handler
