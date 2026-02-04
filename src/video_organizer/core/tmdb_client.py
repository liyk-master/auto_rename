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
        if api_key and api_key.startswith("eyJ"):
            # JWT token - use Bearer authentication
            self.session.headers = {
                "Authorization": f"Bearer {api_key}",
                "accept": "application/json",
            }
        else:
            # Regular API key - use query parameter
            self.session.params = {"api_key": self.api_key}
            self.session.headers = {"accept": "application/json"}

    def search_video_show(
        self,
        query: str,
        year: Optional[str] = None,
        include_adult: Optional[bool] = True,
        language: Optional[str] = "zh-CN",
    ) -> List[Dict]:
        """
        搜索视频信息
        """
        url = f"{self.BASE_URL}/search/multi"
        params = {
            "query": query,
            "include_adult": include_adult,
        }
        # 只有当 language 不为 None 时才添加 language 参数
        if language is not None:
            params["language"] = language
        if year:
            # 同时添加两个年份参数，以支持电影和电视剧
            params["year"] = year
            params["first_air_date_year"] = year

        data = self._request_with_retry(url, params)

        # 调试日志：打印返回数据的结构
        logger.debug(f"search_video_show 返回的数据类型: {type(data)}")
        if data:
            logger.debug(f"search_video_show 返回的数据键: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
            if isinstance(data, dict):
                results = data.get("results", [])
                logger.debug(f"search_video_show results 数量: {len(results)}")
                if results:
                    logger.debug(f"search_video_show 第一个结果: {results[0].get('name') or results[0].get('title') if results else 'none'}")
                return results
            else:
                logger.warning(f"search_video_show 返回的数据不是字典类型: {data}")
                return []
        else:
            logger.warning(f"search_video_show 返回的数据为 None")
            return []

    def get_media_show_details(
        self, show_id: int, media_type: str, language: Optional[str] = "zh-CN"
    ) -> Optional[Dict]:
        """
        获取视频详细信息
        """
        url = f"{self.BASE_URL}/{media_type}/{show_id}"
        params = (
            {"append_to_response": "videos,images", "language": language}
            if not self.api_key.startswith("eyJ")
            else {"language": language}
        )
        return self._request_with_retry(url, params)

    def get_watch_providers(
        self, show_id: int, season_number: Optional[int] = None
    ) -> Optional[Dict]:
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

    def get_season_details(
        self, show_id: int, season_number: int, language: Optional[str] = "zh-CN"
    ) -> Optional[Dict]:
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
        params = (
            {"language": language}
            if not self.api_key.startswith("eyJ")
            else {"language": language}
        )
        return self._request_with_retry(url, params)

    def _request_with_retry(
        self, url: str, params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """发送API请求并处理响应，包含重试机制"""
        import time
        import socket

        retry_count = self.retry_count
        last_error = None

        while retry_count >= 0:
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)

                # 检查 response 是否为 None
                if response is None:
                    logger.error(f"TMDB API returned None for URL: {url}")
                    retry_count -= 1
                    if retry_count >= 0:
                        wait_time = 2 ** (self.retry_count - retry_count)
                        logger.warning(
                            f"Response is None, retrying in {wait_time} seconds..."
                        )
                        time.sleep(wait_time)
                    continue

                # 对404错误不进行重试，因为资源不存在的状态不会改变
                if response.status_code == 404:
                    logger.warning(f"TMDB API returned 404 Not Found for URL: {url}")
                    return None

                # 检查其他客户端错误（4xx）
                if 400 <= response.status_code < 500:
                    logger.error(
                        f"TMDB API client error ({response.status_code}): {response.text[:200]}"
                    )
                    return None

                # 检查服务器错误（5xx）- 这些可以重试
                if response.status_code >= 500:
                    logger.warning(
                        f"TMDB API server error ({response.status_code}), retrying..."
                    )
                    retry_count -= 1
                    if retry_count >= 0:
                        wait_time = 2 ** (self.retry_count - retry_count)
                        logger.warning(
                            f"Server error, retrying in {wait_time} seconds..."
                        )
                        time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.Timeout as e:
                last_error = f"请求超时: {e}"
                retry_count -= 1
                self._handle_retry(retry_count, last_error, url)

            except requests.exceptions.ConnectionError as e:
                last_error = f"连接错误: {e}"
                retry_count -= 1
                self._handle_retry(retry_count, last_error, url)

            except requests.exceptions.ProxyError as e:
                last_error = f"代理错误: {e}"
                logger.error(f"Proxy error occurred: {e}")
                retry_count -= 1
                self._handle_retry(retry_count, last_error, url)

            except requests.exceptions.RequestException as e:
                retry_count -= 1
                self._handle_retry(retry_count, str(e), url)

        logger.error(
            f"TMDB API request failed after multiple attempts. Last error: {last_error}"
        )
        logger.error(f"Failed URL: {url}, params: {params}")
        return None

    def _handle_retry(self, retry_count: int, error_msg: str, url: str):
        """处理重试逻辑"""
        if retry_count < 0:
            logger.error(f"TMDB API request failed: {error_msg}")
            return

        wait_time = min(2 ** (self.retry_count - retry_count), 60)  # 最多等60秒
        logger.warning(
            f"TMDB request failed: {error_msg}, retrying in {wait_time} seconds... (remaining: {retry_count})"
        )
        import time

        time.sleep(wait_time)

    def get_tv_details(
        self,
        tv_id: int,
        append_to_response: str = "videos,images,credits,content_ratings",
        language: Optional[str] = "zh-CN",
    ) -> Optional[Dict]:
        """获取电视剧的详细信息"""
        url = f"{self.BASE_URL}/tv/{tv_id}"
        params = (
            {"append_to_response": append_to_response, "language": language}
            if not self.api_key.startswith("eyJ")
            else {"language": language}
        )
        return self._request_with_retry(url, params)

    def get_movie_details(
        self,
        movie_id: int,
        append_to_response: str = "videos,images,credits,content_ratings,reviews",
        language: Optional[str] = "zh-CN",
    ) -> Optional[Dict]:
        """获取电影的详细信息"""
        url = f"{self.BASE_URL}/movie/{movie_id}"
        params = (
            {"append_to_response": append_to_response, "language": language}
            if not self.api_key.startswith("eyJ")
            else {"language": language}
        )
        return self._request_with_retry(url, params)

    def get_tv_episode_details(
        self,
        tv_id: int,
        season_number: int,
        episode_number: int,
        language: Optional[str] = "zh-CN",
    ) -> Optional[Dict]:
        """获取电视剧集的详细信息"""
        url = f"{self.BASE_URL}/tv/{tv_id}/season/{season_number}/episode/{episode_number}"
        params = (
            {"language": language}
            if not self.api_key.startswith("eyJ")
            else {"language": language}
        )
        return self._request_with_retry(url, params)

    def get_tv_reviews(
        self, tv_id: int, page: int = 1, language: Optional[str] = "zh-CN"
    ) -> Optional[Dict]:
        """获取电视剧的评论"""
        url = f"{self.BASE_URL}/tv/{tv_id}/reviews"
        params = (
            {"page": page, "language": language}
            if not self.api_key.startswith("eyJ")
            else {"page": page, "language": language}
        )
        return self._request_with_retry(url, params)

    def get_movie_reviews(
        self, movie_id: int, page: int = 1, language: Optional[str] = "zh-CN"
    ) -> Optional[Dict]:
        """获取电影的评论"""
        url = f"{self.BASE_URL}/movie/{movie_id}/reviews"
        params = (
            {"page": page, "language": language}
            if not self.api_key.startswith("eyJ")
            else {"page": page, "language": language}
        )
        return self._request_with_retry(url, params)

    def get_external_ids(self, media_id: int, media_type: str) -> Optional[Dict]:
        """获取外部ID信息（IMDB、TVDB等）"""
        url = f"{self.BASE_URL}/{media_type}/{media_id}/external_ids"
        return self._request_with_retry(url)

    def get_images(self, media_id: int, media_type: str) -> Optional[Dict]:
        """获取海报和背景图片"""
        url = f"{self.BASE_URL}/{media_type}/{media_id}/images"
        return self._request_with_retry(url)

    def search_tv(
        self,
        query: str,
        year: Optional[int] = None,
        page: int = 1,
        language: Optional[str] = "zh-CN",
        include_adult: Optional[bool] = True,
    ) -> Optional[Dict]:
        """专门搜索电视剧"""
        url = f"{self.BASE_URL}/search/tv"
        params = (
            {"query": query, "page": page, "include_adult": include_adult}
            if not self.api_key.startswith("eyJ")
            else {"query": query, "page": page, "include_adult": include_adult}
        )
        # 只有当 language 不为 None 时才添加 language 参数
        if language is not None:
            params["language"] = language
        if year:
            params["first_air_date_year"] = year
        result = self._request_with_retry(url, params)
        # 为搜索结果添加media_type字段
        if result and "results" in result:
            for item in result["results"]:
                item["media_type"] = "tv"
        return result

    def search_movie(
        self,
        query: str,
        year: Optional[int] = None,
        page: int = 1,
        language: Optional[str] = "zh-CN",
    ) -> Optional[Dict]:
        """专门搜索电影"""
        url = f"{self.BASE_URL}/search/movie"
        params = (
            {"query": query, "page": page}
            if not self.api_key.startswith("eyJ")
            else {"query": query, "page": page}
        )
        # 只有当 language 不为 None 时才添加 language 参数
        if language is not None:
            params["language"] = language
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

    def search_multi(
        self,
        query: str,
        year: Optional[int] = None,
        page: int = 1,
        language: Optional[str] = "zh-CN",
        include_adult: Optional[bool] = True,
    ) -> List[Dict]:
        """
        使用 /search/multi 接口同时搜索电影和电视剧

        Args:
            query: 搜索词
            year: 年份（可选）
            page: 页码
            language: 搜索语言
            include_adult: 是否包含成人内容

        Returns:
            搜索结果列表，每个结果包含 media_type 字段
        """
        url = f"{self.BASE_URL}/search/multi"
        params = {"query": query, "page": page, "include_adult": include_adult}

        # 只有当 language 不为 None 时才添加 language 参数
        if language is not None:
            params["language"] = language

        if year:
            # multi 接口同时支持 year 和 first_air_date_year
            params["year"] = year
            params["first_air_date_year"] = year

        result = self._request_with_retry(url, params)
        if result and "results" in result:
            # 返回结果列表
            return result["results"]
        return []
