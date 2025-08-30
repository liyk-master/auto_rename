"""
Tests for the VideoRenamer class.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from video_organizer.core.renamer import VideoRenamer


class TestVideoRenamer:
    """Test cases for VideoRenamer."""
    
    @pytest.fixture
    def renamer(self):
        """Create a VideoRenamer instance for testing."""
        return VideoRenamer("f321777b05714595e09a5de9db77fdec")
    
    def test_extract_with_regex(self, renamer):
        """Test metadata extraction using regex patterns."""
        test_cases = [
            (
                "Game.of.Thrones.S01E01.1080p.BluRay.x264-GROUP.mkv",
                {"show_name": "Game Of Thrones", "season": "1", "episode": "1"}
            ),
            (
                "Breaking Bad - s05e16 - Felina.mp4",
                {"show_name": "Breaking Bad", "season": "5", "episode": "16"}
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
    
    @patch("video_organizer.core.renamer.TMDBClient")
    def test_enrich_with_tmdb(self, mock_tmdb_client, renamer):
        """Test metadata enrichment with TMDB data."""
        # Mock TMDB client responses
        mock_client_instance = Mock()
        mock_tmdb_client.return_value = mock_client_instance
        
        mock_client_instance.search_tv_show.return_value = [{"id": 123, "name": "Game of Thrones"}]
        mock_client_instance.get_tv_show_details.return_value = {
            "name": "Game of Thrones",
            "first_air_date": "2011-04-17"
        }
        mock_client_instance.get_season_details.return_value = {
            "episodes": [
                {"name": "Winter Is Coming"},
                {"name": "The Kingsroad"}
            ]
        }
        
        # Test metadata enrichment
        metadata = {"show_name": "Game of Thrones", "season": "1", "episode": "1"}
        result = renamer._enrich_with_tmdb(metadata)
        
        assert result["show_name"] == "Game of Thrones"
        assert result["year"] == "2011"
        assert result["episode_name"] == "Winter Is Coming"
        assert result["tmdb_id"] == 123