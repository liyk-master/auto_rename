"""
Downloader monitor module for monitoring download completion events from aria2 and qBittorrent.
"""

import logging
import threading
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
            import requests
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
        import requests
        
        try:
            # 获取所有已完成的下载
            completed_downloads = self._get_completed_downloads()
            
            # 查找包含该文件的下载任务
            for download in completed_downloads:
                files = download.get("files", [])
                for file_info in files:
                    if file_info.get("path") == file_path:
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
        import time
        import requests
        
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
        import requests
        
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
        从 qBittorrent 中删除指定文件的种子任务
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 删除成功返回 True，否则返回 False
        """
        import requests
        import os
        
        try:
            # 获取所有已完成的种子
            completed_torrents = self._get_completed_torrents()
            
            # 查找包含该文件的种子
            for torrent in completed_torrents:
                torrent_hash = torrent["hash"]
                save_path = torrent.get("save_path", "")
                
                # 获取种子的文件列表
                files = self._get_torrent_files(torrent_hash)
                
                for file in files:
                    file_name = file["name"]
                    full_path = os.path.join(save_path, file_name)
                    
                    if full_path == file_path or file_path.endswith(file_name):
                        # 调用 qBittorrent API 删除种子
                        # deleteFiles=true 表示同时删除文件
                        delete_url = f"{self.rpc_url}/torrents/delete"
                        data = {
                            "hashes": torrent_hash,
                            "deleteFiles": "false"  # 不删除文件，因为已经被上传程序删除了
                        }
                        
                        # 使用 requests 而不是 self.session
                        headers = {
                            "Cookie": self.session_cookie
                        }
                        import requests
                        response = requests.post(delete_url, data=data, timeout=30, headers=headers)
                        if response.status_code == 200:
                            logger.info(f"已从 qBittorrent 删除种子任务: {torrent_hash} ({file_path})")
                            return True
                        else:
                            logger.warning(f"从 qBittorrent 删除种子任务失败: {torrent_hash}, 状态码: {response.status_code}")
                            return False
            
            logger.debug(f"在 qBittorrent 中未找到文件的种子任务: {file_path}")
            return False
            
        except Exception as e:
            logger.error(f"从 qBittorrent 删除种子任务时出错: {e}")
            return False

    def _monitor_loop(self):
        """
        Main monitoring loop for qBittorrent.
        """
        import time
        import requests
        import os
        
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
                    
                    # 跳过已处理的种子
                    if torrent_hash in self._processed_torrents:
                        continue
                    
                    # 获取种子的保存路径
                    save_path = torrent.get("save_path", "")
                    if not save_path:
                        logger.error(f"Failed to get save path for torrent: {torrent_hash}")
                        continue
                    
                    # 获取种子中的文件
                    files = self._get_torrent_files(torrent_hash)
                    for file in files:
                        file_name = file["name"]
                        if file_name.endswith((".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm")):
                            # 构建完整的文件路径
                            file_path = os.path.join(save_path, file_name)
                            
                            # 检查文件是否已经处理过
                            if file_path in self._processed_files:
                                logger.debug(f"qBittorrent: File {file_path} already processed, skipping")
                                continue
                            
                            logger.info(f"Detected completed video file: {file_path}")
                            self.callback(file_path, downloader_monitor=self)
                            # 标记文件为已处理
                            self._processed_files.add(file_path)
                            logger.debug(f"qBittorrent: Marked file as processed: {file_path}")
                    
                    # 标记种子为已处理
                    self._processed_torrents.add(torrent_hash)
                    logger.info(f"Marked torrent as processed: {torrent_hash}")
                
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
        import requests
        
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
        import requests
        
        url = f"{self.rpc_url}/torrents/info"
        params = {
            "filter": "completed"
        }
        headers = {
            "Cookie": self.session_cookie
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def _get_torrent_files(self, torrent_hash: str):
        """
        Get files in a torrent.
        
        Args:
            torrent_hash: Hash of the torrent.
            
        Returns:
            list: List of files in the torrent.
        """
        import requests
        
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
