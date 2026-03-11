# -*- coding: utf-8 -*-
"""
emya 入库服务

提供视频元数据入库到 emya 数据库的核心逻辑
支持电视剧和电影的完整入库流程
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_

from .emya_models import (
    Library,
    VideoList,
    VideoSeason,
    VideoEpisode,
    VideoMedia,
    VideoSubtitle,
    VideoImage,
    VideoListTitleAlias,
    VideoGenre,
    VideoPeople,
    RelationType,
    ImageType,
    PathType,
    VideoType,
)
from .db_manager import get_db

logger = logging.getLogger(__name__)


class EmyaService:
    """emya 入库服务"""

    def __init__(self, default_user_id: Optional[int] = None):
        """
        初始化服务

        Args:
            default_user_id: 默认用户ID（用于上传者标识）
        """
        self.db = get_db()
        self.default_user_id = default_user_id

    def _is_valid_date(self, date_str: str) -> bool:
        """
        检查日期字符串是否为有效的日期格式

        Args:
            date_str: 日期字符串

        Returns:
            是否有效
        """
        import re
        # 支持 YYYY-MM-DD 或 YYYY-MM-DD 格式
        pattern = r'^\d{4}-\d{2}-\d{2}$'
        if re.match(pattern, date_str):
            try:
                from datetime import datetime
                datetime.strptime(date_str, '%Y-%m-%d')
                return True
            except ValueError:
                return False
        return False

    # ============================================================
    # 媒体库操作
    # ============================================================

    def get_or_create_library(
        self,
        session: Session,
        name: str,
        role: str = "public",
    ) -> Library:
        """
        获取或创建媒体库

        Args:
            session: 数据库会话
            name: 媒体库名称（如"国产剧"、"外语电影"）
            role: 角色权限，默认 "public"

        Returns:
            Library 实例
        """
        library = session.query(Library).filter(
            and_(Library.name == name, Library.deleted_at.is_(None))
        ).first()

        if library is None:
            library = Library(
                name=name,
                role=role,
            )
            session.add(library)
            session.flush()
            logger.info(f"创建媒体库: {name} (ID: {library.id})")
        else:
            logger.debug(f"媒体库已存在: {name} (ID: {library.id})")

        return library

    def get_library_by_id(self, session: Session, library_id: int) -> Optional[Library]:
        """根据ID获取媒体库"""
        return session.query(Library).filter(
            and_(Library.id == library_id, Library.deleted_at.is_(None))
        ).first()

    # ============================================================
    # 视频列表操作
    # ============================================================

    def get_video_by_tmdb_id(
        self, session: Session, tmdb_id: int, video_type: str
    ) -> Optional[VideoList]:
        """
        根据 TMDB ID 获取视频

        Args:
            session: 数据库会话
            tmdb_id: TMDB ID
            video_type: 视频类型 (tv/movie)

        Returns:
            VideoList 实例或 None
        """
        return session.query(VideoList).filter(
            and_(
                VideoList.tmdb_id == tmdb_id,
                VideoList.video_type == video_type,
                VideoList.deleted_at.is_(None),
            )
        ).first()

    def create_video_list(
        self,
        session: Session,
        video_library_id: Optional[int],
        video_type: str,
        title: str,
        origin_title: Optional[str] = None,
        description: Optional[str] = None,
        date_air: Optional[str] = None,
        runtime: Optional[int] = None,
        tmdb_id: Optional[str] = None,
        tagline: Optional[str] = None,
        genres: Optional[List[Dict]] = None,
        peoples: Optional[List[Dict]] = None,
        upcoming: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> VideoList:
        """
        创建视频列表

        Args:
            session: 数据库会话
            video_library_id: 媒体库ID
            video_type: 类型 (tv/movie)
            title: 标题
            origin_title: 原始标题
            description: 简介
            date_air: 上映日期
            runtime: 时长(分钟)
            tmdb_id: TMDB ID
            tagline: 标语
            genres: 类型列表
            peoples: 人物列表
            upcoming: 即将上映
            remark: 备注

        Returns:
            VideoList 实例
        """
        # 处理日期格式：确保是有效的日期格式
        if date_air:
            # 如果只是年份（4位数字），转换为 YYYY-01-01
            if isinstance(date_air, str) and len(date_air) == 4 and date_air.isdigit():
                date_air = f"{date_air}-01-01"
            # 如果日期格式不正确，设为 None
            elif isinstance(date_air, str) and not self._is_valid_date(date_air):
                logger.warning(f"无效的日期格式: {date_air}，将设为 None")
                date_air = None

        video_list = VideoList(
            video_library_id=video_library_id,
            video_type=video_type,
            title=title,
            origin_title=origin_title,
            description=description,
            date_air=date_air,
            runtime=runtime,
            tmdb_id=tmdb_id,
            tagline=tagline,
            genres=genres,
            peoples=peoples,
            upcoming=upcoming,
            remark=remark,
        )
        session.add(video_list)
        session.flush()
        logger.info(f"创建视频: {title} (ID: {video_list.id}, TMDB: {tmdb_id})")
        return video_list

    def update_video_list(
        self, session: Session, video_list: VideoList, **kwargs
    ) -> VideoList:
        """
        更新视频列表

        Args:
            session: 数据库会话
            video_list: VideoList 实例
            **kwargs: 要更新的字段

        Returns:
            更新后的 VideoList 实例
        """
        for key, value in kwargs.items():
            if hasattr(video_list, key) and value is not None:
                setattr(video_list, key, value)
        session.flush()
        logger.debug(f"更新视频: {video_list.title} (ID: {video_list.id})")
        return video_list

    def add_title_alias(
        self,
        session: Session,
        video_list_id: int,
        title: str,
        language: Optional[str] = None,
    ) -> VideoListTitleAlias:
        """
        添加标题别名

        Args:
            session: 数据库会话
            video_list_id: 视频ID
            title: 别名
            language: 语言

        Returns:
            VideoListTitleAlias 实例
        """
        # 检查是否已存在
        existing = session.query(VideoListTitleAlias).filter(
            and_(
                VideoListTitleAlias.video_list_id == video_list_id,
                VideoListTitleAlias.title == title,
                VideoListTitleAlias.deleted_at.is_(None),
            )
        ).first()

        if existing:
            return existing

        alias = VideoListTitleAlias(
            video_list_id=video_list_id,
            title=title,
            language=language,
        )
        session.add(alias)
        session.flush()
        return alias

    # ============================================================
    # 季操作
    # ============================================================

    def get_season(
        self, session: Session, video_list_id: int, season_number: int
    ) -> Optional[VideoSeason]:
        """获取指定季"""
        return session.query(VideoSeason).filter(
            and_(
                VideoSeason.video_list_id == video_list_id,
                VideoSeason.season_number == season_number,
                VideoSeason.deleted_at.is_(None),
            )
        ).first()

    def create_season(
        self,
        session: Session,
        video_list_id: int,
        season_number: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        date_air: Optional[str] = None,
        season_number_custom: Optional[int] = None,
    ) -> VideoSeason:
        """
        创建电视季

        Args:
            session: 数据库会话
            video_list_id: 视频ID
            season_number: 季数
            title: 标题
            description: 简介
            date_air: 上映日期
            season_number_custom: 自定义季数

        Returns:
            VideoSeason 实例
        """
        # 确保 season_number 是整数
        try:
            season_number = int(season_number) if season_number is not None else 1
        except (ValueError, TypeError):
            season_number = 1

        season = VideoSeason(
            video_list_id=video_list_id,
            season_number=season_number,
            title=title or f"第{season_number}季",
            description=description,
            date_air=date_air,
            season_number_custom=season_number_custom,
        )
        session.add(season)
        session.flush()
        logger.info(
            f"创建季: S{season_number:02d} (ID: {season.id}, Video: {video_list_id})"
        )
        return season

    # ============================================================
    # 集操作
    # ============================================================

    def get_episode(
        self, session: Session, video_season_id: int, episode_number: int
    ) -> Optional[VideoEpisode]:
        """获取指定集"""
        return session.query(VideoEpisode).filter(
            and_(
                VideoEpisode.video_season_id == video_season_id,
                VideoEpisode.episode_number == episode_number,
                VideoEpisode.deleted_at.is_(None),
            )
        ).first()

    def create_episode(
        self,
        session: Session,
        video_list_id: int,
        video_season_id: int,
        episode_number: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        date_air: Optional[str] = None,
        runtime: Optional[int] = None,
        poster: Optional[str] = None,
        still: Optional[str] = None,
        tmdb_id: Optional[int] = None,
        imdb_id: Optional[str] = None,
    ) -> VideoEpisode:
        """
        创建电视集

        Args:
            session: 数据库会话
            video_list_id: 视频ID
            video_season_id: 季ID
            episode_number: 集数
            title: 标题
            description: 简介
            date_air: 上映日期
            runtime: 时长(分钟)
            poster: 海报路径
            still: 剧照路径
            tmdb_id: TMDB ID
            imdb_id: IMDB ID

        Returns:
            VideoEpisode 实例
        """
        # 确保 episode_number 是整数
        try:
            episode_number = int(episode_number) if episode_number is not None else 1
        except (ValueError, TypeError):
            episode_number = 1

        episode = VideoEpisode(
            video_list_id=video_list_id,
            video_season_id=video_season_id,
            episode_number=episode_number,
            title=title or f"第{episode_number}集",
            description=description,
            date_air=date_air,
            runtime=runtime,
            poster=poster,
            still=still,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )
        session.add(episode)
        session.flush()
        logger.info(
            f"创建集: E{episode_number:02d} (ID: {episode.id}, Season: {video_season_id})"
        )
        return episode

    # ============================================================
    # 媒体资源操作
    # ============================================================

    def create_media(
        self,
        session: Session,
        name: str,
        path_url: str,
        path_type: str = PathType.URL,
        video_list_id: Optional[int] = None,
        video_season_id: Optional[int] = None,
        video_episode_id: Optional[int] = None,
        user_id: Optional[int] = None,
        status: str = "active",
        file_size: Optional[int] = None,
        file_second: Optional[int] = None,
        file_container: Optional[str] = None,
        file_resolution: Optional[str] = None,
        file_matadata: Optional[dict] = None,
        file_chapters: Optional[dict] = None,
        number_view: Optional[int] = 0,
    ) -> VideoMedia:
        """
        创建媒体资源

        Args:
            session: 数据库会话
            name: 名称
            path_url: 播放地址
            path_type: 路径类型
            video_list_id: 视频ID（电影）
            video_season_id: 季ID
            video_episode_id: 集ID（剧集）
            user_id: 上传用户ID
            status: 状态
            file_size: 文件大小
            file_second: 时长(秒)
            file_container: 容器格式
            file_resolution: 分辨率
            file_matadata: 文件元数据
            file_chapters: 章节信息
            number_view: 观看次数

        Returns:
            VideoMedia 实例
        """
        media = VideoMedia(
            uuid=str(uuid.uuid4()),
            video_list_id=video_list_id,
            video_season_id=video_season_id,
            video_episode_id=video_episode_id,
            user_id=user_id or self.default_user_id,
            name=name,
            status=status,
            file_size=file_size,
            file_second=file_second,
            file_container=file_container,
            file_resolution=file_resolution,
            file_matadata=file_matadata,
            file_chapters=file_chapters,
            path_type=path_type,
            path_url=path_url,
            number_view=number_view,
        )
        session.add(media)
        session.flush()
        logger.info(f"创建媒体资源: {name} (ID: {media.id})")
        return media

    def get_media_by_episode(
        self, session: Session, video_episode_id: int
    ) -> List[VideoMedia]:
        """获取剧集的所有媒体资源"""
        return session.query(VideoMedia).filter(
            and_(
                VideoMedia.video_episode_id == video_episode_id,
                VideoMedia.deleted_at.is_(None),
            )
        ).all()

    def get_media_by_video_list(
        self, session: Session, video_list_id: int
    ) -> List[VideoMedia]:
        """获取电影的所有媒体资源"""
        return session.query(VideoMedia).filter(
            and_(
                VideoMedia.video_list_id == video_list_id,
                VideoMedia.video_episode_id.is_(None),
                VideoMedia.deleted_at.is_(None),
            )
        ).all()

    # ============================================================
    # 字幕操作
    # ============================================================

    def create_subtitle(
        self,
        session: Session,
        video_media_id: int,
        path_url: str,
        path_type: str = PathType.URL,
        title: Optional[str] = None,
        codec: Optional[str] = None,
        language: Optional[str] = None,
        user_id: Optional[int] = None,
        is_default: int = 0,
    ) -> VideoSubtitle:
        """
        创建字幕

        Args:
            session: 数据库会话
            video_media_id: 媒体ID
            path_url: 字幕地址
            path_type: 路径类型
            title: 字幕标题
            codec: 编码格式
            language: 语言
            user_id: 上传用户ID
            is_default: 是否默认

        Returns:
            VideoSubtitle 实例
        """
        subtitle = VideoSubtitle(
            video_media_id=video_media_id,
            user_id=user_id or self.default_user_id,
            title=title,
            codec=codec,
            path_type=path_type,
            path_url=path_url,
            language=language,
            is_default=is_default,
        )
        session.add(subtitle)
        session.flush()
        logger.info(f"创建字幕: {title} (ID: {subtitle.id})")
        return subtitle

    # ============================================================
    # 图片操作
    # ============================================================

    def create_image(
        self,
        session: Session,
        relation_type: str,
        relation_id: int,
        path_url: str,
        image_type: str = ImageType.PRIMARY,
        path_type: str = PathType.TMDB,
    ) -> VideoImage:
        """
        创建图片

        Args:
            session: 数据库会话
            relation_type: 关联类型 (vl/vs/ve)
            relation_id: 关联ID
            path_url: 图片路径
            image_type: 图片类型 (Primary/Backdrop/Thumb/Logo)
            path_type: 路径类型 (tmdb/douban/url)

        Returns:
            VideoImage 实例
        """
        # 检查是否已存在相同类型的图片
        existing = session.query(VideoImage).filter(
            and_(
                VideoImage.relation_type == relation_type,
                VideoImage.relation_id == relation_id,
                VideoImage.type == image_type,
                VideoImage.path_url == path_url,
                VideoImage.deleted_at.is_(None),
            )
        ).first()

        if existing:
            return existing

        image = VideoImage(
            type=image_type,
            relation_type=relation_type,
            relation_id=relation_id,
            path_type=path_type,
            path_url=path_url,
        )
        session.add(image)
        session.flush()
        return image

    def add_poster(
        self,
        session: Session,
        relation_type: str,
        relation_id: int,
        poster_path: str,
        path_type: str = PathType.TMDB,
    ):
        """添加海报"""
        return self.create_image(
            session=session,
            relation_type=relation_type,
            relation_id=relation_id,
            path_url=poster_path,
            image_type=ImageType.PRIMARY,
            path_type=path_type,
        )

    def add_backdrop(
        self,
        session: Session,
        relation_type: str,
        relation_id: int,
        backdrop_path: str,
        path_type: str = PathType.TMDB,
    ):
        """添加背景图"""
        return self.create_image(
            session=session,
            relation_type=relation_type,
            relation_id=relation_id,
            path_url=backdrop_path,
            image_type=ImageType.BACKDROP,
            path_type=path_type,
        )

    def add_still(
        self,
        session: Session,
        relation_type: str,
        relation_id: int,
        still_path: str,
        path_type: str = PathType.TMDB,
    ):
        """添加剧照"""
        return self.create_image(
            session=session,
            relation_type=relation_type,
            relation_id=relation_id,
            path_url=still_path,
            image_type=ImageType.THUMB,
            path_type=path_type,
        )

    # ============================================================
    # 类型操作
    # ============================================================

    def create_genre(
        self,
        session: Session,
        tmdb_id: int,
        name: str,
    ) -> VideoGenre:
        """
        创建或获取类型

        Args:
            session: 数据库会话
            tmdb_id: TMDB 类型 ID
            name: 类型名称

        Returns:
            VideoGenre 实例
        """
        # 检查是否已存在
        genre = session.query(VideoGenre).filter(
            VideoGenre.tmdb_id == tmdb_id
        ).first()

        if genre:
            return genre

        genre = VideoGenre(
            tmdb_id=tmdb_id,
            name=name,
        )
        session.add(genre)
        session.flush()
        logger.debug(f"创建类型: {name} (TMDB ID: {tmdb_id})")
        return genre

    def create_genres_from_list(
        self,
        session: Session,
        genres: List[Any],
    ) -> List[VideoGenre]:
        """
        从类型列表创建类型记录

        支持多种格式：
        - [{"id": 1, "name": "动作"}, ...]  # TMDB 标准格式
        - ["动作", "科幻", ...]  # 名称列表格式

        Args:
            session: 数据库会话
            genres: 类型列表

        Returns:
            VideoGenre 列表
        """
        if not genres:
            return []

        created_genres = []
        for genre_data in genres:
            if isinstance(genre_data, dict):
                # TMDB 标准格式: {"id": 1, "name": "动作"}
                tmdb_id = genre_data.get("id")
                name = genre_data.get("name", "")
            elif isinstance(genre_data, str):
                # 名称列表格式: "动作"
                # 使用名称的哈希值作为临时 tmdb_id（负数表示非标准）
                name = genre_data.strip()
                tmdb_id = -abs(hash(name)) % (10 ** 9)  # 生成一个负数的伪 ID
            elif isinstance(genre_data, int):
                # 只有 ID 的情况
                tmdb_id = genre_data
                name = str(genre_data)
            else:
                continue

            if name:
                try:
                    genre = self.create_genre(session, tmdb_id, name)
                    created_genres.append(genre)
                except Exception as e:
                    logger.warning(f"创建类型失败: {name}, 错误: {e}")

        return created_genres

    # ============================================================
    # 高级入库方法
    # ============================================================

    def import_tv_show(
        self,
        tmdb_data: Dict[str, Any],
        video_library_id: int,
        media_files: Optional[List[Dict[str, Any]]] = None,
        subtitles: Optional[List[Dict[str, Any]]] = None,
    ) -> VideoList:
        """
        导入电视剧完整信息

        Args:
            tmdb_data: TMDB 数据，包含剧集信息、季信息、集信息
            video_library_id: 媒体库ID
            media_files: 媒体文件列表
            subtitles: 字幕列表

        Returns:
            VideoList 实例
        """
        with self.db.session_scope() as session:
            # 1. 创建视频列表
            video_list = self.get_video_by_tmdb_id(
                session, tmdb_data["tmdb_id"], VideoType.TV
            )

            if video_list is None:
                video_list = self.create_video_list(
                    session=session,
                    video_library_id=video_library_id,
                    video_type=VideoType.TV,
                    title=tmdb_data.get("title"),
                    origin_title=tmdb_data.get("origin_title"),
                    description=tmdb_data.get("description"),
                    date_air=tmdb_data.get("date_air"),
                    runtime=tmdb_data.get("runtime"),
                    tmdb_id=str(tmdb_data.get("tmdb_id")) if tmdb_data.get("tmdb_id") else None,
                    tagline=tmdb_data.get("tagline"),
                    genres=tmdb_data.get("genres"),
                    peoples=tmdb_data.get("peoples"),
                )

            # 1.1 添加海报和背景（无论视频是否新建都尝试添加）
            if tmdb_data.get("poster_path"):
                self.add_poster(
                    session, RelationType.VIDEO_LIST, video_list.id,
                    tmdb_data["poster_path"]
                )
            if tmdb_data.get("backdrop_path"):
                self.add_backdrop(
                    session, RelationType.VIDEO_LIST, video_list.id,
                    tmdb_data["backdrop_path"]
                )

            # 1.5 创建类型记录
            if tmdb_data.get("genres"):
                self.create_genres_from_list(session, tmdb_data["genres"])

            # 2. 创建季和集
            seasons_data = tmdb_data.get("seasons", [])
            for season_data in seasons_data:
                season_number = season_data.get("season_number")
                if season_number == 0:  # 跳过特别篇
                    continue

                season = self.get_season(session, video_list.id, season_number)
                if season is None:
                    season = self.create_season(
                        session=session,
                        video_list_id=video_list.id,
                        season_number=season_number,
                        title=season_data.get("title"),
                        description=season_data.get("description"),
                        date_air=season_data.get("date_air"),
                    )

                # 添加季海报（无论季是否新建都尝试添加）
                if season_data.get("poster"):
                    self.add_poster(
                        session, RelationType.VIDEO_SEASON, season.id,
                        season_data["poster"]
                    )

                # 创建集
                episodes_data = season_data.get("episodes", [])
                for episode_data in episodes_data:
                    episode_number = episode_data.get("episode_number")
                    episode = self.get_episode(session, season.id, episode_number)

                    if episode is None:
                        episode = self.create_episode(
                            session=session,
                            video_list_id=video_list.id,
                            video_season_id=season.id,
                            episode_number=episode_number,
                            title=episode_data.get("title"),
                            description=episode_data.get("description"),
                            date_air=episode_data.get("date_air"),
                            runtime=episode_data.get("runtime"),
                            still=episode_data.get("still"),
                            tmdb_id=episode_data.get("tmdb_id"),
                        )

                    # 添加集剧照（无论集是否新建都尝试添加）
                    if episode_data.get("still"):
                        self.add_still(
                            session, RelationType.VIDEO_EPISODE, episode.id,
                            episode_data["still"]
                        )

            # 3. 添加媒体资源
            if media_files:
                for media_file in media_files:
                    season_num = media_file.get("season_number")
                    episode_num = media_file.get("episode_number")

                    season = self.get_season(session, video_list.id, season_num)
                    if season:
                        episode = self.get_episode(session, season.id, episode_num)
                        if episode:
                            self.create_media(
                                session=session,
                                name=media_file.get("name"),
                                path_url=media_file.get("path_url"),
                                path_type=media_file.get("path_type", PathType.URL),
                                video_list_id=video_list.id,
                                video_season_id=season.id,
                                video_episode_id=episode.id,
                                file_size=media_file.get("file_size"),
                                file_second=media_file.get("file_second"),
                                file_container=media_file.get("file_container"),
                                file_resolution=media_file.get("file_resolution"),
                                file_matadata=media_file.get("file_matadata"),
                                file_chapters=media_file.get("file_chapters"),
                            )

            # 将对象从 session 分离，使其在 session 关闭后仍可访问
            session.expunge(video_list)
            return video_list

    def import_movie(
        self,
        tmdb_data: Dict[str, Any],
        video_library_id: int,
        media_files: Optional[List[Dict[str, Any]]] = None,
        subtitles: Optional[List[Dict[str, Any]]] = None,
    ) -> VideoList:
        """
        导入电影完整信息

        Args:
            tmdb_data: TMDB 数据
            video_library_id: 媒体库ID
            media_files: 媒体文件列表
            subtitles: 字幕列表

        Returns:
            VideoList 实例
        """
        with self.db.session_scope() as session:
            # 1. 创建视频列表
            video_list = self.get_video_by_tmdb_id(
                session, tmdb_data["tmdb_id"], VideoType.MOVIE
            )

            if video_list is None:
                video_list = self.create_video_list(
                    session=session,
                    video_library_id=video_library_id,
                    video_type=VideoType.MOVIE,
                    title=tmdb_data.get("title"),
                    origin_title=tmdb_data.get("origin_title"),
                    description=tmdb_data.get("description"),
                    date_air=tmdb_data.get("date_air"),
                    runtime=tmdb_data.get("runtime"),
                    tmdb_id=str(tmdb_data.get("tmdb_id")) if tmdb_data.get("tmdb_id") else None,
                    tagline=tmdb_data.get("tagline"),
                    genres=tmdb_data.get("genres"),
                    peoples=tmdb_data.get("peoples"),
                )

                # 添加海报和背景
                if tmdb_data.get("poster_path"):
                    self.add_poster(
                        session, RelationType.VIDEO_LIST, video_list.id,
                        tmdb_data["poster_path"]
                    )
                if tmdb_data.get("backdrop_path"):
                    self.add_backdrop(
                        session, RelationType.VIDEO_LIST, video_list.id,
                        tmdb_data["backdrop_path"]
                    )

            # 1.5 创建类型记录
            if tmdb_data.get("genres"):
                self.create_genres_from_list(session, tmdb_data["genres"])

            # 2. 添加媒体资源（电影直接关联 video_list）
            if media_files:
                for media_file in media_files:
                    self.create_media(
                        session=session,
                        name=media_file.get("name"),
                        path_url=media_file.get("path_url"),
                        path_type=media_file.get("path_type", PathType.URL),
                        video_list_id=video_list.id,
                        file_size=media_file.get("file_size"),
                        file_second=media_file.get("file_second"),
                        file_container=media_file.get("file_container"),
                        file_resolution=media_file.get("file_resolution"),
                        file_matadata=media_file.get("file_matadata"),
                        file_chapters=media_file.get("file_chapters"),
                    )

            # 将对象从 session 分离，使其在 session 关闭后仍可访问
            session.expunge(video_list)
            return video_list

    def import_from_metadata(
        self,
        metadata: Dict[str, Any],
        video_library_id: int,
        media_url: str,
        path_type: str = PathType.URL,
        default_tv_library: str = "电视剧",
        default_movie_library: str = "电影",
    ) -> VideoList:
        """
        从现有元数据导入（与 video_file_handler.py 集成）

        Args:
            metadata: 元数据字典（来自 renamer.py）
            video_library_id: 媒体库ID，为 0 或 None 时自动创建/获取默认媒体库
            media_url: 媒体URL
            path_type: 路径类型
            default_tv_library: 默认电视剧媒体库名称
            default_movie_library: 默认电影媒体库名称

        Returns:
            VideoList 实例
        """
        video_type = metadata.get("media_type", "tv")
        tmdb_id = metadata.get("tmdb_id")

        # 处理日期格式：year 可能只是年份，需要转换为完整日期
        year_value = metadata.get("year")
        date_air = None
        if year_value:
            # 如果只是年份，转换为 YYYY-01-01 格式
            if isinstance(year_value, str) and len(year_value) == 4 and year_value.isdigit():
                date_air = f"{year_value}-01-01"
            else:
                date_air = year_value

        # 构建 TMDB 数据格式
        tmdb_data = {
            "tmdb_id": tmdb_id,
            "title": metadata.get("show_name") or metadata.get("title"),
            "origin_title": metadata.get("origin_title"),
            "description": metadata.get("description"),
            "date_air": date_air,
            "runtime": metadata.get("runtime"),
            "poster_path": metadata.get("poster_path"),
            "backdrop_path": metadata.get("backdrop_path"),
            "genres": metadata.get("genres"),
            "origin_country": metadata.get("origin_country"),
            "vote_average": metadata.get("vote_average"),
            "peoples": metadata.get("peoples"),
            "tagline": metadata.get("tagline"),
        }

        # 构建媒体文件信息
        media_files = [
            {
                "name": metadata.get("show_name", "Unknown"),
                "path_url": media_url,
                "path_type": path_type,
                "season_number": metadata.get("season"),
                "episode_number": metadata.get("episode"),
                "file_size": metadata.get("file_size"),
                "file_second": metadata.get("duration"),
                "file_container": metadata.get("container"),
                "file_resolution": metadata.get("quality_tags"),  # 使用 quality_tags 作为分辨率
            }
        ]

        # 如果 video_library_id 为 0 或 None，自动创建或获取默认媒体库
        if not video_library_id:
            with self.db.session_scope() as session:
                library_name = default_tv_library if video_type == VideoType.TV else default_movie_library
                library_role = "tv" if video_type == VideoType.TV else "movie"
                library = self.get_or_create_library(session, library_name, library_role)
                video_library_id = library.id
                logger.info(f"使用默认媒体库: {library_name} (ID: {video_library_id})")

        if video_type == VideoType.TV:
            # 构建季和集信息
            # 使用 TMDB 返回的季信息（包含季海报）
            seasons_info = metadata.get("seasons_info", [])
            current_season = metadata.get("season", 1)
            current_episode = metadata.get("episode", 1)

            # 确保 current_season 是整数
            try:
                current_season = int(current_season) if current_season is not None else 1
            except (ValueError, TypeError):
                current_season = 1

            logger.info(f"处理季信息: current_season={current_season}, seasons_info={seasons_info}")

            # 查找当前季的信息
            current_season_info = None
            for s in seasons_info:
                s_num = s.get("season_number")
                # 确保 s_num 也是整数进行比较
                try:
                    s_num = int(s_num) if s_num is not None else 0
                except (ValueError, TypeError):
                    s_num = 0
                if s_num == current_season:
                    current_season_info = s
                    logger.info(f"找到当前季信息: {s}")
                    break

            # 构建季数据
            season_poster = None
            if current_season_info:
                season_poster = current_season_info.get("poster_path")
                logger.info(f"季海报路径: {season_poster}")
            else:
                logger.warning(f"未找到季 {current_season} 的信息")

            tmdb_data["seasons"] = [
                {
                    "season_number": current_season,
                    "poster": season_poster,
                    "episodes": [
                        {
                            "episode_number": current_episode,
                            "title": metadata.get("episode_title"),
                            "description": metadata.get("episode_overview"),
                            "runtime": metadata.get("runtime"),
                            "still": metadata.get("still_path"),
                            "date_air": metadata.get("air_date"),
                        }
                    ],
                }
            ]
            return self.import_tv_show(tmdb_data, video_library_id, media_files)
        else:
            return self.import_movie(tmdb_data, video_library_id, media_files)

    # ============================================================
    # 查询方法
    # ============================================================

    def search_video(
        self, session: Session, keyword: str, limit: int = 20
    ) -> List[VideoList]:
        """
        搜索视频

        Args:
            session: 数据库会话
            keyword: 关键词
            limit: 返回数量限制

        Returns:
            VideoList 列表
        """
        return (
            session.query(VideoList)
            .filter(
                and_(
                    VideoList.title.like(f"%{keyword}%"),
                    VideoList.deleted_at.is_(None),
                )
            )
            .limit(limit)
            .all()
        )

    def get_video_detail(
        self, session: Session, video_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        获取视频详情（包含季、集、媒体信息）

        Args:
            session: 数据库会话
            video_id: 视频ID

        Returns:
            视频详情字典
        """
        video_list = session.query(VideoList).filter(
            and_(VideoList.id == video_id, VideoList.deleted_at.is_(None))
        ).first()

        if not video_list:
            return None

        result = {
            "id": video_list.id,
            "title": video_list.title,
            "origin_title": video_list.origin_title,
            "description": video_list.description,
            "video_type": video_list.video_type,
            "date_air": video_list.date_air,
            "runtime": video_list.runtime,
            "tmdb_id": video_list.tmdb_id,
            "vote_average": video_list.vote_average,
            "genres": video_list.genres,
        }

        if video_list.video_type == VideoType.TV:
            seasons = []
            for season in video_list.seasons:
                if season.deleted_at:
                    continue
                episodes = []
                for episode in season.episodes:
                    if episode.deleted_at:
                        continue
                    episodes.append(
                        {
                            "id": episode.id,
                            "episode_number": episode.episode_number,
                            "title": episode.title,
                            "runtime": episode.runtime,
                        }
                    )
                seasons.append(
                    {
                        "id": season.id,
                        "season_number": season.season_number,
                        "title": season.title,
                        "episodes": episodes,
                    }
                )
            result["seasons"] = seasons

        return result
