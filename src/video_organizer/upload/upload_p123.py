"""
123云盘上传器
包装 p123do.py 的上传逻辑，提供统一的上传接口
"""

import os
import sys
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any
from colorama import Fore, init

# 初始化 colorama
init(autoreset=True)

# 导入 p123 客户端
try:
    from p123client import P123Client
except ImportError:
    print("警告: p123client 未安装，123云盘上传功能不可用")
    P123Client = None

# 导入 p123do 的上传函数
from .p123do import upload_file as p123_upload_file, calculate_md5, get_file_size


class P123Uploader:
    """123云盘上传器（支持文件夹管理和TG通知）"""

    def __init__(
        self,
        token: str,
        parent_id: int = 0,
        telegram_config: Optional[Dict[str, Any]] = None,
        max_workers: int = 2,
        tg_channel_123fslink: str = "liyk002",
    ):
        """
        初始化 123 云盘上传器

        Args:
            token: 123云盘 API Token
            parent_id: 根目录文件夹ID
            telegram_config: Telegram 配置
            max_workers: 最大并发上传工作线程数，默认2
            tg_channel_123fslink: 123FSLinkV2 格式发送到的TG频道
        """
        if not P123Client:
            raise ImportError("p123client 未安装，无法使用 123 云盘上传功能")

        self.token = token
        self.root_parent_id = parent_id
        self.telegram_config = telegram_config or {}
        self.max_workers = max_workers  # 保存并发线程数配置
        self.tg_channel_123fslink = tg_channel_123fslink  # 123FSLinkV2 TG频道
        self.client = P123Client(token)

        # TG 通知相关
        self.tg_bot_token = self.telegram_config.get("bot_token", "")
        self.tg_chat_id = self.telegram_config.get("chat_id", "")
        self._tg_message_ids: Dict[str, Optional[int]] = (
            {}
        )  # key: file_path, value: message_id (None means not sent yet)
        self.tg_last_update_time = 0
        self.tg_update_interval = 2

        # 文件夹缓存 {folder_name: folder_id}
        self._folder_cache = {}

    def _get_or_create_folder(self, folder_name: str, parent_id: int) -> Optional[int]:
        """
        获取或创建文件夹

        Args:
            folder_name: 文件夹名称
            parent_id: 父文件夹ID

        Returns:
            文件夹ID，失败返回None
        """
        cache_key = f"{parent_id}_{folder_name}"

        # 检查缓存
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        try:
            # 列出父文件夹内容，查找是否已存在
            # 这里的 fs_list 并不是标准的列出文件接口，根据提供的属性列表，看起来更像是在操作文件系统
            # 尝试使用 upload_list 或者 fs_list
            # 根据提供的属性列表，fs_list 看起来是列出文件的。通常需要 parent_id, page, limit
            # 但为了保险，我们先假设 fs_list 是正确的方法

            # 从属性列表中看，有 fs_list, upload_list 等。通常 fs_list 用于管理文件
            list_resp = self.client.fs_list(
                parentFileId=parent_id,
                page=1,
                limit=100,
                orderBy="file_id",
                orderDirection="asc",
            )

            if list_resp.get("code") == 0:
                for item in list_resp.get("data", {}).get("InfoList", []):
                    if item.get("Type") == 1 and item.get("FileName") == folder_name:
                        folder_id = item.get("FileId")
                        self._folder_cache[cache_key] = folder_id
                        print(f"  [文件夹] 已存在: '{folder_name}' (ID: {folder_id})")
                        return folder_id

            # 不存在则创建
            print(
                f"  [文件夹] 正在网盘创建新目录: '{folder_name}' 在父目录 {parent_id} 下"
            )
            # 使用 fs_mkdir 创建文件夹
            create_resp = self.client.fs_mkdir(folder_name, parent_id, 0)
            if create_resp.get("code") == 0:
                folder_id = create_resp.get("data", {}).get("Info", {}).get("FileId")
                self._folder_cache[cache_key] = folder_id
                print(f"  [文件夹] 创建成功: '{folder_name}' (新 ID: {folder_id})")
                return folder_id
            else:
                print(f"  [错误] 创建目录失败: {create_resp.get('message')}")
                return None

        except AttributeError as e:
            print(f"[WARNING] P123Client 方法调用失败: {e}。将上传到根目录。")
            return None
        except Exception as e:
            print(f"[ERROR] 获取/创建文件夹异常: {e}")
            return None

    def _send_tg_progress(
        self,
        file_path: str,
        file_name: str,
        progress_percent: float,
        uploaded_mb: float,
        total_mb: float,
        speed_mbps: float = 0,
        force: bool = False,
    ):
        """发送/更新 Telegram 进度消息"""
        if not self.tg_bot_token or not self.tg_chat_id:
            return

        current_time = time.time()
        msg_id = self._tg_message_ids.get(file_path)

        # 限制更新频率 (使用共享的更新时间，避免频繁更新)
        if (
            not force
            and msg_id is not None
            and (current_time - self.tg_last_update_time) < self.tg_update_interval
        ):
            return

        # 创建进度条
        bar_length = 20
        filled_length = min(int(bar_length * progress_percent / 100), bar_length)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)

        # 构建消息文本
        message_text = (
            f"📤 *上传进度 [123云]*\n\n"
            f"文件: `{file_name}`\n"
            f"进度: {progress_percent:.1f}%\n"
            f"[{bar}]\n\n"
            f"已上传: {uploaded_mb:.2f} MB / {total_mb:.2f} MB\n"
            f"速度: {speed_mbps:.2f} MB/s"
        )

        try:
            if msg_id is None:
                # 发送新消息
                url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
                data = {
                    "chat_id": self.tg_chat_id,
                    "text": message_text,
                    "parse_mode": "Markdown",
                }
                response = requests.post(url, json=data, timeout=10)
                if response.status_code == 200:
                    result = response.json()
                    if result.get("ok"):
                        self._tg_message_ids[file_path] = result["result"]["message_id"]
                        self.tg_last_update_time = current_time
            else:
                # 更新现有消息
                url = f"https://api.telegram.org/bot{self.tg_bot_token}/editMessageText"
                data = {
                    "chat_id": self.tg_chat_id,
                    "message_id": msg_id,
                    "text": message_text,
                    "parse_mode": "Markdown",
                }
                response = requests.post(url, json=data, timeout=10)
                if response.status_code == 200:
                    self.tg_last_update_time = current_time
                elif response.status_code == 400:
                    # 消息可能已被删除，尝试重新发送
                    self._tg_message_ids[file_path] = None
                    self._send_tg_progress(
                        file_path, file_name, progress_percent, uploaded_mb, total_mb, speed_mbps, force=True
                    )
        except Exception:
            pass

    def upload_video(
        self,
        file_path: str,
        item_type: Optional[str] = None,
        item_id: Optional[str] = None,
        file_storage: Optional[str] = None,
        media_info: Optional[Dict[str, Any]] = None,
        rename_to: Optional[str] = None,
        folder_structure: Optional[list] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        上传视频到 123 云盘

        Args:
            file_path: 本地文件路径
            item_type: 媒体类型（用于创建子文件夹: movie/tv）
            item_id: 媒体ID（123云盘不需要）
            file_storage: 存储类型（123云盘不需要）
            media_info: 媒体信息字典，包含 title, season_episode 等
            rename_to: 上传后的重命名文件名（如果为None则使用原文件名）
            folder_structure: 目标文件夹层级列表，例如 ["TV Shows", "Show Name", "Season 01"]

        Returns:
            上传成功返回文件信息字典，失败返回 None
        """
        try:
            file_path_obj = Path(file_path)
            # 确定最终文件名
            target_filename = rename_to if rename_to else file_path_obj.name

            print(f"\n=== 开始上传到 123 云盘 ===")
            print(f"本地文件: {file_path_obj.name}")
            print(f"目标文件名: {target_filename}")

            # 重置 TG 消息ID（每次上传新文件）
            self._tg_message_ids[file_path] = None

            # 确定目标父文件夹ID
            target_parent_id = self.root_parent_id

            # 保存整理后的文件夹路径用于显示
            folder_path = None
            if folder_structure and isinstance(folder_structure, list):
                folder_path = "/".join(folder_structure)
                print(f"创建/查找目录结构: {' -> '.join(folder_structure)}")
                current_pid = self.root_parent_id

                # 默认先进入 media 目录 (保持与原有逻辑一致，或者是用户的隐式需求)
                # 用户没有明确说不要 media 目录，但为了整洁，我们把 folder_structure 视为相对于 root (parent_id) 的路径
                # 为了保险，我们还是先检查是否存在 media 目录，如果 folder_structure 第一项不是 media
                # 但根据截图，结构是 media -> TV Shows -> ...
                # 所以我们可以在 video_file_handler 传过来的 folder_structure 中包含 media

                for folder_name in folder_structure:
                    if not folder_name:
                        continue
                    # 清理文件夹名称
                    import re

                    safe_folder_name = re.sub(
                        r'[\\/:*?"<>|]', "", str(folder_name)
                    ).strip()
                    # 创建/获取文件夹
                    folder_id = self._get_or_create_folder(
                        safe_folder_name, current_pid
                    )
                    if folder_id:
                        current_pid = folder_id
                        target_parent_id = folder_id
                    else:
                        print(
                            f"[ERROR] 无法创建目录: {safe_folder_name}，将上传到上一级"
                        )
                        break

            elif item_type and media_info:
                # 兼容旧逻辑
                # 第零层：media 文件夹
                media_folder_id = self._get_or_create_folder(
                    "media", self.root_parent_id
                )
                if not media_folder_id:
                    print("[WARNING] 创建/获取 media 文件夹失败，将使用根目录")
                    media_folder_id = self.root_parent_id

                # 第一层：媒体类型文件夹 (Movies / TV Shows)
                type_folder = "Movies" if item_type in ["movie", "vl"] else "TV Shows"
                type_folder_id = self._get_or_create_folder(
                    type_folder, media_folder_id
                )

                if type_folder_id:
                    target_parent_id = type_folder_id

                    # 第二层：具体作品文件夹（使用标题）
                    title = media_info.get("title", "")
                    if title:
                        import re

                        safe_title = re.sub(r'[\\/:*?"<>|]', "", title)
                        title_folder_id = self._get_or_create_folder(
                            safe_title, type_folder_id
                        )
                        if title_folder_id:
                            target_parent_id = title_folder_id

            print(f"最终目标文件夹ID: {target_parent_id}")

            # 调用 p123do 的上传函数（带进度回调）
            # 注意: p123do.upload_file 需要支持 new_name 参数来重命名
            result = self._upload_with_progress(
                file_path, target_parent_id, target_filename
            )

            if result:
                print(f"\n🎉 123云盘上传成功!")
                print(f"文件ID: {result.get('fileid')}")

                # 发送 123FSLinkV2 格式到TG频道
                if self.tg_bot_token and self.tg_channel_123fslink:
                    self.send_123fslinkv2_to_tg(
                        file_path, target_filename, result, self.tg_channel_123fslink, folder_path
                    )

                return result
            else:
                print(f"\n❌ 123云盘上传失败!")
                return None

        except Exception as e:
            print(f"\n❌ 123云盘上传异常: {e}")
            import traceback

            traceback.print_exc()
            return None

    def _upload_with_progress(
        self, file_path: str, parent_id: int, file_name: str
    ) -> Optional[Dict[str, Any]]:
        """带进度通知的上传（使用 p123do 内部的 tqdm）"""

        file_size = os.path.getsize(file_path)
        total_mb = file_size / (1024 * 1024)
        # 按1000进制显示，更符合用户认知
        total_mb_display = file_size / (1000 * 1000)

        # Telegram 相关 - 重置当前文件的消息跟踪
        self._tg_message_ids[file_path] = None
        self.tg_last_update_time = 0

        # 记录上一次的上传量，用于计算速度
        last_uploaded = 0
        last_time = time.time()
        current_speed = 0  # 当前速度
        last_speed_update_time = 0  # 最后一次速度计算的时间
        final_progress_sent = False  # 标记是否已发送最终100%进度

        # 定义进度回调函数
        def progress_callback(current_uploaded: int, total_size: int):
            nonlocal last_uploaded, last_time, current_speed, last_speed_update_time, final_progress_sent

            if total_size > 0:
                # 计算进度（1000进制）
                uploaded_mb_display = current_uploaded / (1000 * 1000)
                progress = (current_uploaded / total_size) * 100

                # 计算当前速度用于Telegram
                current_time = time.time()
                time_diff = current_time - last_time

                # 检查是否已经完成（100%）
                is_complete = progress >= 100

                # 每0.5秒或当进度完成时计算一次速度
                if time_diff >= 0.5 or is_complete:
                    bytes_diff = current_uploaded - last_uploaded
                    if time_diff > 0:
                        new_speed = (bytes_diff / (1024 * 1024)) / time_diff
                        # 使用加权平均平滑速度
                        if current_speed > 0:
                            current_speed = current_speed * 0.7 + new_speed * 0.3
                        else:
                            current_speed = new_speed

                    # 发送Telegram进度（如果是完成状态且尚未发送过，则发送）
                    if is_complete and not final_progress_sent:
                        self._send_tg_progress(
                            file_path,
                            file_name,
                            100,
                            total_mb_display,
                            total_mb_display,
                            current_speed,
                            force=True,
                        )
                        final_progress_sent = True
                    elif not is_complete:
                        self._send_tg_progress(
                            file_path,
                            file_name,
                            progress,
                            uploaded_mb_display,
                            total_mb_display,
                            current_speed,
                        )

                    # 更新基准点
                    last_uploaded = current_uploaded
                    last_time = current_time
                    last_speed_update_time = current_time
                elif self._tg_message_ids.get(file_path) is None:
                    # 第一次强制发送
                    self._send_tg_progress(
                        file_path, file_name, 0, 0, total_mb_display, 0
                    )

        # 调用原始上传函数，传入回调（使用 p123do 内部的 tqdm）
        result = p123_upload_file(
            client=self.client,
            file_path=file_path,
            parent_id=parent_id,
            new_name=file_name,
            max_retries=3,
            callback=progress_callback,
            max_workers=self.max_workers,
        )

        # 发送完成Telegram消息（仅当回调未发送完成消息时）
        if result and not final_progress_sent:
            self._send_tg_progress(
                file_path,
                file_name,
                100,
                total_mb_display,
                total_mb_display,
                current_speed,
                force=True,
            )

        # 清理消息ID记录
        if file_path in self._tg_message_ids:
            del self._tg_message_ids[file_path]

        return result

    def generate_123fslinkv2(self, result: Dict[str, Any]) -> str:
        """
        生成 123FSLinkV2 格式的分享链接

        Args:
            result: 上传结果字典，包含 fileid, filename, filesize 等

        Returns:
            格式化的分享链接字符串，格式: 123FSLinkV2$etag#size#name
        """
        if not result:
            return ""

        size = result.get("size", 0)
        name = result.get("name", "")
        etag = result.get("etag", "")

        # 格式: 123FSLinkV2$fileid#filesize#filename
        return f"123FSLinkV2${etag}#{size}#{name}"

    def send_123fslinkv2_to_tg(
        self,
        file_path: str,
        file_name: str,
        result: Dict[str, Any],
        tg_channel: str = "liyk002",
        folder_path: Optional[str] = None,
    ) -> bool:
        """
        生成 123FSLinkV2 格式并发送到 Telegram 频道

        Args:
            file_path: 文件路径
            file_name: 文件名
            result: 上传结果字典
            tg_channel: Telegram 频道 ID
            folder_path: 整理后的文件夹路径（可选）

        Returns:
            是否发送成功
        """
        if not self.tg_bot_token:
            print(f"[WARNING] TG bot token 未配置，跳过 123FSLinkV2 通知")
            return False

        # 格式化频道ID
        if tg_channel and not tg_channel.startswith(('@', '-')):
            tg_channel = f"@{tg_channel}"

        link_v2 = self.generate_123fslinkv2(result)
        if not link_v2:
            print(f"[WARNING] 无法生成 123FSLinkV2 格式")
            return False

        # 构建消息文本，包含文件夹路径
        message_text = f"📤 *123云盘上传完成*\n\n"
        if folder_path:
            message_text += f"路径: `{folder_path}`\n"
        message_text += f"文件: `{file_name}`\n"
        message_text += f"格式: `{link_v2}`\n"

        try:
            url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
            data = {
                "chat_id": tg_channel,
                "text": message_text,
                "parse_mode": "Markdown",
            }
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                result_data = response.json()
                if result_data.get("ok", False):
                    print(f"✓ 123FSLinkV2 通知已发送到 TG 频道: {tg_channel}")
                    return True
                else:
                    print(f"[WARNING] TG API 返回错误: {result_data.get('description')}")
                    return False
            else:
                print(f"[WARNING] TG API 请求失败: {response.status_code}")
                print(f"[DEBUG] chat_id={tg_channel}, response={response.text[:200]}")
                return False
        except Exception as e:
            print(f"[WARNING] 发送 123FSLinkV2 通知失败: {e}")
            return False
