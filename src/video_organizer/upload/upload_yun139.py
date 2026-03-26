"""
中国移动云盘（139云盘）上传器
包装 yun139.py 的上传逻辑，提供统一的上传接口
支持 STRM 文件生成
"""

import os
import re
import json
import time
import base64
import hashlib
import logging
import tempfile
import requests
import threading
from pathlib import Path
from urllib.parse import quote
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .yun139 import Yun139, CloudType, FileInfo

_logger = logging.getLogger(__name__)


def _report_upload_progress(
    file_path: str,
    filename: str,
    uploader: str,
    progress: float,
    uploaded_bytes: int,
    total_bytes: int,
    speed: str = "",
    status: str = "uploading",
    error: Optional[str] = None
):
    """报告上传进度到 Web 状态管理器"""
    try:
        from ..web.services.state import report_upload_progress
        report_upload_progress(
            file_path=file_path,
            filename=filename,
            uploader=uploader,
            progress=progress,
            uploaded_bytes=uploaded_bytes,
            total_bytes=total_bytes,
            speed=speed,
            status=status,
            error=error
        )
    except Exception:
        pass  # Web 模块未加载时忽略


class Yun139Uploader:
    """139云盘上传器（支持文件夹管理、TG通知和STRM生成）"""

    # 字幕扩展名
    SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.ssa', '.sub', '.vtt'}

    # 断点续传状态目录
    UPLOAD_STATE_DIR = os.path.join(tempfile.gettempdir(), "139", "upload_progress")

    def __init__(
        self,
        authorization: str,
        cloud_type: str = "personal_new",
        cloud_id: str = "",
        parent_id: str = "/",
        custom_part_size: int = 0,
        telegram_config: Optional[Dict[str, Any]] = None,
        strm_server: str = "",
        strm_output_dir: str = "",
        delete_after: bool = False,
    ):
        """
        初始化 139 云盘上传器

        Args:
            authorization: Base64编码的认证信息
            cloud_type: 云盘类型 (personal_new, personal, family, group)
            cloud_id: 家庭云/群组云ID
            parent_id: 根目录文件夹ID
            custom_part_size: 自定义分片大小，0为自动
            telegram_config: Telegram 配置
            strm_server: STRM 服务器地址，如 http://192.168.2.148:5010
            strm_output_dir: STRM 文件输出目录
            delete_after: 上传完成后删除云端文件
        """
        self.authorization = authorization
        # 处理 parent_id：保留原始值，/ 表示根目录
        self.parent_id = parent_id if parent_id else "/"
        self.telegram_config = telegram_config or {}
        self.strm_server = strm_server.rstrip('/') if strm_server else ""
        self.strm_output_dir = strm_output_dir
        self.delete_after = delete_after

        # 映射云盘类型
        cloud_type_map = {
            "personal_new": CloudType.PERSONAL_NEW,
            "personal": CloudType.PERSONAL,
            "family": CloudType.FAMILY,
            "group": CloudType.GROUP,
        }
        self.cloud_type = cloud_type_map.get(cloud_type, CloudType.PERSONAL_NEW)
        self.cloud_id = cloud_id

        # 初始化客户端
        self.client = Yun139(
            authorization=authorization,
            cloud_type=self.cloud_type,
            cloud_id=cloud_id,
            custom_part_size=custom_part_size,
        )

        # 刷新令牌并更新本地 authorization
        try:
            self.client.refresh_token()
            self.authorization = self.client.authorization
        except Exception as e:
            print(f"[WARNING] 刷新139云盘令牌失败: {e}")

        # TG 通知相关
        self.tg_bot_token = self.telegram_config.get("bot_token", "")
        self.tg_chat_id = self.telegram_config.get("chat_id", "")
        self.tg_channel_chat_id = self.telegram_config.get("channel_chat_id", "")  # 频道ID，用于发送JSON消息
        self._tg_message_ids: Dict[str, Optional[int]] = {}
        self.tg_last_update_time = 0
        self.tg_update_interval = 2

        # 文件夹缓存 {folder_name: folder_id}
        self._folder_cache = {}
        self._folder_lock = threading.Lock()  # 文件夹操作锁，防止多线程重复创建

        # 断点续传状态目录
        self._ensure_state_dir()

        # 刷新令牌
        try:
            self.client.refresh_token()
        except Exception as e:
            print(f"[WARNING] 刷新139云盘令牌失败: {e}")

    def _ensure_state_dir(self):
        """确保断点续传状态目录存在"""
        try:
            os.makedirs(self.UPLOAD_STATE_DIR, exist_ok=True)
        except Exception as e:
            print(f"[WARNING] 创建上传状态目录失败: {e}")

    def _get_state_file_path(self, file_path: str) -> str:
        """
        获取断点续传状态文件路径
        
        使用文件路径MD5作为文件名
        
        Args:
            file_path: 本地文件路径
            
        Returns:
            状态文件路径
        """
        path_md5 = hashlib.md5(file_path.encode()).hexdigest()
        return os.path.join(self.UPLOAD_STATE_DIR, f"{path_md5}.json")

    def _get_state_lock(self, file_path: str) -> threading.Lock:
        """
        获取状态文件对应的锁
        
        Args:
            file_path: 本地文件路径
            
        Returns:
            线程锁
        """
        path_md5 = hashlib.md5(file_path.encode()).hexdigest()
        if not hasattr(self, '_state_locks'):
            self._state_locks = {}
        if path_md5 not in self._state_locks:
            self._state_locks[path_md5] = threading.Lock()
        return self._state_locks[path_md5]

    def _save_upload_state(
        self,
        file_path: str,
        file_id: str,
        upload_id: str,
        content_hash: str,
        uploaded_parts: List[int]
    ):
        """
        保存上传状态到文件（线程安全）
        
        Args:
            file_path: 本地文件路径
            file_id: 云盘文件ID
            upload_id: 上传任务ID
            content_hash: 文件 SHA256 哈希值
            uploaded_parts: 已上传的分片号列表
        """
        try:
            with self._get_state_lock(file_path):
                state_file = self._get_state_file_path(file_path)
                state = {
                    "fileId": file_id,
                    "uploadId": upload_id,
                    "contentHash": content_hash,
                    "uploadedParts": uploaded_parts
                }
                
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  [WARNING] 保存上传状态失败: {e}")

    def _load_upload_state(self, file_path: str, content_hash: str) -> Optional[Dict[str, Any]]:
        """
        加载上传状态（线程安全）
        
        Args:
            file_path: 本地文件路径
            content_hash: 当前文件 SHA256 哈希值
            
        Returns:
            上传状态字典，不存在或哈希不匹配返回 None
        """
        try:
            with self._get_state_lock(file_path):
                state_file = self._get_state_file_path(file_path)
                
                if not os.path.exists(state_file):
                    return None
                
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                
                # 验证 SHA256 是否一致（确保是同一文件）
                if state.get("contentHash") != content_hash:
                    print(f"  [断点续传] 文件内容已变化，放弃断点续传")
                    self._clear_upload_state(file_path)
                    return None
                
                return state
        except Exception as e:
            print(f"  [WARNING] 加载上传状态失败: {e}")
            return None

    def _clear_upload_state(self, file_path: str):
        """
        清除上传状态文件（线程安全）
        
        Args:
            file_path: 本地文件路径
        """
        try:
            with self._get_state_lock(file_path):
                state_file = self._get_state_file_path(file_path)
                if os.path.exists(state_file):
                    os.remove(state_file)
        except Exception as e:
            print(f"  [WARNING] 清除上传状态失败: {e}")

    def _get_or_create_folder(self, folder_name: str, parent_id: str) -> Optional[str]:
        """
        获取或创建文件夹（线程安全）

        Args:
            folder_name: 文件夹名称
            parent_id: 父文件夹ID

        Returns:
            文件夹ID，失败返回None
        """
        cache_key = f"{parent_id}_{folder_name}"
        
        # 先检查缓存（无锁快速路径）
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        # 使用锁保护目录创建
        with self._folder_lock:
            # 双重检查：获取锁后再次检查缓存
            if cache_key in self._folder_cache:
                return self._folder_cache[cache_key]

            try:
                # 列出父文件夹内容，查找是否已存在
                files = self.client.list_files(parent_id)

                for f in files:
                    if f.is_folder and f.name == folder_name:
                        self._folder_cache[cache_key] = f.id
                        print(f"  [文件夹] 已存在: '{folder_name}' (ID: {f.id})")
                        return f.id

                # 不存在则创建
                print(f"  [文件夹] 正在创建新目录: '{folder_name}'")
                if self.client.mkdir(parent_id, folder_name):
                    # 重新获取文件夹ID
                    files = self.client.list_files(parent_id)
                    for f in files:
                        if f.is_folder and f.name == folder_name:
                            self._folder_cache[cache_key] = f.id
                            print(f"  [文件夹] 创建成功: '{folder_name}' (ID: {f.id})")
                            return f.id

                print(f"  [错误] 创建目录失败")
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

        # 限制更新频率
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
            f"📤 *上传进度 [139云]*\n\n"
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

    def _send_tg_channel_message(self, message: str) -> bool:
        """
        发送消息到 TG 频道

        Args:
            message: 要发送的消息文本

        Returns:
            发送成功返回 True
        """
        if not self.tg_bot_token:
            print(f"[DEBUG] TG频道: bot_token 未配置")
            return False
        if not self.tg_channel_chat_id:
            print(f"[DEBUG] TG频道: channel_chat_id 未配置")
            return False

        # 格式化频道ID（参考123云盘实现）
        tg_channel = self.tg_channel_chat_id
        if tg_channel:
            # 去除行尾注释（分号或井号后面的内容）
            for sep in [';', '#']:
                if sep in tg_channel:
                    tg_channel = tg_channel.split(sep)[0]
            tg_channel = tg_channel.strip()
            # 自动添加 @ 前缀
            if not tg_channel.startswith(('@', '-')):
                tg_channel = f"@{tg_channel}"

        try:
            url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
            
            # 使用 data 参数（form-urlencoded）而不是 json，更兼容
            data = {
                "chat_id": tg_channel,
                "text": message,
            }
            
            # 打印完整的调试信息
            print(f"\n{'='*60}")
            print(f"[DEBUG] TG API 请求:")
            print(f"URL: {url}")
            print(f"chat_id: {tg_channel}")
            print(f"text 长度: {len(message)} 字符")
            print(f"text 内容:\n{message}")
            print(f"{'='*60}\n")
            
            # 使用 data 参数发送 form-urlencoded 请求
            response = requests.post(url, data=data, timeout=10)
            print(f"[DEBUG] TG频道响应状态: {response.status_code}")
            print(f"[DEBUG] TG频道响应内容: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    print(f"[DEBUG] ✅ 发送成功!")
                    return True
                else:
                    print(f"[DEBUG] TG频道错误: {result.get('description', 'unknown')}")
                return result.get("ok", False)
            else:
                print(f"[提示] 请确保 Bot 已添加到频道并具有管理员权限")
        except Exception as e:
            print(f"[WARNING] 发送 TG 频道消息失败: {e}")
            import traceback
            traceback.print_exc()
        return False

    def _send_upload_complete_to_channel(
        self,
        sha256: str,
        size: int,
        name: str,
        cloud_type: str = "139",
        folder_path: str = ""
    ) -> bool:
        """
        发送上传完成的 JSON 消息到 TG 频道

        Args:
            sha256: 文件 SHA256 哈希值
            size: 文件大小（字节）
            name: 文件名
            cloud_type: 云盘类型标识
            folder_path: 文件夹路径（如 "TV Shows/Show Name/Season 01"）

        Returns:
            发送成功返回 True
        """
        # 构建完整文件路径
        full_path = f"{folder_path}/{name}" if folder_path else name
        
        # 构建 JSON 格式消息（纯文本，不用 Markdown）
        message = f'''{{
    "sha256": "{sha256}",
    "size": {size},
    "name": "{full_path}",
    "cloud": "{cloud_type}"
}}'''
        return self._send_tg_channel_message(message)

    def generate_strm_url(
        self,
        content_hash: str,
        file_size: int,
        file_name: str,
        part_infos: List[Dict[str, Any]]
    ) -> str:
        """
        生成 139 云盘 STRM 播放链接

        格式: http://192.168.2.148:5010/139getDownloadUrl/{sha256}/{size}/{encoded_filename}?part_info={base64_encoded_parts}

        Args:
            content_hash: 文件 SHA256 哈希值
            file_size: 文件大小（字节）
            file_name: 文件名
            part_infos: 分片信息列表

        Returns:
            STRM 播放链接
        """
        if not self.strm_server:
            return ""

        # URL 编码文件名
        encoded_filename = quote(file_name, safe='')

        # 构建 part_info JSON 并 Base64 编码
        import json
        part_info_json = json.dumps(part_infos)
        part_info_encoded = base64.b64encode(part_info_json.encode()).decode()

        # 构建完整 URL
        strm_url = (
            f"{self.strm_server}/139getDownloadUrl/"
            f"{content_hash}/{file_size}/{encoded_filename}"
            f"?part_info={part_info_encoded}"
        )

        return strm_url

    def generate_strm_file(
        self,
        strm_url: str,
        file_name: str,
        folder_structure: Optional[list] = None
    ) -> Optional[str]:
        """
        生成 STRM 文件

        Args:
            strm_url: STRM 播放链接
            file_name: 原始文件名
            folder_structure: 文件夹结构

        Returns:
            STRM 文件路径，失败返回 None
        """
        if not self.strm_output_dir or not strm_url:
            return None

        try:
            # 创建输出目录
            output_dir = Path(self.strm_output_dir)

            # 如果有文件夹结构，创建对应的目录
            if folder_structure:
                # 过滤掉空字符串和 "media"
                folder_parts = [p for p in folder_structure if p and p.lower() != "media"]
                for part in folder_parts:
                    safe_part = re.sub(r'[\\/:*?"<>|]', "", part)
                    output_dir = output_dir / safe_part

            # 确保目录存在
            output_dir.mkdir(parents=True, exist_ok=True)

            # 生成 STRM 文件名（替换原扩展名为 .strm）
            strm_filename = Path(file_name).stem + ".strm"
            strm_path = output_dir / strm_filename

            # 写入 STRM 文件
            with open(strm_path, 'w', encoding='utf-8') as f:
                f.write(strm_url)

            print(f"   ✅ STRM 文件已生成: {strm_path}")
            return str(strm_path)

        except Exception as e:
            print(f"   ❌ 生成 STRM 文件失败: {e}")
            return None

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
        上传视频到 139 云盘

        Args:
            file_path: 本地文件路径
            item_type: 媒体类型（用于创建子文件夹: movie/tv）
            item_id: 媒体ID
            file_storage: 存储类型
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

            print(f"\n=== 开始上传到 139 云盘 ===")
            print(f"本地文件: {file_path_obj.name}")
            print(f"目标文件名: {target_filename}")
            print(f"云盘类型: {self.cloud_type.value}")

            # 重置 TG 消息ID
            self._tg_message_ids[file_path] = None

            # 确定目标父文件夹ID
            target_parent_id = self.parent_id
            folder_path = None

            if folder_structure and isinstance(folder_structure, list):
                folder_path = "/".join(folder_structure)
                print(f"创建/查找目录结构: {' -> '.join(folder_structure)}")
                current_pid = self.parent_id

                for folder_name in folder_structure:
                    if not folder_name:
                        continue
                    # 清理文件夹名称
                    safe_folder_name = re.sub(r'[\\/:*?"<>|]', "", str(folder_name)).strip()
                    # 创建/获取文件夹
                    folder_id = self._get_or_create_folder(safe_folder_name, current_pid)
                    if folder_id:
                        current_pid = folder_id
                        target_parent_id = folder_id
                    else:
                        print(f"[ERROR] 无法创建目录: {safe_folder_name}，将上传到上一级")
                        break

            elif item_type and media_info:
                # 兼容旧逻辑
                # 第一层：media 文件夹
                media_folder_id = self._get_or_create_folder("media", self.parent_id)
                if not media_folder_id:
                    print("[WARNING] 创建/获取 media 文件夹失败，将使用根目录")
                    media_folder_id = self.parent_id

                # 第二层：媒体类型文件夹 (Movies / TV Shows)
                type_folder = "Movies" if item_type in ["movie", "vl"] else "TV Shows"
                type_folder_id = self._get_or_create_folder(type_folder, media_folder_id)

                if type_folder_id:
                    target_parent_id = type_folder_id

                    # 第三层：具体作品文件夹（使用标题）
                    title = media_info.get("title", "")
                    if title:
                        safe_title = re.sub(r'[\\/:*?"<>|]', "", title)
                        title_folder_id = self._get_or_create_folder(safe_title, type_folder_id)
                        if title_folder_id:
                            target_parent_id = title_folder_id

            print(f"最终目标文件夹ID: {target_parent_id}")

            # 上传文件（带进度回调）
            result = self._upload_with_progress(
                str(file_path_obj), target_parent_id, target_filename
            )

            if result:
                print(f"\n🎉 139云盘上传成功!")
                print(f"文件ID: {result.get('file_id')}")
                print(f"SHA256: {result.get('content_hash')}")

                # 生成 STRM 文件（如果配置了）
                if self.strm_server and self.strm_output_dir:
                    print(f"\n📝 生成 STRM 文件...")
                    strm_url = self.generate_strm_url(
                        content_hash=result.get('content_hash', ''),
                        file_size=result.get('size', 0),
                        file_name=target_filename,
                        part_infos=result.get('part_infos', [])
                    )
                    result['strm_url'] = strm_url
                    print(f"   STRM URL: {strm_url}")

                    strm_path = self.generate_strm_file(
                        strm_url=strm_url,
                        file_name=target_filename,
                        folder_structure=folder_structure
                    )
                    result['strm_path'] = strm_path

                # 上传完成后删除云端文件（不依赖 STRM 生成）
                # 注意：139云盘暂不支持直接删除云端文件
                if self.delete_after:
                    print(f"   ⚠️ delete_after 已启用，但139云盘暂不支持删除云端文件")

                # 上传同目录下的字幕文件
                print(f"\n📝 开始上传字幕文件...")
                subtitles = self.upload_subtitles(
                    str(file_path_obj), target_parent_id, target_filename, folder_structure
                )

                # 将字幕信息也返回
                result['subtitles'] = subtitles

                # 发送上传完成消息到 TG 频道
                if self.tg_channel_chat_id:
                    success = self._send_upload_complete_to_channel(
                        sha256=result.get('content_hash', ''),
                        size=result.get('size', 0),
                        name=target_filename,
                        cloud_type="139",
                        folder_path=folder_path
                    )
                    if success:
                        print(f"   📢 已发送上传完成消息到 TG 频道")
                    else:
                        print(f"   ⚠️ 发送 TG 频道消息失败")

                return result
            else:
                print(f"\n❌ 139云盘上传失败!")
                # 报告上传失败
                _report_upload_progress(
                    file_path=str(file_path_obj),
                    filename=target_filename,
                    uploader="yun139",
                    progress=0,
                    uploaded_bytes=0,
                    total_bytes=0,
                    speed="",
                    status="failed",
                    error="上传失败"
                )
                return None

        except Exception as e:
            print(f"\n❌ 139云盘上传异常: {e}")
            import traceback
            traceback.print_exc()
            # 报告上传异常
            _report_upload_progress(
                file_path=str(file_path_obj) if 'file_path_obj' in dir() else file_path,
                filename=target_filename if 'target_filename' in dir() else Path(file_path).name,
                uploader="yun139",
                progress=0,
                uploaded_bytes=0,
                total_bytes=0,
                speed="",
                status="failed",
                error=str(e)
            )
            return None

    def upload_subtitles(
        self,
        video_path: str,
        target_parent_id: str,
        video_filename: str,
        video_folder_structure: Optional[list] = None,
    ) -> List[Dict[str, Any]]:
        """
        上传视频同目录下的所有字幕文件

        Args:
            video_path: 视频文件路径
            target_parent_id: 目标文件夹ID（视频所在的文件夹）
            video_filename: 整理后的视频文件名
            video_folder_structure: 视频的文件夹结构

        Returns:
            成功上传的字幕文件信息列表
        """
        uploaded_subtitles = []

        try:
            video_dir = Path(video_path).parent
            video_stem = Path(video_filename).stem

            print(f"\n📝 扫描字幕文件: {video_dir}")

            # 扫描同目录下的所有字幕文件
            subtitle_files = [
                f for f in video_dir.iterdir()
                if f.is_file() and f.suffix.lower() in self.SUBTITLE_EXTENSIONS
            ]

            if not subtitle_files:
                print(f"   未找到字幕文件")
                return uploaded_subtitles

            print(f"   找到 {len(subtitle_files)} 个字幕文件")

            for subtitle_file in subtitle_files:
                try:
                    print(f"\n   处理字幕: {subtitle_file.name}")

                    # 解析字幕文件名，提取语言和类型信息
                    subtitle_info = self._parse_subtitle_info(subtitle_file.name)

                    # 生成新的字幕文件名
                    new_subtitle_name = self._generate_subtitle_name(
                        video_filename, subtitle_info
                    )

                    print(f"   重命名为: {new_subtitle_name}")

                    # 上传字幕文件
                    result = self._upload_with_progress(
                        str(subtitle_file), target_parent_id, new_subtitle_name
                    )

                    if result:
                        print(f"   ✅ 字幕上传成功")
                        uploaded_subtitles.append(result)
                    else:
                        print(f"   ❌ 字幕上传失败")

                except Exception as e:
                    print(f"   ❌ 处理字幕文件时出错: {e}")
                    import traceback
                    traceback.print_exc()

            print(f"\n📝 字幕上传完成: 成功 {len(uploaded_subtitles)}/{len(subtitle_files)} 个")

        except Exception as e:
            print(f"\n❌ 字幕上传过程异常: {e}")
            import traceback
            traceback.print_exc()

        return uploaded_subtitles

    def _parse_subtitle_info(self, filename: str) -> Dict[str, Optional[str]]:
        """解析字幕文件名，提取语言和类型信息"""
        language_map = {
            'en': 'English', 'eng': 'English', 'english': 'English',
            'zh': 'Chinese', 'chs': 'Chinese', 'zhs': 'Chinese', 'sc': 'Chinese',
            'cht': 'Chinese', 'tc': 'Chinese', 'zh-tw': 'Chinese',
            'ja': 'Japanese', 'jpn': 'Japanese', 'japanese': 'Japanese',
            'ko': 'Korean', 'kor': 'Korean', 'korean': 'Korean',
            'fr': 'French', 'fra': 'French', 'french': 'French',
            'de': 'German', 'deu': 'German', 'german': 'German',
            'es': 'Spanish', 'spa': 'Spanish', 'spanish': 'Spanish',
            'ru': 'Russian', 'rus': 'Russian', 'russian': 'Russian',
            'pt': 'Portuguese', 'por': 'Portuguese', 'portuguese': 'Portuguese',
            'it': 'Italian', 'ita': 'Italian', 'italian': 'Italian',
        }

        info = {'language': None, 'type': 'Normal'}
        filename_lower = filename.lower()

        # 检查字幕类型
        if re.search(r'\.sdh\.|\.hi\.|\.sdh$|\.hi$', filename_lower):
            info['type'] = 'SDH'
        if re.search(r'\.forced\.|\.forced$', filename_lower):
            info['type'] = 'Forced'
        if re.search(r'\.cc\.|\.cc$', filename_lower):
            info['type'] = 'CC'

        # 提取语言
        for code, lang in language_map.items():
            pattern = rf'\.{code}\.|^{code}\.\.{code}$'
            if re.search(pattern, filename_lower):
                info['language'] = lang
                break

        return info

    def _generate_subtitle_name(
        self,
        video_filename: str,
        subtitle_info: Dict[str, Optional[str]]
    ) -> str:
        """生成新的字幕文件名"""
        video_stem = Path(video_filename).stem
        subtitle_ext = '.srt'

        new_name = video_stem

        if subtitle_info.get('language'):
            lang = subtitle_info['language']
            new_name = f"{new_name}.{lang}"

            if subtitle_info.get('type') != 'Normal':
                subtitle_type = subtitle_info['type']
                new_name = f"{new_name}.{subtitle_type}{subtitle_ext}"
            else:
                new_name = f"{new_name}{subtitle_ext}"
        else:
            new_name = f"{new_name}{subtitle_ext}"

        return new_name

    def _upload_with_progress(
        self, file_path: str, parent_id: str, file_name: str
    ) -> Optional[Dict[str, Any]]:
        """带进度通知的上传，返回包含上传信息的字典"""

        file_size = os.path.getsize(file_path)
        total_mb = file_size / (1000 * 1000)

        # 报告上传开始
        _report_upload_progress(
            file_path=file_path,
            filename=file_name,
            uploader="yun139",
            progress=0,
            uploaded_bytes=0,
            total_bytes=file_size,
            speed="",
            status="uploading"
        )

        # 重置进度跟踪
        self._tg_message_ids[file_path] = None
        self.tg_last_update_time = 0

        last_uploaded = 0
        last_time = time.time()
        current_speed = 0
        final_progress_sent = False

        def progress_callback(uploaded: int, total: int):
            nonlocal last_uploaded, last_time, current_speed, final_progress_sent

            if total > 0:
                uploaded_mb = uploaded / (1000 * 1000)
                progress = (uploaded / total) * 100

                current_time = time.time()
                time_diff = current_time - last_time

                is_complete = progress >= 100

                if time_diff >= 0.5 or is_complete:
                    bytes_diff = uploaded - last_uploaded
                    speed_str = ""
                    if time_diff > 0:
                        new_speed = (bytes_diff / (1024 * 1024)) / time_diff
                        if current_speed > 0:
                            current_speed = current_speed * 0.7 + new_speed * 0.3
                        else:
                            current_speed = new_speed
                        speed_str = f"{current_speed:.2f} MB/s"

                    # 报告上传进度到 Web
                    _report_upload_progress(
                        file_path=file_path,
                        filename=file_name,
                        uploader="yun139",
                        progress=progress,
                        uploaded_bytes=uploaded,
                        total_bytes=total,
                        speed=speed_str,
                        status="completed" if is_complete else "uploading"
                    )

                    if is_complete and not final_progress_sent:
                        self._send_tg_progress(
                            file_path, file_name, 100, total_mb, total_mb,
                            current_speed, force=True,
                        )
                        final_progress_sent = True
                    elif not is_complete:
                        self._send_tg_progress(
                            file_path, file_name, progress, uploaded_mb, total_mb,
                            current_speed,
                        )

                    last_uploaded = uploaded
                    last_time = current_time
                elif self._tg_message_ids.get(file_path) is None:
                    self._send_tg_progress(
                        file_path, file_name, 0, 0, total_mb, 0
                    )

        # 调用 yun139 的上传方法并获取返回信息
        try:
            upload_info = self._upload_and_get_info(
                parent_id=parent_id,
                file_path=file_path,
                target_filename=file_name,  # 传递目标文件名
                progress_callback=progress_callback
            )

            if upload_info:
                return upload_info
            return None

        except Exception as e:
            print(f"[ERROR] 上传失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _upload_and_get_info(
        self,
        parent_id: str,
        file_path: str,
        target_filename: Optional[str] = None,
        progress_callback=None
    ) -> Optional[Dict[str, Any]]:
        """
        上传文件并获取上传信息（用于生成 STRM）

        Args:
            parent_id: 目标父文件夹ID
            file_path: 本地文件路径
            target_filename: 上传后的目标文件名（如果为None则使用原文件名）
            progress_callback: 进度回调函数

        Returns:
            包含 content_hash, size, name, part_infos, file_id 的字典
        """
        import json
        from tqdm import tqdm

        if self.cloud_type != CloudType.PERSONAL_NEW:
            raise NotImplementedError("目前仅支持新版个人云上传")

        # 外层重试：失败3次后清除状态重新上传
        max_full_retries = 3
        for full_retry in range(max_full_retries):
            if full_retry > 0:
                print(f"\n  [重试] 第 {full_retry + 1} 次重新上传，已清除断点记录")
                self._clear_upload_state(file_path)
            
            result = self._do_upload(
                parent_id, file_path, target_filename, progress_callback
            )
            
            if result is not None:
                return result
            
            print(f"\n  [ERROR] 上传失败，准备重试...")
        
        print(f"\n  [ERROR] 上传失败，已重试 {max_full_retries} 次")
        return None

    def _do_upload(
        self,
        parent_id: str,
        file_path: str,
        target_filename: Optional[str] = None,
        progress_callback=None
    ) -> Optional[Dict[str, Any]]:
        """
        执行实际的上传操作（单次尝试）

        Args:
            parent_id: 目标父文件夹ID
            file_path: 本地文件路径
            target_filename: 上传后的目标文件名
            progress_callback: 进度回调函数

        Returns:
            上传结果字典，失败返回 None
        """
        import json
        from tqdm import tqdm

        # 使用目标文件名或原文件名
        file_name = target_filename if target_filename else os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        # 计算 SHA256（带进度条）
        print(f"\n🔢 计算 SHA256 哈希值...")
        sha256_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            with tqdm(total=file_size, unit='B', unit_scale=True, desc="SHA256", ncols=80) as pbar:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):  # 1MB chunks
                    sha256_hash.update(chunk)
                    pbar.update(len(chunk))
        content_hash = sha256_hash.hexdigest()
        print(f"   SHA256: {content_hash[:32]}...")

        # 计算分片信息
        part_size = self.client._get_part_size(file_size)
        part_count = max(1, (file_size + part_size - 1) // part_size)
        
        print(f"  [DEBUG] 分片计算: file_size={file_size}, part_size={part_size}, part_count={part_count}")

        part_infos = []
        for i in range(part_count):
            start = i * part_size
            byte_size = min(part_size, file_size - start)
            part_infos.append({
                "partNumber": i + 1,
                "partSize": byte_size,
                "parallelHashCtx": {"partOffset": start}
            })

        # 检查断点续传状态
        saved_state = self._load_upload_state(file_path, content_hash)
        file_id = None
        upload_id = None
        uploaded_part_numbers = []
        
        if saved_state:
            # 断点续传：复用已有的 fileId 和 uploadId
            file_id = saved_state.get("fileId")
            upload_id = saved_state.get("uploadId")
            uploaded_part_numbers = saved_state.get("uploadedParts", [])
            print(f"  [断点续传] 恢复上传: fileId={file_id}, 已完成 {len(uploaded_part_numbers)}/{part_count} 分片")
        else:
            # 创建新的上传任务
            data = {
                "contentHash": content_hash,
                "contentHashAlgorithm": "SHA256",
                "contentType": "application/octet-stream",
                "parallelUpload": False,
                "partInfos": part_infos[:1],  # 秒传时只需一个分片
                "size": file_size,
                "parentFileId": parent_id if parent_id else "",
                "name": file_name,
                "type": "file",
                "fileRenameMode": "auto_rename"
            }

            result = self.client._request("/hcy/file/create", data, is_personal=True)
            upload_data = result.get('data', {})

            # 打印上传任务信息
            print(f"\n{'='*50}")
            print(f"文件名: {file_name}")
            print(f"文件大小: {file_size} bytes")
            print(f"SHA256: {content_hash}")
            print(f"exist: {upload_data.get('exist', False)}")
            print(f"rapidUpload: {upload_data.get('rapidUpload', False)}")
            print(f"fileId: {upload_data.get('fileId', '')}")
            print(f"fileName: {upload_data.get('fileName', '')}")
            print(f"parts_encoded: {base64.b64encode(json.dumps(part_infos[:1]).encode()).decode()}")
            print(f"{'='*50}")

            # 文件已存在相同内容
            if upload_data.get('exist', False):
                print(f"✓ 文件已存在相同内容，跳过上传")
                self._clear_upload_state(file_path)
                return {
                    "file_id": upload_data.get('fileId', ''),
                    "name": upload_data.get('fileName', file_name),
                    "size": file_size,
                    "content_hash": content_hash,
                    "part_infos": part_infos[:1],
                    "url": "",
                    "existed": True,
                }

            # 支持秒传
            if upload_data.get('rapidUpload', False):
                print(f"✓ 秒传成功")
                self._clear_upload_state(file_path)
                return {
                    "file_id": upload_data.get('fileId', ''),
                    "name": upload_data.get('fileName', file_name),
                    "size": file_size,
                    "content_hash": content_hash,
                    "part_infos": part_infos[:1],
                    "url": "",
                    "rapid_upload": True,
                }

            file_id = upload_data['fileId']
            upload_id = upload_data['uploadId']
            
            # 保存初始状态
            self._save_upload_state(file_path, file_id, upload_id, content_hash, [])

        # 获取未上传分片的上传地址
        upload_part_infos = []
        
        # 过滤出未上传的分片
        pending_part_infos = [p for p in part_infos if p['partNumber'] not in uploaded_part_numbers]
        
        if not pending_part_infos:
            print(f"  [断点续传] 所有分片已上传，直接完成上传")
        else:
            print(f"  [断点续传] 需要上传 {len(pending_part_infos)}/{part_count} 个分片")
            
            # 获取未上传分片的上传地址（每批获取 100 个）
            for i in range(0, len(pending_part_infos), 100):
                batch = pending_part_infos[i:i+100]
                more_data = {
                    "fileId": file_id,
                    "uploadId": upload_id,
                    "partInfos": batch,
                    "commonAccountInfo": {
                        "account": self.client.account,
                        "accountType": 1
                    }
                }
                print(f"  [DEBUG] 获取分片上传地址: 第 {batch[0]['partNumber']}-{batch[-1]['partNumber']} 个")
                more_result = self.client._request(
                    "/hcy/file/getUploadUrl",
                    more_data,
                    is_personal=True
                )
                upload_part_infos.extend(more_result['data']['partInfos'])
            
            upload_part_infos = sorted(upload_part_infos, key=lambda x: x['partNumber'])

        # 上传分片（带进度条和重试机制）
        # 注意：139云盘要求分片按顺序上传，不支持并行
        print(f"\n📤 开始上传分片，共 {len(upload_part_infos)} 个分片")
        
        uploaded_parts = []  # 记录已上传的分片信息（用于complete）
        max_retries = 3  # 每个分片最大重试次数
        
        # 计算已上传字节数（用于进度条初始位置）
        initial_uploaded = 0
        for part_num in uploaded_part_numbers:
            part_idx = part_num - 1
            if 0 <= part_idx < len(part_infos):
                initial_uploaded += part_infos[part_idx]['partSize']
        
        with open(file_path, 'rb') as f:
            with tqdm(total=file_size, unit='B', unit_scale=True, desc="上传进度", ncols=80, initial=initial_uploaded) as pbar:
                for part_info in upload_part_infos:
                    part_num = part_info['partNumber'] - 1
                    upload_url = part_info['uploadUrl']
                    
                    # 跳过已上传的分片
                    if part_info['partNumber'] in uploaded_part_numbers:
                        continue
                    
                    f.seek(part_num * part_size)
                    chunk_data = f.read(part_size)
                    
                    # 上传分片（带重试）
                    headers = {
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(len(chunk_data)),
                        "Origin": "https://yun.139.com",
                        "Referer": "https://yun.139.com/"
                    }
                    
                    upload_success = False
                    last_error = None
                    
                    for retry in range(max_retries):
                        try:
                            response = requests.put(upload_url, data=chunk_data, headers=headers, timeout=300)
                            response.raise_for_status()
                            uploaded_parts.append({
                                "partNumber": part_info['partNumber'],
                                "partSize": len(chunk_data),
                                "etag": response.headers.get('ETag', '')
                            })
                            upload_success = True
                            break
                        except Exception as e:
                            last_error = e
                            if retry < max_retries - 1:
                                wait_time = 2 ** retry  # 指数退避
                                print(f"\n  [WARNING] 分片 {part_info['partNumber']} 上传失败 (尝试 {retry + 1}/{max_retries}): {e}")
                                print(f"  [RETRY] {wait_time}秒后重试...")
                                time.sleep(wait_time)
                                # 重新获取上传URL（使用原始 part_infos 中的完整信息）
                                try:
                                    # 从原始 part_infos 获取该分片的完整信息
                                    original_part_info = part_infos[part_num]
                                    refresh_data = {
                                        "fileId": file_id,
                                        "uploadId": upload_id,
                                        "partInfos": [original_part_info],  # 使用包含 parallelHashCtx 的完整信息
                                        "commonAccountInfo": {
                                            "account": self.client.account,
                                            "accountType": 1
                                        }
                                    }
                                    refresh_result = self.client._request(
                                        "/hcy/file/getUploadUrl",
                                        refresh_data,
                                        is_personal=True
                                    )
                                    new_part_infos = refresh_result.get('data', {}).get('partInfos', [])
                                    if new_part_infos:
                                        upload_url = new_part_infos[0]['uploadUrl']
                                        print(f"  [RETRY] 已重新获取上传URL")
                                except Exception as refresh_error:
                                    print(f"  [WARNING] 重新获取上传URL失败: {refresh_error}")
                    
                    if not upload_success:
                        print(f"\n  [ERROR] 分片 {part_info['partNumber']} 上传失败，已重试{max_retries}次: {last_error}")
                        return None  # 返回 None，让外层重试
                    
                    # 更新已上传分片列表并保存进度
                    uploaded_part_numbers.append(part_info['partNumber'])
                    self._save_upload_state(file_path, file_id, upload_id, content_hash, uploaded_part_numbers)
                    
                    pbar.update(len(chunk_data))
                    if progress_callback:
                        progress_callback(pbar.n, file_size)
        
        # 完成上传
        print(f"\n  [DEBUG] 所有分片上传完成，调用 complete 接口")
        
        complete_data = {
            "contentHash": content_hash,
            "contentHashAlgorithm": "SHA256",
            "fileId": file_id,
            "uploadId": upload_id,
        }
        
        self.client._request("/hcy/file/complete", complete_data, is_personal=True)

        # 上传完成，清除断点续传状态文件
        self._clear_upload_state(file_path)

        print(f"上传完成: {file_name}")

        return {
            "file_id": file_id,
            "name": file_name,
            "size": file_size,
            "content_hash": content_hash,
            "part_infos": part_infos[:1],
            "url": "",
        }