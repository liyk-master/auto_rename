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
                {"show_name": "Game Of Thrones", "season": "01", "episode": "01"}
            ),
            (
                "Breaking Bad - s05e16 - Felina.mp4",
                {"show_name": "Breaking Bad", "season": "05", "episode": "16"}
            ),
            (
                "The Office Season 3 Episode 22.avi",
                {"show_name": "The Office", "season": "3", "episode": "22"}
            ),
        ]

        for filename, expected in test_cases:
            result = renamer._extract_with_regex(filename)
            for key in expected:
                assert result.get(key) == expected[key]
    
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
            {"id": 123, "name": "Game of Thrones", "media_type": "tv", "first_air_date": "2011-04-17"}
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
        metadata = {"show_name": "Game of Thrones", "season": "1", "episode": "1", "media_type": "tv"}
        result = renamer._enrich_with_tmdb(metadata)

        assert result["show_name"] == "Game of Thrones"
        assert result["year"] == "2011"

        # 在 patch 生效后创建 renamer，确保 TMDBClient 被 mock
        renamer = VideoRenamer("your_tmdb_api_key")

        # Test metadata enrichment
        metadata = {"show_name": "Game of Thrones", "season": "1", "episode": "1", "media_type": "tv"}
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
                "id": 1001, "name": "少年派", "media_type": "tv",
                "first_air_date": "2019-05-31", "popularity": 50,
            },
            {
                "id": 1002, "title": "少年派的奇幻漂流", "media_type": "movie",
                "release_date": "2012-11-22", "popularity": 60,
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
                "id": 2001, "name": "少年派", "media_type": "tv",
                "first_air_date": "2016-03-01", "popularity": 50,
            },
            {
                "id": 2002, "title": "少年派的奇幻漂流", "media_type": "movie",
                "release_date": "2012-11-22", "popularity": 60,
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
                "id": 3001, "name": "同名", "media_type": "tv",
                "first_air_date": "2019-01-01", "popularity": 50,
            },
            {
                "id": 3002, "title": "同名", "media_type": "movie",
                "release_date": "2019-05-05", "popularity": 60,
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

    @patch(
        "video_organizer.core.renamer.renamer.VideoRenamer._enrich_with_tmdb"
    )
    def test_extract_metadata_refuses_movie_override(self, mock_enrich):
        """extract_metadata 覆盖保护：TMDB movie 结果不能覆盖强 TV 信号"""
        mock_enrich.return_value = {
            "media_type": "movie",
            "tmdb_id": 1646282,
            "show_name": "Adventure Time: Fun with Finn and Jake",
        }

        renamer = VideoRenamer("your_tmdb_api_key")
        result = renamer.extract_metadata(
            Path("E:/alipan备份/TV_欧美亚/探险活宝 (2010)/Season 10/"
                 "Adventure.Time.With.Finn.And.Jake.S10E13.mkv")
        )

        assert result.get("media_type") == "tv"
        assert result.get("season") == "10"
        assert result.get("episode") == "13"

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
