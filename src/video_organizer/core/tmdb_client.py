"""
TMDB API client for fetching TV show information.
"""

import logging
from typing import List, Dict, Optional
import requests

logger = logging.getLogger(__name__)


class TMDBClient:
    """Client for interacting with The Movie Database API."""
    
    BASE_URL = "https://api.themoviedb.org/3"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        # Check if it's a JWT token (Bearer token) or regular API key
        if api_key.startswith('eyJ'):
            # JWT token - use Bearer authentication
            self.session.headers = {
                "Authorization": f"Bearer {api_key}",
                "accept": "application/json"
            }
        else:
            # Regular API key - use query parameter
            self.session.params = {"api_key": self.api_key}
            self.session.headers = {"accept": "application/json"}
    
    def search_video_show(self, query: str, year: Optional[str] = None, include_adult: Optional[bool] = False, language: Optional[str] = "zh-CN") -> List[Dict]:
        """
        搜索视频信息
        """
        params = {
            "query": query,
            "include_adult": include_adult,
            "language": language,
        }
        if year:
            params["first_air_date_year"] = year
            
        try:
            response = self.session.get(f"{self.BASE_URL}/search/multi", params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except requests.RequestException as e:
            logger.error(f"Error searching for TV show '{query}': {e}")
            return []
    
    def get_media_show_details(self, show_id: int, media_type: str) -> Optional[Dict]:
        """
        获取视频详细信息
        """
        try:
            response = self.session.get(f"{self.BASE_URL}/{media_type}/{show_id}?append_to_response=videos,images")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting details for show ID {show_id}: {e}")
            return None

    def get_watch_providers(self, show_id: int, season_number: Optional[int] = None) -> Optional[Dict]:
        """
        获取哪个平台发行的
        """
        try:
            if season_number is not None:
                # Get providers for a specific season
                url = f"{self.BASE_URL}/tv/{show_id}/season/{season_number}/watch/providers"
            else:
                # Get providers for the entire show
                url = f"{self.BASE_URL}/tv/{show_id}/watch/providers"
                
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()
            
            # The structure is {'id': , 'results': {'US': { 'flatrate': [...], 'buy': [...] }, 'DE': {...}}}
            return data.get("results", {})
            
        except requests.RequestException as e:
            logger.error(f"Error getting watch providers for show ID {show_id}: {e}")
            return None
    
    def get_season_details(self, show_id: int, season_number: int) -> Optional[Dict]:
        """
        Get details about a specific season of a TV show.
        
        Args:
            show_id: TMDB ID of the show
            season_number: Season number
            
        Returns:
            Season details dictionary or None if error
        """
        try:
            response = self.session.get(
                f"{self.BASE_URL}/tv/{show_id}/season/{season_number}"
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(
                f"Error getting details for show ID {show_id} season {season_number}: {e}"
            )
            return None