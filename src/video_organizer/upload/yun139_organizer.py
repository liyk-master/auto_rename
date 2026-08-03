"""
139（移动）网盘文件整理功能
识别源目录中的文件，重命名后移动到目标目录
"""

import logging
from typing import Dict, List, Optional, Union

from .yun139_client import CloudType, FileInfo, Yun139
from .base_organizer import BaseCloudOrganizer

logger = logging.getLogger(__name__)


class Yun139Organizer(BaseCloudOrganizer):
    """139（移动）网盘文件整理器"""

    def __init__(
        self,
        authorization: str = "",
        cloud_type: str = "personal_new",
        cloud_id: str = "",
        organize_source_id: Union[str, int] = "",
        organize_target_id: Union[str, int] = "",
        max_workers: int = 2,
        tmdb_api_key: Optional[str] = None,
        app_mode: bool = False,
    ):
        """
        初始化139网盘整理器

        Args:
            authorization: Base64编码的认证信息
            cloud_type: 云盘类型: personal_new, personal, family, group
            cloud_id: 家庭云/群组云ID
            organize_source_id: 需要整理的源目录ID
            organize_target_id: 整理到的目标目录ID
            max_workers: 最大并发工作线程数
            tmdb_api_key: TMDB API密钥（用于从文件名识别元数据）
            app_mode: 使用 Android App 协议栈
        """
        super().__init__(tmdb_api_key=tmdb_api_key, max_workers=max_workers)
        self.authorization = authorization
        self.cloud_type = cloud_type
        self.cloud_id = cloud_id
        self.organize_source_id = organize_source_id
        self.organize_target_id = organize_target_id
        self.app_mode = app_mode
        self.client = (
            Yun139(
                authorization=authorization,
                cloud_type=CloudType(cloud_type),
                cloud_id=cloud_id,
                app_mode=app_mode,
            )
            if authorization
            else None
        )
        self._file_info_map: Dict[str, Dict] = {}

    def is_available(self) -> bool:
        """检查整理功能是否可用"""
        return self.client is not None and bool(self.authorization)

    def _to_dict(self, fi: FileInfo, parent_path: str = "") -> Dict:
        """将 FileInfo 转换为统一 dict 格式"""
        return {
            "id": fi.id,
            "name": fi.name,
            "type": 0 if not fi.is_folder else 1,
            "size": fi.size,
            "is_folder": fi.is_folder,
            "create_time": fi.created_time,
            "update_time": fi.modified_time,
            "path": fi.path,
            "parent_path": parent_path,
        }

    def list_files(
        self, parent_id: Union[str, int], page: int = 1, per_page: int = 100
    ) -> List[Dict]:
        """
        列出目录下的文件

        Args:
            parent_id: 目录ID（根目录为 "/"）
            page: 页码（139客户端内部已自动分页，此参数仅作兼容）
            per_page: 每页数量

        Returns:
            文件列表
        """
        if not self.is_available():
            return []

        try:
            files = self.client.list_files(str(parent_id))
            result = [self._to_dict(fi, str(parent_id)) for fi in files]
            # 缓存文件信息，供 move_file 重命名/移动时还原 FileInfo
            for d in result:
                self._file_info_map[str(d["id"])] = d
            return result
        except Exception as e:
            logger.error(f"列出文件异常: {e}")
            return []

    def _iter_recursive(self, parent_id: str, max_depth: int, depth: int = 1):
        """递归遍历目录（生成器）"""
        if depth > max_depth:
            return
        try:
            items = self.client.list_files(parent_id)
        except Exception as e:
            logger.error(f"递归列出文件异常: {parent_id}, {e}")
            return

        for fi in items:
            d = self._to_dict(fi, parent_id)
            self._file_info_map[str(d["id"])] = d
            yield d
            if fi.is_folder and depth < max_depth:
                yield from self._iter_recursive(fi.id, max_depth, depth + 1)

    def get_all_video_files_recursive(
        self, parent_id: Union[str, int], max_depth: int = 5
    ) -> List[Dict]:
        if not self.is_available():
            return []
        all_files = []
        for d in self._iter_recursive(str(parent_id), max_depth):
            if d.get("type") == 1:
                continue
            all_files.append(d)
        return all_files

    def yield_files_recursive(self, parent_id: Union[str, int], max_depth: int = 5):
        if not self.is_available():
            return
        for d in self._iter_recursive(str(parent_id), max_depth):
            if d.get("type") == 1:
                continue
            yield d

    def count_video_files(self, parent_id: Union[str, int], max_depth: int = 5) -> int:
        if not self.is_available():
            return 0
        count = 0
        for d in self._iter_recursive(str(parent_id), max_depth):
            if d.get("type") != 1:
                count += 1
        return count

    def get_file_detail(self, file_id: Union[str, int]) -> Optional[Dict]:
        """获取文件详情（139无单独详情接口，返回缓存信息）"""
        info = self._file_info_map.get(str(file_id))
        if info:
            return {"id": file_id, **info}
        return {"id": file_id}

    def _build_file_info(self, file_id: Union[str, int]) -> FileInfo:
        """根据 file_id 构造 FileInfo（优先使用缓存中的真实信息）"""
        info = self._file_info_map.get(str(file_id))
        if info:
            return FileInfo(
                id=str(file_id),
                name=info.get("name", ""),
                size=info.get("size", 0),
                is_folder=info.get("type") == 1,
                created_time=info.get("create_time"),
                modified_time=info.get("update_time"),
                path=info.get("path", ""),
            )
        return FileInfo(
            id=str(file_id),
            name="",
            size=0,
            is_folder=False,
            created_time=None,
            modified_time=None,
        )

    def move_file(
        self,
        file_id: Union[str, int],
        target_parent_id: Union[str, int],
        new_name: Optional[str] = None,
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
            file_info = self._build_file_info(file_id)

            # 先重命名（如果需要）
            if new_name:
                self.client.rename(file_info, new_name)
                logger.info(f"重命名成功: file_id={file_id} -> {new_name}")

            # 移动文件
            self.client.move(file_info, str(target_parent_id))
            logger.info(f"移动文件成功: file_id={file_id}, target={target_parent_id}")
            return True

        except Exception as e:
            logger.error(f"移动文件异常: file_id={file_id}, {e}")
            return False

    def rename_file(self, file_id: Union[str, int], new_name: str) -> bool:
        """
        仅重命名文件（不移动）

        Args:
            file_id: 文件ID
            new_name: 新文件名

        Returns:
            是否重命名成功
        """
        if not self.is_available():
            self._last_error = "整理功能不可用"
            return False
        try:
            file_info = self._build_file_info(file_id)
            self.client.rename(file_info, new_name)
            logger.info(f"重命名成功: file_id={file_id} -> {new_name}")
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"重命名异常: file_id={file_id}, {e}")
            return False

    def create_folder(self, parent_id: Union[str, int], name: str) -> Optional[str]:
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
            if self.client.mkdir(str(parent_id), name):
                # 创建成功后重新列出，获取新文件夹ID
                files = self.list_files(parent_id)
                for f in files:
                    if f.get("type") == 1 and f.get("name") == name:
                        return f.get("id")
                logger.error(f"创建文件夹后未找到文件夹ID: {name}")
                return None
            logger.error(f"创建文件夹失败: {name}")
            return None
        except Exception as e:
            logger.error(f"创建文件夹异常: {e}")
            return None

    def find_or_create_folder(self, parent_id: Union[str, int], name: str) -> str:
        """
        查找文件夹，如果不存在则创建

        Args:
            parent_id: 父目录ID
            name: 文件夹名称

        Returns:
            文件夹ID
        """
        if not self.is_available():
            return ""

        cache_key = f"{parent_id}_{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        # 先查找是否已存在
        files = self.list_files(parent_id)
        for f in files:
            if f.get("name") == name and f.get("type") == 1:  # 1表示文件夹
                logger.info(f"找到已存在的文件夹: {name} (id={f.get('id')})")
                self._folder_cache[cache_key] = str(f.get("id"))
                return str(f.get("id"))

        # 不存在则创建
        folder_id = self.create_folder(parent_id, name)
        if folder_id:
            logger.info(f"创建文件夹成功: {name} (id={folder_id})")
            self._folder_cache[cache_key] = folder_id
            return folder_id

        logger.error(f"创建文件夹失败: {name}")
        return ""
