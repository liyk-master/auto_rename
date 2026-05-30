"""
状态管理服务

管理 VideoFileHandler 实例和全局状态，
为 Web API 提供统一的状态访问接口。
"""

import threading
import logging
import asyncio
from typing import Any, Dict, List, Optional, Set, Callable
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

from ...database.operations import get_completed_tasks as db_get_completed
from ...database.operations import get_failed_tasks as db_get_failed


@dataclass
class TaskInfo:
    """任务信息"""
    file_path: str
    status: str  # queued, processing, uploading, completed, failed
    error_message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@dataclass
class UploadProgress:
    """上传进度"""
    file_path: str
    filename: str
    uploader: str  # cloud189, yun139, p123, emos
    progress: float  # 0-100
    uploaded_bytes: int
    total_bytes: int
    speed: str  # 如 "5.2 MB/s"
    status: str  # uploading, completed, failed
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    last_update: Optional[datetime] = None


@dataclass
class SystemStatus:
    """系统状态"""
    queue_size: int = 0
    processing_count: int = 0
    uploading_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    is_running: bool = False
    last_update: Optional[datetime] = None


class StateManager:
    """
    状态管理器（单例模式）
    
    管理 VideoFileHandler 实例和全局状态，
    为 Web API 提供统一的状态访问接口。
    """
    
    _instance: Optional["StateManager"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "StateManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._logger = logging.getLogger(__name__)
        
        # VideoFileHandler 引用
        self._video_handler: Any = None
        self._config: Dict[str, Any] = {}
        self._config_path: Optional[Path] = None
        
        # 下载器监控器列表
        self._downloader_monitors: List[Any] = []
        
        # 系统运行状态
        self._system_running: bool = False
        
        # 任务历史记录（最近 1000 条）
        self._task_history: List[TaskInfo] = []
        self._max_history: int = 1000
        
        # 上传进度追踪
        self._upload_progress: Dict[str, UploadProgress] = {}  # file_path -> UploadProgress
        self._progress_callbacks: List[Callable] = []  # 进度更新回调列表
        
        # 状态锁
        self._state_lock = threading.Lock()
    
    def set_video_handler(self, handler: Any) -> None:
        """设置 VideoFileHandler 实例"""
        with self._state_lock:
            self._video_handler = handler
            self._logger.info("VideoHandler 实例已设置")
    
    def get_video_handler(self) -> Optional[Any]:
        """获取 VideoFileHandler 实例"""
        return self._video_handler
    
    def set_config(self, config: Dict[str, Any], config_path: Optional[Path] = None) -> None:
        """设置配置"""
        with self._state_lock:
            self._config = config
            self._config_path = config_path
    
    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        return self._config.copy()
    
    def get_config_path(self) -> Optional[Path]:
        """获取配置文件路径"""
        return self._config_path
    
    def set_downloader_monitors(self, monitors: List[Any]) -> None:
        """设置下载器监控器列表"""
        with self._state_lock:
            self._downloader_monitors = monitors
    
    def get_downloader_monitors(self) -> List[Any]:
        """获取下载器监控器列表"""
        return self._downloader_monitors.copy()
    
    def set_system_running(self, running: bool) -> None:
        """设置系统运行状态"""
        self._system_running = running
    
    def is_system_running(self) -> bool:
        """获取系统运行状态"""
        return self._system_running
    
    def get_system_status(self) -> SystemStatus:
        """获取系统状态"""
        status = SystemStatus(
            is_running=self._system_running,
            last_update=datetime.now()
        )
        
        if self._video_handler is None:
            return status
        
        try:
            handler = self._video_handler
            
            # 获取队列状态
            if hasattr(handler, "_upload_queue"):
                status.queue_size = handler._upload_queue.qsize()
            
            # 获取处理状态
            if hasattr(handler, "_processing_files"):
                status.processing_count = len(handler._processing_files)
            
            if hasattr(handler, "_uploading_files"):
                status.uploading_count = len(handler._uploading_files)
            
            if hasattr(handler, "_uploaded_files"):
                status.completed_count = len(handler._uploaded_files)
            
            if hasattr(handler, "_failed_files"):
                status.failed_count = len(handler._failed_files)
                
        except Exception as e:
            self._logger.error(f"获取系统状态失败: {e}")
        
        return status
    
    def get_queued_files(self) -> List[str]:
        """获取队列中的文件列表"""
        if self._video_handler is None:
            return []
        
        try:
            handler = self._video_handler
            if hasattr(handler, "_queued_files"):
                return list(handler._queued_files)
        except Exception as e:
            self._logger.error(f"获取队列文件失败: {e}")
        
        return []
    
    def get_processing_files(self) -> List[str]:
        """获取正在处理的文件列表"""
        if self._video_handler is None:
            return []
        
        try:
            handler = self._video_handler
            if hasattr(handler, "_processing_files"):
                return list(handler._processing_files)
        except Exception as e:
            self._logger.error(f"获取处理中文件失败: {e}")
        
        return []
    
    def get_uploading_files(self) -> List[str]:
        """获取正在上传的文件列表"""
        if self._video_handler is None:
            return []
        
        try:
            handler = self._video_handler
            if hasattr(handler, "_uploading_files"):
                return list(handler._uploading_files)
        except Exception as e:
            self._logger.error(f"获取上传中文件失败: {e}")
        
        return []
    
    def get_completed_files(self) -> List[str]:
        """获取已完成的文件列表"""
        if self._video_handler is None:
            return []
        
        try:
            handler = self._video_handler
            if hasattr(handler, "_uploaded_files"):
                return list(handler._uploaded_files)
        except Exception as e:
            self._logger.error(f"获取已完成文件失败: {e}")
        
        return []
    
    def get_failed_files(self) -> Dict[str, str]:
        """获取失败的文件及错误信息"""
        if self._video_handler is None:
            return {}
        
        try:
            handler = self._video_handler
            if hasattr(handler, "_failed_files"):
                return dict(handler._failed_files)
        except Exception as e:
            self._logger.error(f"获取失败文件失败: {e}")
        
        return {}
    
    def get_completed_with_time(self) -> List[Dict]:
        """
        获取已完成的文件列表（含时间戳）
        
        合并内存状态和数据库记录，返回带完成时间的列表。
        """
        seen = {}
        # 数据库记录优先（有时间戳）
        try:
            db_items = db_get_completed(limit=500)
            for item in db_items:
                seen[item["path"]] = item["time"]
        except Exception:
            pass
        # 内存状态补充（实时数据）
        try:
            if self._video_handler and hasattr(self._video_handler, "_uploaded_files"):
                for p in list(self._video_handler._uploaded_files)[-500:]:
                    if p not in seen:
                        seen[p] = None
        except Exception:
            pass
        # 按时间倒序
        result = [{"path": p, "time": t} for p, t in seen.items()]
        result.sort(key=lambda x: x["time"] or "", reverse=True)
        return result[:200]
    
    def get_failed_with_time(self) -> Dict[str, Dict]:
        """
        获取失败的文件列表（含时间戳）
        
        Returns:
            {path: {"error": str, "time": str or None}, ...}
        """
        result = {}
        # 数据库记录优先（有时间戳）
        try:
            db_items = db_get_failed(limit=500)
            for key, val in db_items.items():
                result[key] = val
        except Exception:
            pass
        # 内存状态补充（实时数据/自动重试中的文件）
        try:
            if self._video_handler and hasattr(self._video_handler, "_failed_files"):
                handler_failed = self._video_handler._failed_files
                for p, err in handler_failed.items():
                    if p not in result:
                        result[p] = {"error": err, "time": None}
        except Exception:
            pass
        return dict(list(result.items())[:200])
    
    def add_task_history(self, task: TaskInfo) -> None:
        """添加任务历史记录"""
        with self._state_lock:
            self._task_history.append(task)
            if len(self._task_history) > self._max_history:
                self._task_history = self._task_history[-self._max_history:]
    
    def get_task_history(self, limit: int = 100) -> List[TaskInfo]:
        """获取任务历史记录"""
        return self._task_history[-limit:]
    
    # ========== 上传进度管理 ==========
    
    def register_progress_callback(self, callback: Callable) -> None:
        """注册进度更新回调"""
        with self._state_lock:
            self._progress_callbacks.append(callback)
    
    def unregister_progress_callback(self, callback: Callable) -> None:
        """注销进度更新回调"""
        with self._state_lock:
            if callback in self._progress_callbacks:
                self._progress_callbacks.remove(callback)
    
    def update_upload_progress(self, progress: UploadProgress) -> None:
        """
        更新上传进度
        
        Args:
            progress: 上传进度对象
        """
        with self._state_lock:
            self._upload_progress[progress.file_path] = progress
            
            # 调用所有回调
            for callback in self._progress_callbacks:
                try:
                    callback(progress)
                except Exception as e:
                    self._logger.error(f"进度回调执行失败: {e}")
    
    def get_upload_progress(self, file_path: str) -> Optional[UploadProgress]:
        """获取指定文件的上传进度"""
        return self._upload_progress.get(file_path)
    
    def get_all_upload_progress(self) -> Dict[str, UploadProgress]:
        """获取所有上传进度"""
        return self._upload_progress.copy()
    
    def clear_upload_progress(self, file_path: str) -> None:
        """清除指定文件的上传进度"""
        with self._state_lock:
            if file_path in self._upload_progress:
                del self._upload_progress[file_path]


def get_state_manager() -> StateManager:
    """获取状态管理器单例"""
    return StateManager()


# ========== 全局进度更新函数（供上传器调用） ==========

def report_upload_progress(
    file_path: str,
    filename: str,
    uploader: str,
    progress: float,
    uploaded_bytes: int,
    total_bytes: int,
    speed: str = "",
    status: str = "uploading",
    error: Optional[str] = None,
):
    """
    报告上传进度（全局函数，供上传器调用）
    
    Args:
        file_path: 文件路径
        filename: 文件名
        uploader: 上传器名称 (cloud189, yun139, p123, emos)
        progress: 进度百分比 (0-100)
        uploaded_bytes: 已上传字节数
        total_bytes: 总字节数
        speed: 上传速度字符串
        status: 状态 (uploading, completed, failed)
        error: 错误信息（如果失败）
    """
    state = get_state_manager()
    progress_obj = UploadProgress(
        file_path=file_path,
        filename=filename,
        uploader=uploader,
        progress=progress,
        uploaded_bytes=uploaded_bytes,
        total_bytes=total_bytes,
        speed=speed,
        status=status,
        error=error,
        start_time=datetime.now() if progress == 0 else None,
        last_update=datetime.now(),
    )
    state.update_upload_progress(progress_obj)
