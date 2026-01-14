import os
import unittest
from unittest.mock import Mock, patch
from unittest import mock

# 添加项目根目录到Python路径
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.video_organizer.core.tmdb_client import TMDBClient


class TestTMBDClient(unittest.TestCase):

    def setUp(self):
        """
        设置测试环境
        """
        # 测试API密钥
        self.api_key = "test_api_key"
        self.language = "zh-CN"
        self.region = "CN"

        # 创建测试TMDB客户端
        self.client = TMDBClient(
            api_key=self.api_key,
            language=self.language,
            region=self.region,
            retry_count=2,
            timeout=5,
        )

    @patch("src.video_organizer.core.tmdb_client.requests.Session")
    def test_constructor(self, mock_session_class):
        """
        测试构造函数
        """
        # 验证会话创建
        mock_session = mock_session_class.return_value

        # 验证构造函数参数设置
        self.assertEqual(self.client.api_key, self.api_key)
        self.assertEqual(self.client.language, self.language)
        self.assertEqual(self.client.region, self.region)
        self.assertEqual(self.client.retry_count, 2)
        self.assertEqual(self.client.timeout, 5)

        # 验证会话头设置
        headers = mock_session.headers
        self.assertIn("accept", headers)
        self.assertIn("Authorization", headers)
        self.assertEqual(headers["Authorization"], f"Bearer {self.api_key}")

    @patch("src.video_organizer.core.tmdb_client.requests.Session")
    def test_request_with_retry_success(self, mock_session_class):
        """
        测试请求重试机制 - 成功情况
        """
        # 设置模拟会话
        mock_session = mock_session_class.return_value
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status_code": 200,
            "status_message": "Success",
        }
        mock_session.get.return_value = mock_response

        # 执行请求
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"query": "Test Movie"}
        response = self.client._request_with_retry(url, params)

        # 验证结果
        self.assertEqual(response, {"status_code": 200, "status_message": "Success"})
        mock_session.get.assert_called_once_with(url, params=params, timeout=5)

    @patch("src.video_organizer.core.tmdb_client.requests.Session")
    @patch("src.video_organizer.core.tmdb_client.time.sleep")
    def test_request_with_retry_failure_then_success(
        self, mock_sleep, mock_session_class
    ):
        """
        测试请求重试机制 - 失败后成功
        """
        # 设置模拟会话
        mock_session = mock_session_class.return_value

        # 第一次请求失败，第二次成功
        mock_response_fail = Mock()
        mock_response_fail.status_code = 500
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "status_code": 200,
            "status_message": "Success",
        }

        mock_session.get.side_effect = [mock_response_fail, mock_response_success]

        # 执行请求
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"query": "Test Movie"}
        response = self.client._request_with_retry(url, params)

        # 验证结果
        self.assertEqual(response, {"status_code": 200, "status_message": "Success"})
        self.assertEqual(mock_session.get.call_count, 2)
        mock_sleep.assert_called_once()  # 验证有重试间隔

    @patch("src.video_organizer.core.tmdb_client.requests.Session")
    @patch("src.video_organizer.core.tmdb_client.time.sleep")
    def test_request_with_retry_max_failures(self, mock_sleep, mock_session_class):
        """
        测试请求重试机制 - 达到最大重试次数
        """
        # 设置模拟会话
        mock_session = mock_session_class.return_value
        mock_response = Mock()
        mock_response.status_code = 500
        mock_session.get.return_value = mock_response

        # 执行请求，应该抛出异常
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"query": "Test Movie"}

        with self.assertRaises(Exception):
            self.client._request_with_retry(url, params)

        # 验证重试次数
        self.assertEqual(mock_session.get.call_count, 3)  # 1次初始请求 + 2次重试

    @patch("src.video_organizer.core.tmdb_client.TMDBClient._request_with_retry")
    def test_search_video_show_tv(self, mock_request):
        """
        测试搜索电视剧
        """
        # 设置模拟响应
        mock_request.return_value = {
            "results": [
                {
                    "media_type": "tv",
                    "id": 123,
                    "name": "Test Show",
                    "first_air_date": "2020-01-01",
                    "vote_average": 8.5,
                }
            ]
        }

        # 执行搜索
        result = self.client.search_video_show("Test Show S01E01")

        # 验证结果
        self.assertIsNotNone(result)
        self.assertEqual(result["media_type"], "tv")
        self.assertEqual(result["name"], "Test Show")

        # 验证请求参数
        mock_request.assert_called_once()

    @patch("src.video_organizer.core.tmdb_client.TMDBClient._request_with_retry")
    def test_search_video_show_movie(self, mock_request):
        """
        测试搜索电影
        """
        # 设置模拟响应
        mock_request.return_value = {
            "results": [
                {
                    "media_type": "movie",
                    "id": 456,
                    "title": "Test Movie",
                    "release_date": "2020-01-01",
                    "vote_average": 8.5,
                }
            ]
        }

        # 执行搜索
        result = self.client.search_video_show("Test Movie 2020")

        # 验证结果
        self.assertIsNotNone(result)
        self.assertEqual(result["media_type"], "movie")
        self.assertEqual(result["title"], "Test Movie")

    @patch("src.video_organizer.core.tmdb_client.TMDBClient._request_with_retry")
    def test_get_tv_details(self, mock_request):
        """
        测试获取电视剧详情
        """
        # 设置模拟响应
        mock_request.return_value = {
            "id": 123,
            "name": "Test Show",
            "first_air_date": "2020-01-01",
            "episode_run_time": [45],
            "seasons": [
                {"season_number": 1, "episode_count": 10},
                {"season_number": 2, "episode_count": 12},
            ],
        }

        # 执行请求
        result = self.client.get_tv_details(123)

        # 验证结果
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 123)
        self.assertEqual(result["name"], "Test Show")

        # 验证请求URL
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "https://api.themoviedb.org/3/tv/123")

    @patch("src.video_organizer.core.tmdb_client.TMDBClient._request_with_retry")
    def test_get_movie_details(self, mock_request):
        """
        测试获取电影详情
        """
        # 设置模拟响应
        mock_request.return_value = {
            "id": 456,
            "title": "Test Movie",
            "release_date": "2020-01-01",
            "runtime": 120,
            "genres": [{"name": "Action"}, {"name": "Drama"}],
        }

        # 执行请求
        result = self.client.get_movie_details(456)

        # 验证结果
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 456)
        self.assertEqual(result["title"], "Test Movie")

        # 验证请求URL
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "https://api.themoviedb.org/3/movie/456")


if __name__ == "__main__":
    unittest.main()
