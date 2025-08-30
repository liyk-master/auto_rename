from hmac import new
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from video_organizer.core.tmdb_client import TMDBClient

class TestTMDBClient:
    """Test cases for TMDBClient."""
    
    @pytest.fixture
    def tmdb_client(self):
        """Create a TMDBClient instance for testing."""
        return TMDBClient("eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJmMzIxNzc3YjA1NzE0NTk1ZTA5YTVkZTlkYjc3ZmRlYyIsIm5iZiI6MTcxNzY3NTA3OS4zNDMwMDAyLCJzdWIiOiI2NjYxYTQ0NzJkZTI5YzdhMjdhNDI5YjIiLCJzY29wZXMiOlsiYXBpX3JlYWQiXSwidmVyc2lvbiI6MX0.cjyI_jYk5TkEqMfz5GZhfLCdET-qGM2wfKjTjboqNoY")
    
    def test_search_video_show(self, tmdb_client):
        """Test search video show."""
        results = tmdb_client.search_video_show("超人")
        # assert len(results) > 0
        # assert results[0]["name"] == "超人"
        # assert results[0]["media_type"] == "tv"
        # assert results[0]["id"] == 1000000