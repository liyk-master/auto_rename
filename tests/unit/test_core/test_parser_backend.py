"""Phase 4：parser.backend 配置开关（GuessIt 已移除，guessit/hybrid 均回退 native）。"""

import pytest

from video_organizer.core.filename_parser import FilenameParser
from video_organizer.core.renamer import VideoRenamer


class TestNativeLayers:
    """native 确定性解析器对曾由 GuessIt 处理（且 GuessIt 会出错的）场景的覆盖。"""

    # (文件名, native 期望字段, GuessIt 曾犯的错误)
    CASES = [
        (
            "斗破丨苍穹/210 4K.mkv",
            {"episode": 210, "media_type": "tv"},
            "拆成 S02E10",
        ),
        (
            "入青云01.mp4",
            {"show_name": "入青云", "episode": 1, "media_type": "tv"},
            "show_name 含数字尾巴且 episode 丢失",
        ),
        (
            "1917.mkv",
            {"show_name": "1917", "media_type": "movie"},
            "拆成 S19E17 误判 tv",
        ),
        (
            "The.Amazing.Spider-Man.2.2014.2160p.BluRay.REMUX.HEVC.mkv",
            {"show_name": "The Amazing Spider-Man 2", "media_type": "movie"},
            "续集号 2 被拆成 season",
        ),
    ]

    @pytest.mark.parametrize("filename,native_expect,guessit_broken", CASES)
    def test_native_correct_where_guessit_breaks(
        self, filename, native_expect, guessit_broken
    ):
        native = FilenameParser().parse(filename)
        for key, expected in native_expect.items():
            assert native.get(key) == expected, (
                f"native 对 {filename!r} 应给出 {key}={expected}，实际 {native.get(key)!r}"
                f"（GuessIt 曾犯的错误：{guessit_broken}）"
            )


class TestParserBackend:
    """parser.backend 开关：native / guessit / hybrid 三种模式。

    用 `斗破丨苍穹/210 4K.mkv` 验证：native 提供 episode=210，
    guessit（降级后）不提供（无显式标记，宁可留空）。
    """

    ENTRY = {
        "name": "斗破苍穹",
        "title": "斗破苍穹",
        "original_name": "斗破苍穹",
        "id": 79481,
        "media_type": "tv",
        "first_air_date": "2017-01-01",
        "original_language": "zh-CN",
        "popularity": 50,
        "genre_ids": [16],
        "origin_country": ["CN"],
        "overview": "x",
        "vote_average": 7.0,
        "vote_count": 10,
        "backdrop_path": "",
        "poster_path": "",
    }
    DETAILS = {
        "name": "斗破苍穹",
        "original_name": "斗破苍穹",
        "overview": "x",
        "first_air_date": "2017-01-01",
        "number_of_seasons": 6,
        "number_of_episodes": 300,
        "genres": [{"id": 16, "name": "动画"}],
        "original_language": "zh-CN",
        "origin_country": ["CN"],
        "status": "Returning Series",
        "vote_average": 7.0,
        "vote_count": 10,
        "poster_path": "",
        "backdrop_path": "",
        "adult": False,
        "seasons": [{"season_number": 1, "air_date": "2017-01-01"}],
    }

    def _renamer(self, backend):
        renamer = VideoRenamer(
            "fake_tmdb_key",
            config={"parser": {"backend": backend}, "guessit": {"enabled": True}},
        )

        class Stub:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                return [dict(self.ENTRY)] if "斗破" in str(term) else []

            def get_tv_details(self, *a, **k):
                return dict(self.DETAILS)

            def get_tv_credits(self, *a, **k):
                return {}

            def get_tv_episode_details(self, *a, **k):
                return {}

        stub = Stub()
        stub.ENTRY = self.ENTRY
        stub.DETAILS = self.DETAILS
        renamer.tmdb_client = stub
        renamer._llm_fallback_enabled = False
        return renamer

    def _extract(self, backend, tmp_path):
        d = tmp_path / "斗破丨苍穹"
        d.mkdir(parents=True)
        f = d / "210 4K.mkv"
        f.write_bytes(b"x")
        return self._renamer(backend).extract_metadata(str(f))

    def test_native_backend_episode(self, tmp_path):
        md = self._extract("native", tmp_path)
        assert int(md["episode"]) == 210

    def test_guessit_backend_falls_back_to_native(self, tmp_path):
        """backend=guessit 已废弃：GuessIt 移除后静默回退 native，结果仍正确。"""
        md = self._extract("guessit", tmp_path)
        assert int(md["episode"]) == 210

    def test_hybrid_backend_equals_native(self, tmp_path):
        md = self._extract("hybrid", tmp_path)
        assert int(md["episode"]) == 210
