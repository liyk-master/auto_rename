"""pytest 全局 fixtures。"""

import threading

import pytest

from video_organizer.core.renamer import VideoRenamer
from video_organizer.utils.cache import ThreadSafeLRUCache


@pytest.fixture(autouse=True)
def _isolate_renamer_shared_cache():
    """每个测试使用独立的 VideoRenamer 共享缓存，避免测试间互相污染。

    VideoRenamer 的缓存是类属性（进程级共享，见 renamer.py 类体定义）；
    若不替换，一个测试写入的 TMDB/LLM 缓存会泄漏到后续测试，
    导致断言失败或行为不可复现。
    """
    names = [
        "_tmdb_cache",
        "_tmdb_name_to_id",
        "_search_cache",
        "_season_year_boost_cache",
        "_type_resolve_cache",
        "_llm_parse_cache",
        "_tv_episode_capacity_cache",
    ]
    saved = {}
    for name in names:
        saved[name] = getattr(VideoRenamer, name)
        setattr(VideoRenamer, name, ThreadSafeLRUCache(maxsize=2000))
    saved_inflight = VideoRenamer._llm_inflight
    saved_lock = VideoRenamer._llm_cache_lock
    saved_empty_ttl = VideoRenamer._search_empty_ttl
    saved_season_infer = VideoRenamer._season_infer_cache
    VideoRenamer._llm_inflight = {}
    VideoRenamer._llm_cache_lock = threading.Lock()
    VideoRenamer._search_empty_ttl = {}
    VideoRenamer._season_infer_cache = ThreadSafeLRUCache(maxsize=2000)
    yield
    for name in names:
        setattr(VideoRenamer, name, saved[name])
    VideoRenamer._llm_inflight = saved_inflight
    VideoRenamer._llm_cache_lock = saved_lock
    VideoRenamer._search_empty_ttl = saved_empty_ttl
    VideoRenamer._season_infer_cache = saved_season_infer
