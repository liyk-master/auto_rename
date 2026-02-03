"""
Emos 客户端测试
"""

import pytest
from unittest.mock import Mock, patch
from src.video_organizer.core.emos_client import EmosClient


class TestEmosClient:
    """Emos 客户端测试类"""

    def test_init_default(self):
        """测试默认初始化"""
        client = EmosClient()
        assert client.api_url == "https://emos.prlo.de/api/recognize"
        assert client.timeout == 30
        assert client.enabled is True

    def test_init_custom(self):
        """测试自定义初始化"""
        client = EmosClient(
            api_url="https://custom.api.com/recognize",
            timeout=60,
            enabled=False
        )
        assert client.api_url == "https://custom.api.com/recognize"
        assert client.timeout == 60
        assert client.enabled is False

    def test_init_disabled(self):
        """测试禁用状态"""
        client = EmosClient(enabled=False)
        assert client.enabled is False

    @patch('src.video_organizer.core.emos_client.requests.get')
    def test_recognize_success(self, mock_get):
        """测试成功的识别请求"""
        # 模拟响应
        mock_response = Mock()
        mock_response.json.return_value = {
            "meta_info": {
                "isfile": True,
                "org_string": "唐朝诡事录 S01E01",
                "title": "唐朝诡事录 S01E01.mp4",
                "subtitle": None,
                "type": "电视剧",
                "name": "唐朝诡事录",
                "cn_name": "唐朝诡事录",
                "en_name": None,
                "year": None,
                "total_season": 1,
                "begin_season": 1,
                "end_season": None,
                "total_episode": 1,
                "begin_episode": 1,
                "end_episode": None,
                "season_episode": "S01 E01",
                "episode_list": [1]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = EmosClient()
        result = client.recognize("唐朝诡事录 S01E01.mp4")

        assert result is not None
        assert "meta_info" in result
        assert result["meta_info"]["name"] == "唐朝诡事录"
        mock_get.assert_called_once()

    @patch('src.video_organizer.core.emos_client.requests.get')
    def test_recognize_disabled(self, mock_get):
        """测试禁用状态下不发送请求"""
        client = EmosClient(enabled=False)
        result = client.recognize("test.mp4")

        assert result is None
        mock_get.assert_not_called()

    @patch('src.video_organizer.core.emos_client.requests.get')
    def test_recognize_timeout(self, mock_get):
        """测试请求超时"""
        from requests.exceptions import Timeout
        mock_get.side_effect = Timeout()

        client = EmosClient()
        result = client.recognize("test.mp4")

        assert result is None

    @patch('src.video_organizer.core.emos_client.requests.get')
    def test_recognize_request_exception(self, mock_get):
        """测试请求异常"""
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException("Network error")

        client = EmosClient()
        result = client.recognize("test.mp4")

        assert result is None

    def test_parse_media_info_tv_show(self):
        """测试解析电视剧信息"""
        client = EmosClient()
        response_data = {
            "meta_info": {
                "type": "电视剧",
                "name": "唐朝诡事录",
                "cn_name": "唐朝诡事录",
                "en_name": "Strange Tales of Tang Dynasty",
                "year": 2022,
                "begin_season": 1,
                "begin_episode": 1,
                "total_season": 1,
                "total_episode": 36,
                "season_episode": "S01 E01",
                "episode_list": [1],
                "subtitle": "长安红茶",
                "resource_pix": "1080p",
                "resource_team": "FRDS",
                "video_encode": "H.264",
                "audio_encode": "AAC"
            }
        }

        result = client.parse_media_info(response_data)

        assert result["title"] == "唐朝诡事录"
        assert result["original_title"] == "Strange Tales of Tang Dynasty"
        assert result["year"] == 2022
        assert result["season"] == 1
        assert result["episode"] == 1
        assert result["type"] == "tv_show"
        assert result["episode_title"] == "长安红茶"
        assert result["resource_pix"] == "1080p"
        assert result["resource_team"] == "FRDS"

    def test_parse_media_info_movie(self):
        """测试解析电影信息"""
        client = EmosClient()
        response_data = {
            "meta_info": {
                "type": "电影",
                "name": "流浪地球2",
                "cn_name": "流浪地球2",
                "en_name": "The Wandering Earth II",
                "year": 2023,
                "begin_season": None,
                "begin_episode": None,
                "season_episode": None
            }
        }

        result = client.parse_media_info(response_data)

        assert result["title"] == "流浪地球2"
        assert result["original_title"] == "The Wandering Earth II"
        assert result["year"] == 2023
        assert result["season"] is None
        assert result["episode"] is None
        assert result["type"] == "movie"

    def test_parse_media_info_anime(self):
        """测试解析动漫信息"""
        client = EmosClient()
        response_data = {
            "meta_info": {
                "type": "动漫",
                "name": "葬送的芙莉莲",
                "cn_name": "葬送的芙莉莲",
                "begin_season": 1,
                "begin_episode": 1
            }
        }

        result = client.parse_media_info(response_data)

        assert result["title"] == "葬送的芙莉莲"
        assert result["type"] == "anime"
        assert result["season"] == 1
        assert result["episode"] == 1

    def test_parse_media_info_empty(self):
        """测试解析空数据"""
        client = EmosClient()
        result = client.parse_media_info({})
        assert result == {}

        result = client.parse_media_info({"media_info": None})
        assert result == {}

    def test_parse_media_type_tv_show(self):
        """测试解析电视剧类型"""
        client = EmosClient()
        assert client._parse_media_type("电视剧") == "tv_show"
        assert client._parse_media_type("剧集") == "tv_show"
        assert client._parse_media_type("TV剧") == "tv_show"

    def test_parse_media_type_movie(self):
        """测试解析电影类型"""
        client = EmosClient()
        assert client._parse_media_type("电影") == "movie"
        assert client._parse_media_type("Movie") == "movie"

    def test_parse_media_type_anime(self):
        """测试解析动漫类型"""
        client = EmosClient()
        assert client._parse_media_type("动漫") == "anime"
        assert client._parse_media_type("动画") == "anime"
        assert client._parse_media_type("Anime") == "anime"

    def test_parse_media_type_unknown(self):
        """测试解析未知类型"""
        client = EmosClient()
        assert client._parse_media_type("") == "unknown"
        assert client._parse_media_type("未知") == "unknown"
        assert client._parse_media_type("other") == "unknown"

    def test_is_confident_valid(self):
        """测试可信度判断 - 有效数据"""
        client = EmosClient()
        response_data = {
            "meta_info": {
                "name": "唐朝诡事录",
                "cn_name": "唐朝诡事录"
            }
        }
        assert client.is_confident(response_data) is True

    def test_is_confident_invalid(self):
        """测试可信度判断 - 无效数据"""
        client = EmosClient()
        assert client.is_confident({}) is False
        assert client.is_confident({"meta_info": {}}) is False
        assert client.is_confident({"meta_info": {"name": ""}}) is False

    def test_is_confident_no_meta_info(self):
        """测试可信度判断 - 无 meta_info"""
        client = EmosClient()
        assert client.is_confident({"other": "data"}) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])