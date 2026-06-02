"""
任务监控路由

提供任务队列状态监控 API。
"""

import logging
import asyncio
import threading
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

from ..services.state import get_state_manager
from ...database.operations import (
    get_tasks_paginated,
    get_recent_activity_paginated,
    delete_failed_task,
    delete_all_failed_tasks,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    queue_size: int
    processing_count: int
    uploading_count: int
    completed_count: int
    failed_count: int
    is_running: bool
    last_update: Optional[str] = None


class TaskListResponse(BaseModel):
    """任务列表响应"""
    success: bool
    count: int
    files: List[str]


class CompletedTaskItem(BaseModel):
    """已完成任务项"""
    path: str
    time: Optional[str] = None


class CompletedTaskListResponse(BaseModel):
    """已完成任务列表响应"""
    success: bool
    count: int
    files: List[CompletedTaskItem]


class FailedTaskItem(BaseModel):
    """失败任务项"""
    error: str
    time: Optional[str] = None


class FailedTaskListResponse(BaseModel):
    """失败任务列表响应"""
    success: bool
    count: int
    files: Dict[str, FailedTaskItem]  # path -> {error, time}


class RecentActivityItem(BaseModel):
    """最近活动项"""
    id: Optional[int] = None
    path: str
    status: str
    error: Optional[str] = None
    time: Optional[str] = None


class RecentActivityResponse(BaseModel):
    """最近活动响应"""
    success: bool
    items: List[RecentActivityItem]
    total: int = 0
    page: int = 1
    page_size: int = 20


class TaskListItem(BaseModel):
    """任务列表项"""
    id: int
    path: str
    status: str
    error: Optional[str] = None
    time: Optional[str] = None


class TaskListPaginatedResponse(BaseModel):
    """分页任务列表响应"""
    success: bool
    items: List[TaskListItem]
    total: int
    page: int
    page_size: int


class RetryRequest(BaseModel):
    """重试请求"""
    file_path: str


class UploadProgressResponse(BaseModel):
    """上传进度响应"""
    filename: str
    uploader: str
    progress: float
    uploaded_bytes: int
    total_bytes: int
    speed: str
    status: str
    error: Optional[str] = None


class AllProgressResponse(BaseModel):
    """所有上传进度响应"""
    success: bool
    count: int
    progress: Dict[str, UploadProgressResponse]


@router.get("/status", response_model=TaskStatusResponse)
async def get_task_status():
    """
    获取任务状态概览
    
    返回队列大小、处理中、上传中、已完成、失败的任务数量。
    """
    try:
        state = get_state_manager()
        status = state.get_system_status()
        
        return TaskStatusResponse(
            queue_size=status.queue_size,
            processing_count=status.processing_count,
            uploading_count=status.uploading_count,
            completed_count=status.completed_count,
            failed_count=status.failed_count,
            is_running=status.is_running,
            last_update=status.last_update.isoformat() if status.last_update else None,
        )
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {e}")


@router.get("/queued", response_model=TaskListResponse)
async def get_queued_tasks():
    """
    获取队列中的任务
    
    返回等待处理的文件列表。
    """
    try:
        state = get_state_manager()
        files = state.get_queued_files()
        
        return TaskListResponse(
            success=True,
            count=len(files),
            files=files,
        )
    except Exception as e:
        logger.error(f"获取队列任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取队列任务失败: {e}")


@router.get("/processing", response_model=TaskListResponse)
async def get_processing_tasks():
    """
    获取正在处理的任务
    
    返回当前正在处理的文件列表。
    """
    try:
        state = get_state_manager()
        files = state.get_processing_files()
        
        return TaskListResponse(
            success=True,
            count=len(files),
            files=files,
        )
    except Exception as e:
        logger.error(f"获取处理中任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取处理中任务失败: {e}")


@router.get("/uploading", response_model=TaskListResponse)
async def get_uploading_tasks():
    """
    获取正在上传的任务
    
    返回当前正在上传的文件列表。
    """
    try:
        state = get_state_manager()
        files = state.get_uploading_files()
        
        return TaskListResponse(
            success=True,
            count=len(files),
            files=files,
        )
    except Exception as e:
        logger.error(f"获取上传中任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取上传中任务失败: {e}")


@router.get("/completed", response_model=CompletedTaskListResponse)
async def get_completed_tasks():
    """
    获取已完成的任务
    
    返回已成功处理的文件及其完成时间。
    """
    try:
        state = get_state_manager()
        files = state.get_completed_with_time()
        
        return CompletedTaskListResponse(
            success=True,
            count=len(files),
            files=[CompletedTaskItem(**f) for f in files],
        )
    except Exception as e:
        logger.error(f"获取已完成任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取已完成任务失败: {e}")


@router.get("/failed", response_model=FailedTaskListResponse)
async def get_failed_tasks():
    """
    获取失败的任务
    
    返回处理失败的文件、错误信息及其时间。
    """
    try:
        state = get_state_manager()
        files = state.get_failed_with_time()
        
        return FailedTaskListResponse(
            success=True,
            count=len(files),
            files={p: FailedTaskItem(**v) for p, v in files.items()},
        )
    except Exception as e:
        logger.error(f"获取失败任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败任务失败: {e}")


@router.get("/recent", response_model=RecentActivityResponse)
async def get_recent_activity(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
):
    """
    获取最近活动（分页）
    
    返回最近的已完成和失败任务（含时间戳），用于仪表盘展示。
    """
    try:
        items, total = get_recent_activity_paginated(
            page=page,
            page_size=page_size,
            search=search,
        )
        return RecentActivityResponse(
            success=True,
            items=[RecentActivityItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"获取最近活动失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取最近活动失败: {e}")


@router.get("/list", response_model=TaskListPaginatedResponse)
async def get_task_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
):
    """
    获取分页任务列表，支持按状态过滤和搜索
    """
    try:
        offset = (page - 1) * page_size
        items, total = get_tasks_paginated(
            status=status,
            search=search,
            offset=offset,
            limit=page_size,
        )
        return TaskListPaginatedResponse(
            success=True,
            items=[TaskListItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {e}")


@router.get("/progress", response_model=AllProgressResponse)
async def get_upload_progress():
    """
    获取所有上传进度
    
    返回当前正在上传的文件进度。
    """
    try:
        state = get_state_manager()
        all_progress = state.get_all_upload_progress()
        
        progress_dict = {}
        for file_path, prog in all_progress.items():
            progress_dict[file_path] = UploadProgressResponse(
                filename=prog.filename,
                uploader=prog.uploader,
                progress=prog.progress,
                uploaded_bytes=prog.uploaded_bytes,
                total_bytes=prog.total_bytes,
                speed=prog.speed,
                status=prog.status,
                error=prog.error,
            )
        
        return AllProgressResponse(
            success=True,
            count=len(progress_dict),
            progress=progress_dict,
        )
    except Exception as e:
        logger.error(f"获取上传进度失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取上传进度失败: {e}")


@router.websocket("/ws/progress")
async def websocket_progress(websocket: WebSocket):
    """
    WebSocket 实时上传进度流
    
    通过 WebSocket 实时推送上传进度更新。
    """
    await websocket.accept()
    
    state = get_state_manager()
    progress_queue = []
    queue_lock = threading.Lock()
    
    def on_progress(progress):
        """进度更新回调"""
        with queue_lock:
            progress_queue.append({
                "type": "progress",
                "file_path": progress.file_path,
                "filename": progress.filename,
                "uploader": progress.uploader,
                "progress": progress.progress,
                "uploaded_bytes": progress.uploaded_bytes,
                "total_bytes": progress.total_bytes,
                "speed": progress.speed,
                "status": progress.status,
                "error": progress.error,
            })
    
    # 注册回调
    state.register_progress_callback(on_progress)
    
    try:
        while True:
            # 发送队列中的进度更新
            with queue_lock:
                if progress_queue:
                    for msg in progress_queue:
                        await websocket.send_json(msg)
                    progress_queue.clear()
            
            # 发送心跳（5秒间隔）
            await websocket.send_json({"type": "heartbeat"})
            
            # 等待
            await asyncio.sleep(5)
            
    except WebSocketDisconnect:
        logger.debug("进度 WebSocket 连接已断开")
    except Exception as e:
        logger.debug(f"进度 WebSocket 连接关闭: {e}")
    finally:
        # 注销回调
        state.unregister_progress_callback(on_progress)
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    WebSocket 仪表盘实时更新

    连接时推送当前状态快照，任务状态变更时实时推送更新。
    """
    await websocket.accept()

    state = get_state_manager()
    update_queue = []
    queue_lock = threading.Lock()

    def on_dashboard_update():
        """仪表盘更新回调（在 record_task 线程中触发）"""
        with queue_lock:
            update_queue.append({"type": "update"})

    # 注册回调
    state.register_dashboard_callback(on_dashboard_update)

    try:
        # 连接时推送初始快照
        try:
            status = state.get_system_status()
            items, total = get_recent_activity_paginated(page=1, page_size=20)
            await websocket.send_json({
                "type": "snapshot",
                "stats": {
                    "queue": status.queue_size,
                    "processing": status.processing_count,
                    "uploading": status.uploading_count,
                    "completed": status.completed_count,
                    "failed": status.failed_count,
                },
                "recent": {
                    "items": items,
                    "total": total,
                }
            })
        except Exception as e:
            logger.warning(f"仪表盘初始快照失败: {e}")

        while True:
            # 发送队列中的更新
            needs_refresh = False
            with queue_lock:
                if update_queue:
                    update_queue.clear()
                    needs_refresh = True

            if needs_refresh:
                try:
                    status = state.get_system_status()
                    items, total = get_recent_activity_paginated(page=1, page_size=20)
                    await websocket.send_json({
                        "type": "update",
                        "stats": {
                            "queue": status.queue_size,
                            "processing": status.processing_count,
                            "uploading": status.uploading_count,
                            "completed": status.completed_count,
                            "failed": status.failed_count,
                        },
                        "recent": {
                            "items": items,
                            "total": total,
                        }
                    })
                except Exception as e:
                    logger.warning(f"仪表盘推送更新失败: {e}")

            # 心跳
            await websocket.send_json({"type": "heartbeat"})
            await asyncio.sleep(3)

    except WebSocketDisconnect:
        logger.debug("仪表盘 WebSocket 连接已断开")
    except Exception as e:
        logger.debug(f"仪表盘 WebSocket 连接关闭: {e}")
    finally:
        state.unregister_dashboard_callback(on_dashboard_update)
        try:
            await websocket.close()
        except:
            pass


@router.post("/retry")
async def retry_failed_task(request: RetryRequest):
    """
    重试失败的任务
    
    Args:
        request: 包含 file_path 的请求
    """
    try:
        state = get_state_manager()
        handler = state.get_video_handler()
        
        if handler is None:
            raise HTTPException(status_code=503, detail="系统未就绪")
        
        file_path = request.file_path
        failed_files = state.get_failed_files()
        if file_path not in failed_files:
            raise HTTPException(status_code=404, detail="文件不在失败列表中")
        
        # 从失败列表移除
        if hasattr(handler, "_failed_files") and file_path in handler._failed_files:
            del handler._failed_files[file_path]
        
        # 重新处理
        handler.force_process_file(file_path)
        
        logger.info(f"已重试任务: {file_path}")
        
        return {"success": True, "message": f"已重试任务: {file_path}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"重试任务失败: {e}")


@router.post("/retry-all")
async def retry_all_failed_tasks():
    """
    重试所有失败的任务
    """
    try:
        state = get_state_manager()
        handler = state.get_video_handler()
        
        if handler is None:
            raise HTTPException(status_code=503, detail="系统未就绪")
        
        failed_files = state.get_failed_files()
        retried_count = 0
        
        for file_path in list(failed_files.keys()):
            # 从失败列表移除
            if hasattr(handler, "_failed_files") and file_path in handler._failed_files:
                del handler._failed_files[file_path]
            
            # 重新处理
            handler.force_process_file(file_path)
            retried_count += 1
        
        logger.info(f"已重试 {retried_count} 个失败任务")
        
        return {
            "success": True,
            "message": f"已重试 {retried_count} 个失败任务",
            "retried_count": retried_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试所有失败任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"重试所有失败任务失败: {e}")


@router.delete("/failed/{file_path:path}")
async def clear_failed_task(file_path: str):
    """
    清除失败任务记录
    
    Args:
        file_path: 失败的文件路径
    """
    try:
        state = get_state_manager()
        handler = state.get_video_handler()
        
        if handler is not None and hasattr(handler, "_failed_files") and file_path in handler._failed_files:
            del handler._failed_files[file_path]
        
        db_deleted = delete_failed_task(file_path)
        
        if db_deleted:
            logger.info(f"已清除失败任务记录: {file_path}")
            return {"success": True, "message": f"已清除失败任务记录: {file_path}"}
        else:
            raise HTTPException(status_code=404, detail="文件不在失败列表中")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清除失败任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除失败任务失败: {e}")


@router.delete("/failed")
async def clear_all_failed_tasks():
    """
    清除所有失败任务记录
    """
    try:
        state = get_state_manager()
        handler = state.get_video_handler()
        
        if handler is not None and hasattr(handler, "_failed_files"):
            handler._failed_files.clear()
        
        db_count = delete_all_failed_tasks()
        
        logger.info(f"已清除 {db_count} 条失败任务记录")
        return {"success": True, "message": f"已清除 {db_count} 条失败任务记录"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清除所有失败任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除所有失败任务失败: {e}")
