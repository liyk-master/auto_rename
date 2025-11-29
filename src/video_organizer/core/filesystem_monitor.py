"""
File system monitoring module using watchdog.
"""

import logging
import time
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Dict, Optional

from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.core.file_mover import FileMover

logger = logging.getLogger(__name__)


class VideoFileHandler(FileSystemEventHandler):
    """Handler for new video file events."""
    
    def __init__(self, renamer, file_mover, supported_extensions, output_dir):
        self.renamer = renamer
        self.file_mover = file_mover
        self.supported_extensions = supported_extensions
        self.output_dir = output_dir  # 添加output_dir属性
        self._parent_monitor = None  # 引用到父监控器实例
        
    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            path_str = event.src_path
            if isinstance(path_str, bytes):
                path_str = os.fsdecode(path_str)
            file_path = Path(path_str)
            if file_path.suffix.lower() in self.supported_extensions:
                # 检查文件是否已处理
                if hasattr(self, '_parent_monitor'):
                    if str(file_path) in self._parent_monitor.processed_files:
                        logger.debug(f"File already processed, skipping: {file_path}")
                        return
                
                logger.info(f"New video file detected: {file_path}")
                # 使用延迟处理，确保文件完全写入
                import threading
                def delayed_process():
                    try:
                        # 等待文件写入完成
                        if hasattr(self._parent_monitor, '_is_file_complete'):
                            if self._parent_monitor._is_file_complete(file_path):
                                self.process_file(file_path)
                                if hasattr(self, '_parent_monitor'):
                                    self._parent_monitor.processed_files.add(str(file_path))
                        else:
                            # 如果没有_is_file_complete方法，直接处理
                            time.sleep(2)  # 简单延迟
                            self.process_file(file_path)
                    except Exception as e:
                        logger.error(f"Error in delayed processing: {e}")
                
                threading.Thread(target=delayed_process).start()
    
    def process_file(self, file_path):
        """Process a newly created video file."""
        try:
            # Extract enhanced metadata for Emby
            metadata = self.extract_enhanced_metadata(file_path)
            new_path = self.renamer.generate_new_path(metadata, original_path=file_path, output_dir=self.output_dir)
            
            # Move file to new location
            final_path = self.file_mover.move_file(file_path, new_path)
            
            # Generate Emby metadata files
            # 使用完整路径生成元数据文件
            self.generate_emby_metadata(final_path, metadata)
            
            logger.info(f"Successfully processed and moved {file_path} to {new_path}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
    
    def extract_enhanced_metadata(self, file_path: Path) -> Dict:
        """Extract enhanced metadata for Emby compatibility."""
        # Get basic metadata from renamer
        metadata = self.renamer.extract_metadata(file_path)
        
        # Enhance with additional Emby-specific fields
        if metadata.get('tmdb_id'):
            try:
                # Get detailed show information
                show_details = self.renamer.tmdb_client.get_media_show_details(
                    metadata['tmdb_id'], 
                    metadata.get('media_type', 'tv')
                )
                
                if show_details:
                    # Add comprehensive metadata for Emby
                    metadata.update({
                        'overview': show_details.get('overview', ''),
                        'genres': [genre['name'] for genre in show_details.get('genres', [])],
                        'networks': [network['name'] for network in show_details.get('networks', [])],
                        'created_by': [creator['name'] for creator in show_details.get('created_by', [])],
                        'production_companies': [company['name'] for company in show_details.get('production_companies', [])],
                        'origin_country': show_details.get('origin_country', []),
                        'original_language': show_details.get('original_language', ''),
                        'vote_average': show_details.get('vote_average', 0),
                        'vote_count': show_details.get('vote_count', 0),
                        'popularity': show_details.get('popularity', 0),
                        'status': show_details.get('status', ''),
                        'tagline': show_details.get('tagline', ''),
                        'poster_path': show_details.get('poster_path', ''),
                        'backdrop_path': show_details.get('backdrop_path', ''),
                        'homepage': show_details.get('homepage', '')
                    })
                    
                    # Get episode-specific metadata if available
                    if metadata.get('season') and metadata.get('episode'):
                        season_details = self.renamer.tmdb_client.get_season_details(
                            metadata['tmdb_id'], int(metadata['season'])
                        )
                        if season_details and season_details.get('episodes'):
                            episode_number = int(metadata['episode'])
                            if episode_number <= len(season_details['episodes']):
                                episode = season_details['episodes'][episode_number - 1]
                                metadata.update({
                                    'episode_overview': episode.get('overview', ''),
                                    'episode_air_date': episode.get('air_date', ''),
                                    'episode_vote_average': episode.get('vote_average', 0),
                                    'episode_vote_count': episode.get('vote_count', 0),
                                    'episode_still_path': episode.get('still_path', ''),
                                    'guest_stars': [cast['name'] for cast in episode.get('guest_stars', [])],
                                    'crew': episode.get('crew', [])
                                })
                    
                    # Get cast and crew information
                    credits = self.renamer.tmdb_client.get_tv_credits(metadata['tmdb_id'])
                    if credits:
                        metadata.update({
                            'cast': [{
                                'name': actor['name'],
                                'character': actor.get('character', ''),
                                'profile_path': actor.get('profile_path', '')
                            } for actor in credits.get('cast', [])[:10]],  # Limit to top 10
                            'crew': [{
                                'name': crew['name'],
                                'job': crew.get('job', ''),
                                'department': crew.get('department', '')
                            } for crew in credits.get('crew', []) if crew.get('job') in ['Director', 'Producer', 'Writer']]
                        })
                        
            except Exception as e:
                logger.error(f"Error getting enhanced metadata: {e}")
        
        return metadata
    
    def generate_emby_metadata(self, video_path: Path, metadata: Dict):
        """Generate Emby-compatible metadata files."""
        try:
            # Generate NFO file for Emby
            nfo_path = video_path.with_suffix('.nfo')
            self._create_nfo_file(nfo_path, metadata)
            
            # Download and save poster if available
            if metadata.get('poster_path'):
                poster_path = video_path.parent / 'poster.jpg'
                self._download_image(metadata['poster_path'], poster_path)
            
            # Download and save backdrop if available
            if metadata.get('backdrop_path'):
                backdrop_path = video_path.parent / 'backdrop.jpg'
                self._download_image(metadata['backdrop_path'], backdrop_path)
                
            logger.info(f"Generated Emby metadata for {video_path}")
            
        except Exception as e:
            logger.error(f"Error generating Emby metadata: {e}")
    
    def _create_nfo_file(self, nfo_path: Path, metadata: Dict):
        """Create NFO file with metadata."""
        root = ET.Element('tvshow' if metadata.get('media_type') == 'tv' else 'movie')
        
        # Basic information
        ET.SubElement(root, 'title').text = metadata.get('show_name', '')
        ET.SubElement(root, 'originaltitle').text = metadata.get('show_name', '')
        ET.SubElement(root, 'plot').text = metadata.get('overview', '')
        ET.SubElement(root, 'year').text = str(metadata.get('year', ''))
        ET.SubElement(root, 'premiered').text = metadata.get('first_air_date', '')
        ET.SubElement(root, 'status').text = metadata.get('status', '')
        ET.SubElement(root, 'tagline').text = metadata.get('tagline', '')
        
        # Ratings
        rating_elem = ET.SubElement(root, 'rating')
        rating_elem.text = str(metadata.get('vote_average', 0))
        ET.SubElement(root, 'votes').text = str(metadata.get('vote_count', 0))
        
        # Genres
        for genre in metadata.get('genres', []):
            ET.SubElement(root, 'genre').text = genre
        
        # Cast
        for actor in metadata.get('cast', []):
            actor_elem = ET.SubElement(root, 'actor')
            ET.SubElement(actor_elem, 'name').text = actor['name']
            ET.SubElement(actor_elem, 'role').text = actor.get('character', '')
            if actor.get('profile_path'):
                ET.SubElement(actor_elem, 'thumb').text = f"https://image.tmdb.org/t/p/w500{actor['profile_path']}"
        
        # TMDB ID
        uniqueid_elem = ET.SubElement(root, 'uniqueid')
        uniqueid_elem.set('type', 'tmdb')
        uniqueid_elem.text = str(metadata.get('tmdb_id', ''))
        
        # Write to file
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        tree.write(nfo_path, encoding='utf-8', xml_declaration=True)
    
    def _download_image(self, image_path: str, save_path: Path):
        """Download image from TMDB."""
        try:
            import requests
            if image_path:
                url = f"https://image.tmdb.org/t/p/w500{image_path}"
                response = requests.get(url)
                if response.status_code == 200:
                    with open(save_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Downloaded image: {save_path}")
        except Exception as e:
            logger.error(f"Error downloading image {image_path}: {e}")


class FileSystemMonitor:
    """Monitor a directory for new video files and process them."""
    
    def __init__(self, watch_path, processed_path, tmdb_api_key, 
                 ai_service_url=None, supported_extensions=None, use_polling=False, polling_interval=5, naming_rules=None):
        self.watch_path = Path(watch_path)
        self.processed_path = Path(processed_path)
        self.tmdb_api_key = tmdb_api_key
        self.ai_service_url = ai_service_url
        self.use_polling = use_polling
        self.polling_interval = polling_interval
        self.processed_files = set()  # 存储已处理文件的集合，避免重复处理
        
        if supported_extensions is None:
            self.supported_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.strm']
        else:
            self.supported_extensions = supported_extensions
            
        self.observer = None
        self.stop_event = Event()
        
        # Initialize components
        self.renamer = VideoRenamer(tmdb_api_key, ai_service_url, self.watch_path, naming_rules)
        self.file_mover = FileMover(self.processed_path)
        self.event_handler = VideoFileHandler(
            self.renamer, self.file_mover, self.supported_extensions, self.processed_path
        )
        self.event_handler._parent_monitor = self  # 设置父监控器引用
    
    def start(self):
        """Start monitoring the directory."""
        if not self.watch_path.exists():
            logger.error(f"Watch path does not exist: {self.watch_path}")
            return
        
        # 初始扫描现有文件
        self._scan_existing_files()
            
        if self.use_polling:
            # 使用轮询模式
            self._start_polling()
        else:
            # 使用事件监听模式
            self.observer = Observer()
            self.observer.schedule(self.event_handler, str(self.watch_path), recursive=True)
            self.observer.start()
            
        logger.info(f"Started monitoring {self.watch_path} (Mode: {'Polling' if self.use_polling else 'Event-based'})")
        
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def _scan_existing_files(self):
        """扫描现有文件并处理未处理的文件。"""
        logger.info(f"Scanning existing files in {self.watch_path}")
        try:
            for root, _, files in os.walk(self.watch_path):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in self.supported_extensions:
                        # 检查文件是否已处理
                        if str(file_path) not in self.processed_files:
                            logger.info(f"Found existing video file: {file_path}")
                            # 在新线程中处理文件，避免阻塞启动
                            import threading
                            threading.Thread(target=self.event_handler.process_file, args=(file_path,)).start()
                            self.processed_files.add(str(file_path))
        except Exception as e:
            logger.error(f"Error scanning existing files: {e}")
    
    def _start_polling(self):
        """使用轮询方式监控目录。"""
        def poll_directory():
            while not self.stop_event.is_set():
                try:
                    for root, _, files in os.walk(self.watch_path):
                        for file in files:
                            file_path = Path(root) / file
                            # 检查文件扩展名和是否已处理
                            if (file_path.suffix.lower() in self.supported_extensions and 
                                str(file_path) not in self.processed_files):
                                # 确保文件写入完成（通过检查文件大小变化）
                                if self._is_file_complete(file_path):
                                    logger.info(f"New video file detected via polling: {file_path}")
                                    self.event_handler.process_file(file_path)
                                    self.processed_files.add(str(file_path))
                    time.sleep(self.polling_interval)
                except Exception as e:
                    logger.error(f"Error during directory polling: {e}")
                    time.sleep(self.polling_interval)  # 即使出错也继续轮询
        
        # 在单独的线程中启动轮询
        polling_thread = threading.Thread(target=poll_directory)
        polling_thread.daemon = True
        polling_thread.start()
    
    def _is_file_complete(self, file_path, check_interval=1):
        """检查文件是否已完全写入（通过比较两次检查的文件大小）。"""
        try:
            size1 = file_path.stat().st_size
            time.sleep(check_interval)
            size2 = file_path.stat().st_size
            return size1 == size2
        except Exception as e:
            logger.error(f"Error checking file completeness: {e}")
            return False
    
    def stop(self):
        """Stop monitoring."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.stop_event.set()
        logger.info("Stopped monitoring")
    
    def force_process_file(self, file_path):
        """强制处理指定的文件，无论其是否已被处理过。"""
        file_path = Path(file_path)
        if file_path.exists() and file_path.suffix.lower() in self.supported_extensions:
            logger.info(f"Force processing file: {file_path}")
            self.event_handler.process_file(file_path)
            self.processed_files.add(str(file_path))
            return True
        return False