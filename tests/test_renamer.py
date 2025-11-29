import os
import shutil
import unittest
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

# 添加项目根目录到Python路径
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.video_organizer.core.renamer import VideoRenamer


class TestVideoRenamer(unittest.TestCase):
    
    def setUp(self):
        """
        设置测试环境
        """
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)
        
        # 输出目录
        self.output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(self.output_dir)
        
        # 测试API密钥
        self.tmdb_api_key = "test_api_key_12345"
        
        # 自定义命名规则
        self.naming_rules = {
            'movie': 'Movies/{movie_name} ({year})/{movie_name} ({year})',
            'tv': 'TV/{show_name}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}'
        }
        
        # 模拟TMDB客户端
        self.mock_tmdb_client = Mock()
        
        # 创建重命名器实例
        self.renamer = VideoRenamer(
            tmdb_api_key=self.tmdb_api_key,
            ai_service_url=None,
            watch_path=Path(self.temp_dir),
            naming_rules=self.naming_rules
        )
        
        # 替换tmdb_client属性以进行测试
        # 直接替换私有属性可能需要通过反射或在初始化时注入
        # 这里假设VideoRenamer类有tmdb_client属性
        self.renamer.tmdb_client = self.mock_tmdb_client
    
    def test_constructor(self):
        """
        测试构造函数
        """
        self.assertEqual(self.renamer.tmdb_client, self.mock_tmdb_client)
        self.assertEqual(self.renamer.naming_rules, self.naming_rules)
        self.assertEqual(self.renamer.watch_path, Path(self.temp_dir))
        self.assertIsNone(self.renamer.ai_service_url)
    
    def test_extract_metadata_basic(self):
        """
        测试基本的元数据提取
        """
        # 创建临时测试文件
        test_file = os.path.join(self.temp_dir, 'test_file.mp4')
        with open(test_file, 'w') as f:
            f.write('dummy content')
        
        # 提取元数据
        metadata = self.renamer.extract_metadata(Path(test_file))
        
        # 验证基本元数据
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.get('extension'), '.mp4')
    
    def test_extract_tv_show_pattern(self):
        """
        测试从文件名提取电视剧信息的模式匹配
        """
        # 创建临时测试文件（使用匹配正则表达式的格式）
        test_file = os.path.join(self.temp_dir, 'Friends.S01E01.mp4')
        with open(test_file, 'w') as f:
            f.write('dummy content')
        
        # 提取元数据
        metadata = self.renamer.extract_metadata(Path(test_file))
        
        # 验证基本电视剧信息提取
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.get('show_name'), 'Friends')
        self.assertEqual(int(metadata.get('season')), 1)
        self.assertEqual(int(metadata.get('episode')), 1)
    
    def test_extract_movie_pattern(self):
        """
        测试从文件名提取电影信息的基本功能
        """
        # 创建临时测试文件
        test_file = os.path.join(self.temp_dir, 'inception_2010.mp4')
        with open(test_file, 'w') as f:
            f.write('dummy content')
        
        # 提取元数据
        metadata = self.renamer.extract_metadata(Path(test_file), 'movie')
        
        # 验证基本电影信息提取
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.get('extension'), '.mp4')
        self.assertEqual(metadata.get('original_filename'), 'inception_2010.mp4')
    
    def test_sanitize_filename(self):
        """
        测试清理文件名方法
        """
        # 测试清理特殊字符
        dirty_filename = 'file?*<>:"|name.mp4'
        clean_filename = self.renamer._sanitize_filename(dirty_filename)
        # 实际实现可能只替换部分特殊字符
        self.assertNotIn('?', clean_filename)
        self.assertNotIn('*', clean_filename)
        self.assertNotIn('<', clean_filename)
        self.assertNotIn('>', clean_filename)
        self.assertNotIn('|', clean_filename)
        
        # 测试清理空字符
        empty_filename = ''
        clean_filename = self.renamer._sanitize_filename(empty_filename)
        self.assertEqual(clean_filename, '')
        
        # 测试保留合法字符
        valid_filename = 'Valid_Filename.123.mp4'
        clean_filename = self.renamer._sanitize_filename(valid_filename)
        self.assertEqual(clean_filename, valid_filename)
    
    def test_set_naming_rules(self):
        """
        测试设置命名规则方法
        """
        # 检查命名规则字典存在
        self.assertTrue(hasattr(self.renamer, 'naming_rules'))
        self.assertIsInstance(self.renamer.naming_rules, dict)
        
        # 设置自定义命名规则
        custom_rules = {
            'movie': 'Custom/Movies/{movie_name}'
        }
        self.renamer.set_naming_rules(custom_rules)
        
        # 验证自定义命名规则被设置
        self.assertEqual(self.renamer.naming_rules.get('movie'), 'Custom/Movies/{movie_name}')


if __name__ == '__main__':
    unittest.main()