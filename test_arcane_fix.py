#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：验证"英雄联盟双城之战"被正确分类为电视剧
"""

import sys
import os
import logging
from unittest.mock import Mock, patch

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.video_organizer.core.renamer import VideoRenamer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_arcane_categorization():
    """测试"英雄联盟双城之战"被正确分类为电视剧"""
    logger.info("开始测试'英雄联盟双城之战'分类...")
    
    # 创建VideoRenamer实例
    renamer = VideoRenamer()
    
    # 模拟TMDB API返回的结果，模拟"英雄联盟双城之战"的搜索结果
    mock_tmdb_results = [
        {
            'media_type': 'tv',
            'name': '英雄联盟：双城之战',
            'first_air_date': '2021-11-06',
            'popularity': 100.0,
            'id': 94605
        }
    ]
    
    # 模拟电视剧详细信息
    mock_tv_details = {
        'name': '英雄联盟：双城之战',
        'original_name': 'Arcane',
        'first_air_date': '2021-11-06',
        'genres': [{'name': 'Animation'}, {'name': 'Action'}, {'name': 'Adventure'}],
        'original_language': 'en',
        'origin_country': ['US'],
        'vote_average': 9.0,
        'number_of_seasons': 1,
        'number_of_episodes': 9
    }
    
    # 测试的元数据
    test_metadata = {
        'show_name': '英雄联盟双城之战',
        'year': '2021',
        'season': 1,
        'episode': 1,
        'quality_tags': '1080p WEB-DL'
    }
    
    # 使用mock替换TMDB相关方法
    with patch.object(renamer, '_search_with_language', return_value=mock_tmdb_results):
        with patch.object(renamer.tmdb_client, 'get_tv_details', return_value=mock_tv_details):
            with patch.object(renamer.tmdb_client, 'get_tv_credits', return_value={'cast': [], 'crew': []}):
                with patch.object(renamer.tmdb_client, 'get_tv_episode_details', return_value={'name': 'Welcome to the Playground'}):
                    # 调用TMDB丰富元数据
                    enriched_metadata = renamer._enrich_with_tmdb(test_metadata)
                    logger.info(f"丰富后的元数据: {enriched_metadata}")
                    
                    # 测试1: 检查media_type是否被正确设置为'tv'
                    assert enriched_metadata.get('media_type') == 'tv', f"media_type应该是'tv'，但实际是{enriched_metadata.get('media_type')}"
                    logger.info("✓ 测试1通过：media_type被正确设置为'tv'")
                    
                    # 测试2: 检查分类是否正确
                    category = renamer._determine_category(enriched_metadata)
                    logger.info(f"确定的分类: {category}")
                    
                    # 预期分类应该是 'TV Shows/未分类'（因为是英语动画，不在当前的细分规则中）
                    # 关键是它不应该是 'Other/动画电影'
                    assert category != 'Other/动画电影', f"分类不应该是'Other/动画电影'，但实际是{category}"
                    assert 'TV Shows' in category, f"分类应该包含'TV Shows'，但实际是{category}"
                    logger.info("✓ 测试2通过：分类正确，包含'TV Shows'，不是'Other/动画电影'")
                    
                    # 测试3: 检查genres是否被正确获取
                    assert 'Animation' in enriched_metadata.get('genres', []), f"genres应该包含'Animation'，但实际是{enriched_metadata.get('genres')}"
                    logger.info("✓ 测试3通过：genres被正确获取")
                    
                    logger.info("🎉 所有测试通过！'英雄联盟双城之战'被正确分类为电视剧")
                    return True
    
    logger.error("测试失败")
    return False

if __name__ == "__main__":
    success = test_arcane_categorization()
    sys.exit(0 if success else 1)