import os
import sys
import json
import base64
import shutil
import subprocess
import requests
import threading
import logging
from datetime import datetime
from queue import Queue, Empty
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# 导入项目内部的上传工具
from ..upload.upload_emos import RobustEmosVideoUploader

from .renamer import VideoRenamer
from .tmdb_client import TMDBClient
from .subtitle_handler import SubtitleHandler
from .downloader_monitor import decode_file_path
from ..utils.logging_utils import get_logger, log_success, log_failure, log_exception
from ..database.operations import record_task
from ..database.session import init_db as init_task_db


# 获取模块级别的 logger
_logger = logging.getLogger(__name__)


def console_log(message: str):
    """
    统一的输出函数 - 同时输出到控制台和日志文件
    
    替代直接 print() 调用，确保日志被记录到文件
    """
    # 输出到控制台
    print(message)
    
    # 写入日志文件（移除 ANSI 颜色代码）
    import re
    clean_message = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', message)
    _logger.info(clean_message)


def _upload_cas_file(cas_file: Path, cas_data: dict, url: str, api_key: str, path: str = "") -> None:
    """上传 .cas 文件到外部 API（自动重试 3 次）"""
    api_url = url.rstrip("/") + "/api/upload"
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with open(cas_file, "rb") as f:
                file_bytes = f.read()
            files = {"file": (cas_file.name, file_bytes, "application/octet-stream")}
            data = {"caption": json.dumps(cas_data, ensure_ascii=False)}
            if path:
                data["path"] = path
            resp = requests.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
                timeout=30,
            )
            if not resp.ok:
                body_preview = resp.text[:500]
                console_log(
                    f"⚠️ .cas 文件上传到外部 API 失败 (HTTP {resp.status_code}, "
                    f"第 {attempt}/{max_retries} 次): {body_preview}"
                )
                if attempt < max_retries:
                    time.sleep(5)
                    continue
                return
            console_log(f"📤 .cas 文件已上传到外部 API: {cas_file.name}")
            return
        except Exception as e:
            console_log(f"⚠️ .cas 文件上传到外部 API 异常 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                time.sleep(5)
            else:
                console_log(f"❌ .cas 文件上传到外部 API 已达最大重试次数: {cas_file.name}")


class VideoFileHandler:
    """
    视频文件处理器，用于处理文件系统事件
    """

    def __init__(
        self,
        output_dir: str,
        supported_extensions: List[str],
        naming_rules: Optional[Dict[str, str]] = None,
        tmdb_config: Optional[Dict[str, Any]] = None,
        emos_config: Optional[Dict[str, Any]] = None,
        p123_config: Optional[Dict[str, Any]] = None,
        cloud189_config: Optional[Dict[str, Any]] = None,
        yun139_config: Optional[Dict[str, Any]] = None,
        processing_config: Optional[Dict[str, Any]] = None,
        path_mappings: Optional[Dict[str, str]] = None,
        telegram_config: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        emya_db_config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化视频文件处理器

        Args:
            output_dir: 输出目录
            supported_extensions: 支持的文件扩展名列表
            naming_rules: 命名规则字典
            tmdb_config: TMDB配置字典
            emos_config: Emos配置字典
            processing_config: 处理配置字典
            path_mappings: 路径映射字典 (下载器路径 -> 本地路径)
            yun139_config: 139云盘配置字典
        """
        # 初始化日志记录器
        self.logger = get_logger(__name__)

        self.output_dir = output_dir
        self.supported_extensions = supported_extensions
        self.path_mappings = path_mappings or {}

        # 初始化处理配置
        self.processing_config = processing_config or {}
        self.delete_after_upload = self.processing_config.get(
            "delete_after_upload", False
        )
        # 清理配置值中的行内注释
        raw_targets = self.processing_config.get("upload_targets", "emos")
        raw_targets = str(raw_targets).split("#")[0].split(";")[0].strip()
        
        # 解析上传目标：支持逗号分隔的多选，如 "emos,p123,cloud189"
        # 也兼容旧格式: emos, p123, both, all
        if raw_targets == "both":
            self.upload_targets = ["emos", "p123"]
        elif raw_targets == "all":
            self.upload_targets = ["emos", "p123", "cloud189", "yun139"]
        else:
            # 逗号分隔的多选
            self.upload_targets = [t.strip() for t in raw_targets.split(",") if t.strip()]

        # 初始化Emos配置
        # 初始化Emos配置
        self.emos_config = emos_config or {}
        raw_token = self.emos_config.get("auth_token", "")
        self.emos_auth_token = str(raw_token).split("#")[0].split(";")[0].strip()
        self.emos_base_url = self.emos_config.get("base_url", "https://emos.lol")
        self.emos_file_storage = self.emos_config.get(
            "file_storage", "internal"
        )  # internal 或 global
        self.emos_chunk_size_mb = self.emos_config.get(
            "chunk_size_mb", 50
        )  # 分片大小(MB)，默认50
        self.max_upload_workers = int(
            self.processing_config.get("max_upload_workers", 1)
        )  # 并发上传数（全局默认）

        # 初始化 123 云盘配置
        self.p123_config = p123_config or {}
        raw_p123_token = self.p123_config.get("token", "")
        self.p123_token = str(raw_p123_token).split("#")[0].split(";")[0].strip()
        self.p123_parent_id = int(self.p123_config.get("parent_id", 0))
        self.p123_max_workers = int(
            self.p123_config.get("max_workers", 2)
        )  # 默认2个线程

        # 初始化天翼云盘配置
        self.cloud189_config = cloud189_config or {}
        raw_cloud189_username = self.cloud189_config.get("username", "")
        self.cloud189_username = str(raw_cloud189_username).split("#")[0].split(";")[0].strip()
        raw_cloud189_password = self.cloud189_config.get("password", "")
        self.cloud189_password = str(raw_cloud189_password).split("#")[0].split(";")[0].strip()
        raw_cloud189_cookie = self.cloud189_config.get("cookie", "")
        self.cloud189_cookie = str(raw_cloud189_cookie).split("#")[0].split(";")[0].strip()
        raw_cloud189_parent_id = self.cloud189_config.get("parent_folder_id", "-11")
        self.cloud189_parent_id = str(raw_cloud189_parent_id).split("#")[0].split(";")[0].strip()
        raw_cloud189_family_id = self.cloud189_config.get("family_id", "")
        self.cloud189_family_id = str(raw_cloud189_family_id).split("#")[0].split(";")[0].strip()
        self.cloud189_max_workers = int(self.cloud189_config.get("max_workers", 5))
        raw_cloud189_strm_server = self.cloud189_config.get("strm_server", "")
        self.cloud189_strm_server = str(raw_cloud189_strm_server).split("#")[0].split(";")[0].strip()
        raw_cloud189_strm_output = self.cloud189_config.get("strm_output_dir", "")
        self.cloud189_strm_output_dir = str(raw_cloud189_strm_output).split("#")[0].split(";")[0].strip()
        self.cloud189_delete_after = self.cloud189_config.get("delete_after", False)
        self.cloud189_empty_recycle_bin = self.cloud189_config.get("empty_recycle_bin", False)
        self.cloud189_generate_cas = self.cloud189_config.get("generate_cas", False)
        raw_cas_dir = self.cloud189_config.get("cas_output_dir", "")
        self.cloud189_cas_output_dir = str(raw_cas_dir).strip()
        raw_cas_url = self.cloud189_config.get("cas_upload_url", "")
        self.cloud189_cas_upload_url = str(raw_cas_url).strip()
        raw_cas_key = self.cloud189_config.get("cas_upload_api_key", "")
        self.cloud189_cas_upload_api_key = str(raw_cas_key).strip()

        # 初始化 139 云盘配置
        self.yun139_config = yun139_config or {}
        raw_yun139_auth = self.yun139_config.get("authorization", "")
        self.yun139_authorization = str(raw_yun139_auth).split("#")[0].split(";")[0].strip()
        self.yun139_cloud_type = self.yun139_config.get("cloud_type", "personal_new")
        self.yun139_cloud_id = self.yun139_config.get("cloud_id", "")
        # parent_id: / 或空字符串表示根目录
        raw_yun139_parent_id = self.yun139_config.get("parent_id", "/")
        self.yun139_parent_id = str(raw_yun139_parent_id).split("#")[0].split(";")[0].strip() or "/"
        self.yun139_custom_part_size = int(self.yun139_config.get("custom_part_size", 0))
        self.yun139_max_workers = int(self.yun139_config.get("max_workers", 3))  # 并行上传视频数
        raw_yun139_strm_server = self.yun139_config.get("strm_server", "")
        self.yun139_strm_server = str(raw_yun139_strm_server).split("#")[0].split(";")[0].strip()
        raw_yun139_strm_output = self.yun139_config.get("strm_output_dir", "")
        self.yun139_strm_output_dir = str(raw_yun139_strm_output).split("#")[0].split(";")[0].strip()
        self.yun139_delete_after = self.yun139_config.get("delete_after", False)
        self.yun139_app_mode = self.yun139_config.get("app_mode", False)
        self.yun139_generate_strm = self.yun139_config.get("generate_strm", True)

        # 初始化 Telegram 配置
        self.telegram_config = telegram_config or {}

        # 初始化TMDB客户端
        tmdb_client = None
        if tmdb_config and tmdb_config.get("api_key"):
            try:
                tmdb_client = TMDBClient(
                    api_key=tmdb_config["api_key"],
                    retry_count=tmdb_config.get("retry_count", 3),
                    timeout=tmdb_config.get("timeout", 30),
                    base_url=tmdb_config.get("base_url"),
                )
                self.logger.info("TMDB客户端初始化成功")
            except Exception as e:
                log_failure(self.logger, "初始化TMDB客户端失败", error=e)

        # 初始化 123 云盘上传器
        self.p123_uploader = None
        if self.p123_token and self.p123_parent_id != 0:
            try:
                from ..upload.upload_p123 import P123Uploader

                self.p123_uploader = P123Uploader(
                    self.p123_token,
                    self.p123_parent_id,
                    telegram_config=self.telegram_config,
                    max_workers=self.p123_max_workers,
                )
                self.logger.info("123云盘上传器初始化成功")
            except Exception as e:
                self.logger.error(f"初始化123云盘上传器失败: {e}")

        # 初始化天翼云盘上传器
        self.cloud189_uploader = None
        if self.cloud189_username or self.cloud189_cookie:
            try:
                from ..upload.upload_cloud189 import Cloud189Uploader

                self.cloud189_uploader = Cloud189Uploader(
                    username=self.cloud189_username,
                    password=self.cloud189_password,
                    cookie=self.cloud189_cookie,
                    parent_folder_id=self.cloud189_parent_id,
                    family_id=self.cloud189_family_id,
                    telegram_config=self.telegram_config,
                    max_workers=self.cloud189_max_workers,
                    strm_server=self.cloud189_strm_server,
                    strm_output_dir=self.cloud189_strm_output_dir,
                    delete_after=self.cloud189_delete_after,
                )
                self.logger.info("天翼云盘上传器初始化成功")
            except Exception as e:
                self.logger.error(f"初始化天翼云盘上传器失败: {e}")

        # 初始化 139 云盘上传器
        self.yun139_uploader = None
        if self.yun139_authorization:
            try:
                from ..upload.upload_yun139 import Yun139Uploader

                self.yun139_uploader = Yun139Uploader(
                    authorization=self.yun139_authorization,
                    cloud_type=self.yun139_cloud_type,
                    cloud_id=self.yun139_cloud_id,
                    parent_id=self.yun139_parent_id,
                    custom_part_size=self.yun139_custom_part_size,
                    telegram_config=self.telegram_config,
                    strm_server=self.yun139_strm_server,
                    strm_output_dir=self.yun139_strm_output_dir,
                    delete_after=self.yun139_delete_after,
                    app_mode=self.yun139_app_mode,
                    media_tracker_config=config.get("media_tracker", {}) if config else {},
                    generate_strm=self.yun139_generate_strm,
                )
                # 如果 yun139 配置了 max_workers，则覆盖全局设置
                if self.yun139_max_workers > 0:
                    self.max_upload_workers = self.yun139_max_workers
                    self.logger.info(f"139云盘使用自定义并发数: {self.yun139_max_workers}")
                self.logger.info("139云盘上传器初始化成功")
            except Exception as e:
                self.logger.error(f"初始化139云盘上传器失败: {e}")

        # 初始化文件重命名器
        try:
            # 从配置中获取TMDB API密钥
            tmdb_api_key = tmdb_config.get("api_key") if tmdb_config else None
            self.renamer = VideoRenamer(
                tmdb_api_key=tmdb_api_key,
                naming_rules=naming_rules,
                config=config,
            )
            self.logger.info("视频重命名器初始化成功")
        except Exception as e:
            log_exception(self.logger, "初始化视频重命名器失败")
            # 创建一个基本的重命名器作为后备
            self.renamer = VideoRenamer(tmdb_api_key=None)

        # 初始化字幕处理器
        try:
            self.subtitle_handler = SubtitleHandler()
            self.logger.info("字幕处理器初始化成功")
        except Exception as e:
            log_exception(self.logger, "初始化字幕处理器失败")
            self.subtitle_handler = None

        # 初始化 emya 数据库入库功能
        self.emya_db_config = emya_db_config or {}
        self.emya_enabled = self.emya_db_config.get("enabled", False)
        self.emya_controller = None

        if self.emya_enabled:
            try:
                from .emya_api import init_controller, EmyaApiController

                # 初始化数据库连接
                db_config = {
                    "host": self.emya_db_config.get("host", "localhost"),
                    "port": self.emya_db_config.get("port", 3306),
                    "user": self.emya_db_config.get("user", "root"),
                    "password": self.emya_db_config.get("password", ""),
                    "database": self.emya_db_config.get("database", "emya"),
                    "charset": self.emya_db_config.get("charset", "utf8mb4"),
                    "pool_size": self.emya_db_config.get("pool_size", 5),
                    "max_overflow": self.emya_db_config.get("max_overflow", 10),
                    "pool_recycle": self.emya_db_config.get("pool_recycle", 3600),
                }

                self.emya_controller = init_controller(
                    db_config=db_config,
                    default_user_id=self.emya_db_config.get("default_user_id", 1),
                )
                self.logger.info("emya 数据库入库功能初始化成功")
            except Exception as e:
                self.logger.error(f"初始化 emya 数据库入库功能失败: {e}")
                self.emya_enabled = False

        # 父监控器引用
        self._parent_monitor = None

        # 初始化任务历史数据库（失败不阻塞）
        try:
            init_task_db()
        except Exception:
            self.logger.warning("初始化任务历史数据库失败（部分功能可能受限）")

        # 处理中的文件，用于跟踪文件写入完成状态
        self._processing_files = set()

        # 上传状态跟踪，用于防止重复上传
        self._uploading_files = set()  # 正在上传的文件
        self._uploaded_files = set()  # 已成功上传的文件
        self._failed_files = {}  # 失败的文件及原因
        self._max_set_size = 1000  # 限制集合大小，防止内存溢出

        # 队列去重机制
        self._queued_files = set()  # 追踪队列中的文件，防止重复添加
        self._queue_lock = threading.Lock()  # 队列操作锁，防止竞态条件
        self._file_downloader_map = {}  # 文件到下载器的映射，用于删除下载任务

        # 上传队列配置
        self._upload_queue = Queue()  # 上传队列
        self._use_queue = True  # 是否使用队列（可配置）
        self._queue_running = False  # 队列运行标志
        self._queue_thread = None  # 队列处理线程

        # 注册的下载器列表，用于清理任务
        self.downloaders = []

        # 启动上传队列处理线程
        self._start_upload_queue()

    def add_downloader(self, downloader):
        """
        添加下载器实例

        Args:
            downloader: 下载器监控实例
        """
        if downloader not in self.downloaders:
            self.downloaders.append(downloader)

    def on_created(self, event):
        """
        当文件创建时被调用

        Args:
            event: 文件系统事件
        """
        if event.is_directory:
            return

        file_path = event.src_path
        if self._is_supported_file(file_path):
            # 检查是否是处理中的文件（避免重复处理）
            if file_path in self._processing_files:
                self.logger.debug(f"文件已在处理队列中: {file_path}")
                return

            self._processing_files.add(file_path)
            try:
                # 检查文件是否完整写入
                if self._is_file_complete(file_path):
                    self._process_file(file_path)
                else:
                    # 如果文件未完整写入，设置一个延迟处理
                    self.logger.debug(f"文件尚未完成写入，稍后处理: {file_path}")
                    # 在监控器的下一个轮询周期处理
                    if self._parent_monitor:
                        self._parent_monitor._pending_files.add(file_path)
            finally:
                # 无论处理结果如何，从处理队列中移除
                self._processing_files.discard(file_path)

    def on_modified(self, event):
        """
        当文件修改时被调用

        Args:
            event: 文件系统事件
        """
        if event.is_directory:
            return

        file_path = event.src_path
        if self._is_supported_file(file_path):
            # 检查文件是否已经在上传中或已上传，避免重复处理
            if file_path in self._uploading_files or file_path in self._uploaded_files:
                self.logger.debug(
                    f"文件已在上传中或已上传，跳过修改事件处理: {file_path}"
                )
                return

            # 对于修改事件，检查文件是否已完成写入
            if not file_path in self._processing_files and self._is_file_complete(
                file_path
            ):
                self._process_file(file_path)

    def _is_supported_file(self, file_path: str) -> bool:
        """
        检查文件是否为支持的视频或字幕文件

        Args:
            file_path: 文件路径

        Returns:
            是否为支持的文件
        """
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            return file_ext in self.supported_extensions
        except Exception as e:
            self.logger.error(f"检查文件类型时出错: {file_path}, 错误: {e}")
            return False

    def _is_subtitle_file(self, file_path: str) -> bool:
        """
        检查文件是否为字幕文件

        Args:
            file_path: 文件路径

        Returns:
            是否为字幕文件
        """
        if not self.subtitle_handler:
            return False
        return self.subtitle_handler.is_subtitle_file(Path(file_path))

    def _is_video_file(self, file_path: str) -> bool:
        """
        检查文件是否为视频文件

        Args:
            file_path: 文件路径

        Returns:
            是否为视频文件
        """
        subtitle_extensions = {'.srt', '.ass', '.ssa', '.sub', '.vtt'}
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            return file_ext in self.supported_extensions and file_ext not in subtitle_extensions
        except Exception as e:
            self.logger.error(f"检查文件类型时出错: {file_path}, 错误: {e}")
            return False

    def _is_file_complete(self, file_path: str) -> bool:
        """
        检查文件是否已完成写入

        Args:
            file_path: 文件路径

        Returns:
            文件是否完整
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return False

            # 尝试以只读方式打开文件，检查是否被锁定
            try:
                with open(file_path, "rb") as f:
                    # 读取文件的最后1KB，测试是否能正常访问
                    f.seek(0, 2)  # 移动到文件末尾
                    file_size = f.tell()

                    # 检查文件大小是否为0
                    if file_size == 0:
                        return False

                    # 等待一小段时间，检查文件大小是否变化
                    import time

                    time.sleep(0.5)  # 等待500ms，增加等待时间提高准确性

                    # 再次检查文件大小
                    current_size = os.path.getsize(file_path)

                    # 如果文件大小没有变化，认为文件已完成写入
                    return file_size == current_size
            except PermissionError:
                # 文件被锁定（可能正在下载），返回False
                self.logger.debug(f"文件被锁定，可能正在下载: {file_path}")
                return False
        except Exception as e:
            self.logger.error(f"检查文件完整性时出错: {file_path}, 错误: {e}")
            return False

    def _start_upload_queue(self):
        """
        启动上传队列处理线程
        """
        print(f"DEBUG: 尝试启动上传队列处理线程... 当前状态: {self._queue_running}")
        with threading.Lock():
            if not self._queue_running:
                self._queue_running = True

                print(f"DEBUG: 正在启动 {self.max_upload_workers} 个工作线程...")
                # 启动指定数量的消费者线程
                for i in range(self.max_upload_workers):
                    thread = threading.Thread(
                        target=self._worker_process_queue, args=(i + 1,), daemon=True
                    )
                    thread.start()
                    self.logger.info(f"上传工作线程 #{i+1} 已启动")
                    print(f"DEBUG: 工作线程 #{i+1} 已启动")
            else:
                print("DEBUG: 队列已经在运行中")

    def _worker_process_queue(self, worker_id):
        """
        上传队列消费者工作函数
        Args:
            worker_id: 工作线程ID
        """
        print(f"DEBUG: 工作线程 #{worker_id} 进入主循环")
        while self._queue_running:
            try:
                # print(f"DEBUG: 工作线程 #{worker_id} 等待任务...")
                # 从队列中获取文件路径，超时1秒
                file_path = self._upload_queue.get(timeout=1)
                if file_path is None:  # 退出信号
                    self._upload_queue.task_done()
                    print(f"DEBUG: 工作线程 #{worker_id} 收到退出信号")
                    break

                print(f"DEBUG: 工作线程 #{worker_id} 获取到任务: {file_path}")

                # 显示队列状态
                queue_size = self._upload_queue.qsize()
                console_log(f"\n{'='*80}")
                console_log(f"📋 工作线程 #{worker_id} 开始处理任务")
                console_log(f"当前任务: {os.path.basename(file_path)}")
                console_log(f"剩余任务: {queue_size}")
                console_log(f"{'='*80}")

                try:
                    self._process_file_internal(file_path, worker_id)
                except Exception as e:
                    self.logger.error(
                        f"工作线程 #{worker_id} 处理文件失败: {file_path}, 错误: {e}"
                    )
                finally:
                    # 清理状态（不持有锁，避免阻塞其他线程）
                    self._queued_files.discard(file_path)
                    self._processing_files.discard(file_path)

                    self._upload_queue.task_done()
                    # 显式垃圾回收
                    import gc

                    gc.collect()

            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"工作线程 #{worker_id} 发生未捕获异常: {e}")

    def _upload_file_from_queue(self, file_path, matched_item_type, matched_item_id):
        """
        从队列中上传文件

        Args:
            file_path: 文件路径
            matched_item_type: 项目类型
            matched_item_id: 项目ID
        """
        # 检查文件是否已经在上传中或已上传
        if file_path in self._uploading_files or file_path in self._uploaded_files:
            self.logger.debug(f"文件已在上传中或已上传，跳过: {file_path}")
            return

        # 添加到上传中集合
        self._uploading_files.add(file_path)

        try:
            # 使用增强版上传器
            console_log(f"\n{'='*80}")
            console_log(f"📤 开始上传视频")
            console_log(f"文件: {file_path}")
            console_log(f"类型: {matched_item_type}")
            console_log(f"项目ID: {matched_item_id}")
            console_log(f"{'='*80}\n")
            uploader = RobustEmosVideoUploader(
                self.emos_auth_token, chunk_size_mb=int(self.emos_chunk_size_mb)
            )
            upload_result = uploader.upload_video(
                file_path,
                matched_item_type,
                str(matched_item_id),
                self.emos_file_storage,
            )

            if upload_result:
                console_log(f"\n🎉 视频上传成功!")
                # 从上传中集合移除，添加到已上传集合
                self._uploaded_files.add(file_path)
                record_task(file_path, "completed", end_time=datetime.now())

                # 如果配置了上传后删除文件，执行删除操作
                if self.delete_after_upload:
                    try:
                        # 1. 先暂停下载器中的种子，提前释放文件句柄
                        self._release_file_lock_via_downloader(file_path)

                        # 2. 再从下载器中强制删除任务
                        task_removed = self._force_cleanup_download_task(file_path)

                        if task_removed:
                            # 任务已删除，等待一段时间让下载器完全释放文件
                            import time

                            time.sleep(3.0)

                            # 3. 然后尝试删除文件 (文件可能已被下载器删除)
                            delete_success = False
                            max_retries = 5
                            retry_delay = 3.0

                            for attempt in range(max_retries):
                                try:
                                    if os.path.exists(file_path):
                                        os.remove(file_path)
                                        delete_success = True
                                        console_log(f"✅ 上传成功后已删除原文件: {file_path}")
                                        self.logger.info(
                                            f"上传成功后已删除原文件: {file_path}"
                                        )
                                        break
                                    else:
                                        # 文件已不存在，视为删除成功
                                        delete_success = True
                                        console_log(f"⚠️ 上传成功后原文件已不存在: {file_path}")
                                        self.logger.info(
                                            f"上传成功后原文件已不存在: {file_path}"
                                        )
                                        break
                                except (PermissionError, OSError) as e:
                                    # WinError 32 (ERROR_SHARING_VIOLATION) - 文件被另一个程序占用
                                    if attempt < max_retries - 1:
                                        error_code = (
                                            e.winerror
                                            if hasattr(e, "winerror")
                                            else e.errno
                                        )
                                        self.logger.warning(
                                            f"文件被占用 ({error_code})，{retry_delay}秒后重试: {e}"
                                        )
                                        time.sleep(retry_delay)
                                    else:
                                        self.logger.error(
                                            f"删除原文件失败，已从下载器清理，启动后台重试: {file_path}, 错误: {e}"
                                        )
                                        self._delete_file_with_background_retry(file_path)
                        else:
                            # 任务未删除（种子中还有其他视频），跳过文件删除
                            self.logger.info(
                                f"种子中还有其他视频未处理，跳过文件删除: {file_path}"
                            )
                    except Exception as e:
                        console_log(f"❌ 上传成功后删除原文件失败: {e}")
                        self.logger.error(
                            f"上传成功后删除原文件失败: {file_path}, 错误: {e}"
                        )
            else:
                console_log(f"\n❌ 视频上传失败!")
        except Exception as e:
            console_log(f"\n❌ 视频上传过程中发生错误: {e}")
        finally:
            # 无论上传结果如何，从上传中集合移除
            self._uploading_files.remove(file_path)

    def _process_file(self, file_path: str) -> bool:
        """
        处理视频或字幕文件

        Args:
            file_path: 文件路径
        """
        if not os.path.exists(file_path):
            self.logger.warning(f"文件不存在: {file_path}")
            return False

        # 检查文件类型
        is_subtitle = self._is_subtitle_file(file_path)
        is_video = self._is_video_file(file_path)

        if not is_subtitle and not is_video:
            self.logger.debug(f"文件不是支持的视频或字幕文件，跳过: {file_path}")
            return False

        # 对于字幕文件，使用特殊的处理逻辑
        if is_subtitle:
            return self._process_subtitle_file(file_path)

        # 快速检查：文件是否已经在上传中或已上传（不加锁，因为这些集合只在主线程修改）
        if file_path in self._uploading_files or file_path in self._uploaded_files:
            self.logger.debug(f"文件已在上传中或已上传，跳过处理: {file_path}")
            return True

        # 使用锁保护去重检查，防止竞态条件
        with self._queue_lock:
            # 检查文件是否正在处理中（API调用阶段）
            if file_path in self._processing_files:
                self.logger.debug(f"文件正在处理中，跳过: {file_path}")
                return True

            # 检查文件是否已在队列中
            if file_path in self._queued_files:
                self.logger.debug(f"文件已在队列中，跳过重复添加: {file_path}")
                return True

            # 立即标记为处理中并添加到队列追踪集合（在锁内完成）
            self._processing_files.add(file_path)
            self._queued_files.add(file_path)

        # 检查文件是否完整且可访问（在锁外进行，避免阻塞其他线程）
        if not self._is_file_complete(file_path):
            self.logger.debug(f"文件未完成或被锁定，跳过处理: {file_path}")
            # 清理状态
            with self._queue_lock:
                self._processing_files.discard(file_path)
                self._queued_files.discard(file_path)
            # 如果有父监控器，可以将文件添加到重试队列
            if self._parent_monitor:
                self._parent_monitor._pending_files.add(file_path)
            return False

        if self._use_queue:
            # 放入队列异步处理
            self._upload_queue.put(file_path)

            queue_size = self._upload_queue.qsize()
            console_log(f"\n✅ 已加入处理队列: {os.path.basename(file_path)}")
            console_log(f"   当前队列长度: {queue_size}")
            console_log(f"   工作线程数: {self.max_upload_workers}")

            return True
        else:
            # 同步直接处理
            return self._process_file_internal(file_path)

    def _process_file_internal(self, file_path, worker_id=0):
        """
        内部文件处理逻辑（包含元数据获取、API调用、上传）
        """
        console_log(f"\n🔍 [线程#{worker_id}] 开始深入处理文件: {file_path}")

        try:
            # 第一步：获取视频的tmdbid和media_type (使用本地 Renamer + TMDB Client)
            print(f"正在本地分析文件元数据: {os.path.basename(file_path)}")

            # 使用 VideoRenamer 提取元数据 (包含 Regex 解析和 TMDB 搜索)
            # 注意: 这里使用 extract_metadata 会自动调用 _enrich_with_tmdb
            metadata = self.renamer.extract_metadata(file_path)

            # 打印综合识别结果（类似 --comprehensive 模式）
            console_log(f"✓ [线程#{worker_id}] 本地识别完成")
            important_fields = [
                "show_name",
                "title",
                "tmdb_id",
                "media_type",
                "season",
                "episode",
                "year",
                "quality_tags",
                "release_group",
            ]
            for field in important_fields:
                value = metadata.get(field)
                if value:
                    print(f"  [{worker_id}] {field}: {value}")

            # 提取所需信息
            tmdb_id = str(metadata.get("tmdb_id", ""))

            # 检查是否成功获取到 TMDB ID
            if not tmdb_id or tmdb_id == "":
                console_log(f"\n❌ [线程#{worker_id}] 未找到 TMDB 匹配结果")
                tmdb_request_failed = bool(
                    self.renamer.tmdb_client
                    and getattr(self.renamer.tmdb_client, "last_request_failed", False)
                )
                if tmdb_request_failed:
                    error_msg = getattr(self.renamer.tmdb_client, "last_request_error", None)
                    reason = f"TMDB请求失败: {error_msg}" if error_msg else "TMDB请求失败"
                    console_log(f"⚠️  TMDB 请求异常，文件将加入自动重试: {reason}")
                    self._failed_files[file_path] = reason
                    record_task(file_path, "failed", error_message=reason, end_time=datetime.now())
                    if self._parent_monitor:
                        self._parent_monitor._retry_files.add(file_path)
                else:
                    console_log(f"⚠️  建议：请手动处理该文件或确认文件名是否正确")
                    console_log(f"⚠️  文件将跳过上传，等待手动处理\n")
                    # 记录失败原因，但不标记为已上传（以便后续可以重试）
                    self._failed_files[file_path] = "未找到 TMDB 匹配结果"
                    record_task(file_path, "failed", error_message="未找到 TMDB 匹配结果", end_time=datetime.now())
                self._uploading_files.discard(file_path)
                return False
            media_type = metadata.get(
                "media_type", "tv"
            )  # 默认为 tv, renamer 会返回 'tv' 或 'movie'

            # 标题处理：优先使用 title (电影) 或 show_name (剧集)
            title = (
                metadata.get("title")
                or metadata.get("show_name")
                or metadata.get("original_filename", "")
            )

            # 季集信息处理
            season = metadata.get("season")
            episode = metadata.get("episode")
            season_episode = ""

            # 添加特别篇检测逻辑，与renamer.py中的generate_new_path方法保持一致
            if season is None or episode is None:
                # 检查文件名是否包含特别篇标识
                filename = os.path.basename(file_path)
                special_keywords = [
                    "OVA",
                    "SP",
                    "Special",
                    "特别篇",
                    "番外篇",
                    "OVA01",
                    "OVA02",
                    "OVA03",
                    "OVA04",
                    "OVA05",
                    "OVA06",
                    "OVA07",
                    "OVA08",
                    "OVA09",
                    "OVA10",
                ]
                filename_upper = filename.upper()
                for keyword in special_keywords:
                    if keyword in filename_upper:
                        # 如果是特别篇，设置季数为0，集数从文件名提取
                        season = 0
                        # 尝试从文件名提取集数
                        import re

                        episode_match = re.search(r"(?:OVA|SP)(\d+)", filename_upper)
                        if episode_match:
                            episode = episode_match.group(1)
                        break
                if season is None or episode is None:
                    season = 1
                    episode = 1

            if season is not None and episode is not None:
                try:
                    # 尝试格式化为 SxxExx
                    s_num = int(season)
                    e_num = int(episode)
                    season_episode = f"S{s_num:02d}E{e_num:02d}"
                except:
                    # 如果转换整数失败，直接拼接
                    season_episode = f"S{season}E{episode}"
            else:
                # 如果季集信息缺失，保持为空字符串
                season_episode = ""

            # 输出获取到的信息
            console_log(f"\n[线程#{worker_id}] 文件信息 (本地识别):")
            print(f"  文件: {os.path.basename(file_path)}")
            print(f"  TMDB ID: {tmdb_id}")
            print(f"  媒体类型: {media_type}")
            print(f"  标题: {title}")
            print(f"  季集: {season_episode}")

            # 兼容性处理: 原有逻辑可能依赖 "电视剧" 这样的中文类型，但 Renamer 返回 "tv"/"movie"
            # 下面的逻辑原本是: media_type = "tv" if media_type == "电视剧" else "movie"
            # 现在 renamer 直接返回标准代码，所以我们只需确保它是 tv 或 movie
            if media_type not in ["tv", "movie"]:
                # 如果是 anime 或其他，归类为 tv
                media_type = "tv"

            # 初始化匹配结果
            matched_item_id = None
            matched_item_type = None

            # 第二步：如果获取到了tmdb_id、type、title，且需要上传到 Emos，调用API获取item_id
            # 只有 upload_targets 包含 emos 时才需要获取 item_id
            needs_emos_item = "emos" in self.upload_targets
            if tmdb_id and media_type and title and needs_emos_item:
                # 构建动态 URL，使用实际的 tmdb_id, season, episode
                try:
                    season_num = int(season) if season else 1
                except (ValueError, TypeError):
                    season_num = 1
                try:
                    episode_num = int(episode) if episode else 1
                except (ValueError, TypeError):
                    episode_num = 1
                if media_type == "tv":
                    item_id_url = (
                        f"{self.emos_base_url}/api/video/getVideoId"
                        f"?video_id_type=tmdb"
                        f"&season_number={season_num}"
                        f"&episode_number={episode_num}"
                        f"&tmdb_type=tv"
                        f"&video_id_value={tmdb_id}"
                    )
                else:
                    item_id_url = (
                        f"{self.emos_base_url}/api/video/getVideoId"
                        f"?video_id_type=tmdb"
                        f"&tmdb_type=movie"
                        f"&video_id_value={tmdb_id}"
                    )

                print(f"[线程#{worker_id}] 正在请求 Emos API: {item_id_url}")

                # 定义 Emos API headers
                headers = {
                    "accept": "*/*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "authorization": f"Bearer {self.emos_auth_token}",
                    "origin": "https://emos.prlo.de",
                    "priority": "u=1, i",
                    "referer": "https://emos.prlo.de/",
                    "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "cross-site",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                }

                # 发送请求
                response2 = requests.get(item_id_url, headers=headers, timeout=30)
                response2.raise_for_status()
                result2 = response2.json()

                print(f"[线程#{worker_id}] Emos API 返回: {result2}")

                # 解析返回结果（新版格式：直接包含 season_info 和 episode_info）
                if result2:
                    # 检查是否是电视剧
                    if result2.get("video_type") == "tv":
                        # 直接从返回结果中获取季集信息
                        season_info = result2.get("season_info", {})
                        episode_info = result2.get("episode_info", {})

                        if season_info and episode_info:
                            matched_item_id = episode_info.get("item_id")
                            matched_item_type = episode_info.get("item_type")
                            print(
                                f"[线程#{worker_id}] 剧集匹配成功！"
                                f"item_id: {matched_item_id}, "
                                f"item_type: {matched_item_type}, "
                                f"集标题: {episode_info.get('episode_title')}"
                            )
                        # elif result2.get("item_id"):
                        #     # 如果没有 season_info/episode_info，资源有问题跳过
                        #     # matched_item_id = result2.get("item_id")
                        #     # matched_item_type = result2.get("item_type")
                        #     print(
                        #         f"[线程#{worker_id}] 使用顶层 item_id: {matched_item_id}"
                        #     )

                    elif result2.get("video_type") == "movie" and result2.get("item_id"):
                        matched_item_id = result2.get("item_id")
                        matched_item_type = result2.get("item_type")
                        console_log(f"[线程#{worker_id}] 电影匹配成功！item_id: {matched_item_id}")

                # if not matched_item_id:
                #     console_log(f"✗ [线程#{worker_id}] 未找到匹配的item_id")

            # 步骤4：决定是否需要上传
            # 如果只上传到123云盘、天翼云盘或139云盘（不包含 emos），不需要 item_id，可以直接上传
            if "emos" not in self.upload_targets and len(self.upload_targets) > 0:
                # 只上传到 p123、cloud189 或 yun139，不需要 Emos 的 item_id
                console_log(f"✓ [线程#{worker_id}] 配置为上传到 {self.upload_targets}，跳过Emos匹配")
                self._execute_upload(
                    file_path,
                    media_type,
                    None,
                    worker_id,
                    tmdb_id,
                    media_type,
                    title,
                    season_episode,
                    metadata,
                )
            elif matched_item_id:
                console_log(f"✓ [线程#{worker_id}] 找到匹配的item_id: {matched_item_id}")
                # 需要上传到 Emos 或两者，必须有 item_id
                self._execute_upload(
                    file_path,
                    matched_item_type,
                    matched_item_id,
                    worker_id,
                    tmdb_id,
                    media_type,
                    title,
                    season_episode,
                    metadata,
                )
            else:
                # 需要 Emos 但没有 item_id
                self._failed_files[file_path] = "未找到匹配的item_id"
                record_task(file_path, "failed", error_message="未找到匹配的item_id", end_time=datetime.now())
                log_success(
                    self.logger,
                    "文件元数据获取成功但未匹配到item_id",
                    {
                        "original_path": file_path,
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "title": title,
                        "season_episode": season_episode,
                    },
                )
            # else:
            #     print(f"\n[线程#{worker_id}] 跳过第二个API请求：缺少必要参数")
            #     # 记录结果
            #     log_success(self.logger, "文件元数据获取成功但跳过API请求", {
            #         "original_path": file_path, "tmdb_id": tmdb_id, "media_type": media_type,
            #         "title": title, "season_episode": season_episode
            #     })

            return True

        except KeyboardInterrupt:
            # 让键盘中断正常传播
            raise
        except Exception as e:
            log_exception(self.logger, f"获取元数据时发生错误: {file_path}")
            console_log(f"\n✗ API请求失败: {e}")

            # 记录失败原因
            self._failed_files[file_path] = f"API请求失败: {str(e)}"
            record_task(file_path, "failed", error_message=f"API请求失败: {str(e)}", end_time=datetime.now())

            # 如果有父监控器，可以将文件添加到重试队列
            if self._parent_monitor:
                self.logger.info(f"将文件添加到重试队列: {file_path}")
                self._parent_monitor._retry_files.add(file_path)
        finally:
            # 从处理中集合移除
            self._processing_files.discard(file_path)

    def _execute_upload(
        self,
        file_path,
        matched_item_type,
        matched_item_id,
        worker_id,
        tmdb_id,
        media_type,
        title,
        season_episode,
        metadata,
    ):
        """执行具体的上传操作（支持多云盘）"""
        console_log(f"\n=== [线程#{worker_id}] 开始上传视频 ===")

        # 检查文件是否已经上传完成
        if file_path in self._uploaded_files:
            console_log(f"✗ [线程#{worker_id}] 文件已上传完成，跳过: {file_path}")
            return

        # 添加到上传中集合
        self._uploading_files.add(file_path)

        # 准备媒体信息（用于123云盘创建文件夹）
        media_info = {
            "title": title,
            "season_episode": season_episode,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
        }

        # 根据配置决定上传到哪些云盘
        upload_results = {}

        try:
            # 1. 上传到 Emos
            if "emos" in self.upload_targets:
                print(f"\n{'='*60}")
                console_log(f"📤 [线程#{worker_id}] 上传到 Emos")
                print(f"类型: {matched_item_type}")
                print(f"项目ID: {matched_item_id}")
                print(f"{'='*60}\n")

                if not self.emos_auth_token:
                    console_log(f"✗ [线程#{worker_id}] 未配置Emos认证令牌，跳过Emos上传")
                    upload_results["emos"] = None
                else:
                    try:
                        from ..upload.upload_emos import RobustEmosVideoUploader

                        uploader = RobustEmosVideoUploader(
                            self.emos_auth_token,
                            chunk_size_mb=int(self.emos_chunk_size_mb),
                            telegram_config=self.telegram_config,
                        )
                        upload_results["emos"] = uploader.upload_video(
                            file_path,
                            matched_item_type,
                            str(matched_item_id),
                            self.emos_file_storage,
                        )

                        if upload_results["emos"]:
                            console_log(f"\n🎉 [线程#{worker_id}] Emos上传成功!")
                        else:
                            console_log(f"\n❌ [线程#{worker_id}] Emos上传失败!")
                    except Exception as e:
                        console_log(f"\n❌ [线程#{worker_id}] Emos上传异常: {e}")
                        upload_results["emos"] = None

            # 2. 上传到 123云盘
            if "p123" in self.upload_targets:
                print(f"\n{'='*60}")
                console_log(f"📤 [线程#{worker_id}] 上传到 123云盘")
                print(f"{'='*60}\n")

                if not self.p123_token:
                    console_log(f"✗ [线程#{worker_id}] 未配置123云盘Token，跳过123上传")
                    upload_results["p123"] = None
                else:
                    try:
                        # 确保上传器已初始化
                        uploader = self.p123_uploader
                        if not uploader:
                            # 兜底：如果初始化失败，尝试在此重新初始化
                            from ..upload.upload_p123 import P123Uploader

                            uploader = P123Uploader(
                                self.p123_token,
                                self.p123_parent_id,
                                telegram_config=self.telegram_config,
                            )

                        # 生成标准化路径（包含文件夹结构和新文件名）
                        # 例如: Show Name (2023) {tmdbid=123}/Season 01/Show Name S01E01.mkv
                        try:
                            # 复用本函数开头已经提取好的 metadata
                            renamed_relative_path = self.renamer.generate_new_path(
                                metadata, original_path=file_path
                            )

                            # 获取重命名后的文件名
                            target_filename = renamed_relative_path.name

                            # 获取目录结构列表
                            folder_parts = list(renamed_relative_path.parent.parts)

                            # 构建完整目录结构（直接使用generate_new_path返回的分类结构）
                            base_folders = ["media"]

                            # 合并目录结构
                            folder_structure = base_folders + folder_parts

                            print(
                                f"[线程#{worker_id}] 标准化重命名计划: {os.path.basename(file_path)} -> {renamed_relative_path}"
                            )
                            print(
                                f"[线程#{worker_id}] 网盘目录结构: {' -> '.join(folder_structure)}"
                            )

                        except Exception as e:
                            print(f"生成标准化路径失败: {e}，使用默认命名")
                            target_filename = os.path.basename(file_path)
                            folder_structure = None

                        upload_results["p123"] = uploader.upload_video(
                            file_path,
                            media_type,
                            str(matched_item_id),
                            None,
                            media_info,
                            rename_to=target_filename,
                            folder_structure=folder_structure,
                        )

                        if upload_results["p123"]:
                            console_log(f"\n🎉 [线程#{worker_id}] 123云盘上传成功!")
                        else:
                            console_log(f"\n❌ [线程#{worker_id}] 123云盘上传失败!")
                    except Exception as e:
                        console_log(f"\n❌ [线程#{worker_id}] 123云盘上传异常: {e}")
                        import traceback

                        traceback.print_exc()
                        upload_results["p123"] = None

            # 3. 上传到天翼云盘
            if "cloud189" in self.upload_targets:
                print(f"\n{'='*60}")
                console_log(f"📤 [线程#{worker_id}] 上传到天翼云盘")
                print(f"{'='*60}\n")

                if not self.cloud189_uploader:
                    console_log(f"✗ [线程#{worker_id}] 未配置天翼云盘，跳过上传")
                    upload_results["cloud189"] = None
                else:
                    try:
                        # 生成标准化路径
                        try:
                            renamed_relative_path = self.renamer.generate_new_path(
                                metadata, original_path=file_path
                            )
                            target_filename = renamed_relative_path.name
                            folder_parts = list(renamed_relative_path.parent.parts)
                            base_folders = ["media"]
                            folder_structure = base_folders + folder_parts
                            print(
                                f"[线程#{worker_id}] 标准化重命名计划: {os.path.basename(file_path)} -> {renamed_relative_path}"
                            )
                        except Exception as e:
                            print(f"生成标准化路径失败: {e}，使用默认命名")
                            target_filename = os.path.basename(file_path)
                            folder_structure = None

                        # 获取剧名/电影名
                        show_name = title
                        season = metadata.get("season")
                        episode = metadata.get("episode")

                        upload_results["cloud189"] = self.cloud189_uploader.upload_video(
                            file_path,
                            show_name=show_name,
                            season=season,
                            episode=episode,
                            media_type=media_type,
                            folder_structure=folder_structure,
                            rename_to=target_filename,
                        )

                        if upload_results["cloud189"]:
                            console_log(f"\n🎉 [线程#{worker_id}] 天翼云盘上传成功!")

                            # 生成 .cas 文件（用于 189 云盘秒传校验）
                            if self.cloud189_generate_cas and folder_structure and target_filename:
                                try:
                                    result = upload_results["cloud189"]
                                    cas_data = {
                                        "md5": result.get("file_md5", ""),
                                        "sliceMD5": result.get("slice_md5", ""),
                                        "size": result.get("file_size", 0),
                                        "name": target_filename,
                                        "cloud": "189",
                                    }
                                    cas_content = base64.b64encode(
                                        json.dumps(cas_data, ensure_ascii=False).encode("utf-8")
                                    ).decode("utf-8")

                                    if self.cloud189_cas_output_dir:
                                        cas_dir = Path(self.cloud189_cas_output_dir)
                                    else:
                                        cas_dir = Path(sys.argv[0]).resolve().parent / "cas"
                                    cas_dir = cas_dir / renamed_relative_path.parent
                                    cas_dir.mkdir(parents=True, exist_ok=True)
                                    cas_file = cas_dir / f"{target_filename}.cas"
                                    cas_file.write_text(cas_content, encoding="utf-8")
                                    console_log(f"📄 [线程#{worker_id}] 已生成 .cas 文件: {cas_file}")

                                    # 上传 .cas 文件到外部 API
                                    if self.cloud189_cas_upload_url and self.cloud189_cas_upload_api_key:
                                        _upload_cas_file(cas_file, cas_data, self.cloud189_cas_upload_url, self.cloud189_cas_upload_api_key, str(renamed_relative_path.parent))
                                except Exception as cas_e:
                                    console_log(f"⚠️ [线程#{worker_id}] 生成 .cas 文件失败: {cas_e}")

                            # 上传成功后清空回收站
                            if self.cloud189_empty_recycle_bin:
                                try:
                                    console_log(f"🗑️ [线程#{worker_id}] 清空天翼云盘回收站...")
                                    recycle_result = self.cloud189_uploader.client.empty_recycle(
                                        familyId=self.cloud189_family_id
                                    )
                                    if recycle_result.get("res_code") == 0:
                                        console_log(f"✓ [线程#{worker_id}] 回收站已清空")
                                    else:
                                        console_log(f"⚠️ [线程#{worker_id}] 清空回收站失败: {recycle_result.get('res_message', 'Unknown')}")
                                except Exception as e:
                                    console_log(f"⚠️ [线程#{worker_id}] 清空回收站异常: {e}")
                        else:
                            console_log(f"\n❌ [线程#{worker_id}] 天翼云盘上传失败!")
                    except Exception as e:
                        console_log(f"\n❌ [线程#{worker_id}] 天翼云盘上传异常: {e}")
                        import traceback

                        traceback.print_exc()
                        upload_results["cloud189"] = None

            # 4. 上传到139云盘
            if "yun139" in self.upload_targets:
                print(f"\n{'='*60}")
                console_log(f"📤 [线程#{worker_id}] 上传到 139云盘")
                print(f"{'='*60}\n")

                if not self.yun139_uploader:
                    console_log(f"✗ [线程#{worker_id}] 未配置139云盘，跳过上传")
                    upload_results["yun139"] = None
                else:
                    try:
                        # 生成标准化路径
                        try:
                            renamed_relative_path = self.renamer.generate_new_path(
                                metadata, original_path=file_path
                            )
                            target_filename = renamed_relative_path.name
                            folder_parts = list(renamed_relative_path.parent.parts)
                            base_folders = ["media"]
                            folder_structure = base_folders + folder_parts
                            print(
                                f"[线程#{worker_id}] 标准化重命名计划: {os.path.basename(file_path)} -> {renamed_relative_path}"
                            )
                        except Exception as e:
                            print(f"生成标准化路径失败: {e}，使用默认命名")
                            target_filename = os.path.basename(file_path)
                            folder_structure = None

                        upload_results["yun139"] = self.yun139_uploader.upload_video(
                            file_path,
                            media_type,
                            str(matched_item_id),
                            None,
                            media_info,
                            rename_to=target_filename,
                            folder_structure=folder_structure,
                        )

                        if upload_results["yun139"]:
                            console_log(f"\n🎉 [线程#{worker_id}] 139云盘上传成功!")
                        else:
                            console_log(f"\n❌ [线程#{worker_id}] 139云盘上传失败!")
                    except Exception as e:
                        console_log(f"\n❌ [线程#{worker_id}] 139云盘上传异常: {e}")
                        import traceback

                        traceback.print_exc()
                        upload_results["yun139"] = None

            # 5. 判断是否所有目标云盘都上传成功
            required_targets = self.upload_targets  # 现在是列表格式

            # 检查所有必需的上传是否都成功
            all_success = all(
                upload_results.get(target) is not None for target in required_targets
            )

            if all_success:
                console_log(f"\n🎉 [线程#{worker_id}] 所有云盘上传成功!")
                # 从上传中集合移除，添加到已上传集合
                self._uploaded_files.add(file_path)
                record_task(file_path, "completed", end_time=datetime.now())
                self._uploading_files.discard(file_path)

                # 执行 emya 数据库入库（如果启用）
                emya_import_result = None
                if self.emya_enabled and self.emya_controller:
                    try:
                        print(f"\n{'='*60}")
                        console_log(f"📥 [线程#{worker_id}] 开始 emya 数据库入库")
                        print(f"{'='*60}\n")

                        # 获取媒体 URL
                        media_url = None
                        if upload_results.get("emos"):
                            media_url = upload_results["emos"].get("url") or upload_results["emos"].get("media_uuid")
                        elif upload_results.get("p123"):
                            media_url = upload_results["p123"].get("url") or upload_results["p123"].get("fileid")
                        elif upload_results.get("cloud189"):
                            media_url = upload_results["cloud189"].get("url") or upload_results["cloud189"].get("file_id")
                        elif upload_results.get("yun139"):
                            media_url = upload_results["yun139"].get("url") or upload_results["yun139"].get("file_id")

                        if media_url:
                            # 构建入库元数据
                            import_metadata = {
                                "show_name": title,
                                "title": title,
                                "tmdb_id": int(tmdb_id) if tmdb_id else None,
                                "media_type": media_type,
                                "season": metadata.get("season"),
                                "episode": metadata.get("episode"),
                                "year": metadata.get("year"),
                                "quality_tags": metadata.get("quality_tags"),
                                "release_group": metadata.get("release_group"),
                                "runtime": metadata.get("runtime"),
                                # 使用 overview 作为 description
                                "description": metadata.get("overview") or metadata.get("description"),
                                "poster_path": metadata.get("poster_path"),
                                "backdrop_path": metadata.get("backdrop_path"),
                                "genres": metadata.get("genres"),
                                "origin_country": metadata.get("origin_country"),
                                "vote_average": metadata.get("rating") or metadata.get("vote_average"),
                                # 添加原始标题
                                "origin_title": metadata.get("original_name") or metadata.get("original_title"),
                                # 添加演员和导演信息
                                "peoples": {
                                    "cast": metadata.get("cast", []),
                                    "crew": metadata.get("crew", []),
                                },
                                # 添加剧集详细信息
                                "episode_title": metadata.get("episode_name"),
                                "still_path": metadata.get("still_path"),
                                "air_date": metadata.get("air_date"),
                                # 添加季信息（包含季海报）
                                "seasons_info": metadata.get("seasons_info", []),
                                # 文件信息
                                "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else None,
                                "container": os.path.splitext(file_path)[1].lstrip('.'),
                            }

                            # 获取或创建默认媒体库
                            from .emya_models import VideoType
                            library_name = (
                                self.emya_db_config.get("default_tv_library", "电视剧")
                                if media_type == VideoType.TV
                                else self.emya_db_config.get("default_movie_library", "电影")
                            )

                            # 执行入库
                            result = self.emya_controller.import_from_metadata(
                                metadata=import_metadata,
                                library_id=0,  # 0 表示自动创建/获取默认媒体库
                                media_url=str(media_url),
                            )

                            if result.success:
                                emya_import_result = result.data
                                console_log(f"✅ [线程#{worker_id}] emya 入库成功!")
                                print(f"   视频ID: {result.data.get('video_id')}")
                                self.logger.info(f"emya 入库成功: {result.data}")
                            else:
                                console_log(f"❌ [线程#{worker_id}] emya 入库失败: {result.message}")
                                self.logger.warning(f"emya 入库失败: {result.message}")
                        else:
                            console_log(f"⚠️ [线程#{worker_id}] 未获取到媒体URL，跳过 emya 入库")
                            self.logger.warning("未获取到媒体URL，跳过 emya 入库")

                    except Exception as e:
                        console_log(f"❌ [线程#{worker_id}] emya 入库异常: {e}")
                        self.logger.error(f"emya 入库异常: {e}")

                # 如果配置了上传后删除文件，执行删除操作
                deleted = False
                if self.delete_after_upload:
                    try:
                        # 尝试从下载器中删除任务
                        #   每次调用都会标记当前文件已上传完成
                        #   qB 会在种子内所有视频都上传完后自动 deleteFiles=true
                        task_removed = self._cleanup_download_task(file_path)

                        if task_removed:
                            deleted = True
                            print(
                                f"✅ [线程#{worker_id}] 下载任务已从下载器中删除"
                            )
                            self.logger.info(
                                f"下载任务已从下载器中删除: {file_path}"
                            )

                            # 兜底：某些下载器（如 aria2）只删任务记录不删文件
                            if os.path.exists(file_path):
                                console_log(
                                    f"📁 [线程#{worker_id}] 文件仍存在，执行兜底删除"
                                )
                                self._delete_file_with_background_retry(file_path)
                        else:
                            self.logger.info(
                                f"[线程#{worker_id}] 下载器中仍有未完成的任务，文件暂不删除"
                            )
                    except Exception as e:
                        console_log(f"❌ [线程#{worker_id}] 删除任务失败: {e}")
                        self.logger.error(f"删除任务失败: {file_path}, 错误: {e}")

                # 更新日志
                log_success(
                    self.logger,
                    "文件元数据获取并上传成功",
                    {
                        "original_path": file_path,
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "title": title,
                        "season_episode": season_episode,
                        "matched_item_id": matched_item_id,
                        "upload_success": True,
                        "upload_targets": self.upload_targets,
                        "emos_uuid": (
                            upload_results.get("emos", {}).get("media_uuid")
                            if upload_results.get("emos")
                            else None
                        ),
                        "p123_fileid": (
                            upload_results.get("p123", {}).get("fileid")
                            if upload_results.get("p123")
                            else None
                        ),
                        "deleted_after_upload": deleted,
                    },
                )

                # 清理旧记录防止内存泄露
                self._cleanup_old_records()

            else:
                # 部分上传失败
                failed_targets = [
                    t for t in required_targets if not upload_results.get(t)
                ]
                print(
                    f"\n❌ [线程#{worker_id}] 部分云盘上传失败: {', '.join(failed_targets)}"
                )
                console_log(f"⚠️  [线程#{worker_id}] 保留本地文件，等待重试或手动处理")
                self._uploading_files.discard(file_path)
                # 记录失败原因，以便 Web UI 显示和重试
                self._failed_files[file_path] = f"部分云盘上传失败: {', '.join(failed_targets)}"
                record_task(file_path, "failed", error_message=f"部分云盘上传失败: {', '.join(failed_targets)}", end_time=datetime.now())
                # 加入重试队列，自动重试
                if self._parent_monitor:
                    self._parent_monitor._retry_files.add(file_path)
                log_success(
                    self.logger,
                    "文件元数据获取成功但部分云盘上传失败",
                    {
                        "original_path": file_path,
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "title": title,
                        "season_episode": season_episode,
                        "matched_item_id": matched_item_id,
                        "upload_success": False,
                        "failed_targets": failed_targets,
                    },
                )
        except Exception as e:
            console_log(f"\n❌ [线程#{worker_id}] 视频上传错误: {e}")
            self._uploading_files.discard(file_path)
            # 记录失败原因，以便 Web UI 显示和重试
            self._failed_files[file_path] = f"上传异常: {str(e)}"
            record_task(file_path, "failed", error_message=f"上传异常: {str(e)}", end_time=datetime.now())
            # 加入重试队列，自动重试
            if self._parent_monitor:
                self._parent_monitor._retry_files.add(file_path)
            log_success(
                self.logger,
                "文件元数据获取成功但上传出错",
                {
                    "original_path": file_path,
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "title": title,
                    "season_episode": season_episode,
                    "matched_item_id": matched_item_id,
                    "upload_success": False,
                    "error": str(e),
                },
            )

    def force_process_file(self, file_path: str) -> bool:
        """
        强制处理文件

        Args:
            file_path: 文件路径

        Returns:
            是否处理成功
        """
        try:
            if not os.path.exists(file_path):
                log_failure(self.logger, f"文件不存在: {file_path}")
                return False
        except Exception as e:
            log_failure(self.logger, f"检查文件是否存在时出错: {file_path}", error=e)
            return False

        print(f"检测到文件: {file_path}")

        # 即使文件已上传，强制模式可能希望重试，所以我们尝试从已上传集合中移除它
        if file_path in self._uploaded_files:
            self._uploaded_files.discard(file_path)
            self.logger.info(f"强制处理: 从已上传集合中移除 {file_path}")

        if file_path in self._failed_files:
            del self._failed_files[file_path]
            self.logger.info(f"强制处理: 从失败集合中移除 {file_path}")

        # 使用锁保护去重检查
        with self._queue_lock:
            # 检查文件是否已在队列中，避免重复添加
            if file_path in self._queued_files:
                self.logger.info(f"强制处理: 文件已在队列中，跳过重复添加: {file_path}")
                console_log(f"\n⚠️  文件已在队列中，跳过: {os.path.basename(file_path)}")
                return True

            # 标记为处理中并添加到队列追踪集合
            self._processing_files.add(file_path)
            self._queued_files.add(file_path)

        # 检查文件是否不支持
        if not self._is_supported_file(file_path):
            # 清理状态
            with self._queue_lock:
                self._processing_files.discard(file_path)
                self._queued_files.discard(file_path)
            # log_failure(self.logger, f"不支持的文件类型: {file_path}")
            # return False
            pass

        if self._use_queue:
            # 放入队列异步处理
            self._upload_queue.put(file_path)

            queue_size = self._upload_queue.qsize()
            console_log(f"\n✅ 已加入处理队列: {os.path.basename(file_path)}")
            console_log(f"   当前队列长度: {queue_size}")
            console_log(f"   工作线程数: {self.max_upload_workers}")

            return True
        else:
            # 同步直接处理
            return self._process_file_internal(file_path)

    def stop_upload_queue(self):
        """停止上传队列处理线程"""
        if self._queue_running:
            self._queue_running = False
            # 发送退出信号
            self._upload_queue.put(None)
            # 等待线程结束
            if self._queue_thread and self._queue_thread.is_alive():
                self._queue_thread.join(timeout=5)
            self.logger.info("上传队列处理线程已停止")

    def _reverse_apply_path_mapping(self, file_path: str) -> str:
        """
        反向应用路径映射：将本地文件路径转换为下载器路径

        Args:
            file_path: 本地文件路径

        Returns:
            下载器使用的文件路径
        """
        if not self.path_mappings:
            print("DEBUG: path_mappings 为空，跳过反向映射")
            return file_path

        # 规范化路径分隔符
        file_path = file_path.replace("\\", "/")

        print(f"DEBUG: 尝试反向映射路径: {file_path}")
        print(f"DEBUG: 当前映射配置: {self.path_mappings}")

        for downloader_path, local_path in self.path_mappings.items():
            # 规范化本地映射路径
            local_path = local_path.replace("\\", "/")

            # 如果文件路径以本地映射路径开头
            if file_path.startswith(local_path):
                # 替换为下载器路径
                rel_path = file_path[len(local_path) :].lstrip("/")
                # 拼接下载器路径 (注意 downloader_path 结尾可能有也可能没有 /)
                new_path = f"{downloader_path.rstrip('/')}/{rel_path}"
                self.logger.debug(f"反向路径映射: {file_path} -> {new_path}")
                print(f"DEBUG: 映射成功: {new_path}")
                return new_path

        print(f"DEBUG: 未找到匹配的映射路径")
        return file_path

    def _cleanup_download_task(self, file_path) -> bool:
        """
        从下载器中删除对应的下载任务

        Args:
            file_path: 文件路径 (本地路径)

        Returns:
            bool: 是否成功从下载器中删除了任务
        """
        # 反向映射路径，因为下载器使用的是它自己的路径系统
        downloader_file_path = self._reverse_apply_path_mapping(file_path)
        
        # 解码路径用于查找 _file_downloader_map（因为 map 的 key 是解码形式）
        decoded_file_path = decode_file_path(file_path)
        decoded_downloader_path = decode_file_path(downloader_file_path)

        task_removed = False

        # 1. 尝试从映射中查找下载器（同时尝试编码和解码路径）
        map_key = None
        for key in [file_path, decoded_file_path, downloader_file_path, decoded_downloader_path]:
            if key in self._file_downloader_map:
                map_key = key
                break
        
        if map_key:
            try:
                downloader = self._file_downloader_map[map_key]
                if hasattr(downloader, "remove_download"):
                    # 尝试多种路径格式
                    paths_to_try = [
                        file_path,
                        decoded_file_path,
                        downloader_file_path,
                        decoded_downloader_path
                    ]
                    for path in paths_to_try:
                        if path and downloader.remove_download(path):
                            console_log(f"✅ 已从下载器中删除任务")
                            self.logger.info(f"已从下载器中删除任务: {path}")
                            task_removed = True
                            break
                # 清理映射
                del self._file_downloader_map[map_key]
            except Exception as e:
                self.logger.error(f"从映射的下载器删除任务失败: {e}")

        if task_removed:
            return True

        # 2. 如果映射中没有或删除失败，尝试遍历所有注册的下载器
        # 这在 --process 模式下很有用，因为那时文件可能没有被添加到映射中
        if self.downloaders:
            for downloader in self.downloaders:
                try:
                    if hasattr(downloader, "remove_download"):
                        # 尝试多种路径格式
                        paths_to_try = [
                            downloader_file_path,
                            decoded_downloader_path,
                            file_path,
                            decoded_file_path
                        ]
                        for path in paths_to_try:
                            if path and downloader.remove_download(path):
                                console_log(f"✅ 已从下载器中删除任务 (遍历查找)")
                                self.logger.info(
                                    f"已从下载器中删除任务 (遍历查找): {path}"
                                )
                                return True
                except Exception as e:
                    self.logger.warning(f"尝试从下载器删除任务时出错: {e}")

        console_log(f"⚠️ 未能从下载器删除任务 (未找到匹配任务): {downloader_file_path}")
        self.logger.debug(
            f"未能从下载器删除任务: {file_path} -> {downloader_file_path}"
        )
        return False

    def _force_cleanup_download_task(self, file_path: str) -> bool:
        """
        强制从下载器中删除任务及其文件 (用于文件删除失败时的清理)

        Args:
            file_path: 文件路径 (本地路径)

        Returns:
            bool: 是否成功从下载器中删除了任务
        """
        # 反向映射路径
        downloader_file_path = self._reverse_apply_path_mapping(file_path)
        
        # 解码路径用于查找
        decoded_file_path = decode_file_path(file_path)
        decoded_downloader_path = decode_file_path(downloader_file_path)

        # 1. 首先尝试从映射中查找下载器（同时尝试编码和解码路径）
        map_key = None
        for key in [file_path, decoded_file_path, downloader_file_path, decoded_downloader_path]:
            if key in self._file_downloader_map:
                map_key = key
                break
        
        if map_key:
            try:
                downloader = self._file_downloader_map[map_key]
                if hasattr(downloader, "force_remove_download"):
                    # 尝试多种路径格式
                    paths_to_try = [
                        file_path,
                        decoded_file_path,
                        downloader_file_path,
                        decoded_downloader_path
                    ]
                    for path in paths_to_try:
                        if path and downloader.force_remove_download(path):
                            console_log(f"✅ 已强制从下载器中删除任务及文件")
                            self.logger.info(f"已强制从下载器中删除任务及文件: {path}")
                            del self._file_downloader_map[map_key]
                            return True
            except Exception as e:
                self.logger.error(f"从映射的下载器强制删除失败: {e}")

        # 2. 尝试遍历所有注册的下载器
        if self.downloaders:
            for downloader in self.downloaders:
                try:
                    if hasattr(downloader, "force_remove_download"):
                        paths_to_try = [
                            downloader_file_path,
                            decoded_downloader_path,
                            file_path,
                            decoded_file_path
                        ]
                        for path in paths_to_try:
                            if path and downloader.force_remove_download(path):
                                console_log(f"✅ 已强制从下载器中删除任务及文件 (遍历查找)")
                                self.logger.info(
                                    f"已强制从下载器中删除任务及文件 (遍历查找): {path}"
                                )
                                return True
                except Exception as e:
                    self.logger.warning(f"尝试从下载器强制删除时出错: {e}")

        self.logger.debug(f"未能从下载器强制删除任务: {file_path}")
        return False

    def _process_subtitle_file(self, subtitle_path: str) -> bool:
        """
        处理字幕文件：查找匹配的视频文件并重命名整理

        Args:
            subtitle_path: 字幕文件路径

        Returns:
            是否处理成功
        """
        if not self.subtitle_handler:
            self.logger.warning("字幕处理器未初始化，跳过字幕文件处理")
            return False

        try:
            print(f"\n🎬 发现字幕文件: {os.path.basename(subtitle_path)}")

            # 解析字幕文件信息
            subtitle_info = self.subtitle_handler.parse_subtitle_filename(os.path.basename(subtitle_path))
            language = subtitle_info.get('language', 'Unknown')
            subtitle_type = subtitle_info.get('type', 'Normal')

            print(f"   语言: {language}")
            print(f"   类型: {subtitle_type}")

            # 查找匹配的视频文件
            video_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.wmv')
            video_path = self.subtitle_handler.find_matching_video(Path(subtitle_path), video_extensions)

            if not video_path:
                console_log(f"   ⚠️  未找到匹配的视频文件，跳过处理")
                self.logger.warning(f"未找到匹配的视频文件: {subtitle_path}")
                return False

            console_log(f"   ✓ 找到匹配的视频文件: {os.path.basename(video_path)}")

            # 生成新的字幕文件名
            new_subtitle_name = self.subtitle_handler.generate_subtitle_name(
                video_path.name, subtitle_info
            )
            print(f"   新字幕文件名: {new_subtitle_name}")

            # 查找视频文件的输出目录（如果视频文件已经处理过）
            # 这里我们暂时将字幕文件放在与视频文件相同的目录
            video_dir = video_path.parent
            new_subtitle_path = video_dir / new_subtitle_name

            # 如果目标文件已存在，跳过
            if new_subtitle_path.exists():
                print(f"   ℹ️  目标字幕文件已存在，跳过")
                self.logger.info(f"目标字幕文件已存在: {new_subtitle_path}")
                return True

            # 移动字幕文件
            try:
                import shutil
                shutil.move(subtitle_path, new_subtitle_path)
                console_log(f"   ✅ 字幕文件已移动并重命名")
                self.logger.info(f"字幕文件已处理: {subtitle_path} -> {new_subtitle_path}")
                return True
            except Exception as e:
                console_log(f"   ❌ 移动字幕文件失败: {e}")
                self.logger.error(f"移动字幕文件失败: {subtitle_path} -> {new_subtitle_path}, 错误: {e}")
                return False

        except Exception as e:
            console_log(f"   ❌ 处理字幕文件时出错: {e}")
            self.logger.error(f"处理字幕文件时出错: {subtitle_path}, 错误: {e}")
            return False

    def _release_file_lock_via_downloader(self, file_path: str) -> bool:
        """
        通过暂停下载器中的种子来释放文件句柄

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否成功释放了文件锁
        """
        downloader_file_path = self._reverse_apply_path_mapping(file_path)

        # 1. 首先尝试从映射中查找下载器
        if file_path in self._file_downloader_map:
            try:
                downloader = self._file_downloader_map[file_path]
                if hasattr(downloader, "pause_torrent_for_file"):
                    if downloader.pause_torrent_for_file(file_path) or (
                        file_path != downloader_file_path
                        and downloader.pause_torrent_for_file(downloader_file_path)
                    ):
                        self.logger.info(f"已通过下载器暂停种子释放文件锁: {file_path}")
                        return True
            except Exception as e:
                self.logger.warning(f"通过映射的下载器暂停种子失败: {e}")

        # 2. 尝试遍历所有注册的下载器
        if self.downloaders:
            for downloader in self.downloaders:
                try:
                    if hasattr(downloader, "pause_torrent_for_file"):
                        if downloader.pause_torrent_for_file(downloader_file_path):
                            self.logger.info(
                                f"已通过下载器暂停种子释放文件锁 (遍历): {downloader_file_path}"
                            )
                            return True
                except Exception as e:
                    self.logger.warning(f"尝试暂停种子时出错: {e}")

        return False

    def _delete_file_with_background_retry(
        self, file_path: str, max_retries: int = 20, retry_interval: int = 5
    ) -> bool:
        """
        使用 PowerShell 后台作业持续重试删除文件，即使主进程退出后也能继续

        Args:
            file_path: 文件路径
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）

        Returns:
            bool: 是否成功启动了后台重试
        """
        try:
            ps_script = (
                f'$path = "{file_path}"; '
                f'$maxRetries = {max_retries}; '
                f'$delay = {retry_interval}; '
                "Start-Sleep -Seconds 3; "
                "for($i=0; $i -lt $maxRetries; $i++) { "
                "    if(Test-Path $path) { "
                "        try { "
                "            Remove-Item -LiteralPath $path -Force -ErrorAction Stop; "
                "            exit 0 "
                "        } catch { "
                "            Start-Sleep -Seconds $delay "
                "        } "
                "    } else { "
                "        exit 0 "
                "    } "
                "}; "
                "exit 1"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_script],
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            self.logger.info(f"已启动 PowerShell 后台重试删除文件: {file_path}")
            return True
        except Exception as e:
            self.logger.warning(f"启动 PowerShell 后台重试失败: {e}")
            return False

    def _cleanup_old_records(self):
        """清理旧的处理记录，防止内存溢出"""
        try:
            # 清理已上传文件记录
            if len(self._uploaded_files) > self._max_set_size:
                old_size = len(self._uploaded_files)
                # 保留最近的一半
                self._uploaded_files = set(
                    list(self._uploaded_files)[-(self._max_set_size // 2) :]
                )
                self.logger.info(
                    f"清理已上传文件记录: {old_size} -> {len(self._uploaded_files)}"
                )

            # 清理失败文件记录
            if len(self._failed_files) > self._max_set_size:
                old_size = len(self._failed_files)
                items = list(self._failed_files.items())[-(self._max_set_size // 2) :]
                self._failed_files = dict(items)
                self.logger.info(
                    f"清理失败文件记录: {old_size} -> {len(self._failed_files)}"
                )

            # 清理处理中记录 (防止僵尸记录)
            # 注意：这里需要谨慎，因为正在处理的文件也在这个集合中
            # 一般不需要自动清理，除非确定它已经是僵尸了。这里暂时不自动清理 processing_files
        except Exception as e:
            self.logger.error(f"清理旧记录时出错: {e}")
