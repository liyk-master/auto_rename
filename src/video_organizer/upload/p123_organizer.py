"""
123网盘文件整理功能
识别源目录中的文件，重命名后移动到目标目录
"""

import logging
import re
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

try:
    from p123client import P123Client
    from p123client.tool import iterdir

    P123CLIENT_AVAILABLE = True
except ImportError:
    P123CLIENT_AVAILABLE = False
    logger.warning("p123client 未安装，123云盘整理功能不可用")


class P123Organizer:
    """123网盘文件整理器"""

    def __init__(
        self,
        token: str,
        organize_source_id: int = 0,
        organize_target_id: int = 0,
        max_workers: int = 2,
        tmdb_api_key: str = None,
    ):
        """
        初始化123网盘整理器

        Args:
            token: 123云盘访问令牌
            organize_source_id: 需要整理的源目录ID
            organize_target_id: 整理到的目标目录ID
            max_workers: 最大并发工作线程数
            tmdb_api_key: TMDB API密钥（用于从文件名识别元数据）
        """
        self.token = token
        self.organize_source_id = organize_source_id
        self.organize_target_id = organize_target_id
        self.max_workers = max_workers
        self.tmdb_api_key = tmdb_api_key
        self.client = None
        self._folder_cache = {}

        if not P123CLIENT_AVAILABLE:
            logger.error("p123client 未安装，无法使用123云盘整理功能")
            return

        if not token:
            logger.error("123云盘 token 为空")
            return

        try:
            self.client = P123Client(token=token)
            logger.info("123云盘客户端初始化成功")
        except Exception as e:
            logger.error(f"初始化123云盘客户端失败: {e}")

    def is_available(self) -> bool:
        """检查整理功能是否可用"""
        return P123CLIENT_AVAILABLE and self.client is not None

    def list_files(
        self, parent_id: int, page: int = 1, per_page: int = 100
    ) -> List[Dict]:
        """
        列出目录下的文件

        Args:
            parent_id: 目录ID
            page: 页码
            per_page: 每页数量

        Returns:
            文件列表
        """
        if not self.is_available():
            return []

        try:
            # 使用 fs_list 接口
            result = self.client.fs_list(
                {
                    "parentFileId": parent_id,
                    "page": page,
                    "limit": per_page,
                    "orderBy": "file_id",
                    "orderDirection": "asc",  # 注意：desc 会返回空列表
                    "event": "homeListFile",
                }
            )

            if result.get("code") == 0:
                info_list = result.get("data", {}).get("InfoList", [])
                # 转换为统一格式
                files = []
                for item in info_list:
                    files.append(
                        {
                            "id": item.get("FileId"),
                            "name": item.get("FileName"),
                            "type": item.get("Type"),  # 0=文件, 1=文件夹
                            "size": item.get("FileSize"),
                            "create_time": item.get("CreateTime"),
                            "update_time": item.get("UpdateTime"),
                        }
                    )
                return files
            else:
                logger.error(f"列出文件失败: {result.get('message')}")
                return []
        except Exception as e:
            logger.error(f"列出文件异常: {e}")
            return []

    def get_all_files(self, parent_id: int) -> List[Dict]:
        """
        获取目录下所有文件（自动分页）

        Args:
            parent_id: 目录ID

        Returns:
            所有文件列表
        """
        if not self.is_available() or parent_id == 0:
            return []

        all_files = []
        page = 1

        while True:
            files = self.list_files(parent_id, page=page)
            if not files:
                break

            all_files.extend(files)

            # 如果返回的文件数少于每页数量，说明已经遍历完
            if len(files) < 100:
                break

            page += 1

        return all_files

    def get_all_video_files_recursive(self, parent_id: int, max_depth: int = 5) -> List[Dict]:
        """
        使用 p123client.tool.iterdir 递归获取目录下所有视频文件

        Args:
            parent_id: 目录ID
            max_depth: 最大递归深度

        Returns:
            所有视频文件列表
        """
        if not self.is_available() or parent_id == 0:
            return []

        all_files = []

        for item in iterdir(
            self.client,
            payload=parent_id,
            min_depth=1,
            max_depth=max_depth,
            # predicate=lambda a: not a["is_dir"],
            list_method="list_new",
        ):
            # 后置过滤：只处理视频文件
            if item.get("is_dir", False):
                continue  # 跳过文件夹
            all_files.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": 0 if not item.get("is_dir", False) else 1,
                    "size": item.get("size"),
                    "create_time": item.get("ctime"),
                    "update_time": item.get("mtime"),
                    "parent_path": item.get("parent_id"),
                }
            )

        return all_files

    def _get_content_type(self, media_type: str, origin_country: str) -> str:
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
                # 如果 extracted 中缺少这些字段，需要额外获取
                if not extracted.get("genres") or not extracted.get("origin_country"):
                    logger.info(f"元数据不完整，尝试获取完整TMDB信息: {metadata['show_name']}")
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
                                details = renamer_with_tmdb.tmdb_client.get_tv_details(tmdb_id)
                                if details:
                                    extracted["genres"] = [g["name"] for g in details.get("genres", [])]
                                    extracted["genre_ids"] = [g["id"] for g in details.get("genres", [])]
                                    extracted["origin_country"] = details.get("origin_country", [])
                                    extracted["original_language"] = details.get("original_language", "")
                                    logger.info(f"获取到TMDB信息: genres={extracted.get('genres')}, country={extracted.get('origin_country')}")
                    except Exception as e:
                        logger.warning(f"获取TMDB信息失败: {e}")

                # 使用 VideoRenamer 的 _determine_category 统一分类
                try:
                    renamer_with_config = VideoRenamer(
                        tmdb_api_key=self.tmdb_api_key,
                        config={}
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

    def get_file_detail(self, file_id: int) -> Optional[Dict]:
        """
        获取文件详情

        Args:
            file_id: 文件ID

        Returns:
            文件详情字典
        """
        if not self.is_available():
            return None

        try:
            result = self.client.fs_detail({"fileID": file_id})
            if result.get("code") == 0:
                return result.get("data", {})
            else:
                logger.error(f"获取文件详情失败: {result.get('message')}")
                return None
        except Exception as e:
            logger.error(f"获取文件详情异常: {e}")
            return None

    def move_file(
        self, file_id: int, target_parent_id: int, new_name: Optional[str] = None
    ) -> bool:
        """
        移动文件到目标目录

        Args:
            file_id: 文件ID
            target_parent_id: 目标目录ID
            new_name: 新文件名（可选）

        Returns:
            是否移动成功
        """
        if not self.is_available():
            return False

        try:
            # 先重命名（如果需要）
            if new_name:
                rename_payload = {"fileId": file_id, "fileName": new_name}
                rename_result = self.client.fs_rename_one(rename_payload)
                if rename_result.get("code") != 0:
                    logger.error(f"重命名失败: {rename_result.get('message')}")
                    return False

            # 移动文件
            move_payload = {
                "fileIdList": [{"FileId": file_id}],
                "parentFileId": target_parent_id,
                "event": "fileMove",
            }
            move_result = self.client.fs_move(move_payload)

            if move_result.get("code") == 0:
                logger.info(
                    f"移动文件成功: file_id={file_id}, target={target_parent_id}"
                )
                return True
            else:
                logger.error(f"移动文件失败: {move_result.get('message')}")
                return False

        except Exception as e:
            logger.error(f"移动文件异常: {e}")
            return False

    def create_folder(self, parent_id: int, name: str) -> Optional[int]:
        """
        创建文件夹

        Args:
            parent_id: 父目录ID
            name: 文件夹名称

        Returns:
            新文件夹ID，失败返回None
        """
        if not self.is_available():
            return None

        try:
            result = self.client.fs_mkdir(name, parent_id=parent_id)
            if result.get("code") == 0:
                return result.get("data", {}).get("Info", {}).get("FileId")
            else:
                logger.error(f"创建文件夹失败: {result.get('message')}")
                return None
        except Exception as e:
            logger.error(f"创建文件夹异常: {e}")
            return None

    def find_or_create_folder(self, parent_id: int, name: str) -> int:
        """
        查找文件夹，如果不存在则创建

        Args:
            parent_id: 父目录ID
            name: 文件夹名称

        Returns:
            文件夹ID
        """
        if not self.is_available():
            return 0

        # 先查找是否已存在
        files = self.list_files(parent_id, page=1)
        for f in files:
            if f.get("name") == name and f.get("type") == 0:  # 0表示文件夹
                logger.info(f"找到已存在的文件夹: {name} (id={f.get('id')})")
                return f.get("id")

        # 不存在则创建
        folder_id = self.create_folder(parent_id, name)
        if folder_id:
            logger.info(f"创建文件夹成功: {name} (id={folder_id})")
            return folder_id

        logger.error(f"创建文件夹失败: {name}")
        return 0

    def organize_file(
        self,
        file_info: Dict,
        target_parent_id: int,
        name_format: str = "{show_name} - {season_episode}",
    ) -> bool:
        """
        整理单个文件

        Args:
            file_info: 文件信息（包含tmdb_id, show_name, year, season, episode等）
            target_parent_id: 目标目录ID
            name_format: 命名格式

        Returns:
            是否整理成功
        """
        if not self.is_available():
            return False

        file_id = file_info.get("id")
        if not file_id:
            logger.error("文件信息中缺少id")
            return False

        # 解析文件元数据
        show_name = file_info.get("show_name", "")
        year = file_info.get("year", "")
        tmdb_id = file_info.get("tmdb_id", "")
        season = file_info.get("season", "")
        episode = file_info.get("episode", "")
        media_type = file_info.get("media_type", "tv")
        category_path = file_info.get("category_path", "TV Shows/电视剧")

        if not show_name:
            logger.warning(f"文件缺少show_name，跳过: file_id={file_id}")
            return False

        # 生成新文件名
        new_name = self._generate_name(
            show_name, year, tmdb_id, season, episode, name_format,
            original_name=file_info.get("name", ""),
            quality_tags=file_info.get("quality_tags", ""),
            release_group=file_info.get("release_group", "")
        )

        # 构建目标路径（包含分类子文件夹）
        target_path = self._build_target_path(
            show_name, year, tmdb_id, media_type, category_path, target_parent_id
        )

        # 处理嵌套文件夹路径（如 "TV Shows/国漫/剧集名/Season 01"）
        root_folder = target_path["root_folder"]
        folder_name = target_path["folder_name"]

        # 先找到根目录（TV Shows 或 Movies）
        root_folder_id = self.find_or_create_folder(target_parent_id, root_folder.split("/")[0])
        if not root_folder_id:
            logger.error(f"创建根目录失败: {root_folder.split('/')[0]}")
            return False

        # 如果有子分类，先创建分类文件夹
        if "/" in root_folder:
            category_name = root_folder.split("/")[1]
            target_folder_id = self.find_or_create_folder(root_folder_id, category_name)
            if not target_folder_id:
                logger.error(f"创建分类文件夹失败: {category_name}")
                return False
        else:
            target_folder_id = root_folder_id

        # 创建剧集文件夹
        show_folder_id = self.find_or_create_folder(target_folder_id, folder_name)
        if not show_folder_id:
            logger.error(f"创建剧集文件夹失败: {folder_name}")
            return False

        # 如果是电视剧，创建 Season 子文件夹
        if media_type != "movie" and season:
            season_folder_name = f"Season {int(season):02d}"
            target_folder_id = self.find_or_create_folder(show_folder_id, season_folder_name)
            if not target_folder_id:
                logger.error(f"创建Season文件夹失败: {season_folder_name}")
                return False
        else:
            target_folder_id = show_folder_id

        # 移动文件
        return self.move_file(file_id, target_folder_id, new_name)

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
            for video_ext in [".mp4", ".mkv", ".avi", ".mov", ".wmv"]:
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
        parent_id: int,
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
        source_id: int = None,
        target_id: int = None,
        files: List[Dict] = None,
        dry_run: bool = False,
    ) -> Dict:
        """
        整理所有文件

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

        if source_id == 0:
            logger.error("源目录ID未设置")
            return {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": ["源目录ID未设置"],
            }

        if target_id == 0:
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
            if not any(
                name.endswith(ext) for ext in [".mp4", ".mkv", ".avi", ".mov", ".wmv"]
            ):
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
                        f["category_path"] = metadata.get("category_path", "TV Shows/电视剧")
                        logger.info(
                            f"通过文件名识别元数据: {f.get('name')} -> {metadata['show_name']} ({metadata['category_path']})"
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
