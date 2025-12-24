"""
TMDB API client for fetching TV show information.
"""

import logging
from types import resolve_bases
from typing import List, Dict, Optional
import requests
import json

logger = logging.getLogger(__name__)


class TMDBClient:
    """Client for interacting with The Movie Database API."""
    
    BASE_URL = "https://proxy1.liyk001.eu.org/https://api.themoviedb.org/3"
    
    def __init__(self, api_key: str, retry_count=3, timeout=30):
        self.api_key = api_key
        self.retry_count = retry_count
        self.timeout = timeout
        self.session = requests.Session()
        # Check if it's a JWT token (Bearer token) or regular API key
        if api_key and api_key.startswith('eyJ'):
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
        url = f"{self.BASE_URL}/search/multi"
        params = {
            "query": query,
            "include_adult": include_adult,
            "language": language,
        }
        if year:
            # 同时添加两个年份参数，以支持电影和电视剧
            params["year"] = year
            params["first_air_date_year"] = year
            
        data = self._request_with_retry(url, params)
        return data.get("results", []) if data else []
    
    def get_media_show_details(self, show_id: int, media_type: str, language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """
        获取视频详细信息
        """
        url = f"{self.BASE_URL}/{media_type}/{show_id}"
        params = {"append_to_response": "videos,images", "language": language} if not self.api_key.startswith('eyJ') else {"language": language}
        return self._request_with_retry(url, params)

    def get_watch_providers(self, show_id: int, season_number: Optional[int] = None) -> Optional[Dict]:
        """
        获取哪个平台发行的
        """
        if season_number is not None:
            # Get providers for a specific season
            url = f"{self.BASE_URL}/tv/{show_id}/season/{season_number}/watch/providers"
        else:
            # Get providers for the entire show
            url = f"{self.BASE_URL}/tv/{show_id}/watch/providers"
            
        data = self._request_with_retry(url)
        # The structure is {'id': , 'results': {'US': { 'flatrate': [...], 'buy': [...] }, 'DE': {...}}}
        return data.get("results", {}) if data else {}
    
    def get_season_details(self, show_id: int, season_number: int, language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """
        Get details about a specific season of a TV show.
        
        Args:
            show_id: TMDB ID of the show
            season_number: Season number
            language: Language for the response, defaults to "zh-CN"
            
        Returns:
            Season details dictionary or None if error
        """
        url = f"{self.BASE_URL}/tv/{show_id}/season/{season_number}"
        params = {"language": language} if not self.api_key.startswith('eyJ') else {"language": language}
        return self._request_with_retry(url, params)
    
    def _request_with_retry(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """发送API请求并处理响应，包含重试机制"""
        import time
        
        retry_count = self.retry_count
        while retry_count >= 0:
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                
                # 对404错误不进行重试，因为资源不存在的状态不会改变
                if response.status_code == 404:
                    logger.warning(f"TMDB API returned 404 Not Found for URL: {url}")
                    return None
                
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                retry_count -= 1
                if retry_count < 0:
                    logger.error(f"TMDB API request failed after multiple attempts: {e}")
                    return None
                
                # 对404错误不进行重试
                if hasattr(e, 'response') and getattr(e.response, 'status_code') == 404:
                    logger.warning(f"TMDB API returned 404 Not Found for URL: {url}")
                    return None
                
                wait_time = 2 ** (self.retry_count - retry_count)  # 指数退避
                logger.warning(f"Request failed, retrying in {wait_time} seconds...")
                time.sleep(wait_time)
    
    def get_tv_details(self, tv_id: int, append_to_response: str = "videos,images,credits,content_ratings", language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """获取电视剧的详细信息"""
        url = f"{self.BASE_URL}/tv/{tv_id}"
        params = {"append_to_response": append_to_response, "language": language} if not self.api_key.startswith('eyJ') else {"language": language}
        return self._request_with_retry(url, params)
    
    def get_movie_details(self, movie_id: int, append_to_response: str = "videos,images,credits,content_ratings,reviews", language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """获取电影的详细信息"""
        url = f"{self.BASE_URL}/movie/{movie_id}"
        params = {"append_to_response": append_to_response, "language": language} if not self.api_key.startswith('eyJ') else {"language": language}
        return self._request_with_retry(url, params)
    
    def get_tv_episode_details(self, tv_id: int, season_number: int, episode_number: int, language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """获取电视剧集的详细信息"""
        url = f"{self.BASE_URL}/tv/{tv_id}/season/{season_number}/episode/{episode_number}"
        params = {"language": language} if not self.api_key.startswith('eyJ') else {"language": language}
        return self._request_with_retry(url, params)
    
    def get_tv_reviews(self, tv_id: int, page: int = 1, language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """获取电视剧的评论"""
        url = f"{self.BASE_URL}/tv/{tv_id}/reviews"
        params = {"page": page, "language": language} if not self.api_key.startswith('eyJ') else {"page": page, "language": language}
        return self._request_with_retry(url, params)
    
    def get_movie_reviews(self, movie_id: int, page: int = 1, language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """获取电影的评论"""
        url = f"{self.BASE_URL}/movie/{movie_id}/reviews"
        params = {"page": page, "language": language} if not self.api_key.startswith('eyJ') else {"page": page, "language": language}
        return self._request_with_retry(url, params)
    
    def get_external_ids(self, media_id: int, media_type: str) -> Optional[Dict]:
        """获取外部ID信息（IMDB、TVDB等）"""
        url = f"{self.BASE_URL}/{media_type}/{media_id}/external_ids"
        return self._request_with_retry(url)
    
    def get_images(self, media_id: int, media_type: str) -> Optional[Dict]:
        """获取海报和背景图片"""
        url = f"{self.BASE_URL}/{media_type}/{media_id}/images"
        return self._request_with_retry(url)
    
    def search_tv(self, query: str, year: Optional[int] = None, page: int = 1, language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """专门搜索电视剧"""
        url = f"{self.BASE_URL}/search/tv"
        params = {"query": query, "page": page, "language": language} if not self.api_key.startswith('eyJ') else {"query": query, "page": page, "language": language}
        if year:
            params["first_air_date_year"] = year
        result = self._request_with_retry(url, params)
        # 为搜索结果添加media_type字段
        if result and "results" in result:
            for item in result["results"]:
                item["media_type"] = "tv"
        return result
    
    def search_movie(self, query: str, year: Optional[int] = None, page: int = 1, language: Optional[str] = "zh-CN") -> Optional[Dict]:
        """专门搜索电影"""
        url = f"{self.BASE_URL}/search/movie"
        params = {"query": query, "page": page, "language": language} if not self.api_key.startswith('eyJ') else {"query": query, "page": page, "language": language}
        if year:
            params["year"] = year
        result = self._request_with_retry(url, params)
        # 为搜索结果添加media_type字段
        if result and "results" in result:
            for item in result["results"]:
                item["media_type"] = "movie"
        return result
                
    def get_tv_credits(self, show_id: int) -> Optional[Dict]:
        """
        Get cast and crew information for a TV show.
        
        Args:
            show_id: TMDB ID of the show
            
        Returns:
            Credits dictionary containing cast and crew or None if error
        """
        url = f"{self.BASE_URL}/tv/{show_id}/credits"
        return self._request_with_retry(url)