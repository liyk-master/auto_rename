import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .session import get_session_local, init_db
from .models import TaskHistory

logger = logging.getLogger(__name__)


def record_task(
    file_path: str,
    status: str,
    error_message: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> bool:
    """
    记录任务完成或失败到数据库
    
    Returns:
        是否成功写入
    """
    try:
        session_local = get_session_local()
    except Exception:
        return False

    try:
        with session_local() as db:
            record = TaskHistory(
                file_path=file_path,
                status=status,
                error_message=error_message,
                start_time=start_time or datetime.now(),
                end_time=end_time,
            )
            db.add(record)
            db.commit()
        return True
    except Exception as e:
        logger.warning(f"写入任务历史到数据库失败: {e}")
        return False


def get_completed_tasks(limit: int = 200) -> List[Dict]:
    """
    从数据库获取已完成的任务列表
    
    Returns:
        [{"path": str, "time": str (ISO format) or None}, ...]
    """
    try:
        session_local = get_session_local()
    except Exception:
        return []

    try:
        with session_local() as db:
            records = (
                db.query(TaskHistory)
                .filter(TaskHistory.status == "completed")
                .order_by(TaskHistory.end_time.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "path": r.file_path,
                    "time": r.end_time.isoformat() if r.end_time else None,
                }
                for r in records
            ]
    except Exception as e:
        logger.warning(f"从数据库读取已完成任务失败: {e}")
        return []


def get_failed_tasks(limit: int = 200) -> Dict[str, Dict]:
    """
    从数据库获取失败的任务列表
    
    Returns:
        {path: {"error": str, "time": str (ISO format) or None}, ...}
    """
    try:
        session_local = get_session_local()
    except Exception:
        return {}

    try:
        with session_local() as db:
            records = (
                db.query(TaskHistory)
                .filter(TaskHistory.status == "failed")
                .order_by(TaskHistory.end_time.desc())
                .limit(limit)
                .all()
            )
            result = {}
            for r in records:
                if r.file_path not in result:
                    result[r.file_path] = {
                        "error": r.error_message or "",
                        "time": r.end_time.isoformat() if r.end_time else None,
                    }
            return result
    except Exception as e:
        logger.warning(f"从数据库读取失败任务失败: {e}")
        return {}


def get_task_counts() -> Dict[str, int]:
    """
    从数据库获取已完成和失败的任务计数
    
    Returns:
        {"completed": int, "failed": int}
    """
    try:
        session_local = get_session_local()
    except Exception:
        return {"completed": 0, "failed": 0}

    try:
        with session_local() as db:
            from sqlalchemy import func
            rows = (
                db.query(TaskHistory.status, func.count(TaskHistory.id))
                .filter(TaskHistory.status.in_(["completed", "failed"]))
                .group_by(TaskHistory.status)
                .all()
            )
            result = {"completed": 0, "failed": 0}
            for status, count in rows:
                result[status] = count
            return result
    except Exception as e:
        logger.warning(f"从数据库读取任务计数失败: {e}")
        return {"completed": 0, "failed": 0}


def get_all_tasks_for_dashboard(limit: int = 20) -> List[Dict]:
    """
    获取最近的任务（已完成+失败），用于仪表盘展示
    
    Returns:
        [{"path": str, "status": str, "error": str or None, "time": str or None}, ...]
    """
    try:
        session_local = get_session_local()
    except Exception:
        return []

    try:
        with session_local() as db:
            records = (
                db.query(TaskHistory)
                .order_by(TaskHistory.end_time.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "path": r.file_path,
                    "status": r.status,
                    "error": r.error_message,
                    "time": r.end_time.isoformat() if r.end_time else None,
                }
                for r in records
            ]
    except Exception as e:
        logger.warning(f"从数据库读取仪表盘任务失败: {e}")
        return []


def get_tasks_paginated(
    status: Optional[str] = None,
    search: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
) -> Tuple[List[Dict], int]:
    """
    分页查询任务，支持按状态过滤和按文件路径搜索

    Returns:
        (items, total_count)
        items: [{"path": str, "status": str, "error": str or None, "time": str or None, "id": int}, ...]
    """
    try:
        session_local = get_session_local()
    except Exception:
        return [], 0

    try:
        with session_local() as db:
            query = db.query(TaskHistory)

            if status:
                query = query.filter(TaskHistory.status == status)

            if search:
                like_pattern = f"%{search}%"
                query = query.filter(TaskHistory.file_path.like(like_pattern))

            total = query.count()

            records = (
                query
                .order_by(TaskHistory.end_time.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

            items = [
                {
                    "id": r.id,
                    "path": r.file_path,
                    "status": r.status,
                    "error": r.error_message,
                    "time": r.end_time.isoformat() if r.end_time else None,
                }
                for r in records
            ]
            return items, total
    except Exception as e:
        logger.warning(f"分页查询任务失败: {e}")
        return [], 0


def get_recent_activity_paginated(
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
) -> Tuple[List[Dict], int]:
    """
    分页获取最近活动（已完成+失败混合），用于仪表盘展示

    Returns:
        (items, total_count)
    """
    try:
        session_local = get_session_local()
    except Exception:
        return [], 0

    try:
        offset = (page - 1) * page_size
        with session_local() as db:
            query = db.query(TaskHistory).filter(
                TaskHistory.status.in_(["completed", "failed"])
            )

            if search:
                like_pattern = f"%{search}%"
                query = query.filter(TaskHistory.file_path.like(like_pattern))

            total = query.count()

            records = (
                query
                .order_by(TaskHistory.end_time.desc())
                .offset(offset)
                .limit(page_size)
                .all()
            )

            items = [
                {
                    "id": r.id,
                    "path": r.file_path,
                    "status": r.status,
                    "error": r.error_message,
                    "time": r.end_time.isoformat() if r.end_time else None,
                }
                for r in records
            ]
            return items, total
    except Exception as e:
        logger.warning(f"分页获取最近活动失败: {e}")
        return [], 0
