"""
下载器监控路由

提供下载器状态和任务管理的 API。
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.state import get_state_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class DownloaderInfo(BaseModel):
    """下载器信息"""
    name: str
    type: str  # aria2, qbittorrent
    connected: bool
    status: Optional[str] = None


class DownloaderListResponse(BaseModel):
    """下载器列表响应"""
    success: bool
    downloaders: List[DownloaderInfo]


class DownloaderTask(BaseModel):
    """下载器任务"""
    id: str
    name: str
    status: str
    progress: float
    size: int
    downloaded: int
    upload_speed: int
    download_speed: int
    files: List[str]


class TaskListResponse(BaseModel):
    """任务列表响应"""
    success: bool
    downloader: str
    tasks: List[DownloaderTask]


class TaskOperationResponse(BaseModel):
    """任务操作响应"""
    success: bool
    message: str
    task_id: Optional[str] = None


@router.get("", response_model=DownloaderListResponse)
async def list_downloaders():
    """
    获取下载器列表
    
    返回已配置的下载器及其连接状态。
    """
    try:
        state = get_state_manager()
        monitors = state.get_downloader_monitors()
        
        downloaders = []
        for monitor in monitors:
            info = DownloaderInfo(
                name=getattr(monitor, "name", "Unknown"),
                type=monitor.__class__.__name__.replace("Monitor", "").lower(),
                connected=False,
            )
            
            # 检查连接状态
            if hasattr(monitor, "is_connected"):
                try:
                    info.connected = monitor.is_connected()
                    info.status = "connected" if info.connected else "disconnected"
                except Exception as e:
                    info.status = f"error: {e}"
            
            downloaders.append(info)
        
        return DownloaderListResponse(
            success=True,
            downloaders=downloaders,
        )
        
    except Exception as e:
        logger.error(f"获取下载器列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取下载器列表失败: {e}")


@router.get("/{downloader_type}/status")
async def get_downloader_status(downloader_type: str):
    """
    获取指定下载器状态
    
    Args:
        downloader_type: 下载器类型（aria2, qbittorrent）
    """
    try:
        state = get_state_manager()
        monitors = state.get_downloader_monitors()
        
        monitor = None
        for m in monitors:
            m_type = m.__class__.__name__.replace("Monitor", "").lower()
            if m_type == downloader_type.lower():
                monitor = m
                break
        
        if monitor is None:
            raise HTTPException(status_code=404, detail=f"下载器不存在: {downloader_type}")
        
        # 获取状态
        status = {
            "type": downloader_type,
            "connected": False,
        }
        
        if hasattr(monitor, "is_connected"):
            try:
                status["connected"] = monitor.is_connected()
            except Exception as e:
                status["error"] = str(e)
        
        # 获取详细信息
        if hasattr(monitor, "get_status"):
            try:
                status["details"] = monitor.get_status()
            except Exception as e:
                status["details_error"] = str(e)
        
        return {"success": True, "status": status}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取下载器状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取下载器状态失败: {e}")


@router.get("/{downloader_type}/tasks")
async def get_downloader_tasks(downloader_type: str):
    """
    获取下载器任务列表
    
    Args:
        downloader_type: 下载器类型（aria2, qbittorrent）
    """
    try:
        state = get_state_manager()
        monitors = state.get_downloader_monitors()
        
        monitor = None
        for m in monitors:
            m_type = m.__class__.__name__.replace("Monitor", "").lower()
            if m_type == downloader_type.lower():
                monitor = m
                break
        
        if monitor is None:
            raise HTTPException(status_code=404, detail=f"下载器不存在: {downloader_type}")
        
        # 获取任务列表
        tasks = []
        
        if hasattr(monitor, "get_tasks"):
            try:
                raw_tasks = monitor.get_tasks()
                for task in raw_tasks:
                    tasks.append(DownloaderTask(
                        id=str(task.get("id", task.get("hash", "unknown"))),
                        name=task.get("name", task.get("fileName", "Unknown")),
                        status=task.get("status", "unknown"),
                        progress=task.get("progress", 0) * 100,
                        size=task.get("totalLength", task.get("size", 0)),
                        downloaded=task.get("completedLength", task.get("downloaded", 0)),
                        upload_speed=task.get("uploadSpeed", 0),
                        download_speed=task.get("downloadSpeed", 0),
                        files=task.get("files", []),
                    ))
            except Exception as e:
                logger.warning(f"获取任务列表失败: {e}")
        
        return {
            "success": True,
            "downloader": downloader_type,
            "tasks": tasks,
            "count": len(tasks),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取下载器任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取下载器任务失败: {e}")


@router.post("/{downloader_type}/remove")
async def remove_downloader_task(downloader_type: str, file_path: str, force: bool = False):
    """
    删除下载器任务
    
    Args:
        downloader_type: 下载器类型
        file_path: 文件路径
        force: 是否强制删除（包括文件）
    """
    try:
        state = get_state_manager()
        monitors = state.get_downloader_monitors()
        
        monitor = None
        for m in monitors:
            m_type = m.__class__.__name__.replace("Monitor", "").lower()
            if m_type == downloader_type.lower():
                monitor = m
                break
        
        if monitor is None:
            raise HTTPException(status_code=404, detail=f"下载器不存在: {downloader_type}")
        
        # 执行删除
        if force and hasattr(monitor, "force_remove_download"):
            monitor.force_remove_download(file_path)
            message = f"已强制删除任务及文件: {file_path}"
        elif hasattr(monitor, "remove_download"):
            monitor.remove_download(file_path)
            message = f"已删除任务: {file_path}"
        else:
            raise HTTPException(status_code=501, detail="该下载器不支持删除操作")
        
        logger.info(message)
        
        return TaskOperationResponse(
            success=True,
            message=message,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除下载器任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除下载器任务失败: {e}")


@router.post("/{downloader_type}/pause")
async def pause_downloader_task(downloader_type: str, file_path: str):
    """
    暂停下载器任务
    
    Args:
        downloader_type: 下载器类型
        file_path: 文件路径
    """
    try:
        state = get_state_manager()
        monitors = state.get_downloader_monitors()
        
        monitor = None
        for m in monitors:
            m_type = m.__class__.__name__.replace("Monitor", "").lower()
            if m_type == downloader_type.lower():
                monitor = m
                break
        
        if monitor is None:
            raise HTTPException(status_code=404, detail=f"下载器不存在: {downloader_type}")
        
        # 执行暂停
        if hasattr(monitor, "pause_torrent_for_file"):
            monitor.pause_torrent_for_file(file_path)
            message = f"已暂停任务: {file_path}"
        else:
            raise HTTPException(status_code=501, detail="该下载器不支持暂停操作")
        
        logger.info(message)
        
        return TaskOperationResponse(
            success=True,
            message=message,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停下载器任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"暂停下载器任务失败: {e}")


@router.post("/{downloader_type}/resume")
async def resume_downloader_task(downloader_type: str, file_path: str):
    """
    恢复下载器任务
    
    Args:
        downloader_type: 下载器类型
        file_path: 文件路径
    """
    try:
        state = get_state_manager()
        monitors = state.get_downloader_monitors()
        
        monitor = None
        for m in monitors:
            m_type = m.__class__.__name__.replace("Monitor", "").lower()
            if m_type == downloader_type.lower():
                monitor = m
                break
        
        if monitor is None:
            raise HTTPException(status_code=404, detail=f"下载器不存在: {downloader_type}")
        
        # 执行恢复
        if hasattr(monitor, "resume_torrent_for_file"):
            monitor.resume_torrent_for_file(file_path)
            message = f"已恢复任务: {file_path}"
        else:
            raise HTTPException(status_code=501, detail="该下载器不支持恢复操作")
        
        logger.info(message)
        
        return TaskOperationResponse(
            success=True,
            message=message,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复下载器任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"恢复下载器任务失败: {e}")


@router.get("/{downloader_type}/processed")
async def get_processed_files(downloader_type: str):
    """
    获取已处理的文件列表
    
    返回该下载器已处理过的文件记录。
    
    Args:
        downloader_type: 下载器类型
    """
    try:
        state = get_state_manager()
        monitors = state.get_downloader_monitors()
        
        monitor = None
        for m in monitors:
            m_type = m.__class__.__name__.replace("Monitor", "").lower()
            if m_type == downloader_type.lower():
                monitor = m
                break
        
        if monitor is None:
            raise HTTPException(status_code=404, detail=f"下载器不存在: {downloader_type}")
        
        # 获取已处理文件
        processed = []
        if hasattr(monitor, "_processed_files"):
            processed = list(monitor._processed_files)
        
        return {
            "success": True,
            "downloader": downloader_type,
            "files": processed,
            "count": len(processed),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取已处理文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取已处理文件失败: {e}")
