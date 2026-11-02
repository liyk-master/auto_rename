"""
TMDB API client for fetching TV show information.
"""

import logging
import threading
import time
import re
import urllib.error
import urllib.request
import urllib.parse
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
# TMDB 网站搜索偏好 Cookie（设置语言/时区/成人内容，提高搜索结果匹配度）
TMDB_WEB_COOKIE = (
    "preferences="
    '{"adult":true,"i18n_fallback_language":"en-US",'
    '"locale":"zh-CN","country_code":"US","timezone":"Asia/Shanghai"}'
)
# ⚙ 网站搜索（www.themoviedb.org）的 UA 候选：**故意不装浏览器**。
# TMDB 网站挂在 Cloudflare 后面且开了「浏览器完整性校验」（BIC）：UA 声明自己是
# Chrome（`Chrome/120.0.0.0`）但 TLS/JA3 指纹不是 Chrome 的请求（urllib、requests、
# httpx 一律如此）会被直接判到 JS 挑战页，返回 403 "Just a moment..."。
# 实测（2026-10）：
#   UA = Chrome/120.0.0.0 ...                      → 403（挑战页，即使 IP 正常、
#                                                     即使带了 preferences cookie）
#   UA = Mozilla/5.0 (compatible; xxx)             → 403（Mozilla/ 前缀同样被当浏览器）
#   UA = video-organizer/1.0 (+url) / curl/8.5.0   → 200 + 正常结果卡
# 因此这里自报身份（app UA 优先，curl 兜底），不要在搜索时改回浏览器 UA。
TMDB_WEB_USER_AGENTS = (
    "video-organizer/1.0 (+https://github.com/liyk-master/auto_rename)",
    "curl/8.5.0",
)
# 网站搜索最多保留的结果数。
# 页面通常渲染 40 张卡片（movie+tv 各 20），相关性重排后精确标题匹配会浮到最前，
# 保留较多候选供下游「年份守卫 / 精确匹配消歧」使用；旧逻辑只取前 5 条（页序），
# 冷门条目（如 1975 成人片《映像》id=67018 排在 30+ 名）会被热门子串噪音挤掉。
WEB_FALLBACK_MAX_RESULTS = 20


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
        try:
            rate = int(rate)
        except (TypeError, ValueError):
            return
        with self._lock:
            if rate and rate > self._rate_limit_per_sec:
                self._rate_limit_per_sec = rate

    def degrade(
        self,
        rate: int = DEGRADED_RATE_LIMIT_PER_SEC,
        duration: float = DEGRADE_DURATION,
    ) -> None:
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
            logger.debug(
                f"search_video_show 返回的数据键: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}"
            )
            if isinstance(data, dict):
                results = data.get("results", [])
                logger.debug(f"search_video_show results 数量: {len(results)}")
                if results:
                    logger.debug(
                        f"search_video_show 第一个结果: {results[0].get('name') or results[0].get('title') if results else 'none'}"
                    )
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

    def find_by_imdb_id(
        self,
        imdb_id: str,
        language: Optional[str] = "zh-CN",
    ) -> Optional[Dict]:
        """通过 IMDB ID（ttXXXX）反查 TMDB 条目，返回单个结果（含 media_type）。

        已整理的目录常带 {tt1727824} 标记，这是比年份猜谜强得多的类型/条目
        信号（如《女巫》目录 {tt4263482} 直接定位 2015 电影，不再被 2004
        同名剧集的季年份误判成 tv）。
        """
        url = f"{self.BASE_URL}/find/{imdb_id}"
        params = {"external_source": "imdb_id"}
        if language is not None:
            params["language"] = language
        data = self._request_with_retry(url, params, cacheable=True)
        if not data or not isinstance(data, dict):
            return None
        for mtype, key in (("movie", "movie_results"), ("tv", "tv_results")):
            results = data.get(key) or []
            if results:
                result = results[0]
                result["media_type"] = mtype
                return result
        return None

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

    def search_web_fallback(
        self,
        query: str,
        language: str = "zh-CN",
        media_type: Optional[str] = None,
    ) -> List[Dict]:
        """
        TMDB API 搜索无结果时，爬取 TMDB 网站搜索作为兜底。
        网站搜索的模糊匹配能力比 API 更强，能搜到 API 找不到的条目。

        Args:
            query: 搜索词
            language: 搜索语言（用于 Accept-Language 头）
            media_type: 媒体类型筛选（"movie" 或 "tv"），避免类型串扰

        Returns:
            搜索结果列表，格式与 search_multi 一致
        """
        if media_type in ("movie", "tv"):
            url = f"https://www.themoviedb.org/search/{media_type}?query={urllib.parse.quote(query)}"
        else:
            url = f"https://www.themoviedb.org/search?query={urllib.parse.quote(query)}"
        # language 可能为 None（调用方未指定语言），兜底为 zh-CN 避免 .split 崩溃
        lang = language or "zh-CN"
        headers_common = {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": f"{lang},{lang.split('-')[0]};q=0.9",
            "Cookie": TMDB_WEB_COOKIE,
        }
        # UA 逐个试（见 TMDB_WEB_USER_AGENTS 注释：浏览器 UA 会被 Cloudflare 挑战）
        html = ""
        last_error: Optional[Exception] = None
        for user_agent in TMDB_WEB_USER_AGENTS:
            headers = dict(headers_common, **{"User-Agent": user_agent})
            req = urllib.request.Request(url, headers=headers)
            # 网站搜索不走 API 网关，但同样消耗 TMDB 服务器额度；
            # 必须走进程级全局限速器，否则多实例并发时网站搜索会互相打爆 429
            _global_rate_limiter.acquire()
            try:
                html = (
                    urllib.request.urlopen(req, timeout=15)
                    .read()
                    .decode("utf-8", "ignore")
                )
                break
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code in (403, 429):
                    # 被 Cloudflare 挑战 / 限速：换下一个 UA 再试
                    logger.info(
                        f"TMDB 网站搜索被拦（HTTP {e.code}），换用下一个 UA 重试"
                    )
                    continue
                logger.warning(f"TMDB 网站搜索失败: {e}")
                return []
            except Exception as e:
                last_error = e
                logger.warning(f"TMDB 网站搜索失败: {e}")
                return []

        if not html:
            logger.warning(f"TMDB 网站搜索失败: {last_error}")
            return []

        if not html:
            return []

        # 从 HTML 中提取 movie/tv 卡片（ID / 标题 / 原始名 / 发布日期）
        # 网站搜索结果结构（TMDB 改版后）:
        #   <div id="..." class="comp:media-card ..." data-object-id="...">
        #     <a class="flex w-full" data-media-type="movie" data-media-adult="true"
        #        href="/movie/67018-the-image"><img alt="映像" class="poster" ...></a>
        #     ...
        #     <a ... href="/movie/67018-the-image"><h2 ...><span>映像</span>
        #       <span class="font-light"> (The Image)</span>...</h2></a>
        #     <span class="release_date w-full font-light">1975 年 12 月 20 日</span>
        #   </div>
        # ⚙ href 从 /movie/131482（纯 id）变为 /movie/10054-spy-kids（id-slug 格式），
        #   正则必须允许 slug 后缀，否则全部失配返回 0 结果。
        # ⚙ 按 class="comp:media-card 切分卡片：海报链接和标题链接是两个 <a>，且发布
        #   日期/原始名在标题链接之后，旧「锚点→下一锚点」切片会丢掉这些字段——
        #   缺失 release_date 会让年份守卫把网页候选当「年份未知」，无法按年份选中。
        seen_ids = set()
        results = []
        for card_seg in html.split('class="comp:media-card')[1:]:
            m = re.search(
                r'data-media-type="(movie|tv)"[^>]*?href="/(movie|tv)/(\d+)[^"]*"',
                card_seg,
            )
            if not m:
                continue
            card_media_type = m.group(1)
            entity_id = m.group(3)
            if entity_id in seen_ids:
                continue
            seen_ids.add(entity_id)

            # 标题：海报 <img alt="TITLE">（zh-CN 本地化标题）
            title = ""
            img_alt = re.search(r'<img[^>]*?alt="([^"]*)"', card_seg)
            if img_alt:
                title = img_alt.group(1).strip()
            if not title:
                # 降级：标题链接 h2 内的文本
                title_match = re.search(r"<h2[^>]*><span>([^<]*)</span>", card_seg)
                if title_match:
                    title = title_match.group(1).strip()
            if not title:
                continue

            item = {
                "id": int(entity_id),
                "media_type": card_media_type,
                "title": title,
                "name": title,
                "_web_fallback": True,
            }

            # 原始名（卡片 h2 内 <span class="font-light"> (Original)</span>）
            ot = re.search(
                (
                    r"<h2[^>]*><span>[^<]*</span>"
                    r'<span class="font-light">\s*\(([^)]*)\)\s*</span>'
                ),
                card_seg,
            )
            if ot and ot.group(1).strip():
                item["original_title"] = ot.group(1).strip()
                if card_media_type == "tv":
                    item["original_name"] = ot.group(1).strip()

            # 发布日期（本地化 "1975 年 12 月 20 日"；英文页可能 "Dec 20, 1975"，
            # 兜底只取任意 4 位年份）。下游年份守卫/精确匹配按它做年份对齐，
            # 缺失会让候选变成「年份未知」而无法命中。
            rd = re.search(
                r'<span class="release_date[^"]*"[^>]*>([^<]*)</span>', card_seg
            )
            if rd:
                _dt = rd.group(1).strip()
                if _dt:
                    _dm = re.match(
                        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", _dt
                    )
                    _date_key = (
                        "release_date"
                        if card_media_type == "movie"
                        else "first_air_date"
                    )
                    if _dm:
                        item[_date_key] = (
                            f"{_dm.group(1)}-{int(_dm.group(2)):02d}-"
                            f"{int(_dm.group(3)):02d}"
                        )
                    else:
                        _dy = re.search(r"(\d{4})", _dt)
                        if _dy:
                            item[_date_key] = f"{_dy.group(1)}-01-01"
            results.append(item)

        # 按请求的 media_type 过滤，避免类型串扰
        # （TMDB 页面即使指定 /search/movie，仍可能包含 TV 卡片）
        if media_type in ("movie", "tv"):
            results = [r for r in results if r["media_type"] == media_type]

        # 相关性重排：TMDB 网页按热度排卡片，冷门/成人条目（如 1975 成人片
        # 《映像》id=67018）可能排到 30+ 名，旧逻辑按页序截前 5 条会把它丢掉；
        # 按「本地化标题/原始名 与查询词的匹配度」重排，让精确标题匹配浮到最前，
        # 再截断，冷门条目才不会被热门子串噪音挤掉。
        def _norm_match(s):
            return re.sub(r"[\s\-_;.·・]", "", (s or "").lower())

        _q = _norm_match(query)

        def _relevance(r):
            _t = _norm_match(r.get("title"))
            _o = _norm_match(r.get("original_title"))
            if _q and (_t == _q or (_o and _o == _q)):
                return 0
            if _q and _t and (_q in _t or _t in _q or (_o and (_q in _o or _o in _q))):
                return 1
            return 2

        results.sort(key=_relevance)

        # 去重后保留前 N 条（重排后精确匹配已浮到最前）
        seen = set()
        deduped = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                deduped.append(r)
                if len(deduped) >= WEB_FALLBACK_MAX_RESULTS:
                    break

        if deduped:
            logger.info(
                f"TMDB 网站搜索找到 {len(deduped)} 个结果: "
                f"{[r.get('title') or r.get('name') for r in deduped]}"
            )
        return deduped
