"""
网盘整理功能基类

定义统一网盘整理器接口，封装共享逻辑：
- 文件名识别（复用 VideoRenamer + TMDB）
- 目标路径构建与命名
- 批量整理循环（organize_all / organize_streaming）
- 取消与进度回调支持

各网盘（123、天翼、移动等）通过继承本类实现底层操作。
"""

import logging
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# 支持的视频扩展名
VIDEO_EXTENSIONS = [".mp4", ".mkv", ".avi", ".mov", ".wmv"]


class BaseCloudOrganizer:
    """网盘整理器基类"""

    def __init__(
        self,
        tmdb_api_key: Optional[str] = None,
        max_workers: int = 4,
    ):
        """
        初始化网盘整理器基类

        Args:
            tmdb_api_key: TMDB API密钥（用于从文件名识别元数据）
            max_workers: 最大并发工作线程数
        """
        self.tmdb_api_key = tmdb_api_key
        self.max_workers = max_workers
        self._folder_cache: Dict[str, str] = {}
        self._cancel_flag = False
        self._last_error = ""
        self._folder_lock = threading.Lock()

    # ==================== 抽象方法（子类实现） ====================

    def is_available(self) -> bool:
        """检查整理功能是否可用"""
        raise NotImplementedError

    def list_files(
        self, parent_id: Union[str, int], page: int = 1, per_page: int = 100
    ) -> List[Dict]:
        """列出目录下的文件（统一 dict 格式）"""
        raise NotImplementedError

    def get_all_video_files_recursive(
        self, parent_id: Union[str, int], max_depth: int = 5
    ) -> List[Dict]:
        """递归获取所有视频文件"""
        raise NotImplementedError

    def yield_files_recursive(self, parent_id: Union[str, int], max_depth: int = 5):
        """递归获取所有视频文件（生成器，低内存）"""
        raise NotImplementedError

    def count_video_files(self, parent_id: Union[str, int], max_depth: int = 5) -> int:
        """统计视频文件数量"""
        raise NotImplementedError

    def get_file_detail(self, file_id: Union[str, int]) -> Optional[Dict]:
        """获取文件详情"""
        raise NotImplementedError

    def move_file(
        self,
        file_id: Union[str, int],
        target_parent_id: Union[str, int],
        new_name: Optional[str] = None,
    ) -> bool:
        """移动文件（可同时重命名）"""
        raise NotImplementedError

    def rename_file(self, file_id: Union[str, int], new_name: str) -> bool:
        """仅重命名文件（不改动目录）"""
        raise NotImplementedError

    def move_files(
        self,
        file_ids: List[Union[str, int]],
        target_parent_id: Union[str, int],
    ) -> Dict:
        """
        批量移动文件到目标目录

        默认实现为逐文件调用 move_file，子类可覆盖为批量接口
        （如 123 云盘的 mod_pid 单次批量移动）。

        Returns:
            {"success": 成功数量, "errors": [失败原因...]}
        """
        success = 0
        errors: List[str] = []
        for file_id in file_ids:
            try:
                if self.move_file(file_id, target_parent_id):
                    success += 1
                else:
                    errors.append(f"移动失败: file_id={file_id} - {self._last_error}")
            except Exception as e:
                errors.append(f"移动异常: file_id={file_id} - {str(e)}")
        return {"success": success, "errors": errors}

    def create_folder(
        self, parent_id: Union[str, int], name: str
    ) -> Optional[Union[str, int]]:
        """创建文件夹，返回文件夹ID"""
        raise NotImplementedError

    def find_or_create_folder(
        self, parent_id: Union[str, int], name: str
    ) -> Union[str, int]:
        """查找文件夹，不存在则创建"""
        raise NotImplementedError

    # ==================== 取消与进度 ====================

    def cancel(self) -> None:
        """请求取消整理任务"""
        self._cancel_flag = True

    def reset_cancel(self) -> None:
        """重置取消标记"""
        self._cancel_flag = False

    # ==================== 共享逻辑 ====================

    def _get_content_type(self, media_type: str, origin_country: str) -> str:
        """根据媒体类型和地区返回内容分类"""
        if media_type == "movie":
            return "电影"

        if not origin_country:
            return "电视剧"

        country_mapping = {
            "CN": "国漫",
            "HK": "港剧",
            "TW": "台剧",
            "JP": "日番",
            "KR": "韩剧",
            "US": "美剧",
            "GB": "美剧",
            "CA": "美剧",
            "AU": "美剧",
            "NZ": "美剧",
        }

        return country_mapping.get(origin_country, "电视剧")

    def recognize_file_by_name(self, file_name: str) -> Dict:
        """
        通过文件名识别TMDB元数据

        Args:
            file_name: 文件名

        Returns:
            元数据字典（包含 show_name, year, season, episode, tmdb_id 等）
        """
        from ..core.renamer import VideoRenamer

        metadata = {
            "name": file_name,
            "show_name": "",
            "year": "",
            "season": "",
            "episode": "",
            "tmdb_id": "",
            "media_type": "tv",
            "content_type": "电视剧",
            "category_path": "TV Shows/电视剧",  # 默认分类路径
        }

        if not self.tmdb_api_key:
            logger.warning("TMDB API密钥未配置，无法识别文件名")
            return metadata

        try:
            # 创建临时的 renamer 来识别文件
            renamer = VideoRenamer(tmdb_api_key=self.tmdb_api_key)

            # 使用 renamer 提取元数据
            extracted = renamer.extract_metadata(file_name)

            if extracted and extracted.get("show_name"):
                metadata["show_name"] = extracted.get("show_name", "")
                metadata["year"] = extracted.get("year", "")
                metadata["season"] = extracted.get("season", "")
                metadata["episode"] = extracted.get("episode", "")
                metadata["tmdb_id"] = str(extracted.get("tmdb_id", ""))
                metadata["media_type"] = extracted.get("media_type", "tv")
                metadata["quality_tags"] = extracted.get("quality_tags", "")
                metadata["release_group"] = extracted.get("release_group", "")

                # 确保有 TMDB 丰富后的元数据（genres, origin_country 等）
                if not extracted.get("genres") or not extracted.get("origin_country"):
                    logger.info(
                        f"元数据不完整，尝试获取完整TMDB信息: {metadata['show_name']}"
                    )
                    try:
                        renamer_with_tmdb = VideoRenamer(tmdb_api_key=self.tmdb_api_key)
                        # 使用 show_name 和年份搜索获取完整信息
                        search_term = metadata["show_name"]
                        if metadata.get("year"):
                            search_term = f"{search_term} {metadata['year']}"

                        # 搜索电视剧信息
                        tmdb_results = renamer_with_tmdb.tmdb_client.search_video_show(
                            search_term, metadata.get("year"), language="zh-CN"
                        )
                        if tmdb_results and "results" in tmdb_results:
                            tmdb_id = tmdb_results["results"][0].get("id")
                            if tmdb_id:
                                # 获取详细信息
                                details = renamer_with_tmdb.tmdb_client.get_tv_details(
                                    tmdb_id
                                )
                                if details:
                                    extracted["genres"] = [
                                        g["name"] for g in details.get("genres", [])
                                    ]
                                    extracted["genre_ids"] = [
                                        g["id"] for g in details.get("genres", [])
                                    ]
                                    extracted["origin_country"] = details.get(
                                        "origin_country", []
                                    )
                                    extracted["original_language"] = details.get(
                                        "original_language", ""
                                    )
                                    logger.info(
                                        f"获取到TMDB信息: genres={extracted.get('genres')}, "
                                        f"country={extracted.get('origin_country')}"
                                    )
                    except Exception as e:
                        logger.warning(f"获取TMDB信息失败: {e}")

                # 使用 VideoRenamer 的 _determine_category 统一分类
                try:
                    renamer_with_config = VideoRenamer(
                        tmdb_api_key=self.tmdb_api_key, config={}
                    )
                    category_path = renamer_with_config._determine_category(extracted)
                    metadata["category_path"] = category_path
                    logger.info(
                        f"识别成功: {file_name} -> {metadata['show_name']} "
                        f"(S{metadata['season']}E{metadata['episode']}, {category_path})"
                    )
                except Exception as e:
                    logger.warning(f"获取分类失败，使用默认分类: {e}")
                    metadata["category_path"] = "TV Shows/欧美剧"
            else:
                logger.warning(f"无法识别: {file_name}")

        except Exception as e:
            logger.error(f"识别文件名失败: {file_name}, error: {e}")

        return metadata

    def organize_file(
        self,
        file_info: Dict,
        target_parent_id: Union[str, int],
        name_format: str = "{show_name} - {season_episode}",
    ) -> bool:
        """
        整理单个文件（识别目标目录并移动）

        Args:
            file_info: 文件信息（包含tmdb_id, show_name, year, season, episode等）
            target_parent_id: 目标目录ID
            name_format: 命名格式

        Returns:
            是否整理成功
        """
        resolved = self._resolve_target(file_info, target_parent_id, name_format)
        if not resolved:
            return False
        return self.move_file(
            resolved["file_id"], resolved["target_folder_id"], resolved["new_name"]
        )

    def _resolve_target(
        self,
        file_info: Dict,
        target_parent_id: Union[str, int],
        name_format: str = "{show_name} - {season_episode}",
    ) -> Optional[Dict]:
        """
        解析文件目标：识别元数据生成新文件名，并查找/创建目标文件夹

        供两阶段批量整理使用：第一阶段在 worker 线程中调用本方法解析目标，
        第二阶段在主线程批量移动。

        Args:
            file_info: 文件信息（包含tmdb_id, show_name, year, season, episode等）
            target_parent_id: 目标目录ID
            name_format: 命名格式

        Returns:
            {"file_id", "target_folder_id", "new_name"}，失败返回 None
            （失败原因写入 self._last_error）
        """
        self._last_error = ""
        if not self.is_available():
            self._last_error = "整理功能不可用"
            return None

        file_id = file_info.get("id")
        if not file_id:
            self._last_error = "文件信息中缺少id"
            return None

        # 解析文件元数据
        show_name = file_info.get("show_name", "")
        year = file_info.get("year", "")
        tmdb_id = file_info.get("tmdb_id", "")
        season = file_info.get("season", "")
        episode = file_info.get("episode", "")
        media_type = file_info.get("media_type", "tv")
        category_path = file_info.get("category_path", "TV Shows/电视剧")

        if not show_name:
            self._last_error = "文件缺少show_name"
            return None

        # 生成新文件名
        new_name = self._generate_name(
            show_name,
            year,
            tmdb_id,
            season,
            episode,
            name_format,
            original_name=file_info.get("name", ""),
            quality_tags=file_info.get("quality_tags", ""),
            release_group=file_info.get("release_group", ""),
        )

        # 构建目标路径（包含分类子文件夹）
        target_path = self._build_target_path(
            show_name, year, tmdb_id, media_type, category_path, target_parent_id
        )

        # 处理嵌套文件夹路径（如 "TV Shows/国漫/剧集名/Season 01"）
        root_folder = target_path["root_folder"]
        folder_name = target_path["folder_name"]

        # 先找到根目录（TV Shows 或 Movies）
        # 加锁串行化文件夹查找/创建，避免并发创建同名文件夹
        with self._folder_lock:
            root_folder_id = self.find_or_create_folder(
                target_parent_id, root_folder.split("/")[0]
            )
            if not root_folder_id:
                self._last_error = f"创建根目录失败: {root_folder.split('/')[0]}"
                return None

            # 如果有子分类，先创建分类文件夹
            if "/" in root_folder:
                category_name = root_folder.split("/")[1]
                target_folder_id = self.find_or_create_folder(
                    root_folder_id, category_name
                )
                if not target_folder_id:
                    self._last_error = f"创建分类文件夹失败: {category_name}"
                    return None
            else:
                target_folder_id = root_folder_id

            # 创建剧集文件夹
            show_folder_id = self.find_or_create_folder(target_folder_id, folder_name)
            if not show_folder_id:
                self._last_error = f"创建剧集文件夹失败: {folder_name}"
                return None

            # 如果是电视剧，创建 Season 子文件夹
            if media_type != "movie" and season:
                season_folder_name = f"Season {int(season):02d}"
                target_folder_id = self.find_or_create_folder(
                    show_folder_id, season_folder_name
                )
                if not target_folder_id:
                    self._last_error = f"创建Season文件夹失败: {season_folder_name}"
                    return None
            else:
                target_folder_id = show_folder_id

        return {
            "file_id": file_id,
            "target_folder_id": target_folder_id,
            "new_name": new_name,
        }

    def _generate_name(
        self,
        show_name: str,
        year: str,
        tmdb_id: str,
        season: str,
        episode: str,
        name_format: str,
        original_name: str = "",
        quality_tags: str = "",
        release_group: str = "",
    ) -> str:
        """生成文件名"""
        show_name = re.sub(r'[\\/:*?"<>|]', "", show_name)

        season_episode = ""
        if season and episode:
            season_episode = f"S{int(season):02d}E{int(episode):02d}"
        elif season:
            season_episode = f"S{int(season):02d}"
        elif episode:
            season_episode = f"E{int(episode):02d}"

        # 从原始文件名获取扩展名
        ext = ".mp4"
        if original_name:
            for video_ext in VIDEO_EXTENSIONS:
                if original_name.lower().endswith(video_ext):
                    ext = video_ext
                    break

        # 构建质量标签-发布组后缀
        quality_suffix = ""
        if quality_tags:
            quality_suffix = quality_tags
        if release_group:
            if quality_suffix:
                quality_suffix = f"{quality_suffix}-{release_group}"
            else:
                quality_suffix = release_group

        # 使用统一格式：剧名 季集 质量标签-发布组.ext
        if season_episode:
            if quality_suffix:
                new_name = f"{show_name} {season_episode} {quality_suffix}"
            else:
                new_name = f"{show_name} {season_episode}"
        else:
            if quality_suffix:
                new_name = f"{show_name} {quality_suffix}"
            else:
                new_name = show_name

        return f"{new_name}{ext}"

    def _build_target_path(
        self,
        show_name: str,
        year: str,
        tmdb_id: str,
        media_type: str,
        category_path: str,
        parent_id: Union[str, int],
    ) -> Dict:
        """构建目标路径"""
        show_name = re.sub(r'[\\/:*?"<>|]', "", show_name)

        # 使用 category_path 作为分类路径
        # category_path 格式: "TV Shows/国漫" 或 "Movies/动画电影"
        root_folder = category_path

        return {
            "root_folder": root_folder,
            "folder_name": (
                f"{show_name} ({year}) {{tmdbid={tmdb_id}}}"
                if tmdb_id and year
                else f"{show_name} ({year})" if year else show_name
            ),
            "parent_id": parent_id,
        }

    def organize_all(
        self,
        source_id: Union[str, int] = None,
        target_id: Union[str, int] = None,
        files: List[Dict] = None,
        dry_run: bool = False,
    ) -> Dict:
        """
        整理所有文件（批量模式，一次性加载所有文件到内存）

        Args:
            source_id: 源目录ID（默认使用配置中的organize_source_id）
            target_id: 目标目录ID（默认使用配置中的organize_target_id）
            files: 文件列表（如果提供则使用此列表，否则从source_id获取）
            dry_run: 试运行模式（只显示不执行）

        Returns:
            整理结果统计
        """
        if not self.is_available():
            return {"success": 0, "failed": 0, "skipped": 0, "errors": []}

        # 使用配置或传入的参数
        source_id = source_id or self.organize_source_id
        target_id = target_id or self.organize_target_id

        if source_id == 0 or source_id == "":
            logger.error("源目录ID未设置")
            return {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": ["源目录ID未设置"],
            }

        if target_id == 0 or target_id == "":
            logger.error("目标目录ID未设置")
            return {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": ["目标目录ID未设置"],
            }

        # 获取文件列表（递归获取所有子文件夹中的视频文件）
        if files is None:
            files = self.get_all_video_files_recursive(source_id)
            logger.info(f"从源目录递归获取到 {len(files)} 个视频文件")

        # 过滤出需要整理的文件
        organize_files = []
        for f in files:
            # 跳过文件夹
            if f.get("type") == 1:
                continue
            # 跳过非视频文件
            name = f.get("name", "").lower()
            if not any(name.endswith(ext) for ext in VIDEO_EXTENSIONS):
                continue

            # 如果没有元数据，尝试通过文件名识别
            if not f.get("tmdb_id"):
                if self.tmdb_api_key:
                    metadata = self.recognize_file_by_name(f.get("name", ""))
                    if metadata.get("show_name"):
                        # 将识别的元数据添加到文件信息中
                        f["show_name"] = metadata.get("show_name", "")
                        f["year"] = metadata.get("year", "")
                        f["season"] = metadata.get("season", "")
                        f["episode"] = metadata.get("episode", "")
                        f["tmdb_id"] = metadata.get("tmdb_id", "")
                        f["media_type"] = metadata.get("media_type", "tv")
                        f["quality_tags"] = metadata.get("quality_tags", "")
                        f["release_group"] = metadata.get("release_group", "")
                        f["category_path"] = metadata.get(
                            "category_path", "TV Shows/电视剧"
                        )
                        logger.info(
                            f"通过文件名识别元数据: {f.get('name')} -> "
                            f"{metadata['show_name']} ({metadata['category_path']})"
                        )
                    else:
                        logger.warning(f"无法识别文件名，跳过: {f.get('name')}")
                        continue
                else:
                    logger.warning(
                        f"文件缺少元数据且TMDB API密钥未配置，跳过: {f.get('name')}"
                    )
                    continue

            # 只处理有元数据的文件
            if f.get("tmdb_id"):
                # 确保有 category_path
                if not f.get("category_path"):
                    f["category_path"] = "TV Shows/电视剧"
                organize_files.append(f)

        logger.info(f"需要整理的文件数: {len(organize_files)}")

        # 统计
        success = 0
        failed = 0
        skipped = 0
        errors = []

        # 整理每个文件
        for file_info in organize_files:
            file_name = file_info.get("name", "未知")

            if dry_run:
                logger.info(
                    f"[试运行] 将整理: {file_name} -> {file_info.get('show_name', '未知')}"
                )
                success += 1
                continue

            try:
                result = self.organize_file(file_info, target_id)
                if result:
                    success += 1
                    logger.info(f"整理成功: {file_name}")
                else:
                    failed += 1
                    errors.append(f"整理失败: {file_name}")
                    logger.error(f"整理失败: {file_name}")
            except Exception as e:
                failed += 1
                errors.append(f"整理异常: {file_name} - {str(e)}")
                logger.error(f"整理异常: {file_name}: {e}")

        return {
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "total": len(organize_files),
            "errors": errors,
        }

    def organize_streaming(
        self,
        source_id: Union[str, int] = None,
        target_id: Union[str, int] = None,
        dry_run: bool = False,
        show_progress: bool = True,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ) -> Dict:
        """
        两阶段并行整理所有文件

        优势：
        - 第一阶段并行：识别 + 解析目标目录 + 重命名（ThreadPoolExecutor 并发）
        - 第二阶段批量移动：按目标目录分组，主线程顺序执行 move_files
          （123 云盘单次 mod_pid 批量移动，避免并发移动同一目录冲突）
        - 实时进度：逐个文件完成后立即更新进度与成败统计
        - 可取消：设置取消标记后，剩余未处理文件按跳过处理

        Args:
            source_id: 源目录ID（默认使用配置中的organize_source_id）
            target_id: 目标目录ID（默认使用配置中的organize_target_id）
            dry_run: 试运行模式（只显示不执行）
            show_progress: 是否显示进度条
            progress_callback: 进度回调函数，接收包含进度信息的字典

        Returns:
            整理结果统计
        """
        self.reset_cancel()

        if not self.is_available():
            return {"success": 0, "failed": 0, "skipped": 0, "errors": []}

        # 使用配置或传入的参数
        source_id = source_id or self.organize_source_id
        target_id = target_id or self.organize_target_id

        if source_id == 0 or source_id == "":
            logger.error("源目录ID未设置")
            return {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": ["源目录ID未设置"],
            }

        if target_id == 0 or target_id == "":
            logger.error("目标目录ID未设置")
            return {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": ["目标目录ID未设置"],
            }

        # 收集文件列表（用于进度显示与并行处理）
        files = list(self.yield_files_recursive(source_id))
        total_count = len(files)
        logger.info(f"源目录共有 {total_count} 个文件")

        # 统计（仅主线程累加，无需加锁）
        success = 0
        failed = 0
        skipped = 0
        processed_count = 0
        errors: List[str] = []

        # 进度条
        pbar = None
        if show_progress and total_count > 0:
            try:
                from tqdm import tqdm

                pbar = tqdm(
                    total=total_count,
                    desc="整理进度",
                    unit="文件",
                    ncols=100,
                )
            except ImportError:
                logger.warning("tqdm 未安装，不显示进度条")
                show_progress = False

        def _emit_progress(action: str, name: str = "", detail: str = ""):
            if progress_callback:
                try:
                    progress_callback(
                        {
                            "processed": processed_count,
                            "total": total_count,
                            "action": action,
                            "name": name,
                            "detail": detail,
                            "success": success,
                            "failed": failed,
                            "skipped": skipped,
                        }
                    )
                except Exception:
                    pass

        def _process_file(file_info: Dict) -> Dict:
            """第一阶段 worker：识别 + 解析目标目录 + 重命名（返回待移动的 file_id）"""
            file_name = file_info.get("name", "未知")

            # 跳过文件夹（不计入成败，仅计入已处理）
            if file_info.get("type") == 1:
                return {"result": "ignored", "name": file_name, "detail": "文件夹"}

            # 跳过非视频文件（不计入成败，仅计入已处理）
            if not any(file_name.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
                return {"result": "ignored", "name": file_name, "detail": "非视频文件"}

            # 如果没有元数据，尝试通过文件名识别
            if not file_info.get("tmdb_id"):
                if self.tmdb_api_key:
                    try:
                        metadata = self.recognize_file_by_name(file_name)
                        if metadata.get("show_name"):
                            # 将识别的元数据添加到文件信息中
                            file_info["show_name"] = metadata.get("show_name", "")
                            file_info["year"] = metadata.get("year", "")
                            file_info["season"] = metadata.get("season", "")
                            file_info["episode"] = metadata.get("episode", "")
                            file_info["tmdb_id"] = metadata.get("tmdb_id", "")
                            file_info["media_type"] = metadata.get("media_type", "tv")
                            file_info["quality_tags"] = metadata.get("quality_tags", "")
                            file_info["release_group"] = metadata.get(
                                "release_group", ""
                            )
                            file_info["category_path"] = metadata.get(
                                "category_path", "TV Shows/电视剧"
                            )
                            logger.info(
                                f"识别成功: {file_name} -> {metadata['show_name']}"
                            )
                        else:
                            logger.warning(f"无法识别: {file_name}")
                            return {
                                "result": "skipped",
                                "name": file_name,
                                "detail": "无法识别",
                            }
                    except Exception as e:
                        logger.warning(f"识别异常: {file_name} - {e}")
                        return {
                            "result": "skipped",
                            "name": file_name,
                            "detail": f"识别异常: {e}",
                        }
                else:
                    logger.warning(f"TMDB API未配置，跳过: {file_name}")
                    return {
                        "result": "skipped",
                        "name": file_name,
                        "detail": "TMDB未配置",
                    }

            # 只处理有元数据的文件
            if file_info.get("tmdb_id"):
                # 确保有 category_path
                if not file_info.get("category_path"):
                    file_info["category_path"] = "TV Shows/电视剧"

                if dry_run:
                    logger.info(
                        f"[试运行] 将整理: {file_name} -> "
                        f"{file_info.get('show_name', '未知')}"
                    )
                    return {
                        "result": "preview",
                        "name": file_name,
                        "detail": file_info.get("show_name", ""),
                    }

                # 解析目标目录（worker 线程中完成识别与建目录）
                resolved = self._resolve_target(file_info, target_id)
                if not resolved:
                    reason = self._last_error or "整理失败"
                    logger.error(f"✗ 解析目标失败: {file_name} - {reason}")
                    return {
                        "result": "failed",
                        "name": file_name,
                        "detail": reason,
                        "error": f"整理失败: {file_name} - {reason}",
                    }

                # 第一阶段只重命名（日志证明 rename 不会并发冲突，只有 mod_pid 会）
                try:
                    if not self.rename_file(resolved["file_id"], resolved["new_name"]):
                        reason = self._last_error or "重命名失败"
                        logger.error(f"✗ 重命名失败: {file_name} - {reason}")
                        return {
                            "result": "failed",
                            "name": file_name,
                            "detail": reason,
                            "error": f"整理失败: {file_name} - {reason}",
                        }
                except Exception as e:
                    logger.error(f"✗ 重命名异常: {file_name}: {e}")
                    return {
                        "result": "failed",
                        "name": file_name,
                        "detail": f"重命名异常: {e}",
                        "error": f"整理失败: {file_name} - 重命名异常: {str(e)}",
                    }

                return {
                    "result": "ready",
                    "name": file_name,
                    "detail": file_info.get("show_name", ""),
                    "file_id": resolved["file_id"],
                    "target_folder_id": resolved["target_folder_id"],
                }

            return {"result": "skipped", "name": file_name, "detail": "缺少元数据"}

        # ===== 第一阶段：并行识别 + 建目录 + 重命名 =====
        from concurrent.futures import ThreadPoolExecutor, as_completed

        workers = max(1, self.max_workers or 1)
        pending_moves: Dict = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_process_file, f) for f in files]
            for future in as_completed(futures):
                if self._cancel_flag:
                    break
                try:
                    item = future.result()
                except Exception as e:
                    item = {
                        "result": "failed",
                        "name": "未知",
                        "detail": str(e),
                        "error": str(e),
                    }

                processed_count += 1
                action = item.get("result", "skipped")
                file_name = item.get("name", "未知")

                if action == "ready":
                    folder_id = item.get("target_folder_id")
                    pending_moves.setdefault(folder_id, []).append(item)
                    _emit_progress("recognized", file_name, item.get("detail", ""))
                elif action == "preview":
                    success += 1
                    _emit_progress(action, file_name, item.get("detail", ""))
                elif action == "failed":
                    failed += 1
                    if item.get("error"):
                        errors.append(item["error"])
                    _emit_progress("failed", file_name, item.get("detail", ""))
                elif action == "ignored":
                    pass
                else:
                    skipped += 1
                    _emit_progress("skipped", file_name, item.get("detail", ""))

                if pbar:
                    pbar.update(1)

            # 取消时：未完成任务按跳过处理
            if self._cancel_flag:
                logger.info("整理任务已被取消")
                remaining = [f for f in futures if not f.done()]
                for _ in remaining:
                    processed_count += 1
                    skipped += 1
                    if pbar:
                        pbar.update(1)
                # 已解析/重命名但尚未移动的文件也按跳过处理（保留在源目录）
                skipped += sum(len(items) for items in pending_moves.values())
                if pbar:
                    pbar.close()
                _emit_progress("cancelled", "", "已取消")
                return {
                    "success": success,
                    "failed": failed,
                    "skipped": skipped,
                    "total": processed_count,
                    "errors": errors,
                    "cancelled": True,
                }

        # ===== 第二阶段：按目标目录分组批量移动（主线程顺序执行） =====
        logger.info(f"开始批量移动，共 {len(pending_moves)} 个目标目录")
        for folder_id, items in pending_moves.items():
            # 取消时：剩余已重命名文件按跳过处理（保留在源目录）
            if self._cancel_flag:
                logger.info("整理任务已取消，跳过剩余批量移动")
                skipped += len(items)
                continue

            file_ids = [it["file_id"] for it in items]
            move_result = self.move_files(file_ids, folder_id)
            move_success = move_result.get("success", 0)
            move_errors = move_result.get("errors", [])

            success += move_success
            for it in items[:move_success]:
                _emit_progress("organized", it.get("name", ""), it.get("detail", ""))
            for err in move_errors:
                failed += 1
                errors.append(err)
                _emit_progress("failed", "移动失败", err)

        if pbar:
            pbar.close()

        _emit_progress("completed", "", "完成")
        return {
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "total": processed_count,
            "errors": errors,
        }
