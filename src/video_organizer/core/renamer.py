"""
Module for extracting metadata from video files and generating new names.
"""

import re
import logging
from pathlib import Path
from typing import Dict, Optional

from src.video_organizer.core.tmdb_client import TMDBClient

logger = logging.getLogger(__name__)


class VideoRenamer:
    """Extracts metadata from video files and generates organized paths."""
    
    def __init__(self, tmdb_api_key: str, ai_service_url: Optional[str] = None, watch_path: Optional[Path] = None):
        self.tmdb_client = TMDBClient(tmdb_api_key)
        self.ai_service_url = ai_service_url
        self.watch_path = watch_path
        
    def extract_metadata(self, file_path: Path) -> Dict:
        """
        从视频文件路径中提取元数据。
        """
        print("file_path",file_path)
        print("file_path.parent",file_path.parent)
        print("file_path.name",file_path.name)
        # First try to extract using regex patterns
        metadata = self._extract_with_regex(file_path.name)
        
        # If regex fails or results are incomplete, try AI service
        if (self.ai_service_url and 
            (not metadata.get('show_name') or not metadata.get('season') or not metadata.get('episode'))):
            # 获取相对于watch_path的路径作为视频名称
            if self.watch_path:
                try:
                    # 计算相对路径
                    relative_path = file_path.relative_to(self.watch_path)
                    # 使用相对路径的第一级目录名称作为视频名称
                    if len(relative_path.parts) > 1:
                        video_name = relative_path.parts[0]  # 第一级目录名称
                    else:
                        video_name = file_path.stem  # 如果文件直接在watch_path下，使用文件名
                    logger.info(f"Using directory name as video name: {video_name}")
                    metadata = self._extract_with_ai(video_name, metadata)
                except ValueError:
                    # 如果文件不在watch_path下，使用文件名
                    logger.warning(f"File {file_path} is not under watch_path {self.watch_path}, using filename")
                    metadata = self._extract_with_ai(file_path.name, metadata)
            else:
                metadata = self._extract_with_ai(file_path.name, metadata)
            
        # Enrich with TMDB data if we have a show name
        if metadata.get('show_name'):
            metadata = self._enrich_with_tmdb(metadata)
            
        return metadata
    
    def _extract_with_regex(self, filename: str) -> Dict:
        """Extract metadata using regular expressions."""
        metadata = {}
        
        # Common patterns for TV shows
        patterns = [
            # Pattern: Show.Name.S01E02.quality-group.ext
            r"(?P<show_name>[\w\.]+)\.S(?P<season>\d+)E(?P<episode>\d+)",
            # Pattern: Show Name - s01e02 - Episode Title.ext
            r"(?P<show_name>[\w\s]+)\s*-\s*s(?P<season>\d+)e(?P<episode>\d+)",
            # Pattern: Show Name Season 1 Episode 2.ext
            r"(?P<show_name>[\w\s]+)\s+Season\s+(?P<season>\d+)\s+Episode\s+(?P<episode>\d+)",
            # Pattern: Show Name - Season 1 - Episode 2.ext
            r"(?P<show_name>[\w\s]+)\s*-\s*Season\s+(?P<season>\d+)\s*-\s*Episode\s+(?P<episode>\d+)",
            # Pattern: Show Name - S01E02 - Episode Title.ext
            r"(?P<show_name>[\w\s]+)\s*-\s*S(?P<season>\d+)E(?P<episode>\d+)",

        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                metadata.update(match.groupdict())
                # Clean up show name
                if 'show_name' in metadata:
                    metadata['show_name'] = metadata['show_name'].replace('.', ' ').title()
                break
                
        return metadata
    
    def _extract_with_ai(self, filename: str, existing_metadata: Dict) -> Dict:
        """
        Use AI service to extract metadata from filename.
        """
        logger.warning("AI extraction not implemented, using regex results only")

        
        return existing_metadata
    
    def _enrich_with_tmdb(self, metadata: Dict) -> Dict:
        """Enrich metadata with information from TMDB."""
        show_name = metadata['show_name']
        
        try:
            # Search for the show
            search_results = self.tmdb_client.search_tv_show(show_name)
            if search_results:
                # Use the first result
                show_id = search_results[0]['id']
                show_details = self.tmdb_client.get_tv_show_details(show_id)
                
                # Update metadata with TMDB information
                metadata['tmdb_id'] = show_id
                metadata['show_name'] = show_details.get('name', show_name)
                metadata['year'] = show_details.get('first_air_date', '')[:4] if show_details.get('first_air_date') else ''
                
                # Get season details if we have season number
                if metadata.get('season'):
                    season_details = self.tmdb_client.get_season_details(
                        show_id, int(metadata['season'])
                    )
                    if season_details and metadata.get('episode'):
                        episode_number = int(metadata['episode'])
                        if episode_number <= len(season_details.get('episodes', [])):
                            episode = season_details['episodes'][episode_number - 1]
                            metadata['episode_name'] = episode.get('name', '')
                            
        except Exception as e:
            logger.error(f"Error enriching metadata with TMDB: {e}")
            
        return metadata
    
    def generate_new_path(self, metadata: Dict) -> Path:
        """
        Generate a new organized path based on metadata.
        
        Args:
            metadata: Dictionary containing video metadata
            
        Returns:
            Path object for the new file location
        """
        if not metadata.get('show_name'):
            raise ValueError("Cannot generate path without show name")
            
        # Base structure: Show Name/Season X/Show Name - SXXEXX - Episode Name.ext
        show_name = self._sanitize_filename(metadata['show_name'])
        season = metadata.get('season', '0')
        episode = metadata.get('episode', '0')
        episode_name = self._sanitize_filename(metadata.get('episode_name', ''))
        
        # Format season and episode numbers
        season_str = f"Season {int(season):02d}" if season.isdigit() else f"Season {season}"
        episode_str = f"E{int(episode):02d}" if episode.isdigit() else f"E{episode}"
        
        # Build filename
        filename_parts = [show_name, f"S{season_str}{episode_str}"]
        if episode_name:
            filename_parts.append(episode_name)
            
        filename = " - ".join(filename_parts)
        
        # Build full path
        path = Path(show_name) / season_str / f"{filename}"
        
        return path
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string to be safe for use as a filename."""
        if not name:
            return ""
            
        # Replace problematic characters
        import re
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name