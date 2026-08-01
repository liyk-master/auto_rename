"""TMDB 客户端并发能力测试：全局限速器、请求缓存、429 降速"""

import time
import threading
from unittest.mock import Mock, patch

import pytest

import video_organizer.core.tmdb_client as tmdb_module
from video_organizer.core.tmdb_client import (
    TMDBClient,
    _GlobalRateLimiter,
    _RequestCache,
    make_request_cache_key,
)


class FakeClock:
    """可手动推进的假时钟"""

    def __init__(self):
        self._now = 1000.0
        self._lock = threading.Lock()

    def time(self):
        return self._now

    def advance(self, seconds):
        with self._lock:
            self._now += seconds


@pytest.fixture
def fake_clock():
    clock = FakeClock()
    with patch("video_organizer.core.tmdb_client.time.time", side_effect=clock.time):
        with patch("video_organizer.core.tmdb_client.time.sleep", return_value=None):
            yield clock


class TestGlobalRateLimiter:
    """进程级全局限速器"""

    def test_under_limit_passes(self, fake_clock):
        limiter = _GlobalRateLimiter()
        limiter._rate_limit_per_sec = 5  # 直接设置，避免 set_rate_limit 只增不减的影响
        for _ in range(5):
            limiter.acquire()
        # 同一秒内第 6 次应阻塞，推进时钟后放行
        t = threading.Thread(target=limiter.acquire)
        t.start()
        t.join(timeout=0.2)
        assert t.is_alive()
        fake_clock.advance(1.0)
        t.join(timeout=0.2)
        assert not t.is_alive()

    def test_share_budget_between_clients(self, fake_clock):
        """多客户端共享同一限速预算"""
        shared = _GlobalRateLimiter()
        shared._rate_limit_per_sec = 3
        with patch.object(tmdb_module, "_global_rate_limiter", shared):
            client1 = TMDBClient("test_key", rate_limit_per_sec=3)
            client2 = TMDBClient("test_key", rate_limit_per_sec=3)
            resp = Mock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = {"results": [{"id": 1}]}
            client1.session.get = Mock(return_value=resp)
            client2.session.get = Mock(return_value=resp)
            # client1 打满预算（不同 query 避开缓存）
            for q in ("超人", "电影", "电视剧"):
                client1.search_multi(q, language="zh-CN")
            # client2 应被阻塞（共享预算）
            t = threading.Thread(target=lambda: client2.search_multi("测试", language="zh-CN"))
            t.start()
            t.join(timeout=0.2)
            assert t.is_alive()
            fake_clock.advance(1.0)
            t.join(timeout=0.2)
            assert not t.is_alive()

    def test_single_global_singleton(self):
        """模块级 _global_rate_limiter 是进程共享单例"""
        assert isinstance(tmdb_module._global_rate_limiter, _GlobalRateLimiter)

    def test_degrade_then_recover(self, fake_clock):
        """429 降速 30 秒后恢复原限速"""
        limiter = _GlobalRateLimiter()
        limiter._rate_limit_per_sec = 10
        limiter.degrade(rate=2, duration=30.0)
        # 降速窗口内限速 2/s：第 3 次应阻塞
        limiter.acquire()
        limiter.acquire()
        t = threading.Thread(target=limiter.acquire)
        t.start()
        t.join(timeout=0.2)
        assert t.is_alive()
        # 降速窗口未过，推进 1s 后仍只有 2/s 预算中的 1 个可用
        fake_clock.advance(1.0)
        t.join(timeout=0.2)
        assert not t.is_alive()
        # 降速窗口结束后恢复 10/s
        fake_clock.advance(30.0)
        for _ in range(10):
            limiter.acquire()

    def test_set_rate_limit_takes_max(self):
        """基础限速取所有调用方中的最大值，避免互相降速"""
        limiter = _GlobalRateLimiter()
        limiter.set_rate_limit_per_sec(5)
        limiter.set_rate_limit_per_sec(3)
        assert limiter._rate_limit_per_sec == 35  # 默认 35，5/3 均不大于
        limiter.set_rate_limit_per_sec(8)
        assert limiter._rate_limit_per_sec == 35  # 8 仍小于默认
        limiter.set_rate_limit_per_sec(40)
        assert limiter._rate_limit_per_sec == 40


class TestRequestCache:
    """线程安全 LRU 请求缓存"""

    def test_hit_does_not_re_send(self, fake_clock):
        client = TMDBClient("test_key", rate_limit_per_sec=100)
        url = f"{client.BASE_URL}/search/multi"
        params = {"query": "超人", "page": 1}
        key = make_request_cache_key(url, params)
        client._cache.put(key, {"results": [{"id": 1}]})
        assert client._cache.get(key) == {"results": [{"id": 1}]}

    def test_params_distinguish(self):
        client = TMDBClient("test_key", rate_limit_per_sec=100)
        url = f"{client.BASE_URL}/search/multi"
        client._cache.put(make_request_cache_key(url, {"query": "超人"}), {"r": 1})
        client._cache.put(make_request_cache_key(url, {"query": "电影"}), {"r": 2})
        assert client._cache.get(make_request_cache_key(url, {"query": "超人"})) == {"r": 1}
        assert client._cache.get(make_request_cache_key(url, {"query": "电影"})) == {"r": 2}

    def test_lru_eviction(self):
        cache = _RequestCache(maxsize=2)
        key1 = ("url", (("q", "a"),))
        key2 = ("url", (("q", "b"),))
        key3 = ("url", (("q", "c"),))
        cache.put(key1, {"r": 1})
        cache.put(key2, {"r": 2})
        cache.get(key1)  # key1 变为最近使用
        cache.put(key3, {"r": 3})  # 淘汰最久未用的 key2
        assert cache.get(key1) == {"r": 1}
        assert cache.get(key2) is None
        assert cache.get(key3) == {"r": 3}

    def test_search_hits_cache_no_second_request(self):
        client = TMDBClient("test_key", rate_limit_per_sec=100)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {"results": [{"id": 1, "media_type": "tv"}]}
        client.session.get = Mock(return_value=mock_response)
        client.search_multi("超人", language="zh-CN")
        client.search_multi("超人", language="zh-CN")
        assert client.session.get.call_count == 1


class TestRateLimit429:
    """429 响应处理：降速 + 尊重 Retry-After"""

    def test_429_degrade_and_retry(self):
        client = TMDBClient("test_key", retry_count=2, rate_limit_per_sec=100)
        responses = []
        for status, headers in [(429, {"Retry-After": "0"}), (200, {})]:
            resp = Mock()
            resp.status_code = status
            resp.headers = headers
            resp.text = ""
            resp.json.return_value = {"results": [{"id": 1}]}
            responses.append(resp)
        client.session.get = Mock(side_effect=responses)
        with patch(
            "video_organizer.core.tmdb_client._global_rate_limiter.degrade"
        ) as mock_degrade, patch("video_organizer.core.tmdb_client.time.sleep"):
            result = client.search_multi("超人", language="zh-CN")
        assert result == [{"id": 1}]
        mock_degrade.assert_called_once()

    def test_429_exhausts_retries_returns_none(self):
        client = TMDBClient("test_key", retry_count=1, rate_limit_per_sec=100)
        resp = Mock()
        resp.status_code = 429
        resp.headers = {}
        resp.text = ""
        client.session.get = Mock(return_value=resp)
        with patch(
            "video_organizer.core.tmdb_client._global_rate_limiter.degrade"
        ), patch("video_organizer.core.tmdb_client.time.sleep"):
            result = client.search_multi("超人", language="zh-CN")
        assert result == []
