"""
Tests for the VideoRenamer class.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from video_organizer.core.renamer import VideoRenamer


class TestVideoRenamer:
    """Test cases for VideoRenamer."""

    @pytest.fixture
    def renamer(self):
        """Create a VideoRenamer instance for testing."""
        return VideoRenamer("your_tmdb_api_key")

    def test_extract_with_regex(self, renamer):
        """Test metadata extraction using regex patterns."""
        test_cases = [
            (
                "Game.of.Thrones.S01E01.1080p.BluRay.x264-GROUP.mkv",
                {"show_name": "Game Of Thrones", "season": "01", "episode": "01"},
            ),
            (
                "Breaking Bad - s05e16 - Felina.mp4",
                {"show_name": "Breaking Bad", "season": "05", "episode": "16"},
            ),
            (
                "The Office Season 3 Episode 22.avi",
                {"show_name": "The Office", "season": "3", "episode": "22"},
            ),
            # CJK 竖线（资源站纯装饰分隔符）直接删除："冬城丨猎凶" → "冬城猎凶"
            ("冬城丨猎凶", {"show_name": "冬城猎凶"}),
        ]

        for filename, expected in test_cases:
            result = renamer._extract_with_regex(filename)
            for key in expected:
                assert result.get(key) == expected[key]

    def test_anime_bracket_hyphen_episode_not_polluted(self, renamer):
        """A 型 `[组名] 剧名 - N [标签]`：分辨率标签不得误判为年份。

        pattern 52 匹配 `[ANi] 進擊の巨人 ... - 01` 后，`1080P` 的 1080 曾
        被 year_after 检查当成“年份跟随”→ continue 跳过正确匹配 →
        兜底把整个文件名当 show_name、episode=None。
        """
        md = renamer._extract_with_regex(
            "[ANi] 進擊的巨人 The Final Season 完結篇 後篇 - 01 "
            "[1080P][Baha][WEB-DL][AAC AVC][CHT].mp4"
        )
        assert md["show_name"] == "進擊的巨人 The Final Season 完結篇 後篇"
        assert int(md["episode"]) == 1
        # 电影系列编号保护不被破坏（Jurassic Park 3 2001 不拆集号）
        md2 = renamer._extract_with_regex("Jurassic Park 3 2001 1080p BluRay x264.mkv")
        assert md2.get("episode") is None
        assert md2.get("media_type") == "movie"

    def test_traditional_chinese_episode_marker(self, renamer):
        """繁体 `第N話` 与简体 `第N话` 等价（U+8A71 与 U+8BDD）。"""
        md = renamer._extract_with_regex("[千夏字幕組]葬送的芙莉蓮 第1話 1080p.mp4")
        assert int(md["episode"]) == 1
        # 横杠集号 + END 后缀
        md2 = renamer._extract_with_regex(
            "[jibaketa]Sousou no Frieren 2nd Season - 10 END "
            "(WEB 1920x1080 AVC AACx2 SRT MUSE CHT).mkv"
        )
        assert int(md2["episode"]) == 10

    def test_chinese_dot_inside_title_removed(self, renamer):
        """`凡人.修仙传（2020）`：中文之间的点号是资源站装饰，
        应删除（真实剧名 `凡人修仙传`）；英文点分隔不受影响。"""
        md = renamer._extract_with_regex("凡人.修仙传（2020）")
        assert md["show_name"] == "凡人修仙传"
        assert md.get("year") == "2020"
        # 英文点分隔保留
        md2 = renamer._extract_with_regex("One.Piece.EP1163.1080p.mp4")
        assert md2["show_name"] == "One Piece"
        assert int(md2["episode"]) == 1163

    def test_year_in_filename_episode_extracted_and_season_inferred(self, renamer):
        """`Wednesday（2025）E01.mp4`：文件名内年份+裸 E 集号。

        E01 曾被任何 pattern 提取（patterns 无裸 E 集号）→ episode=None →
        _ensure_season 提前 return，年份反推季号不执行。修复后应提取 E01
        并走年份反推（Wednesday S2 2025 年播出 → S02E01）。
        """
        md = renamer._extract_with_regex("Wednesday（2025）E01.mp4")
        assert md["show_name"] == "Wednesday"
        assert md.get("year") == "2025"
        assert int(md["episode"]) == 1
        # 无集号时不误提（周三夜谈 (2025)）
        md2 = renamer._extract_with_regex("Wednesday（2025）.mp4")
        assert md2.get("episode") is None
        assert md2["show_name"] == "Wednesday"

    def test_naked_numeric_episode_with_quality_tag(self, renamer):
        """`08 4K-Muying.mp4`：裸数字集号 + 质量/发布组应提 episode，
        不得判 movie（原逻辑无 pattern 匹配 → 兜底 movie → 清空 season/episode）。
        电影年份名保护：1917/100/1942 不提取。"""
        md = renamer._extract_with_regex("死神 千年血战篇 祸进谭/08 4K-Muying.mp4")
        assert int(md["episode"]) == 8
        assert md.get("season") == "1"
        assert md.get("media_type") == "tv"
        assert md.get("release_group") == "Muying"
        # 裸文件形式
        md2 = renamer._extract_with_regex("12.1080p.H265.mkv")
        assert int(md2["episode"]) == 12
        assert md2.get("media_type") == "tv"
        # 电影年份名/剧名保护：不误提集号
        for fn in [
            "1917 4K.mkv",
            "100 4K.mkv",
            "12 Monkeys 1080p.mkv",
            "42.2013.1080p.BluRay.x264.mkv",  # 两位数电影（42号传奇）
            "9.2009.1080p.WEB-DL.AAC.mkv",  # 两位数电影（9）
        ]:
            md3 = renamer._extract_with_regex(fn)
            assert md3.get("episode") is None, fn

    def test_movie_series_roman_not_season(self, renamer):
        """电影系列标注中的罗马数字不是季号：

        Star.Wars.Episode.IV / Back.To.The.Future.Part.II / Rocky.II /
        American.History.X / DTS-X.7.1 音频 / .x.mkv 音轨 / V for Vendetta。
        带年份 + 无剧集标记时不提 season，避免 movie 误判 tv；
        剧集的罗马季号（On.Call.36小時II_01）仍必须识别。
        """
        for fn in [
            "星球大战.Star.Wars.Episode.IV.A.New.Hope.1977.Remastered.BD1080P.X264.AAC.mp4",
            "美国X档案.American.History.X.1998.BD1080P.X264.AAC.mkv",
            "回到未来2.Back.To.The.Future.Part.II.1989.BD1080P.X264.AAC.mkv",
            "The.Mummy.1999.2160p.BluRay.REMUX.HEVC.DTS-X.7.1.DTS-HD.MA.7.1.mkv",
            "Jurassic.Park.2.The.Lost.World.1997.1080p.Blu-ray.DTS-HD.MA.7.1.4Audio.PGS.x.mkv",
            "V for Vendetta (2006) - 2160p UHD BluRay HEVC Atmos TrueHD 7.1 2Audio.mkv",
        ]:
            md = renamer._extract_with_regex(fn)
            assert md.get("season") is None, fn
            assert md.get("media_type") != "tv", fn
            assert md.get("show_name"), fn
        # 剧集罗马季号保留
        md2 = renamer._extract_with_regex("进击的巨人 II 03.mkv")
        assert md2.get("season") == "2"
        assert int(md2["episode"]) == 3
        assert md2.get("media_type") == "tv"

    def test_apostrophe_english_movie(self, renamer):
        """撇号电影名（Kiki's / O'Brien / A.Bug's.Life / Here's）
        点分隔英文 pattern 字符类曾不含 `'`，质量长尾（REMUX/多音轨）
        无法提取 show_name。"""
        md = renamer._extract_with_regex(
            "A.Bug's.Life.1998.2160p.BluRay.REMUX.HEVC.DTS-HD.MA.TrueHD.7.1.Atmos.mkv"
        )
        assert md["show_name"].lower().replace("'", "") == "a bugs life"
        assert md.get("year") == "1998"
        md2 = renamer._extract_with_regex(
            "Kiki's.Delivery.Service.1989.BluRay.1080p.x265.mkv"
        )
        assert md2["show_name"].lower().replace("'", "") == "kikis delivery service"

    def test_english_sequel_number_not_episode(self, renamer):
        """英文电影续集号（Toy Story 2 / Gremlins 2 / Spider Man 3）
        不得当集号；中文剧名+空格+集号（大正偽婚 8 / 翻译官 2 / 择日飞升 第3集）
        必须保留。"""
        for fn in [
            "Toy Story 2 (1999) 2160p.Ultra HD BluRay Remux.HDR.H.265.mkv",
            "Gremlins 2 - The New Batch 1080p remux (1990).mkv",
            "Spider Man.3.2007 4K Mastered Blu-ray 1080p DTS-HD MA5.1 TriAudio x264-beAst.mkv",
            "美国丽人.1999.1080p.REMUX.h264.DTSHD-MA.5.1-404.mkv",
            "哥斯拉-1.0 (2023) 2160p.UHD.Blu-ray.JPN.HEVC.TrueHD 7.1 Atmos.mkv",
        ]:
            md = renamer._extract_with_regex(fn)
            assert md.get("episode") is None, fn
            assert md.get("media_type") != "tv", fn
        # 中文剧名 + 空格 + 集号不受影响
        md2 = renamer._extract_with_regex("翻译官 2.mp4")
        assert int(md2["episode"]) == 2
        assert md2.get("media_type") == "tv"
        md3 = renamer._extract_with_regex("大正偽婚～替身新娘與軍服的猛愛 8.mp4")
        assert int(md3["episode"]) == 8

    def test_prepare_search_term_bilingual_strip(self, renamer):
        """搜索词中文双标题剥离：中文剧名+空格+英文副标题只保留中文主名
        （小精灵2 Gremlins 2 - The New Batch → 小精灵2）；
        纯英文剧名、纯中文剧名、中文+数字（翻译官 2）不受影响。"""
        assert (
            renamer._prepare_search_term("小精灵2 Gremlins 2 - The New Batch remux ()")
            == "小精灵2"
        )
        assert (
            renamer._prepare_search_term("進擊的巨人 The Final Season 完結篇 後篇")
            == "進擊的巨人"
        )
        assert renamer._prepare_search_term("翻译官 2") == "翻译官 2"
        assert renamer._prepare_search_term("多罗罗 第一季") == "多罗罗 第一季"
        assert (
            renamer._prepare_search_term("死神 千年血战篇 祸进谭")
            == "死神 千年血战篇 祸进谭"
        )
        assert renamer._prepare_search_term("The Amazing Spider-Man 2") == (
            "The Amazing Spider-Man 2"
        )
        assert renamer._prepare_search_term("小精灵2") == "小精灵2"

    def test_sequel_movie_not_tv_full_chain(self, renamer):
        """双标题续集电影（小精灵2 Gremlins 2 - The New Batch）解析层不提取集号，
        且 max_search_pages 配置字符串被正确转 int（避免搜索静默失败）。"""
        md = renamer._extract_with_regex(
            "小精灵2 Gremlins 2 - The New Batch 1080p remux (1990).mkv"
        )
        assert md.get("episode") is None
        assert md.get("season") is None
        # max_search_pages 必须是 int（configparser 字符串会炸 search_all_pages）
        assert isinstance(renamer.max_search_pages, int)

        qt = renamer._extract_keywords(
            "Against.the.Current.S01E05.2160p.WEB-DL.10bit.25fps.SDR.H.265.AAC.iso"
        )
        assert qt == "2160p.WEB-DL.10bit.25fps.SDR.H.265.AAC"
        # 帧率/色深/带点编码的变体
        qt2 = renamer._extract_keywords("Show.S01E01.2160p.WEB-DL.60fps.HEVC.10bit.mkv")
        assert qt2 == "2160p.WEB-DL.60fps.HEVC.10bit"

    def test_clean_filename_for_search_no_glue(self, renamer):
        """清理搜索词不粘连、不误删剧名（Web.of.Lies 的 Web 是剧名）。"""
        clean = renamer._clean_filename_for_search(
            "Against.the.Current.S01E05.2160p.WEB-DL.10bit.25fps.SDR.H.265.AAC.iso"
        )
        assert clean == "Against the Current S01E05"
        assert (
            renamer._clean_filename_for_search("Web.of.Lies.S01E01.1080p.WEB-DL.mkv")
            == "Web of Lies S01E01"
        )

    def test_sanitize_filename(self, renamer):
        """Test filename sanitization."""
        test_cases = [
            ("Game: of/ Thrones", "Game of Thrones"),
            ("Show<>Name", "ShowName"),
            ("  Extra   Spaces  ", "Extra Spaces"),
        ]

        for input_name, expected in test_cases:
            result = renamer._sanitize_filename(input_name)
            assert result == expected

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_enrich_with_tmdb(self, mock_tmdb_client):
        """Test metadata enrichment with TMDB data."""
        # Mock TMDB client responses
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        # 模拟 TMDB search 返回结果
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 123,
                "name": "Game of Thrones",
                "media_type": "tv",
                "first_air_date": "2011-04-17",
            }
        ]
        mock_client_instance.get_tv_details.return_value = {
            "name": "Game of Thrones",
            "first_air_date": "2011-04-17",
            "genres": [],
            "origin_country": [],
            "original_language": "en",
            "poster_path": "",
            "backdrop_path": "",
            "vote_average": 0,
            "vote_count": 0,
            "popularity": 0,
            "number_of_seasons": 8,
            "number_of_episodes": 73,
            "status": "Ended",
            "overview": "",
            "networks": [],
        }
        mock_client_instance.get_tv_episode_details.return_value = {
            "name": "Winter Is Coming",
            "still_path": "",
            "overview": "",
            "vote_average": 0,
        }
        mock_client_instance.get_tv_credits.return_value = {
            "cast": [],
            "crew": [],
        }
        mock_client_instance.get_external_ids.return_value = {
            "imdb_id": "tt0944947",
            "tvdb_id": 121361,
            "tvrage_id": 0,
        }

        # 在 patch 生效后创建 renamer，确保 TMDBClient 被 mock
        renamer = VideoRenamer("your_tmdb_api_key")

        # Test metadata enrichment
        metadata = {
            "show_name": "Game of Thrones",
            "season": "1",
            "episode": "1",
            "media_type": "tv",
        }
        result = renamer._enrich_with_tmdb(metadata)

        assert result["show_name"] == "Game of Thrones"
        assert result["year"] == "2011"

        # 在 patch 生效后创建 renamer，确保 TMDBClient 被 mock
        renamer = VideoRenamer("your_tmdb_api_key")

        # Test metadata enrichment
        metadata = {
            "show_name": "Game of Thrones",
            "season": "1",
            "episode": "1",
            "media_type": "tv",
        }
        result = renamer._enrich_with_tmdb(metadata)

        assert result["show_name"] == "Game of Thrones"
        assert result["year"] == "2011"
        assert isinstance(result["tmdb_id"], int)

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_resolve_ambiguous_type_tv_by_year(self, mock_tmdb_client):
        """模糊类型判定：只有电视剧匹配年份时判定为 tv"""
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        # multi 搜索同时返回电影和电视剧，但只有电视剧年份匹配 2019
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 1001,
                "name": "少年派",
                "media_type": "tv",
                "first_air_date": "2019-05-31",
                "popularity": 50,
            },
            {
                "id": 1002,
                "title": "少年派的奇幻漂流",
                "media_type": "movie",
                "release_date": "2012-11-22",
                "popularity": 60,
            },
        ]

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {"show_name": "少年派", "season": "01"}
        result = renamer._resolve_ambiguous_media_type_via_tmdb(metadata, 2019)

        assert result == "tv"
        # 确认 multi 搜索未传年份（年份在本地筛选）
        call_kwargs = mock_client_instance.search_all_pages.call_args.kwargs
        assert call_kwargs.get("year") is None
        assert call_kwargs.get("max_pages") == 1

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_resolve_ambiguous_type_movie_by_year(self, mock_tmdb_client):
        """模糊类型判定：只有电影匹配年份时判定为 movie"""
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 2001,
                "name": "少年派",
                "media_type": "tv",
                "first_air_date": "2016-03-01",
                "popularity": 50,
            },
            {
                "id": 2002,
                "title": "少年派的奇幻漂流",
                "media_type": "movie",
                "release_date": "2012-11-22",
                "popularity": 60,
            },
        ]

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {"show_name": "少年派"}
        result = renamer._resolve_ambiguous_media_type_via_tmdb(metadata, 2012)

        assert result == "movie"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_resolve_ambiguous_both_match_none(self, mock_tmdb_client):
        """模糊类型判定：电影和电视剧都匹配年份时返回 None，保持原判断"""
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 3001,
                "name": "同名",
                "media_type": "tv",
                "first_air_date": "2019-01-01",
                "popularity": 50,
            },
            {
                "id": 3002,
                "title": "同名",
                "media_type": "movie",
                "release_date": "2019-05-05",
                "popularity": 60,
            },
        ]

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {"show_name": "同名"}
        result = renamer._resolve_ambiguous_media_type_via_tmdb(metadata, 2019)

        assert result is None

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_enrich_with_tmdb_strong_tv_signal_keeps_tv(self, mock_tmdb_client):
        """强 TV 信号保护：TMDB 只返回 movie 结果时，保持 tv 判定不被覆盖"""
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        movie_result = {
            "id": 1646282,
            "name": "Adventure Time: Fun with Finn and Jake",
            "title": "Adventure Time: Fun with Finn and Jake",
            "media_type": "movie",
            "release_date": "2012-10-14",
            "popularity": 50,
            "genre_ids": [],
        }

        def search_side_effect(method_name, query, *args, **kwargs):
            if method_name == "search_tv":
                return []
            if method_name == "search_video_show":
                return [movie_result]
            return []

        mock_client_instance.search_all_pages.side_effect = search_side_effect

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {
            "show_name": "Adventure Time With Finn And Jake",
            "season": "10",
            "episode": "13",
            "media_type": "tv",
            "_media_type_confidence": 0.9,
        }
        result = renamer._enrich_with_tmdb(metadata)

        assert result["media_type"] == "tv"
        assert result["season"] == "10"
        assert result["episode"] == "13"
        assert result.get("tmdb_id") != 1646282

    @patch("video_organizer.core.renamer.renamer.VideoRenamer._enrich_with_tmdb")
    def test_extract_metadata_refuses_movie_override(self, mock_enrich):
        """extract_metadata 覆盖保护：TMDB movie 结果不能覆盖强 TV 信号"""
        mock_enrich.return_value = {
            "media_type": "movie",
            "tmdb_id": 1646282,
            "show_name": "Adventure Time: Fun with Finn and Jake",
        }

        renamer = VideoRenamer("your_tmdb_api_key")
        result = renamer.extract_metadata(
            Path(
                "E:/alipan备份/TV_欧美亚/探险活宝 (2010)/Season 10/"
                "Adventure.Time.With.Finn.And.Jake.S10E13.mkv"
            )
        )

        assert result.get("media_type") == "tv"
        assert result.get("season") == "10"
        assert result.get("episode") == "13"

    @patch("video_organizer.core.renamer.renamer.VideoRenamer._enrich_with_tmdb")
    def test_extract_metadata_multi_level_parent_lookup(self, mock_enrich):
        """多级父目录补全：剧名(年份)/1-100 4K/第61话… → 跳过集数范围
        中间层（伪剧名），补全到上级真实剧名；区间集号目录不崩溃。"""
        mock_enrich.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        result = renamer.extract_metadata(
            Path(
                "E:/alipan备份/TV_国漫/凡人.修仙传（2020）/1-100 4K/"
                "第61话 初入星海1.mp4"
            )
        )

        assert result.get("show_name") == "凡人修仙传"
        assert result.get("parent_show_name") == "凡人修仙传"
        assert result.get("episode") == "61"

        # 更深层（2 层垃圾中间目录）+ 区间集号目录（原 ValueError 崩溃点）
        result2 = renamer.extract_metadata(
            Path(
                "E:/alipan备份/TV_国漫/凡人.修仙传（2020）/全季合集/第1-100话/"
                "第61话 初入星海1.mp4"
            )
        )
        assert result2.get("show_name") == "凡人修仙传"
        assert result2.get("episode") == "61"

    @patch("video_organizer.core.renamer.renamer.VideoRenamer._enrich_with_tmdb")
    def test_extract_metadata_keeps_parent_show_name(self, mock_enrich):
        """extract_metadata 保留父目录名到 parent_show_name，即使文件名已有 show_name"""
        mock_enrich.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        result = renamer.extract_metadata(
            Path(
                "E:/alipan备份/TV_欧美亚/面朝上游 (2026)/Season 1/"
                "Swimming.Upstream.S01E02.2026.2160p.WEB-DL.H265.AAC.mkv"
            )
        )

        assert result.get("show_name") == "Swimming Upstream"
        assert result.get("parent_show_name") == "面朝上游"
        assert result.get("season") == "01"
        assert result.get("episode") == "02"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_enrich_with_tmdb_uses_parent_show_name_fallback(self, mock_tmdb_client):
        """TMDB 备选搜索：文件名搜不到时降级用父目录名搜索"""
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        tv_result = {
            "id": 9001,
            "name": "面朝上游",
            "media_type": "tv",
            "first_air_date": "2026-05-01",
            "popularity": 50,
            "genre_ids": [],
        }

        # 文件名搜索无结果，父目录名搜索有结果
        def search_side_effect(method_name, query, *args, **kwargs):
            if query in ("Swimming Upstream", "Swimming Upstream S01E02"):
                return []
            if query == "面朝上游":
                return [tv_result]
            return []

        mock_client_instance.search_all_pages.side_effect = search_side_effect
        mock_client_instance.get_tv_details.return_value = {
            "name": "面朝上游",
            "first_air_date": "2026-05-01",
            "genres": [],
            "origin_country": [],
            "original_language": "zh",
            "poster_path": "",
            "backdrop_path": "",
            "vote_average": 0,
            "vote_count": 0,
            "popularity": 0,
            "number_of_seasons": 1,
            "number_of_episodes": 20,
            "status": "Returning Series",
            "overview": "",
            "networks": [],
        }
        mock_client_instance.get_tv_episode_details.return_value = {
            "name": "",
            "still_path": "",
            "overview": "",
            "vote_average": 0,
        }
        mock_client_instance.get_tv_credits.return_value = {"cast": [], "crew": []}
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {
            "show_name": "Swimming Upstream S01E02",
            "parent_show_name": "面朝上游",
            "season": "01",
            "episode": "02",
            "media_type": "tv",
            "_media_type_confidence": 0.9,
        }
        result = renamer._enrich_with_tmdb(metadata)

        assert result.get("tmdb_id") == 9001
        assert result.get("show_name") == "面朝上游"
        # 搜索过后 parent_show_name 不应残留在结果中
        assert "parent_show_name" not in result

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_resolve_ambiguous_requires_year(self, mock_tmdb_client):
        """模糊类型判定：无年份时直接返回 None，不发起请求"""
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {"show_name": "少年派"}
        result = renamer._resolve_ambiguous_media_type_via_tmdb(metadata, None)

        assert result is None
        mock_client_instance.search_all_pages.assert_not_called()
