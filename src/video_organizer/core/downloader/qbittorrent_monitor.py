"""qBittorrent 下载监控器"""

import os
import json
import time
import logging
import threading
import requests
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from collections import defaultdict

from .base import DownloaderMonitor, decode_file_path

logger = logging.getLogger(__name__)


class QBittorrentMonitor(DownloaderMonitor):
    """
    Monitor for qBittorrent downloader.
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        rpc_url: str = "http://localhost:8080/api/v2",
        username: str = "admin",
        password: str = "adminadmin",
        supported_extensions: tuple = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"),
        path_mappings: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the qBittorrent monitor.

        Args:
            callback: Callback function to call when a download is completed.
            rpc_url: RPC URL of the qBittorrent instance.
            username: Username for qBittorrent web UI.
            password: Password for qBittorrent web UI.
            supported_extensions: Tuple of supported file extensions.
            path_mappings: 路径映射字典，将下载器返回的路径映射到主机实际路径
        """
        super().__init__(callback)
        self.rpc_url = rpc_url
        self.username = username
        self.password = password
        self.supported_extensions = supported_extensions
        self.path_mappings = path_mappings or {}
        self.session = requests.Session()  # 使用 Session 管理 Cookie
        self._processed_torrents = set()  # 存储已处理的种子哈希，避免重复处理
        self._processed_files = set()  # 存储已处理的文件路径，避免重复回调同一文件
        self._upload_completed_files = set()  # 存储真正上传完成的文件路径，用于判定是否可删种子
    
    def _apply_path_mapping(self, file_path: str) -> str:
        """
        应用路径映射，将 qBittorrent 返回的路径转换为本地实际路径
        
        Args:
            file_path: qBittorrent 返回的原始路径
            
        Returns:
            str: 映射后的本地路径
        """
        if not self.path_mappings:
            return file_path
        
        # 标准化路径进行比较
        normalized_path = file_path.replace("\\", "/")
        
        # 查找最长的匹配前缀
        longest_match = ""
        for prefix in self.path_mappings.keys():
            norm_prefix = prefix.replace("\\", "/")
            if normalized_path.startswith(norm_prefix):
                if len(norm_prefix) > len(longest_match):
                    longest_match = norm_prefix
        
        if longest_match:
            # 找到原始前缀（保留原始大小写）
            original_prefix = longest_match
            for prefix in self.path_mappings.keys():
                if prefix.replace("\\", "/") == longest_match:
                    original_prefix = prefix
                    break
            
            mapped_path = normalized_path.replace(
                longest_match, 
                self.path_mappings[original_prefix].replace("\\", "/"), 
                1
            )
            # 标准化路径分隔符
            return os.path.normpath(mapped_path)
        
        return file_path

    def start(self):
        """
        Start monitoring qBittorrent for completed downloads.
        """
        # 尝试登录
        if not self._login():
            logger.error("Failed to login to qBittorrent, cannot start monitor")
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info(f"Started qBittorrent monitor with RPC URL: {self.rpc_url}")

    def stop(self):
        """
        Stop monitoring qBittorrent.
        """
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        logger.info("Stopped qBittorrent monitor")

    def is_connected(self) -> bool:
        """
        Check if connected to qBittorrent Web UI.

        Returns:
            bool: True if connected, False otherwise.
        """
        try:
            # 尝试获取应用版本信息
            url = f"{self.rpc_url}/app/version"
            response = self.session.get(url, timeout=30)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to connect to qBittorrent: {e}")
            return False

    def remove_download(self, file_path: str) -> bool:
        """
        从 qBittorrent 中删除指定文件的种子任务 (只有当所有视频都处理完后才真正执行)

        Args:
            file_path: 文件路径 (可能是主机映射后的路径)

        Returns:
            bool: 触发了检查动作返回 True，如果真正执行了删除也返回 True
        """
        try:
            # 获取所有已完成的种子
            completed_torrents = self._get_completed_torrents()

            # 标准化输入路径
            norm_input_path = os.path.normpath(file_path).lower()

            # 查找包含该文件的种子
            target_torrent = None
            for torrent in completed_torrents:
                save_path = torrent.get("save_path", "")
                files = self._get_torrent_files(torrent["hash"])

                for f in files:
                    # 组合完整路径进行比对
                    f_name = f["name"]
                    full_torrent_file_path = os.path.normpath(
                        os.path.join(save_path, f_name)
                    ).lower()

                    # 匹配逻辑：绝对路径一致，或者输入路径是以种子内文件路径结尾的（处理映射点差异）
                    if (
                        full_torrent_file_path == norm_input_path
                        or norm_input_path.endswith(os.path.normpath(f_name).lower())
                    ):
                        target_torrent = torrent
                        break
                if target_torrent:
                    break

            if not target_torrent:
                logger.debug(f"在 qBittorrent 中未找到对应文件的任务: {file_path}")
                return False

            torrent_hash = target_torrent["hash"]

            # 标记当前文件已上传完成（使用标准化路径）
            norm_input_path = os.path.normpath(file_path).lower()
            self._upload_completed_files.add(norm_input_path)

            # 检查种子内是否还有其他待处理的视频文件
            all_files = self._get_torrent_files(torrent_hash)
            remaining_videos = []

            for f in all_files:
                f_name = f["name"]
                # 检查是否是视频文件
                if f_name.lower().endswith(self.supported_extensions):
                    f_full_path = str(
                        Path(os.path.join(target_torrent.get("save_path", ""), f_name))
                    )

                    # 检查文件是否实际存在（区分"未下载"和"未处理"）
                    if not os.path.exists(f_full_path):
                        # 文件未下载，跳过检查
                        continue

                    # 检查该文件是否已上传完成
                    norm_f_full = os.path.normpath(f_full_path).lower()
                    if norm_f_full not in self._upload_completed_files:
                        remaining_videos.append(f_name)

            if remaining_videos:
                logger.info(
                    f"种子 {torrent_hash} 仍有 {len(remaining_videos)} 个视频未处理完毕，将种子暂时保留在下载器中。剩余: {remaining_videos[:2]}..."
                )
                return False  # 返回 False，外层处理器将不会打印"已从下载器中删除"

            # 所有视频都已处理，执行删除
            delete_url = f"{self.rpc_url}/torrents/delete"
            data = {"hashes": torrent_hash, "deleteFiles": "true"}

            response = self.session.post(delete_url, data=data, timeout=30)
            if response.status_code == 200:
                logger.info(
                    f"🎉 种子内所有视频已处理完毕，已删除 qBittorrent 任务: {target_torrent.get('name')} ({torrent_hash})"
                )
                return True
            else:
                logger.warning(
                    f"从 qBittorrent 删除任务失败: {torrent_hash}, 状态码: {response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"从 qBittorrent 清理任务时发生错误: {e}")
            return False

    def force_remove_download(self, file_path: str) -> bool:
        """
        强制从 qBittorrent 中删除种子任务及其文件 (用于文件删除失败时的清理)

        Args:
            file_path: 文件路径 (可能是主机映射后的路径)

        Returns:
            bool: 是否成功删除
        """
        try:
            # 获取所有种子 (包括未完成的)
            url = f"{self.rpc_url}/torrents/info"
            response = self.session.get(url, timeout=30)

            if response.status_code != 200:
                logger.error(f"获取种子列表失败: {response.status_code}")
                return False

            all_torrents = response.json()

            # 标准化输入路径
            norm_input_path = os.path.normpath(file_path).lower()

            # 查找包含该文件的种子
            target_torrent = None
            for torrent in all_torrents:
                save_path = torrent.get("save_path", "")
                files = self._get_torrent_files(torrent["hash"])

                for f in files:
                    f_name = f["name"]
                    full_torrent_file_path = os.path.normpath(
                        os.path.join(save_path, f_name)
                    ).lower()

                    if (
                        full_torrent_file_path == norm_input_path
                        or norm_input_path.endswith(os.path.normpath(f_name).lower())
                    ):
                        target_torrent = torrent
                        break
                if target_torrent:
                    break

            if not target_torrent:
                logger.debug(f"在 qBittorrent 中未找到对应文件的任务: {file_path}")
                return False

            torrent_hash = target_torrent["hash"]
            torrent_name = target_torrent.get("name", "")

            # 检查种子内是否还有其他待处理的视频文件
            all_files = self._get_torrent_files(torrent_hash)
            remaining_videos = []

            for f in all_files:
                f_name = f["name"]
                if f_name.lower().endswith(self.supported_extensions):
                    f_full_path = str(
                        Path(os.path.join(target_torrent.get("save_path", ""), f_name))
                    )

                    # 检查文件是否实际存在（区分"未下载"和"未处理"）
                    if not os.path.exists(f_full_path):
                        # 文件未下载，跳过检查
                        continue

                    if f_full_path not in self._processed_files:
                        norm_f_full = os.path.normpath(f_full_path).lower()
                        is_processed = False
                        for p_file in self._processed_files:
                            if os.path.normpath(p_file).lower() == norm_f_full:
                                is_processed = True
                                break
                        if not is_processed:
                            remaining_videos.append(f_name)

            # 如果还有其他视频待处理，不能强制删除整个种子
            if remaining_videos:
                logger.info(
                    f"种子 {torrent_name} 仍有 {len(remaining_videos)} 个视频待处理，不执行强制删除。剩余: {remaining_videos[:3]}..."
                )
                return False

            # 所有视频都已处理，执行删除 (包含文件)
            delete_url = f"{self.rpc_url}/torrents/delete"
            data = {"hashes": torrent_hash, "deleteFiles": "true"}
            response = self.session.post(delete_url, data=data, timeout=30)

            if response.status_code == 200:
                logger.info(
                    f"已强制删除 qBittorrent 任务及文件: {torrent_name} ({torrent_hash})"
                )
                return True
            else:
                logger.warning(
                    f"强制删除 qBittorrent 任务失败: {torrent_hash}, 状态码: {response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"强制从 qBittorrent 删除任务时发生错误: {e}")
            return False

    def pause_torrent_for_file(self, file_path: str) -> bool:
        """
        暂停包含该文件的种子，以释放文件句柄 (用于处理文件被占用的问题)

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否成功暂停了种子
        """
        try:
            # 获取所有种子
            url = f"{self.rpc_url}/torrents/info"
            response = self.session.get(url, timeout=30)

            if response.status_code != 200:
                return False

            all_torrents = response.json()
            norm_input_path = os.path.normpath(file_path).lower()

            # 查找种子
            for torrent in all_torrents:
                # 只暂停正在做种的种子
                if torrent.get("state") not in ["uploading", "stalledUP", "forcedUP"]:
                    continue

                save_path = torrent.get("save_path", "")
                try:
                    files = self._get_torrent_files(torrent["hash"])
                except Exception:
                    continue

                for f in files:
                    f_name = f["name"]
                    full_path = os.path.normpath(
                        os.path.join(save_path, f_name)
                    ).lower()

                    if full_path == norm_input_path or norm_input_path.endswith(
                        os.path.normpath(f_name).lower()
                    ):
                        # 找到目标种子，暂停它
                        torrent_hash = torrent["hash"]
                        pause_url = f"{self.rpc_url}/torrents/pause"
                        data = {"hashes": torrent_hash}
                        pause_response = self.session.post(
                            pause_url, data=data, timeout=30
                        )

                        if pause_response.status_code == 200:
                            logger.info(
                                f"已暂停种子以释放文件句柄: {torrent.get('name')} ({torrent_hash})"
                            )
                            return True
                        break

            return False
        except Exception as e:
            logger.error(f"暂停种子时发生错误: {e}")
            return False

    def _monitor_loop(self):
        """
        Main monitoring loop for qBittorrent.
        """
        while self.running:
            try:
                logger.debug("qBittorrent monitor loop iteration started")
                
                # 检查会话是否有效，如果无效则重新登录
                if not self.is_connected():
                    logger.info("qBittorrent session invalid, attempting to re-login")
                    if not self._login():
                        logger.warning("qBittorrent re-login failed, will retry in 10s")
                        time.sleep(10)
                        continue
                    logger.info("qBittorrent re-login successful")

                # 获取所有已完成的种子
                all_completed_torrents = self._get_completed_torrents()
                logger.debug(f"qBittorrent: Got {len(all_completed_torrents)} total torrents")

                for torrent in all_completed_torrents:
                    torrent_hash = torrent["hash"]
                    torrent_name = torrent.get("name", "unknown")
                    torrent_progress = torrent.get("progress", 0)

                    # 1. 核心改进：跳过已处理完毕的种子，极大提升大种子库处理性能
                    if torrent_hash in self._processed_torrents:
                        logger.debug(f"Skip already processed torrent: {torrent_name}")
                        continue

                    # 2. 核心改进：通过进度判断是否完成，比 filter 更稳健
                    if torrent_progress < 1:
                        logger.debug(f"Skip incomplete torrent: {torrent_name} (progress: {torrent_progress:.2%})")
                        continue

                    logger.info(f"Processing completed torrent: {torrent_name} ({torrent_hash})")

                    # 检查种子的保存路径
                    save_path = torrent.get("save_path", "")
                    if not save_path:
                        logger.error(
                            f"Failed to get save path for torrent: {torrent_hash}"
                        )
                        continue

                    # 获取种子中的文件
                    files = self._get_torrent_files(torrent_hash)
                    logger.debug(f"Torrent {torrent_name} has {len(files)} files")

                    # 记录种子是否完全处理完毕
                    torrent_fully_processed = True

                    for file in files:
                        file_name = file["name"]
                        if file_name.lower().endswith(self.supported_extensions):
                            # 构建完整的文件路径
                            raw_file_path = str(Path(os.path.join(save_path, file_name)))
                            
                            # 解码 URL 编码的文件名
                            decoded_path = decode_file_path(raw_file_path)
                            
                            # 应用路径映射
                            file_path = self._apply_path_mapping(decoded_path)

                            # 3. 核心改进：使用标准化路径进行“已处理”检测
                            file_path_norm = os.path.normpath(file_path).lower()
                            if any(
                                os.path.normpath(f).lower() == file_path_norm
                                for f in self._processed_files
                            ):
                                continue

                            # Path decoding and mapping already done above
                            logger.info(
                                f"qBittorrent: Detected completed video file: {file_path}"
                            )
                            # 调用回调处理文件
                            try:
                                # 回调返回 True 表示成功处理，False 表示跳过（需要重试）
                                result = self.callback(file_path, downloader_monitor=self)
                                if result is not False:  # None 或 True 都视为成功
                                    self._processed_files.add(file_path)
                                    logger.debug(
                                        f"qBittorrent: Marked file as processed: {file_path}"
                                    )
                                else:
                                    logger.info(
                                        f"qBittorrent: File not processed (will retry): {file_path}"
                                    )
                                    torrent_fully_processed = False
                            except Exception as e:
                                logger.error(
                                    f"qBittorrent: Failed to process file {file_path}: {e}"
                                )
                                torrent_fully_processed = False
                        else:
                            # 非视频文件不计入处理依赖，但有些种子可能只有非视频文件
                            pass

                    # 如果种子中所有视频文件都已处理，且该种子之前未被标记，则标记种子为已处理
                    if (
                        torrent_fully_processed
                        and torrent_hash not in self._processed_torrents
                    ):
                        self._processed_torrents.add(torrent_hash)
                        logger.info(
                            f"Marked torrent as fully processed: {torrent_hash}"
                        )

                # 等待一段时间后再次检查
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error in qBittorrent monitor loop: {e}")
                time.sleep(10)  # 发生错误时，延长等待时间

    def _login(self) -> bool:
        """
        Login to qBittorrent Web UI.

        Returns:
            bool: True if login successful, False otherwise.
        """
        try:
            url = f"{self.rpc_url}/auth/login"
            data = {"username": self.username, "password": self.password}

            # 使用 session 登录，Cookie 会自动管理
            response = self.session.post(url, data=data, timeout=30)
            if response.status_code == 200 and response.text == "Ok.":
                # Session 会自动保存 Cookie
                logger.info(f"Login successful, cookies: {dict(self.session.cookies)}")
                return True
            logger.error(
                f"Login failed with status {response.status_code}: {response.text}"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to login to qBittorrent: {e}")
            return False

    def _get_completed_torrents(self):
        """
        Get completed torrents from qBittorrent.

        Returns:
            list: List of completed torrents.
        """
        url = f"{self.rpc_url}/torrents/info"
        params = {"filter": "all"}  # 改用 all，手动过滤进度，避免状态误判

        max_retries = 3
        for i in range(max_retries):
            try:
                logger.debug(f"Requesting qBittorrent torrents/info (attempt {i+1}/{max_retries})")
                response = self.session.get(url, params=params, timeout=30)
                logger.debug(f"qBittorrent response status: {response.status_code}")
                if response.status_code != 200:
                    logger.warning(f"qBittorrent returned non-200 status: {response.status_code}, body: {response.text[:200]}")
                response.raise_for_status()
                result = response.json()
                logger.debug(f"qBittorrent returned {len(result)} torrents")
                return result
            except Exception as e:
                logger.warning(
                    f"获取 qBittorrent 种子列表失败 ({i+1}/{max_retries}): {e}"
                )
                if i < max_retries - 1:
                    time.sleep(2)
                else:
                    raise

    def _get_torrent_files(self, torrent_hash: str):
        """
        Get files in a torrent.

        Args:
            torrent_hash: Hash of the torrent.

        Returns:
            list: List of files in the torrent.
        """
        url = f"{self.rpc_url}/torrents/files"
        params = {"hash": torrent_hash}

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get files for torrent {torrent_hash}: {e}")
            raise


