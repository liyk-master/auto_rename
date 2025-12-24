"""
Downloader monitor module for monitoring download completion events from aria2 and qBittorrent.
"""

import logging
import threading
import os
import time
import requests
import urllib.parse
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class DownloaderMonitor(ABC):
    """
    Abstract base class for downloader monitors.
    """
    
    def __init__(self, callback: Callable[[str], None]):
        """
        Initialize the downloader monitor.
        
        Args:
            callback: Callback function to call when a download is completed.
                      The callback should accept the file path as an argument.
        """
        self.callback = callback
        self.running = False
        self.monitor_thread = None
    
    @abstractmethod
    def start(self):
        """
        Start monitoring the downloader for completed downloads.
        """
        pass
    
    @abstractmethod
    def stop(self):
        """
        Stop monitoring the downloader.
        """
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if the monitor is connected to the downloader.
        
        Returns:
            bool: True if connected, False otherwise.
        """
        pass


class Aria2Monitor(DownloaderMonitor):
    """
    Monitor for aria2 downloader.
    """
    
    def __init__(self, callback: Callable[[str], None], rpc_url: str = "http://localhost:6800/jsonrpc", secret: Optional[str] = None, supported_extensions: tuple = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm")):
        """
        Initialize the aria2 monitor.
        
        Args:
            callback: Callback function to call when a download is completed.
            rpc_url: RPC URL of the aria2 instance.
            secret: Secret token for accessing the aria2 RPC interface.
            supported_extensions: Tuple of supported file extensions.
        """
        super().__init__(callback)
        self.rpc_url = rpc_url
        self.secret = secret
        self.supported_extensions = supported_extensions
        self._processed_downloads = set()  # 存储已处理的下载ID，避免重复处理
        self._processed_files = set()  # 存储已处理的文件路径，避免重复回调同一文件
    
    def start(self):
        """
        Start monitoring aria2 for completed downloads.
        """
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info(f"Started aria2 monitor with RPC URL: {self.rpc_url}")
    
    def stop(self):
        """
        Stop monitoring aria2.
        """
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        logger.info("Stopped aria2 monitor")
    
    def is_connected(self) -> bool:
        """
        Check if connected to aria2 RPC interface.
        
        Returns:
            bool: True if connected, False otherwise.
        """
        try:
            headers = {
                "Content-Type": "application/json"
            }
            payload = {
                "jsonrpc": "2.0",
                "method": "aria2.getVersion",
                "id": "1",
                "params": [f"token:{self.secret}"] if self.secret else []
            }
            response = requests.post(self.rpc_url, headers=headers, json=payload, timeout=30)
            return response.status_code == 200 and "result" in response.json()
        except Exception as e:
            logger.error(f"Failed to connect to aria2: {e}")
            return False
    

    def remove_download(self, file_path: str) -> bool:
        """
        从 aria2 中删除指定文件的下载任务
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 删除成功返回 True，否则返回 False
        """
        try:
            # 获取所有已完成的下载
            completed_downloads = self._get_completed_downloads()
            
            # 查找包含该文件的下载任务
            for download in completed_downloads:
                files = download.get("files", [])
                for file_info in files:
                    # 获取 aria2 内部记录的文件路径（通常是绝对路径）
                    aria2_path = file_info.get("path")
                    if not aria2_path:
                        continue
                        
                    # 标准化路径比较
                    norm_aria2_path = os.path.normpath(aria2_path).lower()
                    norm_file_path = os.path.normpath(file_path).lower()
                    
                    # 匹配逻辑：
                    # 1. 完整路径精确匹配
                    # 2. 后缀匹配：如果传入的 file_path 以 aria2 记录的文件名结尾
                    #    注意：这里取 aria2_path 的 basename 来匹配，解决路径映射不一致的问题
                    
                    aria2_filename = os.path.basename(norm_aria2_path)
                    
                    if norm_aria2_path == norm_file_path or norm_file_path.endswith(aria2_filename):
                        gid = download.get("gid")
                        
                        # 调用 aria2.removeDownloadResult 删除下载记录
                        headers = {"Content-Type": "application/json"}
                        payload = {
                            "jsonrpc": "2.0",
                            "method": "aria2.removeDownloadResult",
                            "id": "remove",
                            "params": [f"token:{self.secret}", gid] if self.secret else [gid]
                        }
                        
                        response = requests.post(self.rpc_url, headers=headers, json=payload, timeout=30)
                        if response.status_code == 200:
                            result = response.json()
                            if "result" in result and result["result"] == "OK":
                                logger.info(f"已从 aria2 删除下载任务: {gid} ({file_path})")
                                return True
                        
                        logger.warning(f"从 aria2 删除下载任务失败: {gid}")
                        return False
            
            logger.debug(f"在 aria2 中未找到文件的下载任务: {file_path}")
            return False
            
        except Exception as e:
            logger.error(f"从 aria2 删除下载任务时出错: {e}")
            return False

    def _monitor_loop(self):
        """
        Main monitoring loop for aria2.
        """
        while self.running:
            try:
                logger.debug("Aria2 monitoring loop iteration")
                # 获取已完成的下载
                completed_downloads = self._get_completed_downloads()
                logger.debug(f"Aria2: Got {len(completed_downloads)} completed downloads")
                
                for download in completed_downloads:
                    # logger.debug(f"Aria2: Processing download: {download}")
                    download_gid = download.get("gid")
                    logger.debug(f"Aria2: Download GID: {download_gid}")
                    
                    if not download_gid:
                        logger.debug("Aria2: Skipping download without GID")
                        continue
                        
                    if download_gid in self._processed_downloads:
                        logger.debug(f"Aria2: Download {download_gid} already processed, skipping")
                        continue
                    
                    # 获取文件路径
                    files = download.get("files", [])
                    logger.debug(f"Aria2: Download has {len(files)} files")
                    
                    for file_info in files:
                        file_path = file_info.get("path")
                        logger.debug(f"Aria2: File path in download: {file_path}")
                        
                        if file_path:
                            # 检查文件是否已经处理过
                            if file_path in self._processed_files:
                                logger.debug(f"Aria2: File {file_path} already processed, skipping")
                                continue
                            
                            logger.debug(f"Aria2: Checking file extension for: {file_path}")
                            if file_path.endswith(self.supported_extensions):
                                # 解码URL编码的文件名
                                file_path = urllib.parse.unquote(file_path)
                                logger.info(f"Detected completed video file from aria2: {file_path}")
                                logger.debug(f"Aria2: Calling callback for file: {file_path}")
                                self.callback(file_path, downloader_monitor=self)
                                # 标记文件为已处理
                                self._processed_files.add(file_path)
                                logger.debug(f"Aria2: Marked file as processed: {file_path}")
                            else:
                                logger.debug(f"Aria2: File {file_path} has unsupported extension, skipping")
                    
                    # 标记为已处理
                    self._processed_downloads.add(download_gid)
                    logger.info(f"Marked aria2 download as processed: {download_gid}")
                
                # 等待一段时间后再次检查
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error in aria2 monitor loop: {e}")
                time.sleep(10)  # 发生错误时，延长等待时间
    
    def _get_completed_downloads(self):
        """
        Get completed downloads from aria2.
        
        Returns:
            list: List of completed downloads.
        """
        headers = {
            "Content-Type": "application/json"
        }
        
        # 构建请求参数
        params = [f"token:{self.secret}"] if self.secret else []
        
        # 使用aria2.tellStopped获取已完成的下载（offset=0, limit=100表示获取最近100个已停止的下载）
        payload = {
            "jsonrpc": "2.0",
            "method": "aria2.tellStopped",
            "id": "1",
            "params": params + [0, 2000, ["gid", "status", "files"]]
        }
        
        response = requests.post(self.rpc_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        if "result" in result:
            # 过滤出已完成的下载
            return [d for d in result["result"] if d.get("status") == "complete"]
        return []


class QBittorrentMonitor(DownloaderMonitor):
    """
    Monitor for qBittorrent downloader.
    """
    
    def __init__(self, callback: Callable[[str], None], rpc_url: str = "http://localhost:8080/api/v2", username: str = "admin", password: str = "adminadmin", supported_extensions: tuple = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm")):
        """
        Initialize the qBittorrent monitor.
        
        Args:
            callback: Callback function to call when a download is completed.
            rpc_url: RPC URL of the qBittorrent instance.
            username: Username for qBittorrent web UI.
            password: Password for qBittorrent web UI.
            supported_extensions: Tuple of supported file extensions.
        """
        super().__init__(callback)
        self.rpc_url = rpc_url
        self.username = username
        self.password = password
        self.supported_extensions = supported_extensions
        self.session_cookie = None
        self._processed_torrents = set()  # 存储已处理的种子哈希，避免重复处理
        self._processed_files = set()  # 存储已处理的文件路径，避免重复回调同一文件
    
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
            import requests
            
            # 尝试获取应用版本信息
            url = f"{self.rpc_url}/app/version"
            headers = {
                "Cookie": self.session_cookie
            } if self.session_cookie else {}
            
            response = requests.get(url, headers=headers, auth=(self.username, self.password) if not self.session_cookie else None, timeout=30)
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
                    full_torrent_file_path = os.path.normpath(os.path.join(save_path, f_name)).lower()
                    
                    # 匹配逻辑：绝对路径一致，或者输入路径是以种子内文件路径结尾的（处理映射点差异）
                    if full_torrent_file_path == norm_input_path or norm_input_path.endswith(os.path.normpath(f_name).lower()):
                        target_torrent = torrent
                        break
                if target_torrent:
                    break
            
            if not target_torrent:
                logger.debug(f"在 qBittorrent 中未找到对应文件的任务: {file_path}")
                return False
                
            torrent_hash = target_torrent["hash"]
            
            # 检查种子内是否还有其他待处理的视频文件
            all_files = self._get_torrent_files(torrent_hash)
            remaining_videos = []
            
            for f in all_files:
                f_name = f["name"]
                # 检查是否是视频文件
                if f_name.lower().endswith(self.supported_extensions):
                    f_full_path = str(Path(os.path.join(target_torrent.get("save_path", ""), f_name)))
                    # 检查该文件是否在已处理集合中
                    if f_full_path not in self._processed_files:
                        # 再次尝试标准化匹配一次
                        is_processed = False
                        norm_f_full = os.path.normpath(f_full_path).lower()
                        for p_file in self._processed_files:
                            if os.path.normpath(p_file).lower() == norm_f_full:
                                is_processed = True
                                break
                        
                        if not is_processed:
                            remaining_videos.append(f_name)
            
            if remaining_videos:
                logger.info(f"种子 {torrent_hash} 仍有 {len(remaining_videos)} 个视频未处理完毕，将种子暂时保留在下载器中。剩余: {remaining_videos[:2]}...")
                return False # 返回 False，外层处理器将不会打印“已从下载器中删除”
            
            # 所有视频都已处理，执行删除
            delete_url = f"{self.rpc_url}/torrents/delete"
            data = {
                "hashes": torrent_hash,
                "deleteFiles": "false" 
            }
            
            headers = {"Cookie": self.session_cookie}
            response = requests.post(delete_url, data=data, timeout=30, headers=headers)
            if response.status_code == 200:
                logger.info(f"🎉 种子内所有视频已处理完毕，已删除 qBittorrent 任务: {target_torrent.get('name')} ({torrent_hash})")
                return True
            else:
                logger.warning(f"从 qBittorrent 删除任务失败: {torrent_hash}, 状态码: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"从 qBittorrent 清理任务时发生错误: {e}")
            return False

    def _monitor_loop(self):
        """
        Main monitoring loop for qBittorrent.
        """
        while self.running:
            try:
                # 检查会话是否有效，如果无效则重新登录
                if not self.is_connected():
                    if not self._login():
                        time.sleep(10)
                        continue
                
                # 获取所有已完成的种子
                all_completed_torrents = self._get_completed_torrents()
                
                for torrent in all_completed_torrents:
                    torrent_hash = torrent["hash"]
                    
                    # 1. 核心改进：跳过已处理完毕的种子，极大提升大种子库处理性能
                    if torrent_hash in self._processed_torrents:
                        continue
                        
                    # 2. 核心改进：通过进度判断是否完成，比 filter 更稳健
                    if torrent.get("progress", 0) < 1:
                        # 虽然 filter 过滤了完成，但双重保险
                        continue
                        
                    # 检查种子的保存路径
                    save_path = torrent.get("save_path", "")
                    if not save_path:
                        logger.error(f"Failed to get save path for torrent: {torrent_hash}")
                        continue
                    
                    # 获取种子中的文件
                    files = self._get_torrent_files(torrent_hash)
                    
                    # 记录种子是否完全处理完毕
                    torrent_fully_processed = True
                    
                    for file in files:
                        file_name = file["name"]
                        if file_name.lower().endswith(self.supported_extensions):
                            # 构建完整的文件路径
                            file_path = str(Path(os.path.join(save_path, file_name)))
                            
                            # 3. 核心改进：使用标准化路径进行“已处理”检测
                            file_path_norm = os.path.normpath(file_path).lower()
                            if any(os.path.normpath(f).lower() == file_path_norm for f in self._processed_files):
                                continue
                            
                            # 解码URL编码的文件名
                            file_path = urllib.parse.unquote(file_path)
                            logger.info(f"qBittorrent: Detected completed video file: {file_path}")
                            # 调用回调处理文件
                            try:
                                self.callback(file_path, downloader_monitor=self)
                                self._processed_files.add(file_path)
                                logger.debug(f"qBittorrent: Marked file as processed: {file_path}")
                            except Exception as e:
                                logger.error(f"qBittorrent: Failed to process file {file_path}: {e}")
                                torrent_fully_processed = False
                        else:
                            # 非视频文件不计入处理依赖，但有些种子可能只有非视频文件
                            pass
                    
                    # 如果种子中所有视频文件都已处理，且该种子之前未被标记，则标记种子为已处理
                    if torrent_fully_processed and torrent_hash not in self._processed_torrents:
                        self._processed_torrents.add(torrent_hash)
                        logger.info(f"Marked torrent as fully processed: {torrent_hash}")
                
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
            data = {
                "username": self.username,
                "password": self.password
            }
            
            response = requests.post(url, data=data, timeout=30)
            if response.status_code == 200 and response.text == "Ok.":
                # 获取会话cookie
                self.session_cookie = response.headers.get('Set-Cookie', '')
                logger.info(f"Login successful, session cookie: {self.session_cookie}")
                return True
            logger.error(f"Login failed with status {response.status_code}: {response.text}")
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
        params = {
            "filter": "all" # 改用 all，手动过滤进度，避免状态误判
        }
        headers = {
            "Cookie": self.session_cookie
        }
        
        max_retries = 3
        for i in range(max_retries):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.warning(f"获取 qBittorrent 种子列表失败 ({i+1}/{max_retries}): {e}")
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
        params = {
            "hash": torrent_hash
        }
        headers = {
            "Cookie": self.session_cookie
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()


class DownloaderMonitorFactory:
    """
    Factory class for creating downloader monitors.
    """
    
    @staticmethod
    def create_monitor(downloader_type: str, callback: Callable[[str], None], config: dict) -> Optional[DownloaderMonitor]:
        """
        Create a downloader monitor based on the given type.
        
        Args:
            downloader_type: Type of downloader ("aria2" or "qbittorrent").
            callback: Callback function to call when a download is completed.
            config: Configuration dictionary for the downloader.
            
        Returns:
            Optional[DownloaderMonitor]: Created downloader monitor or None if type is not supported.
        """
        if downloader_type == "aria2":
            return Aria2Monitor(
                callback,
                rpc_url=config.get("rpc_url", "http://localhost:6800/jsonrpc"),
                secret=config.get("secret"),
                supported_extensions=config.get("supported_extensions", (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"))
            )
        elif downloader_type == "qbittorrent":
            return QBittorrentMonitor(
                callback,
                rpc_url=config.get("rpc_url", "http://localhost:8080/api/v2"),
                username=config.get("username", "admin"),
                password=config.get("password", "adminadmin"),
                supported_extensions=config.get("supported_extensions", (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"))
            )
        else:
            logger.error(f"Unsupported downloader type: {downloader_type}")
            return None
