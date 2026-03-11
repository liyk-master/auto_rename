"""
天翼云盘上传器
封装 cloud189_upload.py 的上传逻辑，提供统一的上传接口
"""

import os
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any

from .cloud189_upload import Cloud189Client


class Cloud189Uploader:
    """天翼云盘上传器"""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cookie: Optional[str] = None,
        parent_folder_id: str = "-11",
        family_id: str = "623471237149826045",
        token_file: Optional[str] = None,
        max_workers: int = 5,
        telegram_config: Optional[Dict[str, Any]] = None,
        strm_server: Optional[str] = None,
        strm_output_dir: Optional[str] = None,
        delete_after_strm: bool = False,
    ):
        """
        初始化天翼云盘上传器

        Args:
            username: 天翼云盘账号（手机号）
            password: 天翼云盘密码
            cookie: SSO Cookie（可选，与用户名密码二选一）
            parent_folder_id: 根目录文件夹ID，-11 为根目录
            token_file: Token 缓存文件路径
            max_workers: 并发上传线程数
            telegram_config: Telegram 通知配置
            strm_server: STRM 服务器地址，如 http://192.168.2.148:5000
            strm_output_dir: STRM 文件输出目录
            delete_after_strm: 生成 STRM 后是否删除云端文件
        """
        self.parent_folder_id = parent_folder_id
        self.family_id = family_id
        self.max_workers = max_workers
        self.telegram_config = telegram_config or {}
        self.strm_server = strm_server.rstrip("/") if strm_server else None
        self.strm_output_dir = strm_output_dir
        self.delete_after_strm = delete_after_strm

        # TG 通知相关
        self.tg_bot_token = self.telegram_config.get("bot_token", "")
        self.tg_chat_id = self.telegram_config.get("chat_id", "")
        self._tg_message_ids: Dict[str, Optional[int]] = {}
        self.tg_last_update_time = 0
        self.tg_update_interval = 2

        # 文件夹缓存 {folder_name: folder_id}
        self._folder_cache = {}

        # 初始化客户端
        self.client = Cloud189Client(
            username=username,
            password=password,
            cookie=cookie,
            token_file=token_file,
        )

    def _generate_strm_file(
        self,
        strm_url: str,
        file_name: str,
        folder_structure: Optional[list] = None,
    ) -> str:
        """
        生成 STRM 文件（按整理后的路径格式）

        Args:
            strm_url: STRM URL
            file_name: 文件名（可以是重命名后的文件名）
            folder_structure: 文件夹结构列表，例如 ["media", "TV Shows", "Show Name", "Season 01"]

        Returns:
            生成的 STRM 文件路径
        """
        from pathlib import Path
        import re

        # 创建输出目录
        output_dir = Path(self.strm_output_dir)

        # 如果有文件夹结构，创建对应的目录
        if folder_structure:
            # 过滤掉空字符串和 "media"
            folder_parts = [p for p in folder_structure if p and p.lower() != "media"]
            for part in folder_parts:
                # 替换非法字符
                safe_part = re.sub(r'[\\/:*?"<>|]', "", part)
                output_dir = output_dir / safe_part

        # 确保目录存在
        output_dir.mkdir(parents=True, exist_ok=True)

        # 生成 .strm 文件名（去掉原扩展名，加 .strm）
        base_name = os.path.splitext(file_name)[0]
        strm_file_name = f"{base_name}.strm"
        strm_file_path = output_dir / strm_file_name

        # 写入 URL 到文件
        with open(strm_file_path, 'w', encoding='utf-8') as f:
            f.write(strm_url)

        print(f"[Cloud189] STRM 文件已生成: {strm_file_path}")
        return str(strm_file_path)

    def _get_or_create_folder(self, folder_name: str, parent_id: str, family_id: Optional[str] = None) -> Optional[str]:
        """
        获取或创建文件夹

        Args:
            folder_name: 文件夹名称
            parent_id: 父文件夹ID
            family_id: 家庭云ID（可选，上传到家庭云时需要）

        Returns:
            文件夹ID
        """
        cache_key = f"{family_id or 'personal'}/{parent_id}/{folder_name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        try:
            # 尝试创建文件夹（如果已存在会返回已有的）
            result = self.client.create_folder(
                folder_name=folder_name,
                parent_folder_id=parent_id,
                family_id=family_id,
            )

            print(f"[Cloud189] create_folder 返回: {result}")

            # 检查创建结果
            # 家庭云成功: {"id": xxx, "name": "xxx", ...}
            # 个人云成功: {"res_code": 0, "id": xxx, ...}
            # 文件夹已存在: {"res_code": xxx, "res_message": "..."}
            folder_id = result.get("id") or result.get("folderId")
            
            if folder_id:
                self._folder_cache[cache_key] = str(folder_id)
                print(f"[Cloud189] 创建文件夹成功: {folder_name} -> {folder_id}")
                return str(folder_id)
            
            # 检查是否有 res_code 错误
            if result.get("res_code") and result.get("res_code") != 0:
                # 文件夹可能已存在，尝试查找
                print(f"[Cloud189] 创建文件夹返回: {result.get('res_message', result)}，尝试查找...")

            # 尝试在现有文件夹列表中查找
            files = self.client.list_files(folder_id=parent_id, page_size=100, family_id=family_id)

            # 家庭云返回: {"fileListAO": {"folderList": [...]}}
            # 个人云返回: {"fileListAO": {"fileFolderAO": [...]}}
            file_list_ao = files.get("fileListAO", {})
            folder_list = file_list_ao.get("folderList", []) or file_list_ao.get("fileFolderAO", [])
            
            print(f"[Cloud189] 找到 {len(folder_list)} 个文件夹")
            for item in folder_list:
                if item.get("name") == folder_name:
                    folder_id = str(item.get("id", ""))
                    self._folder_cache[cache_key] = folder_id
                    print(f"[Cloud189] 找到已存在文件夹: {folder_name} -> {folder_id}")
                    return folder_id

            print(f"[Cloud189] 获取/创建文件夹失败: {result}")
            return None

        except Exception as e:
            import traceback
            print(f"[Cloud189] 获取/创建文件夹异常: {e}")
            traceback.print_exc()
            return None

    def _build_folder_path(
        self,
        show_name: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        media_type: str = "tv",
    ) -> str:
        """
        构建文件夹路径

        Args:
            show_name: 剧名/电影名
            season: 季数
            episode: 集数
            media_type: 媒体类型

        Returns:
            文件夹路径字符串
        """
        # 清理名称中的非法字符
        safe_name = show_name.strip()
        for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            safe_name = safe_name.replace(char, '_')

        if media_type == "movie":
            return safe_name
        else:
            if season:
                return f"{safe_name}/Season {int(season):02d}"
            return safe_name

    def _send_tg_message(self, text: str, message_id: Optional[int] = None) -> Optional[int]:
        """发送 Telegram 消息"""
        if not self.tg_bot_token or not self.tg_chat_id:
            return None

        try:
            url = f"https://api.telegram.org/bot{self.tg_bot_token}"
            if message_id:
                resp = requests.post(
                    f"{url}/editMessageText",
                    json={"chat_id": self.tg_chat_id, "message_id": message_id, "text": text},
                    timeout=10,
                )
            else:
                resp = requests.post(
                    f"{url}/sendMessage",
                    json={"chat_id": self.tg_chat_id, "text": text},
                    timeout=10,
                )
            result = resp.json()
            if result.get("ok"):
                return result.get("result", {}).get("message_id")
        except Exception as e:
            print(f"[Cloud189] TG 通知失败: {e}")

        return message_id

    def upload_video(
        self,
        file_path: str,
        show_name: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        media_type: str = "tv",
        folder_structure: Optional[list] = None,
        rename_to: Optional[str] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        上传视频文件

        Args:
            file_path: 文件路径
            show_name: 剧名/电影名
            season: 季数
            episode: 集数
            media_type: 媒体类型
            folder_structure: 目标文件夹层级列表，例如 ["media", "TV Shows", "Show Name", "Season 01"]
            rename_to: 上传后的重命名文件名（用于 STRM 文件命名）

        Returns:
            上传结果字典，包含:
            - file_id: 文件ID
            - file_name: 文件名
            - url: 播放链接（如果可获取）
            - rapid_upload: 是否秒传
        """
        abs_path = os.path.abspath(file_path)
        original_file_name = os.path.basename(abs_path)
        # 用于 STRM 文件的文件名
        strm_file_name = rename_to if rename_to else original_file_name
        file_size = os.path.getsize(abs_path)

        # 是否使用家庭云
        use_family = bool(self.family_id)
        location_str = f"家庭云(ID: {self.family_id})" if use_family else "个人云"

        print(f"[Cloud189] 开始上传到{location_str}: {original_file_name}, 大小: {file_size / 1024 / 1024:.2f} MB")

        # 发送 TG 开始通知
        tg_text = f"☁️ [天翼云盘-{location_str}] 开始上传\n📁 {original_file_name}\n📊 {file_size / 1024 / 1024:.2f} MB"
        tg_msg_id = self._send_tg_message(tg_text)
        if tg_msg_id:
            self._tg_message_ids[file_path] = tg_msg_id

        try:
            # 直接上传到配置的目录，不创建子文件夹
            print(f"[Cloud189] 上传目录: {self.parent_folder_id}")

            # 进度回调
            def on_progress(percent: int):
                now = time.time()
                if now - self.tg_last_update_time >= self.tg_update_interval:
                    self.tg_last_update_time = now
                    speed = file_size * percent / 100 / (now - start_time) / 1024 / 1024
                    tg_text = (
                        f"☁️ [天翼云盘] 上传中...\n"
                        f"📁 {original_file_name}\n"
                        f"📊 {percent}% - {speed:.2f} MB/s"
                    )
                    self._send_tg_message(tg_text, self._tg_message_ids.get(file_path))

            start_time = time.time()

            # 执行上传
            result = self.client.upload_file(
                file_path=abs_path,
                parent_folder_id=self.parent_folder_id,
                family_id=self.family_id,
                max_workers=self.max_workers,
                show_progress=True,
                on_progress=on_progress,
            )

            if not result.success:
                raise RuntimeError(result.message)

            elapsed = time.time() - start_time
            speed = file_size / elapsed / 1024 / 1024

            # 发送完成通知
            rapid_tag = "⚡秒传" if result.rapid_upload else "✅完成"
            tg_text = (
                f"{rapid_tag} [天翼云盘]\n"
                f"📁 {original_file_name}\n"
                f"📊 {file_size / 1024 / 1024:.2f} MB\n"
                f"⏱️ {elapsed:.1f}s @ {speed:.2f} MB/s"
            )
            self._send_tg_message(tg_text, self._tg_message_ids.get(file_path))

            # 尝试获取下载链接
            download_url = None
            try:
                if result.user_file_id:
                    download_url = self.client.get_download_link(result.user_file_id)
            except Exception:
                pass

            # 生成 STRM URL
            strm_url = None
            if self.strm_server and result.file_md5 and result.slice_md5:
                from urllib.parse import quote
                # URL 编码文件名
                encoded_file_name = quote(result.file_name, safe='')
                strm_url = (
                    f"{self.strm_server}/createSecondUpload/"
                    f"{result.file_md5}/"
                    f"{result.file_size}/"
                    f"{result.slice_md5}/"
                    f"{encoded_file_name}"
                )
                print(f"[Cloud189] STRM URL: {strm_url}")

                # 生成 STRM 文件（使用标准路径格式）
                if self.strm_output_dir:
                    try:
                        strm_file_path = self._generate_strm_file(
                            strm_url=strm_url,
                            file_name=strm_file_name,
                            folder_structure=folder_structure,
                        )

                        # 生成 STRM 后删除云端文件
                        if self.delete_after_strm and result.user_file_id:
                            try:
                                delete_result = self.client.delete_file(
                                    file_id=result.user_file_id,
                                    file_name=result.file_name,
                                    is_folder=False,
                                    srcParentId=self.parent_folder_id,
                                    familyId=self.family_id
                                )
                                if delete_result.get("res_code") == 0:
                                    print(f"[Cloud189] 云端文件已删除: {result.file_name}")
                                else:
                                    print(f"[Cloud189] 删除云端文件失败: {delete_result.get('res_message', 'Unknown')}")
                            except Exception as e:
                                print(f"[Cloud189] 删除云端文件异常: {e}")
                    except Exception as e:
                        print(f"[Cloud189] 生成 STRM 文件失败: {e}")

            return {
                "file_id": result.user_file_id,
                "file_name": result.file_name,
                "file_size": result.file_size,
                "file_md5": result.file_md5,
                "slice_md5": result.slice_md5,
                "url": download_url,
                "strm_url": strm_url,
                "rapid_upload": result.rapid_upload,
            }

        except Exception as e:
            print(f"[Cloud189] 上传失败: {e}")
            # 发送错误通知
            tg_text = f"❌ [天翼云盘] 上传失败\n📁 {original_file_name}\n⚠️ {e}"
            self._send_tg_message(tg_text, self._tg_message_ids.get(file_path))
            return None

    def get_upload_url(self, file_id: str) -> Optional[str]:
        """
        获取文件下载链接

        Args:
            file_id: 文件ID

        Returns:
            下载链接
        """
        try:
            return self.client.get_download_link(file_id)
        except Exception as e:
            print(f"[Cloud189] 获取下载链接失败: {e}")
            return None

    def list_files(self, folder_id: str = "-11") -> list:
        """
        列出文件夹内容

        Args:
            folder_id: 文件夹ID

        Returns:
            文件列表
        """
        try:
            result = self.client.list_files(folder_id=folder_id)
            if result.get("res_code") == 0:
                return result.get("fileListAO", {}).get("fileListAO", [])
        except Exception as e:
            print(f"[Cloud189] 列出文件失败: {e}")
        return []

    def get_user_info(self) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        try:
            result = self.client.get_user_size_info()
            if result.get("res_code") == 0:
                return result
        except Exception as e:
            print(f"[Cloud189] 获取用户信息失败: {e}")
        return None
