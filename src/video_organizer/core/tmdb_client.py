"""
TMDB API client for fetching TV show information.
"""

import logging
import threading
import time
from typing import List, Dict, Optional, Callable
from collections import OrderedDict, deque
import requests

logger = logging.getLogger(__name__)

# 默认限速配置（请求/秒），TMDB 官方限速约 40 req/s，留 12.5% 余量
DEFAULT_RATE_LIMIT_PER_SEC = 35
# 收到 429 后临时降速（请求/秒）
DEGRADED_RATE_LIMIT_PER_SEC = 20
# 降速持续时间（秒）
DEGRADE_DURATION = 30.0
# 请求缓存默认容量（条）
DEFAULT_CACHE_SIZE = 512


class _GlobalRateLimiter:
    """
    进程级全局 TMDB 限速器（滑动窗口按秒计数）。

    所有 TMDBClient 实例共享同一预算，避免多实例叠加打爆 TMDB 限速。
    支持收到 429 后临时降速，超时后自动恢复。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._timestamps: deque = deque()
        self._rate_limit_per_sec = DEFAULT_RATE_LIMIT_PER_SEC
        self._degraded_rate: Optional[int] = None
        self._degraded_until = 0.0

    def set_rate_limit_per_sec(self, rate: int) -> None:
        """设置基础限速（取所有调用方中的最大值，避免互相降速）"""
        with self._lock:
            if rate and rate > self._rate_limit_per_sec:
                self._rate_limit_per_sec = rate

    def degrade(self, rate: int = DEGRADED_RATE_LIMIT_PER_SEC, duration: float = DEGRADE_DURATION) -> None:
        """临时降速：rate 请求/秒，持续 duration 秒后恢复"""
        with self._lock:
            self._degraded_rate = rate
            self._degraded_until = time.time() + duration

    def _current_rate(self) -> int:
        """获取当前生效的限速值"""
        now = time.time()
        with self._lock:
            if self._degraded_rate is not None and now < self._degraded_until:
                return self._degraded_rate
            return self._rate_limit_per_sec

    def acquire(self) -> None:
        """获取一次发送许可，超限时阻塞等待窗口滑出"""
        while True:
            rate = self._current_rate()
            now = time.time()
            with self._lock:
                # 清理窗口外的时间戳（1 秒滑动窗口）
                while self._timestamps and now - self._timestamps[0] >= 1.0:
                    self._timestamps.popleft()
                if len(self._timestamps) < rate:
                    self._timestamps.append(now)
                    return
                # 计算需要等待的时间（最早时间戳滑出窗口）
                wait_time = 1.0 - (now - self._timestamps[0])
                if wait_time <= 0:
                    continue
            time.sleep(wait_time)


class _RequestCache:
    """线程安全的 LRU 请求缓存，仅缓存成功的搜索请求"""

    def __init__(self, maxsize: int = DEFAULT_CACHE_SIZE):
        self._lock = threading.Lock()
        self._maxsize = maxsize
        self._cache: "OrderedDict[tuple, Dict]" = OrderedDict()

    def get(self, key: tuple) -> Optional[Dict]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: tuple, value: Dict) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# 进程级共享限速器单例
_global_rate_limiter = _GlobalRateLimiter()


def make_request_cache_key(url: str, params: Optional[Dict]) -> tuple:
    """构造请求缓存键：(url, 排序后的 params)"""
    if params:
        return (url, tuple(sorted((str(k), str(v)) for k, v in params.items())))
    return (url, ())


class TMDBClient:
    """Client for interacting with The Movie Database API."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(
        self,
        api_key: str,
        retry_count=3,
        timeout=30,
        rate_limit=40,
        base_url=None,
        rate_limit_per_sec: Optional[int] = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ):
        self.api_key = api_key
        self.retry_count = retry_count
        self.timeout = timeout
        self.BASE_URL = base_url or self.BASE_URL
        self.rate_limit = rate_limit
        self._request_timestamps: deque = deque()
        self.session = requests.Session()
        self.last_request_failed = False
        self.last_request_error = None
        self._cache = _RequestCache(maxsize=cache_size)
        if rate_limit_per_sec:
            _global_rate_limiter.set_rate_limit_per_sec(rate_limit_per_sec)
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
        page: int = 1,
        include_adult: Optional[bool] = True,
        language: Optional[str] = "zh-CN",
    ) -> List[Dict]:
        """
        搜索视频信息
        """
        url = f"{self.BASE_URL}/search/multi"
        params = {
            "query": query,
            "page": page,
            "include_adult": include_adult,
        }
        # 只有当 language 不为 None 时才添加 language 参数
        if language is not None:
            params["language"] = language
        if year:
            # 同时添加两个年份参数，以支持电影和电视剧
            params["year"] = year
            params["first_air_date_year"] = year

        data = self._request_with_retry(url, params, cacheable=True)

        # 与 search_movie 相同的降级逻辑
        if language is not None and (data is None or not data.get("results")):
            logger.debug(
                f"search_video_show 带 language={language} 搜索无结果，"
                f"尝试不带语言参数重新搜索"
            )
            params.pop("language", None)
            data = self._request_with_retry(url, params, cacheable=True)

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

    def search_all_pages(
        self,
        method_name: str,
        query: str,
        max_pages: int = 5,
        include_adult: Optional[bool] = True,
        **kwargs,
    ) -> List[Dict]:
        """
        通用分页搜索：遍历多页 TMDB 搜索结果，去重合并返回。

        Args:
            method_name: 搜索方法名 ('search_tv', 'search_movie', 'search_multi', 'search_video_show')
            query: 搜索词
            max_pages: 最大搜索页数
            include_adult: 是否包含成人内容
            **kwargs: 其他搜索参数（year, language 等）

        Returns:
            合并后的去重结果列表
        """
        all_results: List[Dict] = []
        seen_ids: set = set()
        method: Callable = getattr(self, method_name)

        for page in range(1, max_pages + 1):
            result = method(query, page=page, include_adult=include_adult, **kwargs)

            if not result:
                break

            # 处理不同返回类型：search_tv/search_movie 返回 dict（含 total_pages），
            # search_multi/search_video_show 返回 List[Dict]
            if isinstance(result, dict):
                page_results = result.get("results", [])
                total_pages = result.get("total_pages", 0)
            else:
                page_results = result
                total_pages = 0  # 列表返回类型无法获知总页数

            if not page_results:
                break

            # 按 tmdb_id 去重
            for item in page_results:
                item_id = item.get("id")
                if item_id is not None and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_results.append(item)

            logger.debug(
                f"search_all_pages({method_name}): 第{page}页获取 {len(page_results)} 条, "
                f"累计 {len(all_results)} 条"
            )

            # 已到最后页则提前停止
            if isinstance(result, dict) and total_pages > 0 and page >= total_pages:
                logger.debug(
                    f"search_all_pages({method_name}): 已到第{page}/{total_pages}页，停止翻页"
                )
                break

        logger.info(
            f"分页搜索完成({method_name}): 共{len(all_results)}条结果 "
            f"(搜索了最多{min(page, max_pages)}页)"
        )
        return all_results

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
        self, url: str, params: Optional[Dict] = None, cacheable: bool = False
    ) -> Optional[Dict]:
        """发送API请求并处理响应，包含重试机制和进程级限速"""
        # 请求缓存：仅对可缓存的搜索请求生效，命中则直接返回（不消耗限速预算）
        cache_key = None
        if cacheable:
            cache_key = make_request_cache_key(url, params)
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug(f"TMDB 请求缓存命中: {url}")
                return cached

        # 进程级全局速率限制（所有实例共享预算，按秒滑动窗口）
        _global_rate_limiter.acquire()

        retry_count = self.retry_count
        last_error = None
        self.last_request_failed = False
        self.last_request_error = None

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

                # 429 限速：临时降速并按 Retry-After/指数退避等待后重试
                if response.status_code == 429:
                    _global_rate_limiter.degrade()
                    retry_count -= 1
                    if retry_count >= 0:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and str(retry_after).isdigit():
                            wait_time = float(retry_after)
                        else:
                            wait_time = 2 ** (self.retry_count - retry_count)
                        logger.warning(
                            f"TMDB API rate limited (429), retrying in {wait_time} seconds... "
                            f"(remaining: {retry_count})"
                        )
                        time.sleep(wait_time)
                        continue
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
                self.last_request_failed = False
                self.last_request_error = None
                data = response.json()
                # 仅缓存成功的搜索请求
                if cacheable and cache_key is not None and data is not None:
                    self._cache.put(cache_key, data)
                return data

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
        self.last_request_failed = True
        self.last_request_error = last_error
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
        result = self._request_with_retry(url, params, cacheable=True)

        # 与 search_movie 相同的降级逻辑
        if language is not None and (result is None or not result.get("results")):
            logger.debug(
                f"search_tv 带 language={language} 搜索无结果，"
                f"尝试不带语言参数重新搜索"
            )
            params.pop("language", None)
            result = self._request_with_retry(url, params, cacheable=True)

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
        include_adult: Optional[bool] = True,
    ) -> Optional[Dict]:
        """专门搜索电影"""
        url = f"{self.BASE_URL}/search/movie"
        params = (
            {"query": query, "page": page, "include_adult": include_adult}
            if not self.api_key.startswith("eyJ")
            else {"query": query, "page": page, "include_adult": include_adult}
        )
        # 只有当 language 不为 None 时才添加 language 参数
        if language is not None:
            params["language"] = language
        if year:
            params["year"] = year
        result = self._request_with_retry(url, params, cacheable=True)

        # 如果带了 language 参数但无结果，去掉 language 再试一次
        # TMDB 的 language 参数会限制搜索结果只匹配对应语言的标题变体，
        # 对于只有英文/日文标题的影片，带语言参数的中文搜索会返回 0 结果
        if language is not None and (result is None or not result.get("results")):
            logger.debug(
                f"search_movie 带 language={language} 搜索无结果，"
                f"尝试不带语言参数重新搜索"
            )
            params.pop("language", None)
            result = self._request_with_retry(url, params, cacheable=True)

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

    def get_movie_credits(self, movie_id: int) -> Optional[Dict]:
        """
        Get cast and crew information for a movie.

        Args:
            movie_id: TMDB ID of the movie

        Returns:
            Credits dictionary containing cast and crew or None if error
        """
        url = f"{self.BASE_URL}/movie/{movie_id}/credits"
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

        result = self._request_with_retry(url, params, cacheable=True)

        # 与 search_movie 相同的降级逻辑
        if language is not None and (result is None or not result.get("results")):
            logger.debug(
                f"search_multi 带 language={language} 搜索无结果，"
                f"尝试不带语言参数重新搜索"
            )
            params.pop("language", None)
            result = self._request_with_retry(url, params, cacheable=True)

        if result and "results" in result:
            # 返回结果列表
            return result["results"]
        return []
