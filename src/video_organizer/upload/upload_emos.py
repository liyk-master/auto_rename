import requests
import json
import os
from pathlib import Path
import math
import time
import logging
from typing import Optional, Dict, Any, List
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import datetime
import hashlib

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


class RobustEmosVideoUploader:
    def __init__(
        self,
        auth_token,
        base_url="https://emos.best",
        chunk_size_mb=50,
        telegram_config=None,
        cache_dir=None,
        cache_expire_hours=24,
    ):
        self.base_url = base_url
        self.session = self._create_robust_session()
        self.headers = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "authorization": f"Bearer {auth_token}",
            "origin": base_url,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        # 设置分片大小，限制在 10MB - 200MB 之间
        self.chunk_size_mb = max(50, min(200, chunk_size_mb))
        self.upload_stats = {
            "total_uploaded": 0,
            "start_time": None,
            "last_update_time": None,
            "last_uploaded": 0,
        }

        # Telegram 配置
        self.telegram_config = telegram_config or {}
        self.tg_bot_token = self.telegram_config.get("bot_token", "")
        self.tg_chat_id = self.telegram_config.get("chat_id", "")
        self._tg_message_ids: Dict[str, Optional[int]] = (
            {}
        )  # key: file_path, value: message_id
        self.tg_message_id: Optional[int] = None  # 当前上传的TG消息ID
        self.tg_last_update_time = 0  # 上次更新时间，用于限流
        self.tg_update_interval = 2  # 更新间隔（秒），避免触发TG API限制

        # 断点续传缓存配置
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            # 智能判断运行环境：开发环境 vs 打包后的可执行文件
            import sys
            import os

            if getattr(sys, 'frozen', False):
                # 打包后的可执行文件
                # 优先使用可执行文件所在目录
                base_dir = Path(sys.executable).parent
                # 如果可执行文件在临时目录（如 PyInstaller 的 _MEIPASS），则使用当前工作目录
                if '_MEIPASS' in sys.executable or 'temp' in sys.executable.lower():
                    base_dir = Path(os.getcwd())
            else:
                # 开发环境：使用项目根目录
                base_dir = Path(__file__).parent.parent.parent

            self.cache_dir = base_dir / "data" / "upload_cache"

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_expire_hours = cache_expire_hours

    def _get_cache_key(self, item_type: str, item_id: str, file_path: Path) -> str:
        """生成缓存键，基于 item_type、item_id 和文件路径"""
        file_hash = hashlib.md5(str(file_path).encode('utf-8')).hexdigest()[:8]
        return f"{item_type}_{item_id}_{file_hash}"

    def _get_cache_file_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{cache_key}.json"

    def _is_cache_valid(self, cache_file: Path) -> bool:
        """检查缓存是否有效（未过期）"""
        if not cache_file.exists():
            return False
        try:
            cache_time = datetime.datetime.fromtimestamp(cache_file.stat().st_mtime)
            expire_time = datetime.datetime.now() - datetime.timedelta(hours=self.cache_expire_hours)
            return cache_time > expire_time
        except Exception:
            return False

    def _save_upload_cache(self, cache_key: str, step2_result: Dict[str, Any], uploaded_chunks: list, file_path: Path):
        """保存上传缓存"""
        cache_file = self._get_cache_file_path(cache_key)
        cache_data = {
            "cache_key": cache_key,
            "timestamp": datetime.datetime.now().isoformat(),
            "file_path": str(file_path),
            "file_size": file_path.stat().st_size,
            "step2_result": step2_result,
            "uploaded_chunks": uploaded_chunks,
        }
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"✓ 已保存上传缓存: {cache_key}")
        except Exception as e:
            print(f"✗ 保存缓存失败: {e}")

    def _load_upload_cache(self, cache_key: str, file_path: Path) -> Optional[Dict[str, Any]]:
        """加载上传缓存"""
        cache_file = self._get_cache_file_path(cache_key)
        if not self._is_cache_valid(cache_file):
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 验证文件是否匹配
            if cache_data.get("file_path") != str(file_path):
                print(f"✗ 缓存文件路径不匹配，忽略缓存")
                return None

            current_file_size = file_path.stat().st_size
            cached_file_size = cache_data.get("file_size")
            if current_file_size != cached_file_size:
                print(f"✗ 文件大小已变化（缓存: {cached_file_size}, 当前: {current_file_size}），忽略缓存")
                return None

            print(f"✓ 加载上传缓存: {cache_key}")
            print(f"  - 已上传分片: {len(cache_data.get('uploaded_chunks', []))}")
            return cache_data
        except Exception as e:
            print(f"✗ 加载缓存失败: {e}")
            return None

    def _clear_upload_cache(self, cache_key: str):
        """清除上传缓存"""
        cache_file = self._get_cache_file_path(cache_key)
        try:
            if cache_file.exists():
                cache_file.unlink()
                print(f"✓ 已清除上传缓存: {cache_key}")
        except Exception as e:
            print(f"✗ 清除缓存失败: {e}")

    def _create_robust_session(self):
        """创建具有重试机制和SSL优化的会话"""
        session = requests.Session()

        # 配置重试策略
        retry_strategy = Retry(
            total=5,  # 最大重试次数
            status_forcelist=[429, 500, 502, 503, 504],  # 需要重试的状态码
            allowed_methods=[
                "HEAD",
                "GET",
                "PUT",
                "DELETE",
                "OPTIONS",
                "TRACE",
            ],  # 允许重试的方法
            backoff_factor=1,  # 重试间隔
        )

        # 创建适配器
        adapter = HTTPAdapter(
            max_retries=retry_strategy, pool_connections=10, pool_maxsize=10
        )

        # 挂载适配器
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _format_speed(self, bytes_per_second):
        """格式化速度显示"""
        if bytes_per_second >= 1024 * 1024:
            return f"{bytes_per_second / (1024 * 1024):.2f} MB/s"
        elif bytes_per_second >= 1024:
            return f"{bytes_per_second / 1024:.2f} KB/s"
        else:
            return f"{bytes_per_second:.2f} B/s"

    def _format_size(self, bytes_size):
        """格式化大小显示"""
        if bytes_size >= 1024 * 1024 * 1024:
            return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"
        elif bytes_size >= 1024 * 1024:
            return f"{bytes_size / (1024 * 1024):.2f} MB"
        elif bytes_size >= 1024:
            return f"{bytes_size / 1024:.2f} KB"
        else:
            return f"{bytes_size} B"

    def _format_time(self, seconds):
        """格式化时间显示"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}分{secs:.1f}秒"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = seconds % 60
            return f"{hours}时{minutes}分{secs:.1f}秒"

    def _update_upload_stats(self, chunk_size, chunk_start_time):
        """更新上传统计信息"""
        current_time = time.time()

        if self.upload_stats["start_time"] is None:
            self.upload_stats["start_time"] = current_time
            self.upload_stats["last_update_time"] = current_time
            self.upload_stats["last_uploaded"] = 0

        self.upload_stats["total_uploaded"] += chunk_size

        # 计算瞬时速度（基于上一个分片）
        time_diff = current_time - self.upload_stats["last_update_time"]
        if time_diff > 0:
            instant_speed = chunk_size / time_diff
        else:
            instant_speed = 0

        # 计算平均速度
        total_time = current_time - self.upload_stats["start_time"]
        if total_time > 0:
            average_speed = self.upload_stats["total_uploaded"] / total_time
        else:
            average_speed = 0

        # 更新最后更新时间
        self.upload_stats["last_update_time"] = current_time

        return instant_speed, average_speed, total_time

    def _print_upload_progress(
        self,
        chunk_num,
        total_chunks,
        chunk_size,
        file_size,
        instant_speed,
        average_speed,
        elapsed_time,
        file_name=None,
        file_path=None,
    ):
        """打印上传进度信息"""
        progress_percent = (chunk_num + 1) / total_chunks * 100
        uploaded_size = self.upload_stats["total_uploaded"]
        remaining_size = file_size - uploaded_size

        # 计算预估剩余时间
        if average_speed > 0:
            remaining_time = remaining_size / average_speed
        else:
            remaining_time = 0

        # 创建进度条
        bar_length = 40
        filled_length = int(bar_length * (chunk_num + 1) / total_chunks)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)

        # 报告上传进度到 Web
        if file_path and file_name:
            speed_str = self._format_speed(average_speed)
            _report_upload_progress(
                file_path=str(file_path) if isinstance(file_path, Path) else file_path,
                filename=file_name,
                uploader="emos",
                progress=progress_percent,
                uploaded_bytes=uploaded_size,
                total_bytes=file_size,
                speed=speed_str,
                status="uploading"
            )

        # 使用换行显示，确保在所有环境下都能看到
        print(f"\n{'='*80}")
        if file_name:
            print(f"📁 文件名称: {file_name}")
        print(f"📊 上传进度: {progress_percent:6.2f}%")
        print(f"[{bar}]")
        print(f"分片进度: {chunk_num + 1:3d}/{total_chunks:3d}")
        print(f"已上传: {self._format_size(uploaded_size):>10}")
        print(f"瞬时速度: {self._format_speed(instant_speed):>10}")
        print(f"平均速度: {self._format_speed(average_speed):>10}")
        print(f"已用时间: {self._format_time(elapsed_time):>8}")
        print(f"剩余时间: {self._format_time(remaining_time):>8}")
        print(f"{'='*80}")

    def _send_tg_progress(
        self,
        file_name,
        chunk_num,
        total_chunks,
        chunk_size,
        file_size,
        instant_speed,
        average_speed,
        elapsed_time,
    ):
        """发送/更新 Telegram 进度消息"""
        # 检查是否配置了 TG
        if not self.tg_bot_token or not self.tg_chat_id:
            return

        # 限流：检查距离上次更新是否超过间隔
        current_time = time.time()
        if (
            self.tg_message_id
            and (current_time - self.tg_last_update_time) < self.tg_update_interval
        ):
            return

        # 计算进度信息
        progress_percent = (chunk_num + 1) / total_chunks * 100
        uploaded_size = self.upload_stats["total_uploaded"]
        remaining_size = file_size - uploaded_size

        if average_speed > 0:
            remaining_time = remaining_size / average_speed
        else:
            remaining_time = 0

        # 创建进度条
        bar_length = 20
        filled_length = int(bar_length * (chunk_num + 1) / total_chunks)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)

        # 构建消息文本
        message_text = (
            f"📤 *上传进度*\n\n"
            f"文件: `{file_name}`\n"
            f"进度: {progress_percent:.1f}%\n"
            f"[{bar}]\n\n"
            f"分片: {chunk_num + 1}/{total_chunks}\n"
            f"已上传: {self._format_size(uploaded_size)}\n"
            f"平均速度: {self._format_speed(average_speed)}\n"
            f"已用时间: {self._format_time(elapsed_time)}\n"
            f"剩余时间: {self._format_time(remaining_time)}"
        )
        try:
            if self.tg_message_id is None:
                # 第一次发送消息
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
                        self.tg_message_id = result["result"]["message_id"]
                        self.tg_last_update_time = current_time
            else:
                # 编辑已有消息
                url = f"https://api.telegram.org/bot{self.tg_bot_token}/editMessageText"
                data = {
                    "chat_id": self.tg_chat_id,
                    "message_id": self.tg_message_id,
                    "text": message_text,
                    "parse_mode": "Markdown",
                }
                response = requests.post(url, json=data, timeout=10)
                if response.status_code == 200:
                    self.tg_last_update_time = current_time
        except Exception as e:
            # TG 通知失败不影响主流程，静默处理
            print(f"TG 通知失败: {e}")
            pass

    def step1_init_video(self, item_type, item_id, max_retries=3):
        """步骤1：初始化视频信息"""
        url = f"{self.base_url}/api/upload/video/base"
        params = {"item_type": item_type, "item_id": item_id}

        for attempt in range(max_retries):
            try:
                response = self.session.get(
                    url, headers=self.headers, params=params, timeout=30
                )
                response.raise_for_status()

                result = response.json()
                print(f"步骤1完成 - 视频标题: {result.get('title', '未知')}")
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = attempt + 1
                    print(
                        f"步骤1失败 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}"
                    )
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"步骤1失败，已达到最大重试次数: {e}")
                    raise

    def step2_get_upload_token(self, file_path, file_storage="default", max_retries=3):
        """步骤2：获取上传凭证"""
        url = f"{self.base_url}/api/upload/getUploadToken"

        file_path = Path(file_path)
        file_size = file_path.stat().st_size
        file_name = file_path.name

        mime_types = {
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".wmv": "video/x-ms-wmv",
            ".flv": "video/x-flv",
        }
        file_ext = file_path.suffix.lower()
        file_type = mime_types.get(file_ext, "video/mp4")

        data = {
            "type": "video",
            "file_type": file_type,
            "file_name": file_name,
            "file_size": file_size,
            "file_storage": file_storage,
        }

        headers = self.headers.copy()
        headers["content-type"] = "application/json"

        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    url, headers=headers, data=json.dumps(data), timeout=30
                )

                # 特殊处理 422 错误: 如果是"此资源您之前上传过"，则视为成功
                if response.status_code != 200:
                    try:
                        error_result = response.json()
                        print(
                            f"API响应非200: {response.status_code}, 内容: {error_result}"
                        )
                        if (
                            response.status_code == 422
                            and error_result.get("message") == "此资源您之前上传过"
                        ):
                            print(f"步骤2特殊处理 - 资源已存在，视为成功")
                            return error_result
                    except:
                        pass

                response.raise_for_status()

                result = response.json()
                upload_type = result.get("type", "onedrive")
                print(f"步骤2完成 - 存储类型: {upload_type}, 文件ID: {result.get('file_id')}")
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = attempt + 1
                    print(
                        f"步骤2失败 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}"
                    )
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"步骤2失败，已达到最大重试次数: {e}")
                    raise

    # ─── 各存储类型上传实现 ─────────────────────────────────────────

    def _upload_onedrive_chunk(self, upload_url, chunk_data, start_byte, end_byte, file_size, max_retries=5):
        """onedrive 类型：PUT 带 Content-Range 分片上传"""
        chunk_size = len(chunk_data)

        for attempt in range(max_retries):
            try:
                content_range = f"bytes {start_byte}-{end_byte-1}/{file_size}"
                headers = {
                    "Content-Length": str(chunk_size),
                    "Content-Range": content_range,
                    "Content-Type": "application/octet-stream",
                }

                chunk_start_time = time.time()

                response = self.session.put(
                    upload_url,
                    headers=headers,
                    data=chunk_data,
                    timeout=600,
                )

                status_code = response.status_code

                try:
                    response.close()
                except Exception:
                    pass

                if status_code in [200, 201, 202, 308]:
                    instant_speed, average_speed, elapsed_time = (
                        self._update_upload_stats(chunk_size, chunk_start_time)
                    )
                    return True, None, instant_speed, average_speed, elapsed_time
                elif status_code == 416:
                    print(f"✗ 分片范围无效 (416)")
                    return False, None, 0, 0, 0
                else:
                    print(f"分片上传失败，状态码: {status_code}")

            except requests.exceptions.SSLError as e:
                print(f"SSL错误 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries - 1:
                    wait_time = min(attempt + 1, 5)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return False, None, 0, 0, 0

            except requests.exceptions.RequestException as e:
                print(f"网络错误 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries - 1:
                    wait_time = min(attempt + 1, 5)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return False, None, 0, 0, 0

        return False, None, 0, 0, 0

    def _upload_r2_chunk(self, upload_url, chunk_data, start_byte, end_byte, file_size, max_retries=5):
        """r2 类型：PUT 直接上传（无需 Content-Range，但保持兼容）"""
        chunk_size = len(chunk_data)

        for attempt in range(max_retries):
            try:
                headers = {
                    "Content-Length": str(chunk_size),
                    "Content-Type": "application/octet-stream",
                }

                chunk_start_time = time.time()

                response = self.session.put(
                    upload_url,
                    headers=headers,
                    data=chunk_data,
                    timeout=600,
                )

                status_code = response.status_code

                try:
                    response.close()
                except Exception:
                    pass

                if status_code in [200, 201, 202, 204]:
                    instant_speed, average_speed, elapsed_time = (
                        self._update_upload_stats(chunk_size, chunk_start_time)
                    )
                    return True, None, instant_speed, average_speed, elapsed_time
                else:
                    print(f"R2分片上传失败，状态码: {status_code}")

            except requests.exceptions.RequestException as e:
                print(f"R2网络错误 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries - 1:
                    wait_time = min(attempt + 1, 5)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return False, None, 0, 0, 0

        return False, None, 0, 0, 0

    def _upload_onedrive_single(self, upload_url, file_path, file_size):
        """onedrive 单次上传（小文件不分片）"""
        headers = {
            "Content-Length": str(file_size),
            "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
            "Content-Type": "application/octet-stream",
        }
        with open(file_path, "rb") as f:
            response = self.session.put(
                upload_url,
                headers=headers,
                data=f,
                timeout=600,
            )
        try:
            response.close()
        except Exception:
            pass
        return response.status_code in [200, 201, 202, 308]

    def _upload_r2_single(self, upload_url, file_path, file_size):
        """r2 单次上传（小文件不分片）"""
        headers = {
            "Content-Length": str(file_size),
            "Content-Type": "application/octet-stream",
        }
        with open(file_path, "rb") as f:
            response = self.session.put(
                upload_url,
                headers=headers,
                data=f,
                timeout=600,
            )
        try:
            response.close()
        except Exception:
            pass
        return response.status_code in [200, 201, 202, 204]

    def _cache_multipart_presigns(self, cache_key, file_path, step2_result, file_size, presigns):
        """缓存 multipart presigns（不可重复获取，有效期1天）"""
        cache_file = self._get_cache_file_path(cache_key)
        cache_data = self._load_upload_cache(cache_key, file_path)
        if cache_data:
            cache_data["presigns"] = presigns
            cache_data["step2_result"] = step2_result
        else:
            cache_data = {
                "cache_key": cache_key,
                "timestamp": datetime.datetime.now().isoformat(),
                "file_path": str(file_path),
                "file_size": file_size,
                "step2_result": step2_result,
                "uploaded_chunks": [],
                "uploaded_etags": [],
                "presigns": presigns,
            }
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"✓ 已缓存 presigns（{len(presigns)} 个分片）")
        except Exception as e:
            print(f"✗ 缓存 presigns 失败: {e}")

    def _save_multipart_cache(self, cache_key, step2_result, uploaded_chunks, uploaded_etags, file_path):
        """保存 multipart 上传缓存"""
        cache_file = self._get_cache_file_path(cache_key)
        # 加载已有缓存，保留 presigns
        cache_data = {"presigns": []}
        try:
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
        except Exception:
            pass
        cache_data.update({
            "cache_key": cache_key,
            "timestamp": datetime.datetime.now().isoformat(),
            "file_path": str(file_path),
            "file_size": file_path.stat().st_size,
            "step2_result": step2_result,
            "uploaded_chunks": uploaded_chunks,
            "uploaded_etags": uploaded_etags,
        })
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"✗ 保存缓存失败: {e}")

    def _complete_multipart(self, upload_data, file_path, uploaded_etags, presigns):
        """完成 multipart 上传：调用合并接口"""
        file_id = upload_data.get("file_id", "")

        # 优先使用 multipart 专用合并接口
        merge_url = f"{self.base_url}/api/upload/multipart/{file_id}/complete"
        merge_data = {
            "parts": uploaded_etags,
        }

        print(f"📦 调用分片合并接口: {merge_url}")
        headers = self.headers.copy()
        headers["content-type"] = "application/json"

        for attempt in range(3):
            try:
                resp = self.session.post(
                    merge_url,
                    headers=headers,
                    data=json.dumps(merge_data),
                    timeout=60,
                )
                if resp.status_code in [200, 201]:
                    result = resp.json()
                    print(f"✓ 分片合并完成: {result}")
                    return True
                else:
                    print(f"分片合并请求失败: {resp.status_code}, {resp.text[:200]}")
                    if attempt < 2:
                        time.sleep(2)
            except Exception as e:
                print(f"分片合并异常: {e}")
                if attempt < 2:
                    time.sleep(2)

        return False

    # ─── 分片上传调度 ─────────────────────────────────────────────

    def step3_chunk_upload(self, file_path, upload_data, cache_key=None, resume_from_cache=False):
        """步骤3：根据存储类型选择合适的上传方式"""
        file_path = Path(file_path)
        file_size = file_path.stat().st_size

        data_field = upload_data.get("data", {})
        upload_type = upload_data.get("type", "onedrive")
        file_id = upload_data.get("file_id", "")

        print(f"存储类型: {upload_type}")
        print(f"文件ID: {file_id}")

        # ─── multipart 类型：请求 presigns 后分片上传 ─────
        if upload_type == "multipart":
            multipart_size = 0
            if isinstance(data_field, dict):
                raw_size = data_field.get("multipart_size", 0)
                print(f"multipart_size 原始值: {raw_size} (类型: {type(raw_size).__name__})")
                if isinstance(raw_size, dict):
                    # 格式: {"min": 5242880, "max": 5368709120}
                    min_size = raw_size.get("min", 0)
                    max_size = raw_size.get("max", 0)
                    # 使用配置的分片大小，但限制在 [min, max] 范围内
                    configured = self.chunk_size_mb * 1024 * 1024
                    multipart_size = max(min_size, min(configured, max_size))
                    print(f"分片大小: min={self._format_size(min_size)}, max={self._format_size(max_size)}")
                    print(f"使用分片: {self._format_size(multipart_size)}")
                elif isinstance(raw_size, str):
                    multipart_size = int(raw_size)
                else:
                    multipart_size = int(raw_size)

            if not multipart_size:
                print(f"✗ multipart 响应缺少 multipart_size")
                return False

            # 计算分片数
            num_chunks = math.ceil(file_size / multipart_size)
            print(f"multipart_size: {self._format_size(multipart_size)}")
            print(f"总分片数: {num_chunks}")

            # 检查缓存中是否有 presigns（不可重复获取）
            presigns = None
            if cache_key and resume_from_cache:
                cache_data = self._load_upload_cache(cache_key, file_path)
                if cache_data and cache_data.get("presigns"):
                    presigns = cache_data["presigns"]
                    print(f"✓ 使用缓存的 presigns（{len(presigns)} 个分片）")

            if not presigns:
                # 请求 presigns
                presigns = self._request_multipart_presigns(file_id, num_chunks)
                if not presigns:
                    print(f"✗ 获取分片凭证失败")
                    return False

                print(f"✓ 获取到 {len(presigns)} 个分片凭证")

                # 缓存 presigns（不可重复获取，有效期1天）
                if cache_key:
                    self._cache_multipart_presigns(cache_key, file_path, upload_data, file_size, presigns)

            # 分片上传
            return self._step3_multipart(
                file_path, upload_data, file_size, presigns,
                cache_key, resume_from_cache
            )

        # ─── 其他类型：onedrive / r2 / tusd ─────
        upload_url = ""
        if isinstance(data_field, dict):
            upload_url = data_field.get("upload_url", "")
        elif isinstance(data_field, str):
            upload_url = data_field

        if upload_type == "onedrive":
            return self._step3_onedrive(file_path, upload_url, file_size, cache_key, resume_from_cache)
        elif upload_type == "r2":
            return self._step3_r2(file_path, upload_url, file_size, cache_key, resume_from_cache)
        elif upload_type == "tusd":
            return self._step3_tusd(file_path, upload_url, file_size, cache_key)
        else:
            print(f"未知存储类型 '{upload_type}'，尝试使用 onedrive 方式上传")
            return self._step3_onedrive(file_path, upload_url, file_size, cache_key, resume_from_cache)

    def _request_multipart_presigns(self, file_id, num_chunks, max_retries=3):
        """请求 multipart 分片上传的预签名 URL"""
        url = f"{self.base_url}/api/upload/multipart/{file_id}/presign"
        data = {"number": num_chunks}
        headers = self.headers.copy()
        headers["content-type"] = "application/json"

        print(f"请求 presigns: {url} ({num_chunks} 个分片)")

        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    url, headers=headers, data=json.dumps(data), timeout=30
                )
                if response.status_code == 200:
                    result = response.json()
                    if isinstance(result, list):
                        return result
                    elif isinstance(result, dict) and "data" in result:
                        return result["data"]
                    else:
                        print(f"presigns 响应格式异常: {type(result)}")
                        return result if isinstance(result, list) else []
                else:
                    print(f"请求 presigns 失败: {response.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(attempt + 1)
            except Exception as e:
                print(f"请求 presigns 异常 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(attempt + 1)

        return []

    def _step3_onedrive(self, file_path, upload_url, file_size, cache_key=None, resume_from_cache=False):
        """onedrive 分片上传"""
        chunk_size = self.chunk_size_mb * 1024 * 1024
        total_chunks = math.ceil(file_size / chunk_size)

        # 小文件不分片
        if total_chunks <= 1:
            print(f"文件较小，单次上传...")
            current_time = time.time()
            self.upload_stats = {
                "total_uploaded": 0, "start_time": current_time,
                "last_update_time": current_time, "last_uploaded": 0,
            }
            success = self._upload_onedrive_single(upload_url, file_path, file_size)
            if success:
                self._update_upload_stats(file_size, current_time)
                print(f"✓ 单次上传完成")
            return success

        # 已上传的分片列表
        uploaded_chunks = []

        if resume_from_cache and cache_key:
            cache_data = self._load_upload_cache(cache_key, file_path)
            if cache_data:
                uploaded_chunks = cache_data.get("uploaded_chunks", [])

        print(f"开始分片上传 (onedrive)")
        print(f"文件大小: {self._format_size(file_size)}")
        print(f"分片大小: {self._format_size(chunk_size)}")
        print(f"总分片数: {total_chunks}")

        # 重置统计
        current_time = time.time()
        self.upload_stats = {
            "total_uploaded": 0, "start_time": current_time,
            "last_update_time": current_time, "last_uploaded": 0,
        }

        successful_chunks = 0

        with open(file_path, "rb") as f:
            for chunk_num in range(total_chunks):
                if chunk_num in uploaded_chunks:
                    successful_chunks += 1
                    print(f"⊘ 分片 {chunk_num + 1}/{total_chunks} 已上传，跳过")
                    continue

                start_byte = chunk_num * chunk_size
                end_byte = min(start_byte + chunk_size, file_size)

                f.seek(start_byte)
                chunk_data = f.read(chunk_size)
                chunk_data_len = len(chunk_data)

                success, _, instant_speed, average_speed, elapsed_time = (
                    self._upload_onedrive_chunk(
                        upload_url, chunk_data, start_byte, end_byte, file_size
                    )
                )

                del chunk_data

                if success:
                    successful_chunks += 1
                    uploaded_chunks.append(chunk_num)

                    if cache_key:
                        self._save_upload_cache(cache_key, {"data": {"upload_url": upload_url}}, uploaded_chunks, file_path)

                    self._print_upload_progress(
                        chunk_num, total_chunks, chunk_data_len, file_size,
                        instant_speed, average_speed, elapsed_time,
                        file_name=file_path.name, file_path=file_path,
                    )
                    self._send_tg_progress(
                        file_path.name, chunk_num, total_chunks, chunk_data_len,
                        file_size, instant_speed, average_speed, elapsed_time,
                    )
                else:
                    print(f"\n✗ 分片 {chunk_num + 1} 上传失败，跳过后续分片")
                    if cache_key:
                        self._save_upload_cache(cache_key, {"data": {"upload_url": upload_url}}, uploaded_chunks, file_path)
                    break

                time.sleep(0.5)

        if successful_chunks == total_chunks:
            total_time = time.time() - self.upload_stats["start_time"]
            print(f"所有分片上传完成!")
            print(f"总用时: {self._format_time(total_time)}")
            print(f"平均速度: {self._format_speed(file_size / total_time)}")
            return True
        else:
            print(f"上传中断，成功上传 {successful_chunks}/{total_chunks} 个分片")
            return False

    def _step3_r2(self, file_path, upload_url, file_size, cache_key=None, resume_from_cache=False):
        """r2 分片上传（无需 Content-Range）"""
        chunk_size = self.chunk_size_mb * 1024 * 1024
        total_chunks = math.ceil(file_size / chunk_size)

        # 小文件不分片
        if total_chunks <= 1:
            print(f"文件较小，单次上传 (r2)...")
            current_time = time.time()
            self.upload_stats = {
                "total_uploaded": 0, "start_time": current_time,
                "last_update_time": current_time, "last_uploaded": 0,
            }
            success = self._upload_r2_single(upload_url, file_path, file_size)
            if success:
                self._update_upload_stats(file_size, current_time)
                print(f"✓ R2 单次上传完成")
            return success

        uploaded_chunks = []

        if resume_from_cache and cache_key:
            cache_data = self._load_upload_cache(cache_key, file_path)
            if cache_data:
                uploaded_chunks = cache_data.get("uploaded_chunks", [])

        print(f"开始分片上传 (r2)")
        print(f"文件大小: {self._format_size(file_size)}")
        print(f"分片大小: {self._format_size(chunk_size)}")
        print(f"总分片数: {total_chunks}")

        current_time = time.time()
        self.upload_stats = {
            "total_uploaded": 0, "start_time": current_time,
            "last_update_time": current_time, "last_uploaded": 0,
        }

        successful_chunks = 0

        with open(file_path, "rb") as f:
            for chunk_num in range(total_chunks):
                if chunk_num in uploaded_chunks:
                    successful_chunks += 1
                    print(f"⊘ 分片 {chunk_num + 1}/{total_chunks} 已上传，跳过")
                    continue

                start_byte = chunk_num * chunk_size
                end_byte = min(start_byte + chunk_size, file_size)

                f.seek(start_byte)
                chunk_data = f.read(chunk_size)
                chunk_data_len = len(chunk_data)

                success, _, instant_speed, average_speed, elapsed_time = (
                    self._upload_r2_chunk(
                        upload_url, chunk_data, start_byte, end_byte, file_size
                    )
                )

                del chunk_data

                if success:
                    successful_chunks += 1
                    uploaded_chunks.append(chunk_num)

                    if cache_key:
                        self._save_upload_cache(cache_key, {"data": {"upload_url": upload_url}}, uploaded_chunks, file_path)

                    self._print_upload_progress(
                        chunk_num, total_chunks, chunk_data_len, file_size,
                        instant_speed, average_speed, elapsed_time,
                        file_name=file_path.name, file_path=file_path,
                    )
                    self._send_tg_progress(
                        file_path.name, chunk_num, total_chunks, chunk_data_len,
                        file_size, instant_speed, average_speed, elapsed_time,
                    )
                else:
                    print(f"\n✗ R2 分片 {chunk_num + 1} 上传失败，跳过后续分片")
                    if cache_key:
                        self._save_upload_cache(cache_key, {"data": {"upload_url": upload_url}}, uploaded_chunks, file_path)
                    break

                time.sleep(0.5)

        if successful_chunks == total_chunks:
            total_time = time.time() - self.upload_stats["start_time"]
            print(f"所有 R2 分片上传完成!")
            print(f"总用时: {self._format_time(total_time)}")
            print(f"平均速度: {self._format_speed(file_size / total_time)}")
            return True
        else:
            print(f"R2 上传中断，成功上传 {successful_chunks}/{total_chunks} 个分片")
            return False

    def _step3_tusd(self, file_path, upload_url, file_size, cache_key=None):
        """tusd 协议上传"""
        import base64
        import requests as req

        file_name = file_path.name
        metadata = f"filename {base64.b64encode(file_name.encode('utf-8')).decode('ascii')}"

        # 确定创建上传的 URL
        if upload_url.endswith("/files"):
            creation_url = upload_url
        else:
            creation_url = upload_url.rstrip("/") + "/files"

        # 创建上传会话
        create_headers = {
            "Tus-Resumable": "1.0.0",
            "Upload-Length": str(file_size),
            "Upload-Metadata": metadata,
        }

        print(f"创建 tusd 上传会话...")
        try:
            create_resp = req.post(
                creation_url,
                headers=create_headers,
                timeout=30,
            )
            if create_resp.status_code in [201, 200]:
                location = create_resp.headers.get("Location", "")
                if location.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(upload_url)
                    location = f"{parsed.scheme}://{parsed.netloc}{location}"
                print(f"✓ tusd 上传已创建: {location}")
            else:
                print(f"⚠ tusd 创建返回 {create_resp.status_code}，直接使用 upload_url")
                location = upload_url
        except Exception as e:
            print(f"⚠ tusd 创建失败: {e}，直接使用 upload_url")
            location = upload_url

        # 分片上传
        chunk_size = self.chunk_size_mb * 1024 * 1024
        total_chunks = math.ceil(file_size / chunk_size)

        current_time = time.time()
        self.upload_stats = {
            "total_uploaded": 0, "start_time": current_time,
            "last_update_time": current_time, "last_uploaded": 0,
        }

        uploaded_bytes = 0

        with open(file_path, "rb") as f:
            for chunk_num in range(total_chunks):
                chunk_data = f.read(chunk_size)
                chunk_len = len(chunk_data)

                # 获取当前偏移量
                for head_attempt in range(3):
                    try:
                        head_resp = req.head(
                            location,
                            headers={"Tus-Resumable": "1.0.0"},
                            timeout=30,
                        )
                        offset = int(head_resp.headers.get("Upload-Offset", "0"))
                        break
                    except Exception:
                        offset = uploaded_bytes
                        if head_attempt < 2:
                            time.sleep(1)

                if offset < uploaded_bytes + chunk_len:
                    patch_headers = {
                        "Tus-Resumable": "1.0.0",
                        "Content-Type": "application/offset+octet-stream",
                        "Upload-Offset": str(offset),
                    }

                    for attempt in range(5):
                        try:
                            patch_resp = req.patch(
                                location,
                                headers=patch_headers,
                                data=chunk_data,
                                timeout=600,
                            )
                            if patch_resp.status_code in [204, 200]:
                                break
                            else:
                                print(f"tusd 分片 {chunk_num + 1} 失败: {patch_resp.status_code}")
                                if attempt < 4:
                                    time.sleep(min(attempt + 1, 3))
                        except Exception as e:
                            print(f"tusd 分片 {chunk_num + 1} 异常: {e}")
                            if attempt < 4:
                                time.sleep(min(attempt + 1, 3))
                    else:
                        print(f"✗ tusd 分片 {chunk_num + 1} 上传失败")
                        return False

                uploaded_bytes += chunk_len

                instant_speed, average_speed, elapsed_time = self._update_upload_stats(
                    chunk_len, current_time
                )

                self._print_upload_progress(
                    chunk_num, total_chunks, chunk_len, file_size,
                    instant_speed, average_speed, elapsed_time,
                    file_name=file_path.name, file_path=file_path,
                )

                time.sleep(0.2)

        # 验证上传完成
        try:
            final_head = req.head(location, headers={"Tus-Resumable": "1.0.0"}, timeout=30)
            final_offset = int(final_head.headers.get("Upload-Offset", "0"))
            if final_offset >= file_size:
                print(f"✓ tusd 上传验证通过: {final_offset}/{file_size}")
                return True
        except Exception:
            pass

        return True  # 即使验证失败，也认为上传可能已完成

    def _step3_multipart(self, file_path, upload_data, file_size, presigns, cache_key=None, resume_from_cache=False):
        """multipart 预签名分片上传"""
        # 如果没有 presigns，退化为 onedrive 方式
        if not presigns:
            print("⚠ multipart 类型但无 presigns，退化到 onedrive 方式")
            upload_url = upload_data.get("data", {}).get("upload_url", "")
            if upload_url:
                return self._step3_onedrive(file_path, upload_url, file_size, cache_key, resume_from_cache)
            return False

        total_chunks = len(presigns)
        chunk_size = self.chunk_size_mb * 1024 * 1024

        uploaded_chunks = []
        uploaded_etags = []

        if resume_from_cache and cache_key:
            cache_data = self._load_upload_cache(cache_key, file_path)
            if cache_data:
                uploaded_chunks = cache_data.get("uploaded_chunks", [])
                uploaded_etags = cache_data.get("uploaded_etags", [])

        print(f"开始 multipart 分片上传")
        print(f"文件大小: {self._format_size(file_size)}")
        print(f"分片大小: {self._format_size(chunk_size)}")
        print(f"总分片数: {total_chunks}")

        current_time = time.time()
        self.upload_stats = {
            "total_uploaded": 0, "start_time": current_time,
            "last_update_time": current_time, "last_uploaded": 0,
        }

        with open(file_path, "rb") as f:
            for idx, presign in enumerate(presigns):
                chunk_num = presign.get("number", idx + 1) - 1

                if chunk_num in uploaded_chunks:
                    print(f"⊘ 分片 {chunk_num + 1}/{total_chunks} 已上传，跳过")
                    continue

                part_url = presign["upload_url"]
                start_byte = chunk_num * chunk_size
                end_byte = min(start_byte + chunk_size, file_size)
                part_len = end_byte - start_byte

                f.seek(start_byte)
                chunk_data = f.read(part_len)

                success = False
                for attempt in range(5):
                    try:
                        part_headers = {
                            "Content-Length": str(part_len),
                            "Content-Type": "application/octet-stream",
                        }
                        part_resp = self.session.put(
                            part_url,
                            headers=part_headers,
                            data=chunk_data,
                            timeout=600,
                        )

                        if idx == 0:
                            resp_body = part_resp.text[:500] if part_resp.text else "(空)"
                            print(f"  ── 分片1 响应 ──")
                            print(f"  状态码: {part_resp.status_code}")
                            print(f"  响应头: {dict(part_resp.headers)}")
                            print(f"  响应体: {resp_body}")
                            print(f"  ────────────────")

                        if part_resp.status_code in [200, 201, 204]:
                            etag = part_resp.headers.get("ETag", "").strip('"')
                            if idx == 0:
                                print(f"  提取的 ETag: '{etag}'")
                            uploaded_etags.append({
                                "number": chunk_num + 1,
                                "etag": etag,
                            })
                            uploaded_chunks.append(chunk_num)

                            if cache_key:
                                self._save_multipart_cache(
                                    cache_key, upload_data,
                                    uploaded_chunks, uploaded_etags, file_path
                                )

                            instant_speed, average_speed, elapsed_time = (
                                self._update_upload_stats(part_len, time.time())
                            )
                            self._print_upload_progress(
                                chunk_num, total_chunks, part_len, file_size,
                                instant_speed, average_speed, elapsed_time,
                                file_name=file_path.name, file_path=file_path,
                            )
                            success = True
                            break
                        else:
                            print(f"multipart 分片 {chunk_num + 1} 失败: {part_resp.status_code}")
                            if attempt < 4:
                                time.sleep(min(attempt + 1, 3))
                    except Exception as e:
                        print(f"multipart 分片 {chunk_num + 1} 异常: {e}")
                        if attempt < 4:
                            time.sleep(min(attempt + 1, 3))
                    finally:
                        del chunk_data

                if not success:
                    print(f"✗ multipart 分片 {chunk_num + 1} 上传失败")
                    if cache_key:
                        self._save_multipart_cache(
                            cache_key, upload_data,
                            uploaded_chunks, uploaded_etags, file_path
                        )
                    return False

                time.sleep(0.3)

        # 所有分片上传完成，调用合并
        print(f"所有分片上传完成，调用合并接口...")
        print(f"  已收集 ETags: {len(uploaded_etags)} 个")
        if uploaded_etags:
            print(f"  首条: {uploaded_etags[0]}")
            print(f"  末条: {uploaded_etags[-1]}")
        else:
            print(f"  ⚠ ETags 列表为空！检查 presign 响应是否包含 ETag 头")
        merge_success = self._complete_multipart(upload_data, file_path, uploaded_etags, presigns)

        if merge_success:
            total_time = time.time() - self.upload_stats["start_time"]
            print(f"multipart 上传完成!")
            print(f"总用时: {self._format_time(total_time)}")
            print(f"平均速度: {self._format_speed(file_size / total_time)}")
            if cache_key:
                self._clear_upload_cache(cache_key)
            return True
        else:
            print(f"multipart 合并失败")
            return False

    def _step3_multipart_remote(self, file_path, upload_data, file_size, upload_url, cache_key=None, resume_from_cache=False):
        """multipart 类型：从远端获取 presigns 后分片上传"""
        file_id = upload_data.get("file_id", "")
        chunk_size = self.chunk_size_mb * 1024 * 1024
        total_chunks = math.ceil(file_size / chunk_size)

        print(f"从远端获取 presigns...")
        print(f"文件大小: {self._format_size(file_size)}")
        print(f"分片大小: {self._format_size(chunk_size)}")
        print(f"预估分片数: {total_chunks}")

        # 尝试从 upload_url 获取 presigns
        presigns = []
        try:
            req_url = upload_url
            if "{file_id}" in req_url:
                req_url = req_url.replace("{file_id}", file_id)
            if "{chunks}" in req_url:
                req_url = req_url.replace("{chunks}", str(total_chunks))

            resp = self.session.get(req_url, headers=self.headers, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                if isinstance(result, list):
                    presigns = result
                elif isinstance(result, dict):
                    presigns = result.get("data", result.get("presigns", result.get("parts", [])))
                print(f"✓ 获取到 {len(presigns)} 个分片凭证")
            else:
                print(f"✗ 获取 presigns 失败: {resp.status_code}")
        except Exception as e:
            print(f"✗ 获取 presigns 异常: {e}")

        if not presigns:
            print(f"✗ 无法获取分片凭证，上传失败")
            return False

        # 使用获取到的 presigns 进行分片上传
        upload_data["data"] = {"presigns": presigns}
        return self._step3_multipart(file_path, upload_data, file_size, presigns, cache_key, resume_from_cache)

    def step4_confirm_upload(self, file_id, item_type, item_id, max_retries=3):
        """步骤4：确认上传完成"""
        url = f"{self.base_url}/api/upload/video/save"

        data = {"file_id": file_id, "item_type": item_type, "item_id": item_id}

        headers = self.headers.copy()
        headers["content-type"] = "application/json"

        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    url, headers=headers, data=json.dumps(data), timeout=30
                )
                response.raise_for_status()

                result = response.json()
                print(f"步骤4完成 - 媒体id: {result.get('media_id')}")
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = attempt + 1
                    print(
                        f"步骤4失败 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}"
                    )
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"步骤4失败，已达到最大重试次数: {e}")
                    raise

    def upload_video(self, file_path, item_type, item_id, file_storage="default", enable_resume=True):
        """完整的上传流程（支持断点续传）"""
        file_path_obj = Path(file_path)
        file_size = file_path_obj.stat().st_size
        file_name = file_path_obj.name

        # 报告上传开始
        _report_upload_progress(
            file_path=str(file_path_obj),
            filename=file_name,
            uploader="emos",
            progress=0,
            uploaded_bytes=0,
            total_bytes=file_size,
            speed="",
            status="uploading"
        )

        try:
            cache_key = self._get_cache_key(item_type, item_id, file_path_obj) if enable_resume else None

            print("=== 步骤1: 初始化视频信息 ===")
            step1_result = self.step1_init_video(item_type, item_id)

            # 检查是否有有效的断点续传缓存
            cache_data = None
            if cache_key:
                cache_data = self._load_upload_cache(cache_key, file_path_obj)

            print("\n=== 步骤2: 获取上传凭证 ===")
            step2_result = None

            if cache_data and cache_data.get("step2_result"):
                # 使用缓存的 step2_result（断点续传）
                step2_result = cache_data["step2_result"]
                print("✓ 使用缓存的上传凭证（断点续传）")
            else:
                # 重新获取上传凭证
                step2_result = self.step2_get_upload_token(file_path_obj, file_storage)

            # 检查是否因为资源已存在而跳过
            if step2_result.get("message") == "此资源您之前上传过":
                print(f"检测到文件已存在，跳过后续上传步骤。")
                print(f"如果需要媒体ID，请注意此场景下无法获取新ID。")
                # 清除缓存（如果存在）
                if cache_key:
                    self._clear_upload_cache(cache_key)

                # 报告上传完成（资源已存在）
                _report_upload_progress(
                    file_path=str(file_path_obj),
                    filename=file_name,
                    uploader="emos",
                    progress=100,
                    uploaded_bytes=file_size,
                    total_bytes=file_size,
                    speed="existing resource",
                    status="completed"
                )

                return {"media_uuid": "EXISTING_RESOURCE_SKIPPED", "skipped": True}

            file_id = step2_result["file_id"]

            print("\n=== 步骤3: 上传文件 ===")
            upload_success = self.step3_chunk_upload(
                file_path_obj, step2_result, cache_key=cache_key, resume_from_cache=enable_resume
            )

            # 如果 step3 失败且使用了缓存（file_id 可能过期），清除缓存并重试
            if not upload_success and cache_data and cache_data.get("step2_result"):
                print(f"\n⚠ 使用缓存的 file_id 上传失败，可能是 file_id 已过期")
                print(f"   清除缓存，重新获取上传凭证...")
                self._clear_upload_cache(cache_key)
                print("\n=== 步骤2（重试）: 获取上传凭证 ===")
                step2_result = self.step2_get_upload_token(file_path_obj, file_storage)

                if step2_result.get("message") == "此资源您之前上传过":
                    print(f"检测到文件已存在，跳过后续上传步骤。")
                    if cache_key:
                        self._clear_upload_cache(cache_key)
                    _report_upload_progress(
                        file_path=str(file_path_obj),
                        filename=file_name,
                        uploader="emos",
                        progress=100,
                        uploaded_bytes=file_size,
                        total_bytes=file_size,
                        speed="existing resource",
                        status="completed"
                    )
                    return {"media_uuid": "EXISTING_RESOURCE_SKIPPED", "skipped": True}

                file_id = step2_result["file_id"]
                print("\n=== 步骤3（重试）: 上传文件 ===")
                upload_success = self.step3_chunk_upload(
                    file_path_obj, step2_result, cache_key=cache_key, resume_from_cache=enable_resume
                )

            if not upload_success:
                print("上传未完成，无法进行步骤4")
                # 报告上传失败
                _report_upload_progress(
                    file_path=str(file_path_obj),
                    filename=file_name,
                    uploader="emos",
                    progress=0,
                    uploaded_bytes=0,
                    total_bytes=file_size,
                    speed="",
                    status="failed",
                    error="上传未完成"
                )
                return None

            print("\n=== 步骤4: 确认上传完成 ===")
            step4_result = self.step4_confirm_upload(file_id, item_type, item_id)

            print(f"\n=== 上传完成 ===")
            print(f"视频标题: {step1_result.get('title')}")
            print(f"媒体UUID: {step4_result.get('media_id')}")

            # 上传成功，清除缓存
            if cache_key:
                self._clear_upload_cache(cache_key)

            # 报告上传完成
            _report_upload_progress(
                file_path=str(file_path_obj),
                filename=file_name,
                uploader="emos",
                progress=100,
                uploaded_bytes=file_size,
                total_bytes=file_size,
                speed="",
                status="completed"
            )

            return step4_result

        except Exception as e:
            print(f"上传失败: {e}")

            # 报告上传失败
            _report_upload_progress(
                file_path=str(file_path_obj),
                filename=file_name,
                uploader="emos",
                progress=0,
                uploaded_bytes=0,
                total_bytes=file_size,
                speed="",
                status="failed",
                error=str(e)
            )

            return None


def get_user_input():
    """获取用户输入"""
    print("=== Emos视频上传工具 ===")
    print()

    # 输入文件路径
    while True:
        file_path = input("请输入视频文件路径: ").strip()
        if not file_path:
            print("文件路径不能为空，请重新输入。")
            continue

        file_path = file_path.strip("\"'")  # 去除可能的引号

        if not os.path.exists(file_path):
            print(f"错误: 文件 '{file_path}' 不存在，请重新输入。")
            continue

        if not os.path.isfile(file_path):
            print(f"错误: '{file_path}' 不是文件，请重新输入。")
            continue

        # 检查文件扩展名
        valid_extensions = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}
        file_ext = Path(file_path).suffix.lower()
        if file_ext not in valid_extensions:
            print(
                f"警告: 文件扩展名 '{file_ext}' 可能不是视频文件，支持的格式: {', '.join(valid_extensions)}"
            )
            confirm = input("是否继续上传? (y/n): ").strip().lower()
            if confirm != "y":
                continue

        break

    print()

    # 输入ITEM_TYPE
    while True:
        item_type = input("请输入ITEM_TYPE (默认: ve): ").strip()
        if not item_type:
            item_type = "ve"
            print(f"使用默认值: {item_type}")
            break
        if item_type.strip():
            break
        print("ITEM_TYPE不能为空，请重新输入。")

    print()

    # 输入ITEM_ID
    while True:
        item_id = input("请输入ITEM_ID (默认: 2809377): ").strip()
        if not item_id:
            item_id = "2809377"
            print(f"使用默认值: {item_id}")
            break
        if item_id.strip():
            break
        print("ITEM_ID不能为空，请重新输入。")

    print()

    # 输入文件存储类型
    while True:
        file_storage = (
            input("请输入文件存储类型 (default/internal/global, 默认: default): ")
            .strip()
            .lower()
        )
        if not file_storage:
            file_storage = "default"
            print(f"使用默认值: {file_storage}")
            break
        if file_storage in ["default", "internal", "global"]:
            break
        print("文件存储类型必须是 'default'、'internal' 或 'global'，请重新输入。")

    print()

    return file_path, item_type, item_id, file_storage