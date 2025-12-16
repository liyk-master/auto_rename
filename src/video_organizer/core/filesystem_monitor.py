"""
File system monitoring module.
"""

import logging
import os
import time
import threading
from pathlib import Path
from threading import Event
from typing import Dict, Optional, List

# 导入更新后的VideoFileHandler
from .video_file_handler import VideoFileHandler
from .downloader_monitor import DownloaderMonitorFactory

logger = logging.getLogger(__name__)


class FileSystemMonitor:
    """Monitor downloaders for completed video files and process them."""
    
    def __init__(self, watch_path, processed_path, tmdb_api_key, 
                 ai_service_url=None, supported_extensions=None, use_polling=False, polling_interval=5, naming_rules=None, emos_config=None, processing_config=None, downloader_configs=None, config=None):
        self.watch_path = Path(watch_path)
        self.processed_path = Path(processed_path)
        self.tmdb_api_key = tmdb_api_key
        self.ai_service_url = ai_service_url
        self.config = config  # 保存配置对象，用于路径映射等功能
        self.processed_files = set()  # 存储已处理文件的集合，避免重复处理
        self._processing_lock = threading.Lock()  # 线程锁，保护文件处理逻辑
        self._retry_files = set()  # 需要重试的文件
        self._pending_files = set()  # 待处理的文件
        
        if supported_extensions is None:
            self.supported_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.strm']
        else:
            self.supported_extensions = supported_extensions
            
        self.stop_event = Event()
        
        # 初始化下载器监控器
        self.downloader_monitors = []
        self.downloader_configs = downloader_configs or []
        
        # 准备tmdb_config字典
        tmdb_config = {
            'api_key': tmdb_api_key,
            'retry_count': 3,
            'timeout': 30
        }
        
        # 初始化更新后的VideoFileHandler
        self.event_handler = VideoFileHandler(
            output_dir=str(self.processed_path),
            supported_extensions=self.supported_extensions,
            naming_rules=naming_rules,
            tmdb_config=tmdb_config,
            emos_config=emos_config,
            processing_config=processing_config,
            path_mappings=self.config.get('monitoring', {}).get('path_mappings') if self.config else None,
            telegram_config=self.config.get('telegram') if self.config else None
        )
        self.event_handler._parent_monitor = self  # 设置父监控器引用
        
        # 初始化下载器监控器
        self._init_downloader_monitors()
    
    def _init_downloader_monitors(self):
        """
        Initialize downloader monitors based on the provided configs.
        """
        if not self.downloader_configs:
            logger.warning("没有配置下载器，下载器监控功能将不可用")
            return
        
        for config in self.downloader_configs:
            downloader_type = config.get("type")
            if not downloader_type:
                logger.error("Downloader config missing 'type' field, skipping")
                continue
            
            # 将 supported_extensions 添加到配置中
            config_with_extensions = config.copy()
            config_with_extensions["supported_extensions"] = tuple(self.supported_extensions)
            
            monitor = DownloaderMonitorFactory.create_monitor(
                downloader_type,
                self._on_download_completed,
                config_with_extensions
            )
            
            if monitor:
                self.downloader_monitors.append(monitor)
                logger.info(f"Initialized {downloader_type} monitor")
    
    def _on_download_completed(self, file_path: str, downloader_monitor=None):
        """
        Callback function to handle download completion events from downloaders.
        
        Args:
            file_path: Path to the completed download file.
        """
        logger.info(f"Received download completion event for: {file_path}")
        
        # 保存文件到下载器的映射关系
        if downloader_monitor and hasattr(self.event_handler, '_file_downloader_map'):
            # 先应用路径映射
            mapped_file_path = self._apply_path_mapping(file_path)
            self.event_handler._file_downloader_map[str(Path(mapped_file_path))] = downloader_monitor
        
        # 应用路径映射，将下载器返回的路径转换为主机实际路径
        mapped_file_path = self._apply_path_mapping(file_path)
        logger.debug(f"Mapped file path from {file_path} to {mapped_file_path}")
        
        # 检查文件是否是支持的视频文件
        if Path(mapped_file_path).suffix.lower() in self.supported_extensions:
            file_path_str = str(Path(mapped_file_path))
            
            # 使用锁保护检查和添加操作，防止竞态条件
            with self._processing_lock:
                if (file_path_str in self.processed_files or 
                    file_path_str in self.event_handler._uploading_files or 
                    file_path_str in self.event_handler._uploaded_files):
                    logger.debug(f"File already processed or uploading: {mapped_file_path}")
                    return
                
                # 检查文件是否存在
                if not os.path.exists(mapped_file_path):
                    logger.warning(f"Mapped file does not exist (skipping and marking as processed): {mapped_file_path}")
                    self.processed_files.add(file_path_str)
                    return
                
                # 标记为已处理，防止重复
                self.processed_files.add(file_path_str)
            
            # 在锁外启动线程，避免阻塞
            logger.info(f"Processing completed download: {mapped_file_path}")
            threading.Thread(target=self.event_handler._process_file, args=(file_path_str,)).start()
        else:
            logger.debug(f"File is not a supported video type: {mapped_file_path}")
    
    def _apply_path_mapping(self, file_path: str) -> str:
        """
        将下载器返回的路径应用路径映射，转换为主机实际路径
        
        Args:
            file_path: 下载器返回的原始路径
        
        Returns:
            str: 转换后的主机实际路径
        """
        # 从配置中获取路径映射
        path_mappings = self.config.get('monitoring', {}).get('path_mappings', {}) if hasattr(self, 'config') else {}
        
        # 遍历所有映射规则，找到最长匹配的前缀
        longest_match = ""
        for prefix, target in path_mappings.items():
            if file_path.startswith(prefix) and len(prefix) > len(longest_match):
                longest_match = prefix
        
        # 如果找到匹配的映射规则，则应用映射
        if longest_match:
            mapped_path = file_path.replace(longest_match, path_mappings[longest_match], 1)
            # 确保路径分隔符正确
            mapped_path = mapped_path.replace('/', os.path.sep)
            return mapped_path
        
        # 如果没有找到匹配的映射规则，则返回原始路径
        return file_path
    
    def start(self):
        """
        Start monitoring downloaders for completed downloads.
        """
        # 启动下载器监控器
        for monitor in self.downloader_monitors:
            monitor.start()
        
        logger.info(f"Started downloader monitoring (No filesystem monitoring enabled)")
        
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop monitoring."""
        # 停止下载器监控器
        for monitor in self.downloader_monitors:
            monitor.stop()
            
        self.stop_event.set()
        logger.info("Stopped monitoring")
    
    def force_process_file(self, file_path):
        """
        强制处理指定的文件，无论其是否已被处理过。
        """
        file_path = Path(file_path)
        if file_path.exists() and file_path.suffix.lower() in self.supported_extensions:
            logger.info(f"Force processing file: {file_path}")
            self.event_handler.force_process_file(str(file_path))
            self.processed_files.add(str(file_path))
            return True
        return False