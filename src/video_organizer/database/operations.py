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
