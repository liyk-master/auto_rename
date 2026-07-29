"""下载器监控工厂"""

import logging
from typing import Callable, Dict, Optional

from .base import DownloaderMonitor
from .aria2_monitor import Aria2Monitor
from .qbittorrent_monitor import QBittorrentMonitor

logger = logging.getLogger(__name__)


class DownloaderMonitorFactory:
    """
    Factory class for creating downloader monitors.
    """

    @staticmethod
    def create_monitor(
        downloader_type: str, callback: Callable[[str], None], config: dict
    ) -> Optional[DownloaderMonitor]:
        """
        Create a downloader monitor based on the given type.

        Args:
            downloader_type: Type of downloader ("aria2" or "qbittorrent").
            callback: Callback function to call when a download is completed.
            config: Configuration dictionary for the downloader.

        Returns:
            Optional[DownloaderMonitor]: Created downloader monitor or None if type is not supported.
        """
        if downloader_type == "aria2":
            # 解析路径映射配置
            path_mappings = DownloaderMonitorFactory._parse_path_mappings(
                config.get("path_mappings", {})
            )
            rpc_url = config.get("rpc_url")
            if not rpc_url:
                host = config.get("host", "localhost")
                port = config.get("port", "6800")
                rpc_url = f"http://{host}:{port}/jsonrpc"
            
            return Aria2Monitor(
                callback,
                rpc_url=rpc_url,
                secret=config.get("secret") or config.get("password"),
                supported_extensions=config.get(
                    "supported_extensions",
                    (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"),
                ),
                monitor_mode=config.get("monitor_mode", "polling"),
                path_mappings=path_mappings,
                websocket_reconnect_delay=config.get("websocket_reconnect_delay", 5),
            )
        elif downloader_type == "qbittorrent":
            # qBittorrent 也支持路径映射
            path_mappings = DownloaderMonitorFactory._parse_path_mappings(
                config.get("path_mappings", {})
            )
            rpc_url = config.get("rpc_url")
            if not rpc_url:
                host = config.get("host", "localhost")
                port = config.get("port", "8080")
                rpc_url = f"http://{host}:{port}/api/v2"
            
            monitor = QBittorrentMonitor(
                callback,
                rpc_url=rpc_url,
                username=config.get("username", "admin"),
                password=config.get("password", "adminadmin"),
                supported_extensions=config.get(
                    "supported_extensions",
                    (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"),
                ),
            )
            # 设置路径映射
            monitor.path_mappings = path_mappings
            return monitor
        else:
            logger.error(f"Unsupported downloader type: {downloader_type}")
            return None
    
    @staticmethod
    def _parse_path_mappings(mappings_config) -> Dict[str, str]:
        """
        解析路径映射配置
        
        支持多种配置格式：
        1. 字典格式: {"/downloads": "F:/Downloads"}
        2. 字符串格式: "/downloads:/root/downloads" (旧格式兼容)
        3. 列表格式: ["/downloads:F:/Downloads", "/data:/mnt/data"]
        
        Args:
            mappings_config: 路径映射配置
            
        Returns:
            Dict[str, str]: 解析后的路径映射字典
        """
        if isinstance(mappings_config, dict):
            return mappings_config
        
        if isinstance(mappings_config, str) and mappings_config.strip():
            # 旧格式: "/downloads:/root/downloads"
            parts = mappings_config.split(":", 1)
            if len(parts) == 2:
                return {parts[0].strip(): parts[1].strip()}
        
        if isinstance(mappings_config, list):
            result = {}
            for item in mappings_config:
                if isinstance(item, str) and ":" in item:
                    parts = item.split(":", 1)
                    if len(parts) == 2:
                        result[parts[0].strip()] = parts[1].strip()
            return result
        
        return {}
