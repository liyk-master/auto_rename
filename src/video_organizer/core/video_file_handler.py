import os
import shutil
import requests
import threading
from queue import Queue, Empty
from pathlib import Path
from typing import Dict, List, Optional, Any

# 导入项目内部的上传工具
from ..upload.upload_emos import RobustEmosVideoUploader

from .renamer import VideoRenamer
from .tmdb_client import TMDBClient
from ..utils.logging_utils import get_logger, log_success, log_failure, log_exception


class VideoFileHandler:
    """
    视频文件处理器，用于处理文件系统事件
    """
    
    def __init__(self,
                 output_dir: str,
                 supported_extensions: List[str],
                 naming_rules: Optional[Dict[str, str]] = None,
                 tmdb_config: Optional[Dict[str, Any]] = None,
                 emos_config: Optional[Dict[str, Any]] = None,
                 p123_config: Optional[Dict[str, Any]] = None,
                 processing_config: Optional[Dict[str, Any]] = None,
                 path_mappings: Optional[Dict[str, str]] = None,
                 telegram_config: Optional[Dict[str, Any]] = None,
                 llm_config: Optional[Dict[str, Any]] = None):
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
            llm_config: LLM 翻译配置
        """
        # 初始化日志记录器
        self.logger = get_logger(__name__)
        
        self.output_dir = output_dir
        self.supported_extensions = supported_extensions
        self.path_mappings = path_mappings or {}
        
        # 初始化处理配置
        self.processing_config = processing_config or {}
        self.delete_after_upload = self.processing_config.get('delete_after_upload', False)
        # 清理配置值中的行内注释
        raw_targets = self.processing_config.get('upload_targets', 'emos')
        self.upload_targets = str(raw_targets).split('#')[0].split(';')[0].strip()  # emos, p123, both
        
        # 初始化Emos配置
        # 初始化Emos配置
        self.emos_config = emos_config or {}
        raw_token = self.emos_config.get('auth_token', '')
        self.emos_auth_token = str(raw_token).split('#')[0].split(';')[0].strip()
        self.emos_base_url = self.emos_config.get('base_url', 'https://emos.lol')
        self.emos_file_storage = self.emos_config.get('file_storage', 'internal')  # internal 或 global
        self.emos_chunk_size_mb = self.emos_config.get('chunk_size_mb', 50)  # 分片大小(MB)，默认50
        self.max_upload_workers = int(self.processing_config.get('max_upload_workers', 1)) # 并发上传数
        
        # 初始化 123 云盘配置
        self.p123_config = p123_config or {}
        raw_p123_token = self.p123_config.get('token', '')
        self.p123_token = str(raw_p123_token).split('#')[0].split(';')[0].strip()
        self.p123_parent_id = int(self.p123_config.get('parent_id', 0))
        
        # 初始化 Telegram 配置
        self.telegram_config = telegram_config or {}
        
        # 初始化TMDB客户端
        tmdb_client = None
        if tmdb_config and tmdb_config.get('api_key'):
            try:
                tmdb_client = TMDBClient(
                    api_key=tmdb_config['api_key'],
                    retry_count=tmdb_config.get('retry_count', 3),
                    timeout=tmdb_config.get('timeout', 30)
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
                    telegram_config=self.telegram_config
                )
                self.logger.info("123云盘上传器初始化成功")
            except Exception as e:
                self.logger.error(f"初始化123云盘上传器失败: {e}")
        
        # 初始化文件重命名器
        try:
            # 从配置中获取TMDB API密钥
            tmdb_api_key = tmdb_config.get('api_key') if tmdb_config else None
            self.renamer = VideoRenamer(
                tmdb_api_key=tmdb_api_key,
                naming_rules=naming_rules,
                llm_config=llm_config
            )
            self.logger.info("视频重命名器初始化成功")
        except Exception as e:
            log_exception(self.logger, "初始化视频重命名器失败")
            # 创建一个基本的重命名器作为后备
            self.renamer = VideoRenamer(tmdb_api_key=None)
        
        # 父监控器引用
        self._parent_monitor = None
        
        # 处理中的文件，用于跟踪文件写入完成状态
        self._processing_files = set()
        
        # 上传状态跟踪，用于防止重复上传
        self._uploading_files = set()  # 正在上传的文件
        self._uploaded_files = set()   # 已成功上传的文件
        self._failed_files = {}        # 失败的文件及原因
        self._max_set_size = 1000      # 限制集合大小，防止内存溢出
        self._file_downloader_map = {}  # 文件到下载器的映射，用于删除下载任务
        
        # 上传队列配置
        self._upload_queue = Queue()   # 上传队列
        self._use_queue = True         # 是否使用队列（可配置）
        self._queue_running = False    # 队列运行标志
        self._queue_thread = None      # 队列处理线程
        
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
                self.logger.debug(f"文件已在上传中或已上传，跳过修改事件处理: {file_path}")
                return
            
            # 对于修改事件，检查文件是否已完成写入
            if not file_path in self._processing_files and self._is_file_complete(file_path):
                self._process_file(file_path)
    
    def _is_supported_file(self, file_path: str) -> bool:
        """
        检查文件是否为支持的视频文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            是否为支持的视频文件
        """
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            return file_ext in self.supported_extensions
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
                with open(file_path, 'rb') as f:
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
                    thread = threading.Thread(target=self._worker_process_queue, args=(i+1,), daemon=True)
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
                print(f"\n{'='*80}")
                print(f"📋 工作线程 #{worker_id} 开始处理任务")
                print(f"当前任务: {os.path.basename(file_path)}")
                print(f"剩余任务: {queue_size}")
                print(f"{'='*80}")
                
                try:
                    self._process_file_internal(file_path, worker_id)
                except Exception as e:
                    self.logger.error(f"工作线程 #{worker_id} 处理文件失败: {file_path}, 错误: {e}")
                finally:
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
            print(f"\n{'='*80}")
            print(f"📤 开始上传视频")
            print(f"文件: {file_path}")
            print(f"类型: {matched_item_type}")
            print(f"项目ID: {matched_item_id}")
            print(f"{'='*80}\n")
            
            uploader = RobustEmosVideoUploader(self.emos_auth_token, chunk_size_mb=int(self.emos_chunk_size_mb))
            upload_result = uploader.upload_video(file_path, matched_item_type, str(matched_item_id), self.emos_file_storage)
            
            if upload_result:
                print(f"\n🎉 视频上传成功!")
                # 从上传中集合移除，添加到已上传集合
                self._uploaded_files.add(file_path)
                
                # 如果配置了上传后删除文件，执行删除操作
                if self.delete_after_upload:
                    try:
                        os.remove(file_path)
                        print(f"✅ 上传成功后已删除原文件: {file_path}")
                        self.logger.info(f"上传成功后已删除原文件: {file_path}")
                        
                        # 删除下载任务 (使用统一的清理方法，支持反向映射和多下载器)
                        self._cleanup_download_task(file_path)
                    except Exception as e:
                        print(f"❌ 上传成功后删除原文件失败: {e}")
                        self.logger.error(f"上传成功后删除原文件失败: {file_path}, 错误: {e}")
            else:
                print(f"\n❌ 视频上传失败!")
        except Exception as e:
            print(f"\n❌ 视频上传过程中发生错误: {e}")
        finally:
            # 无论上传结果如何，从上传中集合移除
            self._uploading_files.remove(file_path)
    
    def _process_file(self, file_path: str) -> bool:
        """
        处理视频文件
        Args:
            file_path: 文件路径
        """
        if not os.path.exists(file_path):
            self.logger.warning(f"文件不存在: {file_path}")
            return False
        
        # 检查文件是否已经在上传中或已上传，避免重复处理
        if file_path in self._uploading_files or file_path in self._uploaded_files:
            self.logger.debug(f"文件已在上传中或已上传，跳过处理: {file_path}")
            return True
        
        # 检查文件是否正在处理中（API调用阶段）
        if file_path in self._processing_files:
            self.logger.debug(f"文件正在处理中，跳过: {file_path}")
            return True
        
        # 检查文件是否完整且可访问
        if not self._is_file_complete(file_path):
            self.logger.debug(f"文件未完成或被锁定，跳过处理: {file_path}")
            # 如果有父监控器，可以将文件添加到重试队列
            if self._parent_monitor:
                self._parent_monitor._pending_files.add(file_path)
            return False
        
        # 标记为处理中
        self._processing_files.add(file_path)
        
        if self._use_queue:
            # 放入队列异步处理
            self._upload_queue.put(file_path)
            
            queue_size = self._upload_queue.qsize()
            print(f"\n✅ 已加入处理队列: {os.path.basename(file_path)}")
            print(f"   当前队列长度: {queue_size}")
            print(f"   工作线程数: {self.max_upload_workers}")
            
            return True
        else:
            # 同步直接处理
            return self._process_file_internal(file_path)

    def _process_file_internal(self, file_path, worker_id=0):
        """
        内部文件处理逻辑（包含元数据获取、API调用、上传）
        """
        print(f"\n🔍 [线程#{worker_id}] 开始深入处理文件: {file_path}")
        
        try:
            # 第一步：获取视频的tmdbid和media_type (使用本地 Renamer + TMDB Client)
            print(f"正在本地分析文件元数据: {os.path.basename(file_path)}")
            
            # 使用 VideoRenamer 提取元数据 (包含 Regex 解析和 TMDB 搜索)
            # 注意: 这里使用 extract_metadata 会自动调用 _enrich_with_tmdb
            metadata = self.renamer.extract_metadata(file_path)
            
            print(f"✓ [线程#{worker_id}] 本地识别完成")
            
            # 提取所需信息
            tmdb_id = str(metadata.get('tmdb_id', ''))
            media_type = metadata.get('media_type', 'tv') # 默认为 tv, renamer 会返回 'tv' 或 'movie'
            
            # 标题处理：优先使用 title (电影) 或 show_name (剧集)
            title = metadata.get('title') or metadata.get('show_name') or metadata.get('original_filename', '')
            
            # 季集信息处理
            season = metadata.get('season')
            episode = metadata.get('episode')
            season_episode = ""
            
            if season is not None and episode is not None:
                try:
                    # 尝试格式化为 SxxExx
                    s_num = int(season)
                    e_num = int(episode)
                    season_episode = f"S{s_num:02d}E{e_num:02d}"
                except:
                    # 如果转换整数失败，直接拼接
                    season_episode = f"S{season}E{episode}"
            
            # 输出获取到的信息
            print(f"\n[线程#{worker_id}] 文件信息 (本地识别):")
            print(f"  文件: {os.path.basename(file_path)}")
            print(f"  TMDB ID: {tmdb_id}")
            print(f"  媒体类型: {media_type}")
            print(f"  标题: {title}")
            print(f"  季集: {season_episode}")

            # 兼容性处理: 原有逻辑可能依赖 "电视剧" 这样的中文类型，但 Renamer 返回 "tv"/"movie"
            # 下面的逻辑原本是: media_type = "tv" if media_type == "电视剧" else "movie"
            # 现在 renamer 直接返回标准代码，所以我们只需确保它是 tv 或 movie
            if media_type not in ['tv', 'movie']:
                # 如果是 anime 或其他，归类为 tv
                 media_type = 'tv'
            
            # 初始化匹配结果
            matched_item_id = None
            matched_item_type = None
            
            # 第二步：如果获取到了tmdb_id、type、title，且需要使用 Emos (非仅 p123)，调用第二个API
            if tmdb_id and media_type and title and self.upload_targets != 'p123':
                # print(f"\n正在调用第二个API获取ItemId...")
                # item_id_url = f"{self.emos_base_url}/api/video/getItemId?type={media_type}&title={title}&tmdb_id={tmdb_id}"
                item_id_url = f"{self.emos_base_url}/api/video/getItemId?tmdb_id={tmdb_id}"
                
                # 定义 Emos API headers
                headers = {
                    'accept': '*/*',
                    'accept-language': 'zh-CN,zh;q=0.9',
                    'authorization': f'Bearer {self.emos_auth_token}',
                    'origin': 'https://emos.prlo.de',
                    'priority': 'u=1, i',
                    'referer': 'https://emos.prlo.de/',
                    'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'same-site',
                    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'
                }
                
                headers2 = headers.copy()
                headers2.update({
                    'sec-fetch-site': 'cross-site',
                })
                
                # 发送请求
                response2 = requests.get(item_id_url, headers=headers2)
                response2.raise_for_status()  # 检查请求是否成功
                result2 = response2.json()
                
                # print(f"✓ 第二个API请求成功")
                
                # 解析季集信息并匹配对应的item_id
                # 解析季集信息并匹配对应的item_id
                
                if media_type == "movie" and result2:
                    # 电影匹配逻辑：通常result2中直接包含电影信息，或者是一个包含电影信息的列表
                    for item in result2:
                        # 有些API返回的video_type可能是 "movie" 或者没写，我们要灵活判断
                        # 如果TMDB ID匹配（如果API返回了TMDB ID），或者直接取第一个看起来像电影的结果
                        v_type = item.get("video_type")
                        if v_type == "movie" or (not v_type and item.get("item_id")):
                            matched_item_id = item.get("item_id")
                            matched_item_type = item.get("item_type")
                            
                            # 检查是否有medias列表（用户提供的case）
                            medias = item.get("medias", [])
                            if medias and not matched_item_id:
                                # 如果顶层没有item_id，尝试从medias取第一个（虽然通常medias是具体文件，item_id是条目ID）
                                # 用户提供的json显示顶层有item_id: 218374
                                pass
                            
                            if matched_item_id:
                                print(f"✓ [线程#{worker_id}] 电影匹配成功！item_id: {matched_item_id}")
                                break
                                
                elif season_episode and result2:
                    # 电视剧匹配逻辑
                    # 解析季集字符串，例如 "S01 E11" -> (1, 11)
                    try:
                        # 移除空格并分割
                        parts = season_episode.replace(" ", "").upper().split("E")
                        if len(parts) == 2 and parts[0].startswith("S"):
                            season_num = int(parts[0][1:])
                            episode_num = int(parts[1])
                            
                            # print(f"\n正在匹配季集 S{season_num:02d}E{episode_num:02d} 的item_id...")
                            
                            # 遍历第二个API返回的结果，查找匹配的季集
                            for item in result2:
                                if item.get("video_type") == "tv":
                                    seasons = item.get("seasons", [])
                                    if not seasons:
                                        # 有时候可能没有seasons字段，检查是否直接匹配（不太常见但防御性编程）
                                        continue
                                        
                                    for season in seasons:
                                        if season.get("season_number") == season_num:
                                            episodes = season.get("episodes", [])
                                            for episode in episodes:
                                                if episode.get("episode_number") == episode_num:
                                                    matched_item_id = episode.get("item_id")
                                                    matched_item_type = episode.get("item_type")
                                                    if matched_item_id and matched_item_type:
                                                        print(f"✓ [线程#{worker_id}] 剧集匹配成功！item_id: {matched_item_id}")
                                                        break
                                            if matched_item_id:
                                                break
                                    if matched_item_id:
                                        break
                    except Exception as e:
                        print(f"✗ [线程#{worker_id}] 解析季集信息时出错: {e}")
                
                # if not matched_item_id:
                #     print(f"✗ [线程#{worker_id}] 未找到匹配的item_id")
                
            # 步骤4：决定是否需要上传
            # 如果只上传到123云盘，不需要 item_id，可以直接上传
            if self.upload_targets == 'p123':
                # 只上传到123，不需要 Emos 的 item_id
                print(f"✓ [线程#{worker_id}] 配置为仅上传到123云盘，跳过Emos匹配")
                self._execute_upload(file_path, media_type, None, worker_id, 
                                    tmdb_id, media_type, title, season_episode, metadata)
            elif matched_item_id:
                print(f"✓ [线程#{worker_id}] 找到匹配的item_id: {matched_item_id}")
                # 需要上传到 Emos 或两者，必须有 item_id
                self._execute_upload(file_path, matched_item_type, matched_item_id, worker_id, 
                                    tmdb_id, media_type, title, season_episode, metadata)
            else:
                # 需要 Emos 但没有 item_id
                self._failed_files[file_path] = "未找到匹配的item_id"
                log_success(self.logger, "文件元数据获取成功但未匹配到item_id", {
                        "original_path": file_path, "tmdb_id": tmdb_id, "media_type": media_type,
                        "title": title, "season_episode": season_episode
                })
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
            print(f"\n✗ API请求失败: {e}")
            
            # 记录失败原因
            self._failed_files[file_path] = f"API请求失败: {str(e)}"
            
            # 如果有父监控器，可以将文件添加到重试队列
            if self._parent_monitor:
                self.logger.info(f"将文件添加到重试队列: {file_path}")
                self._parent_monitor._retry_files.add(file_path)
        finally:
            # 从处理中集合移除
            self._processing_files.discard(file_path)

    def _execute_upload(self, file_path, matched_item_type, matched_item_id, worker_id, 
                       tmdb_id, media_type, title, season_episode, metadata):
        """执行具体的上传操作（支持多云盘）"""
        print(f"\n=== [线程#{worker_id}] 开始上传视频 ===")
        
        # 检查文件是否已经上传完成
        if file_path in self._uploaded_files:
            print(f"✗ [线程#{worker_id}] 文件已上传完成，跳过: {file_path}")
            return

        # 添加到上传中集合
        self._uploading_files.add(file_path)
        
        # 准备媒体信息（用于123云盘创建文件夹）
        media_info = {
            'title': title,
            'season_episode': season_episode,
            'tmdb_id': tmdb_id,
            'media_type': media_type
        }
        
        # 根据配置决定上传到哪些云盘
        upload_results = {}
        
        try:
            # 1. 上传到 Emos
            if self.upload_targets in ['emos', 'both']:
                print(f"\n{'='*60}")
                print(f"📤 [线程#{worker_id}] 上传到 Emos")
                print(f"类型: {matched_item_type}")
                print(f"项目ID: {matched_item_id}")
                print(f"{'='*60}\n")
                
                if not self.emos_auth_token:
                    print(f"✗ [线程#{worker_id}] 未配置Emos认证令牌，跳过Emos上传")
                    upload_results['emos'] = None
                else:
                    try:
                        from ..upload.upload_emos import RobustEmosVideoUploader
                        uploader = RobustEmosVideoUploader(
                            self.emos_auth_token, 
                            chunk_size_mb=int(self.emos_chunk_size_mb),
                            telegram_config=self.telegram_config
                        )
                        upload_results['emos'] = uploader.upload_video(
                            file_path, matched_item_type, str(matched_item_id), self.emos_file_storage
                        )
                        
                        if upload_results['emos']:
                            print(f"\n🎉 [线程#{worker_id}] Emos上传成功!")
                        else:
                            print(f"\n❌ [线程#{worker_id}] Emos上传失败!")
                    except Exception as e:
                        print(f"\n❌ [线程#{worker_id}] Emos上传异常: {e}")
                        upload_results['emos'] = None
            
            # 2. 上传到 123云盘
            if self.upload_targets in ['p123', 'both']:
                print(f"\n{'='*60}")
                print(f"📤 [线程#{worker_id}] 上传到 123云盘")
                print(f"{'='*60}\n")
                
                if not self.p123_token:
                    print(f"✗ [线程#{worker_id}] 未配置123云盘Token，跳过123上传")
                    upload_results['p123'] = None
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
                                telegram_config=self.telegram_config
                            )
                        
                        # 生成标准化路径（包含文件夹结构和新文件名）
                        # 例如: Show Name (2023) {tmdbid=123}/Season 01/Show Name S01E01.mkv
                        try:
                            # 复用本函数开头已经提取好的 metadata
                            renamed_relative_path = self.renamer.generate_new_path(metadata, original_path=file_path)
                            
                            # 获取重命名后的文件名
                            target_filename = renamed_relative_path.name
                            
                            # 获取目录结构列表
                            folder_parts = list(renamed_relative_path.parent.parts)
                            
                            # 构建完整目录结构
                            base_folders = ["media"]
                            if media_type == "movie":
                                base_folders.append("Movies")
                            else:
                                base_folders.append("TV Shows")
                            
                            # 合并目录结构
                            folder_structure = base_folders + folder_parts
                            
                            print(f"[线程#{worker_id}] 标准化重命名计划: {os.path.basename(file_path)} -> {renamed_relative_path}")
                            print(f"[线程#{worker_id}] 网盘目录结构: {' -> '.join(folder_structure)}")
                            
                        except Exception as e:
                            print(f"生成标准化路径失败: {e}，使用默认命名")
                            target_filename = os.path.basename(file_path)
                            folder_structure = None

                        upload_results['p123'] = uploader.upload_video(
                            file_path, media_type, str(matched_item_id), 
                            None, media_info,
                            rename_to=target_filename,
                            folder_structure=folder_structure
                        )
                        
                        if upload_results['p123']:
                            print(f"\n🎉 [线程#{worker_id}] 123云盘上传成功!")
                        else:
                            print(f"\n❌ [线程#{worker_id}] 123云盘上传失败!")
                    except Exception as e:
                        print(f"\n❌ [线程#{worker_id}] 123云盘上传异常: {e}")
                        import traceback
                        traceback.print_exc()
                        upload_results['p123'] = None
            
            # 3. 判断是否所有目标云盘都上传成功
            required_targets = []
            if self.upload_targets == 'emos':
                required_targets = ['emos']
            elif self.upload_targets == 'p123':
                required_targets = ['p123']
            elif self.upload_targets == 'both':
                required_targets = ['emos', 'p123']
            
            # 检查所有必需的上传是否都成功
            all_success = all(upload_results.get(target) is not None for target in required_targets)
            
            if all_success:
                print(f"\n🎉 [线程#{worker_id}] 所有云盘上传成功!")
                # 从上传中集合移除，添加到已上传集合
                self._uploaded_files.add(file_path)
                self._uploading_files.discard(file_path)
                
                # 如果配置了上传后删除文件，执行删除操作
                deleted = False
                if self.delete_after_upload:
                    try:
                        os.remove(file_path)
                        print(f"✅ [线程#{worker_id}] 所有云盘上传成功后已删除原文件")
                        self.logger.info(f"所有云盘上传成功后已删除原文件: {file_path}")
                        deleted = True
                    except Exception as e:
                        print(f"❌ [线程#{worker_id}] 删除原文件失败: {e}")
                        self.logger.error(f"删除原文件失败: {file_path}, 错误: {e}")
                
                # 删除下载任务
                self._cleanup_download_task(file_path)

                # 更新日志
                log_success(self.logger, "文件元数据获取并上传成功", {
                    "original_path": file_path, "tmdb_id": tmdb_id, "media_type": media_type,
                    "title": title, "season_episode": season_episode, "matched_item_id": matched_item_id,
                    "upload_success": True, 
                    "upload_targets": self.upload_targets,
                    "emos_uuid": upload_results.get('emos', {}).get("media_uuid") if upload_results.get('emos') else None,
                    "p123_fileid": upload_results.get('p123', {}).get("fileid") if upload_results.get('p123') else None,
                    "deleted_after_upload": deleted
                })
                
                # 清理旧记录防止内存泄露
                self._cleanup_old_records()
                
            else:
                # 部分上传失败
                failed_targets = [t for t in required_targets if not upload_results.get(t)]
                print(f"\n❌ [线程#{worker_id}] 部分云盘上传失败: {', '.join(failed_targets)}")
                print(f"⚠️  [线程#{worker_id}] 保留本地文件，等待重试或手动处理")
                self._uploading_files.discard(file_path)
                log_success(self.logger, "文件元数据获取成功但部分云盘上传失败", {
                    "original_path": file_path, "tmdb_id": tmdb_id, "media_type": media_type,
                    "title": title, "season_episode": season_episode, "matched_item_id": matched_item_id,
                    "upload_success": False,
                    "failed_targets": failed_targets
                })
        except Exception as e:
            print(f"\n❌ [线程#{worker_id}] 视频上传错误: {e}")
            self._uploading_files.discard(file_path)
            log_success(self.logger, "文件元数据获取成功但上传出错", {
                "original_path": file_path, "tmdb_id": tmdb_id, "media_type": media_type,
                "title": title, "season_episode": season_episode, "matched_item_id": matched_item_id,
                "upload_success": False, "error": str(e)
            })
                
    
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

        # 检查文件是否不支持
        if not self._is_supported_file(file_path):
             # log_failure(self.logger, f"不支持的文件类型: {file_path}")
             # return False
             pass
        
        # 标记为处理中
        self._processing_files.add(file_path)
        
        if self._use_queue:
            # 放入队列异步处理
            self._upload_queue.put(file_path)
            
            queue_size = self._upload_queue.qsize()
            print(f"\n✅ 已加入处理队列: {os.path.basename(file_path)}")
            print(f"   当前队列长度: {queue_size}")
            print(f"   工作线程数: {self.max_upload_workers}")
            
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
        file_path = file_path.replace('\\', '/')
        
        print(f"DEBUG: 尝试反向映射路径: {file_path}")
        print(f"DEBUG: 当前映射配置: {self.path_mappings}")
        
        for downloader_path, local_path in self.path_mappings.items():
            # 规范化本地映射路径
            local_path = local_path.replace('\\', '/')
            
            # 如果文件路径以本地映射路径开头
            if file_path.startswith(local_path):
                # 替换为下载器路径
                rel_path = file_path[len(local_path):].lstrip('/')
                # 拼接下载器路径 (注意 downloader_path 结尾可能有也可能没有 /)
                new_path = f"{downloader_path.rstrip('/')}/{rel_path}"
                self.logger.debug(f"反向路径映射: {file_path} -> {new_path}")
                print(f"DEBUG: 映射成功: {new_path}")
                return new_path
        
        print(f"DEBUG: 未找到匹配的映射路径")
        return file_path
    
    def _cleanup_download_task(self, file_path):
        """
        从下载器中删除对应的下载任务
        
        Args:
            file_path: 文件路径 (本地路径)
        """
        # 反向映射路径，因为下载器使用的是它自己的路径系统
        downloader_file_path = self._reverse_apply_path_mapping(file_path)
        
        task_removed = False
        
        # 1. 尝试从映射中查找下载器
        if file_path in self._file_downloader_map:
            try:
                downloader = self._file_downloader_map[file_path]
                if hasattr(downloader, 'remove_download'):
                    # 尝试使用原始路径和映射后的路径
                    if downloader.remove_download(file_path) or (file_path != downloader_file_path and downloader.remove_download(downloader_file_path)):
                        print(f"✅ 已从下载器中删除任务")
                        self.logger.info(f"已从下载器中删除任务: {file_path}")
                        task_removed = True
                # 清理映射
                del self._file_downloader_map[file_path]
            except Exception as e:
                self.logger.error(f"从映射的下载器删除任务失败: {e}")
        
        if task_removed:
            return

        # 2. 如果映射中没有或删除失败，尝试遍历所有注册的下载器
        # 这在 --process 模式下很有用，因为那时文件可能没有被添加到映射中
        if self.downloaders:
            for downloader in self.downloaders:
                try:
                    if hasattr(downloader, 'remove_download'):
                        if downloader.remove_download(downloader_file_path):
                            print(f"✅ 已从下载器中删除任务 (遍历查找)")
                            self.logger.info(f"已从下载器中删除任务 (遍历查找): {downloader_file_path}")
                            return
                except Exception as e:
                    self.logger.warning(f"尝试从下载器删除任务时出错: {e}")
        
        if not task_removed:
            print(f"⚠️ 未能从下载器删除任务 (未找到匹配任务): {downloader_file_path}")
            self.logger.debug(f"未能从下载器删除任务: {file_path} -> {downloader_file_path}")

    def _cleanup_old_records(self):
        """清理旧的处理记录，防止内存溢出"""
        try:
            # 清理已上传文件记录
            if len(self._uploaded_files) > self._max_set_size:
                old_size = len(self._uploaded_files)
                # 保留最近的一半
                self._uploaded_files = set(list(self._uploaded_files)[-(self._max_set_size // 2):])
                self.logger.info(f"清理已上传文件记录: {old_size} -> {len(self._uploaded_files)}")
            
            # 清理失败文件记录
            if len(self._failed_files) > self._max_set_size:
                old_size = len(self._failed_files)
                items = list(self._failed_files.items())[-(self._max_set_size // 2):]
                self._failed_files = dict(items)
                self.logger.info(f"清理失败文件记录: {old_size} -> {len(self._failed_files)}")
                
            # 清理处理中记录 (防止僵尸记录)
            # 注意：这里需要谨慎，因为正在处理的文件也在这个集合中
            # 一般不需要自动清理，除非确定它已经是僵尸了。这里暂时不自动清理 processing_files
        except Exception as e:
            self.logger.error(f"清理旧记录时出错: {e}")

