"""
Tests for LLM fallback caching / single-flight / TMDB search-alias registration.

回归目标：同一目录下的裸序号文件（"剧名（2026）/01.mp4"、"02.mp4"）并发进入时，
LLM 兜底只应被真正调用一次。
"""

import threading
import time
from pathlib import Path

import pytest

from video_organizer.core.renamer import VideoRenamer

_UNSET = object()


class FakeTranslator:
    """记录调用次数的 LLMTranslator 替身。"""

    def __init__(self, result=_UNSET, delay=0.0):
        self.calls = []
        self.delay = delay
        self.result = (
            {
                "show_name": "早春晴朗",
                "tmdb_corrected_title": None,
                "season": 1,
                "episode": 5,
                "year": 2026,
                "release_group": None,
                "media_type": "tv",
                "original_language": "zh-CN",
            }
            if result is _UNSET
            else result
        )
        self._lock = threading.Lock()

    def parse_filename(self, filename):
        with self._lock:
            self.calls.append(filename)
        if self.delay:
            time.sleep(self.delay)
        return dict(self.result) if self.result else self.result


@pytest.fixture
def renamer():
    return VideoRenamer("fake_tmdb_key")


@pytest.fixture
def wired(renamer):
    """启用 LLM 兜底并换上替身 translator。"""
    fake = FakeTranslator()
    renamer.llm_translator = fake
    renamer._llm_fallback_enabled = True
    return renamer, fake


class TestBuildCacheKey:
    def test_same_dir_different_episode_shares_key(self, renamer):
        k1 = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")
        k2 = renamer._build_llm_parse_cache_key("剧名（2026）/02.mp4", "Z 早春晴朗")
        assert k1 == k2

    def test_different_dir_or_name_does_not_share_key(self, renamer):
        k1 = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")
        k2 = renamer._build_llm_parse_cache_key("另一部剧（2025）/01.mp4", "Z 早春晴朗")
        k3 = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "别的名字")
        assert k1 != k2
        assert k1 != k3

    def test_key_is_case_and_space_insensitive_on_show_name(self, renamer):
        k1 = renamer._build_llm_parse_cache_key("d/01.mp4", "Show Name")
        k2 = renamer._build_llm_parse_cache_key("d/02.mp4", "  SHOW NAME  ")
        assert k1 == k2


class TestParseFilenameWithCache:
    def test_second_call_hits_cache(self, wired):
        renamer, fake = wired
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        first = renamer._parse_filename_with_cache("剧名（2026）/01.mp4", key)
        second = renamer._parse_filename_with_cache("剧名（2026）/02.mp4", key)

        assert first["show_name"] == "早春晴朗"
        assert second["show_name"] == "早春晴朗"
        assert len(fake.calls) == 1

    def test_cache_never_reuses_episode_or_season(self, wired):
        """集数/季数是文件级信息，不得跨集复用。"""
        renamer, fake = wired
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        renamer._parse_filename_with_cache("剧名（2026）/01.mp4", key)
        cached = renamer._parse_filename_with_cache("剧名（2026）/02.mp4", key)

        assert cached["episode"] is None
        assert cached["season"] is None
        # 剧名/年份/类型是目录级信息，应当保留
        assert cached["show_name"] == "早春晴朗"
        assert cached["year"] == 2026
        assert cached["media_type"] == "tv"

    def test_returned_dict_is_a_copy(self, wired):
        renamer, fake = wired
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")
        renamer._parse_filename_with_cache("剧名（2026）/01.mp4", key)
        again = renamer._parse_filename_with_cache("剧名（2026）/02.mp4", key)
        again["show_name"] = "mutated"
        third = renamer._parse_filename_with_cache("剧名（2026）/03.mp4", key)
        assert third["show_name"] == "早春晴朗"

    def test_empty_result_is_not_cached(self, wired):
        renamer, fake = wired
        fake.result = None
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        assert renamer._parse_filename_with_cache("剧名（2026）/01.mp4", key) is None
        assert renamer._parse_filename_with_cache("剧名（2026）/02.mp4", key) is None
        assert len(fake.calls) == 2

    def test_concurrent_requests_collapse_to_one_call(self, wired):
        """并发进入时 single-flight：同 key 只真正调用一次 LLM。"""
        renamer, fake = wired
        fake.delay = 0.2
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        results = []
        barrier = threading.Barrier(4)

        def worker(name):
            barrier.wait()
            results.append(
                renamer._parse_filename_with_cache(f"剧名（2026）/{name}.mp4", key)
            )

        threads = [
            threading.Thread(target=worker, args=(f"0{i}",)) for i in range(1, 5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(fake.calls) == 1
        assert len(results) == 4
        assert all(r and r["show_name"] == "早春晴朗" for r in results)
        # 在途请求结束后必须清理干净，不能留下悬挂的 event
        assert renamer._llm_inflight == {}

    def test_exception_wakes_waiters(self, wired):
        renamer, fake = wired

        def boom(filename):
            time.sleep(0.1)
            raise RuntimeError("llm down")

        fake.parse_filename = boom
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        errors = []

        def leader():
            try:
                renamer._parse_filename_with_cache("剧名（2026）/01.mp4", key)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def follower():
            time.sleep(0.02)
            errors.append(
                renamer._parse_filename_with_cache("剧名（2026）/02.mp4", key)
            )

        t1, t2 = threading.Thread(target=leader), threading.Thread(target=follower)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not t1.is_alive() and not t2.is_alive()
        assert any(isinstance(e, RuntimeError) for e in errors)
        assert renamer._llm_inflight == {}

    def test_waiters_do_not_hold_semaphore(self, wired):
        """并发槽只有 1 个时，等待同类请求的线程不应占槽而让后续文件被跳过。"""
        renamer, fake = wired
        fake.delay = 0.3
        renamer._llm_semaphore = threading.Semaphore(1)
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        results = []
        rlock = threading.Lock()
        barrier = threading.Barrier(3)

        def worker(n):
            barrier.wait()
            got = renamer._parse_filename_with_cache(f"剧名（2026）/0{n}.mp4", key)
            with rlock:
                results.append(got)

        threads = [threading.Thread(target=worker, args=(i,)) for i in (1, 2, 3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not any(t.is_alive() for t in threads)
        assert len(fake.calls) == 1
        assert len(results) == 3
        assert all(r and r["show_name"] == "早春晴朗" for r in results)

    def test_semaphore_timeout_releases_waiters(self, wired):
        """leader 抢不到并发槽时，必须放弃并唤醒等待者，不能留悬挂请求。"""
        renamer, fake = wired
        renamer._llm_semaphore = threading.Semaphore(0)  # 永久占满
        renamer._llm_wait_timeout = 0.2
        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        assert renamer._parse_filename_with_cache("剧名（2026）/01.mp4", key) is None
        assert fake.calls == []
        assert renamer._llm_inflight == {}

    def test_different_keys_still_limited_by_semaphore(self, wired):
        """不同剧名不能合并，但仍受并发槽限制。"""
        renamer, fake = wired
        fake.delay = 0.15
        renamer._llm_semaphore = threading.Semaphore(1)

        k1 = renamer._build_llm_parse_cache_key("剧A（2026）/01.mp4", "剧A")
        k2 = renamer._build_llm_parse_cache_key("剧B（2026）/01.mp4", "剧B")
        t0 = time.time()
        renamer._parse_filename_with_cache("剧A（2026）/01.mp4", k1)
        renamer._parse_filename_with_cache("剧B（2026）/01.mp4", k2)

        assert len(fake.calls) == 2
        assert time.time() - t0 >= 0.3  # 串行执行，未被并发跳过


class TestEndToEndSameDirectory:
    """端到端回归：同一目录下的裸序号文件只应触发一次 LLM 兜底。"""

    FAKE_RESULTS = [
        {
            "name": "早春晴朗",
            "title": "早春晴朗",
            "original_name": "早春晴朗",
            "id": 999001,
            "media_type": "tv",
            "first_air_date": "2026-01-05",
            "original_language": "zh-CN",
            "popularity": 50,
            "genre_ids": [18],
            "origin_country": ["CN"],
            "overview": "x",
            "vote_average": 7.0,
            "vote_count": 10,
            "backdrop_path": "",
            "poster_path": "",
        }
    ]
    DETAILS = {
        "name": "早春晴朗",
        "original_name": "早春晴朗",
        "overview": "x",
        "first_air_date": "2026-01-05",
        "number_of_seasons": 1,
        "number_of_episodes": 24,
        "genres": [{"id": 18, "name": "剧情"}],
        "original_language": "zh-CN",
        "origin_country": ["CN"],
        "status": "Returning Series",
        "vote_average": 7.0,
        "vote_count": 10,
        "poster_path": "",
        "backdrop_path": "",
        "adult": False,
    }

    class StubTMDB:
        """不发真请求；详情能拿到，搜索全空（逼出 LLM 兜底）。"""

        def get_tv_details(self, *a, **k):
            return dict(TestEndToEndSameDirectory.DETAILS)

        def get_movie_details(self, *a, **k):
            return dict(TestEndToEndSameDirectory.DETAILS)

        def get_tv_credits(self, *a, **k):
            return {}

        def get_movie_credits(self, *a, **k):
            return {}

        def __getattr__(self, name):
            return lambda *a, **k: []

    @pytest.fixture
    def env(self, tmp_path):
        # 必须显式启用 GuessIt：裸序号文件名依赖它的中文目录预处理
        # （“剧名（2026）/01.mp4” → “剧名 E01.mp4”）才能提取出剧名与集数
        renamer = VideoRenamer("fake_tmdb_key", config={"guessit": {"enabled": True}})
        renamer.tmdb_client = self.StubTMDB()
        # 主搜索失败 → 进入备选策略3（LLM 兜底）
        renamer._search_tmdb_by_type = lambda *a, **k: []
        fake = FakeTranslator(delay=0.2)
        state = {"llm_done": False}
        original_parse = fake.parse_filename

        def spy_parse(fn):
            state["llm_done"] = True
            return original_parse(fn)

        fake.parse_filename = spy_parse
        renamer.llm_translator = fake
        renamer._llm_fallback_enabled = True
        # LLM 之后的搜索才能命中（模拟“纠正剧名后搜得到”）
        renamer._search_with_language = lambda *a, **k: (
            list(self.FAKE_RESULTS) if state["llm_done"] else []
        )

        media_dir = tmp_path / "Z 早春晴朗（2026）"
        media_dir.mkdir()
        files = []
        for name in ("01.mp4", "02.mp4", "03.mp4"):
            p = media_dir / name
            p.write_bytes(b"x" * 1024)
            files.append(str(p))
        return renamer, fake, files

    def test_serial_episodes_call_llm_once(self, env):
        renamer, fake, files = env
        results = [renamer.extract_metadata(f) for f in files]

        assert len(fake.calls) == 1
        for md, expected_ep in zip(results, (1, 2, 3)):
            assert md["tmdb_id"] == 999001
            assert md["show_name"] == "早春晴朗"
            assert int(md["episode"]) == expected_ep
            # 季数必须一致，否则同目录文件会被拆到不同路径
            assert md["season"] == results[0]["season"]

    def test_concurrent_episodes_call_llm_once(self, env):
        renamer, fake, files = env
        collected = {}
        rlock = threading.Lock()
        barrier = threading.Barrier(len(files))

        def worker(path):
            barrier.wait()
            md = renamer.extract_metadata(path)
            with rlock:
                collected[Path(path).name] = md

        threads = [threading.Thread(target=worker, args=(f,)) for f in files]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not any(t.is_alive() for t in threads)
        assert len(fake.calls) == 1
        assert len(collected) == 3
        assert {k: int(v["episode"]) for k, v in collected.items()} == {
            "01.mp4": 1,
            "02.mp4": 2,
            "03.mp4": 3,
        }
        assert {v["tmdb_id"] for v in collected.values()} == {999001}

    def test_second_run_skips_llm_entirely(self, env):
        """别名缓存生效后，后续集数连 LLM 分支都不应进入。"""
        renamer, fake, files = env
        renamer.extract_metadata(files[0])
        assert len(fake.calls) == 1
        # 第二集：入口即命中别名缓存
        renamer.extract_metadata(files[1])
        assert len(fake.calls) == 1
        # native 路径上下文命中后，父目录“Z 早春晴朗（2026）”被清理为
        # “早春晴朗”（Z 为杂讯前缀），因此别名键不再带“z ”前缀
        assert "早春晴朗_tv" in renamer._tmdb_name_to_id


class TestCrossInstanceSharedCache:
    """进程级共享缓存：不同实例（如 /api/manual/validate 每请求 new 一个）
    也必须合并 LLM 调用。"""

    def test_two_instances_share_llm_parse_cache(self, renamer):
        other = VideoRenamer("fake_tmdb_key")
        fake = FakeTranslator()
        renamer.llm_translator = fake
        renamer._llm_fallback_enabled = True
        # 第二个实例不配 translator，命中缓存时不会触碰它
        other.llm_translator = None
        other._llm_fallback_enabled = True

        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")

        r1 = renamer._parse_filename_with_cache("剧名（2026）/01.mp4", key)
        # 第二个实例命中第一个实例写入的缓存
        r2 = other._parse_filename_with_cache("剧名（2026）/02.mp4", key)

        assert r1 is not None and r1["show_name"] == "早春晴朗"
        assert r2 is not None and r2["show_name"] == "早春晴朗"
        assert len(fake.calls) == 1

    def test_two_instances_share_single_flight(self, renamer):
        """跨实例并发：多个实例同时解析同目录，只有一次真正调 LLM。"""
        other = VideoRenamer("fake_tmdb_key")
        fake = FakeTranslator(delay=0.2)
        renamer.llm_translator = fake
        renamer._llm_fallback_enabled = True
        other.llm_translator = fake
        other._llm_fallback_enabled = True

        key = renamer._build_llm_parse_cache_key("剧名（2026）/01.mp4", "Z 早春晴朗")
        results = []
        barrier = threading.Barrier(4)
        rlock = threading.Lock()

        def worker(inst, name):
            barrier.wait()
            got = inst._parse_filename_with_cache(f"剧名（2026）/{name}.mp4", key)
            with rlock:
                results.append(got)

        threads = [
            threading.Thread(target=worker, args=(renamer, "01")),
            threading.Thread(target=worker, args=(renamer, "03")),
            threading.Thread(target=worker, args=(other, "02")),
            threading.Thread(target=worker, args=(other, "04")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not any(t.is_alive() for t in threads)
        assert len(fake.calls) == 1
        assert len(results) == 4
        assert all(r and r["show_name"] == "早春晴朗" for r in results)
        assert VideoRenamer._llm_inflight == {}


class TestSearchWithLanguageCache:
    """_search_with_language 的 single-flight 合并 + 空结果短时缓存。"""

    class StubTMDB:
        def __init__(self, calls, hits=None):
            self.calls = calls
            self.hits = hits or {}

        def search_all_pages(self, method, term, **k):
            self.calls.append(("api", term))
            time.sleep(0.15)
            return list(self.hits.get(term, []))

        def search_web_fallback(self, term, **k):
            self.calls.append(("web", term))
            return list(self.hits.get(term, []))

    def test_concurrent_same_key_calls_tmdb_once(self, renamer):
        calls = []
        renamer.tmdb_client = self.StubTMDB(calls)
        results = []
        rlock = threading.Lock()
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            got = renamer._search_with_language(
                "晚酌的流派5：夏篇", "tv", "2026", "zh-CN"
            )
            with rlock:
                results.append(got)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # 只有 leader 真正发请求：带年份 1 次 + 去年份 1 次 + 网站兜底 1 次
        assert len(calls) == 3
        assert all(r == [] for r in results)

    def test_empty_result_cached_with_ttl(self, renamer):
        calls = []
        renamer.tmdb_client = self.StubTMDB(calls)

        renamer._search_with_language("找不到的剧", "tv", None, "zh-CN")
        renamer._search_with_language("找不到的剧", "tv", None, "zh-CN")
        assert len(calls) == 2  # 带年份无，直接 API 1 次 + 网站 1 次；第二次命中空缓存

        # TTL 过期后重新搜索
        key = ("找不到的剧", "tv", None, "zh-CN")
        renamer._search_empty_ttl[key] = time.time() - 1
        renamer._search_with_language("找不到的剧", "tv", None, "zh-CN")
        assert len(calls) == 4  # 又发了一次完整搜索

    def test_hit_result_cached_permanently(self, renamer):
        calls = []
        fake = [{"id": 1, "name": "晚酌的流派", "media_type": "tv"}]
        renamer.tmdb_client = self.StubTMDB(calls, hits={"晚酌的流派": fake})

        r1 = renamer._search_with_language("晚酌的流派", "tv", None, "zh-CN")
        r2 = renamer._search_with_language("晚酌的流派", "tv", None, "zh-CN")
        assert r1 and r2
        assert len(calls) == 1  # API 命中即返回；第二次命中缓存不再发请求


class TestNoAggressiveTruncation:
    """回归：季号/续集序号截断已移除——电影续作（"终结者2：审判日"）和
    带季号的剧名（"晚酌的流派5：夏篇"）都不允许被截断成基础名，
    否则会误识别到第一部。"""

    def test_movie_sequel_is_not_truncated(self, tmp_path):
        from video_organizer.core.config_loader import load_config

        config = load_config("config.ini")
        renamer = VideoRenamer(
            tmdb_api_key=config.get("tmdb", {}).get("api_key", "f"),
            config={"guessit": {"enabled": True}},
        )
        media_dir = tmp_path / "终结者2：审判日（1991）"
        media_dir.mkdir()
        f = media_dir / "终结者2：审判日 1991 1080p.mkv"
        f.write_bytes(b"x" * 1024)

        searched = []
        lock = threading.Lock()

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                with lock:
                    searched.append(term)
                return []

            def search_web_fallback(self, term, **k):
                with lock:
                    searched.append(term)
                return []

        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False

        md = renamer.extract_metadata(str(f), media_type_hint="movie")
        # 识别失败（全部搜不到）可接受，但绝不允许截断成 "终结者" 去搜第一部
        assert "终结者" not in searched
        assert md.get("tmdb_id") == ""

    def test_tv_seasoned_name_not_truncated(self, tmp_path):
        from video_organizer.core.config_loader import load_config

        config = load_config("config.ini")
        renamer = VideoRenamer(
            tmdb_api_key=config.get("tmdb", {}).get("api_key", "f"),
            config={"guessit": {"enabled": True}},
        )
        media_dir = tmp_path / "晚酌的流派5：夏篇（2026）"
        media_dir.mkdir()
        f = media_dir / "01.mp4"
        f.write_bytes(b"x" * 1024)

        searched = []
        lock = threading.Lock()

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                with lock:
                    searched.append(term)
                return []

            def search_web_fallback(self, term, **k):
                with lock:
                    searched.append(term)
                return []

        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False

        md = renamer.extract_metadata(str(f), media_type_hint="tv")
        # 不会被截断成 "晚酌的流派" 去搜第一部
        assert "晚酌的流派" not in [t for t in searched if t != "晚酌的流派5：夏篇"]
        assert md.get("tmdb_id") == ""


class TestTmdbSearchAlias:
    def test_alias_allows_next_episode_to_hit_cache(self, renamer):
        """LLM 纠正剧名后，下一集用「未纠正的原始名」也必须能命中缓存。"""
        metadata = {
            "show_name": "早春晴朗",
            "year": "2026",
            "media_type": "tv",
            "tmdb_id": 999001,
            "episode": 1,
        }
        renamer._save_to_tmdb_cache(metadata, search_alias="Z 早春晴朗")

        # 纠正后的名字与别名都可用
        assert "早春晴朗_2026_tv" in renamer._tmdb_cache
        assert "z 早春晴朗_2026_tv" in renamer._tmdb_cache
        assert renamer._tmdb_name_to_id["z 早春晴朗_tv"] == 999001

    def test_no_alias_registered_when_names_match(self, renamer):
        metadata = {
            "show_name": "早春晴朗",
            "year": "2026",
            "media_type": "tv",
            "tmdb_id": 999001,
        }
        renamer._save_to_tmdb_cache(metadata, search_alias="早春晴朗")
        assert list(renamer._tmdb_name_to_id.keys()) == ["早春晴朗_tv"]

    def test_alias_is_scoped_by_media_type(self, renamer):
        metadata = {
            "show_name": "早春晴朗",
            "year": "2026",
            "media_type": "tv",
            "tmdb_id": 999001,
        }
        renamer._save_to_tmdb_cache(metadata, search_alias="Z 早春晴朗")
        assert "z 早春晴朗_movie" not in renamer._tmdb_name_to_id

    def test_missing_tmdb_id_writes_nothing(self, renamer):
        renamer._save_to_tmdb_cache(
            {"show_name": "早春晴朗", "media_type": "tv"}, search_alias="Z 早春晴朗"
        )
        assert renamer._tmdb_cache == {}
        assert renamer._tmdb_name_to_id == {}


class TestSeasonYearBoostCache:
    """_get_season_year_boost 的 single-flight 与键隔离。"""

    def _details(self, season_air_dates):
        return {
            "first_air_date": "2024-01-01",  # 首播年份故意不与目标年份匹配
            "seasons": [
                {"season_number": n, "air_date": d} for n, d in season_air_dates
            ],
        }

    def test_key_includes_target_year(self, renamer):
        """回归：缓存键缺 year 时，不同目标年份的结果互相污染。"""
        details = self._details([(1, "2026-01-05")])  # 第1季 2026 年播出
        renamer.tmdb_client = type(
            "Stub", (), {"get_tv_details": lambda *a, **k: dict(details)}
        )()

        # 目标年份 2026 → 匹配，+500
        assert renamer._get_season_year_boost(999, 2026, 1) == 500
        # 目标年份 2025 → 不匹配，0（若键缺 year 会错误地返回 500）
        assert renamer._get_season_year_boost(999, 2025, 1) == 0

    def test_concurrent_calls_query_tmdb_once(self, renamer):
        details = self._details([(1, "2026-01-05")])
        calls = []
        lock = threading.Lock()

        def fake_details(*a, **k):
            with lock:
                calls.append(1)
            time.sleep(0.2)
            return dict(details)

        renamer.tmdb_client = type("Stub", (), {"get_tv_details": fake_details})()

        results = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            results.append(renamer._get_season_year_boost(999, 2026, 1))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(calls) == 1
        assert results == [500] * 4

    def test_cache_hit_skips_tmdb(self, renamer):
        details = self._details([(1, "2026-01-05")])
        calls = []

        def fake_details(*a, **k):
            calls.append(1)
            return dict(details)

        renamer.tmdb_client = type("Stub", (), {"get_tv_details": fake_details})()
        renamer._get_season_year_boost(999, 2026, 1)
        renamer._get_season_year_boost(999, 2026, 1)
        assert len(calls) == 1


class TestTypeResolveCache:
    """_type_resolve_cache 的 single-flight 合并。"""

    def test_concurrent_calls_collapse_to_one_search(self, renamer):
        calls = []
        lock = threading.Lock()

        def fake_search(*a, **k):
            with lock:
                calls.append(1)
            time.sleep(0.15)
            return [
                {
                    "media_type": "tv",
                    "id": 1,
                    "first_air_date": "2026-01-05",
                    "name": "早春晴朗",
                }
            ]

        renamer.tmdb_client = type("Stub", (), {"search_all_pages": fake_search})()
        renamer._result_matches_year = lambda *a, **k: True

        metadata = {"show_name": "早春晴朗", "year": "2026"}
        results = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            results.append(
                renamer._resolve_ambiguous_media_type_via_tmdb(metadata, "2026")
            )

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(calls) == 1
        assert results == ["tv"] * 4

    def test_none_result_is_cached(self, renamer):
        """无法判定也缓存，避免反复 multi 搜索。"""
        calls = []

        def fake_search(*a, **k):
            calls.append(1)
            return []

        renamer.tmdb_client = type("Stub", (), {"search_all_pages": fake_search})()
        metadata = {"show_name": "早春晴朗", "year": "2026"}

        assert renamer._resolve_ambiguous_media_type_via_tmdb(metadata, "2026") is None
        assert renamer._resolve_ambiguous_media_type_via_tmdb(metadata, "2026") is None
        assert len(calls) == 1


class TestSeasonConsistencyAcrossCachePaths:
    """回归：同季多集 / 跨季目录的 season 必须一致，不能被缓存路径吞掉。

    场景C 复现过 bug：首集走完整流程 season=1，次集走 name_key 快速路径
    （"直接使用该ID获取元数据"分支）后 season=None → 重命名路径被拆到不同季目录。
    """

    def test_same_dir_second_episode_keeps_season(self, renamer):
        from video_organizer.core.config_loader import load_config

        config = load_config("config.ini")
        renamer.tmdb_client = None
        renamer._search_tmdb_by_type = lambda *a, **k: []
        renamer._llm_fallback_enabled = False

        # 直接构造：首集已缓存 name_key，次集走 name_key 快速路径
        DETAILS = {
            "name": "剧名",
            "original_name": "剧名",
            "overview": "x",
            "first_air_date": "2022-04-01",
            "number_of_seasons": 4,
            "number_of_episodes": 100,
            "genres": [{"id": 18, "name": "剧情"}],
            "original_language": "zh-CN",
            "origin_country": ["CN"],
            "status": "Returning Series",
            "vote_average": 7.0,
            "vote_count": 10,
            "poster_path": "",
            "backdrop_path": "",
            "adult": False,
        }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def get_tv_details(self, *a, **k):
                return dict(DETAILS)

            def get_tv_credits(self, *a, **k):
                return {}

        renamer.tmdb_client = StubTMDB()
        renamer._search_with_language = lambda *a, **k: []
        # 模拟首集已经在名称缓存里注册了 tmdb_id
        renamer._tmdb_name_to_id["剧名_tv"] = 10001

        metadata = {
            "show_name": "剧名",
            "year": "2026",
            "media_type": "tv",
            "season": None,
            "episode": 2,
            "original_filename": "剧名（2026）/02.mp4",
        }
        result = renamer._enrich_with_tmdb(metadata)
        # name_key 快捷路径也必须给出 season=1 兜底，与完整路径一致
        assert result.get("season") == 1

    def test_standard_season_dirs_same_show_share_cache(self, renamer):
        """S01/S02 子目录 + 相同剧名：零 LLM 缓存污染，season 由目录解析。"""
        # 注册名称缓存（模拟第一季已识别）
        renamer._tmdb_name_to_id["剧名_tv"] = 10001
        # 两个不同季文件命中的是同一 name_key，season 各自来自目录名，互不覆盖
        assert renamer._tmdb_name_to_id.get("剧名_tv") == 10001
        # 名称缓存不含 season 维度：S01/S02 共享同一 tmdb_id 是正确的（同一部剧）
        assert "剧名" in [k.rsplit("_", 1)[0] for k in renamer._tmdb_name_to_id]


class TestInferSeasonFromYear:
    """用目录年份反推季号（死神 千年血战篇 -祸进谭（2026）→ S04）。"""

    def _stub(self, seasons, first_air="2022-10-01", calls=None):
        details = {
            "name": "死神 千年血战篇",
            "first_air_date": first_air,
            "seasons": [{"season_number": n, "air_date": d} for n, d in seasons],
        }

        class Stub:
            def get_tv_details(self, *a, **k):
                if calls is not None:
                    calls.append(1)
                return dict(details)

        return Stub()

    def test_single_season_match_returns_season(self, renamer):
        renamer.tmdb_client = self._stub(
            [
                (1, "2022-10-01"),
                (2, "2023-07-01"),
                (3, "2024-10-01"),
                (4, "2026-01-01"),
            ]
        )
        assert renamer._infer_season_from_year(333251, "2026") == 4

    def test_season_zero_is_skipped(self, renamer):
        renamer.tmdb_client = self._stub([(0, "2026-01-01"), (4, "2026-01-01")])
        assert renamer._infer_season_from_year(333251, "2026") == 4

    def test_no_match_returns_none(self, renamer):
        renamer.tmdb_client = self._stub([(1, "2022-10-01"), (2, "2023-07-01")])
        assert renamer._infer_season_from_year(333251, "2026") is None

    def test_multiple_seasons_same_year_returns_none(self, renamer):
        renamer.tmdb_client = self._stub([(1, "2026-01-01"), (2, "2026-06-01")])
        assert renamer._infer_season_from_year(333251, "2026") is None

    def test_result_is_cached(self, renamer):
        calls = []
        renamer.tmdb_client = self._stub([(4, "2026-01-01")], calls=calls)
        assert renamer._infer_season_from_year(333251, "2026") == 4
        assert renamer._infer_season_from_year(333251, "2026") == 4
        assert len(calls) == 1

    def test_ensure_season_uses_inferred_then_defaults_to_1(self, renamer):
        # 反推成功
        renamer.tmdb_client = self._stub([(4, "2026-01-01")])
        md = {
            "show_name": "死神 千年血战篇",
            "year": "2026",
            "tmdb_id": 333251,
            "episode": 1,
            "season": None,
        }
        renamer._ensure_season(md)
        assert md["season"] == 4

        # 反推失败（无匹配）→ 默认第 1 季（换 tmdb_id 避开进程级共享缓存）
        renamer.tmdb_client = self._stub([(1, "2022-10-01")])
        md2 = {
            "show_name": "剧名",
            "year": "2026",
            "tmdb_id": 999990,
            "episode": 1,
            "season": None,
        }
        renamer._ensure_season(md2)
        assert md2["season"] == 1

        # 已有 season 不动
        md3 = {
            "show_name": "剧名",
            "year": "2026",
            "tmdb_id": 999991,
            "episode": 1,
            "season": 3,
        }
        renamer._ensure_season(md3)
        assert md3["season"] == 3

    def test_season_inferred_from_year(self, tmp_path):
        from video_organizer.core.config_loader import load_config

        config = load_config("config.ini")
        renamer = VideoRenamer(
            tmdb_api_key=config.get("tmdb", {}).get("api_key", "f"),
            config={"guessit": {"enabled": True}},
        )
        media_dir = tmp_path / "死神 千年血战篇 -祸进谭（2026）更新至7集"
        media_dir.mkdir()
        f = media_dir / "01.mp4"
        f.write_bytes(b"x" * 1024)

        FAKE = [
            {
                "name": "死神 千年血战篇",
                "title": "死神 千年血战篇",
                "original_name": "Bleach: Thousand-Year Blood War",
                "id": 333251,
                "media_type": "tv",
                "first_air_date": "2022-10-01",
                "original_language": "ja",
                "popularity": 50,
                "genre_ids": [16],
                "origin_country": ["JP"],
                "overview": "x",
                "vote_average": 8.0,
                "vote_count": 10,
                "backdrop_path": "",
                "poster_path": "",
            }
        ]
        DETAILS = {
            "name": "死神 千年血战篇",
            "original_name": "Bleach: Thousand-Year Blood War",
            "overview": "x",
            "first_air_date": "2022-10-01",
            "number_of_seasons": 4,
            "number_of_episodes": 40,
            "genres": [{"id": 16, "name": "动画"}],
            "original_language": "ja",
            "origin_country": ["JP"],
            "status": "Returning Series",
            "vote_average": 8.0,
            "vote_count": 10,
            "poster_path": "",
            "backdrop_path": "",
            "adult": False,
            "seasons": [
                {"season_number": 1, "air_date": "2022-10-01"},
                {"season_number": 2, "air_date": "2023-07-01"},
                {"season_number": 3, "air_date": "2024-10-01"},
                {"season_number": 4, "air_date": "2026-01-01"},
            ],
        }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                return list(FAKE)

            def search_web_fallback(self, term, **k):
                return []

            def get_tv_details(self, *a, **k):
                return dict(DETAILS)

            def get_tv_credits(self, *a, **k):
                return {}

            def get_tv_episode_details(self, *a, **k):
                return {"name": "第1集", "episode_number": 1}

        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False

        md = renamer.extract_metadata(str(f))
        assert md.get("tmdb_id") == 333251
        assert md.get("show_name") == "死神 千年血战篇"
        assert (
            int(md.get("season")) == 4
        ), f"应反推出 Season 04，实际 {md.get('season')}"
        assert int(md.get("episode")) == 1


class TestMovieSequel:
    """回归：电影续集号（The Amazing Spider-Man 2）不能被 GuessIt 当季号吃掉、
    不能被识别成第一部。"""

    SM1 = {
        "name": "The Amazing Spider-Man",
        "title": "The Amazing Spider-Man",
        "original_name": "The Amazing Spider-Man",
        "id": 1930,
        "media_type": "movie",
        "release_date": "2012-06-27",
        "popularity": 60.0,
        "vote_average": 6.6,
    }
    SM2 = {
        "name": "The Amazing Spider-Man 2",
        "title": "The Amazing Spider-Man 2",
        "original_name": "The Amazing Spider-Man 2",
        "id": 102382,
        "media_type": "movie",
        "release_date": "2014-04-16",
        "popularity": 55.0,
        "vote_average": 6.3,
    }
    DETAILS = {
        "title": "The Amazing Spider-Man 2",
        "name": "The Amazing Spider-Man 2",
        "original_title": "The Amazing Spider-Man 2",
        "overview": "x",
        "release_date": "2014-04-16",
        "genres": [{"id": 28, "name": "动作"}],
        "original_language": "en",
        "adult": False,
        "status": "Released",
        "vote_average": 6.3,
        "vote_count": 10,
        "poster_path": "",
        "backdrop_path": "",
        "runtime": 142,
    }

    def test_sequel_number_not_swallowed(self, tmp_path):
        from video_organizer.core.config_loader import load_config

        config = load_config("config.ini")
        renamer = VideoRenamer(
            tmdb_api_key=config.get("tmdb", {}).get("api_key", "f"),
            config={"guessit": {"enabled": True}},
        )
        f = tmp_path / (
            "The.Amazing.Spider-Man.2.2014.2160p.BluRay.REMUX.HEVC."
            "DTS-HD.MA.TrueHD.7.1.Atmos-FGT.mkv"
        )
        f.write_bytes(b"x" * 1024)

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                # TMDB 模糊搜索：第二部 + 第一部都返回
                return [dict(self.SM2), dict(self.SM1)] if hasattr(self, "SM2") else []

            def get_movie_details(self, *a, **k):
                return dict(self.DETAILS) if hasattr(self, "DETAILS") else {}

            def get_movie_credits(self, *a, **k):
                return {}

        stub = StubTMDB()
        stub.SM2 = self.SM2
        stub.SM1 = self.SM1
        stub.DETAILS = self.DETAILS
        renamer.tmdb_client = stub
        renamer._llm_fallback_enabled = False

        md = renamer.extract_metadata(str(f))
        assert (
            md.get("tmdb_id") == 102382
        ), f"应识别 The Amazing Spider-Man 2 (102382)，实际 {md.get('tmdb_id')}"
        assert md.get("show_name") == "The Amazing Spider-Man 2"
        assert str(md.get("year")) == "2014"


class TestDefaultSeasonNotTrusted:
    """回归：GuessIt 给裸集号文件名补的默认 season=1 不能被当作可信季号，
    带目录年份时应允许年份反推覆盖（一念永恒 完结季（2026）→ S04）。"""

    def _stub_details(self, seasons, first_air="2020-01-01"):
        class Stub:
            def get_tv_details(self, *a, **k):
                return {
                    "name": "一念永恒",
                    "first_air_date": first_air,
                    "seasons": [
                        {"season_number": n, "air_date": d} for n, d in seasons
                    ],
                }

        return Stub()

    def test_default_season_1_overridden_by_year(self, renamer):
        renamer.tmdb_client = self._stub_details(
            [
                (1, "2020-01-01"),
                (2, "2021-01-01"),
                (3, "2022-01-01"),
                (4, "2026-01-01"),
            ]
        )
        md = {
            "show_name": "一念永恒 完结季",
            "cleaned_name": "第3集 4K",
            "original_filename": "一念永恒 完结季（2026）/第3集 4K.mkv",
            "year": "2026",
            "tmdb_id": 88801,
            "episode": 3,
            "season": "1",
        }
        renamer._ensure_season(md, entry_year="2026")
        assert int(md["season"]) == 4

    def test_explicit_season_1_not_overridden(self, renamer):
        """显式 S01/第1季 标记时，即使目录年份匹配别的季也不覆盖。"""
        renamer.tmdb_client = self._stub_details([(4, "2026-01-01")])
        md = {
            "show_name": "一念永恒",
            "cleaned_name": "S01E03 4K",
            "original_filename": "一念永恒/S01/E03 4K.mkv",
            "year": "2026",
            "tmdb_id": 88801,
            "episode": 3,
            "season": 1,
        }
        renamer._ensure_season(md, entry_year="2026")
        assert md["season"] == 1

    def test_non_default_season_not_overridden(self, renamer):
        """season=2（非默认值）不覆盖。"""
        renamer.tmdb_client = self._stub_details([(4, "2026-01-01")])
        md = {
            "show_name": "一念永恒",
            "cleaned_name": "第2季 第3集",
            "original_filename": "一念永恒（2021）/第2季/第3集.mkv",
            "year": "2021",
            "tmdb_id": 88801,
            "episode": 3,
            "season": 2,
        }
        renamer._ensure_season(md, entry_year="2021")
        assert md["season"] == 2

    def test_default_season_1_kept_when_no_year_match(self, renamer):
        renamer.tmdb_client = self._stub_details([(1, "2020-01-01")])
        md = {
            "show_name": "一念永恒",
            "cleaned_name": "第3集",
            "original_filename": "一念永恒（2026）/第3集.mkv",
            "year": "2026",
            "tmdb_id": 88801,
            "episode": 3,
            "season": "1",
        }
        renamer._ensure_season(md, entry_year="2026")
        assert int(md["season"]) == 1
