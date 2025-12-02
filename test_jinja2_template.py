#!/usr/bin/env python3
"""
测试脚本：验证Jinja2模板功能是否正常工作
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

def test_jinja2_template():
    """测试Jinja2模板功能是否正常工作"""
    print("=== 测试Jinja2模板功能 ===")
    
    # 创建模拟的TMDB客户端
    mock_tmdb_client = Mock()
    
    # 设置模拟返回值
    mock_tmdb_client.search_tv.return_value = {
        'results': [
            {
                'id': 1455575,
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
            'id': 1455575,
            'name': '怪奇物语',
            'original_name': 'Stranger Things',
            'original_language': 'en',
            'origin_country': ['US'],
            'first_air_date': '2016-07-15',
            'media_type': 'tv'
        }
    ]
    
    mock_tmdb_client.get_tv_details.return_value = {
        'id': 1455575,
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
    renamer.tmdb_client = mock_tmdb_client
    
    # 设置用户提供的Jinja2模板
    user_template = "{{title}}{% if year %} ({{year}}){% endif %}{% if tmdbid %} {tmdbid={{tmdbid}}}{% endif %}/Season {{(season|string).zfill(2)}}/{{title}} {{season_episode}} {{videoFormat}}{%if webSource %}.{{webSource}}{% endif %}{%if edition %}.{{edition}}{% endif %}{% if videoCodec %}.{{videoCodec}}{% endif %}{% if audioCodec %}.{{audioCodec}}{% endif %}{% if customization %}.{{customization}}{% endif %}{% if releaseGroup %}-{{ releaseGroup }}{% endif %}{{fileExt}}"
    
    renamer.naming_rules = {
        "tv_show": user_template,
        "movie": user_template,
        "anime": user_template,
        "simple": user_template
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
        if "怪奇物语 (2016) {tmdbid=1455575}" in str(new_path):
            print("✅ 测试通过：Jinja2模板已正确处理年份和tmdbid")
            return True
        else:
            print("❌ 测试失败：Jinja2模板未正确处理年份和tmdbid")
            return False
    except Exception as e:
        print(f"❌ 测试失败：生成路径时出错 - {e}")
        return False

if __name__ == "__main__":
    success = test_jinja2_template()
    sys.exit(0 if success else 1)
