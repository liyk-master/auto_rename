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


class ValidateRequest(BaseModel):
    """刮削验证请求"""
    file_path: str


class ValidateResponse(BaseModel):
    """刮削验证响应"""
    success: bool
    file_path: str
    original_name: str
    title: Optional[str] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    media_type: Optional[str] = None
    tmdb_matched: bool = False
    tmdb_info: Optional[dict] = None
    suggested_name: Optional[str] = None
    suggested_path: Optional[str] = None
    confidence: Optional[float] = None
    quality_tags: Optional[str] = None
    release_group: Optional[str] = None
    episode_title: Optional[str] = None
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

    与 /validate 共用相同逻辑，返回预期的重命名结果（不实际执行）。
    
    Args:
        request: 包含 file_path 的请求
    """
    try:
        raw_path = request.file_path.strip().strip('"').strip("'")
        file_path = Path(raw_path)

        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {raw_path}")

        original_name = file_path.stem if file_path.suffix else file_path.name

        state = get_state_manager()
        config = state.get_config()
        tmdb_config = config.get("tmdb", {})

        from ...core.renamer import VideoRenamer
        from ...core.tmdb_client import TMDBClient

        tmdb_client = None
        if tmdb_config.get("api_key"):
            tmdb_client = TMDBClient(
                api_key=tmdb_config.get("api_key", ""),
                retry_count=tmdb_config.get("retry_count", 3),
                timeout=tmdb_config.get("timeout", 30),
                base_url=tmdb_config.get("base_url"),
            )

        renamer = VideoRenamer(
            tmdb_api_key=tmdb_config.get("api_key", ""),
            naming_rules=config.get("naming_rules", config.get("naming", {})),
            config=config,
        )
        if tmdb_client:
            renamer.tmdb_client = tmdb_client

        metadata = renamer.extract_metadata(raw_path)

        title = metadata.get("show_name") or metadata.get("title") or None
        raw_year = metadata.get("year")
        year = int(raw_year) if raw_year and str(raw_year).strip().isdigit() else None
        season = int(metadata["season"]) if metadata.get("season") else None
        episode = int(metadata["episode"]) if metadata.get("episode") else None
        episode_title = metadata.get("episode_title") or None
        media_type = metadata.get("media_type")

        tmdb_matched = bool(metadata.get("tmdb_id"))
        suggested_name = None

        try:
            new_path = renamer.generate_new_path(metadata, original_path=file_path)
            if new_path:
                suggested_name = str(new_path.name)
        except Exception:
            pass

        return PreviewResponse(
            success=True,
            file_path=raw_path,
            original_name=original_name,
            suggested_name=suggested_name,
            media_type=media_type,
            metadata={
                "title": title,
                "season": season,
                "episode": episode,
                "year": year,
                "episode_title": episode_title,
                "tmdb_matched": tmdb_matched,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"预览重命名失败: {e}")
        detail = str(e) if not isinstance(e, HTTPException) else e.detail
        return PreviewResponse(
            success=False,
            file_path=request.file_path,
            original_name=Path(request.file_path).stem,
            error=detail,
        )


@router.post("/validate", response_model=ValidateResponse)
async def validate_scrape(request: ValidateRequest):
    """
    验证命名是否能被刮削识别（文件可不存
    在，仅测试命名解析和 TMDB 匹配）
    """
    try:
        raw_path = request.file_path.strip().strip('"').strip("'")
        file_path = Path(raw_path)
        file_exists = file_path.exists()

        original_name = file_path.stem if file_path.suffix else file_path.name
        parse_input = raw_path

        state = get_state_manager()
        config = state.get_config()
        tmdb_config = config.get("tmdb", {})

        from ...core.renamer import VideoRenamer
        from ...core.tmdb_client import TMDBClient

        tmdb_client = None
        if tmdb_config.get("api_key"):
            tmdb_client = TMDBClient(
                api_key=tmdb_config.get("api_key", ""),
                retry_count=tmdb_config.get("retry_count", 3),
                timeout=tmdb_config.get("timeout", 30),
                base_url=tmdb_config.get("base_url"),
            )

        renamer = VideoRenamer(
            tmdb_api_key=tmdb_config.get("api_key", ""),
            naming_rules=config.get("naming_rules", config.get("naming", {})),
            config=config,
        )
        if tmdb_client:
            renamer.tmdb_client = tmdb_client

        metadata = renamer.extract_metadata(parse_input)

        title = metadata.get("show_name") or metadata.get("title") or None
        raw_year = metadata.get("year")
        year = int(raw_year) if raw_year and str(raw_year).strip().isdigit() else None
        raw_season = metadata.get("season")
        season = int(raw_season) if raw_season else None
        raw_episode = metadata.get("episode")
        episode = int(raw_episode) if raw_episode else None
        episode_title = metadata.get("episode_title") or None
        media_type = metadata.get("media_type")
        quality_tags = metadata.get("quality_tags") or None
        release_group = metadata.get("release_group") or None

        tmdb_matched = False
        tmdb_info = None
        confidence = None
        suggested_name = None
        suggested_path = None

        if metadata.get("tmdb_id"):
            tmdb_matched = True
            tmdb_info = {
                "id": metadata.get("tmdb_id"),
                "title": title or metadata.get("show_name"),
                "overview": metadata.get("overview"),
            }

        try:
            new_path = renamer.generate_new_path(
                metadata,
                original_path=file_path,
            )
            if new_path:
                suggested_path = str(new_path)
                suggested_name = str(new_path.name)
        except Exception:
            pass

        return ValidateResponse(
            success=True,
            file_path=request.file_path,
            original_name=original_name,
            title=title,
            year=year,
            season=season,
            episode=episode,
            episode_title=episode_title,
            media_type=media_type,
            tmdb_matched=tmdb_matched,
            tmdb_info=tmdb_info,
            suggested_name=suggested_name,
            suggested_path=suggested_path,
            confidence=confidence,
            quality_tags=quality_tags,
            release_group=release_group,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证刮削失败: {e}")
        raise HTTPException(status_code=500, detail=f"验证刮削失败: {e}")


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
