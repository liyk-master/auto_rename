"""
日志查看路由

提供日志读取和实时日志推送 API。
"""

import logging
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..services.state import get_state_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class LogEntry(BaseModel):
    """日志条目"""
    line_number: int
    content: str


class LogListResponse(BaseModel):
    """日志文件列表响应"""
    success: bool
    files: List[str]
    current: Optional[str] = None


class LogContentResponse(BaseModel):
    """日志内容响应"""
    success: bool
    file: str
    total_lines: int
    lines: List[LogEntry]


def _find_log_file(filename: str, config: dict) -> Optional[Path]:
    """
    查找日志文件
    
    Args:
        filename: 日志文件名
        config: 配置字典
        
    Returns:
        日志文件路径，如果未找到返回 None
    """
    # 搜索路径列表（按优先级排序）
    search_dirs = []
    
    # 1. 尝试从配置获取日志目录
    logging_config = config.get("logging", {})
    log_file = logging_config.get("file") or logging_config.get("log_file", "")
    
    if log_file:
        log_path = Path(log_file)
        if log_path.is_absolute():
            search_dirs.append(log_path.parent)
        else:
            search_dirs.append(Path.cwd() / log_path.parent)
    
    # 2. 当前工作目录
    search_dirs.append(Path.cwd())
    
    # 3. 项目目录下的 logs 文件夹
    # video_organizer/web/routers/logs.py -> video_organizer/logs
    search_dirs.append(Path(__file__).parent.parent / "logs")
    # video_organizer/web/routers/logs.py -> src/video_organizer/logs
    search_dirs.append(Path(__file__).parent.parent.parent / "video_organizer" / "logs")
    # src/video_organizer/logs
    search_dirs.append(Path(__file__).parent.parent.parent / "logs")
    
    for search_dir in search_dirs:
        if search_dir.exists():
            target = search_dir / filename
            if target.exists():
                return target
    
    return None


@router.get("/files", response_model=LogListResponse)
async def list_log_files():
    """
    获取日志文件列表
    
    返回可用的日志文件。
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        
        log_files = set()
        
        # 搜索路径列表
        search_dirs = []
        
        # 1. 从配置获取日志目录
        logging_config = config.get("logging", {})
        log_file = logging_config.get("file") or logging_config.get("log_file", "")
        
        if log_file:
            log_path = Path(log_file)
            if log_path.is_absolute():
                search_dirs.append(log_path.parent)
            else:
                search_dirs.append(Path.cwd() / log_path.parent)
        
        # 2. 当前工作目录
        search_dirs.append(Path.cwd())
        
        # 3. 项目目录下的 logs 文件夹
        search_dirs.append(Path(__file__).parent.parent / "logs")
        search_dirs.append(Path(__file__).parent.parent.parent / "video_organizer" / "logs")
        search_dirs.append(Path(__file__).parent.parent.parent / "logs")
        
        for search_dir in search_dirs:
            if search_dir.exists():
                for f in search_dir.glob("*.log*"):
                    log_files.add(f.name)
        
        # 确定当前日志文件名
        current_log = None
        if log_file:
            current_log = Path(log_file).name
        elif log_files:
            # 尝试找默认日志文件
            for name in ["video-organizer.log", "video_organizer.log"]:
                if name in log_files:
                    current_log = name
                    break
        
        return LogListResponse(
            success=True,
            files=sorted(log_files, reverse=True),
            current=current_log,
        )
    except Exception as e:
        logger.error(f"获取日志文件列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日志文件列表失败: {e}")


@router.get("/content/{filename}", response_class=PlainTextResponse)
async def get_log_content(
    filename: str,
    lines: int = 100,
    offset: int = 0,
):
    """
    获取日志文件内容
    
    Args:
        filename: 日志文件名
        lines: 返回的行数（从末尾开始）
        offset: 偏移量（从末尾偏移）
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        
        target_file = _find_log_file(filename, config)
        
        if not target_file:
            raise HTTPException(status_code=404, detail=f"日志文件不存在: {filename}")
        
        # 读取文件
        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        
        # 从末尾获取指定行数
        total_lines = len(all_lines)
        start_idx = max(0, total_lines - lines - offset)
        end_idx = total_lines - offset if offset > 0 else total_lines
        
        selected_lines = all_lines[start_idx:end_idx]
        
        return "".join(selected_lines)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日志内容失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日志内容失败: {e}")


@router.get("/tail/{filename}")
async def tail_log(filename: str, lines: int = 50):
    """
    获取日志文件末尾内容
    
    类似 tail -n 命令。
    
    Args:
        filename: 日志文件名
        lines: 返回的行数
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        
        target_file = _find_log_file(filename, config)
        
        if not target_file:
            raise HTTPException(status_code=404, detail=f"日志文件不存在: {filename}")
        
        # 使用 tail 方法读取
        result_lines = []
        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            # 移动到文件末尾
            f.seek(0, 2)
            file_size = f.tell()
            
            if file_size == 0:
                return {"success": True, "lines": [], "total": 0}
            
            # 从后向前读取
            pos = file_size - 1
            line_count = 0
            current_line = ""
            
            while pos >= 0 and line_count < lines:
                f.seek(pos)
                char = f.read(1)
                
                if char == "\n":
                    if current_line:
                        result_lines.insert(0, current_line)
                        line_count += 1
                        current_line = ""
                else:
                    current_line = char + current_line
                
                pos -= 1
            
            # 添加最后一行（如果文件不以换行结尾）
            if current_line and line_count < lines:
                result_lines.insert(0, current_line)
        
        return {
            "success": True,
            "file": filename,
            "lines": result_lines,
            "total": len(result_lines),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日志末尾失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日志末尾失败: {e}")


@router.get("/search/{filename}")
async def search_log(filename: str, keyword: str, limit: int = 100):
    """
    搜索日志内容
    
    Args:
        filename: 日志文件名
        keyword: 搜索关键词
        limit: 最大返回数量
    """
    try:
        state = get_state_manager()
        config = state.get_config()
        
        target_file = _find_log_file(filename, config)
        
        if not target_file:
            raise HTTPException(status_code=404, detail=f"日志文件不存在: {filename}")
        
        # 搜索匹配行
        matches = []
        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                if keyword.lower() in line.lower():
                    matches.append({
                        "line_number": line_num,
                        "content": line.rstrip("\n\r"),
                    })
                    if len(matches) >= limit:
                        break
        
        return {
            "success": True,
            "file": filename,
            "keyword": keyword,
            "matches": matches,
            "total": len(matches),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索日志失败: {e}")


@router.websocket("/ws/{filename}")
async def websocket_log_stream(websocket: WebSocket, filename: str):
    """
    WebSocket 实时日志流
    
    通过 WebSocket 实时推送日志更新。
    
    Args:
        filename: 日志文件名
    """
    await websocket.accept()
    
    try:
        state = get_state_manager()
        config = state.get_config()
        
        target_file = _find_log_file(filename, config)
        
        if not target_file:
            await websocket.send_json({"error": f"日志文件不存在: {filename}"})
            await websocket.close()
            return
        
        # 打开文件并移动到末尾
        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)  # 移动到文件末尾
            heartbeat_counter = 0  # 心跳计数器
            
            while True:
                line = f.readline()
                if line:
                    await websocket.send_json({
                        "type": "log",
                        "content": line.rstrip("\n\r"),
                    })
                else:
                    # 没有新行，短暂等待
                    await asyncio.sleep(0.1)
                    heartbeat_counter += 1
                    
                    # 每 50 次循环（约 5 秒）发送一次心跳
                    if heartbeat_counter >= 50:
                        heartbeat_counter = 0
                        try:
                            await websocket.send_json({"type": "heartbeat"})
                        except:
                            break
                        
    except WebSocketDisconnect:
        logger.info("WebSocket 连接已断开")
    except Exception as e:
        logger.error(f"WebSocket 日志流错误: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass