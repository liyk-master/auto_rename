#!/usr/bin/env python3
"""
测试脚本：验证TMDB搜索只执行一次
"""

import logging
import sys
from pathlib import Path
from unittest.mock import Mock, patch

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(message)s')

def test_tmdb_search_once():
    """测试TMDB搜索只执行一次"""
    print("=== 测试TMDB搜索只执行一次 ===")
    
    # 创建模拟的TMDB客户端
    mock_tmdb_client = Mock()
    
    # 设置模拟返回值
    mock_tmdb_client.search_tv.return_value = {
        'results': [
            {
                'id': 12345,
                'name': '怪奇物语',
                'original_name': 'Stranger Things',
                'original_language': 'en',
                'origin_country': ['US'],
                'first_air_date': '2016-07-15',
                'media_type': 'tv'
            }
        ]
    }
    
    # 也需要设置 search_video_show 的返回值，因为代码中会调用它
    mock_tmdb_client.search_video_show.return_value = [
        {
            'id': 12345,
            'name': '怪奇物语',
            'original_name': 'Stranger Things',
            'original_language': 'en',
            'origin_country': ['US'],
            'first_air_date': '2016-07-15',
            'media_type': 'tv'
        }
    ]
    
    mock_tmdb_client.get_tv_details.return_value = {
        'id': 12345,
        'name': '怪奇物语',
        'original_name': 'Stranger Things',
        'original_language': 'en',
        'origin_country': ['US'],
        'first_air_date': '2016-07-15',
        'genres': [{'name': '科幻'}, {'name': '恐怖'}],
        'number_of_seasons': 4,
        'number_of_episodes': 34,
        'networks': [{'name': 'Netflix'}]
    }
    
    mock_tmdb_client.get_tv_credits.return_value = {'cast': [], 'crew': []}
    mock_tmdb_client.get_tv_episode_details.return_value = {
        'name': 'Chapter One: The Vanishing of Will Byers'
    }
    
    # 创建VideoRenamer实例
    renamer = VideoRenamer(tmdb_api_key="test_key")
    
    # 替换tmdb_client为模拟对象
    renamer.tmdb_client = mock_tmdb_client
    
    # 测试文件路径
    test_file = Path("怪奇物语 S01E01 - 第1集 (1).mp4")
    
    # 提取元数据
    metadata = renamer.extract_metadata(test_file)
    
    # 检查所有搜索方法被调用的次数
    search_tv_call_count = mock_tmdb_client.search_tv.call_count
    search_video_show_call_count = mock_tmdb_client.search_video_show.call_count
    total_search_count = search_tv_call_count + search_video_show_call_count
    
    print(f"TMDB search_tv 调用次数: {search_tv_call_count}")
    print(f"TMDB search_video_show 调用次数: {search_video_show_call_count}")
    print(f"TMDB 总搜索调用次数: {total_search_count}")
    
    # 验证结果
    if total_search_count == 1:
        print("✅ 测试通过：TMDB搜索只执行了一次")
        return True
    else:
        print(f"❌ 测试失败：TMDB搜索执行了 {total_search_count} 次，预期为1次")
        return False

if __name__ == "__main__":
    success = test_tmdb_search_once()
    sys.exit(0 if success else 1)
