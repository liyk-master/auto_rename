"""
网盘整理 API

提供网盘文件整理的 Web 接口：
- 检查整理功能可用性
- 列出源目录文件 / 统计视频数量
- 试运行（dry_run）与正式整理（后台线程 + 进度轮询）
- 取消整理任务
"""

import threading
import logging
from typing import Dict, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.state import get_state_manager
from ...upload.p123_organizer import P123Organizer
from ...upload.yun139_organizer import Yun139Organizer

logger = logging.getLogger(__name__)

router = APIRouter()

# 支持的网盘 provider 列表
PROVIDERS = ["p123", "yun139"]

# 整理运行状态: provider -> {status, lock, ...}
_running: Dict[str, Dict] = {}


class RunRequest(BaseModel):
    """整理请求体"""

    dry_run: bool = False
    source_id: Optional[str] = None
    target_id: Optional[str] = None


def _get_config() -> Dict:
    """获取当前配置"""
    state = get_state_manager()
    return state.get_config()


def _build_organizer(provider: str):
    """根据配置构建对应网盘的整理器"""
    config = _get_config()
    tmdb_api_key = config.get("tmdb", {}).get("api_key", "")

    if provider == "p123":
        p123_config = config.get("p123", {})
        return P123Organizer(
            token=p123_config.get("token", ""),
            organize_source_id=int(p123_config.get("organize_source_id", 0) or 0),
            organize_target_id=int(p123_config.get("organize_target_id", 0) or 0),
            max_workers=int(p123_config.get("max_workers", 2)),
            tmdb_api_key=tmdb_api_key,
            username=p123_config.get("username", ""),
            password=p123_config.get("password", ""),
        )
    elif provider == "yun139":
        yun139_config = config.get("yun139", {})
        return Yun139Organizer(
            authorization=yun139_config.get("authorization", ""),
            cloud_type=yun139_config.get("cloud_type", "personal_new"),
            cloud_id=yun139_config.get("cloud_id", ""),
            organize_source_id=str(yun139_config.get("organize_source_id", "") or ""),
            organize_target_id=str(yun139_config.get("organize_target_id", "") or ""),
            max_workers=int(yun139_config.get("max_workers", 2)),
            tmdb_api_key=tmdb_api_key,
            app_mode=bool(yun139_config.get("app_mode", False)),
        )
    raise HTTPException(status_code=400, detail=f"不支持的网盘类型: {provider}")


def _check_provider(provider: str) -> None:
    """校验 provider 是否支持"""
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的网盘类型: {provider}")


def _init_running(provider: str) -> Dict:
    """初始化运行状态字典"""
    if provider not in _running:
        _running[provider] = {
            "status": "idle",  # idle, running, done
            "lock": threading.Lock(),
            "processed": 0,
            "total": 0,
            "current_name": "",
            "action": "",
            "detail": "",
            "result": None,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }
    return _running[provider]


def _run_organize(provider: str, source_id, target_id, dry_run: bool) -> None:
    """后台线程：执行整理任务"""
    state = _init_running(provider)
    try:
        organizer = _build_organizer(provider)

        def progress_callback(progress: Dict) -> None:
            with state["lock"]:
                state["processed"] = progress.get("processed", 0)
                state["total"] = progress.get("total", 0)
                state["current_name"] = progress.get("name", "")
                state["action"] = progress.get("action", "")
                state["detail"] = progress.get("detail", "")
                state["success"] = progress.get("success", 0)
                state["failed"] = progress.get("failed", 0)
                state["skipped"] = progress.get("skipped", 0)

        result = organizer.organize_streaming(
            source_id=source_id,
            target_id=target_id,
            dry_run=dry_run,
            show_progress=False,
            progress_callback=progress_callback,
        )
        with state["lock"]:
            state["status"] = "done"
            state["result"] = result
            state["action"] = "cancelled" if result.get("cancelled") else "completed"
    except Exception as e:
        logger.exception(f"整理任务异常: {provider}")
        with state["lock"]:
            state["status"] = "done"
            state["result"] = {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "total": 0,
                "errors": [f"整理任务异常: {e}"],
            }
            state["action"] = "failed"
            state["detail"] = str(e)


@router.get("/{provider}/status")
async def organize_status(provider: str):
    """获取整理功能状态"""
    _check_provider(provider)
    organizer = _build_organizer(provider)
    config = _get_config()
    provider_config = config.get(provider, {})
    state = _init_running(provider)
    with state["lock"]:
        running = state["status"] == "running"
    return {
        "provider": provider,
        "available": organizer.is_available(),
        "organize_source_id": provider_config.get("organize_source_id", ""),
        "organize_target_id": provider_config.get("organize_target_id", ""),
        "running": running,
    }


@router.get("/{provider}/files")
async def organize_list_files(
    provider: str,
    parent_id: str = "",
    page: int = 1,
    per_page: int = 100,
):
    """列出目录下的文件"""
    _check_provider(provider)
    organizer = _build_organizer(provider)
    if not organizer.is_available():
        raise HTTPException(status_code=400, detail="整理功能不可用，请检查配置")

    if not parent_id:
        config = _get_config()
        parent_id = str(config.get(provider, {}).get("organize_source_id", "") or "")

    files = organizer.list_files(parent_id, page=page, per_page=per_page)
    return {"files": files, "parent_id": parent_id, "total": len(files)}


@router.get("/{provider}/count")
async def organize_count(provider: str, source_id: str = "", max_depth: int = 5):
    """统计源目录视频文件数量"""
    _check_provider(provider)
    organizer = _build_organizer(provider)
    if not organizer.is_available():
        raise HTTPException(status_code=400, detail="整理功能不可用，请检查配置")

    if not source_id:
        config = _get_config()
        source_id = str(config.get(provider, {}).get("organize_source_id", "") or "")

    if not source_id:
        raise HTTPException(status_code=400, detail="未设置源目录ID")

    count = organizer.count_video_files(source_id, max_depth=max_depth)
    return {"count": count}


@router.post("/{provider}/run")
async def organize_run(provider: str, req: RunRequest):
    """启动整理任务（后台执行）"""
    _check_provider(provider)
    organizer = _build_organizer(provider)
    if not organizer.is_available():
        raise HTTPException(status_code=400, detail="整理功能不可用，请检查配置")

    state = _init_running(provider)
    with state["lock"]:
        if state["status"] == "running":
            raise HTTPException(status_code=400, detail="整理任务正在运行中")

    config = _get_config()
    source_id = req.source_id
    if not source_id:
        source_id = str(config.get(provider, {}).get("organize_source_id", "") or "")
    target_id = req.target_id
    if not target_id:
        target_id = str(config.get(provider, {}).get("organize_target_id", "") or "")

    if not source_id or not target_id:
        raise HTTPException(
            status_code=400,
            detail="未设置源目录ID或目标目录ID，请在配置中填写或通过请求传入",
        )

    # 重置运行状态
    with state["lock"]:
        state.update(
            {
                "status": "running",
                "processed": 0,
                "total": 0,
                "current_name": "",
                "action": "starting",
                "detail": "",
                "result": None,
                "success": 0,
                "failed": 0,
                "skipped": 0,
            }
        )

    # 后台线程执行（转换 source/target 为合适类型：p123 用 int，yun139 用 str）
    source_id_int: Union[str, int]
    target_id_int: Union[str, int]
    if provider == "p123":
        try:
            source_id_int = int(source_id)
            target_id_int = int(target_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="p123 网盘的源/目标目录ID必须是数字"
            )
    else:
        source_id_int = source_id
        target_id_int = target_id

    thread = threading.Thread(
        target=_run_organize,
        args=(provider, source_id_int, target_id_int, req.dry_run),
        daemon=True,
    )
    thread.start()
    return {
        "started": True,
        "dry_run": req.dry_run,
        "source_id": str(source_id),
        "target_id": str(target_id),
    }


@router.post("/{provider}/cancel")
async def organize_cancel(provider: str):
    """取消整理任务"""
    _check_provider(provider)
    organizer = _build_organizer(provider)
    state = _init_running(provider)
    with state["lock"]:
        was_running = state["status"] == "running"
    if was_running:
        organizer.cancel()
        return {"cancelled": True}
    return {"cancelled": False, "message": "当前没有运行中的整理任务"}


@router.get("/{provider}/progress")
async def organize_progress(provider: str):
    """获取整理任务进度"""
    _check_provider(provider)
    state = _init_running(provider)
    with state["lock"]:
        return {
            "status": state["status"],
            "processed": state["processed"],
            "total": state["total"],
            "current_name": state["current_name"],
            "action": state["action"],
            "detail": state["detail"],
            "result": state["result"],
            "success": state["success"],
            "failed": state["failed"],
            "skipped": state["skipped"],
        }
