import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any

from watchdog.events import FileSystemEventHandler

from .renamer import VideoRenamer
from .tmdb_client import TMDBClient
from ..utils.logging_utils import get_logger, log_success, log_failure, log_exception


class VideoFileHandler(FileSystemEventHandler):
    """
    视频文件处理器，用于处理文件系统事件
    """
    
    def __init__(self,
                 output_dir: str,
                 supported_extensions: List[str],
                 naming_rules: Optional[Dict[str, str]] = None,
                 tmdb_config: Optional[Dict[str, Any]] = None):
        """
        初始化视频文件处理器
        
        Args:
            output_dir: 输出目录
            supported_extensions: 支持的文件扩展名列表
            naming_rules: 命名规则字典
            tmdb_config: TMDB配置字典
        """
        # 初始化日志记录器
        self.logger = get_logger(__name__)
        
        self.output_dir = output_dir
        self.supported_extensions = supported_extensions
        
        # 初始化TMDB客户端
        tmdb_client = None
        if tmdb_config and tmdb_config.get('api_key'):
            try:
                tmdb_client = TMDBClient(
                    api_key=tmdb_config['api_key'],
                    retry_count=tmdb_config.get('retry_count', 3),
                    timeout=tmdb_config.get('timeout', 30)
                )
                self.logger.info("TMDB客户端初始化成功")
            except Exception as e:
                log_failure(self.logger, "初始化TMDB客户端失败", error=e)
        
        # 初始化文件重命名器
        try:
            # 从配置中获取TMDB API密钥
            tmdb_api_key = tmdb_config.get('api_key') if tmdb_config else None
            self.renamer = VideoRenamer(
                tmdb_api_key=tmdb_api_key,
                naming_rules=naming_rules
            )
            self.logger.info("视频重命名器初始化成功")
        except Exception as e:
            log_exception(self.logger, "初始化视频重命名器失败")
            # 创建一个基本的重命名器作为后备
            self.renamer = VideoRenamer(tmdb_api_key=None)
        
        # 父监控器引用
        self._parent_monitor = None
        
        # 处理中的文件，用于跟踪文件写入完成状态
        self._processing_files = set()
        
    def on_created(self, event):
        """
        当文件创建时被调用
        
        Args:
            event: 文件系统事件
        """
        if event.is_directory:
            return
        
        file_path = event.src_path
        if self._is_supported_file(file_path):
            # 检查是否是处理中的文件（避免重复处理）
            if file_path in self._processing_files:
                self.logger.debug(f"文件已在处理队列中: {file_path}")
                return
            
            self._processing_files.add(file_path)
            try:
                # 检查文件是否完整写入
                if self._is_file_complete(file_path):
                    self._process_file(file_path)
                else:
                    # 如果文件未完整写入，设置一个延迟处理
                    self.logger.debug(f"文件尚未完成写入，稍后处理: {file_path}")
                    # 在监控器的下一个轮询周期处理
                    if self._parent_monitor:
                        self._parent_monitor._pending_files.add(file_path)
            finally:
                # 无论处理结果如何，从处理队列中移除
                self._processing_files.discard(file_path)
    
    def on_modified(self, event):
        """
        当文件修改时被调用
        
        Args:
            event: 文件系统事件
        """
        if event.is_directory:
            return
        
        file_path = event.src_path
        if self._is_supported_file(file_path):
            # 对于修改事件，检查文件是否已完成写入
            if not file_path in self._processing_files and self._is_file_complete(file_path):
                self._process_file(file_path)
    
    def _is_supported_file(self, file_path: str) -> bool:
        """
        检查文件是否为支持的视频文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            是否为支持的视频文件
        """
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            return file_ext in self.supported_extensions
        except Exception as e:
            self.logger.error(f"检查文件类型时出错: {file_path}, 错误: {e}")
            return False
    
    def _is_file_complete(self, file_path: str) -> bool:
        """
        检查文件是否已完成写入
        
        Args:
            file_path: 文件路径
        
        Returns:
            文件是否完整
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return False
            
            # 获取文件初始大小
            initial_size = os.path.getsize(file_path)
            
            # 检查文件大小是否为0
            if initial_size == 0:
                return False
            
            # 等待一小段时间，检查文件大小是否变化
            import time
            time.sleep(0.1)  # 等待100ms
            
            # 再次获取文件大小
            current_size = os.path.getsize(file_path)
            
            # 如果文件大小没有变化，认为文件已完成写入
            return initial_size == current_size
        except Exception as e:
            self.logger.error(f"检查文件完整性时出错: {file_path}, 错误: {e}")
            return False
    
    def _process_file(self, file_path: str) -> None:
        """
        处理视频文件
        
        Args:
            file_path: 文件路径
        """
        if not os.path.exists(file_path):
            self.logger.warning(f"文件不存在: {file_path}")
            return
        
        try:
            # 提取元数据
            metadata = self.renamer.extract_metadata(file_path)
            
            # 生成新路径，传递output_dir参数以启用文件冲突检测
            new_path = self.renamer.generate_new_path(metadata, original_path=file_path, output_dir=self.output_dir)
            
            if new_path:
                log_success(self.logger, "文件处理成功", {
                    "original_path": file_path,
                    "new_path": str(new_path)
                })
            else:
                log_failure(self.logger, f"处理文件失败: {file_path}")
                
        except KeyboardInterrupt:
            # 让键盘中断正常传播
            raise
        except Exception as e:
            log_exception(self.logger, f"处理文件时发生错误: {file_path}")
            
            # 如果有父监控器，可以将文件添加到重试队列
            if self._parent_monitor:
                self.logger.info(f"将文件添加到重试队列: {file_path}")
                self._parent_monitor._retry_files.add(file_path)
    
    def force_process_file(self, file_path: str) -> bool:
        """
        强制处理文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            是否处理成功
        """
        try:
            if not os.path.exists(file_path):
                log_failure(self.logger, f"文件不存在: {file_path}")
                return False
        except Exception as e:
            log_failure(self.logger, f"检查文件是否存在时出错: {file_path}", error=e)
            return False
        
        if not self._is_supported_file(file_path):
            log_failure(self.logger, f"不支持的文件类型: {file_path}")
            return False
        
        try:
            # 提取元数据
            metadata = self.renamer.extract_metadata(file_path)
            
            # 生成新路径，传递output_dir参数以启用文件冲突检测
            new_path = self.renamer.generate_new_path(metadata, original_path=file_path, output_dir=self.output_dir)
            
            if new_path:
                log_success(self.logger, "文件强制处理成功", {
                    "original_path": file_path,
                    "new_path": str(new_path)
                })
                return True
            else:
                log_failure(self.logger, f"强制处理文件失败: {file_path}")
                return False
                
        except Exception as e:
            log_exception(self.logger, f"强制处理文件时发生错误: {file_path}")
            return False