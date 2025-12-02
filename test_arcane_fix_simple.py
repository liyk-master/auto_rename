#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：验证"英雄联盟双城之战"被正确分类为电视剧
"""

import sys
import os
import logging
from unittest.mock import Mock

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.video_organizer.core.renamer import VideoRenamer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_arcane_categorization():
    """测试"英雄联盟双城之战"被正确分类为电视剧"""
    logger.info("开始测试'英雄联盟双城之战'分类...")
    
    # 创建VideoRenamer实例，使用测试API密钥
    renamer = VideoRenamer(tmdb_api_key="test_api_key")
    
    # 模拟"英雄联盟双城之战"的元数据，包含正确的media_type='tv'
    test_metadata = {
        'media_type': 'tv',
        'show_name': '英雄联盟双城之战',
        'year': '2021',
        'season': 1,
        'episode': 1,
        'genres': ['Animation', 'Action', 'Adventure'],
        'original_language': 'en',
        'origin_country': ['US'],
        'original_show_name': 'Arcane'
    }
    
    # 测试1: 检查media_type是否被正确设置为'tv'
    assert test_metadata.get('media_type') == 'tv', f"media_type应该是'tv'，但实际是{test_metadata.get('media_type')}"
    logger.info("✓ 测试1通过：media_type被正确设置为'tv'")
    
    # 测试2: 检查分类是否正确
    category = renamer._determine_category(test_metadata)
    logger.info(f"确定的分类: {category}")
    
    # 预期分类应该是 'TV Shows/欧美剧' 或 'TV Shows/未分类'，关键是它不应该是 'Other/动画电影'
    assert category != 'Other/动画电影', f"分类不应该是'Other/动画电影'，但实际是{category}"
    assert 'TV Shows' in category, f"分类应该包含'TV Shows'，但实际是{category}"
    logger.info("✓ 测试2通过：分类正确，包含'TV Shows'，不是'Other/动画电影'")
    
    # 测试3: 测试如果没有media_type，会发生什么
    no_media_type_metadata = test_metadata.copy()
    del no_media_type_metadata['media_type']
    category_no_media = renamer._determine_category(no_media_type_metadata)
    logger.info(f"没有media_type时的分类: {category_no_media}")
    assert category_no_media == 'Other/动画电影', f"没有media_type时应该分类为'Other/动画电影'，但实际是{category_no_media}"
    logger.info("✓ 测试3通过：没有media_type时被分类为'Other/动画电影'，验证了问题的根源")
    
    logger.info("🎉 所有测试通过！'英雄联盟双城之战'被正确分类为电视剧")
    return True

if __name__ == "__main__":
    success = test_arcane_categorization()
    sys.exit(0 if success else 1)