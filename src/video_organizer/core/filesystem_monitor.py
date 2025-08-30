"""
File system monitoring module using watchdog.
"""

import logging
import time
from pathlib import Path
from threading import Event
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.core.file_mover import FileMover

logger = logging.getLogger(__name__)


class VideoFileHandler(FileSystemEventHandler):
    """Handler for new video file events."""
    
    def __init__(self, renamer, file_mover, supported_extensions):
        self.renamer = renamer
        self.file_mover = file_mover
        self.supported_extensions = supported_extensions
        
    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            file_path = Path(event.src_path)
            if file_path.suffix.lower() in self.supported_extensions:
                logger.info(f"New video file detected: {file_path}")
                self.process_file(file_path)
    
    def process_file(self, file_path):
        """Process a newly created video file."""
        try:
            # Extract metadata and determine new path
            metadata = self.renamer.extract_metadata(file_path)
            new_path = self.renamer.generate_new_path(metadata)
            
            # Move file to new location
            self.file_mover.move_file(file_path, new_path)
            
            logger.info(f"Successfully processed and moved {file_path} to {new_path}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")


class FileSystemMonitor:
    """Monitor a directory for new video files and process them."""
    
    def __init__(self, watch_path, processed_path, tmdb_api_key, 
                 ai_service_url=None, supported_extensions=None):
        self.watch_path = Path(watch_path)
        self.processed_path = Path(processed_path)
        self.tmdb_api_key = tmdb_api_key
        self.ai_service_url = ai_service_url
        
        if supported_extensions is None:
            self.supported_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.strm']
        else:
            self.supported_extensions = supported_extensions
            
        self.observer = None
        self.stop_event = Event()
        
        # Initialize components
        self.renamer = VideoRenamer(tmdb_api_key, ai_service_url, self.watch_path)
        self.file_mover = FileMover(self.processed_path)
        self.event_handler = VideoFileHandler(
            self.renamer, self.file_mover, self.supported_extensions
        )
    
    def start(self):
        """Start monitoring the directory."""
        if not self.watch_path.exists():
            logger.error(f"Watch path does not exist: {self.watch_path}")
            return
            
        self.observer = Observer()
        self.observer.schedule(self.event_handler, str(self.watch_path), recursive=True)
        self.observer.start()
        
        logger.info(f"Started monitoring {self.watch_path}")
        
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop monitoring."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.stop_event.set()
        logger.info("Stopped monitoring")