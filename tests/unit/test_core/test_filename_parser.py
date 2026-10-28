"""确定性文件名解析器（路径上下文层）测试。"""

from video_organizer.core.filename_parser import FilenameParser


class TestPathContextLayer:
    def setup_method(self):
        self.parser = FilenameParser()

    def test_numeric_episode_with_quality_tags(self):
        """国漫年番裸数字 + 质量标签 → episode。"""
        r = self.parser.parse("_tmp/斗破丨苍穹/210 4K.mkv")
        assert r["episode"] == 210
        assert r["media_type"] == "tv"

    def test_numeric_episode_plain(self):
        r = self.parser.parse("_tmp/斗破丨苍穹/211.mkv")
        assert r["episode"] == 211

    def test_english_dir_not_mistaken(self):
        """英文目录（TV Shows）下裸数字不误判为集号；4 位数字识别为电影标题。"""
        assert self.parser.parse("TV Shows/1917.mkv") == {
            "show_name": "1917",
            "media_type": "movie",
        }
        # 非 4 位数字不妄下结论（留给 GuessIt/TMDB）
        assert self.parser.parse("TV Shows/731.mkv") == {}

    def test_year_dir_not_mistaken(self):
        """纯数字（年份）目录不视为剧名目录。"""
        assert self.parser.parse("2026/210.mkv") == {}

    def test_compact_not_eaten_by_h265(self):
        """L3 紧凑层：H265 里的 265 不是集号（无显式标记也应避开）。"""
        # 已有显式 S13E04，交给 regex
        assert (
            self.parser.parse(
                "狐妖小红娘13 黄风岭篇.S13E04."
                "狐妖小红娘黄风岭篇_04.4K.SDR.8bit.H265.mp4"
            )
            == {}
        )
        # 无显式标记但含 H265 编码标签（标题含点分隔，非紧凑格式）
        assert self.parser.parse("狐妖小红娘.01.H265.mkv") == {}
        # 正常紧凑格式不受影响
        r = self.parser.parse("入青云01.mp4")
        assert r["show_name"] == "入青云"
        assert r["episode"] == 1

    def test_chinese_episode_marker_not_matched(self):
        """中文集号标记（第3集）走 L1，不应被 L2 命中。"""
        assert self.parser.parse("_tmp/一念永恒/第3集 4K.mkv") == {}


class TestDoupoCangqiongEpisode:
    """回归：斗破丨苍穹/210 4K.mkv 应识别 episode=210，而不是被 GuessIt 拆成 S02E10
    后判成电影清空、最终默认 E01。"""

    def test_extract_metadata_keeps_episode_210(self, tmp_path):
        from video_organizer.core.config_loader import load_config
        from video_organizer.core.renamer import VideoRenamer

        config = load_config("config.ini")
        renamer = VideoRenamer(
            tmdb_api_key=config.get("tmdb", {}).get("api_key", "f"),
            config=config,
        )
        f = tmp_path / "斗破丨苍穹" / "210 4K.mkv"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")

        FAKE = [
            {
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
        ]
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
            "seasons": [
                {"season_number": 1, "air_date": "2017-01-01"},
                {"season_number": 2, "air_date": "2018-01-01"},
                {"season_number": 3, "air_date": "2019-01-01"},
                {"season_number": 4, "air_date": "2020-01-01"},
                {"season_number": 5, "air_date": "2021-01-01"},
                {"season_number": 6, "air_date": "2022-01-01"},
            ],
        }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                return list(FAKE)

            def get_tv_details(self, *a, **k):
                return dict(DETAILS)

            def get_tv_credits(self, *a, **k):
                return {}

            def get_tv_episode_details(self, *a, **k):
                return {}

        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False

        md = renamer.extract_metadata(str(f))
        assert (
            int(md.get("episode")) == 210
        ), f"episode 应 210，实际 {md.get('episode')}"
        assert md.get("media_type") == "tv"


class TestNativeLayersEndToEnd:
    """Phase 3：native L3/L4/L5/L6 层修复的格式，端到端验证（跳过 GuessIt）。"""

    @staticmethod
    def _make(entry):
        """构造带 mock TMDB 的 renamer：搜索命中 entry，详情取自身。"""
        from video_organizer.core.config_loader import load_config
        from video_organizer.core.renamer import VideoRenamer

        config = load_config("config.ini")
        renamer = VideoRenamer(
            tmdb_api_key=config.get("tmdb", {}).get("api_key", "f"),
            config=config,
        )

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                return [dict(entry)]

            def get_tv_details(self, *a, **k):
                return dict(entry)

            def get_movie_details(self, *a, **k):
                return dict(entry)

            def get_tv_credits(self, *a, **k):
                return {}

            def get_movie_credits(self, *a, **k):
                return {}

        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        return renamer

    def test_F1_compact_show_episode(self, tmp_path):
        entry = {
            "name": "入青云",
            "title": "入青云",
            "original_name": "入青云",
            "id": 88801,
            "media_type": "tv",
            "first_air_date": "2024-01-01",
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
        f = tmp_path / "入青云01.mp4"
        f.write_bytes(b"x")
        md = self._make(entry).extract_metadata(str(f))
        assert int(md["episode"]) == 1
        assert md["show_name"] == "入青云"

    def test_original_filename_is_full_path(self, tmp_path):
        """native 未命中的文件，original_filename 也必须是完整路径。

        regex 会把「处理后的纯文件名」塞进 original_filename，若不在解析后纠正，
        LLM 兜底（备选策略3）只能看到文件名而丢失父目录线索。
        """
        entry = {
            "name": "Winter City Murder Hunt",
            "title": "Winter City Murder Hunt",
            "original_name": "Winter City Murder Hunt",
            "id": 71001,
            "media_type": "tv",
            "first_air_date": "2025-01-01",
            "original_language": "en",
            "popularity": 30,
            "genre_ids": [80],
            "origin_country": ["US"],
            "overview": "x",
            "vote_average": 7.0,
            "vote_count": 10,
            "backdrop_path": "",
            "poster_path": "",
        }
        f = tmp_path / (
            "Winter.City.Murder.Hunt.S01E07."
            "2160p.WEB-DL.10bit.60fps.SDR.H.265.AAC.iso"
        )
        f.write_bytes(b"x")
        md = self._make(entry).extract_metadata(str(f))
        assert md["original_filename"] == str(f)

    def test_chinese_episode_only_uses_parent_dir(self, tmp_path):
        """`择日飞升（2026）/第11集 4K.mkv`：纯中文集号文件名时
        show_name 用父目录名（择日飞升），不用垃圾搜索词 '第11集'。"""
        entry = {
            "name": "择日飞升",
            "title": "择日飞升",
            "original_name": "择日飞升",
            "id": 12101,
            "media_type": "tv",
            "first_air_date": "2026-01-01",
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
        d = tmp_path / "择日飞升（2026）"
        d.mkdir()
        f = d / "第11集 4K.mkv"
        f.write_bytes(b"x")
        md = self._make(entry).extract_metadata(str(f))
        assert md["show_name"] == "择日飞升"
        assert int(md["episode"]) == 11

    def test_S13E04_not_eaten_by_compact_layer(self, tmp_path):
        """已有显式 S13E04 时紧凑层不得抢（H265 的 265 不是集号）。"""
        entry = {
            "name": "狐妖小红娘13 黄风岭篇",
            "title": "狐妖小红娘13 黄风岭篇",
            "original_name": "狐妖小红娘13 黄风岭篇",
            "id": 99801,
            "media_type": "tv",
            "first_air_date": "2025-01-01",
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
        f = tmp_path / (
            "狐妖小红娘13 黄风岭篇.S13E04." "狐妖小红娘黄风岭篇_04.4K.SDR.8bit.H265.mp4"
        )
        f.write_bytes(b"x")
        md = self._make(entry).extract_metadata(str(f))
        assert int(md["season"]) == 13
        assert int(md["episode"]) == 4
        assert md["show_name"] == "狐妖小红娘13 黄风岭篇"

    def test_C1_bracket_range_episode(self, tmp_path):
        entry = {
            "name": "Solo Leveling",
            "title": "Solo Leveling",
            "original_name": "Solo Leveling",
            "id": 70001,
            "media_type": "tv",
            "first_air_date": "2024-01-01",
            "original_language": "en",
            "popularity": 60,
            "genre_ids": [16],
            "origin_country": ["KR"],
            "overview": "x",
            "vote_average": 8.0,
            "vote_count": 100,
            "backdrop_path": "",
            "poster_path": "",
        }
        d = tmp_path / "[Solo Leveling][13-25][BIG5][720P]"
        d.mkdir(parents=True)
        f = d / "[Solo Leveling][25][BIG5][720P].mp4"
        f.write_bytes(b"x")
        md = self._make(entry).extract_metadata(str(f))
        assert int(md["episode"]) == 25
        assert md["show_name"] == "Solo Leveling"

    def test_E1_pt_naming_movie(self, tmp_path):
        entry = {
            "name": "第二十条",
            "title": "第二十条",
            "original_name": "第二十条",
            "id": 555001,
            "media_type": "movie",
            "release_date": "2024-02-10",
            "original_language": "zh-CN",
            "popularity": 40,
            "genre_ids": [35],
            "origin_country": ["CN"],
            "overview": "x",
            "vote_average": 7.0,
            "vote_count": 50,
            "backdrop_path": "",
            "poster_path": "",
        }
        f = tmp_path / "[第二十条].Article.20.2024.60FPS.2160p.WEB-DL.HEVC.mkv"
        f.write_bytes(b"x")
        md = self._make(entry).extract_metadata(str(f))
        assert md["show_name"] == "第二十条"
        assert md["media_type"] == "movie"
        assert str(md["year"]) == "2024"

    def test_G1_1917_movie(self, tmp_path):
        entry = {
            "name": "1917",
            "title": "1917",
            "original_name": "1917",
            "id": 522016,
            "media_type": "movie",
            "release_date": "2019-12-25",
            "original_language": "en",
            "popularity": 30,
            "genre_ids": [10752],
            "origin_country": ["US"],
            "overview": "x",
            "vote_average": 7.0,
            "vote_count": 50,
            "backdrop_path": "",
            "poster_path": "",
        }
        f = tmp_path / "1917.mkv"
        f.write_bytes(b"x")
        md = self._make(entry).extract_metadata(str(f))
        assert md["media_type"] == "movie"
        assert md["show_name"] == "1917"
