#!/usr/bin/env python3
"""
测试脚本：验证tmdbid模板问题是否已修复
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

def test_tmdbid_template():
    """测试tmdbid模板问题是否已修复"""
    print("=== 测试tmdbid模板问题是否已修复 ===")
    
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
    
    # 创建VideoRenamer实例，使用配置中的模板
    renamer = VideoRenamer(tmdb_api_key="test_key")
    renamer.tmdb_client = mock_tmdb_client
    
    # 设置自定义命名规则，包含 {tmdbid=tmdbid} 格式
    renamer.naming_rules = {
        "tv_show": "{show_name} ({year}) {tmdbid=tmdbid}/Season {season:02d}/{show_name} {season_episode} {quality_tags}",
        "movie": "{movie_name} ({year}) {tmdbid=tmdbid}",
        "anime": "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d}",
        "simple": "{title}"
    }
    
    # 测试文件路径
    test_file = Path("怪奇物语 S01E01 - 第1集 (1).mp4")
    
    try:
        # 提取元数据
        metadata = renamer.extract_metadata(test_file)
        print(f"提取的元数据: {metadata}")
        
        # 生成新路径
        new_path = renamer.generate_new_path(metadata, original_path=test_file)
        print(f"生成的新路径: {new_path}")
        
        # 验证结果
        if "tmdbid=" in str(new_path):
            print("✅ 测试通过：tmdbid模板已正确处理")
            return True
        else:
            print("❌ 测试失败：tmdbid模板未正确处理")
            return False
    except Exception as e:
        print(f"❌ 测试失败：生成路径时出错 - {e}")
        return False

if __name__ == "__main__":
    success = test_tmdbid_template()
    sys.exit(0 if success else 1)
