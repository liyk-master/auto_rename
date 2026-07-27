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