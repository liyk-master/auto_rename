#!/usr/bin/env python3
"""
测试修改后的搜索策略
"""

import logging
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_search_strategy():
    """
    测试修改后的搜索策略
    """
    # 创建VideoRenamer实例
    # 注意：需要提供有效的TMDB API密钥
    renamer = VideoRenamer(tmdb_api_key="your_tmdb_api_key_here")
    
    # 测试用例1：中文剧名"星期三"
    test_metadata1 = {
        "show_name": "星期三",
        "season": 1,
        "episode": 1,
        "media_type": "tv"
    }
    
    logger.info("\n=== 测试用例1：中文剧名\"星期三\" ===")
    try:
        result1 = renamer._enrich_with_tmdb(test_metadata1)
        logger.info(f"搜索结果：{result1.get('show_name', 'N/A')} (ID: {result1.get('tmdb_id', 'N/A')})")
        logger.info(f"年份：{result1.get('year', 'N/A')}")
        logger.info(f"媒体类型：{result1.get('media_type', 'N/A')}")
    except Exception as e:
        logger.error(f"测试用例1失败：{e}")
    
    # 测试用例2：中文剧名"怪奇物语"
    test_metadata2 = {
        "show_name": "怪奇物语",
        "season": 1,
        "episode": 1,
        "media_type": "tv"
    }
    
    logger.info("\n=== 测试用例2：中文剧名\"怪奇物语\" ===")
    try:
        result2 = renamer._enrich_with_tmdb(test_metadata2)
        logger.info(f"搜索结果：{result2.get('show_name', 'N/A')} (ID: {result2.get('tmdb_id', 'N/A')})")
        logger.info(f"年份：{result2.get('year', 'N/A')}")
        logger.info(f"媒体类型：{result2.get('media_type', 'N/A')}")
    except Exception as e:
        logger.error(f"测试用例2失败：{e}")
    
    # 测试用例3：英文剧名"Wednesday"
    test_metadata3 = {
        "show_name": "Wednesday",
        "season": 1,
        "episode": 1,
        "media_type": "tv"
    }
    
    logger.info("\n=== 测试用例3：英文剧名\"Wednesday\" ===")
    try:
        result3 = renamer._enrich_with_tmdb(test_metadata3)
        logger.info(f"搜索结果：{result3.get('show_name', 'N/A')} (ID: {result3.get('tmdb_id', 'N/A')})")
        logger.info(f"年份：{result3.get('year', 'N/A')}")
        logger.info(f"媒体类型：{result3.get('media_type', 'N/A')}")
    except Exception as e:
        logger.error(f"测试用例3失败：{e}")


if __name__ == "__main__":
    test_search_strategy()
