"""
手动处理路由

提供手动触发文件处理的 API。
"""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.state import get_state_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class ProcessFileRequest(BaseModel):
    """处理文件请求"""
    file_path: str
    force: bool = False  # 是否强制处理（即使已在队列中）


class ProcessFileResponse(BaseModel):
    """处理文件响应"""
    success: bool
    message: str
    file_path: str


class ScanDirectoryRequest(BaseModel):
    """扫描目录请求"""
    directory: str
    recursive: bool = True
    extensions: Optional[List[str]] = None


class ScanDirectoryResponse(BaseModel):
    """扫描目录响应"""
    success: bool
    directory: str
    files: List[str]
    count: int


class PreviewRequest(BaseModel):
    """预览请求"""
    file_path: str


class PreviewResponse(BaseModel):
    """预览响应"""
    success: bool
    file_path: str
    original_name: str
    suggested_name: Optional[str] = None
    media_type: Optional[str] = None
    metadata: Optional[dict] = None
    error: Optional[str] = None


@router.post("/process", response_model=ProcessFileResponse)
async def process_file(request: ProcessFileRequest):
    """
    手动处理单个文件
    
    触发指定文件的重命名和上传流程。
    
    Args:
        request: 包含 file_path 和 force 的请求
    """
    try:
        state = get_state_manager()
        handler = state.get_video_handler()
        
        if handler is None:
            raise HTTPException(status_code=503, detail="系统未就绪")
        
        file_path = Path(request.file_path)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_path}")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"不是有效文件: {request.file_path}")
        
        # 检查是否已在队列中
        if not request.force:
            queued_files = state.get_queued_files()
            processing_files = state.get_processing_files()
            
            if str(file_path) in queued_files or str(file_path) in processing_files:
                return ProcessFileResponse(
                    success=False,
                    message="文件已在处理队列中，如需重新处理请使用 force=true",
                    file_path=request.file_path,
                )
        
        # 触发处理
        handler.force_process_file(str(file_path))
        
        logger.info(f"已手动触发文件处理: {request.file_path}")
        
        return ProcessFileResponse(
            success=True,
            message=f"已添加到处理队列: {request.file_path}",
            file_path=request.file_path,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理文件失败: {e}")


@router.post("/scan", response_model=ScanDirectoryResponse)
async def scan_directory(request: ScanDirectoryRequest):
    """
    扫描目录查找视频文件
    
    返回目录中的所有视频文件列表。
    
    Args:
        request: 包含 directory, recursive, extensions 的请求
    """
    try:
        directory = Path(request.directory)
        
        if not directory.exists():
            raise HTTPException(status_code=404, detail=f"目录不存在: {request.directory}")
        
        if not directory.is_dir():
            raise HTTPException(status_code=400, detail=f"不是有效目录: {request.directory}")
        
        # 获取支持的视频扩展名
        state = get_state_manager()
        config = state.get_config()
        
        if request.extensions:
            extensions = [ext.lower() if ext.startswith(".") else f".{ext.lower()}" 
                         for ext in request.extensions]
        else:
            extensions = config.get("monitoring", {}).get(
                "supported_extensions",
                [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv"]
            )
        
        # 扫描文件
        video_files = []
        
        if request.recursive:
            for ext in extensions:
                video_files.extend(directory.rglob(f"*{ext}"))
        else:
            for ext in extensions:
                video_files.extend(directory.glob(f"*{ext}"))
        
        # 转换为字符串列表
        file_list = [str(f) for f in video_files if f.is_file()]
        
        return ScanDirectoryResponse(
            success=True,
            directory=request.directory,
            files=file_list,
            count=len(file_list),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫描目录失败: {e}")
        raise HTTPException(status_code=500, detail=f"扫描目录失败: {e}")


@router.post("/process-batch")
async def process_batch_files(file_paths: List[str]):
    """
    批量处理文件
    
    将多个文件添加到处理队列。
    
    Args:
        file_paths: 文件路径列表
    """
    try:
        state = get_state_manager()
        handler = state.get_video_handler()
        
        if handler is None:
            raise HTTPException(status_code=503, detail="系统未就绪")
        
        added_count = 0
        skipped_count = 0
        errors = []
        
        queued_files = state.get_queued_files()
        processing_files = state.get_processing_files()
        
        for file_path in file_paths:
            path = Path(file_path)
            
            if not path.exists():
                errors.append(f"{file_path}: 文件不存在")
                continue
            
            if str(path) in queued_files or str(path) in processing_files:
                skipped_count += 1
                continue
            
            handler.force_process_file(str(path))
            added_count += 1
        
        logger.info(f"批量处理: 添加 {added_count} 个文件，跳过 {skipped_count} 个")
        
        return {
            "success": True,
            "message": f"已添加 {added_count} 个文件到队列",
            "added_count": added_count,
            "skipped_count": skipped_count,
            "errors": errors if errors else None,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量处理失败: {e}")


@router.post("/preview", response_model=PreviewResponse)
async def preview_rename(request: PreviewRequest):
    """
    预览重命名结果
    
    模拟文件处理流程，返回预期的重命名结果（不实际执行）。
    
    Args:
        request: 包含 file_path 的请求
    """
    try:
        state = get_state_manager()
        handler = state.get_video_handler()
        
        if handler is None:
            raise HTTPException(status_code=503, detail="系统未就绪")
        
        file_path = Path(request.file_path)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_path}")
        
        # 获取文件名（不含扩展名）
        original_name = file_path.stem
        
        # 尝试使用 renamer 预览
        try:
            from ...core.renamer import VideoRenamer
            from ...core.tmdb_client import TMDBClient
            
            config = state.get_config()
            tmdb_config = config.get("tmdb", {})
            
            tmdb_client = None
            if tmdb_config.get("api_key"):
                tmdb_client = TMDBClient(
                    api_key=tmdb_config.get("api_key", ""),
                    language=tmdb_config.get("language", "zh-CN"),
                )
            
            renamer = VideoRenamer(
                naming_rules=config.get("naming", {}),
                tmdb_client=tmdb_client,
            )
            
            # 解析文件名
            metadata = renamer.extract_metadata(original_name)
            
            # 尝试获取 TMDB 信息
            tmdb_info = None
            if tmdb_client and metadata.get("title"):
                try:
                    if metadata.get("season"):
                        # 电视剧
                        results = tmdb_client.search_tv_show(metadata["title"])
                        if results:
                            tmdb_info = results[0]
                            media_type = "tv_show"
                    else:
                        # 电影
                        results = tmdb_client.search_movie(metadata["title"])
                        if results:
                            tmdb_info = results[0]
                            media_type = "movie"
                except Exception as e:
                    logger.warning(f"获取 TMDB 信息失败: {e}")
            
            # 生成建议名称
            if metadata.get("season"):
                media_type = "tv_show"
                suggested_name = renamer.format_tv_show_name(
                    title=tmdb_info.get("name", metadata.get("title", original_name)) if tmdb_info else metadata.get("title", original_name),
                    season=metadata.get("season", 1),
                    episode=metadata.get("episode", 1),
                    episode_title=metadata.get("episode_title", ""),
                )
            elif metadata.get("year"):
                media_type = "movie"
                suggested_name = renamer.format_movie_name(
                    title=tmdb_info.get("title", metadata.get("title", original_name)) if tmdb_info else metadata.get("title", original_name),
                    year=metadata.get("year"),
                )
            else:
                media_type = "unknown"
                suggested_name = None
            
            return PreviewResponse(
                success=True,
                file_path=request.file_path,
                original_name=original_name,
                suggested_name=suggested_name,
                media_type=media_type,
                metadata={
                    "title": metadata.get("title"),
                    "season": metadata.get("season"),
                    "episode": metadata.get("episode"),
                    "year": metadata.get("year"),
                    "episode_title": metadata.get("episode_title"),
                    "tmdb_matched": tmdb_info is not None,
                },
            )
            
        except Exception as e:
            return PreviewResponse(
                success=False,
                file_path=request.file_path,
                original_name=original_name,
                error=str(e),
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"预览重命名失败: {e}")
        raise HTTPException(status_code=500, detail=f"预览重命名失败: {e}")


@router.get("/browse")
async def browse_directory(path: str = ""):
    """
    浏览文件系统目录
    
    返回指定目录下的子目录和文件列表，用于文件选择器。
    
    Args:
        path: 目录路径（空字符串表示根目录）
    """
    try:
        if not path:
            # Windows: 返回驱动器列表
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
            return {
                "success": True,
                "path": "",
                "parent": None,
                "directories": drives,
                "files": [],
            }
        
        directory = Path(path)
        
        if not directory.exists():
            raise HTTPException(status_code=404, detail=f"目录不存在: {path}")
        
        if not directory.is_dir():
            raise HTTPException(status_code=400, detail=f"不是有效目录: {path}")
        
        # 获取子目录和文件
        directories = []
        files = []
        
        try:
            for item in directory.iterdir():
                if item.is_dir():
                    directories.append(item.name)
                elif item.is_file():
                    files.append({
                        "name": item.name,
                        "size": item.stat().st_size,
                        "extension": item.suffix.lower(),
                    })
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"无权限访问目录: {path}")
        
        # 获取父目录
        parent = str(directory.parent) if directory.parent != directory else None
        
        return {
            "success": True,
            "path": str(directory),
            "parent": parent,
            "directories": sorted(directories),
            "files": sorted(files, key=lambda x: x["name"]),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"浏览目录失败: {e}")
        raise HTTPException(status_code=500, detail=f"浏览目录失败: {e}")
