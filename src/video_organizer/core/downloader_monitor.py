"""
Downloader monitor module for monitoring download completion events from aria2 and qBittorrent.
"""

import logging
import threading
import os
import time
import re
import requests
import urllib.parse
import json
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class MonitorMode(Enum):
    """aria2 监控模式"""
    POLLING = "polling"      # 轮询模式（兼容性最好）
    WEBSOCKET = "websocket"  # WebSocket 实时模式（高效）
    WEBHOOK = "webhook"      # Webhook 模式（需要配置 aria2）


def decode_file_path(file_path: str) -> str:
    """
    智能解码文件路径，正确处理 URL 编码的中文和特殊字符。
    
    这个函数解决了以下问题：
    1. aria2 返回的路径可能是 URL 编码的（%E4%B8%89...）
    2. 文件名中的 + 号应该保留，不应该转换为空格
    3. 多次编码的情况需要正确处理
    
    Args:
        file_path: 原始文件路径
        
    Returns:
        str: 解码后的文件路径
    """
    if not file_path:
        return file_path
    
    # 检测是否包含 URL 编码（% 后跟两个十六进制字符）
    if not re.search(r'%[0-9A-Fa-f]{2}', file_path):
        return file_path
    
    try:
        # 方法1：使用 unquote（+ 号保持不变，因为这不是查询字符串）
        decoded = urllib.parse.unquote(file_path)
        
        # 检查是否还需要进一步解码（处理双重编码）
        if re.search(r'%[0-9A-Fa-f]{2}', decoded):
            decoded = urllib.parse.unquote(decoded)
        
        return decoded
    except Exception as e:
        logger.warning(f"Failed to decode file path '{file_path}': {e}")
        return file_path


def normalize_path(path: str) -> str:
    """
    标准化路径，处理不同操作系统的路径分隔符。
    
    Args:
        path: 原始路径
        
    Returns:
        str: 标准化后的路径
    """
    if not path:
        return path
    
    # 统一路径分隔符
    normalized = path.replace('\\', '/').replace('//', '/')
    
    # 对于 Windows 路径，保留驱动器字母后的冒号
    if len(normalized) >= 2 and normalized[1] == ':':
        normalized = normalized[0] + ':' + normalized[2:]
    
    return os.path.normpath(normalized)


def resolve_file_path(file_path: str) -> str:
    """
    智能解析文件路径，处理 aria2 返回解码路径但文件名实际是 URL 编码的情况。
    
    aria2 RPC 返回的路径可能是解码后的（如 "三叉戟.mp4"），
    但实际文件在磁盘上可能是 URL 编码形式（如 "%E4%B8%89%E5%8F%89%E6%88%9F.mp4"）。
    
    此函数会尝试多种方式查找文件：
    1. 原始路径
    2. 标准化路径
    3. 在目录中查找文件名匹配的文件（解码后比较）
    
    Args:
        file_path: aria2 返回的文件路径（可能已解码）
        
    Returns:
        str: 实际存在的文件路径，如果找不到则返回原始路径
    """
    if not file_path:
        return file_path
    
    # 1. 尝试原始路径
    if os.path.exists(file_path):
        return file_path
    
    # 2. 尝试标准化路径
    norm_path = os.path.normpath(file_path)
    if os.path.exists(norm_path):
        return norm_path
    
    # 3. 在目录中查找文件名匹配的文件
    dir_path = os.path.dirname(norm_path)
    filename = os.path.basename(norm_path)
    
    if os.path.exists(dir_path):
        try:
            # 获取目录中的所有文件
            for actual_filename in os.listdir(dir_path):
                # 跳过 .aria2 临时文件
                if actual_filename.endswith('.aria2'):
                    continue
                
                # 解码实际文件名进行比较
                actual_decoded = decode_file_path(actual_filename)
                
                # 比较（不区分大小写，Windows 兼容）
                if actual_decoded.lower() == filename.lower():
                    actual_path = os.path.join(dir_path, actual_filename)
                    logger.debug(f"Resolved file path: {file_path} -> {actual_path}")
                    return actual_path
                
                # 额外检查：如果文件名包含特殊字符，尝试直接比较
                if actual_filename == filename:
                    actual_path = os.path.join(dir_path, actual_filename)
                    return actual_path
                    
        except Exception as e:
            logger.warning(f"Error resolving file path in directory {dir_path}: {e}")
    
    # 4. 尝试重新编码路径（反向操作）
    # 如果解码后的路径不存在，可能文件名实际上是编码的
    try:
        # 只对文件名部分进行编码
        dir_path = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        # 编码非 ASCII 字符
        encoded_filename = urllib.parse.quote(filename, safe=':/\\.+_-')
        encoded_path = os.path.join(dir_path, encoded_filename)
        if os.path.exists(encoded_path):
            logger.debug(f"Found file with encoded name: {encoded_path}")
            return encoded_path
    except Exception:
        pass
    
    # 找不到文件，返回原始路径
    logger.warning(f"Could not resolve file path: {file_path}")
    return file_path


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
    
    支持三种监控模式：
    1. POLLING: 轮询模式，定期查询 aria2 获取已完成的下载（兼容性最好）
    2. WEBSOCKET: WebSocket 模式，实时接收下载完成事件（高效，推荐）
    3. WEBHOOK: Webhook 模式，通过 HTTP 接口接收 aria2 的通知（需要配置 aria2）
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        rpc_url: str = "http://localhost:6800/jsonrpc",
        secret: Optional[str] = None,
        supported_extensions: tuple = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"),
        monitor_mode: str = "polling",
        path_mappings: Optional[Dict[str, str]] = None,
        websocket_reconnect_delay: int = 5,
    ):
        """
        Initialize the aria2 monitor.

        Args:
            callback: Callback function to call when a download is completed.
            rpc_url: RPC URL of the aria2 instance.
            secret: Secret token for accessing the aria2 RPC interface.
            supported_extensions: Tuple of supported file extensions.
            monitor_mode: 监控模式 ("polling", "websocket", "webhook")
            path_mappings: 路径映射字典，将 aria2 返回的路径映射到主机实际路径
                          例如: {"/downloads": "F:/Downloads", "/data": "/mnt/data"}
            websocket_reconnect_delay: WebSocket 断线重连延迟（秒）
        """
        super().__init__(callback)
        self.rpc_url = rpc_url
        self.secret = secret
        self.supported_extensions = supported_extensions
        self.monitor_mode = MonitorMode(monitor_mode.lower())
        self.path_mappings = path_mappings or {}
        self.websocket_reconnect_delay = websocket_reconnect_delay
        
        self._processed_downloads = set()  # 存储已处理的下载ID，避免重复处理
        self._processed_files = set()  # 存储已处理的文件路径，避免重复回调同一文件
        
        # WebSocket 相关
        self._ws = None
        self._ws_thread = None
        self._ws_running = False
        
        # Webhook 相关
        self._webhook_server = None
        self._webhook_thread = None

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
            headers = {"Content-Type": "application/json"}
            payload = {
                "jsonrpc": "2.0",
                "method": "aria2.getVersion",
                "id": "1",
                "params": [f"token:{self.secret}"] if self.secret else [],
            }
            response = requests.post(
                self.rpc_url, headers=headers, json=payload, timeout=30
            )
            return response.status_code == 200 and "result" in response.json()
        except Exception as e:
            logger.error(f"Failed to connect to aria2: {e}")
            return False

    def remove_download(self, file_path: str) -> bool:
        """
        从 aria2 中删除指定文件的下载任务

        Args:
            file_path: 文件路径（可能是映射后的本地路径）

        Returns:
            bool: 删除成功返回 True，否则返回 False
        """
        try:
            # 获取所有已完成的下载
            completed_downloads = self._get_completed_downloads()

            # 解码和标准化输入路径
            decoded_input_path = decode_file_path(file_path)
            norm_input_path = os.path.normpath(decoded_input_path).lower()
            input_filename = os.path.basename(norm_input_path)

            # 查找包含该文件的下载任务
            for download in completed_downloads:
                files = download.get("files", [])
                for file_info in files:
                    # 获取 aria2 内部记录的文件路径
                    aria2_path = file_info.get("path")
                    if not aria2_path:
                        continue
                    
                    # 解码 aria2 返回的路径
                    decoded_aria2_path = decode_file_path(aria2_path)
                    
                    # 应用路径映射后比较
                    mapped_aria2_path = self._apply_path_mapping(decoded_aria2_path)
                    norm_aria2_path = os.path.normpath(mapped_aria2_path).lower()
                    aria2_filename = os.path.basename(norm_aria2_path)

                    # 匹配逻辑：
                    # 1. 完整路径精确匹配
                    # 2. 文件名匹配（解决路径映射不一致的问题）
                    if norm_aria2_path == norm_input_path or input_filename == aria2_filename:
                        gid = download.get("gid")

                        # 调用 aria2.removeDownloadResult 删除下载记录
                        headers = {"Content-Type": "application/json"}
                        payload = {
                            "jsonrpc": "2.0",
                            "method": "aria2.removeDownloadResult",
                            "id": "remove",
                            "params": (
                                [f"token:{self.secret}", gid] if self.secret else [gid]
                            ),
                        }

                        response = requests.post(
                            self.rpc_url, headers=headers, json=payload, timeout=30
                        )
                        if response.status_code == 200:
                            result = response.json()
                            if "result" in result and result["result"] == "OK":
                                logger.info(
                                    f"已从 aria2 删除下载任务: {gid} ({file_path})"
                                )
                                return True

                        logger.warning(f"从 aria2 删除下载任务失败: {gid}")
                        return False

            logger.debug(f"在 aria2 中未找到文件的下载任务: {file_path}")
            return False

        except Exception as e:
            logger.error(f"从 aria2 删除下载任务时出错: {e}")
            return False

    def start(self):
        """
        Start monitoring aria2 for completed downloads.
        根据配置的监控模式启动相应的监控方式。
        """
        self.running = True
        
        if self.monitor_mode == MonitorMode.WEBSOCKET:
            self._start_websocket_monitor()
        elif self.monitor_mode == MonitorMode.WEBHOOK:
            self._start_webhook_server()
        else:
            # 默认使用轮询模式
            self._start_polling_monitor()
        
        logger.info(f"Started aria2 monitor with mode: {self.monitor_mode.value}, RPC URL: {self.rpc_url}")
    
    def _start_polling_monitor(self):
        """启动轮询监控"""
        self.monitor_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self.monitor_thread.start()
    
    def _start_websocket_monitor(self):
        """启动 WebSocket 监控"""
        try:
            import websocket
        except ImportError:
            logger.warning("websocket-client not installed, falling back to polling mode. Run: pip install websocket-client")
            self.monitor_mode = MonitorMode.POLLING
            self._start_polling_monitor()
            return
        
        self._ws_running = True
        self._ws_thread = threading.Thread(target=self._websocket_loop, daemon=True)
        self._ws_thread.start()
        logger.info("WebSocket monitor started")
    
    def _start_webhook_server(self):
        """启动 Webhook HTTP 服务器"""
        # Webhook 模式需要外部调用 handle_webhook 方法
        # 这里只标记为运行状态
        logger.info("Webhook mode enabled. Call handle_webhook(gid) when aria2 sends notification.")
        self.monitor_thread = threading.Thread(target=self._webhook_keepalive, daemon=True)
        self.monitor_thread.start()
    
    def _webhook_keepalive(self):
        """Webhook 模式的保活循环"""
        while self.running:
            time.sleep(60)  # 保持线程运行

    def stop(self):
        """
        Stop monitoring aria2.
        """
        self.running = False
        self._ws_running = False
        
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        
        if self.monitor_thread:
            self.monitor_thread.join()
        if self._ws_thread:
            self._ws_thread.join()
            
        logger.info("Stopped aria2 monitor")

    def _websocket_loop(self):
        """
        WebSocket 监控循环，实时接收 aria2 的下载完成事件。
        """
        import websocket
        
        # 将 HTTP URL 转换为 WebSocket URL
        ws_url = self.rpc_url.replace("http://", "ws://").replace("https://", "wss://")
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                # aria2 WebSocket 通知格式: {"method": "aria2.onDownloadComplete", "params": [{"gid": "xxx"}]}
                if data.get("method") == "aria2.onDownloadComplete":
                    params = data.get("params", [])
                    if params:
                        gid = params[0].get("gid")
                        if gid:
                            logger.info(f"WebSocket received download complete event: {gid}")
                            self._process_download_by_gid(gid)
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
        
        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket connection closed")
            if self._ws_running and self.running:
                logger.info(f"Attempting to reconnect in {self.websocket_reconnect_delay} seconds...")
                time.sleep(self.websocket_reconnect_delay)
                if self._ws_running and self.running:
                    self._connect_websocket(ws_url)
        
        def on_open(ws):
            logger.info("WebSocket connection established")
            # 发送订阅请求
            if self.secret:
                ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "aria2.onDownloadComplete",
                    "id": "subscribe",
                    "params": [f"token:{self.secret}"]
                }))
        
        self._connect_websocket = lambda url: self._create_websocket_connection(
            url, on_message, on_error, on_close, on_open
        )
        self._connect_websocket(ws_url)
    
    def _create_websocket_connection(self, ws_url, on_message, on_error, on_close, on_open):
        """创建 WebSocket 连接"""
        import websocket
        
        self._ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        self._ws.run_forever()
    
    def handle_webhook(self, gid: str) -> bool:
        """
        处理 Webhook 通知（由外部调用）
        
        Args:
            gid: aria2 下载任务的 GID
            
        Returns:
            bool: 处理成功返回 True
        """
        logger.info(f"Webhook received for GID: {gid}")
        return self._process_download_by_gid(gid)
    
    def _process_download_by_gid(self, gid: str) -> bool:
        """
        根据 GID 处理下载完成的任务
        
        Args:
            gid: 下载任务的 GID
            
        Returns:
            bool: 处理成功返回 True
        """
        try:
            # 获取下载信息
            download_info = self._get_download_info(gid)
            if not download_info:
                logger.warning(f"Could not get download info for GID: {gid}")
                return False
            
            # 检查是否已处理
            if gid in self._processed_downloads:
                logger.debug(f"Download {gid} already processed")
                return True
            
            # 处理文件
            files = download_info.get("files", [])
            success = True
            
            for file_info in files:
                file_path = file_info.get("path")
                if file_path and file_path.lower().endswith(self.supported_extensions):
                    if self._process_single_file(file_path):
                        self._processed_files.add(file_path)
                    else:
                        success = False
            
            self._processed_downloads.add(gid)
            return success
            
        except Exception as e:
            logger.error(f"Error processing download {gid}: {e}")
            return False
    
    def _get_download_info(self, gid: str) -> Optional[Dict]:
        """
        获取指定 GID 的下载信息
        
        Args:
            gid: 下载任务的 GID
            
        Returns:
            Optional[Dict]: 下载信息字典
        """
        try:
            headers = {"Content-Type": "application/json"}
            params = [f"token:{self.secret}"] if self.secret else []
            payload = {
                "jsonrpc": "2.0",
                "method": "aria2.tellStatus",
                "id": "1",
                "params": params + [gid, ["gid", "status", "files", "totalLength", "completedLength"]],
            }
            
            response = requests.post(
                self.rpc_url, headers=headers, json=payload, timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            return result.get("result")
        except Exception as e:
            logger.error(f"Failed to get download info for {gid}: {e}")
            return None

    def _polling_loop(self):
        """
        Main polling loop for aria2.
        """
        while self.running:
            try:
                logger.debug("Aria2 polling loop iteration")
                # 获取已完成的下载
                completed_downloads = self._get_completed_downloads()
                logger.debug(
                    f"Aria2: Got {len(completed_downloads)} completed downloads"
                )

                for download in completed_downloads:
                    download_gid = download.get("gid")
                    logger.debug(f"Aria2: Download GID: {download_gid}")

                    if not download_gid:
                        logger.debug("Aria2: Skipping download without GID")
                        continue

                    if download_gid in self._processed_downloads:
                        logger.debug(
                            f"Aria2: Download {download_gid} already processed, skipping"
                        )
                        continue

                    # 获取文件路径
                    files = download.get("files", [])
                    logger.debug(f"Aria2: Download has {len(files)} files")

                    for file_info in files:
                        file_path = file_info.get("path")
                        logger.debug(f"Aria2: File path in download: {file_path}")

                        if file_path:
                            if self._process_single_file(file_path):
                                self._processed_files.add(file_path)

                    # 标记为已处理
                    self._processed_downloads.add(download_gid)
                    logger.info(f"Marked aria2 download as processed: {download_gid}")

                # 等待一段时间后再次检查
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error in aria2 monitor loop: {e}")
                time.sleep(10)  # 发生错误时，延长等待时间
    
    def _process_single_file(self, file_path: str) -> bool:
        """
        处理单个文件
        
        Args:
            file_path: 原始文件路径（aria2 返回的路径）
            
        Returns:
            bool: 处理成功返回 True，需要重试返回 False
        """
        # 检查文件是否已经处理过
        if file_path in self._processed_files:
            logger.debug(f"Aria2: File {file_path} already processed, skipping")
            return True
        
        # 检查扩展名
        if not file_path.lower().endswith(self.supported_extensions):
            logger.debug(f"Aria2: File {file_path} has unsupported extension, skipping")
            return True
        
        # 解码文件路径
        decoded_path = decode_file_path(file_path)
        logger.debug(f"Aria2: Decoded path: {decoded_path}")
        
        # 应用路径映射
        mapped_path = self._apply_path_mapping(decoded_path)
        if mapped_path != decoded_path:
            logger.debug(f"Aria2: Mapped path: {mapped_path}")
        
        logger.info(f"Detected completed video file from aria2: {mapped_path}")
        
        # 调用回调处理文件
        result = self.callback(mapped_path, downloader_monitor=self)
        
        if result is not False:
            logger.debug(f"Aria2: File processed successfully: {mapped_path}")
            return True
        else:
            logger.info(f"Aria2: File not processed (will retry): {mapped_path}")
            return False
    
    def _apply_path_mapping(self, file_path: str) -> str:
        """
        应用路径映射，将 aria2 返回的路径转换为本地实际路径
        
        Args:
            file_path: aria2 返回的原始路径
            
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

    def _get_completed_downloads(self):
        """
        Get completed downloads from aria2.

        Returns:
            list: List of completed downloads.
        """
        headers = {"Content-Type": "application/json"}

        # 构建请求参数
        params = [f"token:{self.secret}"] if self.secret else []

        # 使用aria2.tellStopped获取已完成的下载（offset=0, limit=100表示获取最近100个已停止的下载）
        payload = {
            "jsonrpc": "2.0",
            "method": "aria2.tellStopped",
            "id": "1",
            "params": params + [0, 2000, ["gid", "status", "files"]],
        }

        response = requests.post(
            self.rpc_url, headers=headers, json=payload, timeout=30
        )
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
                logger.info(
                    f"种子 {torrent_hash} 仍有 {len(remaining_videos)} 个视频未处理完毕，将种子暂时保留在下载器中。剩余: {remaining_videos[:2]}..."
                )
                return False  # 返回 False，外层处理器将不会打印"已从下载器中删除"

            # 所有视频都已处理，执行删除
            delete_url = f"{self.rpc_url}/torrents/delete"
            data = {"hashes": torrent_hash, "deleteFiles": "false"}

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


class DownloaderMonitorFactory:
    """
    Factory class for creating downloader monitors.
    """

    @staticmethod
    def create_monitor(
        downloader_type: str, callback: Callable[[str], None], config: dict
    ) -> Optional[DownloaderMonitor]:
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
            # 解析路径映射配置
            path_mappings = DownloaderMonitorFactory._parse_path_mappings(
                config.get("path_mappings", {})
            )
            
            return Aria2Monitor(
                callback,
                rpc_url=config.get("rpc_url", "http://localhost:6800/jsonrpc"),
                secret=config.get("secret"),
                supported_extensions=config.get(
                    "supported_extensions",
                    (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"),
                ),
                monitor_mode=config.get("monitor_mode", "polling"),
                path_mappings=path_mappings,
                websocket_reconnect_delay=config.get("websocket_reconnect_delay", 5),
            )
        elif downloader_type == "qbittorrent":
            # qBittorrent 也支持路径映射
            path_mappings = DownloaderMonitorFactory._parse_path_mappings(
                config.get("path_mappings", {})
            )
            
            monitor = QBittorrentMonitor(
                callback,
                rpc_url=config.get("rpc_url", "http://localhost:8080/api/v2"),
                username=config.get("username", "admin"),
                password=config.get("password", "adminadmin"),
                supported_extensions=config.get(
                    "supported_extensions",
                    (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".strm"),
                ),
            )
            # 设置路径映射
            monitor.path_mappings = path_mappings
            return monitor
        else:
            logger.error(f"Unsupported downloader type: {downloader_type}")
            return None
    
    @staticmethod
    def _parse_path_mappings(mappings_config) -> Dict[str, str]:
        """
        解析路径映射配置
        
        支持多种配置格式：
        1. 字典格式: {"/downloads": "F:/Downloads"}
        2. 字符串格式: "/downloads:/root/downloads" (旧格式兼容)
        3. 列表格式: ["/downloads:F:/Downloads", "/data:/mnt/data"]
        
        Args:
            mappings_config: 路径映射配置
            
        Returns:
            Dict[str, str]: 解析后的路径映射字典
        """
        if isinstance(mappings_config, dict):
            return mappings_config
        
        if isinstance(mappings_config, str) and mappings_config.strip():
            # 旧格式: "/downloads:/root/downloads"
            parts = mappings_config.split(":", 1)
            if len(parts) == 2:
                return {parts[0].strip(): parts[1].strip()}
        
        if isinstance(mappings_config, list):
            result = {}
            for item in mappings_config:
                if isinstance(item, str) and ":" in item:
                    parts = item.split(":", 1)
                    if len(parts) == 2:
                        result[parts[0].strip()] = parts[1].strip()
            return result
        
        return {}
