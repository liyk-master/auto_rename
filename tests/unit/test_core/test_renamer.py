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
    def test_resolve_ambiguous_type_tv_refused_when_episode_less(
        self, mock_tmdb_client
    ):
        """模糊类型判定：零剧集形态的单文件，仅 tv 命中时不锁定 tv。

        "假面-2015-国语7.0.mp4" 无任何季/集信号（无季节/episode/标记），
        multi 搜索只有 2015 韩剧《假面》撞上年份 → 不锁定 tv（同名撞车防护），
        保持模糊交由 TMDB 匹配阶段双类型裁决（电影目录下 tv 候选会被排除）。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        # multi 搜索只返回电视剧命中 2015，电影无 2015 匹配
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 1001,
                "name": "假面",
                "media_type": "tv",
                "first_air_date": "2015-05-27",
                "popularity": 50,
            },
            {
                "id": 1002,
                "title": "假面",
                "media_type": "movie",
                "release_date": "1966-10-18",
                "popularity": 5,
            },
        ]

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {
            "show_name": "假面",
            "year": "2015",
            "original_filename": (r"\影视资源\Downloads\电影\J\假面-2015-国语7.0.mp4"),
        }
        result = renamer._resolve_ambiguous_media_type_via_tmdb(metadata, 2015)

        assert result is None

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_resolve_ambiguous_type_tv_kept_with_episode_marker(self, mock_tmdb_client):
        """有显式季/集标记的文件仍允许锁定 tv（剧集形态信号不受影响）。"""
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 1001,
                "name": "假面",
                "media_type": "tv",
                "first_air_date": "2015-05-27",
                "popularity": 50,
            },
        ]

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {
            "show_name": "假面",
            "year": "2015",
            "original_filename": r"\影视\剧集\假面\假面S01E01.mkv",
        }
        result = renamer._resolve_ambiguous_media_type_via_tmdb(metadata, 2015)

        assert result == "tv"

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

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_chinese_numeral_prefix_not_fuzzy_collapsed_to_tv(self, mock_tmdb_client):
        """回归：fuzzy 去数字只剥尾部续集号，不得全位置抠中文数字。

        "四喜临门" 含前导中文数字"四"。旧逻辑 digit_pattern 全位置移除数字后，
        "四喜临门" 与 "喜临门" 模糊相等得 15000 分，恰好绕过年份守卫 _exact_ok
        阈值，把电影目录里的 "四喜临门 (2008)" 误配成 tv《喜临门》(2004,
        id=263362)。修复后年份守卫正常拒绝无年份匹配候选，走电影目录兜底。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        # API 搜索（multi / video_show）全部 0 结果，只有网页兜底返回 3 条子串卡片
        mock_client_instance.search_all_pages.return_value = []
        mock_client_instance.search_web_fallback.return_value = [
            {
                "id": 263362,
                "media_type": "tv",
                "title": "喜临门",
                "name": "喜临门",
                "_web_fallback": True,
                "first_air_date": "2004-03-25",
            },
            {
                "id": 187169,
                "media_type": "movie",
                "title": "双喜临门",
                "name": "双喜临门",
                "_web_fallback": True,
                "release_date": "1970-02-04",
            },
            {
                "id": 225754,
                "media_type": "tv",
                "title": "三喜临门",
                "name": "三喜临门",
                "_web_fallback": True,
                "first_air_date": "1995-01-01",
            },
        ]

        renamer = VideoRenamer("your_tmdb_api_key")
        fp = (
            r"\影视资源\Downloads\电影\S\四喜临门 (2008) - "
            r"1080p.SDR.H.264.25fps.MP2.ts"
        )
        md = renamer.extract_metadata(fp)

        # 不再被 fuzzy 误配成 tv《喜临门》
        assert not (md.get("media_type") == "tv" and md.get("tmdb_id") == 263362)
        # 电影目录 + 无匹配 → 目录信号兜底 movie，不走 tv
        assert md.get("media_type") == "movie"
        assert md.get("tmdb_id") in ("", None)
        assert md.get("show_name") == "四喜临门"
        assert md.get("year") == "2008"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_movie_dir_episode_less_never_tv(self, mock_tmdb_client):
        """回归：电影目录 + 零剧集形态的单文件不得被同名剧集误配成 tv。

        "假面-2015-国语7.0.mp4"（电影目录 J/ 下，无任何季/集信号）的 multi
        搜索里，2015 韩剧《假面》首播年恰好与文件年份撞车。旧逻辑在"模糊类型
        判定"阶段仅凭"tv 匹配且无 movie 匹配"就锁定 tv(0.7) → 误配韩剧。
        修复后：① 零剧集形态拒绝锁定 tv；② 匹配阶段排除 tv 候选；③ 精确标题
        的电影候选（假面 1966/2007）胜出，最终类型必须为 movie。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 62806,
                "name": "假面",
                "media_type": "tv",
                "first_air_date": "2015-05-27",
                "popularity": 30,
                "genre_ids": [18, 80],
            },
            {
                "id": 797,
                "title": "假面",
                "media_type": "movie",
                "release_date": "1966-10-18",
                "popularity": 8,
                "genre_ids": [],
            },
            {
                "id": 38000,
                "title": "假面",
                "media_type": "movie",
                "release_date": "2007-12-27",
                "popularity": 12,
                "genre_ids": [],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {
            "id": 38000,
            "title": "假面",
            "original_title": "假面",
            "overview": "测试影片",
            "release_date": "2007-12-27",
            "vote_average": 7.0,
            "vote_count": 10,
            "genres": [{"name": "剧情"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["CN"],
            "production_countries": [{"iso_3166_1": "CN"}],
            "runtime": 90,
            "status": "Released",
        }
        mock_client_instance.get_tv_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        fp = r"\影视资源\Downloads\电影\J\假面-2015-国语7.0.mp4"
        md = renamer.extract_metadata(fp)

        # 绝不能锁定成电视剧（旧逻辑：tv + 韩剧 62806）
        assert md.get("media_type") == "movie", md
        assert md.get("tmdb_id") != 62806
        assert md.get("show_name") == "假面"
        # 常被解析成 tv 前的旧行为是 `media_type` 为空——现在不再可能
        assert md.get("media_type") != "tv"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_movie_dir_compact_sequel_never_tv(self, mock_tmdb_client):
        """回归：电影目录 + 紧凑续集号（蜘蛛侠3.mkv）不得被 L3 拆成剧集。

        L3 紧凑格式会把 "蜘蛛侠3" 解析成 show_name=蜘蛛侠 episode=3（与
        "入青云01" 结构同构，单看文件名无法区分）。但文件在电影目录里即
        电影语义——tv 候选无条件排除，最终匹配到电影《蜘蛛侠3》。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        # multi 搜索同时存在同名剧集诱惑与真实电影
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 999,
                "name": "蜘蛛侠",
                "media_type": "tv",
                "first_air_date": "2000-01-01",
                "popularity": 60,
                "genre_ids": [],
            },
            {
                "id": 559,
                "title": "蜘蛛侠3",
                "media_type": "movie",
                "release_date": "2007-05-01",
                "popularity": 50,
                "genre_ids": [],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {
            "id": 559,
            "title": "蜘蛛侠3",
            "original_title": "蜘蛛侠3",
            "overview": "测试影片",
            "release_date": "2007-05-01",
            "vote_average": 6.0,
            "vote_count": 100,
            "genres": [{"name": "动作"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["US"],
            "production_countries": [{"iso_3166_1": "US"}],
            "runtime": 140,
            "status": "Released",
        }
        mock_client_instance.get_tv_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        fp = r"\影视资源\Downloads\电影\S\蜘蛛侠3.mkv"
        md = renamer.extract_metadata(fp)

        assert md.get("media_type") == "movie", md
        assert md.get("tmdb_id") == 559
        assert md.get("tmdb_id") != 999

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_generic_dir_episode_less_never_tv(self, mock_tmdb_client):
        """回归：无电影目录前缀的零剧集形态文件也不得输出 tv。

        "Downloads/假面-2015-国语7.0.mp4"（文件名无任何季/集信号、路径无
        剧集布局）——TV 证据不足：宁可识别为同名电影，也不输出韩剧《假面》。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 62806,
                "name": "假面",
                "media_type": "tv",
                "first_air_date": "2015-05-27",
                "popularity": 30,
                "genre_ids": [18, 80],
            },
            {
                "id": 38000,
                "title": "假面",
                "media_type": "movie",
                "release_date": "2007-12-27",
                "popularity": 20,
                "genre_ids": [],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {
            "id": 38000,
            "title": "假面",
            "original_title": "假面",
            "overview": "测试影片",
            "release_date": "2007-12-27",
            "vote_average": 7.0,
            "vote_count": 10,
            "genres": [{"name": "剧情"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["CN"],
            "production_countries": [{"iso_3166_1": "CN"}],
            "runtime": 90,
            "status": "Released",
        }
        mock_client_instance.get_tv_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        fp = r"\影视资源\Downloads\假面-2015-国语7.0.mp4"
        md = renamer.extract_metadata(fp)

        assert md.get("media_type") == "movie", md
        assert md.get("tmdb_id") != 62806

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_tv_candidate_admissible_evidence(self, mock_tmdb_client):
        """_tv_candidate_admissible：tv 候选可选性由剧集证据驱动。"""
        renamer = VideoRenamer("your_tmdb_api_key")

        # 零剧集形态：不选 tv（宁可不识别也不误配剧）
        assert (
            renamer._tv_candidate_admissible(
                {
                    "show_name": "假面",
                    "year": "2015",
                    "original_filename": r"\影视资源\Downloads\假面-2015-国语7.0.mp4",
                }
            )
            is False
        )
        # 裸集号文件（L2）
        assert (
            renamer._tv_candidate_admissible(
                {
                    "original_filename": r"\影视\剧集\斗破丨苍穹\210 4K.mkv",
                    "episode": 210,
                }
            )
            is True
        )
        # 显式 SxxExx 标记
        assert (
            renamer._tv_candidate_admissible(
                {"original_filename": r"\影视\剧集\假面\假面S01E01.mkv"}
            )
            is True
        )
        # 剧集布局目录（剧集/分类词）
        assert (
            renamer._tv_candidate_admissible(
                {"original_filename": r"\影视\剧集\云之羽\云之羽.mkv"}
            )
            is True
        )
        # 中文剧名父目录（L2 结构：云之羽/云之羽.mkv 视为剧集目录）
        assert (
            renamer._tv_candidate_admissible(
                {"original_filename": r"\影视\云之羽\云之羽.mkv"}
            )
            is True
        )
        # 紧凑后缀 episode 存在（入青云01 类）→ 允许 tv 候选交 TMDB 裁决
        assert (
            renamer._tv_candidate_admissible(
                {"original_filename": r"\影视\Downloads\入青云01.mp4", "episode": 1}
            )
            is True
        )
        # Season 目录上下文
        assert (
            renamer._tv_candidate_admissible(
                {"original_filename": r"\影视\某剧\Season 2\某剧.mkv"}
            )
            is True
        )
        # 无文件上下文（单元测试）→ 保守允许，保持旧行为
        assert renamer._tv_candidate_admissible({"show_name": "早春晴朗"}) is True

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_bare_numeric_stem_default_tv_not_movie(self, mock_tmdb_client):
        """回归：纯数字集号文件（含质量标签）regex 层不得默认成 movie。

        "完美世界\222 4k.mp4" 的 222 是 3 位裸集号（动画已播 200+ 集），
        旧 regex 只保护 1-2 位（"01.mp4"），3 位落到 movie 默认分支 →
        resolver 锁死 movie → 误配电影《完美世界》(2018, id 546794)。
        修复后 1-3 位纯数字（剥质量标签后）默认 tv；4 位年份仍是电影/不确定。
        """
        renamer = VideoRenamer("your_tmdb_api_key")
        # 3 位裸集号 + 质量标签 → tv
        assert (
            renamer._extract_with_regex(r"完美世界\222 4k.mp4").get("media_type")
            == "tv"
        )
        assert (
            renamer._extract_with_regex(r"完美世界\222.mp4").get("media_type") == "tv"
        )
        # 1-2 位裸集号（原有保护，不回归）
        assert renamer._extract_with_regex(r"01.mp4").get("media_type") == "tv"
        # 4 位年份数字 → 电影/不确定（不锁 tv）
        assert renamer._extract_with_regex(r"1917.mkv").get("media_type") != "tv"
        # 紧凑续集号（蜘蛛侠3）不变：movie 默认，交 TMDB 裁决
        assert renamer._extract_with_regex(r"蜘蛛侠3.mkv").get("media_type") == "movie"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_episode_less_tv_show_episode_222_never_movie(self, mock_tmdb_client):
        """回归：剧集证据充足的裸集号文件不得被误配成电影。

        "完美世界\222 4k.mp4"：父目录剧名 + 3 位裸集号 → 动画《完美世界》
        (tmdb 124003, 2021) 的 S01E222。旧逻辑 regex 默认 movie →
        严格 movie 过滤选中电影《完美世界》(2018, id 546794)。
        修复后必须选中 tv 动画 124003，且 episode=222 保留。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 124003,
                "name": "完美世界",
                "media_type": "tv",
                "first_air_date": "2021-07-25",
                "popularity": 73.8878,
                "genre_ids": [16, 10759],
            },
            {
                "id": 7120,
                "name": "完美世界",
                "media_type": "tv",
                "first_air_date": "2000-01-01",
                "popularity": 2.8556,
                "genre_ids": [35],
            },
            {
                "id": 546794,
                "title": "完美世界",
                "media_type": "movie",
                "release_date": "2018-01-01",
                "popularity": 1.5428,
                "genre_ids": [10749],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {}
        mock_client_instance.get_tv_details.return_value = {
            "id": 124003,
            "name": "完美世界",
            "original_name": "完美世界",
            "overview": "测试动画",
            "first_air_date": "2021-07-25",
            "vote_average": 8.0,
            "vote_count": 100,
            "genres": [{"name": "动画"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["CN"],
            "production_countries": [{"iso_3166_1": "CN"}],
            "number_of_episodes": 250,
            "status": "Returning Series",
        }
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        fp = r"\影视资源\Downloads\完美世界\222 4k.mp4"
        md = renamer.extract_metadata(fp)

        # 必须识别成动画剧集，绝不能锁死成电影《完美世界》(2018)
        assert md.get("media_type") == "tv", md
        assert md.get("tmdb_id") == 124003, md
        assert md.get("episode") == 222
        assert md.get("show_name") == "完美世界"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_compact_sequel_generic_dir_matches_installment(self, mock_tmdb_client):
        """回归：通用目录紧凑续集号（蜘蛛侠3.mkv）不得被精确标题+人气误配成第一部。

        搜索词是 L3 剥离续集号后的 "蜘蛛侠"（与 "入青云01" 同构），候选里
        同时有同名第一部《蜘蛛侠》(2002, 557) 与《蜘蛛侠3》(2007, 559)。
        旧逻辑精确匹配"蜘蛛侠"命中两部，按人气选 557 → 错配第一部。
        修复后续集号合并回搜索词（蜘蛛侠3）精确匹配 → 559。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 557,
                "title": "蜘蛛侠",
                "media_type": "movie",
                "release_date": "2002-05-01",
                "popularity": 45.1209,
                "genre_ids": [],
            },
            {
                "id": 559,
                "title": "蜘蛛侠3",
                "media_type": "movie",
                "release_date": "2007-05-01",
                "popularity": 34.5636,
                "genre_ids": [],
            },
            {
                "id": 999,
                "name": "蜘蛛侠",
                "media_type": "tv",
                "first_air_date": "2000-01-01",
                "popularity": 60,
                "genre_ids": [],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {
            "id": 559,
            "title": "蜘蛛侠3",
            "original_title": "蜘蛛侠3",
            "overview": "测试影片",
            "release_date": "2007-05-01",
            "vote_average": 6.0,
            "vote_count": 100,
            "genres": [{"name": "动作"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["US"],
            "production_countries": [{"iso_3166_1": "US"}],
            "runtime": 140,
            "status": "Released",
        }
        mock_client_instance.get_tv_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        fp = r"\影视资源\Downloads\蜘蛛侠3.mkv"
        md = renamer.extract_metadata(fp)

        assert md.get("media_type") == "movie", md
        assert md.get("tmdb_id") == 559, md
        assert md.get("tmdb_id") != 557
        assert md.get("year") == "2007"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_name_cache_not_poisoned_for_compact_sequel(self, mock_tmdb_client):
        """回归：名称缓存不得让紧凑续集号文件串味到上一部。

        同一进程内先处理过《蜘蛛侠》(2002, 557) 会把 "蜘蛛侠_movie"→557
        写进进程级 _tmdb_name_to_id。若后续 "蜘蛛侠3.mkv" 被紧凑拆成
        show_name=蜘蛛侠 并命中该缓存 → 直接取详情 557 → 错配第一部。
        修复：movie + episode 无 season（紧凑续集形态）不信任名称缓存，
        走搜索路径（含续集号合并）→ 559；而合法的 tv 剧集缓存仍生效。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 557,
                "title": "蜘蛛侠",
                "media_type": "movie",
                "release_date": "2002-05-01",
                "popularity": 45.1209,
                "genre_ids": [],
            },
            {
                "id": 559,
                "title": "蜘蛛侠3",
                "media_type": "movie",
                "release_date": "2007-05-01",
                "popularity": 34.5636,
                "genre_ids": [],
            },
            {
                "id": 124003,
                "name": "完美世界",
                "media_type": "tv",
                "first_air_date": "2021-07-25",
                "popularity": 73.8878,
                "genre_ids": [16, 10759],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {
            "id": 559,
            "title": "蜘蛛侠3",
            "original_title": "蜘蛛侠3",
            "overview": "测试影片",
            "release_date": "2007-05-01",
            "vote_average": 6.0,
            "vote_count": 100,
            "genres": [{"name": "动作"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["US"],
            "production_countries": [{"iso_3166_1": "US"}],
            "runtime": 140,
            "status": "Released",
        }
        mock_client_instance.get_tv_details.return_value = {
            "id": 124003,
            "name": "完美世界",
            "original_name": "完美世界",
            "overview": "测试动画",
            "first_air_date": "2021-07-25",
            "vote_average": 8.0,
            "vote_count": 100,
            "genres": [{"name": "动画"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["CN"],
            "production_countries": [{"iso_3166_1": "CN"}],
            "number_of_episodes": 250,
            "status": "Returning Series",
        }
        mock_client_instance.get_external_ids.return_value = {}

        # 模拟上一部《蜘蛛侠》(2002) 留下的进程级污染
        VideoRenamer._tmdb_name_to_id["蜘蛛侠_movie"] = 557
        renamer = VideoRenamer("your_tmdb_api_key")
        md = renamer.extract_metadata(r"\影视资源\Downloads\蜘蛛侠3.mkv")

        # 紧凑续集形态必须无视被污染的缓存，走搜索 → 559
        assert md.get("tmdb_id") == 559, md
        assert md.get("tmdb_id") != 557

        # 合法的 tv 剧集名称缓存仍生效（同一进程、同类型）
        VideoRenamer._tmdb_name_to_id["完美世界_tv"] = 124003
        md2 = renamer.extract_metadata(r"\影视资源\Downloads\完美世界\222 4k.mp4")
        assert md2.get("media_type") == "tv", md2
        assert md2.get("tmdb_id") == 124003, md2
        assert md2.get("episode") == 222

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_tmdb_marker_short_form_extracted(self, mock_tmdb_client):
        """回归：{tmdb-6038} 无 id 短格式标记必须被识别并直接取详情。

        README 文档化的 tmdbid_suffix 是 {tmdb-123}（无 id、连字符），旧正则
        只认 tmdbid=/- 导致写出来的后缀读不回去、6038 被当成数字残渣，
        show_name 变成 '...内封字幕 {tmdb- }' 垃圾搜索词 → 全部搜索策略失败。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance
        mock_client_instance.get_movie_details.return_value = {
            "id": 6038,
            "title": "上海正午2：上海骑士",
            "original_title": "Shanghai Knights",
            "overview": "测试影片",
            "release_date": "2003-02-07",
            "vote_average": 6.0,
            "vote_count": 100,
            "genres": [{"name": "动作"}],
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "zh",
            "adult": False,
            "origin_country": ["US"],
            "production_countries": [{"iso_3166_1": "US"}],
            "runtime": 114,
            "status": "Released",
        }
        mock_client_instance.get_tv_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        fp = (
            r"\影视资源\Downloads\上海正午2：上海骑士.Shanghai.Knights.2003."
            r"1080p.24fps.SDR.H.264.8bit.DD5.1.内封字幕 {tmdb-6038}.mkv"
        )
        md = renamer.extract_metadata(fp)

        assert md.get("tmdb_id") in (6038, "6038"), md
        assert md.get("media_type") == "movie", md
        assert md.get("show_name") == "上海正午2：上海骑士", md

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_show_name_residue_cleaned_for_search(self, mock_tmdb_client):
        """回归：混合中英文名的技术残渣（24fps/H 264/DD5 1/内封字幕）不得
        污染搜索词与 show_name。

        "上海正午2：上海骑士.Shanghai.Knights.2003.1080p.24fps.SDR.H.264."
        "8bit.DD5.1.内封字幕.mkv"（无标记版本）：旧逻辑 show_name 保留
        '24fps H 264 DD5 1 内封字幕 {tmdb- }' 全量残渣 → TMDB 搜索必失败。
        修复后 _prepare_search_term 剥离技术残留 + 字幕标签 → '上海正午2:上海骑士'。
        """
        renamer = VideoRenamer("your_tmdb_api_key")
        prepared = renamer._prepare_search_term(
            "上海正午2:上海骑士 Shanghai Knights 24fps H 264 DD5 1 内封字幕"
        )
        assert prepared == "上海正午2:上海骑士", prepared
        # 双标题剥离支持标题内冒号（全/半角）
        prepared2 = renamer._prepare_search_term(
            "复仇者联盟3：无限战争 Avengers Infinity War 4K HDR 2160p"
        )
        assert prepared2 == "复仇者联盟3：无限战争", prepared2
        # 既有英文形态不回归
        prepared3 = renamer._prepare_search_term(
            "小精灵2 Gremlins 2 - The New Batch 1080p"
        )
        assert prepared3 == "小精灵2", prepared3

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_foreign_transliteration_stripped_from_search(self, mock_tmdb_client):
        """回归：中文标题后的泰米尔/日文音译副标题必须从搜索词剥离。

        "恶魔.அசுரன்.2019..." 与 "安昙春子下落不明.アズミ・ハルコは行方不明."
        "2016..."（点号格式被正则展平成 "中文标题 + 空格 + 外文音译"）。
        音译（含日文汉字如 行方不明）不是标题，残留会污染 TMDB 搜索词。
        判定依据：空格后首字符为外文脚本字母（拉丁/假名/谚文/泰米尔/西里尔）。
        """
        renamer = VideoRenamer("your_tmdb_api_key")
        assert renamer._prepare_search_term("恶魔 அசுரன் 60fps H 264 AAC2 0") == "恶魔"
        assert (
            renamer._prepare_search_term(
                "安昙春子下落不明 アズミ・ハルコは行方不明 24fps"
            )
            == "安昙春子下落不明"
        )
        assert (
            renamer._prepare_search_term("因果报应 மகாராஜா 24fps Netflix") == "因果报应"
        )
        # 中文续集号/中文副标题不得被误剥
        assert renamer._prepare_search_term("流浪地球 2") == "流浪地球 2"
        assert renamer._prepare_search_term("三体 黑暗森林") == "三体 黑暗森林"
        # 演唱会保护
        assert (
            renamer._prepare_search_term("周慧敏 Deep V 25周年演唱会")
            == "周慧敏 Deep V 25周年演唱会"
        )

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_dts_hd_ma_and_fx_subtitle_residue(self, mock_tmdb_client):
        """回归：DTS-HD.MA5.1（点号转空格成 -HD MA5 1）与特效字幕粘连串。

        "深夜食堂2电影版.続・深夜食堂.2016...DTS-HD.MA5.1.5Audios.内封字幕."
        "中文字幕.特效字幕.国语配音"：旧词表只认 DTS-HD 裸词（DTS 先被剥掉
        留 "-HD"），MA5 1 与特效字幕/国语配音（粘连串）全残留。
        """
        renamer = VideoRenamer("your_tmdb_api_key")
        assert (
            renamer._prepare_search_term(
                "深夜食堂2电影版続・深夜食堂 24fps H 264 -HD MA5 1 "
                "5Audios 内封字幕中文字幕特效字幕国语配音"
            )
            == "深夜食堂2电影版続・深夜食堂"
        )
        # DTS-HD.MA5.1 完整形态
        assert (
            renamer._prepare_search_term("深夜食堂2电影版 DTS-HD.MA5.1 5Audios")
            == "深夜食堂2电影版"
        )
        # 上一批不回归
        assert (
            renamer._prepare_search_term(
                "魔法奇缘2:解除魔法 24fps Dovi P5 DDP5 1 内封字幕中文字幕国语配音"
            )
            == "魔法奇缘2:解除魔法"
        )

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_structural_title_year_boundary(self, mock_tmdb_client):
        """回归：点号分隔规范命名以 4 位年份为硬边界切标题（结构性规则）。

        这类命名 '中文标题.英文标题.2023.1080p.24fps.SDR.H.264.8bit.DD5.1.'
        '内封字幕 {tmdb-123}.mkv' 的规律是年份之前是标题、之后全是标签——
        确定性一刀切，不依赖逐词黑名单（24fps/Dovi/DTS-HD.MA5.1/特效字幕
        等新标签层出不穷，黑名单式反剥永远追不完）。
        """
        from video_organizer.core.renamer.renamer import (
            _extract_title_via_year_boundary,
        )

        # 纯中文+英文翻译
        assert (
            _extract_title_via_year_boundary(
                r"上海正午2：上海骑士.Shanghai.Knights.2003.1080p.24fps.SDR.H.264.8bit.DD5.1.内封字幕 {tmdb-6038}.mkv"
            )
            == "上海正午2：上海骑士 Shanghai Knights"
        )
        # 泰米尔音译
        assert (
            _extract_title_via_year_boundary(
                r"恶魔.அசுரன்.2019.1080p.60fps.SDR.H.264.8bit.AAC2.0 {tmdb-576928}.mp4"
            )
            == "恶魔 அசுரன்"
        )
        # 日文原名（汉字开头保留）
        assert (
            _extract_title_via_year_boundary(
                r"深夜食堂2电影版.続・深夜食堂.2016.1080p.24fps.SDR.H.264.8bit.DTS-HD.MA5.1.5Audios.内封字幕.中文字幕.特效字幕.国语配音 {tmdb-429285}.mkv"
            )
            == "深夜食堂2电影版 続・深夜食堂"
        )
        # 英文在前
        assert (
            _extract_title_via_year_boundary(
                r"SPEC.特别篇：翔.2012.1080p.30fps.SDR.H.264.8bit.DD2.0 {tmdb-345699}.mkv"
            )
            == "SPEC 特别篇：翔"
        )
        # 纯英文
        assert (
            _extract_title_via_year_boundary(
                r"The.Matrix.Resurrections.2021.2160p.REMUX.DV.HEVC.mkv"
            )
            == "The Matrix Resurrections"
        )
        # TV 集号标记不进入标题
        assert (
            _extract_title_via_year_boundary(
                r"Swimming.Upstream.S01E02.2026.2160p.WEB-DL.H265.AAC.mkv"
            )
            == "Swimming Upstream"
        )
        # 无年份 → 不适用（走原逻辑）；标题本身就是年份数字（1984.1984）
        # 第一个 1984 是片名、第二个是年份 → 正常提取
        assert _extract_title_via_year_boundary(r"小精灵2.Gremlins.2.mkv") == ""
        assert _extract_title_via_year_boundary(r"1984.1984.1080p.mkv") == "1984"

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_show_name_chinese_primary_name(self, mock_tmdb_client):
        """回归：show_name 主名中文化——'砍人快乐 Freaky' → '砍人快乐'。

        结构性提取忠实还原中文+英文原名，但片名规范主名应为纯中文：
        外文音译/翻译副标题（含 'This Aint Star Trek XXX 3' 这类长尾）
        由 _strip_trailing_transliteration 统一剥离（show_name 与搜索词共用）。
        """
        from video_organizer.core.renamer.renamer import (
            _strip_trailing_transliteration,
        )

        assert _strip_trailing_transliteration("砍人快乐 Freaky") == "砍人快乐"
        assert (
            _strip_trailing_transliteration(
                "这不是星际迷航成人版3 This Aint Star Trek XXX 3"
            )
            == "这不是星际迷航成人版3"
        )
        assert _strip_trailing_transliteration("恶魔 அசுரன்") == "恶魔"
        # 不误伤：中文开头副标题 / 英文开头 / 纯英文 / 续集号 / 演唱会
        assert _strip_trailing_transliteration("三体 黑暗森林") == "三体 黑暗森林"
        assert _strip_trailing_transliteration("SPEC 特别篇:翔") == "SPEC 特别篇:翔"
        assert (
            _strip_trailing_transliteration("The Matrix Resurrections")
            == "The Matrix Resurrections"
        )
        assert _strip_trailing_transliteration("流浪地球 2") == "流浪地球 2"
        assert (
            _strip_trailing_transliteration("周慧敏 Deep V 25周年演唱会")
            == "周慧敏 Deep V 25周年演唱会"
        )

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_seasoned_version_selected_by_dir_year(self, mock_tmdb_client):
        """回归：同名剧分季/不分季两个版本并存时，目录年份应选中分季版本。

        "一念丨永恒（2026）/10 4K.mkv"：TMDB 有两个一念永恒——
        id 107371（不分季，200 集全塞 S1，人气 35.3）与 id 331477
        （分季 S1~S3 + S4 完结季 air=2026，人气 5.8）。旧逻辑季年份
        boost 只看默认补的 season=1（S1 air 2020≠2026 都得 0），纯人气
        选中不分季版，年份反推无季可推 → S01。修复：无显式季标记时
        boost 允许任意季命中目录年份 → 331477 +500 胜出 → 反推 S04。
        """
        mock_client_instance = MagicMock()
        mock_tmdb_client.return_value = mock_client_instance

        def _tv_details(tid, **kw):
            if tid == 107371:
                return {
                    "id": 107371,
                    "name": "一念永恒",
                    "first_air_date": "2020-08-12",
                    "seasons": [
                        {
                            "season_number": 1,
                            "air_date": "2020-08-12",
                            "episode_count": 200,
                        }
                    ],
                    "original_name": "一念永恒",
                    "overview": "x",
                    "poster_path": "",
                    "backdrop_path": "",
                    "vote_average": 7.0,
                    "vote_count": 10,
                    "genres": [{"name": "动画"}],
                    "original_language": "zh",
                    "adult": False,
                    "origin_country": ["CN"],
                    "status": "Returning Series",
                }
            if tid == 331477:
                return {
                    "id": 331477,
                    "name": "一念永恒",
                    "first_air_date": "2020-08-12",
                    "seasons": [
                        {
                            "season_number": 1,
                            "air_date": "2020-08-12",
                            "episode_count": 52,
                        },
                        {
                            "season_number": 2,
                            "air_date": "2022-07-20",
                            "episode_count": 54,
                        },
                        {
                            "season_number": 3,
                            "air_date": "2024-07-03",
                            "episode_count": 59,
                        },
                        {
                            "season_number": 4,
                            "air_date": "2026-07-22",
                            "episode_count": 30,
                        },
                    ],
                    "original_name": "一念永恒",
                    "overview": "x",
                    "poster_path": "",
                    "backdrop_path": "",
                    "vote_average": 7.0,
                    "vote_count": 10,
                    "genres": [{"name": "动画"}],
                    "original_language": "zh",
                    "adult": False,
                    "origin_country": ["CN"],
                    "status": "Returning Series",
                }
            return {"id": tid, "name": "一念永恒", "seasons": []}

        mock_client_instance.get_tv_details.side_effect = _tv_details
        mock_client_instance.search_all_pages.return_value = [
            {
                "id": 107371,
                "name": "一念永恒",
                "media_type": "tv",
                "first_air_date": "2020-08-12",
                "popularity": 35.3233,
                "genre_ids": [16, 10759],
            },
            {
                "id": 331477,
                "name": "一念永恒",
                "media_type": "tv",
                "first_air_date": "2020-08-12",
                "popularity": 5.8322,
                "genre_ids": [16, 10759],
            },
            {
                "id": 261597,
                "name": "一念永恒",
                "media_type": "tv",
                "popularity": 1.9142,
                "genre_ids": [16],
            },
        ]
        mock_client_instance.search_web_fallback.return_value = []
        mock_client_instance.find_by_imdb_id.return_value = None
        mock_client_instance.get_movie_details.return_value = {}
        mock_client_instance.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        md = renamer.extract_metadata(
            r"\影视资源\Downloads\一念丨永恒（2026）\10 4K.mkv"
        )

        # 必须选中分季版本 331477 并反推出 S04，而不是人气更高的不分季版 107371
        assert md.get("tmdb_id") == 331477, md
        assert md.get("media_type") == "tv", md
        assert md.get("season") == 4, md
        assert md.get("episode") == 10, md


class TestLeadingTitleYear:
    """回归：片名以「年份样数字」开头时，年份必须取后面那个。

    ``2001 A Space Odyssey 1968 USA BluRay ...`` 的首个 2001 属于片名本体
    （TMDB 收录名 ``2001: A Space Odyssey``）。若把 2001 当年份，标题会被截成
    ``A Space Odyssey``、父目录只剩 ``太空漫游``，且所有 TMDB 搜索都带
    year=2001（真实条目 1968）——年份噪音过滤会把整批候选判成噪音而识别失败。
    """

    @pytest.fixture
    def renamer(self):
        return VideoRenamer("your_tmdb_api_key")

    def test_leading_year_belongs_to_title(self, renamer):
        md = renamer._extract_with_regex(
            "2001 A Space Odyssey 1968 USA BluRay Remux UHD DoVi HDR10 2160p "
            "DTS-HDMA5.1.mkv"
        )
        assert md["year"] == "1968"

    def test_leading_year_without_second_year_kept(self, renamer):
        """只有一个年份样数字时保持原行为（2012 是发行年份）。"""
        md = renamer._extract_with_regex("2012.1080p.BluRay.x264.mkv")
        assert md["year"] == "2012"

    def test_resolution_not_mistaken_for_second_year(self, renamer):
        """1920x1080 不是年份，不能被当成「后一个年份」。"""
        md = renamer._extract_with_regex("2001 A Space Odyssey 1920x1080 BluRay.mkv")
        assert md["year"] == "2001"


class TestNonVideoEntrySkipped:
    """回归：无有效扩展名的条目（说明文本/目录名）不参与识别。

    139 秒传/网盘清单里 ``1.本片可做为设备测试片使用`` 这类 0 字节说明条目
    （``Path().suffix`` 会返回整个中文串）会被 L2「中文剧名目录 + 数字开头」
    当成集号，误配成父目录电影的第 1/2 集。
    """

    def test_chinese_note_entry_skipped(self):
        renamer = VideoRenamer("your_tmdb_api_key")
        assert (
            renamer.extract_metadata("Q:/影视/双子杀手/1.本片可做为设备测试片使用")
            == {}
        )

    def test_digit_dot_note_entry_skipped(self):
        renamer = VideoRenamer("your_tmdb_api_key")
        assert (
            renamer.extract_metadata(
                "Q:/影视/双子杀手/2.非自动匹配切换帧速率为59.94或者60"
            )
            == {}
        )

    def test_video_extension_still_recognized(self):
        renamer = VideoRenamer("your_tmdb_api_key")
        md = renamer._extract_with_regex("Gemini.Man.2019.2160p.BluRay.REMUX.mkv")
        assert md["year"] == "2019"


class TestUnknownMediaTypeParentDirFallback:
    """回归：media_type 判不出来时兜底搜索必须真的发出去。

    ``_search_with_language`` 此前在 media_type 未知时直接 ``return []``，
    而「cleaned_name / 父目录名 / 截断 / LLM」四个兜底全走这个方法——
    等于「纯英文文件名 + 中文目录名」这一大类（影视/西西里的美丽传说/
    Melina.2000.UNCUT...）的父目录名兜底与 LLM 兜底静默失效。
    """

    @staticmethod
    def _renamer(entries, details):
        """entries: {搜索词小写: [候选...]}；details: {tmdb_id: 详情}。"""
        renamer = VideoRenamer("your_tmdb_api_key")
        table = {k.lower(): v for k, v in entries.items()}

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                return [dict(e) for e in table.get(str(term).lower(), [])]

            def get_movie_details(self, movie_id, **k):
                return dict(details.get(movie_id, {}))

            def get_tv_details(self, tv_id, **k):
                return dict(details.get(tv_id, {}))

            def get_movie_credits(self, *a, **k):
                return {}

            def get_tv_credits(self, *a, **k):
                return {}

        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        return renamer

    def test_unknown_type_uses_generic_search(self):
        renamer = VideoRenamer("your_tmdb_api_key")
        calls = []

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                calls.append(method)
                return [{"id": 1, "name": "x", "media_type": "movie"}]

        renamer.tmdb_client = StubTMDB()
        out = renamer._search_with_language("x", None, "2000", "zh-CN")
        assert calls == ["search_video_show"]
        assert out

    def test_typo_english_name_falls_back_to_parent_dir(self):
        """Melina.2000（源文件名拼错 Malèna）→ 父目录中文名精确命中。"""
        movie = {
            "id": 10867,
            "title": "西西里的美丽传说",
            "name": "西西里的美丽传说",
            "original_title": "Malèna",
            "original_name": "Malèna",
            "media_type": "movie",
            "release_date": "2000-10-27",
            "original_language": "it",
            "popularity": 20.0,
            "genre_ids": [18],
            "overview": "x",
            "vote_average": 8.0,
            "vote_count": 100,
            "poster_path": "",
            "backdrop_path": "",
        }
        renamer = self._renamer({"西西里的美丽传说": [movie]}, {10867: dict(movie)})
        md = renamer.extract_metadata(
            "Q:/影视/西西里的美丽传说/Melina.2000.UNCUT.1080p.Bluray.REMUX.AVC.mkv"
        )
        assert md.get("tmdb_id") == 10867, md
        assert md.get("show_name") == "西西里的美丽传说", md
        assert md.get("media_type") == "movie", md

    def test_leading_number_movie_title_falls_back_to_parent_dir(self):
        """3.ldiots.2009（typо 3 Idiots）→ 父目录中文名精确命中。"""
        movie = {
            "id": 20453,
            "title": "三傻大闹宝莱坞",
            "name": "三傻大闹宝莱坞",
            "original_title": "3 Idiots",
            "original_name": "3 Idiots",
            "media_type": "movie",
            "release_date": "2009-12-23",
            "original_language": "hi",
            "popularity": 30.0,
            "genre_ids": [35],
            "overview": "x",
            "vote_average": 8.0,
            "vote_count": 100,
            "poster_path": "",
            "backdrop_path": "",
        }
        renamer = self._renamer({"三傻大闹宝莱坞": [movie]}, {20453: dict(movie)})
        md = renamer.extract_metadata(
            "Q:/影视/三傻大闹宝莱坞/3.ldiots.2009.1080p.BluRay.REMUX.AVC.mkv"
        )
        assert md.get("tmdb_id") == 20453, md
        assert md.get("show_name") == "三傻大闹宝莱坞", md
        assert md.get("media_type") == "movie", md
        # 不得被当成剧集第 3 集
        assert not md.get("episode"), md

    def test_same_title_tv_pool_resolved_by_parent_dir_year(self):
        """Pride.And.Prejudice.2005：multi 候选全是同名剧集/旧版电影（无 2005
        年份）时，父目录中文名搜索精确命中 2005 电影而不是人气更高的 1995 剧集。"""
        tv_1995 = {
            "id": 1457,
            "name": "傲慢与偏见",
            "title": "傲慢与偏见",
            "original_name": "Pride and Prejudice",
            "media_type": "tv",
            "first_air_date": "1995-09-24",
            "original_language": "en",
            "popularity": 20.03,
            "genre_ids": [18],
            "overview": "x",
            "vote_average": 8.0,
            "vote_count": 100,
            "poster_path": "",
            "backdrop_path": "",
        }
        movie_2005 = {
            "id": 4348,
            "title": "傲慢与偏见",
            "name": "傲慢与偏见",
            "original_title": "Pride & Prejudice",
            "original_name": "Pride & Prejudice",
            "media_type": "movie",
            "release_date": "2005-09-16",
            "original_language": "en",
            "popularity": 40.0,
            "genre_ids": [18, 10749],
            "overview": "x",
            "vote_average": 8.0,
            "vote_count": 100,
            "poster_path": "",
            "backdrop_path": "",
        }
        renamer = self._renamer(
            {
                "pride and prejudice": [tv_1995],
                "傲慢与偏见": [movie_2005],
            },
            {4348: dict(movie_2005), 1457: dict(tv_1995)},
        )
        md = renamer.extract_metadata(
            "Q:/影视/傲慢与偏见/Pride.And.Prejudice.2005.1080p.BluRay.REMUX.VC-1.mkv"
        )
        assert md.get("tmdb_id") == 4348, md
        assert md.get("media_type") == "movie", md


class TestDriveLetterParentSkipped:
    """回归：Windows 盘符（``D:\``）不得被当成父目录名兜底搜索。

    ``Path('D:/Downloads/...').parts`` 的最后一级父目录是 ``'D:\'``（不是单
    字符 ``'\'``，旧过滤条件漏掉）。识别失败时兜底策略会拿盘符去 TMDB 搜，
    返回热门随机结果按得分误配——实测 ``Downloads/Melina.2000...`` 被随机
    配成“吸血鬼猎人D”(9463)。
    """

    def test_drive_letter_not_used_as_search_term(self):
        renamer = VideoRenamer("your_tmdb_api_key")
        searched = []

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                searched.append(str(term))
                return []

        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        md = renamer.extract_metadata(
            "D:/Downloads/Melina.2000.UNCUT.1080p.Bluray.REMUX.AVC.DTS-HD.MA.5.1.mkv"
        )
        # 不得把盘符当搜索词
        assert not any(
            ("D:\\" in t or t.strip("\/:") == "D") for t in searched
        ), searched
        assert md.get("tmdb_id") in ("", None), md


class TestJunkParentDirNotUsedAsShowName:
    """回归：父目录兜底不得把垃圾目录当剧名去搜 TMDB。

    139 ACG 秒传里常见：

    - ``胆大党系列/第一季 蓝光原盘REMUX…年糕/S01E01.2024.mkv``：最近父目录是
      「季节 + 压制描述」（不含剧名），真剧名在上上级 ``胆大党系列``。旧逻辑把
      整串目录名当 show_name 搜 TMDB（0 结果），再截断成 ``第一季`` 搜出 90 条
      任意剧按人气误配（土豆逗严肃科普 / 魔法使莎莉）。
    - 分类目录 ``番剧`` / ``新番`` 不在垃圾词表中：无剧名的英文电影文件名
      （正则收不出 show_name）向上兜底到分类层后拿 ``番剧`` 当搜索词 → 返回一串
      热门电影随手误配（辉夜姬物语被配成 The Jogger / 名侦探柯南）。
    """

    @staticmethod
    def _is_garbage(name: str) -> bool:
        return VideoRenamer._is_garbage_show_candidate(name)

    def test_season_desc_dir_is_garbage(self):
        """季节目录带压制描述（``第一季 蓝光原盘REMUX 内封…字幕``）不是剧名。"""
        assert self._is_garbage("第一季 蓝光原盘REMUX 内封精修简日双语特效字幕 年糕")
        assert self._is_garbage("S01 1080p 4K")
        assert self._is_garbage("Season 2 2025")
        assert self._is_garbage("第二季 蓝光原盘REMUX")

    def test_real_title_dir_not_garbage(self):
        """真实剧名目录不受影响（不因放宽 garbage 而误伤）。"""
        assert not self._is_garbage("胆大党")
        assert not self._is_garbage("千年女优")
        assert not self._is_garbage("未麻的部屋")
        assert not self._is_garbage("火影忍者")

    def test_anime_category_dir_is_garbage(self):
        """ACG 分类目录词不得当剧名。"""
        assert self._is_garbage("番剧")
        assert self._is_garbage("新番")
        assert self._is_garbage("日漫")

    def test_season_dir_skipped_series_dir_used(self):
        """E2E：胆大党/第一季 蓝光原盘…/S01E09 → 搜「胆大党」命中 240411。"""
        searched = []

        def _cand():
            return {
                "id": 240411,
                "name": "胆大党",
                "title": "胆大党",
                "media_type": "tv",
                "release_date": "2024-10-04",
                "first_air_date": "2024-10-04",
                "popularity": 40.0,
                "genre_ids": [16],
                "original_language": "ja",
                "vote_average": 8.0,
                "vote_count": 50,
            }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                searched.append(str(term))
                if str(term).startswith("胆大党"):
                    return [_cand()]
                return []

            def get_tv_details(self, tv_id, **k):
                return dict(id=tv_id, name="胆大党", overview="x")

        renamer = VideoRenamer("your_tmdb_api_key")
        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        md = renamer.extract_metadata(
            "Q:/番剧/胆大党系列/第一季 蓝光原盘REMUX 内封精修简日双语特效字幕 年糕/"
            "S01E09.2024.1080p.BluRay.REMUX.AVC.FLAC.2.0-年糕.mkv"
        )
        assert md.get("tmdb_id") == 240411, md
        assert md.get("season") == "01" and md.get("episode") == "09", md
        assert not any("第一季" in t for t in searched), searched

    def test_category_dir_not_used_when_regex_fails(self):
        """E2E：辉夜姬物语（无年份英文点分标题）→ 分类目录「番剧」不得当
        搜索词，最终走 cleaned_name 命中 149871。"""
        searched = []

        def _cand():
            return {
                "id": 149871,
                "name": "The Tale of The Princess Kaguya",
                "title": "辉耀姬物语",
                "media_type": "movie",
                "release_date": "2013-11-23",
                "popularity": 12.0,
                "original_language": "ja",
                "genre_ids": [16, 18],
                "vote_average": 8.0,
                "vote_count": 10,
            }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                searched.append(str(term))
                if "princess kaguya" in str(term).lower():
                    return [_cand()]
                return []

            def get_movie_details(self, movie_id, **k):
                return dict(id=movie_id, title="辉耀姬物语", overview="x")

        renamer = VideoRenamer("your_tmdb_api_key")
        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        md = renamer.extract_metadata(
            "Q:/番剧/宫崎骏动画合集 蓝光BDREMUX原盘/"
            "The.Tale.of.the.Princess.Kaguya.1080p.BluRay.REMUX.AVC."
            "DTS-HD.MA.5.1.3Audio.mkv"
        )
        assert md.get("tmdb_id") == 149871, md
        assert not any("番剧" in t for t in searched), searched


class TestMovieDirAllowsExplicitTvEvidence:
    """回归：电影目录硬规则不得误杀带显式剧集证据的文件。

    用户可能把剧集放进「电影/H/」等首字母分类目录（路径含「电影」目录段，
    如 ``黑礁.Black.Lagoon.S01E04.2006…mkv``）。旧逻辑一见到电影目录就
    无条件剔除 tv 候选——主搜索被剔空，识别失败。
    """

    def test_tv_with_explicit_episode_in_movie_dir(self):
        """电影目录 + S01E04：tv 证据强于目录语义，应命中黑礁。"""

        def _cand():
            return {
                "id": 12598,
                "name": "黑礁",
                "title": "黑礁",
                "media_type": "tv",
                "first_air_date": "2006-10-02",
                "release_date": "2006-10-02",
                "popularity": 31.0,
                "original_language": "ja",
                "genre_ids": [16, 10759],
                "vote_average": 8.0,
                "vote_count": 20,
            }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                if str(term).startswith("黑礁"):
                    return [_cand()]
                return []

            def get_tv_details(self, tv_id, **k):
                return dict(id=tv_id, name="黑礁", overview="x")

        renamer = VideoRenamer("your_tmdb_api_key")
        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        md = renamer.extract_metadata(
            "Q:/影视库/电影/H/黑礁 Black Lagoon (2006)/Season 1/"
            "黑礁.Black.Lagoon.S01E04.2006.1080p.Blu-ray.Remux.AVC."
            "LPCM 2.0-LuckAni.mkv"
        )
        assert md.get("tmdb_id") == 12598, md
        assert md.get("media_type") == "tv", md
        assert md.get("season") == "01" and md.get("episode") == "04", md

    def test_movie_dir_without_episode_evidence_still_blocks_tv(self):
        """电影目录 + 无剧集证据的单文件：tv 候选仍被排除（宁失败不误配）。"""

        def _cand():
            return {
                "id": 12598,
                "name": "黑礁",
                "title": "黑礁",
                "media_type": "tv",
                "first_air_date": "2006-10-02",
                "popularity": 31.0,
                "original_language": "ja",
                "genre_ids": [16],
            }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                if str(term).startswith("黑礁"):
                    return [_cand()]
                return []

        renamer = VideoRenamer("your_tmdb_api_key")
        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        md = renamer.extract_metadata(
            "Q:/影视库/电影/H/黑礁 Black Lagoon (2006)/黑礁.2006.1080p.mkv"
        )
        # 唯一 tv 候选因「电影目录 + 无剧集证据」被排除 → 宁识别失败
        assert md.get("tmdb_id") in ("", None), md


class TestChineseTitleDotNumberEpisode:
    """回归：「中文剧名.数字」点分形态的集号提取。

    ``遮天.186.4K.mkv`` / ``火影忍者.115[www.haimianxz.com].mkv.iso`` 是
    国产剧/国漫/网盘常见命名。旧逻辑把点分数字当 show_name 的一部分
    （``遮天 186``）或噪音剥掉（cleaned_name），media_type 落回 movie 后
    搜「遮天 186」失败、兜底搜「遮天」电影池错配成「遮蔽的天空」(1990)
    （The Sheltering Sky）。
    """

    def test_chinese_title_dot_number_extracts_episode(self):
        md = VideoRenamer("your_tmdb_api_key")._extract_with_regex("遮天.186.4K.mkv")
        assert md["show_name"] == "遮天", md
        assert md["episode"] == "186", md

    def test_dotted_number_with_watermark_extracts_episode(self):
        md = VideoRenamer("your_tmdb_api_key")._extract_with_regex(
            "火影忍者.115[www.haimianxz.com].mkv.iso"
        )
        assert md["show_name"] == "火影忍者", md
        assert md["episode"] == "115", md

    def test_chinese_dot_number_subtitle_title_still_episode(self):
        """狂飙.01.开端.2023 → 狂飙 + E1（中文副标题点分）。"""
        md = VideoRenamer("your_tmdb_api_key")._extract_with_regex(
            "狂飙.01.开端.2023.1080p.mp4"
        )
        assert md["show_name"] == "狂飙", md
        assert md["episode"] == "1", md

    def test_year_shape_not_episode(self):
        """让子弹飞.2010：4 位年份不提取为集号。"""
        md = VideoRenamer("your_tmdb_api_key")._extract_with_regex(
            "让子弹飞.2010.1080p.mkv"
        )
        assert md["episode"] in (None, ""), md
        assert md.get("year") == "2010", md

    def test_single_digit_sequel_number_not_episode(self):
        """复仇者联盟.2.2015：1 位续集号不提取为集号。"""
        md = VideoRenamer("your_tmdb_api_key")._extract_with_regex(
            "复仇者联盟.2.2015.1080p.mkv"
        )
        assert md["episode"] in (None, ""), md

    def test_resolution_not_episode(self):
        """特工迷阵.1080p：分辨率数字不提取为集号。"""
        md = VideoRenamer("your_tmdb_api_key")._extract_with_regex(
            "特工迷阵.1080p.HD中英双字[最新电影www.5266ys.com].mp4"
        )
        assert md["episode"] in (None, ""), md
        assert md["show_name"] == "特工迷阵", md

    def test_e2e_zhetian_matches_tv(self):
        """E2E：遮天.186.4K → 搜「遮天」tv 命中 224839。"""

        def _cand():
            return {
                "id": 224839,
                "name": "遮天",
                "title": "遮天",
                "media_type": "tv",
                "first_air_date": "2023-05-27",
                "popularity": 20.0,
                "original_language": "zh",
                "genre_ids": [16, 10759],
                "vote_average": 7.0,
                "vote_count": 10,
            }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                if str(term).startswith("遮天"):
                    return [_cand()]
                return []

            def get_tv_details(self, tv_id, **k):
                return dict(id=tv_id, name="遮天", overview="x")

        renamer = VideoRenamer("your_tmdb_api_key")
        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        md = renamer.extract_metadata("Q:/番剧/遮天/遮天.186.4K.mkv")
        assert md.get("tmdb_id") == 224839, md
        assert md.get("media_type") == "tv", md
        assert md.get("episode") == "186", md

    def test_e2e_naruto_watermark_matches_tv(self):
        """E2E：火影忍者.115[水印].mkv.iso → 搜「火影忍者」tv 命中 46260。"""

        def _cand():
            return {
                "id": 46260,
                "name": "火影忍者",
                "title": "火影忍者",
                "media_type": "tv",
                "first_air_date": "2002-10-03",
                "popularity": 100.0,
                "original_language": "ja",
                "genre_ids": [16, 10759],
                "vote_average": 8.5,
                "vote_count": 200,
            }

        class StubTMDB:
            def __getattr__(self, name):
                return lambda *a, **k: []

            def search_all_pages(self, method, term, **k):
                if str(term).startswith("火影忍者"):
                    return [_cand()]
                return []

            def get_tv_details(self, tv_id, **k):
                return dict(id=tv_id, name="火影忍者", overview="x")

        renamer = VideoRenamer("your_tmdb_api_key")
        renamer.tmdb_client = StubTMDB()
        renamer._llm_fallback_enabled = False
        md = renamer.extract_metadata(
            "Q:/番剧/火影忍者TV/火影忍者（1-220）/火影忍者.001-050_[252.02GB]/"
            "火影忍者.115[www.haimianxz.com].mkv.iso"
        )
        assert md.get("tmdb_id") == 46260, md
        assert md.get("media_type") == "tv", md
        assert md.get("episode") == "115", md


class TestSegmentPartFallback:
    """分段短篇（剧场版拆段）的搜索兜底

    线上实例：Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv
    - "YOROSHIKU Girl" 是分段名，TMDB 只有总条目 GROTESQQQUE (2026, id=1313587)
    - 整串搜索 0 条 → 依次剥掉 Part 2 + 尾部词，直到 "Grotesqqque" 才完全匹配
    - Part 2 必须留在输出文件名里（见 tests/unit/test_core/test_part_marker.py）
    """

    @staticmethod
    def _fake_search(method, term, **kwargs):
        """只对总片名返回结果，模拟 TMDB 真实行为"""
        if str(term).strip().lower() in ("grotesqqque", "grotesque"):
            return [
                {
                    "id": 1313587,
                    "media_type": "movie",
                    "title": "GROTESQQQUE",
                    "name": "GROTESQQQUE",
                    "original_title": "GROTESQQQUE",
                    "release_date": "2026-10-08",
                    "popularity": 20.0,
                }
            ]
        return []

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_strip_segment_and_part_hits_movie(self, mock_tmdb_client):
        client = MagicMock()
        mock_tmdb_client.return_value = client
        client.search_all_pages.side_effect = self._fake_search
        client.search_web_fallback.return_value = []
        client.get_movie_details.return_value = {
            "id": 1313587,
            "title": "GROTESQQQUE",
            "original_title": "GROTESQQQUE",
            "release_date": "2026-10-08",
            "genres": [],
        }
        client.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        metadata = {
            "show_name": "Grotesqqque YOROSHIKU Girl Part 2",
            "year": 2026,
            "media_type": "movie",
            "original_filename": (
                "Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv"
            ),
        }
        result = renamer._enrich_with_tmdb(metadata)

        assert result.get("tmdb_id") == 1313587, result
        # 确认真的逐级剥到了总片名（不是靠别的路径猜中）
        searched = [
            str(call.args[1]).strip().lower()
            for call in client.search_all_pages.call_args_list
            if len(call.args) > 1
        ]
        assert "grotesqqque" in searched

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_no_part_marker_never_truncates(self, mock_tmdb_client):
        """没有 Part/Pt 标记的 0 结果标题不做尾部截断（防误配）"""
        client = MagicMock()
        mock_tmdb_client.return_value = client
        client.search_all_pages.return_value = []
        client.search_web_fallback.return_value = []

        renamer = VideoRenamer("your_tmdb_api_key")
        renamer._enrich_with_tmdb(
            {
                "show_name": "Blade Runner 2049",
                "year": 2017,
                "media_type": "movie",
                "original_filename": "Blade.Runner.2049.2017.1080p.mkv",
            }
        )
        searched = [
            str(call.args[1]).strip() for call in client.search_all_pages.call_args_list
        ]
        # 全词照搜没问题，但**截断后的** "Blade Runner" 不能出现
        assert "Blade Runner 2049" in searched
        assert "Blade Runner" not in searched, searched


class TestZeroResultCrossLanguage:
    """0 条结果也必须补做跨语言搜索

    回归点：`_search_tmdb_by_type` 里 `if primary_results:` 之外的分支（else）
    在第一次搜索 0 条时只打了一句「第一次搜索结果充足(0个)，跳过跨语言搜索」
    就放弃 —— 措辞反了，还把 0 命中场景唯一能补搜的一枪（language=None，
    TMDB 索引按语言分片）白白丢掉。
    """

    HIT = {
        "id": 67018,
        "media_type": "movie",
        "title": "映像",
        "name": "映像",
        "original_title": "The Image",
        "release_date": "1975-12-20",
        "popularity": 3.0,
    }

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_zero_results_still_runs_cross_language(self, mock_tmdb_client, caplog):
        import logging as _logging

        client = MagicMock()
        mock_tmdb_client.return_value = client
        searched_languages = []

        def fake_search(method, term, **kwargs):
            searched_languages.append(kwargs.get("language"))
            # 只有不限语言（language=None）的搜索能命中
            if kwargs.get("language") is None:
                return [dict(self.HIT)]
            return []

        client.search_all_pages.side_effect = fake_search
        client.search_web_fallback.return_value = []
        client.get_movie_details.return_value = {
            "id": 67018,
            "title": "映像",
            "original_title": "The Image",
            "release_date": "1975-12-20",
            "genres": [],
        }
        client.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        caplog.set_level(_logging.INFO)
        result = renamer._enrich_with_tmdb(
            {
                "show_name": "映像",
                "year": 1975,
                "media_type": "movie",
                "original_filename": r"E:\media\电影\映像.1975.1080p.BluRay.mkv",
            }
        )

        assert (
            None in searched_languages
        ), "0 条结果后必须补做 language=None 的跨语言搜索"
        assert result.get("tmdb_id") == 67018, result
        # 日志措辞不能再出现「充足(0个)」这种反向描述
        assert "充足" not in caplog.text
        assert "补做跨语言搜索" in caplog.text

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_zero_results_and_empty_cross_language_falls_through(
        self, mock_tmdb_client, caplog
    ):
        """跨语言搜索也 0 条时正常回落备选策略，不抛异常"""
        import logging as _logging

        client = MagicMock()
        mock_tmdb_client.return_value = client
        client.search_all_pages.return_value = []
        client.search_web_fallback.return_value = []

        renamer = VideoRenamer("your_tmdb_api_key")
        caplog.set_level(_logging.INFO)
        result = renamer._enrich_with_tmdb(
            {
                "show_name": "完全不存在的片子",
                "year": 2026,
                "media_type": "movie",
                "original_filename": "完全不存在的片子.2026.1080p.mkv",
            }
        )
        assert not result.get("tmdb_id")
        assert "跨语言搜索同样无结果" in caplog.text

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_fuzzy_cross_language_hits_do_not_block_fallbacks(
        self, mock_tmdb_client, caplog
    ):
        """跨语言搜索只返回子串噪音时不得当候选，否则备选策略（截断/分段剥离/
        父目录/LLM）全部被跳过，精确条目反而识别不到"""
        import logging as _logging

        client = MagicMock()
        mock_tmdb_client.return_value = client
        searched = []

        def fake_search(method, term, **kwargs):
            searched.append(str(term))
            if kwargs.get("language") is None:
                # 只有子串噪音，没有任何完全匹配
                return [
                    {
                        "id": 999001,
                        "media_type": "movie",
                        "title": "Grotesqqque 前传",
                        "name": "Grotesqqque 前传",
                        "release_date": "2024-01-01",
                        "popularity": 50.0,
                    }
                ]
            # 备选策略（截断后的干净片名）才命中
            if str(term).strip().lower() == "grotesqqque":
                return [dict(TestSegmentPartFallback._fake_search("m", term)[0])]
            return []

        client.search_all_pages.side_effect = fake_search
        client.search_web_fallback.return_value = []
        client.get_movie_details.return_value = {
            "id": 1313587,
            "title": "GROTESQQQUE",
            "original_title": "GROTESQQQUE",
            "release_date": "2026-10-08",
            "genres": [],
        }
        client.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        caplog.set_level(_logging.INFO)
        result = renamer._enrich_with_tmdb(
            {
                "show_name": "Grotesqqque YOROSHIKU Girl Part 2",
                "year": 2026,
                "media_type": "movie",
                "original_filename": (
                    "Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv"
                ),
            }
        )

        assert "跨语言搜索无完全匹配" in caplog.text
        assert result.get("tmdb_id") == 1313587, result


class TestTvPartMarkerProtection:
    """TV 文件（日番 cour/Part N）不得参与「Part 剥离重搜」

    日番常把分割期写成 "Part N"（进击的巨人 The Final Season Part 1/2/3、
    呪術廻戦 渋谷事変 等），TMDB 常把同一 IP 拆成多个独立 TV 条目——
    剥掉 Part N 去搜「基底条目」会链到错误的兄弟条目（Season 对照全错）。
    断言方式：策略1.7 有独立日志「分段/Part 剥离变体搜索」，出现即代表触发，
    精确且不依赖其他策略（cleaned_name/父目录兜底也会搜裸剧名）的搜索行为。
    """

    # ---------- 工具 ----------
    @staticmethod
    def _make_client(searched_out):
        client = MagicMock()

        def fake_search(method, term, **kwargs):
            searched_out.append(str(term).strip().lower())
            return []

        client.search_all_pages.side_effect = fake_search
        client.search_web_fallback.return_value = []
        return client

    # ---------- 正向：movie 仍然正常剥离 ----------
    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_movie_still_strips(self, mock_tmdb_client, caplog):
        import logging as _logging

        searched = []

        def fake_search(method, term, **kwargs):
            searched.append(str(term).strip().lower())
            if str(term).strip().lower() == "grotesqqque":
                return [
                    {
                        "id": 1313587,
                        "media_type": "movie",
                        "title": "GROTESQQQUE",
                        "name": "GROTESQQQUE",
                        "release_date": "2026-10-08",
                        "popularity": 20.0,
                    }
                ]
            return []

        client = MagicMock()
        mock_tmdb_client.return_value = client
        client.search_all_pages.side_effect = fake_search
        client.search_web_fallback.return_value = []
        client.get_movie_details.return_value = {
            "id": 1313587,
            "title": "GROTESQQQUE",
            "original_title": "GROTESQQQUE",
            "release_date": "2026-10-08",
            "genres": [],
        }
        client.get_external_ids.return_value = {}

        renamer = VideoRenamer("your_tmdb_api_key")
        caplog.set_level(_logging.INFO)
        result = renamer._enrich_with_tmdb(
            {
                "show_name": "Grotesqqque YOROSHIKU Girl Part 2",
                "year": 2026,
                "media_type": "movie",
                "original_filename": (
                    "Grotesqqque.YOROSHIKU.Girl.Part.2.2026.NF.WEB-DL.x264.AAC.mkv"
                ),
            }
        )
        assert result.get("tmdb_id") == 1313587, result
        assert "分段/Part 剥离变体找到完全匹配" in caplog.text

    # ---------- 反向：tv 不剥离 ----------
    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_tv_type_not_stripped(self, mock_tmdb_client, caplog):
        import logging as _logging

        client = self._make_client(searched_out := [])
        mock_tmdb_client.return_value = client
        renamer = VideoRenamer("your_tmdb_api_key")
        caplog.set_level(_logging.INFO)
        result = renamer._enrich_with_tmdb(
            {
                "show_name": "进击的巨人 The Final Season Part 2",
                "year": 2022,
                "media_type": "tv",
                "season": 2,
                "episode": 10,
                "original_filename": (
                    "进击的巨人.The.Final.Season.Part.2.S02E10.2022.1080p.mkv"
                ),
            }
        )
        assert not result.get("tmdb_id")
        assert "分段/Part 剥离变体搜索" not in caplog.text

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_tv_hint_without_episode_not_stripped(self, mock_tmdb_client, caplog):
        """即使没有 season/episode，media_type=tv 的也不得剥离"""
        import logging as _logging

        client = self._make_client(searched_out := [])
        mock_tmdb_client.return_value = client
        renamer = VideoRenamer("your_tmdb_api_key")
        caplog.set_level(_logging.INFO)
        renamer._enrich_with_tmdb(
            {
                "show_name": "葬送的芙莉莲 Part 2",
                "media_type": "tv",
                "original_filename": "葬送的芙莉莲.Part.2.2024.1080p.mkv",
            }
        )
        assert "分段/Part 剥离变体搜索" not in caplog.text

    @patch("video_organizer.core.renamer.renamer.TMDBClient")
    def test_unknown_type_with_episode_not_stripped(self, mock_tmdb_client, caplog):
        """类型未知但带集号证据的文件也不剥离（防文件名保留 Part N 的伪装）"""
        import logging as _logging

        client = self._make_client(searched_out := [])
        mock_tmdb_client.return_value = client
        renamer = VideoRenamer("your_tmdb_api_key")
        caplog.set_level(_logging.INFO)
        renamer._enrich_with_tmdb(
            {
                "show_name": "咒术回战 涩谷事变 Part 2",
                "media_type": "unknown",
                "season": 2,
                "episode": 10,
                "original_filename": "咒术回战.涩谷事变.Part.2.S02E10.2023.1080p.mkv",
            }
        )
        assert "分段/Part 剥离变体搜索" not in caplog.text
