"""
下载器监控 — 抽象基类 + 状态枚举 + 工具函数
"""

import os
import re
import threading
import logging
import urllib.parse
from abc import ABC, abstractmethod
from typing import Optional, Callable, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class MonitorMode(Enum):
    """aria2 监控模式"""
    POLLING = "polling"      # 轮询模式（兼容性最好）
    WEBSOCKET = "websocket"  # WebSocket 实时模式（高效）
    WEBHOOK = "webhook"      # Webhook 模式（需要配置 aria2）


def decode_file_path(file_path: str) -> str:
    """智能解码文件路径，正确处理 URL 编码的中文和特殊字符。"""
    if not file_path:
        return file_path
    if not re.search(r'%[0-9A-Fa-f]{2}', file_path):
        return file_path
    try:
        decoded = urllib.parse.unquote(file_path)
        if re.search(r'%[0-9A-Fa-f]{2}', decoded):
            decoded = urllib.parse.unquote(decoded)
        return decoded
    except Exception as e:
        logger.warning(f"Failed to decode file path '{file_path}': {e}")
        return file_path


def normalize_path(path: str) -> str:
    """标准化路径，处理不同操作系统的路径分隔符。"""
    if not path:
        return path
    normalized = path.replace('\\', '/').replace('//', '/')
    if len(normalized) >= 2 and normalized[1] == ':':
        normalized = normalized[0] + ':' + normalized[2:]
    return os.path.normpath(normalized)


def resolve_file_path(file_path: str) -> str:
    """智能解析文件路径，处理 aria2 返回解码路径但文件名实际是 URL 编码的情况。"""
    if not file_path:
        return file_path
    if os.path.exists(file_path):
        return file_path
    norm_path = os.path.normpath(file_path)
    if os.path.exists(norm_path):
        return norm_path
    dir_path = os.path.dirname(norm_path)
    filename = os.path.basename(norm_path)
    if os.path.exists(dir_path):
        try:
            for actual_filename in os.listdir(dir_path):
                if actual_filename.endswith('.aria2'):
                    continue
                actual_decoded = decode_file_path(actual_filename)
                if actual_decoded.lower() == filename.lower():
                    actual_path = os.path.join(dir_path, actual_filename)
                    logger.debug(f"Resolved file path: {file_path} -> {actual_path}")
                    return actual_path
                if actual_filename == filename:
                    actual_path = os.path.join(dir_path, actual_filename)
                    return actual_path
        except Exception as e:
            logger.warning(f"Error resolving file path in directory {dir_path}: {e}")
    try:
        dir_path = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        encoded_filename = urllib.parse.quote(filename, safe=':/\\.+_-')
        encoded_path = os.path.join(dir_path, encoded_filename)
        if os.path.exists(encoded_path):
            logger.debug(f"Found file with encoded name: {encoded_path}")
            return encoded_path
    except Exception:
        pass
    logger.warning(f"Could not resolve file path: {file_path}")
    return file_path


class DownloaderMonitor(ABC):
    """Abstract base class for downloader monitors."""

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @abstractmethod
    def start(self):
        ...

    @abstractmethod
    def stop(self):
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...