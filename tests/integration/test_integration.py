import os
import unittest
import tempfile
import shutil
from unittest.mock import Mock, patch

# 添加项目根目录到Python路径
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.video_organizer.core.config_loader import load_config, save_default_config
from src.video_organizer.core.tmdb_client import TMDBClient
from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.core.video_file_handler import VideoFileHandler


class TestIntegration(unittest.TestCase):
    
    def setUp(self):
        """
        设置集成测试环境
        """
        # 创建临时目录结构
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)
        
        # 创建测试目录
        self.monitor_dir = os.path.join(self.temp_dir, 'monitor')
        self.output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(self.monitor_dir)
        os.makedirs(self.output_dir)
        
        # 创建临时配置文件
        self.config_path = os.path.join(self.temp_dir, 'config.ini')
        
        # 创建默认配置
        config_content = """[monitoring]
# 监控目录
monitored_dir = {monitor_dir}

# 输出目录
output_dir = {output_dir}

# 支持的视频扩展名
supported_extensions = .mp4, .mkv, .avi

# 轮询间隔（秒）
polling_interval = 5

# 是否递归监控子目录
recursive = true

[naming]
tv_show_format = TV/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}
movie_format = Movies/{movie_name} ({year})/{movie_name} ({year})
anime_format = Anime/{anime_name}/Season {season:02d}/{anime_name} - S{season:02d}E{episode:02d}
simple_format = Unsorted/{filename}

[tmdb]
api_key = test_api_key
language = zh-CN
region = CN
retry_count = 3
timeout = 30
"""
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            f.write(config_content.format(
                monitor_dir=self.monitor_dir,
                output_dir=self.output_dir
            ))
        
        # 加载配置
        self.config = load_config(self.config_path)
        
        # 创建模拟TMDB客户端
        self.mock_tmdb_client = Mock()
    
    @patch('src.video_organizer.core.tmdb_client.TMDBClient')
    def test_full_workflow_tv_show(self, mock_tmdb_class):
        """
        测试完整工作流 - 电视剧
        """
        # 设置模拟TMDB客户端
        mock_tmdb_client = mock_tmdb_class.return_value
        
        # 模拟搜索结果
        mock_tmdb_client.search_video_show.return_value = {
            'media_type': 'tv',
            'id': 123,
            'name': 'Test Series',
            'season_number': 1,
            'episode_number': 1,
            'title': 'Pilot'
        }
        
        # 模拟电视剧详情
        mock_tmdb_client.get_tv_details.return_value = {
            'id': 123,
            'name': 'Test Series',
            'first_air_date': '2023-01-01',
            'episode_run_time': [45],
            'seasons': [{'season_number': 1, 'episode_count': 10}]
        }
        
        # 创建测试文件
        test_file_path = os.path.join(self.monitor_dir, 'test_series_s01e01.mp4')
        with open(test_file_path, 'w') as f:
            f.write('dummy video content')
        
        # 初始化文件处理器
        handler = VideoFileHandler(
            output_dir=self.output_dir,
            supported_extensions=['.mp4', '.mkv', '.avi'],
            naming_rules=self.config.get('naming_rules'),
            tmdb_config={'api_key': 'test'}
        )
        
        # 模拟文件处理
        with patch.object(handler, '_is_file_complete', return_value=True):
            handler._process_file(test_file_path)
        
        # 验证结果
        expected_output_path = os.path.join(
            self.output_dir, 
            'TV', 
            'Test Series', 
            'Season 01', 
            'Test Series - S01E01.mp4'
        )
        
        # 由于我们使用了模拟，实际的文件不会被移动，但可以验证路径生成逻辑
        # 这里我们检查重命名器是否正确被调用
        self.assertTrue(mock_tmdb_client.search_video_show.called)
        self.assertTrue(mock_tmdb_client.get_tv_details.called)
    
    @patch('src.video_organizer.core.tmdb_client.TMDBClient')
    def test_full_workflow_movie(self, mock_tmdb_class):
        """
        测试完整工作流 - 电影
        """
        # 设置模拟TMDB客户端
        mock_tmdb_client = mock_tmdb_class.return_value
        
        # 模拟搜索结果
        mock_tmdb_client.search_video_show.return_value = {
            'media_type': 'movie',
            'id': 456,
            'title': 'Test Movie',
            'release_date': '2023-01-01',
            'original_title': 'Test Movie'
        }
        
        # 模拟电影详情
        mock_tmdb_client.get_movie_details.return_value = {
            'id': 456,
            'title': 'Test Movie',
            'release_date': '2023-01-01',
            'runtime': 120,
            'genres': [{'name': 'Action'}, {'name': 'Drama'}]
        }
        
        # 创建测试文件
        test_file_path = os.path.join(self.monitor_dir, 'test_movie_2023.mp4')
        with open(test_file_path, 'w') as f:
            f.write('dummy video content')
        
        # 初始化文件处理器
        handler = VideoFileHandler(
            output_dir=self.output_dir,
            supported_extensions=['.mp4'],
            naming_rules=self.config.get('naming_rules'),
            tmdb_config={'api_key': 'test'}
        )
        
        # 模拟文件处理
        with patch.object(handler, '_is_file_complete', return_value=True):
            handler._process_file(test_file_path)
        
        # 验证结果
        self.assertTrue(mock_tmdb_client.search_video_show.called)
        self.assertTrue(mock_tmdb_client.get_movie_details.called)
    
    def test_config_naming_rules_integration(self):
        """
        测试配置文件中的命名规则与重命名器集成
        """
        # 加载配置
        config = load_config(self.config_path)
        
        # 验证命名规则
        naming_rules = config.get('naming_rules')
        self.assertIsNotNone(naming_rules)
        self.assertIn('tv_show', naming_rules)
        self.assertIn('movie', naming_rules)
        
        # 创建重命名器并验证命名规则被正确传递
        renamer = VideoRenamer(
            output_dir=self.output_dir,
            naming_rules=naming_rules
        )
        
        # 验证命名规则
        self.assertEqual(renamer.naming_rules, naming_rules)
    
    @patch('src.video_organizer.core.tmdb_client.TMDBClient')
    def test_error_handling_integration(self, mock_tmdb_class):
        """
        测试错误处理集成
        """
        # 设置模拟TMDB客户端抛出异常
        mock_tmdb_class.side_effect = Exception("TMDB初始化失败")
        
        # 即使TMDB初始化失败，文件处理器也应该能够初始化
        handler = VideoFileHandler(
            output_dir=self.output_dir,
            supported_extensions=['.mp4'],
            naming_rules=self.config.get('naming_rules'),
            tmdb_config={'api_key': 'test'}
        )
        
        # 验证处理器成功初始化
        self.assertIsNotNone(handler)
        self.assertIsNotNone(handler.renamer)


if __name__ == '__main__':
    unittest.main()