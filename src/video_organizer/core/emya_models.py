# -*- coding: utf-8 -*-
"""
emya 数据库模型定义

基于 emya 库详解文档定义的 SQLAlchemy ORM 模型
包含：用户模块、媒体库模块、元数据模块
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    DateTime,
    JSON,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.ext.declarative import declared_attr


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""

    pass


class TimestampMixin:
    """时间戳混入类"""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime, default=datetime.now, nullable=False)

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
        )

    @declared_attr
    def deleted_at(cls) -> Mapped[Optional[datetime]]:
        return mapped_column(DateTime, nullable=True)


# ============================================================
# 用户模块
# ============================================================


class User(Base, TimestampMixin):
    """用户表"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="用户名")
    email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="邮箱"
    )
    password: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="密码"
    )
    avatar: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="头像"
    )
    role: Mapped[str] = mapped_column(
        String(50), default="user", comment="角色: admin/user"
    )
    status: Mapped[str] = mapped_column(
        String(50), default="active", comment="状态: active/banned"
    )

    # 关系
    tokens: Mapped[List["Token"]] = relationship("Token", back_populates="user")
    favorites: Mapped[List["Favorite"]] = relationship("Favorite", back_populates="user")
    video_records: Mapped[List["UserVideoRecord"]] = relationship(
        "UserVideoRecord", back_populates="user"
    )


class Token(Base, TimestampMixin):
    """令牌表"""

    __tablename__ = "token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=False, comment="用户ID"
    )
    token: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="令牌值"
    )
    device: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="设备信息"
    )
    ip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="IP地址")
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="过期时间"
    )

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="tokens")


class Favorite(Base, TimestampMixin):
    """收藏表"""

    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=False, comment="用户ID"
    )
    relation_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="关联类型: vl/vs/ve"
    )
    relation_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="关联ID"
    )

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="favorites")

    __table_args__ = (
        Index("idx_favorites_user_relation", "user_id", "relation_type", "relation_id"),
    )


class UserVideoRecord(Base, TimestampMixin):
    """用户播放记录表"""

    __tablename__ = "user_video_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=False, comment="用户ID"
    )
    video_list_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("video_list.id"), nullable=True, comment="视频ID"
    )
    video_episode_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("video_episode.id"), nullable=True, comment="剧集ID"
    )
    video_media_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("video_media.id"), nullable=True, comment="媒体ID"
    )
    progress: Mapped[int] = mapped_column(
        Integer, default=0, comment="播放进度(秒)"
    )
    duration: Mapped[int] = mapped_column(Integer, default=0, comment="总时长(秒)")
    last_played_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="最后播放时间"
    )

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="video_records")
    video_list: Mapped[Optional["VideoList"]] = relationship(
        "VideoList", back_populates="user_records"
    )
    video_episode: Mapped[Optional["VideoEpisode"]] = relationship(
        "VideoEpisode", back_populates="user_records"
    )
    video_media: Mapped[Optional["VideoMedia"]] = relationship(
        "VideoMedia", back_populates="user_records"
    )


# ============================================================
# 媒体库模块
# ============================================================


class Library(Base, TimestampMixin):
    """媒体库表"""

    __tablename__ = "library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="媒体库名称")
    role: Mapped[Optional[str]] = mapped_column(
        String(255), default="public", nullable=True, comment="角色权限"
    )
    # 注意: 数据库中没有 description 和 poster 字段
    # library 是二级分类，如"国产剧"、"外语电影"等
    # video_type 在 video_list 表中区分 tv/movie

    # 关系
    video_lists: Mapped[List["VideoList"]] = relationship(
        "VideoList", back_populates="library"
    )


class VideoList(Base, TimestampMixin):
    """视频列表表 (电影/剧集)"""

    __tablename__ = "video_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_library_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("library.id"), nullable=False, comment="媒体库ID"
    )
    video_type: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="类型: tv/movie"
    )
    tmdb_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="TMDB ID"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    origin_title: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="原始标题"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="简介"
    )
    tagline: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="标语"
    )
    genres: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="类型列表(JSON)"
    )
    peoples: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="人物列表(JSON)"
    )
    upcoming: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="即将上映"
    )
    date_air: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="上映日期"
    )
    runtime: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="时长(分钟)")
    remark: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="备注"
    )

    # 关系
    library: Mapped[Optional["Library"]] = relationship(
        "Library", back_populates="video_lists"
    )
    seasons: Mapped[List["VideoSeason"]] = relationship(
        "VideoSeason", back_populates="video_list"
    )
    medias: Mapped[List["VideoMedia"]] = relationship(
        "VideoMedia", back_populates="video_list"
    )
    title_aliases: Mapped[List["VideoListTitleAlias"]] = relationship(
        "VideoListTitleAlias", back_populates="video_list"
    )
    user_records: Mapped[List["UserVideoRecord"]] = relationship(
        "UserVideoRecord", back_populates="video_list"
    )

    __table_args__ = (
        Index("idx_video_list_tmdb", "tmdb_id"),
        Index("idx_video_list_library", "video_library_id"),
    )


class VideoListTitleAlias(Base, TimestampMixin):
    """视频标题别名表"""

    __tablename__ = "video_list_title_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("video_list.id"), nullable=False, comment="视频ID"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="别名")
    language: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, comment="语言"
    )

    # 关系
    video_list: Mapped["VideoList"] = relationship(
        "VideoList", back_populates="title_aliases"
    )

    __table_args__ = (
        Index("idx_title_alias_video_list", "video_list_id"),
    )


class VideoSeason(Base, TimestampMixin):
    """电视季表"""

    __tablename__ = "video_season"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("video_list.id"), nullable=False, comment="视频ID"
    )
    season_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="季数")
    season_number_custom: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="自定义季数"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="简介")
    date_air: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="上映日期"
    )

    # 关系
    video_list: Mapped["VideoList"] = relationship("VideoList", back_populates="seasons")
    episodes: Mapped[List["VideoEpisode"]] = relationship(
        "VideoEpisode", back_populates="season"
    )

    __table_args__ = (
        Index("idx_video_season_list", "video_list_id"),
    )


class VideoEpisode(Base, TimestampMixin):
    """电视集表"""

    __tablename__ = "video_episode"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("video_list.id"), nullable=False, comment="视频ID"
    )
    video_season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("video_season.id"), nullable=False, comment="季ID"
    )
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="集数")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="简介")
    date_air: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="上映日期"
    )
    runtime: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="时长(分钟)")
    poster: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="海报路径")
    still: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="剧照路径")
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="TMDB ID")
    imdb_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="IMDB ID")

    # 关系
    video_list: Mapped["VideoList"] = relationship("VideoList")
    season: Mapped["VideoSeason"] = relationship("VideoSeason", back_populates="episodes")
    medias: Mapped[List["VideoMedia"]] = relationship(
        "VideoMedia", back_populates="video_episode"
    )
    # 注意: VideoImage 使用多态关联，无法直接定义 relationship
    user_records: Mapped[List["UserVideoRecord"]] = relationship(
        "UserVideoRecord", back_populates="video_episode"
    )

    __table_args__ = (
        Index("idx_video_episode_season", "video_season_id"),
        Index("idx_video_episode_list", "video_list_id"),
        UniqueConstraint(
            "video_season_id", "episode_number", name="uq_episode_season_number"
        ),
    )


class VideoMedia(Base, TimestampMixin):
    """媒体资源表 (播放文件)"""

    __tablename__ = "video_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, unique=True, comment="UUID")
    video_list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("video_list.id"), nullable=False, comment="视频ID"
    )
    video_season_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("video_season.id"), nullable=True, comment="季ID"
    )
    video_episode_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("video_episode.id"), nullable=True, comment="集ID(剧集)"
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True, comment="上传用户ID"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="名称")
    status: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="状态: active/inactive"
    )
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="文件大小(字节)")
    file_second: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="时长(秒)")
    file_matadata: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="文件元数据(JSON)"
    )
    file_container: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="容器格式: mkv/mp4/avi"
    )
    file_chapters: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="章节信息(JSON)"
    )
    path_type: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="路径类型: url/local"
    )
    path_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="播放地址"
    )
    number_view: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, default=0, comment="观看次数"
    )
    file_resolution: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="分辨率: 1080p/4k"
    )

    # 关系
    video_list: Mapped[Optional["VideoList"]] = relationship(
        "VideoList", back_populates="medias"
    )
    video_season: Mapped[Optional["VideoSeason"]] = relationship("VideoSeason")
    video_episode: Mapped[Optional["VideoEpisode"]] = relationship(
        "VideoEpisode", back_populates="medias"
    )
    subtitles: Mapped[List["VideoSubtitle"]] = relationship(
        "VideoSubtitle", back_populates="video_media"
    )
    user_records: Mapped[List["UserVideoRecord"]] = relationship(
        "UserVideoRecord", back_populates="video_media"
    )

    __table_args__ = (
        Index("idx_video_media_episode", "video_episode_id"),
        Index("idx_video_media_list", "video_list_id"),
    )


class VideoSubtitle(Base, TimestampMixin):
    """字幕表"""

    __tablename__ = "video_subtitle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_media_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("video_media.id"), nullable=False, comment="媒体ID"
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True, comment="上传用户ID"
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="字幕标题")
    codec: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="编码: srt/ass/vtt"
    )
    path_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="路径类型: url/local"
    )
    path_url: Mapped[str] = mapped_column(String(1000), nullable=False, comment="字幕地址")
    language: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, comment="语言: zh/en/ja"
    )
    is_default: Mapped[int] = mapped_column(
        Integer, default=0, comment="是否默认: 0/1"
    )

    # 关系
    video_media: Mapped["VideoMedia"] = relationship(
        "VideoMedia", back_populates="subtitles"
    )

    __table_args__ = (
        Index("idx_video_subtitle_media", "video_media_id"),
    )


class VideoImage(Base, TimestampMixin):
    """视频图片表 (海报/背景)"""

    __tablename__ = "video_image"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="类型: Primary/Backdrop/Thumb/Logo"
    )
    relation_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="关联类型: vb/vl/vs/ve"
    )
    relation_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="关联ID")
    path_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="路径类型: tmdb/douban/url"
    )
    path_url: Mapped[str] = mapped_column(String(500), nullable=False, comment="图片路径")

    # 注意: 此表使用多态关联 (relation_type + relation_id)，无法直接定义 SQLAlchemy relationship
    # 需要通过查询获取关联对象

    __table_args__ = (
        Index("idx_video_image_relation", "relation_type", "relation_id"),
    )


# ============================================================
# 元数据模块
# ============================================================


class VideoGenre(Base, TimestampMixin):
    """类型/标签表"""

    __tablename__ = "video_genre"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="TMDB ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="类型名称")
    # 注意: 数据库实际表中没有 name_en 字段

    __table_args__ = (UniqueConstraint("tmdb_id", name="uq_genre_tmdb_id"),)


class VideoPeople(Base, TimestampMixin):
    """人物表"""

    __tablename__ = "video_people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="TMDB ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="名称")
    name_en: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="英文名称"
    )
    profile_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="头像路径"
    )
    gender: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="性别: 1女/2男")
    known_for_department: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="部门: Acting/Directing"
    )

    __table_args__ = (UniqueConstraint("tmdb_id", name="uq_people_tmdb_id"),)


# ============================================================
# 关系类型常量
# ============================================================

class RelationType:
    """关系类型常量"""
    VIDEO_LIBRARY = "vb"  # video_library
    VIDEO_LIST = "vl"     # video_list
    VIDEO_SEASON = "vs"   # video_season
    VIDEO_EPISODE = "ve"  # video_episode


class ImageType:
    """图片类型常量"""
    PRIMARY = "Primary"    # 海报
    BACKDROP = "Backdrop"  # 背景
    THUMB = "Thumb"        # 缩略图
    LOGO = "Logo"          # Logo


class PathType:
    """路径类型常量"""
    TMDB = "tmdb"      # TMDB 路径
    DOUBAN = "douban"  # 豆瓣路径
    URL = "url"        # 完整 URL
    LOCAL = "local"    # 本地路径


class VideoType:
    """视频类型常量"""
    TV = "tv"
    MOVIE = "movie"
