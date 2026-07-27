"""aria2 下载监控器"""

import os
import json
import time
import logging
import threading
import requests
from typing import Optional, Callable, Dict, Any, List

from .base import DownloaderMonitor, MonitorMode, decode_file_path

logger = logging.getLogger(__name__)


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
                                # aria2.removeDownloadResult 只删记录不删文件，需手动删除
                                try:
                                    if os.path.exists(aria2_path):
                                        os.remove(aria2_path)
                                        logger.info(f"已删除本地文件: {aria2_path}")
                                except Exception as del_e:
                                    logger.warning(
                                        f"删除本地文件失败，交由兜底处理: {del_e}"
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


