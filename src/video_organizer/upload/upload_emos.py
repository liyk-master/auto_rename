import requests
import json
import os
from pathlib import Path
import math
import time
from typing import Optional, Dict, Any
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import datetime
import hashlib


class RobustEmosVideoUploader:
    def __init__(
        self,
        auth_token,
        base_url="https://emos.best",
        chunk_size_mb=50,
        telegram_config=None,
        cache_dir=None,
        cache_expire_hours=1,
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

    def step2_get_upload_token(self, file_path, file_storage="internal", max_retries=3):
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
                print(f"步骤2完成 - 文件ID: {result.get('file_id')}")
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

    def upload_chunk_with_retry(
        self, upload_url, chunk_data, start_byte, end_byte, file_size, max_retries=5
    ):
        """带重试机制的分片上传"""
        chunk_size = len(chunk_data)

        for attempt in range(max_retries):
            try:
                content_range = f"bytes {start_byte}-{end_byte-1}/{file_size}"
                headers = {
                    "Content-Length": str(chunk_size),
                    "Content-Range": content_range,
                    "Content-Type": "application/octet-stream",
                }

                # 记录分片开始时间
                chunk_start_time = time.time()

                # 增加超时时间，特别是对于大文件
                # 使用生成器避免一次性加载到内存
                response = self.session.put(
                    upload_url,
                    headers=headers,
                    data=chunk_data,
                    timeout=600,  # 10分钟超时，因为分片变小了
                )

                status_code = response.status_code

                # 立即关闭响应，避免 _has_decoded_content 错误
                try:
                    response.close()
                except Exception:
                    pass

                if status_code in [200, 201, 202, 308]:
                    # 更新统计信息
                    instant_speed, average_speed, elapsed_time = (
                        self._update_upload_stats(chunk_size, chunk_start_time)
                    )
                    return True, None, instant_speed, average_speed, elapsed_time
                elif status_code == 416:
                    # 416 Range Not Satisfiable: 分片范围无效
                    print(f"✗ 分片范围无效 (416)，可能需要重新获取上传凭证")
                    return False, None, 0, 0, 0
                else:
                    print(f"分片上传失败，状态码: {status_code}")

            except requests.exceptions.SSLError as e:
                print(f"SSL错误 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries - 1:
                    # 优化退避策略：1秒, 2秒, 3秒, 5秒 而不是 1, 2, 4, 8, 16
                    wait_time = min(attempt + 1, 5)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return False, None, 0, 0, 0

            except requests.exceptions.RequestException as e:
                print(f"网络错误 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries - 1:
                    # 优化退避策略
                    wait_time = min(attempt + 1, 5)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return False, None, 0, 0, 0

        return False, None, 0, 0, 0

    def step3_chunk_upload(self, file_path, upload_data, cache_key=None, resume_from_cache=False):
        """步骤3：分片上传文件（支持断点续传）"""
        file_path = Path(file_path)
        upload_url = upload_data["data"]["upload_url"]
        file_size = file_path.stat().st_size

        # 重置上传统计
        self.upload_stats = {
            "total_uploaded": 0,
            "start_time": None,
            "last_update_time": None,
            "last_uploaded": 0,
        }

        # 使用配置的分片大小，已在__init__中限制在10-200MB之间
        chunk_size = self.chunk_size_mb * 1024 * 1024
        total_chunks = math.ceil(file_size / chunk_size)

        # 已上传的分片列表
        uploaded_chunks = []

        # 如果启用断点续传，尝试加载缓存
        if resume_from_cache and cache_key:
            cache_data = self._load_upload_cache(cache_key, file_path)
            if cache_data:
                uploaded_chunks = cache_data.get("uploaded_chunks", [])
                print(f"✓ 检测到断点续传，已上传 {len(uploaded_chunks)}/{total_chunks} 个分片")

        print(f"开始分片上传")
        print(f"文件大小: {self._format_size(file_size)}")
        print(f"分片大小: {self._format_size(chunk_size)}")
        print(f"总分片数: {total_chunks}")
        if uploaded_chunks:
            print(f"已上传分片: {len(uploaded_chunks)}")
        print("-" * 120)

        successful_chunks = 0

        with open(file_path, "rb") as f:
            for chunk_num in range(total_chunks):
                # 跳过已上传的分片
                if chunk_num in uploaded_chunks:
                    successful_chunks += 1
                    print(f"⊘ 分片 {chunk_num + 1}/{total_chunks} 已上传，跳过")
                    continue

                start_byte = chunk_num * chunk_size
                end_byte = min(start_byte + chunk_size, file_size)

                # 读取分片数据
                f.seek(start_byte)
                chunk_data = f.read(chunk_size)
                chunk_data_len = len(chunk_data)

                # 使用带重试的上传
                success, response, instant_speed, average_speed, elapsed_time = (
                    self.upload_chunk_with_retry(
                        upload_url, chunk_data, start_byte, end_byte, file_size
                    )
                )

                # 立即删除 chunk_data，释放内存
                del chunk_data

                if success:
                    successful_chunks += 1
                    uploaded_chunks.append(chunk_num)

                    # 保存缓存（每上传一个分片就保存一次）
                    if cache_key:
                        self._save_upload_cache(cache_key, upload_data, uploaded_chunks, file_path)

                    # 显示实时进度
                    self._print_upload_progress(
                        chunk_num,
                        total_chunks,
                        chunk_data_len,
                        file_size,
                        instant_speed,
                        average_speed,
                        elapsed_time,
                        file_name=file_path.name,
                    )
                    # 发送/更新 Telegram 进度
                    self._send_tg_progress(
                        file_path.name,
                        chunk_num,
                        total_chunks,
                        chunk_data_len,
                        file_size,
                        instant_speed,
                        average_speed,
                        elapsed_time,
                    )
                else:
                    print(f"\n✗ 分片 {chunk_num + 1} 上传失败，跳过后续分片")
                    # 保存当前进度缓存
                    if cache_key:
                        self._save_upload_cache(cache_key, upload_data, uploaded_chunks, file_path)
                    break

                # 添加延迟以避免服务器压力
                time.sleep(0.5)

        # 上传完成，换行显示最终结果
        print()  # 换行
        print("-" * 120)

        if successful_chunks == total_chunks:
            total_time = time.time() - self.upload_stats["start_time"]
            print(f"所有分片上传完成!")
            print(f"总用时: {self._format_time(total_time)}")
            print(f"平均速度: {self._format_speed(file_size / total_time)}")
            return True
        else:
            print(f"上传中断，成功上传 {successful_chunks}/{total_chunks} 个分片")
            return False

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

    def upload_video(self, file_path, item_type, item_id, file_storage="internal", enable_resume=True):
        """完整的上传流程（支持断点续传）"""
        try:
            file_path = Path(file_path)
            cache_key = self._get_cache_key(item_type, item_id, file_path) if enable_resume else None

            print("=== 步骤1: 初始化视频信息 ===")
            step1_result = self.step1_init_video(item_type, item_id)

            # 检查是否有有效的断点续传缓存
            cache_data = None
            if cache_key:
                cache_data = self._load_upload_cache(cache_key, file_path)

            print("\n=== 步骤2: 获取上传凭证 ===")
            step2_result = None

            if cache_data and cache_data.get("step2_result"):
                # 使用缓存的 step2_result（断点续传）
                step2_result = cache_data["step2_result"]
                print("✓ 使用缓存的上传凭证（断点续传）")
            else:
                # 重新获取上传凭证
                step2_result = self.step2_get_upload_token(file_path, file_storage)

            # 检查是否因为资源已存在而跳过
            if step2_result.get("message") == "此资源您之前上传过":
                print(f"检测到文件已存在，跳过后续上传步骤。")
                print(f"如果需要媒体ID，请注意此场景下无法获取新ID。")
                # 清除缓存（如果存在）
                if cache_key:
                    self._clear_upload_cache(cache_key)
                return {"media_uuid": "EXISTING_RESOURCE_SKIPPED", "skipped": True}

            file_id = step2_result["file_id"]

            print("\n=== 步骤3: 分片上传文件 ===")
            upload_success = self.step3_chunk_upload(
                file_path, step2_result, cache_key=cache_key, resume_from_cache=enable_resume
            )

            if not upload_success:
                print("分片上传未完成，无法进行步骤4")
                return None

            print("\n=== 步骤4: 确认上传完成 ===")
            step4_result = self.step4_confirm_upload(file_id, item_type, item_id)

            print(f"\n=== 上传完成 ===")
            print(f"视频标题: {step1_result.get('title')}")
            print(f"媒体UUID: {step4_result.get('media_id')}")

            # 上传成功，清除缓存
            if cache_key:
                self._clear_upload_cache(cache_key)

            return step4_result

        except Exception as e:
            print(f"上传失败: {e}")
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
            input("请输入文件存储类型 (internal/global, 默认: internal): ")
            .strip()
            .lower()
        )
        if not file_storage:
            file_storage = "internal"
            print(f"使用默认值: {file_storage}")
            break
        if file_storage in ["internal", "global"]:
            break
        print("文件存储类型必须是 'internal' 或 'global'，请重新输入。")

    print()

    return file_path, item_type, item_id, file_storage


# def main():
#     # 配置认证令牌
#     AUTH_TOKEN = ""

#     try:
#         # 获取用户输入
#         file_path, item_type, item_id, file_storage = get_user_input()

#         # 显示确认信息
#         print("=== 上传配置 ===")
#         print(f"文件路径: {file_path}")
#         print(f"文件大小: {RobustEmosVideoUploader(None)._format_size(Path(file_path).stat().st_size)}")
#         print(f"ITEM_TYPE: {item_type}")
#         print(f"ITEM_ID: {item_id}")
#         print(f"文件存储: {file_storage}")
#         print()

#         # 确认上传
#         confirm = input("确认开始上传? (y/n): ").strip().lower()
#         if confirm != 'y':
#             print("上传已取消。")
#             return

#         print()

#         # 使用增强版上传器
#         uploader = RobustEmosVideoUploader(AUTH_TOKEN)
#         result = uploader.upload_video(file_path, item_type, item_id, file_storage)

#         if result:
#             print("\n🎉 视频上传成功!")
#         else:
#             print("\n❌ 视频上传失败!")

#     except KeyboardInterrupt:
#         print("\n\n上传被用户中断。")
#     except Exception as e:
#         print(f"\n发生错误: {e}")

# if __name__ == "__main__":
#     main()
