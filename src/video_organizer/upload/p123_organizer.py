"""
123网盘文件整理功能
识别源目录中的文件，重命名后移动到目标目录
"""

import logging
from typing import Dict, Optional, List, Union

from .pan123_client import Pan123Client
from .base_organizer import BaseCloudOrganizer

logger = logging.getLogger(__name__)


class P123Organizer(BaseCloudOrganizer):
    """123网盘文件整理器"""

    def __init__(
        self,
        token: str = "",
        organize_source_id: int = 0,
        organize_target_id: int = 0,
        max_workers: int = 2,
        tmdb_api_key: Optional[str] = None,
        username: str = "",
        password: str = "",
    ):
        """
        初始化123网盘整理器

        Args:
            token: 123云盘访问令牌
            organize_source_id: 需要整理的源目录ID
            organize_target_id: 整理到的目标目录ID
            max_workers: 最大并发工作线程数
            tmdb_api_key: TMDB API密钥（用于从文件名识别元数据）
            username: 123云盘用户名（用于自动登录获取 token）
            password: 123云盘密码
        """
        super().__init__(tmdb_api_key=tmdb_api_key, max_workers=max_workers)
        self.token = token
        self.username = username
        self.password = password
        self.organize_source_id = organize_source_id
        self.organize_target_id = organize_target_id
        self.client = (
            Pan123Client(token=token, username=username, password=password)
            if (token or (username and password))
            else None
        )

    def is_available(self) -> bool:
        """检查整理功能是否可用（已配置账号或令牌即视为可用，登录在调用时惰性进行）"""
        return self.client is not None and bool(
            self.token or (self.username and self.password)
        )

    def list_files(
        self, parent_id: Union[str, int], page: int = 1, per_page: int = 100
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

    def get_all_video_files_recursive(
        self, parent_id: Union[str, int], max_depth: int = 5
    ) -> List[Dict]:
        if not self.is_available() or parent_id == 0:
            return []

        all_files = []
        for item in self.client.iterdir(
            parent_id=parent_id, min_depth=1, max_depth=max_depth
        ):
            if item.get("is_dir", False):
                continue
            all_files.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": 0,
                    "size": item.get("size"),
                    "create_time": item.get("ctime"),
                    "update_time": item.get("mtime"),
                    "parent_path": item.get("parent_id"),
                }
            )
        return all_files

    def yield_files_recursive(self, parent_id: Union[str, int], max_depth: int = 5):
        if not self.is_available() or parent_id == 0:
            return

        for item in self.client.iterdir(
            parent_id=parent_id, min_depth=1, max_depth=max_depth
        ):
            if item.get("is_dir", False):
                continue
            yield {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": 0,
                "size": item.get("size"),
                "create_time": item.get("ctime"),
                "update_time": item.get("mtime"),
                "parent_path": item.get("parent_id"),
            }

    def count_video_files(self, parent_id: Union[str, int], max_depth: int = 5) -> int:
        if not self.is_available() or parent_id == 0:
            return 0

        count = 0
        for item in self.client.iterdir(
            parent_id=parent_id, min_depth=1, max_depth=max_depth
        ):
            if not item.get("is_dir", False):
                count += 1
        return count

    def get_file_detail(self, file_id: Union[str, int]) -> Optional[Dict]:
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
            # 先重命名（如果需要）
            if new_name:
                rename_payload = {"fileId": file_id, "fileName": new_name}
                rename_result = self.client.fs_rename(rename_payload)
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
            rename_payload = {"fileId": file_id, "fileName": new_name}
            result = self.client.fs_rename(rename_payload)
            if result.get("code") == 0:
                logger.info(f"重命名成功: file_id={file_id} -> {new_name}")
                return True
            self._last_error = result.get("message", "重命名失败")
            logger.error(f"重命名失败: {self._last_error}")
            return False
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"重命名异常: {e}")
            return False

    def move_files(
        self,
        file_ids: List[Union[str, int]],
        target_parent_id: Union[str, int],
    ) -> Dict:
        """
        批量移动文件到目标目录（单次 mod_pid 调用）

        失败时自动重试一次，仍失败则回退为逐文件移动以隔离问题文件。

        Args:
            file_ids: 文件ID列表
            target_parent_id: 目标目录ID

        Returns:
            {"success": 成功数量, "errors": [失败原因...]}
        """
        ids = list(file_ids)
        if not ids:
            return {"success": 0, "errors": []}
        if not self.is_available():
            return {"success": 0, "errors": ["整理功能不可用"]}

        # 批量移动（重试一次）
        for attempt in range(2):
            try:
                move_payload = {
                    "fileIdList": [{"FileId": fid} for fid in ids],
                    "parentFileId": target_parent_id,
                    "event": "fileMove",
                }
                result = self.client.fs_move(move_payload)
                if result.get("code") == 0:
                    logger.info(
                        f"批量移动成功: {len(ids)} 个文件 -> {target_parent_id}"
                    )
                    return {"success": len(ids), "errors": []}
                logger.warning(
                    f"批量移动失败(第{attempt + 1}次): {result.get('message')}"
                )
            except Exception as e:
                logger.warning(f"批量移动异常(第{attempt + 1}次): {e}")

        # 回退为逐文件移动，隔离问题文件
        logger.warning(f"批量移动失败，回退逐文件移动: {len(ids)} 个文件")
        success = 0
        errors: List[str] = []
        for fid in ids:
            if self.move_file(fid, target_parent_id):
                success += 1
            else:
                errors.append(f"移动失败: file_id={fid} - {self._last_error}")
        return {"success": success, "errors": errors}

    def create_folder(self, parent_id: Union[str, int], name: str) -> Optional[int]:
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

    def find_or_create_folder(self, parent_id: Union[str, int], name: str) -> int:
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

        cache_key = f"{parent_id}_{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        # 先查找是否已存在
        files = self.list_files(parent_id, page=1)
        for f in files:
            if f.get("name") == name and f.get("type") == 1:  # 1表示文件夹
                logger.info(f"找到已存在的文件夹: {name} (id={f.get('id')})")
                self._folder_cache[cache_key] = f.get("id")
                return f.get("id")

        # 不存在则创建
        folder_id = self.create_folder(parent_id, name)
        if folder_id:
            logger.info(f"创建文件夹成功: {name} (id={folder_id})")
            self._folder_cache[cache_key] = folder_id
            return folder_id

        logger.error(f"创建文件夹失败: {name}")
        return 0
