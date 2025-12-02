#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：验证"英雄联盟双城之战"被正确分类到动画子分类
"""

import sys
import os
import logging

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.video_organizer.core.renamer import VideoRenamer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_arcane_subcategory():
    """测试"英雄联盟双城之战"被正确分类到动画子分类"""
    logger.info("开始测试'英雄联盟双城之战'子分类...")
    
    # 创建VideoRenamer实例，使用测试API密钥
    renamer = VideoRenamer(tmdb_api_key="test_api_key")
    
    # 测试1: 美国动画电视剧（英雄联盟：双城之战）
    logger.info("\n测试1: 美国动画电视剧（英雄联盟：双城之战）")
    arcane_metadata = {
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
    
    arcane_category = renamer._determine_category(arcane_metadata)
    logger.info(f"分类结果: {arcane_category}")
    assert arcane_category == 'TV Shows/欧美动漫', f"分类应该是'TV Shows/欧美动漫'，但实际是{arcane_category}"
    logger.info("✓ 测试1通过：美国动画电视剧被正确分类到'TV Shows/欧美动漫'")
    
    # 测试2: 日本动画电视剧
    logger.info("\n测试2: 日本动画电视剧")
    anime_metadata = {
        'media_type': 'tv',
        'show_name': '进击的巨人',
        'year': '2013',
        'season': 1,
        'episode': 1,
        'genres': ['Animation', 'Action', 'Drama'],
        'original_language': 'ja',
        'origin_country': ['JP'],
        'original_show_name': '進撃の巨人'
    }
    
    anime_category = renamer._determine_category(anime_metadata)
    logger.info(f"分类结果: {anime_category}")
    assert anime_category == 'TV Shows/日番', f"分类应该是'TV Shows/日番'，但实际是{anime_category}"
    logger.info("✓ 测试2通过：日本动画电视剧被正确分类到'TV Shows/日番'")
    
    # 测试3: 中国动画电视剧
    logger.info("\n测试3: 中国动画电视剧")
    chinese_anime_metadata = {
        'media_type': 'tv',
        'show_name': '斗罗大陆',
        'year': '2018',
        'season': 1,
        'episode': 1,
        'genres': ['Animation', 'Action', 'Fantasy'],
        'original_language': 'zh',
        'origin_country': ['CN'],
        'original_show_name': '斗罗大陆'
    }
    
    chinese_anime_category = renamer._determine_category(chinese_anime_metadata)
    logger.info(f"分类结果: {chinese_anime_category}")
    assert chinese_anime_category == 'TV Shows/国漫', f"分类应该是'TV Shows/国漫'，但实际是{chinese_anime_category}"
    logger.info("✓ 测试3通过：中国动画电视剧被正确分类到'TV Shows/国漫'")
    
    # 测试4: 其他国家动画电视剧
    logger.info("\n测试4: 其他国家动画电视剧")
    other_anime_metadata = {
        'media_type': 'tv',
        'show_name': 'Miraculous: Tales of Ladybug & Cat Noir',
        'year': '2015',
        'season': 1,
        'episode': 1,
        'genres': ['Animation', 'Adventure', 'Comedy'],
        'original_language': 'fr',
        'origin_country': ['FR', 'KR'],
        'original_show_name': 'Miraculous: Les Aventures de Ladybug et Chat Noir'
    }
    
    other_anime_category = renamer._determine_category(other_anime_metadata)
    logger.info(f"分类结果: {other_anime_category}")
    assert other_anime_category == 'TV Shows/其他动漫', f"分类应该是'TV Shows/其他动漫'，但实际是{other_anime_category}"
    logger.info("✓ 测试4通过：其他国家动画电视剧被正确分类到'TV Shows/其他动漫'")
    
    logger.info("\n🎉 所有测试通过！动画电视剧子分类功能正常工作")
    return True

if __name__ == "__main__":
    success = test_arcane_subcategory()
    sys.exit(0 if success else 1)