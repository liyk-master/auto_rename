# -*- coding: utf-8 -*-
"""
emya 入库 API 接口

提供 RESTful API 接口用于视频入库操作
支持：电视剧入库、电影入库、查询等操作
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

from .db_manager import get_db, init_db
from .emya_service import EmyaService
from .emya_models import (
    VideoType,
    RelationType,
    ImageType,
    PathType,
)

logger = logging.getLogger(__name__)


# ============================================================
# 数据传输对象 (DTO)
# ============================================================

@dataclass
class ApiResponse:
    """API 响应基类"""
    success: bool
    message: str = ""
    data: Any = None
    error_code: Optional[str] = None


@dataclass
class VideoListDTO:
    """视频列表数据传输对象"""
    id: int
    title: str
    origin_title: Optional[str] = None
    video_type: str = "tv"
    description: Optional[str] = None
    date_air: Optional[str] = None
    runtime: Optional[int] = None
    tmdb_id: Optional[int] = None
    vote_average: Optional[float] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None


@dataclass
class SeasonDTO:
    """季数据传输对象"""
    id: int
    season_number: int
    title: Optional[str] = None
    episode_count: int = 0


@dataclass
class EpisodeDTO:
    """集数据传输对象"""
    id: int
    episode_number: int
    title: Optional[str] = None
    runtime: Optional[int] = None
    still_url: Optional[str] = None


@dataclass
class MediaDTO:
    """媒体资源数据传输对象"""
    id: int
    name: str
    path_url: str
    file_size: Optional[int] = None
    file_second: Optional[int] = None
    file_container: Optional[str] = None
    quality_tags: Optional[str] = None


@dataclass
class ImportTVRequest:
    """导入电视剧请求"""
    tmdb_id: int
    title: str
    library_id: int
    origin_title: Optional[str] = None
    description: Optional[str] = None
    date_air: Optional[str] = None
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    vote_average: Optional[float] = None
    genres: Optional[List[Dict]] = None
    seasons: List[Dict] = field(default_factory=list)
    media_files: List[Dict] = field(default_factory=list)
    # 快捷导入支持的字段
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    episode_title: Optional[str] = None
    media_url: Optional[str] = None


@dataclass
class ImportMovieRequest:
    """导入电影请求"""
    tmdb_id: int
    title: str
    library_id: int
    origin_title: Optional[str] = None
    description: Optional[str] = None
    date_air: Optional[str] = None
    runtime: Optional[int] = None
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    vote_average: Optional[float] = None
    genres: Optional[List[Dict]] = None
    media_files: List[Dict] = field(default_factory=list)


@dataclass
class ImportFromNameRequest:
    """
    从视频名称导入请求
    
    用于接收视频名称和HTTP地址，自动识别并入库
    只需要提供 video_name 和 media_url，系统会自动识别并分类
    """
    video_name: str  # 视频文件名（用于识别）
    media_url: str   # 视频HTTP地址
    library_id: Optional[int] = None  # 媒体库ID（可选，不传则自动选择）
    media_type_hint: Optional[str] = None  # 媒体类型提示（tv/movie/anime）
    path_type: str = PathType.URL  # 路径类型


# ============================================================
# API 控制器
# ============================================================

class EmyaApiController:
    """
    emya API 控制器

    提供入库相关的 API 接口方法
    """

    def __init__(
        self,
        db_config: Optional[Dict] = None,
        default_user_id: Optional[int] = None,
        tmdb_config: Optional[Dict] = None,
    ):
        """
        初始化控制器

        Args:
            db_config: 数据库配置，如果提供则会初始化数据库连接
            default_user_id: 默认用户ID
            tmdb_config: TMDB API 配置（用于视频识别）
        """
        if db_config:
            init_db(db_config)
        self.service = EmyaService(default_user_id=default_user_id)
        self.tmdb_config = tmdb_config
        self._renamer = None

    # ============================================================
    # 初始化接口
    # ============================================================

    def init_database(self, db_config: Dict) -> ApiResponse:
        """
        初始化数据库连接

        Args:
            db_config: 数据库配置

        Returns:
            ApiResponse
        """
        try:
            init_db(db_config)
            db = get_db()
            if db.test_connection():
                return ApiResponse(
                    success=True,
                    message="数据库连接成功",
                    data={"connected": True},
                )
            else:
                return ApiResponse(
                    success=False,
                    message="数据库连接失败",
                    error_code="DB_CONNECTION_FAILED",
                )
        except Exception as e:
            logger.error(f"初始化数据库失败: {e}")
            return ApiResponse(
                success=False,
                message=f"初始化数据库失败: {str(e)}",
                error_code="DB_INIT_ERROR",
            )

    # ============================================================
    # 媒体库接口
    # ============================================================

    def create_library(
        self, name: str, role: str = "public"
    ) -> ApiResponse:
        """
        创建媒体库

        Args:
            name: 媒体库名称（如"国产剧"、"外语电影"）
            role: 角色权限，默认 "public"

        Returns:
            ApiResponse
        """
        try:
            with self.service.db.session_scope() as session:
                library = self.service.get_or_create_library(
                    session, name, role
                )
                return ApiResponse(
                    success=True,
                    message="媒体库创建成功",
                    data={"id": library.id, "name": library.name, "role": library.role},
                )
        except Exception as e:
            logger.error(f"创建媒体库失败: {e}")
            return ApiResponse(
                success=False,
                message=f"创建媒体库失败: {str(e)}",
                error_code="CREATE_LIBRARY_ERROR",
            )

    def list_libraries(self) -> ApiResponse:
        """
        获取所有媒体库列表

        Returns:
            ApiResponse
        """
        try:
            with self.service.db.session_scope() as session:
                from .emya_models import Library
                from sqlalchemy import and_
                libraries = (
                    session.query(Library)
                    .filter(Library.deleted_at.is_(None))
                    .all()
                )
                data = [
                    {"id": lib.id, "name": lib.name, "role": lib.role}
                    for lib in libraries
                ]
                return ApiResponse(
                    success=True,
                    message="获取媒体库列表成功",
                    data=data,
                )
        except Exception as e:
            logger.error(f"获取媒体库列表失败: {e}")
            return ApiResponse(
                success=False,
                message=f"获取媒体库列表失败: {str(e)}",
                error_code="LIST_LIBRARIES_ERROR",
            )

    # ============================================================
    # 视频导入接口
    # ============================================================

    def import_tv_show(self, request: ImportTVRequest) -> ApiResponse:
        """
        导入电视剧

        Args:
            request: 导入请求

        Returns:
            ApiResponse
        """
        try:
            tmdb_data = {
                "tmdb_id": request.tmdb_id,
                "title": request.title,
                "origin_title": request.origin_title,
                "description": request.description,
                "date_air": request.date_air,
                "poster_path": request.poster_path,
                "backdrop_path": request.backdrop_path,
                "vote_average": request.vote_average,
                "genres": request.genres,
                "seasons": request.seasons,
            }

            # 处理快捷导入字段
            media_files = request.media_files or []
            if request.season_number and request.episode_number and request.media_url:
                # 快捷导入模式：自动创建季/集和媒体文件数据
                seasons = tmdb_data.get("seasons", [])
                season_found = False
                for season in seasons:
                    if season.get("season_number") == request.season_number:
                        season_found = True
                        episodes = season.get("episodes", [])
                        episode_found = False
                        for episode in episodes:
                            if episode.get("episode_number") == request.episode_number:
                                episode_found = True
                                break
                        if not episode_found:
                            episodes.append({
                                "episode_number": request.episode_number,
                                "title": request.episode_title or f"第{request.episode_number}集",
                            })
                        break
                
                if not season_found:
                    seasons.append({
                        "season_number": request.season_number,
                        "title": f"第{request.season_number}季",
                        "episodes": [{
                            "episode_number": request.episode_number,
                            "title": request.episode_title or f"第{request.episode_number}集",
                        }],
                    })
                tmdb_data["seasons"] = seasons

                media_files.append({
                    "season_number": request.season_number,
                    "episode_number": request.episode_number,
                    "name": f"{request.title} - S{request.season_number:02d}E{request.episode_number:02d}",
                    "path_url": request.media_url,
                    "path_type": "url",
                })

            video_list = self.service.import_tv_show(
                tmdb_data=tmdb_data,
                video_library_id=request.library_id,
                media_files=media_files,
            )

            return ApiResponse(
                success=True,
                message=f"电视剧 '{request.title}' 导入成功",
                data=VideoListDTO(
                    id=video_list.id,
                    title=video_list.title,
                    origin_title=video_list.origin_title,
                    video_type=video_list.video_type,
                    tmdb_id=video_list.tmdb_id,
                ),
            )
        except Exception as e:
            logger.error(f"导入电视剧失败: {e}")
            return ApiResponse(
                success=False,
                message=f"导入电视剧失败: {str(e)}",
                error_code="IMPORT_TV_ERROR",
            )

    def import_movie(self, request: ImportMovieRequest) -> ApiResponse:
        """
        导入电影

        Args:
            request: 导入请求

        Returns:
            ApiResponse
        """
        try:
            tmdb_data = {
                "tmdb_id": request.tmdb_id,
                "title": request.title,
                "origin_title": request.origin_title,
                "description": request.description,
                "date_air": request.date_air,
                "runtime": request.runtime,
                "poster_path": request.poster_path,
                "backdrop_path": request.backdrop_path,
                "vote_average": request.vote_average,
                "genres": request.genres,
            }

            video_list = self.service.import_movie(
                tmdb_data=tmdb_data,
                video_library_id=request.library_id,
                media_files=request.media_files,
            )

            return ApiResponse(
                success=True,
                message=f"电影 '{request.title}' 导入成功",
                data=VideoListDTO(
                    id=video_list.id,
                    title=video_list.title,
                    origin_title=video_list.origin_title,
                    video_type=video_list.video_type,
                    tmdb_id=video_list.tmdb_id,
                ),
            )
        except Exception as e:
            logger.error(f"导入电影失败: {e}")
            return ApiResponse(
                success=False,
                message=f"导入电影失败: {str(e)}",
                error_code="IMPORT_MOVIE_ERROR",
            )

    def import_from_metadata(
        self,
        metadata: Dict[str, Any],
        library_id: int,
        media_url: str,
        path_type: str = PathType.URL,
    ) -> ApiResponse:
        """
        从元数据导入（用于与 video_file_handler 集成）

        Args:
            metadata: 元数据字典
            library_id: 媒体库ID
            media_url: 媒体URL
            path_type: 路径类型

        Returns:
            ApiResponse
        """
        try:
            video_list = self.service.import_from_metadata(
                metadata=metadata,
                video_library_id=library_id,
                media_url=media_url,
                path_type=path_type,
            )

            return ApiResponse(
                success=True,
                message=f"'{metadata.get('show_name', 'Unknown')}' 导入成功",
                data={
                    "video_id": video_list.id,
                    "title": video_list.title,
                    "tmdb_id": video_list.tmdb_id,
                },
            )
        except Exception as e:
            logger.error(f"从元数据导入失败: {e}")
            return ApiResponse(
                success=False,
                message=f"从元数据导入失败: {str(e)}",
                error_code="IMPORT_METADATA_ERROR",
            )

    def import_from_video_name(
        self,
        video_name: str,
        media_url: str,
        library_id: Optional[int] = None,
        media_type_hint: Optional[str] = None,
        path_type: str = PathType.URL,
    ) -> ApiResponse:
        """
        从视频名称导入（自动识别视频信息并入库）

        接收视频文件名和HTTP地址，自动识别视频信息后入库

        Args:
            video_name: 视频文件名（用于识别）
            media_url: 视频HTTP地址
            library_id: 媒体库ID（可选，不传则根据识别类型自动选择）
            media_type_hint: 媒体类型提示（tv/movie/anime）
            path_type: 路径类型

        Returns:
            ApiResponse
        """
        try:
            # 延迟导入避免循环依赖
            from .renamer import VideoRenamer

            # 初始化 renamer（如果需要）
            if self._renamer is None:
                renamer_kwargs = {}
                if self.tmdb_config:
                    # VideoRenamer 接受 tmdb_api_key 参数
                    tmdb_api_key = self.tmdb_config.get("api_key")
                    if tmdb_api_key:
                        renamer_kwargs["tmdb_api_key"] = tmdb_api_key
                self._renamer = VideoRenamer(**renamer_kwargs)

            # 从视频名称提取元数据
            logger.info(f"正在识别视频: {video_name}")
            metadata = self._renamer.extract_metadata(
                file_path=video_name,
                media_type_hint=media_type_hint,
            )

            if not metadata:
                return ApiResponse(
                    success=False,
                    message=f"无法识别视频: {video_name}",
                    error_code="RECOGNITION_FAILED",
                )

            # 获取识别到的标题和类型
            title = metadata.get("show_name") or metadata.get("title")
            media_type = metadata.get("media_type", "tv")
            sub_category = metadata.get("sub_category", "")

            logger.info(
                f"识别结果: 标题={title}, 类型={media_type}, 子分类={sub_category}, "
                f"季={metadata.get('season')}, 集={metadata.get('episode')}"
            )

            # 如果没有指定 library_id，根据子分类自动选择媒体库
            if library_id is None:
                with self.service.db.session_scope() as session:
                    # 使用子分类作为媒体库名称（如"国产剧"、"日韩剧"、"外语电影"等）
                    library_name = sub_category if sub_category else ("电视剧" if media_type == "tv" else "电影")
                    library = self.service.get_or_create_library(
                        session, library_name
                    )
                    library_id = library.id
                    logger.info(f"自动选择媒体库: {library_name} (ID: {library_id})")

            # 调用入库服务
            video_list = self.service.import_from_metadata(
                metadata=metadata,
                video_library_id=library_id,
                media_url=media_url,
                path_type=path_type,
            )

            return ApiResponse(
                success=True,
                message=f"'{title}' 导入成功",
                data={
                    "video_id": video_list.id,
                    "title": video_list.title,
                    "tmdb_id": video_list.tmdb_id,
                    "media_type": media_type,
                    "sub_category": sub_category,
                    "recognized_name": title,
                    "season": metadata.get("season"),
                    "episode": metadata.get("episode"),
                },
            )
        except Exception as e:
            logger.error(f"从视频名称导入失败: {e}")
            import traceback
            traceback.print_exc()
            return ApiResponse(
                success=False,
                message=f"从视频名称导入失败: {str(e)}",
                error_code="IMPORT_FROM_NAME_ERROR",
            )

    def import_from_name_request(self, request: ImportFromNameRequest) -> ApiResponse:
        """
        从视频名称导入（使用请求对象）

        Args:
            request: 导入请求

        Returns:
            ApiResponse
        """
        return self.import_from_video_name(
            video_name=request.video_name,
            media_url=request.media_url,
            library_id=request.library_id,
            media_type_hint=request.media_type_hint,
            path_type=request.path_type,
        )

    # ============================================================
    # 查询接口
    # ============================================================

    def get_video(self, video_id: int) -> ApiResponse:
        """
        获取视频详情

        Args:
            video_id: 视频ID

        Returns:
            ApiResponse
        """
        try:
            with self.service.db.session_scope() as session:
                detail = self.service.get_video_detail(session, video_id)
                if detail is None:
                    return ApiResponse(
                        success=False,
                        message="视频不存在",
                        error_code="VIDEO_NOT_FOUND",
                    )
                return ApiResponse(
                    success=True,
                    message="获取视频详情成功",
                    data=detail,
                )
        except Exception as e:
            logger.error(f"获取视频详情失败: {e}")
            return ApiResponse(
                success=False,
                message=f"获取视频详情失败: {str(e)}",
                error_code="GET_VIDEO_ERROR",
            )

    def get_video_by_tmdb(self, tmdb_id: int, video_type: str = "tv") -> ApiResponse:
        """
        根据 TMDB ID 获取视频

        Args:
            tmdb_id: TMDB ID
            video_type: 视频类型

        Returns:
            ApiResponse
        """
        try:
            with self.service.db.session_scope() as session:
                video = self.service.get_video_by_tmdb_id(session, tmdb_id, video_type)
                if video is None:
                    return ApiResponse(
                        success=False,
                        message="视频不存在",
                        error_code="VIDEO_NOT_FOUND",
                    )
                return ApiResponse(
                    success=True,
                    message="获取视频成功",
                    data=VideoListDTO(
                        id=video.id,
                        title=video.title,
                        origin_title=video.origin_title,
                        video_type=video.video_type,
                        description=video.description,
                        date_air=video.date_air,
                        runtime=video.runtime,
                        tmdb_id=video.tmdb_id,
                        vote_average=video.vote_average,
                    ),
                )
        except Exception as e:
            logger.error(f"获取视频失败: {e}")
            return ApiResponse(
                success=False,
                message=f"获取视频失败: {str(e)}",
                error_code="GET_VIDEO_ERROR",
            )

    def search_videos(self, keyword: str, limit: int = 20) -> ApiResponse:
        """
        搜索视频

        Args:
            keyword: 关键词
            limit: 返回数量限制

        Returns:
            ApiResponse
        """
        try:
            with self.service.db.session_scope() as session:
                videos = self.service.search_video(session, keyword, limit)
                data = [
                    VideoListDTO(
                        id=v.id,
                        title=v.title,
                        origin_title=v.origin_title,
                        video_type=v.video_type,
                        date_air=v.date_air,
                        tmdb_id=v.tmdb_id,
                        vote_average=v.vote_average,
                    )
                    for v in videos
                ]
                return ApiResponse(
                    success=True,
                    message=f"找到 {len(data)} 个结果",
                    data=[asdict(d) for d in data],
                )
        except Exception as e:
            logger.error(f"搜索视频失败: {e}")
            return ApiResponse(
                success=False,
                message=f"搜索视频失败: {str(e)}",
                error_code="SEARCH_VIDEO_ERROR",
            )

    # ============================================================
    # 媒体资源接口
    # ============================================================

    def add_media(
        self,
        video_id: int,
        name: str,
        path_url: str,
        path_type: str = PathType.URL,
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        file_size: Optional[int] = None,
        file_second: Optional[int] = None,
        file_container: Optional[str] = None,
        quality_tags: Optional[str] = None,
    ) -> ApiResponse:
        """
        添加媒体资源

        Args:
            video_id: 视频ID
            name: 名称
            path_url: 播放地址
            path_type: 路径类型
            season_number: 季数（剧集）
            episode_number: 集数（剧集）
            file_size: 文件大小
            file_second: 时长(秒)
            file_container: 容器格式
            quality_tags: 质量标签

        Returns:
            ApiResponse
        """
        try:
            with self.service.db.session_scope() as session:
                # 获取视频信息
                from .emya_models import VideoList
                video = session.query(VideoList).filter(
                    VideoList.id == video_id
                ).first()

                if not video:
                    return ApiResponse(
                        success=False,
                        message="视频不存在",
                        error_code="VIDEO_NOT_FOUND",
                    )

                season_id = None
                episode_id = None

                # 如果是剧集，获取季和集ID
                if video.video_type == VideoType.TV and season_number and episode_number:
                    season = self.service.get_season(session, video_id, season_number)
                    if season:
                        season_id = season.id
                        episode = self.service.get_episode(session, season_id, episode_number)
                        if episode:
                            episode_id = episode.id

                media = self.service.create_media(
                    session=session,
                    name=name,
                    path_url=path_url,
                    path_type=path_type,
                    video_list_id=video_id if video.video_type == VideoType.MOVIE else video_id,
                    video_season_id=season_id,
                    video_episode_id=episode_id,
                    file_size=file_size,
                    file_second=file_second,
                    file_container=file_container,
                    quality_tags=quality_tags,
                )

                return ApiResponse(
                    success=True,
                    message="媒体资源添加成功",
                    data=MediaDTO(
                        id=media.id,
                        name=media.name,
                        path_url=media.path_url,
                        file_size=media.file_size,
                        file_second=media.file_second,
                        file_container=media.file_container,
                        quality_tags=media.quality_tags,
                    ),
                )
        except Exception as e:
            logger.error(f"添加媒体资源失败: {e}")
            return ApiResponse(
                success=False,
                message=f"添加媒体资源失败: {str(e)}",
                error_code="ADD_MEDIA_ERROR",
            )

    def add_subtitle(
        self,
        media_id: int,
        path_url: str,
        title: Optional[str] = None,
        language: Optional[str] = None,
        codec: Optional[str] = None,
    ) -> ApiResponse:
        """
        添加字幕

        Args:
            media_id: 媒体ID
            path_url: 字幕地址
            title: 字幕标题
            language: 语言
            codec: 编码格式

        Returns:
            ApiResponse
        """
        try:
            with self.service.db.session_scope() as session:
                subtitle = self.service.create_subtitle(
                    session=session,
                    video_media_id=media_id,
                    path_url=path_url,
                    title=title,
                    language=language,
                    codec=codec,
                )

                return ApiResponse(
                    success=True,
                    message="字幕添加成功",
                    data={"id": subtitle.id, "title": subtitle.title},
                )
        except Exception as e:
            logger.error(f"添加字幕失败: {e}")
            return ApiResponse(
                success=False,
                message=f"添加字幕失败: {str(e)}",
                error_code="ADD_SUBTITLE_ERROR",
            )


# ============================================================
# 快捷函数
# ============================================================

# 全局控制器实例
_controller: Optional[EmyaApiController] = None


def get_controller() -> EmyaApiController:
    """获取全局控制器实例"""
    global _controller
    if _controller is None:
        raise RuntimeError("EmyaApiController 未初始化，请先调用 init_controller()")
    return _controller


def init_controller(
    db_config: Dict,
    default_user_id: Optional[int] = None,
    tmdb_config: Optional[Dict] = None,
) -> EmyaApiController:
    """
    初始化全局控制器

    Args:
        db_config: 数据库配置
        default_user_id: 默认用户ID
        tmdb_config: TMDB API 配置（用于视频识别）

    Returns:
        EmyaApiController 实例
    """
    global _controller
    _controller = EmyaApiController(
        db_config=db_config,
        default_user_id=default_user_id,
        tmdb_config=tmdb_config,
    )
    return _controller


# ============================================================
# 便捷 API 函数
# ============================================================

def quick_import_tv(
    tmdb_id: int,
    title: str,
    library_name: str = "电视剧",
    library_role: str = "public",
    **kwargs,
) -> ApiResponse:
    """
    快捷导入电视剧

    Args:
        tmdb_id: TMDB ID
        title: 标题
        library_name: 媒体库名称（如"国产剧"、"日韩剧"）
        library_role: 角色权限，默认 "public"
        **kwargs: 其他参数

    Returns:
        ApiResponse
    """
    controller = get_controller()

    # 创建或获取媒体库
    with controller.service.db.session_scope() as session:
        library = controller.service.get_or_create_library(
            session, library_name, library_role
        )
        library_id = library.id

    request = ImportTVRequest(
        tmdb_id=tmdb_id,
        title=title,
        library_id=library_id,
        **kwargs,
    )

    return controller.import_tv_show(request)


def quick_import_movie(
    tmdb_id: int,
    title: str,
    library_name: str = "电影",
    library_role: str = "public",
    **kwargs,
) -> ApiResponse:
    """
    快捷导入电影

    Args:
        tmdb_id: TMDB ID
        title: 标题
        library_name: 媒体库名称（如"外语电影"、"国产电影"）
        library_role: 角色权限，默认 "public"
        **kwargs: 其他参数

    Returns:
        ApiResponse
    """
    controller = get_controller()

    # 创建或获取媒体库
    with controller.service.db.session_scope() as session:
        library = controller.service.get_or_create_library(
            session, library_name, library_role
        )
        library_id = library.id

    request = ImportMovieRequest(
        tmdb_id=tmdb_id,
        title=title,
        library_id=library_id,
        **kwargs,
    )

    return controller.import_movie(request)


def quick_import_from_name(
    video_name: str,
    media_url: str,
    media_type_hint: Optional[str] = None,
    path_type: str = PathType.URL,
) -> ApiResponse:
    """
    快捷从视频名称导入（自动识别并入库）

    只需要提供视频文件名和HTTP地址，系统自动识别视频类型并选择合适的媒体库

    Args:
        video_name: 视频文件名（用于识别）
        media_url: 视频HTTP地址
        media_type_hint: 媒体类型提示（tv/movie/anime，可选）
        path_type: 路径类型

    Returns:
        ApiResponse
    """
    controller = get_controller()

    return controller.import_from_video_name(
        video_name=video_name,
        media_url=media_url,
        library_id=None,  # 自动选择媒体库
        media_type_hint=media_type_hint,
        path_type=path_type,
    )
