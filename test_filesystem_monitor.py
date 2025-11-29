import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile
import os
from src.video_organizer.core.filesystem_monitor import VideoFileHandler, FileSystemMonitor
from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.core.file_mover import FileMover


class TestVideoFileHandler(unittest.TestCase):
    """测试VideoFileHandler类的process_file方法"""
    
    def setUp(self):
        """设置测试环境"""
        # 创建mock对象
        self.mock_renamer = Mock(spec=VideoRenamer)
        self.mock_file_mover = Mock(spec=FileMover)
        self.supported_extensions = ['.mp4', '.mkv', '.avi']
        
        # 创建VideoFileHandler实例
        self.handler = VideoFileHandler(
            self.mock_renamer,
            self.mock_file_mover,
            self.supported_extensions
        )
    
    def test_process_file_success(self):
        """测试成功处理文件的情况"""
        # 准备测试数据
        test_file = Path("/test/权力的游戏.S01E01.mp4")
        test_metadata = {
            'show_name': '权力的游戏',
            'season': '1',
            'episode': '1',
            'tmdb_id': 1399,
            'media_type': 'tv'
        }
        new_path = Path("/processed/权力的游戏/Season 01/权力的游戏 - S01E01.mp4")
        
        # 设置mock返回值
        self.handler.extract_enhanced_metadata = Mock(return_value=test_metadata)
        self.mock_renamer.generate_new_path.return_value = new_path
        self.mock_file_mover.move_file.return_value = None
        self.handler.generate_emby_metadata = Mock()
        
        # 执行测试
        self.handler.process_file(test_file)
        
        # 验证调用
        self.handler.extract_enhanced_metadata.assert_called_once_with(test_file)
        self.mock_renamer.generate_new_path.assert_called_once_with(test_metadata)
        self.mock_file_mover.move_file.assert_called_once_with(test_file, new_path)
        self.handler.generate_emby_metadata.assert_called_once_with(new_path, test_metadata)
    
    def test_process_file_metadata_extraction_error(self):
        """测试元数据提取失败的情况"""
        test_file = Path("/test/invalid_file.mp4")
        
        # 设置mock抛出异常
        self.handler.extract_enhanced_metadata = Mock(side_effect=Exception("TMDB API error"))
        
        # 执行测试（不应该抛出异常）
        with patch('src.video_organizer.core.filesystem_monitor.logger') as mock_logger:
            self.handler.process_file(test_file)
            
            # 验证错误被记录
            mock_logger.error.assert_called_once()
            
        # 验证其他方法没有被调用
        self.mock_renamer.generate_new_path.assert_not_called()
        self.mock_file_mover.move_file.assert_not_called()
    
    def test_process_file_move_error(self):
        """测试文件移动失败的情况"""
        test_file = Path("/test/test_file.mp4")
        test_metadata = {'show_name': 'Test Show'}
        new_path = Path("/processed/test_path.mp4")
        
        # 设置mock
        self.handler.extract_enhanced_metadata = Mock(return_value=test_metadata)
        self.mock_renamer.generate_new_path.return_value = new_path
        self.mock_file_mover.move_file.side_effect = Exception("File move error")
        
        # 执行测试
        with patch('src.video_organizer.core.filesystem_monitor.logger') as mock_logger:
            self.handler.process_file(test_file)
            
            # 验证错误被记录
            mock_logger.error.assert_called_once()
    
    @patch('src.video_organizer.core.filesystem_monitor.VideoFileHandler.extract_enhanced_metadata')
    def test_extract_enhanced_metadata_called(self, mock_extract):
        """测试extract_enhanced_metadata方法被正确调用"""
        test_file = Path("/test/sample.mp4")
        test_metadata = {'show_name': 'Sample Show'}
        
        # 设置mock
        mock_extract.return_value = test_metadata
        self.mock_renamer.generate_new_path.return_value = Path("/new/path.mp4")
        
        # 执行测试
        self.handler.process_file(test_file)
        
        # 验证调用
        mock_extract.assert_called_once_with(test_file)


class TestFileSystemMonitor(unittest.TestCase):
    """测试FileSystemMonitor类"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        self.watch_path = Path(self.temp_dir) / "watch"
        self.processed_path = Path(self.temp_dir) / "processed"
        self.watch_path.mkdir()
        self.processed_path.mkdir()
        
        # 使用测试用的API密钥
        self.test_api_key = "test_api_key_12345"
    
    def tearDown(self):
        """清理测试环境"""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    @patch('src.video_organizer.core.filesystem_monitor.VideoRenamer')
    @patch('src.video_organizer.core.filesystem_monitor.FileMover')
    def test_monitor_initialization(self, mock_file_mover, mock_renamer):
        """测试监控器初始化"""
        monitor = FileSystemMonitor(
            watch_path=self.watch_path,
            processed_path=self.processed_path,
            tmdb_api_key=self.test_api_key
        )
        
        # 验证组件被正确初始化
        self.assertEqual(monitor.watch_path, self.watch_path)
        self.assertEqual(monitor.processed_path, self.processed_path)
        self.assertEqual(monitor.tmdb_api_key, self.test_api_key)
        
        # 验证默认扩展名
        expected_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.strm']
        self.assertEqual(monitor.supported_extensions, expected_extensions)
    
    def test_process_file_integration(self):
        """集成测试：测试完整的文件处理流程"""
        # 创建测试文件
        test_file = self.watch_path / "权力的游戏.S01E01.mp4"
        test_file.touch()
        
        # 创建mock的监控器组件
        with patch('src.video_organizer.core.filesystem_monitor.VideoRenamer') as mock_renamer_class, \
             patch('src.video_organizer.core.filesystem_monitor.FileMover') as mock_file_mover_class:
            
            # 设置mock实例
            mock_renamer = Mock()
            mock_file_mover = Mock()
            mock_renamer_class.return_value = mock_renamer
            mock_file_mover_class.return_value = mock_file_mover
            
            # 创建监控器
            monitor = FileSystemMonitor(
                watch_path=self.watch_path,
                processed_path=self.processed_path,
                tmdb_api_key=self.test_api_key
            )
            
            # 模拟处理文件
            test_metadata = {
                'show_name': '权力的游戏',
                'season': '1',
                'episode': '1'
            }
            new_path = self.processed_path / "权力的游戏" / "Season 01" / "权力的游戏 - S01E01.mp4"
            
            # 设置mock返回值
            with patch.object(monitor.event_handler, 'extract_enhanced_metadata', return_value=test_metadata), \
                 patch.object(monitor.event_handler, 'generate_emby_metadata'):
                
                mock_renamer.generate_new_path.return_value = new_path
                
                # 执行处理
                monitor.event_handler.process_file(test_file)
                
                # 验证调用
                mock_renamer.generate_new_path.assert_called_once_with(test_metadata)
                mock_file_mover.move_file.assert_called_once_with(test_file, new_path)


if __name__ == "__main__":
    # 运行特定测试
    # print("=== 测试VideoFileHandler.process_file方法 ===")
    
    # # 创建测试套件
    # suite = unittest.TestSuite()
    
    # # 添加process_file相关的测试
    # suite.addTest(TestVideoFileHandler('test_process_file_success'))
    # suite.addTest(TestVideoFileHandler('test_process_file_metadata_extraction_error'))
    # suite.addTest(TestVideoFileHandler('test_process_file_move_error'))
    # suite.addTest(TestVideoFileHandler('test_extract_enhanced_metadata_called'))
    
    # # 添加集成测试
    # suite.addTest(TestFileSystemMonitor('test_monitor_initialization'))
    # suite.addTest(TestFileSystemMonitor('test_process_file_integration'))
    
    # # 运行测试
    # runner = unittest.TextTestRunner(verbosity=2)
    # result = runner.run(suite)
    
    # # 输出结果
    # if result.wasSuccessful():
    #     print("\n✅ 所有测试通过！")
    # else:
    #     print(f"\n❌ 测试失败: {len(result.failures)} 个失败, {len(result.errors)} 个错误")
        
    # # 演示如何手动测试process_file方法
    # print("\n=== 手动测试示例 ===")
    # print("可以使用以下代码手动测试process_file方法:")
    # 创建mock对象
    from unittest.mock import Mock
    from pathlib import Path
    from src.video_organizer.core.filesystem_monitor import VideoFileHandler

    # 设置mock组件
    mock_renamer = Mock()
    mock_file_mover = Mock()
    supported_extensions = ['.mp4', '.mkv', '.avi']

    # 创建handler
    handler = VideoFileHandler(mock_renamer, mock_file_mover, supported_extensions)

    # 模拟方法
    handler.extract_enhanced_metadata = Mock(return_value={'show_name': '测试剧集'})
    handler.generate_emby_metadata = Mock()
    mock_renamer.generate_new_path.return_value = Path('./new/path.mp4')

    # 测试
    test_file = Path('./test/权力的游戏.S01E01.mp4')
    handler.process_file(test_file)
    print('测试完成！')
#     print("""
# # 创建mock对象
# from unittest.mock import Mock
# from pathlib import Path
# from src.video_organizer.core.filesystem_monitor import VideoFileHandler

# # 设置mock组件
# mock_renamer = Mock()
# mock_file_mover = Mock()
# supported_extensions = ['.mp4', '.mkv', '.avi']

# # 创建handler
# handler = VideoFileHandler(mock_renamer, mock_file_mover, supported_extensions)

# # 模拟方法
# handler.extract_enhanced_metadata = Mock(return_value={'show_name': '测试剧集'})
# handler.generate_emby_metadata = Mock()
# mock_renamer.generate_new_path.return_value = Path('/new/path.mp4')

# # 测试
# test_file = Path('/test/权力的游戏.S01E01.mp4')
# handler.process_file(test_file)
# print('测试完成！')
# """)