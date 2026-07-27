"""
上传模块基类 — 提供进度追踪、缓存管理、Telegram 通知等公共功能
"""

import json
import time
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List, Tuple
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ====== 进度格式化工具 ======

def format_speed(bytes_per_second: float) -> str:
    """格式化上传速度"""
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / 1024 / 1024:.2f} MB/s"
    elif bytes_per_second >= 1024:
        return f"{bytes_per_second / 1024:.2f} KB/s"
    else:
        return f"{bytes_per_second:.2f} B/s"


def format_size(bytes_size: int) -> str:
    """格式化文件大小"""
    if bytes_size >= 1024 * 1024 * 1024:
        return f"{bytes_size / 1024 / 1024 / 1024:.2f} GB"
    elif bytes_size >= 1024 * 1024:
        return f"{bytes_size / 1024 / 1024:.2f} MB"
    elif bytes_size >= 1024:
        return f"{bytes_size / 1024:.2f} KB"
    else:
        return f"{bytes_size} B"


def format_time(seconds: float) -> str:
    """格式化时间"""
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    elif seconds >= 60:
        return f"{seconds / 60:.1f}m"
    else:
        return f"{seconds:.0f}s"


# ====== 缓存管理 ======

class UploadCache:
    """上传缓存管理，支持断点续传"""

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def _get_lock(self, key: str) -> threading.Lock:
        with self._lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        safe_name = hashlib.md5(cache_key.encode()).hexdigest()
        return self.cache_dir / f"{safe_name}.json"

    def save(self, cache_key: str, data: Dict[str, Any]) -> None:
        """保存缓存"""
        with self._get_lock(cache_key):
            cache_file = self.get_cache_path(cache_key)
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"保存缓存失败 {cache_key}: {e}")

    def load(self, cache_key: str, max_age: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """加载缓存"""
        cache_file = self.get_cache_path(cache_key)
        if not cache_file.exists():
            return None
        try:
            if max_age and time.time() - cache_file.stat().st_mtime > max_age:
                return None
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载缓存失败 {cache_key}: {e}")
            return None

    def clear(self, cache_key: str) -> None:
        """清除缓存"""
        cache_file = self.get_cache_path(cache_key)
        try:
            if cache_file.exists():
                cache_file.unlink()
        except Exception as e:
            logger.warning(f"清除缓存失败 {cache_key}: {e}")


# ====== 上传进度追踪 ======

class UploadProgress:
    """上传进度追踪器"""

    def __init__(self, file_size: int, callback: Optional[Callable] = None):
        self.file_size = file_size
        self.callback = callback
        self.total_uploaded = 0
        self.chunk_count = 0
        self.start_time = time.time()
        self.last_print_time = 0
        self._lock = threading.Lock()

    def update(self, chunk_size: int) -> None:
        """更新上传进度"""
        with self._lock:
            self.total_uploaded += chunk_size
            self.chunk_count += 1
            now = time.time()
            if now - self.last_print_time >= 2.0:  # 每 2 秒打印一次
                self.last_print_time = now
                elapsed = now - self.start_time
                speed = self.total_uploaded / elapsed if elapsed > 0 else 0
                pct = (self.total_uploaded / self.file_size * 100) if self.file_size > 0 else 0
                logger.info(
                    f"上传进度: {format_size(self.total_uploaded)}/{format_size(self.file_size)} "
                    f"({pct:.1f}%) | {format_speed(speed)} | "
                    f"已用 {format_time(elapsed)}"
                )

    def get_stats(self) -> Dict[str, Any]:
        """获取当前统计信息"""
        elapsed = time.time() - self.start_time
        speed = self.total_uploaded / elapsed if elapsed > 0 else 0
        return {
            "total_uploaded": self.total_uploaded,
            "file_size": self.file_size,
            "percentage": (self.total_uploaded / self.file_size * 100) if self.file_size > 0 else 0,
            "speed": speed,
            "elapsed": elapsed,
            "chunk_count": self.chunk_count,
        }


# ====== Telegram 通知 ======

class TelegramNotifier:
    """Telegram 上传进度通知"""

    def __init__(self, bot_token: str, chat_id: str, thread_id: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.thread_id = thread_id
        self._last_message_id: Optional[int] = None

    def send_progress(
        self, file_name: str, file_size: int, uploaded: int, speed: float
    ) -> Optional[int]:
        """发送上传进度到 Telegram"""
        try:
            import requests
            pct = (uploaded / file_size * 100) if file_size > 0 else 0
            text = (
                f"📤 上传中: {file_name}\n"
                f"进度: {format_size(uploaded)}/{format_size(file_size)} ({pct:.1f}%)\n"
                f"速度: {format_speed(speed)}"
            )
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if self.thread_id:
                payload["message_thread_id"] = self.thread_id
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                self._last_message_id = resp.json().get("result", {}).get("message_id")
            return self._last_message_id
        except Exception as e:
            logger.warning(f"发送 Telegram 进度失败: {e}")
            return None

    def send_message(self, text: str, message_id: Optional[int] = None) -> Optional[int]:
        """发送 Telegram 消息"""
        try:
            import requests
            if message_id:
                url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
                payload = {
                    "chat_id": self.chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                }
            else:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                payload = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                }
            if self.thread_id:
                payload["message_thread_id"] = self.thread_id
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                result = resp.json().get("result", {})
                self._last_message_id = result.get("message_id")
            return self._last_message_id
        except Exception as e:
            logger.warning(f"发送 Telegram 消息失败: {e}")
            return None


# ====== 公共上传基类 ======

class BaseUploader(ABC):
    """上传器抽象基类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._cache: Optional[UploadCache] = None
        self._notifier: Optional[TelegramNotifier] = None

    @property
    @abstractmethod
    def name(self) -> str:
        """上传器名称"""
        ...

    def get_cache(self) -> UploadCache:
        """获取缓存管理器"""
        if self._cache is None:
            cache_dir = self.config.get("cache_dir", "data/upload_cache")
            self._cache = UploadCache(cache_dir)
        return self._cache

    def get_notifier(self) -> Optional[TelegramNotifier]:
        """获取 Telegram 通知器"""
        if self._notifier is None:
            tg_config = self.config.get("telegram", {})
            if tg_config.get("bot_token") and tg_config.get("chat_id"):
                self._notifier = TelegramNotifier(
                    bot_token=tg_config["bot_token"],
                    chat_id=tg_config["chat_id"],
                    thread_id=tg_config.get("thread_id"),
                )
        return self._notifier

    @abstractmethod
    def upload_video(
        self, file_path: str, item_type: str, item_id: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        """上传视频文件"""
        ...

    def cleanup(self) -> None:
        """清理资源"""
        pass