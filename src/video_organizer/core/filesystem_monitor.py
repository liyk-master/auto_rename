"""
File system monitoring module.
"""

import logging
import os
import shutil
import time
import threading
import requests
from pathlib import Path
from threading import Event
from typing import Dict, Optional, List

# 导入更新后的VideoFileHandler
from .video_file_handler import VideoFileHandler
from .downloader_monitor import DownloaderMonitorFactory

logger = logging.getLogger(__name__)


class FileSystemMonitor:
    """Monitor downloaders for completed video files and process them."""

    def __init__(
        self,
        watch_path,
        processed_path,
        tmdb_api_key,
        ai_service_url=None,
        supported_extensions=None,
        use_polling=False,
        polling_interval=5,
        naming_rules=None,
        emos_config=None,
        processing_config=None,
        downloader_configs=None,
        config=None,
    ):
        self.watch_path = Path(watch_path)
        self.processed_path = Path(processed_path)
        self.tmdb_api_key = tmdb_api_key
        self.ai_service_url = ai_service_url
        self.config = config  # 保存配置对象，用于路径映射等功能
        self.processed_files = set()  # 存储已处理文件的集合，避免重复处理
        self._processing_lock = threading.Lock()  # 线程锁，保护文件处理逻辑
        self._retry_files = set()  # 需要重试的文件
        self._pending_files = set()  # 待处理的文件

        if supported_extensions is None:
            self.supported_extensions = [
                ".mp4",
                ".mkv",
                ".avi",
                ".mov",
                ".wmv",
                ".strm",
            ]
        else:
            self.supported_extensions = supported_extensions

        self.stop_event = Event()

        # 初始化下载器监控器
        self.downloader_monitors = []
        self.downloader_configs = downloader_configs or []

        # 准备tmdb_config字典
        tmdb_config = {"api_key": tmdb_api_key, "retry_count": 3, "timeout": 30}

        # 初始化更新后的VideoFileHandler
        self.event_handler = VideoFileHandler(
            output_dir=str(self.processed_path),
            supported_extensions=self.supported_extensions,
            naming_rules=naming_rules,
            tmdb_config=tmdb_config,
            emos_config=emos_config,
            p123_config=self.config.get("p123") if self.config else None,
            processing_config=processing_config,
            path_mappings=(
                self.config.get("monitoring", {}).get("path_mappings")
                if self.config
                else None
            ),
            telegram_config=self.config.get("telegram") if self.config else None,
            llm_config=self.config.get("llm_translation") if self.config else None,
        )
        self.event_handler._parent_monitor = self  # 设置父监控器引用

        # 初始化下载器监控器
        self._init_downloader_monitors()

        # 初始化目录监控配置
        self._init_directory_monitor()

    def _init_downloader_monitors(self):
        """
        Initialize downloader monitors based on the provided configs.
        """
        if not self.downloader_configs:
            logger.warning("没有配置下载器，下载器监控功能将不可用")
            return

        for config in self.downloader_configs:
            downloader_type = config.get("type")
            if not downloader_type:
                logger.error("Downloader config missing 'type' field, skipping")
                continue

            # 将 supported_extensions 添加到配置中
            config_with_extensions = config.copy()
            config_with_extensions["supported_extensions"] = tuple(
                self.supported_extensions
            )

            monitor = DownloaderMonitorFactory.create_monitor(
                downloader_type, self._on_download_completed, config_with_extensions
            )

            if monitor:
                self.downloader_monitors.append(monitor)
                logger.info(f"Initialized {downloader_type} monitor")

    def _init_directory_monitor(self):
        """
        Initialize directory monitoring configuration.
        """
        # 从配置中读取目录监控设置
        monitoring_config = self.config.get("monitoring", {})

        self.directory_monitor_enabled = monitoring_config.get(
            "enable_directory_monitor", False
        )
        self.directory_watch_dir = Path(
            monitoring_config.get("directory_watch_dir", "")
        )
        self.directory_output_dir = Path(
            monitoring_config.get("directory_output_dir", "")
        )
        self.directory_organize_mode = monitoring_config.get(
            "directory_organize_mode", "copy"
        ).lower()
        self.directory_scrape_metadata = monitoring_config.get(
            "directory_scrape_metadata", True
        )
        self.directory_metadata_format = monitoring_config.get(
            "directory_metadata_format", "nfo"
        ).lower()
        # 确保 polling_interval 是整数类型
        polling_interval_raw = monitoring_config.get("directory_polling_interval", 5)
        try:
            self.directory_polling_interval = int(polling_interval_raw)
        except (ValueError, TypeError):
            logger.warning(
                f"无效的轮询间隔值 '{polling_interval_raw}'，使用默认值 5 秒"
            )
            self.directory_polling_interval = 5

        # 记录目录监控中已处理的文件
        self._directory_processed_files = set()
        # 存储目录监控中已处理的目录（用于跟踪哪些目录需要检查是否为空）
        self._directory_processed_dirs = set()
        # 存储目录监控中已成功整理的文件（用于判断目录是否可以删除）
        self._directory_successfully_processed_files = set()

        if self.directory_monitor_enabled:
            if not self.directory_watch_dir.exists():
                logger.warning(
                    f"目录监控已启用，但监控目录不存在: {self.directory_watch_dir}"
                )
                self.directory_monitor_enabled = False
            elif not self.directory_output_dir.exists():
                try:
                    self.directory_output_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"创建目录监控输出目录: {self.directory_output_dir}")
                except Exception as e:
                    logger.error(
                        f"无法创建目录监控输出目录: {self.directory_output_dir}, 错误: {e}"
                    )
                    self.directory_monitor_enabled = False

            if self.directory_monitor_enabled:
                logger.info(f"目录监控已启用:")
                logger.info(f"  监控目录: {self.directory_watch_dir}")
                logger.info(f"  输出目录: {self.directory_output_dir}")
                logger.info(f"  整理方式: {self.directory_organize_mode}")
                logger.info(f"  刮削元数据: {self.directory_scrape_metadata}")
                logger.info(f"  元数据格式: {self.directory_metadata_format}")
                logger.info(f"  轮询间隔: {self.directory_polling_interval}秒")

    def _on_download_completed(self, file_path: str, downloader_monitor=None):
        """
        Callback function to handle download completion events from downloaders.

        Args:
            file_path: Path to the completed download file.
        """
        logger.info(f"Received download completion event for: {file_path}")

        # 保存文件到下载器的映射关系
        if downloader_monitor and hasattr(self.event_handler, "_file_downloader_map"):
            # 先应用路径映射
            mapped_file_path = self._apply_path_mapping(file_path)
            self.event_handler._file_downloader_map[str(Path(mapped_file_path))] = (
                downloader_monitor
            )

        # 应用路径映射，将下载器返回的路径转换为主机实际路径
        mapped_file_path = self._apply_path_mapping(file_path)
        logger.debug(f"Mapped file path from {file_path} to {mapped_file_path}")

        # 检查文件是否是支持的视频文件
        if Path(mapped_file_path).suffix.lower() in self.supported_extensions:
            file_path_str = str(Path(mapped_file_path))

            # 跳过 Sample 文件（样本文件）
            file_name = os.path.basename(mapped_file_path).lower()
            if file_name.startswith("sample"):
                logger.info(f"跳过 Sample 文件: {mapped_file_path}")
                return

            # 使用锁保护检查和添加操作，防止竞态条件
            with self._processing_lock:
                if (
                    file_path_str in self.processed_files
                    or file_path_str in self.event_handler._uploading_files
                    or file_path_str in self.event_handler._uploaded_files
                ):
                    logger.debug(
                        f"File already processed or uploading: {mapped_file_path}"
                    )
                    return

                # 检查文件是否存在
                if not os.path.exists(mapped_file_path):
                    logger.warning(
                        f"Mapped file does not exist (will retry later): {mapped_file_path}"
                    )
                    # 不再添加标记，允许下次重试
                    return

                # 标记为已处理，防止重复
                self.processed_files.add(file_path_str)

            # 在锁外启动线程，避免阻塞
            logger.info(f"Processing completed download: {mapped_file_path}")
            threading.Thread(
                target=self.event_handler._process_file, args=(file_path_str,)
            ).start()
        else:
            logger.debug(f"File is not a supported video type: {mapped_file_path}")

    def _apply_path_mapping(self, file_path: str) -> str:
        """
        将下载器返回的路径应用路径映射，转换为主机实际路径

        Args:
            file_path: 下载器返回的原始路径

        Returns:
            str: 转换后的主机实际路径
        """
        # 从配置中获取路径映射
        path_mappings = (
            self.config.get("monitoring", {}).get("path_mappings", {})
            if hasattr(self, "config")
            else {}
        )

        # 遍历所有映射规则，找到最长匹配的前缀
        longest_match = ""
        for prefix, target in path_mappings.items():
            if file_path.startswith(prefix) and len(prefix) > len(longest_match):
                longest_match = prefix

        # 如果找到匹配的映射规则，则应用映射
        if longest_match:
            mapped_path = file_path.replace(
                longest_match, path_mappings[longest_match], 1
            )
            # 确保路径分隔符正确
            mapped_path = mapped_path.replace("/", os.path.sep)
            return mapped_path

        # 如果没有找到匹配的映射规则，则返回原始路径
        return file_path

    def _scan_directory_for_new_files(self):
        """
        扫描监控目录，查找新的视频文件
        """
        if not self.directory_monitor_enabled:
            return

        try:
            # 递归扫描目录
            for file_path in self.directory_watch_dir.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in self.supported_extensions:
                    file_path_str = str(file_path)

                    # 跳过 Sample 文件（样本文件）
                    file_name = file_path.name.lower()
                    if file_name.startswith("sample"):
                        logger.debug(f"跳过 Sample 文件: {file_path_str}")
                        continue

                    # 检查文件是否已处理
                    if file_path_str not in self._directory_processed_files:
                        # 检查文件是否稳定（文件大小在一段时间内不再变化）
                        if self._is_file_stable(file_path):
                            logger.info(f"发现新文件: {file_path_str}")
                            self._directory_processed_files.add(file_path_str)
                            # 在新线程中处理文件
                            threading.Thread(
                                target=self._process_directory_file,
                                args=(file_path_str,),
                            ).start()
        except Exception as e:
            logger.error(f"扫描目录时发生错误: {e}")

        # 扫描完成后，尝试删除空目录
        self._cleanup_empty_directories()

    def _cleanup_empty_directories(self):
        """
        清理空目录
        只有当目录下的所有支持的视频文件都成功整理后，才删除该目录
        """
        if not self._directory_processed_dirs:
            logger.debug("没有需要清理的目录")
            return

        try:
            logger.debug(f"开始清理空目录，共 {len(self._directory_processed_dirs)} 个目录待检查")
            logger.debug(f"已成功整理的文件数: {len(self._directory_successfully_processed_files)}")

            # 按照深度从深到浅排序，确保先删除子目录
            sorted_dirs = sorted(
                self._directory_processed_dirs,
                key=lambda x: x.count(os.path.sep),
                reverse=True
            )

            removed_count = 0
            for dir_path_str in sorted_dirs:
                dir_path = Path(dir_path_str)
                
                # 检查目录是否存在
                if not dir_path.exists() or not dir_path.is_dir():
                    logger.debug(f"目录不存在或不是目录，跳过: {dir_path}")
                    continue

                try:
                    # 检查目录下所有支持的视频文件是否都已成功整理
                    all_files_processed = True
                    has_video_files = False
                    video_files_in_dir = []

                    for file_path in dir_path.rglob("*"):
                        if file_path.is_file() and file_path.suffix.lower() in self.supported_extensions:
                            has_video_files = True
                            file_path_str = str(file_path)
                            video_files_in_dir.append(file_path_str)
                            
                            # 检查文件是否在成功整理的列表中
                            if file_path_str not in self._directory_successfully_processed_files:
                                all_files_processed = False
                                logger.debug(f"目录中仍有未处理的文件: {file_path_str}")

                    logger.debug(f"目录: {dir_path}")
                    logger.debug(f"  - 视频文件数: {len(video_files_in_dir)}")
                    logger.debug(f"  - 所有文件已处理: {all_files_processed}")
                    logger.debug(f"  - 目录为空: {not any(dir_path.iterdir())}")

                    # 判断是否可以删除目录：
                    # 1. 如果目录是监控目录本身，不删除
                    # 2. 如果目录下仍有视频文件未处理，不能删除
                    # 3. 如果目录下没有视频文件了，并且目录为空（没有其他文件），则删除

                    # 检查是否是监控目录本身
                    is_watch_dir = dir_path.resolve() == self.directory_watch_dir.resolve()
                    if is_watch_dir:
                        logger.debug(f"是监控目录本身，不删除: {dir_path}")
                        continue

                    if not any(dir_path.iterdir()):
                        # 目录为空
                        if len(video_files_in_dir) > 0 and not all_files_processed:
                            # 目录下还有未处理的视频文件，不能删除
                            logger.debug(f"目录下仍有未处理的视频文件，跳过: {dir_path}")
                        else:
                            # 目录为空，且没有未处理的视频文件（或者根本没有视频文件了），可以删除
                            logger.info(f"目录为空且所有文件已处理，删除目录: {dir_path}")
                            dir_path.rmdir()
                            removed_count += 1
                            
                            # 递归删除父目录
                            parent_dir = dir_path.parent
                            watch_dir_resolved = self.directory_watch_dir.resolve()
                            
                            while parent_dir != watch_dir_resolved and parent_dir != parent_dir.parent:
                                # 检查父目录是否存在且为空
                                if parent_dir.exists() and not any(parent_dir.iterdir()):
                                    logger.info(f"父目录也为空，删除: {parent_dir}")
                                    parent_dir.rmdir()
                                    removed_count += 1
                                    parent_dir = parent_dir.parent
                                else:
                                    # 父目录不为空或不存在，停止递归
                                    break
                    else:
                        # 目录不为空（有其他文件）
                        if len(video_files_in_dir) > 0:
                            # 目录下还有视频文件
                            if all_files_processed:
                                logger.debug(f"目录下所有视频文件已处理，但目录仍有其他文件，跳过: {dir_path}")
                            else:
                                logger.debug(f"目录中仍有未处理的视频文件，跳过: {dir_path}")
                        else:
                            # 目录下没有视频文件，但有其他文件
                            logger.debug(f"目录下没有视频文件但有其他文件，跳过: {dir_path}")

                except Exception as e:
                    logger.warning(f"检查目录失败: {dir_path}, 错误: {e}")

            if removed_count > 0:
                logger.info(f"清理完成，删除了 {removed_count} 个空目录")

            # 只清理已删除的目录，保留其他目录的记录
            # 这样可以持续跟踪哪些目录还有未处理的文件
            for dir_path_str in sorted_dirs:
                dir_path = Path(dir_path_str)
                if not dir_path.exists():
                    self._directory_processed_dirs.discard(dir_path_str)

        except Exception as e:
            logger.error(f"清理空目录时发生错误: {e}")

    def _is_file_stable(self, file_path: Path, check_interval: float = 1.0, max_checks: int = 3) -> bool:
        """
        检查文件是否稳定（文件大小不再变化）

        Args:
            file_path: 文件路径
            check_interval: 检查间隔（秒）
            max_checks: 最大检查次数

        Returns:
            bool: 文件是否稳定
        """
        try:
            # 获取初始文件大小
            initial_size = file_path.stat().st_size
            checks = 0

            while checks < max_checks:
                time.sleep(check_interval)
                current_size = file_path.stat().st_size

                if current_size == initial_size:
                    checks += 1
                else:
                    # 文件大小发生变化，重置计数器
                    initial_size = current_size
                    checks = 0

            return True
        except Exception as e:
            logger.warning(f"检查文件稳定性时发生错误: {e}")
            return False

    def _process_directory_file(self, file_path: str):
        """
        处理目录监控中发现的新文件

        Args:
            file_path: 文件路径
        """
        try:
            logger.info(f"开始处理目录文件: {file_path}")

            # 提取元数据
            metadata = self.event_handler.renamer.extract_metadata(file_path)

            if not metadata:
                logger.error(f"无法提取文件元数据: {file_path}")
                return

            # 生成新路径
            new_path = self.event_handler.renamer.generate_new_path(
                metadata, original_path=Path(file_path), output_dir=self.directory_output_dir
            )

            logger.info(f"目标路径: {new_path}")

            # 创建目标目录
            new_path.parent.mkdir(parents=True, exist_ok=True)

            # 检查目标文件是否已存在
            if new_path.exists():
                logger.warning(f"目标文件已存在，跳过: {new_path}")
                return  # 不记录目录，因为文件没有被成功整理

            # 根据配置选择复制或移动
            if self.directory_organize_mode == "move":
                logger.info(f"移动文件: {file_path} -> {new_path}")
                shutil.move(file_path, new_path)
            else:
                logger.info(f"复制文件: {file_path} -> {new_path}")
                shutil.copy2(file_path, new_path)

            # 刮削元数据
            if self.directory_scrape_metadata:
                self._scrape_metadata(new_path, metadata)

            # 只有文件成功整理后，才记录源目录
            source_dir = Path(file_path).parent
            self._directory_processed_dirs.add(str(source_dir))
            self._directory_successfully_processed_files.add(file_path)

            logger.info(f"文件处理完成: {new_path}")

        except Exception as e:
            logger.error(f"处理目录文件时发生错误: {file_path}, 错误: {e}")

    def _scrape_metadata(self, file_path: Path, metadata: dict):
        """
        从 TMDB 下载元数据并保存到文件
        元数据文件保存在剧集目录或电影目录中，多个版本共享同一份元数据

        Args:
            file_path: 视频文件路径
            metadata: 元数据字典
        """
        try:
            # 确定元数据文件的保存位置
            # 对于电视剧：保存在剧集目录（Season XX）中
            # 对于电影：保存在电影目录中
            media_type = metadata.get('media_type', 'tv')
            
            if media_type == 'tv':
                # 电视剧：元数据保存在 Season 目录中
                season_dir = file_path.parent
                nfo_path = season_dir / "tvshow.nfo"
                json_path = season_dir / "tvshow.json"
                poster_path = season_dir / "poster.jpg"
                backdrop_path = season_dir / "fanart.jpg"
            else:
                # 电影：元数据保存在电影目录中
                movie_dir = file_path.parent
                nfo_path = movie_dir / f"{movie_dir.name}.nfo"
                json_path = movie_dir / f"{movie_dir.name}.json"
                poster_path = movie_dir / "poster.jpg"
                backdrop_path = movie_dir / "fanart.jpg"

            # 根据配置选择保存格式
            if self.directory_metadata_format in ["nfo", "both"]:
                self._save_nfo_metadata(nfo_path, metadata)
            if self.directory_metadata_format in ["json", "both"]:
                self._save_json_metadata(json_path, metadata)

            # 下载图片（海报和背景图）- 只下载一次
            self._download_images_for_series(movie_dir if media_type == 'movie' else season_dir, metadata)

            logger.info(f"元数据刮削完成: {file_path.parent}")

        except Exception as e:
            logger.error(f"刮削元数据时发生错误: {file_path}, 错误: {e}")

    def _save_nfo_metadata(self, nfo_path: Path, metadata: dict):
        """
        保存 NFO 格式的元数据

        Args:
            nfo_path: NFO 文件保存路径
            metadata: 元数据字典
        """

        # 构建 NFO 内容
        nfo_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        nfo_content += '<movie>\n' if metadata.get('media_type') == 'movie' else '<tvshow>\n'

        # 添加标题
        title = metadata.get('title') or metadata.get('show_name', '')
        nfo_content += f'  <title>{title}</title>\n'

        # 添加原始标题
        original_title = metadata.get('original_title') or metadata.get('original_name', '')
        if original_title and original_title != title:
            nfo_content += f'  <originaltitle>{original_title}</originaltitle>\n'

        # 添加年份
        year = metadata.get('year', '')
        if year:
            nfo_content += f'  <year>{year}</year>\n'
            nfo_content += f'  <premiered>{year}-01-01</premiered>\n'

        # 添加评分
        rating = metadata.get('rating', 0)
        if rating:
            nfo_content += f'  <rating>{rating}</rating>\n'

        # 添加概览
        overview = metadata.get('overview', '')
        if overview:
            nfo_content += f'  <plot>{overview}</plot>\n'

        # 添加类型
        genres = metadata.get('genres', [])
        for genre in genres:
            nfo_content += f'  <genre>{genre}</genre>\n'

        # 添加 TMDB ID
        tmdb_id = metadata.get('tmdb_id', '')
        if tmdb_id:
            nfo_content += f'  <tmdbid>{tmdb_id}</tmdbid>\n'

        # 添加海报和背景图路径
        poster_path = metadata.get('poster_path')
        if poster_path:
            nfo_content += f'  <thumb aspect="poster">poster.jpg</thumb>\n'

        backdrop_path = metadata.get('backdrop_path')
        if backdrop_path:
            nfo_content += f'  <fanart><thumb>backdrop.jpg</thumb></fanart>\n'

        # 添加演员
        cast = metadata.get('cast', [])
        for actor in cast:
            nfo_content += f'  <actor>\n'
            nfo_content += f'    <name>{actor.get("name", "")}</name>\n'
            nfo_content += f'    <role>{actor.get("character", "")}</role>\n'
            nfo_content += f'  </actor>\n'

        # 添加季集信息（仅电视剧）
        if metadata.get('media_type') == 'tv':
            season = metadata.get('season', 1)
            episode = metadata.get('episode', 1)
            episode_name = metadata.get('episode_name', '')
            nfo_content += f'  <season>{season}</season>\n'
            nfo_content += f'  <episode>{episode}</episode>\n'
            if episode_name:
                nfo_content += f'  <episodetitle>{episode_name}</episodetitle>\n'

            # 添加剧集缩略图
            still_path = metadata.get('still_path')
            if still_path:
                nfo_content += f'  <thumb>thumb.jpg</thumb>\n'

        nfo_content += '</movie>\n' if metadata.get('media_type') == 'movie' else '</tvshow>\n'

        # 保存 NFO 文件
        with open(nfo_path, 'w', encoding='utf-8') as f:
            f.write(nfo_content)

        logger.info(f"NFO 元数据已保存: {nfo_path}")

    def _save_json_metadata(self, json_path: Path, metadata: dict):

            """

            保存 JSON 格式的元数据

    

            Args:

                json_path: JSON 文件保存路径

                metadata: 元数据字典

            """

            import json

    

            # 保存 JSON 文件

            with open(json_path, 'w', encoding='utf-8') as f:

                json.dump(metadata, f, ensure_ascii=False, indent=2)

    

            logger.info(f"JSON 元数据已保存: {json_path}")

    def _download_images_for_series(self, series_dir: Path, metadata: dict):
        """
        下载海报和背景图到剧集/电影目录
        多个版本共享同一份图片

        Args:
            series_dir: 剧集/电影目录路径
            metadata: 元数据字典
        """
        try:
            # 获取 TMDB 图片配置
            tmdb_config = self.config.get("tmdb", {})
            base_url = "https://image.tmdb.org/t/p"
            poster_size = "w500"  # 海报尺寸
            backdrop_size = "w1280"  # 背景图尺寸

            # 下载海报
            poster_path = metadata.get('poster_path')
            if poster_path:
                poster_url = f"{base_url}/{poster_size}{poster_path}"
                self._download_image(poster_url, series_dir / "poster.jpg")

            # 下载背景图
            backdrop_path = metadata.get('backdrop_path')
            if backdrop_path:
                backdrop_url = f"{base_url}/{backdrop_size}{backdrop_path}"
                self._download_image(backdrop_url, series_dir / "fanart.jpg")

            # 不再下载剧集缩略图，因为每个剧集的缩略图不同
            # 剧集缩略图应该由媒体中心根据剧集 NFO 自动获取

        except Exception as e:
            logger.error(f"下载图片时发生错误: {series_dir}, 错误: {e}")

    def _download_image(self, url: str, save_path: Path):
        """
        下载图片并保存到指定路径

        Args:
            url: 图片 URL
            save_path: 保存路径
        """
        try:
            # 如果文件已存在，跳过下载
            if save_path.exists():
                logger.debug(f"图片已存在，跳过下载: {save_path}")
                return

            # 下载图片
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # 保存图片
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"图片已下载: {save_path}")

        except Exception as e:
            logger.warning(f"下载图片失败: {url}, 错误: {e}")

    def start(self):
        """
        Start monitoring downloaders for completed downloads.
        """
        # 启动下载器监控器
        for monitor in self.downloader_monitors:
            monitor.start()

        # 启动目录监控线程
        directory_monitor_thread = None
        if self.directory_monitor_enabled:
            directory_monitor_thread = threading.Thread(target=self._directory_monitor_loop)
            directory_monitor_thread.daemon = True
            directory_monitor_thread.start()
            logger.info("目录监控线程已启动")

        logger.info(f"Started downloader monitoring (No filesystem monitoring enabled)")

        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

        # 等待目录监控线程结束
        if directory_monitor_thread and directory_monitor_thread.is_alive():
            directory_monitor_thread.join(timeout=5)

    def _directory_monitor_loop(self):
        """
        目录监控循环，定期扫描目录中的新文件
        """
        logger.info("目录监控循环已启动")

        while not self.stop_event.is_set():
            try:
                self._scan_directory_for_new_files()
            except Exception as e:
                logger.error(f"目录监控循环发生错误: {e}")

            # 等待指定的轮询间隔
            self.stop_event.wait(self.directory_polling_interval)

        logger.info("目录监控循环已停止")

    def stop(self):
        """Stop monitoring."""
        # 停止下载器监控器
        for monitor in self.downloader_monitors:
            monitor.stop()

        self.stop_event.set()
        logger.info("Stopped monitoring")

    def force_process_file(self, file_path):
        """
        强制处理指定的文件，无论其是否已被处理过。
        """
        file_path = Path(file_path)
        if file_path.exists() and file_path.suffix.lower() in self.supported_extensions:
            logger.info(f"Force processing file: {file_path}")
            self.event_handler.force_process_file(str(file_path))
            self.processed_files.add(str(file_path))
            return True
        return False
